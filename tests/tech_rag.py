"""Technology RAG 스모크 테스트 (Supabase). 실행: python -X utf8 -m tests.tech_rag [케이스번호 ...]

케이스마다 분해(B), 남은 문서(동일/유사), 차이점, 탈락 문서(제목)를 출력하고
gold(정답 doc_id)와 expect_match(매칭 유무 기대)가 있으면 PASS/FAIL 을 표시한다.
gold 는 사람이 정한 값이므로, 비어 있는 케이스는 결과를 눈으로 확인한다.
"""
import sys

from app.technology_rag import TechnologyRagPipeline, load_config

# gold 표기: SHARE-N → pub-2026-N, POSCO-N → pos-2025-N
CASES = [
    {
        "name": "1. ORC 터빈 발전·열교환 연동 제어",
        "q": ("우리는 폐열을 회수하는 폐열 회수시스템 기술을 가지고 있는데, 가열로 중저온 배가스 폐열 회수용 200kW급 고효율 ORC 터빈 "
              "발전 시스템을 개발하고자 한다. 이를 위해 터빈 발전 및 열교환 연동 제어 기술을 확보하고자 하는데, 관련 나눔기술과 공고가 있을까?"),
        "gold": ["pos-2025-113"], "expect_match": True,
    },
    {
        "name": "2. 제설로봇 작업부 압력 조정",
        "q": ("우리는 모든 바퀴가 지면에 일정한 하중으로 밀착되도록 하는 노면 적응형 서스펜션 운반차 기술과, RTK 수신 품질 저하 구간에서 "
              "카메라·라이다·IMU 데이터를 융합해 위치를 추정하는 자율주행 농기계 기술을 가지고 있는데, 폭설 대응 반자율주행 "
              "보도·이면도로 제설로봇을 개발하고자 한다. 이를 위해 제설 작업부가 노면에 가하는 압력을 조정하는 기술을 확보하고자 하는데, "
              "관련 나눔기술과 공고가 있을까?"),
        "gold": ["pub-2026-113"], "expect_match": True,
    },
    {
        "name": "3. 히트펌프-데시컨트 제습·냉난방 통합",
        "q": ("우리는 상부 모듈과 하부 모듈, 급배기 댐퍼, 축열 열교환기, 송풍팬, 온도 감지부, 공기질 감지부를 포함해 동시 급배기가 가능한 "
              "폐열회수형 환기장치 시스템 기술을 가지고 있는데, 10RT급 히트펌프-데시컨트 하이브리드 냉·난방제습 통합 시스템을 개발하고자 한다. "
              "이를 위해 제습·냉난방 통합 제어 및 열교환 통합 기술을 확보하고자 하는데, 관련 나눔기술과 공고가 있을까?"),
        "gold": ["pub-2026-170", "pub-2026-172", "pub-2026-173"], "expect_match": True,
    },
    {
        "name": "4. 피복결함 탐상 → 누수 검지",
        "q": ("우리는 기준전극봉의 전위차로 지중 매설 배관 피복결함을 탐상하고 결과를 저장·송출하며 본체와 유무선으로 통신하는 "
              "장치를 가지고 있는데, 실제 누수 발생을 검지하는 기능으로 확장하고자 한다. 피복결함과 누수는 측정 대상이 다르므로 "
              "누수 센싱·판단과 기존 데이터 송수신부의 연계를 보완하려 한다. 관련 나눔기술과 공고가 있을까?"),
        "gold": ["pub-2026-190", "pos-2025-288"], "expect_match": True,
    },
    {
        "name": "5. 이형철근 압연 치수 측정·보정",
        "q": ("우리는 빌렛을 압연기에 장입해 가열·압연한 뒤 수냉 열처리하는 이형철근 제조 기술과, 이형강 압연에 쓰는 압연롤 어셈블리를 "
              "가지고 있는데, 이형철근 압연 라인의 치수 정밀도를 높이고 자동으로 품질을 관리하는 기술을 개발하고자 한다. 이를 위해 압연 "
              "제품의 치수를 측정·보정하는 기술을 확보하고자 하는데, 관련 나눔기술과 공고가 있을까?"),
        "gold": ["pos-2025-208"], "expect_match": True,
    },
    {
        "name": "6. 가열로 연소 제어·온도 편차 최소화",
        "q": ("우리는 미세먼지 저감을 위한 가열로의 산소 농도 제어 장치 및 방법 기술을 가지고 있는데, 50% 이상 에너지 저감을 위한 "
              "용해로 온도변화 5% 이내 폐열활용공정을 개발하고자 한다. 이를 위해 연소 제어 및 온도 편차 최소화 공정 기술을 확보하고자 하는데, "
              "관련 나눔기술과 공고가 있을까?"),
        "gold": ["pos-2025-113"], "expect_match": True,
    },
    {   # 코퍼스(제조·설비 기술나눔)에 없을 법한 주제: has_match=False 가 나와야 한다
        "name": "7. 무관 주제(없음 기대)",
        "q": ("우리는 철강 압연 공정의 두께 제어 기술을 가지고 있는데, 신약 후보물질의 단백질 결합 친화도를 예측하는 "
              "인공지능 모델 기술을 확보하고자 한다. 관련 나눔기술이 있을까?"),
        "gold": [], "expect_match": False,
    },
]


def run(pipe, case):
    r = pipe.answer(case["q"])
    match = r.result.stats["match"]
    print("=" * 100)
    print(f"[{case['name']}]")
    print("분해 B:", r.query_analysis.target if r.query_analysis else None, "(분해 실패 → 원문 검색)" if r.query_analysis is None else "")
    print("보유기술 A:", r.query_analysis.owned_technologies if r.query_analysis else None)
    print("검색 질의:", r.retrieval_query.replace("\n", " | "))
    print("has_match:", r.has_match, r.verdict, "| LLM 판정:", r.llm_verdict, r.downgrade_note)
    diffs = {x.doc_id: x.difference for x in r.references if x.ok}
    for item in match["items"]:
        print(f"  [{item['level']}] {item['doc_id']} {item['title']}")
        print("      차이점:", diffs.get(item["doc_id"], ""))
    for x in r.references:
        if not x.ok:
            print(f"  [코드 탈락] {x.doc_id} {x.level} - {x.reason}")
    print("  탈락(제목):", [f"{d['doc_id']} {d['title']}" for d in match["dropped_titles"]])
    print("비용(추정, 단가는 이전 모델 기준):", r.usage.cost_usd)

    checks = []
    if case["gold"]:
        found = {i["doc_id"]: i["level"] for i in match["items"]}
        for g in case["gold"]:
            checks.append((f"정답 {g} 포함", g in found))
    if case["expect_match"] is not None:
        checks.append((f"has_match == {case['expect_match']}", r.has_match == case["expect_match"]))
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
