# 통합 분석·답변 테스트

LLM Gap 분석을 주요 결과로, local 분석을 비교 실험으로 사용합니다.
두 방식은 Orchestrator를 한 번 실행해 얻은 같은 `AnalysisState`에서 시작합니다.
local은 기본적으로 키워드만 사용합니다. Python 함수에 `embed`를 전달하면
두 방식의 후보 비교에 같은 임베딩 함수를 적용할 수 있습니다.

## 실행 전 준비

- 프로젝트 루트에서 필요한 패키지가 설치된 Python 환경을 사용하세요.
  기본 `python`과 VS Code에서 선택한 가상환경의 Python은 다를 수 있습니다.
- `.env`에 `OPENAI_API_KEY`가 필요합니다. Supabase Secret key와는 다른 키입니다.
- Technology와 NTIS의 기존 문서·청크·검색 인덱스를 준비하세요.
  `data/raw/technology`에는 기본 분석 대상 기술소개 PDF 2개와 대응 목록이 필요합니다.
- RFP·법령은 기존 Orchestrator에서 첫 실행 시 인덱스를 준비합니다.
- 실제 실행은 Technology·NTIS·Gap·최종 생성/의미 검토의 API 사용 비용이 발생할 수 있습니다.
  `--model`은 Gap 및 최종 답변에 적용되며 Technology·NTIS 모델은 각각의 기존 설정을 따릅니다.

## 처음 실행

기획처럼 한 문장에 보유기술·개발목표·보완 요청을 함께 입력할 수 있습니다.
인자를 생략하면 터미널에서 질문을 입력받습니다.

```powershell
python -X utf8 -m app.scripts.run_analysis
```

압연 예지보전 예시 질문은 `examples/rolling_query.txt`에 들어 있습니다.
질문 파일을 수정하거나 `--query`에 질문 전체를 전달하세요.

```powershell
python -X utf8 -m app.scripts.run_analysis --query-file examples/rolling_query.txt
```

입력 구조화에는 LLM 호출이 한 번 추가됩니다. 보유기술과 보완 요청을 분리하고 원문 근거를
대조하지만, LLM의 역할 분류가 항상 정확하다고 보장하지는 않습니다. `input.json`에서
해석을 확인할 수 있습니다. 기술문제에는 요약 대신 최초 질문 전체가 전달됩니다.
단순 공고 검색 요청을 법령 질문으로 자동 해석하지 않습니다.
보완 요청은 사용자 입력 항목이며, 자동 Gap 판정으로 취급하지 않습니다.

입력 구조화 결과의 기술명·인용문을 원문에서 확인할 수 없으면 실패한 항목과 이전
추출 결과를 LLM에 돌려줘 최대 2회 다시 추출합니다. 교정 시에는 원문의 단어 번호 표에서
시작·끝 범위를 선택하게 하고, 코드는 선택한 원문을 그대로 복사합니다. LLM이 인용문의
어미·조사를 바꾸는 문제를 막고, 범위 밖 선택이나 기존 역할 누락은 거절합니다.
교정 후에도 원문 검증에 실패하면
오류를 반환합니다. 임의의 기술명을 받아들이거나 실패한 보유기술을 누락시키지 않습니다.
`input.json`의 `attempts`, `validation_errors`, `extraction_method`에 교정 이력이 남습니다. 최종 개발목표와
별도 보완 요청을 구분하고, 일반적인 기술 연결 조건 질문은 법령 질문에서 제외합니다.

검색 전 입력 해석만 확인하려면:

```powershell
python -X utf8 -m app.scripts.run_analysis --query-file examples/rolling_query.txt --parse-only
```

이 모드는 입력 구조화 API만 호출하며 검색·Gap 분석·최종 설명 생성은 실행하지 않습니다.

`examples/analysis_request.json`의 질문·보유기술을 수정하고 실행합니다.
`policy_question`은 제도 질문이 필요한 경우에만 문자열로 입력하세요.

```powershell
python -X utf8 -m app.scripts.run_analysis --request examples/analysis_request.json
```

직접 질문을 입력할 수도 있습니다.

```powershell
python -X utf8 -m app.scripts.run_analysis --problem "제조환경에서 작업자와 지게차 충돌을 줄이고 싶다." --owned "SLAM" --owned "영상 객체 인식"
```

결과는 한국 시간 기준 이름의 `outputs/<실행시간>/` 폴더에 저장됩니다.

| 파일 | 용도 |
|---|---|
| `state.json` | 공통 Retrieval 입력·출력·Query 이력, 이후 재실행에 사용 |
| `gap_llm.json` / `gap_local.json` | 방식별 Gap 원본 리포트 |
| `answer.md` | LLM 주요 분석에 대한 최종 답변 |
| `answer_llm.md` / `answer_local.md` | 방식별 설명; local은 잠정 판정으로 표시 |
| `answer_llm.json` / `answer_local.json` | 인용·의미 검토 및 제외된 주장 기록 |
| `comparison.json` | 동일 명칭 판정 비교, 각 방식에만 있는 항목, 실행 정보·실패 단계 |

기존 결과가 있는 폴더는 덮어쓰지 않습니다. 한 방식이 실패하면 다른 방식은 계속 실행하며,
실패 단계는 `comparison.json`에 남기고 CLI 종료코드는 1로 반환합니다.
LLM 결과가 없을 때 local을 주요 답변으로 자동 대체하지 않습니다.

## 검색을 반복하지 않고 분석 비교

실제 출력 폴더 이름으로 바꿔 실행하세요.

```powershell
python -X utf8 -m app.scripts.run_analysis --state outputs/실행폴더/state.json
```

LLM만 실행하려면 `--mode llm`, local만 실행하려면 `--mode local`을 추가합니다.
기존 state에서 local 결과를 API 호출 없이 표·근거만으로 확인하려면:

```powershell
python -X utf8 -m app.scripts.run_analysis --state outputs/실행폴더/state.json --mode local --template-only
```

`--template-only`는 최종 설명 생성·의미 검토 호출만 생략합니다.
`--mode llm`이면 Gap LLM은 여전히 호출됩니다. `--request`나 `--problem`이면
Orchestrator의 Technology·NTIS 호출도 발생합니다.

## 답변 검증 방식과 한계

1. 생성기에 Gap별 RFP·기업·외부기술 근거 ID 및 검증된 매칭 정보를 전달합니다.
   모델은 근거 ID를 선택하고 `quote=null`로 반환할 수 있으며 코드는 실제 제공한
   원문을 연결합니다. 모델이 직접 작성한 인용문도 기존 원문 대조를 통과해야 합니다.
2. Gap 설명은 올바른 행과 연결되어야 하며 해당 행의 RFP 요구 근거를 포함해야 합니다.
   기존보유·외부기술보완·부분충족 설명에는 그 판정을 뒷받침하는 출처 근거도 필요합니다.
   응답 스키마에서 Gap 설명은 정수 `gap_index`, 그 외 설명은 `gap_index=null`로 제한합니다.
   유효한 Gap 행을 선택하면 코드가 그 행의 필수 RFP·매칭 근거를 함께 연결합니다.
   모델이 선택한 잘못된 ID나 가짜 인용을 제거해서 통과시키지는 않습니다.
3. 근거와 판정 규칙을 확인할 수 없는 최종 Gap 행은 근거부족으로 처리합니다.
4. 별도 LLM 호출로 주장 전체가 근거 범위 안에 있는지 검토합니다.
5. 실패·누락·중복 검토를 받은 주장은 사용자 답변에서 제외하고 JSON 감사 기록에 보존합니다.
6. 거절된 설명은 거절 사유와 해당 행의 근거 정보를 사용해 최대 2회 재생성합니다.
   통과한 설명은 보존하고, 교정 후에도 검증에 실패한 설명은 계속 제외합니다.
   `answer_llm.json`의 `stats.draft_attempts`에 시도별 판정이 남습니다.

검토 LLM에는 각 행의 구조화된 매칭·판정 문맥도 전달합니다. '현재 제공 자료에서
충족 근거를 확인하지 못함'은 이 분석 범위의 추론이며 기술 미보유의 확정이 아닙니다.
인용 검증이나 의미 검토를 생략하여 설명을 통과시키지는 않습니다.
부분 보완 설명에 전체 요구 충족을 요구하거나, RFP의 추가 요구 C가 원래 B와 다르다는
이유만으로 C의 원문 사실·Gap 설명을 제외하지 않도록 검토 범위를 명시합니다.

인용 검증은 문장이 실제 자료에 존재한다는 확인입니다. LLM 의미 검토도 오류가 가능하며,
기술 충족 여부나 사업 신청자격을 입증하지 않습니다.
두 Gap 방식은 추출 단위가 다르므로 같은 이름의 요구기술만 직접 비교합니다.
한쪽에만 추출된 항목의 수나 라벨 차이를 정확도 지표로 해석하지 마세요.

자동 테스트:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

테스트는 가짜 모델·메모리 입력을 사용하며 원격 API를 호출하지 않습니다.
