import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import pymupdf

from masker.core import redact_pdf
from masker.detect import detect_document, detect_lines, detect_page, is_scanned
from masker.ocr import OcrUnavailable, PixelWord, pixel_words_to_lines, render_for_ocr


def _text_doc():
    doc = pymupdf.open()
    p = doc.new_page(width=400, height=300)
    p.insert_text((20, 40), "Name: Hong Gildong", fontsize=12)
    p.insert_text((20, 70), "SSN: 900101-1234567", fontsize=12)
    p.insert_text((20, 100), "Tel: 010 1234 5678", fontsize=12)
    p.insert_text((20, 130), "Mail: hong@example.com", fontsize=12)
    p.insert_text((20, 160), "Order 2024-11-04 qty 12", fontsize=12)
    return doc


def _scan_doc(rotation: int = 0):
    """텍스트 페이지를 이미지로 구워 넣은 '스캔본'. 글자 데이터가 없다."""
    src = _text_doc()
    pix = src[0].get_pixmap(dpi=150, alpha=False)
    doc = pymupdf.open()
    p = doc.new_page(width=400, height=300)
    p.insert_image(p.rect, pixmap=pix)
    p.set_rotation(rotation)
    return doc


# ---------- 텍스트 PDF ----------

def test_detects_each_kind():
    doc = _text_doc()
    found, source = detect_page(doc[0])
    assert source == "text"
    kinds = {(d.kind, d.text) for d in found}
    assert ("주민번호", "900101-1234567") in kinds
    assert ("전화번호", "010 1234 5678") in kinds
    assert ("이메일", "hong@example.com") in kinds
    assert not any("2024" in t for _, t in kinds)
    assert not any(k == "카드번호" for k, _ in kinds)


def test_kind_filter():
    found, _ = detect_page(_text_doc()[0], kinds={"이메일"})
    assert [d.kind for d in found] == ["이메일"]


def test_region_covers_text_and_redacts(tmp_path):
    doc = _text_doc()
    src = tmp_path / "in.pdf"
    doc.save(src)
    report = detect_document(doc)
    regions = {}
    for d in report.detections:
        regions.setdefault(d.page, []).append(d.region)
    redact_pdf(src, tmp_path / "out.pdf", regions)
    with pymupdf.open(tmp_path / "out.pdf") as o:
        text = o[0].get_text()
        assert "1234567" not in text and "5678" not in text and "example.com" not in text
        assert "Hong Gildong" in text and "qty 12" in text
    assert report.ocr_pages == [] and report.skipped_pages == []


def test_multiword_phone_region_spans_words():
    doc = _text_doc()
    found, _ = detect_page(doc[0])
    tel = next(d for d in found if d.kind == "전화번호")
    r = pymupdf.Rect(tel.region)
    for w in doc[0].get_text("words"):
        if w[4] in ("010", "1234", "5678"):
            assert r.contains(pymupdf.Rect(w[:4]))


# ---------- 스캔 PDF + OCR ----------

def test_is_scanned_heuristic():
    assert not is_scanned(_text_doc()[0])
    assert is_scanned(_scan_doc()[0])


def _fake_ocr_from_source(rotation: int):
    """진짜 OCR 대신: 원본 텍스트 PDF 의 단어 위치를 '렌더 이미지 픽셀 좌표'로 바꿔 돌려주는 가짜 백엔드.

    OCR 엔진이 돌려줄 법한 결과(회전된 이미지의 픽셀 상자)를 흉내 내어,
    픽셀 → 페이지 좌표 변환과 줄 묶기가 맞는지 검증한다.
    """
    src_page = _text_doc()[0]

    def fake(page: pymupdf.Page):
        _, zoom = render_for_ocr(page)
        words = []
        for w in src_page.get_text("words"):
            r = pymupdf.Rect(w[:4]) * page.rotation_matrix * zoom  # 회전·확대된 이미지 픽셀
            r.normalize()
            words.append(PixelWord(r.x0, r.y0, r.x1, r.y1, w[4], line_id=w[5] * 100 + w[6]))
        return pixel_words_to_lines(page, words, zoom)

    return fake


@pytest.mark.parametrize("rotation", [0, 90])
def test_scanned_page_uses_ocr_and_redacts_pixels(tmp_path, rotation):
    doc = _scan_doc(rotation)
    src = tmp_path / "scan.pdf"
    doc.save(src)
    report = detect_document(doc, ocr=_fake_ocr_from_source(rotation))
    assert report.ocr_pages == [0]
    kinds = {d.kind for d in report.detections}
    assert {"주민번호", "전화번호", "이메일"} <= kinds
    assert all(d.source == "ocr" for d in report.detections)

    regions = {0: [d.region for d in report.detections]}
    redact_pdf(src, tmp_path / "out.pdf", regions)
    # 가려진 자리의 픽셀이 검정인지 확인 (SSN 영역 중심)
    ssn = next(d for d in report.detections if d.kind == "주민번호")
    with pymupdf.open(tmp_path / "out.pdf") as o:
        page = o[0]
        cx = (ssn.region[0] + ssn.region[2]) / 2
        cy = (ssn.region[1] + ssn.region[3]) / 2
        pt = pymupdf.Point(cx, cy) * page.rotation_matrix  # 픽스맵은 회전 적용
        pix = page.get_pixmap(dpi=72, alpha=False)
        assert pix.pixel(int(pt.x), int(pt.y)) == (0, 0, 0)
        # 가리지 않은 흰 배경은 그대로
        assert pix.pixel(5, 5)[0] > 200


def test_ocr_unavailable_is_reported_not_raised():
    def broken(page):
        raise OcrUnavailable("언어 팩 없음")

    doc = _scan_doc()
    report = detect_document(doc, ocr=broken)
    assert report.detections == []
    assert report.skipped_pages == [0]
    assert "언어 팩" in report.ocr_error


def test_ocr_digit_confusions_are_fixed():
    # OCR 이 0→O, 1→l 로 잘못 읽은 경우도 번호로 잡혀야 함
    line = [(10, 10, 40, 20, "SSN:"), (45, 10, 120, 20, "9OOlOl-1234567")]
    found = detect_lines([line], 0, {"주민번호"}, source="ocr")
    assert len(found) == 1 and found[0].kind == "주민번호"
    # 텍스트 PDF 에서는 보정하지 않음 (진짜 글자가 O 인 경우를 오탐하지 않도록)
    assert detect_lines([line], 0, {"주민번호"}, source="text") == []


def test_progress_callback_can_cancel():
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    seen = []

    def progress(i, n):
        seen.append(i)
        return i < 1

    detect_document(doc, progress=progress)
    assert seen == [0, 1]
