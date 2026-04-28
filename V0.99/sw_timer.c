#include "global.h"
#include "utils.h"
#include "init.h"
#include "text.h"
#include "menu.h"
#include "maint_terminal.h"
#include "char_buffer.h"

#define SW_TIMER_C
#include "sw_timer.h"
#undef SW_TIMER_C

//---[tSwTimer_Go]---------------------------------------------------------------------------------
static void tSwTimer_Go(tSwTimer *this, word Time)
{
   // Convert from milliseconds to cycles - avoid floating point
   uint32 Cycles;
   
   if (Time == 0)  // Time == 0, so disable timer
   {
      this->Reload = 0;
      this->Cycles = 0;
      this->Run  = false;
      this->TimedOut = false;
   }
   else
   {      
      if (this->Is_ms_Timer)
      {
         // Timout in ms
         Cycles = Time;
      }
      else
      {
         // Time is seconds - convert to ms intervals
         Cycles = (uint32)Time * 1000;
      }      
               
      // If this is an actual timer, set time and reload value
      if (this != NULL)
      {      
         this->Reload = Cycles;
         this->Cycles = Cycles;
         
         this->Run  = true;
        
         this->TimedOut = false;
      } 
      else
      {
         ; // Do Nothing
      }
   }      
}   

//---[tSwTimer_Update]-----------------------------------------------------------------------------
static void tSwTimer_Update(tSwTimer *this)
{
   if ((this != NULL) && (this->Run))
   {
      if (this->Cycles > 0)
      {
         this->Cycles--;
         this->TimedOut = false;
      }
      else
      {
         ; // Do Nothing
      }
      
      if (this->Cycles == 0)
      {
         this->TimedOut = true;
         
         if (this->IsMonostable || (this->Reload == 0))
         {
            this->Run = false;
         }
         else
         {
            this->Cycles = this->Reload;
         }
         
         if (this->Callback !=  NULL)
         {
            this->Callback(this);
         }
         else
         {
            ; // Do Nothing
         }
      }         
   }
   else
   {
      ; // Do Nothing
   }
}

//---[Run_LED_TmrCallback]-------------------------------------------------------------------------
static void Run_LED_TmrCallback(tSwTimer *this)
{
   if (this->Run)
   {
      oRunLED = !oRunLED;
   }
   else      
   {
      ;// Do Nothing
   }      
}

//---[MenuTmrCallback]------------------------------------------------------------------------------
static void MenuTmrCallback(tSwTimer *this)
{
   if (this->TimedOut)
   {
      // Abort menu adjustments done
      fMenuIsActive = false;
            
      ClrScr();
      
      POS_RxQue.Flush(&POS_RxQue);
      
      GetStoredSettings();
   
      ApplySettings();
            
      WriteStr("Setup timed out - no changes made\r\n");
   }      
}   

//---[OverlayTmrCallback]---------------------------------------------------------------------------
static void OverlayTmrCallback(tSwTimer *this)
{
   if (this->TimedOut)
   {    
      ClrScr();
   }
}

//---[POS_LineTmrCallback]--------------------------------------------------------------------------
static void POS_LineTmrCallback(tSwTimer *this)
{
   if (this->TimedOut)
   {
      GotoEOL();
   }
}
   
//---[ScrollPauseTmrCallback]-----------------------------------------------------------------------
static void ScrollPauseTmrCallback(tSwTimer *this)
{
   if (this->TimedOut)
   {
      TextPause = false;
   }
}

//---[StatusLineFlashTmrCallback]-------------------------------------------------------------------
static void StatusLineFlashTmrCallback(tSwTimer *this)
{
   fStatusFlasher = !fStatusFlasher;  
}
