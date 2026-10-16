"""Fresh technology LoRA experiment against a current read-only DB snapshot."""
import argparse
from pathlib import Path

from app.scripts.retrain_rfp_embedding import ROOT, read, dump, digest, lines, write_lines, normalize, run

OLD=ROOT/'data/experiments/technology_embedding_split'
DEFAULT_OUTPUT=ROOT/'data/experiments/technology_embedding_rerun_20261016'


def prepare(output):
    from app.technology_rag.config import load_config
    from app.technology_rag.schemas import TechDocument
    from app.technology_rag.indexing.chunker import get_chunker
    output=Path(output)
    if (output/'preparation.json').exists() or (output/'corpus.jsonl').exists():
        raise FileExistsError('Existing experiment files will not be overwritten')
    source=output/'source_snapshot'
    documents=read(source/'documents.json')
    chunks=read(source/'chunks.json')
    if any(x['corpus_id']!='technology' for x in documents+chunks):
        raise ValueError('Not a technology snapshot')
    cfg=load_config()
    regenerated=get_chunker(cfg.chunking.strategy,include_title_prefix=cfg.chunking.include_title_prefix).chunk_all(
        [TechDocument.model_validate(d['payload']) for d in documents])
    expected={c['chunk_id']:c['content'] for c in chunks}
    if len(expected)!=len(chunks) or expected!={c.chunk_id:c.text for c in regenerated}:
        raise ValueError('Current chunking and production corpus differ; review inputs before training')
    corpus=lines(OLD/'corpus.jsonl')
    if expected!={c['chunk_id']:c['text'] for c in corpus}:
        raise ValueError('Corpus changed; training/test labels require review before reuse')
    old_docs=read(OLD/'source_snapshot/documents.json')
    if {d['document_id']:d['full_text'] for d in documents}!={d['document_id']:d['full_text'] for d in old_docs}:
        raise ValueError('Original document text changed')
    byid={c['chunk_id']:c for c in corpus}
    bydoc={d['document_id']:d for d in documents}
    split={c['document_id']:c['split'] for c in corpus}
    windows=lines(OLD/'results/lora_pilot_v1/training_windows.jsonl')
    draft_path=OLD/'synthetic_draft_v1/train/questions.draft.json'
    drafts={q['query_id']:q for q in read(draft_path)}
    for w in windows:
        q=drafts[w['query_id']]; positive=byid[w['positive_chunk_id']]
        if q['query']!=w['query'] or positive['document_id'] not in q['relevant_document_ids']:
            raise ValueError('Training labels changed')
        if any(byid[c]['split']!='train' for c in [w['positive_chunk_id']]+w['negative_chunk_ids']):
            raise ValueError('Non-training chunk in gradient data')
        if any(byid[c]['group_id']==positive['group_id'] for c in w['negative_chunk_ids']):
            raise ValueError('Positive family used as negative')
        if not any(e['document_id']==positive['document_id'] and normalize(e['text']) in normalize(positive['text']) for e in q['evidence']):
            raise ValueError('Positive evidence absent')
        for cid in w['negative_chunk_ids']:
            if not any(n['chunk_id']==cid and normalize(n['quote']) in normalize(byid[cid]['text']) for n in q['negative_candidates']):
                raise ValueError('Negative evidence absent')
    ids={q['query_id'] for q in read(OLD/'results/lora_pilot_v1/validation_base.json')['results']}
    validation=[q for q in read(OLD/'synthetic_draft_v1/validation/questions.draft.json') if q['query_id'] in ids]
    if len(validation)!=len(ids): raise ValueError('Validation IDs changed')
    test=read(OLD/'test/questions.json')
    expanded=read(OLD/'test/expanded_v1/questions.json')
    for name,questions in [('validation',validation),('test',test),('test',expanded)]:
        if len({q['query_id'] for q in questions})!=len(questions): raise ValueError('Duplicate question IDs')
        for q in questions:
            if not q['query'].strip() or not q['relevant_document_ids'] or any(split.get(i)!=name for i in q['relevant_document_ids']):
                raise ValueError('Question outside declared split')
            for e in q['evidence']:
                d=bydoc[e['document_id']]
                if normalize(e['text']) not in normalize(d['full_text']): raise ValueError('Question evidence absent')
                page=e.get('pdf_page')
                if page is not None and not any(b['page']+1==page and normalize(e['text']) in normalize(s['text'])
                     for s in d['payload']['sections'] for b in s.get('blocks',[])):
                    raise ValueError('Evidence PDF page mismatch')
    current_hashes={str((source/name).relative_to(ROOT)):digest(source/name) for name in ('documents.json','chunks.json','corpus_payload.json')}
    source_files=[OLD/'corpus.jsonl',OLD/'manifest.json',OLD/'source_snapshot/documents.json',
        OLD/'results/lora_pilot_v1/training_windows.jsonl',draft_path,
        OLD/'synthetic_draft_v1/validation/questions.draft.json',OLD/'test/questions.json',
        OLD/'test/expanded_v1/questions.json',OLD/'test/expanded_v1/review_flags.json',
        OLD/'results/lora_pilot_v1/adapter_epoch_2/adapter_model.safetensors']
    hashes={str(p.relative_to(ROOT)):digest(p) for p in source_files}
    hashes.update(current_hashes)
    write_lines(output/'corpus.jsonl',corpus)
    write_lines(output/'training_windows.jsonl',windows)
    dump(output/'validation_questions.json',validation)
    dump(output/'test_questions.json',test)
    dump(output/'expanded_questions.json',expanded)
    # Do not merge same-family documents or change previously fixed relevance labels.
    dump(output/'equivalent_tasks.json',[])
    dump(output/'label_review_flags.json',read(OLD/'test/expanded_v1/review_flags.json'))
    dump(output/'preparation.json',dict(current_chunks_rebuilt=True,current_db_read_only_snapshot=True,
        corpus_identical_to_previous=True,documents=len(documents),chunks=len(chunks),train=len(windows),
        validation=len(validation),original_test=len(test),expanded_test=len(expanded),source_sha256=hashes,
        reused_synthetic_training_labels=True,human_reviewed_training_labels=False,
        uses_rfp_data_or_adapter=False,supabase_modified=False,labels_modified=False,
        known_missing_positive_review_cases=len(read(output/'label_review_flags.json'))))
    print('PREPARED',len(documents),len(chunks),len(windows),len(validation),len(expanded),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['prepare','train','evaluate'])
    p.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    p.add_argument('--seed',type=int,default=20261016)
    args=p.parse_args()
    if args.stage=='prepare':
        prepare(args.output)
    else:
        run(args.output,args.seed,args.stage,
            previous_adapter=OLD/'results/lora_pilot_v1/adapter_epoch_2',corpus_label='기술나눔')
