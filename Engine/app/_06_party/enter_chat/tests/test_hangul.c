/* ============================================================================
 * test_hangul.c - decomposition unit test (no keyboard input)
 * ========================================================================== */
#include <stdio.h>
#include <string.h>

#include "ec_internal.h"

static int check_keys(const char* label, const wchar_t* s, const char* expect)
{
    char keys[256];
    int n = 0;

    for (const wchar_t* p = s; *p; ++p) {
        int room = (int)sizeof(keys) - n - 1;
        if (room <= 0) break;
        n += ec_hangul_keys(*p, keys + n, room);
    }
    keys[n] = 0;

    if (strcmp(keys, expect) != 0) {
        printf("FAIL  %-14s -> %s (expected %s)\n", label, keys, expect);
        return 0;
    }
    printf("OK    %-14s -> %s\n", label, keys);
    return 1;
}

int main(void)
{
    int ok = 1;

    ok &= check_keys("annyeong", L"안녕하세요", "dkssudgktpdy");
    ok &= check_keys("ga", L"가", "rk");
    ok &= check_keys("gak", L"각", "rkr");
    ok &= check_keys("gakk", L"갂", "rkR");
    ok &= check_keys("gaps", L"값", "rkqt");
    ok &= check_keys("gwa", L"과", "rhk");
    ok &= check_keys("ui", L"의", "dml");
    ok &= check_keys("han", L"한", "gks");
    ok &= check_keys("geul", L"글", "rmf");
    ok &= check_keys("compat-ann", L"ㅇㅏㄴ", "dks");
    ok &= check_keys("compat-wa", L"ㅘ", "hk");
    ok &= check_keys("compat-bs", L"ㅄ", "qt");
    ok &= check_keys("compat-gs", L"ㄳ", "rt");
    ok &= check_keys("shift-jamo", L"ㅃㅆㅒㅖ", "QTOP");

    if (ec_hangul_keys(L'A', (char[8]){0}, 8) != 0) {
        printf("FAIL  non-Hangul A produced keys\n");
        ok = 0;
    } else {
        printf("OK    non-Hangul A -> 0\n");
    }

    if (!ec_is_hangul(L'안') || !ec_is_hangul(L'ㄱ') ||
        !ec_is_hangul(0x1100) || ec_is_hangul(L'A')) {
        printf("FAIL  ec_is_hangul range check\n");
        ok = 0;
    } else {
        printf("OK    ec_is_hangul ranges\n");
    }

    if (!ok) {
        printf("TEST_FAILED\n");
        return 1;
    }
    printf("TEST_OK\n");
    return 0;
}
