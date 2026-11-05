"""OS 내장 OCR 백엔드 (외부 엔진 번들 없음, 네트워크 사용 없음).

- macOS : Vision 프레임워크 (pyobjc-framework-Vision)
- Windows: Windows.Media.Ocr (winrt-Windows.Media.Ocr)  — 한국어 언어 팩 필요
- 그 외 : 사용 불가

공통 출력은 "줄 단위 단어 목록" 이다. 좌표는 회전 전 페이지 좌표(core.Region 과 동일).
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import pymupdf

from masker.core import display_to_page

Word = tuple[float, float, float, float, str]  # x0, y0, x1, y1, text
Line = list[Word]

# OCR 입력 이미지 해상도. Windows OCR 은 한 변 최대 2600px 제한이 있다.
OCR_ZOOM = 2.5
MAX_SIDE_PX = 2500


class OcrUnavailable(RuntimeError):
    """이 환경에서 OCR 을 쓸 수 없을 때. message 는 사용자에게 보여 줄 안내문."""


@dataclass(frozen=True)
class PixelWord:
    """OCR 백엔드가 돌려주는 원시 결과: 렌더링 이미지의 픽셀 좌표(좌상단 원점)."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    line_id: int


# ---------- 공통 ----------

def render_for_ocr(page: pymupdf.Page) -> tuple[bytes, float]:
    """페이지를 PNG 로 렌더링. (png_bytes, zoom) 반환. 회전이 적용된 이미지다."""
    zoom = OCR_ZOOM
    longest = max(page.rect.width, page.rect.height)
    if longest * zoom > MAX_SIDE_PX:
        zoom = MAX_SIDE_PX / longest
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("png"), zoom


def pixel_words_to_lines(page: pymupdf.Page, words: list[PixelWord], zoom: float) -> list[Line]:
    """픽셀 좌표 단어 → 회전 전 페이지 좌표, 줄별로 묶어서 반환."""
    lines: dict[int, Line] = {}
    for w in words:
        if not w.text.strip():
            continue
        x0, y0, x1, y1 = display_to_page(page, (w.x0, w.y0, w.x1, w.y1), zoom)
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            continue
        lines.setdefault(w.line_id, []).append((x0, y0, x1, y1, w.text))
    out = []
    for line_id in sorted(lines):
        out.append(sorted(lines[line_id], key=lambda w: w[0]))
    return out


def ocr_page(page: pymupdf.Page) -> list[Line]:
    """페이지를 OCR 해서 줄 단위 단어 목록을 돌려준다. 불가하면 OcrUnavailable."""
    png, zoom = render_for_ocr(page)
    if sys.platform == "darwin":
        words = _ocr_macos(png)
    elif sys.platform == "win32":
        words = _ocr_windows(png)
    else:
        raise OcrUnavailable("이 운영체제에는 내장 OCR 이 없습니다. (macOS·Windows 지원)")
    return pixel_words_to_lines(page, words, zoom)


def ocr_available() -> tuple[bool, str]:
    """(가능 여부, 불가 사유)."""
    try:
        if sys.platform == "darwin":
            import Vision  # noqa: F401
        elif sys.platform == "win32":
            _windows_engine()
        else:
            return False, "이 운영체제에는 내장 OCR 이 없습니다."
        return True, ""
    except OcrUnavailable as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"OCR 모듈을 불러올 수 없습니다: {exc}"


# ---------- macOS: Vision ----------

def _ocr_macos(png: bytes) -> list[PixelWord]:
    try:
        import Quartz
        import Vision
        from Foundation import NSData, NSMakeRange
    except ImportError as exc:
        raise OcrUnavailable(f"macOS Vision 모듈이 없습니다: {exc}") from exc

    data = NSData.dataWithBytes_length_(png, len(png))
    source = Quartz.CGImageSourceCreateWithData(data, None)
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)  # 번호·이메일은 교정하면 오히려 망가짐
    try:
        request.setRecognitionLanguages_(["ko-KR", "en-US"])
    except Exception:  # noqa: BLE001 — 구형 macOS 는 ko 미지원
        pass
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise OcrUnavailable(f"Vision OCR 실패: {error}")

    def to_pixels(box) -> tuple[float, float, float, float]:
        # Vision 은 정규화 좌표(0~1), 원점이 좌하단
        origin, size = box.origin, box.size
        x0 = origin.x * width
        x1 = (origin.x + size.width) * width
        y1 = (1 - origin.y) * height
        y0 = (1 - origin.y - size.height) * height
        return x0, y0, x1, y1

    words: list[PixelWord] = []
    for line_id, obs in enumerate(request.results() or []):
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        cand = cand[0]
        text = cand.string()
        # 줄을 공백으로 나눠 단어별 상자를 Vision 에 다시 물어본다
        pos = 0
        for token in text.split(" "):
            if token:
                rect_obs, err = cand.boundingBoxForRange_error_(NSMakeRange(pos, len(token)), None)
                box = rect_obs.boundingBox() if rect_obs is not None else obs.boundingBox()
                x0, y0, x1, y1 = to_pixels(box)
                words.append(PixelWord(x0, y0, x1, y1, token, line_id))
            pos += len(token) + 1
    return words


# ---------- Windows: Windows.Media.Ocr ----------

def _windows_engine():
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
    except ImportError as exc:
        raise OcrUnavailable(f"Windows OCR 모듈이 없습니다: {exc}") from exc
    engine = None
    for tag in ("ko", "ko-KR"):
        if OcrEngine.is_language_supported(Language(tag)):
            engine = OcrEngine.try_create_from_language(Language(tag))
            break
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailable(
            "Windows OCR 언어 팩이 없습니다.\n"
            "설정 → 시간 및 언어 → 언어 및 지역 에서 '한국어'를 추가하고 "
            "언어 옵션의 '광학 문자 인식'을 설치하세요."
        )
    return engine


def _ocr_windows(png: bytes) -> list[PixelWord]:
    import asyncio

    engine = _windows_engine()
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    async def run() -> list[PixelWord]:
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        writer.write_bytes(png)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        words: list[PixelWord] = []
        for line_id, line in enumerate(result.lines):
            for w in line.words:
                r = w.bounding_rect
                words.append(PixelWord(r.x, r.y, r.x + r.width, r.y + r.height, w.text, line_id))
        return words

    return asyncio.run(run())
