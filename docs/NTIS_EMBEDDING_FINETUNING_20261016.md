# NTIS 임베딩 첫 파인튜닝 비교

기존 `data/experiments/ntis_embedding_split/`의 분할과 사용자 Test 질문 10개를 그대로 사용합니다.
추가 작성용으로 만들었던 `questions.additional.json`과 `추가작성방법.md`는 삭제했습니다.
새 Test 질문이나 확장 Test는 만들지 않습니다.

실험 산출물은 `data/experiments/ntis_embedding_finetune_20261016/`에 별도 저장합니다.
원본 분할·질문·원문, RFP·기술나눔 모델, Supabase는 변경하지 않습니다.

## 완료 결과

학습 646개, 중복 제거 후 Validation 332개로 2 epoch 학습을 완료했고 Validation 기준으로 epoch 1을 선택했습니다.
사용자 Test 10개에서 기본 모델과 새 모델 모두 Hit@1/3/5/10이 100%, MRR@10이 1.0000입니다.
기본 모델이 이미 10개 모두 1위라서 이번 Test로는 파인튜닝의 추가 이점을 확인하지 못했습니다.
Validation MRR@10은 기본 0.945720, epoch 1이 0.945962, epoch 2가 0.944289로 차이가 작았습니다.
선택된 모델을 다시 로드한 6,580개 코퍼스 벡터가 학습 직후 벡터와 정확히 일치했습니다.
실제 선택 어댑터는 실험 폴더의 `adapter_epoch_1/`이며 운영에 배포하지 않았습니다.

## 데이터와 학습 예제

- 검색 대상: 기존 읽기 전용 사본의 국가 R&D 과제 6,580개 및 청크 6,580개.
- 분할: Train 3,948개, Validation 1,974개, Test 658개. 알려진 동일 과제번호·제목·긴 연구내용 중복 그룹은 같은 세트에 둡니다.
- 첫 파일럿은 Train 전체를 학습하지 않습니다. Train에서 344개 그룹, Validation에서 167개 그룹을 고르고 각각 기술 표현·현장 상황 질문을 생성합니다.
- 분야(`science_medium`)를 순회하며 그룹당 대표 과제 하나를 고르는 방식과 seed 20261016으로 샘플을 고정했습니다. Test 질문·검색 순위로 선택하지 않았습니다.
- 생성기는 `gpt-4o-mini`이며 [OpenAI 공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를 참고한 Pydantic 스키마를 사용합니다.
- 근거는 모델이 새로 쓰지 않습니다. 코드가 실제 연구목표·연구내용의 인용 구간에 ID를 붙이고, 모델은 그 ID를 선택합니다.
- 음성 문서는 Train 안에서만 TF-IDF로 후보를 찾고 모델이 질문의 답이 아닌 후보를 선택합니다. 동일 그룹은 음성으로 사용하지 않습니다.
- 최초 생성에서는 음성 선택이 누락되어 학습에 사용하지 않았습니다. 캐시에 남긴 기존 질문은 유지하고, Train용 출력 스키마와 프롬프트를 분리해 음성 선택을 보강했습니다. 실패·거부된 예제는 제외합니다.
- 인용문이 실제 청크에 있는지, 학습 세트 밖 문서가 섞이지 않았는지, 학습 길이 안에 근거가 남는지 검사합니다.
- 자동 검사 통과는 의미상 정답·비정답의 완전한 검수를 뜻하지 않습니다. 합성 라벨은 사람이 미검수한 초안입니다.

최종 학습 예제는 323개 Train 과제의 646개 질문입니다. 생성 과정에서 기존 질문 유지 등 조건을 통과하지 못한 21개 과제의 초안을 제외했습니다.
생성된 Validation 질문은 334개였으나, Train과 동일한 질문 및 긴 연구목표 문장을 공유한 Validation 과제 1개를 발견했습니다.
Test 결과를 보기 전에 그 과제의 질문 2개를 제외하여 최종 Validation은 332개입니다. 원본 분할과 사용자 Test는 변경하지 않았습니다.
중복 검사 완료 전에 시작했던 학습은 중단하고 `discarded_validation_overlap_attempt/`에 별도 보관했으며, 정리된 입력으로 기본 모델부터 다시 학습했습니다.
동일한 질문·긴 연구목표 문장이 Train과 사용자 Test 사이에는 없다는 것도 확인했습니다.

## 모델과 평가 기준

- 기본 임베딩: `dragonkue/BGE-m3-ko`, revision `7074d66aa46562342193ca4feb3d89bf9dad71b4`.
- 새 모델은 기본 모델에서 시작하며 RFP나 기술나눔 어댑터를 이어 학습하지 않습니다.
- GPU LoRA: query/value, rank 8, alpha 16, dropout 0.05, 학습률 2e-5, weight decay 0.01, 2 epoch, gradient accumulation 8, temperature 0.05.
- 명시적 음성을 사용한 softmax 손실이며 in-batch negatives는 사용하지 않습니다.
- 학습 최대 384 token. 긴 청크는 근거가 실제 포함되는 구간을 골라 학습합니다. 평가에는 최대 8,192 token으로 전체 청크를 사용합니다.
- FP16 autocast와 FP32 벡터 정규화 후 전체 6,580개 청크의 코사인 점수를 계산합니다. 문서별 최고 점수로 순위를 매기며, 그룹을 자동으로 같은 정답으로 합치지 않습니다.
- Validation MRR@10으로 epoch을 선택합니다. 동률이면 먼저 학습한 모델을 선택합니다.
- 선택 이후 기존 Test 10개로 기본 모델과 새 모델을 평가합니다. Test 점수로 학습 설정을 바꾸지 않습니다.
- 임베딩 검색 실험이며 BM25, 리랭킹, LLM 관련성 판정, 최종 생성 답변 평가는 포함하지 않습니다.

## 한계

원문은 기존 엑셀에서 저장된 요약입니다. 일부 필드에 이미 `...` 생략이 있어 완전한 연구계획서가 아닙니다.
명시되지 않은 연차·총괄·세부 관계나 제목이 다른 유사 과제의 중복까지 모두 탐지한 분할은 아닙니다.
합성 Validation은 생성 방식에 유리할 수 있고, 사용자 Test 10개는 작은 표본입니다.
기술나눔·RFP 실험과 다른 문서 수·라벨·샘플을 사용하므로 모듈 간 점수를 직접 성능 순위로 비교하면 안 됩니다.

## 파일과 실행

`app/scripts/prepare_ntis_training_data.py`의 `plan`, `generate`로 생성 작업을 준비합니다. 요청별 캐시와 사용량·실패 기록을 남깁니다.
`app/scripts/finetune_ntis_embedding.py`의 `baseline-corpus`, `prepare`, `train`, `evaluate`를 사용합니다.
`baseline-corpus`는 Test 질문을 읽지 않고 문서 벡터만 계산합니다. 학습에는 Train 예제만 사용합니다.

최종 결과는 실험 폴더의 `report.md`, `comparison.json`, `training_audit.json`, `history.json`, `selection.json`, `reload_verification.json`에 기록합니다.
