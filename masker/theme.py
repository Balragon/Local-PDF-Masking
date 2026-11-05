"""시스템 라이트/다크 설정을 따르는 테마 토큰과 스타일시트."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette, QPixmap

LIGHT = {
    "bg": "#f3f4f6", "panel": "#ffffff", "canvas": "#e5e7eb", "border": "#e2e4e8",
    "text": "#1f2328", "muted": "#6b7280", "accent": "#2563eb", "accent_fg": "#ffffff",
    "hover": "#eef1f5", "selected": "#dbe7ff", "danger": "#dc2626", "mask": "#111111",
}
DARK = {
    "bg": "#1b1d21", "panel": "#23262b", "canvas": "#121316", "border": "#33373d",
    "text": "#e6e8eb", "muted": "#9aa0a8", "accent": "#4f8cff", "accent_fg": "#ffffff",
    "hover": "#2c3036", "selected": "#2f4470", "danger": "#f87171", "mask": "#000000",
}


def is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hints.colorScheme() == Qt.ColorScheme.Dark


def tokens() -> dict[str, str]:
    return DARK if is_dark() else LIGHT


def stylesheet(t: dict[str, str]) -> str:
    return f"""
    QMainWindow, QWidget {{ background: {t['bg']}; color: {t['text']}; font-size: 13px; }}
    QLabel {{ background: transparent; }}
    QToolBar QWidget {{ background: transparent; }}
    QToolBar {{ background: {t['panel']}; border: none; border-bottom: 1px solid {t['border']};
                padding: 4px 8px; spacing: 4px; }}
    QToolBar QToolButton {{ background: transparent; border: none; border-radius: 6px;
                            padding: 5px 8px; color: {t['text']}; }}
    QToolBar QToolButton:hover {{ background: {t['hover']}; }}
    QToolBar QToolButton:pressed, QToolBar QToolButton:checked {{ background: {t['selected']}; }}
    QToolBar QToolButton:disabled {{ color: {t['muted']}; }}
    QToolBar::separator {{ width: 1px; background: {t['border']}; margin: 6px 6px; }}
    QStatusBar {{ background: {t['panel']}; border-top: 1px solid {t['border']}; color: {t['muted']}; }}
    QScrollArea {{ border: none; background: {t['canvas']}; }}
    QScrollArea > QWidget > QWidget {{ background: {t['canvas']}; }}
    QListWidget {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 8px;
                   padding: 4px; outline: none; }}
    QListWidget::item {{ padding: 6px 8px; border-radius: 6px; margin: 1px 0; }}
    QListWidget::item:hover {{ background: {t['hover']}; }}
    QListWidget::item:selected {{ background: {t['selected']}; color: {t['text']}; }}
    QListWidget#thumbs {{ border: none; border-right: 1px solid {t['border']}; border-radius: 0; }}
    QListWidget#thumbs::item {{ padding: 8px 6px; }}
    QPushButton {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 7px;
                   padding: 7px 12px; }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:disabled {{ color: {t['muted']}; }}
    QPushButton#primary {{ background: {t['accent']}; color: {t['accent_fg']}; border: none;
                           font-weight: 600; }}
    QPushButton#primary:hover {{ background: {t['accent']}; opacity: .9; }}
    QPushButton#primary:disabled {{ background: {t['border']}; color: {t['muted']}; }}
    QPushButton#danger {{ color: {t['danger']}; }}
    QLabel#heading {{ font-weight: 600; font-size: 12px; color: {t['muted']};
                      letter-spacing: 0.5px; padding: 6px 2px 2px 2px; }}
    QLabel#hint {{ color: {t['muted']}; }}
    QLabel#welcomeTitle {{ font-size: 20px; font-weight: 600; color: {t['text']}; }}
    QFrame#dropzone {{ border: 2px dashed {t['border']}; border-radius: 16px; background: {t['panel']}; }}
    QFrame#card {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QCheckBox {{ spacing: 6px; }}
    QSplitter::handle {{ background: {t['border']}; width: 1px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 24px; }}
    QToolTip {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 4px; }}
    QMenuBar {{ background: {t['panel']}; }}
    QMenu {{ background: {t['panel']}; border: 1px solid {t['border']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t['selected']}; }}
    """


# 단순한 선형 SVG 아이콘 (Feather 스타일, path 만)
_ICONS = {
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
    "zoom_in": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3M11 8v6M8 11h6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3M8 11h6"/>',
    "fit": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "prev": '<path d="m15 18-6-6 6-6"/>',
    "next": '<path d="m9 18 6-6-6-6"/>',
    "trash": '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 12h10"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
}


def icon(name: str, color: str, size: int = 20) -> QIcon:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
           f'{_ICONS[name]}</svg>')
    pix = QPixmap()
    pix.loadFromData(QByteArray(svg.encode()), "SVG")
    return QIcon(pix)


def qcolor(hex_: str, alpha: int = 255) -> QColor:
    c = QColor(hex_)
    c.setAlpha(alpha)
    return c


def palette(t: dict[str, str]) -> QPalette:
    """스타일시트가 닿지 않는 네이티브 위젯(체크박스, 대화상자)도 같은 색을 쓰도록."""
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["bg"], QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.Base: t["panel"], QPalette.ColorRole.AlternateBase: t["bg"],
        QPalette.ColorRole.Text: t["text"], QPalette.ColorRole.Button: t["panel"],
        QPalette.ColorRole.ButtonText: t["text"], QPalette.ColorRole.Highlight: t["accent"],
        QPalette.ColorRole.HighlightedText: t["accent_fg"], QPalette.ColorRole.ToolTipBase: t["panel"],
        QPalette.ColorRole.ToolTipText: t["text"], QPalette.ColorRole.PlaceholderText: t["muted"],
        QPalette.ColorRole.Mid: t["border"], QPalette.ColorRole.Dark: t["border"],
        QPalette.ColorRole.Light: t["hover"],
    }
    for role, hex_ in roles.items():
        p.setColor(role, QColor(hex_))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["muted"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["muted"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t["muted"]))
    return p
