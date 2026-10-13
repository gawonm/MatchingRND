"""Evidence-backed cascade query construction."""
import re

def build_query(owned_technologies, technical_problem, *, external_elements=None,
                ntis_elements=None, unmet_elements=None, return_details=False):
    """최초 기술문제를 유지하고 출처가 제공된 기술요소로 쿼리를 확장합니다.

    기본 반환값은 검색 문자열입니다. return_details=True이면 Baseline,
    Cascade 및 확장 원문·출처를 함께 반환하며 search에 그대로 전달할 수 있습니다.
    이 함수는 원문 진위나 기술 충족 여부를 판정하지 않습니다.
    """
    def text(value, name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{name}는 비어 있지 않은 문자열이어야 합니다.')
        return value.strip()

    def unique_names(values, name):
        if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
            raise ValueError(f'{name}는 문자열의 목록이어야 합니다.')
        unique, seen = [], set()
        for value in values:
            value = text(value, name)
            key = re.sub(r'\s+', '', value).casefold()
            if key not in seen:
                seen.add(key)
                unique.append(value)
        return unique

    owned = unique_names(owned_technologies, '보유기술')
    problem = text(technical_problem, '최초 기술문제')
    unmet = unique_names(unmet_elements or [], '미충족 검토 요소')
    baseline = '보유기술: ' + ' / '.join(owned) + '\n기술문제: ' + problem
    parts, provenance, seen_sources = [baseline], [], set()
    seen_terms = {re.sub(r'\s+', '', value).casefold() for value in owned}
    for kind, elements in [('external_technology', external_elements or []), ('ntis', ntis_elements or [])]:
        if not isinstance(elements, (list, tuple)):
            raise ValueError('확장 요소는 기술명·원문·출처 ID를 담은 dict의 목록이어야 합니다.')
        for element in elements:
            if not isinstance(element, dict):
                raise ValueError('각 확장 요소는 dict여야 합니다.')
            technology = text(element.get('technology'), '확장 기술명')
            quote = text(element.get('quote'), '확장 근거 원문')
            source_id = text(element.get('source_id'), '확장 출처 ID')
            identity = (kind, source_id, technology, quote)
            if identity not in seen_sources:
                seen_sources.add(identity)
                provenance.append({
                    'kind': kind, 'technology': technology,
                    'quote': quote, 'source_id': source_id,
                })
            term_key = re.sub(r'\s+', '', technology).casefold()
            if term_key not in seen_terms:
                seen_terms.add(term_key)
                label = '외부기술 요소' if kind == 'external_technology' else 'NTIS 기술요소'
                parts.append(f'{label}: {technology}')
    parts.extend('미충족 검토 요소 (기업 입력): ' + element for element in unmet)
    query = '\n'.join(parts)
    if not return_details:
        return query
    return {
        'query': query, 'baseline_query': baseline,
        'owned_technologies': owned, 'technical_problem': problem,
        'expansion_sources': provenance, 'unmet_elements': unmet,
    }
