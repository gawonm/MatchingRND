# -*- coding: utf-8 -*-
"""법령 조문 PDF의 하이브리드 검색 모듈.

통합 코드에서 build_index(data_dir=...)를 한 번 호출하고 반환된 인덱스를
search(index, question)에 재사용합니다. 검색 문맥과 원문 출처를 반환하며,
답변 생성은 통합 단계에서 처리합니다. import 시 데이터 처리는 없습니다.
"""
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote

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


def _extract_articles(raw, document_factory):
    """PDF 조문 단위와 원문 줄의 페이지·좌표를 보존합니다."""
    meta = raw['metadata']
    heading = re.compile(r'^(제\s*\d+\s*조(?:\s*의\s*\d+)?)(?:\s*\(([^)]*)\))?\s*(.*)$')
    lines = []
    for page in raw['pages']:
        for block in page['blocks']:
            for text in block['text'].splitlines():
                text = text.strip()
                if not text or ('법제처' in text and '국가법령정보센터' in text):
                    continue
                if text == meta['law_name'] or text.startswith(meta['law_name'] + ' ('):
                    continue
                if re.search(r'(?:\.{2,}|…|⋯)\s*\d+\s*$', text):
                    continue
                lines.append({'text': text, 'page': page['page'], 'bbox': block['bbox']})
    start = next((i for i, line in enumerate(lines) if heading.match(line['text'])), None)
    reviews, excluded, articles = [], [], []
    if start is None:
        reviews.append({'filename': meta['filename'], 'page': None, 'reason': '조문 본문 시작을 찾지 못함: 검색 제외'})
        return articles, reviews, excluded
    units, current = [], None
    supplementary = appendix = False
    for line in lines[start:]:
        text = line['text']
        if re.match(r'^부\s*칙\s*(?:<|$)', text):
            appendix = False
            supplementary = True
            current = {'article_number': '부칙', 'article_title': text, 'kind': '부칙', 'lines': []}
            units.append(current)
        elif re.match(r'^(?:\[(?:별표|별지)\s*|[■□].*\[(?:별표|별지)\s*|(?:별표|별지)\s*(?:제)?\d+(?:호서식)?\s*$)', text):
            appendix = True
        if appendix:
            excluded.append({**meta, **line, 'reason': '별표·별지: 구조 검토가 필요해 검색에서 제외'})
            continue
        if re.match(r'^제\s*\d+\s*(?:편|장|절|관)(?:\s+.*)?$', text):
            continue
        match = heading.match(text)
        if match and not supplementary:
            number, title, _ = match.groups()
            current = {
                'article_number': re.sub(r'\s+', '', number),
                'article_title': title or '', 'kind': '본칙', 'lines': [],
            }
            units.append(current)
        if current is not None:
            current['lines'].append(line)
    counts = Counter(unit['article_number'] for unit in units if unit['kind'] == '본칙')
    for position, unit in enumerate(units):
        text = '\n'.join(line['text'] for line in unit['lines'])
        spans, offset = [], 0
        for line in unit['lines']:
            spans.append({
                'start': offset, 'end': offset + len(line['text']),
                'page': line['page'], 'bbox': line['bbox'],
            })
            offset += len(line['text']) + 1
        pages = sorted({line['page'] for line in unit['lines']})
        notes = []
        if unit['kind'] == '부칙':
            notes.append('부칙: 공포일별 적용·경과조치 확인 필요')
        if unit['kind'] == '본칙' and counts[unit['article_number']] > 1:
            notes.append('같은 조문 번호 반복: 조문별 시행일·버전 확인 필요')
        if re.search(r'\[시행일|\[시행\s*:', text):
            notes.append('조문별 시행일 표기 확인 필요')
        article_id = hashlib.sha256((meta['document_id'] + str(position) + text).encode()).hexdigest()[:24]
        metadata = {
            **meta, 'article_id': article_id, 'parent_id': meta['document_id'],
            'article_number': unit['article_number'], 'article_title': unit['article_title'],
            'kind': unit['kind'], 'pages': pages, 'page_start': min(pages),
            'page_end': max(pages), 'source_spans': spans, 'review_note': ' / '.join(notes),
        }
        articles.append(document_factory(page_content=text, metadata=metadata))
        for note in notes:
            reviews.append({'filename': meta['filename'], 'page': min(pages), 'reason': note, 'article_id': article_id})
    return articles, reviews, excluded


def build_index(data_dir=None, output_dir=None, *, model_name=None,
                local_files_only=True):
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
    load_dotenv(PROJECT_ROOT / '.env')
    data_dir = Path(data_dir) if data_dir is not None else Path('data/raw')
    data_dir = (PROJECT_ROOT / data_dir).resolve() if not data_dir.is_absolute() else data_dir.resolve()
    OUTPUT = Path(output_dir) if output_dir is not None else Path('db/law')
    OUTPUT = (PROJECT_ROOT / OUTPUT).resolve() if not OUTPUT.is_absolute() else OUTPUT.resolve()
    pdf_files = sorted(data_dir.rglob('*.pdf'))
    if not pdf_files:
        raise ValueError(f'검색할 PDF가 없습니다: {data_dir}')
    (OUTPUT / 'cache').mkdir(parents=True, exist_ok=True)
    root = data_dir
    MODEL = os.getenv('RFP_EMBEDDING_MODEL', 'BAAI/bge-m3')
    CHUNK_TOKENS = _positive_int(os.getenv('LAW_CHUNK_TOKENS', '1000'), 'LAW_CHUNK_TOKENS')
    OVERLAP_TOKENS = _positive_int(os.getenv('LAW_OVERLAP_TOKENS', '80'), 'LAW_OVERLAP_TOKENS', 0)
    KEYWORD_K = _positive_int(os.getenv('LAW_KEYWORD_CANDIDATES', '30'), 'LAW_KEYWORD_CANDIDATES')
    VECTOR_K = _positive_int(os.getenv('LAW_VECTOR_CANDIDATES', '30'), 'LAW_VECTOR_CANDIDATES')
    TOP_K = _positive_int(os.getenv('LAW_TOP_K', '5'), 'LAW_TOP_K')
    RRF_K = _positive_int(os.getenv('LAW_RRF_K', '60'), 'LAW_RRF_K')
    CONTEXT_TOKENS = _positive_int(os.getenv('LAW_CONTEXT_TOKENS', '4000'), 'LAW_CONTEXT_TOKENS')
    MODEL = model_name or os.getenv('LAW_EMBEDDING_MODEL', MODEL)
    raw_documents = []
    review_list = []
    failed_files = []
    for path in pdf_files:
        try:
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            cache_path = OUTPUT / 'cache' / f'law-loader-v1-{file_hash}.json'
            if cache_path.exists():
                raw = json.loads(cache_path.read_text(encoding='utf-8'))
            else:
                with pymupdf.open(path) as pdf:
                    raw = {'pages': [{'page': number, 'text': page.get_text(), 'blocks': [{'bbox': list(b[:4]), 'text': b[4]} for b in page.get_text('blocks') if b[6] == 0]} for number, page in enumerate(pdf, 1)]}
                cache_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
            if not raw.get('pages'):
                raise ValueError('PDF에 추출 가능한 페이지가 없습니다.')
            first = raw['pages'][0]['text']
            law_name = path.stem.split('(')[0].strip()
            version = re.search('\\[시행\\s+([^\\]]+)\\]\\s*\\[([^\\]]+)\\]', first)
            if not version:
                review_list.append({'filename': path.name, 'page': 1, 'reason': '표제 시행일·공포정보 확인 필요'})
            effective = version.group(1).strip() if version else ''
            publication = version.group(2).strip() if version else ''
            kind = '시행규칙' if law_name.endswith('시행규칙') else '시행령' if law_name.endswith('시행령') else '행정규칙' if '지침' in law_name else '법률'
            family = re.sub(r'\s*시행(?:령|규칙)$', '', law_name).strip()
            document_id = hashlib.sha256((str(path.resolve().relative_to(root)) + file_hash).encode()).hexdigest()[:24]
            metadata = {'document_id': document_id, 'law_name': law_name, 'law_type': kind, 'law_family': family, 'effective_date': effective, 'publication': publication, 'filename': path.name, 'source': str(path.resolve().relative_to(root)), 'file_hash': file_hash, 'source_url_type': 'law_name_lookup', 'validity_status': 'not_verified', 'source_url': 'https://www.law.go.kr/' + ('행정규칙/' if kind == '행정규칙' else '법령/') + quote(law_name)}
            for page in raw['pages']:
                if len(re.sub('\\s+', '', page['text'])) < 30:
                    review_list.append({'filename': path.name, 'page': page['page'], 'reason': 'OCR 또는 빈 서식·이미지 원문 확인 필요'})
            raw_documents.append({'metadata': metadata, 'pages': raw['pages']})
        except Exception as error:
            failed_files.append({'filename': path.name, 'reason': str(error)})
    articles = []
    excluded_sections = []
    for raw in raw_documents:
        extracted, reviews, excluded = _extract_articles(raw, Document)
        articles.extend(extracted)
        review_list.extend(reviews)
        excluded_sections.extend(excluded)
    if not articles:
        raise ValueError('조문 추출 결과를 확인하세요.')
    embedding = HuggingFaceEmbeddings(model_name=MODEL, model_kwargs={'device': 'cpu', 'local_files_only': local_files_only}, encode_kwargs={'normalize_embeddings': True})
    tokenizer = embedding._client.tokenizer
    token_limit = min(CHUNK_TOKENS, embedding._client.max_seq_length - 2)
    if token_limit <= 0 or OVERLAP_TOKENS >= token_limit:
        raise ValueError('조문 청크 길이와 겹침 토큰 설정을 확인하세요.')
    docs = []
    for article in articles:
        m = article.metadata
        prefix = f"법령명: {m['law_name']}\n조문: {m['article_number']}({m['article_title']})\nPDF 표제 시행일: {m['effective_date']}\n"
        parts = _split_with_prefix(article.page_content, prefix, tokenizer, token_limit, OVERLAP_TOKENS)
        previous_start = -1
        for number, part in enumerate(parts, 1):
            offset = article.page_content.find(part, previous_start + 1)
            if offset < 0:
                raise ValueError('조문 청크의 원문 위치를 찾을 수 없습니다.')
            previous_start = offset
            locations = [
                span for span in m['source_spans']
                if span['start'] < offset + len(part) and span['end'] > offset
            ]
            pages = sorted({span['page'] for span in locations})
            text = prefix + part
            cid = hashlib.sha256((m['article_id'] + str(number) + text).encode()).hexdigest()[:32]
            docs.append(Document(page_content=text, metadata={
                **m, 'chunk_id': cid, 'parent_id': m['article_id'], 'part': number,
                'original_text': part, 'article_pages': m['pages'],
                'pages': pages, 'page_start': min(pages), 'page_end': max(pages),
                'source_locations': [{'page': span['page'], 'bbox': span['bbox']} for span in locations],
                'page_scope': '검색 청크 원문 페이지', 'char_start': offset, 'char_end': offset + len(part),
            }))
    chunks_by_id = {d.metadata['chunk_id']: d for d in docs}
    corpus_key = hashlib.sha256((MODEL + '|law-v2|normalized|' + '|'.join(sorted(chunks_by_id))).encode()).hexdigest()[:20]
    vectorstore = Chroma(collection_name='law_' + corpus_key, embedding_function=embedding, persist_directory=str(OUTPUT / 'chroma'))
    stored = set(vectorstore.get(include=[])['ids'])
    new_docs = [Document(page_content=d.page_content, metadata={k: v for k, v in d.metadata.items() if isinstance(v, (str, int, float, bool))}) for d in docs if d.metadata['chunk_id'] not in stored]
    for start in range(0, len(new_docs), 8):
        batch = new_docs[start:start + 8]
        vectorstore.add_documents(batch, ids=[d.metadata['chunk_id'] for d in batch])
    stale_ids = sorted(set(vectorstore.get(include=[])['ids']) - set(chunks_by_id))
    if stale_ids:
        vectorstore.delete(ids=stale_ids)
    if not set(vectorstore.get(include=[])['ids']) == set(chunks_by_id):
        raise ValueError('Invalid RAG configuration.')
    dense = vectorstore.as_retriever(search_kwargs={'k': min(VECTOR_K, len(docs))})
    kiwi = Kiwi()

    def kiwi_tokenize(text):
        words = [token.form for token in kiwi.tokenize(text.lower())]
        return words + re.findall('제\\d+조(?:의\\d+)?|[a-z][a-z0-9-]*', text.lower())
    bm25 = BM25Retriever.from_documents(docs, preprocess_func=kiwi_tokenize)
    bm25.k = min(KEYWORD_K, len(docs))
    max_query_tokens = embedding._client.max_seq_length
    return {'docs': docs, 'chunks_by_id': chunks_by_id, 'articles': articles, 'excluded_sections': excluded_sections, 'tokenizer': tokenizer, 'max_query_tokens': max_query_tokens, 'vectorstore': vectorstore, 'dense': dense, 'bm25': bm25, 'kiwi_tokenize': kiwi_tokenize, 'review_list': review_list, 'failed_files': failed_files, 'KEYWORD_K': KEYWORD_K, 'VECTOR_K': VECTOR_K, 'TOP_K': TOP_K, 'RRF_K': RRF_K, 'CONTEXT_TOKENS': CONTEXT_TOKENS}


def search(index, question, *, top_k=None, context_tokens=None, law_filter="", filters=None):
    """제도 참고용 조문과 원문 위치·검색 순위를 반환합니다.

    filters는 law_name, law_type, law_family, kind, document_id, article_number를
    지원합니다. PDF 표제 시행일은 제공하되 현재 유효성·지원자격은 판정하지 않습니다.
    top_k는 고유 조문 수이며 동일 조문의 다른 청크는 문맥 예산 내에서 확장합니다.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError('검색 질문을 문자열로 입력하세요.')
    query = question.strip()
    top_k = _positive_int(top_k if top_k is not None else index['TOP_K'], 'top_k')
    context_tokens = _positive_int(
        context_tokens if context_tokens is not None else index['CONTEXT_TOKENS'], 'context_tokens',
    )
    tokenizer = index['tokenizer']
    if len(tokenizer.encode(query, add_special_tokens=False)) + 2 > index['max_query_tokens']:
        raise ValueError('질문이 임베딩 토큰 한도를 넘었습니다.')
    if filters is not None and not isinstance(filters, dict):
        raise ValueError('filters는 dict여야 합니다.')
    filters = dict(filters or {})
    if not isinstance(law_filter, str):
        raise ValueError('law_filter는 법령명 문자열이어야 합니다.')
    if law_filter:
        if 'law_name' in filters and filters['law_name'] != law_filter:
            raise ValueError('law_filter와 filters의 법령명이 다릅니다.')
        filters['law_name'] = law_filter
    keyword, vector, allowed_docs = _retrieve(
        index, query, filters,
        {'law_name', 'law_type', 'law_family', 'kind', 'document_id', 'article_number'},
    )
    ranking = rrf([keyword, vector], k=index['RRF_K'])
    keyword_ranks = {cid: rank for rank, (cid, _) in enumerate(keyword, 1)}
    vector_ranks = {cid: rank for rank, (cid, _) in enumerate(vector, 1)}
    ranking_rows = _ranking_rows(index, ranking, keyword_ranks, vector_ranks)
    rows_by_id = {row['chunk_id']: row for row in ranking_rows}
    chunks = index['chunks_by_id']
    selected, seen_articles = [], set()
    for cid, score in ranking:
        article_id = chunks[cid].metadata['article_id']
        if article_id not in seen_articles:
            seen_articles.add(article_id)
            selected.append((cid, score))
        if len(selected) == top_k:
            break
    context_parts, sources = [], []
    used_ids, skipped_ids = set(), set()

    def add(cid, candidate_rank, expanded_from=None):
        if cid in used_ids:
            return
        document = chunks[cid]
        metadata = document.metadata
        expanded = expanded_from is not None
        label = (
            f"[근거 {cid} | {metadata['law_name']} {metadata['article_number']} | "
            f"{metadata['filename']} | {metadata['pages']}쪽 | 확장={expanded}]"
        )
        part = label + '\n' + document.page_content
        if len(tokenizer.encode('\n\n'.join(context_parts + [part]), add_special_tokens=False)) > context_tokens:
            skipped_ids.add(cid)
            return
        origin = rows_by_id[expanded_from or cid]
        source = {
            'evidence_id': cid, 'chunk_id': cid, 'article_id': metadata['article_id'],
            'document_id': metadata['document_id'], 'source_type': 'law',
            'role': 'institutional_reference', 'source': metadata['source'],
            'filename': metadata['filename'], 'pages': metadata['pages'],
            'article_pages': metadata.get('article_pages', metadata['pages']),
            'source_locations': metadata.get('source_locations', []),
            'text': metadata.get('original_text', document.page_content), 'content': document.page_content,
            'law_name': metadata['law_name'], 'law_type': metadata['law_type'],
            'law_family': metadata['law_family'], 'article_number': metadata['article_number'],
            'article_title': metadata['article_title'], 'kind': metadata['kind'],
            'effective_date': metadata['effective_date'], 'publication': metadata['publication'],
            'source_url': metadata['source_url'], 'source_url_type': 'law_name_lookup',
            'validity_status': 'not_verified', 'review_note': metadata['review_note'],
            'expanded': expanded, 'expanded_from': expanded_from,
            'rank': None if expanded else candidate_rank,
            'rrf_score': None if expanded else origin['rrf_score'],
            'keyword_rank': None if expanded else origin['keyword_rank'],
            'vector_rank': None if expanded else origin['vector_rank'],
        }
        source.update({
            '법령명': source['law_name'], '법령종류': source['law_type'],
            '조문': source['article_number'], '조문제목': source['article_title'],
            'PDF표제시행일': source['effective_date'], '파일명': source['filename'],
            '페이지': source['pages'], '페이지범위설명': metadata['page_scope'],
            '공식조회URL': source['source_url'], '검토사항': source['review_note'],
            '확장': expanded, '확장원본': expanded_from, '검색순위': source['rank'],
            'RRF점수': source['rrf_score'], 'BM25순위': source['keyword_rank'],
            '벡터순위': source['vector_rank'], '원문': source['text'],
        })
        used_ids.add(cid)
        context_parts.append(part)
        sources.append(source)

    # 후보 조문들의 직접 검색 근거를 우선 넣은 후 주변 조문 청크를 추가합니다.
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        add(cid, candidate_rank)
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        if cid not in used_ids:
            continue
        original = chunks[cid].metadata
        related = [
            doc for doc in allowed_docs
            if doc.metadata['article_id'] == original['article_id']
            and doc.metadata['chunk_id'] != cid
        ]
        related.sort(key=lambda doc: abs(doc.metadata['part'] - original['part']))
        for document in related:
            add(document.metadata['chunk_id'], candidate_rank, expanded_from=cid)
    hits = []
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        metadata = chunks[cid].metadata
        hits.append({
            **rows_by_id[cid], 'rank': candidate_rank,
            'law_name': metadata['law_name'], 'law_type': metadata['law_type'],
            'article_number': metadata['article_number'], 'article_title': metadata['article_title'],
            'effective_date': metadata['effective_date'], 'validity_status': 'not_verified',
            'result_type': 'institutional_reference', 'review_note': metadata['review_note'],
            'context_evidence_ids': [row['chunk_id'] for row in sources if row['article_id'] == metadata['article_id']],
        })
    status = 'ok' if sources else ('context_limit' if ranking else 'no_matches')
    return {
        'question': query, 'context': '\n\n'.join(context_parts), 'sources': sources,
        'hits': hits, 'ranking': ranking_rows, 'status': status,
        'result_type': 'institutional_reference', 'filters': filters,
        'context_truncated': bool(skipped_ids), 'omitted_context_ids': sorted(skipped_ids),
        'diagnostics': {
            'failed_files': index.get('failed_files', []),
            'review_list': index.get('review_list', []),
            'excluded_section_count': len(index.get('excluded_sections', [])),
        },
    }
