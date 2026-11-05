"""PDF 수동 마스킹 데스크톱 앱 (PySide6)."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import pymupdf

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from masker import theme
from masker.core import Region, display_to_page, page_to_display, redact_pdf
from masker.detect import PATTERNS, Detection, detect_document
from masker.ocr import ocr_available

APP_NAME = "PDF Masker"
ZOOM_STEPS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0]
THUMB_WIDTH = 120


class PageCanvas(QLabel):
    """페이지 이미지 위에서 마우스 드래그로 사각형을 그리는 위젯."""

    def __init__(self, on_region_added, on_region_clicked) -> None:
        super().__init__()
        self._on_region_added = on_region_added
        self._on_region_clicked = on_region_clicked
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._regions: list[QRect] = []
        self._candidates: list[QRect] = []
        self._selected = -1
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_content(self, pixmap: QPixmap, regions: list[QRect], selected: int,
                    candidates: list[QRect] | None = None) -> None:
        self._regions = regions
        self._candidates = candidates or []
        self._selected = selected
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.update()

    def set_overlays(self, regions: list[QRect], selected: int, candidates: list[QRect] | None = None) -> None:
        self._regions = regions
        self._candidates = candidates or []
        self._selected = selected
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.pixmap().isNull():
            return
        pos = event.position().toPoint()
        for i, r in enumerate(self._regions):
            if r.contains(pos):
                self._on_region_clicked(i)
                return
        self._start = pos
        self._current = pos

    def mouseMoveEvent(self, event) -> None:
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._start is None:
            return
        rect = QRect(self._start, event.position().toPoint()).normalized()
        self._start = None
        self._current = None
        if rect.width() >= 3 and rect.height() >= 3:
            self._on_region_added(rect)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.pixmap().isNull():
            return
        t = theme.tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for r in self._candidates:  # 자동 탐지 후보: 주황 점선
            painter.setPen(QPen(QColor("#f59e0b"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(theme.qcolor("#f59e0b", 50))
            painter.drawRect(r)
        for i, r in enumerate(self._regions):  # 확정 영역: 저장 결과와 같은 불투명 검정
            selected = i == self._selected
            painter.setPen(QPen(QColor(t["accent"]) if selected else QColor(t["mask"]), 2))
            painter.setBrush(QColor(t["mask"]))
            painter.drawRect(r)
        if self._start is not None and self._current is not None:
            live = QRect(self._start, self._current).normalized()
            painter.setPen(QPen(QColor(t["accent"]), 2, Qt.PenStyle.DashLine))
            painter.setBrush(theme.qcolor(t["accent"], 60))
            painter.drawRect(live)
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 840)
        self.setAcceptDrops(True)

        self.pdf: pymupdf.Document | None = None
        self.pdf_path: Path | None = None
        self.password: str | None = None
        self.page_index = 0
        self.zoom = 1.5
        self._fit_width = True
        # 영역은 회전 전 PDF 포인트 좌표로 보관 -> 확대/축소·페이지 회전과 무관
        self.regions: dict[int, list[Region]] = {}
        self.candidates: list[Detection] = []
        self._thumb_cache: dict[int, QPixmap] = {}

        self._build_ui()
        self._build_actions()
        self._apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self._apply_theme())
        self._update_controls()

    # ---------- UI 구성 ----------
    def _build_ui(self) -> None:
        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(self.toolbar)

        # 왼쪽: 썸네일
        self.thumbs = QListWidget()
        self.thumbs.setObjectName("thumbs")
        self.thumbs.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.4)))
        self.thumbs.setFixedWidth(THUMB_WIDTH + 56)
        self.thumbs.setSpacing(2)
        self.thumbs.setUniformItemSizes(False)
        self.thumbs.currentRowChanged.connect(self._on_thumb_selected)

        # 가운데: 캔버스 / 환영 화면
        self.canvas = PageCanvas(self._add_region_from_display, self._select_region)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidgetResizable(False)
        self.scroll.viewport().installEventFilter(self)

        self.welcome = self._build_welcome()
        self.center = QStackedWidget()
        self.center.addWidget(self.welcome)
        self.center.addWidget(self.scroll)

        # 오른쪽: 영역 목록 + 자동 탐지
        self.region_list = QListWidget()
        self.region_list.currentRowChanged.connect(self._on_region_selected)
        self.btn_del = QPushButton("선택 영역 삭제")
        self.btn_del.setObjectName("danger")
        self.btn_clear = QPushButton("이 페이지 전체 삭제")
        self.btn_del.clicked.connect(self._delete_selected)
        self.btn_clear.clicked.connect(self._clear_page)

        self.kind_checks: dict[str, QCheckBox] = {}
        kinds_row = QHBoxLayout()
        kinds_row.setSpacing(10)
        for kind in PATTERNS:
            cb = QCheckBox(kind)
            cb.setChecked(True)
            self.kind_checks[kind] = cb
            kinds_row.addWidget(cb)
        kinds_row.addStretch(1)
        self.btn_detect = QPushButton("문서 전체에서 찾기")
        self.btn_detect.clicked.connect(self._run_detect)
        ok, why = ocr_available()
        self.ocr_hint = QLabel("스캔본은 OS 내장 OCR로 읽습니다" if ok else f"스캔본 OCR 사용 불가: {why.splitlines()[0]}")
        self.ocr_hint.setObjectName("hint")
        self.ocr_hint.setWordWrap(True)
        self.candidate_list = QListWidget()
        self.candidate_list.itemChanged.connect(lambda _: self._refresh_canvas_overlays())
        self.candidate_list.currentRowChanged.connect(self._on_candidate_selected)
        self.btn_add_candidates = QPushButton("체크한 항목을 마스킹 영역으로 추가")
        self.btn_add_candidates.setObjectName("primary")
        self.btn_add_candidates.clicked.connect(self._add_checked_candidates)
        self.btn_clear_candidates = QPushButton("후보 지우기")
        self.btn_clear_candidates.clicked.connect(self._clear_candidates)

        self.rasterize = QCheckBox("모든 페이지를 이미지로 변환 (가장 안전, 텍스트 검색 불가)")
        self.btn_save = QPushButton("마스킹 적용 후 저장…")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._save)

        side = QVBoxLayout()
        side.setContentsMargins(12, 10, 12, 12)
        side.setSpacing(8)
        side.addWidget(self._heading("마스킹 영역 · 현재 페이지"))
        side.addWidget(self.region_list, 2)
        row = QHBoxLayout()
        row.addWidget(self.btn_del)
        row.addWidget(self.btn_clear)
        side.addLayout(row)
        side.addSpacing(6)
        side.addWidget(self._heading("자동 탐지"))
        side.addLayout(kinds_row)
        side.addWidget(self.btn_detect)
        side.addWidget(self.ocr_hint)
        side.addWidget(self.candidate_list, 2)
        row2 = QHBoxLayout()
        row2.addWidget(self.btn_add_candidates, 1)
        row2.addWidget(self.btn_clear_candidates)
        side.addLayout(row2)
        side.addSpacing(6)
        side.addWidget(self._heading("저장"))
        side.addWidget(self.rasterize)
        side.addWidget(self.btn_save)
        self.side_widget = QWidget()
        self.side_widget.setLayout(side)
        self.side_widget.setMinimumWidth(320)
        self.side_widget.setMaximumWidth(420)

        splitter = QSplitter()
        splitter.addWidget(self.thumbs)
        splitter.addWidget(self.center)
        splitter.addWidget(self.side_widget)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(1, False)
        self.setCentralWidget(splitter)

        self.status_left = QLabel("")
        self.status_right = QLabel("")
        self.statusBar().addWidget(self.status_left, 1)
        self.statusBar().addPermanentWidget(self.status_right)

    def _build_welcome(self) -> QWidget:
        outer = QWidget()
        lay = QVBoxLayout(outer)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card = QFrame()
        card.setObjectName("dropzone")
        card.setFixedSize(460, 300)
        v = QVBoxLayout(card)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setSpacing(10)
        self.welcome_icon = QLabel()
        self.welcome_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("PDF를 여기에 끌어다 놓으세요")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("모든 처리는 이 컴퓨터 안에서만 이루어지며\n파일이 외부로 전송되지 않습니다.")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("파일 열기…")
        btn.setObjectName("primary")
        btn.setFixedWidth(160)
        btn.clicked.connect(self._open)
        v.addWidget(self.welcome_icon)
        v.addWidget(title)
        v.addWidget(hint)
        v.addSpacing(8)
        v.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(card)
        return outer

    @staticmethod
    def _heading(text: str) -> QLabel:
        lab = QLabel(text.upper())
        lab.setObjectName("heading")
        return lab

    def _build_actions(self) -> None:
        def act(text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            if shortcut is not None:
                a.setShortcut(shortcut)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(slot)
            return a

        self.act_open = act("열기", self._open, QKeySequence.StandardKey.Open, "PDF 열기 (Ctrl+O)")
        self.act_save = act("저장", self._save, QKeySequence.StandardKey.Save, "마스킹 적용 후 저장 (Ctrl+S)")
        self.act_prev = act("이전", lambda: self._go_page(self.page_index - 1), QKeySequence(Qt.Key.Key_PageUp))
        self.act_next = act("다음", lambda: self._go_page(self.page_index + 1), QKeySequence(Qt.Key.Key_PageDown))
        self.act_zoom_in = act("확대", lambda: self._zoom_step(+1), QKeySequence.StandardKey.ZoomIn)
        self.act_zoom_out = act("축소", lambda: self._zoom_step(-1), QKeySequence.StandardKey.ZoomOut)
        self.act_fit = act("폭 맞춤", self._fit_to_width, QKeySequence("Ctrl+0"))
        self.act_detect = act("자동 탐지", self._run_detect, QKeySequence("Ctrl+F"))
        self.act_delete = act("영역 삭제", self._delete_selected, QKeySequence(Qt.Key.Key_Delete))
        self.act_quit = act("종료", self.close, QKeySequence.StandardKey.Quit)
        self.addAction(self.act_delete)

        self.zoom_label = QLabel("150%")
        self.zoom_label.setFixedWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label = QLabel("")
        self.page_label.setFixedWidth(70)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        tb = self.toolbar
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addSeparator()
        tb.addAction(self.act_prev)
        tb.addWidget(self.page_label)
        tb.addAction(self.act_next)
        tb.addSeparator()
        tb.addAction(self.act_zoom_out)
        tb.addWidget(self.zoom_label)
        tb.addAction(self.act_zoom_in)
        tb.addAction(self.act_fit)
        tb.addSeparator()
        tb.addAction(self.act_detect)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        tb.addWidget(spacer)
        self.local_badge = QLabel("  로컬 처리 · 외부 전송 없음  ")
        self.local_badge.setObjectName("hint")
        tb.addWidget(self.local_badge)

        m = self.menuBar().addMenu("파일")
        m.addAction(self.act_open)
        m.addAction(self.act_save)
        m.addSeparator()
        m.addAction(self.act_quit)
        m = self.menuBar().addMenu("보기")
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_fit, self.act_prev, self.act_next):
            m.addAction(a)
        m = self.menuBar().addMenu("도구")
        m.addAction(self.act_detect)
        m.addAction(self.act_delete)

    def _apply_theme(self) -> None:
        t = theme.tokens()
        QApplication.instance().setPalette(theme.palette(t))
        self.setStyleSheet(theme.stylesheet(t))
        c = t["text"]
        self.act_open.setIcon(theme.icon("open", c))
        self.act_save.setIcon(theme.icon("save", c))
        self.act_prev.setIcon(theme.icon("prev", c))
        self.act_next.setIcon(theme.icon("next", c))
        self.act_zoom_in.setIcon(theme.icon("zoom_in", c))
        self.act_zoom_out.setIcon(theme.icon("zoom_out", c))
        self.act_fit.setIcon(theme.icon("fit", c))
        self.act_detect.setIcon(theme.icon("scan", c))
        self.btn_detect.setIcon(theme.icon("scan", c, 16))
        self.btn_add_candidates.setIcon(theme.icon("plus", t["accent_fg"], 16))
        self.btn_del.setIcon(theme.icon("trash", t["danger"], 16))
        self.btn_save.setIcon(theme.icon("shield", t["accent_fg"], 16))
        self.welcome_icon.setPixmap(theme.icon("shield", t["accent"], 56).pixmap(56, 56))
        self.canvas.update()

    # ---------- 드래그 앤 드롭 ----------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(".pdf"):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        path = event.mimeData().urls()[0].toLocalFile()
        self._load(path)

    # ---------- 마우스 휠 확대 ----------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._zoom_step(+1 if event.angleDelta().y() > 0 else -1)
                return True
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Resize and self._fit_width:
            # 타이머가 늦게 실행될 때 사용자가 이미 수동 확대했으면 건드리지 않음
            QTimer.singleShot(0, lambda: self._fit_width and self._fit_to_width())
        return super().eventFilter(obj, event)

    # ---------- PDF 열기 / 렌더 ----------
    def _open(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "PDF 열기", "", "PDF 파일 (*.pdf)")
        if path:
            self._load(path)

    def _load(self, path: str) -> None:
        try:
            doc = pymupdf.open(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "열기 실패", f"PDF를 열 수 없습니다.\n{exc}")
            return
        password: str | None = None
        while doc.needs_pass:
            pw, ok = QInputDialog.getText(self, "암호 보호", "PDF 암호를 입력하세요:", QLineEdit.EchoMode.Password)
            if not ok:
                doc.close()
                return
            if doc.authenticate(pw):
                password = pw
            else:
                QMessageBox.warning(self, "암호 오류", "암호가 올바르지 않습니다.")
        if self.pdf is not None:
            self.pdf.close()
        self.pdf = doc
        self.pdf_path = Path(path)
        self.password = password
        self.regions = {}
        self.candidates = []
        self._thumb_cache = {}
        self.page_index = 0
        self.candidate_list.clear()
        self.center.setCurrentWidget(self.scroll)
        self.setWindowTitle(f"{self.pdf_path.name} — {APP_NAME}")
        self._populate_thumbs()
        self._fit_width = True
        self._fit_to_width()
        self.status_left.setText(f"{self.pdf_path.name} · {doc.page_count}쪽 · 드래그로 가릴 영역을 지정하세요 · 클릭으로 선택, Delete로 삭제")

    def _render_pixmap(self, zoom: float) -> QPixmap:
        assert self.pdf is not None
        pix = self.pdf[self.page_index].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(img.copy())

    def _populate_thumbs(self) -> None:
        assert self.pdf is not None
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for i in range(self.pdf.page_count):
            item = QListWidgetItem(self._thumb_icon(i), f"{i + 1}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.thumbs.addItem(item)
        self.thumbs.setCurrentRow(0)
        self.thumbs.blockSignals(False)

    def _thumb_icon(self, index: int):
        if index not in self._thumb_cache:
            page = self.pdf[index]
            zoom = THUMB_WIDTH / max(page.rect.width, 1)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
            self._thumb_cache[index] = QPixmap.fromImage(img.copy())
        base = self._thumb_cache[index]
        n = len(self.regions.get(index, []))
        if n == 0:
            return QIcon(base)
        # 마스킹 영역이 있는 페이지는 배지 표시
        pm = QPixmap(base)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = theme.tokens()
        p.setBrush(QColor(t["accent"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(pm.width() - 24, 4, 20, 20)
        p.setPen(QColor(t["accent_fg"]))
        p.drawText(QRect(pm.width() - 24, 4, 20, 20), Qt.AlignmentFlag.AlignCenter, str(n))
        p.end()
        return QIcon(pm)

    def _refresh_thumb(self, index: int) -> None:
        item = self.thumbs.item(index)
        if item is not None:
            item.setIcon(self._thumb_icon(index))

    def _page_regions_display(self) -> list[QRect]:
        assert self.pdf is not None
        page = self.pdf[self.page_index]
        out = []
        for region in self.regions.get(self.page_index, []):
            x0, y0, x1, y1 = page_to_display(page, region, self.zoom)
            out.append(QRect(round(x0), round(y0), round(x1 - x0), round(y1 - y0)))
        return out

    def _page_candidates_display(self) -> list[QRect]:
        assert self.pdf is not None
        page = self.pdf[self.page_index]
        out = []
        for i, d in enumerate(self.candidates):
            item = self.candidate_list.item(i)
            if d.page != self.page_index or item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            x0, y0, x1, y1 = page_to_display(page, d.region, self.zoom)
            out.append(QRect(round(x0), round(y0), round(x1 - x0), round(y1 - y0)))
        return out

    def _show_page(self, selected: int = -1) -> None:
        if self.pdf is None:
            self._update_controls()
            return
        self.canvas.set_content(self._render_pixmap(self.zoom), self._page_regions_display(), selected,
                                self._page_candidates_display())
        self._refresh_list(selected)
        self.page_label.setText(f"{self.page_index + 1} / {self.pdf.page_count}")
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")
        if self.thumbs.currentRow() != self.page_index:
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(self.page_index)
            self.thumbs.blockSignals(False)
        self._update_controls()

    def _refresh_canvas_overlays(self, selected: int | None = None) -> None:
        if self.pdf is None:
            return
        sel = self.region_list.currentRow() if selected is None else selected
        self.canvas.set_overlays(self._page_regions_display(), sel, self._page_candidates_display())

    def _refresh_list(self, selected: int = -1) -> None:
        self.region_list.blockSignals(True)
        self.region_list.clear()
        for i, (x0, y0, x1, y1) in enumerate(self.regions.get(self.page_index, [])):
            self.region_list.addItem(f"영역 {i + 1}  ·  {x1 - x0:.0f} × {y1 - y0:.0f} pt  @ ({x0:.0f}, {y0:.0f})")
        if selected >= 0:
            self.region_list.setCurrentRow(selected)
        self.region_list.blockSignals(False)

    def _go_page(self, index: int) -> None:
        if self.pdf is None or not 0 <= index < self.pdf.page_count:
            return
        self.page_index = index
        if self._fit_width:
            self._fit_to_width()  # 페이지마다 크기/회전이 다를 수 있음
        else:
            self._show_page()

    def _on_thumb_selected(self, row: int) -> None:
        if row >= 0:
            self._go_page(row)

    # ---------- 확대/축소 ----------
    def _set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.25, min(zoom, 6.0))
        self._show_page(self.region_list.currentRow())

    def _zoom_step(self, direction: int) -> None:
        if self.pdf is None:
            return
        self._fit_width = False
        if direction > 0:
            nxt = next((z for z in ZOOM_STEPS if z > self.zoom + 1e-6), ZOOM_STEPS[-1])
        else:
            nxt = next((z for z in reversed(ZOOM_STEPS) if z < self.zoom - 1e-6), ZOOM_STEPS[0])
        self._set_zoom(nxt)

    def _fit_to_width(self) -> None:
        if self.pdf is None:
            return
        self._fit_width = True
        avail = self.scroll.viewport().width() - 32
        page_w = self.pdf[self.page_index].rect.width
        self._set_zoom(avail / page_w)

    # ---------- 영역 편집 ----------
    def _add_region_from_display(self, rect: QRect) -> None:
        if self.pdf is None:
            return
        page = self.pdf[self.page_index]
        region = display_to_page(page, (rect.left(), rect.top(), rect.right() + 1, rect.bottom() + 1), self.zoom)
        if region[2] - region[0] < 1 or region[3] - region[1] < 1:
            return  # 페이지 밖에서만 드래그한 경우
        self.regions.setdefault(self.page_index, []).append(region)
        self._refresh_list(len(self.regions[self.page_index]) - 1)
        self._refresh_canvas_overlays()
        self._refresh_thumb(self.page_index)
        self._update_controls()

    def _select_region(self, index: int) -> None:
        self.region_list.setCurrentRow(index)

    def _on_region_selected(self, row: int) -> None:
        self._refresh_canvas_overlays(row)

    def _delete_selected(self) -> None:
        row = self.region_list.currentRow()
        items = self.regions.get(self.page_index, [])
        if self.pdf is None or not 0 <= row < len(items):
            return
        del items[row]
        if not items:
            self.regions.pop(self.page_index, None)
        self._refresh_list()
        self._refresh_canvas_overlays(-1)
        self._refresh_thumb(self.page_index)
        self._update_controls()

    def _clear_page(self) -> None:
        if self.pdf is None or self.page_index not in self.regions:
            return
        self.regions.pop(self.page_index, None)
        self._refresh_list()
        self._refresh_canvas_overlays(-1)
        self._refresh_thumb(self.page_index)
        self._update_controls()

    # ---------- 자동 탐지 ----------
    def _fill_candidate_list(self, checked: bool) -> None:
        self.candidate_list.blockSignals(True)
        self.candidate_list.clear()
        for d in self.candidates:
            tag = " · OCR" if d.source == "ocr" else ""
            item = QListWidgetItem(f"p.{d.page + 1}  [{d.kind}]  {d.text}{tag}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.candidate_list.addItem(item)
        self.candidate_list.blockSignals(False)

    def _run_detect(self) -> None:
        if self.pdf is None:
            return
        kinds = {k for k, cb in self.kind_checks.items() if cb.isChecked()}
        if not kinds:
            QMessageBox.information(self, "자동 탐지", "찾을 종류를 하나 이상 선택하세요.")
            return
        progress = QProgressDialog("문서를 읽는 중…", "취소", 0, self.pdf.page_count, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(400)

        def on_progress(i: int, n: int) -> bool:
            progress.setLabelText(f"{i + 1} / {n} 쪽 읽는 중… (스캔본은 OCR 때문에 느릴 수 있습니다)")
            progress.setValue(i)
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            report = detect_document(self.pdf, kinds, progress=on_progress)
        finally:
            progress.close()
        self.candidates = report.detections
        self._fill_candidate_list(checked=True)
        self._refresh_canvas_overlays()
        self._update_controls()

        n = len(self.candidates)
        msg = f"자동 탐지: {n}건 발견" if n else "자동 탐지: 해당 패턴을 찾지 못했습니다"
        if report.ocr_pages:
            msg += f" · OCR 사용 {len(report.ocr_pages)}쪽"
        self.status_left.setText(msg + (" — 목록에서 확인 후 추가하세요" if n else ""))
        if report.skipped_pages:
            pages = ", ".join(str(p + 1) for p in report.skipped_pages[:8])
            more = " 외" if len(report.skipped_pages) > 8 else ""
            QMessageBox.warning(
                self, "스캔 페이지를 읽지 못했습니다",
                f"{pages}{more} 쪽은 스캔본이라 OCR이 필요한데 사용할 수 없습니다.\n\n"
                f"{report.ocr_error}\n\n이 페이지들은 드래그로 직접 가려 주세요.",
            )

    def _on_candidate_selected(self, row: int) -> None:
        if 0 <= row < len(self.candidates):
            d = self.candidates[row]
            if d.page != self.page_index:
                self._go_page(d.page)

    def _add_checked_candidates(self) -> None:
        added = 0
        keep: list[Detection] = []
        for i, d in enumerate(self.candidates):
            item = self.candidate_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                self.regions.setdefault(d.page, []).append(d.region)
                added += 1
            else:
                keep.append(d)
        self.candidates = keep
        self._fill_candidate_list(checked=False)
        for i in range(self.thumbs.count()):
            self._refresh_thumb(i)
        self._show_page()
        self.status_left.setText(f"{added}개 영역을 추가했습니다.")

    def _clear_candidates(self) -> None:
        self.candidates = []
        self.candidate_list.clear()
        self._refresh_canvas_overlays()
        self._update_controls()

    # ---------- 저장 ----------
    def _total_regions(self) -> int:
        return sum(len(v) for v in self.regions.values())

    def _save(self) -> None:
        if self.pdf is None or self.pdf_path is None:
            return
        total = self._total_regions()
        if total == 0:
            QMessageBox.information(self, "영역 없음", "가릴 영역을 먼저 드래그로 지정하세요.")
            return
        default = str(self.pdf_path.with_name(self.pdf_path.stem + "_masked.pdf"))
        dst, _ = QFileDialog.getSaveFileName(self, "마스킹된 PDF 저장", default, "PDF 파일 (*.pdf)")
        if not dst:
            return
        if Path(dst).resolve() == self.pdf_path.resolve():
            QMessageBox.warning(self, "저장 불가", "원본과 다른 이름으로 저장해야 합니다.")
            return
        pages = len(self.regions)
        answer = QMessageBox.question(
            self, "저장 확인",
            f"{pages}개 페이지의 영역 {total}개를 복구 불가능하게 가리고 저장합니다.\n"
            "원본 파일은 변경되지 않습니다. 계속할까요?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # 자동 탐지 등으로 들어온 아주 작은(1pt 미만) 영역은 저장을 막지 않도록 걸러 낸다
        regions = {p: [r for r in rs if r[2] - r[0] >= 1 and r[3] - r[1] >= 1] for p, rs in self.regions.items()}
        regions = {p: rs for p, rs in regions.items() if rs}
        if not regions:
            QMessageBox.information(self, "영역 없음", "가릴 수 있는 크기의 영역이 없습니다.")
            return
        progress = QProgressDialog("마스킹 적용 중…", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        QApplication.processEvents()
        try:
            redact_pdf(self.pdf_path, dst, regions, rasterize=self.rasterize.isChecked(),
                       password=self.password)
        except Exception as exc:  # noqa: BLE001
            progress.close()
            import traceback
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("저장 실패")
            box.setText(f"저장 중 오류가 발생했습니다.\n{type(exc).__name__}: {exc}")
            box.setInformativeText("'자세히' 내용을 복사해서 알려 주시면 원인을 찾는 데 도움이 됩니다.")
            box.setDetailedText(traceback.format_exc())
            box.exec()
            return
        progress.close()
        self.status_left.setText(f"저장 완료: {dst}")
        QMessageBox.information(self, "완료", f"저장했습니다.\n{dst}")

    # ---------- 기타 ----------
    def _update_controls(self) -> None:
        has = self.pdf is not None
        n = self.pdf.page_count if has else 0
        self.act_prev.setEnabled(has and self.page_index > 0)
        self.act_next.setEnabled(has and self.page_index < n - 1)
        for a in (self.act_save, self.act_zoom_in, self.act_zoom_out, self.act_fit, self.act_detect):
            a.setEnabled(has)
        self.btn_del.setEnabled(has and bool(self.regions.get(self.page_index)))
        self.btn_clear.setEnabled(has and bool(self.regions.get(self.page_index)))
        self.btn_detect.setEnabled(has)
        self.btn_add_candidates.setEnabled(has and bool(self.candidates))
        self.btn_clear_candidates.setEnabled(has and bool(self.candidates))
        self.btn_save.setEnabled(has and self._total_regions() > 0)
        self.rasterize.setEnabled(has)
        total = self._total_regions()
        self.status_right.setText(f"영역 {total}개 · {len(self.regions)}쪽" if has else "")

    def _confirm_discard(self, action: str = "다른 파일을 열까요?") -> bool:
        if self._total_regions() == 0:
            return True
        answer = QMessageBox.question(self, "확인", f"지정한 마스킹 영역이 사라집니다. {action}")
        return answer == QMessageBox.StandardButton.Yes

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._confirm_discard("종료할까요?"):
            event.ignore()
            return
        if self.pdf is not None:
            self.pdf.close()
        event.accept()


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")  # 플랫폼별 편차 없이 스타일시트가 일관되게 적용됨
    icon_path = Path(__file__).with_name("assets") / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    args = app.arguments()[1:]
    if args and args[0].lower().endswith(".pdf"):
        win._load(args[0])  # noqa: SLF001 — 파일 연결로 실행된 경우
    return app.exec()
