"""Excel Paster 아이콘 생성: excelpaster/assets/icon.png (512px) 와 icon.ico.

PNG 는 Qt 로 그리고, ICO 는 Pillow 가 있으면 함께 만든다.
사용: python scripts/make_paster_icon.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "excelpaster" / "assets"
SIZE = 512


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 512

    # 배경: 둥근 사각형 (초록 → 엑셀 연상)
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(32 * s, 32 * s, 448 * s, 448 * s), 96 * s, 96 * s)
    p.fillPath(bg, QColor("#1f7a4d"))

    # 왼쪽: 표 (셀 격자)
    p.setPen(QPen(QColor("#ffffff"), 14 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(QColor(255, 255, 255, 40))
    grid = QRectF(92 * s, 140 * s, 150 * s, 232 * s)
    p.drawRoundedRect(grid, 12 * s, 12 * s)
    for i in (1, 2):
        y = grid.top() + grid.height() * i / 3
        p.drawLine(QPointF(grid.left(), y), QPointF(grid.right(), y))
    x = grid.left() + grid.width() / 2
    p.drawLine(QPointF(x, grid.top()), QPointF(x, grid.bottom()))

    # 가운데: 화살표
    p.setPen(QPen(QColor("#ffffff"), 18 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cy = 256 * s
    p.drawLine(QPointF(262 * s, cy), QPointF(318 * s, cy))
    p.drawLine(QPointF(296 * s, cy - 24 * s), QPointF(320 * s, cy))
    p.drawLine(QPointF(296 * s, cy + 24 * s), QPointF(320 * s, cy))

    # 오른쪽: 텍스트 줄
    p.setPen(QPen(QColor("#ffffff"), 18 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i, w in enumerate((84, 60, 84, 48)):
        y = 168 * s + i * 58 * s
        p.drawLine(QPointF(344 * s, y), QPointF((344 + w) * s, y))
    p.end()
    return img


def main() -> None:
    QGuiApplication(sys.argv)
    ASSETS.mkdir(parents=True, exist_ok=True)
    png = ASSETS / "icon.png"
    draw(SIZE).save(str(png), "PNG")
    print(f"written {png}", file=sys.stderr)
    try:
        from PIL import Image
    except ImportError:
        print("Pillow 없음: icon.ico 생략", file=sys.stderr)
        return
    im = Image.open(png)
    im.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"written {ASSETS / 'icon.ico'}", file=sys.stderr)


if __name__ == "__main__":
    main()
