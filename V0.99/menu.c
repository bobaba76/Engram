#include <string.h>
#include <stdlib.h>
#include "global.h"
#include "text.h"
#include "utils.h"
#include "init.h"
#include "sw_timer.h"
#include "char_buffer.h"


#define MENU_C
#include "menu.h"
#undef MENU_C

static tMenu *CurrentMenu = NULL;
static bool MenuUsageChange = false;
static tSettings NewSettings;

//--------------------------------------------------------------------------------------------------
// This function inits a sub menu:
//   1) If ActiveItem not NULL (NULL is used to disable the getting of the active item)
//      the function sets ActiveItem to the item that has the same data value as the relevant
//      setting.
//   2) The SelectedItem is set to the ActiveItem
static void InitSubMenu(tMenu *Menu)
{
   tMenuOption *AnItem;
   tMenuOption *StartItem;
   uint32 CurrentSetting = 0;
   
   if (Menu != NULL)
   {         
      
      if (Menu->ActiveItem != NULL)
      {

         if (Menu->GetCurrentSetting != NULL)
         {
            CurrentSetting = Menu->GetCurrentSetting();
            
            StartItem = Menu->FirstItem;
            AnItem = StartItem;
            
            do
            {
               if (AnItem->Data == CurrentSetting)
               {
                  Menu->ActiveItem = AnItem;
               }
               
               AnItem = AnItem->NextItem;
               
            }  while (AnItem != StartItem);       
         }
      
         Menu->SelectedItem = Menu->ActiveItem;
      }                           
      else
      {
         Menu->SelectedItem = Menu->FirstItem;
      }
      
      
      Menu->ParentMenu = &MainMenu;
            
   }
}   

//--------------------------------------------------------------------------------------------------
void MenuDisplaySurrounds(void)
{
   char strbuf[41] = " "PRODUCT_NAME" Setup ";
   word len = strlen(strbuf);
   
   GotoXY(9,0);
   WriteStr(strbuf);
   GotoXY(9,1);
   
   WriteChar(' ');
   for (word i = 1; i < len - 1; i++)
   {
      WriteChar('-');
   }
   WriteChar(' ');
   
   GotoXY(MENU_LEFT, MENU_TOP-2);
   WriteStr("Menu");
   
   GotoXY(MENU_LEFT, MENU_TOP-1);
   WriteStr("----");
   
   GotoXY(MENU_OPTIONS_LEFT, MENU_OPTIONS_TOP-2);
   WriteStr("Option");
   
   GotoXY(MENU_OPTIONS_LEFT, MENU_OPTIONS_TOP-1);
   WriteStr("------");
   
   GotoXY(0, MENU_HINTS_TOP - 2);
   WriteStr("Info:\r\n");
   WriteStr("-----");
   
   GotoXY(0, MENU_USAGE_TOP - 2);
   WriteStr("Usage:\r\n");
   WriteStr("------\r\n"); 
   
   GotoXY(MENU_OPTIONS_LEFT, MENU_HINTS_TOP - 2);
   WriteStr("** Current Setting");   
   
}   

//--------------------------------------------------------------------------------------------------
static void InitMenuItems(tMenu *AMenu)
{
   tMenuOption *Start = AMenu->FirstItem;
   tMenuOption *MenuItem = Start;
   
   do 
   { 
      
      if ((MenuItem->NextMenu != NULL) && (MenuItem->NextMenu->FirstItem))
         InitMenuItems(MenuItem->NextMenu);
         
      // Init the sub menu
      InitSubMenu(MenuItem->NextMenu);
            
      // Get the next one
      MenuItem = MenuItem->NextItem;
      
      // Until all done.
   } while (MenuItem != Start);   
}   

//--------------------------------------------------------------------------------------------------
static void MenuInit(void)
{
      
   SetTextAttribute(attrBlack_GreyBkgnd);
   
   SetOverlayAlignment(alignTopLeft);

   SetTextSize(4u);
     
   fMenuIsActive = true;
   
   ClrScr();
   
   POS_RxQue.Flush(&POS_RxQue);
   
   MenuDisplaySurrounds();
     
   // Now init the sub menus
   InitMenuItems(&MainMenu);
}   

//--------------------------------------------------------------------------------------------------
static void Callback_BaudRate(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
      NewSettings.UART.BaudRate = MenuItem->Data;
}

//--------------------------------------------------------------------------------------------------
static void Callback_DataBits(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
      NewSettings.UART.DataBits = MenuItem->Data;
}

//--------------------------------------------------------------------------------------------------
static void Callback_StopBits(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
      NewSettings.UART.StopBits = MenuItem->Data;
}

//--------------------------------------------------------------------------------------------------
static void Callback_Parity(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
      NewSettings.UART.Parity = MenuItem->Data;
}

//--------------------------------------------------------------------------------------------------
static void Callback_TabStops(tMenuOption *MenuItem)
{
   word Size;
   
   if (MenuItem != NULL)
   {
      if (MenuItem->Caption != NULL)
      {
         Size = atoi(MenuItem->Caption);
         
         if (Size == 0)
            Size = DEFAULT_TAB_STOP_SIZE;
         
         if (SW_DN)
         {
            if (Size > TAB_MIN_SIZE)
               Size--;
            else
               Size = TAB_MAX_SIZE;
         }
         else if (SW_UP)
         {
            if (Size < TAB_MAX_SIZE)
               Size++;
            else
               Size  = TAB_MIN_SIZE;
         }
         else if (SW_ESC)
         {
            Size = GetSetting_TabStop();
         }
         else if (SW_MENU)
         {
            SetTabStopSize(Size);
         }
         
         strcpy(MenuItem->Caption, IntToStr(Size, 3));
         
         MenuShow(&TabStopMenu);

      }
   }      
}         

//--------------------------------------------------------------------------------------------------
static void Callback_TextAttr(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
   {
      NewSettings.Text.Attribute = MenuItem->Data;
   }
}   

//--------------------------------------------------------------------------------------------------
static void Callback_TextSize(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
   {
      NewSettings.Text.Size = MenuItem->Data;
   }      
}

//--------------------------------------------------------------------------------------------------
static void Callback_OverlayAlignment(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
   {
      NewSettings.Overlay.Alignment = MenuItem->Data;
   }      
}
      
//--------------------------------------------------------------------------------------------------
static void Callback_OverlayTimeout(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
      NewSettings.Overlay.Timeout = MenuItem->Data;
}      

//--------------------------------------------------------------------------------------------------
static void Callback_OverlayRows(tMenuOption *MenuItem)
{
   word Rows;
   
   if (MenuItem != NULL)
   {
      if (MenuItem->Caption != NULL)
      {
         Rows = atoi(MenuItem->Caption);
         
         if (Rows == 0)
            Rows = DEFAULT_OVERLAY_ROWS;
         
         if (SW_DN)
         {
            if (Rows > OVERLAY_MIN_ROWS)
               Rows--;
            else
               Rows = OVERLAY_MAX_ROWS;
         }
         else if (SW_UP)
         {
            if (Rows < OVERLAY_MAX_ROWS)
               Rows++;
            else
               Rows  = OVERLAY_MIN_ROWS;
         }
         else if (SW_ESC)
         {
            Rows = GetSetting_OverlayRows();
         }
         else if (SW_MENU)
         {
            NewSettings.Overlay.Rows = Rows;            
         }
         
         strcpy(MenuItem->Caption, IntToStr(Rows, 3));
         
         MenuShow(&OverlayRowsMenu);

      }
   }      
}         

//--------------------------------------------------------------------------------------------------
static void Callback_OverlayColumns(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
      NewSettings.Overlay.Columns = MenuItem->Data;
}

//--------------------------------------------------------------------------------------------------
static void ResetToDefaultSettings(void)
{
   Settings = DEFAULT_SETTINGS;
   NewSettings = DEFAULT_SETTINGS;
   
   ApplySettings();
   
   ClrScr();
   
   POS_RxQue.Flush(&POS_RxQue);
   
   GotoXY(0, 10);
   
   WriteStr("Settings reset back to default ....\n ");
   
   Delay_ms_Blocking(750);
}
   

//--------------------------------------------------------------------------------------------------
static void Callback_ResetDefaults(tMenuOption *MenuItem)
{
   if (MenuItem != NULL)
   {
      if (MenuItem->Data == 1)
      {
         fMenuIsActive = false;
         
         ResetToDefaultSettings();
         
         MenuInit();
      }         
   }
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_BaudRate(void)
{
   return NewSettings.UART.BaudRate;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_DataBits(void)
{
   return NewSettings.UART.DataBits; 
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_StopBits(void)
{
   return NewSettings.UART.StopBits;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_Parity(void)
{
   return NewSettings.UART.Parity;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_TabStop(void)
{
   word Size = NewSettings.Text.TabSize;
   
   strcpy(TabStopMenu.FirstItem->Caption, IntToStr(Size, 3));

   return Size;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_TextAttr(void)
{
   return NewSettings.Text.Attribute;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_TextSize(void)
{
   return NewSettings.Text.Size;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_OverlayAlignment(void)
{
   return NewSettings.Overlay.Alignment;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_OverlayTimeout(void)
{
   return  NewSettings.Overlay.Timeout;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_OverlayRows(void)
{
   word Rows = NewSettings.Overlay.Rows;
   
   strcpy(OverlayRowsMenu.FirstItem->Caption, IntToStr(Rows, 3));

   return Rows;
}

//--------------------------------------------------------------------------------------------------
static uint32 GetSetting_OverlayColumns(void)
{
   return NewSettings.Overlay.Columns;
}
      
//--------------------------------------------------------------------------------------------------
static void MenuSelectItem(tMenu *Menu)
{
   
   word delta;
   byte y;

   if (Menu != NULL)
   {

      y = Menu->y;  
      
      delta = (((word)Menu->SelectedItem)- ((word)Menu->FirstItem)) / sizeof(tMenuOption);
      
      y = y + delta;
      
      GotoXY(Menu->x-2, y );
         
      // Show locator arrow
      WriteStr("=\x10");
      
      // Do callback.
      if ((Menu->SelectedItem != NULL)
      && (Menu->Callback != NULL)
      && (Menu->CallbackOnSelect == true))
            Menu->Callback(Menu->SelectedItem);      
   
   
      if (Menu->SelectedItem->ItemHint != NULL)
      {  
         // Allow two lines for item help
         // CLear in case text there
         GotoXY(0, MENU_HINTS_TOP);
         ClrEOL();
         GotoXY(0, MENU_HINTS_TOP + 1);
         ClrEOL();
         // And print hint
         GotoXY(0, MENU_HINTS_TOP);
         WriteStr(Menu->SelectedItem->ItemHint);
      }
   }
}   


//--------------------------------------------------------------------------------------------------
// This function hides the "selected" arrow of the selected item
static void MenuDeselectItem(tMenu *Menu)
{
   
   word delta;
   byte y;
   
   if (Menu != NULL)
   {
      // Work out the Y location of the selected item
      y = Menu->y;  
      
      delta = (((word)Menu->SelectedItem)- ((word)Menu->FirstItem)) / sizeof(tMenuOption);
      
      y = y + delta;
      
      // Hide the selection arrow
      GotoXY(Menu->x-2, y);
         
      WriteChar(0);
      WriteChar(0);
   }
      
}  

//--------------------------------------------------------------------------------------------------
static void  MenuShowUsage(tMenu *Menu)
{     
   if (Menu != NULL)
   {  
      for (byte i = MENU_USAGE_TOP; i < MENU_USAGE_TOP + MENU_USAGE_LINES; i++)
      {
         GotoXY(0, i);
         ClrEOL();
      }
      
      if (Menu == &MainMenu)
      {
         GotoXY(0, MENU_USAGE_TOP);
         WriteStr("Use Up/Down keys to choose menu item.\r\n");
         WriteStr("Press Menu key to activate option list.\r\n");
         WriteStr("Press ESC to close and save changes.\r\n");
         WriteStr("Setup exits after ");
         WriteStr(IntToStr(MENU_TIMEOUT_SECS, 0));
         WriteStr(" secs inactivity - \r\nCHANGES WILL BE LOST ON TIMEOUT!");
      }
      else
      {
         GotoXY(0, MENU_USAGE_TOP);
         WriteStr("Use Up/Down keys to choose option.\r\n");
         WriteStr("Press Menu key to activate option.\r\n");
         WriteStr("Press ESC to abort option selection.");            
      }
   }
}

//--------------------------------------------------------------------------------------------------
static void  MenuShow(tMenu *Menu)
{
   tMenuOption *StartItem;
   tMenuOption *AnItem;
   byte i = 0;
   byte len = 0;
   
 //  CurrentMenu = Menu;

   if (Menu != NULL)
   {
      StartItem = Menu->FirstItem;
      AnItem = StartItem;
      
      Menu->MaxCaptionLen = 0;
      
      do 
      {

         len = strlen(AnItem->Caption);
         
         if (len > Menu->MaxCaptionLen)  
            Menu->MaxCaptionLen = len;
                     
         GotoXY(Menu->x, Menu->y + i);
         WriteStr(AnItem->Caption);
         
         if ((Menu->x == MENU_OPTIONS_LEFT) && (Menu->LastItem > Menu->FirstItem))
         {
            if (AnItem == Menu->ActiveItem)
               WriteStr("**");
            
            ClrEOL();               
                              
         }
         
         AnItem = AnItem->NextItem;
         i++;
         
      }  while (AnItem != StartItem);
   }   
}

//--------------------------------------------------------------------------------------------------
tMenu *MenuHide(tMenu *Menu)
{

   if (Menu != NULL)
   {

      tMenuOption *StartMenu = Menu->FirstItem;
      tMenuOption *AnItem = Menu->FirstItem;
      byte i = 0;
      byte len = Menu->MaxCaptionLen;

      len = Menu->MaxCaptionLen;

      do
      {                
         GotoXY(Menu->x - 2, Menu->y + i);
         
         ClrEOL();
         
         if (AnItem != NULL)
         {
            AnItem = AnItem->NextItem;
         }
         else
         {
            // Do Nothing
         }
         
         i++;
         
      }  while ((AnItem != StartMenu) && (AnItem != NULL));
      
      MenuDeselectItem(Menu);
   }   
   
   return Menu;
}         

//--------------------------------------------------------------------------------------------------
void  MenuEnter(tMenu *Menu)
{   
   if (Menu != NULL)
   {
      MenuShow(Menu);
     
      MenuSelectItem(Menu);
      
      MenuShow(Menu->SelectedItem->NextMenu);
   }   
}

//--------------------------------------------------------------------------------------------------
tMenu *MenuLeave(tMenu *Menu)
{ 

   if (Menu != NULL)
   {
   
      MenuHide(Menu);
      
      Menu = Menu->ParentMenu;
            
      MenuEnter(Menu);
      
      if ((Menu != NULL) && (Menu->SelectedItem->NextMenu != NULL))
         MenuShow(Menu->SelectedItem->NextMenu);
      
   }   
   
   return Menu;
}         

//--------------------------------------------------------------------------------------------------
void MenuPrevItem(tMenu *Menu)
{
   if (Menu != NULL)
   {
      tMenuOption *AnItem;
      
      AnItem = Menu->SelectedItem;
      
      if (AnItem->NextItem  !=  NULL)
      {      
         MenuHide(AnItem->NextMenu);
      }
      
      MenuDeselectItem(Menu);   
      
      Menu->SelectedItem = Menu->SelectedItem->PrevItem;
      
      AnItem = Menu->SelectedItem;
      
      MenuSelectItem(Menu);
      
      if (AnItem->NextMenu !=  NULL)
      {      
         MenuShow(AnItem->NextMenu);
      }  
   }
}

//--------------------------------------------------------------------------------------------------
void MenuNextItem(tMenu *Menu)
{
   if (Menu != NULL)
   {
      tMenuOption *AnItem;
      
      AnItem = Menu->SelectedItem;
      
      if (AnItem->NextItem  !=  NULL)
      {      
         MenuHide(AnItem->NextMenu);
      }
      
      MenuDeselectItem(Menu);
      
      Menu->SelectedItem = Menu->SelectedItem->NextItem;
      
      AnItem = Menu->SelectedItem;
      
      MenuSelectItem(Menu);
      
      if (AnItem->NextMenu !=  NULL)
      {      
         MenuShow(AnItem->NextMenu);
      }  
   }
}


//--------------------------------------------------------------------------------------------------
void DoMenu(void)
{   
   static tSettings OldSettings;
   static tWindow SavedWindow;
   

   if (fMenuIsActive)
   {
      SwTimer[MENU_TIMEOUT_TMR].Go(&SwTimer[MENU_TIMEOUT_TMR], MENU_TIMEOUT_SECS);
      
      if (SW_DN)
      {
         MenuNextItem(CurrentMenu);
      } 
      else if (SW_UP)
      {
         MenuPrevItem(CurrentMenu);
      }
      else if (SW_MENU)
      {
         if (CurrentMenu->SelectedItem->NextMenu != NULL)
         {  // In main menu
            CurrentMenu->SelectedItem->NextMenu->ParentMenu = CurrentMenu;
            CurrentMenu = CurrentMenu->SelectedItem->NextMenu;
               
            MenuEnter(CurrentMenu);
            
            MenuUsageChange = true;
            
         }
         else
         {  // In option list
            if (CurrentMenu->ActiveItem != NULL)
               CurrentMenu->ActiveItem = CurrentMenu->SelectedItem;
            
            if (CurrentMenu->Callback != NULL)
                CurrentMenu->Callback(CurrentMenu->SelectedItem);
                                          
            CurrentMenu = MenuLeave(CurrentMenu);
            
            MenuUsageChange = true;
         }
      }
      else if (SW_ESC)
      {           
         // Cancel setting changed when previewing items
         if (CurrentMenu->Callback != NULL)
         {
            CurrentMenu->Callback(CurrentMenu->ActiveItem);
         }
         
         CurrentMenu->SelectedItem = CurrentMenu->ActiveItem;
                   
         CurrentMenu = MenuLeave(CurrentMenu);
         
         MenuUsageChange = true;
         
         if (CurrentMenu == NULL)
         {
            // At the main menu already, so clean up and exit menu mode

            SwTimer[MENU_TIMEOUT_TMR].Run = false;
                                       
            // Wipe out menu display                           
            ClrScr();      
            
            AssignTextWindow(SavedWindow);
            
            Settings = NewSettings;
            
            ApplySettings();
            
            // Clear screen second time to ensure cursor is inside window
            ClrScr();

            // This flag MUST be cleared first - affects following functions.
            fMenuIsActive = false;
            
            POS_RxQue.Flush(&POS_RxQue);
            
            // Check for change
            if (memcmp((byte*)&OldSettings, (byte*)&Settings, sizeof(tSettings)) != 0)
            {
               // Changed
               StoreSettings();
               
               WriteStr("Settings updated!\r\n");
            }
            else
            {                  
               WriteStr("No settings changed!\r\n");                           
            }               
         }
         else
         {

         }               
      }
   }
   else
   {
      // Setup menu page
      if (SW_MENU) 
      {
         if (SW_ESC)    // menu-esc combo to reset
         {
            //TODO: Add status & run LED flash for 3 secs, within that time press menu again
            ResetToDefaultSettings();
         }
         else
         {
            // Start timer
            SwTimer[MENU_TIMEOUT_TMR].Go(&SwTimer[MENU_TIMEOUT_TMR], MENU_TIMEOUT_SECS);
            
            // Save window
            SavedWindow = GetTextWindow();
            
            // Copy Settings
            NewSettings = Settings;
            
            FullScreen();
            
            // Store a copy to see if anything has changed
            OldSettings = Settings;
                     
            MenuInit();
            
            MenuUsageChange = true;

            CurrentMenu = &MainMenu;
            
            CurrentMenu->SelectedItem = (tMenuOption*)&MainMenuItem[0];
            
            MenuEnter(CurrentMenu);
         }
         
      }
   }
   
   if (fMenuIsActive && MenuUsageChange)
   {
      MenuShowUsage(CurrentMenu);
      
      MenuUsageChange = false;
   }      
}
