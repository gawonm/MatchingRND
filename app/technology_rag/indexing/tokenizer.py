"""
BM25용 한국어 토크나이저 (Kiwi).

기본 규칙
---------
- 명사(NNG, NNP, NR), 어근(XR), 한자(SH), 영문(SL), 숫자(SN), 용언 어간(VV, VA)만 남긴다.
  조사·어미·접미사·기호는 버린다.
- 2글자 미만 토큰은 버린다(`단`, `차`, `재` 같은 접미 성분 노이즈). 숫자는 2자리 이상만.
- 영문은 소문자로 맞춘다 (`LiDAR` == `lidar`).
- 의미 없는 용언(`통하`, `위하`, `대하` ...)은 불용어로 버린다.

사용자 사전 (user_words)
------------------------
Kiwi는 도메인 미등록어를 문맥에 따라 잘못 쪼갠다. 실측 예:
    '조가선을 케이스에'      → 조가선/NNG            (정상)
    '조가선이 장착되는'      → 조/NNP 선/NNG 이 ...  (오분석: 문서 쪽 토큰이 사라진다)
    '조가선 위치를 조정'     → 조/NNG 가/JKS 서/VV   (오분석: 쿼리 쪽 토큰이 사라진다)
사전에 등록하면 문서와 쿼리가 모두 고쳐진다. 어떤 단어가 누락되는지는 `coverage()` 로 점검한다.
사전 파일 형식은 app/technology_rag/configs/user_dict.txt 참고.

char_bigrams (옵션, 기본 꺼짐)
------------------------------
3글자 이상 한글 명사에 글자 bigram(`~조가`, `~가선`)을 별도 네임스페이스로 추가해
부분 문자열 매칭을 가능하게 한다. 노이즈도 늘므로 실험으로 켜고 끈 결과를 비교한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence

from app.technology_rag.paths import DEFAULT_USER_DICT_PATH

_NOUN = {"NNG", "NNP", "NR", "XR", "SH"}
_VERB = {"VV", "VA"}

_STOP_VERBS = frozenset({"통하", "위하", "대하", "의하", "관하", "따르", "이루", "가지", "갖", "나타나"})

_HANGUL = re.compile(r"^[가-힣]+$")

#: (단어, 품사, 점수). 점수가 클수록 이 분석을 선호한다.
UserWord = tuple[str, str, float]

#: 모듈 안(app/technology_rag/configs/)에 있다. 모듈 폴더를 옮겨도 사전이 따라간다.
DEFAULT_USER_DICT = DEFAULT_USER_DICT_PATH

_kiwi_cache: dict[tuple[UserWord, ...], object] = {}


def _get_kiwi(user_words: tuple[UserWord, ...] = ()):
    """Kiwi 객체는 초기화가 무겁고(~1초) pickle 이 안 되므로 사전 조합별로 한 번만 만든다."""
    kiwi = _kiwi_cache.get(user_words)
    if kiwi is None:
        from kiwipiepy import Kiwi

        kiwi = Kiwi()
        for word, tag, score in user_words:
            kiwi.add_user_word(word, tag, score)
        _kiwi_cache[user_words] = kiwi
    return kiwi


def load_user_dict(path: Path | str = DEFAULT_USER_DICT) -> tuple[UserWord, ...]:
    """`단어[<TAB>품사[<TAB>점수]]` 형식의 사전 파일을 읽는다. '#' 이후는 주석. 없으면 빈 사전."""
    p = Path(path)
    if not p.exists():
        return ()
    out: list[UserWord] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        word = parts[0].strip()
        tag = parts[1].strip() if len(parts) > 1 else "NNG"
        score = float(parts[2]) if len(parts) > 2 else 3.0
        out.append((word, tag, score))
    return tuple(out)


class KiwiTokenizer:
    def __init__(
        self,
        *,
        min_len: int = 2,
        keep_verbs: bool = True,
        char_bigrams: bool = False,
        user_words: Sequence[Sequence] = (),
    ) -> None:
        self.min_len = min_len
        self.keep_verbs = keep_verbs
        self.char_bigrams = char_bigrams
        self.user_words: tuple[UserWord, ...] = tuple(
            (str(w), str(t), float(s)) for w, t, s in user_words
        )

    def config(self) -> dict:
        """인덱스와 함께 저장해 재현성을 확보한다."""
        return {
            "name": "kiwi",
            "min_len": self.min_len,
            "keep_verbs": self.keep_verbs,
            "char_bigrams": self.char_bigrams,
            "user_words": [list(u) for u in self.user_words],
        }

    @property
    def _kiwi(self):
        return _get_kiwi(self.user_words)

    # ------------------------------------------------------------------
    def _from_tokens(self, tokens) -> list[str]:
        out: list[str] = []
        for t in tokens:
            form, tag = t.form, t.tag
            if tag in _NOUN:
                if len(form) < self.min_len:
                    continue
                out.append(form)
                if self.char_bigrams and len(form) >= 3 and _HANGUL.match(form):
                    out.extend(f"~{form[i:i + 2]}" for i in range(len(form) - 1))
            elif tag == "SL":
                f = form.lower()
                if len(f) >= self.min_len:
                    out.append(f)
            elif tag == "SN":
                if len(form) >= 2:
                    out.append(form)
            elif self.keep_verbs and tag in _VERB:
                if len(form) >= self.min_len and form not in _STOP_VERBS:
                    out.append(form)
        return out

    def __call__(self, text: str) -> list[str]:
        return self._from_tokens(self._kiwi.tokenize(text))

    def tokenize_many(self, texts: Iterable[str]) -> list[list[str]]:
        """말뭉치 전체를 한 번에. Kiwi 내부 멀티스레드를 쓴다."""
        return [self._from_tokens(toks) for toks in self._kiwi.tokenize(list(texts))]

    # ------------------------------------------------------------------
    def coverage(self, words: Iterable[str], texts: Iterable[str]) -> list[tuple[str, int, int]]:
        """단어가 말뭉치에서 토큰으로 얼마나 잡히는지 점검한다.

        반환: [(단어, 원문 등장 횟수, 토큰으로 잡힌 횟수)]
        두 숫자가 다르면 Kiwi가 그 단어를 문맥에서 놓치고 있다 → user_dict 후보.
        """
        texts = list(texts)
        words = list(words)
        raw = {w: sum(t.count(w) for t in texts) for w in words}
        hit = dict.fromkeys(words, 0)
        for toks in self._kiwi.tokenize(texts):
            for t in toks:
                if t.form in hit:
                    hit[t.form] += 1
        return [(w, raw[w], hit[w]) for w in words]


def default_tokenizer(**kwargs) -> KiwiTokenizer:
    """app/technology_rag/configs/user_dict.txt 를 적용한 기본 토크나이저."""
    kwargs.setdefault("user_words", load_user_dict())
    return KiwiTokenizer(**kwargs)
