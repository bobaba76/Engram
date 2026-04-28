#ifndef SYSDEF_H
#define SYSDEF_H

#undef VIDEO_LED_2_LEAD

#ifdef __C30__

#include <p33Fxxxx.h>

#ifndef TYPEDEFS_H
#include "typedefs.h"
#endif

#endif

#define COPYRIGHT             "(c) Copyright R.Davies, J.Davies 2012."
#define OEM_NAME              "JV Surveillance"
#define OEM_CONTACT           ""
#define VENDOR_NAME           "JV Surveillance"
#define VENDOR_CONTACT        ""
#define PRODUCT_NAME          "TillViewer CW100"
#define PRODUCT_DESCRIPTION   "POS and Scale Video Overlay"

#define HW_VERSION         "1.10"
#define SW_VERSION         "0.99"

#define VIDEO_SYSTEM          vidPAL      /* enum declared in typedefs.h */

#define PAL_SYSTEM
#define IGNORE_POS_EIGHTH_BIT          /* Handle 7 & 8 bit data the same */
     
#define FOSC               76800000    /* Processor oscillator frequency in Hz */

// PLL settings
#define PLL_PRE_DIV        5
#define PLL_VCO_MPY        96
#define PLL_POST_DIV       2   

// NB: If anything relating to clock has to be changed, check that:
// ----------------------------------------------------------------
//   1)   800e3 < (FXTAL / PLL_PRE_DIV) < 8e6
//   2)   100e6 < (FXTAL / PLL_PRE_DIV * PLL_VCO_MPY) < 200e6
//   3)   (FXTAL / PLL_PRE_DIV * PLL_VCO_MPY / PLL_POST_DIV) == FOSC defined above.
//   4)   FOSC <= 80e6
//
// ALSO CHECK:
// -----------
//    Consult the datasheet of the target device and verify that the expressions
//    in function InitOSC() in file "Init.c" will produce the correct results.


// Memory definitions
#define FLASH_MAX           0x00ABFFUL
#define FLASH_BLOCK_SIZE   512u     /* Flash block memory size, words (min that can be erased) */
#define FLASH_ROW_SIZE     64u      /* Row size for flash memory row write */
#define RAM_SIZE_BYTES     8192u    /* RAM size in bytes */
#define BL_PAGE_LOCATION   1        /* Bootloader page location */
#define BL_PAGES           2        /* Bootloader size in pages */
#define OEM_SETTINGS_PAGE  3        /* Flash page in which settings only adjustable by OEM are stored */
#define OEM_SETTINGS_PAGES 1
#define SETTINGS_PAGE      4        /* Flash page in which settings are stored */
#define SETTINGS_PAGES     1        /* Flash pages reserved for settings */

#define STACK_CHECK_PATTERN 0x5A5A  /* Pattern placed in RAM to check for TOS */

// Bootloader settings
// -------------------
#if !defined(__C30__) && !defined(_lint)  // Exclude in C30 & when running lint

#define BL_FCY                      38400000         /* Clock speed (hz) in bootloader mode */
#define BL_USE_BRGH                 1                /* Use baud rate generator high speed mode */
#define BL_BAUD_RATE                115200           /* Baud rate */
#define BL_INITAL_TIMOUT_MS         1000             /* Timeout after entering bootloader mode */
#define BL_RX_TIMEOUT_MS            1000             /* Timeout between rx packets */
#define BL_Tx                       LATB,   #RB9     /* Tx pin latch */
#define BL_TxTris                   TRISB,  #RB9     /* Tx pin tris */
#define BL_RxTris                   TRISC,  #RC6     /* Rx pin tris */
#define BL_DSR                      LATB,   #RB15    /* DSR pin - output */
#define BL_DSR_Tris                 TRISB,  #RB15    /* DSR tris */
#define BL_DTR                      PORTB,  #RB14    /* DTR pin - input */
#define BL_DTR_Tris                 TRISB,  #RB14    /* DTR tris */
#define BL_DTR_Pullup               CNPU1,  #CN12PUE /* DTR pin pullup enable */
#define BL_DTR_ChangeNotification   CNEN1,  #CN12IE  /* DTR pin change notification */

#endif

//--------------------------------------------------------------------------------------------------

#define VIDEO_SYNC_OFF_MV           75.0f           /* Threshold for video off, (mV sync amplitude) */
#define VIDEO_SYNC_ON_MV            100.0f          /* Threshold for video on (mV sync amplitude*/
#define VIDEO_SYNC_LOW_MV           170.0f          /* Threshold below which video is flagged as low */
#define VIDEO_SYNC_GOOD_MV          190.0f          /* Threshold above which video is flagged as good */

#define VIDEO_RELAY_ON_DELAY_MS     100             /* Delay in ms between detecting video & turning relay on */
#define VIDEO_RELAY_OFF_DELAY_MS    400            /* Delay in ms between losing video & turning relay off */

#define MAIN_LOOP_MS                1u             /* Main loop update rate in ms */
#define POS_LINE_TIMEOUT_MS_MIN     300u           /* POS Activity timout to write CR/LF */
#define SCROLL_PAUSE_TIMEOUT_MS     500u           /* Slow down scrolling when batch printing */

#define SYNC_LEVEL_FILTER_MS        100u          /* Time constant of sync level filter */

#define TEXT_LEVEL_PWM_MAX          512u           /* value that will set PWM to 100% (TMR3 PR3)*/
#define TEXT_LEVEL_BLACK            (TEXT_LEVEL_PWM_MAX / 2u)
 
// Default Settings
#define DEFAULT_BAUD_RATE           9600ul         /* RS232 default baud rate */
#define DEFAULT_DATA_BITS           8u
#define DEFAULT_STOP_BITS           1u
#define DEFAULT_PARITY              parityNone
#define DEFAULT_TAB_STOP_SIZE       8u
#define DEFAULT_TEXT_SIZE           2u             /* Second smallest */
#define DEFAULT_OVERLAY_COLUMNS     TEXT_COLUMNS   /* 40 columns */
#define DEFAULT_OVERLAY_ROWS        (TEXT_LINES)   /* 30 rows */
#define DEFAULT_OVERLAY_ALIGNMENT   alignTopLeft  /* Top Left */
#define DEFAULT_OVERLAY_TIMEOUT     30u            /* Overlay timeout in seconds */
#define DEFAULT_TEXT_ATTRIBUTE      attrBlack_NoBkgnd
#define DEFAULT_WHITE_LEVEL         ((TEXT_LEVEL_BLACK) + ((0.7f / 3.3f) * TEXT_LEVEL_PWM_MAX))

#define TEXT_COLUMNS                40u         /* Characters per line */
#define TEXT_LINES                  30u         /* Text lines per page */ 
#define TEXT_IS_INTERLACED          false       /* Use / don't use interlaced text */

#define OVERLAY_MAX_ROWS            (TEXT_LINES)/* Maximum scroll block can be set to */
#define OVERLAY_MIN_ROWS            10u         /* Minimum that scroll block can be set to */
#define STATUS_LINE_ROW             0           /* Line location (set to top or bottom) */

#define TAB_MIN_SIZE                1           /* Minumum size tab stop can be */
#define TAB_MAX_SIZE                8           /* Maximum size tab stop can be */

#define FONT_HEIGHT                 8u          /* Number of video lines per font char */
#define FONT_WIDTH                  8u          /* Font width (always 8) */
#define FONT_LINE_SPACE             0u          /* Number of video lines to space text lines */

#define TIME_BURST_START            5.3e-6F     /* Time from sync to start of burst/clamp pulse  */
#define TIME_BURST_END              9e-6F       /* Time from sync to end of burst/clamp pulse    */
#define TIME_VIDEO_START            10.25E-6    /* Time from sync to start of video */
#define TIME_TEXT_LEFT              12.5e-6     /* Time from sync to left align */
#define TIME_TEXT_RIGHT             60.5e-6     /* Time from sync to Right aligned text end time */ 
#define TIME_VIDEO_END              62.25e-6    /* Time from sync to end of video */

#define COMPARATOR_LATENCY          0.8e-6F     /* Sync till OC1 running.(determine experimentaly)*/ 

#define MENU_TOP                    5u          /* Y org of menu */
#define MENU_LEFT                   2u          /* X org of menu */
#define MENU_OPTIONS_TOP            5u          /* Y org of menu options list */
#define MENU_OPTIONS_LEFT           21u         /* X org of menu options list */
#define MENU_HINTS_TOP              16u         /* Y org of menu hint lines */
#define MENU_USAGE_TOP              20u         /* Y org of menu help/usage lines */
#define MENU_USAGE_LINES            6u          /* Number of lines menu usage will occupy */
#undef  MENU_DO_INSTANT_PREVIEW                 /* Enable define to give user immediate feedback on option */
#define MENU_TIMEOUT_SECS           60u         /* Time (s) before menu automatically aborts when no activity */

#define MAINT_TX_BUFFER_SIZE        1024      
#define MAINT_RX_BUFFER_SIZE        512
#define POS_RX_BUFFER_SIZE          2048      

// Sanity checks
//#if ((MENU_USAGE_TOP) + (MENU_USAGE_LINES)) > (TEXT_LINES)
//#error Menu exceeds length of screen
//#endif

// PPS drive outputs
//NOTE: Due to lack of pins, during debugging, DSR is used (RP15/RB15) for clocking SPI2 from SPI1.
// otherwise PGC (RB11/RP11) is used.
#define oSyncSep                    _RP12R      /* Sync separator output (only used for debugging) */
#define oPorch                      _RP17R      /* OC1 as monostable */
#define oText                       _RP3R       /* SDO1 Text out */
#define oTextSolidBkgnd             _RP16R      /* SDO2 Drive high/low whenever solid text background is needed */
#define oTextTrnsBkgnd              _RP4R       /* SDO2 Drive high whenever translucent backround needed */
#define oTextGate                   _RP13R      /* OC3 Text Gate - use OC3 to make framing pulses */
#ifdef __DEBUG
#define oTextClk                    _RP15R      /* SPI1CK out - use to clock SPI2 (slave) used as emit kackground */
#else
#define oTextClk                    _RP11R      /* SPI1CK out - use to clock SPI2 (slave) used as emit kackground */
#endif
#define oLocalSync                  _RP5R       /* When no sync present on I/P, locally generate sync */
#define oTx                         _RP9R       /* UART1 Tx (POS) */
#define oTx_USB                     _RP23R      /* UART2 Tx (USB) */
#define oTextLevel                  _RP2R       /* OC2 (PWM) Text white/black level */

// Same of the same outputs when controlled directly in software
#define LatTextSolidBkgnd           _LATC0
#define LatTextTrnsBkgnd            _LATB4
      
// Software controlled outputs
#define oTextBkgndLevel             _LATC2
#define oRunLED                     _LATB6      /* Run LED */
#define oRlyVideo                   _LATA10     /* Video relay drive */
#define oRlyAux                     _LATA7      /* Auxiliary relay drive */
#define oScopeTrigger               _LATB10     /* Trigger for scope at selected line number */
#define oTxDisable                  _LATA8      /* R232 Tx disable (UART1) */
#define o_U2_DSR                    _LATB15     /* UART2 DSR output */
#if defined(VIDEO_LED_2_LEAD) 
#define oVideoLED                   _LATB7      /* Video LED */
#define oVideoLED_NOT               _LATB8      /* NOT Video LED */
#else
#define oVideoGreenLED              _LATB7      /* Green LED, vcideo present */
#define oVideoRedLED                _LATB8      /* Red LED, no video */
#endif

// PPS controlled inputs
#define iRx                         22u         /* UART1 Rx, RP22 */
#define iRx_USB                     24u         /* UART2 Rx, RP24 */ 
#define iTextGate                   13u         /* OC3 out, SPI1 SS in */
#define iBgndGate                   13u         /* OC3 out, SPI2 SS in */
#ifdef __DEBUG
#define iBgndClk                    15u         /* SPI1 clk out, SPI2 clk in */
#else
#define iBgndClk                    11u         /* SPI1 clk out, SPI2 clk in */
#endif

// Software Inputs
#define iSw1                        _RC5        /* Tactile switch 1   */
#define iSw2                        _RC4        /* Tactile switch 2   */
#define iSw3                        _RC3        /* Tactile switch 3   */
#define iSw4                        _RA9        /* Tactile switch 4   */
#define i_U2_DTR                    _RB14       /* UART2 DTR input */

// Individual TRIS flags
#define TrisTextSolidBkgnd          _TRISC0
#define TrisTextTrnsBkgnd           _TRISB4
#define TrisTextBkgndLevel          _TRISC2
#define TrisTxDisable               _TRISA8
#define TrisSw4                     _TRISA9
#define TrisLocalSync               _TRISB5
#define Tris_U2_DTR                 _TRISB14    /* UART2 DTR tris - input */
#define Trus_US_DSR                 _TRISB15

// Button assignment - schematic
#define SW1                         Buttons.b0
#define SW2                         Buttons.b1
#define SW3                         Buttons.b2
#define SW4                         Buttons.b3

// Button assignment - usage
#define SW_MENU                     SW1      /* Menu button or USB command */
#define SW_UP                       SW2      /* Up button or USB command */
#define SW_DN                       SW3      /* Down button or USB command */
#define SW_ESC                      SW4      /* Esc button or USB command */

// Button change assignment - must be same bits as SW1 .. SW4
#define SW_MENU_CHANGED             ButtonChange.b0
#define SW_UP_CHANGED               ButtonChange.b1
#define SW_DN_CHANGED               ButtonChange.b2
#define SW_ESC_CHANGED              ButtonChange.b3

// Button auto-repeat mask - set corresponding bit to 1 if allowed to autorepeat
#define SW_REPEAT_MASK              0x06u

#define SW_MENU_DELAY               2000u
#define SW_RESET_ALL_DELAY          5000u
#define SW_DEBOUNCE_DELAY           20u
#define DTR_DEBOUNCE_DELAY          250u

// Analog inputs (bit weight in AD1PCFG)
#define aiRef1V7                    1
#define aiSyncPk                    2
#define aiSyncIn                    4
#define aiSyncSlice                 8

#define AD1PCFG_LOAD                (~( aiRef1V7 | aiSyncPk | aiSyncIn | aiSyncSlice | aiSyncIn))

#define TRISA_LOAD                  0x0303u
#define TRISB_LOAD                  0x4023u
#define TRISC_LOAD                  0x0178u

// Output PPS map table
// --------------------                      
#define  PPS_MAP_NULL               0u       /* NULL */
#define  PPS_MAP_C1OUT              1u       /* Comparator 1 Out */
#define  PPS_MAP_C2OUT              2u       /* Comparator 2 Out */
#define  PPS_MAP_U1TX               3u       /* UART1 Transmit */
#define  PPS_MAP_U1RTS              4u       /* UART1 Request To Send */
#define  PPS_MAP_U2TX               5u       /* UART2 Transmit */
#define  PPS_MAP_U2RTS              6u       /* UART2 Request To Send */
#define  PPS_MAP_SDO1               7u       /* SPI1 Data Output */
#define  PPS_MAP_SCK1OUT            8u       /* SPI1 Clock Output */
#define  PPS_MAP_SS1OUT             9u       /* SPI1 Slave Select */
#define  PPS_MAP_SDO2               10u      /* SPI2 Data Output */
#define  PPS_MAP_SCK2OUT            11u      /* SPI2 Clock Output */
#define  PPS_MAP_SS2OUT             12u      /* SPI2 Slave Select */
#define  PPS_MAP_OC1                18u      /* Output Compare 1 */
#define  PPS_MAP_OC2                19u      /* Output Compare 2 */
#define  PPS_MAP_OC3                20u      /* Output Compare 3 */
#define  PPS_MAP_OC4                21u      /* Output Compare 4 */
#define  PPS_MAP_OC5                22u      /* Output Compare 5 */

// Input PPS Mapping
// -----------------
#define	PPS_MAP_INT1               RPINR0bits.INTR1     /* External Interrupt 1 */
#define	PPS_MAP_INT2               RPINR1bits.INTR2R    /* External Interrupt 2 */
#define	PPS_MAP_T2CK               RPINR3bits.T2CKR     /* Timer2 External Clock */
#define	PPS_MAP_T3CK               RPINR3bits.T3CKR     /* Timer3 External Clock */
#define	PPS_MAP_T4CK               RPINR4bits.T4CKR     /* Timer4 External Clock */
#define	PPS_MAP_T5CK               RPINR4bits.T5CKR     /* Timer5 External Clock */
#define	PPS_MAP_IC1                RPINR7bits.IC1R      /* Input Capture 1 */
#define	PPS_MAP_IC2                RPINR7bits.IC2R      /* Input Capture 2 */
#define	PPS_MAP_IC3                RPINR8bits.IC3R      /* Input Capture 3 */
#define	PPS_MAP_IC4                RPINR8bits.IC4R      /* Input Capture 4 */
#define	PPS_MAP_IC5                RPINR9bits.IC5R      /* Input Capture 5 */
#define	PPS_MAP_OCFA               RPINR11bits.OCFAR    /* Output Compare Fault A */
#define	PPS_MAP_OCFB               RPINR11bits.OCFBR    /* Output Compare Fault B */
#define	PPS_MAP_U1RX               RPINR18bits.U1RXR    /* UART1 Receive */
#define	PPS_MAP_U1CTS              RPINR18bits.U1CTSR   /* UART1 Clear To Send */
#define	PPS_MAP_U2RX               RPINR19bits.U2RXR    /* UART2 Receive */
#define	PPS_MAP_U2CTS              RPINR19bits.U2CTSR   /* UART2 Clear To Send */
#define	PPS_MAP_SDI1               RPINR20bits.SDI1R    /* SPI1 Data Input */
#define	PPS_MAP_SCK1IN             RPINR20bits.SCK1R    /* SPI1 Clock Input */
#define	PPS_MAP_SS1IN              RPINR21bits.SS1R     /* SPI1 Slave Select Input */
#define	PPS_MAP_SDI2               RPINR22bits.SDI2R    /* SPI2 Data Input */
#define	PPS_MAP_SCK2IN             RPINR22bits.SCK2R    /* SPI2 Clock Input */
#define	PPS_MAP_SS2IN              RPINR23bits.SS2R     /* SPI2 Slave Select Input  */

#ifdef __dsPIC33FJ64GP204__
// These are the config register addresses - refer to the datasheet for the target processor
#define CONFIG_REG_ADDR 0xF80000UL
#ifdef __C30__
enum
{
   CFG_OFFS_FBS      = 0x00U,
   CFG_OFFS_FSS      = 0x02U,
   CFG_OFFS_FGS      = 0x04U,
   CFG_OFFS_FOSCSEL  = 0x06U,
   CFG_OFFS_FOSC     = 0x08U,
   CFG_OFFS_FWDT     = 0x0AU,
   CFG_OFFS_FPOR     = 0x0CU,
   CFG_OFFS_FICD     = 0x0EU,
   CFG_OFFS_FUID0    = 0x10U,
   CFG_OFFS_FUID1    = 0x12U,
   CFG_OFFS_FUID2    = 0x14U,
   CFG_OFFS_FUID3    = 0x16u
};

// These are the masks for the values stored in the config registers
//  - refer to Microdhip doc DS70152 for the values for the target processor
enum
{
   CFG_MASK_FBS       = 0xCFU,
   CFG_MASK_FSS       = 0xCFU,
   CFG_MASK_FGS       = 0x07U,
   CFG_MASK_FOSCSEL   = 0x87U,
   CFG_MASK_FOSC      = 0xE7U,
   CFG_MASK_FWDT      = 0xDFU,
   CFG_MASK_FPOR      = 0xF7U,
   CFG_MASK_FICD      = 0xE3u
};   
#endif

#else
   #error "Incorrect processor selected - check that the applicable config registers are correct"
#endif

#endif
