"""Prepare strict NTIS source windows and run a first local LoRA comparison."""
import argparse
from pathlib import Path

from app.scripts.retrain_rfp_embedding import ROOT,MODEL,REVISION,read,dump,digest,lines,write_lines,normalize,run
from app.scripts.prepare_ntis_training_data import SOURCE,OUTPUT,anchors


def clean_validation(train,validation,documents):
    """Exclude whole validation projects sharing exact queries or long anchors.

    This rule uses source text only, never retrieval ranks or Test contents.
    """
    train_queries={normalize(q['query']) for q in train}
    train_ids={i for q in train for i in q['relevant_document_ids']}
    source_keys={}
    for i in train_ids:
        for a in anchors(documents[i]):
            key=normalize(a['text'])
            if len(key)>=100:source_keys.setdefault(key,set()).add(i)
    removed={}
    for q in validation:
        for i in q['relevant_document_ids']:
            matches={j for a in anchors(documents[i]) for j in source_keys.get(normalize(a['text']),set())}
            same_query=normalize(q['query']) in train_queries
            if matches or same_query:
                removed[i]=dict(document_id=i,matching_train_document_ids=sorted(matches),
                    exact_query_overlap=same_query or removed.get(i,{}).get('exact_query_overlap',False),
                    reason='exact shared query or long source research anchor; project excluded from pilot Validation')
    kept=[q for q in validation if not set(q['relevant_document_ids'])&set(removed)]
    return kept,list(removed.values())


def window(text,title,quote,tokenizer,limit=384):
    """Keep the actual evidence span within the training budget, not a blind prefix."""
    start=text.find(quote)
    if start<0: raise ValueError('Evidence absent from chunk')
    prefix=title+'\n'
    budget=limit-len(tokenizer.encode(prefix,add_special_tokens=False))-12
    encoded=tokenizer(text,add_special_tokens=False,return_offsets_mapping=True)
    offsets=encoded['offset_mapping']
    first=next(i for i,(_,end) in enumerate(offsets) if end>start)
    last=max(i for i,(begin,_) in enumerate(offsets) if begin<start+len(quote))
    if last-first+1>budget: raise ValueError('Evidence exceeds training window budget')
    left=max(0,first-(budget-(last-first+1))//2)
    right=min(len(offsets),left+budget)
    left=max(0,right-budget)
    value=prefix+text[offsets[left][0]:offsets[right-1][1]]
    if quote not in value or len(tokenizer.encode(value))>limit:
        raise ValueError('Evidence lost from bounded window')
    return value


def prepare(output=OUTPUT):
    from dotenv import load_dotenv
    from transformers import AutoTokenizer
    load_dotenv(ROOT/'.env')
    output=Path(output)
    if (output/'preparation.json').exists() or (output/'corpus.jsonl').exists(): raise FileExistsError('Inputs already frozen')
    plan=read(output/'generation_plan.json')
    for p,h in plan['source_sha256'].items():
        if digest(ROOT/p)!=h: raise ValueError('Frozen input changed')
    manifest=read(SOURCE/'manifest.json')
    for name,h in manifest['source_sha256'].items():
        if digest(SOURCE/'source_snapshot'/name)!=h: raise ValueError('Snapshot changed')
    if digest(SOURCE/'corpus.jsonl')!=manifest['corpus_sha256']: raise ValueError('Corpus changed')
    corpus=lines(SOURCE/'corpus.jsonl')
    bydoc={c['document_id']:c for c in corpus}
    bychunk={c['chunk_id']:c for c in corpus}
    if len(bydoc)!=len(corpus): raise ValueError('This NTIS pilot expects one chunk per project')
    groups={}
    for c in corpus: groups.setdefault(c['group_id'],set()).add(c['split'])
    if any(len(s)!=1 for s in groups.values()): raise ValueError('Group leakage')
    docs={d['document_id']:d for d in read(SOURCE/'source_snapshot/documents.json')}
    tokenizer=AutoTokenizer.from_pretrained(MODEL,revision=REVISION,local_files_only=True)
    train=read(output/'train_questions.draft.json');validation=read(output/'validation_questions.draft.json')
    raw_validation_count=len(validation)
    validation,contamination=clean_validation(train,validation,docs)
    windows=[]; rejected=[]
    for q in train:
        try:
            identity=q['relevant_document_ids'][0];positive=bydoc[identity]
            if positive['split']!='train': raise ValueError('Positive outside Train')
            quote=q['evidence'][0]['text']
            p=window(positive['text'],docs[identity]['title'],quote,tokenizer)
            negatives=[];negative_ids=[]
            for n in q['negative_candidates']:
                other=bydoc[n['document_id']]
                if other['split']!='train' or other['group_id']==positive['group_id']: raise ValueError('Negative leakage')
                try: value=window(other['text'],docs[n['document_id']]['title'],n['quote'],tokenizer)
                except ValueError: continue
                negatives.append(value);negative_ids.append(other['chunk_id'])
            if not negatives: raise ValueError('No valid negative window')
            windows.append(dict(query_id=q['query_id'],query=q['query'],positive=p,negatives=negatives,
                positive_chunk_id=positive['chunk_id'],negative_chunk_ids=negative_ids,synthetic=True,
                review_status='pending_human_review'))
        except (ValueError,KeyError) as error:
            rejected.append(dict(query_id=q['query_id'],reason=str(error)))
    if len(windows)<300 or len(validation)<150: raise ValueError('Insufficient pilot training data')
    test=read(SOURCE/'test/questions.json')
    if len(test)!=10: raise ValueError('Expected the original 10 user questions; review changes')
    _,test_contamination=clean_validation(train,test,docs)
    if test_contamination: raise ValueError('Train/Test overlap: remove contaminated Train sources, never alter user Test')
    for split,questions in [('validation',validation),('test',test)]:
        if len({q['query_id'] for q in questions})!=len(questions): raise ValueError('Duplicate question IDs')
        for q in questions:
            if not q['query'].strip() or not q['relevant_document_ids'] or any(bydoc[i]['split']!=split for i in q['relevant_document_ids']):
                raise ValueError('Invalid query labels')
            for e in q['evidence']:
                if normalize(e['text']) not in normalize(docs[e['document_id']]['full_text']): raise ValueError('Evidence mismatch')
    if {normalize(q['query']) for q in train+validation}&{normalize(q['query']) for q in test}:
        raise ValueError('Exact Test query leakage')
    write_lines(output/'corpus.jsonl',corpus)
    write_lines(output/'training_windows.jsonl',windows)
    dump(output/'validation_questions.json',validation)
    dump(output/'test_questions.json',test)
    dump(output/'equivalent_tasks.json',[])
    dump(output/'validation_decontamination.json',dict(raw_questions=raw_validation_count,
        kept_questions=len(validation),excluded_projects=contamination,
        rule_uses_test_or_search_scores=False,original_split_unchanged=True))
    dump(output/'training_audit.json',dict(accepted=len(windows),rejected=rejected,
        validation=len(validation),test=len(test),all_test_labels_verified=True,test_changed=False,
        train_projects=len({bychunk[w['positive_chunk_id']]['document_id'] for w in windows})))
    paths=[SOURCE/'manifest.json',SOURCE/'corpus.jsonl',SOURCE/'test/questions.json',
        SOURCE/'source_snapshot/documents.json',output/'train_questions.draft.json',
        output/'validation_questions.draft.json',output/'generation_plan.json']
    dump(output/'preparation.json',dict(documents=len(docs),chunks=len(corpus),train=len(windows),
        validation=len(validation),original_test=len(test),source='Frozen original NTIS split snapshot (2026-10-15)',
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in paths},
        no_rfp_or_technology_adapter=True,expanded_test_created=False,synthetic_labels=True,
        supabase_modified=False,original_test_modified=False))
    print('PREPARED',len(windows),'train',len(validation),'validation',len(test),'Test',flush=True)


def cache_baseline_corpus(output=OUTPUT):
    """Encode frozen candidate documents only; do not read any Test questions."""
    import torch
    from dotenv import load_dotenv
    from app.scripts.retrain_rfp_embedding import load_model,evaluate
    load_dotenv(ROOT/'.env')
    torch.set_num_threads(4)
    output=Path(output)
    if (output/'base_corpus.npy').exists(): raise FileExistsError('Baseline cache already exists')
    corpus=lines(SOURCE/'corpus.jsonl')
    model=load_model()
    evaluate(model,corpus,{},output,'base',[])
    dump(output/'baseline_corpus_inputs.json',dict(source_sha256=digest(SOURCE/'corpus.jsonl'),
        model=MODEL,revision=REVISION,test_questions_read=False,gradient_updates=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['prepare','train','evaluate','baseline-corpus'])
    p.add_argument('--output',type=Path,default=OUTPUT)
    p.add_argument('--seed',type=int,default=20261016)
    a=p.parse_args()
    if a.stage=='baseline-corpus': cache_baseline_corpus(a.output)
    elif a.stage=='prepare': prepare(a.output)
    else: run(a.output,a.seed,a.stage,include_previous=False,corpus_label='NTIS',
        data_note='기존 NTIS 분할의 6,580개 과제·청크 고정 사본을 사용했습니다. 이 결과는 임베딩 단독 검색 평가이며 운영 RAG나 최종 생성 답변 평가는 아닙니다.')
