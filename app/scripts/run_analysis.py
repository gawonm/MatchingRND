"""Run retrieval, LLM Gap analysis, and final-answer generation."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.common.paths import PROJECT_ROOT, resolve_project_path
from app.integrated_analysis import run_integrated_analysis
from app.orchestrator import AnalysisRequest, AnalysisState, RagOrchestrator
from app.query_parser import parse_query
from app.gap_analysis import OpenAIStructuredLLM


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--query", help="보유기술·기술문제·보완 요청이 포함된 자연어 질문")
    inputs.add_argument("--query-file", help="자연어 질문을 담은 UTF-8 텍스트 파일")
    inputs.add_argument("--request", help="AnalysisRequest JSON 파일")
    inputs.add_argument("--state", help="기존 state.json 재사용 (Retrieval 재실행 안 함)")
    inputs.add_argument("--problem", help="기술문제 직접 입력")
    parser.add_argument("--owned", action="append", default=[], help="보유기술 (여러 번 지정 가능)")
    parser.add_argument("--policy-question")
    parser.add_argument('--backend', choices=('local','supabase'), default='supabase', help='검색 저장소. Supabase는 사전 적재가 필요합니다.')
    parser.add_argument("--model", default="gpt-4o-mini", help="Gap LLM·답변 생성·의미 검토 모델")
    parser.add_argument("--template-only", action="store_true", help="최종 답변 LLM 호출 없이 표·근거 출력")
    parser.add_argument("--output-dir", help="비어 있는 결과 폴더")
    parser.add_argument("--parse-only", action="store_true", help="자연어 입력 해석만 확인하고 검색은 실행하지 않음")
    args = parser.parse_args(argv)
    if (args.owned or args.policy_question) and not args.problem:
        parser.error("--owned, --policy-question은 --problem과 함께 사용하세요.")
    if args.parse_only and (args.request or args.state or args.problem):
        parser.error("--parse-only는 자연어 질문 입력과 함께 사용하세요.")
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M%S_%f")
    output = resolve_project_path(args.output_dir) if args.output_dir else PROJECT_ROOT / "outputs" / stamp
    try:
        options = {'orchestrator': RagOrchestrator(backend=args.backend)}
        if args.query or args.query_file or not (args.state or args.request or args.problem):
            query = args.query or (resolve_project_path(args.query_file).read_text(encoding="utf-8-sig")
                                  if args.query_file else input("보유기술과 개발하고 싶은 내용을 한 문장으로 입력하세요:\n> "))
            interpretation = parse_query(query, llm=OpenAIStructuredLLM(model=args.model))
            options["request"] = interpretation.request
            print("보유기술:", ", ".join(interpretation.request.owned_technologies) or "명시 없음")
            print("개발목표:", interpretation.parsed.development_goal)
            print("보완 요청:", ", ".join(interpretation.request.unmet_elements) or "명시 없음")
            for warning in interpretation.warnings:
                print(warning)
            if args.parse_only:
                output.mkdir(parents=True, exist_ok=False)
                (output / "input.json").write_text(interpretation.model_dump_json(indent=2) + "\n", encoding="utf-8")
                print(f"입력 해석 결과: {output / 'input.json'}")
                return 0
        elif args.state:
            options["state"] = AnalysisState.model_validate_json(resolve_project_path(args.state).read_text(encoding="utf-8"))
        elif args.request:
            options["request"] = AnalysisRequest.model_validate_json(resolve_project_path(args.request).read_text(encoding="utf-8"))
        else:
            options["request"] = AnalysisRequest(problem=args.problem, owned_technologies=args.owned,
                                                  policy_question=args.policy_question)
        print("같은 Retrieval 결과에서 Gap 분석·답변 생성·검증을 실행합니다.", flush=True)
        result = run_integrated_analysis(**options, output_dir=output,
                                         model=args.model, template_only=args.template_only)
        if "interpretation" in locals():
            (output / "input.json").write_text(interpretation.model_dump_json(indent=2) + "\n", encoding="utf-8")
        for method, answer in result.answers.items():
            role = "주요 분석" if method == "llm" else "비교 실험"
            print(f"\n[{role}: {method}] 상태: {answer.status}\n{answer.markdown}")
        if result.errors:
            print("실패 단계:", json.dumps(result.errors, ensure_ascii=False))
        print(f"결과 폴더: {output}")
        return 1 if result.errors else 0
    except Exception as error:
        print(f"실행 실패: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
