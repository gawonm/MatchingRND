# Technology RAG (기술나눔 검색) — 동작·출력·통합 시 주의사항

작성 기준일: 2026-10-15. 대상 코드: `app/technology_rag/`.
이 문서는 Technology RAG가 현재 어떻게 동작하고 무엇을 돌려주는지, 이전 구현에서 무엇이 바뀌었는지,
Orchestrator·Gap 분석과 통합할 때 고려할 점, 그리고 2026-10-15 시험 결과를 정리한다.

## 1. 무엇을 하는 모듈인가

사용자 입력은 다음 형태의 자연어 한 문장이다.

> "우리는 **A 기술**을 가지고 있는데 **X**를 개발하고자 한다. 이를 위해 **B 기술**을 확보하고자 하는데, 관련 나눔기술과 공고가 있을까?"

Technology RAG의 목표는 **B와 같거나(full) 유사한(similar) 기술나눔 문서가 있는지**를 답하는 것이다.
B와 무관한 문서는 결과에서 **탈락**시킨다. 보유기술(A)과 비슷하다는 이유로는 문서를 고르지 않는다.

## 2. 동작 흐름

`TechnologyRagPipeline.answer(query)` ([pipeline.py](../app/technology_rag/pipeline.py))

```
query(사용자 문장 또는 "보유기술: …\n기술문제: …")
  │ ① 질의 분해 (LLM 1회, generation/query_analysis.py)
  │    → owned_technologies(A), goal, target(B), search_terms
  │    실패하면 입력 문장 전체로 검색 (query_analysis=None)
  ▼
  │ ② 검색 (search): B + 검색어로만 질의
  │    BM25(Kiwi, top 50) + Dense(BGE-m3-ko, top 50) → RRF 융합 → [리랭커: 현재 꺼짐]
  │    → 문서 단위 집계 → 상위 10건(candidates)
  ▼
  │ ③ 문서별 판정 (LLM 1회, generation/generator.py + prompt.py)
  │    상위 judge_docs(10)건의 문서 전체를 주고, B와 같거나 유사한 문서만 matches 로 반환
  │    matches: doc_id, reason, difference, applicable_to_target, level(full|similar), quote
  │    무관한 문서는 matches 에 넣지 않는다 (= 탈락)
  ▼
  │ ④ 코드 검증 (LLM이 아니라 코드가 결정)
  │    - quote 가 문서 원문에 실제로 있는가 (generation/validation.py)
  │    - applicable_to_target 이 false 이면 탈락
  │    - (옵션) B·검색어와 분야 고유 글자쌍 겹침 ≥ min_term_overlap (generation/relevance.py)
  ▼
  GenerationResult  (verdict·has_match 는 검증을 통과한 매칭으로 코드가 정한다)
```

현재 설정 ([technology_rag.yaml](../app/technology_rag/configs/technology_rag.yaml))

| 항목 | 값 | 의미 |
|---|---|---|
| `rerank.enabled` | false | 리랭커 미사용. `hits[].rerank_score` 는 비어 있다 |
| `llm.model` | gpt-5.6-luna | 질의 분해와 문서 판정 모두 |
| `llm.judge_docs` | 10 | 판정하는 검색 상위 문서 수 (문서 전체를 LLM에 전달) |
| `llm.analyze_query` | true | 질의 분해 사용 여부 |
| `llm.min_term_overlap` | 0 | 분야 겹침 검사 끔 (아래 6절 참고) |
| `llm.max_output_tokens` | 3000 | 판정 호출 출력 상한 (분해 호출은 800) |

## 3. 이전 구현과 달라진 점

| 구분 | 이전 | 현재 |
|---|---|---|
| 검색 질의 | 입력 문장 전체 (A 표현이 순위를 좌우) | **B + 동의어 검색어만** (A 제외) |
| LLM이 보는 문서 | 상위 3건 | 상위 `judge_docs`(10)건 |
| 판정 단위 | 답변 전체에 verdict 1개 | **문서별** full / similar (무관은 목록에서 제외) |
| `result.candidates` | 항상 상위 10건 | **매칭된 문서만** (0건일 수 있음) |
| verdict | LLM이 말한 값, 검증된 근거 0이면 강등 | **검증을 통과한 매칭 기준** (full 있음→answerable, similar만→partial, 없음→no_answer) |
| LLM 호출 | 1회 | 2회 (분해 + 판정) |

변경 파일: `config.py`, `configs/technology_rag.yaml`, `pipeline.py`, `generation/{__init__,generator,llm,prompt,schemas}.py`,
신규 `generation/query_analysis.py`, `generation/relevance.py`. 공용 스키마(`app/common/schemas.py`)·Orchestrator·Gap은 수정하지 않았다.
`search()` 는 바꾸지 않았다 (검색 평가 스크립트 영향 없음).

참고: 같은 작업 트리에는 이 작업 이전의 미커밋 변경도 있다 (모델 `gpt-5.6-luna`, `temperature: null`, `rerank.enabled: false`).

## 4. 출력 (정확한 형태)

`answer()` 는 `GenerationResult` 를 반환한다. Orchestrator는 그중 `.result`(ModuleResult)만 가져간다.

### 4.1 GenerationResult (Tech RAG 전용 필드 포함)

| 필드 | 설명 |
|---|---|
| `has_match` | 검증을 통과한 full/similar 매칭이 하나라도 있는가 |
| `verdict` | `answerable`(full 있음) / `partial`(similar만) / `no_answer`(없음) — **코드가 결정** |
| `llm_verdict`, `downgrade_note` | LLM이 말한 판정과, 코드 판정과 다를 때 사유 |
| `answer`, `gaps` | LLM 요약 답변, B 중 확인되지 않은 부분. 코드 탈락한 문서를 `answer` 가 언급할 수 있다 |
| `query_analysis` | 분해 결과 `{owned_technologies, goal, target, search_terms}` (실패·비활성이면 None) |
| `retrieval_query` | 실제 검색에 쓴 질의 (`target` + `search_terms`) |
| `references[]` | 매칭 1건마다 `doc_id, level, why, difference, quote, ok, reason, section, page, bbox, search_rank`. `ok=False` 의 `reason`: `본문에 없음`, `너무 짧음`, `B의 적용 대상에 적용 불가`, `분야 고유 표현 불일치` |
| `tech_elements[]` | LLM이 뽑은 기술요소와 인용 검증 결과 (`ok` = 인용 일치 **and** 매칭된 문서) |
| `dropped_doc_ids` | 판정 대상이었으나 매칭되지 않은 문서 |
| `provided_doc_ids`, `n_verified`, `unsupported_rate`, `usage` | 판정 대상 문서, 검증 통과 인용 수, 검증 실패 비율, 토큰·비용 |
| `dry_run`, `messages` | `dry_run=True` 이면 API 호출 없이 프롬프트만 만든다 (질의 분해도 건너뛴다) |

### 4.2 result (ModuleResult, 통합 계약)

- `query`: **사용자 입력 원문**. (계약 문구는 "실제 실행된 최종 query"이나, 실제 검색 질의는 `stats["retrieval_query"]`)
- `candidates`: **매칭된 문서만**, full 먼저 그 안에서는 검색 순위순. 각 후보에
  `relation_summary` (`"[동일] …"` 또는 `"[유사] …"` 로 시작), `evidences`(검증된 인용, 페이지·bbox), `tech_elements` 가 채워진다.
- `tech_elements`: 매칭된 문서의 검증된 기술요소.
- `hits`: 검색 청크 기록. **필터링하지 않는다** (탈락한 문서의 청크도 남는다).
- `stats` 에 추가된 키:

```python
stats["retrieval_query"]  # 실제 검색 질의
stats["query_analysis"]   # 분해 결과 dict 또는 None
stats["generation"] = {"model", "verdict", "llm_verdict", "n_judged", "n_matched", "n_dropped",
                       "n_refs", "n_verified", "cost_usd"}
stats["match"] = {
    "has_match": bool,
    "target": "<분해된 B>" | None,
    "items": [{"doc_id", "level": "full" | "similar", "title"}],   # 남은 문서, full 먼저
    "dropped": ["doc_id", ...],                                    # 판정했으나 탈락
    "dropped_titles": [{"doc_id", "title"}],
    "rejected": [{"doc_id", "level", "reason"}],                   # LLM은 매칭이라 했으나 코드 검증에서 탈락
}
```

Gap·최종 답변이 Tech RAG 결과를 구조적으로 읽으려면 `state.technology.stats["match"]` 를 쓰면 된다
(Orchestrator가 `.result` 를 그대로 보관하므로 별도 수정이 필요 없다).

## 5. 시험 방법

```
python -X utf8 -m tests.tech_rag          # 7개 케이스 전체 (Supabase 접속, OPENAI_API_KEY 필요)
python -X utf8 -m tests.tech_rag 3 4      # 번호(0부터)로 일부만
```

[tests/tech_rag.py](../tests/tech_rag.py) 는 케이스마다 분해 결과, 남은 문서(full/similar)와 차이점, 코드 탈락 사유,
탈락 문서 제목을 출력하고 정답(gold)·has_match 기대를 PASS/FAIL 로 표시한다. 마지막 줄에 요약이 나온다.
정답 표기: SHARE-N → `pub-2026-N`, POSCO-N → `pos-2025-N`.

## 6. 2026-10-15 시험 결과와 분석

케이스: ① ORC 터빈 연동 제어 (정답 pos-2025-113) ② 제설로봇 작업부 압력 (pub-2026-113)
③ 히트펌프-데시컨트 통합 (pub-2026-170/172/173) ④ 피복결함→누수 검지 (pub-2026-190, pos-2025-288)
⑤ 이형철근 치수 측정·보정 (pos-2025-208) ⑥ 가열로 연소 제어 (pos-2025-113) ⑦ 무관 주제 (has_match=False 기대)

| 실행 | 설정 | 정답 포착 | 케이스당 남은 문서 (①~⑦) |
|---|---|---|---|
| 1회차 | `min_term_overlap: 2` | 6/9 | 2, 1, 3, 3, 2, 3, 0 |
| 2회차 | `min_term_overlap: 0` | 8/9 | 3, 1, 5, 3, 2, 5, 0 |
| 3회차 | `min_term_overlap: 0` + `similar` 기준 완화 (프롬프트 3·4번) | 8/9 | 3, 1, 4, 2, 3, 4, 0 |

**확인된 것**
- 질의 분해는 7/7에서 A와 B를 올바르게 나눴고 검색 질의에 보유기술이 섞이지 않았다.
- 정답 9건은 모두 검색 상위 10건 안에 있었다 (검색 재현율 9/9). 놓친 것은 모두 판정 단계에서 발생했다.
- 무관 쿼리(⑦)는 `has_match=False`. 검색이 무관한 문서를 가져와도 판정 단계가 모두 걸러냈다.
- 비용은 쿼리당 약 $0.002~0.004 (단가 설정이 이전 모델 기준이라 추정치).

**3회차 (similar 기준 완화)**: 판정 프롬프트의 `similar` 를 "B를 이루는 기능·구성요소 중 하나 이상을 같은 산업·설비 영역에서 B의 목적에 쓸 수 있는 구조로 서술"로 넓히고,
"B의 나머지 기능이 없다는 이유만으로 빼지 말 것"을 추가했다. 결과는 아래와 같다.
- `pos-2025-208`(2회차에서 놓침)이 `similar` 로 포착됐다. 반면 `pos-2025-288`(2회차에서 포착)이 다시 탈락해 정답 포착은 8/9로 같다.
- 남은 문서 수는 늘지 않았다 (합계 23건 → 21건). 완화가 남는 문서를 눈에 띄게 늘리지는 않았다.
- 무관 쿼리(⑦)는 여전히 `has_match=False`.
- 정답 문서별 3회 결과 (1회차 / 2회차 / 3회차)

| 문서 | 1회차 | 2회차 | 3회차 |
|---|---|---|---|
| pub-2026-190 (④) | similar | full | similar |
| pos-2025-288 (④) | 탈락 | similar | 탈락 |
| pos-2025-208 (⑤) | 코드 탈락 | 탈락 | similar |
| pub-2026-172 (③) | 코드 탈락 | similar | similar |
| pub-2026-184 (④, 오답) | similar | 탈락 | 탈락 |

**문제로 확인된 것**
1. **분야 겹침 검사(`min_term_overlap: 2`)가 정답을 탈락시켰다.** LLM이 similar로 본 pub-2026-172와 pos-2025-208이
   "분야 고유 표현 불일치"로 탈락했다 (제목이 일반적이면 글자쌍이 겹치지 않는다). 이 검사가 오탐을 막은 사례는 없어 `0`(끔)으로 두었다.
2. **검사를 끈 뒤 약한 후보가 늘었다.** ⑥에서 남은 5건 중 정답은 1건이고 pos-2025-135(열교환기 튜브 파공 검출),
   pos-2025-186(마그네슘 제련) 등은 LLM 자신이 차이점에 "폐열 회수·연소 제어는 명시하지 않는다"고 쓰고도 similar로 남겼다.
   ③의 pub-2026-169(미세유량 제어)·pub-2026-167(흡수식 냉난방기)도 근거가 약하다. 정밀도는 낮다.
3. **판정이 실행마다 달라진다.** ④에서 1회차는 190=similar, 288 탈락, 184=similar였고 2회차는 190=full, 288=similar, 184 탈락이었다.
   분해된 B의 문구가 매번 조금 달라지고 판정도 LLM이라 `seed` 가 best-effort이기 때문이다. 한 번의 실행으로 포착률을 단정할 수 없다.
4. **경계선 정답이 번갈아 빠진다.** `pos-2025-208`("간격 보정 방법", 제목·내용이 일반적)과 `pos-2025-288`(지하 탱크 누출감지, 대상이 배관이 아닌 탱크)은
   실행마다 포착·탈락이 바뀐다 (위 표). 두 문서 모두 B와의 연결이 간접적이라 LLM 판단이 갈린다. 정답 9건(케이스별 집계) 중 3회 모두 포착된 것은 6건(172는 1회차에 겹침 검사 때문에 빠졌고 이후 포착), 번갈아 빠지는 것은 288과 208이다.
5. **같은 약한 후보가 반복해서 남는다.** `pos-2025-135`(열교환기 튜브 파공 검출)는 ORC 케이스(①)와 연소 케이스(⑥)에서 2·3회차 모두 similar로 남았고,
   `pos-2025-111`(워터씰형 열처리로), `pub-2026-178`(가스예열장치)도 LLM 자신이 차이점에 "폐열 회수·터빈 발전은 명시하지 않는다"고 쓰고도 남았다.
   "열교환기", "배가스" 같은 키워드가 걸려 포함되는 것으로 보인다. 완화된 기준에서도 "핵심 기능이 없으면 뺀다"는 규칙을 LLM이 일관되게 지키지 않는다.
6. **full/similar 경계가 불안정하다.** full은 ②(매 회차)와 ④(2회차만)에서만 나왔고 3회차에는 ②에서만 나왔다. "있음/없음"만 쓴다면 문제가 없지만, 동일과 유사를 다르게 취급하려면 기준을 더 다듬어야 한다.
7. 반대로 ⑥에서 pos-2025-235 ("연소 폐열을 활용한 열에너지 공급 방법")가 탈락한 것은 오탈락일 가능성이 있다 (확인 필요).

**개선 후보 (미구현)**
- 판정 스키마에 `core_function_stated: bool` (문서가 B의 핵심 기능을 명시적으로 서술하는가)을 추가해, 핵심 기능이 없으면 코드가 탈락시킨다.
- 같은 쿼리를 2~3회 실행해 합의(교집합 또는 다수결)로 안정화하거나, 분해 결과를 캐시한다.
- 정답이 확실한 케이스를 늘려 `tests/tech_rag.py` 의 `CASES` 에 추가한다.

## 7. 통합·Gap 분석 시 고려사항

1. **`state.technology.candidates` 가 매칭된 문서만 남는다 (0건 가능).**
   `gap_analysis.build_pool` 은 이 후보로 기술나눔 비교 풀을 만들므로 풀이 줄어든다.
   RFP가 B가 아닌 다른 기술을 요구해도 그에 맞는 나눔기술은 풀에 없어 "외부기술보완"으로 판정되지 않는다. B 집중 목적에는 맞으나 RFP 전체 비교 용도로는 손해다.
2. **Gap은 level(동일/유사)과 `has_match` 를 읽지 않는다.** orchestrator가 `.result` 만 보관하고, full/similar 구분은 `relation_summary` 접두어와 `stats["match"]` 에만 있다.
   B/유사B/매칭 안됨을 구분해 보여주려면 `gap_analysis.py` 에서 `state.technology.stats["match"]` 를 읽는 코드를 추가해야 한다 (미구현).
3. **하위 단계 질의 확장이 좁아진다.** `_cascade_elements` 가 `candidates[].tech_elements` 를 NTIS 입력·RFP 질의 확장에 쓰므로 매칭된 문서의 요소만 쓰인다.
   매칭이 없으면 "검증된 기술요소가 없어 Query 확장을 생략" 경고가 나온다. similar 문서의 요소도 확장에 들어가므로 약한 후보(위 6절 2번)가 RFP 질의를 오염시킬 수 있다.
4. **경고 문구가 실제와 다르다.** 매칭이 없으면 orchestrator는 "technology: 검색 후보가 없습니다", Gap은 "비교할 기술나눔 후보가 없어…"를 띄운다.
   검색 실패가 아니라 "매칭 없음"이므로 문구 조정이 필요하다 (이번에는 수정하지 않았다).
5. **B가 두 군데에서 정의된다.** Tech RAG는 문장에서 B를 스스로 분해하고, Orchestrator의 `request.unmet_elements` 는 RFP 질의 확장에만 쓰인다. 두 값이 다를 수 있다.
   `answer(query)` 가 문자열만 받아 `unmet_elements` 를 전달하지 않는다.
6. **Orchestrator가 Tech RAG에 보내는 문자열은 `"보유기술: …\n기술문제: …"` 형식이다.** 분해 프롬프트가 이 형식도 처리하지만 실제 통합 경로에서는 아직 시험하지 않았다 (시험은 자연어 한 문장으로 했다).
7. **`ModuleResult.query` 는 사용자 입력 원문**이다. 계약 설명("실제 실행된 최종 query")과 다르다. Orchestrator는 자체 baseline을 따로 기록하므로 현재 문제는 없다.
8. **LLM 호출이 2회로 늘어** 전체 분석 시간과 비용이 증가한다. 속도는 아직 측정하지 않았다.
9. **`hits` 는 필터링하지 않는다.** `gap_analysis._candidate_pool` 은 `module.candidates` 를 순회하므로 탈락한 문서는 풀에 들어오지 않는다.
10. 리랭커가 꺼져 있어 `hits[].rerank_score` 는 None이다. `final_rank` 정렬에는 영향이 없다.
11. `price_per_1m_input/output` 이 이전 모델(gpt-4o-mini) 기준이라 `usage.cost_usd` 는 참고용이다.
12. `dry_run=True` 는 질의 분해를 건너뛰고 입력 문장으로 검색한다 (B 기준 검색 결과를 볼 수 없다).
13. `answer` 텍스트는 코드가 탈락시킨 문서를 언급할 수 있다. 판정은 `has_match`·`candidates`·`stats["match"]` 를 기준으로 본다.

## 8. 현재 한계 요약

- 시험 쿼리가 7건뿐이라 일반화할 수 없다. 특히 재현율은 정답이 1~3건인 케이스만으로 측정했다.
- 판정은 LLM의 의미 판단에 의존하며 실행마다 달라질 수 있다.
- `min_term_overlap` 을 끈 상태에서는 약한 유사 후보가 섞인다. 정밀도와 재현율은 맞바꿈 관계이며 현재는 재현율을 우선한 설정이다.

---

## 9. 2026-10-16 변경: 분해된 입력 수신 + same / similar / none

> 1~8절은 이 변경 **이전** 동작(질의 분해 포함, full/similar, answerable/partial/no_answer)을 기록한 것이라 그대로 두었다.
> 현재 코드는 아래 내용을 따른다. 아래 변경 이후의 시험 결과는 아직 측정하지 않았다 (6절 수치는 이전 구현 기준).

### 9.1 한 줄 요약

팀 합의 흐름에서 입력은 상류에서 이미 보유기술(A)과 원하는 기술(B)로 나뉘어 온다. 그래서 Technology RAG 안의
**질의 분해(LLM 1회)를 삭제**하고, `answer()` 가 A·B 를 직접 받아 **B 에 대해서만** same / similar / none 으로 판정하도록 바꿨다.

### 9.2 무엇이 달라졌나

| 구분 | 변경 전 (1~8절) | 변경 후 |
|---|---|---|
| 호출 | `answer(query: str)` | `answer(owned, target, *, search_terms=None, ...)` |
| 입력 분해 | LLM 이 문장을 A / 개발목표 / B / 검색어로 분해 (실패하면 원문 전체로 검색) | **없음.** 입력으로 받은 A·B 를 그대로 사용. B 가 비면 오류 (원문 fallback 없음) |
| 검색 질의 | `target` + 분해 LLM 이 만든 동의어 `search_terms` | B(여러 개면 ` / ` 로 연결) + 호출자가 넘긴 `search_terms`(선택). 없으면 B 만 |
| 판정 프롬프트 입력 | B, 개발 목표, A, 사용자 입력 원문 | B 목록, A 목록 (개발 목표·원문 없음). A 는 계속 "매칭 근거 아님" |
| 문서별 등급 | `full` / `similar` (무관은 목록에서 빠짐) | `same` / `similar` / `none` |
| 전체 verdict | `answerable` / `partial` / `no_answer` | `same` / `similar` / `none` (문서 중 가장 높은 등급, 코드가 결정) |
| LLM 호출 수 | 2회 (분해 + 판정) | 1회 (판정) |
| `ModuleResult.query` | 사용자 입력 원문 | 실제 검색 질의 (계약 문구 "실제 실행된 최종 query" 와 일치) |
| `dry_run=True` | 분해를 건너뛰고 원문으로 검색 | B 로 검색한 결과로 프롬프트를 만든다 |
| 설정 | `llm.analyze_query` | 삭제 |

### 9.3 새로 생긴 출력

- `candidates[].extra["match_level"]`: `"same"` 또는 `"similar"`. 이전에는 `relation_summary` 앞의 "[동일]"/"[유사]" 문자열과 `stats["match"]` 에만 있었다.
- `candidates[].extra["matched_target"]`: 문서가 대응한 B 항목. B 가 하나면 그 항목, 여러 개면 LLM 이 고른 항목 (목록에 없는 값이면 `None`).
- `relation_summary` 접두어: `"[same] …"` / `"[similar] …"` (이전: `"[동일]"` / `"[유사]"`).
- `stats["match"]` 변경:
  - `target`(문자열) → `targets`(목록)
  - `verdict`, `items[].matched_target` 추가
  - `none`: 판정했지만 매칭되지 않은 문서와 사유 — `[{"doc_id", "title", "level": "none", "reason"}]`.
    `reason` 은 `LLM 미선택(B와 관련 없음)` 또는 `검증 탈락: <사유>` (인용이 본문에 없음 / B의 적용 대상에 적용 불가 / 분야 고유 표현 불일치).
  - `dropped`, `dropped_titles`, `rejected` 는 그대로 유지
- `GenerationResult.query_analysis` → `tech_input` (입력 A·B·검색어).
- LLM 응답 스키마 `DocMatch` 에 `matched_target` 필드가 추가되고 `level` 은 `same | similar` 가 되었다. 무관한 문서를 `matches` 에 넣지 않는 방식은 그대로다.

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

### 9.4 바뀌지 않은 것

검색(`search()`: BM25 + Dense + RRF, 리랭커 꺼짐, 문서 단위 집계), 청킹·인덱스, 판정 대상 문서 수(`judge_docs`),
인용의 원문 대조(`validation.py`), 분야 겹침 검사(`relevance.py`, 현재 `min_term_overlap: 0`), `applicable_to_target` 검사,
"verdict·has_match 는 LLM 이 아니라 검증을 통과한 매칭으로 코드가 정한다"는 원칙, `evidences`·`tech_elements` 생성, 사용 모델·비용 계산.
따라서 6절에서 확인된 한계(약한 similar 후보, 실행마다 달라지는 판정, 경계 문서)는 이번 변경으로 해결되지 않았다.
다만 "분해된 B 의 문구가 매번 달라진다"는 원인은 입력 고정으로 없어진다.

### 9.5 변경한 파일

`app/technology_rag/` 안에서만 수정했다.
`pipeline.py`, `config.py`, `configs/technology_rag.yaml`, `generation/{__init__,generator,prompt,schemas}.py` 를 고쳤고
`generation/query_analysis.py` 를 삭제했다. 시험 스크립트 `tests/tech_rag.py` 는 A·B 를 따로 적는 입력으로 바꿨다.

### 9.6 아직 따라가지 못한 곳 (이 폴더 밖)

- `app/orchestrator.py` 의 `_technology_answer` 는 여전히 `answer(query)` 에 합친 문자열을 넘긴다. 새 시그니처와 맞지 않아 통합 경로에서는 호출이 실패한다.
  `request.owned_technologies` 와 B(`unmet_elements` 등)를 따로 넘기도록 바꿔야 한다.
- 7절의 "B 가 두 군데에서 정의된다"(5번), "Orchestrator 가 보내는 문자열 형식"(6번), "dry_run 이 원문으로 검색한다"(12번)는 이번 변경으로 해소되는 항목이다. 단 오케스트레이터를 고치기 전에는 해소되지 않는다.
- B 가 여러 개일 때의 판정 규칙 (문서가 B 항목 중 하나만 충족해도 매칭으로 보는지, 전부 충족해야 하는지)은 팀 결정이 필요하다. 현재 구현은 "하나 이상 대응하면 매칭"이다.

### 9.7 시험 방법 변경

실행 방법은 5절과 같다 (`python -X utf8 -m tests.tech_rag`). 케이스는 문장 하나(`q`)가 아니라 `owned`(A 목록)와 `target`(B)으로 적는다.
출력에는 문서별 `[same]/[similar]` 와 대응 B 항목, `none` 문서와 사유가 추가되었다.
