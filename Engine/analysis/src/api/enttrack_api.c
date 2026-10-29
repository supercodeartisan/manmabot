/* enttrack_api.c — LCAPI 모듈 shim. 원천(enttrack_930.c)을 그대로 재사용하고
 * main 만 lcapi_mod_main 으로 리네임한다. 로직 복제 없음. */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../enttrack/enttrack_930.c"
#undef main

const char *lcapi_mod_name    = "enttrack";
const char *lcapi_mod_out     = "enttrack_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Entity snapshot stream (cell/iso/screen coords, attack owner/target, items) as JSON.";
