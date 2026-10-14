"""Apply source-bound review decisions before indexing or database ingestion.

Raw extraction remains in the audit. Held tasks and ambiguous metric regions
never reach search, context expansion, or the structured task payload.
"""
import copy
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from app.common.paths import PROJECT_ROOT

POLICY_PATH = Path(__file__).with_name('review_decisions.json')
INFORMATIONAL = ('좌표가 겹친 동일 문자 제거', '표 추출에서 누락된 단어 좌표 복원')


def compact(text):
    return re.sub(r'\s+', '', text)


def _overlaps(a, b):
    if not a or not b:
        return False
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _replacement_task(spec, template, audit, document_factory):
    """A reviewed page range, never a guessed cross-task attachment."""
    task = copy.deepcopy(template)
    task.update(title=spec['title'], task_number=spec.get('task_number', ''),
                task_type='standalone', parent_task_id=None, parent_title=None,
                subtask_number=None, metrics=[], status='parsed')
    task['task_id'] = hashlib.sha256((task['document_id'] + json.dumps(spec, sort_keys=True,
                                    ensure_ascii=False)).encode()).hexdigest()[:24]
    task['boundary_pages'] = [spec['page_start']]
    task['fields'] = defaultdict(list)
    records = [r for r in audit['blocks'] if spec['page_start'] <= r['page'] <= spec['page_end']]
    proof = next((r for r in records if compact(spec['title']) in compact(r['text'])), None)
    if not proof:
        raise ValueError('검수 제목의 원문 근거가 없습니다: ' + task['filename'])
    task['title_source'] = {'text': proof['text'], 'metadata': {'page': proof['page'],
                            'bbox': proof['bbox'], 'source': task['source']}}
    # Preserve the original text and location without interpreting merged columns.
    from .parsing.task_parser import SECTIONS, key
    field = '기타 원문'
    for r in records:
        if re.fullmatch(r'[-–—]?\s*\d+\s*[-–—]?', r['text'].strip()):
            continue
        for line in r['text'].splitlines():
            heading = key(line.split('|')[0].split(':')[0])
            detected = next((name for name, pattern in SECTIONS if re.match(pattern, heading)), None)
            if detected:
                field = detected
            if spec.get('content_field'):
                field = spec['content_field']
            task['fields'][field].append(document_factory(page_content=line, metadata={
                'kind': 'text', 'page': r['page'], 'bbox': r['bbox'], 'block_id': r['block_id'],
                **{k: task[k] for k in ('source', 'filename', 'file_hash', 'document_id')},
                'reviewed_page_range': True}))
    return task


def apply_review(tasks, issues, data_dir, document_factory, policy_path=POLICY_PATH):
    policy = json.loads(Path(policy_path).read_text(encoding='utf-8')) if Path(policy_path).exists() else {'files': {}}
    decisions = policy.get('files', {})
    audits = {i['filename']: i for i in issues if i.get('audit')}
    grouped = defaultdict(list)
    for task in tasks:
        grouped[task['filename']].append(copy.deepcopy(task))
    approved, outcomes = [], []
    for filename, file_tasks in grouped.items():
        audit = audits.get(filename, {})
        related = [i for i in issues if i.get('filename') == filename and not i.get('audit')]
        meaningful = [i for i in related if i['reason'] not in INFORMATIONAL]
        decision = decisions.get(filename)
        if decision and decision['file_hash'] != file_tasks[0]['file_hash']:
            raise ValueError('원본이 변경되어 재검수가 필요합니다: ' + filename)
        if decision:
            action = decision['action']
        else:
            # Only unambiguous automatic cases are eligible without a manual decision.
            suspect = [r for r in audit.get('blocks', []) if r['role'] == 'context' and
                       any(w in compact(r['text']) for w in ('개발내용', '요구기술', '세부품목명', '과제번호', '품목번호'))]
            ambiguous = meaningful or audit.get('quarantine_blocks') or suspect
            action = 'hold' if ambiguous else 'approve'
            decision = {'reason': '미검수 원문 보류' if ambiguous else '자동 구조 검사 통과'}
        if action in {'hold', 'exclude'}:
            outcomes.append({'filename': filename, 'status': 'hold', 'reason': decision['reason'],
                             'held_tasks': len(file_tasks), 'approved_tasks': 0})
            continue
        if action != 'approve':
            raise ValueError('알 수 없는 검수 판정: ' + action)
        if decision.get('replacement_tasks'):
            file_tasks = [_replacement_task(spec, file_tasks[0], audit, document_factory)
                          for spec in decision['replacement_tasks']]
        by_id = {t['task_id']: t for t in file_tasks}
        referenced = set(decision.get('titles', {})) | set(decision.get('task_types', {})) | set(decision.get('hold_tasks', []))
        referenced |= set(decision.get('merge_tasks', {})) | set(decision.get('merge_tasks', {}).values())
        if referenced - by_id.keys():
            raise ValueError('과제 파싱 결과가 변경되어 재검수가 필요합니다: ' + filename)
        for source_id, target_id in decision.get('merge_tasks', {}).items():
            source, target = by_id[source_id], by_id[target_id]
            for field, fragments in source['fields'].items():
                target['fields'].setdefault(field, []).extend(fragments)
            target['metrics'].extend(source['metrics'])
            del by_id[source_id]
        file_tasks = list(by_id.values())
        for task in file_tasks:
            replacement = decision.get('titles', {}).get(task['task_id'])
            if replacement:
                proof = decision.get('title_proofs', {}).get(task['task_id'], replacement)
                if not any(compact(proof) in compact(r['text']) for r in audit.get('blocks', [])):
                    raise ValueError('검수 제목의 원문 근거가 없습니다: ' + filename)
                task['title_before_review'] = task['title']
                task['title'] = replacement
                task['title_review_proof'] = proof
            if task['task_id'] in decision.get('task_types', {}):
                task['task_type'] = decision['task_types'][task['task_id']]
                task['parent_task_id'] = None
                task['parent_title'] = None
        titles_by_id = {t['task_id']: t['title'] for t in file_tasks}
        for task in file_tasks:
            if task.get('parent_task_id'):
                task['parent_title'] = titles_by_id.get(task['parent_task_id'], task.get('parent_title'))
        metric_pages = {i['page'] for i in related if i['reason'] == '병합 성능표 헤더 확인 필요'}
        regions = defaultdict(list)
        for task in file_tasks:
            for fragments in task['fields'].values():
                for fragment in fragments:
                    meta = fragment.metadata
                    if meta['page'] in metric_pages and meta['kind'] == 'metric_table':
                        regions[meta['page']].append(meta.get('bbox'))
        held_ids = set(decision.get('hold_tasks', []))
        # Include descendants in the held set, even for nested relations.
        while True:
            descendants = {t['task_id'] for t in file_tasks if t.get('parent_task_id') in held_ids}
            if descendants <= held_ids:
                break
            held_ids.update(descendants)
        held = 0
        removed = 0
        for task in file_tasks:
            if task['task_id'] in held_ids:
                held += 1
                continue
            # A child cannot claim a held parent as an eligible structured relation.
            if task.get('parent_task_id') in held_ids:
                held += 1
                continue
            for field, fragments in list(task['fields'].items()):
                safe = []
                for fragment in fragments:
                    meta = fragment.metadata
                    unsafe = meta['page'] in metric_pages and (
                        meta['kind'] == 'metric_table' or field == '성능지표' or
                        any(_overlaps(meta.get('bbox'), box) for box in regions[meta['page']]))
                    if unsafe:
                        removed += 1
                    else:
                        safe.append(fragment)
                task['fields'][field] = safe
            task['metrics'] = [metric for metric in task['metrics'] if metric.get('page') not in metric_pages]
            if not any(task['fields'].values()):
                held += 1
                continue
            task['review'] = {'status': 'approved_with_metric_hold' if metric_pages else 'approved',
                              'reason': decision['reason'], 'unverified_metric_pages': sorted(metric_pages),
                              'excluded_context_pages': decision.get('excluded_context_pages', []),
                              'file_hash': task['file_hash']}
            approved.append(task)
        outcomes.append({'filename': filename, 'status': 'partially_approved' if held or removed else 'approved',
                         'reason': decision['reason'], 'approved_tasks': len(file_tasks) - held,
                         'held_tasks': held, 'excluded_metric_fragments': removed,
                         'unverified_metric_pages': sorted(metric_pages)})
    return approved, outcomes


def build_reviewed_artifacts(input_dir, output_dir):
    """Export exactly the tasks/chunks eligible for ingestion, with source hashes."""
    from langchain_core.documents import Document
    from transformers import AutoTokenizer
    from app.common.embedding import MODEL
    from app.common.supabase_ingestion import pack, unpack
    from .indexing.chunker import build_chunks
    source, target = Path(input_dir), Path(output_dir)
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    tasks, issues = [], []
    for summary in manifest['files']:
        path = PROJECT_ROOT / 'data/raw/rfp' / summary['source']
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != summary['file_hash']:
            raise ValueError('전처리 후 원본이 변경 또는 삭제되었습니다: ' + summary['filename'])
        detail = json.loads((source / summary['detail_file']).read_text(encoding='utf-8'))
        tasks.extend(unpack(detail['tasks']))
        issues.extend(detail['issues'])
    eligible, outcomes = apply_review(tasks, issues, PROJECT_ROOT / 'data/raw/rfp', Document)
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    chunks, _ = build_chunks(eligible, {t['source']: [] for t in eligible}, tokenizer, 1400, 100, Document)
    target.mkdir(parents=True, exist_ok=True)
    (target / 'tasks.json').write_text(json.dumps(pack(eligible), ensure_ascii=False), encoding='utf-8')
    (target / 'chunks.json').write_text(json.dumps(pack(chunks), ensure_ascii=False), encoding='utf-8')
    result = {'input_pdfs': manifest['pdf_count'], 'approved_tasks': len(eligible), 'chunks': len(chunks),
              'held_tasks': sum(o['held_tasks'] for o in outcomes), 'files': outcomes}
    (target / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# RFP 검수 적용 결과', '', '미확인 과제와 병합 성능표는 검색·답변 근거에서 제외했습니다. 원문과 추출 감사 기록은 유지합니다.', '',
             f"입력 PDF {manifest['pdf_count']}개 / 사용 과제 {len(eligible)}개 / 보류 과제 {result['held_tasks']}개 / 청크 {len(chunks)}개", '',
             '| 파일 | 판정 | 사용 과제 | 보류 과제 | 사유 |', '|---|---|---:|---:|---|']
    for o in outcomes:
        lines.append(f"| {o['filename']} | {o['status']} | {o['approved_tasks']} | {o['held_tasks']} | {o['reason']} |")
    (target / 'review.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', default=str(PROJECT_ROOT / 'data/processed/rfp/validated'))
    parser.add_argument('--output-dir', default=str(PROJECT_ROOT / 'data/processed/rfp/approved'))
    args = parser.parse_args()
    result = build_reviewed_artifacts(args.input_dir, args.output_dir)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, ensure_ascii=False, indent=2))
