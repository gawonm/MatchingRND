# RFP 기술 조합 관련성 필터

## 직접 입력하는 임시 테스트

프로젝트 루트의 PowerShell에서 실행합니다. 실제 RFP 인덱스와 LLM API를 사용합니다.

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv-gpu\Scripts\python.exe -m app.rfp_rag.scripts.try_search
```

보유기술, 요청 보완기술, 기술문제를 차례로 입력하세요. 여러 기술은 `;`로 구분합니다.
기본적으로 최대 3개 과제의 제목·원문 파일·연결된 공고 URL·LLM 비교 이유·검증한
인용문을 출력합니다. URL은 원 공고 연결 정보가 있을 때 표시합니다.
전체 결과는 `tmp/rfp-user-tests/rfp_search_시간.json`에 저장합니다.
계속 테스트할 때 `y`를 입력하면 준비한 RFP 인덱스를 재사용합니다.
기술별 LLM 비교 진행 로그는 기본으로 숨깁니다. 필요한 경우 실행 명령 끝에
`--verbose`를 붙이면 표시됩니다. 같은 기술명이 반복되는 것은 서로 다른 과제를
검토하기 때문이며, 이 진행 문구는 RFP 반환 데이터에 포함되지 않습니다.

백엔드는 `.env`의 `RAG_BACKEND`를 따르며, 없으면 로컬입니다.
`--backend local` 또는 `--backend supabase`로 선택할 수 있습니다.
로컬 첫 실행은 PDF 처리·인덱스 준비에 시간이 걸릴 수 있습니다.
Supabase는 기존 DB 접속 설정이 필요합니다. API/연결 실패는 검색 결과 없음과
구분하여 오류로 표시합니다.

```powershell
.\.venv-gpu\Scripts\python.exe -m app.rfp_rag.scripts.try_search --owned "SLAM 기반 이동로봇 위치 추정" --requested "LiDAR 기반 장애물 인지" --problem "이동로봇 충돌 방지" --top-k 3
```

이 테스트는 RFP 검색만 실행합니다. Tech·NTIS 검색, Gap 분석, 통합 최종답변 생성은
실행하지 않습니다. 다른 파트의 검색 결과를 흉내 내어 추가하지 않습니다.

## RFP 모듈 호출

보유기술과 요청 보완기술을 함께 검색할 때는 역할을 구분해서 전달합니다.

```python
from app.rfp_rag.pipeline import search_module_result
from app.rfp_rag.retrieval.query import build_query

details = build_query(
    ["SLAM 기반 자율주행"], "작업자 충돌 방지",
    unmet_elements=["LiDAR 객체 인지"], return_details=True,
)
result = search_module_result(index, details)
print(result.extra["message"])  # 통과 후보가 없으면 "관련 공고가 없습니다."
```

RFP 검색은 Hybrid/Reranker 순서로 후보를 찾은 뒤, LLM이 **같은 과제의 요구사항
원문**에서 보유기술과 요청기술 각각의 관련성을 `same`, `similar`, `different`,
`insufficient`로 판단합니다. 양쪽 모두 `same` 또는 `similar`이며 인용문이 원문에서
검증된 공고만 반환합니다. 같은 분야라는 이유만으로 통과시키지 않으며,
한쪽이라도 다른 기술이거나 근거가 부족하면 후보·검색 순위·답변 문맥에서 제외합니다.
탈락 후보 뒤의 공고도 확인하여 통과한 과제 기준으로 `top_k`를 채웁니다.

PDF 줄바꿈으로 문장이 여러 조각에 나뉜 경우에는 같은 과제·항목·페이지·출처의
연속 조각을 대조합니다. 공백·줄바꿈 차이만 허용하며, 중간 문장을 건너뛰거나 다른
페이지·항목·출처를 합쳐 인용을 통과시키지 않습니다. 검증에 사용한 원문 조각과
좌표는 각 판정의 `verified_sections`에 보존합니다.

보유기술 목록은 활용 가능한 기술 묶음이므로 하나 이상이 대응해야 하고, 사용자가
명시한 보완 요청은 모든 항목이 대응해야 합니다. 보완 요청을 별도로 전달하지 않으면
최초 `technical_problem`을 요청기술 B로 검사합니다. 외부기술 검색 결과가 없어도
이 검증은 꺼지지 않습니다. NTIS 확장이나 다른 외부기술이 원래 B를 대체할 수 없습니다.
보유기술이 없는 구조화 입력은 양쪽 관련성을 확인할 수 없으므로 통과시키지 않습니다.
최초 기술문제도 없이 외부 확장만 전달하는 기존 호출은 보유기술 하나 이상과
외부기술 하나 이상을 검사합니다.
`build_query()`의 문자열 반환값도 같은 검증을 적용합니다. 역할이 없는 일반 문자열
검색은 기존 키워드 검색으로 동작하므로, 기술 조합 검증에는 위 입력 방식을 사용하세요.

기본 LLM은 `gpt-5.6-luna`이며 `RFP_RELEVANCE_MODEL`로 변경할 수 있습니다.

같은 과제의 보유기술(A)과 요청기술(B)은 원문을 한 번만 보내 함께 판정합니다.
각 기술의 판정·인용은 독립적으로 검증하며, 기술 인덱스 누락·중복·범위 오류가
있으면 해당 후보를 통과시키지 않습니다. 요청기술 전체와 보유기술 중 하나 이상에
대한 원문 근거가 있어야 통과합니다.

기본 배치는 A/B 동시 판정, 최대 5개 과제, 토큰 기준 배치입니다.
2026-10-18 검증 결과와 전체 호출 절감 목적을 근거로 ②를 기본값으로 선택했습니다.
`RFP_RELEVANCE_BATCH_MODE=tokens`의 추정 입력 예산은 기본 32,000토큰입니다.
① 문자 기준 배치로 비교하거나 되돌리려면 `RFP_RELEVANCE_BATCH_MODE=chars`를 사용합니다.
명시 정답 회수는 두 방식 모두 3/6이었지만 품질 동등성을 입증하지는 않았습니다.
선택 근거와 한계는 [전체 변경 정리](LLM_CALL_OPTIMIZATION_20261018.md)를 참고하세요.
`RFP_RELEVANCE_BATCH_SIZE`, `RFP_RELEVANCE_MAX_TOKENS`로 조절할 수 있습니다.
토큰 수는 `tiktoken`의 `o200k_base`로 메시지·스키마를 계산하고 2,048토큰을
추가로 예약한 로컬 추정치이며, 실제 사용량·비용은 API 응답의 usage가 기준입니다.
단일 과제가 예산을 넘더라도 원문을 자르지 않고 개별 호출합니다.
문자 배치에서는 `RFP_RELEVANCE_MAX_CHARS`의 기본값이 24,000입니다.

### 관련 원문 우선 판정과 검토 순서 실험

기본값은 전체 기술 원문과 기존 검색 순서를 유지합니다. 다음 옵션은 별도로 활성화합니다.

- `RFP_RELEVANCE_CONTEXT_MODE=excerpt`: A/B와 어휘가 대응하는 원문 조각과 인접 조각을 먼저 제공합니다.
  `RFP_RELEVANCE_EXCERPT_CHARS` 기본값은 12,000자입니다. 원문 조각을 요약·재작성하지 않습니다.
  판단이 불확실하거나 인용·기술 인덱스 검증에 실패하면 전체 원문으로 한 번 더 판정합니다.
  선택되지 않은 중간 조각을 건너뛰어 인용문을 이어 붙일 수 없습니다.
- `RFP_RELEVANCE_CANDIDATE_ORDER=balanced`: 추가 LLM 없이 A/B 양쪽의 어휘 대응으로 후보 순서를 조정합니다.
  동점은 기존 검색 순서를 유지합니다.
- `RFP_RELEVANCE_CANDIDATE_WINDOW=12`: 최소 12개를 검토한 이후 배치 경계에서 통과 후보가 있으면 종료합니다.
  통과 후보가 없으면 계속 탐색합니다. `top_k`보다 적은 후보를 반환할 수 있고 뒤쪽 정답을 놓칠 수 있습니다.
  `diagnostics.candidate_selection`에 검토·미검토 후보 수와 종료 사유를 남깁니다.

명시적인 함수 인자로는 `relevance_context_mode`, `relevance_batch_mode`, `candidate_order`,
`candidate_window`를 `search()` 또는 `search_module_result()`에 전달할 수 있습니다.
위 실험 옵션은 성능·정답 회수 평가를 확인한 뒤 선택해야 하며, 기본 설정에는 자동 적용하지 않습니다.
`OPENAI_API_KEY`가 필요합니다. 각 과제의 A/B 기술을 같은 입력에서 독립 판정하며,
최대 5개 과제를 토큰 예산 안에서 묶어서 호출합니다. 각 과제의 원문·판정·인용은
독립적으로 검증합니다. 동일 요청은 캐시를 재사용합니다. 호출 수와 설정은
[NTIS/RFP 호출 최적화](NTIS_RFP_LLM_OPTIMIZATION.md)를 참고하세요.
테스트·다른 LLM 연결에는 `search(..., relevance_llm=callable)`을 사용합니다.
판정 근거는 후보의 `extra["technology_relevance"]`, 제외 사유는
`result.extra["diagnostics"]["technology_relevance"]`에 보존합니다.
LLM/API 오류는 빈 결과로 숨기지 않고 예외로 전달합니다. 이 단계는 기술적 관련성
필터이며, 공고 참여 자격이나 모든 요구사항의 충족을 보증하는 Gap 판정은 아닙니다.

검증 명령: `python -m unittest discover -s tests -p test_rfp_relevance.py`.
2026-10-15 실제 LLM 예시 검증에서 보유기술·요청기술의 동일/유사/다름 조합
9가지 중 동일·유사 조합 4가지만 통과하고 나머지 5가지는 제외됨을 확인했습니다.
이는 예시 검증 결과이며 전체 도메인에 대한 LLM 판정 정확도를 보증하지 않습니다.
