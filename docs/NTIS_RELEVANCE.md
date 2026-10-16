# NTIS 과제의 A/B 관련성 검증

NTIS 검색 결과는 검색 점수만으로 반환하지 않습니다. Hybrid/Reranker로 찾은 과제에
대해 LLM이 같은 과제 원문을 기준으로 보유기술 A와 보완 요청 B를 각각 판정합니다.
로컬 인덱스와 Supabase 모두 동일한 검증 파이프라인을 사용합니다.

- `same`: 동일 기능·적용대상의 기술을 개발·사용·연구합니다.
- `similar`: 기능·적용대상이 대응하거나 관련된 일부 기능·구성요소가 명시됩니다.
- `different`, `insufficient`: 미매칭 또는 근거부족으로 제외합니다.

동일·유사·부분매칭의 의미 판단은 LLM이 담당합니다. 코드는 키워드 겹침이나 검색 점수로
유사성을 판정하지 않고, 판정 형식과 인용문이 해당 과제 원문에 존재하는지 검증합니다.
인용문은 공백·줄바꿈 차이만 허용합니다. 실제 의미 판단의 정확성은 LLM 평가가 필요합니다.

## 입력과 통과 조건

`run_ntis_module(problem, owned_technologies=[...], requested_technologies=[...],
external_technologies=[...])`를 사용합니다. 보유기술은 하나 이상, 명시한 보완 요청은
모든 항목이 `same` 또는 `similar`이고 원문 근거가 검증되어야 통과합니다.
여러 보유기술 중 하나 이상을 요구하는 규칙은 RFP 명세와 같습니다.

`requested_technologies`가 없으면 원래 `problem`을 B의 판정 대상으로 사용합니다.
기업 입력의 `unmet_elements`는 Orchestrator에서 `requested_technologies`로 전달합니다.
외부기술은 검색 확장 문맥이며 원래 B를 대신하지 않습니다. 기술나눔 매칭이 없어도
원래 A와 B로 NTIS 검색·검증을 진행합니다. A 또는 과제 원문이 없으면 통과시키지 않습니다.

A와 B가 매칭된 과제에 추가 기술 C가 포함되어도 제외하지 않습니다. 추가 기술의
충족 여부는 후속 Gap 분석에서 판단하며, NTIS 사례 자체가 R&D 필요의 확정 근거는 아닙니다.

## 결과와 오류

`analysis_top_n`은 통과한 과제 수의 상한입니다. 최대 `max(NTIS_RERANK_CANDIDATES,
analysis_top_n)`개의 검색 후보를 받아 순서대로 검사하므로 앞의 미매칭 과제가 결과 수를
차지하지 않습니다. 검색 후보 풀 밖까지 무제한 재검색하지는 않습니다.

탈락 과제는 `related_projects`, `candidates`, `hits`, 기술요소 추출 및 질의 확장에서 제외됩니다.
통과 과제는 추가 요구기술을 포함한 원문을 보존합니다. 판정은
`extra.diagnostics.technology_relevance`와 후보의 `extra.technology_relevance`에 기록합니다.
통과 결과가 없으면 `extra.status == 'no_matches'`입니다.

LLM의 판정 형식이 잘못되거나 인용 근거가 없으면 통과시키지 않습니다. API 오류는
후보를 그대로 반환하지 않고 상위 호출에 전달합니다. 모델은 `NTIS_RELEVANCE_MODEL`,
미설정 시 기존 `NTIS_LLM_MODEL`을 사용합니다. 과제마다 A/B 항목 수만큼 LLM 호출이 추가됩니다.

검증: `python -B -X utf8 -m unittest tests.test_ntis_relevance tests.test_orchestrator`
모의 LLM·검색 결과로 양쪽 매칭 조합, 원문 검증, 외부기술 미매칭 시 진행,
추가 C 보존, 양쪽 백엔드의 결과 제외 및 후속 단계 유입 차단을 검사합니다.
