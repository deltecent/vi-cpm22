#!/usr/bin/env python3
"""MOTION battery -- checks every landing offset of the motion set.

MOTTST.MAC walks the cursor through l w w $ 0 e j j k G gg W b h /def n, some
counted motions, H M L and the scrolls over a fixed 3-line file and snapshots
(TOFF,TLINE,TCOL) after each motion. This driver compares every snapshot
against the expected vi landing.

Build first:   python3 build_vi.py MOTTST
Then run:      python3 mottst.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcpdrive import AltairSim

MACHINE = "vi.toml"
DISK = "CPM22-8MB-56K-VI.DSK"
EOF = 0x1A
NAME = "MOTIN.TXT"

# Line 2 carries nested brackets (a(b[c]d)e) from when this battery still had a
# '%' to check; it stays because every landing below is measured against it.
FILE = "abc def ghi\r\njklmno\r\na(b[c]d)e\r\n"

# (label, expected offset, expected line, expected col) after each motion.
EXPECT = [
    ("l",   1, 0, 1),
    ("w",   4, 0, 4),
    ("w",   8, 0, 8),
    ("$",  10, 0, 10),
    ("0",   0, 0, 0),
    ("e",   2, 0, 2),
    ("j",  15, 1, 2),
    ("j",  23, 2, 2),
    ("k",  15, 1, 2),
    ("G",  21, 2, 0),
    ("gg",  0, 0, 0),
    ("W",   4, 0, 4),
    ("b",   0, 0, 0),
    ("h",   0, 0, 0),
    ("/def", 4, 0, 4),
    ("n",   4, 0, 4),
    ("3l",  7, 0, 7),
    ("2w", 13, 1, 0),
    ("^",  13, 1, 0),
    ("B",   8, 0, 8),
    # screen-relative H/M/L with stubbed NEDIT=3, WINROW=0 over the 3 lines
    ("gg",   0, 0, 0),   # reset
    ("H",    0, 0, 0),   # top line
    ("2H",  13, 1, 0),   # 2nd from top
    ("L",   21, 2, 0),   # bottom visible line
    ("2L",  13, 1, 0),   # 2nd from bottom
    ("M",   13, 1, 0),   # middle of [0..2]
    ("3L",   0, 0, 0),   # floored at top
    ("5H",  21, 2, 0),   # clamps at last line
    # scrolls (stub NEDIT=3, SCEOF=SCBOF=1): ^F -> the last line (on screen, so
    # vim makes it the top line); ^B no-op; ^D/^U step one line
    ("gg",   0, 0, 0),   # reset
    ("^F",  21, 2, 0),   # last line (row SCBOT=2) becomes the top line
    ("^D",  21, 2, 0),   # cursor down NEDIT/2 = 1 line
    ("^B",  21, 2, 0),   # first line at top -> no-op
    ("^U",  13, 1, 0),   # cursor up 1 line
    ("^L",  13, 1, 0),   # redraw only, no move
]


def pad_record(data):
    body = data + bytes([EOF])
    if len(body) % 128:
        body += bytes([EOF]) * (128 - len(body) % 128)
    return body


def load_sym(path):
    toks = open(path).read().split()
    syms = {}
    for i in range(0, len(toks) - 1, 2):
        addr, name = toks[i], toks[i + 1]
        if re.fullmatch(r"[0-9A-Fa-f]{4}", addr):
            syms[name] = int(addr, 16)
    return syms


def main():
    sym = load_sym(os.path.join(HERE, "MOTTST.SYM"))
    for n in ("SNCNT", "SNOFF", "SNLIN", "SNCOL", "DONE", "ERRFLG"):
        if n not in sym:
            sys.exit(f"FAIL: symbol {n} missing from MOTTST.SYM")

    fails = []
    with AltairSim(MACHINE, cwd=HERE, disk=DISK) as sim:
        sim.boot()
        sim.cmd("ERA MOTIN.*", timeout=30)
        sim.cmd("ERA VIBACKUP.*", timeout=30)
        with open(os.path.join(HERE, NAME), "wb") as f:
            f.write(pad_record(FILE.encode("ascii")))
        sim.rfile(NAME)
        sim.cmd(f"MOTTST {NAME}", timeout=180)

        done = sim.mem(sym["DONE"], 1)[0]
        errflg = sim.mem(sym["ERRFLG"], 1)[0]
        cnt = sim.mem(sym["SNCNT"], 1)[0]
        off_b = sim.mem(sym["SNOFF"], 2 * cnt)
        lin_b = sim.mem(sym["SNLIN"], 2 * cnt)
        col_b = sim.mem(sym["SNCOL"], 2 * cnt)

    def w(buf, i):
        return buf[2 * i] | (buf[2 * i + 1] << 8)

    def check(cond, msg):
        print(("  OK   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    print(f"done={done:02X} errflg={errflg:02X} snapshots={cnt} (expect {len(EXPECT)})")
    check(done == 0xFF, "MOTTST reached the end")
    check(errflg == 0, "no ERRMSG fired")
    check(cnt == len(EXPECT), f"snapshot count {cnt} == {len(EXPECT)}")

    for i, (label, eo, el, ec) in enumerate(EXPECT):
        if i >= cnt:
            check(False, f"[{i}] {label}: missing snapshot")
            continue
        go, gl, gc = w(off_b, i), w(lin_b, i), w(col_b, i)
        ok = (go == eo and gl == el and gc == ec)
        check(ok, f"[{i:2}] {label:5} off={go} line={gl} col={gc} "
                  f"(expect off={eo} line={el} col={ec})")

    if fails:
        sys.exit(f"MOTTST FAILED ({len(fails)} check(s))")
    print("MOTTST OK")


if __name__ == "__main__":
    main()
