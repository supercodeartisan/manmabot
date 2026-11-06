/* party_api.c — LCAPI 모듈 shim (원천 재사용). lparty.h 는 /Isrc\party 필요. */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../party/party_1009.c"
#undef main

const char *lcapi_mod_name    = "party";
const char *lcapi_mod_out     = "party_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    = "Party members (leader / name / GUID / class / HP% / MP% / position / level / dead).";
