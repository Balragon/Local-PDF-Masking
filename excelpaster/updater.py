"""GitHub Releases 기반 업데이트 확인·다운로드·교체.

- 확인: https://api.github.com/repos/<repo>/releases/latest 의 tag_name 과 현재 버전 비교
- 다운로드: 플랫폼에 맞는 자산을 임시 파일로 받고 SHA256SUMS.txt 로 무결성 검증
- 교체(Windows): 실행 중인 exe 는 지울 수 없으므로 작은 .cmd 스크립트가 앱 종료를 기다렸다가
  파일을 바꿔치기하고 새 버전을 실행한다. macOS 는 dmg 를 받은 뒤 Finder 로 열어 준다.

네트워크 접속은 이 모듈에서만 일어나며, 보내는 것은 버전 조회 요청뿐이다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from excelpaster._version import __version__

REPO = "Balragon/Local-PDF-Masking"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET_NAMES = {
    "win32": "Excel-Paster-windows.exe",
    "darwin": "Excel-Paster-macos-arm64.dmg",
}
CHECKSUMS_NAME = "SHA256SUMS.txt"
USER_AGENT = f"Excel-Paster/{__version__}"


@dataclass
class Release:
    version: str                      # "1.2.3"
    tag: str                          # "v1.2.3"
    page_url: str
    assets: dict[str, str] = field(default_factory=dict)  # 파일 이름 → 다운로드 URL
    notes: str = ""

    def asset_url(self, platform: str = sys.platform) -> str | None:
        name = ASSET_NAMES.get(platform)
        return self.assets.get(name) if name else None

    @property
    def checksums_url(self) -> str | None:
        return self.assets.get(CHECKSUMS_NAME)


class UpdateError(Exception):
    pass


# ---------------------------------------------------------------- 버전 비교

def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3', '1.2.3-beta' → (1, 2, 3). 숫자 부분만 본다."""
    m = re.search(r"(\d+(?:\.\d+)*)", text or "")
    if not m:
        return (0,)
    return tuple(int(x) for x in m.group(1).split("."))


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


# ---------------------------------------------------------------- 네트워크

def _get(url: str, timeout: float, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — https 고정 URL
        return resp.read()


def parse_release(payload: dict) -> Release:
    tag = str(payload.get("tag_name", ""))
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in payload.get("assets", [])}
    return Release(
        version=".".join(str(x) for x in parse_version(tag)),
        tag=tag,
        page_url=payload.get("html_url") or RELEASES_PAGE,
        assets={k: v for k, v in assets.items() if k and v},
        notes=payload.get("body") or "",
    )


def fetch_latest(timeout: float = 6.0) -> Release | None:
    """최신 릴리스. 릴리스가 하나도 없으면 None. 네트워크 오류는 UpdateError."""
    try:
        raw = _get(API_LATEST, timeout, accept="application/vnd.github+json")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise UpdateError(f"업데이트 서버 응답 오류 ({e.code})") from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"업데이트 서버에 연결할 수 없습니다: {e.reason if hasattr(e, 'reason') else e}") from e
    try:
        return parse_release(json.loads(raw.decode("utf-8")))
    except (ValueError, AttributeError) as e:
        raise UpdateError("업데이트 정보를 해석할 수 없습니다") from e


def parse_checksums(text: str) -> dict[str, str]:
    """'해시  파일이름' 줄들 → {파일이름: 해시}. '*파일이름' 형식도 허용."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            out[parts[1].strip().lstrip("*")] = parts[0].lower()
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, progress: Callable[[int, int], None] | None = None,
             timeout: float = 30.0) -> None:
    """url → dest. progress(받은 바이트, 전체 바이트 또는 0)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:  # noqa: S310
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"다운로드 실패: {e}") from e


def download_and_verify(release: Release, progress: Callable[[int, int], None] | None = None,
                        platform: str = sys.platform) -> Path:
    """플랫폼 자산을 임시 폴더에 받고 SHA-256 을 검증해 경로를 돌려준다."""
    url = release.asset_url(platform)
    name = ASSET_NAMES.get(platform)
    if not url or not name:
        raise UpdateError("이 운영체제용 파일이 릴리스에 없습니다")
    if not release.checksums_url:
        raise UpdateError("릴리스에 체크섬 파일(SHA256SUMS.txt)이 없어 검증할 수 없습니다")
    try:
        sums = parse_checksums(_get(release.checksums_url, 15).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"체크섬 파일을 받을 수 없습니다: {e}") from e
    expected = sums.get(name)
    if not expected:
        raise UpdateError(f"체크섬 파일에 {name} 항목이 없습니다")
    tmpdir = Path(tempfile.mkdtemp(prefix="excel-paster-update-"))
    dest = tmpdir / name
    download(url, dest, progress)
    actual = sha256_of(dest)
    if actual != expected:
        dest.unlink(missing_ok=True)
        raise UpdateError("받은 파일의 SHA-256 이 릴리스 체크섬과 다릅니다. 설치를 중단했습니다.")
    return dest


# ---------------------------------------------------------------- 교체

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_executable() -> Path:
    return Path(sys.executable).resolve()


def windows_swap_script(current_exe: Path, new_exe: Path, pids: list[int]) -> str:
    """앱 종료를 기다렸다가 exe 를 바꿔치기하고 새 버전을 실행하는 cmd 스크립트."""
    waits = "\n".join(
        f':wait{p}\ntasklist /FI "PID eq {p}" 2>nul | find "{p}" >nul && (timeout /t 1 /nobreak >nul & goto wait{p})'
        for p in pids
    )
    old = f"{current_exe}.old"
    return (
        "@echo off\r\n"
        + waits.replace("\n", "\r\n") + "\r\n"
        f'if exist "{old}" del /f /q "{old}"\r\n'
        f'move /y "{current_exe}" "{old}" >nul || (echo 교체 실패 & pause & exit /b 1)\r\n'
        f'move /y "{new_exe}" "{current_exe}" >nul || (move /y "{old}" "{current_exe}" >nul & echo 교체 실패 & pause & exit /b 1)\r\n'
        f'start "" "{current_exe}"\r\n'
        f'del /f /q "{old}" >nul 2>&1\r\n'
        'del /f /q "%~f0" >nul 2>&1\r\n'
    )


def apply_update(new_file: Path, platform: str = sys.platform) -> str:
    """새 파일을 설치 위치에 적용한다. 돌려주는 문자열은 사용자에게 보여 줄 안내.

    Windows: 교체 스크립트를 띄우고 호출자는 곧바로 앱을 종료해야 한다.
    macOS: dmg 를 열어 주고 사용자가 끌어다 놓는다.
    """
    if platform == "win32":
        if not is_frozen():
            raise UpdateError("개발 환경(소스 실행)에서는 자동 교체를 하지 않습니다. 받은 파일: " + str(new_file))
        exe = current_executable()
        pids = [os.getpid()]
        try:
            pids.append(os.getppid())  # PyInstaller onefile 은 부트로더(부모) + 본체(자식)
        except Exception:  # noqa: BLE001
            pass
        script = Path(tempfile.gettempdir()) / "excel-paster-update.cmd"
        script.write_text(windows_swap_script(exe, new_file, pids), encoding="cp949", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=flags, close_fds=True)  # noqa: S603
        return "새 버전으로 교체하기 위해 앱을 종료합니다. 잠시 뒤 자동으로 다시 실행됩니다."
    if platform == "darwin":
        subprocess.Popen(["open", str(new_file)])  # noqa: S603, S607
        return "디스크 이미지를 열었습니다. Excel Paster 를 Applications 폴더로 끌어다 놓아 교체하세요."
    return f"받은 파일: {new_file}"
