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

기본 LLM은 `gpt-4o-mini`이며 `RFP_RELEVANCE_MODEL`로 변경할 수 있습니다.
`OPENAI_API_KEY`가 필요하고 검증한 과제의 입력 기술마다 추가 LLM 호출이 발생합니다.
입력 기술끼리의 비교로 혼동하지 않도록 기술별로 별도 호출하며, 각 호출에는 해당
기술 하나와 과제의 요구사항 원문만 제공합니다.
테스트·다른 LLM 연결에는 `search(..., relevance_llm=callable)`을 사용합니다.
판정 근거는 후보의 `extra["technology_relevance"]`, 제외 사유는
`result.extra["diagnostics"]["technology_relevance"]`에 보존합니다.
LLM/API 오류는 빈 결과로 숨기지 않고 예외로 전달합니다. 이 단계는 기술적 관련성
필터이며, 공고 참여 자격이나 모든 요구사항의 충족을 보증하는 Gap 판정은 아닙니다.

검증 명령: `python -m unittest discover -s tests -p test_rfp_relevance.py`.
2026-10-15 실제 LLM 예시 검증에서 보유기술·요청기술의 동일/유사/다름 조합
9가지 중 동일·유사 조합 4가지만 통과하고 나머지 5가지는 제외됨을 확인했습니다.
이는 예시 검증 결과이며 전체 도메인에 대한 LLM 판정 정확도를 보증하지 않습니다.
