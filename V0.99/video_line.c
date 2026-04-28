#include "sysdefs.h"
#include "typedefs.h"
#include "global.h"
#include "utils.h"
#include "font.h"
#include "text.h"

#include "video_line.h"


// GLobal
int16 ScopeTriggerLineNo = 1; // When LineCntr == ScopeTrigger, set oScopeTrigger high one line
int16 VideoLineCount = 0;     // Used to detect NTSC / PAL (can't use LineCnt, wraps at max line)

// Local
static int16 VideoLineCntr = 1;     // Counter for VideoLineCnt
static int16 LineCntr;              // State machine line counter
static int16 HalfLineCntr;          // Half line counter for field sync
static int16 FontLineOffs = 0;   // For odd lines == 0, even lines == 1
static int16 vTextOffs;          // Video line offset into current text line
static int16 vTextRow;           // Current video text row in page
static int16 vTextCol;           // Current video text col in page
static bool  vTextOn;            // Turn on when video line is in text area
static bool  fFieldSample;       // Sync sampled to check if in field pulses. Set in OC1 interrupt

//-------------------------------------------------------------------------------------------------
inline void PAL_SetLineState(void)
{
   static bool OldFieldSample;
   static byte MismatchCntr = 5;
   
   // Check to see if start of field     
   if (fFieldSample && !OldFieldSample)
   {
      // This is a field pulse, now determine which one    
      if (!(HalfLineCntr & 0x0001))
      {        
         // Start of "odd" field (field 1)
         VideoLineCount = VideoLineCntr;
         VideoLineCntr = 0;
         
         LineCntr = PAL_ODD_SYNC_START;
      }
      else
      {       
          LineCntr = PAL_EVEN_SYNC_START;
         // Start of "even" field (field 2)          
      }
   }
   OldFieldSample = fFieldSample;

   switch (LineCntr)
   {
      case PAL_ODD_LINE_START:
         if (VideoLineCount < (PAL_LINES - 20))
         {
            if (!--MismatchCntr)
            {
               VideoSystem = vidNTSC;
            }
            else
            {
               ; // Do Nothing
            }
         }
         else
         {
            MismatchCntr = 5;
         }      
      
         break;
      case PAL_ODD_VIDEO_START:
         if (fVideoPresent)
            EnableDC_ClampOut();
         break;
      case PAL_ODD_TEXT_START:
         vTextOn = true;
         FontLineOffs = 0;
         vTextRow = 0;
         vTextCol = 0;
         vTextOffs = 0;
         break;
      case PAL_ODD_TEXT_END:
         vTextOn = false;
         break;
      case PAL_ODD_VIDEO_END:
         if (fVideoPresent)
            DisableDC_ClampOut();
         break;
      case PAL_EVEN_LINE_START:
         break;
      case PAL_EVEN_VIDEO_START:
         if (fVideoPresent)
            EnableDC_ClampOut();
         break;
      case PAL_EVEN_TEXT_START:
         vTextOn = true;
         if (TEXT_IS_INTERLACED)
            FontLineOffs = 1;
         else
            FontLineOffs = 0;
         vTextRow = 0;
         vTextCol = 0;
         vTextOffs = 0;
         break;
      case PAL_EVEN_TEXT_END:
         vTextOn = false;
         break;
      case PAL_EVEN_VIDEO_END:
         if (fVideoPresent)
            DisableDC_ClampOut();
         break;
      default:

         break;
   }      
}

//-------------------------------------------------------------------------------------------------
inline void NTSC_SetLineState(void)
{
   static bool OldFieldSample;   
   static byte MismatchCntr = 5;
   
   // Check to see if start of field     
   if (fFieldSample && !OldFieldSample)
   {
      // This is a field pulse, now determine which one
      if (!(HalfLineCntr & 0x0001))
      {        
         // Start of "odd" field (field 1)
         VideoLineCount = VideoLineCntr;       
         VideoLineCntr = 0;
         
         LineCntr = NTSC_ODD_SYNC_START;
      }
      else
      {       
         // Start of "even" field (field 2)
          LineCntr = NTSC_EVEN_SYNC_START;
      }
   }
   OldFieldSample = fFieldSample;

   switch (LineCntr)
   {
      case NTSC_ODD_LINE_START:
         if (VideoLineCount > (NTSC_LINES +20))
         {
            if (!--MismatchCntr)
            {
               VideoSystem = vidPAL;
            }
            else
            {
               ; // Do Nothing
            }
         }
         else
         {
            MismatchCntr = 5;
         }
         
         break;
      case NTSC_ODD_VIDEO_START:
         if (fVideoPresent)
            EnableDC_ClampOut();
         break;
      case NTSC_ODD_TEXT_START:
         vTextOn = true;
         FontLineOffs = 0;
         vTextRow = 0;
         vTextCol = 0;
         vTextOffs = 0;
         break;
      case NTSC_ODD_TEXT_END:
         vTextOn = false;
         break;
      case NTSC_ODD_VIDEO_END:
         if (fVideoPresent)
            DisableDC_ClampOut();
         break;
      case NTSC_EVEN_LINE_START:
         break;
      case NTSC_EVEN_VIDEO_START:
         if (fVideoPresent)
            EnableDC_ClampOut();
         break;
      case NTSC_EVEN_TEXT_START:
         vTextOn = true;
         if (TEXT_IS_INTERLACED)
            FontLineOffs = 1;
         else
            FontLineOffs = 0;
         vTextRow = 0;
         vTextCol = 0;
         vTextOffs = 0;
         break;
      case NTSC_EVEN_TEXT_END:
         vTextOn = false;
         break;
      case NTSC_EVEN_VIDEO_END:
         if (fVideoPresent)
            DisableDC_ClampOut();
         break;
      default:

         break;
   }      
}

//---[LoadSPI]--------------------------------------------------------------------------------------   
// Packs the SPI foreground and background buffers with data for the current video line
inline void LoadSPI(void)
{
   word i;
   byte *pBuf = &(SPI1TxBuf[0]);
   byte *pBkgnd = &(SPI2TxBuf[0]);
   byte *pChar  = (byte*)(&(TextPage[vTextRow][0]));
         
   if (vTextOffs < FONT_HEIGHT)
   {
      // Put out one line of one row
      for (i = 0; i < TEXT_COLUMNS; i++)
      {
             // If there is a char to show (including space or tab), add background
             if (*pChar != 0)
             {
                *pBkgnd++ = TextBackgroundFill;
             }
             else
             {
                *pBkgnd++ = 0;
             }
   
            *pBuf++ = (Font[*pChar++][vTextOffs]);
         if (i == 0)
         {
            DMA1REQbits.FORCE = 1;
            DMA2REQbits.FORCE = 1;
         }
      }
   }
   else
   {
      // Space between text rows

      for (i = 0; i < TEXT_COLUMNS; i++)
      {
          if (*pChar++ != 0)
          {
             *pBkgnd++ = TextBackgroundFill;
          }
          else
          {
             *pBkgnd++ = 0;
          }
         *pBuf++ = 0;

         if (i == 0)
         {
            DMA1REQbits.FORCE = 1;
            DMA2REQbits.FORCE = 1;
         }
      }
   }

   // Ensure that the SPI output is 0
   *pBuf = 0;
   *pBkgnd = 0;

   // Text row done? 
   if (vTextOffs >= FONT_LINE_HEIGHT)
   {
      // .. yes, next row
      vTextRow++;
      vTextOffs = FontLineOffs;

      // Sanity check
      if (vTextRow > TEXT_LINES)
      {
         vTextRow = 0;
         vTextOffs = 0;
         vTextCol = 0;
         FontLineOffs = 0;

      }
   }
   else
   {
      // .. no, next line in current row
      if (TEXT_IS_INTERLACED)
         vTextOffs += 2;
      else
         vTextOffs++;
   }
}


//--------------------------------------------------------------------------------------------------
void _ISR_NO_PSV _OC1Interrupt(void)
{
//   static bool New;
//   static bool Old;
   byte *pBuf = &(SPI1TxBuf[0]);
   byte *pBkgnd = &(SPI2TxBuf[0]);

   _OC1IF = 0;

   DMA1CONbits.CHEN = 1;
   DMA2CONbits.CHEN = 1;

   OC3CONbits.OCM = 0b101;
   
   fFieldSample = _C2OUT;
   
   if (vTextOn)
   {
      vTextCol = 0;

      LoadSPI();
   }
   else
   {
      // Keep SPI going, but transmit blanks ( if not done. some garbage at top of screen)
      // TODO: Checkout why
      for (int i = 0; i < TEXT_COLUMNS; i++)
      {
         *pBuf++ = 0;
         *pBkgnd++ = 0;
      }
   }
   
   // Update line state machines
   if (VideoSystem == vidPAL)
   {
      PAL_SetLineState();
   }
   else
   {
      NTSC_SetLineState();
   }   
}

//--------------------------------------------------------------------------------------------------
void _ISR_NO_PSV _CMPInterrupt(void)
{
  word LineTime;
  word GetTmr1;
  static word OldTmr1 = 0;

  // Only handle the leading edge of the sync pulse - the comparator output is inverted compared 
  // to video sync pulses
  if(_C2EVT && _C2OUT)
  {
      // Timer 2 is used for both OC1 and OC3 - OC1 must give a single pulse during the back-porch
      // period, OC3 must pulse once for text column, but not until it is time to
      // start showing text - OC3 generates the frame pulse for frame-slave SPI.
      // The initial delay is accomplished by preloading TMR2 with a value such that it is
      // greater then the trigger point for OC3, (and PR2) so that TMR2 will wrap around before
      // triggering OC3 and reloading with the PR2 value (char rate).
      // OC1's trip points must be adjusted accordingly to generate the DC clamp pulse.
      TMR2 = CyclesTimer2Preload;

      _T2IF = 0;

      // Restart (and re-sync) SPI
      SPI1STATbits.SPIROV = 0;
      SPI2STATbits.SPIROV = 0;
      _SPI2ON = 1;
      _SPI1ON = 1;

      OC1CONbits.OCM = 0b100;          // re-initialize OCx for single output pulse on OCx pin

      GetTmr1 = TMR1;
      LineTime = GetTmr1 - OldTmr1;    // Time line duration
      OldTmr1 = GetTmr1;

      // Test to see if this is a field line or a normal line
      if (LineTime > LINE_3QUARTER_CYCLES)
      {
         // Past half line, so this is a normal line
         HalfLineCntr = 0;
      }
      else if (LineTime > LINE_1QUARTER_CYCLES)   // Filter glitches
      {
         // First half, don't know if it is field or normal, increment half line cntr
         HalfLineCntr++;
      }

      // Increment on even (or 0) half line counts
      if ((HalfLineCntr & 0x01) == 0)
      {
         LineCntr++;
         VideoLineCntr++;
         
         if (VideoSystem == vidNTSC)
         {
            if (LineCntr > NTSC_LINES)
               LineCntr = 1;
         }
         else
         {
            if (LineCntr > PAL_LINES)
               LineCntr = 1;
         }
         

         if (LineCntr == ScopeTriggerLineNo)
            oScopeTrigger = 1; 
         else
            oScopeTrigger = 0; 
      }

      
   }
   _CMIF = 0;
}

//--------------------------------------------------------------------------------------------------
void _ISR_NO_PSV _DMA1Interrupt(void)
{
   // It is necessary to turn SPI off so that it's clock (which is slower than the CPU clock) can
   // be synced with the comparator pulse - at least to the resolution of the CPU clock
   _SPI1ON = 0;
   _SPI2ON = 0;

   // Disable DMA
   DMA1CONbits.CHEN = 0;
   DMA2CONbits.CHEN = 0;

   OC3CONbits.OCM = 0;

   // Clear flag
   _DMA1IF = 0;
}

//--------------------------------------------------------------------------------------------------
void SetScopeTrigger(char c)
{ 
//<REMOVE ME>
   switch (c)
   {
      case '0':      // Move scope display to start of odd (field 1) field synch pulses
         if (VideoSystem == vidNTSC)
            ScopeTriggerLineNo = 1;
         else
            ScopeTriggerLineNo = 1;
         break;
   
      case '1':      // Move scope display left 1 line
         ScopeTriggerLineNo++;
         break;
      
      case '2':      // Move scope display right 1 line
         ScopeTriggerLineNo--;
         break;
     
      case '3':      // Move scope display left 10 lines
         ScopeTriggerLineNo += 10;
         break;
         
      case '4':      // Move scope display right 10 lines
         ScopeTriggerLineNo -= 10; 
         break;
         
      case '9':      // Move scope display to start of even field synch pulses
         if (VideoSystem == vidNTSC)
            ScopeTriggerLineNo = 263;
         else
            ScopeTriggerLineNo = 313;
         break;
      case  '`':     // Toggle scope between same location on odd/even fields
         if (VideoSystem == vidNTSC)
            ScopeTriggerLineNo = ((((ScopeTriggerLineNo - 1) * 2) + 526) % 1051) / 2 + 1;         
         else
            ScopeTriggerLineNo = ((((ScopeTriggerLineNo - 1) * 2) + 626) % 1251) / 2 + 1;  
         break;
   }
         
   if (VideoSystem == vidNTSC)
   {      
      if (ScopeTriggerLineNo < 1)
      {
         ScopeTriggerLineNo = NTSC_LINES;
      }
      else if (ScopeTriggerLineNo > NTSC_LINES)
      {
         ScopeTriggerLineNo = 1;
      }
   }
   else
   {
      if (ScopeTriggerLineNo < 1)
      {
         ScopeTriggerLineNo = PAL_LINES;
      }
      else if (ScopeTriggerLineNo > PAL_LINES)
      {
         ScopeTriggerLineNo = 1;
      }
   }
}
//</REMOVE ME> 
 

