#!/usr/bin/env python3
"""Prices WordMaster's pager against a piece table, on a floppy (issue #29).

    python3 pagermodel.py                    # every scenario, both BIOS kinds
    python3 pagermodel.py browse midedit     # some of them
    python3 pagermodel.py --bios=buffered    # one BIOS kind
    python3 pagermodel.py --keys             # every key, not just totals
    python3 pagermodel.py --lazy             # piece-table G does not count lines
    python3 pagermodel.py --scan-ms=37       # charge the piece table's line count
                                             # WordMaster's own line-loop cost

THE TWO SIDES ARE NOT MADE THE SAME WAY.

* WordMaster is not modelled.  `pagerprobe.py --log=pagertrace.jsonl` records,
  for every key of every scenario, each BDOS file call the real editor made:
  the simulator time it was made at, the file, the record, and how long BDOS
  and the BIOS took to return.  The time between calls is the editor's own CPU.
  This script replays that sequence onto the floppy below, so the WordMaster
  column is the real editor's real disk traffic, priced on another drive.  The
  check at start-up holds it to PAGING.md's per-key counts.
* The piece table IS modelled: `PieceTable` below runs each scenario's edits
  on a piece list, emits the BDOS calls the design would make, and checks the
  text it ends with against the same expected file `pagerprobe.py` checks.

Both call sequences then go through the same CP/M 2.2 file system and the same
drive, so the difference between the columns is the design, not the pricing.

THE DRIVE (Altair 8" floppy, from the guest BIOS of ~/iCloud/AltairGIT/vi/
BIOS.ASM, drives C: and D:): 77 tracks of 32 sectors of 128 bytes, two
reserved tracks, 2 K blocks, 150 blocks (300 K), 64 directory entries, EXM 0
(16 K per directory entry), 360 rpm, the BIOS's translate table and its
Altair skew on tracks 6-76.

THE BIOS, two kinds:
* `buffered` is that BIOS: it reads a whole track into RAM in one revolution
  when a different track is wanted, writes the whole track back (one more
  revolution, no verify by default) before leaving a dirty one, and on console
  input flushes, invalidates the buffer and unloads the head.
* `sector` is a BIOS that reads and writes one sector per call and waits for
  it to come under the head.  It uses the same tables; until a real unbuffered
  BIOS is in hand its skew is a stand-in.

ASSUMED, not read from anything (change them here): STEP, SETTLE and HEADLOAD
below; the piece table's CPU costs (`PT_CPU`).  The editor CPU on the
WordMaster side is measured, not assumed.
"""
import argparse
import collections
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- the drive

TRACKS, SPT, RESTRK = 77, 32, 2
BLKRECS = 16                    # 2 K blocks
DSM = 149                       # blocks 0..149
DIRENTS, DIRRECS = 64, 16       # 64 entries, four to a record
DIRBLKS = 2                     # AL0 = C0H
EXTRECS = 128                   # EXM 0: 16 K per directory entry
ENTBLKS = EXTRECS // BLKRECS    # 8 block numbers used per entry
REV = 60.0 / 360                # 166.7 ms
SECT = REV / SPT                # 5.2 ms

STEP = 0.010                    # ASSUMED: per track stepped
SETTLE = 0.020                  # ASSUMED: after the last step
HEADLOAD = 0.040                # ASSUMED: first access after the head unloads

TRAN = [1, 9, 17, 25, 3, 11, 19, 27, 5, 13, 21, 29, 7, 15, 23, 31,
        2, 10, 18, 26, 4, 12, 20, 28, 6, 14, 22, 30, 8, 16, 24, 32]


def hard_sector(track, lsec):
    """BIOS secTran, then altSkew: the hard sector a logical sector is on."""
    s = TRAN[lsec] - 1
    if track >= 6 and s & 1:
        s ^= 0x10
    return s


class Drive:
    """The head, the platter and the clock; `t` is seconds."""

    def __init__(self):
        self.t = 0.0
        self.track = RESTRK
        self.loaded = False
        self.seeks = 0
        self.steps = 0

    def seek(self, track):
        if not self.loaded:
            self.t += HEADLOAD
            self.loaded = True
        if track != self.track:
            n = abs(track - self.track)
            self.t += n * STEP + SETTLE
            self.seeks += 1
            self.steps += n
            self.track = track

    def next_sector(self):
        """Wait for the next sector boundary."""
        frac = (self.t / SECT) % 1.0
        if frac:
            self.t += (1.0 - frac) * SECT

    def wait_for(self, hard):
        """Wait until hard sector `hard` starts under the head."""
        self.next_sector()
        now = int(round(self.t / SECT)) % SPT
        self.t += ((hard - now) % SPT) * SECT


class BufferedBIOS:
    """BIOS.ASM: read, ckFlush, readTrk, wrtTrk, invFlsh."""
    name = "buffered"

    def __init__(self, drive):
        self.d = drive
        self.track = None
        self.dirty = False
        self.reads = self.writes = 0        # whole tracks

    def _flush(self):
        if self.dirty:
            self.d.next_sector()
            self.d.t += REV                 # every sector of the track
            self.writes += 1
            self.dirty = False

    def io(self, track, lsec, write):
        if self.dirty and track != self.track:
            self._flush()
        if track != self.track:
            self.d.seek(track)
            self.d.next_sector()
            self.d.t += REV                 # all 32 in the order they pass
            self.reads += 1
            self.track = track
        if write:
            self.dirty = True

    def idle(self):
        """Console input: flush, invalidate, unload the head."""
        self._flush()
        self.track = None
        self.d.loaded = False


class SectorBIOS:
    """One sector per call, no buffer."""
    name = "sector"

    def __init__(self, drive):
        self.d = drive
        self.reads = self.writes = 0        # sectors

    def io(self, track, lsec, write):
        self.d.seek(track)
        self.d.wait_for(hard_sector(track, lsec))
        self.d.t += SECT
        if write:
            self.writes += 1
        else:
            self.reads += 1

    def idle(self):
        self.d.loaded = False


# ---------------------------------------------------------- the file system

class Disk:
    """CP/M 2.2 BDOS file calls on that drive: a directory of 64 entries,
    a block map, and an FCB per open file holding its current extent.

    Each rule is OS3BDOS.ASM's (~/iCloud/AltairGIT/cpm2-plm):
    * `search` reads the directory a record at a time from the first; a name
      it finds stops it, one it does not find reads all 16 records.
    * `open` searches for extent 0; `make` searches for the first empty entry
      and writes its record; `close` does nothing unless the extent was
      written (`fwfmsk`: a new block, or a record past its record count),
      then searches for the extent and writes its record.
    * `delete` and `rename` search the whole directory and write the record
      of each entry they change, once per entry.
    * A random read or write in another extent (`rseek`) closes the open one
      and opens the new one, or makes it for a write; a sequential one at
      record 128 does the same (`open$reel`).
    * A read at or past the extent's record count is end of file, no I/O.
    * A write into an unallocated block takes `get$block`'s: the free block
      nearest the extent's previous block, left first; with no previous block
      in this extent, the first free one from block 1."""

    def __init__(self, bios_cls, files, bdos_cpu):
        self.d = Drive()
        self.bios = bios_cls(self.d)
        self.cpu = bdos_cpu             # seconds per call and per dir record
        self.dir = [None] * DIRENTS     # [name, extent number, [blocks]]
        self.free = [True] * (DSM + 1)
        for b in range(DIRBLKS):
            self.free[b] = False
        self.fcb = {}                   # name -> [entry index, modified]
        self.counts = collections.Counter()
        self.peak = 0
        for name, nrec in files:
            self._create(name, nrec)

    # -- layout
    def _create(self, name, nrec):
        """A file already on the disk, laid down block after block."""
        blk = None
        for ext in range((nrec + EXTRECS - 1) // EXTRECS):
            e = self.dir.index(None)
            n = min(ENTBLKS, (nrec - ext * EXTRECS + BLKRECS - 1) // BLKRECS)
            blocks = []
            for _ in range(n):
                blk = self._getblock(blk or 0)
                blocks.append(blk)
            rc = min(EXTRECS, nrec - ext * EXTRECS)
            self.dir[e] = [name, ext, blocks + [0] * (ENTBLKS - n), rc]
        self._note_used()

    def _note_used(self):
        self.peak = max(self.peak, sum(1 for f in self.free if not f))

    def _getblock(self, near):
        """get$block: the free block nearest `near`, left first."""
        for k in range(1, DSM + 2):
            for b in (near - k, near + k):
                if 0 < b <= DSM and self.free[b]:
                    self.free[b] = False
                    return b
        raise RuntimeError("disk full")

    # -- the drive
    def _rec_io(self, absrec, write):
        self.bios.io(RESTRK + absrec // SPT, absrec % SPT, write)

    def _dir_read(self, r):
        self.d.t += self.cpu["dir"]
        self._rec_io(r, False)
        self.counts["dir r"] += 1

    def _dir_write(self, r):
        self._rec_io(r, True)
        self.counts["dir w"] += 1

    def _search(self, match, stop=True):
        """Read the directory from the start; the entry indexes that match."""
        hits = []
        for r in range(DIRRECS):
            self._dir_read(r)
            for e in range(r * 4, r * 4 + 4):
                if match(e):
                    hits.append(e)
                    if stop:
                        return hits
        return hits

    def _find(self, name, ext):
        return self._search(lambda e: self.dir[e] is not None and
                            self.dir[e][0] == name and self.dir[e][1] == ext)

    # -- BDOS calls
    def call(self, fn, name, rec, new=None):
        self.d.t += self.cpu["call"]
        if fn == 0x0F:                                  # open
            hit = self._find(name, 0)
            self.fcb[name] = [hit[0] if hit else None, False]
        elif fn == 0x16:                                # make
            e = self._search(lambda e: self.dir[e] is None)[0]
            self.dir[e] = [name, 0, [0] * ENTBLKS, 0]
            self._dir_write(e // 4)
            self.fcb[name] = [e, False]
        elif fn == 0x10:                                # close
            self._close(name)
        elif fn in (0x13, 0x17):                        # delete, rename
            self.fcb.pop(name, None)
            hits = self._search(lambda e: self.dir[e] is not None and
                                self.dir[e][0] == name, stop=False)
            for e in hits:
                if fn == 0x13:
                    for b in self.dir[e][2]:
                        if b:
                            self.free[b] = True
                    self.dir[e] = None
                else:
                    self.dir[e][0] = new
            for e in hits:
                self._dir_write(e // 4)
        elif fn == 0x23:                                # file size
            self._search(lambda e: False, stop=False)
        elif fn in (0x14, 0x21, 0x15, 0x22):            # read, write
            write = fn in (0x15, 0x22)
            self.d.t += self.cpu["w" if write else "r"]
            self._data(name, rec, write)

    def _close(self, name):
        f = self.fcb.get(name)
        if f and f[0] is not None and f[1]:
            e = f[0]
            self._find(name, self.dir[e][1])
            self._dir_write(e // 4)
            f[1] = False

    def _data(self, name, rec, write):
        f = self.fcb.setdefault(name, [None, False])
        ext = rec // EXTRECS
        if f[0] is None or self.dir[f[0]] is None or self.dir[f[0]][1] != ext:
            self._close(name)
            hit = self._find(name, ext)
            if hit:
                f[:] = [hit[0], False]
            elif write:
                e = self._search(lambda e: self.dir[e] is None)[0]
                self.dir[e] = [name, ext, [0] * ENTBLKS, 0]
                self._dir_write(e // 4)
                f[:] = [e, False]
            else:
                f[:] = [None, False]
                self.counts["eof"] += 1
                return
        ent = self.dir[f[0]]
        i = (rec % EXTRECS) // BLKRECS
        if not write and (rec % EXTRECS >= ent[3] or not ent[2][i]):
            self.counts["eof"] += 1
            return
        if not ent[2][i]:
            prev = ent[2][i - 1] if i else 0        # dm$position - 1, or 0
            ent[2][i] = self._getblock(prev)
            self._note_used()
            f[1] = True
        if write and rec % EXTRECS >= ent[3]:
            ent[3] = rec % EXTRECS + 1
            f[1] = True
        self.counts[("w " if write else "r ") + name] += 1
        self._rec_io(ent[2][i] * BLKRECS + rec % BLKRECS, write)

    def idle(self):
        self.bios.idle()


# ------------------------------------------------------------ the scenarios

def lines(n):
    return [b"%06d\r\n" % i for i in range(1, n + 1)]


BIG, SMALL = lines(10240), lines(1280)

# name -> (file lines, keys as pagerprobe types them, piece-table ops)
SCENARIOS = {
    "small":    (SMALL, ["G", "gg", "x", ":w"],
                 [("goto", "end"), ("goto", 1), ("x", 1), ("save",)]),
    "browse":   (BIG, ["G", "gg", "G", ":q!"],
                 [("goto", "end"), ("goto", 1), ("goto", "end"), ("quit",)]),
    "savenone": (BIG, [":w"], [("save",)]),
    "saveback": (BIG, ["G", "gg", ":w"],
                 [("goto", "end"), ("goto", 1), ("save",)]),
    "endedit":  (BIG, ["G", "x", "gg", "G", ":w"],
                 [("goto", "end"), ("x", 10240), ("goto", 1), ("goto", "end"), ("save",)]),
    "topedit":  (BIG, ["x", "G", "gg", ":w"],
                 [("x", 1), ("goto", "end"), ("goto", 1), ("save",)]),
    "midedit":  (BIG, ["5000G", "ihello", "<Esc>", "gg", "G", ":w"],
                 [("goto", 5000), ("ins", 5000, b"hello"), ("none",), ("goto", 1),
                  ("goto", "end"), ("save",)]),
    "twoedit":  (BIG, ["2000G", "x", "8000G", "x", "gg", "G", ":w"],
                 [("goto", 2000), ("x", 2000), ("goto", 8000), ("x", 8000),
                  ("goto", 1), ("goto", "end"), ("save",)]),
    "local":    (BIG, ["6000G", "6100G", "5900G", "\\x06", "\\x02", "100G"],
                 [("goto", 6000), ("goto", 6100), ("goto", 5900), ("none",),
                  ("none",), ("goto", 100)]),
    "bigdd":    (BIG, ["100G", "3000dd", ":w"],
                 [("goto", 100), ("del", 100, 3000), ("save",)]),
    "bigdel":   (BIG, ["100G", "d3099G", ":w"],
                 [("goto", 100), ("del", 100, 3000), ("save",)]),
    "bigput":   (BIG, ["6000G", ":6000,9000w T.TXT", "100G", ":r T.TXT", ":w"],
                 [("goto", 6000), ("wrange", 6000, 9000, "T.TXT"), ("goto", 100),
                  ("readin", 100, "T.TXT"), ("save",)]),
    "undo":     (BIG, ["G", "x", "gg", "G", "u"],
                 [("goto", "end"), ("x", 10240), ("goto", 1), ("goto", "end"),
                  ("undo",)]),
}

# Every scenario's per-key reads and writes, from PAGING.md section 3: the
# replay refuses a trace that does not reproduce them.
PAGING_MD = {
    ("browse", "G"): {"r TEST.TXT": 625, "w TEST.$$$": 607},
    ("browse", "gg"): {"r TEST.$$$": 607},
    ("savenone", ":w"): {"r TEST.TXT": 641, "w TEST.$$$": 640},
    ("saveback", ":w"): {"r TEST.TXT": 497, "w TEST.$$$": 33},
    ("endedit", "gg"): {"r TEST.$$$": 607, "w VIBACKUP.$$$": 480},
    ("endedit", ":w"): {"r TEST.TXT": 640, "w TEST.$$$": 591},
    ("midedit", "gg"): {"r TEST.$$$": 288, "w VIBACKUP.$$$": 185},
    ("midedit", "G"): {"r VIBACKUP.$$$": 185, "r TEST.TXT": 328, "w TEST.$$$": 240},
    ("twoedit", "gg"): {"r TEST.$$$": 446, "w VIBACKUP.$$$": 340},
    ("local", "100G"): {"r TEST.$$$": 288},
    ("bigdd", "3000dd"): {"r TEST.TXT": 158, "w TEST.$$$": 156, "r TEST.$$$": 156,
                          "w VIBACKUP.$$$": 18},
    ("bigdel", "d3099G"): {"r TEST.TXT": 240, "w TEST.$$$": 48, "r TEST.$$$": 48},
}


def expected(name):
    ls = SCENARIOS[name][0]
    x = lambda ls, i: ls[:i] + [ls[i][1:]] + ls[i + 1:]
    return {
        "small": lambda: x(SMALL, 0),
        "savenone": lambda: BIG, "saveback": lambda: BIG,
        "endedit": lambda: x(BIG, 10239), "topedit": lambda: x(BIG, 0),
        "midedit": lambda: BIG[:4999] + [b"hello" + BIG[4999]] + BIG[5000:],
        "twoedit": lambda: x(x(BIG, 1999), 7999),
        "bigdd": lambda: BIG[:99] + BIG[3099:],
        "bigdel": lambda: BIG[:99] + BIG[3099:],
        "bigput": lambda: BIG[:100] + BIG[5999:9000] + BIG[100:],
    }.get(name, lambda: ls)()


# ------------------------------------------------- WordMaster: the real trace

def load_traces(path):
    opener = gzip.open if path.endswith(".gz") else open
    t = collections.defaultdict(list)
    with opener(path, "rt") as f:
        for line in f:
            d = json.loads(line)
            t[d["scenario"]].append(d)
    return t


def wm_calls(key):
    """A key's calls as (editor CPU before it, fn, file, record, new name),
    and the editor CPU after the last one."""
    out, end = [], 0.0
    for e in key["events"]:
        t, fn, name, rec, took = e[:5]
        out.append((t - end, fn, name, rec, e[5] if len(e) > 5 else None))
        end = t + took
    return out, key["seconds"] - end


def wm_counts(key):
    c = collections.Counter()
    for e in key["events"]:
        if e[1] in (0x14, 0x21):
            c["r " + e[2]] += 1
        elif e[1] in (0x15, 0x22):
            c["w " + e[2]] += 1
    return dict(c)


def check_traces(traces):
    bad = []
    for (scn, k), want in PAGING_MD.items():
        keys = [d for d in traces.get(scn, []) if d["key"] == k]
        if not keys:
            bad.append("%s %s: not in the trace" % (scn, k))
        elif wm_counts(keys[0]) != want:
            bad.append("%s %s: %s, PAGING.md says %s" % (scn, k, wm_counts(keys[0]), want))
    if bad:
        sys.exit("the trace does not reproduce PAGING.md:\n  " + "\n  ".join(bad))


def bdos_cpu(traces):
    """BDOS and BIOS CPU per call, from calls that hit the simulator's track
    buffer (the median, which is far below a call that loads a track)."""
    rd, wr = [], []
    for keys in traces.values():
        for k in keys:
            for e in k["events"]:
                if e[1] in (0x14, 0x21):
                    rd.append(e[4])
                elif e[1] in (0x15, 0x22):
                    wr.append(e[4])
    med = lambda v: sorted(v)[len(v) // 2]
    r, w = med(rd), med(wr)
    return {"r": r, "w": w, "dir": r, "call": 0.0}


# ----------------------------------------------- the piece table: the design

# ASSUMED CPU costs for the piece table, in seconds.  `rec` is moving one
# record between the disk buffer and the window, taken from WordMaster's own
# save (savenone's :w, editor CPU / records moved); `count` is a line-feed
# count over 128 bytes (CMP M / JNZ / INX H / DCR C / JNZ, about 40 T-states a
# byte at 2 MHz); `key` is what a key costs with no disk at all, the repaint
# among it, and `move` that for a key that moves the cursor a long way.
PT_CPU = {"rec": 0.0053, "count": 0.0027, "key": 0.1, "move": 0.5}

WINDOW = 20 * 1024              # text RAM: 22 K arena less ~2 K of tables
SCREEN = 2048                   # what a jump loads: as WordMaster's open does
BATCH = 16 * 1024               # records moved per pass in a copy or save


class PieceTable:
    """A piece table on disk with a gap-buffer window over it.

    The source is never written.  Typed or read-in text goes to an add file
    (VIEDIT.ADD), through a one-record tail kept in RAM.  The document is a
    list of pieces (file, offset, length).  The window is a contiguous span of
    the document in RAM; it only ever caches, so dropping it costs nothing.
    Line feeds are counted once, by reading forward from the start, into a
    per-chunk index; `known` is how far that index reaches.  A save writes the
    whole document to name.$$$ and renames, as now; afterwards the new file
    is the source, one piece, fully indexed."""

    def __init__(self, data, lazy):
        self.files = {"TEST.TXT": bytes(data), "ADD": bytearray()}
        self.pieces = [("TEST.TXT", 0, len(data))] if data else []
        self.text = bytearray(data)
        self.win = (0, min(len(data), SCREEN))      # open read 16 records
        self.known = self.win[1]
        self.add_written = 0                        # records of ADD on disk
        self.add_made = False
        self.lazy = lazy
        self.undo = None
        self.calls = []
        self.cpu = 0.0
        self.counted = 0                            # records counted

    # -- emitting calls
    def _call(self, fn, name, rec=0, new=None):
        self.calls.append((self.cpu, fn, name, rec, new))
        self.cpu = 0.0

    def _name(self, f):
        return "VIEDIT.ADD" if f == "ADD" else f

    # -- the document
    def _line_off(self, n):
        if n == "end":
            i = self.text.rfind(b"\n", 0, len(self.text) - 1)
            return i + 1
        off = 0
        for _ in range(n - 1):
            off = self.text.index(b"\n", off) + 1
        return off

    def _spans(self, a, b):
        """The pieces under document bytes [a, b): (file, start, end)."""
        pos = 0
        for f, o, n in self.pieces:
            lo, hi = max(a, pos), min(b, pos + n)
            if lo < hi:
                yield f, o + lo - pos, o + hi - pos
            pos += n

    def _read(self, a, b, count=False, seen=None):
        """Read document bytes [a, b) from disk, skipping what the window
        holds, the add file's unwritten tail, and records in `seen` (a pass
        in batches keeps the record a batch boundary splits)."""
        seen = set() if seen is None else seen
        w0, w1 = self.win
        for lo, hi in ((a, min(b, w0)), (max(a, w1), b)):
            if lo >= hi:
                continue
            for f, s, e in self._spans(lo, hi):
                for r in range(s // 128, (e - 1) // 128 + 1):
                    if f == "ADD" and r >= self.add_written:
                        continue
                    if (f, r) in seen:
                        continue
                    seen.add((f, r))
                    self.cpu += PT_CPU["rec"] + (PT_CPU["count"] if count else 0)
                    self._call(0x21, self._name(f), r)
                    if count:
                        self.counted += 1

    def _show(self, a, b):
        """Make the window hold [a, b), keeping what is next to it."""
        a, b = max(0, a), min(len(self.text), b)
        self._read(a, b)
        w0, w1 = self.win
        if a <= w1 and b >= w0 and max(b, w1) - min(a, w0) <= WINDOW:
            self.win = (min(a, w0), max(b, w1))
        else:
            self.win = (a, b)

    def _count_to(self, off):
        """Extend the line index to `off`, reading forward."""
        while self.known < off:
            b = min(off, self.known + BATCH)
            self._read(self.known, b, count=True)
            w0, w1 = self.win
            start = w0 if w1 >= self.known else self.known
            self.win = (max(start, b - WINDOW), b)  # what was read stays in RAM
            self.known = b

    def _shift(self, at, delta):
        if self.known > at:
            self.known += delta
        w0, w1 = self.win
        if w1 > at:
            self.win = (w0 if w0 <= at else w0 + delta, w1 + delta)

    def _put(self, at, f, o, n):
        """Insert piece (f, o, n) at document offset `at`."""
        out, pos = [], 0
        for pf, po, pn in self.pieces:
            if pos <= at < pos + pn and at > pos:
                k = at - pos
                out += [(pf, po, k), (f, o, n), (pf, po + k, pn - k)]
            elif at == pos and (f, o, n) not in out:
                out += [(f, o, n), (pf, po, pn)]
            else:
                out.append((pf, po, pn))
            pos += pn
        if at == pos and (f, o, n) not in out:
            out.append((f, o, n))
        self.pieces = out

    def _cut(self, a, b):
        out, pos = [], 0
        for f, o, n in self.pieces:
            lo, hi = max(a, pos), min(b, pos + n)
            if lo >= hi:
                out.append((f, o, n))
            else:
                if lo > pos:
                    out.append((f, o, lo - pos))
                if hi < pos + n:
                    out.append((f, o + hi - pos, pos + n - hi))
            pos += n
        self.pieces = out

    def _add(self, data):
        """Append to the add file; full records go to disk."""
        add = self.files["ADD"]
        o = len(add)
        add += data
        while (len(add) // 128) > self.add_written:
            if not self.add_made:
                self._call(0x16, "VIEDIT.ADD")
                self.add_made = True
            self.cpu += PT_CPU["rec"]
            self._call(0x22, "VIEDIT.ADD", self.add_written)
            self.add_written += 1
        return o

    def _verify(self):
        got = b"".join(bytes(self.files[f][o:o + n]) for f, o, n in self.pieces)
        assert got == self.text, "the pieces no longer spell the document"

    # -- the operations a key performs
    def op(self, o):
        kind = o[0]
        self.cpu += PT_CPU["key"]
        if kind == "goto":
            self.cpu += PT_CPU["move"] - PT_CPU["key"]
            off = self._line_off(o[1])
            if o[1] == "end" and self.lazy:
                self._show(len(self.text) - SCREEN, len(self.text))
            elif off >= self.known:
                self._count_to(off)
                self._show(off, off + SCREEN)
            elif not (self.win[0] <= off < self.win[1] - 200):
                self._show(off, off + SCREEN)
        elif kind == "x":
            at = self._line_off(o[1])
            self.undo = (list(self.pieces), bytes(self.text), self.known, self.win)
            self._cut(at, at + 1)
            del self.text[at]
            self._shift(at, -1)
        elif kind == "ins":
            at = self._line_off(o[1])
            self.undo = (list(self.pieces), bytes(self.text), self.known, self.win)
            ao = self._add(o[2])
            self._put(at, "ADD", ao, len(o[2]))
            self.text[at:at] = o[2]
            self._shift(at, len(o[2]))
        elif kind == "del":
            a = self._line_off(o[1])
            b = self._line_off(o[1] + o[2])
            self._count_to(b)                       # find where the span ends
            self.undo = (list(self.pieces), bytes(self.text), self.known, self.win)
            self._cut(a, b)
            del self.text[a:b]
            self.known -= b - a
            self.win = (a, a)
            self._show(a, a + SCREEN)
        elif kind == "wrange":
            a = self._line_off(o[1])
            b = self._line_off(o[2] + 1)
            self._count_to(b)
            self._call(0x13, o[3])
            self._call(0x16, o[3])
            r, seen = 0, set()
            for lo in range(a, b, BATCH):
                hi = min(b, lo + BATCH)
                self._read(lo, hi, seen=seen)
                for _ in range((hi - lo + 127) // 128):
                    self.cpu += PT_CPU["rec"]
                    self._call(0x22, o[3], r)
                    r += 1
            self._call(0x10, o[3])
            self.files[o[3]] = bytes(self.text[a:b])
        elif kind == "readin":
            at = self._line_off(o[1] + 1)
            src = self.files[o[2]]
            self._call(0x0F, o[2])
            self.undo = (list(self.pieces), bytes(self.text), self.known, self.win)
            ao, nrec = None, (len(src) + 127) // 128
            for r0 in range(0, nrec, BATCH // 128):         # read a batch,
                r1 = min(nrec, r0 + BATCH // 128)           # then append it
                for r in range(r0, r1):
                    self.cpu += PT_CPU["rec"]
                    self._call(0x21, o[2], r)
                o2 = self._add(src[r0 * 128:r1 * 128])
                ao = o2 if ao is None else ao
            self._put(at, "ADD", ao, len(src))
            self.text[at:at] = src
            self._shift(at, len(src))
            self.win = (at, at)
            self._show(at, at + SCREEN)
        elif kind == "save":
            self._save()
        elif kind == "quit":
            if self.add_made:
                self._call(0x13, "VIEDIT.ADD")
        elif kind == "undo":
            if self.undo:
                self.pieces, t, self.known, self.win = self.undo
                self.text = bytearray(t)
        self._verify()

    def _save(self):
        self._call(0x13, "TEST.$$$")
        self._call(0x16, "TEST.$$$")
        n = len(self.text)
        r, seen = 0, set()
        for lo in range(0, n, BATCH):
            hi = min(n, lo + BATCH)
            self._read(lo, hi, seen=seen)
            for _ in range((hi - lo + 127) // 128):
                self.cpu += PT_CPU["rec"]
                self._call(0x22, "TEST.$$$", r)
                r += 1
        self._call(0x10, "TEST.$$$")
        self._call(0x13, "TEST.BAK")
        self._call(0x17, "TEST.TXT", 0, "TEST.BAK")
        self._call(0x17, "TEST.$$$", 0, "TEST.TXT")
        self._call(0x0F, "TEST.TXT")
        if self.add_made:
            self._call(0x13, "VIEDIT.ADD")
        self.files = {"TEST.TXT": bytes(self.text), "ADD": bytearray()}
        self.pieces = [("TEST.TXT", 0, n)] if n else []
        self.add_written, self.add_made = 0, False
        self.known = n
        self.undo = None


# ------------------------------------------------------------------- report

def price(calls_per_key, nrec, bios_cls, cpu):
    """Run keys' calls through a fresh disk; per key (seconds, counts)."""
    disk = Disk(bios_cls, [("TEST.TXT", nrec)], cpu)
    disk.fcb["TEST.TXT"] = [0, False]              # the open left it open
    out = []
    for calls, tail in calls_per_key:
        t0 = disk.d.t
        c0 = collections.Counter(disk.counts)
        s0, k0 = disk.d.seeks, (disk.bios.reads, disk.bios.writes)
        editor = tail
        for cpu_before, fn, name, rec, new in calls:
            disk.d.t += cpu_before
            editor += cpu_before
            disk.call(fn, name, rec, new)
        disk.d.t += tail
        disk.idle()
        c = collections.Counter(disk.counts)
        c.subtract(c0)
        out.append({"s": disk.d.t - t0, "editor": editor, "counts": +c,
                    "seeks": disk.d.seeks - s0,
                    "bios": (disk.bios.reads - k0[0], disk.bios.writes - k0[1])})
    return out, disk.peak * BLKRECS * 128 // 1024


def show_counts(c):
    keep = {k: v for k, v in c.items() if k[:2] in ("r ", "w ")}
    return ", ".join("%s %d" % (k, v) for k, v in sorted(keep.items())) or "none"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--trace", default=os.path.join(HERE, "pagertrace.jsonl.gz"))
    ap.add_argument("--bios", choices=["buffered", "sector", "both"], default="both")
    ap.add_argument("--keys", action="store_true")
    ap.add_argument("--lazy", action="store_true")
    ap.add_argument("--scan-ms", type=float)
    a = ap.parse_args()
    if a.scan_ms is not None:
        PT_CPU["count"] = a.scan_ms / 1000 - PT_CPU["rec"]

    traces = load_traces(a.trace)
    check_traces(traces)
    cpu = bdos_cpu(traces)
    bioses = {"buffered": [BufferedBIOS], "sector": [SectorBIOS],
              "both": [BufferedBIOS, SectorBIOS]}[a.bios]
    print("trace %s: matches PAGING.md's counts" % os.path.basename(a.trace))
    print("BDOS+BIOS CPU per call, measured: read %.1f ms, write %.1f ms" % (
        cpu["r"] * 1000, cpu["w"] * 1000))
    print("ASSUMED: step %d ms, settle %d ms, head load %d ms; piece table CPU %s" % (
        STEP * 1000, SETTLE * 1000, HEADLOAD * 1000,
        ", ".join("%s %g ms" % (k, v * 1000) for k, v in PT_CPU.items())))
    print()

    names = [n for n in SCENARIOS if not a.names or n in a.names]
    totals = collections.defaultdict(float)
    for name in names:
        content, labels, ops = SCENARIOS[name]
        data = b"".join(content)
        nrec = (len(data) + 127) // 128
        keys = traces[name]
        assert [k["key"] for k in keys] == labels, (name, [k["key"] for k in keys])
        wm = [wm_calls(k) for k in keys]

        pt = PieceTable(data, a.lazy)
        ptk = []
        for o in ops:
            pt.op(o)
            calls, pt.calls = pt.calls, []
            ptk.append((calls, pt.cpu))
            pt.cpu = 0.0
        if any(o[0] == "save" for o in ops):
            ok = bytes(pt.text) == b"".join(expected(name))
            assert ok, "%s: the piece table's text is not the expected edit" % name

        print("## %s: %s" % (name, " ".join(labels)))
        rows = []
        for bc in bioses:
            w, wpeak = price(wm, nrec, bc, cpu)
            p, ppeak = price(ptk, nrec, bc, cpu)
            rows.append((bc.name, w, wpeak, p, ppeak))
        hdr = "  %-20s %8s" % ("key", "sim WM")
        for bname, *_ in rows:
            hdr += " | %-8s %8s %8s" % (bname, "WM", "piece")
        print(hdr)
        sim_total = 0.0
        for i, lab in enumerate(labels):
            sim_total += keys[i]["seconds"]
            if a.keys:
                line = "  %-20s %7.1fs" % (lab, keys[i]["seconds"])
                for bname, w, _, p, _ in rows:
                    line += " | %-8s %7.1fs %7.1fs" % ("", w[i]["s"], p[i]["s"])
                print(line)
        line = "  %-20s %7.1fs" % ("total", sim_total)
        for bname, w, wpeak, p, ppeak in rows:
            ws, ps = sum(k["s"] for k in w), sum(k["s"] for k in p)
            line += " | %-8s %7.1fs %7.1fs" % ("", ws, ps)
            totals[(bname, "WM")] += ws
            totals[(bname, "piece")] += ps
        totals["sim"] += sim_total
        print(line)
        we = sum(k["editor"] for k in rows[0][1])
        pe = sum(k["editor"] for k in rows[0][3])
        totals["WM editor"] += we
        totals["piece editor"] += pe
        print("  %-20s %7s  | %-8s %7.1fs %7.1fs   (the editor's own CPU, in every total)" % (
            "editor CPU", "", "", we, pe))
        for bname, w, wpeak, p, ppeak in rows[:1]:
            for i, lab in enumerate(labels):
                if a.keys:
                    print("    %-18s WM: %s" % (lab, show_counts(w[i]["counts"])))
                    print("    %-18s piece: %s" % ("", show_counts(p[i]["counts"])))
            print("  disk used at most: WM %d K, piece table %d K (of 300 K)" % (wpeak, ppeak))
        print()

    print("## all scenarios")
    line = "  %-20s %7.1fs" % ("total", totals["sim"])
    for bc in bioses:
        line += " | %-8s %7.1fs %7.1fs" % (bc.name, totals[(bc.name, "WM")],
                                           totals[(bc.name, "piece")])
    print(line)
    print("  %-20s %7s  | %-8s %7.1fs %7.1fs" % ("editor CPU", "", "",
                                              totals["WM editor"], totals["piece editor"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
