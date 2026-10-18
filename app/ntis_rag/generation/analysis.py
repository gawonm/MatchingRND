"""질의 구조화 → 과제별 기술요소 추출 → canonical 기술 → prior_rd_axes."""
import json
import os
import re
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Sequence

from langchain_openai import ChatOpenAI

from ..config import LLM_MODEL

llm = ChatOpenAI(
    model=LLM_MODEL,
    timeout=float(os.getenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "60")),
    max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "0")),
) if os.getenv("OPENAI_API_KEY") else None
_calls = ContextVar('ntis_analysis_llm_calls', default=None)


@contextmanager
def track_llm_calls():
    counts = dict(query_structuring=0, technology_extraction=0, canonicalization=0, axis_aggregation=0)
    token = _calls.set(counts)
    try:
        yield counts
    finally:
        _calls.reset(token)


def _invoke(stage, prompt):
    counts = _calls.get()
    if counts is not None:
        counts[stage] += 1
    return llm.invoke(prompt)


def parse_json_object(content: Any) -> Dict[str, Any]:
    if not isinstance(content, str):
        raise TypeError("LLM 응답 content가 문자열이 아닙니다.")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I | re.S)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise TypeError("LLM 응답은 JSON 객체여야 합니다.")
    return parsed


# ==================================================
# Query Structuring
# ==================================================
def structure_query(
    problem: str,
    owned_technologies: Optional[Sequence[str]] = None,
    external_technologies: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    problem = problem.strip()
    if not problem:
        raise ValueError("problem은 비어 있을 수 없습니다.")

    owned = [str(item).strip() for item in (owned_technologies or []) if str(item).strip()]
    external = [str(item).strip() for item in (external_technologies or []) if str(item).strip()]
    fallback = {
        "core_problem": problem,
        "key_technologies": list(dict.fromkeys([*owned, *external])),
        "search_query": " ".join([problem, *owned, *external]).strip(),
    }
    if llm is None:
        return fallback

    prompt = f"""
당신은 국가 R&D 과제 검색용 질의 구조화기다. 원래 기술문제를 보존하고,
보유기술과 외부기술은 검색 문맥으로만 사용하라. 입력에 없는 사실을 만들지 마라.

기술문제: {problem}
보유기술: {owned}
외부기술: {external}

다음 JSON 객체만 반환하라:
{{
  "core_problem": "한 문장 핵심 문제",
  "key_technologies": ["검색 핵심 기술"],
  "search_query": "NTIS 검색용 자연어 질의"
}}
"""
    try:
        result = parse_json_object(_invoke('query_structuring', prompt).content)
        for field in ("core_problem", "key_technologies", "search_query"):
            if field not in result:
                raise ValueError(f"구조화 질의 필드 누락: {field}")
        return result
    except Exception as exc:
        print(f"Query structuring fallback 사용: {exc}")
        return fallback


# ==================================================
# 과제별 기술요소 추출 — 실패 시 1회 retry
# ==================================================
def validate_project_analysis(parsed: Dict[str, Any], project_text: str) -> Dict[str, Any]:
    research_topic = parsed.get("research_topic")
    elements = parsed.get("technology_elements")
    if not isinstance(elements, list):
        raise TypeError("technology_elements는 list여야 합니다.")

    verified = []
    for item in elements:
        if not isinstance(item, dict):
            raise TypeError("technology element는 객체여야 합니다.")
        element = str(item.get("element", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if not element or not evidence:
            raise ValueError("기술요소와 evidence는 비어 있을 수 없습니다.")
        if evidence not in project_text:
            raise ValueError(f"원문에서 evidence를 찾지 못했습니다: {evidence[:80]}")
        verified.append({"element": element, "evidence": evidence})

    return {"research_topic": research_topic, "technology_elements": verified}


def extract_project_tech(project: Dict[str, Any], max_retries: int = 1) -> Dict[str, Any]:
    base = {
        "project_id": project["project_id"],
        "project_title": project.get("project_title"),
        "research_topic": None,
        "technology_elements": [],
        "error": None,
    }
    if llm is None:
        return {**base, "error": "OPENAI_API_KEY가 없어 기술요소 추출을 건너뜀"}

    prompt = f"""
다음 NTIS 과제 원문에서 연구주제와 구체 기술요소를 추출하라.
evidence는 반드시 원문에 연속된 형태로 존재하는 짧은 구절을 그대로 사용하라.
원문에 없는 기술을 추론하거나 보완하지 마라.

[과제 원문]
{project['text']}

다음 JSON 객체만 반환하라:
{{
  "research_topic": "연구주제",
  "technology_elements": [
    {{"element": "구체 기술요소", "evidence": "원문 근거 구절"}}
  ]
}}
"""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            parsed = parse_json_object(_invoke('technology_extraction', prompt).content)
            validated = validate_project_analysis(parsed, project["text"])
            return {**base, **validated}
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries:
                print(f"기술요소 추출 재시도 ({project['project_id']}): {last_error}")

    print(f"기술요소 추출 최종 실패 ({project['project_id']}): {last_error}")
    return {**base, "error": last_error}


def extract_all_project_tech(related_projects: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    import sys
    from .batched_extraction import extract_projects
    retries = int(os.getenv("NTIS_EXTRACTION_MAX_RETRIES", "0"))
    if retries < 0:
        raise ValueError("NTIS_EXTRACTION_MAX_RETRIES는 0 이상이어야 합니다.")
    return extract_projects(related_projects, sys.modules[__name__],
        batch_size=int(os.getenv('NTIS_EXTRACTION_BATCH_SIZE', '1')),
        max_chars=int(os.getenv('NTIS_EXTRACTION_MAX_CHARS', '24000')), max_retries=retries)


# ==================================================
# Concrete canonical technologies
# ==================================================
def flatten_technology_elements(project_analyses: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for project in project_analyses:
        for item in project.get("technology_elements", []):
            rows.append({
                "project_id": project["project_id"],
                "project_title": project.get("project_title"),
                "original_element": item["element"],
                "evidence": item["evidence"],
            })
    return rows


def canonicalize_technologies(project_analyses: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = flatten_technology_elements(project_analyses)
    if not rows:
        return []
    if llm is None:
        return [{**row, "canonical_name": row["original_element"]} for row in rows]

    indexed = [
        {"item_id": index, "technology": row["original_element"]}
        for index, row in enumerate(rows)
    ]
    prompt = f"""
다음 선행 R&D 기술표현을 구체성을 유지하면서 의미가 같은 표현끼리 정규화하라.
모든 item_id를 정확히 한 번 포함하고 입력에 없는 기술을 추가하지 마라.
여기서는 상위 기술축을 만들거나 Coverage를 판정하지 마라.

입력:
{json.dumps(indexed, ensure_ascii=False, indent=2)}

다음 JSON 객체만 반환하라:
{{
  "items": [
    {{"item_id": 0, "canonical_name": "구체적인 정규화 기술명"}}
  ]
}}
"""
    parsed = parse_json_object(_invoke('canonicalization', prompt).content)
    items = parsed.get("items")
    if not isinstance(items, list):
        raise TypeError("canonicalization items는 list여야 합니다.")

    assignments = {}
    for item in items:
        item_id = int(item["item_id"])
        canonical_name = str(item.get("canonical_name", "")).strip()
        if not canonical_name or item_id in assignments:
            raise ValueError("canonicalization 결과에 빈 이름 또는 중복 item_id가 있습니다.")
        assignments[item_id] = canonical_name

    expected_ids = set(range(len(rows)))
    if set(assignments) != expected_ids:
        raise ValueError("canonicalization 결과가 입력 item_id 전체와 일치하지 않습니다.")

    return [
        {**row, "canonical_name": assignments[index]}
        for index, row in enumerate(rows)
    ]


# ==================================================
# Prior R&D axis aggregation
# ==================================================
def canonical_source_map(canonical_rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    source_map = defaultdict(list)
    seen = set()
    for row in canonical_rows:
        source = {
            "project_id": row["project_id"],
            "project_title": row.get("project_title"),
            "original_element": row["original_element"],
            "evidence": row["evidence"],
        }
        signature = (row["canonical_name"], *source.values())
        if signature not in seen:
            seen.add(signature)
            source_map[row["canonical_name"]].append(source)
    return dict(source_map)


def aggregate_prior_rd_axes(canonical_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not canonical_rows:
        return []

    source_map = canonical_source_map(canonical_rows)
    canonical_names = list(source_map)
    if llm is None:
        groups = [{"axis": "미분류 기술축", "technologies": canonical_names}]
    else:
        indexed = [
            {"technology_id": index, "canonical_name": name}
            for index, name in enumerate(canonical_names)
        ]
        prompt = f"""
다음 구체 기술들을 기능적으로 묶어 상위 선행 R&D 연구축을 생성하라.
축은 문제 해결 접근을 나타내는 명사형 한국어로 작성하라.
모든 technology_id를 정확히 한 번 포함하고 입력에 없는 기술을 추가하지 마라.
구체 기술명을 다시 쓰거나 Coverage를 판정하지 마라.

입력:
{json.dumps(indexed, ensure_ascii=False, indent=2)}

다음 JSON 객체만 반환하라:
{{
  "groups": [
    {{"axis": "상위 연구 접근축", "technology_ids": [0, 1]}}
  ]
}}
"""
        parsed = parse_json_object(_invoke('axis_aggregation', prompt).content)
        raw_groups = parsed.get("groups")
        if not isinstance(raw_groups, list):
            raise TypeError("prior axis groups는 list여야 합니다.")

        assigned_ids = set()
        groups = []

        for group in raw_groups:
            if not isinstance(group, dict):
                continue

            axis = str(group.get("axis") or "").strip()
            if not axis:
                continue

            valid_ids = []

            for item in group.get("technology_ids", []):
                try:
                    tech_id = int(item)
                except (TypeError, ValueError):
                    continue

                # 존재하지 않는 ID 제외
                if not 0 <= tech_id < len(canonical_names):
                    continue

                # 중복 배정 제외
                if tech_id in assigned_ids:
                    continue

                assigned_ids.add(tech_id)
                valid_ids.append(tech_id)

            if valid_ids:
                groups.append({
                    "axis": axis,
                    "technologies": [canonical_names[i] for i in valid_ids],
                })

        # LLM이 누락한 기술을 별도 기술축으로 보존
        missing_ids = set(range(len(canonical_names))) - assigned_ids

        if missing_ids:
            groups.append({
                "axis": "미분류 기술축",
                "technologies": [canonical_names[i] for i in sorted(missing_ids)],
            })

    result = []
    for group in groups:
        technologies = [
            {"canonical_name": name, "sources": source_map[name]}
            for name in group["technologies"]
        ]
        result.append({"axis": group["axis"], "technologies": technologies})

    result.sort(
        key=lambda group: (
            -sum(len(technology["sources"]) for technology in group["technologies"]),
            group["axis"],
        )
    )
    return result
