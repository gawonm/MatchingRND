# NTIS / RFP LLM 호출 최적화

2026-10-16. Gap, Tech, 최종답변 및 답변 스키마는 변경하지 않았다.

## 변경 방식

- 기존: 후보마다 보유기술 / 요청기술을 한 기술씩 개별 호출했다.
- 변경: 한 기술을 비교하는 방식은 유지하고, 서로 독립적인 후보 최대 5개를 한 호출에 넣는다.
  각 후보의 원문, 판정, 인용문은 분리한다. 후보 순위와 선별 기준은 그대로다.
- 보유기술 하나 이상과 명시적인 요청기술 전부가 동일/유사이며 원문 근거가 검증되어야 통과한다.
  한쪽이 무관하거나 근거가 부족하면 제외하며, 통과 후보가 없으면 관련 과제/공고 없음으로 반환한다.
- 중복 후보는 한 번만 검증한다. 이미 적용된 중복 제거를 유지한다.
- 기본 묶음당 입력 JSON은 합계 24,000자 이내로 제한한다. 넘으면 묶음을 나누며 원문을 자르지 않는다.
  후보 하나가 한도를 넘으면 해당 후보를 단독으로 검증한다.
- 묶음 응답 형식 오류, 후보 번호 누락/중복/범위 오류는 해당 묶음을 개별 호출로 재검증한다.
  API 연결 오류는 검색 결과 없음으로 숨기지 않는다.
- 동일 요청은 디스크 캐시를 재사용한다. 모델, 프롬프트, 스키마, 입력 원문이 달라지면 새로 검증한다.
  캐시는 `storage/llm_cache/ntis_relevance`, `storage/llm_cache/rfp_relevance`에 저장된다.
  캐시는 정확히 같은 요청 묶음에 적용되며, 후보 순서/묶음이 달라지면 다시 호출할 수 있다.

## 수정 파일

| 파일 | 역할 |
| --- | --- |
| `app/common/relevance_batch.py` | NTIS/RFP 전용 묶음 호출, 응답 번호 검사, 개별 호출 대체, 호출/캐시 계측 |
| `app/ntis_rag/retrieval/eligibility.py` | 기술별 여러 NTIS 원문을 묶어서 판정하고 각 과제 원문 인용 검증 |
| `app/ntis_rag/pipeline.py` | 검색 순서대로 후보 묶음 검증 및 NTIS 전체 호출 수 노출 |
| `app/ntis_rag/generation/analysis.py` | 질의 구조화·기술 추출·정규화·연구축 호출 계측만 추가 |
| `app/rfp_rag/retrieval/eligibility.py` | 기술별 여러 RFP 요구사항을 묶어서 판정하고 각 과제 원문 인용 검증 |
| `app/rfp_rag/retrieval/pipeline.py` | 검색 순서대로 후보 묶음 검증 |
| `app/rfp_rag/scripts/try_search.py` | 임시 테스트에도 캐시 적용, 실제 API 호출/캐시 횟수 표시 |

공유 Gap LLM 클라이언트는 기존 캐시 기능을 재사용할 뿐 해당 파일을 수정하지 않는다.
NTIS 기술 추출/정규화/연구축 생성 알고리즘, 임베딩 및 검색 모델은 변경하지 않는다.

## 검증한 호출 수

### 같은 후보·판정으로 비교한 자동 테스트 (API 모의 응답)

보유기술 1개 + 요청기술 1개. RFP 후보 32개, NTIS 후보 20개를 끝까지 검증하고 각각 마지막 2개가 통과하는 조건이다.
묶음 크기 1(기존 호출 방식)과 5를 실제 파이프라인에 적용해 비교했다.

| 구간 | 기존 | 변경 | 감소 |
| --- | ---: | ---: | ---: |
| RFP 관련성 검증 | 64 | 14 | 78.1% |
| NTIS 관련성 검증 | 40 | 8 | 80.0% |
| NTIS 그 외: 질의 1 + 추출 2 + 정규화 1 + 연구축 1 | 5 | 5 | 변경 없음 |
| NTIS 합계 | 45 | 13 | 71.1% |
| 두 모듈 합계 | 109 | 27 | 75.2% |

반환 후보와 순위, NTIS 원문 근거 및 추출·연구축 결과가 같음을 검사한다.
이는 호출 구조를 검증하는 고정 데이터 테스트이며 실제 DB 검색 전체의 정확도나 실서비스 고정 호출 수를 뜻하지 않는다.

### 실제 LLM 예시 검증

SLAM 위치추정 보유기술 + LiDAR 장애물 인지 요청기술에 대해 동일/유사/무관 원문 조합 9개를 각 모듈에 입력했다.
NTIS/RFP 각각 관련성 검증은 개별 방식이면 18회인 입력을 실제 API 4회로 처리했다 (77.8% 감소).
두 모듈 모두 동일·유사 조합 4개만 통과하고 무관 조합 5개를 제외했다.
같은 입력을 새 gate 인스턴스로 재실행하면 각 모듈의 관련성 API 호출은 0회, 캐시 적중은 4회였다.

첫 묶음 프롬프트에서는 RFP 유사/유사 조합 하나가 누락되어, 후보별 원문을 새로 읽고 독립적으로 판단하도록 지시를 보완했다.
보완 후 위 9가지 검사를 통과했다. LLM 결과는 호출 방식 변경으로 달라질 수 있으며 이 검사는 전체 도메인의 정확도 보증이 아니다.
실제 실행 기록은 로컬 `outputs/relevance_batch_live_20261016.json`에 저장했다.

## 실제 실행 횟수 확인

- NTIS `run_ntis_pipeline()` 결과: `diagnostics.llm_usage`에 단계별 횟수와 `total`이 있다.
  `run_ntis_module()`에서는 `result.extra['diagnostics']['llm_usage']`로 접근한다.
- NTIS/RFP 공통: `diagnostics.technology_relevance.llm_usage`의 `api_calls`, `cache_hits`,
  `llm_requests`, `fallback_requests`를 확인한다. 공통 ModuleResult에서는 `extra` 아래에 있다.
- `api_calls`는 관련성 클라이언트 호출 수로 SDK 내부 네트워크 재시도는 따로 세지 않는다.
  NTIS 그 외 단계는 `llm.invoke` 시도 횟수이며 기술 추출 재시도도 포함한다.
- 긴 원문으로 묶음이 나뉘거나 개별 재검증이 발생하면 호출 수가 늘 수 있다.
  필요한 결과 수를 채운 마지막 묶음도 끝까지 검증하므로 최대 4개의 후보를 더 판정할 수 있다.
  따라서 후보 수가 적거나 초반에 통과하는 검색은 감소 폭이 작거나 없을 수 있다.

## 설정 / 회귀 테스트

기본값은 `NTIS_RELEVANCE_BATCH_SIZE=5`, `RFP_RELEVANCE_BATCH_SIZE=5`,
`NTIS_RELEVANCE_MAX_CHARS=24000`, `RFP_RELEVANCE_MAX_CHARS=24000`이다.
호출 비교 시 묶음 크기를 1로 지정하면 개별 호출 방식으로 실행할 수 있다.
임베딩을 다시 만들 필요는 없다.

```powershell
.venv-gpu/Scripts/python.exe -m unittest discover -s tests -p test_relevance_batching.py
.venv-gpu/Scripts/python.exe -m unittest discover -s tests -p 'test_ntis*.py'
.venv-gpu/Scripts/python.exe -m unittest discover -s tests -p 'test_rfp_*.py'
.venv-gpu/Scripts/python.exe -m unittest discover -s tests -p test_orchestrator.py
```

`test_relevance_batching.py`는 후보 순서 유지, 누락/중복/범위 오류 대체 호출, 응답 파싱 실패 대체 호출,
원문 길이 제한, 다른 후보 원문 도용 차단, 캐시/원문 변경, NTIS 단계별 재시도 계측과 위 호출 수를 검증한다.
