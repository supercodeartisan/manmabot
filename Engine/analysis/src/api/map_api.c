/* map_api.c — LCAPI 모듈 shim (원천 재사용). */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../map/map_930.c"
#undef main

const char *lcapi_mod_name    = "map";
const char *lcapi_mod_out     = "map_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Current map id / player cell / region / sub-region.";
