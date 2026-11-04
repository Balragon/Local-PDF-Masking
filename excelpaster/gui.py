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
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
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


def _extra_stylesheet(t: dict[str, str]) -> str:
    return f"""
    QPlainTextEdit, QComboBox {{
        background: {t['panel']}; border: 1px solid {t['border']}; border-radius: 7px;
        padding: 6px 8px; selection-background-color: {t['accent']};
        selection-color: {t['accent_fg']}; }}
    QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
    QPlainTextEdit[readOnly="true"] {{ background: {t['canvas']}; }}
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
        self.input.setFocus()

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
        # 1. 입력
        self.input = QPlainTextEdit()
        self.input.setFont(self._mono())
        self.input.setPlaceholderText("엑셀에서 셀 범위를 복사한 뒤 여기에 Ctrl+V 로 붙여넣으세요.\n"
                                      "창이 활성화될 때 클립보드를 자동으로 가져오는 옵션도 있습니다.")
        self.input.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.input.textChanged.connect(self._on_input_changed)
        self.input_status = QLabel("")
        self.input_status.setObjectName("ok")
        self.input_status.setWordWrap(True)
        self.chk_header = QCheckBox("첫 행을 열 이름으로 사용")
        self.chk_header.setChecked(True)
        self.chk_header.toggled.connect(self._on_spec_changed)
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
        left.addWidget(self.chk_header)
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
            "원하는 양식을 글로 적으세요. 엑셀의 한 행마다 이 글이 반복됩니다.\n\n"
            "예)  {이름}님 ({부서}) - {금액|comma}원\n"
            "예)  {1}, {2}, {3}\n\n"
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
            header_row=self.chk_header.isChecked(),
            skip_blank_rows=self.chk_skip_blank.isChecked(),
        )

    def _load_spec(self, spec: FormatSpec) -> None:
        self._loading = True
        try:
            self.template.setPlainText(spec.template)
            self.chk_header.setChecked(spec.header_row)
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
        self.input.setPlainText(text)

    def _clear_input(self) -> None:
        self.input.clear()
        self._last_imported = ""

    def _on_input_changed(self) -> None:
        self.table = core.parse_table(self.input.toPlainText())
        self._refresh_chips()
        if not self.table:
            self.input_status.setText("")
        else:
            rows, cols = len(self.table), len(self.table[0])
            self.input_status.setText(f"{rows}행 × {cols}열 감지")
        self._debounce.start()

    # ------------------------------------------------------------ 양식

    def _on_spec_changed(self) -> None:
        if self._loading:
            return
        self._refresh_chips()
        self._debounce.start()

    def _refresh_chips(self) -> None:
        self.chips.clear()
        names = core.column_names(self.table, self.chk_header.isChecked())
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
            self.btn_copy.setEnabled(False)
            return
        headers, data = core.split_table(self.table, spec.header_row, spec.skip_blank_rows)
        unknown = core.unknown_placeholders(spec.template, headers)
        if unknown:
            self.template_warn.setText("알 수 없는 자리표시자: " + ", ".join("{" + u + "}" for u in unknown))
        try:
            result = core.render(self.table, spec)
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
