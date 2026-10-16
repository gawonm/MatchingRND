# NTIS 확장 Test 비교

총 191개 = 사용자 10개 + 합성 181개.
이전에 Validation으로 선택한 epoch 1 모델을 고정했습니다. 재학습·재선택하지 않았습니다.

## original

| 지표 | 기본 모델 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 100.00% | 100.00% |
| hit_at_3 | 100.00% | 100.00% |
| hit_at_5 | 100.00% | 100.00% |
| hit_at_10 | 100.00% | 100.00% |
| mrr_at_10 | 1.0000 | 1.0000 |
## generated

| 지표 | 기본 모델 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 83.43% | 82.87% |
| hit_at_3 | 89.50% | 89.50% |
| hit_at_5 | 91.16% | 90.61% |
| hit_at_10 | 93.37% | 93.37% |
| mrr_at_10 | 0.8659 | 0.8640 |
## all

| 지표 | 기본 모델 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 84.29% | 83.77% |
| hit_at_3 | 90.05% | 90.05% |
| hit_at_5 | 91.62% | 91.10% |
| hit_at_10 | 93.72% | 93.72% |
| mrr_at_10 | 0.8730 | 0.8712 |
## technical

| 지표 | 기본 모델 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 93.33% | 93.33% |
| hit_at_3 | 96.67% | 96.67% |
| hit_at_5 | 96.67% | 96.67% |
| hit_at_10 | 96.67% | 96.67% |
| mrr_at_10 | 0.9444 | 0.9472 |
## scenario

| 지표 | 기본 모델 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 83.82% | 83.82% |
| hit_at_3 | 92.65% | 92.65% |
| hit_at_5 | 94.12% | 94.12% |
| hit_at_10 | 97.06% | 97.06% |
| mrr_at_10 | 0.8858 | 0.8867 |
## constraint

| 지표 | 기본 모델 | 파인튜닝 |
|---|---:|---:|
| hit_at_1 | 71.70% | 69.81% |
| hit_at_3 | 77.36% | 77.36% |
| hit_at_5 | 81.13% | 79.25% |
| hit_at_10 | 84.91% | 84.91% |
| mrr_at_10 | 0.7516 | 0.7408 |

합성 질문은 원문에서 생성한 사람이 미검수한 초안이며 어휘·생성 방식 편향이 있습니다.
같은 과제의 질문 세 개는 독립 표본이 아닙니다. 추가 정답이 누락될 수 있으며 정확한 원문 인용 검사는 의미상 정답의 완전성을 보장하지 않습니다.
연구 원문 자체의 ... 생략은 복원하지 않았습니다. 임베딩 단독 검색 평가이며 최종 답변 품질 평가는 아닙니다.
기존 Test·Train/Validation·모델·Supabase를 변경하지 않았습니다.

## 차이의 불확실성

원문 그룹 98개를 단위로 4,000회 paired cluster bootstrap을 수행했습니다.

| 지표 | 파인튜닝 − 기본 | 95% 구간 |
|---|---:|---|
| hit_at_1 | -0.0052 | [-0.0276, +0.0165] |
| hit_at_5 | -0.0052 | [-0.0167, +0.0000] |
| mrr_at_10 | -0.0018 | [-0.0146, +0.0106] |

구간에 0이 포함되면 이 표본에서 일관된 우위를 확인했다고 해석하지 않습니다. 이 구간은 합성 질문·정답 누락 편향까지 보정하지는 않습니다.

## Evaluation revision and pending review

V1 was scored before a whole-cohort source-quality revision. V2 is exploratory, not an independent confirmatory test. No V2 labels were changed after scoring. See docs/NTIS_EXPANDED_EVALUATION.md for the full history and limitations. One possible additional positive is recorded in review_flags.json; reported scores retain the frozen labels.
