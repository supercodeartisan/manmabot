@echo off
cd /d "%~dp0.."
REM Seller bundle: this folder (tool) + Seller\SellerData (vault). Never ship to customers.
set "PYTHONPATH=%CD%\Engine;%CD%\UI"
set "MANMABOT_SELLER_DATA=%CD%\Seller\SellerData"

if defined MANMABOT_BUILD_PYTHON (
  "%MANMABOT_BUILD_PYTHON%" "%CD%\Seller\seller_license_gui.py"
  goto :eof
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python "%CD%\Seller\seller_license_gui.py"
  goto :eof
)

if exist "%CD%\python\python.exe" (
  "%CD%\python\python.exe" "%CD%\Seller\seller_license_gui.py"
  goto :eof
)

echo Python not found. Install CPython 3.14 or set MANMABOT_BUILD_PYTHON.
pause
