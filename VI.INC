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
; edit lowers it to R_LINE so only the current row is redrawn.  A mistag can
; therefore only cost an unnecessary full repaint, never leave stale text.
;------------------------------------------------------------
R_FULL	EQU	0		; edit area may be stale -> full repaint (SCDRAW)
R_MOVE	EQU	1		; cursor moved only -> reposition (if viewport stable)
R_LINE	EQU	2		; current line changed only -> redraw that one row
R_DLIN	EQU	3		; one line deleted at the cursor row -> DL + redraw bottom
R_ICH	EQU	4		; one printable char inserted mid-line -> ICH (no tail redraw)
R_ILIN	EQU	5		; one line opened at the cursor row -> IL + redraw that row and the one above
R_JOIN	EQU	6		; the line below joined onto the cursor's -> redraw that row + DL the one under it

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

EXMAX	EQU	40		; max chars on the ':' ex command line

;------------------------------------------------------------
; RESERVE BLOCK -- sizes of storage that RSV.MAC holds above the linked image
; on behalf of another module.  They live here, not in the module that uses
; the storage, so the module and RSV.MAC cannot disagree about a size.
;------------------------------------------------------------
DOTMAX	EQU	128		; keys one recorded change may hold (see '.')
KBRSIZ	EQU	32		; KEY.MAC's type-ahead ring (a power of two)
MKMAX	EQU	3		; marks 'a'-'c' -- three is enough (COMMANDS.md)
MKSIZ	EQU	4		; each: its offset, then PGTOPM when it was set

;------------------------------------------------------------
; KEY DECODER -- GETKEY return types (B) and action codes (C when B=KT_ACT).
; See KEY.MAC.
;------------------------------------------------------------
KT_NONE EQU	0		; no key (unrecognised ESC sequence, discarded)
KT_ACT	EQU	1		; C = ACT_xxx action code
KT_CHAR EQU	2		; C = ASCII character (printable or control)

ACT_CURUP EQU	1		; cursor up    (ESC[A / ESC OA)
ACT_CURDN EQU	2		; cursor down  (ESC[B / ESC OB)
ACT_CURRT EQU	3		; cursor right (ESC[C / ESC OC)
ACT_CURLT EQU	4		; cursor left  (ESC[D / ESC OD)
ACT_LINST EQU	5		; Home / line start (ESC[H / ESC[1~)
ACT_LINEN EQU	6		; End  / line end   (ESC[F / ESC[4~)
ACT_PGUP  EQU	7		; page up   (ESC[5~)
ACT_PGDN  EQU	8		; page down (ESC[6~)
ACT_INS	  EQU	9		; Insert key (ESC[2~)
ACT_DEL	  EQU	10		; Delete key (ESC[3~)
ACT_ESC	  EQU	11		; lone ESC (after timeout)
ACT_MAX	  EQU	11		; highest defined action code

ESCTMO	EQU	500		; polls before a lone ESC is confirmed
