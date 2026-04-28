#ifndef VIDEO_OVERLAY_H
#define VIDEO_OVERLAY_H

// Boot Segment Program Flash Write Protection
   _FBS(RBS_NO_RAM & BSS_NO_BOOT_CODE)
   
// Secure esgment protection
   _FSS(RSS_NO_RAM & SSS_NO_FLASH & SWRP_WRPROTECT_OFF)
   
// General segment code protection
#ifdef __DEBUG
   _FGS(GWRP_OFF)
#else
   _FGS(GCP_ON)
#endif

// Oscillator
   _FOSCSEL(FNOSC_PRIPLL & IESO_ON)
   _FOSC(FCKSM_CSDCMD & IOL1WAY_OFF & POSCMD_XT)
   
// Power-up timer
   _FPOR(FPWRT_PWR128 & ALTI2C_OFF)

#ifdef __DEBUG   
// Debug
   _FICD(JTAGEN_OFF & ICS_PGD2)
#else
   _FICD(JTAGEN_OFF)
#endif      
   
// Watchdog timer
#ifdef __DEBUG
   _FWDT(FWDTEN_OFF)
#else
   _FWDT(FWDTEN_ON & WINDIS_OFF & WDTPRE_PR32 & WDTPOST_PS256)
#endif
   
   
#else
#error "This file must be included only once"
#endif
