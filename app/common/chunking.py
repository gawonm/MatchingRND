"""Token-budget splitting shared by PDF RAG modules."""

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
