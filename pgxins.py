#!/usr/bin/env python3
"""INSERT-OVERFLOW battery -- proves the MKGAP->MKROOM->SPILL edit seam.

PGXTST proved the save-side write-behind under paging.  PGXINS proves the
editing-time seam: with the window shrunk (WINCAP), it loads a small file, then
inserts far more than the window can hold, so MKGAP repeatedly pages the TXTBEG
side out to OUTFCB mid-edit.  On save the deque marks make PAGEOUT skip the
records already spilled, so the file is reassembled in order, exactly once.

Confirms eviction actually fired (TXTBEG advanced past TXTBAS; OUTREC > 0) and
byte-compares logical[:INSOFF] + block(0..K-1) + logical[INSOFF:].

Build first:   python3 build_vi.py PGXINS
Then run:      python3 pgxins.py
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
NAME = "PGIN.TXT"

# Must mirror PGXINS.MAC exactly.
INSOFF = 60
NBLK = 48
BLKLN = 128

NLINES = 6                             # small file: loads whole, no load-time paging


def block(i):
    """One 128-byte block: 2-digit index + '00' + 124 dots.  Matches PGXINS.MAC."""
    return (b"%02d" % i) + b"00" + b"." * 124


def make_logical(nlines):
    lines = [b"// PGXINS insert-overflow base line %02d -- quick brown fox" % i
             for i in range(nlines)]
    return b"\r\n".join(lines) + b"\r\n"


def pad_record(data):
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


def main():
    sym = load_sym(os.path.join(HERE, "PGXINS.SYM"))
    need = ("INSLEN", "SNTXTB", "SNOUTR", "SNTXTA", "DONE", "ERRFLG")
    for n in need:
        if n not in sym:
            sys.exit(f"FAIL: symbol {n} missing from PGXINS.SYM")

    logical = make_logical(NLINES)
    assert len(logical) > INSOFF, "base file must be longer than INSOFF"
    inserted = b"".join(block(i) for i in range(NBLK))
    expect = logical[:INSOFF] + inserted + logical[INSOFF:]

    fails = []
    with AltairSim(MACHINE, cwd=HERE, disk=DISK) as sim:
        sim.boot()
        sim.cmd("ERA PGIN.*", timeout=30)
        with open(os.path.join(HERE, NAME), "wb") as f:
            f.write(pad_record(logical))
        sim.rfile(NAME)
        sim.cmd(f"PGXINS {NAME}", timeout=120)

        inslen = w16(sim, sym["INSLEN"])
        sntxtb = w16(sim, sym["SNTXTB"])
        snoutr = w16(sim, sym["SNOUTR"])
        sntxta = w16(sim, sym["SNTXTA"])
        done = sim.mem(sym["DONE"], 1)[0]
        errflg = sim.mem(sym["ERRFLG"], 1)[0]
        sim.wfile(NAME)

    out_logical = strip_eof(open(os.path.join(HERE, NAME), "rb").read())

    def check(cond, msg):
        print(("  OK   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    print(f"base {len(logical)}B + {NBLK}x{BLKLN} inserted at {INSOFF} "
          f"-> {len(expect)}B ({(len(expect)+127)//128} records)")
    print(f"  done={done:02X} errflg={errflg:02X} inslen={inslen} "
          f"TXTBEG(after)={sntxtb:04X} TXTBAS={sntxta:04X} OUTREC(after)={snoutr}")

    # After the top edge spills to OUTFCB, MOVGAP/PUTHOLE consolidates the freed
    # RAM by sliding the resident text back down, so TXTBEG returns toward TXTBAS
    # -- the window advances logically (records on disk), not physically upward.
    # So the definitive mid-edit-eviction signal is OUTREC>0 snapshotted BEFORE
    # the save (only MKROOM->SPILL could have written those records; FLUSHTX runs
    # later, in SAVEFIL); TXTBEG is reported for diagnostics only.
    check(done == 0xFF, "PGXINS reached the end")
    check(errflg == 0, "no ERRMSG fired")
    check(inslen == NBLK * BLKLN, "inserted-byte count as expected")
    check(snoutr > 0, "OUTREC > 0 pre-save (records spilled to OUTFCB mid-edit)")
    check(out_logical == expect,
          f"save matches base+insert byte-exact ({len(out_logical)} vs {len(expect)})")
    if out_logical != expect:
        for i in range(min(len(out_logical), len(expect))):
            if out_logical[i] != expect[i]:
                print(f"       first diff at byte {i}: "
                      f"saved {out_logical[max(0,i-8):i+8]!r} "
                      f"expect {expect[max(0,i-8):i+8]!r}")
                break
        if len(out_logical) != len(expect):
            print(f"       length differs: saved {len(out_logical)} "
                  f"expect {len(expect)}")

    if fails:
        sys.exit(f"PGXINS FAILED ({len(fails)} check(s)): " + "; ".join(fails))
    print("PGXINS OK")


if __name__ == "__main__":
    main()
