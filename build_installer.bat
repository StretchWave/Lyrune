@echo off
REM ============================================================
REM  Lyrune Windows Installer Build Script
REM  Builds the PyInstaller distribution and Inno Setup installer.
REM
REM  Prerequisites:
REM    - Python 3.10+ with pip
REM    - PyInstaller:  pip install pyinstaller
REM    - Pillow:       pip install Pillow
REM    - Inno Setup:   https://jrsoftware.org/isdl.php
REM      (iscc.exe must be in PATH, or edit ISCC_PATH below)
REM ============================================================

setlocal

REM --- Configuration ---
set ISCC_PATH=iscc
set SPEC_FILE=Lyrune.spec
set ISS_FILE=installer.iss

echo.
echo ========================================
echo  Step 1: Generate logo.ico from logo.png
echo ========================================
python -c "from PIL import Image; img = Image.open('assets/logo.png'); img.save('assets/logo.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to generate logo.ico. Make sure Pillow is installed: pip install Pillow
    exit /b 1
)
echo [OK] assets/logo.ico generated.

echo.
echo ========================================
echo  Step 2: Build with PyInstaller
echo ========================================
pyinstaller --clean --noconfirm %SPEC_FILE%
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)
echo [OK] PyInstaller build complete.

echo.
echo ========================================
echo  Step 3: Compile Inno Setup Installer
echo ========================================
%ISCC_PATH% %ISS_FILE%
if %errorlevel% neq 0 (
    echo [ERROR] Inno Setup compilation failed. Make sure iscc.exe is in your PATH.
    echo         Download Inno Setup from: https://jrsoftware.org/isdl.php
    exit /b 1
)
echo [OK] Installer compiled successfully.

echo.
echo ========================================
echo  BUILD COMPLETE
echo ========================================
echo  Output:
echo    dist\Lyrune\              (PyInstaller directory build)
echo    dist\Lyrune-Setup-v2.0.0.exe  (Windows installer)
echo ========================================

endlocal
