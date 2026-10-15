"""Technology RAG 스모크 테스트 (Supabase). 실행: python -X utf8 -m tests.tech_rag [케이스번호 ...]

입력은 상류에서 이미 나뉘어 오는 값과 같은 형태다: 보유기술(owned, A)과 원하는 기술(target, B).
Technology RAG 는 문장을 분해하지 않으므로 케이스마다 A·B 를 직접 적는다.
(B 는 예전 질의 분해가 '확보하려는 기술'로 뽑던 부분이다. 이미 보유한 기능은 B 에서 뺐다.)

케이스마다 문서별 판정(same/similar), 대응한 B 항목, 차이점, none(탈락) 사유를 출력하고
gold(정답 doc_id)와 expect_match(매칭 유무 기대)가 있으면 PASS/FAIL 을 표시한다.
gold 는 사람이 정한 값이므로, 비어 있는 케이스는 결과를 눈으로 확인한다.
"""
import sys

from app.technology_rag import TechnologyRagPipeline, load_config

# gold 표기: SHARE-N → pub-2026-N, POSCO-N → pos-2025-N
# owned: 이미 보유한 기술(A) 목록 / target: 확보하려는 기술(B) / search_terms: B 의 동의어(선택, 없으면 B 만으로 검색)
CASES = [
    {
        "name": "1. ORC 터빈 발전·열교환 연동 제어",
        "owned": ["폐열을 회수하는 폐열 회수시스템 기술"],
        "target": "터빈 발전 및 열교환 연동 제어 기술",
        "gold": ["pos-2025-113"], "expect_match": True,
    },
    {
        "name": "2. 제설로봇 작업부 압력 조정",
        "owned": ["모든 바퀴가 지면에 일정한 하중으로 밀착되도록 하는 노면 적응형 서스펜션 운반차 기술",
                  "RTK 수신 품질 저하 구간에서 카메라·라이다·IMU 데이터를 융합해 위치를 추정하는 자율주행 농기계 기술"],
        "target": "제설 작업부가 노면에 가하는 압력을 조정하는 기술",
        "gold": ["pub-2026-113"], "expect_match": True,
    },
    {
        "name": "3. 히트펌프-데시컨트 제습·냉난방 통합",
        "owned": ["상부 모듈과 하부 모듈, 급배기 댐퍼, 축열 열교환기, 송풍팬, 온도 감지부, 공기질 감지부를 포함해 "
                  "동시 급배기가 가능한 폐열회수형 환기장치 시스템 기술"],
        "target": "제습·냉난방 통합 제어 및 열교환 통합 기술",
        "gold": ["pub-2026-170", "pub-2026-172", "pub-2026-173"], "expect_match": True,
    },
    {
        "name": "4. 피복결함 탐상 → 누수 검지",
        "owned": ["기준전극봉의 전위차로 지중 매설 배관 피복결함을 탐상하고 결과를 저장·송출하며 본체와 유무선으로 통신하는 장치"],
        "target": "지중 매설 배관의 누수 발생을 검지하는 누수 센싱·판단 기술",
        "gold": ["pub-2026-190", "pos-2025-288"], "expect_match": True,
    },
    {
        "name": "5. 이형철근 압연 치수 측정·보정",
        "owned": ["빌렛을 압연기에 장입해 가열·압연한 뒤 수냉 열처리하는 이형철근 제조 기술",
                  "이형강 압연에 쓰는 압연롤 어셈블리"],
        "target": "압연 제품의 치수를 측정·보정하는 기술",
        "gold": ["pos-2025-208"], "expect_match": True,
    },
    {
        "name": "6. 가열로 연소 제어·온도 편차 최소화",
        "owned": ["미세먼지 저감을 위한 가열로의 산소 농도 제어 장치 및 방법 기술"],
        "target": "연소 제어 및 온도 편차 최소화 공정 기술",
        "gold": ["pos-2025-113"], "expect_match": True,
    },
    {   # 코퍼스(제조·설비 기술나눔)에 없을 법한 주제: has_match=False 가 나와야 한다
        "name": "7. 무관 주제(없음 기대)",
        "owned": ["철강 압연 공정의 두께 제어 기술"],
        "target": "신약 후보물질의 단백질 결합 친화도를 예측하는 인공지능 모델 기술",
        "gold": [], "expect_match": False,
    },
]


def run(pipe, case):
    r = pipe.answer(case["owned"], case["target"], search_terms=case.get("search_terms"))
    match = r.result.stats["match"]
    print("=" * 100)
    print(f"[{case['name']}]")
    print("보유기술 A:", r.tech_input.owned_technologies)
    print("원하는 기술 B:", r.tech_input.targets, "| 검색어:", r.tech_input.search_terms)
    print("검색 질의:", " | ".join(r.retrieval_query.splitlines()))
    print("has_match:", r.has_match, "| verdict:", r.verdict, "| LLM 판정:", r.llm_verdict, r.downgrade_note)
    diffs = {x.doc_id: x.difference for x in r.references if x.ok}
    for item in match["items"]:
        print(f"  [{item['level']}] {item['doc_id']} {item['title']}  (대응 B: {item['matched_target']})")
        print("      차이점:", diffs.get(item["doc_id"], ""))
    for x in r.references:
        if not x.ok:
            print(f"  [코드 탈락] {x.doc_id} {x.level} - {x.reason}")
    print("  none(탈락):")
    for item in match["none"]:
        print(f"    [none] {item['doc_id']} {item['title']} - {item['reason']}")
    print("비용(추정, 단가는 이전 모델 기준):", r.usage.cost_usd)

    checks = []
    if case["gold"]:
        found = {i["doc_id"]: i["level"] for i in match["items"]}
        for g in case["gold"]:
            checks.append((f"정답 {g} 포함", g in found))
    if case["expect_match"] is not None:
        checks.append((f"has_match == {case['expect_match']}", r.has_match == case["expect_match"]))
    # 모든 남은 문서에 등급(same|similar)과 대응 B 항목이 기록돼 있어야 한다
    for cand in r.result.candidates:
        checks.append((f"{cand.doc_id} extra.match_level 기록",
                       cand.extra.get("match_level") in {"same", "similar"} and cand.extra.get("matched_target") is not None))
    for label, ok in checks:
        print("  PASS" if ok else "  FAIL", label)
    return checks, len(match["items"])


if __name__ == "__main__":
    cfg = load_config()
    cfg.index.backend = "supabase"   # .env 의 SUPABASE_* 로 접속 (from_config 가 이 설정값만 본다)
    pipe = TechnologyRagPipeline.from_config(cfg)
    picked = [int(a) for a in sys.argv[1:]] or range(len(CASES))
    all_checks, n_items = [], []
    for i in picked:
        checks, n = run(pipe, CASES[i])
        all_checks += checks
        n_items.append(n)
    print("=" * 100)
    gold_checks = [c for c in all_checks if c[0].startswith("정답")]
    print(f"요약: 정답 포착 {sum(ok for _, ok in gold_checks)}/{len(gold_checks)} | "
          f"전체 PASS {sum(ok for _, ok in all_checks)}/{len(all_checks)} | 케이스당 남은 문서 {n_items}")
