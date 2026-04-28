#ifndef GET_TRAP_ADDRESS_H
#define GET_TRAP_ADDRESS_H

// This file is an interface for an assembler file, get_trap_address.s, and as a result does not
// conform to the company c standard

// Exported Functions:
//--------------------
uint32 GetTrapAddress(void);

#else
#error "File 'get_trap_address.h' included more than once'
#endif /* GLOBAL_H */
