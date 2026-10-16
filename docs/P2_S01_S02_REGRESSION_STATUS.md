# P2 S01/S02 회귀 상태

기준 자료: 기존 실행의 `s01/report_view_response.json`, `s01/analysis2.txt`,
`s02/report_view_response.json`, `s02/analysis_s02_core.txt` (Claude scratchpad).
이 문서는 새 API 호출이나 RAG 재실행 결과가 아니다.

| 구분 | P2 수정 전 실데이터에서 확인한 오류 | P2 수정 후 무료 테스트로 확인한 범위 | 미확인 |
| --- | --- | --- | --- |
| S01 폐열→ORC | 원문 인용은 검증됐지만 Gap 설명 생성 시도에서 Gap Claim이 반려됐다. 무관한 외부 기술 연결이 있었고 보유기술 연결은 없었다. | `test_s01_s02_incidental_external_overlap_is_rejected`가 우연한 단어 중첩에 따른 외부기술 연결을 막는다. 기존 라벨을 반려만으로 일괄 변경하지 않고, 반려·경고를 별도 표시하는 테스트가 있다. | 실제 S01 재실행의 추천 순위, 연결률, 최종 Gap 정확도. |
| S02 제설로봇 | 저장된 응답은 `partial`, `rejected_claims=2`였다. 삽날 접지압 기술이 경로 계획(`gap-3`)과 안전벨트 공정의 제어변수(`gap-30`)에 연결됐다. `not_analyzed` 플라스틱 사출 과제가 `gap-18/31/32`의 `rfp_ids`에 들어갔다. | 같은 외부기술 오매칭 방지 fixture와 `test_not_analyzed_task_sharing_pdf_is_not_added_to_gap_rfp_ids`가 해당 경계를 검증한다. | 실제 S02 재실행의 최종 매칭·Gap 정확도와 PDF 정량요건 8건의 근거 검증. |

현재 P2 범위는 Gap Claim 반려 표시, 명백한 외부기술 오매칭 차단,
미분석 RFP의 Gap 연결 차단이다. 보유기술 연결률, RFP 재랭킹, PDF 정량요건 파싱은 개선·실데이터 검증 대상에 남아 있다.
무료 fixture 통과는 실데이터의 기술 충족 판단 정확도를 입증하지 않는다.
