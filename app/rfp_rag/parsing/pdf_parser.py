"""PDF block extraction and task/requirement parsing."""
import hashlib
import json
import re
from .notices import _source_key

def load_documents(data_dir, OUTPUT, pdf_files, document_factory):
    import pymupdf
    import pdfplumber
    Document = document_factory
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
            cache_path = cache_dir / (hashlib.sha256(('rfp-loader-v6' + file_hash).encode()).hexdigest() + '.json')
            recovered_cache=cache_dir/(hashlib.sha256(('rfp-loader-v7'+file_hash).encode()).hexdigest()+'.json')
            recovered=recovered_cache.exists()
            if recovered:
                cache_path=recovered_cache
            if cache_path.exists():
                cached = json.loads(cache_path.read_text(encoding='utf-8'))
                loaded = [Document(page_content=d['text'], metadata={**d['metadata'], 'source': _source_key(pdf_path, data_dir), 'filename': pdf_path.name, 'document_id': hashlib.sha256((_source_key(pdf_path, data_dir) + file_hash).encode()).hexdigest()[:24]}) for d in cached['blocks']]
                issues.extend(({**i, 'filename': pdf_path.name} for i in cached['issues']))
            else:
                with pdfplumber.open(pdf_path) as pdf:
                    for page_number, page in enumerate(pdf.pages, 1):
                        before = len(page.chars)
                        page = page.dedupe_chars(tolerance=1,extra_attrs=())
                        if len(page.chars)<before:
                            issues.append({'filename':pdf_path.name,'page':page_number,
                                           'reason':'좌표가 겹친 동일 문자 제거','removed_chars':before-len(page.chars)})
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
                            if label not in {'품목명', '과제명', '프로젝트명', 'RFP명', '관리번호', '과제번호',
                                             '품목번호','총괄품목명','세부품목명','세부과제명'}:
                                continue
                            if any(len([v for v in d.metadata.get('cells',[]) if str(v).strip()])>=2
                                   and re.sub(r'\s+','',next((v for v in d.metadata.get('cells',[]) if str(v).strip()),'')).endswith(label)
                                   for _,d in blocks):
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
                cache_path.write_text(json.dumps({'loader': 'rfp-loader-v6', 'file_hash': file_hash, 'blocks': [{'text': d.page_content, 'metadata': d.metadata} for d in loaded], 'issues': issues}, ensure_ascii=False, indent=2), encoding='utf-8')
            if not recovered:
                from .layout_recovery import recover_layout
                loaded=recover_layout(pdf_path,loaded,issues,Document)
                recovered_cache.write_text(json.dumps({'loader':'rfp-loader-v7','file_hash':file_hash,
                    'blocks':[{'text':d.page_content,'metadata':d.metadata} for d in loaded],
                    'issues':issues},ensure_ascii=False,indent=2),encoding='utf-8')
            loaded_docs.extend(loaded)
            review_list.extend(issues)
        except Exception as error:
            failed_files.append({'filename': pdf_path.name, 'reason': str(error)})
    return loaded_docs, review_list, failed_files


from .task_parser import parse_tasks
