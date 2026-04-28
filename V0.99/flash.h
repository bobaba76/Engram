#ifndef FLASH_H
#define FLASH_H

// Global function prototypes
bool FlashWriteConst(uint32 StartAddress, byte *Data, word ByteCount);
bool FlashTestOK(void);

#ifndef FLASH_C
// Header invoked from CSU other than flash.c ...

// Exported variables:
// -------------------

// None

#else
// Header invoked from flash.c ...

// Global variable declarations:
// -----------------------------

// None

// Local function prototypes:
// --------------------------

static uint32 FlashRead(uint32 Address);
static void FlashReadBlock(uint32 Address, byte *Dest, word Count);
static bool FlashErasePage(uint32 PageAddress);
static bool FlashInitiateProgramming(void);

#endif


#else
#error "File 'flash.h' included more than once"
#endif /* FLASH_H */
