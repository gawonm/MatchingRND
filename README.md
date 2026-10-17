# MatchingRND

2026-10-15~16 작업의 통합 범위와 검증 결과는
[브랜치 통합 기록](docs/BRANCH_INTEGRATION_20261017.md)에 정리했습니다.
API와 화면 실행은 [프런트엔드 안내](frontend/README.md)를 참고하세요.

LLM 기본 모델은 입력 해석·기술나눔·NTIS·RFP·Gap·최종 답변 및
학습 데이터 생성·평가 모두 `gpt-5.6-luna`입니다.
공통 기본값은 `app/common/llm_config.py`에서 관리합니다.
명시적인 CLI `--model`, `NTIS_LLM_MODEL`, `NTIS_RELEVANCE_MODEL`,
`RFP_RELEVANCE_MODEL`, 기술 RAG YAML 설정은 기본값보다 우선합니다.

## 통합 Orchestrator

`app/orchestrator.py`의 `RagOrchestrator`가 Technology → NTIS → RFP를 연결합니다.
Technology는 `answer()`를 호출해 추출·검증된 기술요소를 얻고, 검증된 원문 근거가
있는 요소만 NTIS와 RFP Query 확장에 사용합니다. 최초 기술문제는 유지합니다.
제도 질문을 제공하면 RFP 검색 이후 법령 검색을 실행합니다.

```python
from app.orchestrator import AnalysisRequest, RagOrchestrator

orchestrator = RagOrchestrator()
state = orchestrator.run(AnalysisRequest(
    problem="작업자와 지게차가 함께 이동하는 제조환경에서 안전주행 성능을 높이고 싶다.",
    owned_technologies=["SLAM 기반 자율주행", "영상 객체 인식", "경로계획"],
    # 필요한 경우에만 제도 질문을 추가
    policy_question="기술나눔 기술을 이전받을 때 확인할 조건은 무엇인가?",
))

print(state.rfp_query_details)  # Baseline/Cascade Query와 확장 원문·출처
for candidate in state.rfp.candidates:
    print(candidate.title, candidate.extra.get("requirements"))
print(state.warnings)
print(state.model_dump_json(indent=2))
```

실행 전 Technology 및 NTIS 인덱스를 준비하고 `.env`에 `OPENAI_API_KEY`를 설정해야 합니다.
원본 자료는 모듈별 `data/raw/` 아래에 정리되어 있으며 기본 설정이 해당 경로를 읽습니다.
NTIS는 `data/raw/ntis/ntis_projects_2026_mechanical.xlsx`, Technology는
`data/raw/technology`를 읽습니다. RFP·법령은 `data/raw/rfp/pdf`, `data/raw/policy`를
사용하고 첫 호출 시 인덱스를 준비합니다. RFP 공고 연결은
`data/raw/rfp/RFP_공고목록.xlsx`을 사용합니다.
같은 Orchestrator 객체를 재사용하면 Technology 파이프라인과 PDF 인덱스를 재사용합니다.

데이터 구조와 각 파일의 용도는 [data/README.md](data/README.md)에 정리했습니다.
NTIS 인덱스는 `data/processed/ntis/index`, Technology 문서·청크는
`data/processed/technology`에 생성됩니다. 환경변수로 경로를 덮어쓰는 경우에는
정리된 새 경로를 지정해야 합니다.

`technology_runner`, `ntis_runner`, `rfp_runner`, `policy_runner`에 기존에 준비한
파이프라인을 연결하는 함수를 주입할 수도 있습니다. 반환값은 공통 `ModuleResult`이며
Technology의 `GenerationResult`도 지원합니다. 각 단계 오류는 `OrchestrationError.stage`로
구분하고 이후 단계는 실행하지 않습니다. 빈 검색 결과는 경고와 함께 보존합니다.

반환 `AnalysisState`는 입력, 단계별 결과, 검증된 기술요소, Query 이력을 담습니다.
**기술요소 의미 정렬·Gap 판정과 통합 최종 설명 생성은 별도 구현 단계입니다.**
`unmet_elements`는 사용자가 제공하는 검토 요소이며 검색 실패로 자동 추정하지 않습니다.

## RAG 공통 반환 스키마

통합 호출부는 `app.common.schemas.ModuleResult`를 사용합니다.
공통 필드는 `module`, `query`, `query_expansion`, `candidates`, `tech_elements`,
`hits`, `stats`, `extra`입니다. JSON이 필요하면 `result.model_dump(mode="json")`을 사용합니다.

| 모듈 | 공통 스키마 진입점 |
| --- | --- |
| Technology | `TechnologyRagPipeline.search(query)` 또는 `.answer(query).result` |
| NTIS | `app.ntis_rag.pipeline.run_ntis_module(problem, **options)` |
| RFP | `app.rfp_rag.pipeline.search_module_result(index, question, **options)` |
| 법령 | `app.policy_rag.pipeline.search_module_result(index, question, **options)` |

RFP·법령의 기존 `search()`와 NTIS의 `run_ntis_pipeline()`은 원본 결과를 반환하는
호환용 API입니다. **통합 시에는 위 표의 공통 스키마 진입점을 사용해야 합니다.**
이미 얻은 NTIS 원본 결과는 `app.ntis_rag.adapter.to_module_result(raw)`로 변환할 수 있습니다.
기존 NTIS dict 변환 함수도 공통 모델로 검증한 뒤 dict를 반환합니다.

```python
from app.rfp_rag.pipeline import build_index, search_module_result

index = build_index()  # 인덱스 생성은 기존 설정·인자를 사용
result = search_module_result(index, "검토할 기술문제")
for candidate in result.candidates:
    print(candidate.title, candidate.relevance_score)
    for evidence in candidate.evidences:
        print(evidence.quote, evidence.page, evidence.verified)
context = result.extra["context"]
```

공통 `Evidence.page`는 0부터 시작합니다. PDF 원본의 1부터 시작하는 페이지·다중
좌표는 `Evidence.extra`에 보존하며, 여러 위치에 걸친 인용은 단일 `page/bbox`를 비워 둡니다.
RFP 공고 연결·요구사항·성능지표, 법령 조문·시행일·유효성 확인 상태, NTIS 기술축은
`extra`에 보존합니다. PDF 후보는 과제/조문 단위이며 같은 PDF의 여러 후보는 같은
`doc_id`를 가질 수 있습니다. 원본 ID는 인덱스·평가 데이터와의 연결을 위해 유지합니다.

검색 단계에서는 기술요소·연관성 설명이 비어 있을 수 있습니다. RFP·법령의 공통
출력은 검색 근거이며 답변 생성은 별도 단계입니다.

스키마 검증: `python -m unittest discover -s tests -p "test_*.py"`

## RAG 파일 구조

Technology·NTIS·RFP·법령 모두 다음 역할별 구조를 사용합니다.

```text
app/<module>_rag/
├── __init__.py       # 외부에 제공하는 진입점
├── config.py         # 경로·환경변수·설정
├── pipeline.py       # 단계 연결 및 통합 호출
├── parsing/          # PDF·Excel 원문 추출과 구조화
├── indexing/         # 청크 생성·임베딩·검색 인덱스 구축
├── retrieval/        # 검색·순위 병합·문맥 구성
└── scripts/          # 명령행 실행
```

LLM 생성·분석 기능이 있는 Technology와 NTIS는 `generation/`을 추가로 사용합니다.
모듈별 원문 형식이 달라 내부 파서 파일은 `pdf_parser.py`, `excel_loader.py` 등으로 구분합니다.
공통 출력 모델은 `app/common/schemas.py`, PDF의 중복 검색·검증·분할 코드는
`app/common/retrieval.py`, `validation.py`, `chunking.py`에서 관리합니다.
RFP·법령·NTIS의 `adapter.py`가 공통 출력 변환을 담당합니다.

새 호출부는 각 모듈의 `pipeline.py`를 사용합니다. 기존 `rfp_rag.py`, `law_rag.py`,
NTIS의 `analysis.py`·`build_index.py`와 Technology의 `retrieval/pipeline.py`는
기존 import를 지원하는 호환 파일입니다. 기존 NTIS `retrieval` import도 유지됩니다.
NTIS의 분석 모델·검색 인덱스는 파이프라인을 실행할 때 로드합니다.

인덱스 실행 경로는 `python -m app.<module>_rag.scripts.build_index`로 통일했습니다.
RFP·법령은 `--data-dir`, `--output-dir`, `--model-name`을 지원합니다.
NTIS는 기존 환경변수 설정을, Technology는 기존 CLI 옵션을 사용합니다.
인덱스·추출 캐시 형식과 문서/청크 ID 생성 규칙은 기존과 동일합니다.

구조 검증 테스트에는 모델·벡터 저장소를 대체한 파싱→인덱싱→검색 연결 테스트와
실제 임시 Excel 파일을 읽는 NTIS 파싱 테스트가 포함됩니다.
