"""통합 흐름 스모크 테스트 (Supabase + OpenAI 필요).

실행: python -X utf8 -m tests.integration_e2e [--template-only] [--query "..."] [--model gpt-4o-mini]

자연어 질문 → 입력 해석 → Technology → NTIS → RFP 캐스케이드 → Gap 분석 → 최종 답변까지 한 번에 돌리고,
단계마다 결과 요약과 PASS/FAIL 을 출력한다. 결과 파일은 outputs/integration_e2e_<시각>/ 에 저장된다.
단계가 실패해도 이후 단계는 건너뛰고 어디서 멈췄는지 보여 준다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from app.common.paths import PROJECT_ROOT
from app.gap_analysis import OpenAIStructuredLLM
from app.integrated_analysis import run_integrated_analysis
from app.orchestrator import OrchestrationError, RagOrchestrator
from app.query_parser import parse_query

QUERY = (
    "우리는 폐열을 회수하는 폐열 회수시스템 기술을 가지고 있는데, 가열로 중저온 배가스 폐열 회수용 200kW급 "
    "고효율 ORC 터빈 발전 시스템을 개발하고자 한다. 이를 위해 터빈 발전 및 열교환 연동 제어 기술을 확보하고자 하는데, "
    "관련 나눔기술과 공고가 있을까?"
)

checks: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> bool:
    checks.append((label, bool(ok)))
    print("  PASS" if ok else "  FAIL", label)
    return bool(ok)


def show_module(name: str, module) -> None:
    print(f"\n[{name}] 질의: {' | '.join(str(module.query).splitlines())[:200]}")
    print(f"  후보 {len(module.candidates)}건 | 기술요소 {len(module.tech_elements)}건")
    for c in module.candidates:
        level = c.extra.get("match_level") if getattr(c, "extra", None) else None
        print(f"  - {c.doc_id} {c.title}" + (f"  [{level}]" if level else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", default=QUERY)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--template-only", action="store_true", help="최종 답변 LLM 호출 없이 표·근거만 출력")
    ap.add_argument("--backend", choices=("local", "supabase"), default="supabase")
    args = ap.parse_args(argv)

    stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M%S")
    out = PROJECT_ROOT / "outputs" / f"integration_e2e_{stamp}"

    print("=" * 100)
    print("질문:", args.query)

    # 1) 입력 해석
    print("\n[1. 입력 해석]")
    interp = parse_query(args.query, llm=OpenAIStructuredLLM(model=args.model))
    req = interp.request
    print("  보유기술:", req.owned_technologies)
    print("  기술문제/개발목표:", req.problem)
    print("  보완 요청:", req.unmet_elements)
    for w in interp.warnings:
        print("  경고:", w)
    check("보유기술이 추출됨", bool(req.owned_technologies))
    check("개발목표(problem)가 추출됨", bool(req.problem.strip()))
    check("보완 요청(확보하려는 기술)이 추출됨", bool(req.unmet_elements))

    # 2) Technology → NTIS → RFP 캐스케이드
    print("\n[2. 검색 캐스케이드]")
    try:
        state = RagOrchestrator(backend=args.backend).run(req)
    except OrchestrationError as error:
        print(f"  실패 단계: {error.stage}\n  원인: {error.__cause__!r}")
        check(f"{error.stage} 단계 실행", False)
        return summary()
    check("Technology/NTIS/RFP 캐스케이드 완료", True)

    show_module("Technology", state.technology)
    show_module("NTIS", state.ntis)
    show_module("RFP", state.rfp)
    for w in state.warnings:
        print("  경고:", w)

    check("Technology 후보 존재", bool(state.technology.candidates))
    check("Technology 후보마다 match_level(same|similar)",
          all(c.extra.get("match_level") in {"same", "similar"} for c in state.technology.candidates))
    check("NTIS 후보 존재", bool(state.ntis.candidates))
    check("RFP 후보 존재", bool(state.rfp.candidates))
    check("검증된 기술요소로 질의가 확장됨", bool(state.external_elements) or bool(state.ntis_elements))

    # 3) Gap 분석 + 최종 답변 (위 state 그대로 사용 — 검색 재실행 없음)
    print("\n[3. Gap 분석·최종 답변]")
    run = run_integrated_analysis(state=state, modes=("llm",), output_dir=out,
                                  model=args.model, template_only=args.template_only)
    check("Gap/답변 단계 오류 없음", not run.errors)
    for stage, message in run.errors.items():
        print(f"  오류 {stage}: {message}")
    answer = run.answers.get("llm")
    if answer is not None:
        print(f"\n  답변 상태: {answer.status}\n")
        print(answer.markdown)
    check("최종 답변 생성됨", answer is not None and bool(answer.markdown.strip()))

    print(f"\n결과 폴더: {out}")
    return summary()


def summary() -> int:
    print("=" * 100)
    failed = [label for label, ok in checks if not ok]
    print(f"요약: PASS {len(checks) - len(failed)}/{len(checks)}")
    for label in failed:
        print("  FAIL:", label)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
