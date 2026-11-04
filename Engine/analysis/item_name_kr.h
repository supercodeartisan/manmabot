#ifndef ITEM_NAME_KR_H
#define ITEM_NAME_KR_H
#include <stdint.h>

/* item_name_kr.csv KR column, keyed by the $mid in an item format string.
   A missing file leaves every lookup empty so the memory string is kept. */
void itemNameKrLoadNear(const char* anchorPath);
const char* itemNameKr(uint32_t id);

#endif
