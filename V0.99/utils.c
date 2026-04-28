#include <string.h>
#include "global.h"
#include "init.h"
#include "text.h"
#include "flash.h"

#define UTILS_C
#include "utils.h"
#undef UTILS_C


tWordAccess Buttons = {0};
tWordAccess ButtonChange = {0};

//--------------------------------------------------------------------------------------------------
void IO_Unlock(void)
{
   asm volatile ("MOV #OSCCON, w1 \n"
   "MOV #0x46, w2 \n"
   "MOV #0x57, w3 \n"
   "MOV.b w2, [w1] \n"
   "MOV.b w3, [w1] \n"
   "BCLR OSCCON,#6");
}

//--------------------------------------------------------------------------------------------------
void IO_Lock(void)  
{
   asm volatile ("MOV #OSCCON, w1 \n"
   "MOV #0x46, w2 \n"
   "MOV #0x57, w3 \n"
   "MOV.b w2, [w1] \n"
   "MOV.b w3, [w1] \n"
   "BSET OSCCON, #6");
}   

//--------------------------------------------------------------------------------------------------
void EnableDC_ClampOut(void)
{
   word current_cpu_ipl;
   //TODO: Add this to all IO lock and unlock sequences
   SET_AND_SAVE_CPU_IPL(current_cpu_ipl, 7); // disable interrupts
   
   IO_Unlock();
   oPorch = PPS_MAP_OC1;
   IO_Lock();
   
   RESTORE_CPU_IPL(current_cpu_ipl);
}

//--------------------------------------------------------------------------------------------------
void DisableDC_ClampOut(void)
{
   word current_cpu_ipl;
      
   SET_AND_SAVE_CPU_IPL(current_cpu_ipl, 7); // disable interrupts
   
   IO_Unlock();
   oPorch = PPS_MAP_NULL;
   IO_Lock();
   
   RESTORE_CPU_IPL(current_cpu_ipl);
}
               
//--------------------------------------------------------------------------------------------------
// Returns debounced state of UART2 DTR (1 or 0). Call every 1ms
bool Debounced_BL_DTR(void)
{
   static bool OldDTR = high;  // DTR idles high
   static word DebounceCount = DTR_DEBOUNCE_DELAY;
   static byte DTR_Debounced = high;
   byte DTR_Sample = i_U2_DTR;
   
   if (DTR_Sample != OldDTR)
   {
      DebounceCount = DTR_DEBOUNCE_DELAY;
   }
   else if (DebounceCount)
   {
      if (!--DebounceCount)
      {
         DTR_Debounced = DTR_Sample;
      }
   }
   
   OldDTR = DTR_Sample;
      
   return DTR_Debounced;
}                     
               
//--------------------------------------------------------------------------------------------------
bool ScanButtons(void)
{
   static word OldButtons = 0xFFFF;
   tWordAccess NewButtons;
   static word DebounceCount = SW_DEBOUNCE_DELAY;
   bool Debounced = false;
   static bool IsResetCombo = false; // True when menu & esc pressed together. To initiate reset, press
                                     // and hold Esc, then press and hold Menu for further 5 seconds.
   
   // Unfortunately iSw4 does not have a weak pullup - so to work around this,
   // we set it to output and drive it high and then tri-state it after
   // a few cycles, if the switch is low, the port will read low, else high
   
   NewButtons.AsWord &= 0x000F;
  
   // Switch input to output & set high
   iSw4 = 1;
   TrisSw4 = 0;
   
   // Delay
   Nop();
   Nop();
   Nop();
   Nop();
   Nop();
   
   // Back to input
   TrisSw4 = 1; 
   
   // Read the port pins into NewButtons

   NewButtons.b0 = !iSw1;
   NewButtons.b1 = !iSw2;
   NewButtons.b2 = !iSw3;
   NewButtons.b3 = !iSw4;
   
   if (fMenuIsActive)
   {
      IsResetCombo = false;
      
      // Debounce
      if (NewButtons.AsWord != OldButtons)
      {
         DebounceCount = SW_DEBOUNCE_DELAY;
      }
      else if (DebounceCount)
      {
         if (!--DebounceCount)
         {
              Debounced = true;
              
              ButtonChange.AsWord = ((NewButtons.AsWord ^ Buttons.AsWord) & 0x000F);
              
              Buttons.AsWord = NewButtons.AsWord;
         }
      }
   }
   else
   {
      // Menu not active, so only examine menu button - must be pressed for longer period
      // (SW_MENU_DELAY) before setting flag
      if (NewButtons.b0)
      {
         if (DebounceCount) 
         {
            if (!--DebounceCount)
            {
               Debounced = true;
               
               if (IsResetCombo)
               {
                  Buttons.AsWord = NewButtons.AsWord & 0x0009; // Return menu and esc - that combination resets settings
               }
               else
               {
                  Buttons.AsWord = NewButtons.AsWord & 0x0001; // Return menu
               }
               
               ButtonChange.AsWord = Buttons.AsWord;
               
            }
         }
      }
      else
      {
         if (NewButtons.AsWord == 0x0008)
         {
            DebounceCount = SW_RESET_ALL_DELAY;
            IsResetCombo = true;
         }
         else
         {
            DebounceCount = SW_MENU_DELAY;
            IsResetCombo = false;
         }
      }
   }      

   OldButtons = NewButtons.AsWord;                
   
   return Debounced;
}

//--------------------------------------------------------------------------------------------------
void SetVideoLED(tVLED State)
{
   static bool toggle = false;
#if defined(VIDEO_LED_2_LEAD)
   switch (State)
   {
      case vledOff:
         oVideoLED = 0;
         oVideoLED_NOT = 0;
         break;
      case vledRed:
         oVideoLED = 1;
         oVideoLED_NOT = 0;
         break;
      case vledOrange:
         if (Toggle)
         {
            oVideoLED = 1;
            oVideoLED_NOT = 0;
         }
         else
         {
            oVideoLED = 0;
            oVideoLED_NOT = 1;
         }     
         
         toggle = ~toggle;    
         break;
      case vledGreen:
         oVideoLED = 0;
         oVideoLED_NOT = 1;
         break;
      default:
         oVideoLED = 0;
         oVideoLED_NOT = 0;
         break;
   }
#else
   switch (State)
   {
      case vledOff:
         oVideoRedLED = 0;
         oVideoGreenLED = 0;
         break;
      case vledRed:
         oVideoRedLED = 1;
         oVideoGreenLED = 0;
         break;
      case vledOrange:
         if (toggle)
         {
            oVideoRedLED = 1;
            oVideoGreenLED = 0;
         }
         else
         {
            oVideoRedLED = 0;
            oVideoGreenLED = 1;
         }    
         
         toggle = !toggle;
         break;
      case vledGreen:
         oVideoRedLED = 0;
         oVideoGreenLED = 1;
         break;
      default:
         oVideoRedLED = 0;
         oVideoGreenLED = 0;
         break;
   }
#endif   
}  

//--------------------------------------------------------------------------------------------------
bool HandleVideoPresence(void)
{
   enum 
   {
      CNT_MAX = 20,
      VIDEO_OFF_THRESHOLD = (int)(VIDEO_SYNC_OFF_MV / 1000.0f / 3.3f * 1023.0f),
      VIDEO_ON_THRESHOLD = (int)(VIDEO_SYNC_ON_MV / 1000.0f / 3.3f * 1023.0f),
      VIDEO_LOW_THRESHOLD = (int)(VIDEO_SYNC_LOW_MV / 1000.0f / 3.3f * 1023.0f),
      VIDEO_GOOD_THRESHOLD = (int)(VIDEO_SYNC_GOOD_MV / 1000.0f / 3.3f * 1023.0f)
   };
   
   static bool HasVideo = false;
   static bool HadVideo = false;
   static bool VideoDetected;  
   static int16 VidCntr = CNT_MAX;

   static word DelayCntr = VIDEO_RELAY_ON_DELAY_MS; 
   pFilter pSyncFilter = &SyncLevelFilter;
   int16 SyncLevel = (*pVRef1V7) - (*pSyncPk);

   // Get the filtered sync pulse amplitude
   SyncLevel = Filter(pSyncFilter, SyncLevel);
   
   // And calulate the while level - PWM has half resolution of ADC. White level is 3.5 x sync
   VideoWhiteLevel = ((SyncLevel * 112) >> 6) + TEXT_LEVEL_BLACK;
   
   // Set the text level PWM
   if (GetTextColor() == clrBlack)
   {
      OC2RS = TEXT_LEVEL_BLACK;
   }
   else
   {
      OC2RS = VideoWhiteLevel;
   }
 
   // Check for video presence, use hysteresys
   if (VideoDetected)
   {
      VideoDetected = (SyncLevel >= VIDEO_OFF_THRESHOLD);
   }
   else
   {
      VideoDetected = SyncLevel >= VIDEO_ON_THRESHOLD; 
   }
   
   // Check for low video, with hysteresis
   if (fLowVideo)
   {
      fLowVideo = (SyncLevel < VIDEO_GOOD_THRESHOLD);
   }
   else
   {
      fLowVideo = (SyncLevel < VIDEO_LOW_THRESHOLD);
   }
   
   // Take action on flags
   if (VideoDetected)
   {
      if (VidCntr > 0) 
         --VidCntr;
      else         
         HasVideo = true;
       
      if (fLowVideo)
      {
         SetVideoLED(vledOrange);
      }         
      else
      {  
         SetVideoLED(vledGreen);
      }         
   }
   else
   {
      if (VidCntr < CNT_MAX)
         VidCntr++;
      else      
          HasVideo = false;
         
      SetVideoLED(vledRed);
   } 

   if (HasVideo)
   {   
     
      if (!HadVideo)
      {
         PR2 = CyclesPerChar - 1;
         
         OC1CONbits.OCM = 0b101;       // Generate continuous pulses on OC1 pin
         
         OC1CONbits.OCTSEL = 0;        // Timer2 is the clock source for Output Compare 1
         
         OC1CONbits.OCSIDL = 0;        // Output Compare x will continue to operate in CPU Idle mode
         
         OC1R  = ((word)(CyclesTimer2Preload + (CYCLE_BURST_START)));
         OC1RS = ((word)(CyclesTimer2Preload + (CYCLE_BURST_END)));
         
         _OC1IE = 1;
      
         TMR2 = CyclesTimer2Preload;
      }
      
      // Energise relay
      if ((oRlyVideo == 0) && (!--DelayCntr))
      {
         DelayCntr = VIDEO_RELAY_OFF_DELAY_MS;
         
         oRlyVideo = 1;
      }
        
      // Disable LocalSync output
      TrisLocalSync = 1;
   }
   else 
   {  
      
      // Setup for video loss      
      PR2 =  TMR2_PERIOD;
   
      OC1CONbits.OCM = 5u;
   
      OC1R  = 100u;
      OC1RS = 120u;
   
      _OC1IE = 0;
      
      // De-energise relay
      if ((oRlyVideo == 1) && (!--DelayCntr))
      {
         DelayCntr = VIDEO_RELAY_ON_DELAY_MS;
       
         oRlyVideo = 0;
      }         
         
      // Enable LocalSync output
      TrisLocalSync = 0;
            
      // If DC clamp not enabled, enable it
      if (oPorch != PPS_MAP_OC1)
      {
         EnableDC_ClampOut();
      }
   }
   
   HadVideo = HasVideo;
   
   return HasVideo;
}


//--------------------------------------------------------------------------------------------------
void Delay_ms_Blocking(word ms_Delay)
{
   TMR5 = 0;
   
   _T5IF = 0;
   
   while (ms_Delay)
   {
      while (!_T5IF);
      
      _T5IF = 0;
      
      ms_Delay--;
      
      ClrWdt();
   }      
}

//--------------------------------------------------------------------------------------------------
void GetStoredSettings(void)
{
   //TODO: Add checksum checks and complement checks.
   Settings = STORED_SETTINGS.Data;
}  

//--------------------------------------------------------------------------------------------------
void StoreSettings(void)
{
//TODO: This function consumes 692 bytes of stack. Fix
   tStoredSettings SettingsToStore;
   byte *pSource = (byte*)&Settings;
   byte *pDest = (byte*)&SettingsToStore.DataComplement;
   word Checksum = 0;
   
   // Store data
   SettingsToStore.Data = Settings;

   // and then the complement and calculate checksum
   for (word i = 0; i < sizeof(Settings); i++)
   {
      *pDest = (byte)(~(*pSource));

      Checksum += *pSource + *pDest;

      pSource++;
      pDest++;
   }
   
   // Flag that settings have been initialised
   SettingsToStore.IsInitialised = 1;
   SettingsToStore.IsInitialisedComplement = ~1;   
   
   Checksum += (sizeof(SettingsToStore.Checksum) + sizeof(SettingsToStore.IsInitialised)) * 0xFF;
   
   // Store checksum
   SettingsToStore.Checksum = Checksum;
   SettingsToStore.ChecksumComplement = (word)~Checksum;

   // And write to Flash
   FlashWriteConst((uint32)&STORED_SETTINGS, (byte*)&SettingsToStore, sizeof(SettingsToStore));

}

//--------------------------------------------------------------------------------------------------
void StoreDefault_OEM_Settings(void)
{
//TODO: This function consumes ??? bytes of stack. Fix   
   tStored_OEM_Settings SettingsToStore;
   byte *pSource = (byte*)&DEFAULT_OEM_SETTINGS;
   byte *pDest = (byte*)&SettingsToStore.DataComplement;
   word Checksum = 0;
   
   // Store data
   SettingsToStore.Data = DEFAULT_OEM_SETTINGS;

   // and then the complement and calculate checksum
   for (word i = 0; i < sizeof(tOEM_Settings); i++)
   {
      *pDest = (byte)(~(*pSource));

      Checksum += *pSource + *pDest;

      pSource++;
      pDest++;
   }
   
   // Flag that settings have been initialised
   SettingsToStore.IsInitialised = 1;
   SettingsToStore.IsInitialisedComplement = ~1;   
   
   Checksum += (sizeof(SettingsToStore.Checksum) + sizeof(SettingsToStore.IsInitialised)) * 0xFF;
   
   // Store checksum
   SettingsToStore.Checksum = Checksum;
   SettingsToStore.ChecksumComplement = (word)~Checksum;

   // And write to Flash
   FlashWriteConst((uint32)&STORED_OEM_SETTINGS,
                     (byte*)&SettingsToStore, sizeof(SettingsToStore));

}

//--------------------------------------------------------------------------------------------------
void Store_OEM_Setting(byte StrIndex, char *SettingStr)
{
   // The OEM settings are at a low page address, & the values in OEM_STRING_INDEX have the 
   // MSB set, indicating it is a PSV address, so here we kill the MSB
   
   // Get string length & do sanity check
  word Len = (word)strlen(SettingStr) + 1;
  uint32 Address = (uint32)__builtin_tblpage(&STORED_OEM_SETTINGS) << 16;
   
   Address |= ((word)OEM_STRING_INDEX[StrIndex] & 0x7FFF);
   
   if (Len > OEM_STR_MAX_LENGTH)
      Len = OEM_STR_MAX_LENGTH;
    
   SettingStr[Len-1] = '\0';
   
   FlashWriteConst(Address, (byte*)SettingStr, Len);

}

//--------------------------------------------------------------------------------------------------
char *IntToHex (uint16 Value)
{
    
   enum { BUF_MAX = 10, BUF_LEN = 11};
   static char Buffer [BUF_LEN];
   char *pReturnVal;
   byte SingleDigit = 0;
   uint16 Index = 0U;
   
   pReturnVal = Buffer + BUF_MAX - 1U;
   
   // store null terminator at end of string
   *pReturnVal = 0;
   
   // Extract 4 hex digits from the input and store to string
   for (Index = 0; Index < 4; Index++)
   {
     // Get the each digit and store to 
     // the string, starting from the right
     SingleDigit = (Value >> (Index * 4U)) & 0x0FU;
     
     if (SingleDigit < 0x0A)
     {
        SingleDigit += '0';
     }
     else
     {
        SingleDigit = (SingleDigit - 0x0A) + 'A';
     }
     // Put character 
     *--pReturnVal = SingleDigit;
   }
   
   // Add "0x" to front of string
   *--pReturnVal = 'x';
   *--pReturnVal = '0';
   
   return ( pReturnVal );
}

//--------------------------------------------------------------------------------------------------
// This function will always return at least the ascii converted string, even if StrLen is too short.
char *IntToStr(int16 Value, byte StrLen)
{
   enum {BUFMAX = 10, BUFLEN = 11}; 
   static char Buffer[BUFLEN];
   word uValue = abs16(Value);
   byte sign = Value < 0;
   char *pResult;
   byte Count = StrLen;
   bool  Done = false;
   bool IsZero = Value == 0;

   // Check width input validity
   if (Count > BUFMAX)
   {
     Count = BUFMAX;
   }
   else
   {
     Count = StrLen;
   }
   
   pResult = &Buffer[BUFMAX];
   
   // Terminate the string
   *pResult-- = '\0';
   
   // populate the string from the least significant character
   while (!Done && (pResult >= Buffer))
   {     
      
      // populate the string while digits are available, otherwise add sign or pad with spaces
      if (uValue || IsZero)
      {
         word Remainder = uValue;
         
         uValue = uValue / 10;
         
         Remainder -= (uValue * 10);
                   
         *pResult = Remainder + '0';
         
         IsZero = false;   // If Value is zero, only produce one digit
         
      }
      else if (sign)
      {
         *pResult = '-';
         
         // clear sign flag so that space padding occurs
         // if string width is available
         sign = 0;
      }
      else if (Count) // && (Count < StrLen))
      {
         *pResult = ' ';
      }
      else
      {
         ; // Do Nothing
      }
      
      if (Count)
      {
         Count--;
      }
      else
      {
         ; // Do Nothing
      }
      
      if (Count || uValue || sign)
      {
         pResult--;
      }
      else
      {
         Done = true;
      }
   }
    
    return pResult;
}

//--------------------------------------------------------------------------------------------------
// Find where start of DMA area
word *GetDMA_AreaAddress(void)
{
   word *StartAddress = (word*)&ADC1Buffer;
   
   if ((word*)&SPI1TxBuf < StartAddress)
   {
      StartAddress = (word*)&SPI1TxBuf;
   }
   
   if ((word*)&SPI1RxBuf < StartAddress)
   {      
      StartAddress = (word*)&SPI1RxBuf;
   }
   
   if ((word*)SPI2TxBuf < StartAddress)
   {
      StartAddress = (word*)&SPI2RxBuf;
   }
   
   if ((word*)SPI2RxBuf < StartAddress)
   {
      StartAddress = (word*)&SPI2RxBuf;
   }
   
   return StartAddress;
}

//--------------------------------------------------------------------------------------------------
// This function fills RAM from the current TOS with a pattern, so that TOS checking can be done
// Call before running Init()
// TODO: Convert this to assembler that runs before variables are initialised.
void FillRAM(word WordPattern)
{
   word *Start = (word*)WREG15;
   word *End = GetDMA_AreaAddress();
   
   while (Start < End)
   {
      *Start++ = WordPattern;
   }
}

//--------------------------------------------------------------------------------------------------
// This function is called once every main loop. Starts at the top and decrements by up to 100.
// Initially, will loop for 100 counts, but once program stack usage has stabilised, won't loop
//TODO: Possible problem - can latch on to single isolated word that has the correct pattern.
// Modify to check there is an array of the pattern of say 10 words that is correct.
word GetFreeRAM(void)
{
   // Get top os stack
   byte LoopCntr = 100;
   static word *pTOS = 0;  // Initilising this to (word*)(&ADC1Buffer - 2) causes a linker error
   static word *DMA_Start = 0;
   
   // So init it here
   if (pTOS == 0)
   {
      DMA_Start = (word*)GetDMA_AreaAddress();
      pTOS =  DMA_Start - 1;
   }
   
   while ((*pTOS == STACK_CHECK_PATTERN) && LoopCntr)
   {
      *pTOS--;
      LoopCntr--;
   }
   
   while ((*pTOS != STACK_CHECK_PATTERN) && (pTOS < DMA_Start) && LoopCntr)
   {
      *pTOS++;
      LoopCntr--;
   }
   
   return ((word)DMA_Start - (word)pTOS);
}         

//-------------------------------------------------------------------------------------------------
// This function calculates a single pole filter's time coefficient from the 
// TimeConstant_ms parameter. The time constant cannot be less than the filter update rate:
// A divide by zero would occur. Where the time constant is too short, the filter transfer function 
// is set to unity. (in any event, short time constants of a few update cycles are not accurate)
void SetFilter(pFilter Filter, word TimeConstant_ms)
{
   // Check for too short time constant. Filter is updated once every main cycle, 
   // so use MAIN_LOOP_MS as cutoff point
   if (TimeConstant_ms <= ((word)(MAIN_LOOP_MS)))
   {
      // Too short, set to unity transfer
      Filter->Coefficient.AsQ16 = FloatToQ16(1.0F);
   }
   else
   {
      // OK, calculate the filter co-efficient
      Filter->Coefficient.AsQ16 = FloatToQ16(MAIN_LOOP_MS) / TimeConstant_ms;
   }
   
   return;
}

//--------------------------------------------------------------------------------------------------
int16 Filter(pFilter AFilter, int16 NewValue)
{
   tQ16_Access Delta;
   word  BitPos;
   
   // Calculate the delta between the new vaulue and the current value
   Delta.Fraction = 0;
   Delta.Integer = NewValue;
   Delta.AsQ16 -= AFilter->Y.AsQ16;

   // Multiply the delta by the coefficient. If coefficient is >= 1.0, then return 
   // with a unity transfer (The coefficient should never be bigger than 1.0)
   if (AFilter->Coefficient.Integer == 0)
   {        
      // The coefficient is less than (Q16)1.000
      BitPos = AFilter->Coefficient.Fraction; // Get the MSB position
      BitPos = GetMSB_UInt16(BitPos) + 1;       
   
      // Shift Delta to prevent overflow.
      Delta.AsQ16 = Delta.AsQ16 >> BitPos;
      
      // Multiply
      Delta.AsQ16 = (Delta.AsQ16 * AFilter->Coefficient.AsQ16);
      
      // and then shift delta again to normalise result
      Delta.AsQ16 = Delta.AsQ16 >> (16u - BitPos);
   }
   else
   {
      // Coefficient is 1.0 or greater so filter has unity transfer....
      ; // Do Nothing
   }                  

   // Addback the updated delta
   AFilter->Y.AsQ16 += Delta.AsQ16;
   
   
   return Q16ToInt(AFilter->Y);
}
