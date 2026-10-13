"""Optional notice workbook links and source path identities."""
from collections import defaultdict
from pathlib import Path
from ..config import PROJECT_ROOT

def _source_key(path, data_dir):
    return path.resolve().relative_to(data_dir.resolve()).as_posix()

def _load_notices(data_dir, pdf_files, notice_path=None):
    """공고 연결은 선택적으로 읽으며 누락·중복은 검토 목록에 남깁니다."""
    notices, issues = {}, []
    links = {_source_key(path, data_dir): [] for path in pdf_files}
    by_name = defaultdict(list)
    for path in pdf_files:
        by_name[path.name].append(_source_key(path, data_dir))
    explicit = notice_path is not None
    if explicit:
        workbook = Path(notice_path)
    else:
        # PDF files live in rfp/pdf; the associated workbook lives in rfp/.
        candidates = [data_dir / 'RFP_공고목록.xlsx', data_dir.parent / 'RFP_공고목록.xlsx']
        workbook = next((path for path in candidates if path.is_file()), candidates[0])
    if explicit and not workbook.is_absolute():
        workbook = (PROJECT_ROOT / workbook).resolve()
    if not workbook.is_file():
        if explicit:
            raise FileNotFoundError(f'공고목록 파일이 없습니다: {workbook}')
        issues.append({'reason': '공고목록 없음: PDF 검색은 수행하지만 공고 URL은 제공하지 않음', 'source': str(workbook)})
    else:
        import pandas as pd

        try:
            notice_table = pd.read_excel(workbook, sheet_name='공고목록').fillna('')
            match_table = pd.read_excel(workbook, sheet_name='파일매칭').fillna('')
            for columns, table in [
                ({'공고 UID', '공고명', '원 공고기관 URL'}, notice_table),
                ({'공고 UID', '파일명'}, match_table),
            ]:
                if not columns.issubset(table.columns):
                    raise ValueError(f'공고목록 필수 열 누락: {sorted(columns - set(table.columns))}')
            for _, row in notice_table.iterrows():
                uid = str(row['공고 UID']).strip().removesuffix('.0')
                if not uid:
                    issues.append({'reason': '공고 UID 없음'})
                    continue
                entry = {'title': str(row['공고명']).strip(), 'url': str(row['원 공고기관 URL']).strip()}
                if uid in notices and notices[uid] != entry:
                    issues.append({'reason': '같은 공고 UID의 내용이 다름', 'notice_id': uid})
                    continue
                notices[uid] = entry
            for _, row in match_table.iterrows():
                uid = str(row['공고 UID']).strip().removesuffix('.0')
                filename = str(row['파일명']).strip().replace('\\', '/')
                keys = ([filename] if filename in links else []) if '/' in filename else by_name.get(filename, [])
                if len(keys) != 1:
                    issues.append({'reason': 'PDF 연결 없음 또는 같은 파일명 중복', 'filename': filename, 'notice_id': uid})
                    continue
                if uid not in notices:
                    issues.append({'reason': '공고 ID 없음', 'filename': filename, 'notice_id': uid})
                    continue
                if uid not in links[keys[0]]:
                    links[keys[0]].append(uid)
        except Exception as error:
            # PDF 원문 근거는 사용할 수 있으므로 공고 연결 실패만 별도 보고합니다.
            notices = {}
            links = {_source_key(path, data_dir): [] for path in pdf_files}
            issues.append({'reason': '공고목록 읽기 실패', 'source': str(workbook), 'detail': str(error)})
    for source, ids in links.items():
        if not ids:
            issues.append({'reason': 'PDF 공고 연결 없음', 'source': source})
    return notices, links, issues
