# VI — commands, and where they deviate from vim

This is the state of the editor: what is built, what it does, and every place it
does not do what vim 9.1 does. The editor pages — the screen follows
WordMaster's cursor-relative model (`WINROW`, WM `LINPOSB`/`RGET`/`NEEDIN`) and
moves use WM's own paged line move — so a command is not "built" until it works
on files far larger than the arena.

## What ✅ means here

Proven by an **editor-level acceptance test** — the real `VI.COM` in the
simulator, run with `run_tests.py` (or `fastcheck.py` for the groups in
parallel) — that stages 0 / 1-line / ~2 K / ~40 K / 100 K files and, for each:
`:w` byte-exact round-trip; motions reaching the *true* first/last line; paging
the whole file and back; edits correct anywhere, including past the arena; the
cursor, window and screen row where vim puts them. Tests are written **first**
and start **red**, and they include lines past the right screen edge (the vim
references are recorded with `nowrap`). A green unit or component test proves
nothing on its own.

The vim comparisons are reproducible, not folklore: every "vs vim" table in
`accept_vi.py` was recorded from real vim 9.1 on a 24x80 pty, and
`python3 vimref.py` replays all of them through vim again (`--print` prints a
table to paste in) and reports any row vim no longer agrees with.

**Status legend:** ✅ complete and proven in the assembled editor on 0–100 K ·
🟥 works, but incomplete or not fully proven on paged files (gap named) ·
⬜ not built.

---

## Commands

| Keys | Command | Status | Proven / gap |
|------|---------|:------:|--------------|
| `h` `l` | left / right N chars | ✅ | counts; stops at col 0 and at the last char; 200-column lines pan both ways; tabs (the cursor on a TAB sits on its last column, as in vi) |
| `j` `k` | down / up N lines | ✅ | counts, huge counts, first/last line; screen rows exact on 1–12800 lines; one j/k deep in 100 K takes 0.08 s. Match vim 9.1 (`accept_vi.py` "j / k vs vim"): the goal is a screen column (a TAB under the cursor counts at its last column; `$` sticks to the line end; x, dd and leaving insert take it afresh from the cursor), j/k land on the char whose columns hold it; a line up to NEDIT/2+1 below or NEDIT/2-2 above the screen scrolls onto it, farther is centered |
| `G` | last line / line N | ✅ | bare `G` and `nG` (counts past the end land on the last line) reach the true line at 3 / 30 / 5120 / 12800 lines and a 109 K file of 200-column lines; window and row match vim 9.1 (`accept_vi.py` "G / gg vs vim"): the window stays if the line is on screen, a line just below or above scrolls onto the bottom or top row, anything farther is centered, clamped at both ends and after `^F` past EOF; the cursor lands on the first non-blank; on an empty file it stays home |
| `gg` | first line / line N | ✅ | bare `gg` and `ngg`, placed exactly as `G` (same checks) |
| `^F` `^B` | page forward / back | ✅ | window, cursor line, row and column match vim 9.1 (`accept_vi.py` "scrolls vs vim") on 1–12800-line files, a 109 K file of 200-column lines and a 66 K indented file: a count pages that many times (`100^F`, `99999^B`); a page is NEDIT-2 lines, NEDIT once the last line is on the screen (`^F`), NEDIT / NEDIT-1 when the top line is the last / next-to-last (`^B`); `^F` stops with the last line on the top row (`~` rows below); the cursor lands on the first non-blank (a panned line pans back); no-op at the ends |
| `^D` `^U` | half page down / up | ✅ | same checks: move `scroll` lines, NEDIT/2 until a count sets it (at most NEDIT, sticky, shared by both, as vim's 'scroll'); the cursor keeps its row, the text stops at either end while the cursor goes on; first non-blank; on the last / first line nothing moves, the column included |
| `0` `^` | line start / first non-blank | ✅ | match vim 9.1 (`accept_vi.py` "0 ^ $ <CR> w b W B vs vim", arg `mot`) on a 100 K file of words, punctuation, empty and blank-only lines, tabs, indents and 200-column lines, a small file with no final line end, one line and an empty file: `0` pans a wide line back and sets the goal to column 0; `^` stays on the last blank of a blank-only line and ignores a count; the line start is WM's `LINPOSB` (paged back) and the line is read with WM's `RGET` (paged in) |
| `$` | line end | ✅ | same checks: `N$` goes N-1 lines down first (scrolling as `j`), the goal sticks to the line end; on the last line a count over 1 moves nothing (the goal still becomes the line end) |
| `<CR>` | down N lines, first non-blank | ✅ | same checks: counts past the end land on the last line; on the last line nothing moves |
| `w` `b` `W` `B` | word forward / back | ✅ | same checks, with counts up to `99999` (the count prefix stops at 65535 rather than wrapping) through the whole 100 K file both ways: vim's classes (letters, digits and `_`; other non-blanks; `W`/`B` one class), an empty line is a word, a blank-only line is not; `w` on the last word goes to the file's last char and stops there; `b` stops at the file's start; the window scrolls as for `j`/`k`; the motions leave the file unmodified |
| `i` | insert before cursor | ✅ | text, CR (a `<CR>` typed at the end of the text opens a real empty last line, `ENDBRK`, as `o` does — see that row), TAB, far right of a wide line, 4.8 K bursts that page, at BOF / deep / in an empty file; `:w` byte-exact. BS/DEL as vim's (`backspace=indent,eol,start`): joins lines (a CR,LF goes as one, WM's rubout), goes back past the insert start and past the start of the paged-in window, no-op at the start of the file; checked against vim on plain, wide and indented files, 0–100 K. **Gap:** a count (`3iab<Esc>`) is ignored where vim repeats the typed text; held back for size — the same gap on `a A I o O R` |
| `a` `A` `I` | insert after the cursor / at the line end / at the first non-blank | ✅ | match vim 9.1 (`accept_vi.py` "a A I r R vs vim", arg `ins`) on small files (a line of blanks only, a TAB indent, an empty line, no line end after the last line, an empty file), a 66 K indented file, a 109 K file of 200-column lines and 100 K, each written back as vim wrote it: `a` on a line's terminator inserts in place -- stepping over the CR of the CR,LF an empty line is would put the text between the CR and its LF (that was the bug this test found); `A` inserts before the CR,LF, past all of a blank-only line's blanks; `I` at the first non-blank, and on a line of blanks only past the last of them, where `^` -- a motion, so it must land on a char -- stays on it. **Gap:** a count (`3aX<Esc>`) is ignored where vim repeats the typed text; held back for size — the same gap on `i o O R` |
| `r` | replace one char | ✅ | same files and checks: the next key is the replacement, a count digit (`r3`) or a control char included; nothing at all happens where there is no char -- an empty line, an empty file, the end of a line; ESC drops it; `r<CR>` makes the char a line break, as vim does. **Gaps:** a count is ignored (vim's `3rx` replaces three chars, or refuses when the line is shorter); an arrow / PgUp / PgDn clears the pending `r` and moves, where vim drops it |
| `R` | replace mode | ✅ | same files and checks: each char overwrites the one under the cursor, or is appended past the line's end; BS puts back what was replaced, char by char -- over a 200-column line and over 3000 chars appended deep in 100 K, both `:w` byte-exact afterwards (the overwritten chars are still in the gap, below `GAPEND`, and the restore is given up rather than got wrong when an insert has had to relocate the text); ESC leaves the cursor a char to the left, as vi does. **Gaps:** a count (`3Rxy<Esc>`) is ignored where vim repeats the typed text; held back for size — the same gap on `i a A I o O`; a BS with nothing of its own left stops at the line's start where vim carries on to the line above; and a line break typed in `R` ends what BS can put back (vim rejoins it) |
| `H` `M` `L` | window top / middle / last row | ✅ | match vim 9.1 (`accept_vi.py` "H / M / L vs vim", arg `hml`) on 1- / 2- / 3-line, 66 K, 100 K and 109 K wide files: `H` counts rows from the top, `L` up from the last text row, `M` ignores a count; the cursor lands on the first non-blank (a panned line pans back) and takes its goal column from there (a following `j` keeps it); the window never moves -- a count past it is clamped to the bottom / top row (vim's `cursor_correct`), and a count past the last text row to that row, so where `~` rows show (`G` then `^F`, or after `dd` at the end) all three land on the last line; after `^D` they use the rows as displayed |
| `o` `O` | open a line below / above, then insert | ✅ | match vim 9.1 (`accept_vi.py` "o O J ~ dw cw D  ^L vs vim", arg `ops`) on the files the inserts use (a blank-only line, a TAB indent, an empty line, no line end after the last line, an empty file), a 66 K indented file, a 109 K file of 200-column lines and 100 K, each written back as vim wrote it: the break goes in at the line's content end (`o`) or its start (`O`), so the new line is empty and the typing lands on it at column 0 — vim with no configuration has no autoindent, and neither has this; `o` on a last line with no line end appends the break rather than leaving the text unterminated, and gives the opened line a terminator of its own (`ENDBRK`) — an empty last line is a line, as it is in vim, so `k` then `j` comes back to it and `:w` writes it (two line ends, which is what vim writes); without that second break the row was painted but no motion could reach it and the write lost it; on an empty file `o` opens the second line and `O` the first. A 4.8 K burst typed on an opened line 6000 lines into 100 K pages out and is written byte-exact. **Gap:** a count (`3oX<Esc>`) is ignored where vim opens count lines and repeats the typed text; held back for size — the same gap on `i a A I R` |
| `J` | join the next line up | ✅ | same files and checks: the next line's leading blanks go and ONE space takes their place — except where nothing is appended at all (the next line is empty or blank-only, so only the break goes), where what is appended starts with `)`, where the line already ends in a blank, or where the line is empty; all four recorded from vim, the last two on a file written for them. The cursor lands on the join point, pulled back onto the line's last char when nothing was appended. On the last line nothing happens (vim beeps there). Joins a 200-column line, a TAB-indented line and deep in 100 K, `:w` byte-exact. **Gap:** a count is ignored (vim's `3J` joins three lines) |
| `~` | toggle case, step right | ✅ | same files and checks: the char under the cursor changes case and the cursor steps right; on a line's last char it stays there; a char with no case (a digit, a blank, punctuation) still steps over; where there is no char — an empty line, the end of the text — nothing happens. Over a 200-column line and the last char of a file with no line end. **Gap:** a count is ignored (vim's `3~` toggles three) |
| `dw` | delete a word | ✅ | same files and checks, and this is where vim is *not* a description of itself: `dw` never joins the next line up — vim's own `fwd_word` stops at the end of the line under an operator (its `eol` flag), so `dw` on the last word of a line deletes to the line's end, and on the **last word of the last line** it takes the whole word (not all but its last char, which is where our `w` has to stop as a motion); on an **empty line** vim promotes the span to linewise and the line goes away entirely, the cursor landing on the first non-blank of the line that follows, as `dd`'s does — it was landing on that line's *start*, which stayed invisible for as long as the only empty-line case had an unindented line after it (`bl`'s is followed by `xy`); the `.` group's `wd` case, whose next line is TAB-indented, is what showed it. The cursor is never left past the line's last char. `dw` on a blank run deletes just the blanks; deep in 100 K, `:w` byte-exact. **Gap:** a count (`3dw`, `d3w`) is untested — the motion takes it, but vim's rules above change with a count |
| `cw` | change a word | ✅ | same files and checks: `cw` is vi's one operator+motion special case — it changes to the word's END, like `ce`, *provided* there is an ordinary char under the cursor; on a blank it is a plain `w` (so `cw` on a blank-only line changes just the blanks), and on an empty line it changes nothing and simply opens the insert there. Proven on words, punctuation, a TAB indent, a 200-column line and deep in 100 K, `:w` byte-exact. On a line's **last char** `cw` stops at the line's content end, where a plain `ce` — and `de` — runs on into the next line's word, and `d%` crosses to its mate: vim's `cw`-is-`ce` rewrite keeps `w`'s own end-of-line stop, so the clamp belongs to the rewrite and not to inclusive motions at large (all four recorded from vim before the fix). That was DATA LOSS and it is the second bug the `.` group found: `cw` on the `b` of `ab` / `  cd` wrote `aX` and nothing else, the following line simply gone, and the `ops` group never saw it because the visible row was right. Other `c{motion}` forms share the machinery but are NOT proven; `cc` `s` `S` are not built — `cc` does nothing at all rather than deleting the line the way `dd` would (`C` **is** built, see its own row) |
| `D` | delete to the line's end | ✅ | same files and checks, unchanged code that this test finally proves: the content goes and the CR,LF stays, the cursor is pulled onto the new last char, an empty line and a blank-only line behave as vim's, and on the last line of a file with no line end too; mid-line 100 chars into a 200-column line, deep in 100 K, `:w` byte-exact |
| `C` | change to the line's end | ✅ | vi's `c$`: it takes exactly the span `D` takes and then opens the insert at the deletion point, so it is `D`'s code plus `SETINS` (12 bytes all in, `VCB_CD` shared). Matches vim 9.1 (`accept_vi.py`, group `ops`) on every file the `D` rows use — mid-line, at `0`, at `$`, a blank-only line, an empty line, a TAB indent, 100 chars into a 200-column line, deep in 100 K — each `:w` byte-exact; a bare `C<Esc>` types nothing and leaves the truncated line, hashing **identical to plain `D`**. `C` is deliberately not the idiom `D` then `a`, though the text they leave is the same (measured both ways): `C` is **one** change, so `.` repeats the delete and the typed text together and one `u` restores the whole line, where `Da` is two — `.` repeats only the append, and since undo here is single-level and `u` undoes `u`, one `u` reaches the truncated line and the next puts the insert back, leaving the deleted tail unrecoverable. Both are checked against vim in `dot` and `undo`. **Gap:** a count is ignored (`2C`), the same gap `D` has, where vim's `2C` changes to the end of the next line and joins them — and vim's `2C` on the last line fails and does nothing, as `2D` does |
| `^L` | redraw | ✅ | a full repaint that changes nothing: the text rows, the cursor and the window come back identical, an ex error message on the bottom row is blanked (a full repaint clears the message line, as vim's own `^L` clears its), and the text is unmodified (`:q` exits). It writes the whole screen where a still motion writes only the cursor |
| `x` | delete char at cursor | ✅ | mid-line, last char (cursor steps back), count stops at the line end, on a TAB, last line of 100 K |
| `dd` | delete line | ✅ | `dd`/`Ndd` at BOF, EOF, the only line, deep, and counts that run past the paged-in window (WM's line kill, DELLN, repeated until the count is spent); `:w` byte-exact, 0–100 K. As vim's: the cursor goes to the first non-blank, the window top stays, a count past the end deletes to it and lands on the new last line, a count over 1 on the last line does nothing; checked against vim on plain, wide (panned), indented and tabbed files |
| `.` | repeat the last change | ✅ | match vim 9.1 (`accept_vi.py` "`.` (repeat) vs vim", group `dot`) on the files the other edit groups use (a blank-only line, a TAB indent, an empty line, no line end after the last line), a 66 K indented file, a 109 K file of 200-column lines and deep in 100 K, each written back as vim wrote it: it repeats the last command that CHANGED the text — `x` `dd` `dw` `cw` `D` `r` `~` `J` `p` and the inserts `i a A I o O R` — while a motion, a `yy`, a `:w` or a key that is not a command at all leaves the previous change in place, and with nothing changed yet `.` rings the bell and moves nothing. The repeat carries the original count (`3x` then `.` deletes three) and a count typed on the `.` replaces it (`3x` then `2.` deletes two). An insert repeats with its typed text because the repeat IS the keystrokes: they go back through the same `CMDDIS` dispatch, so there is no second implementation of any command to keep in step and a command built later is repeatable the day it is built. `.` never becomes the last change itself, so a second `.` repeats the same change again. **Gap:** the recording holds 128 keys, so a longer change — an insert of more than 126 characters — is not repeatable at all and `.` rings the bell, where vim has no limit |
| `u` | undo the last change | ✅ | match vim 9.1 (`accept_vi.py` "`u` (undo) vs vim", group `undo`) over one change of every kind — `x` `dd` `Ndd` `dw` `D` `cw` `r` `~` `J` `p` `P` and the inserts `i a A I o O R` — on the small edit files (a TAB indent, an empty line, no line end after the last line) and deep in 100 K / 66 K indented / 109 K of 200-column lines, each written back **byte-exact** as vim wrote it. The capture is not in the command layer at all: the six primitives that can change resident text (`PUTGAP` `QGET` `DELFWD` `DELPRV` `UNDELF` `QPUTLN`) each report what they did, so no command can forget to record itself and a command built later is undoable the day it is built. A record holds only where, how much and where its bytes went, in **logical offsets**, and the replay walks the records backward so each step restores the offsets the steps after it were measured against. The bytes are kept for an insert as well as a delete, so the region is settled once the command ends and `u` can walk it either way — which is what makes `u` undo `u` with one region. The text lives in its own region of the arena between the slider and the text, grown through the same `MKGAP` as the Q-buffer, so the pointer row's two interleaved walks (`NEXTPR` over holes from `BUFBEG`, over data regions from `QBEG`) stay aligned and `MOVGAP`/`BUFSUM`/`HOLEUP`/`HOLEDN`/`INIBAS` are untouched. The region grows **only at the command boundary**, and the capture then writes into that claimed room without ever calling `MKGAP` — because growing it where a primitive can see it both invalidates the raw pointer `DELPRV` hands `SETGAPB` and overwrites the gap, which is exactly where a forward-deleted byte waits for `R`'s backspace to call `UNDELF` and give it back. The room is claimed as the region's own content rather than left as the hole above it, because holes are shared and the text takes whatever it can reach. `u` is not itself a change, so a `.` after a `u` still repeats the command the undo took back. **DEVIATIONS:** one level, so a second `u` puts the change back where vim walks further down its undo tree (real vi's behaviour, and the reason this is a `u`-undoes-`u` and not a `^R`); a change is undoable only up to 24 primitive steps and 1024 bytes of text, and past either `u` rings rather than doing half of it (`R` reaches the step limit quickest — it deletes and inserts per character, so about 12 characters — while a typed insert coalesces into one record and is bounded only by the 1024); once the pager has moved the window's top off the change (`PGTOPM`) `u` says so on the bottom row instead of chasing it through the file; a `:w` clears the undo, because the write rewinds the buffer through the pager and rebuilds every offset a record holds; and the cursor goes back to where the command that made the change **began**, which is what vim does for every command measured except `A` (vim lands on the line end `A` moved to, clamped into the restored line) — recorded as `UNDO_SKIP` beside the table |
| `m` `` ` `` `'` | set a mark / go back to it | ✅ | match vim 9.1 (`accept_vi.py` "`m` / `` ` `` / `'` (marks) vs vim", group `marks`) over 53 recorded rows: `m{a-c}` sets a mark, `` `{a-c} `` goes back to the **exact spot** it was set at and `'{a-c}` to that line's **first non-blank** — the one difference between the two spellings, and most of the table exists to hold it. Proven with the mark on an indented line, on an empty line, on the last line, in a file with no final line end, with three marks live at once, and with the file written back byte-exact. A mark is a logical offset plus the `PGTOPM` the window carried when it was set, and it is held in `RSV.MAC`'s reserve block, so the three of them cost the `.COM` nothing. **DEVIATIONS:** a mark is **dropped, never shifted** — vim moves a mark to follow its text when something above it changes, and this editor instead invalidates it, so an edit at or above a mark, an undo reaching back past it, a `:e`, or the window paging away all lose it. A lost mark rings the bell and moves nothing, exactly as `.` and `u` do when they will not run; there is no separate "mark not set" message, so never-set and gone-stale answer alike. A consequence worth knowing: `.` after a `d'a` refuses, because the delete drops the very mark the replay would need. Only `a`-`c` exist (`m{d-z}` rings), and a count on any of the three is ignored, as it is on `r`. **Under an operator:** `d'a` is LINEWISE (the mark's line through the cursor's, whole) and `` d`a `` is CHARWISE exclusive, so it deletes the span between the two points and the two partial lines JOIN — the difference between the spellings again, and both recorded from vim. `` c`a `` changes such a span; **`c'a` is refused**, as every linewise motion under `c` is (`cj`, `cG`, `cH` likewise — `OPPEND` drops them rather than get them wrong), though the mark letter is still swallowed so a refused `c'a` cannot type an orphaned `a` into the buffer. A mark that will not answer cancels the operator whole rather than applying it over an empty span — which matters because an empty LINEWISE span still takes a line. `` ` `` is classed a JUMP (`OPCTAB` class 3), not an ordinary exclusive motion, so it is exempt from the end-of-line clamp that stops `dw` joining the next line up. **Under a yank:** `y'a` yanks the mark's line through the cursor's, whole, and leaves the cursor on the **low** endpoint exactly where the motion put it — on `'a`'s first non-blank, recorded from vim. `` y`a `` is **refused**, as every charwise motion under `y` is, because there is no charwise register; its mark letter is swallowed all the same, so a refused `` y`a `` cannot type an orphaned `a` into the buffer either. A mark that will not answer cancels the yank whole, and a yank is not a change, so `.` still repeats whatever changed before it |
| `:w` | write | ✅ | byte-exact at every size (a file with no line end after its last line is written back without one); editing continues afterwards (same line, row and column; then `:w` again); WM `H`-style re-open. The `:` line is WM's RDLINE, as vim's: it shows on the bottom row and echoes what is typed; BS/DEL erase the last char; BS/DEL on an empty line or ESC cancels it, leaving the typed line on the row rather than blanking it, as vim leaves it too; checked on plain, wide (panned) and 100 K files |
| `:q` `:q!` | quit / force-quit | ✅ | `:q` exits when unmodified or just saved and refuses when modified, showing "File changed (! to force)"; `:q!` exits and leaves the file on disk untouched; neither leaves `name.$$$` or `VIBACKUP.$$$` behind. The `:` line as for `:w`; a line edited with BS/DEL runs as it was left. The quit is the one key that repaints nothing: the text already on the screen is what is left behind, the cursor on the bottom left with that row cleared, so the `A>` the CCP prints lands there (one scroll, no redraw). It writes nothing, and a session that never spilled deletes nothing either -- a BDOS delete scans the whole directory whether the name is on it or not, which cost a second of dead time per work file on a large drive |
| `:w {file}` `:w! {file}` | write to another file | ✅ | as vim's: the buffer keeps its name and stays modified (`^G` still says `[Modified]`); an existing file needs `!` ("File exists (! to force)"); a buffer with no name takes the name. `[d:]name.typ` is upper-cased and cut to 8.3 (WM's parser); a wildcard, a CCP delimiter, a bad drive or more after the name is "Invalid file name". Writes to another drive copy the work file. Byte-exact on 100 K, then editing and `:w` continue; checked on drive B too |
| `:wq` `:x` | write and quit | ✅ | `:wq` always writes, `:x` only a changed text; with `{file}`, a still-changed buffer refuses to quit after the write (vim's E162, shown as the E37 text); `!` forces the quit. The buffer's own file keeps `name.BAK` on exit, as WM's `E` does |
| `:e` `:e!` | reload the file | ✅ | as vim's: back on the same line (the last one if the file is now shorter), on the middle row (clamped at either end), on the first non-blank; a changed text needs `!`; the line is counted before the text is dropped (the output records read back); checked against vim on 100 K, wide and indented files |
| `:e {file}` `:e! {file}` | edit another file | ✅ | its first line, first non-blank; a file that does not exist is a new, empty buffer with that name (`:w` creates it); the old work files are deleted |
| `:s` `:%s` `:N,Ms` | substitute (with `g`) | ✅ | recorded from vim 9.1 BEFORE it was written (`accept_vi.py` ":s / :%s / :N,Ms vs vim", 30 cases): `:s` changes the first match on the cursor's line, `g` every match, `:%s` the whole file and `:N,Ms` that span, on 100 K numbered, 109 K 200-column and 66 K indented files -- including one that GROWS the file 12800 bytes. The cursor lands on the first non-blank of the LAST line changed, placed exactly as `G` places a line (measured: `:12800,12800s` leaves it on row 22, `:100,105s` on row 11); a pattern found nowhere changes nothing and moves nothing, on a line, over a paged file and on an empty one; the written file is byte-exact. One substitute is ONE change for `u`, which lands on the first line changed. The pattern is LITERAL (see the search deviation) and it becomes the last search pattern, so `n` repeats it, as in vim. A blank between the range and the command name is taken the way ex takes it (`:2,4 s/a/Z/`, `:% s/a/Z/`, more than one blank) -- 7 more recorded rows, each hashing identical to its no-blank twin, for 3 bytes; **DEVIATION:** a blank around the comma (`:2, 4s`) is still refused |
| `:ve` | show the version | ✅ | "V1.0" on the bottom row, where it stays as any message does; the text and the cursor are left alone (`accept_vi.py` group `file`, with the messages). The version is typed into CMD.MAC (`SVER`) by hand. **DEVIATION:** vim's `:version` fills the screen with the build and its features and waits for ENTER; this is one line. Only `:ve` is accepted: `:ver` and `:version` are "Invalid command", because the ex parser takes names of one or two letters. A range (`:1ve`) is refused and anything after it is "Trailing chars", as for `:q` |
| (no file name) | `VI` alone | ✅ | an empty buffer, status `[No Name]`; `:w` `:wq` `:x` show "No file name" on the bottom row; `:w {file}` names it; 48 K typed pages out and is written byte-exact |
| `yy` `Nyy` `Y` | yank N lines | ✅ | linewise, into WordMaster's own Q-buffer (`QBEG..QEND`), a second gap buffer inside the arena — so the register is not a fixed block: it grows through the same `MKGAP` machinery as the text, the text pages out from underneath it, and the ceiling is `QROOM`'s (the arena less `RESVMEM`, about 27 K). Match vim 9.1 (`accept_vi.py` "yy / p / P vs vim", group `put`) on 1- / 2- / 3- / 40-line files, an indented one, blank and empty lines, 200-column lines and a file with no line end after its last: a count **clamps** at the last line rather than refusing it, and the cursor does not move. WordMaster has no copy-without-delete (`QCOPY`'s source is always `GAPEND`, and a non-deleting chunked copy has no pointer the gap machinery keeps valid across its `MKGAP`), so `yy` takes the lines out with `dd`'s engine and puts them straight back with `QGET`, restoring `MODF` and `LNDLT` — correct, but it moves the text twice, so a big `Nyy` costs about double a `Ndd`. `y{linewise motion}` shares that machinery (`YKGO`): only how the lines are taken differs — `yy` by `dd`'s count, `y'a` by a span whose end `YSPAN` recognises from the text's length. The marks are held across it (`MKHOLD`), because the lines come back unchanged and every mark still points at the same text. A count of more than one **on the last line** is refused, by `yy` as by `dd`, and the register keeps what the previous yank put there — recorded from vim. Because `yy` takes its lines out and puts them back, a refusal that still put the register back spliced that earlier yank's line into the file; `YKGO` now puts nothing back when nothing came out |
| `p` `P` `Np` | put the yanked lines | ✅ | same group: `p` after the cursor's line, `P` before it, a count putting that many copies, and the cursor on the **first non-blank of the first line put** whatever the count — all recorded from vim before any of it was written. `dd`/`Ndd` fill the register too, as vim's do, so `dd`…`p` moves lines. With nothing yanked yet `p` rings the bell and changes nothing. A put past a last line with no line end on it adds the missing break first. Overflow is WordMaster's `'QBUF FULL'`, raised from inside `QCOPY`'s chunk loop — what has already moved is in the register and gone from the text, so text + register is conserved and the put gives back exactly what was taken |
| `/` `?` `n` `N` | search | ✅ | a **literal string**, not a regular expression (see the deviation below). `/` forward from one character past the cursor, `?` backward, both landing **on** the match's first character and keeping that column as the goal column; `n` repeats the last search's direction and `N` reverses it, so `n` after a `?` keeps going backward; an empty pattern (`/` then `<CR>`) repeats the last one; a count repeats the search (`2/a` is the second match, `15n` fifteen `n`s). `wrapscan` is on, as vim's is: a search that runs off one end of the file starts again at the other, so `/` on a file's only match finds it again. Not found leaves the cursor exactly where it was — at any count — and says "Pattern not found: …" on the bottom row; `n` with nothing searched for yet says "No previous search pattern". Matches vim 9.1 (`accept_vi.py` "/ ? n N vs vim", group `srch`) on a 12800-line file the search pages all the way through, 200-column lines that pan past the right screen edge, an empty file and a pattern that is not there. It is WordMaster's own matcher — `MATCHF` / `MATCHB` over `SCANF` / `SCANB` — swept across the file by WM's `FINDA` loop, so the search sees the whole file, not the resident window; the window is placed exactly as `G` and `+{n}` place it, because it ends in the same `GPLACE` |
| `+{n}` `+` | the line to start on | ✅ | on the command line, AFTER the file name (`VI REPORT.TXT +500`) where vim takes it before, because the CCP parses the first token of the line into the FCB at 005CH. Lands where vim 9.1 lands (`accept_vi.py` "+n / -R on the command line vs vim", arg `arg`) on a 100 K file, a 66 K indented one, a 109 K file of 200-column lines, a 100 K file of words, 1- / 3-line files, a file with no line end after the last line and an empty file: the line's first non-blank, with the window scrolled the least it can be while the line is near the top and **centred** once it is farther off (the boundary is `+35` / `+36` on 24 rows), `+` alone and a number past the end on the last line, `+0` and `+00` on line 1, `+007` on line 7. It is not placed by hand: the digits go through the command dispatcher and a `G` does the work, so it *is* vim's `nG` from a file just opened — which is what vim's own `+{n}` turned out to be, every recorded row. More than 5 digits is past the 16-bit line space and is taken as `+` alone |
| `-R` `/R` | read only | ✅ | same group: a write to the file it opened is refused with "'-R' is set (! to force)" (vim's E45, shortened — see the messages row) — `:w`, `:wq`, `:x` and `ZZ` alike, each leaving the text, the cursor and the file on disk alone; `:w!` overrides it and `:w {file}` was never refused, as in vim. It does not stop the editing itself (vim's `-R` is not `nomodifiable`). One test in `WRCHK`'s own-file arm covers every write path. `/R` is accepted as CP/M spells a switch, and the CCP's upper casing makes `-r` the same |
| `ZZ` | write if changed, then quit | ✅ | vim's `ZZ`, which is `:x`: it writes a changed text (leaving `name.BAK`, as `:x` does) and exits, exits without writing when nothing changed, and says "No file name" on the bottom row for a buffer that has none; a count is ignored; only a second `Z` may follow the first -- any other key is dropped with it and moves nothing, as vim does (except an arrow / PgUp / PgDn, which has no vi key of its own here: it clears the pending `Z` and moves) |
| `^G` | which file, and where am I | ✅ | `"TEST.TXT" [Modified][readonly] line 2 col 1`, with the flags run together after the name and one space before the first of them, as vim writes them. The line and both columns are vim 9.1's own, recorded by `vimref.py` (`ctrlg`) BEFORE any of it was written (`accept_vi.py` "^G / the message line vs vim") on 1- / 2- / 3-line files, a file with no line end after the last, blank and empty lines, a 66 K TAB-indented file, a 109 K file of 200-column lines and a 12800-line one: a TAB under the cursor makes the byte and screen columns differ and vim prints both (`col 1-8`), an empty buffer is `--Buffer empty--` (vim says `--No lines in buffer--`; see the messages row) and a buffer with no file is `"[No Name]"`. The line number is `CNTLF`, which counts the line ends behind the cursor by reading back the records already spilled — so it costs disk on a paged file and nothing at all on a resident one. **DEVIATION:** vim also gives the file's line total and a percentage of it (`line 2 of 4 --50%--`); no line total is kept anywhere here, and counting one means sweeping the whole file out to EOF and paging it back, which costs the wait and the undo region (`PGTOPM`) both |
| the bottom row | vim's message line | ✅ | it is a MESSAGE line, blank unless something has been said on it — not a status row. Opening a file says `"TEST.TXT"`, `"TEST.TXT" [readonly]` or `"NEWF.TXT" [New]` (and nothing at all for a buffer with no file, as in vim); `:e` says the same; `:w` says `"TEST.TXT" written`; an insert shows `-- INSERT --` and `R` shows `-- REPLACE --`, both gone on ESC. A file on another drive is named with its drive (`vi b:test.txt` from `A>` says `"B:TEST.TXT"`, in the load line, `^G` and `:w` alike), because vim writes a path relative to the current directory and the logged drive is CP/M's current directory: a file on the logged drive is bare, even if it was typed as `A:TEST.TXT`. A message stays until another replaces it or a full repaint blanks the row, so it survives motions and edits the way vim's load line does. **DEVIATION:** vim counts what it read and wrote (`"TEST.TXT" 3L, 30B`, `3L, 29B written`) and this does not, for the same missing line total `^G` describes; the byte count alone was affordable (the directory gives the size in records and one read of the last record finds where it stops) but a byte count with no line count beside it is not vim's line either way. **HISTORY:** this row used to be a permanent status row showing the file name and a `[+]` marker — vim's default status line, which stock single-window vim does not show at all. It was removed here because vim does not deviate that way |
| messages | ex errors | ✅ | on the bottom row, without vim's `Enn` number; a message stays until another replaces it or a full repaint clears it (an edit does not wipe it, as vim's does not): "No file name", "File changed (! to force)", "File exists (! to force)", "Invalid command: …", "Trailing chars: …", "Invalid file name", "'-R' is set (! to force)", "Cannot undo: change has paged out", "Too large to undo", "--Buffer empty--". **DEVIATION:** most of these are SHORTENED from vim's own wording — the strings are image bytes, and image bytes come out of the editing arena (the shortening saves 69 bytes). They read the same but they are not vim's text, so do not cite them as evidence of matching vim; "Invalid file name" is not vim's at all (CP/M names). The behaviour around them — which error outranks which, and that a message survives an edit — is vim's and is tested |

## Not built

Anything not in the table above. A handful of handlers exist but are
resident-only and unproven on paged files (🟥); the rest is unbuilt (⬜). Listed
with the reasoning, because several of these are decisions rather than gaps.

A 🟥 here is **not** a candidate for deletion. `e`/`E` are load-bearing for
`cw`; `d`/`c` over the other motions are not handlers at all but the operator
machinery meeting motions that are each ✅ in their own right, so removing them
would mean *adding* a rejection list; and charwise `y` is already refused in
`OPPEND`. The two ⬜ removal bullets that open this list are a different
case: `^E`/`^Y` worked and were proven, and are out for the bytes; `f F t T ;
, %` are out because they are not wanted and were never proven on a paged
file.

- Scrolls: `^E` `^Y` — ⬜ **removed, deliberately.** These were built and
  proven against vim 9.1 like every other scroll, so this is not a quality cut:
  it is a usage one. `^E`/`^Y` are in POSIX vi but are on no list of commands
  people actually reach for, and `^D`/`^U`/`^F`/`^B` cover the need while
  moving the cursor with the text, which is what one usually wants. They cost
  **173 bytes** — 56 for `VC_SCDN`, 107 for `VC_SCUP`, 6 of `CMDTAB` rows and 4
  of state (`SCYCNT`, `SCYLN`) — and the binary is the scarce resource. The
  asymmetry is worth recording: `^E` could leave the cursor and let `LAYOUT`
  clamp at the file end, while `^Y` had to go to the top line, walk up, then
  come back down to the old line or the screen bottom, and that round trip
  through `MVROW`/`LNDLT` was the extra 51 bytes. Nothing else called either
  one: both were leaf handlers with no `OPCTAB` row, so unlike `e`/`E` below
  there was no computed-key path into them. The 18 `VIM_SCROLLS` rows and 2
  `VIM_HML` rows that recorded them went too (`scrolls`, `hml`). `SCBOT` /
  `SCEOF` / `SCBOF` stay: `^B`, `^U` and `H M L` read them.
- Motions: `f F t T ; , %` — ⬜ **removed, deliberately.** Their handlers
  only ever worked on the resident window and were never proven on a paged
  file; removing them saved 546 bytes — 511 of handler, 21 of `CMDTAB` rows
  and 14 of find-char/bracket state. `d`{motion} reached them through the
  dispatch table, so `df{c}` and `d%` are gone too, and their `OPCTAB` rows
  with them: an operator on one of these keys cancels, as `cq` does. The
  binary is the scarce resource and these are commands this editor does not
  want. All fourteen operator+motion pairs are checked in `ops`, because an
  `OPCTAB` row without a `CMDTAB` row is not inert: `OPPEND` takes a class,
  `VSCAN` finds no handler so the cursor does not move, and the class-1
  inclusive `INX H` turns the empty span into one character — `df` would
  delete the char under the cursor and `cf` delete it and open an insert, an
  unannounced `x` and `s`. The rule the table's own comment carries: **every
  key in `OPCTAB` must also be a row in `CMDTAB`**
- Motions: `e` `E` — 🟥, and they **stay**, because `cw`/`cW` need them: vi's one
  operator+motion special case is that `cw` is `ce`, and `OPPEND` implements it
  by rewriting the pending key (`SUI 'w'-'e'`) and dispatching it through
  `CMDTAB`. So the two rows and the `VC_E`/`EDO`/`ESTEP` word-end scanner (184
  bytes) are load-bearing for a *proven* command, and `e`/`E` remain typeable as
  a side effect. A label search does not show this — the dispatch table is
  reachable by computed key, so cutting a row can break code that names nothing
- Operators / registers: `d`{motion} other than `dw` (🟥 — the span machinery is proven through `dw`/`cw`, the other motions are not); `c`{motion} other than `cw` (🟥); `cc` `s` `S` `>> <<` — ⬜; `y`{motion} — ✅ for **linewise** motions (`y'a` `yj` `yk` `yG` `yH` `yM` `yL`), 🟥 for charwise ones, which `OPPEND` drops: a charwise register (from `x`, `D`, `dw`) is not built — it needs a type flag beside the Q-buffer, and `p` would have to put within a line. So `y` takes class-2 motions only, the mirror of `c`, which takes every class but 2 (`cc` is deliberately inert)
- Undo / marks: `m`{a-c} `` ` `` `'` — ✅ **built**, `a`-`c` as decided; `d`-`z`
  are ⬜ and ring the bell. `.` and `u` are both built and proven — see the
  table above
- Search: `* #` — ⬜; search **offsets** (`/pat/e`, `/pat/+2`) — ⬜; `:set ignorecase` / `smartcase` — ⬜ (the search is case-sensitive, as vim's default is)
- Ex: `:N` as a goto (the address parser is there for `:s`, so `:100` would be a few bytes -- not built), `:r` `:e #` `:stat`, long command names (`:write`) — ⬜
- Command line: `/Ln` `/Cn` (screen geometry) switches and a config file — ⬜ **deliberately not built.** `SCINIT`'s DSR probe autodetects the terminal with a bounded fallback, which is strictly better than a switch; a config parser would cost about two CP/M records to do what the probe does for nothing. A terminal that lies is better patched in the `.COM` at a documented offset. `/B` is not a switch either: the backup rule is per command, as vim's — `:w` on the buffer's own file keeps `name.BAK`, `:w {file}` does not

### Deviation: `yy` on a genuinely empty buffer

vim's buffer always holds at least one line, ours can hold zero bytes. Everywhere
that matters the two were made to agree — `p` into an empty buffer puts *after*
an empty line, as vim does, because the missing-line-end path runs when `LOGLEN`
is 0 — but `yy` on a buffer with no text in it cannot: vim yanks its phantom
empty line, so a following `p` adds a line, while `QPUTLN` yanks a zero-byte span
and leaves the register empty, so `p` rings the bell. Two rows of `VIM_PUT` (the
empty file `'0'` and `'mt'`) record vim's numbers and are the only ones the
editor is not held to.

Not fixed on purpose: matching it means giving the register a synthetic CR,LF for
the one case that has no text to yank, and the binary is the scarce resource
(16384 bytes, and every byte of image is a byte less editing arena). Nothing is
lost or corrupted
— an empty file yanks nothing and puts nothing.

### Deviation: a put's last line and `noeol`

vim's `'noeol'` is a flag on the **buffer**, not on a line. So on a file whose
last line has no line end, `3yy` `G` `p` makes vim write the put's last line
without one — even though that line came from a *terminated* source line — while
we write the bytes the register actually carried:

    source      ab / (blanks) / TAB cd / (empty) / xy      <- no final line end
    vim wrote    ... xy, ab, (blanks), TAB cd               <- no final line end
    we wrote     ... xy, ab, (blanks), TAB cd, <CR><LF>

Ours is what vim itself puts on disk; only `vimref.py`'s fold, which exists to
model *this* editor's write path, disagrees. The `'nl'` rows pass because there
the yanked line was itself unterminated, so the register carried no terminator
either. One row of `VIM_PUT` (`bl` `3yy G p`) has its file hash skipped for
this; its cursor rows are still checked.

---

### Deviation: the search is a literal string, not a regular expression

vim searches with a regular expression: `/a.*b`, `/^foo`, `/\<word\>`. This
searches for the characters typed, exactly as typed — `.` matches a dot and `*`
matches an asterisk. An 8080 has no room for a regex engine (the matcher that
*is* here, `MATCHF` + `MATCHB` + `SCANF` + `SCANB` + `WCMATCH`, is 111 bytes
altogether), and a literal search is the part of `/` that gets used.

WordMaster's own search wildcards still reach `WCMATCH`, because the matchers
compare through it: `^A` matches any character, `^S` any non-alphanumeric, `^O`
negates the next. They are WordMaster's syntax rather than vim's and nothing
advertises them, but they are not removed either — they cost nothing and the
`RDLINE` prompt drops control characters, so they can only arrive in a pattern
deliberately.

### Deviation: overlapping matches

Given `xxxxxx` and the pattern `xxx`, vim finds matches at columns 0 and 3 —
its scan resumes at the end of each match, so the matches in a line tile
non-overlapping from the first one. `searchpos('xxx','Wn')` from column 8 of a
run of x's answers column 9, not column 9 because the search began at 9: `xx`
steps by two and `xxx` by three, whatever column the cursor is on.

This editor finds every match, overlapping ones included, so the same `n` walks
0, 1, 2, 3. It is the natural behaviour of a literal scan (`SCANF` finds each
candidate first character and the comparison starts there), and reproducing
vim's would mean rescanning each line from its start to rebuild the tiling.
The two behaviours only ever differ for a pattern that can overlap itself,
which is why `VIM_SRCH` covers the long-line cases with `ab-cd` and says so.

### Deviation: a match that straddles the cursor

`?` finds the last match that ENDS before the cursor; vim finds the last one
that BEGINS before it. With the cursor on the `b` of `abc`, vim's `?ab` finds
the `ab` starting one character back and this does not.

This is the gap buffer showing through, and it is WordMaster's behaviour too:
`MATCHB` is set up at `GAPBEG` less the pattern length so the whole match lies
below the gap, because the bytes at and above `GAPBEG` are the gap itself, not
text. Reading a match across the cursor would mean reading the hole.

### Deviation: what `:s` does not do

The pattern and the replacement are both LITERAL, for the reason the search is
(above), so there is no `&`, no `\1` and no `~` either -- a replacement is the
characters typed. Not built: the `c` (confirm) and `n` (count) flags, relative
addresses (`:.,$s`), and a bare `:s` repeating the last substitute (`&`).

The `:` line itself holds 40 characters (`EXMAX`), which is the real limit on
how long a substitute can be: `s/`, the pattern, `/`, the replacement and an
optional `/g` all have to fit, so pattern and replacement come to about 35
between them. The replacement buffer is sized from `EXMAX` rather than guessed
(`SREPMX EQU EXMAX-4`), so a substitute that fits on the line always fits in
the buffer -- nothing is ever silently truncated.

A blank between the range and the command name is taken, the way ex has always
taken it: `:2,4 s/a/Z/` reads as `:2,4s/a/Z/`, and so does `:% s/a/Z/` and more
than one blank. Seven rows record this from vim, and each is one of the
no-blank substitutes above with the blank typed in, so every hash comes out
**identical to its no-blank twin** -- which is the assertion. It costs 3 bytes:
`EXADDR` deliberately does not eat its own trailing blanks, and `VC_EX` calls
the same `SKIPB` after it that it already called before it. **DEVIATION:** the
one place a blank is still refused is INSIDE the range, around the comma
(`:2, 4s`), which ex accepts. The comma is read mid-number off `DE` rather than
through `SKIPB`'s `HL`, so skipping there costs more than the position is
worth; `subst_cmds()` pins the refusal and its message.

An address PAST the last line is clamped onto it, where vim refuses the whole
command ("E16: Invalid range"). Refusing would mean counting the file's lines
before doing anything, which is a full paged walk of up to 100 K to reject a
typo; `:20000s` on a 12800-line file therefore substitutes on line 12800, as
`G` with too large a count lands on the last line. `:0s` IS refused, because
line 0 needs no counting to rule out.

A BACKWARDS range is refused rather than swapped. vim asks "Backwards range
given, OK to swap (y/n)?"; there is nowhere to ask that from a one-line ex
prompt, and a silent swap would be a different command from the one typed, so
`:100,99s` answers "Invalid command:" with the line. That also makes it
the one case vim cannot be the reference for -- a prompt cannot be scripted --
so it is proven in `subst_cmds()` instead.

### Deviation: a substitute too large for the undo region

The undo region is a fixed 1024 bytes with room for 24 records, and a
substituted line costs two (the delete, then the insert), so about a dozen
lines fit. A bigger substitute still happens -- it is the useful command --
but `u` cannot take it back, and it SAYS so instead of ringing a silent bell:
`u` answers "Too large to undo". `UNDWHY` carries the reason, which fixes the
same silent bell after a large `R` as well.

The warning arrives on `u`, not when the substitute runs. That is a choice:
the deferred-message machinery (`MSGWHT` / `MSGPST`, drawn after the frame)
could carry it past the full repaint a substitute needs. It is not wired to
it, because `u` is the moment the
reader is asking the question, and a warning on every large `:s` would be noise
on the line vim keeps for what it just did.

---

## Decided, deliberately not built

## What is trusted vs. not

| Layer | State |
|-------|-------|
| `BUF.MAC` — gap buffer | trusted (verbatim WM); `LOGLEN` = resident length, correct for a window |
| `PAGE.MAC` — pager + safe-save | trusted engine (verbatim WM); proven byte-exact through the editor at 0–100 K. `:w`-and-continue uses appended `REOPEN`/`SEEKTO` (WM `H` re-init plus the `SAVCLO` flush/refill loop); `:w {file}`/`:e` use appended `WRTO`/`DISCRD`/`CNTLF` (WM's `SAVCLO`, `RENAME`, `RENF`, `DELF`, `RDNEXT`) |
| `PAGE.MAC` — `SAVEFIL` (WM 557, `ENDEDIT`) | **still live code, not dead**: it writes back only the file it read, so the *editor* does not call it (it writes through `WRTO`, which can name another file), but all four pager tests — `PGTST`, `PGXTST`, `PGXINS`, `PGBKTST` — drive it as their write-back step, and that is how WM's own save side (`SAVCLO` → `FLUSHTX`/`FILLBF2` + the two renames) stays gated. Keep it: it is 26 bytes, and dropping it shrinks `VI.COM` only when that crosses a 128-byte record boundary. If it is ever removed, those four stubs must be pointed at `WRTO` first |
| `KEY.MAC` — key decoder | trusted (paging-orthogonal) |
| `SCRN.MAC` — terminal I/O half | trusted (`BCONxx`/`OUTCH`/`OUTSTR`/`GOTOXY`/DSR/`RDNUM`) |
| `SCRN.MAC` — viewport/paint | built on WM's cursor-relative model (`WINROW`, `LINPOSB`, `RGET`/`NEEDIN`, `WRLIM` as WM `MEASURE`); see `RENDER.md` |
| `CMD.MAC` — vi command layer | every command runs on WM's paged line move (`MVLIND`/`SETBWD`/`MVLMAX`); gaps are listed in the table above |
| navigation/paging layer | WM's own: line moves page as they go; the screen pages in on demand (`NEEDIN`) and back (`LINPOSB` → `PAGEWIN`) |

> There are no per-command byte-size tables here. The old ones tracked handler
> sizes for commands that did not actually work on real files — exactly the kind
> of green-looking-but-false accounting this file exists to avoid.
