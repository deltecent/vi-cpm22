#!/usr/bin/env python3
"""What the pager does, scenario by scenario, read out of the running editor.

    python3 pagerprobe.py              # every scenario
    python3 pagerprobe.py top mid      # only scenarios whose name matches
    python3 pagerprobe.py --list       # the scenario names
    python3 pagerprobe.py --log=F.json # also record every disk call, timed
    python3 pagerprobe.py browse --trace   # every disk call, in runs

PAGING.md's figures are this script's output, transcribed.  Each scenario is a fresh editor
on a test file, a list of keys, and after each key: the window (the pointer
row), the work-file record marks, and every disk call the key made, counted
by catching the BDOS entry (a conditional breakpoint at 0005H, so nothing in
the editor is changed to count it).  A scenario that saves reads the file back
through the guest and checks it byte for byte against what the edits should
have made.

The seconds are the simulator's clock, less what finding the guest idle
costs; the simulated drive has no seek or rotation time, so they are a floor.
`--log` writes, per key, each disk call with the simulator time it was made
at, the file and the record: `pagermodel.py` prices those on a floppy.

Build first: python3 build_vi.py VI.  Never run this beside a test battery.
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_ARGS = [a for a in sys.argv[1:] if not a.startswith("-")]
SANDBOX = os.path.join(HERE, "_pagerprobe" + ("_" + "_".join(_ARGS) if _ARGS else ""))

shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX)
for _f in ("vi.toml", "VI.COM"):
    shutil.copy(os.path.join(HERE, _f), SANDBOX)
os.environ["VI_SIMDIR"] = SANDBOX
os.environ.pop("VI_WORK", None)
sys.path.insert(0, HERE)

from smoke_vi import Editor, SYM                           # noqa: E402

CLOCK_HZ = 2e6
TRACE = "--trace" in sys.argv
LOG = next((a[6:] for a in sys.argv if a.startswith("--log=")), None)
ESC, CR = "\x1b", "\r"


def lines(n):
    """n lines of 8 bytes: '000001' CR LF ... -- line k starts at 8*(k-1)."""
    return [b"%06d\r\n" % i for i in range(1, n + 1)]


BIG = lines(10240)              # 81,920 bytes, 640 records
SMALL = lines(1280)             # 10,240 bytes, 80 records

FN = {0x0F: "open", 0x10: "close", 0x13: "delete", 0x14: "read",
      0x15: "write", 0x16: "make", 0x17: "rename", 0x21: "rread",
      0x22: "rwrite", 0x23: "size", 0x24: "setrr"}


def fcbfile(f):
    """The 8.3 name an FCB's 36 bytes name, as 'NAME.TYP'."""
    n = bytes(b & 0x7F for b in f[1:9]).decode().strip()
    t = bytes(b & 0x7F for b in f[9:12]).decode().strip()
    return n + "." + t


def fcbrec(fn, f):
    """The record a read or write names: the random record for 21H-24H, else
    the sequential position S2/EX/CR."""
    if fn >= 0x21:
        return f[33] | f[34] << 8 | f[35] << 16
    return (f[14] & 0x3F) * 4096 + (f[12] & 0x1F) * 128 + f[32]


def fcbname(de):
    if de == 0x5C:
        return "TEST.TXT"
    if de == SYM["OUTFCB"]:
        return "TEST.$$$"
    if de == SYM["BAKFCB"]:
        return "VIBACKUP.$$$"
    return "FCB %04XH" % de


# ---------------------------------------------------------------- the guest

class Probe:
    def __init__(self, content):
        self.e = Editor(content)
        self.io = {}
        self.trace = []
        self.t = 0                      # T-states run since the key was typed
        self.events = []
        self.mon("BREAK 0005 IF C >= 00F && C <= 024 && C != 01A")
        t = self.clock()
        self.settle()
        self.idle = self.clock() - t

    def close(self):
        self.e.close()

    def mon(self, command):
        raw = self.e.s._rpc("tools/call", {"name": "monitor",
                                           "arguments": {"command": command}})
        return "".join(b.get("text", "") for b in raw.get("content", []))

    def clock(self):
        return int(re.search(r"\((\d+) T-states\)",
                             self.mon("SHOW CLOCK")).group(1))

    def _bdos(self):
        r = self.e.s._tool("regs")["registers"]
        key = (FN.get(r["C"], "%02XH" % r["C"]), fcbname(r["DE"]))
        self.io[key] = self.io.get(key, 0) + 1
        if LOG:
            f = self.e.s.mem(r["DE"], 36)
            ev = [self.t, r["C"], fcbfile(f), fcbrec(r["C"], f)]
            # Run the call to its return, so the log separates the time the
            # editor spends between calls from the time BDOS and the BIOS take.
            m = self.e.s.mem(r["SP"], 2)
            ret, t0 = m[0] | m[1] << 8, self.t
            bp = re.search(r"breakpoint (\d+)", self.mon("BREAK %04X" % ret)).group(1)
            while True:
                q = self.e.s._run()
                self.t += q.get("t_states", 0)
                if q.get("stopped") == "breakpoint" and q.get("pc") == ret:
                    break
            self.mon("NOBREAK " + bp)
            ev.append(self.t - t0)
            if r["C"] == 0x17:                      # rename: the new name too
                ev.append(fcbfile(f[16:]))
            self.events.append(ev)
        if TRACE:
            m = self.e.s.mem(SYM["TXTBEG"], 8)
            tb, gb, ge, te = (m[i] | m[i + 1] << 8 for i in (0, 2, 4, 6))
            self.trace.append((key, (gb - tb) + (te - ge), gb - tb, tb, te))

    def settle(self, confirms=4, slices=200000):
        idle = 0
        for _ in range(slices):
            r = self.e.s._run()
            self.t += r.get("t_states", 0)
            if r.get("stopped") == "breakpoint":
                self._bdos()
                idle = 0
            elif r.get("stopped") == "idle" and not r.get("output"):
                idle += 1
                if idle >= confirms:
                    return
            else:
                idle = 0
        raise RuntimeError("the guest never came back to the keyboard")

    def bottom(self):
        return "".join(self.e.screen().screen[23]).strip()

    def key(self, k):
        """Type k and wait; (seconds, disk calls) it cost."""
        self.io = {}
        self.trace = []
        self.events = []
        self.t = 0
        was = self.bottom() if k == ESC else None
        t = self.clock()
        self.e.s.send(k)
        self.settle()
        waits = 1
        for _ in range(50):                 # an ESC ending an insert: wait
            if was is None or self.bottom() != was:   # for the mode message
                break
            self.settle()
            waits += 1
        took = max(self.clock() - t - self.idle * waits, 0) / CLOCK_HZ
        return took, dict(self.io)

    def word(self, name, off=0):
        m = self.e.s.mem(SYM[name] + off, 2)
        return m[0] | m[1] << 8

    def byte(self, name):
        return self.e.s.mem(SYM[name], 1)[0]

    def state(self):
        w = self.word
        tb, gb, ge, te, be = (w(n) for n in
                              ("TXTBEG", "GAPBEG", "GAPEND", "TXTEND", "BUFEND"))
        before = bytes(self.e.s.mem(tb, gb - tb)) if gb > tb else b""
        lf = before.count(b"\n")
        return {
            "resident": (gb - tb) + (te - ge), "before": gb - tb,
            "after": te - ge, "gap": ge - gb, "abovetop": be - te,
            "line": w("TOPLF") + lf + 1,
            "out_at": w("OUTFCB", 0x22), "outhi": w("OUTHI"),
            "outrec": w("OUTREC"), "outpos": w("OUTPOS"),
            "src_at": (lambda m: m[0] | m[1] << 8)(self.e.s.mem(0x7E, 2)),
            "srcrdy": self.e.s.mem(0x5B, 1)[0] != 0,
            "bak_at": w("BAKFCB", 0x22), "bakpos": w("BAKPOS"),
            "bakrdy": self.byte("BAKRDY") != 0,
            "srcrec": w("SRCREC"), "bakrec": w("BAKREC"),
            "pgtopm": w("PGTOPM"), "toplf": w("TOPLF"),
            "msg": self.bottom(),
        }

    def saved(self):
        """The file on disk, read back through the guest (quits the editor)."""
        return self.e.diskfile("TEST", "TXT")


# ---------------------------------------------------------------- scenarios
# (name, title, file lines, keys, the file a save should leave or None)

def drop(ls, i, n):
    return ls[:i] + ls[i + n:]


def x_at(ls, i):
    return ls[:i] + [ls[i][1:]] + ls[i + 1:]


SCENARIOS = [
    ("small", "a file that fits: 10 K, `G`, `gg`, `x`, `:w`", SMALL,
     ["G", "gg", "x", ":w" + CR], x_at(SMALL, 0)),
    ("browse", "80 K, unchanged: `G`, `gg`, `G`, `:q!`", BIG,
     ["G", "gg", "G", ":q!" + CR], None),
    ("savenone", "80 K, unchanged: `:w` from the top", BIG,
     [":w" + CR], BIG),
    ("saveback", "80 K, unchanged: `G`, `gg`, `:w`", BIG,
     ["G", "gg", ":w" + CR], BIG),
    ("endedit", "80 K, edit at the end: `G`, `x`, `gg`, `G`, `:w`", BIG,
     ["G", "x", "gg", "G", ":w" + CR], x_at(BIG, 10239)),
    ("topedit", "80 K, edit at the top: `x`, `G`, `gg`, `:w`", BIG,
     ["x", "G", "gg", ":w" + CR], x_at(BIG, 0)),
    ("midedit", "80 K, insert in the middle: `5000G`, `ihello<Esc>`, `gg`, `G`, `:w`", BIG,
     ["5000G", "ihello", ESC, "gg", "G", ":w" + CR],
     BIG[:4999] + [b"hello" + BIG[4999]] + BIG[5000:]),
    ("twoedit", "80 K, two edits: `2000G`, `x`, `8000G`, `x`, `gg`, `G`, `:w`", BIG,
     ["2000G", "x", "8000G", "x", "gg", "G", ":w" + CR], x_at(x_at(BIG, 1999), 7999)),
    ("local", "80 K, moving near the cursor: `6000G`, `6100G`, `5900G`, `^F`, `^B`, `100G`", BIG,
     ["6000G", "6100G", "5900G", "\x06", "\x02", "100G"], None),
    ("bigdd", "80 K, a `dd` the register cannot hold: `100G`, `3000dd`, `:w`", BIG,
     ["100G", "3000dd", ":w" + CR], BIG),
    ("bigdel", "80 K, delete bigger than memory: `100G`, `d3099G`, `:w`", BIG,
     ["100G", "d3099G", ":w" + CR], drop(BIG, 99, 3000)),
    ("bigput", "80 K, insert bigger than memory: `6000G`, `:6000,9000w T.TXT`, `100G`, `:r T.TXT`, `:w`", BIG,
     ["6000G", ":6000,9000w T.TXT" + CR, "100G", ":r T.TXT" + CR, ":w" + CR],
     BIG[:100] + BIG[5999:9000] + BIG[100:]),
    ("undo", "80 K, undo after paging: `G`, `x`, `gg`, `G`, `u`", BIG,
     ["G", "x", "gg", "G", "u"], None),
]

FIELDS = ("resident", "before", "after", "gap", "abovetop", "line",
          "out_at", "outhi", "outrec", "src_at", "srcrdy", "bak_at", "bakpos",
          "bakrdy", "srcrec", "bakrec", "pgtopm", "msg")


def show_io(io):
    if not io:
        return "none"
    order = sorted(io.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    return ", ".join("%s %s x%d" % (f, n, c) for (f, n), c in order)


def show_trace(tr):
    """Runs of the same disk call, with the window size across each run."""
    i = 0
    while i < len(tr):
        j = i
        while j + 1 < len(tr) and tr[j + 1][0] == tr[i][0]:
            j += 1
        (f, n), r0, b0 = tr[i][0], tr[i][1], tr[i][2]
        r1, b1 = tr[j][1], tr[j][2]
        print("      %-6s %-12s x%-4d resident %5d -> %5d  before cursor %5d -> %5d" % (
            f, n, j - i + 1, r0, r1, b0, b1), flush=True)
        i = j + 1


def logged(name, label, took, events):
    """One key's disk calls, as a JSON line: [seconds into the key, BDOS
    function, file, record, seconds the call took, (rename) new name]."""
    import json
    with open(LOG, "a") as f:
        f.write(json.dumps({"scenario": name, "key": label, "seconds": took,
                            "events": [[e[0] / CLOCK_HZ] + e[1:4] + [e[4] / CLOCK_HZ] + e[5:]
                                       for e in events]})
                + "\n")


def run(scn):
    name, title, content, keys, want = scn
    data = b"".join(content)
    print("## %s -- %s" % (name, title), flush=True)
    print("file %d bytes, %d records, %d lines" % (
        len(data), (len(data) + 127) // 128, len(content)), flush=True)
    p = Probe(data)
    try:
        s = p.state()
        print("  %-22s %s" % ("open", " ".join("%s=%s" % (f, s[f]) for f in FIELDS)),
              flush=True)
        for k in keys:
            took, io = p.key(k)
            s = p.state() if not k.startswith(":q") else {}
            label = repr(k)[1:-1].replace("\\x1b", "<Esc>").replace("\\r", "")
            if LOG:
                logged(name, label, took, p.events)
            print("  %-22s %.1f s | io: %s" % (label, took, show_io(io)), flush=True)
            if TRACE:
                show_trace(p.trace)
            if s:
                print("  %-22s %s" % ("", " ".join("%s=%s" % (f, s[f]) for f in FIELDS)),
                      flush=True)
        if want is not None:
            got = p.saved()
            ok = got.rstrip(b"\x1a") == b"".join(want)
            print("  saved file: %d bytes, %s" % (
                len(got.rstrip(b"\x1a")), "MATCHES the expected edit" if ok
                else "DIFFERS from the expected edit"), flush=True)
    finally:
        p.close()
    print(flush=True)


def main():
    if "--list" in sys.argv:
        for s in SCENARIOS:
            print(s[0], "--", s[1])
        shutil.rmtree(SANDBOX, ignore_errors=True)
        return 0
    todo = [s for s in SCENARIOS if not _ARGS or any(a == s[0] for a in _ARGS)]
    for s in todo:
        run(s)
    shutil.rmtree(SANDBOX, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
