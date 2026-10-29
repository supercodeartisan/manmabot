/* realtime_party_api.c — LCAPI 모듈 shim (원천 재사용). lparty.h 는 /Isrc\party 필요. */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../realtime_party/realtime_party_1009.c"
#undef main

const char *lcapi_mod_name    = "realtime_party";
const char *lcapi_mod_out     = "realtime_party_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Realtime party snapshot + driver call/time stats.";
