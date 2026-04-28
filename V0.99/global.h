#ifndef GLOBAL_H
#define GLOBAL_H

#ifndef SYSDEFS_H
#include "sysdefs.h"
#endif

// Constants:
// ----------

#define FCYC                     ((uint32)(FOSC/2.0F))
#define TCYC                     ((float)(1.0F/(float)FCYC))

#define MAIN_LOOP_CYCLES         ((uint32)(((float)(MAIN_LOOP_MS) * 0.001F) / (TCYC)))
#define DC_CLAMP_CYCLES          ((word)(((TIME_BURST_END) - (TIME_BURST_START)) / (TCYC)))

#define CYCLE_BURST_START        ((word)(((TIME_BURST_START) - (COMPARATOR_LATENCY))/(TCYC)))
#define CYCLE_BURST_END          ((word)(((TIME_BURST_END) - (COMPARATOR_LATENCY))/(TCYC)))
#define CYCLE_VIDEO_START        ((word)(((TIME_VIDEO_START) - (COMPARATOR_LATENCY))/(TCYC)))
#define CYCLE_VIDEO_END          ((word)(((TIME_VIDEO_END) - (COMPARATOR_LATENCY))/(TCYC)))
#define CYCLE_TEXT_LEFT_ALIGN    ((word)(((TIME_TEXT_LEFT) - (COMPARATOR_LATENCY))/(TCYC)))
#define CYCLE_TEXT_RIGHT_ALIGN   ((word)(((TIME_TEXT_RIGHT) - (COMPARATOR_LATENCY))/(TCYC)))

#define TMR2_PERIOD        ((word)((61e-6F)/(TCYC)))
//#define TMR2_PERIOD        ((word)((CYCLE_VIDEO_END - CYCLE_VIDEO_START) / (T2_INTERRUPT_PER_LINE)))

#define ADC_BUF_SIZE    16

#define _T1ON  T1CONbits.TON
#define _T2ON  T1CONbits.TON
#define _T3ON  T1CONbits.TON
#define _SPI1ON SPI1STATbits.SPIEN
#define _SPI2ON SPI2STATbits.SPIEN

#define FLASH_BUFFER_SIZE (FLASH_BLOCK_SIZE * 3u)

#define STORED_SETTINGS_ADDRESS (SETTINGS_PAGE * FLASH_BLOCK_SIZE * 2)
#define OEM_SETTINGS_ADDRESS   (OEM_SETTINGS_PAGE * FLASH_BLOCK_SIZE * 2)
#define OEM_SETTINGS_STR_COUNT 9

#define _ISR_NO_PSV __attribute__((interrupt, no_auto_psv))

// Exported variables
// ------------------

#ifndef GLOBAL_C

// The following two buffers could be hidden in char_buffer.c, but we do not have enough RAM with
// the current dsPIC33FJ64GP204 to allow FlashWriteConst() to create a buffer on the stack. 
// Instead we map it to the POS_RxBuffer, and flush the buffer when done. If we declare one buffer
// here, we might as well declare all of them.
extern char MaintTxBuffer[MAINT_TX_BUFFER_SIZE];
extern char MaintRxBuffer[MAINT_RX_BUFFER_SIZE];
extern char POS_RxBuffer[POS_RX_BUFFER_SIZE];
extern byte *FlashBuffer;

extern word ADC1Buffer[ADC_BUF_SIZE] __attribute__((space(dma)));
extern byte SPI1TxBuf[TEXT_COLUMNS + 1] __attribute__((space(dma)));
extern byte SPI1RxBuf[1] __attribute__((space(dma)));
extern byte SPI2TxBuf[TEXT_COLUMNS + 1] __attribute__((space(dma)));
extern byte SPI2RxBuf[1] __attribute__((space(dma)));
     
extern word SPI_Prescaler;
extern word CyclesPerChar;          /* duration in processor cycles of 1 char (+ space) */
extern word FontCharSpace;          /* Space between chars */
extern word CyclesTimer2Preload;    /* Preload value for Timer2 at start of line */

extern word POS_LineTimeoutMS;      /* When NewLine = newlnTimeout, use this timeout */

extern byte TextSize;
extern byte TextBackgroundFill;
extern tOverlayAlignment OverlayAlignment;

extern int16 *pVRef1V7;
extern int16 *pSyncPk;
extern int16 *pSyncSlice;
extern int16 *pVideoIn;

extern int16 VideoWhiteLevel;

extern tVideoSystem VideoSystem;

extern bool fMenuIsActive;
extern bool fVideoPresent;
extern bool fLowVideo;

extern bool fStatusLineIsActive;
extern bool fFlashStatusLine;

extern tFilter SyncLevelFilter;

__psv__ extern const tStoredSettings STORED_SETTINGS;
__psv__ extern const tFlashChecksum FLASH_CHECKSUM;
__psv__ extern const tOEM_Settings DEFAULT_OEM_SETTINGS;
__psv__ extern const tStored_OEM_Settings STORED_OEM_SETTINGS;
__psv__ extern const tSettings DEFAULT_SETTINGS;
__psv__ extern const char VIDEO_SYSTEM_STR[vidMAX][8];
__psv__ extern const char OEM_TITLE_STR[OEM_SETTINGS_STR_COUNT][20];
extern const char *OEM_STRING_INDEX[OEM_SETTINGS_STR_COUNT];
__psv__ extern const word OEM_MODIFIABLE;
__psv__ extern const word VENDOR_MODIFIABLE;
__psv__ extern const word USER_MODIFIABLE;
__psv__ extern const word VENDOR_READABLE;
__psv__ extern const word USER_READABLE;


extern tSettings Settings;  

extern bool fCaptureToUSB; // When on, capture text & codes to USB port. Turn ctrl-codes into text     
extern bool Bootload_DTR;

#else

// Included in Global.c


#endif

#endif
