#ifndef UART_H
#define UART_H

#ifndef CHAR_BUFFER_H
#include "char_buffer.h"
#endif

// Global Type Definitions
// -----------------------

typedef struct tagBUFFERED_UART_TYPE tBufferedUART, *pBufferedUART;

// UART control struct
typedef struct tagUART_CONTROL_TYPE
{
   // Important - this struct must follow the layout of the registers in the processor header file
   // Point the struct to the processor U?MODE word
   U1MODEBITS  Mode;
   U1STABITS   Status;
   word        TxReg;
   word        RxReg;
   word        Brg;
} tUART_Ctrl, *pUART_Ctrl;

// buffered UART buffer "object"
struct tagBUFFERED_UART_TYPE
{
   pUART_Ctrl  Ctrl;    // Pointer to UART hardware registers
   pCharBuffer RxQue;
   pCharBuffer TxQue;
};

// Global Variables
// ----------------
// ... None

#ifndef UART_C
// Invoked from another module

// Exported Variables
// ------------------

// the POS terminal does not use a UART object, each character is handled as received - after some
// processing it is however que'd into a buffer.
extern tBufferedUART MaintUart;

#else
// Invoked from this module

// Private to this module
// ----------------------

// Local Constants
// ---------------
// ... None

// Local Variables
// ---------------
//

// Private "methods"
// ----------------


// Initilisation of exported variables
// -----------------------------------

// Definition and initialisation of exported variables
// ---------------------------------------------------

tBufferedUART MaintUart  =
{
   .Ctrl = (pUART_Ctrl)&U2MODE,
   .RxQue = &MaintRxQue,
   .TxQue = &MaintTxQue
};

#endif

#endif
