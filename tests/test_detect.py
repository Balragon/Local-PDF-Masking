import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import pymupdf

from masker.core import redact_pdf
from masker.detect import detect_document, detect_page


def _doc():
    doc = pymupdf.open()
    p = doc.new_page(width=400, height=300)
    p.insert_text((20, 40), "Name: Hong Gildong", fontsize=12)
    p.insert_text((20, 70), "SSN: 900101-1234567", fontsize=12)
    p.insert_text((20, 100), "Tel: 010 1234 5678", fontsize=12)
    p.insert_text((20, 130), "Mail: hong@example.com", fontsize=12)
    p.insert_text((20, 160), "Order 2024-11-04 qty 12", fontsize=12)
    return doc


def test_detects_each_kind():
    doc = _doc()
    found = {(d.kind, d.text) for d in detect_page(doc[0])}
    assert ("주민번호", "900101-1234567") in found
    assert ("전화번호", "010 1234 5678") in found
    assert ("이메일", "hong@example.com") in found
    # 날짜/수량은 잡히지 않아야 함
    assert not any("2024" in t for _, t in found)
    assert not any(k == "카드번호" for k, _ in found)


def test_kind_filter():
    doc = _doc()
    found = detect_page(doc[0], kinds={"이메일"})
    assert [d.kind for d in found] == ["이메일"]


def test_region_covers_text_and_redacts(tmp_path):
    doc = _doc()
    src = tmp_path / "in.pdf"
    doc.save(src)
    dets = detect_document(doc)
    regions = {}
    for d in dets:
        regions.setdefault(d.page, []).append(d.region)
    redact_pdf(src, tmp_path / "out.pdf", regions)
    with pymupdf.open(tmp_path / "out.pdf") as o:
        text = o[0].get_text()
        assert "1234567" not in text and "5678" not in text and "example.com" not in text
        assert "Hong Gildong" in text and "qty 12" in text


def test_multiword_phone_region_spans_words():
    doc = _doc()
    tel = next(d for d in detect_page(doc[0]) if d.kind == "전화번호")
    words = [w for w in doc[0].get_text("words") if w[4] in ("010", "1234", "5678")]
    r = pymupdf.Rect(tel.region)
    for w in words:
        assert r.contains(pymupdf.Rect(w[:4]))
