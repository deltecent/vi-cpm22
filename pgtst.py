#!/usr/bin/env python3
"""File-I/O battery -- proves WordMaster's file layer (PAGE.MAC) in RAM.

Boots PGTST.COM (BUF + PAGE, both transcribed verbatim from WM.ASM, on a file
that fits, so nothing evicts), which for the file named on its command tail:
  1. BINIT   -- init the gap buffer
  2. OPENFIL -- open the file and read it in (FILLBUF)
  3. records an order-sensitive checksum + length of the loaded text
  4. inserts a marker at EDITAT (opens a gap straddling a record boundary)
  5. SAVEFIL -- flush the edited buffer back out (name.$$$ -> original)

This script stages source files of several sizes on the CP/M disk, runs PGTST on
each, checks the load checksum against the source, and byte-compares the saved
load+edit round-trip -- so the read side (record engine + FILLBUF), the write
side (SAVCLO/FLUSHTX/PAGEOUT + rename dance), and FLUSHTX's mid-buffer gap
collapse are all proven at single-record and multi-record scales.

Build first:   python3 build_vi.py PGTST
Then run:      python3 pgtst.py
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
NAME = "PGIN.TXT"                       # guest filename (also on the command tail)

# PGTST.MAC inserts this marker at this offset after loading (fixed in the .COM).
MARKER = b"[EDIT@150]"
EDITAT = 150

# Sizes to exercise, in lines (~55 bytes each).  All > EDITAT so the marker
# lands inside the text.  Covers: just over one record, ~3 records, ~10 records.
SIZES = [4, 6, 22]


def make_logical(nlines):
    lines = [b"// PGTST round-trip sample %02d -- the quick brown fox." % i
             for i in range(nlines)]
    return b"\r\n".join(lines) + b"\r\n"


def measure(text):
    """Order-sensitive checksum (rotate-left-1 then add) + length, matching
    PGTST.MAC's SUMBC (CLNSEC masks bit 7, so mask here too)."""
    cks = 0
    for b in text:
        b &= 0x7F
        carry = 1 if (cks & 0x8000) else 0
        cks = (((cks << 1) & 0xFFFF) + carry + b) & 0xFFFF
    return cks, len(text)


def pad_record(data):
    """CP/M text file image: logical bytes + ^Z, padded up to a 128-byte record
    boundary with ^Z (so CLNSEC sees the logical end as the first ^Z)."""
    body = data + bytes([EOF])
    if len(body) % 128:
        body += bytes([EOF]) * (128 - len(body) % 128)
    return body


def strip_eof(data):
    """Logical content of a CP/M text image: up to the first ^Z."""
    i = data.find(EOF)
    return data[:i] if i >= 0 else data


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


def run_one(sim, sym, nlines, fails):
    """Stage one source file, run PGTST, and check load + load+edit round-trip."""
    logical = make_logical(nlines)
    expect = logical[:EDITAT] + MARKER + logical[EDITAT:]
    with open(os.path.join(HERE, NAME), "wb") as f:
        f.write(pad_record(logical))

    sim.rfile(NAME)                             # host -> guest
    sim.cmd(f"PGTST {NAME}", timeout=60)
    ldcks = w16(sim, sym["LDCKS"])
    ldlen = w16(sim, sym["LDLEN"])
    done = sim.mem(sym["DONE"], 1)[0]
    errflg = sim.mem(sym["ERRFLG"], 1)[0]
    win = {k: w16(sim, sym[k]) for k in ("TXTBEG", "GAPBEG", "GAPEND", "TXTEND")}
    sim.wfile(NAME)                             # guest -> host (overwrites source)

    out_logical = strip_eof(open(os.path.join(HERE, NAME), "rb").read())
    want_cks, want_len = measure(logical)
    recs = (len(logical) + 127) // 128

    def check(cond, msg):
        print(("    OK   " if cond else "    FAIL ") + msg)
        if not cond:
            fails.append(f"[{nlines} lines] {msg}")

    print(f"  {nlines} lines / {len(logical)} bytes / {recs} records:  "
          f"done={done:02X} errflg={errflg:02X}  "
          f"load cks={ldcks:04X}/{ldlen} model={want_cks:04X}/{want_len}")

    check(done == 0xFF, "PGTST reached the end")
    check(errflg == 0, "no ERRMSG fired")
    check(win["TXTBEG"] <= win["GAPBEG"] <= win["GAPEND"] <= win["TXTEND"],
          "final window invariant TXTBEG <= GAPBEG <= GAPEND <= TXTEND")
    check((ldcks, ldlen) == (want_cks, want_len), "load matches source")
    check(out_logical == expect,
          f"save matches load+edit byte-exact ({len(out_logical)} vs {len(expect)})")
    if out_logical != expect:
        for i in range(min(len(out_logical), len(expect))):
            if out_logical[i] != expect[i]:
                print(f"         first diff at byte {i}: "
                      f"saved {out_logical[max(0,i-8):i+8]!r} "
                      f"expect {expect[max(0,i-8):i+8]!r}")
                break
        if len(out_logical) != len(expect):
            print(f"         length differs: saved {len(out_logical)} "
                  f"expect {len(expect)}")


def main():
    sym = load_sym(os.path.join(HERE, "PGTST.SYM"))
    need = ("LDCKS", "LDLEN", "DONE", "ERRFLG",
            "TXTBEG", "GAPBEG", "GAPEND", "TXTEND")
    for n in need:
        if n not in sym:
            sys.exit(f"FAIL: symbol {n} missing from PGTST.SYM")

    fails = []
    with AltairSim(MACHINE, cwd=HERE, disk=DISK) as sim:
        sim.boot()
        for nlines in SIZES:
            sim.cmd("ERA PGIN.*", timeout=30)   # clean slate each scenario
            run_one(sim, sym, nlines, fails)

    if fails:
        sys.exit(f"PGTST FAILED ({len(fails)} check(s)): " + "; ".join(fails))
    print("PGTST OK")


if __name__ == "__main__":
    main()
