"""통합 흐름 스모크 테스트 (Supabase + OpenAI 필요).

실행: python -X utf8 -m tests.integration_e2e [--template-only] [--query "..."] [--model gpt-5.6-luna]

자연어 질문 → 입력 해석 → Technology → NTIS → RFP → Gap 분석 → 최종 답변까지 한 번에 돌리고,
단계마다 결과 요약과 PASS/FAIL 을 출력한다. 결과 파일은 outputs/integration_e2e_<시각>/ 에 저장된다.
단계가 실패해도 이후 단계는 건너뛰고 어디서 멈췄는지 보여 준다.
마지막에 단계별 소요 시간·LLM 호출 수·토큰 사용량 표를 출력한다 (OpenAI SDK 호출을 직접 세므로 모든 단계가 포함된다).
"""
from __future__ import annotations

from app.common.llm_config import DEFAULT_LLM_MODEL

import argparse
import functools
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from app.answer_format import COMMON_RND_INTRO, COMMON_RND_NOTICES
from app.common.paths import PROJECT_ROOT
from app.gap_analysis import OpenAIStructuredLLM
from app.integrated_analysis import run_integrated_analysis
from app.orchestrator import OrchestrationError, RagOrchestrator
from app.query_parser import parse_query

QUERY = (
    "우리는 모든 바퀴가 지면에 일정한 하중으로 밀착되도록 하는 노면 적응형 서스펜션 운반차 기술과, RTK 수신 품질 저하 구간에서 카메라·라이다·IMU 데이터를 융합해 위치를 추정하는 자율주행 농기계 기술을 가지고 있는데, 폭설 대응 반자율주행 보도·이면도로 제설로봇을 개발하고자 한다. 이를 위해 제설 작업부가 노면에 가하는 압력을 조정하는 기술을 확보하고자 하는데, 관련 나눔기술과 공고가 있을까?"
)

checks: list[tuple[str, bool]] = []


class Metrics:
    """단계별 소요 시간·LLM 호출 수·토큰. OpenAI SDK의 chat.completions / responses 호출을 센다."""

    def __init__(self):
        self.rows: dict[str, dict[str, float]] = {}
        self.current: str | None = None

    def _row(self, name):
        return self.rows.setdefault(name, {"seconds": 0.0, "calls": 0, "tokens": 0})

    @contextmanager
    def stage(self, name):
        previous, self.current = self.current, name
        start = time.perf_counter()
        try:
            yield
        finally:
            self._row(name)["seconds"] += time.perf_counter() - start
            self.current = previous

    def wrap_runner(self, name, runner):
        @functools.wraps(runner)
        def wrapped(*args, **kwargs):
            with self.stage(name):
                return runner(*args, **kwargs)
        return wrapped

    def count_call(self):
        self._row(self.current or "기타")["calls"] += 1

    def add_tokens(self, result):
        usage = getattr(result, "usage", None)
        total = getattr(usage, "total_tokens", None)
        if total is None and usage is not None:  # Responses API
            total = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "output_tokens", 0) or 0)
        self._row(self.current or "기타")["tokens"] += total or 0

    @contextmanager
    def patch_openai(self):
        from openai.resources.chat.completions import Completions
        targets = [(Completions, "create"), (Completions, "parse")]
        try:
            from openai.resources.responses import Responses
            targets += [(Responses, "create"), (Responses, "parse")]
        except ImportError:
            pass
        originals = [(cls, name, getattr(cls, name)) for cls, name in targets if hasattr(cls, name)]
        metrics = self

        def make(original):
            @functools.wraps(original)
            def wrapper(self, *args, **kwargs):
                metrics.count_call()
                result = original(self, *args, **kwargs)
                metrics.add_tokens(result)
                return result
            return wrapper

        for cls, name, original in originals:
            setattr(cls, name, make(original))
        try:
            yield
        finally:
            for cls, name, original in originals:
                setattr(cls, name, original)

    def report(self):
        """호출·토큰은 가장 안쪽 단계에 기록되므로 합계는 모든 행의 합, 시간은 최상위 단계의 합."""
        nested = [n for n in self.rows if n in NESTED_STAGES]
        print("\n" + "-" * 100)
        print(f"{'단계':<24}{'소요(초)':>10}{'LLM 호출':>10}{'토큰':>12}")
        for name, row in self.rows.items():
            if name in NESTED_STAGES:
                continue
            calls, tokens = row["calls"], row["tokens"]
            if name.startswith("2."):  # 캐스케이드 행은 하위 모듈 호출을 포함해 표시
                calls += sum(self.rows[n]["calls"] for n in nested)
                tokens += sum(self.rows[n]["tokens"] for n in nested)
            print(f"{name:<24}{row['seconds']:>10.1f}{int(calls):>10}{int(tokens):>12}")
            if name.startswith("2."):
                for n in nested:
                    r = self.rows[n]
                    print(f"{n:<24}{r['seconds']:>10.1f}{int(r['calls']):>10}{int(r['tokens']):>12}")
        top = [r for n, r in self.rows.items() if n not in NESTED_STAGES]
        seconds = sum(r["seconds"] for r in top)
        calls = sum(r["calls"] for r in self.rows.values())
        tokens = sum(r["tokens"] for r in self.rows.values())
        print(f"{'합계':<24}{seconds:>10.1f}{int(calls):>10}{int(tokens):>12}")


NESTED_STAGES = {"  Technology", "  NTIS", "  RFP"}
metrics = Metrics()


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
    ap.add_argument("--model", default=DEFAULT_LLM_MODEL)
    ap.add_argument("--template-only", action="store_true", help="최종 답변 LLM 호출 없이 표·근거만 출력")
    ap.add_argument("--backend", choices=("local", "supabase"), default="supabase")
    args = ap.parse_args(argv)
    with metrics.patch_openai():
        code = run(args)
    metrics.report()
    return code


def run(args) -> int:
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M%S")
    out = PROJECT_ROOT / "outputs" / f"integration_e2e_{stamp}"

    print("=" * 100)
    print("질문:", args.query)

    # 1) 입력 해석
    print("\n[1. 입력 해석]")
    with metrics.stage("1. 입력 해석"):
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
        orchestrator = RagOrchestrator(backend=args.backend)
        for attr, label in (("technology_runner", "  Technology"), ("ntis_runner", "  NTIS"),
                            ("rfp_runner", "  RFP")):
            setattr(orchestrator, attr, metrics.wrap_runner(label, getattr(orchestrator, attr)))
        with metrics.stage("2. 검색 캐스케이드"):
            state = orchestrator.run(req)
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
    with metrics.stage("3. Gap 분석·최종 답변"):
        result = run_integrated_analysis(state=state, modes=("llm",), output_dir=out,
                                         model=args.model, template_only=args.template_only)
    check("Gap/답변 단계 오류 없음", not result.errors)
    for stage, message in result.errors.items():
        print(f"  오류 {stage}: {message}")
    answer = result.answers.get("llm")
    if answer is not None:
        print(f"\n  답변 상태: {answer.status}\n")
        print(answer.markdown)
    check("최종 답변 생성됨", answer is not None and bool(answer.markdown.strip()))
    check("최종 답변에 공통 R&D 유의사항 고정 문구 포함",
          answer is not None and all(text in answer.markdown for text in (*COMMON_RND_INTRO, *COMMON_RND_NOTICES)))
    check("최종 답변에 법령 검색 섹션이 없음", answer is not None and "## 6. 관련 법령" not in answer.markdown)

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
