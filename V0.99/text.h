#ifndef TEXT_H
#define TEXT_H

typedef struct tagT_WINDOW
{
   byte Left;
   byte Top;
   byte Width;
   byte Height;
} tWindow, *pWindow;

void ClrScr(void);
void SetTextWindow(const byte Left, const byte Top, const byte Width, const byte Height);
void AssignTextWindow(const tWindow AWindow);
tWindow GetTextWindow(void);
void SetOverlayWindow(void);
tWindow GetOverlayWindow(void);
void FullScreen(void);
void ClrEOL(void);
void GotoXY(const byte X, const byte Y);
byte GetCursorX(void);
byte GetCursorY(void);
tPoint GetCursor(void);
void SetCursor(const tPoint Point);
void WriteChar(const char c);
void WriteStr(const char String[]);
void WriteStrXY(byte X, byte Y, bool RightJustify, const char String[]);
void WriteFill(const char FillChar, const byte Count);
void ScrollUp(void);
void SetTabStopSize(const byte TabSize);
void SetTextSize(const byte Size);
void SetTextColor(const tTextColor NewTextColor);
tTextColor GetTextColor(void);
void SetTextBackground(const tTextBkgnd NewTextBackground);
void SetTextAttribute(const tTextAttribute NewTextAttribute);
void SetOverlayAlignment(const tOverlayAlignment NewTextBlockAlignment);
bool TextIsEOL(void);
void GotoEOL(void);
void StatusLineClr(void);
void StatusLinePutStr(const char *StatusStr);

#ifndef TEXT_C
extern char TextPage[TEXT_LINES][TEXT_COLUMNS];
extern bool fEchoText;
extern bool fEchoMenu;
extern bool TextPause;
extern bool fStatusFlasher;

#endif   



#endif
