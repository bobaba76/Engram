#include "sysdefs.h"
#include "global.h"
#include "utils.h"
#include "text.h"
#include "flash.h"
#include "init.h"
#include "splash_screen.h"


// Prototypes
// ----------
static void init_comparator(void);
static void init_OC1(void);
static void init_OC2(void);
static void init_OC3(void);
static void init_TMR1(void);  // Line Timer
static void init_TMR2(void);  // Time-base for OC1
static void init_TMR3(void);  // Time-base for the text brightness level PWM
static void init_TMR4(void);  // 
static void init_TMR5(void);  // Time-base for the main loop and ADC
static void init_IO(void);
static void init_Osc(void);
static void init_SPI1(void);
static void init_SPI2(void);
static void init_SPI1_DMA(void);
static void init_SPI2_DMA(void);
static void init_ADC(void);
static void init_ADC_DMA(void);
static void init_UART2(uint32 BaudRate);

//---[init]----------------------------------------------------------------------------------------
void init(void)
{    
   // Fill RAM with a pattern that will be used to check for top-of stack
   FillRAM(STACK_CHECK_PATTERN);
  
   //TODO: At the moment flash check function only calculates and stores checksum (first time round), what do we do with checksum mismatch?
   if (!FlashTestOK())
   {
      Nop();
   }
   else
   {
      Nop();
   }   
   
   // Preload settings with default values, in case not set.
   Settings = DEFAULT_SETTINGS;

   // If necessary program default settings to Flash
   if (!STORED_OEM_SETTINGS.IsInitialised)
   {  
      StoreDefault_OEM_Settings();
   }
   
   if (!STORED_SETTINGS.IsInitialised)
   {    
      // Variable Settings already inited with default values by compiler
      StoreSettings();
   }

   
   // Clear interrupt flag registers
   IFS0 = 0;
   
   IFS1 = 0;
	
	IFS4 = 0;
	
	// Clear interrupt control registers
	IEC0 = 0;
	
	IEC1 = 0;
	
	IEC4 = 0;
	
	// Initialize peripherals
	init_Osc();
	
	while (!_LOCK);
   
   init_comparator();      
   
   init_SPI1_DMA();
   
   init_SPI2_DMA();
   
   init_SPI1();
   
   init_SPI2();
   
   init_TMR1();
   
   init_TMR2();
   
   init_TMR3();
   
   init_TMR4();
   
   init_TMR5();
   
   init_OC1();
   
   init_OC2();
   
   init_OC3();
     
   init_ADC_DMA();
   
   init_ADC(); 
   
   init_IO();  
   
   init_UART2( 115200ul );
   
   SetFilter(&SyncLevelFilter, SYNC_LEVEL_FILTER_MS);
     
   // Variable and port pins 
   Buttons.AsWord = 0;

   oRlyVideo = 0;
   oRlyAux = 0;
   
   SetVideoLED(vledRed);
   
   Delay_ms_Blocking(100u);
   
   FullScreen();
   
   if ((_POR || _BOR) && !_EXTR)
   {
      // If power-on reset Show splash screen
     
      SetTextAttribute(attrBlack_GreyBkgnd);
      
      SetOverlayAlignment(alignTopLeft);
   
      SetTextSize(4u);
      
#ifndef __DEBUG      
      ShowSplash();
#endif      
   }      
   
   RCON = 0;
      
   GetStoredSettings();

   ApplySettings();
   
   oRunLED = 1;
   
}

//---[init-comparator]-----------------------------------------------------------------------------
static void init_comparator(void)
{
   // Setup Comparator 2 to produce a positive pulse on RP12 when SyncIn  goes low
   // relative to SyncSlice
   
   _CMIDL = 0;                   // Continue normal module operation in Idle mode
   
   _C2EN = 1;                    // Comparator 2 enabled
   
   _C2OUTEN = 1;                 // Comparator 2 output enabled
   
   _C2INV = 0;                   // C2 output not inverted
   
   _C2NEG = 0;                   // C2 negative is connected to VIn-
   
   _C2POS = 1;                   // C2 positive is connected to VIn+     
   
   _CMIF = 0;
   
   _CMIE = 1;                    // Enable comparator interrupt
}   

//---[init_OC1]------------------------------------------------------------------------------------
static void init_OC1(void)
{
   // Setup OC1 to produce the burst/DC-clamp pulse
   
   OC1CONbits.OCM = 0b101;       // Generate continuous pulses on OC1 pin
   
   OC1CONbits.OCTSEL = 0;        // Timer2 is the clock source for Output Compare 1
   
   OC1CONbits.OCSIDL = 0;        // Output Compare x will continue to operate in CPU Idle mode
   
   OC1R  = ((word)(CyclesTimer2Preload + (CYCLE_BURST_START)));
   OC1RS = ((word)(CyclesTimer2Preload + (CYCLE_BURST_END)));
   
   _OC1IE = 1;
}

//---[init_OC2]------------------------------------------------------------------------------------
static void init_OC2(void)
{
   // Setup OC2 as PWM to set text white/black level
   
   OC2CONbits.OCM = 0b110;       // PWM mode on OC2, Fault pin, OCF2, disabled
   
   OC2CONbits.OCTSEL = 1;        // Timer3 is the clock source for Output Compare 2
   
   OC2CONbits.OCSIDL = 0;        // Output Compare x will continue to operate in CPU Idle mode
   
   //OC2R = 400;                   // (3.3V/2 + 0.8V) / 3.3 * 512
   
   //OC2RS = 400;                  // Ditto
   
   OC2RS = 380;
 
   _OC2IE = 0;
}   


//---[init_OC3]------------------------------------------------------------------------------------
static void init_OC3(void)
{
   // Setup OC3 to gate text (drive SPI /SS)
   OC3CONbits.OCM = 0b101;       // Continuous mode pulses on OC3 pin
   
   OC3CONbits.OCTSEL = 0;        // Timer2 is the clock source for Output Compare 3
   
   OC3CONbits.OCSIDL = 0;        // Output Compare x will continue to operate in CPU Idle mode
   
   OC3R = 0;    // Cycles
   OC3RS = SPI_Prescaler + 1;     // Cycles
 
   _OC3IE = 0;
}   

//---[init_TMR1]-----------------------------------------------------------------------------------
static void init_TMR1(void)
{
   // Setup timer 1 with 1:1 prescaler, no interrupt
   // Timer 1 is used to time the video line duration
   
   TMR1 = 0;
   
   PR1 = 0xFFFF;

   T1CONbits.TCS = 0;            // Internal clock (FOSC/2)
   
   T1CONbits.TSYNC = 0;          // Do not synchronize external clock input
   
   T1CONbits.TCKPS = 0;          // 1:1
   
   T1CONbits.TGATE = 0;          // 0 = Gated time accumulation disabled
   
   T1CONbits.TSIDL = 0;          // Continue module operation in Idle mode
   
   T1CONbits.TON = 1;            // Start Timer 1

   _T1IF = 0;                    
   
   _T1IE = 0;                    // Disable interrupts
}

//---[init_TMR2]-----------------------------------------------------------------------------------
static void init_TMR2(void)
{
   // Timer 2 provides the time-base for OC1. Set prescaler at 1:1, no interrupt
   // Do not start timer 2 here - gets started in OC1 startup, so it follows that 
   // OC1 setup must be after timer 2 setup
   
   TMR2 = 0;
   
   PR2 = TMR2_PERIOD;
  
   T2CONbits.TCS = 0;            // Internal clock (FOSC/2)
   
   T2CONbits.TCKPS = 0;          // 1:1
   
   T2CONbits.TGATE = 0;          // 0 = Gated time accumulation disabled
   
   T2CONbits.TSIDL = 0;          // Continue module operation in Idle mode
   
   T2CONbits.TON = 1;            // Start timer

   _T2IF = 0;             
   
   _T2IE = 0;                    // Disable interrupts
}

//---[init_TMR3]-----------------------------------------------------------------------------------
static void init_TMR3(void)
{
   // Timer 3 provides the time-base for the text brightness level PWM

   
   TMR3 = 0;
   
   PR3 = TEXT_LEVEL_PWM_MAX;
  
   T3CONbits.TCS = 0;            // Internal clock (FOSC/2)
   
   T3CONbits.TCKPS = 0;          // 1:1
   
   T3CONbits.TGATE = 0;          // 0 = Gated time accumulation disabled
   
   T3CONbits.TSIDL = 0;          // Continue module operation in Idle mode
   
   T3CONbits.TON = 1;            // Start timer

   _T3IF = 0;             
   
   _T3IE = 0;                    // Disable interrupts 
}

//---[init_TMR4]-----------------------------------------------------------------------------------
static void init_TMR4(void)
{
   // Timer 4 provides the time-base for the maintenance UART timeouts. 419 ms max timeout
   
   TMR4 = 0;
   
   PR4 = 0xFFFF;
  
   T4CONbits.TCS = 0;            // Internal clock (FOSC/2)
   
   T4CONbits.TCKPS = 0x03;       // 256:1
   
   T4CONbits.TGATE = 0;          // 0 = Gated time accumulation disabled
   
   T4CONbits.TSIDL = 0;          // Continue module operation in Idle mode
   
   T4CONbits.TON = 1;            // Start timer

   _T4IF = 0;             
   
   _T4IE = 0;                    // Disable interrupts 
}

//---[init_TMR5]-----------------------------------------------------------------------------------
static void init_TMR5(void)
{
   // Timer 5 provides the time-base for the main loop and ADC. Overflow every 1ms
   // Set prescaler at 64:1, no interrupt.
  
   TMR5 = 0;
   
   PR5 = (MAIN_LOOP_CYCLES) / 64u;
  
   T5CONbits.TCS = 0;            // Internal clock (FOSC/2)
   
   T5CONbits.TCKPS = 0x02;       // 64:1
   
   T5CONbits.TGATE = 0;          // 0 = Gated time accumulation disabled
   
   T5CONbits.TSIDL = 0;          // Continue module operation in Idle mode
   
   T5CONbits.TON = 1;            // Start timer

   _T5IF = 0;             
   
   _T5IE = 0;                    // Disable interrupts 
}


//---[init_IO]-------------------------------------------------------------------------------------
static void init_IO(void)
{
   // AN3/RB1 - is sync slice  - Use as reference for comparator 1
   // AN2/RB0 is SyncIn
   // AN1/RA1 is SynPk  - use A-D to monitor this & drive porch/DC-clamp if needed
   // AN0/RA0 is VRef1V7 - (TODO: Measure SynkPk relative to this)
   
   AD1PCFGL = AD1PCFG_LOAD;     
   
   PORTA = 0;
   
   PORTB = 0;
   
   PORTC = 0;

   // Disable RS232 Tx
   oTxDisable = 1;
   
   TRISA = TRISA_LOAD;
   
   TRISB = TRISB_LOAD;
   
   TRISC = TRISC_LOAD; 
   
   CNPU2bits.CN25PUE = 1;
   CNPU2bits.CN26PUE = 1;
   CNPU2bits.CN28PUE = 1;
     
   IO_Unlock();
   
   // Outputs
   oSyncSep = PPS_MAP_C2OUT;     // Comparator 2 output
   
   oPorch =  PPS_MAP_OC1;        // OC1

   oText = PPS_MAP_SDO1;         // RB3/RP3 assigned to SDO1
   
   oTextLevel = PPS_MAP_OC2;     // Text white/black level PWM
   
   oTextGate = PPS_MAP_OC3;      // OC3 acts as frame puls gene for SPI1 & SPI2
   
   oTextClk = PPS_MAP_SCK1OUT;   // SPI1 clk out ( which is SPI2 clk in ) assigned to RP14R/RB14
      
   oTextSolidBkgnd = PPS_MAP_SDO2;     // SPI2 SDO, assigned to RP16/RC0
   oTextTrnsBkgnd = PPS_MAP_NULL; 
    
   oTx = PPS_MAP_U1TX;           // UART1 Tx
   
   oTx_USB = PPS_MAP_U2TX;       // UART2 Tx
   
   // Inputs
   PPS_MAP_U1RX = iRx;           // UART1 Rx
   
   PPS_MAP_U2RX = iRx_USB;       // UART2 Rx
   
   PPS_MAP_SS1IN = iTextGate;    // SPI1 frame pulse
   PPS_MAP_SS2IN = iBgndGate;    // SPI2 frame pulse to same pin
   
   PPS_MAP_SCK2IN = iBgndClk;    // SP12 clock in
   
   //oLocalSync =       
   IO_Lock();
}   

//---[init_Osc]------------------------------------------------------------------------------------
static void init_Osc(void)
{
   OSCCONbits.COSC = 0b011;      // Primary Oscillator with PLL module (XTPLL, HSPLL, ECPLL)
   
   OSCCONbits.NOSC = 0b011;      // Primary Oscillator with PLL module (XTPLL, HSPLL, ECPLL)
   
   CLKDIV = ((PLL_PRE_DIV - 2) | ((PLL_POST_DIV - 2) << 6));
   PLLFBD = (PLL_VCO_MPY - 2);
}  
   
//---[init_SPI1]------------------------------------------------------------------------------------
static void init_SPI1(void)
{
   // Temporarily disable SPI
   SPI1STATbits.SPIEN = 0;
   
   IFS0bits.SPI1IF = 0;          //Clear the Interrupt Flag

   IEC0bits.SPI1IE = 0;          //disable the Interrupt
   
   // Setup SPI1CON1
   SPI1CON1bits.DISSCK = 0;      // Don't disable pin SCK out
   
   SPI1CON1bits.DISSDO = 0;      // SDOx pin is controlled by the module
   
   SPI1CON1bits.MODE16 = 0;      // 8 bit mode
   
   SPI1CON1bits.SMP = 0;         // Input data sampled at middle of data output time
   
   SPI1CON1bits.CKE = 0;         // Serial output data changes on transition from Idle clock state to active clock state
   
   SPI1CON1bits.SSEN = 1;        // SSEN ignored in framed mode
   
   SPI1CON1bits.CKP = 0;         // Idle state for clock is a low level; active state is a high level
   
   SPI1CON1bits.MSTEN = 1;       // Master Mode enabled
   
   SPI1CON1bits.PPRE = 0b11;     // Primary prescaler = 1:1
   
   SPI1CON1bits.SPRE = 0x100 - SPI_Prescaler;    // Secondary prescaler
   
    // Setup SPI1CON2
   SPI1CON2bits.FRMEN = 1;       // Framed SPIx support enabled
   
   SPI1CON2bits.SPIFSD = 1;      // Framed slave (but SPI master)
   
   SPI1CON2bits.FRMPOL = 1;      // Frame sync pulse is active-high
    
   SPI1CON2bits.FRMDLY = 0;      // Frame sync pulse coincides with first bit clock
   
  // Setup SPI1STAT   
   SPI1STATbits.SPIROV = 0;
   
   SPI1STATbits.SPIEN = 1;       // Enable SPI  
   
   // Setup interrupt
   _SPI1IF = 0;
}   

//---[init_SPI2]------------------------------------------------------------------------------------
static void init_SPI2(void)
{
   // Temporarily disable SPI
   SPI2STATbits.SPIEN = 0;
   
   IFS2bits.SPI2IF = 0;          //Clear the Interrupt Flag

   IEC2bits.SPI2IE = 0;          //disable the Interrupt
   
   // Setup SPI2CON1
   SPI2CON1bits.DISSCK = 1;      // Disable pin SCK out
   
   SPI2CON1bits.DISSDO = 0;      // SDOx pin is controlled by the module
   
   SPI2CON1bits.MODE16 = 0;      // 8 bit mode
   
   SPI2CON1bits.SMP = 0;         // Input data sampled at middle of data output time
   
   SPI2CON1bits.CKE = 0;         // Serial output data changes on transition from Idle clock state to active clock state
   
   SPI2CON1bits.SSEN = 1;        // SSEN ignored in framed mode
   
   SPI2CON1bits.CKP = 0;         // Idle state for clock is a low level; active state is a high level
   
   SPI2CON1bits.MSTEN = 0;       // Master Mode disabled
   
   SPI2CON1bits.PPRE = 0b11;     // Primary prescaler = 1:1
   
   SPI2CON1bits.SPRE = 0x100 - SPI_Prescaler;    // Secondary prescaler
   
    // Setup SPI2CON2
   SPI2CON2bits.FRMEN = 1;       // Framed SPIx support enabled
   
   SPI2CON2bits.SPIFSD = 1;      // Framed slave, SPI slave
   
   SPI2CON2bits.FRMPOL = 1;      // Frame sync pulse is active-high
    
   SPI2CON2bits.FRMDLY = 0;      // Frame sync pulse coincides with first bit clock
   
  // Setup SPI1STAT   
   SPI2STATbits.SPIROV = 0;
   
   SPI2STATbits.SPIEN = 1;       // Enable SPI  
   
   // Setup interrupt
   _SPI2IF = 0;
}

//---[init_SPI1_DMA]--------------------------------------------------------------------------------
static void init_SPI1_DMA(void)
{
   // Setup Tx DMA ....
   
   // Disable channel
   DMA1CONbits.CHEN = 0;
   
   // Assign DMA0 to SPI1
   DMA1REQ = 0x000A;           
   
   // Associate DMA channel 1 with SPI buffer
   DMA1PAD = (volatile word)&SPI1BUF;    // Set peripheral adddress to SPI1BUF
   
   // Setup DMA1 address pointers
   DMA1STA = __builtin_dmaoffset(SPI1TxBuf);
   
   // Configure DMA channel 1 to:
   //   Transfer data from to RAM SPI
   //   One shot, no Ping-Pong
   //   Transfer bytes
   DMA1CONbits.SIZE = 1;   // Byte transfers   
   
   DMA1CONbits.DIR = 1;    // RAM to Peripheral transfer
      
   DMA1CONbits.HALF = 0;   // Initiate block transfer complete interrupt when all of the data has been moved
   
   DMA1CONbits.AMODE = 0;  // Register Indirect with Post-Increment
   
   DMA1CONbits.MODE = 0x01;   // One-Shot, Ping-Pong modes disabled

   // Set number of DMA requests to handle before generating IRQ
   DMA1CNT = TEXT_COLUMNS;   // 40 == 41 requests (n+1) - we transmit one more byte to ensure
                             // SDO is low at end of line.
   // Setup dummy Rx DMA ....
   
   // Disable channel
   DMA3CONbits.CHEN = 0;
   
   // Assign DMA2 to SPI1
   DMA3REQ = 0x000A;           
   
   // Associate DMA channel 2 with SPI Rx buffer
   DMA3PAD = (volatile word)&SPI1BUF;    // Set peripheral adddress to SPI1BUF
   
   // Setup DMA1 address pointers
   DMA3STA = __builtin_dmaoffset(SPI1RxBuf);
   
   // Configure DMA channel 2 to:
   //   Transfer data from to SPI to RAM
   //   No ping-pong
   //   Transfer bytes
   DMA3CONbits.SIZE = 1;   // Byte transfers   
   
   DMA3CONbits.DIR = 0;    // Peripheral to RAM transfer
      
   DMA3CONbits.HALF = 0;   // Initiate block transfer complete interrupt when all of the data has been moved
   
   DMA3CONbits.AMODE = 0;  // Register Indirect with Post-Increment
   
   DMA3CONbits.MODE = 0x00;   // Continuous, Ping-Pong modes disabled

   // Set number of DMA requests to handle before generating IRQ
   DMA3CNT = 0;   // 1 request
   
   // Enable channels
   DMA1CONbits.CHEN = 1;   // Enable channel 1
   DMA3CONbits.CHEN = 1;   // Enable channel 3
   
   _DMA1IF = 0;
   _DMA1IE = 1;
   
   _DMA3IF = 0;
   _DMA3IE = 0;


}

//---[init_SPI2_DMA]--------------------------------------------------------------------------------
static void init_SPI2_DMA(void)
{
   // Setup Tx DMA ....
   
   // Disable channel
   DMA2CONbits.CHEN = 0;
   
   // Assign DMA2 to SPI2
   DMA2REQ = 0x0021;           
   
   // Associate DMA channel 1 with SPI buffer
   DMA2PAD = (volatile word)&SPI2BUF;    // Set peripheral adddress to SPI1BUF
   
   // Setup DMA1 address pointers
   DMA2STA = __builtin_dmaoffset(SPI2TxBuf);
   
   // Configure DMA channel 2 to:
   //   Transfer data from to RAM SPI
   //   One shot, no Ping-Pong
   //   Transfer bytes
   DMA2CONbits.SIZE = 1;   // Byte transfers   
   
   DMA2CONbits.DIR = 1;    // RAM to Peripheral transfer
      
   DMA2CONbits.HALF = 0;   // Initiate block transfer complete interrupt when all of the data has been moved
   
   DMA2CONbits.AMODE = 0;  // Register Indirect with Post-Increment
   
   DMA2CONbits.MODE = 0x01;   // One-Shot, Ping-Pong modes disabled

   // Set number of DMA requests to handle before generating IRQ
   DMA2CNT = TEXT_COLUMNS;   // 40 == 41 requests (n+1)

   // Setup dummy Rx DMA ....
   
   // Disable channel
   DMA4CONbits.CHEN = 0;
   
   // Assign DMA4 to SPI2
   DMA4REQ = 0x0021;           
   
   // Associate DMA channel 2 with SPI Rx buffer
   DMA4PAD = (volatile word)&SPI2BUF;    // Set peripheral adddress to SPI1BUF
   
   // Setup DMA3 address pointers
   DMA4STA = __builtin_dmaoffset(SPI2RxBuf);
   
   // Configure DMA channel 4 to:
   //   Transfer data from to SPI to RAM
   //   No ping-pong
   //   Transfer bytes
   DMA4CONbits.SIZE = 1;   // Byte transfers   
   
   DMA4CONbits.DIR = 0;    // Peripheral to RAM transfer
      
   DMA4CONbits.HALF = 0;   // Initiate block transfer complete interrupt when all of the data has been moved
   
   DMA4CONbits.AMODE = 0;  // Register Indirect with Post-Increment
   
   DMA4CONbits.MODE = 0x00;   // Continuous, Ping-Pong modes disabled

   // Set number of DMA requests to handle before generating IRQ
   DMA4CNT = 0;   // 1 request
   
   
   DMA2CONbits.CHEN = 1;   // Enable channel 2
   DMA4CONbits.CHEN = 1;   // Enable channel 4
   
   _DMA2IF = 0;
   _DMA2IE = 0;
   _DMA4IF = 0;
   _DMA4IE = 0;
   
}

//---[init_UART1]----------------------------------------------------------------------------------
void init_UART1(tUART Settings)
{
   
   // U1MODE
   U1MODEbits.UARTEN = 0;        // Disable UART
   
   U1MODEbits.USIDL = 0;         // Continue module operation in Idle mode
   
   U1MODEbits.IREN = 0;          // IrDA encoder and decoder disabled
   
   U1MODEbits.RTSMD = 0;         // UxRTS pin in Flow Control mode (flow control not used)
   
   U1MODEbits.UEN =  0x00;       // UxCTS and UxRTS/BCLKx pins controlled by PORT latches
   
   U1MODEbits.WAKE = 0;          // No wake-up enabled
   
   U1MODEbits.LPBACK = 0;        // Loopback mode is disabled
   
   U1MODEbits.ABAUD = 0;         // Baud rate measurement disabled or completed
  
   U1MODEbits.URXINV = 0;        // U1RX Idle state is '1?'
   
   U1MODEbits.BRGH = 0;          // Baud rate generator low speed
   
   U1MODEbits.PDSEL = Settings.Parity;      // Parity
   
   U1MODEbits.STSEL = (Settings.StopBits == 2);         // 0 = One, 1 = Two stop bits
   
   // U1STA
   U1STAbits.UTXISEL1 = 0;       // Interrupt when a char is transferred to the Transmit Shift Register   
   U1STAbits.UTXISEL0 = 0;
   
   U1STAbits.UTXINV = 0;         // UxTX Idle '1'
   
   U1STAbits.UTXBRK = 0;         // Sync Break transmission disabled or completed 
     
   U1STAbits.URXISEL = 0x00;     // Interrupt on single char
   
   U1STAbits.ADDEN = 0;          // Address Detect Mode disabled
   
   // U1BRG
   U1BRG = ((FCYC) / (16ul * Settings.BaudRate)) - 1;
   
   // .. and run
   U1MODEbits.UARTEN = 1;        // Enable UART
   
   // IMPORTANT: This bit can only be set AFTER enabling UART - if not, Tx won't work.
   U1STAbits.UTXEN = 1;          // Enable transmission
   
   U1TXREG = 0x55;               // Transmit something, else port pin stays low until tx done.
}  


//---[init_UART2]----------------------------------------------------------------------------------
void init_UART2(uint32 BaudRate)
{
   
   // U2MODE
   U2MODEbits.UARTEN = 0;        // Disable UART
   
   U2MODEbits.USIDL = 0;         // Continue module operation in Idle mode
   
   U2MODEbits.IREN = 0;          // IrDA encoder and decoder disabled
   
   U2MODEbits.RTSMD = 0;         // UxRTS pin in Flow Control mode (flow control not used)
   
   U2MODEbits.UEN =  0x00;       // UxCTS and UxRTS/BCLKx pins controlled by PORT latches
   
   U2MODEbits.WAKE = 0;          // No wake-up enabled
   
   U2MODEbits.LPBACK = 0;        // Loopback mode is disabled
   
   U2MODEbits.ABAUD = 0;         // Baud rate measurement disabled or completed
  
   U2MODEbits.URXINV = 0;        // U1RX Idle state is '1?'
   
   U2MODEbits.BRGH = 0;          // Baud rate generator low speed
   
   U2MODEbits.PDSEL = 0;         // No Parity
   
   U2MODEbits.STSEL = 0;         // 0 = One, 1 = Two stop bits
   
   // U2STA
   U2STAbits.UTXISEL1 = 0;       // Interrupt when a char is transferred to the Transmit Shift Register   
   U2STAbits.UTXISEL0 = 0;
   
   U2STAbits.UTXINV = 0;         // UxTX Idle '1'
   
   U2STAbits.UTXBRK = 0;         // Sync Break transmission disabled or completed 
     
   U2STAbits.URXISEL = 0x00;     // Interrupt on single char
   
   U2STAbits.ADDEN = 0;          // Address Detect Mode disabled
   
   // U1BRG
   U2BRG = ((FCYC) / (16ul * BaudRate)) - 1;
   
   // .. and run
   U2MODEbits.UARTEN = 1;        // Enable UART
   
   // IMPORTANT: This bit can only be set AFTER enabling UART - if not, Tx won't work.
   U2STAbits.UTXEN = 1;          // Enable transmission
   
   U2TXREG = 0x55;               // Transmit something, else port pin stays low until tx done.
}  

//---[init_ADC]-------------------------------------------------------------------------------------
static void init_ADC(void)
{
   // Turn off ADC
   AD1CON1 = 0;   
   
   // Clear Channel Select
   AD1CSSL = 0;  
   
   // Set ADC so DMA store in order of conversion, unsigned int, trig on timer 5, simsam, auto sample
   AD1CON1bits.ADSIDL = 0;       // Continue module operation in Idle mode
   
   AD1CON1bits.ADDMABM = 1;      // DMA buffers are written in the order of conversion
   
   AD1CON1bits.AD12B = 0;        // 10-bit, 4-channel ADC operation
   
   AD1CON1bits.FORM = 0x00u;     // Unsigned Integer format
   
   AD1CON1bits.SSRC = 0x04u;     // Timer5 for ADC1 compare ends sampling and starts conversion
   
   AD1CON1bits.SIMSAM = 1;       // Sample CH0, CH1, CH2, CH3 simultaneously
   
   AD1CON1bits.ASAM = 1;         // Sampling begins right after last conversion. SAMP bit auto-set 
   
   
   // Set ADC Ref+ = AVdd, Ref- = AVss, no scan, convert CH<0:3>, no alternate i/p with sample A & B
   AD1CON2bits.VCFG = 0x00;      // ADREF+ = Avdd, ADREF- = Avss
   
   AD1CON2bits.CSCNA = 0;        // Do not scan inputs for CH0+ during Sample A
   
   AD1CON2bits.CHPS = 0x02u;     // Convert CH0, CH1, CH2 and CH3
   
   AD1CON2bits.SMPI = 0x00u;     // Increment DMA address or generates interrupt after every sample/conversion
   
   AD1CON2bits.BUFM = 0;         // Always starts filling buffer at address 0x0
   
   AD1CON2bits.ALTS = 0;         // Always uses channel input selects for Sample A
   
   // Set ADC to use system clock, Sample time to 0 * Tad, ADC cycle time Tad = 3 * Tcy
   AD1CON3bits.ADRC = 0;         // Clock derived from system clock
   
   AD1CON3bits.SAMC = 0x00;      // Sample time = 0 * Tad
   
   AD1CON3bits.ADCS = 0x02;      // ADC clocl = 3 * Tcy
   
   // Set ADC DMA buffering to buffer only one word per analog input
   AD1CON4 = 0x0000u;            // 1 word of buffer per analog input

   // Setup s&h for 4 four channel simultaneous sample, scan A to scan four different channels.
   // 
   // a) Set ADC Mux for CH<1:3>;
   //    CH<1:3>- = AVss; CH<1:3>+ = AN<0:2>
   AD1CHS123 = 0x0000u;

   // b) Set ADC Mux for CH0;
   AD1CHS0 = 0x0003u;   // CH0, -Ve = VRef, +Ve = AN3
    
   // Enable ADC
   AD1CON1bits.ADON = 1;         // Turn on ADC
}



//---[init_ADC]-------------------------------------------------------------------------------------
static void init_ADC_DMA(void)
{
   // Disable channel
   DMA0CONbits.CHEN = 0;
   
   // Assign DMA0 to ADC1
   DMA0REQ = 0x000D;           
   DMA0PAD = (volatile word)&ADC1BUF0;    // Set peripheral adddress to ADC1BUF0 
   
   // Associate DMA channel 0 with ADC buffers
   DMA0STA = __builtin_dmaoffset(ADC1Buffer);
   
   // Configure DMA channel 0 to:
   //   Transfer data from ADC1 to RAM
   //   Continuous without ping-pong
   //   Transfer words
   DMA0CONbits.SIZE = 0;   // Word transfers   
   
   DMA0CONbits.DIR = 0;    // Peripheral-to-RAM direction   
      
   DMA0CONbits.HALF = 0;   // Initiate block transfer complete interrupt when all of the data has been moved
   
   DMA0CONbits.AMODE = 0;  // Register Indirect with Post-Increment
   
   DMA0CONbits.MODE = 0;   // Continuous, Ping-Pong disabled

   // Set number of DMA requests to handle before generating IRQ
   DMA0CNT = 3; // 7 == 8 requests (n+1)
   
   DMA0CONbits.CHEN = 1;   // Enable channel

}


//---[ApplySettings]-------------------------------------------------------------------------------------
void ApplySettings(void)
{
   uint32 UART_LineTime_ms;  // Time taken to receive one full line & current baud rate in millisec

   word current_cpu_ipl;

   // Disable interrupts
   SET_AND_SAVE_CPU_IPL(current_cpu_ipl, 7);

   init_UART1(Settings.UART);

   // Allow 30% margin, 10 bits per word, and allow for CR + LF
   UART_LineTime_ms = ((uint32)((1.3F * 1000ul) * 10ul) * ((uint32)TEXT_COLUMNS + 2ul))
                           / (uint32)Settings.UART.BaudRate;

   if (UART_LineTime_ms > POS_LINE_TIMEOUT_MS_MIN)
   {
      POS_LineTimeoutMS = UART_LineTime_ms;
   }
   else
   {
      POS_LineTimeoutMS = POS_LINE_TIMEOUT_MS_MIN;
   }
   
   SetTextSize(Settings.Text.Size);
   
   SetTextAttribute(Settings.Text.Attribute);
   
   SetOverlayAlignment(Settings.Overlay.Alignment);
   
   SetOverlayWindow();
      
   // Restore interrupts
   RESTORE_CPU_IPL(current_cpu_ipl);
   
}  

