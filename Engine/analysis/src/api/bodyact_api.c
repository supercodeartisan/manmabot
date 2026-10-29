/* bodyact_api.c — LCAPI 모듈 shim (원천 재사용). */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../bodyact/bodyact_930.c"
#undef main

const char *lcapi_mod_name    = "bodyact";
const char *lcapi_mod_out     = "bodyact_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Player body action + command (stand/walk/attack/spell/turn ...).";
