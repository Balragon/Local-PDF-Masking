#!/usr/bin/env bash
# macOS / Linux 로컬 빌드. 결과: dist/PDF Masker.app (mac) 또는 dist/PDF Masker (linux)
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install -q -r requirements.txt pyinstaller pillow
if [[ "$(uname)" == "Darwin" ]]; then
  python scripts/make_icns.py
fi
pyinstaller --noconfirm --clean pdfmasker.spec
echo "빌드 완료: dist/"
