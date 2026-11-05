# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 스펙. 사용: pyinstaller pdfmasker.spec
import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH) / "scripts"))
from pyi_trim import trim_qt  # noqa: E402  — 쓰지 않는 Qt 구성 요소 제거

from PyInstaller.utils.hooks import collect_all

APP_NAME = "PDF Masker"
ROOT = Path(SPECPATH)
icon = None
if sys.platform == "win32":
    icon = str(ROOT / "masker" / "assets" / "icon.ico")
elif sys.platform == "darwin" and (ROOT / "masker" / "assets" / "icon.icns").exists():
    icon = str(ROOT / "masker" / "assets" / "icon.icns")

# OS 내장 OCR 바인딩은 동적으로 불러오므로 PyInstaller 가 놓친다 → 명시적으로 수집
extra_datas, extra_binaries, extra_hidden = [], [], []
ocr_packages = {"win32": ["winrt"], "darwin": ["Vision", "Quartz", "Foundation", "objc"]}.get(sys.platform, [])
for pkg in ocr_packages:
    try:
        d, b, h = collect_all(pkg)
        extra_datas += d
        extra_binaries += b
        extra_hidden += h
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not collect {pkg}: {exc}")

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=extra_binaries,
    datas=[(str(ROOT / "masker" / "assets" / "icon.png"), "masker/assets")] + extra_datas,
    hiddenimports=extra_hidden,
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtPdf",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
              "pymupdf4llm", "pymupdf_layout", "tkinter"],
    noarchive=False,
)
trim_qt(a)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, exclude_binaries=True, name=APP_NAME, console=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="dev.local.pdfmasker",
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # 다크 모드 지원
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PDF", "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["com.adobe.pdf"], "LSHandlerRank": "Alternate",
            }],
        },
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name=APP_NAME, console=False, icon=icon, upx=False,
    )
