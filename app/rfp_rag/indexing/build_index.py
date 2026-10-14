"""Compose parsing, chunking, embeddings and reusable search indexes."""
import hashlib
import re
import json
from ..config import load_config
from ..parsing.notices import _load_notices
from ..parsing.pdf_parser import load_documents, parse_tasks
from .chunker import build_chunks

def build_index(data_dir=None, output_dir=None, *, model_name=None,
                local_files_only=True, notice_path=None):
    """PDF를 처리해 재사용 가능한 검색 인덱스와 검토 목록을 반환합니다.

    data_dir와 output_dir는 절대 경로나 프로젝트 기준 상대 경로입니다.
    모델은 기본적으로 로컬 캐시를 사용하며 출력 폴더에는 추출 캐시와
    Chroma 인덱스만 저장합니다. 입력 PDF가 없으면 ValueError를 발생시킵니다.
    """
    from langchain_core.documents import Document
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma
    from langchain_community.retrievers import BM25Retriever
    from kiwipiepy import Kiwi
    config = load_config(data_dir, output_dir, model_name=model_name)
    data_dir = config['data_dir']
    OUTPUT = config['OUTPUT']
    pdf_files = config['pdf_files']
    EMBEDDING_MODEL = config['EMBEDDING_MODEL']
    CHUNK_TOKENS = config['CHUNK_TOKENS']
    OVERLAP_TOKENS = config['OVERLAP_TOKENS']
    KEYWORD_K = config['KEYWORD_K']
    VECTOR_K = config['VECTOR_K']
    TOP_K = config['TOP_K']
    RRF_K = config['RRF_K']
    CONTEXT_TOKENS = config['CONTEXT_TOKENS']
    notices, file_notice_ids, matching_issues = _load_notices(data_dir, pdf_files, notice_path)
    loaded_docs, review_list, failed_files = load_documents(data_dir, OUTPUT, pdf_files, Document)
    tasks, review_list, excluded_files = parse_tasks(loaded_docs, pdf_files, data_dir, review_list, Document)
    from ..review import apply_review
    tasks, review_outcomes = apply_review(tasks, review_list, data_dir, Document)
    # Full block accounting belongs in the local audit, not repeated in every search hit.
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'source_audit.json').write_text(json.dumps([row for row in review_list if row.get('audit')],
        ensure_ascii=False,indent=2),encoding='utf-8')
    review_list=[{key:value for key,value in row.items() if key!='blocks'} for row in review_list]
    if not tasks:
        raise ValueError(f'구조가 확인된 RFP 과제가 없습니다. 추출 실패 {len(failed_files)}개, 검토 제외 {len(excluded_files)}개를 확인하세요.')
    embedding = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL, model_kwargs={'device': 'cpu', 'local_files_only': local_files_only}, encode_kwargs={'normalize_embeddings': True})
    tokenizer = embedding._client.tokenizer
    token_limit = min(CHUNK_TOKENS, embedding._client.max_seq_length - 2)
    if token_limit <= 0 or OVERLAP_TOKENS >= token_limit:
        raise ValueError('RFP 청크 길이와 겹침 토큰 설정을 확인하세요.')
    docs, chunks_by_id = build_chunks(tasks, file_notice_ids, tokenizer, token_limit, OVERLAP_TOKENS, Document)
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
    return {'docs': docs, 'chunks_by_id': chunks_by_id, 'dataset': dataset, 'tasks': tasks, 'tasks_by_id': {task['task_id']: task for task in tasks}, 'excluded_files': excluded_files, 'matching_issues': matching_issues, 'tokenizer': tokenizer, 'max_query_tokens': max_query_tokens, 'vectorstore': vectorstore, 'dense': dense, 'bm25': bm25, 'kiwi_tokenize': kiwi_tokenize, 'review_list': review_list, 'review_outcomes': review_outcomes, 'failed_files': failed_files, 'KEYWORD_K': KEYWORD_K, 'VECTOR_K': VECTOR_K, 'TOP_K': TOP_K, 'RRF_K': RRF_K, 'CONTEXT_TOKENS': CONTEXT_TOKENS}
