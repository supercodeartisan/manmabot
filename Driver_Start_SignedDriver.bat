@echo off
cd /d "%~dp0"
REM Driver — start WinNotify / signeddrv (admin)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0Drivers\SignedDriver\load_signeddrv.ps1\" -Action start' -Verb RunAs"
