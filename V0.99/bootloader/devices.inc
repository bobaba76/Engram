;------------------------------------------------------------------------------
;
; Title:			ds30 loader for dsPIC33
;
; File description:	Device specific constants
;
; Copyright: 		Copyright © 09-10, Mikael Gustafsson
;
; Webpage: 			http://mrmackey.no-ip.org/elektronik/ds30loader/
;
; History:			1.1.0 -
;					1.0.4 -
;					1.0.3 -
;					1.0.2 -
;					1.0.1 -
;					1.0.0 -
;					0.9.4 -
;					0.9.3 -
;					0.9.2 -
;					0.9.1 Added pps equ
;					0.9.0 First version of this file
;                                                                             
;------------------------------------------------------------------------------

;-----------------------------------------------------------------------------
;    This file is part of ds30 Loader.
;
;    ds30 Loader is free software: you can redistribute it and/or modify
;    it under the terms of the GNU General Public License as published by
;    the Free Software Foundation.
;
;    ds30 Loader is distributed in the hope that it will be useful,
;    but WITHOUT ANY WARRANTY; without even the implied warranty of
;    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
;    GNU General Public License for more details.
;
;    You should have received a copy of the GNU General Public License
;    along with ds30 Loader. If not, see <http:;www.gnu.org/licenses/>.
;------------------------------------------------------------------------------ 


.ifdef	__33FJ06GS101
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x1000
	.equ		DEVICEID,		100
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ06GS102
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x1000
	.equ		DEVICEID,		101
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ06GS202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x1000
	.equ		DEVICEID,		102
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ128GP202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		170
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ128GP204
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		171
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ128GP206
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		172
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128GP206A
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		173
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128GP306
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		174
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128GP306A
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		175
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128GP310
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		176
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128GP706
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		177
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128GP708
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		178
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128GP710
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		179
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128GP802
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		180
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ128GP804
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		181
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ128MC202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		182
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ128MC204
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		183
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ128MC506
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		184
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128MC510
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		185
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128MC706
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		186
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128MC708
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		187
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128MC710
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		188
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ128MC802
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		189
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ128MC804
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x15800
	.equ		DEVICEID,		190
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ12GP201
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2000
	.equ		DEVICEID,		110
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ12GP202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2000
	.equ		DEVICEID,		111
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ12MC201
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2000
	.equ		DEVICEID,		112
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ12MC202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2000
	.equ		DEVICEID,		113
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ256GP506
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2AC00
	.equ		DEVICEID,		195
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ256GP510
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2AC00
	.equ		DEVICEID,		196
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ256GP710
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2AC00
	.equ		DEVICEID,		197
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ256MC510
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2AC00
	.equ		DEVICEID,		198
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ256MC710
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2AC00
	.equ		DEVICEID,		199
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ16GP304
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2C00
	.equ		DEVICEID,		120
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ16GS402
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2C00
	.equ		DEVICEID,		121
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ16GS404
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2C00
	.equ		DEVICEID,		122
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ16GS502
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2C00
	.equ		DEVICEID,		123
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ16GS504
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2C00
	.equ		DEVICEID,		124
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ16MC304
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x2C00
	.equ		DEVICEID,		125
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ32GP202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		130
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ32GP204
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		131
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ32GP302
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		132
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ32GP304
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		133
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ32GS406
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		161
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ32GS606
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		162
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ32GS608
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		163
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ32GS610
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		164
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ32MC202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		134
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ32MC204
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		135
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ32MC302
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		136
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ32MC304
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0x5800
	.equ		DEVICEID,		137
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ64GP202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		140
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ64GP204
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		141
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ64GP206
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		142
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GP306
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		143
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GP310
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		144
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GP706
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		145
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GP706A
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		146
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GP708
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		147
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GP710
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		148
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GP802
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		149
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ64GP804
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		150
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ64GS406
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		165
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GS606
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		166
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GS608
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		167
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64GS610
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		168
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64MC202
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		151
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ64MC204
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		152
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ64MC506
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		153
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64MC508
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		154
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64MC510
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		155
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64MC510A
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		156
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64MC706
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		157
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64MC710
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		158
	.equ		HAS_UART2,		1
.endif
.ifdef	__33FJ64MC802
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		159
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif
.ifdef	__33FJ64MC804
	.equ		VALID_DEV,		1
	.equ		FLASHSIZE,		0xAC00
	.equ		DEVICEID,		160
	.equ		HAS_UART2,		1
	.equ		HAS_PPS, 		1
.endif


;------------------------------------------------------------------------------
; 
;------------------------------------------------------------------------------ 
.ifndef VALID_DEV
	.error "Unknown device specified"
.endif
