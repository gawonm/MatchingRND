"""Local PDF -> tasks -> chunks -> review report. No embeddings or database writes."""
import argparse
import hashlib
import json
import time
import marshal
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.common.paths import PROJECT_ROOT, RFP_RAW_DIR
from app.common.supabase_ingestion import pack
from .parsing.pdf_parser import load_documents,parse_tasks
from .indexing.chunker import build_chunks


def preprocess(data_dir=RFP_RAW_DIR,output_dir=None,workers=2):
    from langchain_core.documents import Document
    from transformers import AutoTokenizer
    from app.common.embedding import MODEL
    import pymupdf
    root=Path(data_dir).resolve()
    target=Path(output_dir or PROJECT_ROOT/'data/processed/rfp').resolve()
    target.mkdir(parents=True,exist_ok=True)
    (target/'files').mkdir(exist_ok=True)
    tokenizer=AutoTokenizer.from_pretrained(MODEL,local_files_only=True)
    files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower()=='.pdf')
    if not files:
        raise ValueError(f'PDF가 없습니다: {root}')
    started=time.perf_counter()
    from .parsing.layout_recovery import recover_layout
    pipeline_version=hashlib.sha256(marshal.dumps((load_documents.__code__,parse_tasks.__code__,build_chunks.__code__,recover_layout.__code__,preprocess.__code__))).hexdigest()

    def process(path):
        blocks,issues,failed=load_documents(root,PROJECT_ROOT/'db/rfp',[path],Document)
        tasks,issues,excluded=parse_tasks(blocks,[path],root,issues,Document)
        links={task['source']:[] for task in tasks}
        chunks,_=build_chunks(tasks,links,tokenizer,1400,100,Document)
        audits=[i for i in issues if i.get('audit')]
        records=audits[0]['blocks'] if audits else []
        source_text={r['block_id']:r['text'] for r in records}
        fragment_ids={fragment.metadata['block_id'] for task in tasks for fs in task['fields'].values()
                      for fragment in fs}
        chunk_block_ids={s['block_id'] for chunk in chunks for s in chunk.metadata['sources']}
        missing=sorted(fragment_ids-chunk_block_ids)
        bad_quotes=[]
        for task in tasks:
            for fs in task['fields'].values():
                for fragment in fs:
                    raw=source_text.get(fragment.metadata['block_id'],'')
                    if ''.join(fragment.page_content.split()) not in ''.join(raw.split()):
                        bad_quotes.append(fragment.metadata['block_id'])
        try:
            with pymupdf.open(path) as pdf:
                page_count=len(pdf)
        except Exception:
            page_count=None
        marked_pages={i.get('page') for i in issues if i.get('page')}
        text_pages={b.metadata['page'] for b in blocks}
        unaccounted_pages=sorted(set(range(1,(page_count or 0)+1))-text_pages-marked_pages)
        unresolved=[i for i in issues if not i.get('audit') and '좌표가 겹친' not in i['reason']
                    and '표 추출에서 누락된 단어 좌표 복원' not in i['reason']]
        quarantined=[r for r in records if r['role']=='quarantine']
        suspect_context=[r['block_id'] for r in records if r['role']=='context' and
                         any(word in ''.join(r['text'].split()) for word in ('개발내용','요구기술','세부품목명','과제번호','품목번호'))]
        parent_ids={task['task_id'] for task in tasks}
        orphan_children=[task['task_id'] for task in tasks if task.get('parent_task_id') and task['parent_task_id'] not in parent_ids]
        status='failed' if failed else 'review_required' if excluded or missing or bad_quotes or unaccounted_pages or quarantined or unresolved or orphan_children or suspect_context else 'automatic_checks_passed'
        summary=dict(filename=path.name,source=str(path.relative_to(root)),file_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            pages=page_count,tasks=len(tasks),chunks=len(chunks),raw_blocks=len(blocks),status=status,
            duplicate_chars_removed=sum(i.get('removed_chars',0) for i in issues),
            unmatched_context_blocks=sum(r['role']=='context' for r in records),quarantined_blocks=len(quarantined),
            missing_chunk_blocks=missing,invalid_source_quotes=sorted(set(bad_quotes)),
            unaccounted_pages=unaccounted_pages,orphan_children=orphan_children,review_issue_count=len(unresolved))
        summary['suspect_context_blocks']=suspect_context
        summary['pipeline_version']=pipeline_version
        key=hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:24]
        detail=dict(summary=summary,tasks=pack(tasks),chunks=pack(chunks),issues=issues,failed=failed)
        (target/'files'/f'{key}.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2),encoding='utf-8')
        summary['detail_file']=f'files/{key}.json'
        print(f"[{summary['status']}] {path.name}: 과제 {len(tasks)}, 청크 {len(chunks)}",flush=True)
        return summary,tasks,chunks

    summaries,all_tasks,all_chunks=[],[],[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for summary,tasks,chunks in pool.map(process,files):
            summaries.append(summary)
            all_tasks.extend(tasks)
            all_chunks.extend(chunks)
    manifest=dict(pdf_count=len(files),task_count=len(all_tasks),chunk_count=len(all_chunks),
                  statuses=dict(Counter(s['status'] for s in summaries)),seconds=round(time.perf_counter()-started,2),
                  unique_file_hashes=len({s['file_hash'] for s in summaries}),files=summaries,
                  pipeline_version=pipeline_version,
                  note='자동 검수 통과는 의미적 과제 연결의 완전성을 보장하지 않습니다. review_required의 상세 기록을 확인하세요.')
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (target/'tasks.json').write_text(json.dumps(pack(all_tasks),ensure_ascii=False),encoding='utf-8')
    (target/'chunks.json').write_text(json.dumps(pack(all_chunks),ensure_ascii=False),encoding='utf-8')
    lines=['# RFP 로컬 전처리 검수','',f'PDF {len(files)}개 / 과제 {len(all_tasks)}개 / 청크 {len(all_chunks)}개','',
           '| 파일 | 상태 | 과제 | 청크 | 검수 기록 |','|---|---|---:|---:|---|']
    for s in summaries:
        lines.append(f"| {s['filename'].replace('|','/')} | {s['status']} | {s['tasks']} | {s['chunks']} | [상세]({s['detail_file']}) |")
    (target/'review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',default=str(RFP_RAW_DIR))
    parser.add_argument('--output-dir')
    parser.add_argument('--workers',type=int,choices=range(1,5),default=2)
    args=parser.parse_args()
    manifest=preprocess(args.data_dir,args.output_dir,args.workers)
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
