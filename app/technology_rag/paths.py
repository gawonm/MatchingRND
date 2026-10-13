"""
Technology RAG(A) 의 경로 해석 — 두 종류를 한 곳에서 계산한다.

1. 모듈 **안**의 자원 (설정 파일, 사용자 사전): 이 파일 기준 상대 위치.
   모듈 폴더를 통째로 다른 저장소로 옮겨도 자원이 따라간다.
2. 프로젝트 **루트** 기준 자원 (data/, storage/, .env): 루트를 아래 우선순위로 찾는다.
       1) 환경변수 `TECHRAG_ROOT`   ← 다른 저장소에 통합할 때 이것만 설정하면 된다
       2) 이 파일에서 위로 올라가며 marker 파일(requirements.txt, pyproject.toml) 탐색
       3) 현재 작업 디렉터리
   `parents[N]` 을 세는 방식은 디렉터리 구조가 바뀌면 조용히 깨지므로 쓰지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- 모듈 안의 자원
#: app/technology_rag/
PACKAGE_DIR = Path(__file__).resolve().parent

#: 모듈과 함께 다니는 설정·사전
CONFIG_DIR = PACKAGE_DIR / "configs"

DEFAULT_CONFIG_PATH = CONFIG_DIR / "technology_rag.yaml"
DEFAULT_USER_DICT_PATH = CONFIG_DIR / "user_dict.txt"

# ---------------------------------------------------------------- 프로젝트 루트 기준
#: 프로젝트 루트임을 알려주는 파일들 ('.git' 은 쓰지 않는다 — 상위 디렉터리가 git 저장소일 수 있다)
_MARKERS = ("requirements.txt", "pyproject.toml")

ENV_VAR = "TECHRAG_ROOT"


def find_project_root(start: Path | None = None) -> Path:
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if any((candidate / m).exists() for m in _MARKERS):
            return candidate
    return Path.cwd().resolve()


PROJECT_ROOT = find_project_root()

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


def resolve(path: str | Path) -> Path:
    """설정 파일에 적힌 상대경로를 프로젝트 루트 기준 절대경로로 바꾼다."""
    p = Path(path)
    return p if p.is_absolute() else (PROJECT_ROOT / p)
