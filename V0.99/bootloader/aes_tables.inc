    
    .ifndef __C30__
    
    .equ    RAM_START,          0x0900              ; Leave space for ICD3
    .equ    BUFFER_START,       (RAM_START + 2)     ; And lnk instruction push
    .equ    LTABLE_SIZE,        256
    .equ    ATABLE_SIZE,        256
    .equ    KEY_TABLE_SIZE,     176
    .equ    INV_S_BOX_SIZE,     256
    .equ    INIT_VECTOR_SIZE,   16 
        
    ; C tables 
    ; We cannot use .space to allocate variable, etc. - they will be permanently linked in
    ; and we wan't to use the stack (which is plentifull during bootloading) so that no 
    ; application RAM is used.
    
    ;extern unsigned char ltable[256];      //0x9C4
    .equ    _ltable,        (BUFFER_START + BUFFER_ALLOCATE_SIZE) 
    
    ;extern unsigned char atable[256];      //0xAC4
    .equ    _atable,        (_ltable + (LTABLE_SIZE))             

    ;extern unsigned char key_table[17];    //0xBC4
    .equ    _key_table,     (_atable + (ATABLE_SIZE))            

    ;extern unsigned char inv_s_box[256];   //0xC74
    .equ    _inv_s_box,     (_key_table + (KEY_TABLE_SIZE))    
    ;extern unsigned char init_vector[16];  //0xD74
    .equ    _init_vector,   (_inv_s_box + (INV_S_BOX_SIZE))
    
    .equ    BL_STACK_FRAM_SIZE, (BUFFER_ALLOCATE_SIZE+LTABLE_SIZE+ATABLE_SIZE+KEY_TABLE_SIZE+INV_S_BOX_SIZE+INIT_VECTOR_SIZE+10)
    
    .global _ltable
    .global _atable
    .global _key_table
    .global _inv_s_box
    .global _init_vector
    
    .endif
       




