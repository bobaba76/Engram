#include "global.h"
#include "uart.h"

#define FLASH_C
#include "flash.h"
#undef FLASH_C


//---[Flash_OK]--------------------------------------------------------------------------------
// This function performs a checksum of all the bytes in program memory, as well as the config
// bits, excluding user ID

bool FlashTestOK(void)
{
   tFlashChecksum NewChecksum;   
   uint32   ProgWord;
   bool     Result = false;
   bool     IsChecksumSet = false;
   int16    Retry = 3;
   uint16  Checksum = 0;   
      
   // First do a byte-wise sum of program memory, with a 16 bit checksum, ignoring overflow.
   do
   {
      uint32  Address = 0;
      
      Checksum = 0;
            
      IsChecksumSet = (FLASH_CHECKSUM.IsSet == true) 
                   && (FLASH_CHECKSUM.IsSetComplement == ~FLASH_CHECKSUM.IsSet);

      while (Address <= FLASH_MAX)
      {
         ProgWord = FlashRead(Address);
         
         for (uint16 i = 0; i < 3U; i++)
         {
            Checksum = Checksum + (ProgWord & 0xFFU);
            ProgWord = ProgWord >> 8U;
         }
   
         Address += 2U;
      }
         
      // Then the config words: refer to document DS70152 for the target processor. 
      // Change enums in "sytem_config.h" as required  
      ProgWord = FlashRead(CONFIG_REG_ADDR + CFG_OFFS_FBS) & CFG_MASK_FBS;
      Checksum += ProgWord;
      
      ProgWord = FlashRead(CONFIG_REG_ADDR + CFG_OFFS_FSS) & CFG_MASK_FSS;
      Checksum += ProgWord;
      
      ProgWord = FlashRead(CONFIG_REG_ADDR + CFG_OFFS_FGS) & CFG_MASK_FGS;
      Checksum += ProgWord;
      
      ProgWord = FlashRead(CONFIG_REG_ADDR + CFG_OFFS_FOSCSEL) & CFG_MASK_FOSCSEL;
      Checksum += ProgWord;
      
      ProgWord = FlashRead(CONFIG_REG_ADDR + CFG_OFFS_FOSC) & CFG_MASK_FOSC;
      Checksum += ProgWord;
      
      ProgWord = FlashRead(CONFIG_REG_ADDR + CFG_OFFS_FWDT) & CFG_MASK_FWDT;
      Checksum += ProgWord;
      
      ProgWord = FlashRead(CONFIG_REG_ADDR + CFG_OFFS_FPOR) & CFG_MASK_FPOR;
      Checksum += ProgWord;
      
      ProgWord = FlashRead(CONFIG_REG_ADDR + CFG_OFFS_FICD) & CFG_MASK_FICD;
      Checksum += ProgWord;
                         
      if (!IsChecksumSet)
      {        
         int16 WriteRetry = 3;
         

         NewChecksum.Sum = Checksum;
         NewChecksum.SumComplement = ~Checksum;
         NewChecksum.IsSet = 0x0001;
         NewChecksum.IsSetComplement = ~NewChecksum.IsSet;
         
         while (!FlashWriteConst((uint32)&FLASH_CHECKSUM, (byte *)&NewChecksum, sizeof(tFlashChecksum))
             && (--WriteRetry > 0));
        
         // The checksum will be checked at least once more.
      }
      else
      {
         ; // Do Nothing
      }             
   }
   while ((!IsChecksumSet) && (--Retry > 0));
         
   Result = (Checksum == FLASH_CHECKSUM.Sum);

   return Result;

}

//-----[FlashWriteConst]---------------------------------------------------------------------------
// This function writes a block of const values to program memory. Because a const in code space 
// does not use the upper 8 bits, this is padded with 0x00
// The flash buffer is mapped over the POS Rx buffer - not enough RAM for both (also no need).
bool FlashWriteConst(uint32 StartAddress, byte *Data, uint16 ByteCount)
{
   // Program memory is erased in pages of 512 words (3 bytes) = 1536 bytes = 1024 memory locations
   uint16 Offset = StartAddress & ((FLASH_BLOCK_SIZE * 2U) - 1U);
   uint32 CodePageStart = StartAddress & (~((FLASH_BLOCK_SIZE * 2U) - 1));
   uint16 Index;
   uint16 WordLo;
   uint16 WordHi;
   uint16 ProgOffset;
   uint32 ProgramWord;
   bool Result = true;     // Assume success
   byte Retry = 3;
     
   // Some sanity checks:
   if (Offset + ByteCount > (FLASH_BLOCK_SIZE * 2U))
   {
      ByteCount = (FLASH_BLOCK_SIZE * 2U) - Offset;
   }
   else
   {
      ; // Do nothing
   }
   
   // Read block of program memory
   FlashReadBlock(CodePageStart, &FlashBuffer[0U], FLASH_BLOCK_SIZE);
   
   // Modify a portion of it - fit 16 bits into 24 bits by padding upper 8 bits with 0x00
   Index = (Offset * 3) / 2;
   
   while (ByteCount)
   {
      if ((Index + 1) % 3 == 0)
      {
         FlashBuffer[Index++] = 0x00;
      }
      else
      {
         FlashBuffer[Index++] = *Data;
         Data++;
         ByteCount--;
      }
   } 
   
   do
   {  
      // Erase the page
      if (FlashErasePage(CodePageStart))
      {
         // Write back from RAM to flash, 64 bytes at a time
         Index = 0;
         ProgOffset = CodePageStart & 0xFFFFU;
         
         for (uint16 i = 0; i < (FLASH_BLOCK_SIZE / FLASH_ROW_SIZE); i++)
         {
            // Set up NVMCON for row programming operations
            NVMCON = 0x4001U;
            
            // Point to first location to be written
            TBLPAG = (CodePageStart >> 16);
            
            // Load the 64 byte row buffer
            for (uint16 j = 0; j < 64U; j++)
            {
                WordLo = FlashBuffer[Index++];
                WordLo = WordLo | (FlashBuffer[Index++] << 8U);
                WordHi = FlashBuffer[Index++];
                __builtin_tblwtl(ProgOffset, WordLo);
                __builtin_tblwth(ProgOffset, WordHi);
                ProgOffset += 2U;
            }
            
            // Do the row write
            if (!FlashInitiateProgramming())
            {
               Result = false;
            }
            else
            {
               ; // Do nothing
            }
         } 
      }
      else
      {
      }

      // Verify
      if (Result)
      {        
         ProgOffset = CodePageStart;
         
         for (uint16 i = 0; i < FLASH_BLOCK_SIZE; i++)
         {
            ProgramWord = FlashRead(ProgOffset);
                     
            if (((FlashBuffer[i * 3U]) != (ProgramWord & 0xFFU))
            ||  ((FlashBuffer[(i * 3U) + 1U]) != ((ProgramWord >> 8U) & 0xFFU))
            ||  ((FlashBuffer[(i * 3U) + 2U]) != ((ProgramWord >> 16U) & 0xFFU)))
            {
               Result = false;
               break;
            }
            else
            {
               ; // Do nothing
            }
            
            // Next location
            ProgOffset += 2;
         }
      }
      else
      {
         ; // Do nothing
      }
      
   } 
   while (!Result && (--Retry > 0));   
  
   POS_RxQue.Flush(&POS_RxQue);
   
//   MaintUart.TxBuff->Flush(MaintUart.TxBuff);
   
   return Result;
}

//-----[FlashRead]---------------------------------------------------------------------------------
static uint32 FlashRead(uint32 Address)
{
   uint32 Result;
   
   word Offset;
   word WordLo;
   word WordHi;

   // Table page = high word of address - mask redundant, but improves code generation
   TBLPAG = ((Address & 0xFFFF0000ul) >> 16u);  
   
   // Offset = low word of address
   Offset = (Address & 0xFFFFu);
   
   WordLo = __builtin_tblrdl(Offset);
   WordHi = __builtin_tblrdh(Offset);
   
   Result = ((uint32)(((uint32)WordHi << 16u) | ((uint32)WordLo)));
   
   return   Result;
}

//-----[FlashReadBlock]----------------------------------------------------------------------------
// This function reads a block of program memory into a buffer. all 24 bits of each word are read

static void FlashReadBlock(uint32 Address, byte *Dest, word Count)
{
   word Offset;
   word WordLo;
   word WordHi;
   
   // Table page = high word of address - mask redundant, but improves code generation
   TBLPAG = ((Address & 0xFFFF0000ul) >> 16u);  
   
   // Offset = low word of address
   Offset = (Address & 0xFFFFu);

   while (Count > 0)
   {
      // Read the 24 bit word at Offset
      WordLo = __builtin_tblrdl(Offset);
      WordHi = __builtin_tblrdh(Offset);
      
      // Store the 24 bit word in the buffer
      *Dest++ = WordLo & 0xFFu;
      WordLo = WordLo >> 8u;
      *Dest++ = WordLo & 0xFFu; 
      *Dest++ = WordHi & 0xFFu;
      
      // Step offset to the next code location (increment by 2)
      Offset = Offset + 2u;      
      Count--;
   }
}

//-----[FlashErasePage]----------------------------------------------------------------------------
static bool FlashErasePage(uint32 PageAddress)
{
   // On entry, W0 contains the low-word of the address (offset), and W1 the high-word (page)
   __asm__ volatile
   (                                  
      "\t mov #0x4042, W2 \n"          // Set up NVMCON for block erase operation
      "\t mov W2, NVMCON \n"           // Initialize NVMCON
      "\t mov W1, TBLPAG \n"           // Init pointer to page to be ERASED
      "\t tblwtl W0, [W0] \n"          // Set base address of erase block
      "\t disi #5 \n"                  // Block all interrupts with priority < 7 for 5 instructions
      "\t mov #0x55, W0 \n"            // Write the 55 key
      "\t mov W0, NVMKEY \n"           
      "\t mov #0xAA, W1 \n"            // Write the AA key
      "\t mov W1, NVMKEY \n"           
      "\t bset NVMCON, #15 \n"         // Start the erase sequence
      "\t nop \n"                      // Insert two NOPs after the erase command is asserted
      "\t nop \n"                      
   );
   
   // Return the erase result (WRERR == 0 if successfull, so return NOT WRERR)
   return !_WRERR;
}

//-----[FlashInitiateProgramming]------------------------------------------------------------------
static bool FlashInitiateProgramming(void)
{
   __asm__ volatile
   (
      "\t disi #5 \n"                  // Block all interrupts with priority < 7 for 5 instructions
      "\t mov #0x55, W0 \n"            // Write the 55 key
      "\t mov W0, NVMKEY \n"           
      "\t mov #0xAA, W1 \n"            // Write the AA key
      "\t mov W1, NVMKEY \n"           
      "\t bset NVMCON, #15 \n"         // Start the erase sequence
      "\t nop \n"                      // Insert two NOPs after the erase command is asserted
      "\t nop \n"        
   );

   return !_WRERR;
}

//=================================================================================================
