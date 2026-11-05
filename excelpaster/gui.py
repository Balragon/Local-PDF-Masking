"""엑셀 → 텍스트 양식 변환 데스크톱 앱 (PySide6)."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QFontDatabase, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from excelpaster import core
from excelpaster.core import BUILTIN_PRESETS, FormatSpec
from masker import theme

APP_NAME = "Excel Paster"
ORG_NAME = "LocalTools"
MAX_PREVIEW_CELLS = 200_000  # 이보다 큰 표는 미리보기만 생략 (복사는 됨)
MAX_GRID_ROWS = 500          # 왼쪽 격자 표에 보여 줄 최대 행 수


def _extra_stylesheet(t: dict[str, str]) -> str:
    return f"""
    QPlainTextEdit, QLineEdit, QComboBox {{
        background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 7px;
        padding: 6px 8px; selection-background-color: {t['accent']};
        selection-color: {t['accent_fg']}; }}
    QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
    QPlainTextEdit[readOnly="true"] {{ background: {t['canvas']}; }}
    QTableWidget {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 7px;
        gridline-color: {t['border']}; selection-background-color: {t['selected']};
        selection-color: {t['text']}; outline: none; }}
    QHeaderView::section {{ background: {t['bg']}; color: {t['muted']}; border: none;
        border-right: 1px solid {t['border']}; border-bottom: 1px solid {t['border']};
        padding: 4px 6px; font-weight: 600; }}
    QTableCornerButton::section {{ background: {t['bg']}; border: none; }}
    QFrame#dropzone:hover {{ border-color: {t['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {t['panel']}; border: 1px solid {t['border']};
        selection-background-color: {t['selected']}; selection-color: {t['text']}; outline: none; }}
    QToolButton#chip {{ background: {t['selected']}; color: {t['text']}; border: none;
        border-radius: 10px; padding: 3px 9px; font-size: 12px; }}
    QToolButton#chip:hover {{ background: {t['accent']}; color: {t['accent_fg']}; }}
    QLabel#warn {{ color: {t['danger']}; }}
    QLabel#ok {{ color: {t['muted']}; }}
    QLabel#field {{ color: {t['muted']}; font-size: 12px; }}
    """


class FlowLayout(QLayout):
    """줄바꿈되는 가로 배치 (Qt 예제 기반). 열 이름 칩 표시용."""

    def __init__(self, parent=None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items = []
        self._space = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def clear(self) -> None:
        while self._items:
            it = self._items.pop()
            w = it.widget()
            if w is not None:
                w.hide()  # deleteLater 가 처리되기 전까지 화면에 남지 않도록
                w.setParent(None)
                w.deleteLater()

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, w, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _layout(self, rect: QRect, dry: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            w, h = it.sizeHint().width(), it.sizeHint().height()
            if x + w > rect.right() + 1 and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + self._space, 0
            if not dry:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += w + self._space
            line_h = max(line_h, h)
        return y + line_h - rect.y()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1240, 760)
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.table: core.Table = []
        self.user_presets: list[FormatSpec] = core.load_presets(self.settings.value("presets", "", str))
        self._last_result = ""
        self._last_imported = ""
        self._loading = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._update_output)

        self._build_actions()
        self._build_ui()
        self._apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self._apply_theme())
        self._restore_state()
        self._reload_preset_combo()
        self.paste_hint.setFocus()

    # ------------------------------------------------------------ UI

    @staticmethod
    def _heading(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("heading")
        return lab

    @staticmethod
    def _field(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("field")
        return lab

    @staticmethod
    def _mono() -> QFont:
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setPointSize(max(f.pointSize(), 10))
        return f

    def _build_actions(self) -> None:
        def act(text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(f"{tip} ({a.shortcut().toString()})" if shortcut else tip)
            return a

        self.act_paste = act("클립보드 가져오기", self._paste_clipboard, "Ctrl+Shift+V",
                             "엑셀에서 복사한 내용을 입력칸에 넣기")
        self.act_copy = act("결과 복사", self._copy_result, "Ctrl+Shift+C", "변환 결과를 클립보드로")
        self.act_clear = act("입력 지우기", self._clear_input, "Ctrl+L")
        self.act_save_preset = act("프리셋 저장…", self._save_preset, "Ctrl+S")
        self.act_delete_preset = act("프리셋 삭제", self._delete_preset)
        self.act_export = act("프리셋 내보내기…", self._export_presets)
        self.act_import = act("프리셋 가져오기…", self._import_presets)
        self.act_help = act("자리표시자 도움말", self._show_help, "F1")
        self.act_quit = act("종료", self.close, "Ctrl+Q")

        self.toolbar = QToolBar("도구")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for a in (self.act_paste, self.act_copy):
            self.toolbar.addAction(a)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.act_clear)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.act_help)
        self.addToolBar(self.toolbar)

        m = self.menuBar().addMenu("파일")
        for a in (self.act_paste, self.act_copy, self.act_clear):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_quit)
        m = self.menuBar().addMenu("프리셋")
        for a in (self.act_save_preset, self.act_delete_preset):
            m.addAction(a)
        m.addSeparator()
        for a in (self.act_export, self.act_import):
            m.addAction(a)
        m = self.menuBar().addMenu("도움말")
        m.addAction(self.act_help)

    def _build_ui(self) -> None:
        # 1. 입력: 복사한 내용을 엑셀처럼 격자 표로 보여 준다 (붙여넣기는 Ctrl+V 또는 안내 화면 클릭)
        self._raw = ""
        self.grid = QTableWidget()
        self.grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.grid.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.grid.setAlternatingRowColors(False)
        self.grid.setWordWrap(False)
        self.grid.verticalHeader().setDefaultSectionSize(24)
        self.grid.horizontalHeader().setHighlightSections(False)
        self.grid.horizontalHeader().setStretchLastSection(False)
        self.grid.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.grid.installEventFilter(self)

        self.paste_hint = QFrame()
        self.paste_hint.setObjectName("dropzone")
        self.paste_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paste_hint.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.paste_hint.installEventFilter(self)
        hint_lay = QVBoxLayout(self.paste_hint)
        hint_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_title = QLabel("엑셀에서 복사한 뒤 Ctrl+V")
        hint_title.setObjectName("welcomeTitle")
        hint_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_sub = QLabel("또는 이 칸을 클릭하면 클립보드 내용을 가져옵니다.\n"
                          "창이 활성화될 때 자동으로 가져오는 옵션이 기본으로 켜져 있습니다.")
        hint_sub.setObjectName("hint")
        hint_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lay.addWidget(hint_title)
        hint_lay.addWidget(hint_sub)

        self.input = QStackedWidget()
        self.input.addWidget(self.paste_hint)
        self.input.addWidget(self.grid)
        self.input_status = QLabel("")
        self.input_status.setObjectName("ok")
        self.input_status.setWordWrap(True)
        # 열 이름: 헤더 없이 데이터만 복사해도 {품명} 같은 이름을 쓸 수 있도록 한 번 저장해 둠
        self.col_names = QLineEdit()
        self.col_names.setPlaceholderText("비어 있으면 첫 행이 열 이름일 때만 이름으로 참조 가능")
        self.col_names.setToolTip("시트의 열 순서대로 쉼표로 구분. 빈 열은 비워 둠 (예: 품명, 규격, , , , 재질, 수량)")
        self.col_names.textChanged.connect(self._on_col_names_changed)
        self.btn_grab_header = QPushButton("첫 행에서 가져오기")
        self.btn_grab_header.setToolTip("지금 붙여넣은 내용의 첫 행을 열 이름으로 저장")
        self.btn_grab_header.clicked.connect(self._grab_header)
        col_row = QHBoxLayout()
        col_row.addWidget(self.col_names, 1)
        col_row.addWidget(self.btn_grab_header)
        self.chk_skip_blank = QCheckBox("빈 행 건너뛰기")
        self.chk_skip_blank.setChecked(True)
        self.chk_skip_blank.toggled.connect(self._on_spec_changed)
        self.chk_auto = QCheckBox("창이 활성화되면 클립보드 자동 가져오기")
        self.chk_auto.setToolTip("엑셀에서 복사하고 이 창으로 돌아오면 바로 입력칸에 들어갑니다.")
        self.chk_auto.toggled.connect(lambda v: self.settings.setValue("auto_paste", v))

        left = QVBoxLayout()
        left.setContentsMargins(12, 10, 6, 12)
        left.setSpacing(8)
        left.addWidget(self._heading("1. 엑셀에서 복사한 내용"))
        left.addWidget(self.input, 1)
        left.addWidget(self.input_status)
        left.addWidget(self._field("열 이름 (헤더 없이 복사할 때 사용, 한 번만 저장)"))
        left.addLayout(col_row)
        left.addWidget(self.chk_skip_blank)
        left.addWidget(self.chk_auto)
        left_w = QWidget()
        left_w.setLayout(left)

        # 2. 양식: 템플릿 글상자 하나
        self.preset_combo = QComboBox()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.btn_save_preset = QPushButton("저장…")
        self.btn_save_preset.setToolTip("지금 템플릿을 이름 붙여 저장 (Ctrl+S)")
        self.btn_save_preset.clicked.connect(self._save_preset)
        self.btn_del_preset = QPushButton("삭제")
        self.btn_del_preset.setObjectName("danger")
        self.btn_del_preset.clicked.connect(self._delete_preset)
        preset_row = QHBoxLayout()
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.btn_save_preset)
        preset_row.addWidget(self.btn_del_preset)

        self.chips_box = QWidget()
        self.chips = FlowLayout(self.chips_box)
        self.chips_hint = self._field("열 이름을 클릭하면 템플릿 커서 위치에 들어갑니다")

        self.template = QPlainTextEdit()
        self.template.setFont(self._mono())
        self.template.setPlaceholderText(
            "원하는 양식을 그대로 적으세요. { } 가 든 줄만 엑셀 행마다 반복되고\n"
            "나머지 줄은 한 번만 나옵니다.\n\n"
            "예)\n"
            "11/5일 입고요청\n"
            "{품명} {규격} {재질} {수량}개\n"
            "오전입고 바랍니다.\n\n"
            "{열이름} 또는 {1} {2} 로 셀 값을 넣습니다. 자세한 것은 F1.")
        self.template.textChanged.connect(self._on_spec_changed)
        self.template_warn = QLabel("")
        self.template_warn.setObjectName("warn")
        self.template_warn.setWordWrap(True)

        mid = QVBoxLayout()
        mid.setContentsMargins(6, 10, 6, 12)
        mid.setSpacing(8)
        mid.addWidget(self._heading("2. 출력 양식 (템플릿)"))
        mid.addWidget(self.chips_box)
        mid.addWidget(self.chips_hint)
        mid.addWidget(self.template, 1)
        mid.addWidget(self.template_warn)
        mid.addWidget(self._field("저장된 템플릿"))
        mid.addLayout(preset_row)
        mid_w = QWidget()
        mid_w.setLayout(mid)
        mid_w.setMinimumWidth(320)

        # 3. 결과
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(self._mono())
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setPlaceholderText("변환 결과가 여기에 바로 표시됩니다.")
        self.output_status = QLabel("")
        self.output_status.setObjectName("ok")
        self.btn_copy = QPushButton("결과 복사  (Ctrl+Shift+C)")
        self.btn_copy.setObjectName("primary")
        self.btn_copy.setMinimumHeight(40)
        self.btn_copy.clicked.connect(self._copy_result)
        self.chk_minimize = QCheckBox("복사한 뒤 창 최소화")
        self.chk_minimize.toggled.connect(lambda v: self.settings.setValue("minimize_after_copy", v))

        right = QVBoxLayout()
        right.setContentsMargins(6, 10, 12, 12)
        right.setSpacing(8)
        right.addWidget(self._heading("3. 결과"))
        right.addWidget(self.output, 1)
        right.addWidget(self.output_status)
        right.addWidget(self.chk_minimize)
        right.addWidget(self.btn_copy)
        right_w = QWidget()
        right_w.setLayout(right)

        self.splitter = QSplitter()
        for w in (left_w, mid_w, right_w):
            self.splitter.addWidget(w)
            self.splitter.setCollapsible(self.splitter.count() - 1, False)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 4)
        self.setCentralWidget(self.splitter)

        self.status_left = QLabel("엑셀에서 복사 → 붙여넣기 → 결과 복사")
        self.status_right = QLabel("")
        self.statusBar().addWidget(self.status_left, 1)
        self.statusBar().addPermanentWidget(self.status_right)

    def _apply_theme(self) -> None:
        t = theme.tokens()
        QApplication.instance().setPalette(theme.palette(t))
        self.setStyleSheet(theme.stylesheet(t) + _extra_stylesheet(t))
        c = t["text"]
        self.act_paste.setIcon(theme.icon("open", c))
        self.act_copy.setIcon(theme.icon("save", c))
        self.act_clear.setIcon(theme.icon("trash", c))
        self.act_help.setIcon(theme.icon("shield", c))

    # ------------------------------------------------------------ 상태 저장/복원

    def _restore_state(self) -> None:
        s = self.settings
        self.chk_auto.setChecked(s.value("auto_paste", True, bool))
        self.col_names.setText(s.value("column_names", "", str))
        self.chk_minimize.setChecked(s.value("minimize_after_copy", False, bool))
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        sizes = s.value("splitter")
        if sizes:
            self.splitter.setSizes([int(x) for x in sizes])
        last = s.value("last_spec", "", str)
        specs = core.load_presets(last)
        self._load_spec(specs[0] if specs else BUILTIN_PRESETS[0])

    def _current_spec(self) -> FormatSpec:
        return FormatSpec(
            name="",
            template=self.template.toPlainText(),
            header_row=None,  # 첫 행이 열 이름인지 자동 판단
            skip_blank_rows=self.chk_skip_blank.isChecked(),
        )

    def _load_spec(self, spec: FormatSpec) -> None:
        self._loading = True
        try:
            self.template.setPlainText(spec.template)
            self.chk_skip_blank.setChecked(spec.skip_blank_rows)
        finally:
            self._loading = False
        self._on_spec_changed()

    def closeEvent(self, event) -> None:  # noqa: N802
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("splitter", self.splitter.sizes())
        s.setValue("last_spec", core.dump_presets([self._current_spec()]))
        s.setValue("presets", core.dump_presets(self.user_presets))
        event.accept()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.WindowActivate and self.chk_auto.isChecked():
            QTimer.singleShot(0, self._auto_paste)
        return super().event(e)

    # ------------------------------------------------------------ 입력

    def _auto_paste(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text or text == self._last_imported or text == self._last_result:
            return
        if "\t" not in text and "\n" not in text.strip():
            return  # 표 모양이 아니면 건드리지 않음
        self._set_input(text)
        self.status_left.setText("클립보드에서 자동으로 가져왔습니다")

    def _paste_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text:
            self.status_left.setText("클립보드에 텍스트가 없습니다")
            return
        self._set_input(text)
        self.status_left.setText("클립보드에서 가져왔습니다")

    def _set_input(self, text: str) -> None:
        self._last_imported = text
        self._raw = text
        self._on_input_changed()

    def _clear_input(self) -> None:
        self._raw = ""
        self._last_imported = ""
        self._on_input_changed()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # 격자 표나 안내 화면에서 Ctrl+V → 클립보드 가져오기, 안내 화면 클릭도 같은 동작
        if obj in (self.grid, self.paste_hint):
            if event.type() == QEvent.Type.KeyPress and event.matches(QKeySequence.StandardKey.Paste):
                self._paste_clipboard()
                return True
            if obj is self.paste_hint and event.type() == QEvent.Type.MouseButtonRelease:
                self._paste_clipboard()
                return True
        return super().eventFilter(obj, event)

    def _fill_grid(self, headers: list[str], data: core.Table, is_header: bool) -> None:
        """복사한 내용을 격자 표로. 열 머리글은 인식된 열 이름(없으면 번호)."""
        if not self.table:
            self.input.setCurrentWidget(self.paste_hint)
            self.grid.clear()
            self.grid.setRowCount(0)
            self.grid.setColumnCount(0)
            return
        self.input.setCurrentWidget(self.grid)
        rows = data[:MAX_GRID_ROWS]
        self.grid.setUpdatesEnabled(False)
        try:
            self.grid.clear()
            self.grid.setColumnCount(len(headers))
            self.grid.setHorizontalHeaderLabels(core.column_names(headers))
            self.grid.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    item = QTableWidgetItem(val.replace("\r\n", " ⏎ ").replace("\n", " ⏎ "))
                    item.setToolTip(val) if ("\n" in val or len(val) > 40) else None
                    self.grid.setItem(r, c, item)
            self.grid.resizeColumnsToContents()
            for c in range(len(headers)):
                self.grid.setColumnWidth(c, min(max(self.grid.columnWidth(c), 48), 260))
        finally:
            self.grid.setUpdatesEnabled(True)

    def _known_headers(self) -> list[str]:
        return core.parse_column_names(self.col_names.text())

    def _resolve(self) -> tuple[list[str], core.Table, bool]:
        return core.resolve_table(self.table, self._current_spec(), self._known_headers())

    def _on_input_changed(self) -> None:
        self.table = core.parse_table(self._raw)
        self.btn_grab_header.setEnabled(bool(self.table))
        self._refresh_chips()
        self._debounce.start()

    def _on_col_names_changed(self) -> None:
        self.settings.setValue("column_names", self.col_names.text())
        self._on_spec_changed()

    def _grab_header(self) -> None:
        if not self.table:
            return
        names = [core.normalize_header(c) for c in self.table[0]]
        while names and not names[-1]:
            names.pop()
        self.col_names.setText(", ".join(names))
        self.status_left.setText("첫 행을 열 이름으로 저장했습니다. 이제 데이터만 복사해도 이름으로 참조됩니다.")

    def _update_input_status(self, is_header: bool, data_rows: int) -> None:
        if not self.table:
            self.input_status.setText("")
            return
        rows, cols = len(self.table), len(self.table[0])
        how = "첫 행은 열 이름으로 인식해 건너뜀" if is_header else "모든 행을 데이터로 처리"
        more = f" (표에는 {MAX_GRID_ROWS}행까지만 표시)" if data_rows > MAX_GRID_ROWS else ""
        self.input_status.setText(f"{rows}행 × {cols}열 감지 · {how} · 데이터 {data_rows}행{more}")

    # ------------------------------------------------------------ 양식

    def _on_spec_changed(self) -> None:
        if self._loading:
            return
        self._refresh_chips()
        self._debounce.start()

    def _refresh_chips(self) -> None:
        self.chips.clear()
        headers, _, _ = self._resolve()
        names = core.column_names(headers)
        for name in names:
            b = QToolButton()
            b.setObjectName("chip")
            b.setText(name)
            b.setToolTip(f"{{{name}}} 삽입")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self._insert_placeholder(n))
            self.chips.addWidget(b)
        for name, tip in (("#", "행 번호"), ("행수", "전체 행 수")):
            b = QToolButton()
            b.setObjectName("chip")
            b.setText(name)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self._insert_placeholder(n))
            self.chips.addWidget(b)
        self.chips_hint.setText("열 이름을 클릭하면 템플릿 커서 위치에 들어갑니다" if names
                                else "먼저 왼쪽에 엑셀 내용을 붙여넣으세요")

    def _insert_placeholder(self, name: str) -> None:
        self.template.insertPlainText("{" + name + "}")
        self.template.setFocus()

    # ------------------------------------------------------------ 출력

    def _update_output(self) -> None:
        spec = self._current_spec()
        self.template_warn.setText("")
        if not self.table:
            self.output.setPlainText("")
            self.output_status.setText("")
            self.input_status.setText("")
            self._fill_grid([], [], False)
            self.btn_copy.setEnabled(False)
            return
        headers, data, is_header = core.resolve_table(self.table, spec, self._known_headers())
        self._update_input_status(is_header, len(data))
        self._fill_grid(headers, data, is_header)
        unknown = core.unknown_placeholders(spec.template, headers)
        if unknown:
            hint = "" if self._known_headers() or is_header else " — 헤더 없이 복사했다면 왼쪽 '열 이름'을 저장하세요"
            self.template_warn.setText("알 수 없는 자리표시자: " + ", ".join("{" + u + "}" for u in unknown) + hint)
        try:
            result = core.render(self.table, spec, self._known_headers())
        except core.TemplateError as e:
            self.template_warn.setText(str(e))
            self.output.setPlainText("")
            self.output_status.setText("")
            self.btn_copy.setEnabled(False)
            return
        self._result = result
        cells = len(self.table) * len(self.table[0])
        if cells > MAX_PREVIEW_CELLS:
            self.output.setPlainText(result[:20000] + "\n…(미리보기 생략, 복사는 전체가 됩니다)")
        else:
            self.output.setPlainText(result)
        self.output_status.setText(f"{len(data)}행 변환 · {len(result):,}자")
        self.btn_copy.setEnabled(bool(result))

    def _copy_result(self) -> None:
        result = getattr(self, "_result", "")
        if not result:
            self.status_left.setText("복사할 결과가 없습니다")
            return
        QGuiApplication.clipboard().setText(result)
        self._last_result = result
        self.status_left.setText(f"결과를 클립보드에 복사했습니다 ({len(result):,}자) — 원하는 곳에 Ctrl+V")
        if self.chk_minimize.isChecked():
            self.showMinimized()

    # ------------------------------------------------------------ 프리셋

    def _reload_preset_combo(self, select_name: str | None = None) -> None:
        self._loading = True
        try:
            self.preset_combo.clear()
            self.preset_combo.addItem("(저장된 템플릿 선택)", None)
            for i, p in enumerate(self.user_presets):
                self.preset_combo.addItem(f"★ {p.name}", ("user", i))
            for i, p in enumerate(BUILTIN_PRESETS):
                self.preset_combo.addItem(p.name, ("builtin", i))
            if select_name is not None:
                for i in range(self.preset_combo.count()):
                    d = self.preset_combo.itemData(i)
                    if d and d[0] == "user" and self.user_presets[d[1]].name == select_name:
                        self.preset_combo.setCurrentIndex(i)
                        break
        finally:
            self._loading = False
        self._update_preset_buttons()

    def _update_preset_buttons(self) -> None:
        d = self.preset_combo.currentData()
        self.btn_del_preset.setEnabled(bool(d) and d[0] == "user")
        self.act_delete_preset.setEnabled(bool(d) and d[0] == "user")

    def _on_preset_selected(self) -> None:
        if self._loading:
            return
        d = self.preset_combo.currentData()
        self._update_preset_buttons()
        if not d:
            return
        spec = self.user_presets[d[1]] if d[0] == "user" else BUILTIN_PRESETS[d[1]]
        self._load_spec(spec)
        self.status_left.setText(f"프리셋 적용: {spec.name}")

    def _save_preset(self) -> None:
        d = self.preset_combo.currentData()
        default = self.user_presets[d[1]].name if d and d[0] == "user" else ""
        name, ok = QInputDialog.getText(self, "프리셋 저장", "프리셋 이름:", text=default)
        name = name.strip()
        if not ok or not name:
            return
        spec = self._current_spec().copy(name=name)
        for i, p in enumerate(self.user_presets):
            if p.name == name:
                self.user_presets[i] = spec
                break
        else:
            self.user_presets.append(spec)
        self.settings.setValue("presets", core.dump_presets(self.user_presets))
        self._reload_preset_combo(select_name=name)
        self.status_left.setText(f"프리셋 저장: {name}")

    def _delete_preset(self) -> None:
        d = self.preset_combo.currentData()
        if not d or d[0] != "user":
            return
        name = self.user_presets[d[1]].name
        if QMessageBox.question(self, "프리셋 삭제", f"'{name}' 프리셋을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        del self.user_presets[d[1]]
        self.settings.setValue("presets", core.dump_presets(self.user_presets))
        self._reload_preset_combo()
        self.status_left.setText(f"프리셋 삭제: {name}")

    def _export_presets(self) -> None:
        if not self.user_presets:
            QMessageBox.information(self, "프리셋 내보내기", "저장된 프리셋이 없습니다.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "프리셋 내보내기", "excel-paster-presets.json", "JSON (*.json)")
        if not path:
            return
        Path(path).write_text(core.dump_presets(self.user_presets), encoding="utf-8")
        self.status_left.setText(f"프리셋 {len(self.user_presets)}개 내보냄: {path}")

    def _import_presets(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "프리셋 가져오기", "", "JSON (*.json)")
        if not path:
            return
        try:
            loaded = core.load_presets(Path(path).read_text(encoding="utf-8"))
        except OSError as e:
            QMessageBox.warning(self, "프리셋 가져오기", f"파일을 읽을 수 없습니다.\n{e}")
            return
        if not loaded:
            QMessageBox.warning(self, "프리셋 가져오기", "프리셋을 찾을 수 없는 파일입니다.")
            return
        names = {p.name for p in self.user_presets}
        added = 0
        for p in loaded:
            if not p.name:
                continue
            if p.name in names:
                self.user_presets = [p if q.name == p.name else q for q in self.user_presets]
            else:
                self.user_presets.append(p)
                names.add(p.name)
            added += 1
        self.settings.setValue("presets", core.dump_presets(self.user_presets))
        self._reload_preset_combo()
        self.status_left.setText(f"프리셋 {added}개 가져옴")

    # ------------------------------------------------------------ 도움말

    def _show_help(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("자리표시자 도움말")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setFont(self._mono())
        box.setText(core.HELP_TEXT)
        box.exec()


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setStyle("Fusion")
    icon_path = Path(__file__).with_name("assets") / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    return app.exec()
