#ifndef SW_TIMER_H
#define SW_TIMER_H

// Global Constants:
// -----------------

// Software timer update rate is once a main cycle
#define SW_TIMER_UPDATE_RATE (MAIN_LOOP_MS)


// Indices of sw timers
enum
{
   RUN_LED_TMR,
   MENU_TIMEOUT_TMR,
   OVERLAY_TIMEOUT_TMR,
   POS_LINE_TMR,
   SCROLL_PAUSE_TMR,
   STATUS_LINE_FLASH_TMR,
   SW_TIMER_COUNT                // Number of sw timer - must be last in enum
};

// Allocate timers


// Global Type Definitions:
// ------------------------

// Software Timer "object". The function pointers except *Callback are populated in this file
// as global variable initialisation.
typedef struct tagSW_TIMER tSwTimer; 
struct tagSW_TIMER
{
   uint32 Cycles;                // Timer is based on cycles. Updated everytime .Update is called
   uint32 Reload;              	// Reload value for astable operation
   bool Run;                     // Timer updates when Run is true. Monostable timeout clears this
   bool TimedOut;                // Cleared in Go, set on timeout
   bool IsMonostable;            // When true, timer operates in astable mode
   bool Is_ms_Timer;             // When true, times in ms, else in seconds
   void (*Go)(tSwTimer*, word);	// First parameter pointer to timer instance, second to time in ms
                                 //   ms. Example usage; foo.Go(&foo, 100); 
   void (*Update)(tSwTimer*);    
   void (*Callback)(tSwTimer*);
};


// Global function prototypes:
// ---------------------------

#ifndef SW_TIMER_C
// Header file invoked from CSU other than sw_timer.c

// Exported Variables:
// -------------------

extern tSwTimer SwTimer[SW_TIMER_COUNT];

#else

// Local Type Definitions:
// -----------------------
// .. None

// Local Constants:
// ----------------
// .. None

// Local Function Prototypes:
// --------------------------

static void tSwTimer_Go(tSwTimer *this, word Time);

static void tSwTimer_Update(tSwTimer *this);

static void Run_LED_TmrCallback(tSwTimer *this);

static void MenuTmrCallback(tSwTimer *this);

static void OverlayTmrCallback(tSwTimer *this);

static void POS_LineTmrCallback(tSwTimer *this);

static void ScrollPauseTmrCallback(tSwTimer *this);

static void StatusLineFlashTmrCallback(tSwTimer *this);

// Local Persistant Variables
// --------------------------
// .. None

// Global Variable Allocation and Init:
// ------------------------------------

tSwTimer SwTimer[SW_TIMER_COUNT] =
{
   [RUN_LED_TMR] =    
   {
      .Cycles = 300,
      .Reload = 300,
      .Run = false,         // Set to Run here so we do not need to init (call SwTimer.Go())
      .TimedOut = false,
      .IsMonostable = false,
      .Is_ms_Timer = true,
      .Go = tSwTimer_Go,
      .Update = tSwTimer_Update,
      .Callback = Run_LED_TmrCallback
   },
   [MENU_TIMEOUT_TMR] = 
   {
      .Cycles = 0,
      .Reload = 0,
      .TimedOut = false,
      .Run = false,
      .IsMonostable = true,
      .Is_ms_Timer = false,
      .Go = tSwTimer_Go,
      .Update = tSwTimer_Update,
      .Callback = MenuTmrCallback
   }, 
   [OVERLAY_TIMEOUT_TMR] = 
   {
      .Cycles = 0,
      .Reload = 0,
      .TimedOut = false,
      .Run = false,
      .IsMonostable = true,
      .Is_ms_Timer = false,
      .Go = tSwTimer_Go,
      .Update = tSwTimer_Update,
      .Callback = OverlayTmrCallback
   }, 
   [POS_LINE_TMR] =
   {
      .Cycles = 0,
      .Reload = 0,
      .TimedOut = false,
      .Run = false,
      .IsMonostable = true,
      .Is_ms_Timer = true,
      .Go = tSwTimer_Go,
      .Update = tSwTimer_Update,
      .Callback = POS_LineTmrCallback
   },
   [SCROLL_PAUSE_TMR] =
   {
      .Cycles = 0,
      .Reload = 0,
      .TimedOut = false,
      .Run = false,
      .IsMonostable = true,
      .Is_ms_Timer = true,
      .Go = tSwTimer_Go,
      .Update = tSwTimer_Update,
      .Callback = ScrollPauseTmrCallback
   },
   [STATUS_LINE_FLASH_TMR] =
   {
      .Cycles = 333,
      .Reload = 333,
      .TimedOut = false,
      .Run = true,
      .IsMonostable = false,
      .Is_ms_Timer = true,
      .Go = tSwTimer_Go,
      .Update = tSwTimer_Update,
      .Callback = StatusLineFlashTmrCallback
   }
};

#endif /* SW_TIMER_C */

#else
#error "File 'sw_timer.h' included more than once"
#endif /* SW_TIMER_H */
