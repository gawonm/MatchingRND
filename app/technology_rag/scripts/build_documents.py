"""
PDF 파싱 결과 + 엑셀 → data/processed/technology/tech_documents.jsonl  (A 단계의 지식베이스 원본)

실행:
    .venv\\Scripts\\python.exe -X utf8 -m app.technology_rag.scripts.build_documents            # PDF 캐시 재사용
    .venv\\Scripts\\python.exe -X utf8 -m app.technology_rag.scripts.build_documents --reparse  # PDF부터 다시 (약 2분)

전제: python -m app.technology_rag.scripts.build_pdf_documents 로 data/processed/technology/pdf_documents.jsonl 이 만들어져 있어야 한다.
      (--reparse 면 이 스크립트가 직접 PDF를 파싱한다)
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from app.technology_rag.paths import PROJECT_ROOT, RAW_DIR, PROCESSED_DIR
from app.common.schemas import SourceType
from app.technology_rag.schemas import TechDocument
from app.technology_rag import constants as C
from app.technology_rag.parsing.excel_loader import load_excel
from app.technology_rag.parsing.merger import MergeReport, merge_documents
from app.technology_rag.parsing.pdf_parser import iter_documents

ROOT = PROJECT_ROOT   # app.technology_rag.paths — TECHRAG_ROOT 로 바꿀 수 있다
RAW = RAW_DIR
PDF_CACHE = PROCESSED_DIR / "pdf_documents.jsonl"
OUT = PROCESSED_DIR / "tech_documents.jsonl"

SOURCES = (SourceType.PUBLIC_TECH, SourceType.POSCO_TECH)


def load_pdf_documents(reparse: bool) -> list[TechDocument]:
    if not reparse and PDF_CACHE.exists():
        with PDF_CACHE.open(encoding="utf-8") as f:
            docs = [TechDocument.model_validate_json(line) for line in f if line.strip()]
        print(f"PDF 캐시 로드: {len(docs)}건 ({PDF_CACHE.name})")
        return docs
    docs = []
    for src in SOURCES:
        got = list(iter_documents(src, RAW))
        print(f"[{src.value}] {len(got)}건 파싱")
        docs.extend(got)
    return docs


def validate(docs: list[TechDocument], report: MergeReport) -> list[str]:
    problems: list[str] = []
    if report.unjoined_docs:
        problems.append(f"조인 실패 {len(report.unjoined_docs)}건: {report.unjoined_docs[:5]}")
    if report.unused_excel:
        problems.append(f"PDF에 없는 엑셀 행 {len(report.unused_excel)}건: {report.unused_excel[:5]}")

    for src in SOURCES:
        n = sum(1 for d in docs if d.source == src)
        if n != C.SOURCE_SPECS[src]["expected_records"]:
            problems.append(f"{src.value}: {n}건 (기대 {C.SOURCE_SPECS[src]['expected_records']})")

    for d in docs:
        if d.source == SourceType.PUBLIC_TECH and d.transfer_condition.value == "미상":
            problems.append(f"{d.doc_id} 이전조건 미상")
        if d.source == SourceType.POSCO_TECH and not (d.sharing_start and d.sharing_end):
            problems.append(f"{d.doc_id} 나눔기간 없음")
        if not (d.patent.expiry_date and d.taxonomy.major and d.provider):
            problems.append(f"{d.doc_id} 필수 메타 누락")
    return problems


def print_report(docs: list[TechDocument], report: MergeReport) -> None:
    print("\n" + "=" * 72)
    print(f"병합: {report.joined}/{report.total_docs}건 조인")
    print("\n[PDF ↔ 엑셀 교차검증] 불일치 (PDF 값 유지, 기록용)")
    if not report.mismatches:
        print("  불일치 없음")
    for k, v in sorted(report.mismatches.items()):
        print(f"  {k:<22}{len(v):>4}건   예) {v[0]}")

    pub = [d for d in docs if d.source == SourceType.PUBLIC_TECH]
    pos = [d for d in docs if d.source == SourceType.POSCO_TECH]
    print("\n[엑셀로 보강된 메타데이터]")
    print(f"  이전조건(공공기관): {dict(collections.Counter(d.transfer_condition.value for d in pub))}")
    print(f"  나눔기간(포스코)  : {collections.Counter((str(d.sharing_start), str(d.sharing_end)) for d in pos)}")
    print(f"  출원일 확보       : 공공 {sum(1 for d in pub if d.patent.application_date)}/{len(pub)}"
          f"  포스코 {sum(1 for d in pos if d.patent.application_date)}/{len(pos)}")
    print(f"  IPC 확보(포스코)  : {sum(1 for d in pos if d.patent.ipc)}/{len(pos)}")
    print(f"  출원인 확보(포스코): {sum(1 for d in pos if d.applicant)}/{len(pos)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    docs = load_pdf_documents(args.reparse)
    records = {src: load_excel(src, RAW) for src in SOURCES}
    for src, r in records.items():
        print(f"엑셀 로드 [{src.value}]: {len(r)}행")

    report = merge_documents(docs, records)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(d.model_dump_json() + "\n")
    print(f"저장: {args.out}  ({args.out.stat().st_size / 1e6:.1f} MB)")

    print_report(docs, report)

    problems = validate(docs, report)
    print("\n" + "=" * 72)
    if problems:
        print(f"❌ 검증 위반 {len(problems)}건 (앞 20건)")
        for p in problems[:20]:
            print("  -", p)
        return 1
    print("✅ 검증 통과: 591/591 조인, 미사용 엑셀 행 0, 필수 메타 누락 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
