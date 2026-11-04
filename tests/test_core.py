import warnings
from pathlib import Path

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import pymupdf

from masker.core import redact_pdf


def _make_text_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 50), "Name: Hong Gildong", fontsize=12)
    page.insert_text((20, 80), "SSN: 900101-1234567", fontsize=12)
    doc.set_metadata({"author": "Hong Gildong", "title": "secret"})
    doc.save(path)
    doc.close()


def _make_scan_pdf(path: Path) -> None:
    # 이미지 한 장만 있는 "스캔" PDF. 빨간 사각형을 주민번호 자리라고 가정.
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    pix.set_rect(pymupdf.IRect(40, 60, 200, 100), (255, 0, 0))
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path)
    doc.close()


def test_text_is_actually_removed(tmp_path):
    src = tmp_path / "in.pdf"
    dst = tmp_path / "out.pdf"
    _make_text_pdf(src)

    # "SSN: ..." 줄 영역 (y ≈ 68~84)
    applied = redact_pdf(src, dst, {0: [(15, 66, 200, 86)]})

    assert applied == 1
    with pymupdf.open(dst) as out:
        text = out[0].get_text()
        raw = out.tobytes().decode("latin-1", errors="ignore")
        assert "1234567" not in text
        assert "900101" not in text
        assert "Hong Gildong" in text  # 가리지 않은 부분은 유지
        assert "1234567" not in raw  # 바이트 레벨에도 남지 않아야 함
        assert out.metadata.get("author") in (None, "")  # 메타데이터 정리


def test_original_is_not_modified(tmp_path):
    src = tmp_path / "in.pdf"
    dst = tmp_path / "out.pdf"
    _make_text_pdf(src)
    before = src.read_bytes()

    redact_pdf(src, dst, {0: [(15, 66, 200, 86)]})

    assert src.read_bytes() == before


def test_scanned_image_pixels_are_removed(tmp_path):
    src = tmp_path / "scan.pdf"
    dst = tmp_path / "scan_out.pdf"
    _make_scan_pdf(src)

    redact_pdf(src, dst, {0: [(60, 70, 120, 90)]})

    with pymupdf.open(dst) as out:
        pix = out[0].get_pixmap(dpi=72, alpha=False)
        # 가린 영역 중심은 빨강이 아니어야 함 (검정)
        r, g, b = pix.pixel(90, 80)
        assert (r, g, b) == (0, 0, 0)
        # 가리지 않은 빨간 영역은 그대로
        assert pix.pixel(150, 80)[0] > 200


def test_rasterize_has_no_text(tmp_path):
    src = tmp_path / "in.pdf"
    dst = tmp_path / "flat.pdf"
    _make_text_pdf(src)

    redact_pdf(src, dst, {0: [(15, 66, 200, 86)]}, rasterize=True)

    with pymupdf.open(dst) as out:
        assert out.page_count == 1
        assert out[0].get_text().strip() == ""


def test_no_regions_still_saves(tmp_path):
    src = tmp_path / "in.pdf"
    dst = tmp_path / "out.pdf"
    _make_text_pdf(src)

    assert redact_pdf(src, dst, {}) == 0
    assert dst.exists()


def test_same_path_rejected(tmp_path):
    src = tmp_path / "in.pdf"
    _make_text_pdf(src)
    with pytest.raises(ValueError):
        redact_pdf(src, src, {0: [(0, 0, 10, 10)]})


def test_bad_page_index(tmp_path):
    src = tmp_path / "in.pdf"
    _make_text_pdf(src)
    with pytest.raises(ValueError):
        redact_pdf(src, tmp_path / "o.pdf", {5: [(0, 0, 10, 10)]})


# ---------- 검토 후 추가된 테스트 ----------

from masker.core import display_to_page, page_to_display  # noqa: E402


def test_rotated_page_display_mapping_roundtrip(tmp_path):
    src = tmp_path / "rot.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 80), "SECRET-ROT", fontsize=12)
    page.set_rotation(90)
    doc.save(src)
    doc.close()

    with pymupdf.open(src) as d:
        page = d[0]
        # 회전된 화면에서 글자가 보이는 위치 = 회전 전 bbox를 화면 좌표로
        word_bbox = page.get_text("words")[0][:4]
        disp = page_to_display(page, word_bbox, zoom=2.0)
        back = display_to_page(page, disp, zoom=2.0)
        assert all(abs(a - b) < 1e-3 for a, b in zip(back, word_bbox))
        # 화면(회전 후) 좌표는 페이지 rect(200x300) 안에 있어야 함
        assert 0 <= disp[0] and disp[2] <= page.rect.width * 2
        assert 0 <= disp[1] and disp[3] <= page.rect.height * 2

    # 화면 좌표로 드래그한 영역을 변환해 넘기면 실제로 글자가 지워져야 함
    out = tmp_path / "rot_out.pdf"
    with pymupdf.open(src) as d:
        region = display_to_page(d[0], disp, zoom=2.0)
    redact_pdf(src, out, {0: [region]})
    with pymupdf.open(out) as o:
        assert "SECRET" not in o[0].get_text()


def test_display_to_page_clamps_outside_drag(tmp_path):
    with pymupdf.open() as d:
        page = d.new_page(width=300, height=200)
        r = display_to_page(page, (-50, -50, 1000, 1000), zoom=1.0)
        assert r == (0, 0, 300, 200)


def test_form_field_value_is_removed(tmp_path):
    src = tmp_path / "form.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    w = pymupdf.Widget()
    w.field_name = "ssn"
    w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w.rect = pymupdf.Rect(20, 60, 200, 90)
    w.field_value = "900101-1234567"
    page.add_widget(w)
    w2 = pymupdf.Widget()
    w2.field_name = "keep"
    w2.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w2.rect = pymupdf.Rect(20, 150, 200, 180)
    w2.field_value = "stay"
    page.add_widget(w2)
    doc.save(src)
    doc.close()

    redact_pdf(src, tmp_path / "o.pdf", {0: [(10, 50, 220, 100)]})
    with pymupdf.open(tmp_path / "o.pdf") as o:
        fields = {x.field_name: x.field_value for x in o[0].widgets()}
        assert "ssn" not in fields
        assert fields.get("keep") == "stay"
        assert b"1234567" not in o.tobytes()


def test_annotation_content_is_removed(tmp_path):
    src = tmp_path / "annot.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.add_text_annot((30, 70), "secret note 777")
    page.add_text_annot((30, 170), "public note")
    doc.save(src)
    doc.close()

    redact_pdf(src, tmp_path / "o.pdf", {0: [(10, 50, 220, 100)]})
    with pymupdf.open(tmp_path / "o.pdf") as o:
        contents = [a.info["content"] for a in o[0].annots()]
        assert contents == ["public note"]
        assert b"777" not in o.tobytes()


def test_password_pdf(tmp_path):
    src = tmp_path / "enc.pdf"
    doc = pymupdf.open()
    doc.new_page(width=300, height=200).insert_text((20, 50), "SSN 1234567")
    doc.save(src, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    doc.close()

    with pytest.raises(ValueError):
        redact_pdf(src, tmp_path / "o.pdf", {0: [(0, 40, 300, 60)]})
    redact_pdf(src, tmp_path / "o.pdf", {0: [(0, 40, 300, 60)]}, password="pw")
    with pymupdf.open(tmp_path / "o.pdf") as o:
        assert not o.needs_pass
        assert "1234567" not in o[0].get_text()


def test_degenerate_region_rejected(tmp_path):
    src = tmp_path / "in.pdf"
    _make_text_pdf(src)
    with pytest.raises(ValueError):
        redact_pdf(src, tmp_path / "o.pdf", {0: [(10, 10, 10, 10)]})


def test_reversed_coordinates_are_normalized(tmp_path):
    src = tmp_path / "in.pdf"
    dst = tmp_path / "o.pdf"
    _make_text_pdf(src)
    redact_pdf(src, dst, {0: [(200, 86, 15, 66)]})
    with pymupdf.open(dst) as o:
        assert "1234567" not in o[0].get_text()
