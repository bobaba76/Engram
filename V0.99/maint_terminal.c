#include <stdlib.h>
#include <string.h>
#include "global.h"
#include "init.h"
#include "text.h"
#include "utils.h"
#include "char_buffer.h"
#include "uart.h"
#include "maint_terminal.h"

// Set bit in return result for blocking receive functions indicating checksum error
#define FLAG_CHECKSUM_ERR 0x8000

tMaintenanceCmd MaintenanceCmd; // Updated in MaintGetCmd() once every cycle, only one cycle to use

//--------------------------------------------------------------------------------------------------
// If any bytes to transmit, do so
void MaintTxPoll()
{
   if (!MaintUart.TxQue->IsBufferEmpty && !MaintUart.Ctrl->Status.UTXBF)
   {
      MaintUart.Ctrl->TxReg = MaintUart.TxQue->GetChar(MaintUart.TxQue);
   }
}

//--------------------------------------------------------------------------------------------------
// Polls the maintenance port and if any data present in UART rx buffer, adds it to the que and
// returns true, else returns false
bool MaintRxPoll(void)
{
   char rx_char;
   
   bool result = false;
   
   
   if (U2STAbits.OERR)
   {
      U2STAbits.OERR = 0;
   }
   else if (U2STAbits.FERR)
   {   
      U2STAbits.FERR = 0;
   }
   else
   {     
      while (U2STAbits.URXDA)   
      {
         
         rx_char = U2RXREG;
         
         MaintRxQue.PutChar(&MaintRxQue, rx_char);
         
         result = true;
      }
   }   
 
//   if (MaintUart.Ctrl->Status.OERR)
//   {
//      MaintUart.Ctrl->Status.OERR = 0;
//   }
//   else if (MaintUart.Ctrl->Status.FERR)
//   {   
//      MaintUart.Ctrl->Status.FERR = 0;
//   }
//   else
//   {     
//      while (MaintUart.Ctrl->Status.URXDA)   
//      {
//         
//         rx_char = MaintUart.Ctrl->RxReg;
//         
//         MaintRxQue.PutChar(&MaintRxQue, rx_char);
//         
//         result = true;
//      }
//   }
   
   return result;
}

//--------------------------------------------------------------------------------------------------
// This function reads a block of data of an expected size. If less than the expected number of bytes
// is received. or there is a checksum error, then the function returns 0
// It is also blocking - we are setting the device up, not running it.
word MaintReadBlocking(byte *Buffer, int16 Count)
{
   int16 Timeout = 3000 + (Count * 25); // 20 ms + 160u * Count
   int16 Received = 0;
   word StartTime = TMR4;
   word Elapsed = 0;
   byte Checksum;
    
   while ((!MaintRxQue.IsBufferFull) && (MaintRxQue.Count < Count) && (Elapsed < Timeout))
   {
      MaintRxPoll();
      
      ClrWdt();
      
      Elapsed = TMR4 - StartTime;        
   }
   
   Received = MaintRxQue.Count;
   
   Checksum = MaintRxQue.CalcChecksum(&MaintRxQue);

   if ((Received == Count) && (Checksum == 0))
   {     
      while (MaintRxQue.Count > 1)
         *Buffer++ = MaintRxQue.GetChar(&MaintRxQue);     
   }
   else
   {
      Received = 0;
   }
   
   // Que still contains checksum
   MaintRxQue.Flush(&MaintRxQue); 
   
   return Received;
   
}
 
//--------------------------------------------------------------------------------------------------
// This function reads data until it times out. 
// Returns:
//    0  if nothing received
//    (bytes received & FLAG_CHECKSUM_ERR) if checksum mismatch
//    bytes received if no mismatch.
// If bytes received & checksum OK, places date in buffer.
int16 MaintReadStrBlocking(char *Buffer)
{
   int16 Timeout = 15000;   // About 100 ms
   int16 Received = 0;
   word StartTime = TMR4;
   word Elapsed = 0;
 
   while ((!MaintRxQue.IsBufferFull) && (Elapsed < Timeout))
   {
      if (MaintRxPoll())
      {
         StartTime = TMR4;
         Timeout = 50;
      }
      
      ClrWdt();
      
      Elapsed = TMR4 - StartTime;        
        
   }
   
   Received = MaintRxQue.Count;     

   if (Received > 0)
   {     
      if (MaintRxQue.CalcChecksum(&MaintRxQue) == 0)
      {
         while (MaintRxQue.Count > 1)
            *Buffer++ = MaintRxQue.GetChar(&MaintRxQue);
         // Terminate string
         *Buffer = 0x00;
      }
      else
      {
         Received = Received | FLAG_CHECKSUM_ERR;         
      } 
   }
   else
   {
      ;
   }
   
   // Que still contains checksum
   MaintRxQue.Flush(&MaintRxQue); 
     
   return Received;
   
}   

//--------------------------------------------------------------------------------------------------
// This function is used only during startup prior to main loop being operational
// Test to see if DTR is low && command received from terminal/bootloader. MUST be polled every 1 ms
// Returns true if bootloader commanded - DTR low and 0xC1 received via UART2
bool MaintTestForBootloadCmd(void)
{
   bool result = false;
   byte c;
   
   if (Debounced_BL_DTR() == 0)
   {
      if (MaintUart.Ctrl->Status.URXDA)
      {
         c = MaintUart.Ctrl->RxReg;

         // Check for bootload command with flags
         result = ((c & blFlagValidMask) == c);
      }
   }
   
   return result;
} 

//--------------------------------------------------------------------------------------------------
// Get commands from terminal / bootloader. Some commands emulate buttons on the device
bool MaintGetCmd(void)
{
 
   MaintenanceCmd = cmdNone;
   
   if (MaintRxQue.Count)
   {
      MaintenanceCmd = (byte)MaintRxQue.GetChar(&MaintRxQue); // MaintenanceCmd is signed!
   }
      
   return MaintenanceCmd != cmdNone;
}

//--------------------------------------------------------------------------------------------------
void MaintClrEOL(void)
{
   MaintPutStr("\x1B[K");
}   

//--------------------------------------------------------------------------------------------------
void MaintClrScr(void)
{
   MaintPutStr("\x1B[2J");
}

//--------------------------------------------------------------------------------------------------
void MaintGotoXY(const byte X, const byte Y)
{
   char buf[] = "\x1B[00;00H";
   div_t Temp;
   
   if (Y < TEXT_LINES)
   {
      Temp = div(Y + 1, 10);
      buf[2] += Temp.quot;
      buf[3] += Temp.rem;
   }
   if (Y < TEXT_COLUMNS)
   {
      Temp = div(X + 1, 10);
      buf[5] += Temp.quot;
      buf[6] += Temp.rem;
   }
   
   MaintPutStr(&buf[0]);
}

//--------------------------------------------------------------------------------------------------
void MaintScrollUp(void)
{
   MaintPutStr("\x1B""D");
}

//--------------------------------------------------------------------------------------------------
// Use when raw data must be received instead of MaintGetChar
byte MaintGetByte(void)
{
   if (!MaintUart.RxQue->IsBufferEmpty)
   {
      return MaintUart.RxQue->GetChar(MaintUart.RxQue);
   }
   else
   {
      return 0;
   }
}   

//--------------------------------------------------------------------------------------------------
bool MaintPutWord(word W)
{
   if (MaintPutChar(W & 0xFF) && MaintPutChar(W >> 8))
      return true;
   else
      return false;
}

//--------------------------------------------------------------------------------------------------
// Warning, substitutes null for space, 0x10 for '>'
bool MaintPutScreenChar(char c)
{
   if (!MaintUart.TxQue->IsBufferFull)
   {
      if (c == 0)
      {
         c = ' ';
      }
      else if (c == '\x10')
      {
         c = '>';
      }
      return MaintUart.TxQue->PutChar(MaintUart.TxQue, c);
   }
   else
   {
      return false;
   }
} 
      
   
//--------------------------------------------------------------------------------------------------
bool MaintPutChar(char c)
{
   if (!MaintUart.TxQue->IsBufferFull)
   {
      return MaintUart.TxQue->PutChar(MaintUart.TxQue, c);
   }
   else
   {
      return false;
   }
}   

//--------------------------------------------------------------------------------------------------
void MaintPutStr(char *AStr)
{
   word i = 0;
   
   while (AStr[i] != 0)  
   {
      MaintPutChar(AStr[i++]);
   }
}

//--------------------------------------------------------------------------------------------------
void MaintScreenDump(void)
{
   static byte Line = 0;
   byte EndLine;
   
   if (MaintUart.TxQue->IsBufferEmpty)
   {
      
      if (Line == 0)
      {
         MaintGotoXY(0, 0);
      }
      
      for (byte i = 0; i < TEXT_COLUMNS; i++)
      {
         MaintPutScreenChar(TextPage[Line][i]);
      }
            
      MaintPutStr("\r\n");
      
      if (fMenuIsActive)
      {
         EndLine = TEXT_LINES - 1;
      }
      else
      {
         EndLine = Settings.Overlay.Rows - 1;
      }
      
      if (Line >= EndLine)
      {
         Line = 0;
      }
      else
      {
         Line++;
      }
   }
   else
   {
      ;
   }
} 

//--------------------------------------------------------------------------------------------------
typedef struct tagRX_STR 
{
   byte index;
   char Str[41];
} tRxArrayString;
typedef char tArrayString[10][41];
tRxArrayString AStr;
tArrayString As;
void MaintHandleCmd()
{
  
   tBootload_Flags BL_Flags = 0;
    
   // Check for bootload command with flags
   if (((MaintenanceCmd & cmdDoBootload) == cmdDoBootload) &&
       ((MaintenanceCmd & blFlagValidMask) == MaintenanceCmd))
   {
      BL_Flags = (MaintenanceCmd & blFlagMask);
                  
      // And remove them from mask
      MaintenanceCmd &= blFlagCmdMask;            
   }
          
   // No command is caught by cmdNone clause
   switch (MaintenanceCmd) 
   {
      case cmdNone           : // No Command, just break
         break;   
         
      case cmdMenuKey        : // Emulate device Menu key
         SW_MENU = 1;
         break;
         
      case cmdUpArrowKey     : // "       "      Up Arrow key
         SW_UP = 1;
         break;
         
      case cmdDnArrowKey     : // "       "      Dn Arrow key
         SW_DN = 1;
         break;
         
      case cmdEscKey         : // "       "      Esc key
         SW_ESC = 1;
         break;
         
      case cmdCapture        : // Start capture to terminal    
         fCaptureToUSB = true;
         fEchoText = false;  
         break;
         
      case cmdEndCapture     : // End capture
         fCaptureToUSB = false;
         break;
         
      case cmdEchoText       : // Echo screen text to terminal
         fEchoText = true; 
         fCaptureToUSB = false;
         break;
         
      case cmdEndEchoText    : // End echo screen text to terminal
         fEchoText = false;
         break;
         
      case cmdDisableMenuEcho : // Disable menu echo to terminal
         fEchoMenu = false;
         break;
      
      case cmdEnableMenuEcho : // Enable menu echo to terminal
         fEchoMenu = true;
         break;
         
      case cmdWriteDeviceInfo : // Send software version, model etc.
         // Flags indicating which items are modifiable
         MaintPutWord(OEM_MODIFIABLE);
         MaintPutWord(VENDOR_MODIFIABLE);
         MaintPutWord(USER_MODIFIABLE);
         MaintPutWord(VENDOR_READABLE);
         MaintPutWord(USER_READABLE);
      
         // Strings and headings.
         for (int i = 0; i < OEM_SETTINGS_STR_COUNT; i++)
         {
            MaintPutStr((char*)OEM_TITLE_STR[i]);
            MaintPutStr("\r\n");
            MaintPutStr((char*)OEM_STRING_INDEX[i]);
            MaintPutStr("\r\n");
         }
         
         MaintPutStr("Video System\r\n");
         MaintPutStr((char*)VIDEO_SYSTEM_STR[VideoSystem]);
         MaintPutStr("\r\n");
         
         MaintPutStr("Checksum\r\n");
         MaintPutStr(IntToHex(FLASH_CHECKSUM.Sum));
         break;
         
      case cmdReadDeviceInfo : // Get software version, model etc.
         {
            int16 Received;
            
            Received = MaintReadStrBlocking((char*)&AStr);

            // Check for no string or checksum error
            if (!Received || (Received & FLAG_CHECKSUM_ERR))
            {
               MaintPutChar('E');
            }
            else
            {
               if (AStr.index < OEM_SETTINGS_STR_COUNT)
                  Store_OEM_Setting(AStr.index, AStr.Str);
               MaintPutChar('K');              
            }   
         }
         break;
         
      case cmdWriteSettings   : // Send settings, include NULLs in strings.
         {        
            byte *AByte = (byte*)&Settings;
            byte Checksum = 0;
            int16 i;
            
            for (i = 0; i < sizeof(tSettings); i++)
            {
               Checksum += *AByte;
               MaintPutChar(*AByte++);
            }
            
            Checksum = ((byte)255 - Checksum) + 1;
            MaintPutChar(Checksum);
            
         }
         break;
         
      case cmdReadSettings    : // Get settings, including NULL padded strings.
         {
            byte *AByte = (byte*)&Settings;
            word Received;
   

            Received = MaintReadBlocking(AByte, sizeof(tSettings) + 1); // Allow for checksum
            if (Received == sizeof(tSettings) + 1)
            {
               // Make sure we erase whole screen & not just window
               FullScreen();
               ClrScr();
               StoreSettings();
               ApplySettings();
               MaintPutChar('K'); // Transmit OK code               
            }
            else
            {
               // Restore possibly corrupted settings
               Settings = STORED_SETTINGS.Data;
               MaintPutChar('E'); // Transmit error code
            }
         }
         break;
         
      case cmdQueryPresence  : // Respond with 'P'
         MaintPutChar('P');
         break;

      case cmdDoBootload:      // Start bootloader            
         if (Bootload_DTR == low)
            SwReset();
         break;
         
      default :
         break;
         
   }
}         
