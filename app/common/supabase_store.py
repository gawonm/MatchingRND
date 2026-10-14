"""PostgreSQL repository. Credentials never appear in errors or logs."""
from contextlib import contextmanager
import hashlib
import json
import math
import os

from app.common.embedding import MODEL, PROFILE, DIMENSION
from app.common.paths import PROJECT_ROOT


def connect():
    from dotenv import load_dotenv
    import psycopg
    load_dotenv(PROJECT_ROOT / ".env")
    fields = {"host": "SUPABASE_DB_HOST", "user": "SUPABASE_DB_USER", "password": "SUPABASE_DB_PASSWORD"}
    dsn = os.getenv("SUPABASE_DB_DSN")
    if not dsn:
        missing = [key for key in fields.values() if not os.getenv(key)]
        if missing:
            raise RuntimeError("DB 접속 정보가 필요합니다: " + ", ".join(missing))
    try:
        kwargs = {name: os.getenv(key) for name, key in fields.items()} if not dsn else {}
        if not dsn:
            kwargs.update(port=os.getenv("SUPABASE_DB_PORT", "5432"), dbname=os.getenv("SUPABASE_DB_NAME", "postgres"))
        return psycopg.connect(dsn or "", **kwargs, sslmode="require", connect_timeout=10,
                              prepare_threshold=None, options="-c statement_timeout=120000")
    except Exception:
        raise RuntimeError("Supabase DB 접속 실패. Connect 화면의 Session pooler 정보와 DB 비밀번호를 확인하세요.") from None


def vector_literal(vector):
    values = [float(value) for value in vector]
    if len(values) != DIMENSION or not all(math.isfinite(v) for v in values):
        raise ValueError("임베딩은 유한한 1024차원 벡터여야 합니다.")
    if not any(values):
        raise ValueError("영벡터는 코사인 검색에 사용할 수 없습니다.")
    return "[" + ",".join(map(str, values)) + "]"


def corpus_fingerprint(documents, chunks, payload):
    body = {"model": MODEL, "profile": PROFILE, "documents": documents, "chunks": chunks, "payload": payload}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class SupabaseRepository:
    def __init__(self, connection_factory=connect):
        self.connection_factory = connection_factory

    @contextmanager
    def connection(self):
        with self.connection_factory() as conn:
            from psycopg import sql
            row = conn.execute("select n.nspname from pg_extension e join pg_namespace n on n.oid=e.extnamespace where e.extname='vector'").fetchone()
            conn.execute(sql.SQL("set search_path to rag, {}, pg_catalog").format(sql.Identifier(row[0] if row else 'extensions')))
            yield conn

    def apply_schema(self):
        sql = (PROJECT_ROOT / "supabase/migrations/202610140001_rag.sql").read_text(encoding="utf-8")
        with self.connection() as conn:
            from psycopg import sql as psql
            row = conn.execute("select n.nspname from pg_extension e join pg_namespace n on n.oid=e.extnamespace where e.extname='vector'").fetchone()
            namespace = psql.Identifier(row[0] if row else 'extensions').as_string(conn)
            sql = sql.replace('extensions.vector', namespace + '.vector').replace('rag, extensions, pg_catalog', 'rag, ' + namespace + ', pg_catalog')
            conn.execute(sql, prepare=False)

    def corpus(self, corpus_id):
        with self.connection() as conn:
            row = conn.execute("select embedding_model, embedding_profile, fingerprint, payload from rag.corpora where corpus_id=%s", (corpus_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"Supabase에 {corpus_id} 자료가 없습니다. 먼저 ingest 명령을 실행하세요.")
        if row[0] != MODEL or row[1] != PROFILE:
            raise ValueError("기존 임베딩 프로필이 다릅니다. 통일 모델로 다시 적재하세요.")
        return {"fingerprint": row[2], "payload": row[3]}

    def snapshot(self, corpus_id):
        # One repeatable-read transaction prevents mixing corpus generations.
        with self.connection() as conn:
            conn.commit()
            conn.execute("set transaction isolation level repeatable read read only")
            header = conn.execute("select embedding_model, embedding_profile, fingerprint, payload from rag.corpora where corpus_id=%s", (corpus_id,)).fetchone()
            if header is None or header[:2] != (MODEL, PROFILE):
                raise RuntimeError(f"{corpus_id}: 통일 모델로 적재한 자료가 없습니다.")
            from psycopg.rows import dict_row
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute("select * from rag.documents where corpus_id=%s order by document_id", (corpus_id,))
                documents = cursor.fetchall()
                cursor.execute("select * from rag.chunks where corpus_id=%s order by chunk_id", (corpus_id,))
                chunks = cursor.fetchall()
        if not chunks:
            raise RuntimeError(f"{corpus_id}: 검색할 청크가 없습니다.")
        return documents, chunks, header[3]

    def search(self, corpus_id, vector, k=30, filters=None, document_filters=None):
        from psycopg.types.json import Jsonb
        from psycopg.rows import dict_row
        if not 1 <= k <= 1000:
            raise ValueError("검색 개수는 1~1000이어야 합니다.")
        with self.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute("select * from rag.match_chunks(%s::vector,%s,%s,%s,%s)",
                               (vector_literal(vector), corpus_id, k, Jsonb(filters or {}), Jsonb(document_filters or {})))
                return cursor.fetchall()

    def replace(self, corpus_id, documents, chunks, vectors, payload, fingerprint):
        """Atomically publish a complete snapshot; other corpora remain untouched."""
        from psycopg.types.json import Jsonb
        if not documents or not chunks or len(chunks) != len(vectors):
            raise ValueError("문서·청크·벡터 개수를 확인하세요.")
        if len({d['document_id'] for d in documents}) != len(documents) or len({c['chunk_id'] for c in chunks}) != len(chunks):
            raise ValueError("문서 또는 청크 ID가 중복되었습니다.")
        doc_ids = {d['document_id'] for d in documents}
        if any(c['document_id'] not in doc_ids for c in chunks):
            raise ValueError("청크의 부모 문서가 없습니다.")
        literals = [vector_literal(v) for v in vectors]
        with self.connection() as conn:
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", ("rag:" + corpus_id,))
            conn.execute("insert into rag.corpora values (%s,%s,%s,%s,%s,now()) on conflict(corpus_id) do update set embedding_model=excluded.embedding_model,embedding_profile=excluded.embedding_profile,fingerprint=excluded.fingerprint,payload=excluded.payload,updated_at=now()", (corpus_id, MODEL, PROFILE, fingerprint, Jsonb(payload)))
            # This is an explicit corpus replacement, not a database-wide reset.
            conn.execute("delete from rag.documents where corpus_id=%s", (corpus_id,))
            conn.execute("delete from rag.announcements where corpus_id=%s", (corpus_id,))
            # Batch network round trips for domain rows as well as vectors.
            with conn.pipeline(), conn.cursor() as cursor:
                cursor.executemany("insert into rag.documents(corpus_id,document_id,source,title,year,institution,source_path,category_major,category_middle,category_minor,full_text,metadata,payload) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [
                    (corpus_id, d['document_id'], d['source'], d['title'], d.get('year'), d.get('institution'), d.get('source_path'), d.get('category_major'), d.get('category_middle'), d.get('category_minor'), d['full_text'], Jsonb(d.get('metadata', {})), Jsonb(d.get('payload', {}))) for d in documents])
                cursor.executemany("insert into rag.chunks(corpus_id,chunk_id,document_id,section,content,page_start,page_end,metadata,payload) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)", [
                    (corpus_id, c['chunk_id'], c['document_id'], c.get('section'), c['content'], c.get('page_start'), c.get('page_end'), Jsonb(c.get('metadata', {})), Jsonb(c.get('payload', {}))) for c in chunks])
                cursor.executemany("insert into rag.embeddings values(%s,%s,%s::vector)", [(corpus_id, c['chunk_id'], v) for c,v in zip(chunks,literals)])
                for notice_id, notice in payload.get('notices', {}).items():
                    cursor.execute("insert into rag.announcements values(%s,%s,%s,%s,%s,%s,%s)", (corpus_id, notice_id, notice['title'], notice.get('year'), notice.get('institution'), notice.get('url'), Jsonb(notice)))
                for task in payload.get('tasks', []):
                    cursor.execute("insert into rag.rfp_tasks values(%s,%s,%s,%s,%s,%s)", (corpus_id,task['task_id'],task['document_id'],task.get('task_number'),task['title'],Jsonb(task)))
                    notices = {n for c in chunks if c['metadata'].get('task_id') == task['task_id'] for n in c['metadata'].get('notice_ids', [])}
                    for notice_id in notices:
                        cursor.execute("insert into rag.task_announcements values(%s,%s,%s)", (corpus_id,task['task_id'],notice_id))
                for d in documents:
                    for patent in d.get('patents', []):
                        cursor.execute("insert into rag.patents values(%s,%s,%s,%s,%s,%s,%s) on conflict do nothing", (corpus_id,d['document_id'],patent['number'],d['title'],patent.get('owner'),patent.get('classification'),Jsonb(patent)))
                    if corpus_id == 'ntis':
                        m = d['metadata']
                        cursor.execute("insert into rag.ntis_projects values(%s,%s,%s,%s,%s,%s)", (corpus_id,d['document_id'],m['project_id'],d['title'],d.get('institution'),Jsonb(m)))
