"""Compose law parsing, chunking and reusable search indexes."""
import hashlib
import re
from ..config import load_config
from ..parsing.pdf_parser import load_documents, parse_articles
from .chunker import build_chunks

def build_index(data_dir=None, output_dir=None, *, model_name=None,
                local_files_only=True):
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
    MODEL = config['MODEL']
    CHUNK_TOKENS = config['CHUNK_TOKENS']
    OVERLAP_TOKENS = config['OVERLAP_TOKENS']
    KEYWORD_K = config['KEYWORD_K']
    VECTOR_K = config['VECTOR_K']
    TOP_K = config['TOP_K']
    RRF_K = config['RRF_K']
    CONTEXT_TOKENS = config['CONTEXT_TOKENS']
    raw_documents, review_list, failed_files = load_documents(data_dir, OUTPUT, pdf_files)
    articles, review_list, excluded_sections = parse_articles(raw_documents, review_list, Document)
    if not articles:
        raise ValueError('조문 추출 결과를 확인하세요.')
    embedding = HuggingFaceEmbeddings(model_name=MODEL, model_kwargs={'device': 'cpu', 'local_files_only': local_files_only}, encode_kwargs={'normalize_embeddings': True})
    tokenizer = embedding._client.tokenizer
    token_limit = min(CHUNK_TOKENS, embedding._client.max_seq_length - 2)
    if token_limit <= 0 or OVERLAP_TOKENS >= token_limit:
        raise ValueError('조문 청크 길이와 겹침 토큰 설정을 확인하세요.')
    docs, chunks_by_id = build_chunks(articles, tokenizer, token_limit, OVERLAP_TOKENS, Document)
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
