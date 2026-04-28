
#ifndef MENU_H
#define MENU_H



void DoMenu(void);
void MenuDisplaySurrounds(void);

#ifndef MENU_C


#else

#define BAUD_MENU_ITEMS				9
#define BAUD_MENU_MAX				(BAUD_MENU_ITEMS - 1)
#define BAUD_MENU_MIN				0

#define DATABIT_MENU_ITEMS			2
#define DATABIT_MENU_MAX			(DATABIT_MENU_ITEMS - 1)
#define DATABIT_MENU_MIN			0

#define STOPBIT_MENU_ITEMS			2
#define STOPBIT_MENU_MAX			(STOPBIT_MENU_ITEMS - 1)
#define STOPBIT_MENU_MIN			0

#define PARITY_MENU_ITEMS			3
#define PARITY_MENU_MAX				(PARITY_MENU_ITEMS - 1)
#define PARITY_MENU_MIN				0

#define TABSTOP_MENU_ITEMS			1
#define TABSTOP_MENU_MAX			(TABSTOP_MENU_ITEMS - 1)
#define TABSTOP_MENU_MIN			0

#define TEXTSIZE_MENU_ITEMS		4
#define TEXTSIZE_MENU_MAX			(TEXTSIZE_MENU_ITEMS - 1)
#define TEXTSIZE_MENU_MIN			0

#define TEXTATTR_MENU_ITEMS		7
#define TEXTATTR_MENU_MAX			(TEXTATTR_MENU_ITEMS - 1)
#define TEXTATTR_MENU_MIN			0

#define OVERLAYROWS_MENU_ITEMS	1
#define OVERLAYROWS_MENU_MAX		(OVERLAYROWS_MENU_ITEMS - 1)
#define OVERLAYROWS_MENU_MIN		0

#define OVERLAYCOLS_MENU_ITEMS	2
#define OVERLAYCOLS_MENU_MAX		(OVERLAYCOLS_MENU_ITEMS - 1)
#define OVERLAYCOLS_MENU_MIN		0

#define ALIGNMENT_MENU_ITEMS		4
#define ALIGNMENT_MENU_MAX			(ALIGNMENT_MENU_ITEMS - 1)
#define ALIGNMENT_MENU_MIN			0

#define TIMEOUT_MENU_ITEMS			6
#define TIMEOUT_MENU_MAX			(TIMEOUT_MENU_ITEMS - 1)
#define TIMEOUT_MENU_MIN			0

#define RESET_MENU_ITEMS			2
#define RESET_MENU_MAX				(RESET_MENU_ITEMS - 1)
#define RESET_MENU_MIN				0

#define RS232_MENU_ITEMS			4
#define RS232_MENU_MAX				(RS232_MENU_ITEMS - 1)
#define RS232_MENU_MIN				0

#define MAIN_MENU_ITEMS				9
#define MAIN_MENU_MAX				(MAIN_MENU_ITEMS - 1)
#define MAIN_MENU_MIN				0

typedef struct tMenuOption tMenuOption;
typedef struct tMenu tMenu;

typedef enum 
{
   mnuSetOption,
   mnuMenu
} tMenuType;

struct tMenuOption
{
   tMenuOption  *NextItem;
   tMenuOption  *PrevItem;
   tMenu        *NextMenu;
   uint32        Data;
   char         *Caption;
   char         *ItemHint;
};

struct tMenu
{
   tMenuType    MenuType;
   tMenuOption  *FirstItem;
   tMenuOption  *LastItem;
   tMenuOption  *SelectedItem;
   tMenuOption  *ActiveItem;
   tMenu        *NextMenu;
   tMenu        *ParentMenu;
   void         (*Callback)(void *);
   uint32       (*GetCurrentSetting)(void);
   bool         CallbackOnSelect;
   byte x;
   byte y;
   byte MaxCaptionLen;
};


static void Callback_BaudRate(tMenuOption *MenuItem);
static void Callback_DataBits(tMenuOption *MenuItem);
static void Callback_StopBits(tMenuOption *MenuItem);
static void Callback_Parity(tMenuOption *MenuItem);
static void Callback_TabStops(tMenuOption *MenuItem);
static void Callback_TextAttr(tMenuOption *MenuItem);
static void Callback_TextSize(tMenuOption *MenuItem);
static void Callback_OverlayRows(tMenuOption *MenuItem);
static void Callback_OverlayColumns(tMenuOption *MenuItem);
static void Callback_OverlayAlignment(tMenuOption *MenuItem);
static void Callback_OverlayTimeout(tMenuOption *MenuItem);
static void Callback_ResetDefaults(tMenuOption *MenuItem);

static uint32 GetSetting_BaudRate(void);
static uint32 GetSetting_DataBits(void);
static uint32 GetSetting_StopBits(void);
static uint32 GetSetting_Parity(void);
static uint32 GetSetting_TabStop(void);
static uint32 GetSetting_TextAttr(void);
static uint32 GetSetting_TextSize(void);
static uint32 GetSetting_OverlayRows(void);
static uint32 GetSetting_OverlayColumns(void);
static uint32 GetSetting_OverlayAlignment(void);
static uint32 GetSetting_OverlayTimeout(void);

static void InitSubMenu(tMenu *Menu);
static void MenuInit(void);
static void MenuEnter(tMenu *Menu);
static void MenuPrevItem(tMenu *Menu);
static void MenuNextItem(tMenu *Menu);
static tMenu *MenuLeave(tMenu *Menu);
static void MenuSelectItem(tMenu *Menu);
static void MenuDeselectItem(tMenu *Menu);
static void MenuShow(tMenu *Menu);

//--------------------------------------------------------------------------------------------------
const char UART_ItemHint[] = "WARNING: If incorrect, POS overlay\r\nwill not display correctly!";
const tMenuOption BaudMenuOptions[BAUD_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&BaudMenuOptions[1],
      .PrevItem = (tMenuOption *)&BaudMenuOptions[BAUD_MENU_MAX],
      .NextMenu = NULL,
      .Data = 1200,
      .Caption = "  1200",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [1] = 
   {
      .NextItem = (tMenuOption *)&BaudMenuOptions[2],
      .PrevItem = (tMenuOption *)&BaudMenuOptions[0],
      .NextMenu = NULL,
      .Data = 2400,
      .Caption = "  2400",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [2] =
   {
      .NextItem = (tMenuOption *)&BaudMenuOptions[3],
      .PrevItem = (tMenuOption *)&BaudMenuOptions[1],
      .NextMenu = NULL,
      .Data = 4800,
      .Caption = "  4800",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [3] = 
   {
      .NextItem = (tMenuOption *)&BaudMenuOptions[4],
      .PrevItem = (tMenuOption *)&BaudMenuOptions[2],
      .NextMenu = NULL,
      .Data = 9600,
      .Caption = "  9600",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [4] =
   {
      .NextItem = (tMenuOption *)&BaudMenuOptions[5],
      .PrevItem = (tMenuOption *)&BaudMenuOptions[3],
      .NextMenu = NULL,
      .Data = 14400,
      .Caption = " 14400",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [5] = 
   {
      .NextItem = (tMenuOption *)&BaudMenuOptions[6],
      .PrevItem = (tMenuOption *)&BaudMenuOptions[4],
      .NextMenu = NULL,
      .Data = 19200,
      .Caption = " 19200",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [6] = 
   {
      .NextItem = (tMenuOption *)&BaudMenuOptions[7],
      .PrevItem = (tMenuOption *)&BaudMenuOptions[5],
      .NextMenu = NULL,
      .Data = 38400,
      .Caption = " 38400",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [7] = 
   {
      .NextItem = (tMenuOption *)&BaudMenuOptions[8],
      .PrevItem = (tMenuOption *)&BaudMenuOptions[6],
      .NextMenu = NULL,
      .Data = 57600,
      .Caption = " 57600",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [8] = 
   {
      .NextItem = (tMenuOption *)&BaudMenuOptions[BAUD_MENU_MIN],
      .PrevItem = (tMenuOption*)&BaudMenuOptions[7],
      .NextMenu = NULL,
      .Data = 115200,
      .Caption = "115200",
      .ItemHint = (char*)&UART_ItemHint[0]
   }
};

const tMenuOption DataBitsMenuOptions[DATABIT_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&DataBitsMenuOptions[DATABIT_MENU_MAX],
      .PrevItem = (tMenuOption *)&DataBitsMenuOptions[DATABIT_MENU_MAX],
      .NextMenu = NULL,
      .Data = 7,
      .Caption = "7 Data Bits",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [1] = 
   {
      .NextItem = (tMenuOption *)&DataBitsMenuOptions[DATABIT_MENU_MIN],
      .PrevItem = (tMenuOption *)&DataBitsMenuOptions[DATABIT_MENU_MIN],
      .NextMenu = NULL,
      .Data = 8,
      .Caption = "8 Data Bits",
      .ItemHint = (char*)&UART_ItemHint[0]
   }
};

const tMenuOption StopBitsMenuOptions[STOPBIT_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&StopBitsMenuOptions[STOPBIT_MENU_MAX],
      .PrevItem = (tMenuOption *)&StopBitsMenuOptions[STOPBIT_MENU_MAX],
      .NextMenu = NULL,
      .Data = 1,
      .Caption = "1 Stop Bit ",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [1] = 
   {
      .NextItem = (tMenuOption *)&StopBitsMenuOptions[STOPBIT_MENU_MIN],
      .PrevItem = (tMenuOption *)&StopBitsMenuOptions[STOPBIT_MENU_MIN],
      .NextMenu = NULL,
      .Data = 2,
      .Caption = "2 Stop Bits",
      .ItemHint = (char*)&UART_ItemHint[0]
   }
};

const tMenuOption ParityMenuOptions[PARITY_MENU_ITEMS] =
{
   [0] = 
   {
      .NextItem = (tMenuOption *)&ParityMenuOptions[1],
      .PrevItem = (tMenuOption *)&ParityMenuOptions[PARITY_MENU_MAX],
      .NextMenu = NULL,
      .Data = parityNone,
      .Caption = "No Parity  ",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [1] = 
   {
      .NextItem = (tMenuOption *)&ParityMenuOptions[2],
      .PrevItem = (tMenuOption *)&ParityMenuOptions[0],
      .NextMenu = NULL,
      .Data = parityEven,
      .Caption = "Even Parity",
      .ItemHint = (char*)&UART_ItemHint[0]
   },
   [2] = 
   {
      .NextItem = (tMenuOption *)&ParityMenuOptions[PARITY_MENU_MIN],
      .PrevItem = (tMenuOption *)&ParityMenuOptions[1],
      .NextMenu = NULL,
      .Data = parityOdd,
      .Caption = "Odd Parity ",
      .ItemHint = (char*)&UART_ItemHint[0]
   }
};

static char TabStopCaption[10] = "  8";
// Menu cannot be const
tMenuOption TabStopMenuItems[TABSTOP_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&TabStopMenuItems[TABSTOP_MENU_MAX],
      .PrevItem = (tMenuOption *)&TabStopMenuItems[TABSTOP_MENU_MAX],
      .NextMenu = NULL,
      .Data = 8,
      .Caption = &TabStopCaption[0],
      .ItemHint = "Use up/down buttons to adjust\r\nTab Stop size"
   }
};

const tMenuOption TextSizeMenuOptions[TEXTSIZE_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&TextSizeMenuOptions[1],
      .PrevItem = (tMenuOption *)&TextSizeMenuOptions[TEXTSIZE_MENU_MAX],
      .NextMenu = NULL,
      .Data = 1,
      .Caption = "1 (Smallest)",
      .ItemHint = NULL
   },
   [1] = 
   {      
      .NextItem = (tMenuOption *)&TextSizeMenuOptions[2],
      .PrevItem = (tMenuOption *)&TextSizeMenuOptions[0],
      .NextMenu = NULL,
      .Data = 2,
      .Caption = "2           ",
      .ItemHint = NULL
   },
   [2] = 
   {      
      .NextItem = (tMenuOption *)&TextSizeMenuOptions[3],
      .PrevItem = (tMenuOption *)&TextSizeMenuOptions[1],
      .NextMenu = NULL,
      .Data = 3,
      .Caption = "3           ",
      .ItemHint = NULL
   },
   [3] = 
   {      
      .NextItem = (tMenuOption *)&TextSizeMenuOptions[TEXTSIZE_MENU_MIN],
      .PrevItem = (tMenuOption *)&TextSizeMenuOptions[2],
      .NextMenu = NULL,
      .Data = 4,
      .Caption = "4 (Largest) ",
      .ItemHint = NULL
   }
};

const tMenuOption TextAttrMenuOptions[TEXTATTR_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&TextAttrMenuOptions[1],
      .PrevItem = (tMenuOption *)&TextAttrMenuOptions[TEXTATTR_MENU_MAX],
      .NextMenu = NULL,
      .Data = attrWhite_NoBkgnd,
      .Caption =  "White/None       ",
      .ItemHint = "White text, no background"
   },
   [1] = 
   {      
      .NextItem = (tMenuOption *)&TextAttrMenuOptions[2],
      .PrevItem = (tMenuOption *)&TextAttrMenuOptions[0],
      .NextMenu = NULL,
      .Data = attrWhite_TranslucentBkgnd,
      .Caption =  "White/Translucent",
      .ItemHint = "White text, translucent background"

   },
   [2] = 
   {      
      .NextItem = (tMenuOption *)&TextAttrMenuOptions[3],
      .PrevItem = (tMenuOption *)&TextAttrMenuOptions[1],
      .NextMenu = NULL,
      .Data = attrWhite_GreyBkgnd,
      .Caption =  "White/Grey       ",
      .ItemHint = "White text, grey background"

   },
   [3] = 
   {      
      .NextItem = (tMenuOption *)&TextAttrMenuOptions[4],
      .PrevItem = (tMenuOption *)&TextAttrMenuOptions[2],
      .NextMenu = NULL,
      .Data = attrWhite_BlackBkgnd,
      .Caption =  "White/Black      ",
      .ItemHint = "White text, black background"
   },
   [4] = 
   {      
      .NextItem = (tMenuOption *)&TextAttrMenuOptions[5],
      .PrevItem = (tMenuOption *)&TextAttrMenuOptions[3],
      .NextMenu = NULL,
      .Data = attrBlack_NoBkgnd,
      .Caption =  "Black/None       ",
      .ItemHint = "Black text, no background"

   },
   [5] = 
   {      
      .NextItem = (tMenuOption *)&TextAttrMenuOptions[6],
      .PrevItem = (tMenuOption *)&TextAttrMenuOptions[4],
      .NextMenu = NULL,
      .Data = attrBlack_TranslucentBkgnd,
      .Caption =  "Black/Translucent",
      .ItemHint = "Black text, translucent background"
   },
   [6] = 
   {      
      .NextItem = (tMenuOption *)&TextAttrMenuOptions[TEXTATTR_MENU_MIN],
      .PrevItem = (tMenuOption *)&TextAttrMenuOptions[5],
      .NextMenu = NULL,
      .Data = attrBlack_GreyBkgnd,
      .Caption =  "Black/Grey       ",
      .ItemHint = "Black text, grey background"
   }
};

static char RowsCaption[10] = " 25";
// Menu cannot be const
tMenuOption OverlayRowsMenuOptions[OVERLAYROWS_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&OverlayRowsMenuOptions[OVERLAYROWS_MENU_MAX],
      .PrevItem = (tMenuOption *)&OverlayRowsMenuOptions[OVERLAYROWS_MENU_MAX],
      .NextMenu = NULL,
      .Data = 0,
      .Caption = &RowsCaption[0],
      .ItemHint = "Use up/down buttons to adjust amount\r\nof rows that will be displayed"
   }
};

const tMenuOption OverlayColumnMenuOptions[OVERLAYCOLS_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&OverlayColumnMenuOptions[OVERLAYCOLS_MENU_MAX],
      .PrevItem = (tMenuOption *)&OverlayColumnMenuOptions[OVERLAYCOLS_MENU_MAX],
      .NextMenu = NULL,
      .Data = 20,
      .Caption = "20 Columns  ",
      .ItemHint = "Use when connected to pole display"
   },
   [1] = 
   {      
      .NextItem = (tMenuOption *)&OverlayColumnMenuOptions[OVERLAYCOLS_MENU_MIN],
      .PrevItem = (tMenuOption *)&OverlayColumnMenuOptions[OVERLAYCOLS_MENU_MIN],
      .NextMenu = NULL,
      .Data = 40,
      .Caption = "40 Columns  ",
      .ItemHint = "Use when connected to printer"
   }
};

const tMenuOption OverlayAlignmentMenuOptions[ALIGNMENT_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&OverlayAlignmentMenuOptions[1],
      .PrevItem = (tMenuOption *)&OverlayAlignmentMenuOptions[ALIGNMENT_MENU_MAX],
      .NextMenu = NULL,
      .Data = alignTopLeft,
      .Caption = "Top Left    ",
      .ItemHint = NULL
   },
   [1] = 
   {      
      .NextItem = (tMenuOption *)&OverlayAlignmentMenuOptions[2],
      .PrevItem = (tMenuOption *)&OverlayAlignmentMenuOptions[0],
      .NextMenu = NULL,
      .Data = alignBottomLeft,
      .Caption = "Bottom Left ",
      .ItemHint = NULL
   },
   [2] = 
   {      
      .NextItem = (tMenuOption *)&OverlayAlignmentMenuOptions[3],
      .PrevItem = (tMenuOption *)&OverlayAlignmentMenuOptions[1],
      .NextMenu = NULL,
      .Data = alignTopRight,
      .Caption = "Top Right   ",
      .ItemHint = NULL
   },
   [3] = 
   {      
      .NextItem = (tMenuOption *)&OverlayAlignmentMenuOptions[ALIGNMENT_MENU_MIN],
      .PrevItem = (tMenuOption *)&OverlayAlignmentMenuOptions[2],
      .NextMenu = NULL,
      .Data = alignBottomRight,
      .Caption = "Bottom Right",
      .ItemHint = NULL
   }
};

const tMenuOption OverlayTimeoutMenuOptions[TIMEOUT_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&OverlayTimeoutMenuOptions[1],
      .PrevItem = (tMenuOption *)&OverlayTimeoutMenuOptions[TIMEOUT_MENU_MAX],
      .NextMenu = NULL,
      .Data = 0,
      .Caption = " Never",
      .ItemHint = NULL
   },
   [1] = 
   {      
      .NextItem = (tMenuOption *)&OverlayTimeoutMenuOptions[2],
      .PrevItem = (tMenuOption *)&OverlayTimeoutMenuOptions[0],
      .NextMenu = NULL,
      .Data = 10,
      .Caption = "10 sec",
      .ItemHint = NULL
   },
   [2] = 
   {      
      .NextItem = (tMenuOption *)&OverlayTimeoutMenuOptions[3],
      .PrevItem = (tMenuOption *)&OverlayTimeoutMenuOptions[1],
      .NextMenu = NULL,      
      .Data = 20,
      .Caption = "20 sec",
      .ItemHint = NULL
   },
   [3] = 
   {      
      .NextItem = (tMenuOption *)&OverlayTimeoutMenuOptions[4],
      .PrevItem = (tMenuOption *)&OverlayTimeoutMenuOptions[2],
      .NextMenu = NULL,
      .Data = 30,
      .Caption = "30 sec",
      .ItemHint = NULL
   },
   [4] = 
   {      
      .NextItem = (tMenuOption *)&OverlayTimeoutMenuOptions[5],
      .PrevItem = (tMenuOption *)&OverlayTimeoutMenuOptions[3],
      .NextMenu = NULL,
      .Data = 60,
      .Caption = " 1 min",
      .ItemHint = NULL
   },
   [5] = 
   {      
      .NextItem = (tMenuOption *)&OverlayTimeoutMenuOptions[TIMEOUT_MENU_MIN],
      .PrevItem = (tMenuOption *)&OverlayTimeoutMenuOptions[4],
      .NextMenu = NULL,
      .Data = 120,
      .Caption = " 2 min",
      .ItemHint = NULL
   }
};

const tMenuOption AlarmTriggersMenuOptions[1] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&AlarmTriggersMenuOptions[0],
      .PrevItem = (tMenuOption *)&AlarmTriggersMenuOptions[0],
      .NextMenu = NULL,
      .Data = 0,
      .Caption = "Open triggers page",
      .ItemHint = "FUTURE UPGRADE OPTION"
   }
};

const char ResetDefaultsItemHint[] = "Select Yes to reset all settings\r\nto factory default";
const tMenuOption ResetDefaultsMenuOptions[RESET_MENU_ITEMS] =
{
   [0] = 
   {      
      .NextItem = (tMenuOption *)&ResetDefaultsMenuOptions[RESET_MENU_MAX],
      .PrevItem = (tMenuOption *)&ResetDefaultsMenuOptions[RESET_MENU_MAX],
      .NextMenu = NULL,
      .Data = 0,
      .Caption = "No   ",
      .ItemHint = (char*)&ResetDefaultsItemHint[0]
   },
   [1] = 
   {
      .NextItem = (tMenuOption *)&ResetDefaultsMenuOptions[RESET_MENU_MIN],
      .PrevItem = (tMenuOption *)&ResetDefaultsMenuOptions[RESET_MENU_MIN],
      .NextMenu = NULL,
      .Data = 1,
      .Caption = "Yes  ",
      .ItemHint = (char*)&ResetDefaultsItemHint[0]
   }
};

tMenu BaudMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&BaudMenuOptions[BAUD_MENU_MIN],
   .LastItem = (tMenuOption *)&BaudMenuOptions[BAUD_MENU_MAX],
   .SelectedItem = (tMenuOption *)&BaudMenuOptions[BAUD_MENU_MIN],
   .ActiveItem = (tMenuOption *)&BaudMenuOptions[BAUD_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_BaudRate,
   .GetCurrentSetting = (void *)GetSetting_BaudRate,
   .CallbackOnSelect =  false,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP,
};

tMenu DataBitsMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&DataBitsMenuOptions[DATABIT_MENU_MIN],
   .LastItem = (tMenuOption *)&DataBitsMenuOptions[DATABIT_MENU_MAX],
   .SelectedItem = (tMenuOption *)&DataBitsMenuOptions[DATABIT_MENU_MIN],
   .ActiveItem = (tMenuOption *)&DataBitsMenuOptions[DATABIT_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_DataBits,
   .GetCurrentSetting = (void *)GetSetting_DataBits,
   .CallbackOnSelect = false,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP,
};

tMenu StopBitsMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&StopBitsMenuOptions[STOPBIT_MENU_MIN],
   .LastItem = (tMenuOption *)&StopBitsMenuOptions[STOPBIT_MENU_MAX],
   .SelectedItem = (tMenuOption *)&StopBitsMenuOptions[STOPBIT_MENU_MIN],
   .ActiveItem = (tMenuOption *)&StopBitsMenuOptions[STOPBIT_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_StopBits,
   .GetCurrentSetting = (void *)GetSetting_StopBits,
   .CallbackOnSelect = false,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP,
};

tMenu ParityMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&ParityMenuOptions[PARITY_MENU_MIN],
   .LastItem = (tMenuOption *)&ParityMenuOptions[PARITY_MENU_MAX],
   .SelectedItem = (tMenuOption *)&ParityMenuOptions[PARITY_MENU_MIN],
   .ActiveItem = (tMenuOption *)&ParityMenuOptions[PARITY_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_Parity,
   .GetCurrentSetting = (void *)GetSetting_Parity,
   .CallbackOnSelect = false,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP,
};

const tMenuOption RS232_MenuItem[RS232_MENU_ITEMS] =
{
   [0] =
   {
      .NextItem = (tMenuOption*)&RS232_MenuItem[1],
      .PrevItem = (tMenuOption*)&RS232_MenuItem[RS232_MENU_MAX],
      .NextMenu = (tMenu*)&BaudMenu,
      .Caption =  "Baud Rate       ",
      .ItemHint = "Set to same Baud Rate as POS terminal\r\n(typically 9600 Baud)"
   },
   [1] =
   {
      .NextItem = (tMenuOption*)&RS232_MenuItem[2],
      .PrevItem = (tMenuOption*)&RS232_MenuItem[0],
      .NextMenu = (tMenu*)&DataBitsMenu,
      .Caption =  "Data Bits       ",
      .ItemHint = "Set to same Data Bit as POS terminal\r\n(typically 8 bits)"
   },
   [2] =
   {
      .NextItem = (tMenuOption*)&RS232_MenuItem[3],
      .PrevItem = (tMenuOption*)&RS232_MenuItem[1],
      .NextMenu = (tMenu*)&StopBitsMenu,
      .Caption =  "Stop Bits       ",
      .ItemHint = "Set to same Stop Bit as POS terminal\r\n(typically 1 bit)"
   },
   [3] =
   {
      .NextItem = (tMenuOption*)&RS232_MenuItem[RS232_MENU_MIN],
      .PrevItem = (tMenuOption*)&RS232_MenuItem[2],
      .NextMenu = (tMenu*)&ParityMenu,
      .Caption =  "Parity          ",
      .ItemHint = "Set to same Parity as POS terminal\r\n(typically No Parity)"
   }
};

tMenu TabStopMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&TabStopMenuItems[TABSTOP_MENU_MIN],
   .LastItem = (tMenuOption *)&TabStopMenuItems[TABSTOP_MENU_MAX],
   .SelectedItem = (tMenuOption *)&TabStopMenuItems[TABSTOP_MENU_MIN],
   .ActiveItem = (tMenuOption *)&TabStopMenuItems[TABSTOP_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_TabStops,
   .GetCurrentSetting = (void *)GetSetting_TabStop,
   .CallbackOnSelect = true,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP,
};

tMenu TextSizeMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&TextSizeMenuOptions[TEXTSIZE_MENU_MIN],
   .LastItem = (tMenuOption *)&TextSizeMenuOptions[TEXTSIZE_MENU_MAX],
   .SelectedItem = (tMenuOption *)&TextSizeMenuOptions[TEXTSIZE_MENU_MIN],
   .ActiveItem = (tMenuOption *)&TextSizeMenuOptions[TEXTSIZE_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_TextSize,
#ifdef MENU_DO_INSTANT_PREVIEW   
   .CallbackOnSelect = true,
#else
   .CallbackOnSelect = false,
#endif
   .GetCurrentSetting = (void *)GetSetting_TextSize,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP,
};

tMenu TextAttrMenu =
{  
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&TextAttrMenuOptions[TEXTATTR_MENU_MIN],
   .LastItem = (tMenuOption *)&TextAttrMenuOptions[TEXTATTR_MENU_MAX],
   .SelectedItem = (tMenuOption *)&TextAttrMenuOptions[TEXTATTR_MENU_MIN],
   .ActiveItem = (tMenuOption *)&TextAttrMenuOptions[TEXTATTR_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_TextAttr,
   .GetCurrentSetting = (void *)GetSetting_TextAttr,
#ifdef MENU_DO_INSTANT_PREVIEW   
   .CallbackOnSelect = true,
#else
   .CallbackOnSelect = false,
#endif
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP,
};

tMenu OverlayRowsMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&OverlayRowsMenuOptions[OVERLAYROWS_MENU_MIN],
   .LastItem = (tMenuOption *)&OverlayRowsMenuOptions[OVERLAYROWS_MENU_MAX],
   .SelectedItem = (tMenuOption *)&OverlayRowsMenuOptions[OVERLAYROWS_MENU_MIN],
   .ActiveItem = (tMenuOption *)&OverlayRowsMenuOptions[OVERLAYROWS_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_OverlayRows,
   .GetCurrentSetting = (void *)GetSetting_OverlayRows,
   .CallbackOnSelect = true,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP
};

tMenu OverlayColumnMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&OverlayColumnMenuOptions[OVERLAYCOLS_MENU_MIN],
   .LastItem = (tMenuOption *)&OverlayColumnMenuOptions[OVERLAYCOLS_MENU_MAX],
   .SelectedItem = (tMenuOption *)&OverlayColumnMenuOptions[OVERLAYCOLS_MENU_MIN],
   .ActiveItem = (tMenuOption *)&OverlayColumnMenuOptions[OVERLAYCOLS_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_OverlayColumns,
   .GetCurrentSetting = (void *)GetSetting_OverlayColumns,
   .CallbackOnSelect = true,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP
};

tMenu OverlayAlignmentMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&OverlayAlignmentMenuOptions[ALIGNMENT_MENU_MIN],
   .LastItem = (tMenuOption *)&OverlayAlignmentMenuOptions[ALIGNMENT_MENU_MAX],
   .SelectedItem = (tMenuOption *)&OverlayAlignmentMenuOptions[ALIGNMENT_MENU_MIN],
   .ActiveItem = (tMenuOption *)&OverlayAlignmentMenuOptions[ALIGNMENT_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_OverlayAlignment,
   .GetCurrentSetting = (void *)GetSetting_OverlayAlignment,
#ifdef MENU_DO_INSTANT_PREVIEW
   .CallbackOnSelect = true,
#else
   .CallbackOnSelect = false,
#endif
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP
};

tMenu OverlayTimeoutMenu =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&OverlayTimeoutMenuOptions[TIMEOUT_MENU_MIN],
   .LastItem = (tMenuOption *)&OverlayTimeoutMenuOptions[TIMEOUT_MENU_MAX],
   .SelectedItem = (tMenuOption *)&OverlayTimeoutMenuOptions[TIMEOUT_MENU_MIN],
   .ActiveItem = (tMenuOption *)&OverlayTimeoutMenuOptions[TIMEOUT_MENU_MIN],
   .ParentMenu =  NULL,
   .Callback = (void *)Callback_OverlayTimeout,
   .GetCurrentSetting = (void *)GetSetting_OverlayTimeout,
   .CallbackOnSelect = false,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP
};

tMenu SetAlarmTriggersMenu = 
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&AlarmTriggersMenuOptions[0],
   .LastItem = (tMenuOption *)&AlarmTriggersMenuOptions[0],
   .SelectedItem = (tMenuOption *)&AlarmTriggersMenuOptions[0],
   .ActiveItem = (tMenuOption *)&AlarmTriggersMenuOptions[0],
   .ParentMenu = NULL,
   .Callback = (void *)NULL,
   .GetCurrentSetting = NULL,
   .CallbackOnSelect = false,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP
};

tMenu ResetDefaultsMenu = 
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&ResetDefaultsMenuOptions[RESET_MENU_MIN],
   .LastItem = (tMenuOption *)&ResetDefaultsMenuOptions[RESET_MENU_MAX],
   .SelectedItem = (tMenuOption *)&ResetDefaultsMenuOptions[RESET_MENU_MIN],
   .ActiveItem = NULL,
   .ParentMenu = NULL,
   .Callback = (void *)Callback_ResetDefaults,
   .GetCurrentSetting = NULL,
   .CallbackOnSelect = false,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP
};

tMenu RS232_Menu =
{
   .MenuType = mnuMenu,
   .FirstItem = (tMenuOption *)&RS232_MenuItem[RS232_MENU_MIN],
   .LastItem = (tMenuOption *)&RS232_MenuItem[RS232_MENU_MAX],
   .SelectedItem = (tMenuOption *)&RS232_MenuItem[RS232_MENU_MIN],
   .ActiveItem = (tMenuOption *)&RS232_MenuItem[RS232_MENU_MIN],
   .ParentMenu = NULL,
   .Callback = NULL,
   .GetCurrentSetting = NULL,
   .CallbackOnSelect = false,
   .x = MENU_LEFT,
   .y = MENU_TOP,
};

const tMenuOption RS232_MenuActivateItem[1] =
{
   [0] =
   {
      .NextItem = (tMenuOption*)&RS232_MenuActivateItem[0],
      .PrevItem = (tMenuOption*)&RS232_MenuActivateItem[0],
      .NextMenu = (tMenu*)&RS232_Menu,
      .Caption =  "Setup RS232     ",
      .ItemHint = "Setup serial port Baud rate, data bits\r\nstop bits and parity"
   }
};

tMenu RS232_MenuActivate =
{
   .MenuType = mnuSetOption,
   .FirstItem = (tMenuOption *)&RS232_MenuActivateItem[0],
   .LastItem = (tMenuOption *)&RS232_MenuActivateItem[0],
   .SelectedItem = (tMenuOption *)&RS232_MenuActivateItem[0],
   .ActiveItem = (tMenuOption *)&RS232_MenuActivateItem[0],
   .ParentMenu = NULL,
   .Callback = NULL,
   .GetCurrentSetting = NULL,
   .CallbackOnSelect = false,
   .x = MENU_OPTIONS_LEFT,
   .y = MENU_OPTIONS_TOP,
};

const tMenuOption MainMenuItem[MAIN_MENU_ITEMS] =
{
   [0] =
   {      
      .NextItem = (tMenuOption*)&MainMenuItem[1],
      .PrevItem = (tMenuOption*)&MainMenuItem[MAIN_MENU_MAX],
      .NextMenu = (tMenu*)&RS232_MenuActivate,
      .Caption =  "RS232 Settings  ",
      .ItemHint = "Setup RS232 Serial Port"
   },
   [1] =
   {      
      .NextItem = (tMenuOption*)&MainMenuItem[2],
      .PrevItem = (tMenuOption*)&MainMenuItem[0],
      .NextMenu = (tMenu*)&TabStopMenu,
      .Caption =  "Tab Stop Size   ",
      .ItemHint = "Set Tab Stop size\r\n(typically 8)"
   },
   [2] =
   {
      .NextItem = (tMenuOption*)&MainMenuItem[3],
      .PrevItem = (tMenuOption*)&MainMenuItem[1],
      .NextMenu = (tMenu*)&TextSizeMenu,
      .Caption =  "Text Size       ",
      .ItemHint = "Select text font size",
   },
   [3] =
   {
      .NextItem = (tMenuOption*)&MainMenuItem[4],
      .PrevItem = (tMenuOption*)&MainMenuItem[2],
      .NextMenu = (tMenu*)&TextAttrMenu,
      .Caption = "Text/Background ",
      .ItemHint = "Select black or white text and \r\nbackground fill"
   },  
   [4] =
   {
      .NextItem = (tMenuOption*)&MainMenuItem[5],
      .PrevItem = (tMenuOption*)&MainMenuItem[3],
      .NextMenu = (tMenu*)&OverlayRowsMenu,
      .Caption = "Overlay Rows    ",
      .ItemHint = "Set number of rows overlay\r\ndisplay block will show",
   },
   [5] = 
   {
      .NextItem = (tMenuOption*)&MainMenuItem[6],
      .PrevItem = (tMenuOption*)&MainMenuItem[4],
      .NextMenu = (tMenu*)&OverlayColumnMenu,
      .Caption = "Overlay Columns ",
      .ItemHint = "Select 20 / 40 columns overlay display\r\nblock width",
   },
   [6] =
   {
      .NextItem = (tMenuOption*)&MainMenuItem[7],
      .PrevItem = (tMenuOption*)&MainMenuItem[5],
      .NextMenu = (tMenu*)&OverlayAlignmentMenu,
      .Caption =  "Overlay Alignmnt",
      .ItemHint = "Set alignment of overlay display block",
   },
   [7] =
   {
      .NextItem = (tMenuOption*)&MainMenuItem[8],
      .PrevItem = (tMenuOption*)&MainMenuItem[6],
      .NextMenu = (tMenu*)&OverlayTimeoutMenu,
      .Caption =  "Overlay Timeout ",
      .ItemHint = "Set the time delay between last POS \r\nactivity and when overlay display clears",
   },
//!!!!!!!!!!!
//   [80] =
//   {
//      .NextItem = (tMenuOption*)&MainMenuItem[11],
//      .PrevItem = (tMenuOption*)&MainMenuItem[9],
//      //TODO: Next menu must point to alarm triggers menu when implemented
//      .NextMenu = &MainMenu,
//      .Caption =  "Alarm Triggers  ",
//      .ItemHint = "Set the Alarm Trigger phrase(s)",
//   },
//   [11] =
//   {
//      .NextItem = (tMenuOption*)&MainMenuItem[0],
//      .PrevItem = (tMenuOption*)&MainMenuItem[10],
//      .NextMenu = (tMenu*)&ResetDefaultsMenu,
//      .Caption =  "RESET TO DEFAULT",
//      .ItemHint = "Reset all settings to factory defaults",
//   }
   [8]=
   {
      .NextItem = (tMenuOption*)&MainMenuItem[MAIN_MENU_MIN],
      .PrevItem = (tMenuOption*)&MainMenuItem[7],
      .NextMenu = (tMenu*)&ResetDefaultsMenu,
      .Caption =  "RESET TO DEFAULT",
      .ItemHint = "Reset all settings to factory defaults",
   }
};

tMenu MainMenu =
{
   .MenuType = mnuMenu,
   .FirstItem = (tMenuOption *)&MainMenuItem[0],
   .LastItem = (tMenuOption *)&MainMenuItem[MAIN_MENU_MAX],
   .SelectedItem = (tMenuOption *)&MainMenuItem[0],
   .ActiveItem = (tMenuOption *)&MainMenuItem[0],
   .ParentMenu = NULL,
   .Callback = NULL,
   .GetCurrentSetting = NULL,
   .CallbackOnSelect = false,
   .x = MENU_LEFT,
   .y = MENU_TOP,
};

#endif

#endif
