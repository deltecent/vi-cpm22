#!/usr/bin/env python3
"""Buffer battery -- proves WordMaster's gap buffer (BUF.MAC) in RAM.

Boots BUFTST.COM (BUF transcribed verbatim from WM.ASM; the text fits, so
nothing pages),
which runs a deterministic battery of ops with WM's own primitives (BINIT/
INSBLK/PUTCUR/DELTO) and, after EACH op, records an order-sensitive checksum +
length of the logical text.  This script replays the identical SCRIPT in a
Python model and compares every checkpoint, so any op that corrupts the buffer
is caught at the point it happens -- not just at the end.

Build first:   python3 build_vi.py BUFTST
Then run:      python3 buftst.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcpdrive import AltairSim

MACHINE = "vi.toml"
DISK = "CPM22-8MB-56K-VI.DSK"

# The op battery -- mirrors BUFTST.MAC's START list 1:1 (same order).
#   INS  bytes   insert at the cursor (CPYGAP masks bit 7)
#   HOME         cursor -> start of text
#   TEND         cursor -> end of text
#   RIGHT n      cursor +n chars
#   LEFT  n      cursor -n chars
#   DELF  n      delete n chars forward  (cursor fixed)
#   DELB  n      delete n chars backward (cursor -n)
ALPHA = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SCRIPT = [
    ("INS", b"Hello, World!\r\n"),          # 1
    ("HOME",),                              # 2
    ("INS", b"// header\r\n"),              # 3
    ("TEND",),                              # 4
    ("INS", ALPHA * 10),                    # 5  260 bytes -> multi-chunk
    ("HOME",),                              # 6
    ("RIGHT", 1),                           # 7
    ("RIGHT", 1),                           # 8
    ("RIGHT", 1),                           # 9
    ("LEFT", 1),                            # 10
    ("LEFT", 1),                            # 11
    ("LEFT", 1),                            # 12
    ("RIGHT", 5),                           # 13
    ("INS", b"XYZ"),                        # 14
    ("DELB", 3),                            # 15
    ("DELF", 4),                            # 16
    ("TEND",),                              # 17
    ("DELB", 10),                           # 18
    ("HOME",),                              # 19
    ("INS", bytes([0xC8, 0xE9, 0xEC, 0xEC, 0xEF])),  # 20 -> "Hello"
    ("TEND",),                              # 21
]


def measure(text):
    """Order-sensitive checksum (rotate-left-1 then add) + length, matching
    BUFTST.MAC's SUMBC."""
    cks = 0
    for b in text:
        carry = 1 if (cks & 0x8000) else 0
        cks = (((cks << 1) & 0xFFFF) + carry + b) & 0xFFFF
    return cks, len(text)


def model():
    """Replay SCRIPT; return the list of (cksum,len) checkpoints, one per op."""
    text = bytearray()
    cur = 0
    checks = []
    for op in SCRIPT:
        name = op[0]
        if name == "INS":
            data = bytes(b & 0x7F for b in op[1])   # CPYGAP masks bit 7
            text[cur:cur] = data
            cur += len(data)
        elif name == "HOME":
            cur = 0
        elif name == "TEND":
            cur = len(text)
        elif name == "RIGHT":
            cur += op[1]
        elif name == "LEFT":
            cur -= op[1]
        elif name == "DELF":
            del text[cur:cur + op[1]]
        elif name == "DELB":
            n = op[1]
            del text[cur - n:cur]
            cur -= n
        else:
            raise ValueError(f"unknown op {name}")
        assert 0 <= cur <= len(text), f"model cursor out of range after {op}"
        checks.append(measure(text))
    return checks


def load_sym(path):
    toks = open(path).read().split()
    syms = {}
    for i in range(0, len(toks) - 1, 2):
        addr, name = toks[i], toks[i + 1]
        if re.fullmatch(r"[0-9A-Fa-f]{4}", addr):
            syms[name] = int(addr, 16)
    return syms


def w16(sim, addr):
    b = sim.mem(addr, 2)
    return b[0] | (b[1] << 8)


def main():
    sym = load_sym(os.path.join(HERE, "BUFTST.SYM"))
    need = ("NRES", "RESLTS", "ERRFLG",
            "TXTBEG", "GAPBEG", "GAPEND", "TXTEND")
    for n in need:
        if n not in sym:
            sys.exit(f"FAIL: symbol {n} missing from BUFTST.SYM")

    with AltairSim(MACHINE, cwd=HERE, disk=DISK) as sim:
        sim.boot()
        sim.cmd("BUFTST", timeout=60)
        nres = w16(sim, sym["NRES"])
        raw = sim.mem(sym["RESLTS"], 4 * nres) if nres else b""
        got = []
        for i in range(nres):
            o = 4 * i
            cks = raw[o] | (raw[o + 1] << 8)
            ln = raw[o + 2] | (raw[o + 3] << 8)
            got.append((cks, ln))
        errflg = sim.mem(sym["ERRFLG"], 1)[0]
        win = {k: w16(sim, sym[k]) for k in ("TXTBEG", "GAPBEG", "GAPEND", "TXTEND")}

    want = model()
    fails = []

    def check(cond, msg):
        print(("  OK   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    print(f"  window TXTBEG={win['TXTBEG']:04X} GAPBEG={win['GAPBEG']:04X} "
          f"GAPEND={win['GAPEND']:04X} TXTEND={win['TXTEND']:04X}")
    print(f"  checkpoints: device={nres} model={len(want)} errflg={errflg:02X}")

    check(errflg == 0, "no ERRMSG fired")
    check(win["TXTBEG"] <= win["GAPBEG"] <= win["GAPEND"] <= win["TXTEND"],
          "final window invariant TXTBEG <= GAPBEG <= GAPEND <= TXTEND")
    check(nres == len(want), f"checkpoint count matches ({len(want)})")

    n = min(nres, len(want))
    mism = 0
    for i in range(n):
        if got[i] != want[i]:
            mism += 1
            if mism <= 6:      # show the first few divergences
                print(f"       op {i + 1:2d} {SCRIPT[i][0]:5}: "
                      f"device cks={got[i][0]:04X} len={got[i][1]}  "
                      f"model cks={want[i][0]:04X} len={want[i][1]}")
    check(mism == 0, f"all {n} checkpoints match the model")

    if fails:
        sys.exit(f"BUFTST FAILED ({len(fails)} check(s))")
    print("BUFTST OK")


if __name__ == "__main__":
    main()
