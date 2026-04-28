#include "global.h"

#define CHAR_BUFFER_C
#include "char_buffer.h"
#undef CHAR_BUFFER_C

//--------------------------------------------------------------------------------------------------
void tCharBuffer_Flush(pCharBuffer this)
{
   // Theoretically, no need to set these both to zero, buffer is empty if Head == Tail,
   // but doing so ensures that they are within the bounds of the array.
   this->Head = 0;
   this->Tail = 0;
   this->Count = 0;
   
   this->FreeCount = this->Size - 1;
   this->Count = 0;
   
   this->IsBufferFull = false;
   this->IsBufferEmpty = true;
}

//--------------------------------------------------------------------------------------------------
char tCharBuffer_CalcChecksum(pCharBuffer this)
{
   int16 i = this->Head;
   char Checksum = 0;
   
   while (i != this->Tail)
   {
      Checksum += this->Buffer[i++];
      i = i % (this->Size - 1);         
   }

   return Checksum;
}   



//--------------------------------------------------------------------------------------------------
bool tCharBuffer_Put(pCharBuffer this, char c)
{
   bool Succeed = false;
   
   if (this != NULL)
   { 
      if (this->FreeCount > 0)
      {         
         this->Buffer[this->Tail++] = c;
         
         this->Tail = this->Tail % (this->Size - 1);
                
         this->Count++;
         this->FreeCount--;
         
         this->IsBufferFull = !this->FreeCount;
         this->IsBufferEmpty = false;
         
         Succeed = true;
      }
      else
      {
         // Precautionary resets
         this->FreeCount = 0;
         this->Count = this->Size - 1;
         
         this->IsBufferFull = true;
         this->IsBufferEmpty = false;
      }
   }      
   else
   {
      // Do Nothing
   }
   
   return Succeed;
}

//--------------------------------------------------------------------------------------------------
char tCharBuffer_Get(pCharBuffer this)
{
   char c = '\0';
   
   if (this != NULL)
   {  
      if (this->Count > 0)
      {       
         c = this->Buffer[this->Head++];
         this->Head = this->Head % (this->Size - 1);
         
         this->Count--;
         this->FreeCount++;
         
         this->IsBufferFull = false;
         this->IsBufferEmpty = !this->Count;
         
      }
      else
      {
         // Precautionary resets
         this->FreeCount = this->Size - 1;
         this->Count = 0;
         
         this->IsBufferFull = false;
         this->IsBufferEmpty = true;
      }
   }

   return c;
}

//--------------------------------------------------------------------------------------------------
bool tCharBuffer_PutStr(pCharBuffer this, char *AString)
{
   bool Succeed = false;
   
   if (this != NULL)
   {
      Succeed = *AString != '\0';
      
      while (*AString && Succeed)
      {
         Succeed = tCharBuffer_Put(this, *AString++);
      }
   }
   
   return Succeed;
}

