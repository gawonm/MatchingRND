# UI ↔ RAG 통합 실행 가이드 (2026-10-19)

브랜치 `integration/ui-rag-parity`. 기존 비UI RAG 파이프라인(`tests/integration_e2e.py`)을 기준으로
React → FastAPI → RAG 의 입력·실행 설정·출력 계약을 맞췄다. RAG 검색·Gap·Evidence·생성 로직과 `app/query_parser.py`는 변경하지 않았다.

## 변경 요약

| 영역 | 내용 |
| --- | --- |
| 분석 요청 | `problem`에 원문 질문 전체(없으면 세 입력칸 문맥 전체)를 보낸다. 이전에는 '해결 문제' 칸만 보냈다. |
| 추출 API | `original_query`가 있으면 원문 그대로 `parse_query`에 넣는다. 원문만 입력해도 된다. 재시도 2회(`parse_query` 기본값과 동일). |
| policy_question | 추출 결과를 반환·표시하고 분석 요청에 보존한다. 호환용 필드이며 정책·법령 검색은 수행하지 않는다. |
| 승인 | 보유기술(A) 필수 조건 제거(`AnalysisRequest.owned_technologies` 기본값 `[]`과 일치). 입력이 AI 추출 이후 바뀌면 이전 추출 요소를 "현재 입력 미검증"으로 표시하고 승인을 막는다. |
| 실행 설정 | FastAPI 시작 로그에 실제 `RAG_BACKEND`·모델 설정을 기록하고, 미설정이면 경고한다(인증정보는 기록하지 않음). |

유지한 정책: Gap 분석은 검색 상위 RFP 2건만 수행(`gap_analysis.DEFAULT_MAX_RFPS = 2`), Gap 화면은 내부 `decision_path`를 노출하지 않는다.

## 1. 환경 설정

1. Python 3.12 가상환경에 `pip install -r requirements-dev.txt` (Supabase 적재는 [SUPABASE_SETUP.md](SUPABASE_SETUP.md)).
2. 프로젝트 루트에 `.env`를 만든다. `.env.example`을 복사해 `OPENAI_API_KEY`, `SUPABASE_*` 값을 채운다. `.env`는 커밋하지 않는다.
3. **`RAG_BACKEND=supabase`를 반드시 명시한다.** 비UI CLI(`tests/integration_e2e.py`, `app/scripts/run_analysis.py`)는
   `--backend` 기본값 `supabase`를 쓰지만, FastAPI가 쓰는 `RagOrchestrator()`는 환경변수가 없으면 `local`을 쓴다.
   값이 없으면 두 경로가 다른 저장소를 검색한다.

## 2. 실행

앱의 CORS 허용 출처는 `http://localhost:5173`, `http://127.0.0.1:5173` 뿐이다. 8000·5173 포트에 다른 서버가 떠 있으면 먼저 정리한다.

```powershell
# 백엔드 (프로젝트 루트)
$env:RAG_BACKEND = "supabase"
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000

# 프론트엔드 (다른 터미널)
cd frontend
npm ci
npm run dev    # http://127.0.0.1:5173 , API 주소는 VITE_API_BASE_URL (기본 http://127.0.0.1:8000)
```

## 3. 정상 동작 확인

1. 백엔드 시작 로그에 다음 줄이 있고 경고가 없다.
   `RAG runtime settings: {'rag_backend': 'supabase', 'rag_backend_from_env': True, 'default_llm_model': 'gpt-5.6-luna', ...}`
   `RAG_BACKEND 미설정` 경고가 보이면 1-3을 확인한다.
2. `GET http://127.0.0.1:8000/api/health` → `{"status":"ok", ...}`, 화면 상단 배지가 "API 연결됨"으로 표시된다.
3. Workspace에서 원문 질문 입력 → `AI로 기술요소 추출` → A/B 확인 → `이 내용으로 분석 준비 완료` → `실제 RAG 분석 시작`.
4. 결과 화면 Overview·기술·RFP·Gap·Evidence·Report 탭이 열리고, RFP 탭에서 상위 2건만 "Gap 분석 완료"로 표시되며,
   Report 탭에 7개 섹션이 있다. 브라우저 콘솔과 API 응답에 오류가 없다.
5. 입력을 수정하면 이전 승인이 해제되고, 다시 추출하기 전까지 이전 추출 요소는 "현재 입력 미검증"으로 표시된다.

분석 1회는 유료 LLM 호출을 수행한다. 측정 1회 기준 gpt-5.6-luna 약 50회, 약 $0.16, 약 11분이 걸렸다(질문에 따라 달라짐).
추출은 버튼을 누를 때 1~3회만 호출한다.

## 4. 테스트 (유료 호출 없음)

```powershell
# 백엔드: 실제 키·DB 접속을 막은 상태로 실행
$env:OPENAI_API_KEY = "sk-invalid-offline"; Remove-Item Env:RAG_BACKEND -ErrorAction SilentlyContinue
python -m unittest discover -s tests -p "test_*.py"

# 프론트엔드
cd frontend; npm test; npm run lint; npm run build
```

## 5. 검증 범위

- 자동: 백엔드 unittest 252건, 프론트 77건, ESLint·tsc·Vite build 통과.
- UI ↔ 비UI `AnalysisRequest` 동등성: 가짜 LLM 5개 시나리오(정상 추출, 복구 경로 재시도, 재시도 예산, 제도 질문, 원문만 입력)에서 일치.
- 응답 → 화면: 근거 ID 포함 관계, claim 연결, 후보 중복, RFP·기술·Gap 양방향 연결, 라벨 집계 등 15항목을 실제 응답으로 검사.
- 실제 E2E: 평가 문항 1개를 브라우저 → FastAPI → RAG로 1회 실행해 HTTP 200·LLM 오류 0, 수신 요청이 비UI 해석 결과와 같음을 확인.
  결과 화면은 같은 응답을 재생해 확인했다. 다른 문항과 반복 실행은 미검증.

## 6. 알려진 한계

- `parse_query` 단어 범위 복구 경로: 1차 응답의 근거 문장이 원문과 글자 단위로 일치하지 않으면 공백 단위 단어 범위로 재시도하며,
  이때 기술명에 조사("…기술을")나 접속어("이를 위해 …")가 포함될 수 있다. UI는 이름을 가공하지 않으므로 비UI와 같은 결과를 받는다.
  모델에 따라 빈도가 다르며(gpt-4o-mini에서 관측, gpt-5.6-luna 1회 실행에서는 미발생) 수정은 별도 과제다.
  방안: ① 이름은 원문에 있고 근거만 의역이면 근거를 원문 문장으로 대체 ② 복구 이름의 끝 조사·앞 접속어 보수적 제거 ③ 문자 단위 범위.
  별도 브랜치에서 `parse_query` 테스트와 추출 전용 회귀 비교로 검증한다.
- `RAG_BACKEND` 코드 기본값은 경로마다 다르다(위 1-3). 실행 환경에서 명시하는 것으로 대응하며 기본값은 바꾸지 않았다.
- 검색 상위 RFP에 질문과 관련이 낮은 후보가 포함될 수 있다(검색 정밀도 문제, UI와 무관).
- 결과는 브라우저 메모리에만 있어 새로고침하면 사라진다.
