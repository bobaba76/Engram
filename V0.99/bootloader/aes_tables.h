#ifndef AES_GLOBAL_H
#define AES_GLOBAL_H

/* Global tables defined in assembler include file included with bootloader so that space used */
/* is not added to application variable space - everything on the stack & deleted when done.   */

/* Log table using 0xe5 (229) as the generator */
extern unsigned char ltable[256];

/* Anti-log table: */
extern unsigned char atable[256];

/* Key Table */
extern unsigned char key_table[176];

/* inverse s-box */
extern unsigned char inv_s_box[256];

/* Initialisation Vector for CBC */
extern unsigned char init_vector[16];

#endif
