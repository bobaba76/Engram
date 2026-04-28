#ifndef STATUS_LINE_H
#define STATUS_LINE_H

#define STATUS_ITEM_COUNT 10
#define USER_STATUS_ITEMS 8
#define STATUS_INDEX_VIDEO_LOW 8
#define STATUS_INDEX_VIDEO_OFF 9

typedef enum tagSTATUS_LINE_ITEM_TYPE
{
   sliNone,          // 
   sliStatus,        // Items like low-video
   sliAlarm,         // 
} tStatusLineItemType;

typedef enum tagSTATUS_LINE_END_CONDITION
{
   slcOnConditionClear,
   slcOnTimeout,
   slcOnNewTransaction,
   slcOnTransactonOrTimeout
} tStatusLineEndCondition;



typedef struct tagSTATUS_LINE_ITEM
{
   tStatusLineItemType     ItemType;
   tStatusLineEndCondition EndCondition;
   word                    DisplayTimeMaxSec;
   word                    DisplayTimer;
   bool                    IsActive;
   bool                    PrevActiveState;
   char                    *Caption;   
   char                    *ShortCaption;
} tStatusLineItem;


extern tStatusLineItem  StatusLineItem[STATUS_ITEM_COUNT];

void UpdateStatusLine(void);

//--------------------------------------------------------------------------------------------------
#ifdef STATUS_LINE_C

tStatusLineItem  StatusLineItem[STATUS_ITEM_COUNT] ={
   [0] =   
   {
      .ItemType =  sliAlarm,
      .EndCondition =  slcOnTransactonOrTimeout,
      .DisplayTimeMaxSec =  30,
      .DisplayTimer =  30,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "TRANSACTION VOID",
      .ShortCaption =  (char*)&STORED_SETTINGS.Data.AlarmTriggers[0] //"VOID"
   },
   [1] =   
   {
      .ItemType =  sliAlarm,
      .EndCondition =  slcOnTransactonOrTimeout,
      .DisplayTimeMaxSec =  30,
      .DisplayTimer =  30,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "TRANSACTION CANCELLED",   
      .ShortCaption = (char*)&STORED_SETTINGS.Data.AlarmTriggers[1]  // Cancelled
   },
   [2] =   
   {
      .ItemType =  sliAlarm,
      .EndCondition =  slcOnTransactonOrTimeout,
      .DisplayTimeMaxSec =  30,
      .DisplayTimer =  30,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "REFUND",   
      .ShortCaption =  "REFUND"
   },
   [3] =   
   {
      .ItemType =  sliNone,
      .EndCondition =  slcOnTransactonOrTimeout,
      .DisplayTimeMaxSec =  30,
      .DisplayTimer =  30,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "",   
      .ShortCaption =  ""
   },
   [4] =   
   {
      .ItemType =  sliNone,
      .EndCondition =  slcOnTransactonOrTimeout,
      .DisplayTimeMaxSec =  30,
      .DisplayTimer =  30,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "",   
      .ShortCaption =  ""
   },   
   [5] =   
   {
      .ItemType =  sliNone,
      .EndCondition =  slcOnTransactonOrTimeout,
      .DisplayTimeMaxSec =  30,
      .DisplayTimer =  30,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "",   
      .ShortCaption =  ""
   },
   [6] =   
   {
      .ItemType =  sliNone,
      .EndCondition =  slcOnTransactonOrTimeout,
      .DisplayTimeMaxSec =  30,
      .DisplayTimer =  30,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "",   
      .ShortCaption =  ""
   },
   [7] =   
   {
      .ItemType =  sliNone,
      .EndCondition =  slcOnTransactonOrTimeout,
      .DisplayTimeMaxSec =  30,
      .DisplayTimer =  30,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "",   
      .ShortCaption =  ""
   },
   [8] =
   {
      .ItemType =  sliStatus,
      .EndCondition =  slcOnConditionClear,
      .DisplayTimeMaxSec =  0,
      .DisplayTimer =  0,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "VIDEO LOW",   
      .ShortCaption =  ""
   },
   [9] =
   {
      .ItemType =  sliStatus,
      .EndCondition =  slcOnConditionClear,
      .DisplayTimeMaxSec =  0,
      .DisplayTimer =  0,
      .IsActive =  false,
      .PrevActiveState = false,
      .Caption =  "NO VIDEO IN",   
      .ShortCaption =  ""
   }
};

#endif

#endif
