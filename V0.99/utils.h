#ifndef UTILS_H
#define UTILS_H


// Exported functions
void IO_Lock(void);
void IO_Unlock(void);

void EnableDC_ClampOut(void);
void DisableDC_ClampOut(void);
bool Debounced_BL_DTR(void);
bool ScanButtons(void);
void Delay_ms_Blocking(word ms_Delay);
bool HandleVideoPresence(void);
void SetVideoLED(tVLED State);
void StoreSettings(void);
void GetStoredSettings(void);
void StoreDefault_OEM_Settings(void);
void Store_OEM_Setting(byte Index, char *SettingStr);
char *IntToHex(uint16 Value);
char *IntToStr(int16 Value, byte StrLen);
word GetFreeRAM(void);
void FillRAM(word WordPattern);
void SetFilter(pFilter Filter, word TimeConstant_ms);
int16 Filter(pFilter AFilter, int16 NewValue);

//--------------------------------------------------------------------------------------------------
// Return rounded integer part of Q16 value                     
static int16 inline Q16ToInt(tQ16_Access Value)
{
   // If the value is less greater or equal to zero
   if (Value.AsQ16 >= 0)
   {
      if (Value.Fraction & 0x8000)
      {
         Value.Integer++;
      }
      else
      {
         ; // Do Nothing
      }         
   }      
   else
   {  
      if ((word)(Value.Fraction) > 0x8000u)
      {
         Value.Integer++;
      }
      else
      {
         ; // Do Nothing
      }
   }
   
   return Value.Integer;
}

//--------------------------------------------------------------------------------------------------
// This function returns the bit number in the range 0..15 of the MSB of parameter AWord
// If the number is 0x0000, returns -1
static inline int16 GetMSB_UInt16(word AWord)
{
   // Returns the bit number of the MSB of an unsigned 16 bit number
    
   __asm__ volatile
   (
      "ff1l %0, %0 \n\t"       // Find the MSB from the left (e.g. 16 for 0x8000)
      "mov  #16, w1 \n\t"      // And calculate MSB from right
      "sub w1, %0, %0 \n\t"    // .. the result is in W0
      "btsc %0, #4 \n\t"       // A value of 16 means the AWord was zero
      "mov  #-1, %0 \n\t"      // ... so return -1
      : "+r"(AWord)            // Tell the compiler AWord is both input & output
   );
   
   return AWord;
}

//--------------------------------------------------------------------------------------------------

  

//--------------------------------------------------------------------------------------------------

// Global Macros
// -------------

#define SwReset() __asm__ ("reset")
#define abs16(x) (((x) < 0)?((word)-(x)):((word)(x)))
#define FloatToQ16(x)\
      (((x) >= 0.0F) ? ((int32)((double)(((double)(x) + (0.5F/65536.0F)) * 65536.0F)))\
                     : ((int32)((double)(((double)(x) - (0.5F/65536.0F)) * 65536.0F))))
                     
#define Limit(Value, Low, High) (((Value) < (Low)) ? (Low) : (((Value) < (High)) ? (Value) : (High)))

// Macro function to locate a constant at a fixed location in flash memory
// usage:
// var_type const_at("section_name", 0x400) var_name ....
#define const_at(SectionName, Address)\
    __attribute__((space(psv), section(SectionName), address(Address)))


#ifdef UTILS_C

#endif

extern tWordAccess CommandFlags;
extern tWordAccess Buttons;
extern tWordAccess ButtonChange;

#endif
