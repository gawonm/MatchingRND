# -*- coding: utf-8 -*-
"""RFP 요구사항 PDF의 하이브리드 검색 모듈.

통합 코드에서 build_index(data_dir=...)를 한 번 호출하고 반환된 인덱스를
search(index, question)에 재사용합니다. 검색 문맥과 원문 출처를 반환하며,
답변 생성은 통합 단계에서 처리합니다. import 시 데이터 처리는 없습니다.
"""
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def rrf(result_lists, k=60):
    """키워드 및 벡터 검색 순위를 reciprocal rank fusion으로 병합합니다."""
    if k <= 0:
        raise ValueError('RRF k는 양수여야 합니다.')
    scores = {}
    for hits in result_lists:
        seen = set()
        rank = 0
        for chunk_id, _ in hits:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            rank += 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def _positive_int(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f'{name}는 {minimum} 이상의 정수여야 합니다.')
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f'{name}는 {minimum} 이상의 정수여야 합니다.') from error
    if result < minimum:
        raise ValueError(f'{name}는 {minimum} 이상의 정수여야 합니다.')
    return result


def _split_with_prefix(text, prefix, tokenizer, token_limit, overlap):
    """제목의 실제 토큰 수를 포함해 긴 원문을 누락 없이 분할합니다."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    length = lambda value: len(tokenizer.encode(value, add_special_tokens=False))
    if length(prefix + text) <= token_limit:
        return [text]
    budget = token_limit - length(prefix) - 8
    if budget < 1:
        raise ValueError('문서 제목이 청크 토큰 한도를 초과합니다.')
    while budget >= 1:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=budget, chunk_overlap=min(overlap, max(0, budget - 1)),
            length_function=length, separators=['\n\n', '\n', '. ', ' ', ''],
            strip_whitespace=False,
        )
        parts = [part for part in splitter.split_text(text) if part.strip()]
        if parts and all(length(prefix + part) <= token_limit for part in parts):
            return parts
        if budget == 1:
            break
        budget = max(1, budget // 2)
    raise ValueError('현재 토크나이저와 청크 설정으로 원문을 분할할 수 없습니다.')


def _retrieve(index, query, filters, allowed_keys):
    """메타데이터 조건을 키워드·벡터 검색과 문맥 확장에 함께 적용합니다."""
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        raise ValueError('filters는 메타데이터 키와 값을 담은 dict여야 합니다.')
    for key, value in filters.items():
        if key not in allowed_keys or not isinstance(value, (str, int, float, bool)):
            raise ValueError(f'지원하지 않는 검색 필터: {key}')
        if isinstance(value, str) and not value.strip():
            raise ValueError(f'검색 필터 값이 비어 있습니다: {key}')
    allowed = [
        doc for doc in index['docs']
        if all(doc.metadata.get(key) == value for key, value in filters.items())
    ]
    if not allowed:
        return [], [], []
    if filters:
        from langchain_community.retrievers import BM25Retriever

        keyword = BM25Retriever.from_documents(allowed, preprocess_func=index['kiwi_tokenize'])
        keyword.k = min(index['KEYWORD_K'], len(allowed))
        conditions = [{key: value} for key, value in filters.items()]
        where = conditions[0] if len(conditions) == 1 else {'$and': conditions}
        keyword_hits = keyword.invoke(query)
        dense_hits = index['vectorstore'].similarity_search(
            query, k=min(index['VECTOR_K'], len(allowed)), filter=where,
        )
    else:
        keyword_hits = index['bm25'].invoke(query)
        dense_hits = index['dense'].invoke(query)
    valid_ids = {doc.metadata['chunk_id'] for doc in allowed}

    def valid_hits(hits):
        seen = set()
        result = []
        for doc in hits:
            cid = doc.metadata.get('chunk_id') or getattr(doc, 'id', None)
            if cid in valid_ids and cid not in seen:
                seen.add(cid)
                result.append((cid, 0))
        return result

    return valid_hits(keyword_hits), valid_hits(dense_hits), allowed


def _ranking_rows(index, ranking, keyword_ranks, vector_ranks, reranker_scores=None):
    """문맥에 넣기 전의 검색 순위를 보존해 문맥 예산과 독립적으로 평가합니다."""
    rows = []
    for rank, (cid, score) in enumerate(ranking, 1):
        metadata = index['chunks_by_id'][cid].metadata
        rows.append({
            'rank': rank, 'chunk_id': cid,
            'document_id': metadata['document_id'],
            'article_id': metadata.get('article_id'),
            'task_id': metadata.get('task_id'),
            'rrf_score': score, 'keyword_rank': keyword_ranks.get(cid),
            'vector_rank': vector_ranks.get(cid),
            'reranker_score': (reranker_scores or {}).get(cid),
        })
    return rows


def evaluate_retrieval(result, relevant_ids, *, k=5, id_key='document_id'):
    """정답 ID를 직접 제공해 단일 질문의 Recall@K, MRR, Hit@K를 계산합니다.

    id_key를 chunk_id로 지정하면 정답 근거 청크의 검색 여부를 평가합니다.
    같은 문서의 여러 청크는 문서·과제 단위 평가에서 한 번만 계산합니다.
    relevance는 점수나 검색 실패로 추정하지 않고 외부 정답을 사용합니다.
    """
    k = _positive_int(k, 'k')
    if id_key not in {'document_id', 'article_id', 'task_id', 'chunk_id'}:
        raise ValueError('지원하지 않는 평가 ID입니다.')
    if isinstance(relevant_ids, str):
        raise ValueError('relevant_ids는 정답 ID의 목록 또는 집합이어야 합니다.')
    relevant = set(relevant_ids)
    if not relevant or any(not isinstance(value, str) or not value for value in relevant):
        raise ValueError('평가에는 하나 이상의 비어 있지 않은 정답 ID가 필요합니다.')
    ordered = list(dict.fromkeys(
        row[id_key] for row in result['ranking'] if row.get(id_key)
    ))
    first = next((rank for rank, value in enumerate(ordered, 1) if value in relevant), None)
    retrieved = ordered[:k]
    matched = relevant.intersection(retrieved)
    return {
        'k': k, 'id_key': id_key, 'recall_at_k': len(matched) / len(relevant),
        'mrr': 1.0 / first if first else 0.0, 'hit_at_k': bool(matched),
        'retrieved_ids': retrieved,
    }


TECHNICAL_SECTIONS = (
    '개발목표', '개발내용', '요구기술', '적용대상', '성능지표',
    '실증조건', '연구개발범위', '평가방법·평가조건',
)
CONTEXT_SECTIONS = TECHNICAL_SECTIONS + ('지원기간', '지원금액', '지원조건·특이사항')


def _source_key(path, data_dir):
    return path.resolve().relative_to(data_dir.resolve()).as_posix()


def _load_notices(data_dir, pdf_files, notice_path=None):
    """공고 연결은 선택적으로 읽으며 누락·중복은 검토 목록에 남깁니다."""
    notices, issues = {}, []
    links = {_source_key(path, data_dir): [] for path in pdf_files}
    by_name = defaultdict(list)
    for path in pdf_files:
        by_name[path.name].append(_source_key(path, data_dir))
    explicit = notice_path is not None
    workbook = Path(notice_path) if explicit else data_dir / 'RFP_공고목록.xlsx'
    if explicit and not workbook.is_absolute():
        workbook = (PROJECT_ROOT / workbook).resolve()
    if not workbook.is_file():
        if explicit:
            raise FileNotFoundError(f'공고목록 파일이 없습니다: {workbook}')
        issues.append({'reason': '공고목록 없음: PDF 검색은 수행하지만 공고 URL은 제공하지 않음', 'source': str(workbook)})
    else:
        import pandas as pd

        try:
            notice_table = pd.read_excel(workbook, sheet_name='공고목록').fillna('')
            match_table = pd.read_excel(workbook, sheet_name='파일매칭').fillna('')
            for columns, table in [
                ({'공고 UID', '공고명', '원 공고기관 URL'}, notice_table),
                ({'공고 UID', '파일명'}, match_table),
            ]:
                if not columns.issubset(table.columns):
                    raise ValueError(f'공고목록 필수 열 누락: {sorted(columns - set(table.columns))}')
            for _, row in notice_table.iterrows():
                uid = str(row['공고 UID']).strip().removesuffix('.0')
                if not uid:
                    issues.append({'reason': '공고 UID 없음'})
                    continue
                entry = {'title': str(row['공고명']).strip(), 'url': str(row['원 공고기관 URL']).strip()}
                if uid in notices and notices[uid] != entry:
                    issues.append({'reason': '같은 공고 UID의 내용이 다름', 'notice_id': uid})
                    continue
                notices[uid] = entry
            for _, row in match_table.iterrows():
                uid = str(row['공고 UID']).strip().removesuffix('.0')
                filename = str(row['파일명']).strip().replace('\\', '/')
                keys = ([filename] if filename in links else []) if '/' in filename else by_name.get(filename, [])
                if len(keys) != 1:
                    issues.append({'reason': 'PDF 연결 없음 또는 같은 파일명 중복', 'filename': filename, 'notice_id': uid})
                    continue
                if uid not in notices:
                    issues.append({'reason': '공고 ID 없음', 'filename': filename, 'notice_id': uid})
                    continue
                if uid not in links[keys[0]]:
                    links[keys[0]].append(uid)
        except Exception as error:
            # PDF 원문 근거는 사용할 수 있으므로 공고 연결 실패만 별도 보고합니다.
            notices = {}
            links = {_source_key(path, data_dir): [] for path in pdf_files}
            issues.append({'reason': '공고목록 읽기 실패', 'source': str(workbook), 'detail': str(error)})
    for source, ids in links.items():
        if not ids:
            issues.append({'reason': 'PDF 공고 연결 없음', 'source': source})
    return notices, links, issues


def build_index(data_dir=None, output_dir=None, *, model_name=None,
                local_files_only=True, notice_path=None):
    """PDF를 처리해 재사용 가능한 검색 인덱스와 검토 목록을 반환합니다.

    data_dir와 output_dir는 절대 경로나 프로젝트 기준 상대 경로입니다.
    모델은 기본적으로 로컬 캐시를 사용하며 출력 폴더에는 추출 캐시와
    Chroma 인덱스만 저장합니다. 입력 PDF가 없으면 ValueError를 발생시킵니다.
    """
    from dotenv import load_dotenv
    from langchain_core.documents import Document
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma
    from langchain_community.retrievers import BM25Retriever
    from kiwipiepy import Kiwi
    import pymupdf
    import pdfplumber
    load_dotenv(PROJECT_ROOT / '.env')
    data_dir = Path(data_dir) if data_dir is not None else Path('data/rfp')
    data_dir = (PROJECT_ROOT / data_dir).resolve() if not data_dir.is_absolute() else data_dir.resolve()
    OUTPUT = Path(output_dir) if output_dir is not None else Path('db/rfp')
    OUTPUT = (PROJECT_ROOT / OUTPUT).resolve() if not OUTPUT.is_absolute() else OUTPUT.resolve()
    pdf_files = sorted(data_dir.rglob('*.pdf'))
    if not pdf_files:
        raise ValueError(f'검색할 PDF가 없습니다: {data_dir}')
    (OUTPUT / 'cache').mkdir(parents=True, exist_ok=True)
    EMBEDDING_MODEL = os.getenv('RFP_EMBEDDING_MODEL', 'BAAI/bge-m3')
    CHUNK_TOKENS = _positive_int(os.getenv('RFP_CHUNK_TOKENS', '1400'), 'RFP_CHUNK_TOKENS')
    OVERLAP_TOKENS = _positive_int(os.getenv('RFP_OVERLAP_TOKENS', '100'), 'RFP_OVERLAP_TOKENS', 0)
    KEYWORD_K = _positive_int(os.getenv('RFP_KEYWORD_CANDIDATES', '30'), 'RFP_KEYWORD_CANDIDATES')
    VECTOR_K = _positive_int(os.getenv('RFP_VECTOR_CANDIDATES', '30'), 'RFP_VECTOR_CANDIDATES')
    TOP_K = _positive_int(os.getenv('RFP_TOP_K', '5'), 'RFP_TOP_K')
    RRF_K = _positive_int(os.getenv('RFP_RRF_K', '60'), 'RFP_RRF_K')
    CONTEXT_TOKENS = _positive_int(os.getenv('RFP_CONTEXT_TOKENS', '3500'), 'RFP_CONTEXT_TOKENS')
    if not (CHUNK_TOKENS > 300 and 0 <= OVERLAP_TOKENS < CHUNK_TOKENS - 200):
        raise ValueError('Invalid RAG configuration.')
    EMBEDDING_MODEL = model_name or os.getenv('RFP_EMBEDDING_MODEL', EMBEDDING_MODEL)
    notices, file_notice_ids, matching_issues = _load_notices(data_dir, pdf_files, notice_path)
    loaded_docs = []
    review_list = []
    failed_files = []
    for pdf_path in pdf_files:
        try:
            loaded, issues = ([], [])
            file_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            with pymupdf.open(pdf_path) as native_pdf:
                for pn, p in enumerate(native_pdf, 1):
                    meaningful = len(re.sub('\\s+', '', p.get_text()))
                    if meaningful < 30 and (p.get_images() or p.get_drawings()):
                        issues.append({'filename': pdf_path.name, 'page': pn, 'reason': 'OCR 필요 또는 그림 위주 페이지: 원문 검토'})
            cache_dir = OUTPUT / 'cache'
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = cache_dir / (hashlib.sha256(('rfp-loader-v4' + file_hash).encode()).hexdigest() + '.json')
            if cache_path.exists():
                cached = json.loads(cache_path.read_text(encoding='utf-8'))
                loaded = [Document(page_content=d['text'], metadata={**d['metadata'], 'source': _source_key(pdf_path, data_dir), 'filename': pdf_path.name, 'document_id': hashlib.sha256((_source_key(pdf_path, data_dir) + file_hash).encode()).hexdigest()[:24]}) for d in cached['blocks']]
                issues.extend(({**i, 'filename': pdf_path.name} for i in cached['issues']))
            else:
                with pdfplumber.open(pdf_path) as pdf:
                    for page_number, page in enumerate(pdf.pages, 1):
                        if len(page.chars) < 30:
                            reason = 'OCR 필요 또는 읽기 불명확' if page.images or page.curves else '빈 페이지 확인 필요'
                            issues.append({'filename': pdf_path.name, 'page': page_number, 'reason': reason})
                            continue
                        words = page.extract_words(x_tolerance=2, y_tolerance=3)
                        tables = page.find_tables()
                        blocks = []
                        for table in tables:
                            children = [child for child in tables if child is not table and child.bbox[0] >= table.bbox[0] and (child.bbox[1] >= table.bbox[1]) and (child.bbox[2] <= table.bbox[2]) and (child.bbox[3] <= table.bbox[3])]
                            rows = [[str(cell or '').strip() for cell in row] for row in table.extract()]
                            header_text = ' '.join(rows[0]) if rows else ''
                            metric_table = ('항목' in header_text or '지표' in header_text or '성능' in header_text) and ('차년도' in header_text or '목표' in header_text or '단위' in header_text)
                            if metric_table and (not children):
                                headers = rows[0]
                                if len(set(headers)) != len(headers) or any((not h for h in headers)):
                                    issues.append({'filename': pdf_path.name, 'page': page_number, 'reason': '병합 성능표 헤더 확인 필요'})
                                for row_index, row in enumerate(rows[1:], 1):
                                    for column, value in enumerate(row):
                                        if not value and table.rows[0].cells[column]:
                                            left, _, right, _ = table.rows[0].cells[column]
                                            _, top, _, bottom = table.rows[row_index].bbox
                                            row[column] = page.crop((left, top, right, bottom)).extract_text() or ''
                                text = '\n'.join((' | '.join((f'{h}: {v}' for h, v in zip(headers, row))) for row in rows[1:]))
                                blocks.append((table.bbox[1], Document(page_content=text, metadata={'kind': 'metric_table', 'headers': headers, 'rows': rows[1:], 'bbox': list(table.bbox), 'row_bboxes': [list(row.bbox) for row in table.rows[1:]]})))
                                continue
                            for row_index, row in enumerate(rows):
                                bbox = table.rows[row_index].bbox
                                contained = [child for child in children if child.bbox[1] >= bbox[1] - 1 and child.bbox[3] <= bbox[3] + 1]
                                if contained:
                                    row_words = [w for w in words if bbox[0] <= (w['x0'] + w['x1']) / 2 <= bbox[2] and bbox[1] <= (w['top'] + w['bottom']) / 2 <= bbox[3] and (not any((c.bbox[0] <= (w['x0'] + w['x1']) / 2 <= c.bbox[2] and c.bbox[1] <= (w['top'] + w['bottom']) / 2 <= c.bbox[3] for c in contained)))]
                                    line_groups = []
                                    for word in sorted(row_words, key=lambda w: (w['top'], w['x0'])):
                                        if not line_groups or abs(word['top'] - line_groups[-1][0]['top']) > 3:
                                            line_groups.append([word])
                                        else:
                                            line_groups[-1].append(word)
                                    text = '\n'.join((' '.join((w['text'] for w in sorted(group, key=lambda w: w['x0']))) for group in line_groups))
                                    cells = []
                                else:
                                    text = ' | '.join((value for value in row if value))
                                    cells = row
                                if text.strip():
                                    blocks.append((bbox[1], Document(page_content=text, metadata={'kind': 'table_row', 'cells': cells, 'bbox': list(bbox)})))
                        outside = [w for w in words if not any((t.bbox[0] <= (w['x0'] + w['x1']) / 2 <= t.bbox[2] and t.bbox[1] <= (w['top'] + w['bottom']) / 2 <= t.bbox[3] for t in tables))]
                        line_groups = []
                        for word in sorted(outside, key=lambda w: (w['top'], w['x0'])):
                            if not line_groups or abs(word['top'] - line_groups[-1][0]['top']) > 3:
                                line_groups.append([word])
                            else:
                                line_groups[-1].append(word)
                        for group in line_groups:
                            text = ' '.join((w['text'] for w in sorted(group, key=lambda w: w['x0'])))
                            if re.fullmatch('[-–—]?\\s*\\d+\\s*[-–—]?', text):
                                continue
                            blocks.append((group[0]['top'], Document(page_content=text, metadata={'kind': 'text', 'bbox': [min((w['x0'] for w in group)), min((w['top'] for w in group)), max((w['x1'] for w in group)), max((w['bottom'] for w in group))]})))
                        for label_word in words:
                            label = re.sub('\\s+', '', label_word['text']).strip(':：')
                            if label not in {'품목명', '과제명', '프로젝트명', 'RFP명', '관리번호', '과제번호'}:
                                continue
                            if any((re.sub('\\s+', '', d.metadata.get('cells', [''])[0] if d.metadata.get('cells') else '') == label for _, d in blocks)):
                                continue
                            candidates = [w for w in words if w['x0'] > label_word['x1'] + 4 and label_word['top'] - 16 <= w['top'] <= label_word['bottom'] + 16]
                            if not candidates:
                                continue
                            groups = []
                            for w in sorted(candidates, key=lambda w: (w['top'], w['x0'])):
                                if not groups or abs(w['top'] - groups[-1][0]['top']) > 3:
                                    groups.append([w])
                                else:
                                    groups[-1].append(w)
                            value = '\n'.join((' '.join((w['text'] for w in sorted(g, key=lambda w: w['x0']))) for g in groups))
                            value = re.split('\\(TRL\\s*:', value, flags=re.I)[0].strip()
                            if value:
                                blocks.append((label_word['top'] - 0.1, Document(page_content=label + ' | ' + value, metadata={'kind': 'table_row', 'cells': [label, value], 'bbox': [label_word['x0'], min((w['top'] for w in candidates)), max((w['x1'] for w in candidates)), max((w['bottom'] for w in candidates))]})))
                                issues.append({'filename': pdf_path.name, 'page': page_number, 'reason': '무테 라벨 좌표 복원: 제목·번호 원문 검토 필요'})
                        for _, block in sorted(blocks, key=lambda pair: pair[0]):
                            block.metadata.update({'source': _source_key(pdf_path, data_dir), 'filename': pdf_path.name, 'page': page_number, 'file_hash': file_hash, 'document_id': hashlib.sha256((_source_key(pdf_path, data_dir) + file_hash).encode()).hexdigest()[:24]})
                            loaded.append(block)
                counts = Counter(((d.page_content.strip(), round(d.metadata['bbox'][1] / 10)) for d in loaded if d.metadata['kind'] == 'text' and len(d.page_content) < 70))
                loaded = [d for d in loaded if not (counts[d.page_content.strip(), round(d.metadata['bbox'][1] / 10)] >= 3 and (d.metadata['bbox'][1] < 35 or d.metadata['bbox'][1] > 800) and (not re.search('과제|품목|번호|목표|개발|지원|지표', d.page_content)))]
                cache_path.write_text(json.dumps({'loader': 'rfp-loader-v4', 'file_hash': file_hash, 'blocks': [{'text': d.page_content, 'metadata': d.metadata} for d in loaded], 'issues': issues}, ensure_ascii=False, indent=2), encoding='utf-8')
            loaded_docs.extend(loaded)
            review_list.extend(issues)
        except Exception as error:
            failed_files.append({'filename': pdf_path.name, 'reason': str(error)})
    issues = list(review_list)
    tasks = []
    excluded_files = []
    title_labels = {'과제명', '품목명', '프로젝트명', 'RFP명', '연구개발과제명', '세부과제명', '세부품목명', '연구과제명'}
    number_labels = {'과제번호', '관리번호', '기술번호', 'RFP번호', 'RFP관리번호'}
    section_patterns = [
        ('개발목표', r'^(?:개발목표|연구개발목표|과제목표|최종목표|개념)'),
        ('개발내용', r'^(?:세부개발내용|개발내용|연구개발내용|연구내용|개념및개발내용)'),
        ('요구기술', r'^(?:요구기술|핵심기술|필요기술|기술요구사항|주요기술)'),
        ('적용대상', r'^(?:적용대상|적용분야|적용범위|대상시스템)'),
        ('실증조건', r'^(?:실증조건|실증내용|실증환경|실증대상|실증계획|검증조건)'),
        ('연구개발범위', r'^(?:연구개발범위|개발범위|연구범위|사업범위)'),
        ('평가방법·평가조건', r'^(?:평가방법|평가조건|시험조건|시험방법)'),
        ('성능지표', r'^(?:성능지표|성과지표|평가지표|성능목표|정량적목표)'),
        ('지원기간', r'^(?:개발기간|연구기간|지원기간)$'),
        ('지원금액', r'^(?:지원금액|정부지원금|총투입비용)'),
        ('지원조건·특이사항', r'^(?:지원조건|특기사항|기타사항|주관기관|주관연구개발기관|기술료|기타|안전관리)'),
        ('기타 원문', r'^(?:추진배경|필요성|기대효과|활용방안|추진체계)'),
    ]
    for pdf_path in pdf_files:
        file_blocks = [d for d in loaded_docs if d.metadata['source'] == _source_key(pdf_path, data_dir)]
        current_task = None
        pending_number = ''
        item = '기타 원문'
        file_tasks = []
        ambiguous = any((i['filename'] == pdf_path.name and 'OCR' in i['reason'] for i in issues))
        for block in file_blocks:
            compact_text = re.sub('\\s+', '', block.page_content)
            if re.search('총괄품목명|[1-9]세부품목명', compact_text):
                ambiguous = True
                issues.append({'filename': pdf_path.name, 'page': block.metadata['page'], 'reason': '총괄·세부 관계 확인 필요'})
            cells = [v for v in block.metadata.get('cells', []) if v.strip()]
            label = re.sub('\\s+', '', cells[0]).strip(':：') if cells else ''
            label = re.sub('^[①②③④⑤⑥⑦⑧⑨⑩0-9]+', '', label)
            if not cells and block.metadata['kind'] == 'text':
                match = re.match('^(연구개발과제명|세부과제명|연구과제명|과제명|품목명|프로젝트명|RFP명)\\s*[:：|]?\\s+(.+)$', block.page_content)
                if match:
                    label, value = match.groups()
                    if any((d.metadata['page'] == block.metadata['page'] and d.metadata.get('cells') and (re.sub('\\s+', '', d.metadata['cells'][0]) == label) and (abs(d.metadata['bbox'][1] - block.metadata['bbox'][1]) < 40) for d in file_blocks)):
                        continue
                    cells = [label, value]
                elif compact_text in title_labels:
                    reconstructed = any((d.metadata['page'] == block.metadata['page'] and d.metadata.get('cells') and (re.sub('\\s+', '', d.metadata['cells'][0]) == compact_text) and (abs(d.metadata['bbox'][1] - block.metadata['bbox'][1]) < 40) for d in file_blocks))
                    if reconstructed:
                        continue
            if label in number_labels and len(cells) > 1:
                number_lines = [line for line in cells[1].splitlines() if not re.search('산업|중분류|대분류|기술분류', line)]
                pending_number = ''.join(number_lines).strip()
            if label in title_labels and len(cells) > 1:
                title = re.split('\\(TRL\\s*:', cells[1], flags=re.I)[0].strip()
                task_id = hashlib.sha256((block.metadata['document_id'] + title + str(len(file_tasks))).encode()).hexdigest()[:24]
                current_task = {'task_id': task_id, 'title': title, 'task_number': pending_number, 'document_id': block.metadata['document_id'], 'file_hash': block.metadata['file_hash'], 'filename': pdf_path.name, 'source': _source_key(pdf_path, data_dir), 'title_source': {'text': block.page_content, 'metadata': block.metadata}, 'fields': defaultdict(list), 'metrics': []}
                file_tasks.append(current_task)
                pending_number = ''
                item = '기타 원문'
                continue
            if label not in title_labels and re.match('^(?:과제명|품목명|RFP명|프로젝트명)\\s*[:：|]?', block.page_content):
                if block.metadata['kind'] == 'text':
                    ambiguous = True
                    current_task = None
                    issues.append({'filename': pdf_path.name, 'page': block.metadata['page'], 'reason': '제목 경계 구조화 확인 필요'})
            if current_task is None:
                continue
            if block.metadata['kind'] == 'metric_table':
                item = '성능지표'
                current_task['fields'][item].append(block)
                for row in block.metadata['rows']:
                    columns = dict(zip(block.metadata['headers'], row))
                    indicator = next((v for h, v in columns.items() if h in {'항목', '지표명', '평가항목', '성능지표'}), '')
                    goals = [{'stage': h, 'value': v} for h, v in columns.items() if '차년도' in h or '목표' in h or '단계' in h]
                    current_task['metrics'].append({'columns': columns, 'indicator': indicator, 'goals': goals, 'unit': next((v for h, v in columns.items() if '단위' in h), ''), 'evaluation_method': next((v for h, v in columns.items() if '평가방법' in h or '시험방법' in h), ''), 'evaluation_conditions': next((v for h, v in columns.items() if '평가조건' in h or '시험조건' in h), ''), 'page': block.metadata['page'], 'bbox': block.metadata['bbox']})
                continue
            text_lines = block.page_content.splitlines() if block.metadata['kind'] == 'text' or not cells else [block.page_content]
            for line in text_lines:
                clean = re.sub('^[\\s□■ㅇ◦○▪※]+', '', line).strip()
                clean = re.sub('^(?:\\d+|[가-하])[.)]\\s*', '', clean)
                head = re.sub('\\s+', '', clean.split('|')[0].split(':')[0])
                found = next((name for name, pattern in section_patterns if re.search(pattern, head)), None)
                if found:
                    item = found
                if not line.strip():
                    continue
                fragment = Document(page_content=line, metadata=dict(block.metadata))
                current_task['fields'][item].append(fragment)
        if not file_tasks:
            issues.append({'filename': pdf_path.name, 'page': None, 'reason': '명확한 표 안 과제명 발견 못함'})
            ambiguous = True
        if ambiguous:
            excluded_files.append(pdf_path.name)
            continue
        for task in file_tasks:
            if not task['fields'].get('개발목표'):
                issues.append({'filename': pdf_path.name, 'page': None, 'reason': '명시적 개발목표 항목 없음: 원문 확인 필요'})
            if not any((task['fields'].get(name) for name in TECHNICAL_SECTIONS)):
                issues.append({'filename': pdf_path.name, 'page': None, 'reason': '명시적 요구사항 항목 없음'})
                continue
            tasks.append(task)
    review_list = issues
    if not tasks:
        raise ValueError(f'구조가 확인된 RFP 과제가 없습니다. 추출 실패 {len(failed_files)}개, 검토 제외 {len(excluded_files)}개를 확인하세요.')
    embedding = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL, model_kwargs={'device': 'cpu', 'local_files_only': local_files_only}, encode_kwargs={'normalize_embeddings': True})
    tokenizer = embedding._client.tokenizer
    token_limit = min(CHUNK_TOKENS, embedding._client.max_seq_length - 2)
    if token_limit <= 0 or OVERLAP_TOKENS >= token_limit:
        raise ValueError('RFP 청크 길이와 겹침 토큰 설정을 확인하세요.')
    issues = review_list
    docs = []
    chunks_by_id = {}
    for task in tasks:
        prefix = f"과제명: {task['title']}\n과제번호: {task['task_number']}\n"
        atoms = []
        for item, fragments in task['fields'].items():
            if item == '기타 원문':
                continue
            for fragment in fragments:
                if fragment.metadata['kind'] == 'metric_table':
                    headers = fragment.metadata['headers']
                    for row_number, row in enumerate(fragment.metadata['rows']):
                        body = ' | '.join(f'{h}: {v}' for h, v in zip(headers, row))
                        metadata = dict(fragment.metadata)
                        row_bboxes = metadata.get('row_bboxes', [])
                        if row_number < len(row_bboxes):
                            metadata['bbox'] = row_bboxes[row_number]
                        metadata['kind'] = 'metric_row'
                        atoms.append((item, body, metadata))
                else:
                    atoms.append((item, fragment.page_content, fragment.metadata))
        packs = []
        for item, body, metadata in atoms:
            label = prefix + f'항목명: {item}\n'
            # 긴 표 행·실증조건도 삭제하지 않고 실제 제목 토큰 예산에 맞춰 분할합니다.
            for part in _split_with_prefix(body, label, tokenizer, token_limit, OVERLAP_TOKENS):
                source = {**metadata, 'original_text': part}
                if packs and packs[-1]['item'] == item and len(tokenizer.encode(
                    label + '\n'.join(packs[-1]['bodies'] + [part]), add_special_tokens=False,
                )) <= token_limit:
                    packs[-1]['bodies'].append(part)
                    packs[-1]['sources'].append(source)
                else:
                    packs.append({'item': item, 'bodies': [part], 'sources': [source]})
        whole = prefix + '항목명: 과제전체\n' + '\n'.join(
            f"[{pack['item']}]\n" + '\n'.join(pack['bodies']) for pack in packs
        )
        if packs and len(tokenizer.encode(whole, add_special_tokens=False)) <= token_limit:
            packs = [{
                'item': '과제전체', 'bodies': [whole[len(prefix + '항목명: 과제전체\n'):]],
                'sources': [source for pack in packs for source in pack['sources']],
            }]
        for pack_number, pack in enumerate(packs, 1):
            original_text = '\n'.join(pack['bodies'])
            text = prefix + f"항목명: {pack['item']}\n" + original_text
            chunk_id = hashlib.sha256((task['task_id'] + str(pack_number) + text).encode()).hexdigest()[:32]
            pages = sorted({source['page'] for source in pack['sources']})
            metadata = {
                'chunk_id': chunk_id, 'parent_id': task['task_id'], 'task_id': task['task_id'],
                'document_id': task['document_id'], 'title': task['title'],
                'task_number': task['task_number'], 'item': pack['item'],
                'source': task['source'], 'filename': task['filename'], 'file_hash': task['file_hash'],
                'pages': pages, 'page_start': min(pages), 'page_end': max(pages),
                'notice_ids': file_notice_ids[task['source']], 'sources': pack['sources'],
                'original_text': original_text,
            }
            document = Document(page_content=text, metadata=metadata)
            docs.append(document)
            chunks_by_id[chunk_id] = document
    review_list = issues
    if not docs:
        raise ValueError('검색 가능한 청크가 없습니다. 원문·검토 목록을 확인하세요.')
    corpus_key = hashlib.sha256((EMBEDDING_MODEL + '|normalized|rfp-requirements-v4|' + '|'.join(sorted(chunks_by_id))).encode()).hexdigest()[:20]
    vectorstore = Chroma(collection_name='rfp_study_' + corpus_key, embedding_function=embedding, persist_directory=str(OUTPUT / 'chroma'))
    stored_ids = set(vectorstore.get(include=[])['ids'])
    new_docs = []
    for document in docs:
        if document.metadata['chunk_id'] not in stored_ids:
            scalar_metadata = {key: value for key, value in document.metadata.items() if isinstance(value, (str, int, float, bool))}
            new_docs.append(Document(page_content=document.page_content, metadata=scalar_metadata))
    for start in range(0, len(new_docs), 4):
        batch = new_docs[start:start + 4]
        vectorstore.add_documents(batch, ids=[d.metadata['chunk_id'] for d in batch])
    if not set(vectorstore.get(include=[])['ids']) == set(chunks_by_id):
        raise ValueError('Invalid RAG configuration.')
    dense = vectorstore.as_retriever(search_kwargs={'k': min(VECTOR_K, len(docs))})
    dataset = {'notices': notices, 'tasks': tasks}
    kiwi = Kiwi()

    def kiwi_tokenize(text):
        text = re.sub('[‐‑‒–—−]', '-', text.lower())
        text = re.sub('(?<=-)\\s*\\n\\s*', '', text)
        words = [token.form for token in kiwi.tokenize(text)]
        identifiers = re.findall('[a-z0-9가-힣]+(?:[-+&./][a-z0-9가-힣]+)*', text)
        return words + identifiers
    bm25 = BM25Retriever.from_documents(docs, preprocess_func=kiwi_tokenize)
    bm25.k = min(KEYWORD_K, len(docs))
    max_query_tokens = embedding._client.max_seq_length
    return {'docs': docs, 'chunks_by_id': chunks_by_id, 'dataset': dataset, 'tasks': tasks, 'tasks_by_id': {task['task_id']: task for task in tasks}, 'excluded_files': excluded_files, 'matching_issues': matching_issues, 'tokenizer': tokenizer, 'max_query_tokens': max_query_tokens, 'vectorstore': vectorstore, 'dense': dense, 'bm25': bm25, 'kiwi_tokenize': kiwi_tokenize, 'review_list': review_list, 'failed_files': failed_files, 'KEYWORD_K': KEYWORD_K, 'VECTOR_K': VECTOR_K, 'TOP_K': TOP_K, 'RRF_K': RRF_K, 'CONTEXT_TOKENS': CONTEXT_TOKENS}


def build_query(owned_technologies, technical_problem, *, external_elements=None,
                ntis_elements=None, unmet_elements=None, return_details=False):
    """최초 기술문제를 유지하고 출처가 제공된 기술요소로 쿼리를 확장합니다.

    기본 반환값은 검색 문자열입니다. return_details=True이면 Baseline,
    Cascade 및 확장 원문·출처를 함께 반환하며 search에 그대로 전달할 수 있습니다.
    이 함수는 원문 진위나 기술 충족 여부를 판정하지 않습니다.
    """
    def text(value, name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{name}는 비어 있지 않은 문자열이어야 합니다.')
        return value.strip()

    def unique_names(values, name):
        if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
            raise ValueError(f'{name}는 문자열의 목록이어야 합니다.')
        unique, seen = [], set()
        for value in values:
            value = text(value, name)
            key = re.sub(r'\s+', '', value).casefold()
            if key not in seen:
                seen.add(key)
                unique.append(value)
        return unique

    owned = unique_names(owned_technologies, '보유기술')
    problem = text(technical_problem, '최초 기술문제')
    unmet = unique_names(unmet_elements or [], '미충족 검토 요소')
    baseline = '보유기술: ' + ' / '.join(owned) + '\n기술문제: ' + problem
    parts, provenance, seen_sources = [baseline], [], set()
    seen_terms = {re.sub(r'\s+', '', value).casefold() for value in owned}
    for kind, elements in [('external_technology', external_elements or []), ('ntis', ntis_elements or [])]:
        if not isinstance(elements, (list, tuple)):
            raise ValueError('확장 요소는 기술명·원문·출처 ID를 담은 dict의 목록이어야 합니다.')
        for element in elements:
            if not isinstance(element, dict):
                raise ValueError('각 확장 요소는 dict여야 합니다.')
            technology = text(element.get('technology'), '확장 기술명')
            quote = text(element.get('quote'), '확장 근거 원문')
            source_id = text(element.get('source_id'), '확장 출처 ID')
            identity = (kind, source_id, technology, quote)
            if identity not in seen_sources:
                seen_sources.add(identity)
                provenance.append({
                    'kind': kind, 'technology': technology,
                    'quote': quote, 'source_id': source_id,
                })
            term_key = re.sub(r'\s+', '', technology).casefold()
            if term_key not in seen_terms:
                seen_terms.add(term_key)
                label = '외부기술 요소' if kind == 'external_technology' else 'NTIS 기술요소'
                parts.append(f'{label}: {technology}')
    parts.extend('미충족 검토 요소 (기업 입력): ' + element for element in unmet)
    query = '\n'.join(parts)
    if not return_details:
        return query
    return {
        'query': query, 'baseline_query': baseline,
        'owned_technologies': owned, 'technical_problem': problem,
        'expansion_sources': provenance, 'unmet_elements': unmet,
    }


def compare_queries(index, query_details, relevant_ids, *, k=5, id_key='task_id', **search_options):
    """같은 인덱스·검색 설정으로 Baseline/Cascade의 단일 질문 평가를 비교합니다."""
    if not isinstance(query_details, dict) or not query_details.get('baseline_query'):
        raise ValueError('build_query(..., return_details=True)의 결과가 필요합니다.')
    baseline = search(index, query_details['baseline_query'], **search_options)
    cascade = search(index, query_details, **search_options)
    relevant_ids = list(relevant_ids) if not isinstance(relevant_ids, str) else relevant_ids
    return {
        'baseline': {'result': baseline, 'metrics': evaluate_retrieval(baseline, relevant_ids, k=k, id_key=id_key)},
        'cascade': {'result': cascade, 'metrics': evaluate_retrieval(cascade, relevant_ids, k=k, id_key=id_key)},
    }


def _task_requirements(task):
    """검색된 과제의 명시적 요구항목 원문을 위치와 함께 반환합니다."""
    return {
        item: [{
            'text': fragment.page_content, 'page': fragment.metadata['page'],
            'bbox': fragment.metadata.get('bbox'), 'source': fragment.metadata['source'],
            'source_kind': fragment.metadata['kind'],
        } for fragment in fragments]
        for item, fragments in task.get('fields', {}).items()
        if item in TECHNICAL_SECTIONS
    }


def search(index, question, *, top_k=None, context_tokens=None, run_reranker=False,
           filters=None, reranker=None):
    """RFP 후보와 요구사항 원문·문맥·출처·평가용 전체 순위를 반환합니다.

    question은 문자열 또는 build_query(..., return_details=True)의 결과입니다.
    top_k는 중복 청크 수가 아닌 고유 과제 후보 수입니다. 필터는 키워드·벡터
    검색 및 문맥 확장에 동일하게 적용합니다. LLM 답변·기술 Gap 판정은 수행하지 않습니다.
    """
    details = dict(question) if isinstance(question, dict) else None
    query = details.get('query') if details is not None else question
    if not isinstance(query, str) or not query.strip():
        raise ValueError('검색 질문을 문자열로 입력하세요.')
    query = query.strip()
    if details is not None and details.get('baseline_query') and not query.startswith(details['baseline_query']):
        raise ValueError('Cascade 질문에는 최초 입력인 baseline_query가 유지되어야 합니다.')
    tokenizer = index['tokenizer']
    top_k = _positive_int(top_k if top_k is not None else index['TOP_K'], 'top_k')
    context_tokens = _positive_int(
        context_tokens if context_tokens is not None else index['CONTEXT_TOKENS'], 'context_tokens',
    )
    if len(tokenizer.encode(query, add_special_tokens=False)) + 2 > index['max_query_tokens']:
        raise ValueError('질문이 임베딩 토큰 한도를 넘었습니다. 최초 기술문제를 유지하며 확장 요소를 줄이세요.')
    keyword, vector, allowed_docs = _retrieve(
        index, query, filters,
        {'document_id', 'task_id', 'task_number', 'filename', 'source', 'item'},
    )
    ranking = rrf([keyword, vector], k=index['RRF_K'])
    keyword_ranks = {cid: rank for rank, (cid, _) in enumerate(keyword, 1)}
    vector_ranks = {cid: rank for rank, (cid, _) in enumerate(vector, 1)}
    chunks = index['chunks_by_id']
    reranker_scores = {}
    if ranking and (run_reranker or reranker is not None):
        import math

        if reranker is None:
            from sentence_transformers import CrossEncoder

            model = os.getenv('RFP_RERANKER_MODEL', '')
            if not model:
                raise ValueError('RFP_RERANKER_MODEL을 지정하거나 reranker를 전달하세요.')
            reranker = CrossEncoder(model, device='cpu', local_files_only=True)
        scores = list(reranker.predict([(query, chunks[cid].page_content) for cid, _ in ranking]))
        if len(scores) != len(ranking) or any(not math.isfinite(float(score)) for score in scores):
            raise ValueError('리랭커의 점수 개수 또는 값이 올바르지 않습니다.')
        reranker_scores = {cid: float(score) for (cid, _), score in zip(ranking, scores)}
        ranking.sort(key=lambda pair: -reranker_scores[pair[0]])
    ranking_rows = _ranking_rows(index, ranking, keyword_ranks, vector_ranks, reranker_scores)
    rows_by_id = {row['chunk_id']: row for row in ranking_rows}
    selected, seen_tasks = [], set()
    for cid, score in ranking:
        task_id = chunks[cid].metadata['task_id']
        if task_id not in seen_tasks:
            seen_tasks.add(task_id)
            selected.append((cid, score))
        if len(selected) == top_k:
            break

    # 모든 후보의 대표 근거를 먼저 배치한 뒤 같은 과제의 조건을 보충합니다.
    sources, context_parts = [], []
    used_ids, skipped_ids = set(), set()
    notices_by_id = index['dataset']['notices']

    def add(cid, candidate_rank, expanded_from=None):
        if cid in used_ids:
            return
        document = chunks[cid]
        metadata = document.metadata
        expanded = expanded_from is not None
        label = (
            f"[근거 {cid} | {metadata['source']} | {metadata['pages']}쪽 | "
            f"과제={metadata['task_id']} | 항목={metadata['item']} | 확장={expanded}]"
        )
        part = label + '\n' + document.page_content
        if len(tokenizer.encode('\n\n'.join(context_parts + [part]), add_special_tokens=False)) > context_tokens:
            skipped_ids.add(cid)
            return
        linked = [notices_by_id[nid] for nid in metadata.get('notice_ids', []) if nid in notices_by_id]
        origin = rows_by_id[expanded_from or cid]
        evidence = {
            'evidence_id': cid, 'chunk_id': cid, 'task_id': metadata['task_id'],
            'document_id': metadata['document_id'], 'source_type': 'rfp',
            'role': 'technical_candidate', 'source': metadata['source'],
            'filename': metadata['filename'], 'pages': metadata['pages'],
            'text': metadata.get('original_text', document.page_content),
            'content': document.page_content, 'item': metadata['item'], 'title': metadata['title'],
            'source_locations': [{
                'page': source['page'], 'bbox': source.get('bbox'),
                'source_kind': source['kind'], 'text': source.get('original_text', ''),
            } for source in metadata.get('sources', [])],
            'rank': None if expanded else candidate_rank,
            'rrf_score': None if expanded else origin['rrf_score'],
            'keyword_rank': None if expanded else origin['keyword_rank'],
            'vector_rank': None if expanded else origin['vector_rank'],
            'reranker_score': None if expanded else origin['reranker_score'],
            'expanded': expanded, 'expanded_from': expanded_from,
            'notice_ids': metadata.get('notice_ids', []),
            'notice_titles': [notice['title'] for notice in linked],
            'notice_urls': [notice['url'] for notice in linked if notice['url']],
            'notice_link_status': 'linked' if linked else 'not_available',
        }
        # 기존 표시용 필드도 유지하여 통합 시 호출부 수정을 줄입니다.
        evidence.update({
            '과제명': evidence['title'], '항목': evidence['item'],
            '파일명': evidence['filename'], '페이지': evidence['pages'],
            '공고명': evidence['notice_titles'], '공고URL': evidence['notice_urls'],
            '원문': evidence['text'],
        })
        used_ids.add(cid)
        context_parts.append(part)
        sources.append(evidence)

    for candidate_rank, (cid, _) in enumerate(selected, 1):
        add(cid, candidate_rank)
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        original = chunks[cid]
        if cid not in used_ids or original.metadata['item'] == '과제전체':
            continue
        for item in CONTEXT_SECTIONS:
            for related in allowed_docs:
                if related.metadata['task_id'] == original.metadata['task_id'] and related.metadata['item'] == item:
                    add(related.metadata['chunk_id'], candidate_rank, expanded_from=cid)

    hits = []
    tasks_by_id = index.get('tasks_by_id') or {
        task['task_id']: task for task in index['dataset'].get('tasks', [])
    }
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        metadata = chunks[cid].metadata
        task = tasks_by_id.get(metadata['task_id'], {})
        hits.append({
            **rows_by_id[cid], 'rank': candidate_rank, 'title': metadata['title'],
            'task_number': metadata.get('task_number', ''), 'filename': metadata['filename'],
            'source': metadata['source'], 'result_type': 'technical_candidate',
            'requirements': _task_requirements(task), 'metrics': task.get('metrics', []),
            'context_evidence_ids': [row['chunk_id'] for row in sources if row['task_id'] == metadata['task_id']],
            'review_notes': [row for row in index.get('review_list', []) if row.get('filename') == metadata['filename']],
        })
    status = 'ok' if sources else ('context_limit' if ranking else 'no_matches')
    return {
        'question': query, 'query_details': details, 'context': '\n\n'.join(context_parts),
        'sources': sources, 'hits': hits, 'ranking': ranking_rows, 'status': status,
        'result_type': 'technical_candidate', 'filters': dict(filters or {}),
        'context_truncated': bool(skipped_ids), 'omitted_context_ids': sorted(skipped_ids),
        'diagnostics': {
            'failed_files': index.get('failed_files', []),
            'excluded_files': index.get('excluded_files', []),
            'matching_issues': index.get('matching_issues', []),
        },
    }
