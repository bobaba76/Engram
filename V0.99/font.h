#include "global.h"
#ifndef FONT_H
#define FONT_H

#define FONT_OFFS          0x00 // 0x20    // initial offset
#define FONT_LINE_HEIGHT ((FONT_HEIGHT) + FONT_LINE_SPACE)

#ifndef FONT_C

extern const word FONT_TABLE_START;
extern const word FONT_TABLE_END;

extern const byte Font[96][FONT_HEIGHT];

//// Sanity checks
//#if (((FONT_LINE_HEIGHT) * (TEXT_LINES)) + (PAL_ODD_TEXT_START)) > ((PAL_ODD_VIDEO_END) - 10u)
//#error Text exceeds screen height
//#endif

#endif

#endif
