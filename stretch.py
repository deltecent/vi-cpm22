#!/usr/bin/env python3
"""How long the editor goes without looking at the console, while it pages.

    python3 stretch.py                 # every row, 100 K of 8-byte lines
    python3 stretch.py --wide          # the same rows on 80-byte lines
    python3 stretch.py gg              # only rows whose name matches
    python3 stretch.py --profile       # and where the CPU is in the long ones
    python3 stretch.py --check 50      # exit 1 if a stretch in the editor's
                                       #   own code is over 50 ms

A 2SIO with no flow control holds one received byte.  If a second key
arrives before the program reads the first, one of them is lost (#30).  At
9600 baud a fast typist's keys are some 50-100 ms apart, so the editor must
read the console at least that often, even in the middle of a 30-second
move.  It reads it through the BIOS, which tests the 2SIO's status port
(10H) first.

So a breakpoint on every read of port 10H (`BREAK IO R 10`) splits the run
into stretches, and the simulator's `run` reports the T-states of each
one.  A stretch is the time from one status read to the next.  The status
port is also read by CONOUT before each character it sends, which does not
take a waiting key; but a long command sends nothing while it pages, so the
long stretches are the ones that matter.

With --profile, the run is also stopped every 20,000 instructions, and the
PC of each stop is booked to the stretch it falls in, mapped to the
nearest label in the .PRN listings (or to the BDOS or BIOS).  Each stretch
over the limit is then booked whole to the code most of its samples are
in, and the line under the row gives, per owner, how many stretches and the longest.  A
stretch owned by the BDOS or BIOS is one disk call: the editor cannot read
the console in the middle of it.

Each row is a fresh editor.  The keys before the measured ones are typed
with no breakpoint set.  The measured keys end when the editor waits in the
BIOS for the next key.  Seconds are the simulator's clock at 2 MHz.

--check implies --profile and fails only on the stretches booked to the
editor's own code; those in one BDOS or BIOS call are reported, not failed.
Measured on the simulator's 8 MB drive: a BDOS Open of the next extent
(function 15, which WordMaster's paging calls itself) searches the whole
directory, about 0.65 s; a sequential read can take 176 ms; the close,
delete and rename of a `:w` up to 6.3 s.  No program can read the console
in the middle of one.

Build first: python3 build_vi.py VI.  Never run this beside a test battery.
"""
import bisect
import collections
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX = os.path.join(HERE, "_stretch")

# A sandbox of its own, as timecost.py has: it must exist before smoke_vi is
# imported.
shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX)
for _f in ("vi.toml", "VI.COM"):
    shutil.copy(os.path.join(HERE, _f), SANDBOX)
os.environ["VI_SIMDIR"] = SANDBOX
os.environ.pop("VI_WORK", None)
sys.path.insert(0, HERE)

from smoke_vi import Editor, SYM                           # noqa: E402
import covmap                                              # noqa: E402

CLOCK_HZ = 2e6
SAMPLE = 20000          # instructions between --profile samples
DISK = ("BDOS", "BIOS")   # owners whose stretches are one disk call
IDLE_T = 40000          # T-states of tight polling that mean "waiting"
ESC, CR = "\x1b", "\r"


def big(width):
    """About 100 K of lines *width* bytes long, CR LF included."""
    n = 102400 // width
    pad = width - 8
    return b"".join(b"%06d" % i + b"x" * pad + b"\r\n"
                    for i in range(1, n + 1))


# (name, keys typed first, keys measured)
ROWS = [
    ("G from the top", [], ["G"]),
    ("gg from the end", ["G"], ["gg"]),
    ("G again, after G gg", ["G", "gg"], ["G"]),
    ("100G from the end", ["G"], ["100G"]),
    (":w after x at the end", ["G", "x"], [":w" + CR]),
    ("/zzzz from 6000, missed", ["6000G"], ["/zzzz" + CR]),
    ("?000100 from 6000", ["6000G"], ["?000100" + CR]),
]


def mon(e, command):
    raw = e.s._rpc("tools/call", {"name": "monitor",
                                  "arguments": {"command": command}})
    return "".join(b.get("text", "") for b in raw.get("content", []))


def settle(e, confirms=4, slices=20000):
    """Run until the guest waits on the keyboard (as timecost.py does)."""
    idle = 0
    for _ in range(slices):
        r = e.s._run()
        if r.get("stopped") == "idle" and not r.get("output"):
            idle += 1
            if idle >= confirms:
                return
        else:
            idle = 0
    raise RuntimeError("the guest never came back to the keyboard")


class Where:
    """PC -> the name of the code it is in."""

    def __init__(self, e):
        # Every label in the .PRN listings, not only the publics: a loop
        # in a routine's private part is booked to its own label.
        names = dict(SYM)
        pub, img = covmap.publics(), covmap.image()
        for m in covmap.MODS + ["RSV"]:
            names.update(covmap.read_module(m, pub, img)[1])
        pub = sorted((a, n) for n, a in names.items())
        self.addr = [a for a, _ in pub]
        self.name = [n for _, n in pub]
        m = e.s.mem(0, 8)
        self.bios = (m[1] | m[2] << 8) - 3          # the jump at 0000H
        self.bdos = m[6] | m[7] << 8                # the jump at 0005H

    def __call__(self, pc):
        if pc >= self.bios:
            return "BIOS"
        if pc >= self.bdos - 6:
            return "BDOS"
        i = bisect.bisect_right(self.addr, pc) - 1
        return self.name[i] if i >= 0 else "%04XH" % pc


def stretches(e, keys, profile):
    """The stretches of *keys*, as [(T-states, Counter of samples)]."""
    # Where the guest waits for a key: the PC its status reads stop at once
    # it is idle in the BIOS.
    mon(e, "BREAK IO R 10")
    idle_pc = collections.Counter(e.s._run()["pc"] for _ in range(20))
    idle_pc = idle_pc.most_common(1)[0][0]
    out = []
    for k in keys:
        e.s.send(k)
    cur_t, cur_s = 0, collections.Counter()
    at_idle = 0
    args = {"timeout_ms": 2000}
    if profile:
        args["max_steps"] = SAMPLE
    where = Where(e) if profile else None
    while True:
        r = e.s._tool("run", args)
        e.s._tee(r.get("output", ""))
        cur_t += r.get("t_states", 0) or 0
        if r.get("stopped") == "breakpoint":
            out.append((cur_t, cur_s))
            cur_t, cur_s = 0, collections.Counter()
            # Waiting: tight polls at the idle PC.  Keys arrive at 9600
            # baud, about 1 ms apart, so only 20 ms of nothing else ends it.
            if r["pc"] == idle_pc and r.get("steps", 99) <= 10:
                at_idle += out[-1][0]
                if at_idle >= IDLE_T:
                    break
            else:
                at_idle = 0
        elif r.get("stopped") in ("halt", "interrupted", "unclaimed"):
            raise RuntimeError("the guest stopped: %r" % r)
        elif profile:
            cur_s[where(r["pc"])] += 1
    mon(e, "NOBREAK")
    while out and out[-1][0] < 100:
        out.pop()                       # the wait for the next key
    return out


def ms(t):
    return t / CLOCK_HZ * 1000


def measure(text, setup, keys, profile, limit):
    e = Editor(text)
    try:
        for k in setup:
            e.s.send(k)
            settle(e)
        st = stretches(e, keys, profile)
    finally:
        e.close()
    total = sum(t for t, _ in st)
    longs = [s for s in st if ms(s[0]) > limit]
    top = sorted((t for t, _ in st), reverse=True)[:5]
    line = "%6.1f s  %5d reads  %3d over %d ms  longest %s" % (
        total / CLOCK_HZ, len(st), len(longs), limit,
        " ".join("%.0f" % ms(t) for t in top))
    # Each long stretch is booked whole to the code most of its samples
    # are in: (stretches, the longest in ms) per owner.
    where = {}
    for t, s in longs:
        own = s.most_common(1)[0][0] if s else "?"
        n, top_ms = where.get(own, (0, 0))
        where[own] = (n + 1, max(top_ms, ms(t)))
    mine = sum(n for w, (n, _) in where.items() if w not in DISK)
    return line, mine, where


def main(argv):
    profile = "--profile" in argv or "--check" in argv
    wide = "--wide" in argv
    limit = 50
    check = False
    names = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--check":
            check = True
            limit = int(argv[i + 1])
            i += 1
        elif not a.startswith("--"):
            names.append(a)
        i += 1
    text = big(80 if wide else 8)
    print("%d bytes of %d-byte lines; limit %d ms" % (
        len(text), 80 if wide else 8, limit), flush=True)
    bad = 0
    for name, setup, keys in ROWS:
        if names and not any(n in name for n in names):
            continue
        line, over, where = measure(text, setup, keys, profile, limit)
        bad += over
        print("%-24s %s" % (name, line), flush=True)
        if profile and where:
            print("    " + "  ".join(
                "%s %d (%.0f ms)" % (w, n, t)
                for w, (n, t) in sorted(where.items(),
                                         key=lambda x: -x[1][0])),
                  flush=True)
    if check and not bad:
        print("OK: no stretch in the editor's code over %d ms" % limit)
    if check and bad:
        print("FAIL: %d stretches in the editor's code over %d ms"
              % (bad, limit))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
