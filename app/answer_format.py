"""Fixed, evidence-linked presentation of already validated analysis results.

This module does not retrieve, call an LLM, change rankings, or decide Gap labels.
The full analysis and audit remain in the existing JSON outputs.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

from app.common.schemas import GapLabel, SourceType

if TYPE_CHECKING:
    from app.final_answer import ClaimCheck, EvidenceRecord
    from app.gap_analysis import GapReport
    from app.orchestrator import AnalysisState


HEADINGS = (
    '1. 우선 추천 나눔기술', '2. 우선 추천 공고', '3. 기술요소 Gap',
    '4. 관련 RFP', '5. 관련 나눔기술', '6. 공통 R&D 유의사항', '7. 확인이 필요한 사항',
)
TECH_SOURCES = {SourceType.PUBLIC_TECH, SourceType.POSCO_TECH}
# 검색·근거와 무관하게 모든 답변에 같은 문구를 안내한다 (법령 RAG 대체).
COMMON_RND_INTRO = (
    '국가 R&D 과제 참여와 나눔기술 도입 시 일반적으로 확인할 사항입니다.',
    '이번 검색 결과나 원문 근거에 기반한 판단이 아니므로, 공고문과 관련 법령 원문으로 확인하세요.',
)
COMMON_RND_NOTICES = (
    '국가 R&D 과제 참여 시 국가연구개발혁신법 적용 여부 확인',
    '연구개발비 사용 및 정산 기준 확인',
    '연구개발성과의 소유·활용 조건 확인',
    '나눔기술 도입 시 기술이전 조건 및 지식재산권 확인',
)


def _key(text):
    return ''.join(text.split()).casefold()


def _text(value):
    """Keep source text from becoming HTML, a table column, or a new heading."""
    return str(value).replace('<', '\\<').replace('>', '\\>').replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def _brief(value, limit=180):
    """Short display excerpt only; complete source text stays in the audit JSON."""
    text = re.sub(r'\s+', ' ', str(value)).strip()
    text = re.sub(r'\[E\d+\](?:\(#[^)]+\))?', '', text).strip()
    return _text(text if len(text) <= limit else text[:limit].rstrip() + '…')


def _url(value):
    # Spreadsheet cells can contain an announcement URL followed by a footer URL.
    # Only the first URL in each supplied metadata value represents that link.
    match = re.search(r'https?://[^\s<>]+', str(value))
    if not match:
        return None
    url = match.group()
    if not urlsplit(url).netloc:
        return None
    return quote(url, safe=":/?=&%+#@,;!~*'[]")


def _notices(candidate):
    titles, urls = [], []
    for extra in [candidate.extra, *(ev.extra for ev in candidate.evidences)]:
        for title in extra.get('notice_titles', []):
            if title and title not in titles:
                titles.append(title)
        for raw in extra.get('notice_urls', []):
            url = _url(raw)
            if url and url not in urls:
                urls.append(url)
    return titles, urls


def _unique_candidates(module):
    """Keep upstream order; RFP tasks in one PDF remain distinct candidates."""
    result, seen = [], set()
    if module is None:
        return result
    for candidate in module.candidates:
        identity = candidate.extra.get('task_id') or candidate.doc_id
        if identity not in seen:
            seen.add(identity)
            result.append(candidate)
    return result


class _Presentation:
    def __init__(self, state, report, claims, evidence):
        self.state, self.report = state, report
        self.claims = [claim for claim in claims if claim.accepted]
        verified = [record for record in evidence if record.evidence.verified]
        self.by_id = {record.evidence_id: record for record in verified}
        self.records, self.canonical = [], {}
        seen = {}
        for record in verified:
            ev = record.evidence
            identity = (ev.source, ev.doc_id, _key(ev.quote))
            if identity not in seen:
                seen[identity] = record.evidence_id
                self.records.append(record)
            self.canonical[record.evidence_id] = seen[identity]
        self.shown = set()
        self.names = {}
        for module in (state.technology, state.rfp, state.ntis):
            if module:
                for candidate in module.candidates:
                    self.names[(module.module, candidate.doc_id)] = candidate.title
                    if module.module == 'technology':
                        for source in TECH_SOURCES:
                            self.names[(source.value, candidate.doc_id)] = candidate.title

    def matching_records(self, evidences):
        return [r for r in self.records if any(
            ev.source == r.evidence.source and ev.doc_id == r.evidence.doc_id
            and _key(r.evidence.quote) == _key(ev.quote) for ev in evidences
        )]

    def candidate_records(self, candidate, sources):
        originals = list(candidate.evidences)
        originals.extend(ev for element in candidate.tech_elements for ev in element.evidences)
        bodies = [_key(ev.quote) for ev in originals]
        if SourceType.RFP in sources:
            # Gap extraction can cite a smaller span than a retrieved chunk.
            bodies.extend(_key('\n'.join(row['text'] for row in rows))
                          for rows in candidate.extra.get('requirements', {}).values())
        return [r for r in self.records if r.evidence.source in sources
                and r.evidence.doc_id == candidate.doc_id
                and any(_key(r.evidence.quote) in body for body in bodies)]

    def select_evidence(self, records, limit=None):
        cited = {self.canonical.get(c.evidence_id, c.evidence_id)
                 for claim in self.claims for c in claim.draft.citations}
        terms = set(re.findall(r'[a-zA-Z0-9가-힣]{2,}', ' '.join([
            self.state.request.problem, *self.state.request.owned_technologies,
            *self.state.request.unmet_elements,
        ]).casefold()))
        ordered = sorted(records, key=lambda r: (
            -int(r.evidence_id in cited),
            -sum(term in r.evidence.quote.casefold() for term in terms),
        ))
        selected, seen = [], set()
        for record in ordered:
            key = (record.evidence.source, record.evidence.doc_id, _key(record.evidence.quote))
            if not key[2] or key in seen:
                continue
            seen.add(key)
            selected.append(record)
            if limit and len(selected) == limit:
                break
        return selected

    def evidence_block(self, records):
        if not records:
            return ['검증된 원문 근거를 확보하지 못했습니다.']
        lines = []
        for record in records[:2]:
            if record.evidence_id in self.shown:
                continue
            self.shown.add(record.evidence_id)
            ev = record.evidence
            title = ev.extra.get('filename') or self.names.get((ev.source.value, ev.doc_id), '출처 문서')
            pages = sorted({location['page'] for location in ev.extra.get('source_locations', [])
                            if isinstance(location.get('page'), int)})
            location = f'{ev.page + 1}쪽' if ev.page is not None else (
                ', '.join(map(str, pages)) + '쪽' if pages else '페이지 정보 미확인')
            lines += ['> ' + _brief(ev.quote, 220), '',
                      f'출처: {_text(title)} · {location} · 원문 발췌', '']
        return lines

    def claim_texts(self, section, candidate=None, gap_index=None, allowed_ids=None):
        texts = []
        for claim in self.claims:
            if claim.draft.section != section:
                continue
            if gap_index is not None and claim.draft.gap_index != gap_index:
                continue
            records = [self.by_id[c.evidence_id] for c in claim.draft.citations if c.evidence_id in self.by_id]
            if len(records) != len(claim.draft.citations):
                continue
            if allowed_ids is not None and any(self.canonical.get(r.evidence_id, r.evidence_id) not in allowed_ids for r in records):
                continue
            if candidate and (not records or any(r.evidence.doc_id != candidate.doc_id for r in records)):
                continue
            line = _text(claim.draft.text).strip()
            if line not in texts:
                texts.append(line)
        return texts

    def source_description(self, candidate, section):
        sources = {'external': TECH_SOURCES, 'rfp': {SourceType.RFP}}[section]
        records = self.select_evidence(self.candidate_records(candidate, sources), 5)
        claims = self.claim_texts(section, candidate, allowed_ids={r.evidence_id for r in records})
        if claims:
            # Detailed source statements remain in the audit; avoid a wall of prose.
            return [_brief(claims[0])]
        if section == 'external' and candidate.relation_summary.strip():
            return [_brief(candidate.relation_summary)]
        return ['검색 순위에 따른 기술적 관련 후보이며, 세부 대응은 아래 Gap 분석을 참고하세요.']

    def gap_indices(self, candidate):
        shared = sum(c.doc_id == candidate.doc_id for c in self.state.rfp.candidates) > 1
        ids = {r.evidence_id for r in self.candidate_records(candidate, {SourceType.RFP})}
        return [i for i, item in enumerate(self.report.items) if candidate.doc_id in item.rfp_doc_ids
                and (not shared or any(r.evidence_id in ids for r in self.matching_records(item.requirement.evidences)))]


def render_answer(state: AnalysisState, report: GapReport, claims: list[ClaimCheck],
                  evidence: list[EvidenceRecord], warnings: list[str]) -> str:
    """Public seven-section summary: plain Markdown, bounded excerpts, no audit IDs."""
    view = _Presentation(state, report, claims, evidence)
    tech = _unique_candidates(state.technology)[:5]
    rfps = _unique_candidates(state.rfp)[:5]
    lines = ['# 기술기획 분석 결과', '',
             '- **보유기술:** ' + _text('; '.join(state.request.owned_technologies) or '입력 없음'),
             '- **요청 보완기술:** ' + _text('; '.join(state.request.unmet_elements) or '명시 없음'),
             '- **기술문제:** ' + _brief(state.request.problem, 250), '']
    lines += [f'## {HEADINGS[0]}', '']
    if tech:
        c = tech[0]
        lines += [f'**{_text(c.title)}**', '', f'- 제공기관: {_text(c.provider or "미확인")}',
                  f'- 기술이전 조건: {_text(c.transfer_condition or "미확인")}', '',
                  *view.source_description(c, 'external')]
    else:
        lines += ['이번 검색에서 관련 나눔기술을 찾지 못했습니다.']
    lines += ['', '### 1-1. 원문 근거', '']
    lines += view.evidence_block(view.select_evidence(view.candidate_records(tech[0], TECH_SOURCES), 2)) if tech else ['표시할 원문 근거가 없습니다.']

    lines += ['', f'## {HEADINGS[1]}', '']
    if rfps:
        c = rfps[0]
        titles, urls = _notices(c)
        lines += [f'**{_text(" / ".join(titles))}**' if titles else '**원 공고 연결 정보 미확인**', '',
                  f'- RFP 과제명: {_text(c.title)}']
        lines.extend(f'- [원 공고 확인 {i}]({url})' for i, url in enumerate(urls, 1))
        if not urls:
            lines += ['- 원 공고 URL: 미확인']
        lines += ['', *view.source_description(c, 'rfp')]
    else:
        lines += ['이번 검색에서 관련 공고·RFP 후보를 찾지 못했습니다.']
    lines += ['', '### 2-1. 원문 근거', '']
    lines += view.evidence_block(view.select_evidence(view.candidate_records(rfps[0], {SourceType.RFP}), 2)) if rfps else ['표시할 원문 근거가 없습니다.']

    lines += ['', f'## {HEADINGS[2]}', '']
    if report.method == 'local':
        lines += ['키워드·유사도에 따른 잠정 판정입니다. 성능·범위의 충족을 입증하지 않습니다.', '']
    scoped = set(i for c in _unique_candidates(state.rfp) for i in view.gap_indices(c))
    groups = {label: [] for label in GapLabel}
    for i in sorted(scoped):
        item = report.items[i]
        label = item.label if view.matching_records(item.requirement.evidences) else GapLabel.INSUFFICIENT
        groups[label].append(item)
    if not scoped:
        lines += ['Gap을 판단할 충분한 근거가 없습니다.']
    else:
        titles = [c.title for c in _unique_candidates(state.rfp) if view.gap_indices(c)]
        lines += [f'분석한 기술요소 {len(scoped)}개를 판정별로 요약했습니다. 사용자 입력과 이번 검색 자료 범위의 분석입니다.', '',
                  '- 분석 대상: ' + _brief('; '.join(titles), 220), '',
                  '| 판정 | 기술요소 수 | 대표 기술요소 | 보유·외부기술 대응 요약 |', '|---|---:|---|---|']
        for label, items in groups.items():
            if not items:
                continue
            names = list(dict.fromkeys(item.requirement.name for item in items))
            examples = ', '.join(names[:3]) + (f' 외 {len(names)-3}개' if len(names) > 3 else '')
            if label in {GapLabel.OWNED, GapLabel.EXTERNAL, GapLabel.PARTIAL}:
                matches = [m for item in items for m in (
                    item.company if label == GapLabel.OWNED else item.external if label == GapLabel.EXTERNAL
                    else [*item.company, *item.external]) if m.verified and view.matching_records(m.evidences)
                    and m.coverage == ('partial' if label == GapLabel.PARTIAL else 'full')]
                sources = list(dict.fromkeys(m.title or m.element_name for m in matches))
                source_text = ', '.join(sources[:2]) + (' 등' if len(sources) > 2 else '')
                summaries = {GapLabel.OWNED: '사용자 입력 보유기술과 요구기술의 대응이 확인됐습니다. 보유 사실을 독립 검증한 결과는 아닙니다.',
                             GapLabel.EXTERNAL: '외부 나눔기술에서 보완 근거가 확인됐습니다.',
                             GapLabel.PARTIAL: '일부 대응 근거가 있으며, 남은 요구 범위는 추가 확인이 필요합니다.'}
                summary = summaries[label] + (f' 대응 기술: {source_text}.' if source_text else '')
            elif label == GapLabel.RND_NEEDED:
                summary = 'RFP에서 요구하지만 현재 보유·외부기술 자료에서 충분한 충족 근거를 확인하지 못했습니다.'
            else:
                summary = '요구사항 또는 대응 근거가 부족하여 충족 여부를 판단하기 어렵습니다.'
            lines += [f'| {label.value} | {len(items)} | {_brief(examples, 150)} | {_brief(summary, 200)} |']
        # At most two distinct reviewed interpretations, without repeating every Gap row.
        interpretations = list(dict.fromkeys(text for text in view.claim_texts('gap')
            if any(_key(report.items[i].requirement.name) in _key(text) for i in scoped)))
        if interpretations:
            lines += ['', *[f'- {_brief(text, 160)}' for text in interpretations[:2]]]
        lines += ['', '세부 기술요소별 판정과 전체 원문 근거는 상세 분석 JSON에 보존됩니다.']

    lines += ['', '### 선행 R&D 참고', '']
    ntis = []
    for c in _unique_candidates(state.ntis):
        if c.extra.get('technology_relevance', {}).get('accepted') is False:
            continue
        records = view.select_evidence(view.candidate_records(c, {SourceType.NTIS}), 1)
        if records:
            ntis.append((c, records))
        if len(ntis) == 5:
            break
    for rank, (c, records) in enumerate(ntis, 1):
        lines += [f'{rank}. **{_text(c.title)}** — 관련 근거 발췌: {_brief(records[0].evidence.quote, 130)}']
    if not ntis:
        lines += ['이번 검색에서 검증된 관련 선행 과제 근거를 확보하지 못했습니다.']
    lines += ['', '기존 검색 관련성 순서의 검증된 후보만 표시하며, NTIS는 기술 충족 판정의 단독 근거로 사용하지 않습니다.']

    lines += ['', f'## {HEADINGS[3]}', '']
    if rfps:
        lines += ['| 순위 | RFP 과제명 | 주요 요구기술·관련성 | 원 공고 |', '|---|---|---|---|']
    else:
        lines += ['이번 검색에서 관련 RFP를 찾지 못했습니다.']
    for rank, c in enumerate(rfps, 1):
        _, urls = _notices(c)
        names = [report.items[i].requirement.name for i in view.gap_indices(c)]
        summary = _brief(', '.join(dict.fromkeys(names)), 150) if names else '검색 관련 후보 · Gap 미분석'
        link = f'[원 공고]({urls[0]})' if urls else '연결 정보 미확인'
        lines += [f'| {rank}{" · 우선 추천" if rank == 1 else ""} | {_text(c.title)} | {summary} | {link} |']

    lines += ['', f'## {HEADINGS[4]}', '']
    if tech:
        lines += ['| 순위 | 나눔기술명 | 제공기관 | 관련성 요약 |', '|---|---|---|---|']
    else:
        lines += ['이번 검색에서 관련 나눔기술을 찾지 못했습니다.']
    for rank, c in enumerate(tech, 1):
        summary = _brief(c.relation_summary or '기술적 관련 후보 · 보완 범위 추가 확인 필요', 130)
        lines += [f'| {rank}{" · 우선 추천" if rank == 1 else ""} | {_text(c.title)} | {_text(c.provider or "미확인")} | {summary} |']

    lines += ['', f'## {HEADINGS[5]}', '']
    lines += [*COMMON_RND_INTRO, '', *[f'- {notice}' for notice in COMMON_RND_NOTICES]]

    lines += ['', f'## {HEADINGS[6]}', '']
    concerns = list(warnings)
    concerns.extend(check for item in report.items for check in item.policy_check)
    for c in tech:
        if c.transfer_condition in {'', '미상', '미확인'} and not any(c.title in value and '이전' in value for value in concerns):
            concerns.append(f'기술이전 조건 확인 필요: {c.title}')
    for c in rfps:
        titles, urls = _notices(c)
        if not titles or not urls:
            concerns.append(f'원 공고 연결 정보 확인 필요: {c.title}')
    concerns.extend(view.claim_texts('next_steps'))
    unique = list(dict.fromkeys(_brief(value, 180) for value in concerns if value.strip()))
    lines += [f'- {value}' for value in unique[:5]] if unique else ['현재 분석에서 별도로 확인이 필요한 사항은 없습니다.']
    if len(unique) > 5:
        lines += [f'- 추가 확인사항 {len(unique)-5}건은 상세 분석 JSON에 보존됩니다.']
    lines += ['', '추천은 기술적 관련 후보입니다. 기술 도입 가능성·사업 신청자격·법적 적합성을 확정하지 않습니다.',
              '추가 R&D 검토 후보는 현재 자료의 충족 근거 부족을 의미하며, 신규 개발이 반드시 필요하다는 확정이 아닙니다.']
    return '\n'.join(lines) + '\n'
