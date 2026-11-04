"""PDF 영역 마스킹 핵심 로직 (GUI와 분리되어 테스트 가능).

마스킹 영역은 **회전 전(unrotated) 페이지 좌표계**의 PDF 포인트 사각형
(x0, y0, x1, y1) 이며 좌상단이 원점입니다. 화면에 보이는(회전된) 좌표와
변환하려면 display_to_page / page_to_display 를 사용하세요.

복구 불가 처리 방식
- 텍스트: 영역과 겹치는 글자를 실제로 삭제 (PDF_REDACT_TEXT_REMOVE)
- 이미지(스캔본 포함): 영역과 겹치는 이미지 픽셀을 실제로 지움
- 벡터 그래픽: 영역과 닿는 선/도형 제거
- 영역과 겹치는 폼 필드(값 포함)와 주석(메모 내용 포함), 링크 제거
- 메타데이터, 첨부파일, 숨은 텍스트 정리
- garbage 수집으로 이전 리비전/미사용 객체 제거 (증분 저장 사용 안 함)
- 옵션: 모든 페이지를 이미지로 변환 (가장 안전, 텍스트 검색 불가)
"""

from __future__ import annotations

import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import pymupdf

Region = tuple[float, float, float, float]


def display_to_page(page: pymupdf.Page, rect: Region, zoom: float = 1.0) -> Region:
    """화면(회전 적용, zoom 배율) 좌표 -> 회전 전 페이지 좌표. 페이지 밖은 잘라냄."""
    r = pymupdf.Rect(*rect) / zoom
    r = (r * page.derotation_matrix).normalize()
    r &= page.mediabox  # 회전 전 페이지 경계로 클램프
    return (r.x0, r.y0, r.x1, r.y1)


def page_to_display(page: pymupdf.Page, rect: Region, zoom: float = 1.0) -> Region:
    """회전 전 페이지 좌표 -> 화면(회전 적용, zoom 배율) 좌표."""
    r = (pymupdf.Rect(*rect) * page.rotation_matrix).normalize() * zoom
    return (r.x0, r.y0, r.x1, r.y1)


def _normalize(regions: list[Region]) -> list[pymupdf.Rect]:
    out = []
    for r in regions:
        rect = pymupdf.Rect(*r).normalize()
        if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
            raise ValueError(f"너무 작거나 비어 있는 영역: {r}")
        out.append(rect)
    return out


def _remove_overlapping_annots_and_widgets(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> None:
    """영역과 겹치는 폼 필드와 (redact 외) 주석을 삭제한다.

    apply_redactions 는 텍스트/이미지/링크만 지우고, 폼 필드 값이나 메모 주석의
    내용은 그대로 남기므로 별도로 제거해야 한다.
    """
    for widget in list(page.widgets()):
        if any(widget.rect.intersects(r) for r in rects):
            page.delete_widget(widget)
    for annot in list(page.annots()):
        if annot.type[0] == pymupdf.PDF_ANNOT_REDACT:
            continue
        if any(annot.rect.intersects(r) for r in rects):
            page.delete_annot(annot)


def redact_pdf(
    src: str | Path,
    dst: str | Path,
    regions_by_page: dict[int, list[Region]],
    rasterize: bool = False,
    dpi: int = 200,
    password: str | None = None,
) -> int:
    """src PDF의 지정 영역을 복구 불가능하게 가린 뒤 dst에 저장.

    반환값: 적용된 영역 개수.
    원본(src)은 수정하지 않습니다. dst는 src와 달라야 합니다.
    """
    src = Path(src)
    dst = Path(dst)
    if src.resolve() == dst.resolve():
        raise ValueError("출력 파일이 원본과 같을 수 없습니다.")

    applied = 0
    with pymupdf.open(src) as doc:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                raise ValueError("암호가 필요하거나 잘못되었습니다.")

        for pno, regions in sorted(regions_by_page.items()):
            if not regions:
                continue
            if not 0 <= pno < doc.page_count:
                raise ValueError(f"잘못된 페이지 번호: {pno}")
            page = doc[pno]
            rects = _normalize(regions)
            _remove_overlapping_annots_and_widgets(page, rects)
            for rect in rects:
                page.add_redact_annot(rect, fill=(0, 0, 0))
                applied += 1
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )

        if rasterize:
            out = pymupdf.open()
            try:
                for page in doc:
                    pix = page.get_pixmap(dpi=dpi, alpha=False)
                    new_page = out.new_page(width=page.rect.width, height=page.rect.height)
                    new_page.insert_image(new_page.rect, pixmap=pix)
                out.save(dst, garbage=4, deflate=True)
            finally:
                out.close()
        else:
            doc.scrub(
                attached_files=True,
                clean_pages=True,
                embedded_files=True,
                hidden_text=True,
                metadata=True,
                xml_metadata=True,
            )
            # 암호가 걸려 있던 문서도 출력은 암호 없이 저장 (encryption=NONE)
            doc.save(dst, garbage=4, deflate=True, encryption=pymupdf.PDF_ENCRYPT_NONE)

    return applied
