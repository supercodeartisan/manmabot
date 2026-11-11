@echo off
REM verify.bat - offline config check + optional live LCAPI smoke test.
REM   config check needs only python; host test needs LC.exe + signeddrv running.
cd /d "%~dp0.."
if not exist _build\check_configs.py (
  echo [skip] _build\check_configs.py not found
) else (
  python _build\check_configs.py || exit /b 1
)
if not exist _build\lcapi_host_test.exe (
  echo [skip] lcapi_host_test.exe not built - run _build\build_host.bat first
  echo VERIFY OK ^(config only^)
  exit /b 0
)
echo -- live party smoke --
_build\lcapi_host_test.exe dll\party.dll registry\LC930_REGISTRY.txt 2 || exit /b 1
echo -- live partyhud smoke --
_build\lcapi_host_test.exe dll\partyhud.dll registry\LC930_REGISTRY.txt 2 || exit /b 1
echo VERIFY OK
