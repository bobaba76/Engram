#ifndef CHAR_BUFFER_H
#define CHAR_BUFFER_H

// Global Type Definitions
// -----------------------

// Circular Char buffer "object"
typedef struct tagCHAR_BUFFER_TYPE tCharBuffer, *pCharBuffer;

struct tagCHAR_BUFFER_TYPE
{
   char    *Buffer;
   word     Head;
   word     Tail;
   word     Size;
   word     CountMask;  // To use a mask instead of modulo division, Size must be a power of 2
   
   int16    Count;
   int16    FreeCount;

   bool     IsBufferFull;
   bool     IsBufferEmpty;

   void   (*Flush)(pCharBuffer);
   bool   (*PutChar)(pCharBuffer, char);
   char   (*GetChar)(pCharBuffer);
   bool   (*PutStr)(pCharBuffer, char *);
   char   (*CalcChecksum)(pCharBuffer);
};

// Global Variables
// ----------------
// ... None


#ifndef CHAR_BUFFER_C
// Invoked from another module

// Exported Variables
// ------------------

extern tCharBuffer POS_RxQue;
extern tCharBuffer MaintTxQue;
extern tCharBuffer MaintRxQue;

#else
// Private to this module
// ----------------------

// Constants
// ---------
// ... None

// Variables
// ---------

// Private "methods"
// -----------------
void tCharBuffer_Flush(pCharBuffer this);
bool tCharBuffer_Put(pCharBuffer this, char c);
char tCharBuffer_Get(pCharBuffer this);
bool tCharBuffer_PutStr(pCharBuffer this, char *c);
char tCharBuffer_CalcChecksum(pCharBuffer this);

// Initilisation of exported variables
// -----------------------------------

tCharBuffer POS_RxQue =
{
   .Buffer = (char*)&POS_RxBuffer,
   .Head = 0,
   .Tail = 0,
   .Size = POS_RX_BUFFER_SIZE,
   .Count = 0,
   .FreeCount = POS_RX_BUFFER_SIZE - 1,
   .IsBufferFull = false,
   .IsBufferEmpty = true,
   .Flush = tCharBuffer_Flush,
   .PutChar = tCharBuffer_Put,
   .GetChar = tCharBuffer_Get,
   .PutStr = tCharBuffer_PutStr,
   .CalcChecksum = tCharBuffer_CalcChecksum
};

tCharBuffer  MaintTxQue =
{
   .Buffer = (char*)&MaintTxBuffer[0],
   .Head = 0,
   .Tail = 0,
   .Size = MAINT_TX_BUFFER_SIZE,
   .Count = 0,
   .FreeCount = MAINT_TX_BUFFER_SIZE - 1,
   .IsBufferFull = false,
   .IsBufferEmpty = true,
   .Flush = tCharBuffer_Flush,
   .PutChar = tCharBuffer_Put,
   .GetChar = tCharBuffer_Get,
   .PutStr = tCharBuffer_PutStr,
   .CalcChecksum = tCharBuffer_CalcChecksum
};

tCharBuffer  MaintRxQue =
{
   .Buffer = (char*)&MaintRxBuffer[0],
   .Head = 0,
   .Tail = 0,
   .Size = MAINT_RX_BUFFER_SIZE,
   .Count = 0,
   .FreeCount = MAINT_RX_BUFFER_SIZE - 1,
   .IsBufferFull = false,
   .IsBufferEmpty = true,
   .Flush = tCharBuffer_Flush,
   .PutChar = tCharBuffer_Put,
   .GetChar = tCharBuffer_Get,
   .PutStr = tCharBuffer_PutStr,
   .CalcChecksum = tCharBuffer_CalcChecksum
};

#endif

#endif
