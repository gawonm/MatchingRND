"""Rebuild current RFP chunks, retrain locally, and evaluate frozen model variants.

No LLM calls, Supabase writes, or changes to prior experiments. A changed corpus
requires fresh label review rather than silently reusing incompatible labels.
"""
import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT/'data/experiments/rfp_embedding_split'
REVISION = '7074d66aa46562342193ca4feb3d89bf9dad71b4'
MODEL = 'dragonkue/BGE-m3-ko'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf8').splitlines() if line.strip()]


def write_lines(path, values):
    Path(path).write_text(''.join(json.dumps(v, ensure_ascii=False)+'\n' for v in values), encoding='utf8')


def normalize(text):
    return ''.join(text.split())


def prepare(output):
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    from transformers import AutoTokenizer
    from langchain_core.documents import Document
    from app.common.supabase_ingestion import unpack
    from app.rfp_rag.config import load_config
    from app.rfp_rag.indexing.chunker import build_chunks
    cfg = load_config()
    # Approved parsing is reusable only if its implementation is still identical.
    changed = subprocess.check_output(['git','diff','01307bd','HEAD','--',
        'app/rfp_rag/parsing','app/rfp_rag/review.py','app/rfp_rag/review_decisions.json'], cwd=ROOT)
    dirty = subprocess.check_output(['git','diff','HEAD','--',
        'app/rfp_rag/parsing','app/rfp_rag/review.py','app/rfp_rag/review_decisions.json'], cwd=ROOT)
    if changed.strip() or dirty.strip():
        raise ValueError('Parser/review changed: regenerate and review approved tasks before training')
    tasks = unpack(read(ROOT/'data/processed/rfp/approved/tasks.json'))
    for task in tasks:
        source = cfg['data_dir']/task['source']
        if not source.is_file() or digest(source) != task['file_hash']:
            raise ValueError('Approved source changed: '+task['source'])
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
    chunks, _ = build_chunks(tasks, {t['source']:[] for t in tasks}, tokenizer,
                             cfg['CHUNK_TOKENS'], cfg['OVERLAP_TOKENS'], Document)
    previous = lines(OLD/'corpus.jsonl')
    old_by_id = {c['chunk_id']:c for c in previous}
    current = {d.metadata['chunk_id']:d for d in chunks}
    if set(current) != set(old_by_id) or any(current[i].page_content != old_by_id[i]['text'] for i in current):
        dump(output/'corpus_change.json', dict(old_chunks=len(previous), current_chunks=len(current),
            added=list(set(current)-set(old_by_id)), removed=list(set(old_by_id)-set(current))))
        raise ValueError('Current chunks changed: review/relabel training and test inputs before reuse')
    # Preserve validated split/group assignment and all original text exactly.
    write_lines(output/'corpus.jsonl', previous)
    byid = {c['chunk_id']:c for c in previous}
    windows = lines(OLD/'results/lora_pilot_v1/training_windows.jsonl')
    drafts = {q['query_id']:q for q in read(OLD/'synthetic_draft_v1/train/questions.draft.json')}
    for w in windows:
        q = drafts[w['query_id']]
        if q['query'] != w['query']:
            raise ValueError('Training question changed')
        for cid in [w['positive_chunk_id']]+w['negative_chunk_ids']:
            if byid[cid]['split'] != 'train':
                raise ValueError('Non-training chunk in training data')
        if not any(e['task_id']==byid[w['positive_chunk_id']]['task_id'] and
                   normalize(e['text']) in normalize(byid[w['positive_chunk_id']]['text']) for e in q['evidence']):
            raise ValueError('Training evidence changed')
        for cid in w['negative_chunk_ids']:
            if byid[cid]['group_id'] == byid[w['positive_chunk_id']]['group_id']:
                raise ValueError('Positive family used as a negative')
    write_lines(output/'training_windows.jsonl', windows)
    old_val = read(OLD/'results/lora_pilot_v1/validation_base.json')
    val_ids = {q['query_id'] for q in old_val['results']}
    validation = [q for q in read(OLD/'synthetic_draft_v1/validation/questions.draft.json') if q['query_id'] in val_ids]
    if len(validation) != len(val_ids):
        raise ValueError('Validation question IDs changed')
    test = read(OLD/'test/questions.json')
    expanded = read(OLD/'test/expanded_v3/questions.json')
    task_split = {c['task_id']:c['split'] for c in previous}
    for split, questions in [('validation',validation), ('test',test), ('test',expanded)]:
        for q in questions:
            if not q['relevant_task_ids'] or any(task_split.get(i)!=split for i in q['relevant_task_ids']):
                raise ValueError('Question labels outside declared split')
            for e in q.get('evidence',[]):
                if not any(c['task_id']==e['task_id'] and normalize(e['text']) in normalize(c['text']) for c in previous):
                    raise ValueError('Question evidence absent: '+q['query_id'])
    dump(output/'validation_questions.json', validation)
    dump(output/'test_questions.json', test)
    dump(output/'expanded_questions.json', expanded)
    dump(output/'equivalent_tasks.json', read(OLD/'test/equivalent_tasks.json'))
    sources = [OLD/'corpus.jsonl', OLD/'manifest.json', OLD/'results/lora_pilot_v1/training_windows.jsonl',
               OLD/'synthetic_draft_v1/train/questions.draft.json', OLD/'synthetic_draft_v1/validation/questions.draft.json',
               OLD/'test/questions.json', OLD/'test/expanded_v3/questions.json', OLD/'test/equivalent_tasks.json']
    dump(output/'preparation.json', dict(current_chunks_rebuilt=True, corpus_identical_to_previous=True,
        approved_tasks=len(tasks), chunks=len(chunks), train=len(windows), validation=len(validation),
        original_test=len(test), expanded_test=len(expanded), source_sha256={str(p.relative_to(ROOT)):digest(p) for p in sources},
        reused_synthetic_training_labels=True, human_reviewed_training_labels=False,
        production_rag_changed='retrieval relevance filtering; parser unchanged', supabase_modified=False))
    print('PREPARED', len(tasks),len(chunks),len(windows),len(validation),len(expanded), flush=True)


def rank_metrics(scores, corpus, questions, equivalents):
    import numpy as np
    identity_field='task_id' if 'task_id' in corpus[0] else 'document_id'
    label_field='relevant_task_ids' if identity_field=='task_id' else 'relevant_document_ids'
    task_ids = sorted({c[identity_field] for c in corpus})
    parent = {i:i for i in task_ids}
    def find(i):
        while parent[i]!=i:
            i=parent[i]
        return i
    for group in equivalents:
        roots = [find(i) for i in group if i in parent]
        for i in roots:
            parent[i] = min(roots)
    grouped = {}
    for column, chunk in enumerate(corpus):
        grouped.setdefault(find(chunk[identity_field]), []).append(column)
    ordered = sorted(grouped)
    task_scores = np.column_stack([scores[:,grouped[i]].max(axis=1) for i in ordered])
    results=[]
    for row,q in enumerate(questions):
        truth = {find(i) for i in q[label_field]}
        ranking = sorted(range(len(ordered)), key=lambda j:(-float(task_scores[row,j]),ordered[j]))
        positions = [k for k,j in enumerate(ranking,1) if ordered[j] in truth]
        first = min(positions)
        results.append(dict(query_id=q['query_id'], first_relevant_rank=first,
                            **{f'top_10_{identity_field}s':[ordered[j] for j in ranking[:10]]}))
    aggregate = {f'hit_at_{k}':sum(r['first_relevant_rank']<=k for r in results)/len(results) for k in (1,3,5,10)}
    aggregate['mrr_at_10'] = sum(1/r['first_relevant_rank'] if r['first_relevant_rank']<=10 else 0 for r in results)/len(results)
    return dict(question_count=len(questions), aggregate=aggregate, results=results)


def load_model(adapter=None):
    from sentence_transformers import SentenceTransformer
    from peft import PeftModel
    model = SentenceTransformer(MODEL, device='cuda', revision=REVISION, local_files_only=True)
    model.max_seq_length=8192
    if adapter:
        model[0].model = PeftModel.from_pretrained(model[0].model, str(adapter), is_trainable=False)
    return model


def ensure_adapter_checkpoint(folder):
    """Recover adapter-only weights from ST's deprecated read-only alias save.

    The first live run attached the PeftModel through auto_model. Its base model
    contained the trained LoRA layers but saved a full state dict. Extract those
    exact tensors without changing or retraining them. Keep the full copy until
    reload verification is complete.
    """
    folder=Path(folder)
    if (folder/'adapter_config.json').exists():
        return
    from safetensors import safe_open
    from safetensors.torch import save_file
    from peft import LoraConfig, TaskType
    import torch
    full=folder/'model.safetensors'
    tensors={}
    with safe_open(full,framework='pt',device='cpu') as handle:
        for key in handle.keys():
            if '.lora_A.default.' in key or '.lora_B.default.' in key:
                tensors['base_model.model.'+key.replace('.default.','.')]=handle.get_tensor(key).clone()
    b=[t for k,t in tensors.items() if '.lora_B.' in k]
    if len(tensors)!=96 or len(b)!=48 or not all(torch.isfinite(t).all() and torch.count_nonzero(t)>0 for t in b):
        raise ValueError('Incomplete or untrained LoRA tensors')
    config=LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,target_modules=['query','value'],
        bias='none',task_type=TaskType.FEATURE_EXTRACTION,base_model_name_or_path=MODEL,
        revision=REVISION,inference_mode=True)
    config.save_pretrained(folder)
    save_file(tensors,folder/'adapter_model.safetensors',metadata={'format':'pt'})
    dump(folder/'adapter_extraction.json',dict(full_state_sha256=digest(full),
        adapter_sha256=digest(folder/'adapter_model.safetensors'),lora_tensors=len(tensors),
        nonzero_lora_b=len(b),exact_tensor_extraction=True,weights_changed=False))


def evaluate(model, corpus, sets, output, name, equivalents):
    import numpy as np
    import torch
    model.eval()
    with torch.inference_mode(), torch.autocast('cuda',dtype=torch.float16):
        if name=='base' and (output/'base_corpus.npy').exists():
            cv=np.load(output/'base_corpus.npy')
            if cv.shape!=(len(corpus),1024) or not np.isfinite(cv).all():
                raise ValueError('Invalid current-run baseline vectors')
        else:
            cv = model.encode([c['text'] for c in corpus], batch_size=4, normalize_embeddings=True,
                              show_progress_bar=True, convert_to_numpy=True).astype(np.float32)
            # Renormalize after fp16 conversion for an exact cosine comparison.
            cv /= np.linalg.norm(cv,axis=1,keepdims=True)
            np.save(output/f'{name}_corpus.npy',cv)
        reports={}
        for split,qs in sets.items():
            qv=model.encode([q['query'] for q in qs],batch_size=16,normalize_embeddings=True,
                            convert_to_numpy=True).astype(np.float32)
            qv/=np.linalg.norm(qv,axis=1,keepdims=True)
            reports[split]=rank_metrics(qv@cv.T,corpus,qs,equivalents)
            dump(output/f'{name}_{split}.json',reports[split])
    print('EVALUATION',name,{s:r['aggregate'] for s,r in reports.items()},flush=True)
    return reports


def run(output, seed, stage, *, previous_adapter=None, corpus_label='RFP', include_previous=True, data_note=None):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    if stage=='prepare':
        if (output/'preparation.json').exists(): raise FileExistsError('Preparation already exists')
        return prepare(output)
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    import numpy as np
    import torch
    from peft import LoraConfig, get_peft_model, TaskType
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(4)
    if not torch.cuda.is_available(): raise RuntimeError('CUDA required')
    corpus=lines(output/'corpus.jsonl')
    windows=lines(output/'training_windows.jsonl')
    sets={s:read(output/f'{s}_questions.json') for s in ('validation','test','expanded')
          if (output/f'{s}_questions.json').exists()}
    if not sets.get('validation') or not sets.get('test'):
        raise ValueError('Nonempty Validation and Test are required')
    equivalents=read(output/'equivalent_tasks.json')
    if stage=='train':
        protocol=dict(model=MODEL,revision=REVISION,seed=seed,epochs=2,learning_rate=2e-5,lora_rank=8,
            lora_alpha=16,lora_dropout=.05,train_tokens=384,inference_tokens=8192,accumulation=8,
            loss='explicit-negative softmax, temperature 0.05; no in-batch negatives',
            selection='highest validation MRR@10, earliest tie',test_used_for_selection=False,
            gpu=torch.cuda.get_device_name(),git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            supabase_modified=False,model_deployed=False,corpus=corpus_label,
            precision='fp16 autocast; fp32 vector normalization',weight_decay=.01)
        if (output/'protocol.json').exists():
            if read(output/'protocol.json') != protocol or (output/'history.json').exists() or list(output.glob('adapter_epoch_*')):
                raise FileExistsError('Cannot overwrite existing training or change its protocol')
            print('RESUME pre-training only; no optimizer step or checkpoint existed',flush=True)
        else:
            dump(output/'protocol.json',protocol)
        model=load_model()
        if (output/'base_validation.json').exists():
            if read(output/'base_validation.json')['question_count'] != len(sets['validation']):
                raise ValueError('Invalid cached baseline')
        else:
            evaluate(model,corpus,{'validation':sets['validation']},output,'base',equivalents)
        model[0].model=get_peft_model(model[0].model,LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,
            target_modules=['query','value'],bias='none',task_type=TaskType.FEATURE_EXTRACTION))
        model[0].model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        model.max_seq_length=384
        trainable=[p for p in model.parameters() if p.requires_grad]
        optimizer=torch.optim.AdamW(trainable,lr=2e-5)
        scaler=torch.amp.GradScaler('cuda',init_scale=1024)
        history=[]
        for epoch in (1,2):
            model.train(); model.max_seq_length=384
            order=list(range(len(windows))); random.Random(seed+epoch).shuffle(order)
            optimizer.zero_grad(set_to_none=True); losses=[]; updates=0; skips=0
            for step,index in enumerate(order):
                w=windows[index]
                texts=[w['query'],w['positive']]+w['negatives']
                features={k:v.to('cuda') if torch.is_tensor(v) else v for k,v in model.preprocess(texts).items()}
                group_start=(step//8)*8
                group_size=min(8,len(order)-group_start)
                with torch.autocast('cuda',dtype=torch.float16):
                    embeddings=torch.nn.functional.normalize(model(features)['sentence_embedding'].float(),p=2,dim=1)
                    logits=(embeddings[:1]@embeddings[1:].T)/.05
                    raw_loss=torch.nn.functional.cross_entropy(logits,torch.zeros(1,dtype=torch.long,device='cuda'))
                    loss=raw_loss/group_size
                if not torch.isfinite(loss): raise RuntimeError('Nonfinite loss')
                scaler.scale(loss).backward(); losses.append(float(raw_loss.detach()))
                if (step+1)%8==0 or step+1==len(order):
                    scaler.unscale_(optimizer); torch.nn.utils.clip_grad_norm_(trainable,1.)
                    scale=scaler.get_scale(); scaler.step(optimizer); scaler.update()
                    if scaler.get_scale()<scale: skips+=1
                    else: updates+=1
                    optimizer.zero_grad(set_to_none=True)
                if (step+1)%40==0: print('TRAIN',epoch,step+1,'loss',sum(losses)/len(losses),flush=True)
            model[0].model.save_pretrained(output/f'adapter_epoch_{epoch}')
            model.max_seq_length=8192
            val=evaluate(model,corpus,{'validation':sets['validation']},output,f'epoch_{epoch}',equivalents)['validation']['aggregate']
            history.append(dict(epoch=epoch,mean_loss=sum(losses)/len(losses),validation=val,optimizer_updates=updates,amp_skips=skips))
            dump(output/'history.json',history)
        best=max(history,key=lambda row:(row['validation']['mrr_at_10'],-row['epoch']))
        dump(output/'selection.json',dict(epoch=best['epoch'],selected_by='validation only'))
        del optimizer,model; torch.cuda.empty_cache()
        return
    if stage=='evaluate':
        if (output/'comparison.json').exists(): raise FileExistsError('Evaluation already completed')
        selection=read(output/'selection.json')
        for folder in output.glob('adapter_epoch_*'):
            ensure_adapter_checkpoint(folder)
        variants=[('base',None)]
        if include_previous:
            variants.append(('previous_finetuned',previous_adapter or OLD/'results/lora_pilot_v1/adapter_epoch_2'))
        variants.append(('new_finetuned',output/f'adapter_epoch_{selection["epoch"]}'))
        result={}
        for name,adapter in variants:
            model=load_model(adapter)
            result[name]=evaluate(model,corpus,{s:q for s,q in sets.items() if s!='validation'},output,name,equivalents)
            del model; torch.cuda.empty_cache()
        before=np.load(output/f'epoch_{selection["epoch"]}_corpus.npy')
        after=np.load(output/'new_finetuned_corpus.npy')
        error=float(np.max(np.abs(before-after)))
        dump(output/'reload_verification.json',dict(max_absolute_vector_error=error,
            compared_corpus_vectors=len(corpus),passed=error<1e-5))
        if error>=1e-5: raise ValueError('Reloaded adapter differs from selected checkpoint')
        for path,h in read(output/'preparation.json')['source_sha256'].items():
            if digest(ROOT/path)!=h: raise ValueError('Original experiment changed')
        dump(output/'comparison.json',dict(results={n:{s:r['aggregate'] for s,r in reports.items()} for n,reports in result.items()},
            old_inputs_unchanged=True,selected_epoch=selection['epoch'],supabase_modified=False,
            note='Embedding-only search, not production hybrid/relevance-gate or final answer quality'))
        report=[f'# {corpus_label} 임베딩 학습 비교 결과','',
            data_note or '현재 코드로 청크를 재생성한 결과 이전 원문과 동일했습니다. 검색 후 관련성 판정 변경은 이 임베딩 단독 평가에 포함되지 않습니다.',
            '기본 모델에서 새 LoRA를 학습했습니다. 원래 모델과 실험 파일은 보존했습니다.','']
        model_labels={'base':'기본 모델','previous_finetuned':'이전 파인튜닝','new_finetuned':'새 파인튜닝'}
        for split in (s for s in ('test','expanded') if s in sets):
            report += [f'## {split} ({len(sets[split])} questions)','',
                       '| 지표 | '+' | '.join(model_labels[n] for n,_ in variants)+' |',
                       '|---|'+'---:|'*len(variants)]
            for metric in ('hit_at_1','hit_at_3','hit_at_5','hit_at_10','mrr_at_10'):
                values=[result[n][split]['aggregate'][metric] for n,_ in variants]
                formatted=[f'{v:.4f}' if metric=='mrr_at_10' else f'{v:.2%}' for v in values]
                report.append('| '+metric+' | '+' | '.join(formatted)+' |')
        report += ['', '학습·Validation은 사람이 검수하지 않은 합성 라벨이며 의미상 오류 가능성이 있습니다. Test 결과로 학습 설정을 재선택하지 않았습니다.']
        if 'expanded' in sets:
            extra_count=len(sets['expanded'])-len(sets['test'])
            report += [f"{len(sets['expanded'])}개 확장 질문 중 {extra_count}개는 사람이 검수하지 않은 합성 질문입니다."]
        report += ['Validation으로만 epoch을 선택했습니다. 원문·운영 모델·Supabase는 변경하지 않았습니다.']
        (output/'report.md').write_text('\n'.join(report)+'\n',encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/experiments/rfp_embedding_rerun_20261016')
    parser.add_argument('--seed',type=int,default=20261016)
    parser.add_argument('stage',choices=['prepare','train','evaluate'])
    args=parser.parse_args()
    run(args.output,args.seed,args.stage)
