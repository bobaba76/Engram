#ifndef POS_ESC_H
#define POS_ESC_H

typedef enum tag_CONTROL_CODES
{
   NUL =  0,   //  	Null char
   SOH =  1,   //    Start of Heading
   STX =  2,   //    Start of Text
   ETX =  3,   //    End of Text
   EOT =  4,   //    End of Transmission
   ENQ =  5,   //    Enquiry
   ACK =  6,   //    Acknowledgment
   BEL =  7,   //    Bell
   BS	 =  8,   //    Back Space
   HT	 =  9,   //    Horizontal Tab
   LF	 =  10,  //    Line Feed
   VT	 =  11,  //    Vertical Tab
   FF	 =  12,  //    Form Feed
   CR	 =  13,  //    Carriage Return
   SO  =  14,  //    Shift Out / X-On
   SI  =  15,  //    Shift In / X-Off
   DLE =  16,	//    Data Line Escape
   DC1 =  17,	//    Device Control 1 (oft. XON)
   DC2 =  18,	//    Device Control 2
   DC3 =  19,	//    Device Control 3 (oft. XOFF)
   DC4 =  20,	//    Device Control 4
   NAK =  21,	//    Negative Acknowledgement
   SYN =  22,	//    Synchronous Idle
   ETB =  23,	//    End of Transmit Block
   CAN =  24,	//    Cancel
   EM	 =  25,	//    End of Medium
   SUB =  26,	//    Substitute
   ESC =  27,	//    Escape
   FS  =  28,	//    File Separator
   GS  =  29,	//    Group Separator
   RS  =  30,	//    Record Separator
   US  =  31,  //    Unit Separator
   SP  =  32,  //    Space
   DEL = 127   //    Delete
} tControlCodes;

typedef enum tagESC_SEQUENCE_STATE
{
   escNone,
   escBusy,
   escFound
} tEscSequenceState;

typedef struct tagESC_SEQUENCE_RESULT
{
   tEscSequenceState State;
   byte  TableIndex;
} tEscSequenceResult;

#define ESC_SEQUENCE_TABLE_LEN 53
#define ESC_SEQUENCE_MAX_LEN  5
   
tEscSequenceResult TestForEscSequence(byte c);
int8 MatchEscCode(byte *Sequence);
char TestAndHandleEOL(char c);

#endif
