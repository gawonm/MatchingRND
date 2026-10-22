# 잇다(ITDA) 프런트엔드

보유기술과 개발 목표를 입력하고, 기술요소를 검토·승인한 뒤 기술나눔·NTIS·RFP·Gap 분석 결과와 원문 근거를 확인하는 React 화면입니다. 프로젝트 배경과 전체 실행 방법은 [루트 README](../README.md)를 참고하세요.

## 기술 구성

React · TypeScript · Vite · React Bootstrap을 사용합니다. Node.js 22.12 이상 또는 24 이상이 필요합니다.

## 실행

프로젝트 루트에서 Python 환경과 `.env`, Supabase 자료를 준비한 뒤 API를 실행합니다.

```powershell
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

별도 터미널에서 이 폴더로 이동해 화면을 실행합니다.

```powershell
cd frontend
Copy-Item .env.example .env.local
npm ci
npm run dev
```

화면은 기본 `http://localhost:5173`에서 열립니다. `VITE_API_BASE_URL`은 FastAPI 주소이며 기본값은 `http://127.0.0.1:8000`입니다. `/api/health`로 연결을 확인할 수 있습니다.

프런트엔드 설정에는 서버 API 주소만 넣습니다. LLM 키와 DB 접속 정보는 프로젝트 루트의 백엔드 `.env`에서 관리합니다.

## 화면 흐름

1. **기술 입력:** 보유기술·개발 목표·확보하고 싶은 기술을 작성합니다.
2. **AI 추출:** `/api/analysis/extract`로 입력을 기술요소로 구조화합니다.
3. **기술요소 검토:** 사용자가 추출 결과를 수정·승인합니다. 입력 원문과 검토 상태를 분석 요청에 보존합니다.
4. **분석 실행:** `/api/analysis/report-view`로 검색·Gap 분석·보고서 생성을 요청합니다.
5. **결과 확인:** Overview·기술·RFP·Gap·Evidence·Report 탭에서 후보, 요구기술별 판정과 원문 인용을 확인합니다.

Discover는 데모 데이터와 `/api/discovery/search`를 이용한 실제 DB 검색을 구분합니다. 데모 화면만 확인할 때와 실제 LLM 분석을 실행할 때의 결과를 구분해야 합니다.

## 검증·빌드

```powershell
npm test
npm run build
npm run lint
```

빌드 결과는 `dist/`에 생성됩니다. `npm run preview`는 빌드 화면을 확인하는 로컬 서버이며, 실제 분석을 위해서는 별도의 FastAPI 서버와 데이터가 필요합니다.

## 주요 파일

| 경로 | 역할 |
| --- | --- |
| `src/api.ts` | 백엔드 API 연결 |
| `src/components/WorkspaceWizard.tsx` | 입력·검토·분석 단계 연결 |
| `src/components/TechnologyReview.tsx` | 기술요소 검토·승인 |
| `src/components/ResultsWorkspace.tsx` | 분석 결과 탭 |
| `src/components/analysis/` | 기술·RFP·Gap·근거 탐색 |
| `src/state/analysisSession.ts` | 분석 입력·검토 상태 |
| `src/lib/analysisView.ts` | API 결과의 화면 모델 처리 |
| `tests/` | 입력 상태·API 계약·보고서·화면 로직 테스트 |
