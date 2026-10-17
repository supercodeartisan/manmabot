@echo off
REM Install Interception into THIS Windows (%%SystemRoot%%\System32\drivers).
REM The official 32-bit installer often fails with "Could not write to \system32\drivers"
REM on 64-bit Windows. This bat prepares those write paths, then copies bundled
REM drivers and writes the filter registry if the official exe still fails.
setlocal EnableExtensions
cd /d "%~dp0"
set "NOPAUSE="
if /i "%~1"=="nopause" set "NOPAUSE=1"

net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  exit /b
)

echo Windows system root: %SystemRoot%
echo Driver folder:       %SystemRoot%\System32\drivers
echo.

set "DRIVERS=%SystemRoot%\System32\drivers"
if not exist "%DRIVERS%\" (
  echo FAILED: driver folder does not exist: %DRIVERS%
  echo This PC's Windows is not where you expected.
  goto :endfail
)

REM 32-bit installer may write through Wow64 to SysWOW64\drivers.
if exist "%SystemRoot%\SysWOW64" (
  if not exist "%SystemRoot%\SysWOW64\drivers" (
    mkdir "%SystemRoot%\SysWOW64\drivers" 2>nul
    echo Created %SystemRoot%\SysWOW64\drivers
  )
)

REM Official exe prints \system32\drivers and may use ^<drive^>\system32\drivers.
call :ensure_junction "%SystemDrive%\system32\drivers"
if /i not "%~d0"=="%SystemDrive%" call :ensure_junction "%~d0\system32\drivers"

set "PROBE=%DRIVERS%\.manmabot_write_probe"
echo. > "%PROBE%" 2>nul
if not exist "%PROBE%" (
  echo FAILED: cannot write to %DRIVERS%
  echo Right-click this bat - Run as administrator.
  echo Close antivirus / Controlled Folder Access if they block driver writes.
  goto :endfail
)
del /f /q "%PROBE%" >nul 2>&1

set "INST=%~dp0Interception\command line installer\install-interception.exe"
set "RC=1"
if exist "%INST%" (
  echo Running official installer...
  pushd "%~dp0Interception\command line installer"
  "%INST%" /install
  set "RC=%errorlevel%"
  popd
  echo Official installer exit: %RC%
) else (
  echo Official installer missing, using bundled drivers.
)
echo.

if exist "%SystemRoot%\SysWOW64\drivers\keyboard.sys" copy /y "%SystemRoot%\SysWOW64\drivers\keyboard.sys" "%DRIVERS%\keyboard.sys" >nul 2>&1
if exist "%SystemRoot%\SysWOW64\drivers\mouse.sys" copy /y "%SystemRoot%\SysWOW64\drivers\mouse.sys" "%DRIVERS%\mouse.sys" >nul 2>&1

set "ARCH=x86"
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" set "ARCH=amd64"
if /i "%PROCESSOR_ARCHITEW6432%"=="AMD64" set "ARCH=amd64"
set "BUNDLED=%~dp0Interception\drivers\%ARCH%"

if not exist "%DRIVERS%\keyboard.sys" goto :fallback
if not exist "%DRIVERS%\mouse.sys" goto :fallback
goto :registry

:fallback
echo Official copy did not place the drivers. Installing bundled %ARCH% files...
if not exist "%BUNDLED%\keyboard.sys" (
  echo FAILED: missing %BUNDLED%\keyboard.sys
  goto :endfail
)
if not exist "%BUNDLED%\mouse.sys" (
  echo FAILED: missing %BUNDLED%\mouse.sys
  goto :endfail
)
call :force_copy "%BUNDLED%\keyboard.sys" "%DRIVERS%\keyboard.sys"
if errorlevel 1 goto :endfail
call :force_copy "%BUNDLED%\mouse.sys" "%DRIVERS%\mouse.sys"
if errorlevel 1 goto :endfail

:registry
echo Writing filter registry...
reg add "HKLM\SYSTEM\CurrentControlSet\Services\keyboard" /v DisplayName /t REG_SZ /d "Keyboard Upper Filter Driver" /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\keyboard" /v Type /t REG_DWORD /d 1 /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\keyboard" /v ErrorControl /t REG_DWORD /d 1 /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\keyboard" /v Start /t REG_DWORD /d 3 /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\keyboard" /v ImagePath /t REG_EXPAND_SZ /d "\SystemRoot\System32\drivers\keyboard.sys" /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\mouse" /v DisplayName /t REG_SZ /d "Mouse Upper Filter Driver" /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\mouse" /v Type /t REG_DWORD /d 1 /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\mouse" /v ErrorControl /t REG_DWORD /d 1 /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\mouse" /v Start /t REG_DWORD /d 3 /f >nul
reg add "HKLM\SYSTEM\CurrentControlSet\Services\mouse" /v ImagePath /t REG_EXPAND_SZ /d "\SystemRoot\System32\drivers\mouse.sys" /f >nul

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Interception\register_filters.ps1"
if errorlevel 1 (
  echo FAILED: could not write UpperFilters registry
  goto :endfail
)

if not exist "%DRIVERS%\keyboard.sys" goto :endfail
if not exist "%DRIVERS%\mouse.sys" goto :endfail

echo.
echo SUCCESS. keyboard.sys and mouse.sys are in:
echo   %DRIVERS%
echo Reboot Windows before using the bot.
if not defined NOPAUSE pause
endlocal
exit /b 0

:endfail
echo.
echo FAILED. Driver files were not installed.
echo Close antivirus / Controlled Folder Access if they block .sys writes.
if not defined NOPAUSE pause
endlocal
exit /b 1

:ensure_junction
set "JDIR=%~1"
if exist "%JDIR%\" exit /b 0
for %%I in ("%JDIR%") do set "JPARENT=%%~dpI"
if not exist "%JPARENT%" mkdir "%JPARENT%" 2>nul
mklink /J "%JDIR%" "%DRIVERS%" >nul 2>&1
if exist "%JDIR%\" echo Linked %JDIR% -^> %DRIVERS%
exit /b 0

:force_copy
set "SRCFILE=%~1"
set "DSTFILE=%~2"
if exist "%DSTFILE%" (
  takeown /f "%DSTFILE%" >nul 2>&1
  icacls "%DSTFILE%" /grant Administrators:F >nul 2>&1
)
copy /y "%SRCFILE%" "%DSTFILE%" >nul
if exist "%DSTFILE%" (
  echo Copied %~nx2
  exit /b 0
)
echo FAILED: copy %SRCFILE% -^> %DSTFILE%
exit /b 1
