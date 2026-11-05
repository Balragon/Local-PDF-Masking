import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pyi_trim import _should_drop  # noqa: E402


def test_drops_unused_qt_modules_on_each_platform():
    # Linux
    assert _should_drop("PySide6/Qt/lib/libQt6Quick.so.6")
    assert _should_drop("PySide6/Qt/lib/libQt6Qml.so.6")
    assert _should_drop("PySide6/Qt/lib/libQt6Pdf.so.6")
    assert _should_drop("PySide6/Qt/lib/libQt6Network.so.6")
    assert _should_drop("PySide6/QtNetwork.abi3.so")
    # Windows
    assert _should_drop("PySide6/Qt6Quick.dll")
    assert _should_drop("PySide6/QtPdf.pyd")
    assert _should_drop("PySide6/opengl32sw.dll")
    assert _should_drop("PySide6/d3dcompiler_47.dll")
    # macOS
    assert _should_drop("PySide6/Qt/lib/QtQuick.framework/Versions/A/QtQuick")
    assert _should_drop("PySide6/Qt/lib/QtPdf.framework/Resources/Info.plist")


def test_keeps_what_the_apps_use():
    for p in (
        "PySide6/Qt/lib/libQt6Core.so.6", "PySide6/Qt/lib/libQt6Gui.so.6", "PySide6/Qt/lib/libQt6Widgets.so.6",
        "PySide6/Qt/lib/libQt6Svg.so.6", "PySide6/Qt/lib/libQt6DBus.so.6", "PySide6/Qt/lib/libQt6OpenGL.so.6",
        "PySide6/Qt6Core.dll", "PySide6/Qt6Widgets.dll", "PySide6/Qt6Svg.dll",
        "PySide6/QtWidgets.pyd", "PySide6/QtCore.abi3.so", "PySide6/libpyside6.abi3.so.6.12",
        "PySide6/Qt/lib/QtWidgets.framework/Versions/A/QtWidgets",
        "PySide6/Qt/plugins/platforms/libqxcb.so", "PySide6/plugins/platforms/qwindows.dll",
        "PySide6/Qt/plugins/styles/libqmacstyle.dylib",
        "PySide6/Qt/plugins/imageformats/libqsvg.so", "PySide6/plugins/imageformats/qico.dll",
        "PySide6/Qt/plugins/iconengines/libqsvgicon.so",
        "PySide6/Qt/plugins/platformthemes/libqgtk3.so", "PySide6/Qt/plugins/platforminputcontexts/libibusplatforminputcontextplugin.so",
        "shiboken6/libshiboken6.abi3.so.6.12",
        "masker/assets/icon.png", "libpython3.13.so.1.0", "PIL/_imaging.cpython-313-x86_64-linux-gnu.so",
    ):
        assert not _should_drop(p), p


def test_drops_plugins_and_folders():
    assert _should_drop("PySide6/Qt/translations/qtbase_ko.qm")
    assert _should_drop("PySide6/translations/qtbase_ko.qm")
    assert _should_drop("PySide6/Qt/plugins/tls/libqopensslbackend.so")
    assert _should_drop("PySide6/plugins/networkinformation/qnetworklistmanager.dll")
    assert _should_drop("PySide6/Qt/plugins/qmltooling/libqmldbg_debugger.so")
    assert _should_drop("PySide6/Qt/plugins/imageformats/libqpdf.so")
    assert _should_drop("PySide6/plugins/imageformats/qpdf.dll")
    assert _should_drop("PySide6/Qt/qml/QtQuick/libqtquick2plugin.so")
    assert _should_drop("PySide6/Qt/libexec/QtWebEngineProcess")
    assert _should_drop("PySide6/Qt/plugins/wayland-shell-integration/libxdg-shell.so")
