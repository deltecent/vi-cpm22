#!/usr/bin/env python3
"""PAGING battery -- proves WordMaster's eviction seam under REAL paging.

PGTST proved the file layer RAM-only (everything fits, nothing evicts).  PGXTST
shrinks the window (WINCAP: BUFEND := TXTBEG + WINSIZE, done in PGXTST.MAC) so a
modest file no longer fits, then:
  1. BINIT + WINCAP  -- force a small window
  2. OPENFIL         -- FILLBUF loads only the head of an over-large file, leaving
                        input unread (005BH stays FFH) -- the paging signal
  3. records the resident length + the 005BH flag
  4. inserts a marker at EDITAT
  5. SAVEFIL         -- SAVCLO's FLUSHTX/FILLBF2 loop pages the WHOLE file back
                        out through OUTFCB with real deque marks

For each staged size this script confirms whether the load was partial (paging
fired), checks the resident-head checksum, and byte-compares the full load+edit
round-trip -- so the multi-pass write-behind (PAGEOUT + OUTREC/OUTPOS advancing
across batches) and the reassembly of the paged-out tail are proven byte-exact.

Build first:   python3 build_vi.py PGXTST
Then run:      python3 pgxtst.py
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

# PGXTST.MAC inserts this marker at this offset after loading (fixed in the .COM).
MARKER = b"[EDIT@150]"
EDITAT = 150

# WINSIZE in PGXTST.MAC is 1800H (~6 KB); the text capacity after PGCONST's
# reserve is a few KB.  Sizes below straddle it: one small control that fits
# (no eviction), two that overflow it (eviction fires, multi-batch on the big one).
#   (nlines, must_page)
SIZES = [(4, False), (200, True), (400, True)]


def make_logical(nlines):
    """Deterministic, unique-per-line content, all lines > EDITAT bytes in total."""
    lines = [b"// PGXTST paging round-trip sample line %04d -- quick brown fox" % i
             for i in range(nlines)]
    return b"\r\n".join(lines) + b"\r\n"


def measure(text):
    """Order-sensitive checksum (rotate-left-1 then add) + length, matching
    PGXTST.MAC's SUMBC (CLNSEC masks bit 7, so mask here too)."""
    cks = 0
    for b in text:
        b &= 0x7F
        carry = 1 if (cks & 0x8000) else 0
        cks = (((cks << 1) & 0xFFFF) + carry + b) & 0xFFFF
    return cks, len(text)


def pad_record(data):
    """CP/M text file image: logical bytes + ^Z, padded to a 128-byte record."""
    body = data + bytes([EOF])
    if len(body) % 128:
        body += bytes([EOF]) * (128 - len(body) % 128)
    return body


def strip_eof(data):
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


def run_one(sim, sym, nlines, must_page, fails):
    logical = make_logical(nlines)
    expect = logical[:EDITAT] + MARKER + logical[EDITAT:]
    with open(os.path.join(HERE, NAME), "wb") as f:
        f.write(pad_record(logical))

    sim.rfile(NAME)                             # host -> guest
    sim.cmd(f"PGXTST {NAME}", timeout=90)
    ldcks = w16(sim, sym["LDCKS"])
    ldlen = w16(sim, sym["LDLEN"])
    reslen = w16(sim, sym["RESLEN"])
    inrem = sim.mem(sym["INREM0"], 1)[0]
    done = sim.mem(sym["DONE"], 1)[0]
    errflg = sim.mem(sym["ERRFLG"], 1)[0]
    win = {k: w16(sim, sym[k]) for k in ("TXTBEG", "GAPBEG", "GAPEND", "TXTEND")}
    sim.wfile(NAME)                             # guest -> host (overwrites source)

    out_logical = strip_eof(open(os.path.join(HERE, NAME), "rb").read())
    recs = (len(logical) + 127) // 128
    # resident head is whole records: logical[:reslen] (no ^Z in the head)
    head_cks, _ = measure(logical[:reslen])
    paged = (inrem == 0xFF)

    def check(cond, msg):
        print(("    OK   " if cond else "    FAIL ") + msg)
        if not cond:
            fails.append(f"[{nlines} lines] {msg}")

    print(f"  {nlines} lines / {len(logical)} bytes / {recs} records:  "
          f"done={done:02X} errflg={errflg:02X}  "
          f"resident={reslen} inrem={inrem:02X} paged={paged}  "
          f"load cks={ldcks:04X}/{ldlen}")

    check(done == 0xFF, "PGXTST reached the end")
    check(errflg == 0, "no ERRMSG fired")
    check(win["TXTBEG"] <= win["GAPBEG"] <= win["GAPEND"] <= win["TXTEND"],
          "final window invariant TXTBEG <= GAPBEG <= GAPEND <= TXTEND")
    if must_page:
        check(paged, "load was partial (005BH set => eviction engaged)")
        check(reslen < len(logical), "resident text < file (did not all fit)")
    else:
        check(not paged, "small file fit without paging (005BH clear)")
        check(reslen == len(logical), "resident text == whole file")
    check((ldcks, ldlen) == (head_cks, reslen), "resident head matches source")
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
    sym = load_sym(os.path.join(HERE, "PGXTST.SYM"))
    need = ("LDCKS", "LDLEN", "RESLEN", "INREM0", "DONE", "ERRFLG",
            "TXTBEG", "GAPBEG", "GAPEND", "TXTEND")
    for n in need:
        if n not in sym:
            sys.exit(f"FAIL: symbol {n} missing from PGXTST.SYM")

    fails = []
    with AltairSim(MACHINE, cwd=HERE, disk=DISK) as sim:
        sim.boot()
        for nlines, must_page in SIZES:
            sim.cmd("ERA PGIN.*", timeout=30)   # clean slate each scenario
            run_one(sim, sym, nlines, must_page, fails)

    if fails:
        sys.exit(f"PGXTST FAILED ({len(fails)} check(s)): " + "; ".join(fails))
    print("PGXTST OK")


if __name__ == "__main__":
    main()
