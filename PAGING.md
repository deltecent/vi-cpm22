# How the pager behaves

`BUFFER.md` describes the gap buffer and names the routines that page it. This
document shows what those routines **do** in a series of editing scenarios,
with and without edits. It covers which file each record goes to, how many
disk transfers each key costs, and what is left in memory afterwards.

Every figure was read out of the running editor by `pagerprobe.py`. The code
is cited to name what a measurement shows; the few statements that come from
the code alone say so. Every scenario that saves was checked: the
saved file matches, byte for byte, what its edits should have produced.

* **Build:** `VI.COM` of 74f46c0, 23,040 bytes, on the harness machine
  (`vi.toml`). It has `PAGE.MAC` deviation 8 (`SAMREC`, section 1) and the
  jump back to the file's start (section 2). Section 5 compares a2abca7, the
  first build with deviation 8, with aabc816, which had WordMaster's pager
  unchanged; section 6 compares 924a8ff, the jump's build, with a2abca7. The
  pager has not changed since 924a8ff; the arena is 192 bytes smaller, which
  moves the window's edges by a record or two in places.
* **Memory:** the arena is 21,551 bytes (`61D6H`–`B605H`), and the first
  command claims 1 K of it for undo, so about 20 K holds text.
* **Test file:** `TEST.TXT`, 81,920 bytes, which is 640 records of 128 bytes.
  It has 10,240 lines of 8 bytes (`000001` CR LF ...). Line *n* starts at byte
  8(*n*−1), and record *r* holds lines 16*r*+1 to 16*r*+16.
* **Seconds:** the simulator's 2 MHz clock, less what finding the guest idle
  costs. The simulated drive has no seek or rotation time, so every figure is
  a floor. A real drive adds head movement to every transfer, and most of all
  when the pager alternates between two files.
* **Disk calls:** counted by a conditional breakpoint on the BDOS entry
  (0005H), so the editor runs unmodified. "r" is a record read and "w" a
  record write. "source" is `TEST.TXT` read forward through the FCB at 005CH;
  "source front" is `TEST.TXT` read through `SRCFCB`, the second FCB that
  reads the unchanged front back (section 1).

---

## 1. Where the text is

At any moment every byte of the file is in exactly one of these places:

```
          above the window               the window (RAM)               below the window
  ┌────────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
  │ records 0..SAMREC-1:       │  │ TXTBEG .. [gap] .. TXTEND │  │ VIBACKUP.$$$ (a stack),   │
  │   still TEST.TXT's own     │  │ 21 K at most              │  │ then the unread rest of   │
  │   (read back via SRCFCB)   │  │                           │  │ TEST.TXT                  │
  │ records SAMREC..OUTPOS-1:  │  │                           │  │                           │
  │   TEST.$$$  (OUTFCB)       │  │                           │  │                           │
  └────────────────────────────┘  └───────────────────────────┘  └───────────────────────────┘
       REWIND reads ◀── top edge                bottom edge ──▶ FILLBUF reads
       PAGEOUT writes ──▶                                  ◀── PAGEBOT pushes back
```

* **Above the window, the text is in the source or in `TEST.$$$`.** The
  records at the front of the file that no edit has touched are still the
  source's own, at the same record numbers, and the pager reads them back
  from `TEST.TXT`. Every record from the first edit on is in `TEST.$$$`.
  `TEST.$$$` is not a scratch copy. It is the new file, written at its own
  record numbers, and a save first copies the unchanged front into it, then
  renames it over `TEST.TXT`.
* **Below the window is input that has not been read yet.** That is the rest
  of the source from its read pointer on, with `VIBACKUP.$$$` in front of it
  holding records the pager pushed back down. `VIBACKUP.$$$` is a stack: the
  record pushed last is the next one read.

WordMaster kept everything above the window in `TEST.$$$`, so it wrote every
record that left the top, changed or not. `SAMREC` is VI's own
(`PAGE.MAC` deviation 8); section 5 measures what it changed.

The marks the pager keeps, and what they mean in the measurements:

| Mark | Meaning |
|---|---|
| `OUTPOS` | `TEST.$$$` record number of `TXTBEG`; the records above the window |
| `SAMREC` | how many records at the front of the file are still the source's own. FFFFH ("all of them") at every open; an edit lowers it to the edit's record (`UPDMARK`): an `x` on line 1 makes it 0, `ihello` on line 5000 makes it 312. A record leaving the top below it is not written. |
| `OUTREC` | how many records at the front are valid, in `TEST.$$$` or (below `SAMREC`) in the source. A record leaving the top below this is not written again. An edit below it lowers it to the edit's record (`UPDMARK`): `d3099G` from line 100 takes it to 6. |
| source read pointer | the next `TEST.TXT` record `FILLBUF` will read (FCB 005CH, WM's word at +22H) |
| `BAKPOS` | depth of the `VIBACKUP.$$$` stack |
| `SRCREC` | the record of the edit furthest down the file, biased by 8000H (an `x` in record 499 makes it 81F3H; an edit higher up leaves it alone). A record leaving the bottom after it is still the source's own. |
| `BAKREC` | the same for records already on the `VIBACKUP.$$$` stack |
| `TOPLF` | line feeds above the window, so the cursor's line is known without reading the disk |
| `PGTOPM` | times the window's top has moved; undo refuses a change made before the last move |

The five routines that change text (`PUTGAP`, `SETGAPB`, `DELTO`, `QCOPY`,
`INSBLK`) each call `UPDMARK` at the first byte they change, so no command
can change a record without lowering `SAMREC` past it (`DESIGN.md`).

## 2. The four edge moves

Paging is four moves, two at each edge of the window. Every scenario below is
some sequence of these, and each one's rule is confirmed by a measurement.

| Edge | Move | Routine | What it costs |
|---|---|---|---|
| top | text **leaves** (scrolling forward, or an insert needs room) | `SPILL` → `PAGEOUT` | **nothing** if the record is below `SAMREC` (the source still holds it) or below `OUTREC` (`TEST.$$$` already holds it). Otherwise a **write** to `TEST.$$$`. Confirmed by 3.2 (`G` on an unchanged file writes none), 3.6 (an `x` on line 1: 586 written) and 3.7 (`ihello` on line 5000: only the records from 312 on are written). |
| top | text **comes back** (scrolling back) | `REWIND` | a **read**, backward: from the source through `SRCFCB` below `SAMREC`, from `TEST.$$$` above it. Confirmed by 3.5 (587 from the source) and 3.8 (318 from `TEST.$$$`, then 124 from the source). |
| top | a **far move up** on a file not changed since it was opened or written | `PGJUMP` | **16 reads**, from the source's start: the window is dropped and filled again as an open fills it, and the move goes on forward. VI's own (#34 part B). Confirmed by 3.2 (`gg`: 1.5 s where paging back took 27.1), 3.3 and 3.11 (`100G`). |
| bottom | text **comes in** (scrolling forward) | `FILLBUF` / `RDIN` | a **read**, from the `VIBACKUP.$$$` stack first, then from the source |
| bottom | text **leaves** (scrolling back, or room needed at the bottom) | `SPILLB` → `PAGEBOT` | **nothing** if the record lies after every edit: the source's read pointer just steps back one (`RECDEC`). Otherwise it is **written** to `VIBACKUP.$$$`. Confirmed by 3.6 (none written), 3.5 (all 512 written), 3.7 (3 handed back, then 189 written) and 3.8 (two edits: 8 handed back, then 376 written). |

The two edges mirror each other. A record at the top that lies **before**
every edit is still the source's, in its own place, so it need not be
written; a record at the bottom that lies **after** every edit is the
source's too, so it is handed back. `PAGEBOT` cuts records off the window
counting back from `TXTEND`, and `TXTEND` sits on a source record boundary,
so below the last edit every 128-byte block is exactly a source record. At
the top, `TXTBEG` is record `OUTPOS` of the new file, and above the first edit
the new file and the source are the same bytes. Between the first and the
last edit the blocks are shifted by whatever the edits added or removed, and
the source no longer holds them anywhere.

The jump needs `SAMREC` at FFFFH: then no record holds a change, nothing is
in `TEST.$$$`, and the stack holds only text the source holds too, so the
window can be thrown away. `GOLN` (`{n}G`, `{n}gg`, `d{n}G`, `:N`) jumps
when the line wanted is less than half as far down as the window's top
(`TOPLF`), and `MKPAGE` (a mark, a search landing, the way back from an ESC
or from an operator's motion) when its record is less than half of
`OUTPOS`. The yank register and the undo region are left alone (no `BINIT`).
Afterwards the window holds what an open reads, 2 K, and fills as keys need
more.

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
  20 K before anything leaves the top (3.2). A move that stays inside that,
  such as `2000G` from the top (3.8), reads 112 records and writes none.
* **`PAGEOUT`** moves records in batches that grow each time `SPILL` runs:
  48, 96 and 144 records, then as much as the window holds. The limit is
  computed from `SPLCNT`, a count of `SPILL` calls that is never reset during
  a session (WM 4398). A record skipped because it is below `OUTREC` uses up
  the batch faster, so a batch of those moves only 16 (`IOBATCH`). A record
  skipped because it is below `SAMREC` counts as the write WordMaster would
  have made, so the batches, and with them `PGTOPM` and the window's size
  after each key, are exactly WordMaster's.
* **`PAGEBOT` writes** come in batches of 32.
* **The save's front copy** (`SVFRNT`) goes through the free RAM above the
  text, as many records as fit at a time: read a batch from the source, write
  it to `TEST.$$$`. One record at a time, alternating, the BIOS's
  deblocking makes each call about ten times dearer.

The growing batch is why the first forward sweep through a file empties
the window: after 3.2's first `G` it holds under 7 K. A sweep over records that are
already valid moves only 16 at a time and keeps the window at 18 K (3.5's
second `G`).

---

## 3. Scenarios

Each table shows the disk calls a key made and the state after it. "Window"
is the text in RAM; "valid" is `OUTREC`; "same" is `SAMREC` ("all" for
FFFFH); "src" is the source's read pointer; "stack" is the `VIBACKUP.$$$`
depth. The window is in bytes; every other count is in records.

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
is written until the save. The `x` makes `SAMREC` 0, so the save has no
front to copy. It writes all 80 records to `TEST.$$$`,
renames `TEST.TXT` to `TEST.BAK` and `TEST.$$$` to `TEST.TXT`, then re-opens
the file and reads the first 2 K back, as an open does. A file that fits is
the case in which nothing has paged out. It runs the same code.

### 3.2 80 K, unchanged: `G` `gg` `G` `:q!`

Measured by `pagerprobe.py browse`.

| Key | s | Disk | Window after | valid | same | src | stack |
|---|---|---|---|---|---|---|---|
| (open) | | 16 r source | 2,048 | 0 | all | 16 | 0 |
| `G` | 17.8 | 625 r source, **0 w** | 6,784 (the last 53 records) | 587 | all | 640 (end) | 0 |
| `gg` | 1.5 | **16 r source** | 2,048 (the first 16 records) | 0 | all | 16 | 0 |
| `G` | 17.6 | 625 r source, 0 w | 12,928 | 539 | all | 640 | 0 |
| `:q!` | 2.0 | none | | | | | |

* **`G`** is `MVLMAX`: a forward line move with count FFFFH. Each pass of
  `MVLLOOP` does three things. `GOLINE` counts line feeds to `TXTEND`.
  `SCRLST` puts the cursor there, so all the resident text is behind it and
  free to leave. `PAGESTP` → `FILLBUF` then reads more. Nothing has been
  edited, so `SAMREC` is FFFFH and no record leaving the top is written.
  `OUTREC` still rises to 587, the records now valid above the window.
* **`gg`** gets the cursor's line from `TOPLF` with no disk read. Line 1 is
  less than half as far down as the window's top, and nothing has changed,
  so `PGJUMP` drops the window, puts the source's pointer back at record 0
  and reads the first 16 records, as the open did. Until #34 part B this
  `gg` paged back through `REWIND`: 607 records read back from the source
  and 480 handed back at the bottom, 27.1 s (section 6).
* **The second `G`** is the first one again: the marks are all at zero, so
  it reads the whole source forward, with the same growing batches.
* **`:q!`** has nothing to delete: no work file was ever made (`WRKMAD`
  clear, `DISCRD`).

Browsing a big file writes nothing, and needs no free disk space.

### 3.3 80 K, moving near the cursor: `6000G` `6100G` `5900G` `^F` `^B` `100G`

Measured by `pagerprobe.py local`.

| Key | s | Disk | Window after | line |
|---|---|---|---|---|
| `6000G` | 10.0 | 364 r source | 11,776 (records 288–379) | 6000 |
| `6100G` | 1.9 | 16 r source | 13,824 | 6100 |
| `5900G` | 0.8 | none | 13,824 | 5900 |
| `^F` | 0.4 | none | 13,824 | 5910 |
| `^B` | 0.5 | none | 13,824 | 5911 |
| `100G` | 1.7 | 16 r source | 2,048 (records 0–15) | 100 |

Inside the window nothing touches the disk. `6100G` reads 16 records because
the window ends short of line 6100 after `6000G` (the window's edges move
with the arena's size). `100G` is the jump: line 100 is less than half as far
down as the window's top at 288 records, so the file is read again from its
start, where paging back took 14.3 s.

### 3.4 80 K, saving with no edits: `:w` from the top, and `G` `gg` `:w`

Measured by `pagerprobe.py savenone saveback`.

| Sequence | `:w` s | `:w` disk |
|---|---|---|
| `:w` straight after opening | 42.4 | 641 r source, **640 w** `TEST.$$$` |
| `G` `gg` `:w` | 42.3 | 641 r source, **640 w** `TEST.$$$` |

A save is `SAVCLO`. It flushes the window to `TEST.$$$`, refills it from the
input side, and repeats to the end, then renames. Nothing above the window
has been written in either case, so both saves write the whole file. After
`G` `gg` the window holds what an open reads (`gg` jumped), so the two saves
are the same. `OUTPOS` is 0 when both saves begin, so the front copy has nothing
to do (`SVBEG` counts min(`SAMREC`, `OUTPOS`)): every record goes out from
RAM.

Both saves leave `TEST.TXT` byte-identical to the original, plus a
`TEST.BAK`. VI does not skip the save when nothing has changed.

### 3.5 80 K, an edit at the end: `G` `x` `gg` `G` `:w`

Measured by `pagerprobe.py endedit`.

| Key | s | Disk | Window after | valid | same | src | stack |
|---|---|---|---|---|---|---|---|
| `G` | 17.8 | 625 r source, 0 w | 6,784 | 587 | all | 640 | 0 |
| `x` | 0.0 | none | 6,783 | 587 | 639 | 640 | 0 |
| `gg` | 42.2 | 587 r source front, **512 w `VIBACKUP.$$$`** | 16,383 | 587 | 639 | 640 | 512 |
| `G` | 21.7 | **512 r `VIBACKUP.$$$`**, 0 w | 18,431 | 587 | 639 | 640 | 0 |
| `:w` | 56.0 | 496 r source front + 640 w `TEST.$$$`; then 640 r source | 15,871 | | | | |

* **`x`** on the last line sets `SRCREC` to that record (827FH: record 639)
  and lowers `SAMREC` to 639.
* **`gg`:** the edit stops the jump (3.2), so this `gg` pages back. The
  records above the window are all before the edit, so they come back from
  the source. Every record that leaves the bottom is above the edit, shifted
  one byte against the source, so none can be handed back. All 512 are
  written to `VIBACKUP.$$$` in batches of 32. The source's pointer stays at
  its end. One byte changed makes this `gg` 42.2 s where 3.2's takes 1.5.
* **`G` again** takes its input from the stack, all 512 records, and writes
  nothing to `TEST.$$$`: the records leaving the top are before the edit.
* **`:w`** has the window at records 496–639 and nothing in `TEST.$$$`. The
  first `FLUSHTX` writes the window's text, then the front copy reads
  records 0–495 from the source and writes them (`SVBEG`/`SVFRNT`), then the
  file is renamed. VI's own `SEEKTO` then pages the saved file back in up to
  the cursor on the last line: 640 reads. The re-opened file is all
  unchanged, so that pass writes nothing.

### 3.6 80 K, an edit at the top: `x` `G` `gg` `:w`

Measured by `pagerprobe.py topedit`.

| Key | s | Disk | Window after | valid | same | src | stack |
|---|---|---|---|---|---|---|---|
| `x` | 0.1 | none | 2,047 | 0 | 0 | 16 | 0 |
| `G` | 37.5 | 625 r source, **586 w `TEST.$$$`** | 6,911 | 586 | 0 | 640 | 0 |
| `gg` | 24.5 | 586 r `TEST.$$$`, **0 w** | 18,431 | 586 | 0 | 144 | 0 |
| `:w` | 22.5 | 513 r source, 54 w `TEST.$$$` | 2,048 | | | | |

The edit is in record 0, so `SAMREC` is 0 and the pager behaves exactly as
WordMaster's: every record leaving the top is written, and `gg` reads them
back from `TEST.$$$`. Every record that leaves the bottom on `gg` lies after
the edit; they all line up with the source and go back without a transfer.
An edit near the top costs the writes at the top, and an edit near the end
(3.5) costs them at the bottom. Where an edit is, not whether there is one,
decides what moving past it costs.

### 3.7 80 K, an insert in the middle: `5000G` `ihello<Esc>` `gg` `G` `:w`

Measured by `pagerprobe.py midedit`.

| Key | s | Disk | Window after | valid | same | src | stack |
|---|---|---|---|---|---|---|---|
| `5000G` | 8.9 | 300 r source, 0 w | 3,584 | 288 | all | 316 | 0 |
| `ihello` `<Esc>` | 0.3 | none | 3,589 | 288 | 312 | 316 | 0 |
| `gg` | 18.7 | 288 r source front, **189 w `VIBACKUP.$$$`** | 15,877 | 288 | 312 | 313 | 189 |
| `G` | 31.6 | 189 r `VIBACKUP.$$$`, 328 r source, **216 w `TEST.$$$`** | 14,341 | 528 | 312 | 640 | 0 |
| `:w` | 41.5 | 312 r source front + 425 w `TEST.$$$`; then 641 r source | 15,877 | | | | |

* **The insert** is in record 312 (line 5000), so `SRCREC` = 8138H and
  `SAMREC` = 312.
* **`gg`:** the 288 records above the window are before the insert and come
  back from the source. The first 3 records to leave the bottom (313–315) lie
  after the insert and go back to the source, whose pointer steps from 316
  to 313. Every record from the insert upward is shifted 5 bytes and goes to
  `VIBACKUP.$$$`: 189 of them.
* **`G`** reads those 189 back off the stack, then the source from record
  313. Records 0–311 leave the top unwritten; every one from the insert's
  record 312 on is written: 216, records 312–527.
* **`:w`** writes the window and the rest of the file (113 records), copies
  records 0–311 from the source (312), and renames: 425 writes in all, one
  file's worth less the 216 already in `TEST.$$$`. `SEEKTO` then re-reads the
  saved file to the cursor on the last line, writing nothing.

### 3.8 80 K, two edits: `2000G` `x` `8000G` `x` `gg` `G` `:w`

Measured by `pagerprobe.py twoedit`.

| Key | s | Disk | Window after | valid | same | src | stack |
|---|---|---|---|---|---|---|---|
| `2000G` | 2.7 | 112 r source | 16,384 | 0 | all | 128 | 0 |
| `x` | 0.0 | none | 16,383 | 0 | 124 | 128 | 0 |
| `8000G` | 23.5 | 380 r source, 318 w `TEST.$$$` | 8,447 | 442 | 124 | 508 | 0 |
| `x` | 0.1 | none | 8,446 | 442 | 124 | 508 | 0 |
| `gg` | 34.0 | 318 r `TEST.$$$` + 124 r source front, **376 w `VIBACKUP.$$$`** | 15,870 | 442 | 124 | 500 | 376 |
| `G` | 28.8 | 376 r `VIBACKUP.$$$`, 141 r source, 144 w `TEST.$$$` | 6,910 | 586 | 124 | 640 | 0 |
| `:w` | 28.8 | 124 r source front + 178 w `TEST.$$$`; then 640 r source | 15,870 | | | | |

* **The first `x`** (record 124) sets `SRCREC` to 807CH and `SAMREC` to 124.
  **The second** (record 499) raises `SRCREC` to 81F3H and leaves `SAMREC`
  alone. `SAMREC` follows the edit nearest the top, `SRCREC` the one
  furthest down.
* **`8000G`** writes records 124–441 and not 0–123.
* **`gg`** reads back from `TEST.$$$` down to record 124, then from the
  source. Only the 8 records after the second edit (500–507) go back to the
  source at the bottom. Every record above it that leaves the window, the 376
  from record 499 up to record 124, goes to `VIBACKUP.$$$`. They are shifted
  one byte by the second `x`, however far they are from it.
* **The rule, as measured:** records before the first edit are never
  written above the window; once the window scrolls back past the edit
  furthest down the file, every record that leaves its bottom is written to
  `VIBACKUP.$$$`.

### 3.9 80 K, a delete bigger than memory: `100G` `d3099G` `:w`

Measured by `pagerprobe.py bigdel`.

| Key | s | Disk | Window after | valid | same |
|---|---|---|---|---|---|
| `100G` | 0.5 | none | 2,048 | 0 | all |
| `d3099G` | 9.8 | 396 r source | 2,624 | 0 | 6 |
| `:w` | 31.9 | 449 r source, 453 w `TEST.$$$` | 2,048 | | |

The saved file is 57,920 bytes: 3,000 lines (24 K) gone, exactly. `d3099G`
first runs the motion forward to line 3099, which moves 48 records off the
top without writing them, and comes back to line 100. Nothing has changed
yet, so it comes back by the jump: the window the motion read is dropped and
the file read again from its start (where `REWIND` read 48 records back).
Then it deletes forward from the cursor, and `DELTO`'s `PAGESTP` reads the
source in as the gap swallows it. The deleted text is never written. The
jump costs this one 0.7 s: the delete reads again the records the motion had
read (396 reads, 288 before).

### 3.10 80 K, a `dd` the register cannot hold: `100G` `3000dd` `:w`

Measured by `pagerprobe.py bigdd`.

| Key | s | Disk | Window after | message |
|---|---|---|---|---|
| `3000dd` | 17.7 | 140 r source + 6 r source front, 130 w + 130 r `TEST.$$$`, 20 w `VIBACKUP.$$$` | 15,872 | Too large to yank |
| `:w` | 37.9 | 513 r source + 20 r `VIBACKUP.$$$`, 510 w `TEST.$$$` | 2,048 | |

`dd` keeps its lines in the yank register, and 24 K does not fit, so it is
refused (`QFIT`/`QREFUS`, VI's code, documented in `COMMANDS.md`). The text is
unchanged and the save matches the original. The refusal is not free,
though. `QPUTLN` takes the lines pass by pass and `QREFUS` puts them back, so
the window paged forward and back, and the take and the put-back are edits
as far as the marks know: `SAMREC` falls to 6, and the 130 records from there
that left the top were written, and 20 that left the bottom. `d3099G` (3.9) takes the same lines for less,
because it keeps nothing.

### 3.11 80 K, an insert bigger than memory: `6000G` `:6000,9000w T.TXT` `100G` `:r T.TXT` `:w`

Measured by `pagerprobe.py bigput`.

| Key | s | Disk | Window after | valid | same | src | stack |
|---|---|---|---|---|---|---|---|
| `6000G` | 10.0 | 364 r source | 11,776 | 288 | all | 380 | 0 |
| `:6000,9000w T.TXT` | 26.3 | 188 w `T.TXT`; 192 r source, 80 r source front | 18,688 | 442 | all | 508 | 0 |
| `100G` | 1.5 | 16 r source | 2,048 | 0 | all | 16 | 0 |
| `:r T.TXT` | 20.5 | 188 r `T.TXT`; 3 r source front, 141 w + 141 r `TEST.$$$`, 55 w `VIBACKUP.$$$` | 17,480 | 147 | 6 | 7 | 55 |
| `:w` | 52.9 | 650 r source + 3 r source front, 55 r `VIBACKUP.$$$`, 687 w `TEST.$$$` | 2,048 | | | | |

The saved file is 105,928 bytes, with lines 6000–9000 after line 100,
exactly. Writing out lines 6000–9000 pages the window forward and back
over unchanged text, so it writes nothing to `TEST.$$$`, and `100G` after it
is the jump (17.1 s when it paged back).

* **`:r`** inserts 24 K into a window that holds 21 K. It reads `T.TXT` 17
  records at a time into the gap, and each time the arena fills, `MKROOM`
  spills the top (the inserted text, already behind the cursor) to
  `TEST.$$$`. The insert streams through memory into the work file.
* Afterwards the cursor must go back to the first line put (line 101), so the
  window pages back 144 records: 141 from `TEST.$$$`, then the last 3
  (records 3–5, before `SAMREC`) from the source. The
  first text pushed out of the bottom is the text after the insert, which is
  unchanged: it goes back to the source (its pointer falls to 7). Then comes
  the end of the inserted text, which the window can no longer hold. It is
  not in the source at all, so those 55 records go to `VIBACKUP.$$$`.

### 3.12 Undo after paging: `G` `x` `gg` `G` `u`

Measured by `pagerprobe.py undo`.

`u` answers "Cannot undo: change has paged out" and changes nothing. The `x`
was made with `PGTOPM` at 587, and `gg` `G` moved the window's top 1,083 more
times. An undo offset is measured from `TXTBEG`, so once the top has moved it
no longer names the right byte, and undo refuses rather than guess.

---

## 4. Where the time and the disk go

These are the measured facts above, collected. Each one says whether the
code involved is WordMaster's or VI's own, since that decides how much risk
a change carries.

| What | Measured | Whose code |
|---|---|---|
| A transfer, at the simulator's floor | about 0.028 s per record read forward and scanned for lines (3.2's first `G`: 625 reads, 17.8 s); about 0.042 s per record read backward (3.6's `gg`: 586 reads, 24.5 s); about 0.038 s per record written (3.4's first `:w`, less its reads at 0.028) | WM |
| A far move up on an unchanged file starts the file again | `gg` from the end: 16 reads, 1.5 s (3.2); `100G` from line 6000: 1.7 s (3.3); the next key past the first 2 K reads more, as after an open | **VI** (`PGJUMP`, #34 part B) |
| A save copies the unchanged front from the source into `TEST.$$$` | `G` `gg` `:w`: 640 writes where WordMaster's wrote 33 (3.4); `x` on the last line then `:w`: 496 reads and writes of the front (3.5) | **VI** (`SVFRNT`, deviation 8) |
| `:w` pages the saved file back to the cursor | `:w` on the last line re-reads all 640 records (3.5); since deviation 8 it writes none of them | **VI** (`SEEKTO`) |
| Scrolling back past an edit writes everything above the edit to `VIBACKUP.$$$` | `x` on the last line, then `gg`: 512 writes, 42.2 s against 1.5 without the `x` (3.5, 3.2); two edits: 376 (3.8) | WM (`PAGEBOT`, `SRCREC`) |
| An edit makes `TEST.$$$` invalid from the edit's record on, and makes the front up to it the save's to copy | 3.7: records 312–527 written by the next `G`, 0–311 copied by `:w`; 3.9: `SAMREC` falls to 6 | WM (`UPDMARK`, `OUTREC`); VI (`SAMREC`) |
| A refused `dd` still pages forward and back, and counts as an edit | `3000dd`: 17.7 s, 130 + 20 writes, nothing changed (3.10) | **VI** (`QPUTLN`/`QREFUS` on WM's Q-buffer) |
| The growing `SPILL` batch empties the window on a first forward sweep | 7 K left after `G` (3.2) | WM (`SPILL`, `SPLCNT`) |
| `:w` with no edits still saves | 42.4 s from the top, plus a `.BAK` (3.4) | **VI** (no modified check before the save) |
| A real drive adds seeks | the pager alternates between the source, `SRCFCB`'s place in it, and `TEST.$$$` (or `VIBACKUP.$$$`) every batch; the simulator does not price that | WM (batch sizes) |

## 5. What deviation 8 changed

These are the figures of a2abca7 against aabc816, as measured then; section 3
has the current build's. `PAGE.MAC` deviation 8 (a2abca7, issue #34 part A)
added `SAMREC` and `SRCFCB`. Before it, the figures were those of aabc816, which ran
WordMaster's pager as written. Two other things moved between the builds:
the arena is 742 bytes smaller (23,298 then), and the copy loops are faster
(#30). `topedit` is the control: its `x` on line 1 makes `SAMREC` 0, so it
pages as WordMaster's did, and it moved by those two alone (`G` 36.9 → 36.8,
`gg` 28.2 → 24.7, `:w` 21.3 → 21.2, the same transfers).

| Scenario, key | aabc816 s | disk then | a2abca7 s | disk now |
|---|---|---|---|---|
| browse `G` | 36.9 | 625 r, 607 w | 17.5 | 625 r, 0 w |
| browse `gg` | 28.2 | 607 r `TEST.$$$` | 27.1 | 607 r source front |
| browse second `G` | 25.6 | 481 r | 21.9 | 481 r |
| browse `:q!` | 4.1 | delete both work files | 2.0 | none |
| saveback `:w` | 21.3 | 497 r, 33 w | 39.7 | 497 r, 640 w |
| endedit `G` | 36.9 | 625 r, 607 w | 17.5 | 625 r, 0 w |
| endedit `G` (second) | 25.1 | 480 r stack | 21.0 | 480 r stack |
| endedit `:w` | 42.4 | 640 r, 591 w | 55.1 | 1,136 r, 640 w |
| midedit `5000G` | 19.1 | 304 r, 288 w | 8.7 | 304 r |
| midedit `G` | 31.4 | 513 r, 240 w | 30.9 | 513 r, 216 w |
| midedit `:w` | 44.8 | 641 r, 671 w | 41.7 | 953 r, 425 w |
| twoedit `8000G` | 25.5 | 384 r, 446 w | 23.2 | 384 r, 322 w |
| twoedit `:w` | 41.6 | 640 r, 608 w | 28.5 | 764 r, 174 w |
| local `6000G` | 20.3 | 368 r, 288 w | 9.9 | 368 r |
| bigdd `3000dd` | 20.2 | 314 r, 174 w | 14.6 | 272 r, 126 w |
| bigdel `d3099G` | 12.5 | 288 r, 48 w | 9.0 | 288 r |
| bigput `6000G` | 20.3 | 368 r, 288 w | 9.9 | 368 r |
| bigput `:6000,9000w` | 29.4 | 272 r, 346 w | 24.9 | 272 r, 188 w |

* **Moving forward through text no edit has touched no longer writes.**
  `G` on 80 K takes half the time, and a browse needs no free disk space.
* **Moving back reads the same number of records**, from the source instead
  of `TEST.$$$`.
* **The save pays for the front.** The records WordMaster wrote on the way
  down, the save now copies: `saveback`'s `:w` writes the 607 records its `G`
  no longer wrote, so the sequence costs about the same (86.4 s then, 84.3 s
  now). A save with the cursor near the end (`endedit`) costs 12.7 s more,
  because the copy reads every front record a second time.
* **`SEEKTO` no longer rewrites the file.** After a save, the re-opened file
  is all unchanged, so paging back to the cursor writes nothing. That is
  why `midedit`'s and `twoedit`'s saves got cheaper.

## 6. What the jump changed

These are the figures of 924a8ff against a2abca7, as measured then; section
3 has the current build's. `PGJUMP` (issue #34 part B) is the only pager
change between them, but the arena shrank too: 22,556 bytes at a2abca7,
21,743 at 924a8ff (813 bytes, most of it the search's reader, #35), and that
moves the window's edges. `topedit` is again
the control, since its `x` on line 1 stops the jump: `G` 36.8 → 37.3, `gg`
24.7 → 24.2, `:w` 21.2 → 21.7, with 587 records written where 606 were.

| Scenario, key | a2abca7 s | disk | 924a8ff s | disk |
|---|---|---|---|---|
| browse `gg` | 27.1 | 607 r source front | 1.5 | 16 r source |
| browse second `G` | 21.9 | 481 r | 17.4 | 625 r |
| saveback `:w` | 39.7 | 497 r, 640 w | 40.7 | 641 r, 640 w |
| local `100G` | 14.3 | 288 r source front | 1.8 | 16 r source |
| bigput `100G` | 17.1 | 366 r source front | 1.5 | 16 r source |
| bigput `:r T.TXT` | 31.7 | 181 w + 181 r `TEST.$$$` | 20.5 | 142 w + 142 r `TEST.$$$` |
| bigdel `d3099G` | 9.0 | 288 r | 9.7 | 397 r |

* **A far move up costs an open, not the way back.** The sequence `G` `gg`
  `G` (browse) went from 66.5 to 36.5 s.
* **What the jump throws away is read again.** The window holds 2 K after
  it, so a `G` after `gg` reads the whole file instead of the records past
  160, and a save after `G` `gg` reads 144 more. `d3099G` reads again the
  records its motion read on the way down.
* **The first key that needs text past those 2 K reads it**, as after an
  open. `dd` low on the screen after `G` `gg` on a 116 K file takes 0.66 s
  this way, and 0.29 s with the window full after a page back
  (`accept_vi.py`'s `resp` rows page back on purpose, with an `x` at the
  end, so that they time the full window).

## 7. Measuring again

```
python3 pagerprobe.py --list          # the scenarios
python3 pagerprobe.py browse midedit  # some of them
python3 pagerprobe.py browse --trace  # every disk call, in runs, with the window size
python3 pagerprobe.py browse --log=F.jsonl  # every disk call, timed, for pagermodel.py
```

`pagermodel.py` (issue #29) replays the logged calls, `pagertrace.jsonl.gz`,
onto an Altair 8" floppy and compares them with a piece table on the same
drive (section 8). The trace is section 3's runs, recorded on the same
build, and `pagermodel.py` refuses it unless it reproduces section 3's
per-key counts. To record it again after a pager change:

```
python3 pagerprobe.py --log=pagertrace.jsonl
gzip -9 -n -f pagertrace.jsonl
python3 pagermodel.py        # refuses until its PAGING_MD table matches section 3
```

Build first (`python3 build_vi.py VI`), and never run it beside a test
battery. Each scenario takes one to four minutes of wall time. Separate
invocations get separate sandboxes, so several can run at once. The figures
in this document change whenever the image size changes the arena. Re-run
the probe after such a change before quoting them.

## 8. On a floppy

`pagermodel.py` prices section 3's disk calls on an Altair 8" floppy, through
CP/M 2.2's file system: directory searches, extents and block allocation, the
guest BIOS's skew, and head movement between files, which the simulator does
not charge. Step, settle and head-load times are assumed (10, 20, 40 ms).
Beside it, the same edits on a piece table (issue #29): the source is never
written, typed text goes to an add file, and the document is a list of
pieces, with a line index built by reading forward. The piece table's CPU
costs are estimates. Seconds on the track-buffered BIOS (the guest's):

| Scenario | simulator | floppy | piece table |
|---|---|---|---|
| small | 13.1 | 7.5 | 5.7 |
| browse | 38.9 | 37.4 | 16.2 |
| savenone | 42.4 | 36.3 | 31.6 |
| saveback | 61.6 | 54.6 | 46.6 |
| endedit | 137.7 | 139.6 | 48.2 |
| topedit | 84.6 | 80.1 | 47.5 |
| midedit | 100.9 | 99.9 | 50.1 |
| twoedit | 117.9 | 125.7 | 47.7 |
| local | 15.4 | 14.7 | 13.3 |
| bigdd | 56.1 | 50.8 | 29.0 |
| bigdel | 42.2 | 35.9 | 29.0 |
| bigput | 111.3 | 104.7 | 78.6 |
| undo | 81.8 | 83.8 | 16.3 |
| all thirteen | 904.2 | 871.0 | 459.9 |

On aabc816, before deviation 8 and the jump, the floppy column totalled
1,065 s and the piece table's 459 s. On a BIOS that reads one sector at a
time, all thirteen take 2,059 s against 1,025 s (2,515 s on aabc816).

* **Where the two now cost the same:** moving near the cursor (`local`), a
  far move up on an unchanged file (`gg`, `100G`: 1.2–1.5 s each), and every
  save (both make a full pass; `topedit`'s `:w` is cheaper here, 18.0 s
  against 32.4, because the front copy starts at record 0).
* **Where the piece table still wins: moving past an edit.** `gg` after an
  edit at the end costs 43.4 s here and 1.3 s there, and the `G` after it
  23.0 s against 1.1 s (`endedit`). That is section 2's bottom edge: every
  record above the edit is shifted against the source, so it goes to
  `VIBACKUP.$$$` and back. `twoedit`'s `gg` (40.3 s) and `midedit`'s (19.8 s)
  are the same cost. A piece table never writes text it did not change.
* **A `G` after a jump reads the whole file again** (browse's second `G`,
  17.0 s against 1.1 s): the jump keeps no index of where the lines are.
* `undo` is not like for like: this editor refuses the `u`, the piece table
  carries it out. `bigdd` neither: this editor refuses the `3000dd`.
