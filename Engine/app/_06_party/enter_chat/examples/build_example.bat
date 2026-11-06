@echo off
setlocal
cd /d "%~dp0"

call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul

cl /nologo /O2 /W3 /MT /utf-8 /D_CRT_SECURE_NO_WARNINGS /I..\include ^
   call_enter_chat.c /Fe:..\bin\example_call.exe ^
   /link ..\bin\enter_chat.lib user32.lib
if errorlevel 1 exit /b 1

del /q call_enter_chat.obj 2>nul
echo EXAMPLE_BUILD_OK
