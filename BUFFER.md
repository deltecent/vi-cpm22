# The VI gap buffer

How VI stores and edits text. The buffer is WordMaster 5.55A's, transcribed
verbatim from `WM.ASM` (every routine cites its WM line), with a small appended
layer the vi commands use on top of it.

The design has **one** idea:

> There is a single in-RAM **gap buffer** that holds a **window** onto the file.
> The rest of the file lives on disk and is paged in and out as the cursor moves.
> A file that fits in RAM is just the run in which nothing has paged out — the
> identical code runs either way.

There is no "RAM mode" and no "virtual mode", no flag that switches behaviour.

The code lives in two modules:

* **`BUF.MAC`** — the gap buffer and the WordMaster routines that walk it:
  insert, delete, cursor move, the pointer-row mechanics, the Q-buffer (the
  yank register), the line moves, the string matchers and the screen reads.
  Appended to it, and tagged as not WordMaster: the logical-offset API (§7),
  single-level undo, and the cursor-line count the renderer reads (`LNDLT`).
* **`PAGE.MAC`** — everything on the disk side: the record engine, the load
  and save drivers, and the paging that slides the window along the file.
  `BUF.MAC` reaches it through `MKROOM` (the gap ran dry), `REWIND` (a read
  below the window), `UPDMARK`/`MARKGB` (keep the record marks), `PAGEDIR` /
  `PAGEWIN` (page one step either way) and `NEEDIN` (a read past the window).

---

## 1. The arena and the pointer row

The **arena** is all the RAM between the program and CP/M:

```
 0100H            RSVTOP = PBEGMEM                          BUFEND   BDOS
   | VI.COM image | reserve block |  ======== arena ======== |        |
                  (RSV.MAC: stack,                           (from the word
                   buffers -- no file bytes)                  at 0006, WM 378)
```

`RSV.MAC` links last and emits no bytes: it names the storage that only needs
to exist at run time (the stack, the key ring, the undo records, the sector
buffer) as offsets above the image, so none of it costs `.COM` bytes. The arena
starts at `PBEGMEM`, past that block. Every byte of image is a byte less arena.

Inside the arena, one row of `(base, limit)` pointer pairs describes every
region. `PBEGMEM` holds a 0 sentinel and `TXTBAS = PBEGMEM + 1`:

| Pointer  | Meaning                                                          |
|----------|------------------------------------------------------------------|
| `BUFBEG` | the row's base                                                   |
| `QBEG` / `QEND` | the Q-buffer — the yank register, a second gap buffer, `QEND` its insertion point |
| `UBEG` / `UEND` | the undo region (appended), `UEND` its insertion point   |
| `TXTBEG` | first buffered text byte — the window's start                    |
| `GAPBEG` | the insertion point; the byte left of the cursor is `[GAPBEG-1]` |
| `GAPEND` | first text byte after the gap — the cursor byte is `[GAPEND]`    |
| `TXTEND` | end of buffered text — the window's end                          |
| `BUFEND` | top of usable text RAM                                           |

Walked from `BUFBEG`, the pairs are the **holes** — `(BUFBEG,QBEG)`
`(QEND,HOLEQP)` `(TXTBAS,UBEG)` `(UEND,TXTBEG)` `(GAPBEG,GAPEND)`
`(TXTEND,BUFEND)`; walked from `QBEG` they are the **data** —
`(QBEG,QEND)` `(HOLEQP,TXTBAS)` `(UBEG,UEND)` `(TXTBEG,GAPBEG)`
`(GAPEND,TXTEND)`. `PRSPAN` measures one pair, `NEXTPR` steps to the next and
`BUFSUM` totals the holes, which is every free byte in the arena. The undo
region sits between the Q-buffer and the text precisely so both walks stay
aligned and none of that arithmetic had to change.

Everything is an **absolute address**, not an offset: the hot path is a bare
`LHLD GAPBEG`, and one set of pair arithmetic serves every region.

---

## 2. Inserting = consuming the gap

`PUTGAP` stores one byte at `GAPBEG` and advances it; `INSBLK` splices a block,
chunk by chunk; `INSSTR` splices a length-prefixed string (`:s` uses it). Each
first asks `MKGAP` for room (§5). The byte lands just left of the cursor, which
is where `i` puts it.

```
   before:   .. A B [   gap   ] C D ..      GAPBEG at the gap, cursor byte C
   after:    .. A B X [  gap  ] C D ..      GAPBEG advanced by 1, C unmoved
```

---

## 3. Deleting = growing the gap

`DELTO` swallows the span between the cursor and a target into the gap —
forward by moving `GAPEND` up, backward by moving `GAPBEG` down — then updates
the record marks and ends on `PAGESTP` (§6). A delete frees space, so it never
has to page anything out, and the swallowed bytes are never written anywhere.

They are not overwritten either, until something reuses the gap: a forward
delete only moves `GAPEND` past the byte, so it is still sitting in the gap.
`R`'s backspace depends on that — `UNDELF` moves `GAPEND` back over the byte
and it is text again.

---

## 4. Moving the cursor = moving the gap

`PUTCUR` takes a physical address and slides the gap there (`GAPRT` / `GAPLF`
copy the span between across it), so the cursor lands on whatever byte lives
at that address. A motion is: work out the target, map it to an address,
`PUTCUR` there.

### Line endings

VI stores line endings **verbatim** — CR,LF, a bare LF, exactly as on disk.
A CR,LF is one line break and the cursor is never left between the CR and the
LF: on an empty line it sits on the CR. `DELPRV` (WordMaster's rubout) takes
the CR with its LF, and the vi commands that insert at a line's end insert
before the CR,LF, never inside it.

---

## 5. Making room: `MKGAP`

```
   MKGAP:
     at least 256 bytes of gap?          ── yes ──▶ done
        │ no
     at least 256 bytes free in holes?   ── yes ──▶ MOVGAP gathers them into the gap
        │ no
     MKROOM (PAGE.MAC): evict a window edge to disk ──▶ retry
        │ nothing left to evict
     MEM FULL
```

`MOVGAP` (WordMaster's `PUTHOLE`) slides the regions so the free bytes collect
at the gap. Only when the arena is genuinely full does the disk get involved,
and then through `MKROOM` alone: forward it `SPILL`s the text above the cursor
out to the work file, backward it `SPILLB`s the text below it back to the input
side.

---

## 6. The window onto the file

`TXTBEG..TXTEND` is only a window. Text above `TXTBEG` has been spilled to the
work file `name.$$$` (`OUTFCB`); text below `TXTEND` is still on the input side
— the unread rest of the original file, plus `VIBACKUP$$$` for anything
`PAGEBOT` has pushed back down.

```
   spilled (above)        │   RAM window: R1 [gap] R2   │   input side (below)
   name.$$$  (OUTFCB)     │   TXTBEG ......... TXTEND    │   the file + VIBACKUP$$$
        REWIND reads back ▲                              ▼ FILLBUF / NEEDIN read in
```

* `PAGEDIR` pages one step in the current direction (`DIRFLG`): `REWIND`
  backward, `FILLBUF` forward. `PAGESTP` calls it while the command count is
  unspent, which is how a count loop — the line moves, `dd`, the search sweep —
  runs on past the window's edge.
* `NEEDIN` pages in when a read (`RGET`) runs past `TXTEND`; `LINPOSB`/`PAGEWIN`
  page back when the renderer needs text above `TXTBEG`. `PGNEED`/`PAGEWIN` keep
  `PGMARGN` pages of text resident on the active edge.
* `UPDMARK` keeps three record marks (`OUTREC`, `SRCREC`, `BAKREC`) so the
  pager can tell a record already on disk from one it must transfer: nothing is
  written twice, and nothing is lost.

Paging moves `TXTBEG`, and with it every resident offset. `PAGE.MAC` counts
those moves in `PGTOPM` — the only true "the window has paged" signature
(`OUTREC`/`SRCREC` move on every edit). Undo and the marks key on it.

---

## 7. The logical-offset API

Appended to `BUF.MAC`, not WordMaster. A **logical offset** is a byte index
into the resident text as if the gap were absent:

```
   CUROFF (cursor)  = GAPBEG - TXTBEG
   LOGLEN (total)   = (GAPBEG - TXTBEG) + (TXTEND - GAPEND)
```

| Routine  | Job                                                          |
|----------|--------------------------------------------------------------|
| `CUROFF` / `LOGLEN` | the cursor's offset / the resident length          |
| `CHARAT` | the byte at an offset                                        |
| `GOTO`   | move the cursor to an offset, keeping `LNDLT` (lines crossed) |
| `LFCNT`  | count the line feeds in a span                               |
| `DELFWD` | delete N bytes forward                                       |
| `DELPRV` | rubout, WordMaster's own (`WM 3260`), CR,LF as one            |
| `UNDELF` | give back the byte last swallowed forward (`R`'s backspace)  |

Most vi commands work in these offsets alone. Anything that has to reach past
the window uses WordMaster's own pointer-based routines instead — the line
moves, `RGET`, the matchers, the line kill, the Q-buffer — because those page
as they go. An offset is resident-relative, so it is only meaningful while
`PGTOPM` is unchanged.

### The Q-buffer and undo

The yank register is WordMaster's Q-buffer: a region of the arena that grows
through the same `MKGAP` as the text, with the text free to page out from under
it (`QROOM` keeps `RESVMEM` in reserve). `QCOPY` fills it by deleting what it
takes, which is why `yy` is a delete and a put-back.

Undo is captured inside the primitives that change text, so no command can
forget to record itself. Its region grows only at a command boundary, never
while a primitive runs, and holds one change: a record per primitive step,
with the bytes of inserts as well as deletes, so `u` can walk the change
either way. See `COMMANDS.md` for its limits.

### Marks

Marks live in `CMD.MAC`, not here: a logical offset plus the `PGTOPM` it was
taken under. A mark is **dropped, never shifted** — any edit at or above it,
or the window paging, invalidates it (`MKDROP`, called from `MARKMOD`, which
every edit passes through).

---

## 8. How it is proven

* **`BUFTST`** (`BUFTST`, `PAGE`, `BUF`, `RSV`) runs a fixed battery of
  WordMaster primitives — insert past 256 bytes, one-byte walks both ways,
  forward and backward deletes, mid-text relocation, high-bit bytes — and
  records a checksum and length of the logical text after every op.
  `buftst.py` replays the same script in an independent Python model and
  compares every checkpoint, the window invariant
  `TXTBEG ≤ GAPBEG ≤ GAPEND ≤ TXTEND` read from the `.SYM`, and the error flag.
* **`PGTST`**, **`PGXTST`**, **`PGXINS`**, **`PGBKTST`** load, edit and save
  real files byte-exact: resident; with the window shrunk (`WINCAP`) so the
  load and save page; with an insert far bigger than the window; and with the
  window walked forward to the end and back to the start.
* **`accept_vi.py`** proves the assembled editor on files of 0 bytes to 100 K.

*Source: `BUF.MAC` and `PAGE.MAC` are annotated routine by routine.*
