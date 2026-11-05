"""개인정보 자동 탐지: 텍스트 PDF 는 글자 데이터에서, 스캔 PDF 는 OS 내장 OCR 로.

결과는 후보일 뿐이며, 사용자가 확인한 뒤 마스킹 영역으로 추가한다.
좌표는 core.redact_pdf 와 같은 회전 전 페이지 좌표계다.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import pymupdf

from masker.core import Region
from masker.ocr import Line, OcrUnavailable, ocr_page

PATTERNS: dict[str, re.Pattern[str]] = {
    "주민번호": re.compile(r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)"),
    "전화번호": re.compile(r"(?<!\d)0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)"),
    "이메일": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "카드번호": re.compile(r"(?<!\d)(?:\d{4}[-\s]?){3}\d{4}(?!\d)"),
}

# OCR 이 흔히 틀리는 글자 보정 (숫자 문맥에서만 쓰임)
_OCR_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})


@dataclass(frozen=True)
class Detection:
    page: int
    kind: str
    text: str
    region: Region
    source: str  # "text" | "ocr"


@dataclass
class DetectReport:
    detections: list[Detection]
    ocr_pages: list[int]           # OCR 을 사용한 페이지
    skipped_pages: list[int]       # 스캔본인데 OCR 을 쓰지 못한 페이지
    ocr_error: str | None = None   # OCR 불가 사유


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def text_lines(page: pymupdf.Page) -> list[Line]:
    """텍스트 PDF 의 글자 데이터를 줄 단위 단어 목록으로."""
    grouped: dict[tuple[int, int], list] = {}
    for w in page.get_text("words"):  # x0,y0,x1,y1,text,block,line,word
        grouped.setdefault((w[5], w[6]), []).append(w)
    lines: list[Line] = []
    for key in sorted(grouped):
        ws = sorted(grouped[key], key=lambda w: w[7])
        lines.append([(w[0], w[1], w[2], w[3], w[4]) for w in ws])
    return lines


def is_scanned(page: pymupdf.Page) -> bool:
    """글자 데이터가 거의 없고 이미지가 있으면 스캔본으로 본다."""
    return len(page.get_text("words")) < 3 and bool(page.get_images())


def detect_lines(lines: list[Line], page_number: int, kinds: set[str], source: str,
                 pad: float = 1.5) -> list[Detection]:
    """줄 단위 단어 목록에서 패턴을 찾아 겹친 단어들의 bbox 합집합을 영역으로 삼는다."""
    out: list[Detection] = []
    for line in lines:
        text = ""
        spans: list[tuple[int, int, pymupdf.Rect]] = []
        for x0, y0, x1, y1, t in line:
            if text:
                text += " "
            start = len(text)
            text += t
            spans.append((start, len(text), pymupdf.Rect(x0, y0, x1, y1)))
        candidates = [text]
        if source == "ocr":
            candidates.append(text.translate(_OCR_DIGIT_FIX))
        seen: set[tuple[str, int, int]] = set()
        for variant in candidates:
            for kind in kinds:
                for m in PATTERNS[kind].finditer(variant):
                    key = (kind, *m.span())
                    if key in seen:
                        continue
                    seen.add(key)
                    rect = pymupdf.Rect()
                    for s, e, r in spans:
                        if _spans_overlap((s, e), m.span()):
                            rect |= r
                    if rect.is_empty:
                        continue
                    rect += (-pad, -pad, pad, pad)
                    out.append(Detection(page_number, kind, text[m.start():m.end()],
                                         (rect.x0, rect.y0, rect.x1, rect.y1), source))
    # 같은 자리를 두 패턴이 잡으면(카드번호 vs 전화번호 등) 하나만
    dedup: list[Detection] = []
    for d in sorted(out, key=lambda d: (d.region[1], d.region[0])):
        if any(pymupdf.Rect(d.region).intersects(pymupdf.Rect(e.region)) and e.text == d.text for e in dedup):
            continue
        dedup.append(d)
    return dedup


def detect_page(page: pymupdf.Page, kinds: set[str] | None = None,
                ocr: Callable[[pymupdf.Page], list[Line]] = ocr_page) -> tuple[list[Detection], str]:
    """한 페이지 탐지. (결과, 사용한 소스 'text'|'ocr'). OCR 불가 시 OcrUnavailable."""
    kinds = kinds or set(PATTERNS)
    if is_scanned(page):
        return detect_lines(ocr(page), page.number, kinds, "ocr"), "ocr"
    return detect_lines(text_lines(page), page.number, kinds, "text"), "text"


def detect_document(doc: pymupdf.Document, kinds: set[str] | None = None,
                    ocr: Callable[[pymupdf.Page], list[Line]] = ocr_page,
                    progress: Callable[[int, int], bool] | None = None) -> DetectReport:
    """문서 전체 탐지. progress(i, n) 가 False 를 돌려주면 중단."""
    report = DetectReport([], [], [])
    for i, page in enumerate(doc):
        if progress is not None and not progress(i, doc.page_count):
            break
        try:
            found, source = detect_page(page, kinds, ocr)
        except OcrUnavailable as exc:
            report.skipped_pages.append(i)
            report.ocr_error = report.ocr_error or str(exc)
            continue
        if source == "ocr":
            report.ocr_pages.append(i)
        report.detections.extend(found)
    return report
