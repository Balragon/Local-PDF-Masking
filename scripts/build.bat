@echo off
REM Windows 로컬 빌드. 결과: dist\PDF Masker.exe, dist\Excel Paster.exe
cd /d "%~dp0\.."
py -3 -m venv .venv-build || python -m venv .venv-build
call .venv-build\Scripts\activate.bat
pip install -q -r requirements.txt pyinstaller pillow
pyinstaller --noconfirm --clean pdfmasker.spec
pyinstaller --noconfirm --clean excelpaster.spec
echo 빌드 완료: dist\
