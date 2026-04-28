#include "global.h"
#include "text.h"

#define STATUS_LINE_C
#include "status_line.h"
#undef STATUS_LINE_C

void UpdateStatusLine(void)
{     
   static bool fMenuWasActive = false;
   
   bool  fForceUpdate = fMenuWasActive && !fMenuIsActive;
   
   if (!fMenuIsActive)
   {
      StatusLineItem[0].IsActive = true;
      StatusLineItem[STATUS_INDEX_VIDEO_LOW].IsActive = fLowVideo & fVideoPresent;
      StatusLineItem[STATUS_INDEX_VIDEO_OFF].IsActive = !fVideoPresent;
   }
   else
   {
      for (int i = 0; i < STATUS_ITEM_COUNT; i++)
         StatusLineItem[i].IsActive = false;
   }
//TODO: This seems to be OK - test properly.
//SO THAT STATUS WILL BE UPDATED CORRECTLY WHEN EXITING MENU, MAINTAIN A GLOBAL STATUS STRING
//AND IN HERE, UPDATE THAT STRING. ON EXITING THE MENU, PUT THE STRING   
   for (int16 i = 0; i < STATUS_ITEM_COUNT; i++)
   {
      if (fForceUpdate || (StatusLineItem[i].IsActive != StatusLineItem[i].PrevActiveState))
      {
         if (StatusLineItem[i].IsActive)
         {
            StatusLinePutStr(StatusLineItem[i].Caption);
         } 
         else
         {
            StatusLineClr();
         }
      }     

      StatusLineItem[i].PrevActiveState = StatusLineItem[i].IsActive;
   }
   
   fMenuWasActive = fMenuIsActive;
}   
