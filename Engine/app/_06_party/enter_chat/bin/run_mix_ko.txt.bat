@echo off
cd /d "e:\10_17\ManmabotV1_final_final_final\Engine\app\_06_party\enter_chat\bin"
enter_chat_cli_admin.exe --pid 6020 --file mix_ko.txt --cps 9 --jitter 35 --open --enter --json > mix_ko.txt.out 2>&1
echo EXIT=%ERRORLEVEL%>> mix_ko.txt.out
