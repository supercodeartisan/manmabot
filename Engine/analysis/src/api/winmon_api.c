/* winmon_api.c — LCAPI 모듈 shim (UI 창 텍스트 모니터: 채팅/통보문 등). */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../winmon/winmon_930.c"
#undef main

const char *lcapi_mod_name    = "winmon";
const char *lcapi_mod_out     = "winmon_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "UI window text monitor (reads on-screen texts of chat / notification popups directly from widgets).";
