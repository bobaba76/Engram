#ifndef MAINT_TERMINAL_H
#define MAIN_TERMINAL_H

typedef enum tagMAINTENANCE_CMD
{
   cmdNone                        = 0,    // No Command
   cmdMenuKey                     = 1,    // Emulate device Menu key
   cmdUpArrowKey                  = 2,    // "       "      Up Arrow key
   cmdDnArrowKey                  = 3,    // "       "      Dn Arrow key
   cmdEscKey                      = 4,    // "       "      Esc key
   cmdCapture                     = 5,    // Start capture to terminal    
   cmdEndCapture                  = 6,    // End capture
   cmdEchoText                    = 7,    // Echo screen text to terminal
   cmdEndEchoText                 = 8,    // End echo screen text to terminal
   cmdDisableMenuEcho             = 9,    // Disable echoing of menu text to terminal (Enabled by default)
   cmdEnableMenuEcho              = 10,   // Enable echoing of menu text to terminal
   cmdWriteDeviceInfo             = 11,   // Send software version, model etc.
   cmdReadDeviceInfo              = 12,   // Receive device info
   cmdWriteSettings               = 13,   // WriteSettings to PC
   cmdReadSettings                = 14,   // Read settings from PC
   cmdQueryPresence               = 15,   // Respond with 'P'
   cmdDoBootload                  = 0xC0  // Start bootloader. Same as open-source dsBootloader
} tMaintenanceCmd;                        // (but only if flag blFlagWriteProgam is set)

// NOTE: Must be in same order as in bootloader firmware AND in PC application
typedef enum tagBL_FLAGS
{   
   blFlagWriteProgram             = 0x01,      // Bootload, (not just set some settings)
   blFlagWriteSettings            = 0x02,      // Overwrite settings
   blFlagWriteOEM_Settngs         = 0x04,      // Overwrite OEM settings
   blFlagNotEncrypted             = 0x08,      // Image is not encrypted
   blFlagWriteBootloader          = 0x10,      // Overwrite bootloader
   blFlagMask                     = 0x1F,       // Mask for flags
   blFlagCmdMask                  = cmdDoBootload, // Mask to extract cmd
   blFlagValidMask                = blFlagCmdMask | blFlagMask // Mask to check if cmd & flags valid
} tBootload_Flags;

void MaintTxPoll();
bool MaintRxPoll(void);
bool MaintGetCmd(void);
bool MaintTestForBootloadCmd(void);
bool IsMaintBufferFull(void);
bool IsMaintBufferEmpty(void);
void MaintClrEOL(void);
void MaintClrScr(void);
void MaintGotoXY(const byte X, const byte Y);
void MaintScrollUp(void);
bool MaintPutWord(word w);
bool MaintPutChar(char c);
bool MaintPutScreenChar(char c);
int16 MaintReadStrBlocking(char *Buffer);
word MaintReadBlocking(byte *Buffer, int16 Count);
byte MaintGetByte(void);
char MaintGetChar(void);
void MaintPutStr(char *AStr);
void MaintScreenDump(void);
void MaintHandleCmd();

extern tMaintenanceCmd MaintenanceCmd; // Updated in MaintGetCmd() once every cycle, only one cycle to use

#endif
