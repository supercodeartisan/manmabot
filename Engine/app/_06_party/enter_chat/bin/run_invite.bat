@echo off
cd /d "e:\10_17\ManmabotV1_final_final_final\Engine\app\_06_party\enter_chat\bin"
enter_chat_cli_admin.exe --pid 6020 --file invite_line.txt --cps 9 --jitter 35 --open --enter --json > invite_out.txt 2>&1
echo EXIT=%ERRORLEVEL%>> invite_out.txt
