# How the pager behaves

`BUFFER.md` describes the gap buffer and names the routines that page it. This
document shows what those routines **do** in a series of editing scenarios,
with and without edits. It covers which file each record goes to, how many
disk transfers each key costs, and what is left in memory afterwards.

Every figure was read out of the running editor by `pagerprobe.py`. The code
is cited to name what a measurement shows; the few statements that come from
the code alone say so. Every scenario that saves was checked: the
saved file matches, byte for byte, what its edits should have produced.

* **Build:** `VI.COM` of aabc816, 21,504 bytes, on the harness machine
  (`vi.toml`).
* **Memory:** the arena is 23,298 bytes (`5B03H`–`B605H`), and the first
  command claims 1 K of it for undo, so about 22 K holds text.
* **Test file:** `TEST.TXT`, 81,920 bytes, which is 640 records of 128 bytes.
  It has 10,240 lines of 8 bytes (`000001` CR LF ...). Line *n* starts at byte
  8(*n*−1), and record *r* holds lines 16*r*+1 to 16*r*+16.
* **Seconds:** the simulator's 2 MHz clock, less what finding the guest idle
  costs. The simulated drive has no seek or rotation time, so every figure is
  a floor. A real drive adds head movement to every transfer, and most of all
  when the pager alternates between two files.
* **Disk calls:** counted by a conditional breakpoint on the BDOS entry
  (0005H), so the editor runs unmodified. "r" is a record read and "w" a
  record write.

---

## 1. Where the text is

At any moment every byte of the file is in exactly one of these places:

```
      above the window             the window (RAM)               below the window
  ┌──────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
  │ TEST.$$$  (OUTFCB)   │  │ TXTBEG .. [gap] .. TXTEND │  │ VIBACKUP.$$$ (a stack),   │
  │ records 0..OUTPOS-1  │  │ 22 K at most              │  │ then the unread rest of   │
  │ the new file, built  │  │                           │  │ TEST.TXT                  │
  │ from the front       │  │                           │  │                           │
  └──────────────────────┘  └───────────────────────────┘  └───────────────────────────┘
       REWIND reads ◀── top edge                bottom edge ──▶ FILLBUF reads
       PAGEOUT writes ──▶                                  ◀── PAGEBOT pushes back
```

* **Above the window, the text exists only in `TEST.$$$`.** The source is
  read forward only, and the pager never goes back to it for text above the
  window. `TEST.$$$` is not a scratch copy. It is the new file, written from
  its first record, and a save renames it over `TEST.TXT`.
* **Below the window is input that has not been read yet.** That is the rest
  of the source from its read pointer on, with `VIBACKUP.$$$` in front of it
  holding records the pager pushed back down. `VIBACKUP.$$$` is a stack: the
  record pushed last is the next one read.

The marks the pager keeps, and what they mean in the measurements:

| Mark | Meaning |
|---|---|
| `OUTPOS` | `TEST.$$$` record number of `TXTBEG`; the records above the window |
| `OUTREC` | how many records at the front of `TEST.$$$` are valid. A record leaving the top below this is already on disk and is not written again. An edit below it lowers it to the edit's record (`UPDMARK`): `d3099G` from line 100 takes it from 48 to 6. |
| source read pointer | the next `TEST.TXT` record `FILLBUF` will read (FCB 005CH, WM's word at +22H) |
| `BAKPOS` | depth of the `VIBACKUP.$$$` stack |
| `SRCREC` | the record of the edit furthest down the file, biased by 8000H (an `x` in record 499 makes it 81F3H; an edit higher up leaves it alone). A record leaving the bottom after it is still the source's own. |
| `BAKREC` | the same for records already on the `VIBACKUP.$$$` stack |
| `TOPLF` | line feeds above the window, so the cursor's line is known without reading the disk |
| `PGTOPM` | times the window's top has moved; undo refuses a change made before the last move |

## 2. The four edge moves

Paging is four moves, two at each edge of the window. Every scenario below is
some sequence of these, and each one's rule is confirmed by a measurement.

| Edge | Move | Routine | What it costs |
|---|---|---|---|
| top | text **leaves** (scrolling forward, or an insert needs room) | `SPILL` → `PAGEOUT` | a **write** to `TEST.$$$`, unless the record is below `OUTREC` (already there, so nothing is written). Confirmed by 3.2: the first `G` writes 607 records and the second `G` writes none. |
| top | text **comes back** (scrolling back) | `REWIND` | a **read** from `TEST.$$$`, backward (`RDPREV`), always |
| bottom | text **comes in** (scrolling forward) | `FILLBUF` / `RDIN` | a **read**, from the `VIBACKUP.$$$` stack first, then from the source |
| bottom | text **leaves** (scrolling back, or room needed at the bottom) | `SPILLB` → `PAGEBOT` | **nothing** if the record lies after every edit: the source's read pointer just steps back one (`RECDEC`). Otherwise it is **written** to `VIBACKUP.$$$`. Confirmed by 3.6 (none written), 3.5 (all 480 written), 3.7 (7 handed back, then 185 written) and 3.8 (two edits: 12 handed back, then 340 written). |

Why "after every edit" decides the bottom: `PAGEBOT` cuts records off the
window counting back from `TXTEND`, and `TXTEND` sits on a source record
boundary. Below the last edit, every 128-byte block is therefore exactly a
source record in its original place. At and above an edit, the blocks are
shifted by whatever the edit added or removed, and the source no longer holds
them anywhere.

**When the pager runs** (from the code; `G`, `gg`, `{n}G`, `d{motion}`, `dd`,
`:r`, `:w` and the renderer's page-back are among the measurements below):

* in a count loop that runs off the window's edge: `G`, `gg`, `{n}G`, counted
  `j`/`k`, `dd`, `d{motion}`, a search (`PAGESTP` after each `GOLINE` or
  delete step)
* when an insert finds the arena full (`MKGAP` → `MKROOM`)
* on a read past `TXTEND` (`NEEDIN`)
* when the renderer needs lines above `TXTBEG` (`PAGEWIN`)
* on a save (`SAVCLO`), and again on the page-back to the cursor after `:w`
  (`SEEKTO`, which is VI's code, not WordMaster's)

**Batch sizes, measured:**

* **Reads** fill the free space. On a first sweep the window fills to about
  20 K before anything is written out (3.2). A move that stays inside that,
  such as `2000G` from the top (3.8), reads 112 records and writes none.
* **`PAGEOUT` writes** come in batches that grow each time `SPILL` runs:
  48, 96 and 144 records, then as much as the window holds. The limit is
  computed from `SPLCNT`, a count of `SPILL` calls that is never reset during
  a session (WM 4398). When the records are already on disk, a batch moves
  only 16 (`IOBATCH`).
* **`PAGEBOT` writes** come in batches of 32.

The growing write batch is why the first forward sweep through a file empties
the window. In 3.2, the window fell to 256 bytes several times during
`G`, and ended with 4 K. A sweep that writes nothing keeps it at 18 K.

---

## 3. Scenarios

Each table shows the disk calls a key made and the state after it. "Window"
is the text in RAM; "valid" is `OUTREC`; "src" is the source's read pointer;
"stack" is the `VIBACKUP.$$$` depth. The window is in bytes; every other
count is in records.

### 3.1 A file that fits: 10 K, `G` `gg` `x` `:w`

Measured by `pagerprobe.py small`.

| Key | s | Disk | Window after |
|---|---|---|---|
| (open) | | 16 r source | 2,048 |
| `G` | 1.9 | 65 r source | 10,240: the whole file |
| `gg` | 1.3 | none | 10,240 |
| `x` | 0.1 | none | 10,239 |
| `:w` | 9.9 | 80 w `TEST.$$$`, rename, then 16 r source | 2,048 |

Nothing pages: the whole file reads into memory on the way down, and nothing
is written until the save. The save writes all 80 records to `TEST.$$$`,
renames `TEST.TXT` to `TEST.BAK` and `TEST.$$$` to `TEST.TXT`, then re-opens
the file and reads the first 2 K back, as an open does. A file that fits is
the case in which nothing has paged out. It runs the same code.

### 3.2 80 K, unchanged: `G` `gg` `G` `:q!`

Measured by `pagerprobe.py browse`.

| Key | s | Disk | Window after | `TEST.$$$` valid | src | stack |
|---|---|---|---|---|---|---|
| (open) | | 16 r source | 2,048 | 0 | 16 | 0 |
| `G` | 36.9 | 625 r source, **607 w** `TEST.$$$` | 4,224 (the last 33 records) | 607 | 640 (end) | 0 |
| `gg` | 28.2 | 607 r `TEST.$$$` | 20,480 (the first 160 records) | 607 | 160 | 0 |
| `G` | 25.6 | 481 r source, **0 w** | 18,432 | 607 | 640 | 0 |
| `:q!` | 4.1 | delete `TEST.$$$`, delete `VIBACKUP.$$$` | | | | |

* **`G`** is `MVLMAX`: a forward line move with count FFFFH. Each pass of
  `MVLLOOP` does three things. `GOLINE` counts line feeds to `TXTEND`.
  `SCRLST` puts the cursor there, so all the resident text is behind it and
  free to leave. `PAGESTP` → `FILLBUF` then reads more. Every record leaving
  the top is written, because `OUTREC` starts at 0. `TOPLF` ends at 9,712
  line feeds above the window.
* **`gg`** gets the cursor's line from `TOPLF` with no disk read, and moves
  10,239 lines back with the same loop. `REWIND` reads `TEST.$$$` backward.
  Every record leaving the bottom is unchanged, so `PAGEBOT` hands it back
  by stepping the source's pointer back: 480 records go back without a
  transfer. Records 160–639 are now unread input again.
* **The second `G`** reads the source from record 160, and the records
  leaving the top are all below `OUTREC`, so none is written. It is 11 s
  faster, and the window stays full.
* **`:q!`** deletes both work files.

**Why an unchanged file is written out.** Text above the window exists only
in `TEST.$$$` (section 1), so text leaving the top has to be written
somewhere. Writing it as the new file makes a later save cheap: 3.4 saves
after this exact sequence and writes only 33 records. The rule WordMaster
keeps is that a valid record is written **once**, not that unchanged text is
never written. The cost lands on someone only reading a big file: 77 K
written that `:q!` throws away, and about a file's worth of free disk space
needed for it.

### 3.3 80 K, moving near the cursor: `6000G` `6100G` `5900G` `^F` `^B` `100G`

Measured by `pagerprobe.py local`.

| Key | s | Disk | Window after | line |
|---|---|---|---|---|
| `6000G` | 20.3 | 368 r source, 288 w `TEST.$$$` | 12,288 (records 288–383) | 6000 |
| `6100G` | 0.8 | none | 12,288 | 6100 |
| `5900G` | 0.9 | none | 12,288 | 5900 |
| `^F` | 0.4 | none | 12,288 | 5910 |
| `^B` | 0.5 | none | 12,288 | 5911 |
| `100G` | 14.6 | 288 r `TEST.$$$` | 20,480 (records 0–159) | 100 |

Inside the window nothing touches the disk. Moving back costs reads only: the
records leaving the bottom are unchanged, so they go back to the source
without a transfer.

### 3.4 80 K, saving with no edits: `:w` from the top, and `G` `gg` `:w`

Measured by `pagerprobe.py savenone saveback`.

| Sequence | `:w` s | `:w` disk |
|---|---|---|
| `:w` straight after opening | 41.6 | 641 r source, **640 w** `TEST.$$$` |
| `G` `gg` `:w` | 21.3 | 497 r source, **33 w** `TEST.$$$` |

A save is `SAVCLO`. It flushes the window to `TEST.$$$`, refills it from the
input side, and repeats to the end, then renames. Straight after opening,
nothing is in `TEST.$$$` yet, so the save writes the whole file (in batches of
173, the whole window at a time). After `G` `gg`, records 0–606 are already
valid. The save still reads the source through to the end, but writes only
records 607–639.

Both saves leave `TEST.TXT` byte-identical to the original, plus a
`TEST.BAK`. VI does not skip the save when nothing has changed.

### 3.5 80 K, an edit at the end: `G` `x` `gg` `G` `:w`

Measured by `pagerprobe.py endedit`.

| Key | s | Disk | Window after | src | stack |
|---|---|---|---|---|---|
| `G` | 36.9 | 625 r source, 607 w `TEST.$$$` | 4,224 | 640 | 0 |
| `x` | 0.0 | none | 4,223 | 640 | 0 |
| `gg` | 38.9 | 607 r `TEST.$$$`, **480 w `VIBACKUP.$$$`** | 20,479 | 640 | 480 |
| `G` | 25.1 | **480 r `VIBACKUP.$$$`**, 0 w | 18,431 | 640 | 0 |
| `:w` | 42.4 | 640 r source, 591 w `TEST.$$$` | 10,495 | | |

* **`x`** on the last line sets `SRCREC` to that record (827FH: record 639).
* **`gg`:** every record that leaves the bottom is above the edit, shifted
  one byte against the source, so none can be handed back. All 480 are
  written to `VIBACKUP.$$$` in batches of 32. The source's pointer stays at
  its end. This is the same move as 3.2's `gg`, and the edit costs it 11 s of
  writes.
* **`G` again** takes its input from the stack, all 480 records, and writes
  nothing to `TEST.$$$`, because records 160–606 are still valid there.
* **`:w`** writes the last 33 records, then renames. Then VI's own `SEEKTO`
  pages the saved file back in up to the cursor, which is on the last line.
  That re-reads all 640 records and writes 558 of them to a new `TEST.$$$`. So
  `:w` at the end of a big file costs a second full pass: 42.4 s here,
  against 21.3 s for the same save with the cursor on line 1 (3.4).

### 3.6 80 K, an edit at the top: `x` `G` `gg` `:w`

Measured by `pagerprobe.py topedit`.

| Key | s | Disk | Window after | src | stack |
|---|---|---|---|---|---|
| `x` | 0.1 | none | 2,047 | 16 | 0 |
| `G` | 36.9 | 625 r source, 606 w `TEST.$$$` | 4,351 | 640 | 0 |
| `gg` | 28.2 | 606 r `TEST.$$$`, **0 w** | 20,479 | 160 | 0 |
| `:w` | 21.3 | 497 r source, 34 w `TEST.$$$` | 2,048 | | |

The edit is in record 0, so every record that leaves the bottom on `gg` lies
after it. They all line up with the source and go back without a transfer.
An edit near the top costs nothing extra, where the same `x` at the end (3.5)
cost 480 writes. Where an edit is, not whether there is one, decides what
scrolling back past it costs.

### 3.7 80 K, an insert in the middle: `5000G` `ihello<Esc>` `gg` `G` `:w`

Measured by `pagerprobe.py midedit`.

| Key | s | Disk | Window after | valid | src | stack |
|---|---|---|---|---|---|---|
| `5000G` | 19.1 | 304 r source, 288 w `TEST.$$$` | 4,096 | 288 | 320 | 0 |
| `ihello` `<Esc>` | 0.3 | none | 4,101 | 288 | 320 | 0 |
| `gg` | 18.2 | 288 r `TEST.$$$`, **185 w `VIBACKUP.$$$`** | 16,389 | 288 | 313 | 185 |
| `G` | 31.4 | 185 r `VIBACKUP.$$$`, 328 r source, **240 w `TEST.$$$`** | 14,341 | 528 | 640 | 0 |
| `:w` | 44.8 | 641 r source, 671 w `TEST.$$$` | 10,501 | | | |

* **The insert** is in record 312 (line 5000), so `SRCREC` = 8138H.
* **`gg`:** the first 7 records to leave the bottom (313–319) lie after the
  insert and go back to the source, whose pointer steps from 320 to 313.
  Every record from the insert upward is shifted 5 bytes and goes to
  `VIBACKUP.$$$`: 185 of them.
* **`G`** reads those 185 back off the stack, then the source from record
  313. `TEST.$$$` was valid only to record 288, the window's top when the
  insert was made, so every record from there on is written again: 240.
* **`:w`** writes the rest, then `SEEKTO` re-reads and re-writes the file up
  to the cursor on the last line, as in 3.5.

### 3.8 80 K, two edits: `2000G` `x` `8000G` `x` `gg` `G` `:w`

Measured by `pagerprobe.py twoedit`.

| Key | s | Disk | Window after | valid | src | stack |
|---|---|---|---|---|---|---|
| `2000G` | 2.7 | 112 r source | 16,384 | 0 | 128 | 0 |
| `x` | 0.0 | none | 16,383 | 0 | 128 | 0 |
| `8000G` | 25.5 | 384 r source, 446 w `TEST.$$$` | 8,447 | 446 | 512 | 0 |
| `x` | 0.0 | none | 8,446 | 446 | 512 | 0 |
| `gg` | 33.4 | 446 r `TEST.$$$`, **340 w `VIBACKUP.$$$`** | 20,478 | 446 | 500 | 340 |
| `G` | 31.0 | 340 r `VIBACKUP.$$$`, 141 r source, 144 w `TEST.$$$` | 6,398 | 590 | 640 | 0 |
| `:w` | 41.6 | 640 r source, 608 w `TEST.$$$` | 10,494 | | | |

* **The first `x`** (record 124) sets `SRCREC` to 807CH. **The second**
  (record 499) raises it to 81F3H. The mark follows the edit furthest down
  the file.
* **`gg`:** only the 12 records after the second edit (500–511) go back to
  the source. Every record above it that leaves the window, the 340 from
  record 499 up to record 160, goes to `VIBACKUP.$$$`. They are shifted one
  byte by the second `x`, however far they are from it.
* **The rule, as measured:** once the window scrolls back past the edit
  furthest down the file, every record that leaves its bottom is written to
  `VIBACKUP.$$$`. Edits higher up change nothing about that.

### 3.9 80 K, a delete bigger than memory: `100G` `d3099G` `:w`

Measured by `pagerprobe.py bigdel`.

| Key | s | Disk | Window after |
|---|---|---|---|
| `100G` | 0.5 | none | 2,048 |
| `d3099G` | 12.5 | 240 r source, 48 w + 48 r `TEST.$$$` | 2,624 |
| `:w` | 30.1 | 449 r source, 447 w `TEST.$$$` | 2,048 |

The saved file is 57,920 bytes: 3,000 lines (24 K) gone, exactly. `d3099G`
first runs the motion forward to line 3099, which writes 48 records off the
top, and comes back (48 read). Then it deletes forward from the cursor, and
`DELTO`'s `PAGESTP` reads the source in as the gap swallows it. The deleted
text is read once. The only part of it ever written is what the motion's own
48 records held (lines 100 to 768), and that is never saved.

### 3.10 80 K, a `dd` the register cannot hold: `100G` `3000dd` `:w`

Measured by `pagerprobe.py bigdd`.

| Key | s | Disk | Window after | message |
|---|---|---|---|---|
| `3000dd` | 20.2 | 158 r source, 156 w + 156 r `TEST.$$$`, 18 w `VIBACKUP.$$$` | 18,176 | Too large to yank |
| `:w` | 36.1 | 497 r source, 18 r `VIBACKUP.$$$`, 484 w `TEST.$$$` | 2,048 | |

`dd` keeps its lines in the yank register, and 24 K does not fit, so it is
refused (`QFIT`/`QREFUS`, VI's code, documented in `COMMANDS.md`). The text is
unchanged and the save matches the original. The refusal is not free,
though. `QPUTLN` takes the lines pass by pass and `QREFUS` puts them back, so
the window paged forward and back. It wrote 156 records to `TEST.$$$` and 18
to `VIBACKUP.$$$`, all for a command that changed nothing. `d3099G` (3.9)
takes the same lines for less, because it keeps nothing.

### 3.11 80 K, an insert bigger than memory: `6000G` `:6000,9000w T.TXT` `100G` `:r T.TXT` `:w`

Measured by `pagerprobe.py bigput`.

| Key | s | Disk | Window after | valid | src | stack |
|---|---|---|---|---|---|---|
| `6000G` | 20.3 | 368 r source, 288 w `TEST.$$$` | 12,288 | 288 | 384 | 0 |
| `:6000,9000w T.TXT` | 29.4 | 188 w `T.TXT`; 192 r source, 80 r + 158 w `TEST.$$$` | 20,736 | 446 | 528 | 0 |
| `100G` | 18.0 | 366 r `TEST.$$$` | 20,480 | 446 | 160 | 0 |
| `:r T.TXT` | 28.2 | 188 r `T.TXT`; 186 r + 180 w `TEST.$$$`, 55 w `VIBACKUP.$$$` | 17,864 | 186 | 7 | 55 |
| `:w` | 45.7 | 650 r source, 55 r `VIBACKUP.$$$`, 642 w `TEST.$$$` | 2,048 | | | |

The saved file is 105,928 bytes, with lines 6000–9000 after line 100,
exactly.

* **`:r`** inserts 24 K into a window that holds 22 K. It reads `T.TXT` 17
  records at a time into the gap, and each time the arena fills, `MKROOM`
  spills the top (the inserted text, already behind the cursor) to
  `TEST.$$$`. The insert streams through memory into the work file.
* Afterwards the cursor must go back to the first line put (line 101), so the
  window pages back 186 records. The first text pushed out of the bottom is
  the text after the insert, which is unchanged: 153 records go back to the
  source (its pointer falls to 7). Then comes the end of the inserted text,
  which the window can no longer hold. It is not in the source at all, so
  those 55 records go to `VIBACKUP.$$$`.

### 3.12 Undo after paging: `G` `x` `gg` `G` `u`

Measured by `pagerprobe.py undo`.

`u` answers "Cannot undo: change has paged out" and changes nothing. The `x`
was made with `PGTOPM` at 607, and `gg` `G` moved the window's top 1,103 more
times. An undo offset is measured from `TXTBEG`, so once the top has moved it
no longer names the right byte, and undo refuses rather than guess.

---

## 4. Where the time and the disk go

These are the measured facts above, collected. Each one says whether the
code involved is WordMaster's or VI's own, since that decides how much risk
a change carries.

| What | Measured | Whose code |
|---|---|---|
| A transfer, at the simulator's floor | about 0.045 s per record read and scanned for lines; about 0.022 s per record written | WM |
| The first pass over a file writes every record that leaves the top, changed or not | `G`: 607 writes (77 K, about 13 s of 37 s) that `:q!` deletes (3.2) | WM (`PAGEOUT`, `OUTREC`) |
| `:w` pages the saved file back to the cursor, rewriting a new `TEST.$$$` up to it | `:w` on the last line: 42.4 s against 21.3 s on line 1; 558 extra writes (3.5) | **VI** (`SEEKTO`) |
| Scrolling back past an edit writes everything above the edit to `VIBACKUP.$$$` | `x` on the last line, then `gg`: 480 writes, +11 s (3.5); two edits: 340 (3.8) | WM (`PAGEBOT`, `SRCREC`) |
| An edit makes `TEST.$$$` invalid from the edit's record on | 3.7: the next `G` rewrites 240 records; 3.9: `OUTREC` falls from 48 to 6 | WM (`UPDMARK`, `OUTREC`) |
| A refused `dd` still pages forward and back | `3000dd`: 20 s, 174 writes, nothing changed (3.10) | **VI** (`QPUTLN`/`QREFUS` on WM's Q-buffer) |
| The growing `SPILL` batch empties the window on a first forward sweep | the window falls to 128–256 bytes between batches; 4 K left after `G` | WM (`SPILL`, `SPLCNT`) |
| `:w` with no edits still saves | 41.6 s from the top, plus a `.BAK` (3.4) | **VI** (no modified check before the save) |
| A real drive adds seeks | the pager alternates between source and `TEST.$$$` (or `VIBACKUP.$$$`) every batch; the simulator does not price that | WM (batch sizes) |

## 5. Measuring again

```
python3 pagerprobe.py --list          # the scenarios
python3 pagerprobe.py browse midedit  # some of them
python3 pagerprobe.py browse --trace  # every disk call, in runs, with the window size
python3 pagerprobe.py browse --log=F.jsonl  # every disk call, timed, for pagermodel.py
```

`pagermodel.py` (issue #29) replays the logged calls, `pagertrace.jsonl.gz`,
onto an Altair 8" floppy and compares them with a piece table on the same
drive. Re-record the log whenever the figures here are re-measured.

Build first (`python3 build_vi.py VI`), and never run it beside a test
battery. Each scenario takes one to four minutes of wall time. Separate
invocations get separate sandboxes, so several can run at once. The figures
in this document change whenever the image size changes the arena. Re-run
the probe after such a change before quoting them.
