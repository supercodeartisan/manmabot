/* storewin_api.c — LCAPI 모듈 shim (창고 창 상태/표시목록 읽기 독립 모듈). */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../storewin/storewin_930.c"
#undef main

const char *lcapi_mod_name    = "storewin";
const char *lcapi_mod_out     = "storewin_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Storage window state + on-screen list (reads the window's ListSlot texts directly; independent of uidialogmon).";
