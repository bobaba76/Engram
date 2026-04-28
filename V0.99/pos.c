#include <string.h>

#include "global.h"
#include "utils.h"
#include "pos_esc.h"
#include "uart.h"
#include "sw_timer.h"
#include "text.h"

#include "pos.h"

bool Poll_POS_Rx(void)
{
   bool Result = false;
   
   if (U1STAbits.OERR)
   {
      U1STAbits.OERR = 0;
   }
   else if (U1STAbits.FERR)
   {
      U1STAbits.FERR = 0;
   }
   else
   {
      Result = U1STAbits.URXDA;
   }
   
   return Result;
}

//--------------------------------------------------------------------------------------------------
void Handle_POS_Rx(void)
{
   tEscSequenceResult EscTestResult = {0, -1};

   unsigned char POS_RxChar = U1RXREG;
   
   static byte SpaceCount = 0;

   // If menu not active, process char
   if (!fMenuIsActive)
   {
      #if defined(IGNORE_POS_EIGHTH_BIT)
      POS_RxChar = POS_RxChar & 0x7F;
      #else
      if (Settings.UART.DataBits == 7u)
         POS_RxChar = POS_RxChar & 0x7F;
      #endif

      // Capturing to USB needs to be done before processing esc codes, line feeds etc.
      if (fCaptureToUSB)
      {
         if ((POS_RxChar >= SP) && (POS_RxChar < 128))
         {
            while (MaintUart.Ctrl->Status.UTXBF);
            
            MaintUart.Ctrl->TxReg = POS_RxChar;
         }
         else
         {
            // print ctrl code as decimal, surrounded by brackets.
            char buf[6] = "[";
            
            strcat(&buf[0], IntToStr(POS_RxChar, 0));
            strcat(&buf[0], "]");

            for (byte i = 0; i < strlen(buf); i++)
            {
            while (MaintUart.Ctrl->Status.UTXBF);

            MaintUart.Ctrl->TxReg = buf[i];
            }
         }
      }

      POS_RxChar = TestAndHandleEOL(POS_RxChar);

      EscTestResult = TestForEscSequence(POS_RxChar);

      switch (EscTestResult.State)
      {
         case escNone:
//TODO: This really need tidying up ....

            // Compress spaces - place first space followed by count - even a single space
            // gets a count of 1, but overall there should be a reduction, because POS
            // till slips use a lot of spaces.
            if (POS_RxChar == SP)
            {
//               if (SpaceCount == 0)
//               {
                  // First space
                  POS_RxQue.PutChar(&POS_RxQue, SP);
//               }
//               else
//               {
//                  ; // Do nothing
//               }   
//
//               SpaceCount++;
            }
            else
            {
//!!!!               if (SpaceCount)
//               {
//                  POS_RxQue.PutChar(&POS_RxQue, SpaceCount);
//                  SpaceCount = 0;
//               }
               
               // No matching escape code - if unused control code, fallback & ignore char
               if (POS_RxChar == CR)
               {
                  // Internally we expect CR+LF
                  // Will work on DOS/Windows machine as well as Mac, but not Linux
                  POS_RxQue.PutStr(&POS_RxQue, "\r\n");
   
                  // Was EOL, so no need to do a timed EOL
                  SwTimer[POS_LINE_TMR].Run = false;
               }
               else if (((POS_RxChar > SP) && (POS_RxChar < 128u)) || (POS_RxChar == HT))
               {
                  POS_RxQue.PutChar(&POS_RxQue, POS_RxChar);
               }
               else  
               {
                  ; // Do Nothing
               }
            }
            break;

         case escBusy:
            // Char still matches escape code sequence - do nothing
            break;

         case escFound:
            // If we want to take specific action, on a specific code,
            // EscTestResult.TableIndex can be used to decide which code was parsed.
            break;

         default:
            break;
      }
   }
}

//-------------------------------------------------------------------------------------------------
void Put_POS_ToScreen()
{
   if (!POS_RxQue.IsBufferEmpty && !TextPause)
   {
      byte SpaceCount;
      
      char c = POS_RxQue.GetChar(&POS_RxQue);
      
      // Unpack spaces
      if (c == SP)
      {              
//!!!!               // Next byte holds length
//               SpaceCount = POS_RxQue.GetChar(&POS_RxQue);
//               
//               for (byte i = 0; i < SpaceCount; i++)
//               {
            WriteChar(SP);
      }
      else
      {           
         WriteChar(c);
      }
      
      SwTimer[POS_LINE_TMR].Go(&SwTimer[POS_LINE_TMR], POS_LineTimeoutMS);            
     
      // Retrigger the overlay ClrScr timer
      SwTimer[OVERLAY_TIMEOUT_TMR].Go(&SwTimer[OVERLAY_TIMEOUT_TMR], Settings.Overlay.Timeout);
   }
   else
   {
      ; // Do Nothing
   }
}
