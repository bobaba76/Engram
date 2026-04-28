#include <string.h>

#include "global.h"
#include "maint_terminal.h"
#include "char_buffer.h"
#include "font.h"
#include "utils.h"

#define TEXT_C
#include "text.h"
#undef TEXT_C

byte TextPage[TEXT_LINES][TEXT_COLUMNS];

static tPoint Cursor = {0, 0};    // The cursor is always referenced to the current window

bool fEchoText = false;
bool fEchoMenu = false;
bool TextPause = false;
bool fStatusFlasher = false;

const tWindow FULL_SCREEN = {0, 0, TEXT_COLUMNS, TEXT_LINES};

static tWindow TextWindow = {0, 0, TEXT_COLUMNS, TEXT_LINES};

static tWindow OverlayWindow = {0, 0, TEXT_COLUMNS, TEXT_LINES};

static tTextColor CurrentTextColor = clrBlack;

//--------------------------------------------------------------------------------------------------
static inline byte ScreenX(byte WindowX)
{
   return (TextWindow.Left + WindowX);
}
//--------------------------------------------------------------------------------------------------

static inline byte ScreenY(byte WindowY)
{
   return (TextWindow.Top + WindowY);
}   
//--------------------------------------------------------------------------------------------------
static inline tPoint ScreenPoint(tPoint WindowPoint)
{
   tPoint Result;
   
   Result.X = ScreenX(WindowPoint.X);
   Result.Y = ScreenY(WindowPoint.Y);
   
   return Result;
}   

//--------------------------------------------------------------------------------------------------
static inline void ScreenPut(char c)
{
   TextPage[ScreenY(Cursor.Y)][ScreenX(Cursor.X)] = c;
}   

//--------------------------------------------------------------------------------------------------
bool TextIsEOL(void)
{
   return Cursor.X >= TextWindow.Width;
}

//--------------------------------------------------------------------------------------------------
void ClrTextWindow(void)
{  
   for (byte row = TextWindow.Top; row < TextWindow.Top + TextWindow.Height; row++)
   {
      for (byte col = TextWindow.Left; col < TextWindow.Left + TextWindow.Width; col++)
      {
         TextPage[row][col] = 0;
      }
   }
   
   Cursor.X = 0;
   Cursor.Y = 0;
}

//--------------------------------------------------------------------------------------------------
void ClrScr(void)
{

   ClrTextWindow();
     
//   if (fEchoText || fMenuIsActive)
//   {
//      MaintClrScr();
//   }   
}

//--------------------------------------------------------------------------------------------------
void SetTextWindow(const byte Left, const byte Top, const byte Width, const byte Height)
{
   if (Left > (TEXT_COLUMNS - 2))
      TextWindow.Left = TEXT_COLUMNS - 2;
   else
      TextWindow.Left = Left;
      
   if (Top > (TEXT_LINES - 2)) 
      TextWindow.Top = TEXT_LINES - 2;
   else
      TextWindow.Top = Top;
      
   if (Width > (TEXT_COLUMNS - Left))
      TextWindow.Width = TEXT_COLUMNS - Left;
   else
      TextWindow.Width = Width;
      
   if (Height > (TEXT_LINES - Top))
      TextWindow.Height = TEXT_LINES - Top;
   else
      TextWindow.Height = Height;
   
   Cursor.X = 0;
   Cursor.Y = 0;

}

//--------------------------------------------------------------------------------------------------
void FullScreen(void)
{
   TextWindow = FULL_SCREEN;
   
   Cursor.X = 0;
   Cursor.Y = 0;
}   

//--------------------------------------------------------------------------------------------------
void AssignTextWindow(const tWindow AWindow)
{
   TextWindow = AWindow;
}

//--------------------------------------------------------------------------------------------------
tWindow GetTextWindow(void)
{
   tWindow AWindow = TextWindow;
   return AWindow;
}

//--------------------------------------------------------------------------------------------------
void ClrEOL(void)
{  
   for (byte X = ScreenX(Cursor.X), Y = ScreenY(Cursor.Y)
       ; X < ScreenX(TextWindow.Width)
       ; X++)
   {
      TextPage[Y][X] = 0;
   }
}   

//--------------------------------------------------------------------------------------------------
void GotoXY(const byte X, const byte Y)
{
   Cursor.X = X;
   Cursor.Y = Y;
}

//--------------------------------------------------------------------------------------------------
// Goto one past last char in line
void GotoEOL(void)
{
   GotoXY(TextWindow.Width, Cursor.Y);
}   

//--------------------------------------------------------------------------------------------------
byte GetCursorX(void)
{
   return Cursor.X;
}

//--------------------------------------------------------------------------------------------------
byte GetCursorY(void)
{
   return Cursor.Y;
}

//--------------------------------------------------------------------------------------------------
tPoint GetCursor(void)
{
   return Cursor;
}

//--------------------------------------------------------------------------------------------------
void SetCursor(const tPoint Point)
{
   // Constrain the cursor to the current window size + 1 - prevents problems when changing window
   // size & screen is scrolling, such as when status line is activated
   Cursor.X = Limit(Point.X, 0, TextWindow.Width);
   Cursor.Y = Limit(Point.Y, 0, TextWindow.Height);
}

////--------------------------------------------------------------------------------------------------
//void WriteChar(const char c)
//{      
//   word NextTabStop;
//   static bool IsNewLine = false;
//   bool IsEOL;
//   bool IsWindowBottom = Cursor.Y >= TextWindow.Height - 1;
//   
//   // Precaution in case Y > WindowBottom
//   if (IsWindowBottom)
//      Cursor.Y = TextWindow.Height - 1;
//   
//   if (IsNewLine) // !! (Cursor.X > TextWindow.Width - 1)
//   {
//      if (!IsWindowBottom)
//      {
//         Cursor.X = 0;
//         Cursor.Y++;
//      }
//      else
//      {
//         ScrollUp();
//      }
//   }
//   
//   if (c == '\r')
//      Nop();
//   
//   if (c == '\n')
//      Nop();
//      
//   if (IsNewLine)
//      Nop();
//    
//   IsEOL = (Cursor.X >= TextWindow.Width - 1) || ((c == '\n') && !IsNewLine); 
//   
//   if (IsEOL)
//      Nop();
//      
//
//
//   if (c != '\r')
//      IsNewLine = false;
//   // Wrap around?
//   if (IsEOL && (c != '\r') && (c != '\b'))
//   {
//      // Yes
//      IsNewLine = true; 
//      TextPause = IsWindowBottom;
//   }
//   
//
//   // Handle character
//   switch (c)
//   {
//      // Line feed
//      case '\n':
////         if (!IsEOL)
////         {
////            IsNewLine = true;
////
////            TextPause = IsWindowBottom;
////         }            
//         break;
//         
//      // Carriage return
//      case '\r':
//         Cursor.X = 0;
//         break;
//         
//      // Horizontal tab
//      case '\t':
//         // Our co-ord system is zero based, so we have to compensate for that here
//         // Note: CurX points to the NEXT char location.
//         NextTabStop = (((Cursor.X / Settings.TabStopSize) + 1) * Settings.TabStopSize);
//         
//         for (word i = Cursor.X; i < NextTabStop; i++)
//         {
//            WriteChar(' ');
//         }
//         
//         break;
//      
//      // Backspace
//      case '\b':         
//         if (Cursor.X > 0)
//         {
//            Cursor.X--;
//         }
//         else if (Cursor.Y > 0)
//         {
//            Cursor.X = TextWindow.Width - 1;
//            Cursor.Y--;
//         }
//         
//         ScreenPut(0);
//         
//         break;
//         
//      // Vertical tab
//      case '\v':
//         Cursor.X = 0;
//            
//         for (byte i = 0; i < 6; i++)
//         {
//            Cursor.Y++;
//            if (Cursor.Y >= TextWindow.Height - 1)
//            {
//               ScrollUp();
//               
//               Cursor.Y = TextWindow.Height - 1;
//  
//            } 
//         }
//         
//         break;             
//            
//      default:        
//   
//         ScreenPut(c - FONT_OFFS);
//   
//         Cursor.X++; 
//   
//         break;
//   }
//
//}

////--------------------------------------------------------------------------------------------------
void WriteChar(const char c)
{      
   word NextTabStop;
   
   bool IsEOL;
      
   // Wrap around ?
   if ((Cursor.X >= TextWindow.Width) && (c != '\n') && (c != '\r'))
   {
      // Yes 
      Cursor.X = 0;
      Cursor.Y++;
      
   }
   
   // Need to scroll up
   if (Cursor.Y >= TextWindow.Height)
   {
      // Yes
      ScrollUp();
      
      Cursor.Y = TextWindow.Height - 1;
   }
   
   // Handle character
   switch (c)
   {
      // Line feed
      case '\n':
         Cursor.Y++;
         
         // Is it the char at the end of the line
         if (Cursor.X >= TextWindow.Width - 1)
         {
            Cursor.X = 0;
         }
         break;
         
      // Carriage return
      case '\r':
         Cursor.X = 0;
         break;
         
      // Horizontal tab
      case '\t':
         // Our co-ord system is zero based, so we have to compensate for that here
         // Note: CurX points to the NEXT char location.
         NextTabStop = (((Cursor.X / Settings.Text.TabSize) + 1) * Settings.Text.TabSize);
         
         for (word i = Cursor.X; i < NextTabStop; i++)
         {
            WriteChar(' ');
         }
         
         break;
      
      // Backspace
      case '\b':         
         if (Cursor.X > 0)
         {
            Cursor.X--;
         }
         else if (Cursor.Y > 0)
         {
            Cursor.X = TextWindow.Width - 1;
            Cursor.Y--;
         }
         
         ScreenPut(0);
         
         break;
         
      // Vertical tab
      case '\v':
         Cursor.X = 0;
            
         for (byte i = 0; i < 6; i++)
         {
            Cursor.Y++;
            if (Cursor.Y >= TextWindow.Height - 1)
            {
               ScrollUp();
               
               Cursor.Y = TextWindow.Height - 1;
  
            } 
         }
         
         break;             
            
      default:        
   
         ScreenPut(c - FONT_OFFS);
   
         Cursor.X++; 
   
         break;
   }

 
   IsEOL = ((Cursor.X >= TextWindow.Width) || (c == '\n'));

   TextPause = (IsEOL &&  (Cursor.Y >= TextWindow.Height - 1)); 
   
}
//
//--------------------------------------------------------------------------------------------------
void WriteStr(const char String[])
{
   char *c = (char*)&String[0];

   while (*c != '\0')
   {
      WriteChar(*(c++));
   }
}

//--------------------------------------------------------------------------------------------------
void WriteFill(const char FillChar, const byte Count)
{
   for (byte i = 0; i < Count; i++)
   {
      WriteChar(FillChar);
   }
}

//--------------------------------------------------------------------------------------------------
void WriteStrXY(byte X, byte Y, bool RightJustify, const char String[])
{
   if (RightJustify)
   {
      byte len = strlen(&String[0]);
      
      if (X > len)
         X -= len;
      else
         X = 0;
   }

   GotoXY(X, Y);
   WriteStr(String);

}  

//-------------------------------------------------------------------------------------------------- 
void ScrollUp(void)
{     
   byte *line1;
   byte *line2;
   
   for (byte Y = TextWindow.Top; Y < TextWindow.Top + TextWindow.Height; Y++)
   {
      line1 = &TextPage[Y][TextWindow.Left];
      line2 = &TextPage[Y+1][TextWindow.Left];
      memcpy(line1, line2, TextWindow.Width);
   }
   
   GotoXY(0, TextWindow.Height - 1);
   
   ClrEOL();   
}

//--------------------------------------------------------------------------------------------------
void SetTextSize(const byte NewSize)
{
   float FSPI;              
   float TSPI;
   
   bool SaveSPI_En = SPI1STATbits.SPIEN;
   byte SaveOC3_OCM = OC3CONbits.OCM;
   bool SaveDMA1_EN = DMA1CONbits.CHEN;
     
   if (NewSize < 3)
   {
      FontCharSpace = 2;
   }
   else
   {
      FontCharSpace = 1;
   }

   if (NewSize < 5) 
   {
      SPI_Prescaler = NewSize + 1;
   }
   else
   {
      SPI_Prescaler = 5;
   }
   
   TextSize = NewSize;

   FSPI = (FCYC) / (float)SPI_Prescaler;
   
   TSPI = 1.0F / FSPI;
   
   CyclesPerChar = (word)(((TSPI) * (FONT_WIDTH + FontCharSpace)) / (TCYC));
   PR2 = CyclesPerChar - 1;
   
   SPI1STATbits.SPIEN = 0;
   OC3CONbits.OCM = 0;
   DMA1CONbits.CHEN = 0; 
   
   OC3RS = SPI_Prescaler;
   
   SPI1CON1bits.SPRE = 0x100 - SPI_Prescaler;
   
   SPI1STATbits.SPIEN = SaveSPI_En;
   OC3CONbits.OCM = SaveOC3_OCM;
   DMA1CONbits.CHEN = SaveDMA1_EN;
   
   SetOverlayAlignment(Settings.Overlay.Alignment);

}                          

//--------------------------------------------------------------------------------------------------
void SetTextBackground(const tTextBkgnd NewTextBackground)
{
   switch (NewTextBackground)
   {
      case bkgndNone:
         // Disable translucent background, enable solid
         TrisTextTrnsBkgnd = 0;
         LatTextTrnsBkgnd = 0;
       
         // Drive TextBgnd permanently off
         TrisTextSolidBkgnd  = 0;
         LatTextSolidBkgnd = 0;    
         
         // Turn off SPI output
         IO_Unlock();
         
         //oTextSolidBkgnd = PPS_MAP_SDO2;
         oTextSolidBkgnd = PPS_MAP_NULL;
         oTextTrnsBkgnd = PPS_MAP_NULL;
         
         IO_Lock();
         
         TextBackgroundFill = 0;
         
         break;
         
      case  bkgndTranslucent:
         // Enable translucent background, disable solid
         
         // Drive TextBgnd permanently off
         TrisTextSolidBkgnd = 0;
         LatTextSolidBkgnd = 0;
         
         TextBackgroundFill = 0xFF;   
         
         IO_Unlock();
         oTextSolidBkgnd = PPS_MAP_NULL;
         oTextTrnsBkgnd = PPS_MAP_SDO2;
         IO_Lock();
         
         break;
         
      case  bkgndGrey:
         // Disable translucent background, enable solid
         TrisTextTrnsBkgnd = 0;
         LatTextTrnsBkgnd = 0;
         
         TrisTextBkgndLevel = 0;
         oTextBkgndLevel = 1;
         
         TextBackgroundFill = 0xFF;   
         
         IO_Unlock();
         
         oTextSolidBkgnd = PPS_MAP_SDO2;
         oTextTrnsBkgnd = PPS_MAP_NULL;
         
         IO_Lock();
      
         break;
      case  bkgndBlack:
      
         TrisTextBkgndLevel = 1;
         TextBackgroundFill = 0xFF;      
         
         IO_Unlock();
         oTextSolidBkgnd = PPS_MAP_SDO2;
         oTextTrnsBkgnd = PPS_MAP_NULL;
         IO_Lock();

         break;
      default:
         break;
   }      
}   

//--------------------------------------------------------------------------------------------------
void SetTextColor(const tTextColor NewTextColor)
{  
   CurrentTextColor = NewTextColor;
   
   switch (CurrentTextColor)
   {
      case clrBlack:
         OC2RS = TEXT_LEVEL_BLACK;
         
         break;
         
      case  clrWhite:
         OC2RS = VideoWhiteLevel;
         break;
         
      default:
         break;         
   }      
}   

//--------------------------------------------------------------------------------------------------
tTextColor GetTextColor(void)
{
   return CurrentTextColor;
}

//--------------------------------------------------------------------------------------------------
void SetTextAttribute(const tTextAttribute NewTextAttribute)
{   
  
   switch (NewTextAttribute)               
   {
      case attrBlack_NoBkgnd :
         SetTextColor(clrBlack);
         SetTextBackground(bkgndNone);
         break;
      case attrWhite_NoBkgnd :
         SetTextColor(clrWhite);
         SetTextBackground(bkgndNone);
         break;
      case attrBlack_TranslucentBkgnd :
         SetTextColor(clrBlack);
         SetTextBackground(bkgndTranslucent);
         break;
      case attrWhite_TranslucentBkgnd :
         SetTextColor(clrWhite);
         SetTextBackground(bkgndTranslucent);
         break;
      case attrBlack_GreyBkgnd :
         SetTextColor(clrBlack);
         SetTextBackground(bkgndGrey);
         break;
      case attrWhite_GreyBkgnd :
         SetTextColor(clrWhite);
         SetTextBackground(bkgndGrey);
         break;
      case attrWhite_BlackBkgnd:
         SetTextColor(clrWhite);
         SetTextBackground(bkgndBlack);
         break;
      default :
         break;
   }
}

//--------------------------------------------------------------------------------------------------
void SetOverlayAlignment(const tOverlayAlignment NewOverlayAlignment)
{
   word RowCycles = CyclesPerChar * TEXT_COLUMNS;
                
   switch (NewOverlayAlignment)
   {
      case alignTopLeft :
            // Drop through            
      case alignBottomLeft:
         CyclesTimer2Preload = ((word)(-(CYCLE_TEXT_LEFT_ALIGN)));
         break;

      case alignTopRight :
            // Drop through
      case alignBottomRight :
         CyclesTimer2Preload = ((word)(-((CYCLE_TEXT_RIGHT_ALIGN) - RowCycles - 1)));
         break;

      default :
         CyclesTimer2Preload = ((word)(-(CYCLE_TEXT_LEFT_ALIGN)));
         break;
   }
   
   OC1R  = ((word)(CyclesTimer2Preload + (CYCLE_BURST_START)));
   OC1RS = ((word)(CyclesTimer2Preload + (CYCLE_BURST_END)));
}   

//--------------------------------------------------------------------------------------------------
void SetOverlayWindow(void)
{
   byte Left;   
   byte Top;
   byte Height = Settings.Overlay.Rows;
   byte Width = Settings.Overlay.Columns;

   switch (Settings.Overlay.Alignment)
   {
      case alignTopLeft :
         Left = 0;
         Top = 0;
         break;
      case alignTopRight :
         Left = TEXT_COLUMNS - Settings.Overlay.Columns;
         Top = 0;
         break;
      case alignBottomLeft:
         Left = 0;
         Top = TEXT_LINES - Settings.Overlay.Rows;
         break;
      case alignBottomRight :
         Left = TEXT_COLUMNS - Settings.Overlay.Columns;
         Top = TEXT_LINES - Settings.Overlay.Rows;
         break;
      default :
         Left = 0;
         Top = 0;
         break;
   }
   
   if (fStatusLineIsActive)
   {
      if ((STATUS_LINE_ROW == 0) && (Top == 0))
      {
         Top++;
      }
      else if (STATUS_LINE_ROW == (Top + Height -1))
      {
         Height--;
      }
      else
      {
         ; // Do Nothing
      }
   }
   else
   {
      ; // Do Nothing
   }
   
   OverlayWindow.Left = Left;
   OverlayWindow.Top = Top;
   OverlayWindow.Width = Width;
   OverlayWindow.Height = Height;
   
     
   SetTextWindow(Left, Top, Width, Height);
}

//--------------------------------------------------------------------------------------------------
tWindow GetOverlayWindow(void)
{
   return OverlayWindow;
}

//--------------------------------------------------------------------------------------------------
void SetTabStopSize(const byte TabSize)
{   
   Settings.Text.TabSize = TabSize;
}

//--------------------------------------------------------------------------------------------------
// DOES NOT WORK IF MENU ACTIVE
void StatusLinePutStr(const char *StatusStr)
{

   // The status line is disabled when the string is empty - test for it & set flag accordingly
   fStatusLineIsActive = (StatusStr[0] != '\0');
   
   // Save the current writing position
   tPoint Point = GetCursor();

   // Open the status line window
   SetTextWindow(0, STATUS_LINE_ROW, TEXT_COLUMNS, 1); 
   
   // Erase status area
   ClrScr();
   
   // Write the string out
   WriteStr(StatusStr);
   
   // And revert to the now resized overlay window and cursor location
   SetOverlayWindow();
   
   SetCursor(Point);
  
}
   

//--------------------------------------------------------------------------------------------------
// DOES NOT WORK IF MENU ACTIVE
void StatusLineClr(void)
{
   if (!fMenuIsActive)
   {
      StatusLinePutStr("");
      
      // It the status line is inactive, the window is now one line bigger - we need to adjust the 
      // cursor so that if we are busy writing to the screen when the status line is removed, writing
      // will continue at the sameplace.
      if (!fStatusLineIsActive && (Cursor.Y > STATUS_LINE_ROW))
      {
         Cursor.Y++;
      }
   }
}

//--------------------------------------------------------------------------------------------------
