# Technology RAG (기술나눔 검색) — 동작·출력·통합 시 주의사항

대상 코드: `app/technology_rag/`. 이 문서는 **현재 코드 기준**이다.
(2026-10-15 최초 작성 후, 2026-10-16 질의 분해 제거·same/similar/none 전환과 이후 Orchestrator 연동을 반영해 다시 정리했다.
변경 전 구현의 시험 결과는 6절에 이력으로만 남겼다.)

## 1. 무엇을 하는 모듈인가

입력은 상류(Orchestrator)가 이미 나눈 **보유기술(A)** 과 **확보하려는 기술(B)** 이다.
Technology RAG의 목표는 **B와 같거나(same) 유사한(similar) 기술나눔 문서가 있는지**를 답하는 것이다.
B와 무관한 문서(none)는 결과에서 **탈락**시킨다. 보유기술(A)과 비슷하다는 이유로는 문서를 고르지 않으며,
A는 검색에 쓰지 않고 판정 단계에 참고로만 전달한다.

이 모듈은 문장을 분해하지 않는다. 사용자 입력의 A/B 분해는 Orchestrator 쪽에서 미리 이뤄지며,
RAG 내부 분해 단계(LLM 1회)는 중복이라 제거했다 (커밋 afac2a6).

## 2. 동작 흐름

`TechnologyRagPipeline.answer(owned, target, *, search_terms=None, ...)` ([pipeline.py](../app/technology_rag/pipeline.py))

```
owned(A), target(B), search_terms(선택, B의 동의어·상하위 표현)
  │ ① 검색 질의 구성: B(여러 개면 " / " 로 연결) + 줄바꿈 + search_terms(" / " 로 연결).  A는 넣지 않는다
  ▼
  │ ② 검색 (search)
  │    BM25(Kiwi, top 50) + Dense(BGE-m3-ko, top 50) → RRF 융합 → [리랭커: 현재 꺼짐]
  │    → 문서 단위 집계(max) → 상위 10건(candidates)
  ▼
  │ ③ 문서별 판정 (LLM 1회, generation/generator.py + prompt.py)
  │    상위 judge_docs 건의 문서 전체를 주고, B와 같거나 유사한 문서만 matches 로 반환
  │    matches: doc_id, matched_target, reason, difference, applicable_to_target, level(same|similar), quote
  │    무관한 문서는 matches 에 넣지 않는다 (= none, 탈락)
  ▼
  │ ④ 코드 검증 (LLM이 아니라 코드가 결정)
  │    - quote 가 문서 원문에 실제로 있는가 (generation/validation.py)
  │    - applicable_to_target 이 false 이면 탈락
  │    - B·검색어와 분야 고유 글자쌍 겹침 ≥ min_term_overlap (generation/relevance.py)
  ▼
  GenerationResult  (verdict·has_match 는 검증을 통과한 매칭으로 코드가 정한다)
```

B가 비어 있으면 오류이며 원문 fallback은 없다. LLM 호출은 판정 1회다.

현재 설정 ([technology_rag.yaml](../app/technology_rag/configs/technology_rag.yaml))

| 항목 | 값 | 의미 |
|---|---|---|
| `rerank.enabled` | false | 리랭커 미사용(지연 0.03초→0.4초, VRAM +1.2GB를 고려해 선택). `hits[].rerank_score` 는 비어 있다 |
| `llm.model` | gpt-5.6-luna | 문서 판정 |
| `llm.judge_docs` | 10 | 판정하는 검색 상위 문서 수 (문서 전체를 LLM에 전달). 코드 기본값은 8 |
| `llm.min_term_overlap` | 2 | 일반 용어뿐인 고득점 후보를 차단하는 하한. 0이면 검사를 끈다 (6절 참고) |
| `llm.max_output_tokens` | 6000 | 판정 호출 출력 상한. 코드 기본값은 3000 |
| `llm.request_timeout_seconds` / `max_retries` | 60 / 0 | 단일 요청 대기 시간 / SDK 자동 재시도로 인한 중복 과금 방지 |

## 3. 설계 결정

| 구분 | 이전 | 현재 |
|---|---|---|
| 검색 질의 | 입력 문장 전체 (A 표현이 순위를 좌우) | **B + 동의어 검색어만** (A 제외) |
| 입력 분해 | RAG 내부 LLM 분해 (2회 호출) | **상류에서 분해해 A·B를 직접 입력** (1회 호출) |
| LLM이 보는 문서 | 상위 3건 | 상위 `judge_docs`(10)건, 문서 전체 |
| 판정 단위 | 답변 전체에 verdict 1개 | **문서별** same / similar (무관은 none) |
| `result.candidates` | 항상 상위 10건 | **매칭된 문서만** (0건일 수 있음) |
| verdict | LLM이 말한 값 | **검증을 통과한 매칭 기준** (same 있음→same, similar만→similar, 없음→none) |

## 4. 출력

`answer()` 는 `GenerationResult` 를 반환한다. Orchestrator는 그중 `.result`(ModuleResult)만 가져간다.

### 4.1 GenerationResult

| 필드 | 설명 |
|---|---|
| `has_match` | 검증을 통과한 same/similar 매칭이 하나라도 있는가 |
| `verdict` | `same` / `similar` / `none` — 문서 중 가장 높은 등급, **코드가 결정** |
| `llm_verdict`, `downgrade_note` | LLM이 말한 판정과, 코드 판정과 다를 때 사유 |
| `answer`, `gaps` | LLM 요약 답변, B 중 확인되지 않은 부분. 코드가 탈락시킨 문서를 `answer` 가 언급할 수 있다 |
| `tech_input` | 입력으로 받은 A·B·검색어 |
| `retrieval_query` | 실제 검색에 쓴 질의 (B + search_terms) |
| `references[]` | 매칭 1건마다 `doc_id, level, matched_target, why, difference, quote, ok, reason, section, page, bbox, search_rank`. `ok=False` 의 `reason`: `제공 안 한 문서`, `본문에 없음`, `너무 짧음`, `B의 적용 대상에 적용 불가`, `분야 고유 표현 불일치`. 그 밖에 `role`("직접 해결"/"부분 관련")도 담긴다 |
| `tech_elements[]` | LLM이 뽑은 기술요소와 인용 검증 결과 (`ok` = 인용 일치 **and** 매칭된 문서) |
| `dropped_doc_ids` | 판정 대상이었으나 매칭되지 않은 문서 |
| `provided_doc_ids`, `n_verified`, `unsupported_rate`, `usage` | 판정 대상 문서, 검증 통과 인용 수, 검증 실패 비율, 토큰·비용 |
| `dry_run`, `messages` | `dry_run=True` 이면 API 호출 없이 프롬프트만 만든다 (B로 검색한 결과로 프롬프트 생성) |

### 4.2 result (ModuleResult, 통합 계약)

- `query`: 실제 검색 질의 (B + search_terms).
- `candidates`: **매칭된 문서만**, same 먼저 그 안에서는 검색 순위순. 각 후보에
  `relation_summary` (`"[same] …"` 또는 `"[similar] …"` 로 시작), `evidences`(검증된 인용, 페이지·bbox), `tech_elements` 가 채워지고
  `extra["match_level"]` (same | similar), `extra["matched_target"]` (대응한 B 항목. B가 하나면 항상 그 항목, 여러 개일 때 LLM 값이 목록에 없으면 None)가 들어간다.
- `tech_elements`: 매칭된 문서의 검증된 기술요소.
- `hits`: 검색 청크 기록. **필터링하지 않는다** (탈락한 문서의 청크도 남는다).
- `stats` 에 추가된 키:

```python
stats["retrieval_query"]  # 실제 검색 질의
stats["tech_input"]       # 입력 A·B·검색어 dict
stats["generation"] = {"model", "verdict", "llm_verdict", "n_judged", "n_matched", "n_dropped",
                       "n_refs", "n_verified", "cost_usd"}
stats["match"] = {
    "has_match": bool,
    "verdict": "same" | "similar" | "none",
    "targets": ["<B>", ...],
    "items": [{"doc_id", "level": "same" | "similar", "title", "matched_target"}],  # 남은 문서, same 먼저
    "none": [{"doc_id", "title", "level": "none", "reason"}],   # 판정했으나 매칭되지 않은 문서와 사유
    "dropped": ["doc_id", ...],
    "dropped_titles": [{"doc_id", "title"}],
    "rejected": [{"doc_id", "level", "reason"}],                # LLM은 매칭이라 했으나 코드 검증에서 탈락
    "judgments": [{"doc_id", "level", "reason"}],               # 문서별 LLM 판정 기록
    "unlisted": ["doc_id", ...],                                # 판정은 same/similar 인데 matches 에 없어 버려진 문서
}
```

`none[].reason` 은 `LLM 미선택(B와 관련 없음)` 또는 `검증 탈락: <사유>` 이다.
Gap·최종 답변이 결과를 구조적으로 읽으려면 `state.technology.stats["match"]` 를 쓰면 된다.

```python
r = pipe.answer(
    ["폐열을 회수하는 폐열 회수시스템 기술"],        # 보유기술 A (문자열 하나도 가능)
    "터빈 발전 및 열교환 연동 제어 기술",            # 원하는 기술 B (목록도 가능)
    search_terms=["ORC 터빈 발전", "열교환 연동 제어"],  # 선택
)
r.verdict                       # same | similar | none
r.result.candidates[0].extra    # {"match_level": "same", "matched_target": "..."}
r.result.stats["match"]["none"] # 탈락 문서와 사유
```

## 5. 시험 방법

```
python -X utf8 -m tests.tech_rag          # 케이스 전체 (Supabase 접속, OPENAI_API_KEY 필요)
python -X utf8 -m tests.tech_rag 3 4      # 번호(0부터)로 일부만
```

[tests/tech_rag.py](../tests/tech_rag.py) (현재 9케이스) 는 케이스를 `owned`(A 목록)와 `target`(B)으로 적는다.
케이스마다 문서별 `[same]/[similar]` 와 대응 B 항목, 차이점, 코드 탈락 사유, `none` 문서와 사유를 출력하고
정답(gold)·has_match 기대를 PASS/FAIL 로 표시한다. 정답 표기: SHARE-N → `pub-2026-N`, POSCO-N → `pos-2025-N`.
검색 후보 풀(pool)·top-k 비교는 `tests/tech_pool_eval.py`, `tests/tech_topk_eval.py` 를 사용한다.

## 6. 시험 이력 (질의 분해 제거 이전 구현 기준)

> 아래는 2026-10-15, **RAG 내부 질의 분해와 full/similar 등급을 쓰던 구현**의 시험이다.
> 분해 제거 이후 같은 시험은 재측정하지 않았다. 등급 이름(full → same)과 분해 관련 항목은 현재와 다르며,
> 판정·검증 계층에서 확인된 한계(약한 similar 후보, 실행마다 달라지는 판정)는 현재도 유효하다.

케이스: ① ORC 터빈 연동 제어 (정답 pos-2025-113) ② 제설로봇 작업부 압력 (pub-2026-113)
③ 히트펌프-데시컨트 통합 (pub-2026-170/172/173) ④ 피복결함→누수 검지 (pub-2026-190, pos-2025-288)
⑤ 이형철근 치수 측정·보정 (pos-2025-208) ⑥ 가열로 연소 제어 (pos-2025-113) ⑦ 무관 주제 (has_match=False 기대)

| 실행 | 설정 | 정답 포착 | 케이스당 남은 문서 (①~⑦) |
|---|---|---|---|
| 1회차 | `min_term_overlap: 2` | 6/9 | 2, 1, 3, 3, 2, 3, 0 |
| 2회차 | `min_term_overlap: 0` | 8/9 | 3, 1, 5, 3, 2, 5, 0 |
| 3회차 | `min_term_overlap: 0` + `similar` 기준 완화 | 8/9 | 3, 1, 4, 2, 3, 4, 0 |

**확인된 것**
- 정답 9건은 모두 검색 상위 10건 안에 있었다 (검색 재현율 9/9). 놓친 것은 모두 판정 단계에서 발생했다.
- 무관 쿼리(⑦)는 `has_match=False`. 검색이 무관한 문서를 가져와도 판정 단계가 모두 걸러냈다.
- 비용은 쿼리당 약 $0.002~0.004 (당시 단가 설정 기준 추정치).

**문제로 확인된 것**
1. **분야 겹침 검사(`min_term_overlap: 2`)가 정답을 탈락시켰다.** LLM이 similar로 본 pub-2026-172와 pos-2025-208이
   "분야 고유 표현 불일치"로 탈락했다 (제목이 일반적이면 글자쌍이 겹치지 않는다). 이 검사가 오탐을 막은 사례는 없어 당시 `0`으로 시험했다.
   현재 yaml은 다시 2이며, 이 설정으로 재측정한 결과는 없다.
2. **검사를 끈 뒤 약한 후보가 늘었다.** LLM 자신이 차이점에 "폐열 회수·연소 제어는 명시하지 않는다"고 쓰고도 similar로 남긴 문서가 있었다. 정밀도와 재현율은 맞바꿈 관계다.
3. **판정이 실행마다 달라진다.** `seed` 가 best-effort이고 판정이 LLM이라 한 번의 실행으로 포착률을 단정할 수 없다.
   (당시에는 분해된 B의 문구가 매번 달라지는 것도 원인이었으나, 입력 고정으로 이 원인은 없어졌다.)
4. **경계선 정답이 번갈아 빠진다.** B와의 연결이 간접적인 문서(`pos-2025-208`, `pos-2025-288`)는 실행마다 포착·탈락이 바뀐다.
5. **같은 약한 후보가 반복해서 남는다.** "열교환기", "배가스" 같은 키워드가 걸려 포함되는 것으로 보이며, "핵심 기능이 없으면 뺀다"는 규칙을 LLM이 일관되게 지키지 않는다.
6. **same/similar 경계가 불안정하다.** "있음/없음"만 쓴다면 문제가 없지만, 동일과 유사를 다르게 취급하려면 기준을 더 다듬어야 한다.

**개선 후보 (미구현)**
- 판정 스키마에 `core_function_stated: bool` (문서가 B의 핵심 기능을 명시적으로 서술하는가)을 추가해, 핵심 기능이 없으면 코드가 탈락시킨다.
- 같은 쿼리를 2~3회 실행해 합의(교집합 또는 다수결)로 안정화한다.
- 정답이 확실한 케이스를 늘려 `tests/tech_rag.py` 의 `CASES` 에 추가한다.

## 7. 통합·Gap 분석 시 고려사항

1. **`state.technology.candidates` 가 매칭된 문서만 남는다 (0건 가능).**
   `gap_analysis.build_pool` 은 이 후보로 기술나눔 비교 풀을 만들므로 풀이 줄어든다.
   RFP가 B가 아닌 다른 기술을 요구해도 그에 맞는 나눔기술은 풀에 없어 "외부기술보완"으로 판정되지 않는다. B 집중 목적에는 맞으나 RFP 전체 비교 용도로는 손해다.
2. **Gap은 `match_level`(same/similar)과 `has_match` 를 직접 읽지 않는다.** Orchestrator가 `.result` 만 보관하므로
   구분이 필요하면 `candidates[].extra["match_level"]` 또는 `state.technology.stats["match"]` 를 읽는 코드를 `gap_analysis.py` 에 추가해야 한다 (미구현).
   현재 `candidates[].extra["match_level"]` 을 읽는 곳은 `analysis_view.py` (화면용 `match_level` 필드)뿐이고, `stats["match"]` 는 `app` 안에서 아무도 읽지 않는다.
3. **하위 단계 질의 확장이 좁아진다.** `_cascade_elements` 가 `candidates[].tech_elements` 를 NTIS 입력·RFP 질의 확장에 쓰므로 매칭된 문서의 요소만 쓰인다.
   매칭이 없으면 "검증된 기술요소가 없어 Query 확장을 생략" 경고가 나온다. similar 문서의 요소도 확장에 들어가므로 약한 후보(6절 2번)가 RFP 질의를 오염시킬 수 있다.
4. **경고 문구가 실제와 다르다.** 매칭이 없으면 Orchestrator는 "technology: 검색 후보가 없습니다", Gap은 "비교할 기술나눔 후보가 없어…"를 띄운다.
   검색 실패가 아니라 "매칭 없음"이므로 문구 조정이 필요하다.
5. **Orchestrator 연동:** `_technology_answer` 가 `answer(owned_technologies, targets or query)` 로 A와 B를 따로 넘긴다.
   `run()` 은 `targets=request.unmet_elements`, 없으면 `[request.problem]` 을 넘기므로 실제 B는 확보하려는 기술 목록 또는 기술문제 원문이다.
   `query`(보유기술+문제 baseline)는 `targets` 가 비어 있을 때만 쓰이며 `run()` 경로에서는 쓰이지 않는다. `search_terms` 는 넘기지 않아 항상 비어 있다.
6. **B가 여러 개일 때 판정 규칙:** 문서가 B 항목 중 하나 이상에 대응하면 매칭으로 본다. 전부 충족해야 하는지는 팀 결정 사항이다.
7. 리랭커가 꺼져 있어 `hits[].rerank_score` 는 None이다. `final_rank` 정렬에는 영향이 없다.
8. `price_per_1m_input/output` 기본값은 `gpt-5.6-luna`의 입력 $0.20·출력 $1.20/100만 토큰이다. `usage.cost_usd`는 캐시 읽기·쓰기 단가를 구분하지 않는 단순 추정치다.
9. `answer` 텍스트는 코드가 탈락시킨 문서를 언급할 수 있다. 판정은 `has_match`·`candidates`·`stats["match"]` 를 기준으로 본다.

## 8. 현재 한계 요약

- `tests/tech_rag.py` 에 케이스가 9건(6절의 7건 + 계류 체인 제어, 배관 결함 비파괴 탐상)이나, 분해 제거 이후에는 재측정하지 않았다. 재현율은 정답이 1~3건인 케이스만으로 측정했다.
- 판정은 LLM의 의미 판단에 의존하며 실행마다 달라질 수 있다.
- `min_term_overlap` 은 켜면 정답을 놓치고 끄면 약한 후보가 섞인다. 현재 설정(2)으로 재측정한 결과는 없다.
