#ifndef TYPEDEFS_H
#define TYPEDEFS_H

#ifdef __C30__

#include <stdbool.h>

typedef unsigned char byte;
typedef unsigned char uchar;
typedef signed char int8;
typedef unsigned int word;
typedef unsigned int uint16;
typedef signed int int16;
typedef signed long int32;
typedef signed long Q16;
typedef unsigned long uint32;

enum {low = 0, high = 1};

#ifndef NULL
 #define NULL	0U
#endif /* NULL */
typedef enum tagVLED {vledOff, vledRed, vledOrange, vledGreen}  tVLED;
typedef enum tagVIDEO_SYSTEM {vidPAL, vidNTSC, vidMAX} tVideoSystem;

__extension__ typedef union tagTQ16_ACCESS
{
   Q16 AsQ16;
   struct
   {
      int16 Fraction;
      int16 Integer;
   };
} tQ16_Access;

typedef struct tagT_FILTER
{
  tQ16_Access  Y;             // Output
  tQ16_Access  Coefficient;   // Filter co-efficient
}  tFilter, *pFilter;  

typedef struct tagTPOINT
{
   int8 X;
   int8 Y;
} tPoint;

typedef union tagTRECTANGLE
{
   byte X1;
   byte Y1;
   byte X2;
   byte Y2;
} tRectangle;

typedef enum tagPARITY
{
   parityNone,
   parityEven,
   parityOdd
} tParity;   

typedef enum tagOVERLAY_ALIGNMENT
{
   alignTopLeft,
   alignTopRight,
   alignBottomLeft,
   alignBottomRight
} tOverlayAlignment;
#define OVERLAY_ALIGNMENT_MIN alignTopLeft
#define OVERLAY_ALIGNMENT_MAX alignBottomRight

typedef enum tagTEXT_COLOR
{
   clrBlack,
   clrWhite
} tTextColor;

typedef enum tagTEXT_BKGND
{
   bkgndNone,
   bkgndTranslucent,
   bkgndGrey,
   bkgndBlack
} tTextBkgnd;

typedef enum tagTEXT_ATTIBUTE
{
   attrBlack_NoBkgnd,
   attrWhite_NoBkgnd,
   attrBlack_TranslucentBkgnd,
   attrWhite_TranslucentBkgnd,
   attrBlack_GreyBkgnd,
   attrWhite_GreyBkgnd,
   attrWhite_BlackBkgnd
} tTextAttribute;
#define TEXT_ATTRIBUTE_MIN attrBlack_NoBkgnd
#define TEXT_ATTRIBUTE_MAX attrWhite_BlackBkgnd

typedef char tAlarmTriggers[8][21];

typedef struct tagBYTE_BITS
{
   bool b0:1;
   bool b1:1;
   bool b2:1;
   bool b3:1;
   bool b4:1;
   bool b5:1;
   bool b6:1;
   bool b7:1;
} tByteBits;

typedef struct tagWORD_BITS
{
   bool b0:1;
   bool b1:1;
   bool b2:1;
   bool b3:1;
   bool b4:1;
   bool b5:1;
   bool b6:1;
   bool b7:1;
   bool b8:1;
   bool b9:1;
   bool b10:1;
   bool b11:1;
   bool b12:1;
   bool b13:1;
   bool b14:1;
   bool b15:1;
} tWordBits;
   
__extension__ typedef union tagBYTE_ACCESS
{
   byte AsByte;
   struct
   {
      bool b0:1;
      bool b1:1;
      bool b2:1;
      bool b3:1;
      bool b4:1;
      bool b5:1;
      bool b6:1;
      bool b7:1;
   };
} tByteAccess;

__extension__ typedef union tagWORD_ACCESS
{
   word AsWord;
   struct
   {
      byte lo;
      byte hi;
   };
   struct
   {
      bool b0:1;
      bool b1:1;
      bool b2:1;
      bool b3:1;
      bool b4:1;
      bool b5:1;
      bool b6:1;
      bool b7:1;
      bool b8:1;
      bool b9:1;
      bool b10:1;
      bool b11:1;
      bool b12:1;
      bool b13:1;
      bool b14:1;
      bool b15:1;
   };
} tWordAccess;  

typedef struct tag_UART
{
   uint32   BaudRate;
   word     DataBits;
   word     StopBits;
   tParity  Parity;
} tUART;

typedef struct tag_TEXT_SETTINGS
{
   word                 Size;
   tTextAttribute       Attribute;
   word                 TabSize;
} tTextSettings;

typedef struct tag_OVERLAY_SETTINGS
{
   word                 Rows;
   word                 Columns;
   tOverlayAlignment    Alignment;
   word                 Timeout;
} tOverlaySettings;   

typedef struct tagSETTINGS
{
   tUART                UART;
   tTextSettings        Text;
   tOverlaySettings     Overlay;
   tAlarmTriggers       AlarmTriggers;  
} tSettings, *ptSettings;

typedef struct tagSTORED_SETTINGS
{
   // Data is stored with its complement, so that the checksum does not change when
   // a setting changes.
   word      Checksum;              // Locate these two fields at beginning of struct - make it 
   word      ChecksumComplement;    // easy for bootloader to locate.
   tSettings Data;
   tSettings DataComplement;
   word      IsInitialised;           // Flag checked on startup 
   word      IsInitialisedComplement;         
} tStoredSettings, *pStoredSettings;

#define OEM_STR_MAX_LENGTH 41 /* 40 chars + terminating char */
// Settings that cannot be changed by user
typedef char OEM_String[OEM_STR_MAX_LENGTH];
typedef struct tagOEM_SETTINGS
{
   OEM_String Copyright;
   OEM_String OEM_Name;
   OEM_String OEM_Contact;
   OEM_String VendorName;
   OEM_String VendorContact;
   OEM_String ProductName;
   OEM_String ProductDescription;
   OEM_String SwVersion;
   OEM_String HwVersion;
} tOEM_Settings, *pOEM_Settings;

// Settings with checksum and "is set" flags
typedef struct tagSTORED_OEM_SETTINGS
{
   word Checksum;
   word ChecksumComplement;
   tOEM_Settings Data;
   tOEM_Settings DataComplement;
   word      IsInitialised;           // Flag checked on startup 
   word      IsInitialisedComplement;        
} tStored_OEM_Settings, *pStored_OEM_Settings;

typedef enum tagCTRL_ALPHA
{	
   ctrl_at,
   ctrl_A,
   ctrl_B,
   ctrl_C,
   ctrl_D,
   ctrl_E,
   ctrl_F,
   ctrl_G,
   ctrl_H,
   ctrl_I,
   ctrl_J,
   ctrl_K,
   ctrl_L,
   ctrl_M,     
   ctrl_N,
   ctrl_O,
   ctrl_P,
   ctrl_Q,
   ctrl_R,
   ctrl_S,
   ctrl_T,
   ctrl_U,
   ctrl_V,
   ctrl_W,
   ctrl_X,
   ctrl_Y,
   ctrl_Z
} tCtrlAlpha;

typedef struct tag_FLASH_CHECKSUM
{
   uint16 Sum;
   uint16 SumComplement;
   uint16 IsSet;
   uint16 IsSetComplement;
} tFlashChecksum;


// Check the data type sizes are as expected, especially unions
//----------------------------------------------------------------
// GCC does not support "sizeof" in preprocessor conditionals - the following macro is
// a workaround: it creats an enum where invoked  e.g: if invoked on line 69, will
// generate "enum {__STATIC_ASSERT__69 = 0};" if assertion OK, but causes an error if
// assertion fails. There is no run-time penalty, as no code is generated.
// Macro derived from http://www.pixelbeat.org/programming/gcc/static_assert.html

#ifndef _lint  
#define _CONCAT_(a, b) a ## b
#define CONCAT(a, b) _CONCAT_(a, b)
#define STATIC_ASSERT(assertion) enum { CONCAT(__STATIC_ASSERT__ ,__LINE__) = 1/(!!(assertion)) }
#endif /*_lint*/

STATIC_ASSERT(sizeof(tByteBits) == 1);
STATIC_ASSERT(sizeof(tByteAccess) == 1);
STATIC_ASSERT(sizeof(tWordAccess) == 2);
STATIC_ASSERT(sizeof(bool) == 1);
STATIC_ASSERT(sizeof(tFlashChecksum) == 8);

#endif

#endif
