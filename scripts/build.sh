#!/usr/bin/env bash
# macOS / Linux 로컬 빌드. 결과: dist/PDF Masker.app, dist/Excel Paster.app (mac) 또는 dist/<이름> (linux)
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install -q -r requirements.txt pyinstaller pillow
if [[ "$(uname)" == "Darwin" ]]; then
  python scripts/make_icns.py masker
  python scripts/make_icns.py excelpaster
fi
pyinstaller --noconfirm --clean pdfmasker.spec
pyinstaller --noconfirm --clean excelpaster.spec
echo "빌드 완료: dist/"
