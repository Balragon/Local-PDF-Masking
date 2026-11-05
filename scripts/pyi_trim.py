"""PyInstaller 번들에서 쓰지 않는 Qt 구성 요소를 걸러내 exe 크기를 줄인다.

두 앱 모두 QtCore · QtGui · QtWidgets (+ SVG 아이콘) 만 쓰는데, PyInstaller 의 PySide6 훅은
Qt Quick/Qml, Pdf, Network, 번역 파일, 소프트웨어 OpenGL 등을 통째로 넣는다.
스펙 파일에서 `trim_qt(a)` 를 Analysis 뒤에 호출한다.
"""

from __future__ import annotations

import re

# 모듈 이름(Qt6<이름>) 이 이 접두사로 시작하면 제거
DROP_MODULE_PREFIXES = (
    "Quick", "Qml", "Labs", "Pdf", "Network", "VirtualKeyboard", "Multimedia", "WebEngine",
    "WebChannel", "WebSockets", "WebView", "3D", "Designer", "Help", "Sql", "Test", "Xml",
    "PrintSupport", "Charts", "DataVisualization", "Graphs", "Bluetooth", "Nfc", "Positioning",
    "Location", "Sensors", "SerialPort", "SerialBus", "StateMachine", "Scxml", "RemoteObjects",
    "TextToSpeech", "SpatialAudio", "HttpServer", "Concurrent", "OpenGLWidgets", "ShaderTools",
    "SvgWidgets", "UiTools", "Wayland", "Core5Compat", "Protobuf", "Grpc", "Examples",
)
# 플러그인 폴더 (plugins/<이름>) 중 제거할 것. platforms · styles · imageformats · iconengines 는 유지
DROP_PLUGIN_DIRS = {
    "qmltooling", "qmllint", "networkinformation", "tls", "multimedia", "sqldrivers", "position",
    "sensors", "texttospeech", "printsupport", "virtualkeyboard", "webview", "scenegraph", "designer",
    "canbus", "geoservices", "assetimporters", "renderers", "sceneparsers", "geometryloaders",
    "egldeviceintegrations", "wayland-decoration-client", "wayland-graphics-integration-client",
    "wayland-shell-integration", "xcbglintegrations", "generic", "help", "qmlls",
}
# imageformats 중 제거 (qpdf 는 Qt6Pdf 에 의존하므로 함께 빼야 함)
DROP_IMAGEFORMATS = {"qpdf", "qtiff", "qwebp", "qtga", "qwbmp", "qicns"}
# 파일 이름으로 제거 (Windows 소프트웨어 OpenGL, ANGLE)
DROP_FILES = {"opengl32sw.dll", "d3dcompiler_47.dll", "libegl.dll", "libglesv2.dll"}
# 폴더 (PySide6 아래) 통째로 제거
DROP_DIRS = ("translations", "qml", "libexec", "resources", "examples", "typesystems", "include", "glue")

_MODULE_RE = re.compile(r"^(?:lib)?Qt6?(?P<mod>[A-Za-z0-9]+?)(?:\.framework|\.abi3\.so|\.pyd|\.dll|\.so(?:\.\d+)*|\.dylib)$")


def _module_name(basename: str) -> str | None:
    m = _MODULE_RE.match(basename)
    return m.group("mod") if m else None


def _should_drop(dest: str) -> bool:
    d = dest.replace("\\", "/")
    if "PySide6" not in d and "shiboken6" not in d:
        return False
    parts = d.split("/")
    base = parts[-1]
    low = base.lower()
    if low in DROP_FILES:
        return True
    rel = parts[parts.index("PySide6") + 1:] if "PySide6" in parts else parts
    if rel and rel[0] == "Qt":
        rel = rel[1:]
    if rel and rel[0] in DROP_DIRS:
        return True
    if len(rel) >= 2 and rel[0] == "plugins":
        if rel[1] in DROP_PLUGIN_DIRS:
            return True
        if rel[1] == "imageformats" and any(low.startswith(("lib" + n, n)) for n in DROP_IMAGEFORMATS):
            return True
        return False
    # Qt 라이브러리 / PySide6 확장 모듈. macOS 프레임워크는 경로 중간에 Qt<Mod>.framework 가 온다
    for p in rel:
        mod = _module_name(p)
        if mod and mod.startswith(DROP_MODULE_PREFIXES):
            return True
    return False


def trim_qt(analysis) -> None:
    """Analysis 결과의 binaries/datas 에서 불필요한 Qt 파일을 제거하고 요약을 출력한다."""
    for attr in ("binaries", "datas"):
        toc = getattr(analysis, attr)
        kept = [t for t in toc if not _should_drop(t[0])]
        removed = len(toc) - len(kept)
        toc[:] = kept
        print(f"pyi_trim: {attr}: {removed} removed, {len(kept)} kept")
