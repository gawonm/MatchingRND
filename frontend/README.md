# R&D Match 프런트엔드

React + TypeScript + Vite 기반 분석 화면입니다. Node.js 22.12 이상(또는 24 이상)이 필요합니다.

## FastAPI 연결

프로젝트 루트에서 기존 RAG 가상환경을 사용해 API를 실행합니다.

```powershell
.venv-gpu/Scripts/python.exe -m pip install -r requirements-api.txt
.venv-gpu/Scripts/python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

별도 터미널에서 `frontend` 폴더로 이동해 화면을 실행합니다.

```powershell
Copy-Item .env.example .env.local
npm ci
npm run dev
```

`VITE_API_BASE_URL`은 FastAPI 주소이며 기본값은 `http://127.0.0.1:8000`입니다.
`/api/health`로 연결 상태를 확인합니다. Workspace의 AI 추출은
`/api/analysis/extract`, 승인 후 보고서 생성은 `/api/analysis/report-view`를 호출합니다.
Discover에서는 데모 데이터와 `/api/discovery/search` 기반 실제 검색을 선택할 수 있습니다.
실제 분석에는 루트 `.env`의 API 키와 RAG 인덱스 또는 Supabase 데이터가 필요합니다.

검증: `npm test`, `npm run build`, `npm run lint`.

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])

```

You can also install [eslint-plugin-react-x](https://npmx.dev/package/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://npmx.dev/package/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])

```
