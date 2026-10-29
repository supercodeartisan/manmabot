/* realtime_buff_api.c — LCAPI 모듈 shim (원천 재사용). */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../realtime_buff/realtime_buff_930.c"
#undef main

const char *lcapi_mod_name    = "realtime_buff";
const char *lcapi_mod_out     = "realtime_buff_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Realtime buff snapshot line ([BUFF] t/n/ioctl/time | name(remain) ...).";
