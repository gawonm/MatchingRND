# RFP 확장 Test 비교

기존 사용자 질문과 새 합성 질문을 분리해 해석해야 합니다.
전체 46개 = 사용자 5개 + 합성 41개.
기존 모델과 이전에 Validation으로 선택한 epoch 2 LoRA를 그대로 사용했습니다. 재학습하지 않았습니다.

## 기존 사용자 질문

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 40.0% | 40.0% |
| hit_at_3 | 60.0% | 60.0% |
| hit_at_5 | 60.0% | 80.0% |
| hit_at_10 | 80.0% | 80.0% |
| mrr_at_10 | 0.5000 | 0.5067 |
## 추가 합성 질문

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 70.7% | 70.7% |
| hit_at_3 | 92.7% | 92.7% |
| hit_at_5 | 92.7% | 95.1% |
| hit_at_10 | 95.1% | 95.1% |
| mrr_at_10 | 0.8117 | 0.8138 |
## 전체 참고값

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 67.4% | 67.4% |
| hit_at_3 | 89.1% | 89.1% |
| hit_at_5 | 89.1% | 93.5% |
| hit_at_10 | 93.5% | 93.5% |
| mrr_at_10 | 0.7778 | 0.7804 |
## 합성 기술 표현 질문

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 70.0% | 70.0% |
| hit_at_3 | 90.0% | 90.0% |
| hit_at_5 | 90.0% | 95.0% |
| hit_at_10 | 95.0% | 95.0% |
| mrr_at_10 | 0.7972 | 0.8017 |
## 합성 실무 상황 질문

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 71.4% | 71.4% |
| hit_at_3 | 95.2% | 95.2% |
| hit_at_5 | 95.2% | 95.2% |
| hit_at_10 | 95.2% | 95.2% |
| mrr_at_10 | 0.8254 | 0.8254 |

## 질문별 정답 순위

| 질문 ID | 유형 | 기존 | 파인튜닝 |
|---|---|---:|---:|
| test-001 | user | 75 | 73 |
| test-002 | user | 1 | 1 |
| test-003 | user | 1 | 1 |
| test-004 | user | 3 | 3 |
| test-005 | user | 6 | 5 |
| expanded-b9e0616ff16974 | technical | 1 | 1 |
| expanded-3243ba3b185d0c | scenario | 18 | 13 |
| expanded-826f2c5d557694 | technical | 1 | 1 |
| expanded-b294d9ff577b71 | scenario | 1 | 1 |
| expanded-1963a2beed06c7 | technical | 1 | 1 |
| expanded-8c2d73551aeb00 | scenario | 1 | 1 |
| expanded-90650b094e3573 | technical | 1 | 1 |
| expanded-e7dfe674d728f6 | technical | 1 | 1 |
| expanded-19052116661f2f | scenario | 1 | 1 |
| expanded-fc729bfdbd3c2e | technical | 1 | 1 |
| expanded-ce23d9b7abad6b | scenario | 1 | 1 |
| expanded-155a58e4668e7d | technical | 1 | 1 |
| expanded-50afa398c5d7f8 | scenario | 1 | 1 |
| expanded-38dd3ce0caa2fc | technical | 2 | 2 |
| expanded-6a58bd3fdb478f | scenario | 2 | 2 |
| expanded-19d07f4cec24cc | technical | 1 | 1 |
| expanded-c2b3f7bcbd7dcf | scenario | 1 | 1 |
| expanded-b3134bf86a8dff | technical | 3 | 3 |
| expanded-de7e1f8316714f | scenario | 1 | 1 |
| expanded-7301236dec7543 | technical | 1 | 1 |
| expanded-d61ef824a4c589 | scenario | 1 | 1 |
| expanded-1916a534773598 | scenario | 3 | 3 |
| expanded-7a7290c56754aa | technical | 1 | 1 |
| expanded-7044ac72696f3e | scenario | 1 | 1 |
| expanded-67a436d8334d06 | technical | 50 | 39 |
| expanded-af0cdea100abfc | scenario | 1 | 1 |
| expanded-a86141ae9f4947 | scenario | 2 | 2 |
| expanded-1d9a1f52c8677b | technical | 1 | 1 |
| expanded-5f1d767ab3c23a | scenario | 2 | 2 |
| expanded-f1d3dacd826ff2 | technical | 2 | 2 |
| expanded-029f9a8155235b | scenario | 1 | 1 |
| expanded-5f37d8e51618e4 | technical | 1 | 1 |
| expanded-f682e0b1459442 | scenario | 1 | 1 |
| expanded-f27621a4c42e0b | scenario | 1 | 1 |
| expanded-8e3bebd50594fe | technical | 1 | 1 |
| expanded-fb9b3d924fa454 | technical | 2 | 2 |
| expanded-897444c709cca4 | scenario | 2 | 2 |
| expanded-70e54d661bca38 | technical | 1 | 1 |
| expanded-d9058b28e47e72 | scenario | 1 | 1 |
| expanded-84f14b6f8f75df | technical | 9 | 5 |
| expanded-d211c3ba24e704 | scenario | 1 | 1 |

실제 포함 범위는 과제 24개, 원문 그룹 10개입니다. 추가 합성 질문은 과제 22개, 원문 그룹 9개에서 나왔습니다.

## 해석의 한계

추가 질문은 사람이 미검수한 합성 데이터이고 원문에서 생성해 어휘 중복 편향이 있을 수 있습니다.
같은 과제에서 나온 두 질문은 독립 표본이 아닙니다. Test 원문 그룹도 14개로 한정됩니다.
같은 제목의 미확인 중복 과제와 다른 관련 정답이 라벨에서 누락됐을 수 있습니다.
원문 인용 검사는 의미상 정답이나 PDF 추출 완전성을 보장하지 않습니다.
사용자 질문 성적과 합성 질문 성적 차이를 표본 수 증가만의 효과라고 해석할 수 없습니다.
이번 확장 결과를 보고 학습 설정이나 체크포인트를 다시 선택하지 않았습니다.
최종 LLM 답변 생성 성능이 아닌 검색 평가입니다. Supabase와 운영 모델은 변경하지 않았습니다.
