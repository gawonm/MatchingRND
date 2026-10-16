# 기술나눔 확장 Test 비교

**평가 상태: 지정된 출처 정답을 찾는 기준의 예비 점수입니다. 복수 정답 후보 누락을 발견했으며 사람 검수가 필요합니다.**

전체 154개 = 사용자 10개 + 합성 144개.
누출 방지 기준 기술 그룹 58개. 기존 epoch 2 모델을 고정했고 재학습하지 않았습니다.

## 기존 사용자 질문

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| Hit@1 | 100.0% | 100.0% |
| Hit@3 | 100.0% | 100.0% |
| Hit@5 | 100.0% | 100.0% |
| Hit@10 | 100.0% | 100.0% |
| MRR@10 | 1.0000 | 1.0000 |
## 추가 합성 질문

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| Hit@1 | 94.4% | 93.8% |
| Hit@3 | 97.2% | 98.6% |
| Hit@5 | 99.3% | 99.3% |
| Hit@10 | 99.3% | 99.3% |
| MRR@10 | 0.9620 | 0.9609 |
## 전체 참고값

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| Hit@1 | 94.8% | 94.2% |
| Hit@3 | 97.4% | 98.7% |
| Hit@5 | 99.4% | 99.4% |
| Hit@10 | 99.4% | 99.4% |
| MRR@10 | 0.9645 | 0.9634 |
## 기술 표현

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| Hit@1 | 97.9% | 97.9% |
| Hit@3 | 100.0% | 100.0% |
| Hit@5 | 100.0% | 100.0% |
| Hit@10 | 100.0% | 100.0% |
| MRR@10 | 0.9896 | 0.9896 |
## 현장 문제

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| Hit@1 | 89.6% | 89.6% |
| Hit@3 | 95.8% | 97.9% |
| Hit@5 | 100.0% | 100.0% |
| Hit@10 | 100.0% | 100.0% |
| MRR@10 | 0.9330 | 0.9347 |
## 요구 조건

| 지표 | 기존 | 파인튜닝 |
|---|---:|---:|
| Hit@1 | 95.8% | 93.8% |
| Hit@3 | 95.8% | 97.9% |
| Hit@5 | 97.9% | 97.9% |
| Hit@10 | 97.9% | 97.9% |
| MRR@10 | 0.9635 | 0.9583 |

## 질문별 정답 순위

| 질문 ID | 유형 | 기존 | 파인튜닝 |
|---|---|---:|---:|
| tech-test-001 | user | 1 | 1 |
| tech-test-002 | user | 1 | 1 |
| tech-test-003 | user | 1 | 1 |
| tech-test-004 | user | 1 | 1 |
| tech-test-005 | user | 1 | 1 |
| tech-test-006 | user | 1 | 1 |
| tech-test-007 | user | 1 | 1 |
| tech-test-008 | user | 1 | 1 |
| tech-test-009 | user | 1 | 1 |
| tech-test-010 | user | 1 | 1 |
| tech-extra-376a7b2fbce822 | technical | 1 | 1 |
| tech-extra-c76f34ea62072e | scenario | 3 | 5 |
| tech-extra-0aef0e8eff1ff9 | constraint | 1 | 1 |
| tech-extra-086962f7136142 | technical | 1 | 1 |
| tech-extra-b1ada99a01e216 | scenario | 1 | 1 |
| tech-extra-eebf5492960c29 | constraint | 1 | 1 |
| tech-extra-01477ae7719f1d | technical | 1 | 1 |
| tech-extra-e5e51abee7d659 | scenario | 1 | 1 |
| tech-extra-a12644a6b265a1 | constraint | 1 | 1 |
| tech-extra-1828d668718db3 | technical | 1 | 1 |
| tech-extra-c186b91f8b1a84 | scenario | 1 | 1 |
| tech-extra-d15e5cacc097e8 | constraint | 1 | 1 |
| tech-extra-97b3add3e4203d | technical | 1 | 1 |
| tech-extra-1a73d77e6c000f | scenario | 1 | 1 |
| tech-extra-7ece7c9f8cefc2 | constraint | 1 | 1 |
| tech-extra-efc65f702b4360 | technical | 1 | 1 |
| tech-extra-1477a9c0dff302 | scenario | 1 | 1 |
| tech-extra-e9de42d2fb6ff1 | constraint | 1 | 1 |
| tech-extra-d9c0cc839002fa | technical | 1 | 1 |
| tech-extra-7a1975b2647bc7 | scenario | 1 | 1 |
| tech-extra-1b8c9d3322eb18 | constraint | 1 | 1 |
| tech-extra-769e8da5c5dc79 | technical | 1 | 1 |
| tech-extra-ff6d5589abe309 | scenario | 1 | 1 |
| tech-extra-78439aa649fda8 | constraint | 1 | 1 |
| tech-extra-6e469b97868c58 | technical | 1 | 1 |
| tech-extra-091709e10618ef | scenario | 1 | 1 |
| tech-extra-4a37de33d9d834 | constraint | 1 | 1 |
| tech-extra-53460e195808fc | technical | 1 | 1 |
| tech-extra-a3b30ea3852204 | scenario | 1 | 1 |
| tech-extra-2e893325552fdc | constraint | 1 | 1 |
| tech-extra-c9c0d58588a0bc | technical | 1 | 1 |
| tech-extra-31bf3dddd50a26 | scenario | 1 | 1 |
| tech-extra-3d580d5396b20f | constraint | 1 | 1 |
| tech-extra-14780489238a5b | technical | 1 | 1 |
| tech-extra-089ba09af54b2e | scenario | 1 | 1 |
| tech-extra-07af46f274afc5 | constraint | 1 | 1 |
| tech-extra-8deff258241aef | technical | 1 | 1 |
| tech-extra-273ae5f5cb753c | scenario | 1 | 1 |
| tech-extra-c4d5782037fd5c | constraint | 1 | 1 |
| tech-extra-66db8dfb8ce398 | technical | 1 | 1 |
| tech-extra-6e30110a83798e | scenario | 1 | 1 |
| tech-extra-f5f2cc5b3b597a | constraint | 4 | 2 |
| tech-extra-857be463f2dc59 | technical | 1 | 1 |
| tech-extra-6bf2f45f034405 | scenario | 1 | 1 |
| tech-extra-33e27909abe30a | constraint | 1 | 1 |
| tech-extra-6c747949abefcf | technical | 1 | 1 |
| tech-extra-ed638a198fdba9 | scenario | 1 | 1 |
| tech-extra-1d054d5aeb5097 | constraint | 1 | 1 |
| tech-extra-bd274284bbac19 | technical | 1 | 1 |
| tech-extra-0346042f743adc | scenario | 1 | 1 |
| tech-extra-edb17d8d25b1c2 | constraint | 1 | 1 |
| tech-extra-5fc7d10757df9f | technical | 1 | 1 |
| tech-extra-7f8098a158d040 | scenario | 2 | 2 |
| tech-extra-e475853243a024 | constraint | 1 | 1 |
| tech-extra-4b8a99cc2caf31 | technical | 1 | 1 |
| tech-extra-7c8260f1d4e765 | scenario | 1 | 1 |
| tech-extra-587c42e4c7f102 | constraint | 1 | 1 |
| tech-extra-0c67ba980535e9 | technical | 1 | 1 |
| tech-extra-e0d57a35836df3 | scenario | 1 | 1 |
| tech-extra-7c5eb2f9cd4fd1 | constraint | 1 | 1 |
| tech-extra-deb897caedaf3c | technical | 1 | 1 |
| tech-extra-82af4eadafcbe2 | scenario | 1 | 1 |
| tech-extra-14c00aeef56dc5 | constraint | 1 | 1 |
| tech-extra-2c6ff2d5d85d9c | technical | 1 | 1 |
| tech-extra-c848c931a087a3 | scenario | 1 | 1 |
| tech-extra-125fd4dd49d89f | constraint | 1 | 1 |
| tech-extra-8367fdeeeee450 | technical | 1 | 1 |
| tech-extra-00536e46c02701 | scenario | 1 | 1 |
| tech-extra-f8f47a70122849 | constraint | 1 | 1 |
| tech-extra-64bf156039230b | technical | 1 | 1 |
| tech-extra-80c8d9f0ae8def | scenario | 1 | 1 |
| tech-extra-1a09ffa97a85e8 | constraint | 1 | 1 |
| tech-extra-5542f6239cb21f | technical | 1 | 1 |
| tech-extra-61f03af897e067 | scenario | 1 | 1 |
| tech-extra-f6acc6de8c2cf8 | constraint | 1 | 1 |
| tech-extra-6ea6758e7dfa44 | technical | 1 | 1 |
| tech-extra-6a7f619473dd63 | scenario | 1 | 1 |
| tech-extra-b3fa0468101574 | constraint | 1 | 1 |
| tech-extra-798e45ea972173 | technical | 1 | 1 |
| tech-extra-66bdef05347246 | scenario | 2 | 2 |
| tech-extra-029949cb15f9b9 | constraint | 1 | 1 |
| tech-extra-a6b365e197aa2d | technical | 1 | 1 |
| tech-extra-5998e5091958bf | scenario | 1 | 1 |
| tech-extra-3cbb84b7a0315d | constraint | 1 | 1 |
| tech-extra-3612fedfbf27ba | technical | 1 | 1 |
| tech-extra-901d01146c64a1 | scenario | 1 | 1 |
| tech-extra-08eca5bac65c05 | constraint | 1 | 1 |
| tech-extra-5e75c1da02c7de | technical | 1 | 1 |
| tech-extra-efd517631b6f8c | scenario | 1 | 1 |
| tech-extra-5c529a2c3b31ba | constraint | 1 | 1 |
| tech-extra-949028ed5bc432 | technical | 1 | 1 |
| tech-extra-2943a9d57a0ecf | scenario | 1 | 1 |
| tech-extra-2d2f5ac78e2c0e | constraint | 1 | 1 |
| tech-extra-89f73a65c59106 | technical | 1 | 1 |
| tech-extra-e1853489b536d7 | scenario | 1 | 1 |
| tech-extra-933171137dd10f | constraint | 1 | 1 |
| tech-extra-2d327b019a5f5a | technical | 1 | 1 |
| tech-extra-652a00c624a308 | scenario | 1 | 1 |
| tech-extra-a2dbbf3b19cb4c | constraint | 1 | 1 |
| tech-extra-21308ef11ca91f | technical | 1 | 1 |
| tech-extra-370a66cbc86d89 | scenario | 5 | 3 |
| tech-extra-fd27bd79afce42 | constraint | 1 | 1 |
| tech-extra-2285688040a114 | technical | 1 | 1 |
| tech-extra-dfd55ee00050c2 | scenario | 1 | 1 |
| tech-extra-2d5f4f0f211950 | constraint | 1 | 1 |
| tech-extra-577bccec10afa9 | technical | 1 | 1 |
| tech-extra-c7a0e6c770d3db | scenario | 1 | 1 |
| tech-extra-02a086527d2ed4 | constraint | 1 | 1 |
| tech-extra-f7fbd7ac82167f | technical | 1 | 1 |
| tech-extra-4e3e2c5a846110 | scenario | 1 | 1 |
| tech-extra-36e310ae2c7774 | constraint | 1 | 1 |
| tech-extra-fcc5f451d911fe | technical | 1 | 1 |
| tech-extra-b155cb11fbbe7b | scenario | 1 | 1 |
| tech-extra-460db5b25e4d79 | constraint | 1 | 1 |
| tech-extra-4a0a1ea3262365 | technical | 1 | 1 |
| tech-extra-10d2f09b9dcdb7 | scenario | 1 | 1 |
| tech-extra-1557a8305ecd62 | constraint | 1 | 1 |
| tech-extra-ffbf7fbb01e66a | technical | 1 | 1 |
| tech-extra-bdfb74caa8b903 | scenario | 1 | 1 |
| tech-extra-e623eef6a01f36 | constraint | 1 | 1 |
| tech-extra-85335773843ae6 | technical | 1 | 1 |
| tech-extra-0f037c40fe559d | scenario | 1 | 1 |
| tech-extra-59573d02c9b69f | constraint | 1 | 1 |
| tech-extra-53d83a7a154421 | technical | 1 | 1 |
| tech-extra-842adcc4dfeb0e | scenario | 1 | 1 |
| tech-extra-23e834cfc35998 | constraint | 1 | 1 |
| tech-extra-db3c164d53da78 | technical | 2 | 2 |
| tech-extra-2e79719733efac | scenario | 1 | 1 |
| tech-extra-60b1dfa50e9a40 | constraint | 1 | 2 |
| tech-extra-de1e49b4a49db6 | technical | 1 | 1 |
| tech-extra-33d36c92ddf5a5 | scenario | 4 | 3 |
| tech-extra-b1c34a3b2b2140 | constraint | 26 | 20 |
| tech-extra-786f245bb1bf2c | technical | 1 | 1 |
| tech-extra-cd249dd047ad5e | scenario | 1 | 1 |
| tech-extra-4347aed868a5a9 | constraint | 1 | 1 |
| tech-extra-a74088cd072f44 | technical | 1 | 1 |
| tech-extra-7c7e2793e60b26 | scenario | 1 | 1 |
| tech-extra-b6e425c5e5a904 | constraint | 1 | 1 |
| tech-extra-e47564d0cc3ead | technical | 1 | 1 |
| tech-extra-60b4c4417b6527 | scenario | 1 | 1 |
| tech-extra-73536c340d097e | constraint | 1 | 1 |
| tech-extra-2370aae85a4797 | technical | 1 | 1 |
| tech-extra-d994e7232d409f | scenario | 1 | 1 |
| tech-extra-a9fd0d055eacdf | constraint | 1 | 1 |

## 한계

추가 질문은 원문에서 생성한 미검수 합성 초안이며, 실제 사용자 질문보다 쉬울 수 있습니다.
질문이 늘어도 같은 기술에서 나온 질문들은 독립 표본이 아닙니다. 서로 다른 기술 그룹 수를 함께 확인하세요.
그룹 부트스트랩은 라벨이 맞다는 조건의 불확실성 추정이며 정답 라벨의 누락·오류까지 반영하지 않습니다.
분할 그룹은 정답 동등성 정의가 아닙니다. 원문이 비슷한 다른 정답이 목록에서 빠졌을 수 있습니다.
모델 성적을 보고 질문을 제외하지 않았고 Test 결과로 재학습·체크포인트 재선택을 하지 않았습니다.
전체 후보 기술 591개, 청크 1773개에서 정확 코사인 검색·기술별 최고 점수로 평가했습니다.
기존 질문·분할·모델 가중치·Supabase는 변경하지 않았습니다. 최종 LLM 답변 품질 평가는 아닙니다.

복수 정답 검수 대상은 [review_flags.md](review_flags.md)에 정리했습니다. 추가 후보가 정답으로 확정되면 두 모델의 순위 점수가 달라질 수 있으므로 현재의 작은 차이를 성능 우열로 단정하지 않습니다.
