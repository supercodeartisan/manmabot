/* partyhud_api.c — LCAPI shim. Party HUD list-row boxes. */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../partyhud/partyhud_930.c"
#undef main

const char *lcapi_mod_name    = "partyhud";
const char *lcapi_mod_out     = "partyhud_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Party HUD member rows (guid / HP% / MP% / client-pixel box).";
