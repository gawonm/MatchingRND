"""Pack parsed task fields into token-budgeted chunks with source locations."""
import hashlib
from app.common.chunking import _split_with_prefix

def build_chunks(tasks, file_notice_ids, tokenizer, token_limit, OVERLAP_TOKENS, document_factory):
    Document = document_factory
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
    return docs, chunks_by_id
