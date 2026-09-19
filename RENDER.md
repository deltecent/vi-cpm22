# RENDER.md — the VT100 renderer (`SCRN.MAC`)

How VI puts the text on the screen: where each frame is placed, which paint the last key
gets, and what each paint emits. The code is `SCRN.MAC`; the render intents are set in
`CMD.MAC` and the frame is driven from `VI.MAC`'s main loop.

## Two halves, two sources

**Placement** — which line goes on which row — follows WordMaster's cursor-relative display
model (WM `MEASURE`, `WM.ASM:3762`). **Output** — what bytes reach the terminal — does not:
WordMaster assumed an install-time-fixed 80×24 terminal, let the glass auto-scroll off its
physical bottom row, and knew only clear-screen, cursor-address and erase-to-EOL, so it had
no insert/delete line or character to be cheap with. VI runs under terminal emulators of any
size and uses the VT100 scroll region, IL/DL, RI and ICH.

## Screen layout and runtime geometry

Rows `1..NEDIT` are the text window; the last row (`NROWS`) is vim's message line.
`NEDIT = NROWS - 1`.

**Geometry is probed at startup** (`SCINIT`):

1. Emit `ESC[999;999H` then `ESC[6n` (DSR) — park the cursor in the far corner, which the
   terminal clamps to bottom-right, and ask where it is.
2. Parse the reply `ESC[<rows>;<cols>R` (`RDNUMS`/`RDNUM`), each byte read with a bounded
   65536-poll spin (`RDB`).
3. Clamp rows to `[24..200]`, cols to `[80..132]`; store `NROWS`/`NCOLS`.
4. **Fallback:** a timeout or any malformed byte leaves the 24×80 defaults. The editor always
   has a valid geometry and can only enlarge past 80×24.

There is no geometry switch or config file; a terminal that answers wrongly is better patched
in the `.COM`.

**Message-row protection.** The steady-state scroll region is the whole screen. Every native
scroll (`SCFWD`, `SCBWD`, `SCDL`, `SC_IL`/`SC_ILQ`, `SC_JN`) first sets `ESC[1;<NEDIT>r`
(`SRGN`) and resets with `ESC[r` (`CRGRS`) after, so DL/IL/RI never move the message row. The
full repaint never scrolls: it addresses row 1 and steps with `CR,LF`, the last `LF` landing
on the message row.

**Long lines: horizontal pan, never wrap.** `HSCROL` is the first visible display column.
`HPAN` keeps the cursor's display column in `[HSCROL, HSCROL+NCOLS)`, panning only as far as
it must. `PROW` expands tabs (to 8-column stops) and clips every row to that window, so
autowrap never fires. A `CR` anywhere in a line is dropped from the display. In command mode
a cursor on a tab sits on the tab's last column (`TABCUR`), as vi's does; in insert mode on
its first.

## Placement (`LAYOUT`)

`LAYOUT` emits nothing. It works from `WINROW` (the cursor line's row last frame) and
`LNDLT` (the signed number of lines the cursor crossed since — BUF `GOTO`/`DELPRV` and the
`CMD.MAC` line moves keep it):

- **The row.** `CURRW` (`CMD.MAC`) is `WINROW + LNDLT` clamped to the edit rows, so a cursor
  that runs off an edge scrolls the text. `LYFAR` applies vim's rule (not WordMaster's) for
  one that went far: more than `NEDIT/2+1` lines below the bottom row or `NEDIT/2-2` above
  the top, it goes on the middle row instead.
- **The top line.** `LINPSB` (WM `LINPOSB`) finds the start of the line that many lines above
  the cursor's, paging back if it is on disk. `WRLIM` is then raised past it (WM
  `WM.ASM:3784-3788`) so a spill never evicts text that is on the screen.
- **Below.** `RGET0`/`RDGET` (WM `RGET`) read forward from the cursor to the bottom row,
  paging in on demand (WM `NEEDIN`).
- **Outputs:** `WINROW`, `SCRLN` (lines the text moved up this frame: `LNDLT` minus the row
  change), `CURDCL`, `HSCROL`, and the window facts the screen motions use — `SCBOT` (last
  row holding text), `SCEOF`/`SCBOF` (the file's end / start is on the screen).
- **`WFILL`.** When `'~'` rows show but text above could fill them (`G`, `^D`, a far jump),
  the cursor's line is moved down by the shortfall and the layout runs once more.

`LINPSB` runs WM's `SETCNT`, so `LAYOUT` saves and restores `CMDCNT`, `AUXCNT` and `DIRFLG`
around itself.

So a frame costs one screenful of text however deep the cursor is. The paints read it
straight from the gap buffer (`RDTOP`/`RDBOL`/`RDCH`): before the gap by pointer, taken from
`GAPBEG` when the read starts; after it by `RGET`. After `LAYOUT` all of it is resident, so a
paint never pages.

## Escape-sequence vocabulary

Everything `SCRN.MAC` emits (`STRINGS`, plus `GOTOXY`):

| Op | Bytes | Use |
|----|-------|-----|
| CUP | `ESC [ r ; c H` | `GOTOXY`; 1-based |
| EL | `ESC [ K` | clear a row before drawing it (`CEKL`) |
| DL | `ESC [ M` | at the region top: scroll up one; at a row: delete it |
| IL | `ESC [ n L` | open `ILN` rows at the cursor's row |
| RI | `ESC M` | at the region top: scroll down one |
| ICH | `ESC [ 1 @` | open one cell for a typed char |
| DECSTBM | `ESC [ 1 ; NEDIT r` / `ESC [ r` | transient message-row guard |
| DECTCEM | `ESC [ ? 25 l` / `h` | cursor hidden for every multi-step paint |
| DSR probe | `ESC [ 999 ; 999 H` `ESC [ 6 n` | geometry, once |
| Row step | `CR , LF` | next row in a repaint |
| Rubout | `BS , ' ' , BS` | the `:` / `/` line (`EXRUB`, WM `BSCOL`) |

No `ESC[2J` — not even at startup: the first frame paints over whatever is there. No DCH, no
SGR: this is a non-highlighting editor. Control characters other than tab and `CR` are sent
as they are and counted as one column.

## Render intents

There is no shadow screen and no diff. Each key's handler says what it changed by setting
`RINTENT` (`CMD.MAC`, equates in `VI.INC`); the main loop resets it to `R_FULL` before every
dispatch, so a handler that says nothing gets a full repaint.

| Intent | Set by (`CMD.MAC`) | Meaning |
|--------|--------------------|---------|
| `R_FULL` | default; `SETFUL` | the edit area may be stale |
| `R_MOVE` | `SETMOV`, `GP_ONS`, `EXERR`, `^G` | the cursor moved; nothing was edited |
| `R_LINE` | `SETLIN` | only the cursor's row changed |
| `R_ICH` | insert of a printable char (+ `ICHAPP`) | one char went in at the cursor |
| `R_DLIN` | single `dd` | the cursor's line was deleted |
| `R_ILIN` | `SETILN` (+ `ILN` = lines, `ILABOV`) | lines opened at the cursor's row |
| `R_JOIN` | `SETJON` | the line below joined onto the cursor's |

**Main loop** (`VI.MAC`): `GETKEY` → `SCPRE` (snapshot `WINROW`/`HSCROL` into
`OLDWR`/`OLDHS`) → `RINTENT = R_FULL` → `CMDDIS` → `SCDRAW` → `MODEMS` → `MSGPST`.

**`SCDRAW`** runs `LAYOUT`, then picks the paint:

1. `FORCEF` set (an earlier repaint was aborted) or `HSCROL` changed → full repaint.
2. `R_MOVE`: `SCRLN = 0` → cursor only (`SCURS`); `SCRLN` in `1..NEDIT-1` → region scroll up
   (`SCFWD`) or down (`SCBWD`); otherwise → full.
3. `R_LINE`, `R_ICH`, `R_DLIN`, `R_JOIN` need the text to have stayed put — `SCRLN = 0` and
   the same `WINROW` — else full.
4. `R_ILIN` has its own test (`SC_ILQ`): `SCRLN = 0` → open in place; `SCRLN = 1` with
   `ILN = 1` (a line opened on the bottom row) → scroll up one first; otherwise full.
5. Anything else → full.

## The paints

- **Full repaint (`SCFULL`).** Hide cursor, `CUP` row 1, then for each edit row `ESC[K`, the
  row, `CR,LF`; rows past the text show `~`. Then `ESC[K` on the message row (which blanks
  any message, so `OEDMOD` is set unknown and `MODEMS` draws the mode again), `CUP` the
  cursor and show it.
- **Cursor only (`SCURS`).** `CUP` + show. Nothing else.
- **Region scroll up (`SCFWD`).** Region `1..NEDIT`; N times: `ESC[M` at row 1, then draw
  the newly exposed row into row `NEDIT`. The overlap the terminal shifted is never re-sent.
- **Region scroll down (`SCBWD`).** Region `1..NEDIT`; N × `ESC M` at row 1, then draw the N
  opened rows from the top.
- **One row (`SC_LNBD`, `R_LINE`).** `CUP` the row, `ESC[K`, redraw it from its first byte.
- **Insert char (`SC_ICH`, `R_ICH`).** `CUP` the new char's cell, `ESC[1@`, the char. The
  cursor is left where the terminal put it. Falls back to the one-row redraw if that cell is
  not on the screen. **`ICHAPP`** (the char went at the row's end — `CMD.MAC`'s `ATCEND`)
  drops the `ESC[1@`: ICH exists to shift the rest of the row out of the way, and with
  nothing after the cursor there is nothing to shift. That path drops the hide/show pair
  too, there being nothing to see happen between the address and one byte — 7 bytes on the
  wire against 20, on the commonest keystroke there is.
- **Delete line (`SCDL`, `R_DLIN`).** `ESC[M` at the cursor's row, then draw row `NEDIT`.
- **Open lines (`SC_IL`, `R_ILIN`).** `ESC[<ILN>L` at the cursor's row, then redraw the
  `ILN` opened rows from there, clipped to the bottom edit row. Everything above the
  cursor's row stands: `o`, `O` and a put leave the line above exactly as it was.
  **`ILABOV`** says that line lost text to the opened rows — a `<CR>` typed with text after
  the cursor, `r<CR>` — and only then is it redrawn as well. `SETILN` clears the flag, so a
  handler that does not set it gets the cheap form. On the bottom row (`SC_ILQ`) it is a
  `ESC[M` at the top instead, then the same rows.
- **Join (`SC_JN`, `R_JOIN`).** Redraw the cursor's row, `ESC[M` the row under it, draw row
  `NEDIT`. On the bottom edit row only the cursor's row is redrawn — the joined line was never
  on the screen.

Every multi-step paint is bracketed by `ESC[?25l` … `CUP` + `ESC[?25h`.

## Per-command paint

| Command | Intent | Paint |
|---------|--------|-------|
| Motion not leaving the screen (`h j k l w b e W B 0 ^ $ H M L`, …) | `R_MOVE` | cursor only |
| Motion scrolling 1..NEDIT-1 rows (`j`/`k` off an edge, `^F ^B ^D ^U`) | `R_MOVE` | region scroll + exposed rows |
| `G` `gg` `/` `?` `n` `N` landing on a line already on screen | `R_MOVE` (`GP_ONS`) | cursor only |
| … landing off the screen | `R_FULL` (`GP_SET`) | full — the window may have paged |
| Count digits, `m`, a pending `d`/`c`/`y`, a key that is no command, `^G`, an ex error | `R_MOVE` | cursor only |
| `x` `~` `r{c}`, `R` overwrite, insert BS within a line | `R_LINE` | one row |
| `i` `a` `A` `I` `R`, and the `ESC` leaving insert | `R_MOVE` (`SETINM`, `VI_ACT`) | cursor only — they change no text |
| Insert printable, no tab after the cursor | `R_ICH` | ICH + char |
| … typed at the row's end | `R_ICH` + `ICHAPP` | the char, nothing else |
| Insert control char or with a tab after the cursor | `R_LINE` | one row |
| `dw` `cw` `D` (`d`/`c` span with no line break) | `R_LINE` | one row |
| `d`/`c` span with a line break, insert BS joining lines | `R_FULL` | full |
| `dd` (single, not the last line) | `R_DLIN` | DL + bottom row |
| `Ndd`, `dd` of the last line | `R_FULL` | full |
| `o` `O`, a `<CR>` typed at the line's end | `R_ILIN` (1) | IL + the opened row |
| a `<CR>` typed with text after it, `r<CR>` | `R_ILIN` (1) + `ILABOV` | IL + that row and the one above |
| `p` `P` (linewise; the only kind there is) | `R_ILIN` (lines put, if < 256) | IL + the opened rows |
| `J` | `R_JOIN` | row + DL + bottom row |
| `.` `u` `:s` `^L` | `R_FULL` | full |
| `:q` `:q!` `:wq` `:x` `ZZ` | — | none (below) |

## The message row

The last row is vim's message line, not a status row. It holds:

- the mode, from `MODEMS`: `-- INSERT --`, `-- REPLACE --`, or blank in command mode — drawn
  only when the mode differs from what the row last showed (`OEDMOD`), so a message stays
  until the mode really changes or a full repaint blanks it;
- the `:` / `/` line (`EXPRM`, `EXRUB`) and ex messages (`EXMSG`);
- whatever the key asked to say (`MSGPST`, `CMD.MAC`) — the load line, `^G`.

Anything that writes it after a frame ends in `SCURS`, putting the cursor back on the text.

## Type-ahead ring and repaint abort

**Console.** Every console primitive goes direct to the BIOS, as WM's `BIOSC`
(`WM.ASM:6187`) does: `LHLD 1` (the warm-boot vector), add 3/6/9 for CONST/CONIN/CONOUT,
`PCHL`. Recomputed per call. `BCONST`/`BCONIN`/`BCONOU` in `SCRN.MAC`.

**Ring.** `KEY.MAC` keeps WordMaster's type-ahead ring (WM `GETKEY`/`GETBUF`,
`WM.ASM:6094`/`6052`) over `BCONIN`: `KBPUMP` drains whatever the BIOS has waiting into
`KBRING` without blocking; `KBGETB` takes the oldest byte, blocking on `BCONIN` only when the
ring is empty. `KBRDY` pumps, then reports whether a byte is waiting.

**Abort** (WM `RPOLL`, `WM.ASM:2637`). `SCFULL` calls `KBRDY` before every row; with a key
waiting it stops (`SCABRT`), leaving the cursor hidden, and latches `FORCEF` so the next
frame repaints in full even if that key is a pure motion — an abort is a deferral, never a
dropped update. The other paints are short and bounded and run to completion. At 9600 baud
a full repaint is about 1.6 s, so this is what keeps a burst of `j`s from painting screens
nobody sees.

## Leaving

A key that sets `QUITF` skips `SCDRAW`: the screen is what the editor leaves behind.
`SCDONE` resets the scroll region, shows the cursor, and clears the bottom row with the
cursor at its left end. No `CR,LF` — the CCP prints its own before `A>`, which scrolls the
text up one row and puts the prompt on the bottom row.
