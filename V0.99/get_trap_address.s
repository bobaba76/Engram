    .section *,bss, near    

    .text    
    .global _GetTrapAddress 
    
_GetTrapAddress:
    sub w15,#26,w1           ; 26 bytes pushed since last trap! (28 if stack frames used)
    mov [w1++], w0
    mov [w1], w1
    mov #0x7F, w2
    and w2, w1, w1
    return
    
    .end
    