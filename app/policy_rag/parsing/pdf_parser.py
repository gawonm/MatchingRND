"""Law PDF extraction and article boundary parsing."""
import hashlib
import json
import re
from collections import Counter
from urllib.parse import quote

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

def load_documents(data_dir, OUTPUT, pdf_files):
    import pymupdf
    root = data_dir
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
    return raw_documents, review_list, failed_files

def parse_articles(raw_documents, review_list, document_factory):
    Document = document_factory
    articles = []
    excluded_sections = []
    for raw in raw_documents:
        extracted, reviews, excluded = _extract_articles(raw, Document)
        articles.extend(extracted)
        review_list.extend(reviews)
        excluded_sections.extend(excluded)
    return articles, review_list, excluded_sections
