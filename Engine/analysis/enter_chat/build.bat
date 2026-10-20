@echo off
setlocal
cd /d "%~dp0"

call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if not exist bin mkdir bin

echo [1/4] enter_chat.dll
cl /nologo /O2 /W3 /MT /utf-8 /D_CRT_SECURE_NO_WARNINGS /DENTER_CHAT_EXPORTS /Iinclude /Isrc ^
   src\enter_chat.c src\ec_target.c src\ec_keyboard.c src\ec_hangul.c src\ec_text.c ^
   /Fe:bin\enter_chat.dll /LD /link /IMPLIB:bin\enter_chat.lib ^
   user32.lib imm32.lib winmm.lib advapi32.lib
if errorlevel 1 exit /b 1

echo [2/4] enter_chat_cli.exe (asInvoker)
cl /nologo /O2 /W3 /MT /utf-8 /D_CRT_SECURE_NO_WARNINGS /Iinclude ^
   cli\enter_chat_cli.c /Fe:bin\enter_chat_cli.exe ^
   /link bin\enter_chat.lib user32.lib /MANIFEST:EMBED ^
   /MANIFESTUAC:"level='asInvoker' uiAccess='false'"
if errorlevel 1 exit /b 1

echo [3/4] enter_chat_cli_admin.exe (requireAdministrator)
cl /nologo /O2 /W3 /MT /utf-8 /D_CRT_SECURE_NO_WARNINGS /Iinclude ^
   cli\enter_chat_cli.c /Fe:bin\enter_chat_cli_admin.exe ^
   /link bin\enter_chat.lib user32.lib /MANIFEST:EMBED ^
   /MANIFESTUAC:"level='requireAdministrator' uiAccess='false'"
if errorlevel 1 exit /b 1

echo [4/4] test_hangul.exe
cl /nologo /O2 /W3 /MT /utf-8 /D_CRT_SECURE_NO_WARNINGS /DEC_TEST /DENTER_CHAT_STATIC /Iinclude /Isrc ^
   tests\test_hangul.c src\ec_hangul.c /Fe:bin\test_hangul.exe
if errorlevel 1 exit /b 1

if exist "..\..\autologin\bot\win\interception.dll" copy /Y "..\..\autologin\bot\win\interception.dll" "bin\interception.dll" >nul

echo.
bin\test_hangul.exe
if errorlevel 1 exit /b 1

del /q *.obj 2>nul
del /q bin\*.exp 2>nul

echo.
echo BUILD_OK
