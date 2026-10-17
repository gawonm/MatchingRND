# 2026-10-17 브랜치 통합 기록

통합 브랜치: `integration/latest-20261017`.
2026-10-15~16에 갱신된 원격 브랜치를 중심으로 변경 내용과 이력을 비교했다.
`chore/finetuning-cleanup`을 기준으로 API/UI 변경을 병합하고,
동일 수정이 다른 커밋으로 올라온 NTIS/RFP 브랜치의 이력도 연결했다.

## 확인한 브랜치

| 원격 브랜치 | 확인한 끝 커밋 | 처리 |
| --- | --- | --- |
| `feature/rfp-output-adjustment` | `2eb107d` | RFP 출력 변경 유지. main의 `d518b7c`와 동일 패치 |
| `fix/ntis-relevance-and-evidence-validation` | `90833d3` | NTIS/RFP 관련성, 입력·답변 근거 검증 유지. main의 `089a40b`에 반영된 수정 |
| `feat/tech-rag-b-matching` | `cdd1523` | A/B 입력 분리 및 문서 전체 판정 유지. main에 다른 커밋 번호로 반영됨 |
| `feature/ntis-rfp-llm-call-reduction` | `35e2076` | 호출 감소 유지 및 브랜치 이력 병합. `087df54`와 동일 패치 |
| `test/tech-rag-ntis-integration` | `37e03c9` | API/UI 브랜치에 포함됨. Gap 호출 감소는 `f86c975`와 동일 패치 |
| `main` | `01d5ba1` | 법령 RAG 호출 제거, 공통 R&D 유의사항, NTIS 리랭킹 기본 비활성화 유지 |
| `chore/finetuning-cleanup` | `793cfb4` | 파인튜닝 코드·실험 결과 및 LLM 전용 분석 경로 유지 |
| `feature/fastapi-ui-integration` | `49282b9` | API, Workspace·Discover UI, 구조화 근거/Gap 뷰 및 외부기술 오매칭 방지 병합 |

원격에 남아 있는 모든 브랜치의 끝 커밋은 통합 브랜치의 조상으로 연결했다.
옛 브랜치의 기능이 이후 main에서 의도적으로 제거된 경우에는 최신 동작을 유지했다.
삭제된 원격 브랜치 `feature/evidence-based-recommendations`의 로컬 사본과
기존 stash는 변경하지 않았다.

## 충돌과 보완

- API/UI 병합은 파일 충돌 없이 완료됐다. 파인튜닝 실험 파일과 로컬 Gap 분석 삭제가 유지됐다.
- NTIS/RFP 이력 병합에서 `tests/test_orchestrator.py` 한 곳이 충돌했다.
  예전 `policy_runner` 주입을 복구하지 않고 main의 법령 검색 제거를 유지했다.
  이 병합은 최종 파일 내용을 추가로 변경하지 않았다.
- API 의존성 목록이 없어 로컬에서 API 테스트를 불러오지 못했다.
  `requirements-api.txt`를 추가하고 프런트엔드 실행 안내를 실제 API 흐름에 맞췄다.
- Windows CRLF에서도 프런트엔드 포커스·스크롤 검증이 동작하도록 테스트 정규식을 수정했다.
- 삭제된 local Gap 분석을 참조하며 건너뛰던 테스트 3개를 현행 LLM 전용 경로에 맞췄다.
  저장 상태 재사용, Gap 실패 시 답변 생성 중단, 제거된 local 모드 거부를 확인한다.

## 검증

- `.venv-gpu/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"`: 239개 통과, 건너뛰기 없음.
- `frontend`: `npm test` 69개 통과, `npm run build` 통과, `npm run lint` 통과.
- `git branch -r --no-merged HEAD`: 출력 없음.
- 유료 LLM 호출, 실제 데이터 전체 분석 및 임베딩 재학습은 실행하지 않았다.
  단위 테스트 통과가 실데이터의 추천·Gap 판정 정확도를 보장하지는 않는다.

## 남아 있는 모델 설정

브랜치 통합으로 모델을 변경하지 않았다. 현재 기본값은 기술 RAG의
`gpt-5.6-luna`, NTIS의 `gpt-4.1-mini`, 질의 해석·RFP 관련성·Gap·최종 답변의
`gpt-4o-mini`로 나뉜다. 모델 통일은 별도 변경이 필요하다.

## 협업 기준

이번 통합 브랜치를 검토한 뒤 main에 병합하고, 이후 작업 브랜치는 갱신된 main에서 만든다.
여러 작업자의 커밋을 다시 cherry-pick하기 전에 main 반영 여부와 패치 내용을 비교한다.
