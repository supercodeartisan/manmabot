/* lasthit_api.c — LCAPI 모듈 shim (원천 재사용).
 *  주의: lasthit 원천은 argv[1] 을 secs 로만 해석하므로 인자는 %S 만 준다.
 *  registry 는 원천이 호스트 EXE 기준으로 자동 탐색한다. */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../lasthit/lasthit_930.c"
#undef main

const char *lcapi_mod_name    = "lasthit";
const char *lcapi_mod_out     = "lasthit_out.txt";
const char *lcapi_mod_args    = "%S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Ground-item loot attribution events (ITEM/DEATH/GONE/RELABEL MINE|OTHER|UNKNOWN).";
