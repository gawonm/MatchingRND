"""Article chunking with exact source spans and stable IDs."""
import hashlib
from app.common.chunking import _split_with_prefix

def build_chunks(articles, tokenizer, token_limit, OVERLAP_TOKENS, document_factory):
    Document = document_factory
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
    return docs, chunks_by_id
