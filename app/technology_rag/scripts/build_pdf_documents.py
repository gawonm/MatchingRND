"""
기술나눔 PDF 2종 → data/processed/technology/pdf_documents.jsonl

실행:
    .venv\\Scripts\\python.exe -X utf8 -m app.technology_rag.scripts.build_pdf_documents
    .venv\\Scripts\\python.exe -X utf8 -m app.technology_rag.scripts.build_pdf_documents --limit 5   # 소스별 5건만

출력 JSONL 한 줄 = TechDocument 1건 (엑셀 조인 전, PDF만으로 만든 상태).
마지막에 검증 요약을 출력한다. 위반이 있으면 종료코드 1.
"""

from __future__ import annotations

import argparse
import collections
import logging
import statistics
import sys
import time
from pathlib import Path

from app.technology_rag.paths import PROJECT_ROOT, RAW_DIR, PROCESSED_DIR
from app.common.schemas import SourceType
from app.technology_rag.schemas import TechDocument
from app.technology_rag import constants as C
from app.technology_rag.parsing.pdf_parser import iter_documents

ROOT = PROJECT_ROOT   # app.technology_rag.paths — TECHRAG_ROOT 로 바꿀 수 있다
RAW = RAW_DIR
OUT = PROCESSED_DIR / "pdf_documents.jsonl"

# 정제 후에도 남아 있으면 안 되는 문자
FORBIDDEN = {"\x01": "U+0001", "Ÿ": "불릿(Ÿ)", "": "불릿(U+F0D8)"}


def validate(docs: list[TechDocument]) -> list[str]:
    """전수 점검. 위반 사항 문자열 목록을 반환한다."""
    problems: list[str] = []

    ids = [d.doc_id for d in docs]
    dup = [k for k, v in collections.Counter(ids).items() if v > 1]
    if dup:
        problems.append(f"doc_id 중복 {len(dup)}건: {dup[:5]}")

    for src in SourceType:
        spec = C.SOURCE_SPECS.get(src)
        if not spec:
            continue
        n = sum(1 for d in docs if d.source == src)
        if n != spec["expected_records"]:
            problems.append(f"{src.value}: 레코드 {n}건 (기대 {spec['expected_records']})")

    apps = [d.patent.application_number for d in docs if d.patent.application_number]
    dup_app = [k for k, v in collections.Counter(apps).items() if v > 1]
    if dup_app:
        problems.append(f"출원번호 중복 {len(dup_app)}건: {dup_app[:5]}")

    for d in docs:
        tag = d.doc_id
        for w in d.extra.get("parse_warnings", []):
            problems.append(f"{tag} 경고: {w}")
        if not d.title:
            problems.append(f"{tag} 기술명 없음")
        if not d.patent.application_number:
            problems.append(f"{tag} 출원번호 없음")
        elif len(d.patent.application_number) != 13:
            problems.append(f"{tag} 출원번호 길이 {len(d.patent.application_number)}")
        for s in d.sections:
            for ch, name in FORBIDDEN.items():
                if ch in s.text:
                    problems.append(f"{tag}/{s.code.value} 잔존 문자 {name}")
            if not s.blocks:
                problems.append(f"{tag}/{s.code.value} blocks 없음")
    return problems


def summarize(docs: list[TechDocument]) -> None:
    print("\n" + "=" * 72)
    print(f"총 {len(docs)}건")
    for src in (SourceType.PUBLIC_TECH, SourceType.POSCO_TECH):
        sub = [d for d in docs if d.source == src]
        if not sub:
            continue
        print(f"\n[{src.value}] {len(sub)}건")
        print(f"  제공기관: {dict(collections.Counter(d.provider for d in sub))}")
        print(f"  대분류  : {dict(collections.Counter(d.taxonomy.major for d in sub))}")
        print(f"  만료일 파싱: {sum(1 for d in sub if d.patent.expiry_date)}/{len(sub)}"
              f"  등록번호: {sum(1 for d in sub if d.patent.registration_number)}/{len(sub)}"
              f"  부제: {sum(1 for d in sub if d.subtitle)}/{len(sub)}"
              f"  발명자: {sum(1 for d in sub if d.inventors)}/{len(sub)}")
        print(f"  {'section':<12}{'mean':>7}{'med':>6}{'max':>6}{'items(avg)':>12}")
        for code in C.SECTION_ORDER:
            lens = [len(d.section(code).text) for d in sub]
            blks = [len(d.section(code).blocks) for d in sub]
            print(f"  {code.value:<12}{statistics.mean(lens):>7.0f}{statistics.median(lens):>6.0f}"
                  f"{max(lens):>6}{statistics.mean(blks):>12.1f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="소스별 앞 N건만")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    docs: list[TechDocument] = []
    t0 = time.time()
    for src in (SourceType.PUBLIC_TECH, SourceType.POSCO_TECH):
        t = time.time()
        got = list(iter_documents(src, RAW, limit=args.limit))
        print(f"[{src.value}] {len(got)}건 파싱 ({time.time() - t:.1f}s)")
        docs.extend(got)

    with args.out.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(d.model_dump_json() + "\n")
    print(f"저장: {args.out}  ({args.out.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.0f}s)")

    summarize(docs)

    problems = validate(docs) if args.limit is None else [
        p for p in validate(docs) if "레코드" not in p
    ]
    print("\n" + "=" * 72)
    if problems:
        print(f"❌ 검증 위반 {len(problems)}건 (앞 30건)")
        for p in problems[:30]:
            print("  -", p)
        return 1
    print("✅ 검증 통과: doc_id/출원번호 유일, 경고 0, 빈 섹션 0, 금지문자 잔존 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
