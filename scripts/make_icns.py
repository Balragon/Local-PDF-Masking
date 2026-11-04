"""icon.png -> icon.icns (macOS 전용, iconutil 사용)."""
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

assets = Path(__file__).resolve().parent.parent / "masker" / "assets"
src = assets / "icon.png"
iconset = assets / "icon.iconset"
if iconset.exists():
    shutil.rmtree(iconset)
iconset.mkdir()
im = Image.open(src)
for size in (16, 32, 64, 128, 256, 512):
    im.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
    im.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(assets / "icon.icns")], check=True)
shutil.rmtree(iconset)
print("icon.icns written", file=sys.stderr)
