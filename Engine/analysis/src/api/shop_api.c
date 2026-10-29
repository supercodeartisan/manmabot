/* shop_api.c — LCAPI 모듈 shim (원천 재사용). */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../shop/shop_930.c"
#undef main

const char *lcapi_mod_name    = "shop";
const char *lcapi_mod_out     = "shop_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Shop buy/sell lists (order / item id / template / price / name).";
