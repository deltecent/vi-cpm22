;============================================================
; FILE:    VI.INC
; PROJECT: VI -- vi-style CP/M editor on WordMaster's gap buffer
; CPU:     Intel 8080 (strict -- no Z80 extensions)
; ASSEMBLER: Microsoft M80
;------------------------------------------------------------
; Shared equates for the vi LAYER only (KEY.MAC, CMD.MAC).  BUF.MAC and
; PAGE.MAC are verbatim WordMaster transcriptions and define their own local
; constants; they do NOT include this file.  INCLUDE VI.INC first in KEY/CMD.
; There is one windowed gap buffer (BUF.MAC's flat pointer row), so there is no
; buffer descriptor or mode flag here.
;============================================================

;------------------------------------------------------------
; CP/M SYSTEM ADDRESSES
;------------------------------------------------------------
BDOS	EQU	0005H		; BDOS entry point
WBOOT	EQU	0000H		; warm boot / exit to CP/M
DFTFCB	EQU	005CH		; default FCB (command argument 1)
CMDTAIL EQU	0080H		; command tail / default DMA

;------------------------------------------------------------
; BDOS FUNCTION NUMBERS (only those the vi layer uses)
;------------------------------------------------------------
BF_CONIN  EQU	1		; console input (blocking)
BF_CONOUT EQU	2		; console output: E = char
BF_PRTSTR EQU	9		; print $-terminated string: DE = addr
BF_CONST  EQU	11		; console status
BF_CURDSK EQU	25		; current disk: A = 0 (A:) ..

;------------------------------------------------------------
; ASCII AND CP/M CONTROL CODES
;------------------------------------------------------------
NUL	EQU	00H		; null (string terminator)
BEL	EQU	07H		; bell
BS	EQU	08H		; backspace (Ctrl-H)
TAB	EQU	09H		; horizontal tab
LF	EQU	0AH		; line feed  -- the line TERMINATOR
CR	EQU	0DH		; carriage return -- decoration before LF
ESC	EQU	1BH		; escape
DEL	EQU	7FH		; rubout / delete
CPMEOF	EQU	1AH		; CP/M end-of-file marker (Ctrl-Z)

TABWID	EQU	8		; tab stop interval (display only)

;------------------------------------------------------------
; RENDER INTENT (RINTENT) -- what the last dispatched command did, so SCRN.MAC
; can choose the cheapest correct paint.  The command layer (CMD.MAC) sets it
; per key; SCRN.MAC reads it.  The default is the conservative R_FULL (full
; repaint = the proven Stage-3a behavior); pure cursor motions lower it to
; R_MOVE so the renderer repositions the cursor without redrawing; an in-line
; edit lowers it to R_LINE so only the cursor's line is redrawn.  A mistag can
; therefore only cost an unnecessary full repaint, never leave stale text.
;------------------------------------------------------------
; PLACE -- what a command asks of the next layout (SCRN.MAC), cleared by it.
PL_ASK	EQU	0		; the cursor only moved: is its line on the screen
				;   still, near it, or far off? (vim's rule)
PL_SET	EQU	1		; the command set the lines above it (WINROW)
PL_MID	EQU	2		; mid-screen, as the rows fall

R_FULL	EQU	0		; edit area may be stale -> full repaint (SCDRAW)
R_MOVE	EQU	1		; cursor moved only -> reposition (if viewport stable)
R_LINE	EQU	2		; the cursor's line changed only -> redraw it from the cursor's row
R_DLIN	EQU	3		; the cursor's line deleted -> DL its rows + redraw the bottom
R_ICH	EQU	4		; one printable char inserted, no TAB after it -> ICH
R_ILIN	EQU	5		; ILN lines opened at the cursor -> IL + their rows (ILABOV: the line above)
R_JOIN	EQU	6		; the line below joined onto the cursor's -> redraw it + DL the rows saved
R_DCH	EQU	7		; chars deleted at the cursor, none after it a TAB -> DCH

;------------------------------------------------------------
; EDITOR MODES (EDMODE)
;------------------------------------------------------------
EM_CMD	EQU	0		; command mode (default)
EM_INS	EQU	1		; insert mode
EM_REP	EQU	2		; replace mode ('R')
EM_EX	EQU	3		; ex command line (transient, inside VC_EX)

; THE MESSAGE THE BOTTOM ROW STILL OWES (MSGWHT).  A message is drawn after the
; frame, never during the command, because a full repaint blanks that row.
MW_NON	EQU	0		; nothing to say
MW_FIL	EQU	1		; the file just opened
MW_WRT	EQU	2		; ':w' wrote it
MW_CTG	EQU	3		; '^G' -- where am I
MW_BIG	EQU	4		; the yank register cannot hold that

EXMAX	EQU	40		; max chars on the ':' ex command line

;------------------------------------------------------------
; RESERVE BLOCK -- sizes of storage that RSV.MAC holds above the linked image
; on behalf of another module.  They live here, not in the module that uses
; the storage, so the module and RSV.MAC cannot disagree about a size.
;------------------------------------------------------------
DOTMAX	EQU	128		; keys one recorded change may hold (see '.')
KBRSIZ	EQU	32		; KEY.MAC's type-ahead ring (a power of two)
MKMAX	EQU	3		; marks 'a'-'c' -- three is enough (COMMANDS.md)
MKSIZ	EQU	4		; each: a 3-byte file position (the 4th is spare)

