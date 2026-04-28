#include "global.h"
#include "get_trap_address.h"

void _ISR_NO_PSV _OscillatorFail(void);
void _ISR_NO_PSV _AddressError(void);
void _ISR_NO_PSV _StackError(void);
void _ISR_NO_PSV _MathError(void);
void _ISR_NO_PSV _DMACError(void);

void _ISR_NO_PSV _AltOscillatorFail(void);
void _ISR_NO_PSV _AltAddressError(void);
void _ISR_NO_PSV _AltStackError(void);
void _ISR_NO_PSV _AltMathError(void);
void _ISR_NO_PSV _AltDMACError(void);

/*
Primary Exception Vector handlers:
These routines are used if INTCON2bits.ALTIVT = 0.
All trap service routines in this file simply ensure that device
continuously executes code within the trap service routine. Users
may modify the basic framework provided here to suit to the needs
of their application.
*/

uint32 TrapAddress = 0;

void _ISR_NO_PSV _OscillatorFail(void)
{
   INTCON1bits.OSCFAIL = 0;        //Clear the trap flag
//TODO: Handle this   
//   while (1);
}

void _ISR_NO_PSV _AddressError(void)
{
   TrapAddress = GetTrapAddress();
   INTCON1bits.ADDRERR = 0;        //Clear the trap flag
//TODO: Determine how to handle this
//asm ("RETFIE");
}
void _ISR_NO_PSV _StackError(void)
{
   TrapAddress = GetTrapAddress();
   INTCON1bits.STKERR = 0;         //Clear the trap flag
//TODO: Determine how to handle this
//   while (1);
}

void _ISR_NO_PSV _MathError(void)
{
   TrapAddress = GetTrapAddress();
   INTCON1bits.MATHERR = 0;        //Clear the trap flag
//TODO: Determine how to handle this
//   while (1);
}

void _ISR_NO_PSV _DMACError(void)
{
        INTCON1bits.DMACERR = 0;        //Clear the trap flag
//TODO: Determine how to handle this
}





/*
Alternate Exception Vector handlers:
These routines are used if INTCON2bits.ALTIVT = 1.
All trap service routines in this file simply ensure that device
continuously executes code within the trap service routine. Users
may modify the basic framework provided here to suit to the needs
of their application.
*/

void _ISR_NO_PSV _AltOscillatorFail(void)
{
        INTCON1bits.OSCFAIL = 0;
//        while (1);
}

void _ISR_NO_PSV _AltAddressError(void)
{
        INTCON1bits.ADDRERR = 0;
//        while (1);
}

void _ISR_NO_PSV _AltStackError(void)
{
        INTCON1bits.STKERR = 0;
//        while (1);
}

void _ISR_NO_PSV _AltMathError(void)
{
        INTCON1bits.MATHERR = 0;
//        while (1);
}

void _ISR_NO_PSV _AltDMACError(void)
{
        INTCON1bits.DMACERR = 0;        //Clear the trap flag
//        while (1);
}

