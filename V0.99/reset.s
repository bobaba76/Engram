/* --------------- Original copyright and notes from file crt0_standard.s -------------------------
*                                                                                                 *
* C Run-time startup module for dsPIC30 C compiler.                                               *
* (c) Copyright 2009 Microchip Technology, All rights reserved                                    *
*                                                                                                 *
* Primary version, with data initialization support.                                              *
* The linker loads this version when the --data-init                                              *
* option is selected.                                                                             *
*                                                                                                 *
* Standard 16-bit support, for use with devices that do not support                               *
* Extended Data Space                                                                             *
*                                                                                                 *
* See file crt1.s for the alternate version without                                               *
* data initialization support.                                                                    *
*                                                                                                 *
* Entry __reset takes control at device reset and                                                 *
* performs the following:                                                                         *
*                                                                                                 *
*  1. initialize stack and stack limit register                                                   *
*  2. initialize PSV window if __const_length > 0                                                 *
*  3. process the data initialization template                                                    *
*  4. call the .user_init section, if it exists                                                   *
*  5. call the user's _main entry point                                                           *
*                                                                                                 *
* Assigned to section .init, which may be allocated                                               *
* at a specific address in linker scripts.                                                        *
*                                                                                                 *
* If a local copy of this file is customized, be sure                                             *
* to choose a file name other than crt0.s or crt1.s.                                              *
-------------------------------------------------------------------------------------------------*/

        .include "p33Fxxxx.inc"

        .global __application_reset
        
        .weak    __user_init, __has_user_init

        ; Always locate this code at a 0x200 so no matter how the rest of the code changes, the
        ; linker does not move this, and execution will be able to correctly resume from the 
        ; bootloader.
        .section .application_reset, code, address(0x0200)

__application_reset:

        ; Re-initialise SP, SPLIM & W14
        mov      #__SP_init, w15            ; initialize w15
        mov      #__SPLIM_init, w14         ; Set stack pointer limit
        mov      w14, SPLIM

        rcall    __psv_init                 ; initialize PSV
        mov      #__dinit_tbloffset,w0      ; w0,w1 = template
        mov      #__dinit_tblpage,w1        ;
        rcall    __data_init_standard       ; initialize data

        mov      #__has_user_init,w0
        cp0      w0                         ; user init functions?
        bra      eq,1f                      ; br if not
        call     __user_init                ; else call them
1:
        call  _main                         ; call user's main()

        .pword 0xDA4000                     ; halt the simulator
        reset                               ; reset the processor

	.ifdef ffunction
	.section .init.psv_init, code
	.endif
        .global __psv_init
__psv_init:
; 
; Initialize PSV window if _constlen > 0
; 
; Registers used:  w0
; 
; Inputs (defined by linker):
;  __const_lengths
;  __const_psvpage
; 
; Outputs:
;  (none)
; 
;	.equiv   PSV, 0x0002

        bclr     _CORCON,#PSV               ; disable PSV (default)
        mov      #__const_length,w0         ; 
        cp0      w0                         ; test length of constants
        bra      z,1f                       ; br if zero

        mov      #__const_psvpage,w0        ; 
        mov      w0,_PSVPAG                 ; PSVPAG = psvpage(constants)
        bset     _CORCON,#PSV               ; enable PSV

1:      return                              ;  and exit


