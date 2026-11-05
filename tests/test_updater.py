from pathlib import Path

from excelpaster import updater
from excelpaster._version import __version__
from excelpaster.updater import (
    Release,
    is_newer,
    parse_checksums,
    parse_release,
    parse_version,
    windows_swap_script,
)


def test_version_parse_and_compare():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.10") == (1, 10)
    assert parse_version("junk") == (0,)
    assert is_newer("v1.0.1", "1.0.0")
    assert is_newer("v2", "1.9.9")
    assert not is_newer("v1.0.0", "1.0.0")
    assert not is_newer("v0.9", "1.0.0")
    assert not is_newer("1.0", "1.0.0")
    assert parse_version(__version__) >= (1, 0, 0)


def test_parse_release_and_assets():
    payload = {
        "tag_name": "v1.2.0",
        "html_url": "https://github.com/x/y/releases/tag/v1.2.0",
        "body": "notes",
        "assets": [
            {"name": "Excel-Paster-windows.exe", "browser_download_url": "https://dl/win.exe"},
            {"name": "Excel-Paster-macos-arm64.dmg", "browser_download_url": "https://dl/mac.dmg"},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://dl/sums"},
            {"name": "PDF-Masker-windows.exe", "browser_download_url": "https://dl/pdf.exe"},
        ],
    }
    rel = parse_release(payload)
    assert rel.version == "1.2.0" and rel.tag == "v1.2.0" and rel.notes == "notes"
    assert rel.asset_url("win32") == "https://dl/win.exe"
    assert rel.asset_url("darwin") == "https://dl/mac.dmg"
    assert rel.asset_url("linux") is None
    assert rel.checksums_url == "https://dl/sums"
    assert Release(version="1", tag="v1", page_url="u").asset_url("win32") is None


def test_parse_checksums():
    text = ("96bda7c5148b0e76b1fc6ddbdf5b09d79e8f25018835e6c2ed9aa66cc3a1d8e3  Excel-Paster-windows.exe\n"
            "55F7CD964E08399281EAB8F919DB24A47CB8E323C48CCC6CFC0DDFE2AE2D01B3 *PDF-Masker-windows.exe\n"
            "not a checksum line\n")
    sums = parse_checksums(text)
    assert sums["Excel-Paster-windows.exe"].startswith("96bda7c5")
    assert sums["PDF-Masker-windows.exe"].startswith("55f7cd96")
    assert len(sums) == 2


def test_sha256_of(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    assert updater.sha256_of(f) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_windows_swap_script_waits_and_swaps():
    script = windows_swap_script(Path(r"C:\Apps\Excel Paster.exe"), Path(r"C:\Temp\new.exe"), [123, 456])
    assert "PID eq 123" in script and "PID eq 456" in script
    assert 'move /y "C:\\Apps\\Excel Paster.exe" "C:\\Apps\\Excel Paster.exe.old"' in script
    assert 'move /y "C:\\Temp\\new.exe" "C:\\Apps\\Excel Paster.exe"' in script
    assert 'start "" "C:\\Apps\\Excel Paster.exe"' in script
    assert script.endswith('del /f /q "%~f0" >nul 2>&1\r\n')
