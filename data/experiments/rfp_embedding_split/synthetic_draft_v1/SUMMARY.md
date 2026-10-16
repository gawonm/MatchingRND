# 학습·검증 합성 데이터 초안

| 구분 | 수량 | 파일 |
|---|---:|---|
| Train 질문 | 392 | [검토 목록](train/review.md) / [JSON](train/questions.draft.json) |
| Train 질문·정답·오답 학습 묶음 | 325 | [JSONL](train/triplets.draft.jsonl) |
| Validation 질문 | 184 | [검토 목록](validation/review.md) / [JSON](validation/questions.draft.json) |

학습 묶음은 Train 질문 중 근거가 확인된 오답 후보가 있는 사례입니다. 오답 후보가 없는 67개 질문은 질문 초안에만 남겼습니다.

원문 인용·ID·분할 검사를 통과한 합성 초안이며, 사람 검수 완료 자료는 아닙니다. 정답 관련성과 오답 후보의 부적합성을 확인해야 합니다.

Test 문서·Test 질문은 생성에 사용하지 않았고 기존 questions.json은 변경하지 않았습니다. 모델 파인튜닝·Supabase 적재는 실행하지 않았습니다.

생성 실패·검사 실패는 [failures.json](failures.json)에, 입력 해시와 검사 결과는 [manifest.json](manifest.json)에 저장했습니다. API 호출 실행 이력은 [generation_history.json](generation_history.json)에 있습니다.
