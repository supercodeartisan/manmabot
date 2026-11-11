@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
cl /utf-8 lcapi_host_test.c /O2 /GS- /Fe:lcapi_host_test.exe /I..\core /D_CRT_SECURE_NO_WARNINGS /nologo
