"""개인정보 자동 탐지: 페이지 텍스트에서 패턴을 찾아 후보 영역을 돌려준다.

결과는 후보일 뿐이며, 사용자가 확인한 뒤 마스킹 영역으로 추가한다.
좌표는 core.redact_pdf 와 같은 회전 전 페이지 좌표계다.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import pymupdf

from masker.core import Region

PATTERNS: dict[str, re.Pattern[str]] = {
    "주민번호": re.compile(r"\b\d{6}[-\s]?[1-8]\d{6}\b"),
    "전화번호": re.compile(r"\b0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}\b"),
    "이메일": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "카드번호": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
}


@dataclass(frozen=True)
class Detection:
    page: int
    kind: str
    text: str
    region: Region


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def detect_page(page: pymupdf.Page, kinds: set[str] | None = None, pad: float = 1.5) -> list[Detection]:
    """한 페이지에서 패턴에 맞는 텍스트의 bbox 를 찾는다.

    단어 단위 bbox 를 이어 붙여 줄 텍스트를 만들고, 매치된 문자 구간에 걸친
    단어들의 bbox 합집합을 영역으로 삼는다. 같은 줄에서 여러 단어에 걸친
    번호(예: '010 1234 5678')도 잡힌다.
    """
    kinds = kinds or set(PATTERNS)
    words = page.get_text("words")  # x0,y0,x1,y1,text,block,line,word
    lines: dict[tuple[int, int], list] = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)

    out: list[Detection] = []
    for line_words in lines.values():
        line_words.sort(key=lambda w: w[7])
        text = ""
        spans: list[tuple[int, int, pymupdf.Rect]] = []
        for w in line_words:
            if text:
                text += " "
            start = len(text)
            text += w[4]
            spans.append((start, len(text), pymupdf.Rect(w[:4])))

        for kind in kinds:
            for m in PATTERNS[kind].finditer(text):
                rect = pymupdf.Rect()
                for s, e, r in spans:
                    if _spans_overlap((s, e), m.span()):
                        rect |= r
                if rect.is_empty:
                    continue
                rect += (-pad, -pad, pad, pad)
                out.append(Detection(page.number, kind, m.group(), (rect.x0, rect.y0, rect.x1, rect.y1)))

    # 같은 영역이 두 패턴에 걸리면(카드번호 vs 전화번호 등) 하나만 남긴다
    dedup: list[Detection] = []
    for d in sorted(out, key=lambda d: (d.region[1], d.region[0])):
        if any(pymupdf.Rect(d.region).intersects(pymupdf.Rect(e.region)) and e.text == d.text for e in dedup):
            continue
        dedup.append(d)
    return dedup


def detect_document(doc: pymupdf.Document, kinds: set[str] | None = None) -> list[Detection]:
    out: list[Detection] = []
    for page in doc:
        out.extend(detect_page(page, kinds))
    return out
