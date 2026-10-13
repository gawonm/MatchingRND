"""PDF block extraction and task/requirement parsing."""
import hashlib
import json
import re
from collections import Counter, defaultdict
from ..config import TECHNICAL_SECTIONS
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
    return loaded_docs, review_list, failed_files

def parse_tasks(loaded_docs, pdf_files, data_dir, review_list, document_factory):
    Document = document_factory
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
    return tasks, review_list, excluded_files
