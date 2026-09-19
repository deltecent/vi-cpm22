#!/usr/bin/env python3
"""What each keystroke costs the console, in characters -- which IS the clock.

The interactive machine (altairsim.toml) straps the 2SIO console at 9600 baud,
so the guest emits 960 characters a second and a 23-row repaint -- about 1500
characters -- is **1.6 seconds of watching the screen fill**.  Next to that the
8080's own work at 2 MHz is noise: gap arithmetic, CHARAT per byte, TAILTAB's
scan are all microseconds.  So the speed of this editor is not how fast it
computes, it is how few characters it agrees to send, and that is what this
script measures.

It is a GUARD as much as a report.  Every case carries the budget its paint
should fit in; a change that silently drops a command back to the full repaint
(by not lowering RINTENT, or by tripping one of SC_ED's gates) blows the budget
by an order of magnitude and this exits non-zero.  The budgets are loose --
several times the measured cost -- because the point is to catch a 1500, not to
freeze a 98 at 98.

    python3 paintcost.py               # every case
    python3 paintcost.py insert put    # only cases whose name matches
    python3 paintcost.py --record      # print the table as measured, no verdict

Build first: python3 build_vi.py VI

The measurement needs no harness of its own -- smoke_vi's Editor already
accumulates everything the guest draws in ed.cap, so a keystroke's cost is the
length that string grows by.  Cases run one per simulator, like the accept
suite; this is a few minutes, not twelve.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Keep the work disks out of the repo: smoke_vi clears WORK at import, which
# must never happen under a battery that is already running.
os.environ.setdefault("VI_WORK", os.path.join(HERE, "_paintcost_work"))

from smoke_vi import Editor                                # noqa: E402

BAUD_CPS = 960.0                        # 9600 8N1 -- altairsim.toml's strap
FULL = 1450                             # about what a 23-row repaint costs

# The file most cases run on: a full screen and more, every line inside the
# window so nothing pans.  The lines are long on purpose -- a repaint costs a
# row's worth of text per row, so on a file of short lines even the full
# repaint is cheap and the budgets below would have nothing to catch.
PLAIN = "".join("L%03d " % i + "word wordy words " * 3 + "\r\n"
                for i in range(40)).encode()
# ... and one whose lines run off the right edge, because a paint that is right
# only for lines that fit is not right (see the accept suite's own wide files).
WIDE = "".join("L%03d " % i + "wide " * 30 + "\r\n" for i in range(40)).encode()

# (name, file, keys to set up, the key measured, budget in characters)
# budget None = recorded only: these repaint by decision, not by oversight.
CASES = [
    ("motion-j",        PLAIN, ["10j"],            "j",   60),
    ("insert-char",     PLAIN, ["10j", "5l", "i"], "X",   80),
    ("insert-bs",       PLAIN, ["10j", "5l", "i", "XY"], "\b", 300),
    ("insert-cr",       PLAIN, ["10j", "5l", "i"], "\r",  300),
    ("insert-cr-bottom", PLAIN, ["G", "i"],        "\r",  300),
    ("open-o",          PLAIN, ["10j"],            "o",   300),
    ("open-o-bottom",   PLAIN, ["G"],              "o",   300),
    ("open-O",          PLAIN, ["10j"],            "O",   300),
    ("delete-x",        PLAIN, ["10j", "5l"],      "x",   250),
    ("delete-x-wide",   WIDE,  ["10j", "5l"],      "x",   300),
    ("delete-dw",       PLAIN, ["10j", "5l"],      "dw",  300),
    ("change-cw",       PLAIN, ["10j", "5l"],      "cw",  350),
    ("delete-D",        PLAIN, ["10j", "5l"],      "D",   250),
    ("delete-dd",       PLAIN, ["10j"],            "dd",  350),
    ("join-J",          PLAIN, ["10j"],            "J",   450),
    ("join-J-bottom",   PLAIN, ["G", "k"],         "J",   350),
    ("put-p",           PLAIN, ["10j", "yy"],      "p",   300),
    ("put-P",           PLAIN, ["10j", "yy"],      "P",   300),
    ("put-p-3lines",    PLAIN, ["10j", "3yy"],     "p",   450),
    ("put-2p",          PLAIN, ["10j", "yy"],      "2p",  450),
    ("undo-u",          PLAIN, ["10j", "5l", "x"], "u",   None),
    ("redraw-ctrl-L",   PLAIN, ["10j"],            "\x0c", None),
]


def measure(case):
    name, content, setup, key, budget = case
    ed = Editor(content)
    try:
        for k in setup:
            ed.key(k)
        before = len(ed.cap.getvalue())
        ed.key(key)
        return len(ed.cap.getvalue()) - before
    finally:
        ed.close()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    record = "--record" in sys.argv
    cases = [c for c in CASES if not args or any(a in c[0] for a in args)]
    if not cases:
        print("no case matches %s" % " ".join(args))
        return 1

    print("keystroke cost at %d characters/second (24x80)" % BAUD_CPS)
    print()
    over = []
    for case in cases:
        name, _, _, _, budget = case
        n = measure(case)
        secs = n / BAUD_CPS
        if budget is None:
            verdict = "repaints by decision" if n >= FULL else ""
        elif n > budget:
            verdict = "OVER BUDGET %d" % budget
            over.append((name, n, budget))
        else:
            verdict = ""
        print("  %-18s %6d chars  %5.2f s   %s" % (name, n, secs, verdict))

    print()
    if record:
        print("recorded only (--record): no verdict")
        return 0
    if over:
        print("%d case(s) over budget -- a paint has fallen back to the full"
              " repaint:" % len(over))
        for name, n, budget in over:
            print("    %-18s %d chars, budget %d" % (name, n, budget))
        return 1
    print("all %d case(s) within budget" % len(cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
