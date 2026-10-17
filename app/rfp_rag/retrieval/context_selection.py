"""Deterministic source selection and balanced A/B ordering; no LLM or gold labels."""
import math
import re

_STOP = {'기술', '기술을', '기술과', '기반', '시스템', '개발', '보유', '위해', '관련', '하는', '있는'}


def _features(text):
    words = [w for w in re.findall(r'[a-z0-9]+|[가-힣]+', str(text).lower()) if w not in _STOP]
    features = set()
    for word in words:
        if word.isascii():
            features.add('word:' + word)
        else:
            features.update(word[i:i + 2] for i in range(len(word) - 1))
    return features


def _score(name, text):
    query = _features(name)
    if not query:
        return 0.0
    return len(query & _features(text)) / len(query) / math.sqrt(1 + len(text) / 4000)


def select_sections(sections, technologies, *, max_chars=12000, neighbors=1):
    """Keep whole source fragments and their original order; never synthesize a quote."""
    if sum(len(s['text']) for s in sections) <= max_chars:
        return sections, False
    seeds = []
    for name in technologies:
        ranked = sorted(range(len(sections)), key=lambda i: (-_score(name, sections[i]['text']), i))
        seeds.extend(i for i in ranked[:2] if _score(name, sections[i]['text']) > 0)
    if not seeds:
        return sections, False
    selected, used = set(), 0
    for seed in dict.fromkeys(seeds):
        window = [i for i in range(max(0, seed-neighbors), min(len(sections), seed+neighbors+1))
                  if sections[i].get('item') == sections[seed].get('item')
                  and sections[i].get('page') == sections[seed].get('page')
                  and sections[i].get('source') == sections[seed].get('source')]
        additions = [i for i in window if i not in selected]
        size = sum(len(sections[i]['text']) for i in additions)
        if not selected or used + size <= max_chars:
            selected.update(additions)
            used += size
        elif seed not in selected and used + len(sections[seed]['text']) <= max_chars:
            selected.add(seed)
            used += len(sections[seed]['text'])
    if len(selected) == len(sections):
        return sections, False
    return [{**sections[i], '_original_index': i} for i in sorted(selected)], True


def task_balance_score(task, owned, requested):
    """Prefer evidence for both A and B, retaining the retrieval order as a tie-breaker."""
    text = str(task.get('title', '')) + '\n' + '\n'.join(
        fragment.page_content for fragments in task.get('fields', {}).values() for fragment in fragments)
    a = max((_score(name, text) for name in owned), default=0.0)
    b = min((_score(name, text) for name in requested), default=0.0)
    return 2*a*b/(a+b) if a+b else 0.0


def filter_candidates(candidates, chunks, tasks, gate, top_k, *, order='retrieval', window=None):
    if order not in {'retrieval', 'balanced'}:
        raise ValueError('후보 순서는 retrieval 또는 balanced여야 합니다.')
    if window is not None and window < 1:
        raise ValueError('후보 검토 창은 1 이상이어야 합니다.')
    candidates = list(candidates)
    if order == 'balanced' and gate.active:
        candidates.sort(key=lambda pair: -task_balance_score(
            tasks.get(chunks[pair[0]].metadata['task_id'], {}), gate.owned, gate.requested))
    selected, checks_by_id, examined = [], {}, 0
    reason = 'exhausted'
    for offset in range(0, len(candidates), gate.runner.batch_size):
        batch = candidates[offset:offset+gate.runner.batch_size]
        checks = gate.check_many([tasks.get(chunks[cid].metadata['task_id'], {}) for cid, _ in batch]) if gate.active else [None]*len(batch)
        examined += len(batch)
        for pair, check in zip(batch, checks):
            tid = chunks[pair[0]].metadata['task_id']
            if check is not None:
                checks_by_id[tid] = check
            if len(selected) < top_k and (check is None or check['accepted']):
                selected.append(pair)
        if len(selected) >= top_k:
            reason = 'target_reached'
            break
        if window is not None and examined >= window and selected:
            reason = 'budget_with_matches'
            break
    return selected, checks_by_id, dict(order=order, window=window, examined=examined,
                                       available=len(candidates), stop_reason=reason,
                                       unexamined=max(0, len(candidates)-examined))
