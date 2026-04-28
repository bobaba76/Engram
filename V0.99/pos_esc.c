#include "sysdefs.h"
#include "pos_esc.h"

// This table MUST be in sorted order, sorted by column 1 first, then 2 etc.
// Unused locations MUST be filled with 0xFF
// '?' is used as a wild-card. If a wild-card appears in the same position as codes in other
// sequences that match up to the position of the wild card, and the sequence must be retained, then
// the other sequence must be in the array location before the one with the wild card. See Underline
// off and Underline on for epson
static const byte ESC_SEQUENCES [ESC_SEQUENCE_TABLE_LEN][ESC_SEQUENCE_MAX_LEN] = 
{
   { 7,  0xFF,  0xFF,  0xFF,  0xFF},   // 0   BEL                 Open drawer 1            CBM
   { 7,    27,  0xFF,  0xFF,  0xFF},   // 1   BEL ESC             Open drawer 1            ESC-POS
   {14,  0xFF,  0xFF,  0xFF,  0xFF},   // 2   SO                  Big Print                Star
   {20,  0xFF,  0xFF,  0xFF,  0xFF},   // 3   DC4                 Cutter                   Westrex
   {27,     7,    10,    50,     7},   // 4   ESC BEL LF 2 BEL    Open drawer              Star
   {27,     7,    11,    55,     7},   // 5   ESC BEL VT 7 BEL    Open drawer              Star
   {27,    32,   '?',  0xFF,  0xFF},   // 6   ESC SP #n           Set space on rhs         Epson
   {27,    33,     0,    32,   '?'},   // 7   ESC ! #0 SP #n      Set print style          P & P only?      V0.97d2   *new
   {27,    33,   '?',  0xFF,  0xFF},   // 8   ESC ! #n            Set print style          Epson
   {27,    45,     0,  0xFF,  0xFF},   // 9   ESC - #0            Underline off            Epson
   {27,    45,   '?',  0xFF,  0xFF},   // 10  ESC - #2,48,49,50   Underline on             Epson
   {27,    64,  0xFF,  0xFF,  0xFF},   // 11  ESC @               Reset Printer            Epson
   {27,    69,     0,  0xFF,  0xFF},   // 12  ESC E #0            Bold Off                 Epson
   {27,    69,   '?',  0xFF,  0xFF},   // 13  ESC E #1..255       "    On                  Epson
   {27,    70,     0,    50,    50},   // 14  ESC F #0 2 2        Drawer code              Epson
   {27,    71,     0,  0xFF,  0xFF},   // 15  ESC G #0            Double strike Off        Epson
   {27,    71,   '?',  0xFF,  0xFF},   // 16  ESC G #1            Double Strike On         Epson
   {27,    73,  0xFF,  0xFF,  0xFF},   // 17  ESC I               Autocutter Full Cut      ?
   {27,    77,   '?',  0xFF,  0xFF},   // 18  ESC M #0..2,48..50  Select font ...          Epson
   {27,    80,     0,    25,   250},   // 19  ESC P #0 EM #250    Open Drawer #1
   {27,    80,     0,    64,   240},   // 20  ESC P #0 @  #240    Open Drawer #1                            V0.97d2  *new
   {27,    80,     0,   '?',  0xFF},   // 21  ESC P #0 n
   {27,    97,   '?',  0xFF,  0xFF},   // 22  ESC a #0..2,48..50  Justify                  Epson
   {27,    99,   '?',   '?',  0xFF},   // 23  ESC c #m #n         Select paper sensor      Epson
   {27,   100,   '?',  0xFF,  0xFF},   // 24  ESC d #n            Print and feed n lines   Epson
   {27,   105,  0xFF,  0xFF,  0xFF},   // 25  ESC i               Autocutter partial       ESC-POS
   {27,   109,  0xFF,  0xFF,  0xFF},   // 26  ESC m               Autocutter full          ESC-POS
   {27,   110,     0,    25,   250},   // 27  ESC n #0 EM #250    Open Drawer                               V0.97d2  *new
   {27,   112,     0,   '?',   '?'},   // 28  ESC p #0 #5 #250    Cutter/drawer            Epson/various
   {27,   112,     1,   '?',   '?'},   // 29  ESC p #1 1  #251    Drawer Code              Various
   {27,   112,    32,   '?',   '?'},   // 30  ESC p SP 7  #255    Drawer Code              Toshiba SX2100   V0.97d2  *new
   {27,   112,    48,   '?',   '?'},   // 31  ESC p  0 7  #251    Drawer Code              Various
   {27,   112,    49,   '?',   '?'},   // 32  ESC p  1 #m  #n     Drawer Code              WASP
   {27,   114,     0,  0xFF,  0xFF},   // 33  ESC r #0            Color 1                  Epson
   {27,   114,     1,  0xFF,  0xFF},   // 34  ESC r #1            Color 2                  Epson
   {27,   114,    48,  0xFF,  0xFF},   // 35  ESC r #48           Color 1                  Epson
   {27,   114,    49,  0xFF,  0xFF},   // 36  ESC r #49           Color 2                  Epson
   {27,   116,   '?',  0xFF,  0xFF},   // 37  ESC t n             Select char code table   Epson  
   {27,   118,  0xFF,  0xFF,  0xFF},   // 38  ESC v               Cutter                   Ithica
   {27,   120,     1,  0xFF,  0xFF},   // 39  ESC x #1            Drawer Code                              V0.97d2  *new
   {27,   122,    49,     7,  0xFF},   // 40  ESC z 1 BEL         Cutter                   Star
   {29,    35,   '?',  0xFF,  0xFF},   // 41  GS  # #0            Download bitmap ????
   {29,    47,   '?',  0xFF,  0xFF},   // 42  GS  / #n            Print downloaded image n ESC-POS         V0.97d2 *new
   {29,    66,     0,  0xFF,  0xFF},   // 43  GS  B #0            Reverse Color print Off  Epson
   {29,    66,   '?',  0xFF,  0xFF},   // 44  GS  B #1..255       "       "     "     On   Epson 
   {29,    86,     0,  0xFF,  0xFF},   // 45  GS  V #0            Full paper cut           Epson
   {29,    86,   '?',  0xFF,  0xFF},   // 46  GS  V #1..255       Partial paper cut        Epson
   {29,    86,    48,  0xFF,  0xFF},   // 47  GS  V #48           Full paper cut           Epson
   {29,    86,    49,  0xFF,  0xFF},   // 48  GS  V #49           Partial paper cut        Epson
   {29,    86,    65,  '?',   0xFF},   // 49  GS  V #65           Feed paper and full cut  Epson
   {29,    86,    66,  '?',   0xFF},   // 50  GS  V #66           Feed paper & partial cut Epson 
   {29,   114,   '?',  0xFF,  0xFF},   // 51  GS  r #n            Send paper/drawer status ESC-POSc
   {30,  0xFF,  0xFF,  0xFF,  0xFF}    // 52  RS                  Buzzer                   Star
};


//--------------------------------------------------------------------------------------------------
// This function scans the EscSequences table for sequence and returns the index into the table. 
// If the sequence does not exist in the table, returns -1
int8 MatchEscCode(byte *Sequence)
{
         
   byte SeqIndex = 0;
   byte RowIndex = 0;
   bool NewSequence = false;
   
   while (( SeqIndex < ESC_SEQUENCE_MAX_LEN ) && (RowIndex < ESC_SEQUENCE_TABLE_LEN))
   {
      while ((SeqIndex < ESC_SEQUENCE_MAX_LEN) && !NewSequence &&
             ((*Sequence == ESC_SEQUENCES[RowIndex][SeqIndex]) ||
              (ESC_SEQUENCES[RowIndex][SeqIndex] == '?')))
      {
         SeqIndex++;
         Sequence++;
         
         // Check for consecutive esc sequences
         NewSequence = *Sequence == ESC;
         
         if (NewSequence)
         {
            break;
         }
      }
      
      
      if ((ESC_SEQUENCES[RowIndex][SeqIndex] == 0xFF) ||
          (SeqIndex == ESC_SEQUENCE_MAX_LEN) ||
          (NewSequence))
      {
         break;
      }
      RowIndex++;
   }
   
   if (RowIndex >= (sizeof(ESC_SEQUENCES) / ESC_SEQUENCE_MAX_LEN))
      RowIndex = 255;   

   return RowIndex;   
}   

//-------------------------------------------------------------------------------------------------
tEscSequenceResult TestForEscSequence(byte c)
{
   static bool InEscSequence = false;
   static byte SeqIndex = 0;
   static byte Bottom = 0;
   static byte Top = 0;
   tEscSequenceResult Result;
   bool Found = false;
   bool NewSequence = false;
   
   // Handle consecutive esc sequences
   if (InEscSequence && ((c == ESC) || (c == GS)))
   {
      // Restart
      InEscSequence = false;
   }
      
   if (!InEscSequence && (c < ' ') && ((c < BS) || (c > CR)))
   {
      // Esc sequence detected - setup to parse
      Result.State = escBusy;
      Result.TableIndex = -1;
      
      SeqIndex = 0;
      Bottom = 0;
      Top = ESC_SEQUENCE_TABLE_LEN - 1;

      InEscSequence = true;
   }
    
   if (InEscSequence)
   {
      // Scan from below to find the bottom occurance of c
      while ((ESC_SEQUENCES [Bottom][SeqIndex] != c) 
         &&  (Bottom < ESC_SEQUENCE_TABLE_LEN) && (Bottom < Top))
         {
            Bottom++;
         }
      
      InEscSequence = ((Bottom < ESC_SEQUENCE_TABLE_LEN) 
                      && ((c == ESC_SEQUENCES[Bottom][SeqIndex]) 
                          || (ESC_SEQUENCES[Bottom][SeqIndex] == '?')));
      
      if (InEscSequence)
      {
         // Scan from the top to find top occurence of c
         while ((Top > Bottom) && (c != ESC_SEQUENCES [Top][SeqIndex]))
         {
            Top--;
         }
         // Down to one row?
         if (Top == Bottom)
         {
            byte SeqMax = SeqIndex;
            
            // Get length of current esc sequence
            while ((SeqMax < (ESC_SEQUENCE_MAX_LEN - 1)) 
                && (ESC_SEQUENCES[Bottom][SeqMax + 1] != 0xFF))
            {
               SeqMax++;
            }
            
            Found = (SeqIndex == SeqMax);
         }
         
         SeqIndex++;
      }
   }

   if (Found)
   {
      InEscSequence = false;
      
      Result.State = escFound;
      Result.TableIndex = Bottom;
   }
   else if (InEscSequence)
   {
      Result.State = escBusy;
      Result.TableIndex = -1;
   }
   else
   {
      InEscSequence = false;
      
      Result.State = escNone;
      Result.TableIndex = -1;
   }

   return Result;

}

//--------------------------------------------------------------------------------------------------
// Handle CR, CR+LF, FF, VT the same. Also ignore multiple line feeds
// CR, LF, FF, VT all return CR. CR+LF returns CR+'\0'
char TestAndHandleEOL(char c)
{
   static bool LastCharWasNewLine = false;
   static char lastchar;
   
   lastchar = c;
   
   if ((c == CR) || (c == LF) || (c == FF) || (c == VT))
   {
      if (LastCharWasNewLine)
      {
         c = '\0';
      }
      else
      {
         LastCharWasNewLine = true;
       
          c = CR;
      }
   }
   else
   {
      LastCharWasNewLine = false;
   }
   
   return c;
}
