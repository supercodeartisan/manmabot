/* Korean item names from item_name_kr.csv (ID,EP,TYPE,KR,...).
   desc* / string* / empty KR cells are not names. */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "item_name_kr.h"

#define ITEM_NAME_MAX_ID 20000
#define ITEM_NAME_ARENA  (512 * 1024)

static char s_arena[ITEM_NAME_ARENA];
static uint32_t s_used = 1;
static uint32_t s_at[ITEM_NAME_MAX_ID];
static int s_ready = 0;

const char* itemNameKr(uint32_t id) {
    uint32_t at;
    if (!id || id >= ITEM_NAME_MAX_ID) return 0;
    at = s_at[id];
    return at ? s_arena + at : 0;
}

static int csvField(const char* s, int want, char* out, int cap) {
    int col = 0;
    out[0] = 0;
    while (*s && col <= want) {
        int inq = 0, o = 0;
        if (*s == '"') { inq = 1; s++; }
        while (*s) {
            if (inq) {
                if (*s == '"') { s++; break; }
                if (col == want && o + 1 < cap) out[o++] = *s;
                s++;
            } else {
                if (*s == ',') break;
                if (col == want && o + 1 < cap) out[o++] = *s;
                s++;
            }
        }
        if (col == want) { out[o] = 0; return 1; }
        if (*s == ',') s++;
        col++;
    }
    return 0;
}

static int rejected(const char* kr) {
    return !kr[0] || strncmp(kr, "desc", 4) == 0 || strncmp(kr, "string", 6) == 0;
}

static int loadFile(const char* path) {
    FILE* f;
    char line[4096], idb[32], kr[160];
    int n = 0;
    f = fopen(path, "rb");
    if (!f) return 0;
    if (!fgets(line, sizeof(line), f)) { fclose(f); return 0; }
    while (fgets(line, sizeof(line), f)) {
        unsigned id;
        char* nl = strchr(line, '\n');
        if (nl) *nl = 0;
        nl = strchr(line, '\r');
        if (nl) *nl = 0;
        if (!csvField(line, 0, idb, (int)sizeof(idb))) continue;
        if (!csvField(line, 3, kr, (int)sizeof(kr))) continue;
        id = (unsigned)strtoul(idb, 0, 10);
        if (!id || id >= ITEM_NAME_MAX_ID || s_at[id] || rejected(kr)) continue;
        if (s_used + strlen(kr) + 1 >= ITEM_NAME_ARENA) break;
        memcpy(s_arena + s_used, kr, strlen(kr) + 1);
        s_at[id] = s_used;
        s_used += (uint32_t)strlen(kr) + 1;
        n++;
    }
    fclose(f);
    return n;
}

static void sibling(const char* src, const char* name, char* out, int cap) {
    const char* slash;
    int n;
    out[0] = 0;
    if (!src || !src[0]) {
        strncpy(out, name, (size_t)cap - 1);
        out[cap - 1] = 0;
        return;
    }
    slash = strrchr(src, '\\');
    if (!slash) slash = strrchr(src, '/');
    if (!slash) {
        strncpy(out, name, (size_t)cap - 1);
        out[cap - 1] = 0;
        return;
    }
    n = (int)(slash - src + 1);
    if (n >= cap) n = cap - 1;
    memcpy(out, src, (size_t)n);
    out[n] = 0;
    strncat(out, name, (size_t)cap - strlen(out) - 1);
}

void itemNameKrLoadNear(const char* anchorPath) {
    char path[520];
    if (s_ready) return;
    s_ready = 1;
    sibling(anchorPath, "..\\data\\item_name_kr.csv", path, (int)sizeof(path));
    if (loadFile(path)) return;
    sibling(anchorPath, "data\\item_name_kr.csv", path, (int)sizeof(path));
    if (loadFile(path)) return;
    loadFile("data\\item_name_kr.csv");
}
