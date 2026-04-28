
#define GLOBAL_C
#include "global.h"
#undef GLOBAL_C

#include "utils.h"

tFilter SyncLevelFilter = {{0},{0}};

char MaintTxBuffer[MAINT_TX_BUFFER_SIZE];
char MaintRxBuffer[MAINT_RX_BUFFER_SIZE];
__attribute__((far)) char POS_RxBuffer[POS_RX_BUFFER_SIZE];

byte *FlashBuffer = (byte*)&POS_RxBuffer;

#if FLASH_BUFFER_SIZE > POS_RX_BUFFER_SIZE
#error The POS_RxBuffer must be at least 3 times bigger than FLASH_BLOCK_SIZE - the buffers overlap
#endif

bool Bootload_DTR = high;  // DTR if low s used to enter bootloader

bool  fCaptureToUSB = false; // When on, capture text & codes to USB port. Turn ctrl-codes into text

int16 ADC1Buffer[ADC_BUF_SIZE] __attribute__((space(dma)));

byte SPI1TxBuf[TEXT_COLUMNS + 1] __attribute__((space(dma)));
byte SPI1RxBuf[1] __attribute__((space(dma)));

byte SPI2TxBuf[TEXT_COLUMNS + 1] __attribute__((space(dma)));
byte SPI2RxBuf[1] __attribute__((space(dma)));

word CyclesTimer2Preload = ((word)(-(CYCLE_TEXT_LEFT_ALIGN)));
word CyclesPerChar;
word SPI_Prescaler;
word FontCharSpace;           /* Space between chars */

byte TextSize = DEFAULT_TEXT_SIZE;

byte  TextBackgroundFill = 0;

int16 *pVRef1V7   = (int16*)&ADC1Buffer[1];
int16 *pSyncPk    = (int16*)&ADC1Buffer[2];
int16 *pSyncSlice = (int16*)&ADC1Buffer[0];
int16 *pVideoIn   = (int16*)&ADC1Buffer[3];

int16 VideoWhiteLevel = DEFAULT_WHITE_LEVEL;

bool fVideoPresent = false;

bool fLowVideo = false;

bool fMenuIsActive = false;

bool fStatusLineIsActive = false;

bool fFlashStatusLine = false;

word POS_LineTimeoutMS =  POS_LINE_TIMEOUT_MS_MIN;

__psv__ const tSettings DEFAULT_SETTINGS = 
{
   .UART.BaudRate       = DEFAULT_BAUD_RATE,
   .UART.DataBits       = DEFAULT_DATA_BITS,
   .UART.StopBits       = DEFAULT_STOP_BITS,
   .UART.Parity         = DEFAULT_PARITY,
   .Text.TabSize        = DEFAULT_TAB_STOP_SIZE,
   .Text.Size           = DEFAULT_TEXT_SIZE,
   .Text.Attribute      = DEFAULT_TEXT_ATTRIBUTE,
   .Overlay.Rows        = DEFAULT_OVERLAY_ROWS,
   .Overlay.Columns     = DEFAULT_OVERLAY_COLUMNS,
   .Overlay.Alignment   = DEFAULT_OVERLAY_ALIGNMENT,
   .Overlay.Timeout     = DEFAULT_OVERLAY_TIMEOUT,
   .AlarmTriggers       = {"VOID","CANCEL","REFUND","NO SALE","","","",""}
};

__psv__ const char OEM_TITLE_STR[OEM_SETTINGS_STR_COUNT][20] =
{
   "Copyright",
   "OEM",
   "OEM Contact",
   "Vendor",
   "Vendor Contact",
   "Product",
   "Description",
   "Sw Version",
   "Hw Version",
};
 

__psv__ const tOEM_Settings DEFAULT_OEM_SETTINGS =
{
   .Copyright           = COPYRIGHT,
   .OEM_Name            = OEM_NAME,
   .OEM_Contact         = OEM_CONTACT,
   .VendorName          = VENDOR_NAME,
   .VendorContact       = VENDOR_CONTACT,
   .ProductName         = PRODUCT_NAME,
   .ProductDescription  = PRODUCT_DESCRIPTION,
   .SwVersion           = SW_VERSION,
   .HwVersion           = HW_VERSION
};

// Set a bit for each "OEM Setting" item that is readable modifiable 
//                                              +---------- Hardware Version
//                                              |+--------- Software Version
//                                              ||+-------- Product Description
//                                              |||+------- Product Name
//                                              ||||+------ Vendor Contact
//                                              |||||+----- Vendor Name
//                                              ||||||+---- OEM Contact
//                                              |||||||+--- OEM Name
//                                              ||||||||+-- Copyright
//                                              |||||||||
__psv__ const word OEM_MODIFIABLE    = 0b0000000101111110;
__psv__ const word VENDOR_MODIFIABLE = 0b0000000001111000;
__psv__ const word USER_MODIFIABLE   = 0b0000000000000000;
__psv__ const word VENDOR_READABLE   = 0b0000000111111110;
__psv__ const word USER_READABLE     = 0b0000000111111000;


__psv__ const char VIDEO_SYSTEM_STR[vidMAX][8] = { [vidPAL] = "PAL", [vidNTSC] = "NTSC" };

tVideoSystem VideoSystem = vidPAL;

tSettings Settings;

__psv__ const tFlashChecksum FLASH_CHECKSUM =
   {
      .Sum = 0x0000,
      .SumComplement = 0xFFFF,
      .IsSet = 0x0000,
      .IsSetComplement = 0xFFFF
   };  

//-------------------------------------------------------------------------------------------------
// IMPORTANT: To avoid linker errors when using DWARF format, it is necessary to locate these
// constant blocks at the end of the file. This is because these constants are assigned their own
// sections in program code space. This is done because these factors are re-programmed during setup
// and need to occupy a section of code space by themselves to avoid the possibility of program
// memory corruption. Also doing this makes it easy to preserve these during bootloading.
__psv__ const tStored_OEM_Settings const_at(".oem_settings", OEM_SETTINGS_ADDRESS)
   STORED_OEM_SETTINGS =
{
   .Checksum = ((sizeof(tOEM_Settings)) * 0xFFu),
   .ChecksumComplement = ~((sizeof(tOEM_Settings)) * 0xFFu),
//   .Data = 
//   {
//      .Copyright = COPYRIGHT,   
//      .OEM_Name = OEM_NAME,
//      .OEM_Contact = OEM_CONTACT,
//      .VendorName = VENDOR_NAME,
//      .VendorContact = VENDOR_CONTACT, 
//      .ProductName = PRODUCT_NAME,
//      .ProductDescription = PRODUCT_DESCRIPTION,
//      .SwVersion = HW_VERSION,
//      .HwVersion = SW_VERSION
//   },
//   .DataComplement = 
//   {
//      .Copyright = ,
//      .OEM_Name = ,
//      .OEM_Contact = ,
//      .VendorName = ,
//      .VendorContact = , 
//      .ProductName = ,
//      .ProductDescription = ,
//      .SwVersion = ,
//      .HwVersion = 
//   },
     .IsInitialised = 0,
     .IsInitialisedComplement = ~0
};

// Pad the rest of the flash page with zeros
const byte  const_at(".oem_settings_padding", (OEM_SETTINGS_ADDRESS + sizeof(tStored_OEM_Settings)))
   OEM_SETTINGS_PADDING[FLASH_BLOCK_SIZE * 2 - sizeof(tStored_OEM_Settings)] = {0};

__psv__ const tStoredSettings const_at(".settings", STORED_SETTINGS_ADDRESS) STORED_SETTINGS =
{  
   .Checksum = ((sizeof(tSettings)) * 0xFFu),
   .ChecksumComplement = ~((sizeof(tSettings)) * 0xFFu),

//   .Data = 
//   {   
//      .UART.BaudRate = DEFAULT_BAUD_RATE,
//      .UART.DataBits = DEFAULT_DATA_BITS, 
//      .UART.StopBits = DEFAULT_STOP_BITS, 
//      .UART.Parity = DEFAULT_PARITY,
//      .TabStopSize = DEFAULT_TAB_STOP_SIZE,
//      .TextSize = DEFAULT_TEXT_SIZE,
//      .TextAttribute = DEFAULT_TEXT_ATTRIBUTE,
//      .OverlayRows = DEFAULT_OVERLAY_ROWS,
//      .OverlayColumns = DEFAULT_OVERLAY_COLUMNS,
//      .OverlayAlignment = DEFAULT_OVERLAY_ALIGNMENT,
//      .OverlayTimeout = DEFAULT_OVERLAY_TIMEOUT,
//      .AlarmTriggers = {"VOID","CANCEL","REFUND","NO SALE","","","",""}
//   },
//TODO: Macro to fill with 0xFF
//   .DataComplement = 
//   {
//      .UART.BaudRate = ~DEFAULT_BAUD_RATE,
//      .UART.DataBits = ((word)~DEFAULT_DATA_BITS), 
//      .UART.StopBits = ((word)~DEFAULT_STOP_BITS), 
//      .UART.Parity = ~DEFAULT_PARITY,
//      .TabStopSize = ~DEFAULT_TAB_STOP_SIZE,
//      .TextSize = ((word)~DEFAULT_TEXT_SIZE),
//      .TextAttribute = ((word)~DEFAULT_TEXT_ATTRIBUTE),
//      .OverlayRows = (word)~DEFAULT_OVERLAY_ROWS,
//      .OverlayColumns = (word)~DEFAULT_OVERLAY_COLUMNS,
//      .OverlayAlignment = ~DEFAULT_OVERLAY_ALIGNMENT,
//      .OverlayTimeout = ~DEFAULT_OVERLAY_TIMEOUT,
//      .AlarmTriggers = 
//      {
//         COMPL_ALARM_STR0,
//         COMPL_ALARM_STR1,
//         COMPL_ALARM_STR2,
//         COMPL_ALARM_STR3,
//         COMPL_BLANK_STR,
//         COMPL_BLANK_STR,
//         COMPL_BLANK_STR,
//         COMPL_BLANK_STR
//      }
//   },
     .IsInitialised = 0,
     .IsInitialisedComplement = ~0
};

// Pad the rest of the flash page with zeros
const byte  const_at(".settings_padding", (STORED_SETTINGS_ADDRESS + sizeof(tStoredSettings)))
   SETTINGS_PADDING[FLASH_BLOCK_SIZE * 2 - sizeof(tStoredSettings)] = {0};
   
STATIC_ASSERT(sizeof(STORED_SETTINGS) + sizeof(SETTINGS_PADDING) == FLASH_BLOCK_SIZE * 2);

// Array of pointers to strings in stored OEM settings. Used because strings are different lengths.
const char *OEM_STRING_INDEX[OEM_SETTINGS_STR_COUNT] =
{
   (char*)&STORED_OEM_SETTINGS.Data.Copyright[0],
   (char*)&STORED_OEM_SETTINGS.Data.OEM_Name[0],
   (char*)&STORED_OEM_SETTINGS.Data.OEM_Contact[0],
   (char*)&STORED_OEM_SETTINGS.Data.VendorName[0],
   (char*)&STORED_OEM_SETTINGS.Data.VendorContact[0],
   (char*)&STORED_OEM_SETTINGS.Data.ProductName[0],       
   (char*)&STORED_OEM_SETTINGS.Data.ProductDescription[0],
   (char*)&STORED_OEM_SETTINGS.Data.SwVersion[0],
   (char*)&STORED_OEM_SETTINGS.Data.HwVersion[0],             
};
