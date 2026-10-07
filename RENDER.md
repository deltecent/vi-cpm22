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
size and uses the VT100 scroll region, IL/DL and ICH/DCH.

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

**Message-row protection.** The steady-state scroll region is the whole screen. A paint
that moves rows (`SHFT`) first sets `ESC[1;<NEDIT>r` (`SRGN`) and resets with `ESC[r`
(`CRGRS`) after, so IL/DL never move the message row. The full repaint never scrolls: it
addresses row 1 and steps with `CR,LF`, the last `LF` landing on the message row.

**Long lines wrap, as vi's do.** A line wider than the screen goes on down the rows under
it. The paint steps to the next row itself (`PWRAP`: `CR,LF`, `ESC[K`), so the terminal's
own autowrap is never relied on, and a row is left only when there is one more cell to put:
a line exactly as wide as the screen is one row. `PROW` expands tabs to 8-column stops; a
TAB that crosses the right edge carries on in the next row. A `CR` anywhere in a line is
dropped from the display. In command mode a cursor on a tab sits on the tab's last column
(`TABCUR`), as vi's does; in insert mode on its first.

Three things follow from wrapping, each as vim does it:

- **The top row is always the first row of a line** (vim without `smoothscroll`).
- **A line the bottom has no room for is not shown.** The rows it would have started on
  hold `@` (`FILCH`); past the end of the file they hold `~`.
- **A line taller than the screen** is the one exception to the first rule: when the cursor
  is in it, it is the top line, shown from its row `SKIPR` (vim's `w_skipcol`), with `<<<`
  over the first three cells. `SKIPR` moves only as far as keeps the cursor's row on the
  screen, and is given up as soon as the cursor is on another line.

## Placement (`LAYOUT`)

`LAYOUT` emits nothing. It works from `WINROW` (the number of **lines** on the screen above
the cursor's, last frame), `LNDLT` (the signed number of lines the cursor crossed since —
BUF `GOTO`/`DELPRV` and the `CMD.MAC` line moves keep it) and `PLACE`, one byte in which the
command says what it wants: the cursor only moved (`PL_ASK`), the command set `WINROW`
itself (`PL_SET`), or mid-screen (`PL_MID`).

**The row table.** A line's height is not known without reading it, so the lines about the
cursor are measured once a frame (`HTBLD`) into `HTAB[0..HTN)`, a byte a line saying how
many rows it takes; `HTCUR` is the cursor line's entry. The table holds as many lines above
the cursor's as the placement could want and a screenful of rows from it on. Everything
after that is arithmetic on the table — nothing reads the text a second time to place it.
The table is 255 bytes of reserve (`RSV.MAC`). `H M L` read it as it stands; `^F ^B ^D ^U`
build a wider one with the same routine.

- **The lines wanted above.** `CURRW` (`CMD.MAC`) is `WINROW + LNDLT` clamped to the edit
  rows, so a cursor that runs off an edge scrolls the text. With `PL_ASK`, `LYFAR` applies
  vim's rule (`update_topline`, not WordMaster's) for a line that went off the screen: more
  than `NEDIT/2-2` lines above the top it goes mid-screen; below, more than `NEDIT` lines
  under the last one shown is mid-screen too, and nearer than that is a matter of rows,
  which `LYMID` settles as vim's `scroll_cursor_bot` does.
- **Mid-screen (`LYMID`).** vim's `scroll_cursor_halfway`, counting rows: starting with the
  cursor's line, take a line below while the rows below are no more than those above, else
  a line above, until one will not fit.
- **The top line.** Of the lines wanted above, as many are kept as leave the cursor's whole
  line room. `LINPSB` (WM `LINPOSB`) finds the start of the line that many above the
  cursor's, paging back if it is on disk. `WRLIM` is then raised past it (WM
  `WM.ASM:3784-3788`) so a spill never evicts text that is on the screen.
- **Below.** The table is walked down from the cursor's line, taking each line that fits
  whole. The first that does not ends the text there with `@` rows.
- **Outputs:** `WINROW`; `LYABV` (rows the lines above the cursor's take); `CURDCL` (the
  cursor's display column in its line) and from it `SROW`/`SCOL` (`CURSC`: `CURDCL / NCOLS`
  rows into the line, column `CURDCL mod NCOLS`); `TXEND` and `FILCH` (the first row with no
  text, and what such rows show); `SCRLN` (lines the text moved up this frame); `SKIPR`,
  `TALLF`; and the window facts the screen motions use — `SCBOT` (the last line shown,
  counted as `WINROW` is), `SCEOF`/`SCBOF` (the file's end / start is on the screen).

**A move measures nothing (`LYQK`).** All of the above reads every line on the screen,
which on a full screen is most of a quarter of a second. A key that only moved the cursor
does not need it: the text on every row is what it was, so the row table is too. `LAYOUT`
therefore asks `LYQK` first, and when

- the table is the screen's own (`LYOK`: set at the end of a full layout, cleared when
  anything else measures into it) and the pager has not moved the window since (`PGTOPM`),
- the key's intent is `R_MOVE`, in command mode, with no `PLACE` request,
- the cursor's line is one the screen shows whole (`0 <= WINROW + LNDLT <= SCBOT`),
- and no line taller than the screen is involved (`SKIPR`, `TALLF`, `LYXE` all clear),

the layout is arithmetic: `WINROW` and `HTCUR` move by `LNDLT`, `LYABV` is a sum down the
table, the top line is as far into the text in memory as it was (`LYTOP`), and the one
thing read is the cursor's own line from its start to the cursor, for `CBOL` and `CURDCL`.
`SCRLN` is 0, so `SCDRAW` sends the cursor and nothing else. Any other key takes the full
layout, which makes the table the screen's again.

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
| IL | `ESC [ n L` | open n rows at a row; everything below moves down (`SHFT`) |
| DL | `ESC [ n M` | delete n rows at a row; everything below moves up (`SHFT`) |
| ICH | `ESC [ 1 @` | open one cell for a typed char |
| DCH | `ESC [ n P` | delete n cells at the cursor (`x`) |
| DECSTBM | `ESC [ 1 ; NEDIT r` / `ESC [ r` | transient message-row guard |
| DECTCEM | `ESC [ ? 25 l` / `h` | cursor hidden for every multi-step paint |
| DSR probe | `ESC [ 999 ; 999 H` `ESC [ 6 n` | geometry, once |
| Row step | `CR , LF` | next row of a paint, and of a wrapped line |
| Rubout | `BS , ' ' , BS` | the `:` / `/` line (`EXRUB`, WM `BSCOL`) |

No `ESC[2J` — not even at startup: the first frame paints over whatever is there. No RI
(a scroll down is an IL at row 1), no SGR: this is a non-highlighting editor. Control characters other than tab and `CR` are sent
as they are and counted as one column.

## Render intents

There is no shadow screen and no diff. Each key's handler says what it changed by setting
`RINTENT` (`CMD.MAC`, equates in `VI.INC`); the main loop resets it to `R_FULL` before every
dispatch, so a handler that says nothing gets a full repaint.

| Intent | Set by (`CMD.MAC`) | Meaning |
|--------|--------------------|---------|
| `R_FULL` | default; `SETFUL` | the edit area may be stale |
| `R_MOVE` | `SETMOV`, `GP_ONS`, `EXERR`, `^G` | the cursor moved; nothing was edited |
| `R_LINE` | `SETLIN` | only the cursor's line changed |
| `R_ICH` | insert of a printable char (+ `ICHAPP`) | one char went in at the cursor |
| `R_DCH` | `x` (+ `DCHN` = cells) | chars went at the cursor; no TAB or control char after it |
| `R_DLIN` | single `dd` | the cursor's line was deleted |
| `R_ILIN` | `SETILN` (+ `ILN` = lines, `ILABOV`) | lines opened at the cursor |
| `R_JOIN` | `SETJON` | the line below joined onto the cursor's |

**Main loop** (`VI.MAC`): `GETKEY` → `SCPRE` → `RINTENT = R_FULL` → `CMDDIS` → `SCDRAW` →
`MODEMS` → `MSGPST`. `SCPRE` keeps what is on the screen: the frame's facts (`WINROW`,
`SKIPR`, `SROW`/`SCOL`, `TXEND`/`FILCH`, `SCBOT`, `LYABV`, and the rows the cursor's line
and the one under it take) are block-copied to their `OLD` twins, so `SCDRAW` can tell what
the key changed.

## The paint (`SCDRAW`)

There is one cheap paint, and it counts **rows**. A frame is two changes, each of the form
"this many rows were here, that many are":

- **at the top row** — the text scrolled, so the screen gave up `OPN` rows there or gained
  `OPM`;
- **at the cursor** — an edit whose first row is `EDR`, which took `EDA` rows before and
  takes `EDB` now, and is to be drawn from row `EDP`.

The terminal moves the rows that stand, only the rows that are new are sent, and whatever
the move left wrong at the bottom is drawn last. A wrapped line is not a special case: it is
a line whose row count is not 1.

**Turning the intent into the two changes.** After `LAYOUT`:

1. `FORCEF` set (an earlier repaint was aborted), `SKIPR` changed, or `R_FULL` → full.
2. **The cursor is on the same line** (`R_MOVE`, `R_LINE`, `R_ICH`, `R_DCH`, `R_DLIN`,
   `R_JOIN`). The edit is the cursor's line: `EDR` = its first row, `EDA`/`EDB` = the rows
   it had and has (`R_DLIN`: has none; `R_JOIN`: had its own and the next line's; `R_MOVE`:
   nothing to draw). It is drawn from the row the cursor was on or is on, whichever is
   higher — the rows of the line above that cannot have changed. If that line now starts
   higher on the screen than it did, the difference is `OPN`; lower, and it is a full
   repaint.
3. **`R_ILIN`.** Opened where the cursor's line was (`O`, `P`): no rows before, the opened
   lines' rows now. Opened under it (`o`, a typed `<CR>`, `p`): the edit starts with the
   line above, which is redrawn only from the row the cursor was on, and only if `ILABOV`
   says text came off it.
4. **`R_MOVE` to another line.** `SCRLN = 0` → nothing moved. Text moved up: `OPN` is the
   rows of the lines that left the top. Text moved down: `OPM` is the rows of the lines
   that came on. A screenful or more → full.
5. Anything else, or an edit that would run off the bottom → full.

**Then**, with the two changes in hand:

- **Nothing moves, nothing to draw** → the cursor alone (`SCURS`: `CUP` + show).
- **Nothing moves, and only the line's last row is dirty**, the cursor on it before and
  after: `R_ICH` → `SC_ICH`, `R_DCH` → `SC_DCH` (below).
- **Otherwise** hide the cursor; if rows move, set the region and `SHFT` twice (the top
  change at row 1, the edit at `EDR`) — each an `ESC[nL` or `ESC[nM` at the row under the
  rows that stay; then `PRNG` the rows opened at the top, `PRNG` the edit's rows from `EDP`,
  and fix the bottom: the rows between where the old good rows ended up and where good rows
  should end, and any rows a move up left bare. `@` rows are never "good" (`TEV`), so a line
  that was cut off is drawn when it gets room. A screen with `<<<` on it is repainted in
  full instead.

**`PRNG`** (`B` = first row, `C` = the row to stop before) is the only thing that puts text
on the screen. It finds row `B`'s line in the row table, starts the reader at that line and
skips the rows of it above `B`, then for each row: `ESC[K`, the text, `CR,LF`. An empty
range sends nothing.

- **Full repaint (`SCFULL`).** Hide cursor, `PRNG` rows `0..NEDIT`, then `ESC[K` on the
  message row (which blanks any message, so `OEDMOD` is set unknown and `MODEMS` draws the
  mode again), `<<<` if `SKIPR` is set, `CUP` the cursor and show it.
- **Insert char (`SC_ICH`).** `ESC[1@`, the char. No cursor address: the terminal's cursor
  is already on the cell, and is left where insert mode wants it. **`ICHAPP`** (the char
  went at the line's end — `CMD.MAC`'s `ATCEND`) drops the `ESC[1@` too, there being nothing
  after the cursor to shift: one byte on the wire, on the commonest keystroke there is.
- **Delete char (`SC_DCH`).** `ESC[<DCHN>P`: the terminal draws the rest of the row up.
  The cursor is addressed only if the delete took the line's last char from under it.

The two cell operations work on one row, so they are used only on a line's last row. An
insert or `x` higher up a wrapped line redraws from the cursor's row to the line's end;
there is no row-by-row ripple, and no special path for long lines (the target is lines of
80 columns or less).

## Per-command paint

| Command | Intent | Paint |
|---------|--------|-------|
| Motion not leaving the screen (`h j k l w b e W B 0 ^ $ H M L`, …) | `R_MOVE` | cursor only |
| Motion scrolling less than a screenful (`j`/`k` off an edge, `^F ^B ^D ^U`) | `R_MOVE` | IL/DL at row 1 + the rows that came on |
| `G` `gg` `/` `?` `n` `N` landing on a line already on screen | `R_MOVE` (`GP_ONS`) | cursor only |
| … landing off the screen | `R_FULL` (`GP_SET`) | full — the window may have paged |
| Count digits, `m`, a pending `d`/`c`/`y`, a key that is no command, `^G`, an ex error | `R_MOVE` | cursor only |
| `x`, no TAB or control char after the cursor, on the line's last row | `R_DCH` | DCH |
| `x` otherwise, `~` `r{c}`, `R` overwrite, insert BS within a line | `R_LINE` | the line, from the cursor's row down |
| `i` `a` `A` `I` `R`, and the `ESC` leaving insert | `R_MOVE` (`SETINM`, `VI_ACT`) | cursor only — they change no text |
| Insert printable, no tab after the cursor, on the line's last row | `R_ICH` | ICH + char |
| … typed at the line's end | `R_ICH` + `ICHAPP` | the char, nothing else |
| … that takes the line onto a new row | `R_ICH` | IL under the line + the new row |
| Insert control char or with a tab after the cursor | `R_LINE` | the line, from the cursor's row down |
| `dw` `cw` `D` (`d`/`c` span with no line break) | `R_LINE` | the line, from the cursor's row down; DL if it lost rows |
| `d`/`c` span with a line break, insert BS joining lines | `R_FULL` | full |
| `dd` (single, not the last line) | `R_DLIN` | DL of the line's rows + the rows that came on at the bottom |
| `Ndd`, `dd` of the last line | `R_FULL` | full |
| `o` `O`, a `<CR>` typed at the line's end | `R_ILIN` (1) | IL + the opened row |
| a `<CR>` typed with text after it, `r<CR>` | `R_ILIN` (1) + `ILABOV` | IL + the opened rows and the line above, from the row the cursor was on |
| `yy` `Y` `y{motion}` copied where the lines lie | `R_MOVE` (`YNDONE`) | cursor only — the text is not touched |
| … taken out and put back (no room, or a count past the window) | `R_FULL` | full — the pager may have moved the window |
| `p` `P` (linewise; the only kind there is) | `R_ILIN` (lines put, if < 256) | IL + the opened rows |
| `J` | `R_JOIN` | the line from the cursor's row + DL of the rows saved + the bottom |
| Any of the above typed on the bottom row | same | the same, with a DL at row 1 first |
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

**Abort** (WM `RPOLL`, `WM.ASM:2637`). During a full repaint `PRNG` calls `KBRDY` before
every row; with a key waiting it abandons the frame, leaving the cursor hidden and `FORCEF`
set, so the next frame repaints in full even if that key is a pure motion — an abort is a
deferral, never a dropped update. The cheap paints run to completion. At 9600 baud a full
repaint is about 1.6 s, so this is what keeps a burst of `j`s from painting screens nobody
sees.

## Leaving

A key that sets `QUITF` skips `SCDRAW`: the screen is what the editor leaves behind.
`SCDONE` resets the scroll region, shows the cursor, and clears the bottom row with the
cursor at its left end. No `CR,LF` — the CCP prints its own before `A>`, which scrolls the
text up one row and puts the prompt on the bottom row.
