#!/usr/bin/env python3
"""Command-layer battery -- proves KEY.MAC + CMD.MAC headlessly.

CMDTST.MAC replays a scripted vi session (see its header) over CMDIN.TXT with no
terminal: scripted BCONST/BCONIN feed GETKEY, so the real decode + dispatch +
edit + ex + search path runs.  A snapshot sentinel freezes the cursor before the
save.  This driver stages the file, runs it, checks the frozen cursor snapshot,
and byte-compares the saved file against the expected edited text.

Build first:   python3 build_vi.py CMDTST
Then run:      python3 cmdtst.py
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
NAME = "CMDIN.TXT"

# The staged file.
LINES = ["hello world", "second line here", "third", "", "last line xyz"]

# The scripted session (CMDTST.MAC): x, j, dd, G, 0, i X ESC, :wq.
#   x  -> "ello world"        (delete 'h')
#   dd -> remove "second line here"
#   iX -> "Xlast line xyz"
EXPECT_LINES = ["ello world", "third", "", "Xlast line xyz"]

# Cursor after the insert (stepped back onto 'X'): offset 21, line 3, col 0.
EXP_OFF = 21
EXP_LINE = 3
EXP_COL = 0


def make_file(lines):
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


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
    sym = load_sym(os.path.join(HERE, "CMDTST.SYM"))
    need = ("TOFFV", "TLINEV", "TCOLV", "DONE", "QUITF", "MODF", "ERRFLG")
    for n in need:
        if n not in sym:
            sys.exit(f"FAIL: symbol {n} missing from CMDTST.SYM")

    logical = make_file(LINES)
    expect = make_file(EXPECT_LINES)

    fails = []
    with AltairSim(MACHINE, cwd=HERE, disk=DISK) as sim:
        sim.boot()
        sim.cmd("ERA CMDIN.*", timeout=30)
        sim.cmd("ERA VIBACKUP.*", timeout=30)
        with open(os.path.join(HERE, NAME), "wb") as f:
            f.write(pad_record(logical))
        sim.rfile(NAME)
        sim.cmd(f"CMDTST {NAME}", timeout=180)

        toff = w16(sim, sym["TOFFV"])
        tline = w16(sim, sym["TLINEV"])
        tcol = w16(sim, sym["TCOLV"])
        done = sim.mem(sym["DONE"], 1)[0]
        quitf = sim.mem(sym["QUITF"], 1)[0]
        modf = sim.mem(sym["MODF"], 1)[0]
        errflg = sim.mem(sym["ERRFLG"], 1)[0]
        sim.wfile(NAME)

    out_logical = strip_eof(open(os.path.join(HERE, NAME), "rb").read())

    def check(cond, msg):
        print(("  OK   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    print(f"file {len(logical)}B -> edited {len(expect)}B")
    print(f"  done={done:02X} quitf={quitf:02X} modf={modf:02X} errflg={errflg:02X}")
    print(f"  cursor: off={toff} line={tline} col={tcol} "
          f"(expect off={EXP_OFF} line={EXP_LINE} col={EXP_COL})")

    check(done == 0xFF, "CMDTST reached the end")
    check(errflg == 0, "no ERRMSG fired")
    check(quitf == 0xFF or quitf == 1, ":wq set QUITF")
    check(modf == 0, "buffer marked saved after :w (MODF=0)")
    check(toff == EXP_OFF, f"cursor offset {toff} == {EXP_OFF}")
    check(tline == EXP_LINE, f"cursor line {tline} == {EXP_LINE}")
    check(tcol == EXP_COL, f"cursor col {tcol} == {EXP_COL}")
    check(out_logical == expect,
          f"saved file matches edited text byte-exact "
          f"({len(out_logical)} vs {len(expect)})")
    if out_logical != expect:
        print(f"       saved  = {out_logical!r}")
        print(f"       expect = {expect!r}")

    if fails:
        sys.exit(f"CMDTST FAILED ({len(fails)} check(s)): " + "; ".join(fails))
    print("CMDTST OK")


if __name__ == "__main__":
    main()
