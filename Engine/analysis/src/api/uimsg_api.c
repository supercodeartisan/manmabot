/* uimsg_api.c — LCAPI module shim for CommonMessageSubsystem (UIMessage).
 *
 * Build: analysis/build_bot_modules.bat (includes uimsg).
 * Host:  LoadLibrary(dll/uimsg.dll) → lcapi_configure → lcapi_run(sink).
 * Source: probes/uimsg_1021.c (EXE and DLL share the same probe).
 */
#define LCAPI_INPROC 1
#define main lcapi_mod_main
#include "../../probes/uimsg_1021.c"
#undef main

const char *lcapi_mod_name    = "uimsg";
const char *lcapi_mod_out     = "uimsg_out.txt";
const char *lcapi_mod_args    = "%R %S";
const char *lcapi_mod_version = "1.0.0";
const char *lcapi_mod_info    =
    "UIMessage / CommonMessageSubsystem popup text "
    "(disconnect + operator policy; UTF-8).";
