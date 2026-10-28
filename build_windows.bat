@echo off
chcp 65001 >nul
REM ===================================================================
REM  StrCAD suite (launcher + modules) - build Windows installer
REM  Needs: Python 3.11/3.12, Inno Setup 6 (https://jrsoftware.org/isdl.php)
REM  Usage: build_windows.bat 1.0.0   ->  dist\StrCAD_Setup_1.0.0.exe
REM ===================================================================
setlocal
cd /d "%~dp0"
set VER=%1
if "%VER%"=="" set VER=1.0.0

echo [1/4] pip install
python -m pip install --upgrade pip >nul
python -m pip install ezdxf pillow tkinterdnd2 openpyxl numpy opencv-python-headless rapidocr_onnxruntime python-docx olefile pywin32 pyinstaller || goto :err

echo [2/4] PyInstaller
python -m PyInstaller launcher.py --noconfirm --clean --windowed --name StrCAD ^
  --icon strcad_cad_analysis\cad_analysis\assets\icon.ico ^
  --paths strcad_cad_analysis --paths report_design ^
  --add-data "strcad_cad_analysis\cad_analysis\assets;cad_analysis\assets" ^
  --add-data "strcad_cad_analysis\mobile;mobile" ^
  --add-data "strcad_cad_analysis\samples;samples" ^
  --add-data "autotable\auto_table.py;autotable" ^
  --hidden-import cad_analysis.app --hidden-import cad_analysis.licensing_ui --hidden-import design_2d ^
  --hidden-import cad_analysis.photo_plan --hidden-import cad_analysis.sheets ^
  --hidden-import report_assistant --hidden-import report_core --hidden-import hwp_reader --hidden-import docx_doc ^
  --hidden-import olefile --hidden-import win32com.client --hidden-import pythoncom ^
  --collect-all tkinterdnd2 --collect-all ezdxf --collect-all docx --collect-all rapidocr_onnxruntime --collect-all onnxruntime ^
  --exclude-module matplotlib --exclude-module PyQt5 --exclude-module PySide6 || goto :err

echo [3/4] self test
dist\StrCAD\StrCAD.exe --selftest "%CD%\selftest.txt"
type selftest.txt
findstr /c:"FAIL" /c:"MISSING" selftest.txt >nul && goto :err

echo [4/4] Inno Setup
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (echo Inno Setup 6 not found. Install from https://jrsoftware.org/isdl.php & goto :err)
echo #define AppVersion "%VER%"> installer\version.iss
pushd installer
%ISCC% strcad_suite.iss || (popd & goto :err)
popd
echo.
echo DONE: dist\StrCAD_Setup_%VER%.exe
exit /b 0

:err
echo.
echo *** FAILED - see messages above ***
exit /b 1
