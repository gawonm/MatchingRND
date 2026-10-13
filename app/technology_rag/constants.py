"""
기술나눔 기술소개자료 PDF의 레이아웃 상수.

[핵심 발견]
두 PDF 모두 섹션 제목("기술 개요" 등)이 텍스트가 아니라 **이미지**로 렌더링되어
있어 get_text()로는 추출되지 않는다. 그러나 같은 제목 이미지가 전 문서에서
동일한 바이너리로 재사용되므로, 이미지 md5 digest로 섹션을 100% 식별할 수 있다.
(OCR 불필요)

[실측 검증 결과]
  공공기관 PDF: 604p, 298 레코드, 전 레코드 정확히 2페이지, 6개 배너 각 298회
  포스코   PDF: 592p, 293 레코드, 전 레코드 정확히 2페이지, 6개 배너 각 293회
  출원번호 추출 298/298, 293/293 → 엑셀 조인률 100%
"""

from __future__ import annotations

from app.common.schemas import SourceType
from app.technology_rag.schemas import SectionCode

# =============================================================================
# 섹션 제목 배너 이미지 digest → 섹션 코드
# digest = md5(doc.extract_image(xref)["image"]).hexdigest()[:10]
# =============================================================================

SECTION_BANNERS: dict[str, SectionCode] = {
    # --- 공공기관 (4._2026년_공공기관_기술나눔_기술소개자료.pdf) ---
    "8ebe2decdf": SectionCode.OVERVIEW,      # 기술 개요
    "472668700f": SectionCode.PROBLEM,       # 산업계 문제 해결 포인트
    "25e25fa5db": SectionCode.STRENGTH,      # 기술의 강점 및 차별성
    "f95b926a62": SectionCode.APPLICATION,   # 주요 적용 산업 및 활용처
    "dc633fb7e4": SectionCode.COMPOSITION,   # 기술의 구성 및 특징
    "0b01b31fec": SectionCode.MARKET,        # 시장성 및 사업화 가능성
    # --- 포스코 (2025년_포스코그룹_기술나눔_기술소개자료.pdf) ---
    "e386170507": SectionCode.OVERVIEW,
    "27cd14e007": SectionCode.PROBLEM,
    "4627c7dde0": SectionCode.STRENGTH,
    "71080db873": SectionCode.APPLICATION,
    "e1c5fe6314": SectionCode.COMPOSITION,
    "68252ac168": SectionCode.MARKET,
}

SECTION_TITLES: dict[SectionCode, str] = {
    SectionCode.OVERVIEW: "기술 개요",
    SectionCode.PROBLEM: "산업계 문제 해결 포인트",
    SectionCode.STRENGTH: "기술의 강점 및 차별성",
    SectionCode.APPLICATION: "주요 적용 산업 및 활용처",
    SectionCode.COMPOSITION: "기술의 구성 및 특징",
    SectionCode.MARKET: "시장성 및 사업화 가능성",
    SectionCode.META: "표지/서지정보",
}

# 레코드 안에서의 섹션 등장 순서 (페이지1: 1~4, 페이지2: 5~6)
SECTION_ORDER: list[SectionCode] = [
    SectionCode.OVERVIEW,
    SectionCode.PROBLEM,
    SectionCode.STRENGTH,
    SectionCode.APPLICATION,
    SectionCode.COMPOSITION,
    SectionCode.MARKET,
]

# 배너 이미지 판별 조건 (digest 미등록분 탐지용 가드)
BANNER_MIN_WIDTH = 480.0
BANNER_MAX_HEIGHT = 25.0

# =============================================================================
# 페이지 레이아웃
# =============================================================================

CONTENT_START_PAGE = 4      # 0~3 = 표지/목차/대분류 간지. 본문은 4페이지부터
FOOTER_Y_THRESHOLD = 805.0  # 이보다 아래 블록은 '- 1 -' 페이지번호 → 제외
HEADER_Y_THRESHOLD = 80.0   # 러닝헤더 '2026년 한국산업기술진흥원-OOO 기술나눔'
TITLE_Y_THRESHOLD = 140.0   # 일련번호 + 기술명 블록

# 대분류 간지 페이지는 일련번호가 없어 자동으로 건너뛴다
#   공공기관: 336, 337, 526, 527
#   포스코  : 472, 473

# 표지 영역 고정 좌표 (x 기준으로 분류 필드 식별)
TAXONOMY_X_MIN = 470.0      # 대/중/소분류는 우측 열(x≈481)에 y 순서로 배치
TAXONOMY_WRAP_DY = 18.0     # 항목 간격 ~26pt, 줄바꿈된 항목의 둘째 줄 ~13pt

# =============================================================================
# 소스 정의
# =============================================================================

SOURCE_SPECS = {
    SourceType.PUBLIC_TECH: {
        "pdf": "4._2026년_공공기관_기술나눔_기술소개자료.pdf",
        "excel": "2. 2026년 공공기관 기술나눔 목록(298건).xlsx",
        "excel_sheet": "기술나눔 목록(298건)",
        "year": 2026,
        "expected_records": 298,
        "join_key_excel": "출원번호",
    },
    SourceType.POSCO_TECH: {
        "pdf": "2025년_포스코그룹_기술나눔_기술소개자료.pdf",
        "excel": "나눔기술.xls",
        "excel_sheet": 0,
        "year": 2025,
        "expected_records": 293,
        "join_key_excel": "출원번호",
    },
}

# 러닝헤더에서 제공기관 추출: "2026년 한국산업기술진흥원-한국철도공사 기술나눔"
PROVIDER_PATTERN = r"기술진흥원\s*-\s*(.+?)\s*기술나눔"

# 표지 출원/등록번호. 출원번호 '10-2008-0054298' 안에서 '08-0054298' 이
# 등록번호 패턴으로 오탐되지 않도록 앞뒤를 lookaround 로 막는다.
APPLICATION_NO_PATTERN = r"(?<![\d-])(\d{2}-\d{4}-\d{7})(?!\d)"
REGISTRATION_NO_PATTERN = r"(?<![\d-])(\d{2}-\d{7})(?![\d-])"
PAREN_DATE_PATTERN = r"\(\s*(\d{4}-\d{2}-\d{2})\s*\)"

# =============================================================================
# 섹션 본문 재구성 규칙 (라인 좌표 실측 기반)
# =============================================================================
# 텍스트 정제 자체(U+0001, 불릿, 캡션)는 app/technology_rag/text.py 에 있다.

# 2단 조판: 라인 x0 >= 이 값이면 우측 열. 열 → y → x 순으로 읽는다.
COLUMN_SPLIT_X = 300.0

# 불릿 라인과 본문 첫 줄은 별개 라인이고 y가 최대 ~1pt 어긋난다.
BULLET_Y_TOL = 4.0

# 같은 항목의 이어진 줄: 첫 줄과 x0가 이 값 이내, 직전 줄과 y간격이 이 값 이내
CONT_X_TOL = 3.0
CONT_MAX_DY = 22.0

# 표 섹션(strength: 구분|내용, composition: 구성|내용)
#   행 = [라벨(가운데정렬)] [불릿] [내용(여러 줄)]
#   라벨은 불릿 왼쪽, 내용은 불릿 오른쪽. 라벨의 y는 행 중앙이라 불릿보다 최대 ~13pt 아래.
TABLE_HEADER_LEFT = ("구분", "구성")
TABLE_HEADER_RIGHT = "내용"
TABLE_HEADER_DY_TOL = 3.0
TABLE_LABEL_Y_TOL = 3.0     # 라벨 y0 + tol >= 불릿 y0 이면 그 행 소속
TABLE_ROW_END_TOL = 6.0     # 행 마지막 내용줄보다 이만큼 아래의 라벨은 행 소속 아님
