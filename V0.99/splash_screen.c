#include <string.h>
#include "sysdefs.h"
#include "utils.h"
#include "text.h"
#include "font.h"
#include "maint_terminal.h"



void ShowSplash(void)
{
   char strbuf[100];
   word len;
   word maxlen = 0;
   word i;
   const word X_CENTRE = (TEXT_COLUMNS) / 2;
   const word BANNER_TOP = 3;
   const word BANNER_LEN = 13;

   ClrScr();
      
   GotoXY(0, BANNER_TOP);
   
   // Write the frame:
   // Top bar
   WriteStr("+--------------------------------------+\r\n");
   
   // Side bars
   for (word i = BANNER_TOP + 1; i < BANNER_LEN; i++)
   {
         WriteStr("|                                      |\r\n");
   }
   
   // Bottom bar
   WriteStr("+--------------------------------------+\r\n");   
   
   // Interior:
   // Vendor Name
   len = strlen(VENDOR_NAME);
   if (len > maxlen) maxlen = len;
   GotoXY(X_CENTRE - len / 2, BANNER_TOP + 2);
   WriteStr(VENDOR_NAME"\r\n");
   
   // Product Name
   len = strlen(PRODUCT_NAME);
   if (len > maxlen) maxlen = len;
   GotoXY(X_CENTRE - len / 2, BANNER_TOP + 3);
   WriteStr(PRODUCT_NAME);
   
   // Product Description
   len = strlen(PRODUCT_DESCRIPTION);
   if (len > maxlen) maxlen = len;
   GotoXY(X_CENTRE - len / 2, BANNER_TOP + 4);
   WriteStr(PRODUCT_DESCRIPTION);
   
   // Underline
   for (i = 0; i < maxlen; i++)
   {
      strbuf[i] = '-';
   }
   
   strbuf[i] = '\0';
   
   GotoXY(X_CENTRE - len / 2, BANNER_TOP + 5);
   WriteStr(strbuf);

   // Software &  hardware versions
   GotoXY(2, 10);
   WriteStr("SW Version:  ");
   WriteStr(SW_VERSION);
   
   GotoXY(2, 12);
   WriteStr("SW Checksum: ");
   WriteStr(IntToHex(FLASH_CHECKSUM.Sum));
   
   GotoXY(2, 11);
   WriteStr("HW Version:  ");
   WriteStr(HW_VERSION);
   
   GotoXY(0, 16);
   WriteStr("To enter setup, press and hold menu key for ");
   WriteStr(IntToStr(SW_MENU_DELAY / 1000U, 0));
   WriteStr(" sec.");
   
   GotoXY(0, 24);
   WriteStr("WAIT, Initialising ");

   for (int i = 0; i < 20; i++)
   {
      WriteChar('.');
      for (int j = 0; j < 150; j++)
      {
         Delay_ms_Blocking(1);
      
         fVideoPresent = HandleVideoPresence();
         
         if (MaintTestForBootloadCmd())
         {
            SwReset();
         }
      }   

   } 
   
   ClrScr();
   
}   

