#include "global.h"
#include "font.h"
#include "video_line.h"
#include "VideoOverlay.h"
#include "init.h"
#include "text.h"
#include "utils.h"
#include "maint_terminal.h"
#include "menu.h"
#include "sw_timer.h"
#include "status_line.h"
#include "pos.h"

//TODO: At various places individual pins (e.g. LocalSync) are tri-stated. To reduce power 
// consumption, consider also converting to analog in when tri-stated.

static word  FreeRAM;            // Amount of free ram left

//--------------------------------------------------------------------------------------------------
int main(void)
{   
   init();

   // Main Loop
   for(;;)
   {
      _T5IF = 0;

      ClrWdt();
           
      while (!_T5IF)
      {
         //--------------------------------
         // Perform asynchronous tasks here

         // Transmit from maintenance buffer to maintenance terminal
         MaintTxPoll();

         // Check for data on POS port
         while (Poll_POS_Rx())
            Handle_POS_Rx();
            
         MaintRxPoll();
            
         // Move text from POS Rx Que to screen
         Put_POS_ToScreen();
         
      } //end while !_T5IF
  
      //-------------------------
      // Synchronous tasks polled every 1 ms 
      
      Bootload_DTR = Debounced_BL_DTR();
      
      // Trigger timeout to un-pause scrolling
      if (TextPause && !SwTimer[SCROLL_PAUSE_TMR].Run)
      {
         SwTimer[SCROLL_PAUSE_TMR].Go(&SwTimer[SCROLL_PAUSE_TMR], SCROLL_PAUSE_TIMEOUT_MS);  
      }

      // Some timers run only during setup, others inhibited there - set this
      if (fMenuIsActive)
      {
         // This timer flashes oRunLED
         SwTimer[RUN_LED_TMR].Run = true;
         
         SwTimer[OVERLAY_TIMEOUT_TMR].Run = false;

         SwTimer[POS_LINE_TMR].Run = false;
      }
      else
      {
         SwTimer[RUN_LED_TMR].Run = false;
         
         oRunLED = 1;
      }
      
      // Update status line
      UpdateStatusLine();
   
      // 
      FreeRAM = GetFreeRAM();
   
      // Update timers
      for (int i = 0; i < SW_TIMER_COUNT; i++)
      {
         SwTimer[i].Update(&SwTimer[i]);
      }
      
      // Check for video presence, determine video level and switch relay
      fVideoPresent = HandleVideoPresence();

      // Update buttons and handle USB commands - most USB commands emulate button presses
      // Maintenance commands take precedence over butttons and so must be tested first.
      
      // Buttons won't get scanned if there was a command, so clear here in case it is a 
      // "button" command
      Buttons.AsWord = 0;
      if (MaintGetCmd() || ScanButtons())
      {
         if (MaintenanceCmd != 0)
         {
            MaintHandleCmd();
         }
         // Some commands map to button presses, so this mustn't be an else statement
           
         if (Buttons.AsWord != 0)
         {
            DoMenu();
         }
      }

      // 
      if (fEchoText || (fEchoMenu && fMenuIsActive))
         MaintScreenDump();        
      
   }
}

