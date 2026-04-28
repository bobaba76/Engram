#ifndef VIDOE_LINE_H
#define VIDEO_LINE_H

#define PAL_LINE_TIME            64e-6F
#define PAL_LINE_CYCLES          ((int16)((PAL_LINE_TIME)/(TCYC)))

#define NTSC_LINE_TIME           63.5558e-6F
#define NTSC_LINE_CYCLES         ((word)((NTSC_LINE_TIME)/(TCYC)))

// Used for both PAL & NTSC (does not have to be exact).
#define LINE_3QUARTER_CYCLES ((int16)(((PAL_LINE_TIME)*0.75F)/(TCYC)))
#define LINE_1QUARTER_CYCLES ((int16)(((PAL_LINE_TIME)*0.25F)/(TCYC)))

#define PAL_ODD_TEXT_START_LINE    33u  // TODO: Determine - just a guess for now
#define PAL_ODD_TEXT_END_LINE      (PAL_ODD_TEXT_START_LINE +  (TEXT_LINES * (((FONT_LINE_HEIGHT)) + 1)))
#define PAL_EVEN_TEXT_START_LINE   (PAL_ODD_TEXT_START_LINE + 313u)
#define PAL_EVEN_TEXT_END_LINE     (PAL_EVEN_TEXT_START_LINE + (TEXT_LINES * (((FONT_LINE_HEIGHT)) + 1)))
   
#define NTSC_ODD_TEXT_START_LINE      28u  // TODO: Determine - just a guess for now
#define NTSC_ODD_TEXT_END_LINE     (NTSC_ODD_TEXT_START_LINE +  (TEXT_LINES * (((FONT_LINE_HEIGHT)) + 1)))
#define NTSC_EVEN_TEXT_START_LINE  (NTSC_ODD_TEXT_START_LINE + 263u)
#define NTSC_EVEN_TEXT_END_LINE    (NTSC_EVEN_TEXT_START_LINE + (TEXT_LINES * (((FONT_LINE_HEIGHT)) + 1)))
 
#define PAL_LINES                   625         // LINE 625
#define PAL_ODD_SYNC_START          1           // Line 1
#define PAL_ODD_LINE_START          5           // END OF LINE 5.
#define PAL_ODD_VIDEO_START         6
#define PAL_ODD_TEXT_START          PAL_ODD_TEXT_START_LINE
#define PAL_ODD_TEXT_END            PAL_ODD_TEXT_END_LINE
#define PAL_ODD_VIDEO_END           305
#define PAL_EVEN_SYNC_START         313
#define PAL_EVEN_LINE_START         318         // END OF LINE 318
#define PAL_EVEN_VIDEO_START        320
#define PAL_EVEN_TEXT_START         PAL_EVEN_TEXT_START_LINE
#define PAL_EVEN_TEXT_END           PAL_EVEN_TEXT_END_LINE
#define PAL_EVEN_VIDEO_END          618

#define NTSC_LINES                  525          // Line 525
#define NTSC_ODD_SYNC_START         1            // Line 1
#define NTSC_ODD_LINE_START         6            // End of line 6.
#define NTSC_ODD_VIDEO_START        16
#define NTSC_ODD_TEXT_START         NTSC_ODD_TEXT_START_LINE
#define NTSC_ODD_TEXT_END           NTSC_ODD_TEXT_END_LINE
#define NTSC_ODD_VIDEO_END          255 
#define NTSC_EVEN_SYNC_START        263
#define NTSC_EVEN_LINE_START        268          // End of line 268
#define NTSC_EVEN_VIDEO_START       278 
#define NTSC_EVEN_TEXT_START        NTSC_EVEN_TEXT_START_LINE
#define NTSC_EVEN_TEXT_END          NTSC_EVEN_TEXT_END_LINE
#define NTSC_EVEN_VIDEO_END         522

extern int16 ScopeTriggerLineNo; // When LineCntr == ScopeTrigger, set LATB10 high one line
extern int16 VideoLineCount;     // Used to detect NTSC / PAL (LineCntr can't be used, wraps at max line)

#endif
