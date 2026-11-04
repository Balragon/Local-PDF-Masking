# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 스펙. 사용: pyinstaller pdfmasker.spec
import sys
from pathlib import Path

APP_NAME = "PDF Masker"
ROOT = Path(SPECPATH)
icon = None
if sys.platform == "win32":
    icon = str(ROOT / "masker" / "assets" / "icon.ico")
elif sys.platform == "darwin" and (ROOT / "masker" / "assets" / "icon.icns").exists():
    icon = str(ROOT / "masker" / "assets" / "icon.icns")

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "masker" / "assets" / "icon.png"), "masker/assets")],
    hiddenimports=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtPdf",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
              "pymupdf4llm", "pymupdf_layout", "tkinter"],
    noarchive=False,
)
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
