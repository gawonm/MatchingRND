"""Build database snapshots from existing parsers, without building Chroma."""
import csv
import hashlib
import json
import io
from pathlib import Path

from app.common.embedding import get_embedder
from app.common.paths import PROJECT_ROOT, RAW_DIR, RFP_NOTICE_PATH


def pack(value):
    """JSON-safe lossless serialization of parsed LangChain documents."""
    if hasattr(value, 'page_content') and hasattr(value, 'metadata'):
        return {'__document__': True, 'text': value.page_content, 'metadata': pack(value.metadata)}
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    if isinstance(value, dict):
        return {str(k): pack(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [pack(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def unpack(value):
    if isinstance(value, dict):
        if value.get('__document__') is True:
            from langchain_core.documents import Document
            return Document(page_content=value['text'], metadata=value['metadata'])
        return {k:unpack(v) for k,v in value.items()}
    if isinstance(value, list):
        return [unpack(v) for v in value]
    return value


def retrieval_metadata(metadata):
    """Remove extraction-only table copies; preserve query evidence and locations."""
    result = {k:v for k,v in metadata.items() if k not in {'cells', 'headers', 'rows', 'row_bboxes'}}
    if 'sources' in result:
        result['sources'] = [retrieval_metadata(source) for source in result['sources']]
    return result


def retrieval_tasks(tasks):
    """Indexing used full tables already; runtime only needs text and source coordinates."""
    result = pack(tasks)
    for task in result:
        if 'title_source' in task:
            source = task['title_source']
            source['metadata'] = retrieval_metadata(source.get('metadata', {}))
        for fragments in task.get('fields', {}).values():
            for fragment in fragments:
                fragment['metadata'] = retrieval_metadata(fragment['metadata'])
    return result


def document_record(document_id, source, title, text, metadata, **kwargs):
    return dict(document_id=document_id, source=source, title=title, full_text=text,
                metadata=pack(metadata), **kwargs)


def technology_snapshot():
    from app.technology_rag.config import load_config
    from app.technology_rag.schemas import TechDocument
    from app.technology_rag.indexing.chunker import load_chunks
    cfg = load_config()
    documents = [TechDocument.model_validate_json(line) for line in cfg.documents_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    records = []
    for d in documents:
        patent = d.patent.model_dump(mode='json')
        numbers = list(dict.fromkeys(str(patent[k]) for k in ('application_number', 'registration_number') if patent.get(k)))
        records.append(document_record(d.doc_id, d.source.value, d.title, d.full_text,
            {'transfer_condition': d.transfer_condition.value, **d.taxonomy.model_dump()},
            institution=d.provider, source_path=d.pdf_path, payload=d.model_dump(mode='json'),
            year=2026 if d.source.value == 'pub' else 2025,
            category_major=d.taxonomy.major, category_middle=d.taxonomy.middle, category_minor=d.taxonomy.minor,
            patents=[{'number': n, 'owner': d.applicant or d.provider, 'classification': ','.join(patent.get('ipc', [])), **patent} for n in numbers]))
    chunks = [dict(chunk_id=c.chunk_id, document_id=c.parent_doc_id, section=c.section_key,
                   content=c.text, page_start=c.page_start, page_end=c.page_end,
                   metadata=c.metadata, payload=c.model_dump(mode='json')) for c in load_chunks(cfg.chunks_path)]
    return records, chunks, {'collection': cfg.collection_name, 'chunking': cfg.chunking.model_dump(), 'tokenizer': cfg.tokenizer.model_dump()}


def pdf_snapshot(module):
    from langchain_core.documents import Document
    embedder = get_embedder()
    tokenizer = embedder.model.tokenizer
    if module == 'rfp':
        from app.rfp_rag.config import load_config
        from app.rfp_rag.parsing.pdf_parser import load_documents, parse_tasks
        from app.rfp_rag.parsing.notices import _load_notices
        from app.rfp_rag.indexing.chunker import build_chunks
        cfg = load_config()
        notices, links, issues = _load_notices(cfg['data_dir'], cfg['pdf_files'], RFP_NOTICE_PATH)
        import pandas as pd
        for _, row in pd.read_excel(RFP_NOTICE_PATH, sheet_name='공고목록').fillna('').iterrows():
            uid = str(row['공고 UID']).strip().removesuffix('.0')
            if uid in notices:
                date = pd.to_datetime(row.get('공고일') or row.get('접수시작일'), errors='coerce')
                notices[uid].update(year=int(date.year) if pd.notna(date) else None,
                                    institution=str(row.get('전문기관/관리기관') or row.get('부처') or '') or None,
                                    ministry=str(row.get('부처') or '') or None)
        loaded, review, failed = load_documents(cfg['data_dir'], cfg['OUTPUT'], cfg['pdf_files'], Document)
        tasks, review, excluded = parse_tasks(loaded, cfg['pdf_files'], cfg['data_dir'], review, Document)
        from app.rfp_rag.review import apply_review
        tasks, review_outcomes = apply_review(tasks, review, cfg['data_dir'], Document)
        docs, _ = build_chunks(tasks, links, tokenizer, min(cfg['CHUNK_TOKENS'],embedder.max_seq_length-2), cfg['OVERLAP_TOKENS'], Document)
        packed_tasks = retrieval_tasks(tasks)
        payload = dict(tasks=packed_tasks, notices=notices, dataset={'notices':notices},
                       excluded_files=excluded, matching_issues=issues, review_outcomes=review_outcomes)
    else:
        from app.policy_rag.config import load_config
        from app.policy_rag.parsing.pdf_parser import load_documents, parse_articles
        from app.policy_rag.indexing.chunker import build_chunks
        cfg = load_config()
        loaded, review, failed = load_documents(cfg['data_dir'],cfg['OUTPUT'],cfg['pdf_files'])
        articles, review, excluded = parse_articles(loaded, review, Document)
        docs, _ = build_chunks(articles, tokenizer, min(cfg['CHUNK_TOKENS'],embedder.max_seq_length-2), cfg['OVERLAP_TOKENS'], Document)
        payload = dict(articles=pack(articles), excluded_sections=excluded)
    if not docs:
        raise ValueError(f'{module}: 파싱된 청크가 없습니다.')
    payload.update(review_list=[{k:v for k,v in row.items() if k != 'blocks'} for row in review], failed_files=failed,
                   **{k:cfg[k] for k in ('KEYWORD_K','VECTOR_K','TOP_K','RRF_K','CONTEXT_TOKENS')})
    grouped = {}
    chunks = []
    for d in docs:
        m = d.metadata
        grouped.setdefault(m['document_id'], []).append(d)
        chunks.append(dict(chunk_id=m['chunk_id'],document_id=m['document_id'],section=m.get('item') or m.get('article_number'),
                           content=d.page_content,page_start=m['page_start']-1,page_end=m['page_end']-1,
                           metadata=pack(retrieval_metadata(m) if module == 'rfp' else m)))
    records = []
    for did, group in grouped.items():
        m = group[0].metadata
        related = [payload['notices'][nid] for d in group for nid in d.metadata.get('notice_ids', [])] if module == 'rfp' else []
        years = {n['year'] for n in related if n.get('year') is not None}
        institutions = {n['institution'] for n in related if n.get('institution')}
        records.append(document_record(did,module,m.get('filename') or m.get('law_name') or did,
                        '\n'.join(d.metadata.get('original_text', d.page_content) for d in group),
                        retrieval_metadata(m) if module == 'rfp' else m,
                        source_path=str(cfg['data_dir']/m['source']),
                        year=next(iter(years)) if len(years)==1 else None,
                        institution=next(iter(institutions)) if len(institutions)==1 else None))
    return records, chunks, payload


def split_document(record, token_limit=1400, overlap=100):
    from app.common.chunking import _split_with_prefix
    embedder = get_embedder()
    prefix = record['title'] + '\n'
    parts = _split_with_prefix(record['full_text'], prefix, embedder.model.tokenizer,
                               min(token_limit,embedder.max_seq_length-2),overlap)
    return [dict(chunk_id=hashlib.sha256((record['document_id']+str(i)+part).encode()).hexdigest()[:32],
                 document_id=record['document_id'], section='body', content=prefix+part,
                 metadata={**record['metadata'], 'document_id':record['document_id'], 'original_text':part}) for i,part in enumerate(parts)]


def ntis_snapshot():
    from langchain_core.documents import Document
    from app.ntis_rag.config import DATA_PATH
    from app.ntis_rag.parsing.excel_loader import load_documents
    records, chunks = [], []
    for d in load_documents(DATA_PATH, Document):
        m = d.metadata
        r = document_record('ntis-'+m['project_id'],'ntis',m.get('project_title') or m['project_id'],d.page_content,m,
                            institution=m.get('research_agency'), source_path=str(DATA_PATH),
                            category_major=m.get('science_large'), category_middle=m.get('science_middle'), category_minor=m.get('science_small'))
        records.append(r)
        chunks.extend(split_document(r))
    return records, chunks, {}


def company_snapshot():
    path = RAW_DIR/'company/특허등록목록(시나리오용도).csv'
    # Patent rows are scenario inputs, not proof of real company ownership.
    try:
        text = path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError:
        text = path.read_text(encoding='cp949')
    rows = list(csv.DictReader(io.StringIO(text)))
    records, chunks = [], []
    for i,row in enumerate(rows):
        row = {k:str(v or '').strip() for k,v in row.items() if k}
        title = next((row[k] for k in ('발명의 명칭','발명의명칭','특허명','명칭') if row.get(k)), None)
        if not title:
            raise ValueError('기업 CSV에서 발명의 명칭 열을 확인할 수 없습니다.')
        number = next((row[k] for k in ('등록번호','특허등록번호','출원번호') if row.get(k)), None)
        identity = number or hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
        # Multiple CSV rows can share a registration number; keep each source row.
        did = f'company-{identity}-{i}'
        owner = next((row[k] for k in ('출원인','출원인명','등록권자','특허권자') if row.get(k)), None)
        classification = next((row[k] for k in ('IPC','IPC분류','IPC 분류') if row.get(k)),None)
        r = document_record(did,'company',title,'\n'.join(f'{k}: {v}' for k,v in row.items() if v),
                            {'source_row':i+2, **row}, source_path=str(path), institution=owner,
                            patents=[{'number':number,'owner':owner,'classification':classification}] if number else [])
        records.append(r)
        chunks.extend(split_document(r))
    return records, chunks, {'scenario_only':True}


def build_snapshot(module):
    if module == 'technology':
        return technology_snapshot()
    if module in {'rfp','policy'}:
        return pdf_snapshot(module)
    if module == 'ntis':
        return ntis_snapshot()
    if module == 'company':
        return company_snapshot()
    raise ValueError(f'지원하지 않는 자료 종류: {module}')
