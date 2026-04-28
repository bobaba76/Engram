        .include "p33Fxxxx.inc"
;TODO: Implement bootloader reprogramming        
        
        ; Unlike ds30Loader firmware,  we always do a full flash program to ensure the checksum
        ; will be correct, and just to make life a little bit more difficult for crackers, all 
        ; pages are erased at the start, with the exception page 0. This is to preserve the vector 
        ; to the bootloader until we are ready to write to the first page, in case bootloading 
        ; gets interrupted. 
        ;
        ; This CSU also preserves (by default) the settings and OEM settings page and protects the 
        ; bootloader code. This requires the bootloader to occupy pages 1 & 2, OEM settings page 3 
        ; and user settings page 4. IF this changes, the bootloader must be reloaded onto the target.
        ;
        ; Optionally if flags BL_FLAG_WRITE_SETTINGS .. BL_FLAG_NEW_BOOTLOADER are set in the 
        ; 'Hello' command, the bootloader will overwrite settings etc.
        ;
        ; Because of CBC AES decoding, we need to feed ALL rows through the decoder, so instead
        ; of completely skipping unused rows, flag fSKIP_ROW is set prevent writes.
        
        
;------------------------------------------------------------------------------
; Register usage
;------------------------------------------------------------------------------
        .equ    DECODECNTR, W2
        .equ    WDECODEPTR, W3      ;aes decode pointer
        .equ	WBUFPTR,	W4		;buffer pointer
        .equ	WCNT,		W5   	;loop counter
        .equ	WPPSTEMP1,	W6		;used to restore pps register
        .equ	WPPSTEMP2,	W7		;used to restore pps register
        .equ	WTEMP1,		W8		;
        .equ	WDEL1,		W9 		;delay outer
        .equ	WDEL2,		W10		;delay inner
        .equ    FLAGS,      W11     ; Flags register
        .equ	WCMD,		W12		;command
        .equ 	WCRC, 		W13		;checksum
        .equ    FRAMEPTR,   W14     ;Frame pointer
        .equ	STKPTR,		W15		;stack pointer

;------------------------------------------------------------------------------
; Includes
;------------------------------------------------------------------------------

        #include "../sysdefs.h"
        #include "../bootloader/devices.inc"
        #include "../bootloader/aes_tables.inc"
        ; In MPLAB 8, if .include directive is used, path is relative to
        ; project, in MPLAB X, path is relative to location of this file
        ; Using C preprocessor #include means path is relative to this file
        ; in both environments
;-----------------------------------------------------------------------------
; UART stuff
;-----------------------------------------------------------------------------

        .equ    UMODE,	    U2MODE			;uart mode
        .equ    USTA,  		U2STA			;uart status
        .equ    UBRG,		U2BRG			;uart baudrate
        .equ    UTXREG,		U2TXREG			;uart transmit
        .equ	URXREG,		U2RXREG			;uart receive
        .equ	UIFS,		IFS0			;uart interupt flag sfr
        .equ	URXIF,		U2RXIF			;uart received interupt flag
        .equ	UTXIF,		U2TXIF			;uart transmit interupt flag

;------------------------------------------------------------------------------
; Constants
;------------------------------------------------------------------------------
        .equ	VERMAJ,		1				/*firmware version major*/
        .equ	VERMIN,		0				/*fimrware version minor*/
        .equ	VERREV,		0				/*firmware version revision*/
        
        ; Commands
        .equ 	BOOTLOAD_CMD,    			0xC0
        #define BL_FLAG_DO_BOOTLOAD         W0, #0
        #define BL_FLAG_WRITE_SETTINGS      W0, #1  /* When true, settings will be overwritten */
        #define BL_FLAG_WRITE_OEM_SETTINGS  W0, #2  /* TODO */
        #define BL_FLAG_NEW_BOOTLOADER      W0, #3  /* TODO: BOOTLOAD-RELOADER NOT DONE YET */
        #define BL_FLAG_UNENCRYPTED         W0, #4  /* Data is unencrypted */

        #define CMD_FLAG_ERASE_PAGE         WCMD, #0
        #define CMD_FLAG_WRITE_ROW          WCMD, #1
        #define CMD_FLAG_WRITE_EEPROM       WCMD, #2
        #define CMD_FLAG_WRITE_CONFIG       WCMD, #3
        
        ; Command responses
        .equ    ABORT,          'A'         /*Inform master bootloading aborted*/
        .equ 	OK, 		    'K'			/*erase/write ok*/
        .equ 	CHECKSUMERR,    'N'			/*checksum error*/
        .equ	VERFAIL,	    'V'			/*verification failed*/
        .equ   	UCMD,     	    'U'         /*unknown command*/

        .equ    DELAY_1MS, ( 1 * (FCYC / 1000) / 3)
        .equ	BL_1ST_DELAY,(BL_INITAL_TIMOUT_MS * (FCYC / 1000) /(65536 * 7)) ;1st delay before user app is loaded
        .equ    BLDELAY, (BL_RX_TIMEOUT_MS * (FCYC / 1000) /(65536 * 7))     ;other delay before user app  loaded

        .if BL_USE_BRGH == 1
            .equ UARTBR, ((((FCYC / BL_BAUD_RATE) / 2) - 1) / 2 ) /*brg calculation with rounding*/
        .else
            .equ UARTBR, ((((FCYC / BL_BAUD_RATE) / 8) - 1) / 2 ) /*brg calculation with rounding*/
        .endif

        .equ    PAGESIZEW,      512         /*pagesize [words]*/
        .equ	PAGESIZER,	    8           /*pagesize [rows]*/
        .equ	ROWSIZEW,       64	        /*rowsize  [words]*/
        .equ	INSTRSIZEB,     3	        /*instr size [bytes] */
        .equ    AESBLOCKSIZEB,  16          /*AES decode block size [bytes] */
        .equ    ROWSIZEBLOCKS,  ((ROWSIZEW * INSTRSIZEB)/ AESBLOCKSIZEB) 

        .equ    FLASH_PAGE_MAX, (FLASHSIZE / PAGESIZEW / 2)

        ; Bootloader placement
        .equ	STARTADDR,	    (BL_PAGE_LOCATION * PAGESIZER * ROWSIZEW * 2)
        .equ    BL_START_PAGE,  (BL_PAGE_LOCATION)
        .equ    BL_END_PAGE,    (BL_START_PAGE + BL_PAGES - 1)
        .equ	BL_START_ROW,   (STARTADDR / ROWSIZEW / 2)
        .equ	BL_END_ROW,	    (BL_START_ROW + (BL_PAGES * PAGESIZER) - 1)

        ; Settings locations
        .equ    SETTINGS_START_ADDR, (SETTINGS_PAGE * PAGESIZER * ROWSIZEW * 2)
        .equ    SETTINGS_START_PAGE,  SETTINGS_PAGE
        .equ    SETTINGS_END_PAGE,   (SETTINGS_START_PAGE + SETTINGS_PAGES - 1)
        .equ    SETTINGS_START_ROW,  (SETTINGS_START_ADDR / ROWSIZEW / 2)
        .equ    SETTINGS_END_ROW,    (SETTINGS_START_ROW + (SETTINGS_PAGES * PAGESIZER) - 1)
        
        ; OEM Settings locations
        .equ    OEM_SETTINGS_START_ADDR, (OEM_SETTINGS_PAGE * PAGESIZER * ROWSIZEW * 2)
        .equ    OEM_SETTINGS_START_PAGE,  OEM_SETTINGS_PAGE
        .equ    OEM_SETTINGS_END_PAGE,   (OEM_SETTINGS_START_PAGE + OEM_SETTINGS_PAGES - 1)
        .equ    OEM_SETTINGS_START_ROW,  (OEM_SETTINGS_START_ADDR / ROWSIZEW / 2)
        .equ    OEM_SETTINGS_END_ROW,    (OEM_SETTINGS_START_ROW + (OEM_SETTINGS_PAGES * PAGESIZER) - 1)        

        ; NVMCON Codes for erasing / writing
        .equ 	FLASH_ERASE_CODE,	0x4042
        .equ 	FLASH_WRITE_CODE,	0x4001
        .equ 	CFG_ERASE_CODE, 	0x4040
        .equ 	CFG_WRITE_CODE,	    0x4000

        ; Buffer allocated on stack ....
        .equ    BUFFER_BYTE_SIZE, ((ROWSIZEW * INSTRSIZEB) + 1)            ; Extra byte for checksum
        .equ    BUFFER_ALLOCATE_SIZE, (((BUFFER_BYTE_SIZE + 1) / 2) * 2)  ; MUST be even number

        ; Flag declarations - need C pre-processor to handle these
        ; Command flags
        #define fDO_BOOTLOAD        FLAGS, #0   ; Bootload, (not just set some settings)
        #define fKEEP_SETTINGS      FLAGS, #1   ; Set when settings can be kept (checksum etc)
        #define fKEEP_OEM_SETTINGS  FLAGS, #2   ; Do not overwrite OEM settings
        #define fUNENCRYPTED        FLAGS, #3   ; Image is not encrypted
        #define fLOAD_NEW_BOOTLOAD  FLAGS, #4   ; Image is a new bootloader
        ; Working flags     
        #define fDO_ERASE           FLAGS, #8   ; Set to precede write with page erase (normal page erase)        
        #define fIS_FIRST_ROW       FLAGS, #9   ; Set when at address 0x000000
        #define fIN_INITIAL_TIMEOUT FLAGS, #10  ; Set during initial timeout
        #define fSKIP_ROW           FLAGS, #11  ; Set when row must be protected

;------------------------------------------------------------------------------
; Validate user settings
;------------------------------------------------------------------------------
        ; Internal cycle clock
        .equ FCYC, (FOSC / 2)
        
        .if FCYC > 40000000
            .error "FCYC specified is out of range"
        .endif

        ; Baudrate error
        .if BL_USE_BRGH == 1
            .equ REALBR,	(FCYC / (4 * (UARTBR + 1)))
        .else
            .equ REALBR,	(FCYC / (16 * (UARTBR + 1)))
        .endif
;
;        .equ BAUDERR,	((1000 * ( BL_BAUD_RATE - REALBR)) / BL_BAUD_RATE )
;        .if ( BAUDERR > 25) || (BAUDERR < -25 )
;            .error "Baudrate error is more than 2.5%. Remove this check or try another baudrate and/or clockspeed."
;        .endif

;------------------------------------------------------------------------------
; Global declarations
;------------------------------------------------------------------------------

        .global __resetPRI
        .global _bootloader_end
        .global _bootloader_size
        .equ _bootloader_size, (.sizeof.(.bootloader))

;------------------------------------------------------------------------------
; External functions and variables
;------------------------------------------------------------------------------

        .extern _SETTINGS
        .extern _SETTINGS_PADDING
        .extern __application_reset


;------------------------------------------------------------------------------
; unlock IO and lock IO macros
;------------------------------------------------------------------------------
        .macro unlock_IO
            mov #OSCCON, w1
            mov #0x46,   w2
            mov #0x57,   w3
            mov.b w2,   [w1]
            mov.b w3,   [w1]
            bclr OSCCON, #6
        .endm

        .macro lock_IO
            mov #OSCCON, w1
            mov #0x46,   w2
            mov #0x57,   w3
            mov.b w2,   [w1]
            mov.b w3,   [w1]
            bset OSCCON, #6
        .endm

;------------------------------------------------------------------------------
; Send macro
;------------------------------------------------------------------------------
        .macro SendL char
            mov #\char, W0
            rcall Send
        .endm

;------------------------------------------------------------------------------
; Start of bootloader code section in program memory
;------------------------------------------------------------------------------
        .section .bootloader, code, address(STARTADDR)

;------------------------------------------------------------------------------
; Reset vector
;------------------------------------------------------------------------------

        .ifdef __C30ELF
            .type   __resetPRI,@function
        .endif
__resetPRI:
    .weak  __reset

    .ifdef __C30ELF
       .type   __reset,@function
    .endif

__reset:
        ; Set stack to bottom of RAM during bootload process, leave space for ICD3
        mov      #RAM_START, w15           ; initialize w15

        mov      #__SPLIM_init, w14     ; Set stack pointer limit
        mov      w14, SPLIM

        ;----------------------------------------------------------------------
        ; Osc config
        ;----------------------------------------------------------------------
        
        ; OSCCONbits.COSC = 0x011 - Primary Oscillator with PLL module (XTPLL, HSPLL, ECPLL)
        
        bset	OSCCON, #COSC0
        bset 	OSCCON, #COSC1
        bclr	OSCCON, #COSC2
        ; OSCCONbits.NOSC = 0b011 - Primary Oscillator with PLL module (XTPLL, HSPLL, ECPLL)		
        bset	OSCCON, #NOSC0
        bset	OSCCON, #NOSC1
        bclr	OSCCON, #NOSC2

        ;   CLKDIV = ((PLL_PRE_DIV - 2) | ((PLL_POST_DIV - 2) << 6))
        mov		#((PLL_PRE_DIV - 2) | ((PLL_POST_DIV - 2) << 6)), w0
        mov		w0, CLKDIV
        
        ;   PLLFBD = (PLL_VCO_MPY - 2)
        mov		#(PLL_VCO_MPY - 2), w0
        mov		w0, PLLFBD
        
        ; wait for PLL to stabilise
Wait_PLL:
        btss    OSCCON, #LOCK
        bra     Wait_PLL

        ; At this point the PLL has not been set up, so
        repeat  #384                    ; 10 us delay to allow things to stabilise
        nop
        
;------------------------------------------------------------------------------
; Bootloader check
;------------------------------------------------------------------------------

bootload_check:
        ; Set the UART Tx pin high, so that the master will not receive a bunch of 0's and
        ; generate a framing error

        ; Enable port pullup and tristate
        setm    AD1PCFGL
        bset    BL_Tx
        bclr    BL_TxTris
        bset    BL_RxTris
        bset    BL_DTR_Tris
        bset    BL_DTR_Pullup
        bset    BL_DTR_ChangeNotification

        bclr    IFS1,  #CNIF            ; Clear change-notification interrupt flag

        mov     #1000, w0               ; loop for 100 ms, or until port pin high, or until port pin change
delay:
        repeat  #3840                   ; small delay 100 us
        nop

        clrwdt                          ; Clear watchdog

        btsc    BL_DTR                  ; Is the DTR port pin high ?
        bra     usrapp                  ; .. yes, bypass the bootloader

        btsc    IFS1, #CNIF             ; Change on the port pin while we were not looking ?
        bra     usrapp                  ; .. yes, bypass the bootloader

        dec     w0, w0                  ; and repeat until done
        bra     NZ, delay
delay_end:


;------------------------------------------------------------------------------
; Do bootloading
;------------------------------------------------------------------------------

bootloader_reset:
        ; Create a stack frame for the buffer and aes tables
        lnk     #BL_STACK_FRAM_SIZE
        
        ; Initialise decryption, passing key as parameter
        ; aes_init(*key);
        mov     #psvpage(key), w0
        mov     w0, PSVPAG
        bset    CORCON, #PSV      ; Enable PSV
        mov     #psvoffset(key), w0
        rcall   aes_init

        ;----------------------------------------------------------------------
        ; RS232 port on UART2 settings
        ;----------------------------------------------------------------------
        ;----------------------------------------------------------------------
        ; I/O config
        ;----------------------------------------------------------------------
        
        ; Backup, these are restored in exit code at end of file
        ; Changes needs to be done in exit, search for xxx
        mov		RPINR19, WPPSTEMP1		;xxx
        mov		RPOR11, WPPSTEMP2		;xxx
       
        unlock_IO
        
        ; Receive, map pin (24 = 11000) to uart 2 RX
        bclr	RPINR19, #U2RXR0		;xxx
        bclr	RPINR19, #U2RXR1		;xxx
        bclr	RPINR19, #U2RXR2		;xxx
        bset	RPINR19, #U2RXR3		;xxx
        bset	RPINR19, #U2RXR4		;xxx
                
        ; Transmit, map pin 23 to uart 2 TX (00101)
        bset	RPOR11, #RP23R0			;xxx
        bclr	RPOR11, #RP23R1			;xxx
        bset	RPOR11, #RP23R2			;xxx
        bclr	RPOR11, #RP23R3			;xxx
        bclr	RPOR11, #RP23R4			;xxx

        lock_IO

;------------------------------------------------------------------------------
; Init
;------------------------------------------------------------------------------
        ; Clear flags
        clr     FLAGS

        ; Check to see if settings exist. Function sets flag fKEEP_SETTINGS if
        ; they exist & checksums are OK
        rcall   Chk_keep_settings

        ; UART
        bset	UMODE, #BRGH

        mov		#UARTBR, W0 		;set baudrate
        mov 	W0, UBRG			;
        bset 	UMODE, #UARTEN		;enable uart
        bset 	USTA, #UTXEN		;enable transmit

        mov     #10, w0             ; Wait for 10 ms
        call    Delay_ms

say_ready:
        ; At this point, we need to ack to the master controller that we can bootload

;------------------------------------------------------------------------------
; Receive DoBootload (from PC bootloader)
;------------------------------------------------------------------------------
        rcall 	Receive_1st_byte
        ; Validate command
        mov     #BOOTLOAD_CMD, w2           ; Store command without flags in w1
        and     w0, w2, w1
        
        bset    fDO_BOOTLOAD                ; Assume flag set
        btss    BL_FLAG_DO_BOOTLOAD         ; Check if bootload flag set
        bclr    fDO_BOOTLOAD                ; Not set, clear local flag
               
        xor     w1, w2, w2                  ; Check command in w1
        bra     nz, Abort                   ; bad command
        
        ; Test flags
        bset    fKEEP_SETTINGS              ; Assume keep user settings
        btsc    BL_FLAG_WRITE_SETTINGS      ; Test flag in command
        bclr    fKEEP_SETTINGS              ; Wipe OEM settings
        
        bset    fKEEP_OEM_SETTINGS          ; Assume keep OEM settings
        btsc    BL_FLAG_WRITE_OEM_SETTINGS  ; Test flag in command
        bclr    fKEEP_OEM_SETTINGS          ; Wipe OEM settings
        
        bclr    fLOAD_NEW_BOOTLOAD          ; Assume not a new bootloader
        btsc    BL_FLAG_NEW_BOOTLOADER      ; Test flag in command.
        bset    fLOAD_NEW_BOOTLOAD          ; Image is a new bootloader!    //TODO:
        
        bclr    fUNENCRYPTED                ; Assume enrypted
        btsc    BL_FLAG_UNENCRYPTED         ; Test flag in command.
        bset    fUNENCRYPTED                ; Unencrypted
        
        
bootloader_todo:
;TODO: It may be at a later stage we want to only program certain things, in this case no abort here.
 btss    fDO_BOOTLOAD
 bra     Abort                       ; .. abort, not implemented yet
 btsc    fLOAD_NEW_BOOTLOAD          ; .. Abort, not implemented yet
 bra    Abort

Bootload_start:
        ; Pre-erase the entire flash memory, excluding settings
        ; (if fKEEP_SETTINGS is true) and the bootloader.
        rcall   Flash_pre_erase

;------------------------------------------------------------------------------
; Send device id and firmware version
;------------------------------------------------------------------------------

        SendL 	DEVICEID
        SendL	VERMAJ
        SendL	(VERMIN*16 + VERREV)

;------------------------------------------------------------------------------
; Main
;------------------------------------------------------------------------------
        ; Send ok
Main:
        mov     #1, w0
        call    Delay_ms
        SendL 	OK
main1:
        clr 	WCRC     ; Init checksum

        ;----------------------------------------------------------------------
        ; Receive address
        ;----------------------------------------------------------------------
        ; Upper byte
        rcall 	Receive
        mov 	W0, TBLPAG
        ; High byte, use PR1 as temporary sfr
        rcall 	Receive
        mov.b	WREG, PR1+1
        ; Low byte, use PR1 as temporary sfr
        rcall 	Receive
        mov.b	WREG, PR1
        ;
        mov		PR1, WREG

        ;----------------------------------------------------------------------
        ; Receive command
        ;----------------------------------------------------------------------
        rcall 	Receive
        mov		W0, WCMD

        ;----------------------------------------------------------------------
        ; Receive nr of data bytes that will follow
        ;----------------------------------------------------------------------
        rcall 	Receive
        mov 	W0, WCNT

        ;----------------------------------------------------------------------
        ; Receive data
        ;----------------------------------------------------------------------
        mov 	FRAMEPTR, WBUFPTR
        mov     WCNT, W1
rcvdata:
        rcall 	Receive
        mov.b 	W0, [WBUFPTR++]
        dec		W1, W1
        bra 	NZ, rcvdata			;last byte received is checksum

        mov     #ROWSIZEW, WCNT     ;WCNT now contains number of words

        ;----------------------------------------------------------------------
        ; Check checksum
        ;----------------------------------------------------------------------
chksum:
        cp0.b 	WCRC
        bra 	Z, chksumok
        SendL 	CHECKSUMERR
        bra 	main1
chksumok:
        bclr    fSKIP_ROW

        ;----------------------------------------------------------------------
        ; 0x00 goto protection
        ;----------------------------------------------------------------------
chk_0x00_goto:
        bclr  fIS_FIRST_ROW     ; Assume not first row
        
        ; Only for write command
        btss	CMD_FLAG_WRITE_ROW
        bra		protgotook

        ; Only first row
        cp0		TBLPAG
        bra		nz, protgotook
        cp0		PR1
        bra		nz, protgotook
        
        ; OK 

        ; Flag to skip this row
        bset    fIS_FIRST_ROW
        
        bra     chk_cmd
protgotook:

        ;----------------------------------------------------------------------
        ; Bootloader protection
        ;----------------------------------------------------------------------
blprot:
        ; Calculate row number of received address
        mov		TBLPAG, W1
        mov		PR1,  W0
        mov		#(ROWSIZEW*2), WTEMP1
        repeat	#17
        div.ud	W0, WTEMP1  ; W = received address / (rowsizew*2)
        mov     W0, WTEMP1  ; Save row for settings protection

        ; Received row < bl start row = OK
        mov		#BL_START_ROW, W1
        cp		WTEMP1, W1
        bra		N, blprotok
        ; Received row > bl end row = OK
        mov		#BL_END_ROW, W1
        cp		W1, WTEMP1
        bra		N, blprotok
        ; In bootloader - skip and send OK
        bset    fSKIP_ROW

blprotok:

        ;----------------------------------------------------------------------
        ; Settings protection
        ;----------------------------------------------------------------------
settings_protect:
        ; Do we need to protect settings ?
        btss    fKEEP_SETTINGS
        bra     set_prot_ok       ; Flag clear, so if in settings region, it will be overwritten

        ; Flag set, so check if in settings region

        ; Received row < bl start row = OK
        mov		#SETTINGS_START_ROW, W1
        cp		WTEMP1, W1
        bra		N, set_prot_ok
        ; Received row > bl end row = OK
        mov		#SETTINGS_END_ROW, W1
        cp		W1, WTEMP1
        bra		N, set_prot_ok
        ; In settings range - skip
        bset    fSKIP_ROW
        
set_prot_ok:        
        
        ;----------------------------------------------------------------------
        ; OEM_Settings protection
        ;----------------------------------------------------------------------
oem_settings_protect:
        ; Do we need to protect settings ?
        btss    fKEEP_OEM_SETTINGS
        bra     oem_set_prot_ok       ; Flag clear, so if in oem-settings region, it will be overwritten

        ; Flag set, so check if in settings region

        ; Received row < bl start row = OK
        mov		#OEM_SETTINGS_START_ROW, W1
        cp		WTEMP1, W1
        bra		N, oem_set_prot_ok
        ; Received row > bl end row = OK
        mov		#OEM_SETTINGS_END_ROW, W1
        cp		W1, WTEMP1
        bra		N, oem_set_prot_ok
        ; In settings range - skip
        bset    fSKIP_ROW        
        
oem_set_prot_ok:        


        ;----------------------------------------------------------------------
        ; Check command
        ;----------------------------------------------------------------------
chk_cmd:
        mov 	FRAMEPTR, WBUFPTR		; Init pointer

        ; Erase page - but only react to PC bootloader command for page 0      
        btsc    CMD_FLAG_ERASE_PAGE
        bra		eraseact      

        ; Write row
        btsc	CMD_FLAG_WRITE_ROW
        bra		write_row

        ; Write config byte/word
        btsc	CMD_FLAG_WRITE_CONFIG
        bra		config

        ; Else, unknown command
        SendL   UCMD
        bra     main1

        ;----------------------------------------------------------------------
        ; "Erase activation"
        ;----------------------------------------------------------------------
eraseact:
        bset    fDO_ERASE
        bra		Main

        ;----------------------------------------------------------------------
        ; Write Row
        ;----------------------------------------------------------------------
write_row:
        btss	fDO_ERASE
        bra		decode
        
        ; All other pages have been erase, so only erase first page when first row is
        ; received
        btss    fIS_FIRST_ROW
        bra     decode
        
        btsc    fSKIP_ROW
        bra     decode
        
erase_1st_page:
        mov     PR1, W1
        tblwtl	W1, [W1]			;set base address of erase block
        ; Erase
        mov 	#FLASH_ERASE_CODE, W0
        rcall 	Write
        ; Erase finished
        bclr	fDO_ERASE

        ;----------------------------------------------------------------------
        ; Write row
        ;----------------------------------------------------------------------
decode:
        ; Unencrypted data ?
        btsc    fUNENCRYPTED
        bra     program ; .. Yes
        
        push.d  w4
        push.d  w6
        push.d  w8
        push.d  w10
        push.d  w12
        
        mov     FRAMEPTR, WDECODEPTR
        mov     #ROWSIZEBLOCKS, DECODECNTR
decode_loop:

        push.d  DECODECNTR
        mov     WDECODEPTR, w0
        mov     WDECODEPTR, w1
        rcall   aes_decode
        pop.d   DECODECNTR
        
        mov     #AESBLOCKSIZEB, w0
        dec     DECODECNTR, DECODECNTR
        bra     Z, decode_done
        add     w0, WDECODEPTR, WDECODEPTR
        bra     decode_loop
decode_done:        
        pop.d   w12
        pop.d   w10
        pop.d   w8
        pop.d   w6
        pop.d   w4
      
program:        
        btss    fIS_FIRST_ROW  
        bra     program_row
        
        ; Force first two instruction words to goto bootloader (2 word instruction)
        mov     FRAMEPTR, WBUFPTR
        mov     WBUFPTR, w1
        ; Goto instruction upper byte (instruction code)
        mov     #0x04, w0           
        mov.b   w0, [w1++]
        ; Lo byte of address
        mov.b   #STARTADDR & 0xFF, w0      
        mov.b   w0, [w1++]
        ; high byte of address
        mov.b   #(STARTADDR >> 8) & 0xFF, w0 
        mov.b   w0, [w1++]
        ;  zero out upper byte of second word
        clr     w0                  
        mov.b   w0, [w1++]
        
        ; upper byte of goto instruction into low byte of second word
        mov.b   #(STARTADDR >> 16) & 0xFF, w0 
        mov.b   w0, [w1++]
        
        ; zero out high byte of second word
        clr     w0        
        mov.b   w0, [w1++]
        
        ; Load latches
program_row:        
        ; Skip this row ?
        btsc    fSKIP_ROW
        bra     Main
        
        mov 	FRAMEPTR, WBUFPTR
        mov 	WCNT, W2
        mov     PR1, W1
latlo:
        tblwth.b 	[WBUFPTR++], [W1] 	;upper byte
        tblwtl.b	[WBUFPTR++], [W1++]	;low byte
        tblwtl.b	[WBUFPTR++], [W1++]	;high byte
        dec 	W2, W2
        bra 	nz, latlo
        ; Write flash row
        mov 	#FLASH_WRITE_CODE, W0
        rcall 	Write

        ;----------------------------------------------------------------------
        ; Verify row
        ;----------------------------------------------------------------------
        mov 	WCNT, W2
        mov 	FRAMEPTR, WBUFPTR
        mov     PR1, W1
        ; Verify upper byte
verrow:
        tblrdh.b [W1], W0
        cp.b	W0, [WBUFPTR++]
        bra		NZ, vfail
        ; Verify low byte
        tblrdl.b [W1++], W0
        cp.b	W0, [WBUFPTR++]
        bra		NZ, vfail
        ; Verify high byte
        tblrdl.b [W1++], W0
        cp.b	W0, [WBUFPTR++]
        bra		NZ, vfail
        ; Loop
        dec		W2, W2
        bra 	nz, verrow
        ; Verify completed without errors
        bra		Main

        ;----------------------------------------------------------------------
        ; Verify fail
        ;----------------------------------------------------------------------
vfail:
        SendL	VERFAIL
        bra		main1

        ;----------------------------------------------------------------------
        ; Write config words
        ;----------------------------------------------------------------------
config:
        mov  PR1, W1
        tblwtl.b W1, [W1]		;set base address of erase block
        ; Erase
        mov 	#CFG_ERASE_CODE, W0
        rcall 	Write
        ; Load latch
        tblwtl.b [WBUFPTR], [W1]
        ; Write
        mov 	#CFG_WRITE_CODE, W0
        rcall 	Write
        ; Write finished
        bra 	Main

;------------------------------------------------------------------------------
; Write()
;------------------------------------------------------------------------------
Write:
        mov 	W0, NVMCON
        disi    #0x55
        mov 	#0x55, W0
        mov 	W0, NVMKEY
        mov 	#0xAA, W0
        mov 	W0, NVMKEY
        bset 	NVMCON, #WR
        nop
        nop
        ; Wait for erase/write to finish
compl:
        btsc	NVMCON, #WR
        bra 	compl
        return

;------------------------------------------------------------------------------
; Send()
;------------------------------------------------------------------------------
Send:
        ;Send byte
        mov 	WREG, UTXREG
        nop
        nop
        ; Wait until transmit shift register is empty
txwait:
        btss	USTA, #TRMT
        bra		txwait

        ; Send complete
        return

;------------------------------------------------------------------------------
; Receive()
;------------------------------------------------------------------------------
; Allow time for the user to connect the bootloader on the PC - subsequent
; timeouts shorter.
Receive_1st_byte:
        mov     #BL_1ST_DELAY, WDEL1
        bset	fIN_INITIAL_TIMEOUT
        bra     rpt1
        ; Init delay
Receive:
        mov 	#BLDELAY, WDEL1
        bclr	fIN_INITIAL_TIMEOUT
        ; Check for received byte
rpt1:
        clr		WDEL2
rptc:
        clrwdt						;clear watchdog
        btss 	USTA, #URXDA
        bra 	notrcv
        mov 	URXREG, W0
        add 	WCRC, W0, WCRC		;add to checksum
        bclr	fIN_INITIAL_TIMEOUT        
        return
        ; Delay
notrcv:
        ; Check port pin if initial timeout
        btss	fIN_INITIAL_TIMEOUT  ; Initial timeout ?
        bra     NZ, rtimeout          ; .. No, update timeout
        btsc    BL_DTR                ; .. Yes, check port pin
        bra     exit                  ; Port pin high, so exit
        
rtimeout:
        dec 	WDEL2, WDEL2
        bra 	nz, rptc
        dec 	WDEL1, WDEL1
        bra 	nz, rpt1
        
        ; Send notification of timeout to master
        mov     WTEMP1, w0
        rcall   Send

        bra    exit                 ; and exit

;---------------------------------------------------------------------
; Flash_pre_erase - Pre-erase the entire flash memory, excluding page 0, settings
;    constants (if fKEEP_SETTINGS is true) and the bootloader.
;    This is done because the main program's checksum is calculated on the entire
;    flash memory. The PC bootloader will only command erasure of pages which are
;    in the hex file.
;---------------------------------------------------------------------
Flash_pre_erase:
        clr     TBLPAG
        mov     #1, W2  ; Skip page0 - point to second page

page_erase_loop:
        ; Some house-keeping
        clrwdt

        ; Clear Rx buffer - bootloading takes longer than default poll-time on PC bootloader
        ; program - so program will resend DO_BOOTLOAD char, so keep Rx buffer empty
clr_rx:
        btss 	USTA, #URXDA
        bra     chk_skip
        mov     URXREG, W0
        bra     clr_rx

chk_skip:
        ; Skip oem settings - if flag fOEM_KEEP_SETTINGS is true
        btss    fKEEP_OEM_SETTINGS
        bra     1f                 ; Flag clear, so don't check settings constant location
        mov		#OEM_SETTINGS_START_PAGE, W1
        cp		W2, W1
        bra		N, 1f
        ; Received row > bl end row = OK
        mov		#OEM_SETTINGS_END_PAGE, W1
        cp		W1, W2
        bra		N, 1f
        bra     next_page
1:

        ; Skip settings - if flag fKEEP_SETTINGS is true
        btss    fKEEP_SETTINGS
        bra     2f                 ; Flag clear, so don't check settings constant location
        mov		#SETTINGS_START_PAGE, W1
        cp		W2, W1
        bra		N, 2f
        ; Received row > bl end row = OK
        mov		#SETTINGS_END_PAGE, W1
        cp		W1, W2
        bra		N, 2f
        bra     next_page
2:

        ; Skip bootloader
        mov		#BL_START_PAGE, W1
        cp		W2, W1
        bra		N, 3f
        ; Received row > bl end row = OK
        mov		#BL_END_PAGE, W1
        cp		W1, W2
        bra		N, 3f
        bra     next_page
3:
        ; Calculate address
        mov     #1024, W0           ; Multiply W2 by 1024
        mul.uu  W0, W2, W0          ; Low word in W0
        mov     W1, TBLPAG          ; High word to TBLPAG
        tblwtl	W0, [W0]			; set base address of erase block
        ; Erase
        mov 	#FLASH_ERASE_CODE, W0
        rcall 	Write
next_page:
        inc     W2, W2
        mov     #FLASH_PAGE_MAX - 1, W0
        cp      W0, W2
        bra     GEU, page_erase_loop

        return

;---------------------------------------------------------------------
; Chk_keep_settings() - Check if settings must be kept
;  Sets / clears flag fKEEP_SETTINGS accordigly.
;  Checks the stored checksum against the calculated checksum,
; if that passes, checks the checksum complement
; if that passes, does a checksum on the whole settings page 
; including checksum and flags - if passes, keeps settings 
;---------------------------------------------------------------------
Chk_keep_settings:
        ; Determine if settings must be protected:
        ; 1) Checksum OK
        ; Set return 1 check if passes, else clear

        bclr    fKEEP_SETTINGS     ; Assume failure
        
        ; Calculate settings constants checksum
        ;-----------------------------------------

        ; Calculate expected checksum
        mov     #(.sizeof.(.settings)), w0  ; Get size of _STORED_SETTINGS in words
        asr		w0, #1, w0
        mov     #0x00FF, w1                 ; Checksum = 0xFF *
        mul.uu  w0, w1, w0
        mov		w0, w2						; W2 now contains expected checksum
                 

        ; .. point W0 to _STORED_SETTINGS data field
        bset.b  CORCONL, #PSV
        mov     #psvpage(_STORED_SETTINGS), w3
        mov     w3, PSVPAG
        mov     #psvoffset(_STORED_SETTINGS), w3  ; W3 now points to _STORED_SETTINGS
        
        ; Check the stored checksum
        cp  	w2, [w3]
        bra		nz, settings_overwite
        
        ; complement expected checksum & compare with stored checksum complement
        com		w2, w2
        inc2	w3, w3
        cp 		w2, [w3]
        bra		nz, settings_overwite
        
        ; Check checksum against stored data
        ; Use W3 as the itteration counter & w0 to point to settings
        mov     #.sizeof.(.settings), w3
        mov		#psvoffset(_STORED_SETTINGS), w0	; w0 points to stored setting struct
        
        com		w2, w2				; Restore calculated checksum
        clr		w1

settings_chksum_sub:
        mov.b   [w0++], w1
        sub     w2, w1, w2
        dec     w3, w3
        bra     NZ,settings_chksum_sub

        ; w2 should now be zero
        cp0	    w2
        bra		nz, settings_overwite
        
settings_keep:
        bset    fKEEP_SETTINGS
settings_overwite:
        ; No need to clear flag, assumption was made at start of routine
        ; that test would fail.
        return

;------------------------------------------------------------------------------
; Delay() for amount of ms passed in w0
;------------------------------------------------------------------------------
Delay_ms:
        mov     w0, WDEL1
dly_loop:
        clrwdt
        mov     #DELAY_1MS, WDEL2
dly11ms:
        dec     WDEL2, WDEL2
        bra     nz, dly11ms
        dec     WDEL1, WDEL1
        bra     nz, dly_loop

        return

;------------------------------------------------------------------------------
; Bootloader sent wrong DO_BOOTLOAD cmd char, abort
;------------------------------------------------------------------------------
Abort:
        SendL   ABORT

;------------------------------------------------------------------------------
; Exit point, clean up and load user application
;------------------------------------------------------------------------------
exit:
        ulnk                        ;Release variables on stack

        bclr	UIFS, #URXIF		;clear uart received interupt flag
        bclr	UIFS, #UTXIF		;clear uart transmit interupt flag
        bclr	USTA, #UTXEN		;disable uart transmit
        bclr 	UMODE, #UARTEN		;disable uart
        clr		PR1					;clear PR1, was used as temporary sfr

        ;---------------------------------------------------
        ; RS232 port on UART1 settings
        ;---------------------------------------------------
        unlock_IO
        mov		WPPSTEMP1, RPINR19	;xxx restore 
        mov		WPPSTEMP2, RPOR11		;xxx  pps settings
        lock_IO
        ; drop through to user application

;------------------------------------------------------------------------------
; Load user application
;------------------------------------------------------------------------------
usrapp:
        goto    __application_reset

key:   
    #include "../bootloader/key.inc"     

;------------------------------------------------------------------------------
; AES Decryption
;------------------------------------------------------------------------------
        
     ;---------------------------------------------------------------------------
     ;void aes_init(unsigned char *key)
aes_init:
     ;{
     push.w w8
     mov.w w0,w8
     ;   generate_log_tables();
     rcall generate_log_tables

     ;   aes_decode_init();
     rcall aes_decode_init

     ;   expand_key(key, &key_table[0]);
     mov.w #_key_table,w1
     mov.w w8,w0
     rcall expand_key
     ;}
     pop.w  w8
     return

     ;----------------------------------------------------------------------------
     ;void aes_decode_init(void)
aes_decode_init:
     ;{
     ;   make_inverse_s_box(&inv_s_box[0]);
     mov.w #_inv_s_box, w0
     rcall make_inverse_s_box
     ;}
     return

     ;---------------------------------------------------------------------------
     ;static void generate_log_tables()
generate_log_tables:
     ;{
     mov.b #0x1,w2
     clr.w w3
     mov.w #0xff,w5
     mov.w #_atable, w7
     mov.b #0x80,w4
     mov.w #0x7f8,w6
     ;   unsigned char n;
     ;   unsigned short ix;
     ;   unsigned char a = 1;
     ;   unsigned char d;

     ;   for(n = 0; n < 255; n++)
      ;   {
1:	
     ;     // Transpose table
     ;     ix = ((int)n * (int)8) % 255;
     repeat #17
     div.sw w3,w5
     exch w0,w1
     ;     atable[ix] = a;
     mov.b w2,[w0+w7]

           /* Multiply by three */
     ;      d = a & 0x80;
     ;      a <<= 1;
     add.b w2,w2,w1

     ;      if(d == 0x80)
     and.b w2,w4,w0
     sub.b w0,w4,[w15]
     bra nz, 2f   ; 0x000710
     ;      {
     ;        a ^= 0x1b;
     xor.b #0x1b,w1
     ;      }

     ;      a ^= atable[ix];
2:
     xor.b w2,w1,w2
     add.w w3,#8,w3

     sub.w w3,w6,[w15]
     bra nz, 1b   ;0x0006fe

           /* Set the log table value */
     ;   }

     ;   atable[255] = atable[0];
     mov.b _atable, wreg
     mov.b wreg, (_atable + 255)
     mov.w #0x1,w1
     mov.w #_atable,w4
     mov.w #_ltable,w3
     mov.w #0x100,w2

     ;   for (ix = 1; ix < 256; ix++)
3:
     mov.b [w4+w1],w0
     ze w0,w0
     mov.b w1,[w0+w3]

     inc.w w1,w1
     sub.w w1,w2,[w15]
     bra nz, 3b   ;0x000724
     ;   {
           /* Set the log table value */
     ;      ltable[atable[ix]] = ix;

     ;   }

     ;   ltable[0] = 0;
     clr.b _ltable
     ;}
     return


     ;---------------------------------------------------------------------------
     ;static unsigned char inline gadd(unsigned char a, unsigned char b)
     ;{
     ;	return a ^ b;
     ;}

     ;---------------------------------------------------------------------------
     ;static unsigned char gmul(unsigned char a, unsigned char b)
     ;{
gmul:
     ;  unsigned char p = 0;
     ; 	unsigned char counter;
     ;	unsigned char hi_bit_set;

     mov.b w0,w2
     clr.b w4
     mov.b #0x8,w3
     mov.b #0x80,w5
     ;   for (counter = 0; counter < 8; counter++)
     ;   {
1:
     btst.z w1,#0
     bra z, 2f    ;0x000742
     ;		if ((b & 1) == 1)
     ;            p ^= a;
     xor.b w4,w2,w4
     ;		hi_bit_set = (a & 0x80);
2:
     and.b w2,w5,w0
     ;		a <<= 1;
     add.b w2,w2,w2		
     ;		if (hi_bit_set)
     cp0.b w0
     bra z, 3f    ;0x00074c
     ;			a ^= 0x1b;
     xor.b #0x1b,w2
     ;		b >>= 1;
3:
     ze w1,w0
     lsr.w w0,w1
     dec.b w3,w3
     ;	}
     bra nz, 1b   ;0x00073C
     ze w4,w0

     ;   return p;
     ;}
     return

     ;---------------------------------------------------------------------------
     ;static unsigned char gmul_e(unsigned char a, unsigned char b)
gmul_e:
     ;{
     ;   int s;
     ;   int ix;
     mov.b w1,w3
     ;   if (!a || !b)
     cp0.b w0
     bra z, 3f	;0x000788
     cp0.b w1
     bra z, 3f	;0x000788
     ;   {
     ;	    s = 0;
     ;   }
     ;   else
     ;   {
     ;      s = ltable[a] + ltable[b];
     ze w0,w0
     mov.w #_ltable,w2
     mov.b [w0+w2],w1
     ze w1,w1
     ze w3,w0
     mov.b [w0+w2],w0
     ze w0,w0
     add.w w1,w0,w1

     ;      // Alternate:
     ;      //   ix = s % 255;
     ;      if (s>254)
     mov.w #0xfe,w0
     sub.w w1,w0,[w15]
     bra gt, 1f ;0x00077c
     mov.w w1,w0
     bra 2f ;0x00077e
     ;          ix = ++s;
1:
     inc.w w1,w0
     ;      else
     ;         ix = s;
     ;      ix &= 0xFF;
            /* Get the antilog */
     ;      s = atable[ix];
2:
     ze w0,w0
     mov.w #_atable,w1
     mov.b [w0+w1],w0
     ze w0,w0
     bra 4f	;0x00078a
3:
     clr.w w0
4:
     ze w0,w0
     ;  }

         
     ;    return s;
     ;}
     return

     ;----------------------------------------------------------------------------
     ;static unsigned char ginv(unsigned char in)
ginv:
     ;{
          /* 0 is self inverting */
     ;   if (in == 0)
     clr.w w1
     cp0.b w0
     bra z, 1f  ;0x0007a4
     ;      return 0;
     ;   else
     ;      return atable[(255 - ltable[in])];
     ze w0,w1
     mov.w #_ltable,w0
     mov.b [w1+w0],w0
     com.b w0,w0
     ze w0,w0
     mov.w #_atable,w1
     mov.b [w0+w1],w0
     ze w0,w1
1:
    ;}
     mov.w w1,w0
     return

     ;----------------------------------------------------------------------------
     /* Calculate the s-box for a given number */
     ;static unsigned char s_box_n (unsigned char n)
s_box_n:
     ;{
     ;    unsigned char x = ginv(n);
     rcall ginv

     ;   x = 0x63 ^ x ^ (x << 1) ^ (x << 2) ^ (x << 3) ^ (x << 4)
     ;                ^ (x >> 7) ^ (x >> 6) ^ (x >> 5) ^ (x >> 4);
     ze w0,w1
     add.w w1,w1,w2
     xor.b w0,w2,w0
     sl w1,#2,w2
     xor.b w0,w2,w0
     sl w1,#3,w2
     xor.b w0,w2,w0
     sl w1,#4,w2
     xor.b w0,w2,w0
     lsr w1,#7,w2
     xor.b w0,w2,w0
     lsr w1,#6,w2
     xor.b w0,w2,w0
     lsr w1,#5,w2
     xor.b w0,w2,w0
     lsr w1,#4,w1
     xor.b w0,w1,w0
     xor.b #0x63,w0
     ze w0,w0


     ;   return x;
     ;}
     return

     ;---------------------------------------------------------------------------
     /* Calculate the rcon used in key expansion */
     ;static unsigned char rcon(unsigned char in)
rcon:
     ;{
     push.d w8
     mov.b w0,w2
     ;   unsigned char c = 1;

     ;   if (in == 0)
     clr.w w0
     cp0.b w2
     bra z, 5f ;0x000804
     bra 4f   ;0x0007fc
1:
     mov.b w2,w8
     mov.b #0x1,w3
     setm.w w0
     mul.ss w2,w0,w0
     add.b w2,w0,w0
     inc.b w0,w9
     ;      return 0;
2:
     mov.b #0x2,w1
     mov.b w3,w0
     rcall gmul
     mov.b w0,w3

     dec.b w8,w8

     ;   while (in != 1)
     sub.b w8,w9,[w15]
     bra nz, 2b  ;0x0007ea
3:
     ze w3,w0
     bra 5f ;0x000804
4:
     sub.b w2,#1,[w15]
     bra nz, 1b ;0x0007de
     mov.b w2,w3
     bra 3b ;0x0007f8
     ;   {
     ;      c = gmul(c, 2);

     ;      in--;
     ;   }

     ;   return c;
5:
     ;}
     pop.d w8
     return

     ;---------------------------------------------------------------------------
     /* This is the core key expansion, which, given a 4-byte value, does some scrambling */
     ;static void schedule_core(unsigned char *in, unsigned char i)
schedule_core:
     ;{
     push.d w8
     push.d w10
     mov.w w0,w10
     ;     unsigned char a;
         /* Rotate the input 8 bits to the left */
     ;   rotate(in);
     mov.b w1,w11
     rcall rotate

         /* Apply Rijndael's s-box on all 4 bytes */
     ;   for (a = 0; a < 4; a++)
     clr.w w9
1:
     add.w w10,w9,w8
     ;      in[a] = s_box_n(in[a]);
     mov.b [w8],w0
     rcall s_box_n
     mov.b w0,[w8]
     inc.w w9,w9

     sub.w w9,#4,[w15]
     bra nz, 1b ;0x000814

         /* On just the first byte, add 2^i to the byte */
     ;   in[0] ^= rcon(i);
     mov.b [w10],w8
     mov.b w11,w0
     rcall rcon
     xor.b w8,w0,[w10]
     ;}
     pop.d,w10
     pop.d,w8
     return

     ;---------------------------------------------------------------------------
     ;static void expand_key(unsigned char *key, unsigned char *key_table)
expand_key:
     ;{
     lnk #0x04
     push.d w8
     push.d w10
     push.d w12
     ;   unsigned char t[4];
         /* c is 16 because the first sub-key is the user-supplied key */
     ;   unsigned char c = 16;
     ;   unsigned char i = 1;
     ;   unsigned char a;

     ;   for (i=0; i < 16; i++)
     mov.w w0,w2
     mov.w w1,w9
     clr.w w0
     mov.w #_init_vector,w3
     clr.b w1
     ;   {
1:
     ;      key_table[i] = key[i];
     ;      init_vector[i] = 0;
     mov.b [w2+w0],[w9+w0]
     mov.b w1,[w0+w3]
     inc.w w0,w0

     sub.w w0,#16,[w15]
     bra nz, 1b;
     ;   }
     
     add.w w9,#12,w10
     
     ;   i = 1;
     mov.b #0x1,w13

         /* We need 11 sets of sixteen bytes each for 128-bit mode */
     ;   while(c < 176)
     ;   {
     mov.w w0,w11
     sub.w w15,#12,w12
2:
            /* Copy the temporary variable over from the last 4-byte block */
     ;      for(a = 0; a < 4; a++)
     mov.b w11,w8
     mov.w w10,w1
     sub.w w15,#16,w0
     ;         t[a] = key_table[a + c - 4];     
3:
     mov.b [w1++],[w0++]
     sub.w w12,w0,[w15]
     bra nz, 3b   ;0x000890
            /* Every four blocks (of four bytes), do a complex calculation */
     ;      if(c % 16 == 0)
     and.w w11,#15,w0
     bra nz, 4f   ;0x0008a2
     ;      {
     ;         schedule_core(t, i);
     mov.b w13,w1
     sub.w w15,#16,w0
     rcall schedule_core
     ;         i++;
     inc.b w13,w13
4:
     sub.w w15,#16,w2
     ;      }
     ;      for(a = 0; a < 4; a++)
     ;      {
5:
     ze w8,w0
     add.w w9,w0,w0
     ;         key_table[c] = key_table[c - 16] ^ t[a];
     ;         c++;
     mov.b [w0-16],w1
     xor.b w1,[w2++],[w0]

     inc.b w8,w8

     ;      }     
     sub.w w12,w2,[w15]
     bra nz, 5b   ;0x0008a4
     add.w w11,#4,w11
     add.w w10,#4,w10

     ;}
     mov.w #0xb0,w0
     sub.w w11,w0,[w15]
     bra nz, 2b   ;0x00088a
     ;}

     pop.d w12
     pop.d w10
     pop.d w8
     ulnk
     return
    ;}

     ;---------------------------------------------------------------------------
     ;static void add_round_key(unsigned char *in, unsigned char *r_key)
add_round_key:
     ;{
     mov.w w0,w4
     mov.w w1,w3
     ;     unsigned char n;

     ;   for (n = 0; n < 16; n++)
     clr.w w2
     ;   {
1:
     add.w w4,w2,w1
     ;      in[n] = gadd(in[n], r_key[n]);
     mov.b [w2+w3],w0
     xor.b w0,[w1],[w1]
     inc.w w2,w2
     ;   }
     sub.w w2,#16,[w15]
     bra nz, 1b   ;0x000890
     ;}
     return

     ;---------------------------------------------------------------------------
     ;static void rotate(unsigned char *in)
rotate:
     ;{
     ;   unsigned char a, c;

     ;   a = in[0];
     mov.b [w0],w3
     mov.w w0,w1
     mov.b #0x3,w2

     ;   for (c = 0; c < 3; c++)
1:
     ;      in[c] = in[c + 1];
     mov.b [w1+1],w4
     mov.b w4,[w1]
     dec.b w2,w2
     inc.w w1,w1

     cp0.b w2
     bra nz, 1b   ;0x0008a4

     ;   in[3] = a;
     mov.b w3,[w0+3]

     ;   return;
     ;}

     return

     ;----------------------------------------------------------------------------
     /* Calculate the inverse  s-box for a given number */
     ;static unsigned char inv_s_box_n(unsigned char n)
inv_s_box_n:
     ;{
     ;    return ginv(0x05 ^ (n << 1) ^ (n << 3) ^ (n << 6)
     ;                     ^ (n >> 7) ^ (n >> 5) ^ (n >> 2));
     ze w0,w2
     add.w w2,w2,w0
     sl w2,#3,w1
     xor.b w0,w1,w0
     sl w2,#6,w1
     xor.b w0,w1,w0
     lsr w2,#7,w1
     xor.b w0,w1,w0
     lsr w2,#5,w1
     xor.b w0,w1,w0
     lsr w2,#2,w1
     xor.b w0,w1,w0
     xor.b #0x5,w0
     rcall ginv
     ze w0,w0
     ;}
     return

     ;----------------------------------------------------------------------------
     ;static void make_inverse_s_box (unsigned char inv_s_box[256])
make_inverse_s_box:
     ;{
     push.d w8
     push.w w10
     mov.w w0,w9
     clr.w w8
     mov.w #0x100,w10

     ;   for (int n = 0; n < 256; n++)
     ;   {
1:
     ;      inv_s_box[n] = inv_s_box_n(n);
     mov.b w8,w0
     rcall inv_s_box_n
     mov.b w0,[w8+w9]
     ;   }
     inc.w w8,w8
     sub.w w8,w10,[w15]
     bra nz, 1b   ;0x0008de
     ;}
     pop.w w10
     pop.d w8
     return

     ;---------------------------------------------------------------------------
     ;static void inv_mix_column (unsigned char *r)
inv_mix_column:
     ;{
     lnk #0x04
     push.d w8
     push.d w10
     push.d w12
     mov.w w0,w13
     ;   unsigned char a[4];
     ;   unsigned char c;
     
     ;   for(c = 0; c < 4; c++)
     clr.w w0
     ;   {
1:
     ;      a[c] = r[c];
     mov.b [w0+w13],w2
     sub.w w15,#16,w1
     mov.b w2,[w1+w0]
     inc.w w0,w0
     ;   }
     sub.w w0,#4,[w15]
     bra nz, 1b   ;0x0008fc

     ;   r[0] = gmul_e(a[0],14) ^ gmul_e(a[3],9) ^ gmul_e(a[2],13) ^ gmul_e(a[1],11);
     mov.b [w15-16],w11
     mov.b [w15-13],w8
     mov.b [w15-14],w9
     mov.b [w15-15],w10
     mov.b #0xe,w1
     mov.b w11,w0
     rcall gmul_e
     mov.b w0,w12
     mov.b #0x9,w1
     mov.b w8,w0
     rcall gmul_e
     xor.b w12,w0,w12
     mov.b #0xd,w1
     mov.b w9,w0
     rcall gmul_e
     xor.b w12,w0,w12
     mov.b #0xb,w1
     mov.b w10,w0
     rcall gmul_e
     xor.b w12,w0,[w13]
     ;   r[1] = gmul_e(a[1],14) ^ gmul_e(a[0],9) ^ gmul_e(a[3],13) ^ gmul_e(a[2],11);
     mov.b #0xe,w1
     mov.b w10,w0
     rcall gmul_e
     mov.b w0,w12
     mov.b #0x9,w1
     mov.b w11,w0
     rcall gmul_e
     xor.b w12,w0,w12
     mov.b #0xd,w1
     mov.b w8,w0
     rcall gmul_e
     xor.b w12,w0,w12
     mov.b #0xb,w1
     mov.b w9,w0
     rcall gmul_e
     xor.b w12,w0,w0
     mov.b w0,[w13+1]
     ;   r[2] = gmul_e(a[2],14) ^ gmul_e(a[1],9) ^ gmul_e(a[0],13) ^ gmul_e(a[3],11);
     mov.b #0xe,w1
     mov.b w9,w0
     rcall gmul_e
     mov.b w0,w12
     mov.b #0x9,w1
     mov.b w10,w0
     rcall gmul_e
     xor.b w12,w0,w12
     mov.b #0xd,w1
     mov.b w11,w0
     rcall gmul_e
     xor.b w12,w0,w12
     mov.b #0xb,w1
     mov.b w8,w0
     rcall gmul_e
     xor.b w12,w0,w0
     mov.b w0,[w13+2]
     ;   r[3] = gmul_e(a[3],14) ^ gmul_e(a[2],9) ^ gmul_e(a[1],13) ^ gmul_e(a[0],11);
     mov.b #0xe,w1
     mov.b w8,w0
     rcall gmul_e
     mov.b w0,w8
     mov.b #0x9,w1
     mov.b w9,w0
     rcall gmul_e
     xor.b w8,w0,w8
     mov.b #0xd,w1
     mov.b w10,w0
     rcall gmul_e
     xor.b w8,w0,w8
     mov.b #0xb,w1
     mov.b w11,w0
     rcall gmul_e
     xor.b w8,w0,w0
     mov.b w0,[w13+3]
     ;}
     pop.d w12
     pop.d w10
     pop.d w8
     ulnk
     return

     ;---------------------------------------------------------------------------
     ;static void inv_rotate_row(unsigned char *in, unsigned char n)
inv_rotate_row:
     ;{
     ;   unsigned char a, c, i;

     ;   // The arrays are structured such that column[0] is array[0..3],
     ;   // column[1] is array[4..7], so row[0] consists of array[0,4,8,12],
     ;   // row[1] consists of array[1,5,9,13] etc.

     ;   for (i = 0; i < n; i++)
     cp0.b w1
     bra z, 3f    ;0x0009c0
     clr.b w5
     ;   {
1:
     ;      a = in[12];
     mov.b [w0+12],w4
     add.w w0,#8,w2
     mov.b #0x3,w3

     ;      // Because of order in which c stores data, transpose
     ;      for (c = 3; c > 0; c--)
     ;      {
2:
     ;         in[c * 4] = in[(c - 1) * 4];
     mov.b [w2],w6
     mov.b w6,[w2+4]
     dec.b w3,w3
     sub.w w2,#4,w2
     ;      }
     cp0.b w3
     bra nz, 2b   ;0x0009ac

     ;      in[0] = a;
     mov.b w4,[w0]
     ;   }
     inc.b w5,w5
     sub.b w1,w5,[w15]
     bra nz, 1b   ;0x0009a6
3:
     ;}
     return


     ;---------------------------------------------------------------------------
     ;static void decode_row_shift(unsigned char *in)
decode_row_shift:
     ;{
     push.d w8
     inc.w w0,w8
     ;   unsigned char row;

     ;   // Row[0] does not get shifted, Row[1] gets shifted one place right,
     ;   // Row[2] two places etc.
     ;   for (row = 1; row < 4; row++)
   mov.b #0x1,w9
     ;   {
1:
     ;      inv_rotate_row(&in[row], row);
     mov.b w9,w1
     mov.w w8,w0
     rcall inv_rotate_row

     inc.b w9,w9
     inc.w w8,w8
     sub.b w9,#4,[w15]
     bra nz, 1b   ;0x0009c8
     ;   }
     ;}
     pop.d w8
     return

     ;---------------------------------------------------------------------------
     ;static void decode_subtitute(unsigned char *in)
decode_subtitute:
     ;{
     ;   unsigned char n;
     ;   for (n = 0; n < 16; n++)
     mov.w w0,w3
     clr.w w2
     mov.w #_inv_s_box,w4
1:
     add.w w2,w3,w1
     ;      in[n] = inv_s_box[in[n]];
     ze [w1],w0
     mov.b [w0+w4],[w1]
     inc.w w2,w2
     ;   }
     sub.w w2,#16,[w15]
     bra nz, 1b   ;0x0009e0
     ;}
     return
     
     ;---------------------------------------------------------------------------
     ;static void decode_mix_columns(unsigned char *in)
decode_mix_columns:
     ;{
     ;   unsigned char col;
     ;   for (col = 0; col < 4; col++)
     ;   {
     push.d w8
     mov.w w0,w8
     mov.b #0x4,w9
1:
     ;      inv_mix_column(&in[col * 4]);
     mov.w w8,w0
     rcall inv_mix_column
     dec.b w9,w9
     add.w w8,#4,w8
     ;   }
     cp0.b w9
     bra nz, 1b   ;0x0009f4
     ;}
     pop.d w8
     return


     ;---------------------------------------------------------------------------
     ;void aes_decode(unsigned char *in, unsigned char *state)
aes_decode:
     ;{
     lnk #0x10
     push.d w8
     push.w w10
     ;   unsigned char round_cntr = 10;
     ;   unsigned char *key = &key_table[0];
     ;   unsigned char i;
     ;   unsigned char new_iv[16];    
     ;{
     mov.w w0,w2
     mov.w w1,w8
     ;   for (i = 0; i < 16; i++)
   clr.w w1
     ;   {
1:
     add.w w1,w2,w0
     ;      new_iv[i] = in[i];
     mov.b [w0],w3
     mov.b w3,[w8+w1]
     ;      state[i] = in[i];
     mov.b [w0],w3
     sub.w w15,#22,w4
     mov.b w3,[w4+w1]
     ;   }          
     inc.w w1,w1
     sub.w w1,#16,[w15]
     bra nz, 1b   ;0x000a4c

         // Key Add
     ;   add_round_key(&state[0], &key[round_cntr * 16]);
     mov.w #_key_table + 160,w1
     mov.w w8,w0
     rcall add_round_key
     mov.b #0xa,w9
     mov.w #_key_table,w10
     ;   do
     ;   {
     
     bra 3f   ;0x000a72
2:
     ;      if (round_cntr != 10)
     sub.b w9,#10,[w15]
     bra z, 3f    ;0x000a72
     ;         decode_mix_columns(&state[0]);
     mov.w w8,w0
     rcall decode_mix_columns
            // Shift
     ;      decode_row_shift(&state[0]);
3:
     mov.w w8,w0
     rcall decode_row_shift

            // substitution
     ;      decode_subtitute(&state[0]);
     mov.w w8,w0
     rcall decode_subtitute
     
     ;      round_cntr--;
     dec.b w9,w9

         // Key Add
     ;      add_round_key(&state[0], &key[round_cntr * 16]);
     ze w9,w1
     sl w1,#4,w1
     add.w w1,w10,w1
     mov.w w8,w0
     rcall add_round_key
     
     ;    }
     ;      while (round_cntr > 0);
     cp0.b w9
     bra nz, 2b   ;0x000a6a
     clr.w w1

     ;       init_vector[i] = new_iv[i];
     mov.w #_init_vector,w2
     
          // Save Initialisation vector for next time
     ;    for (i = 0; i < 16; i++)     
     ;    {     
 4:
     add.w w8,w1,w0
     ;       state[i] = state[i] ^ init_vector[i];
     mov.b [w0],w4
     xor.b w4,[w2],[w0]

     sub.w w15,#22,w0
     mov.b [w0+w1],[w2++]
     inc.w w1,w1
     ;}
     sub.w w1,#16,[w15]
     bra nz, 4b   ;0x000a8e
      
     ;}
     pop.w w10
     pop.d w8
     ulnk
     return
     

        ; Pad the rest of the segment with the reset instruction (0xFE0000)
        .fillupper 0xFE
        .align 1024, 0x00

_bootloader_end:

;------------------------------------------------------------------------------
; End of code
;------------------------------------------------------------------------------
        .end
