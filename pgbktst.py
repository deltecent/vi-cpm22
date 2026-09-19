#!/usr/bin/env python3
"""BACKWARD-PAGING battery -- proves REWIND / SPILLB / PAGEBOT.

PGXTST/PGXINS proved the forward paging paths.  PGBKTST proves the deque window
sliding BOTH ways over a file far larger than RAM:

  forward scroll  = SPILL (evict the top to OUTFCB) + FILLBUF (read the bottom)
  backward scroll = REWIND (re-read the top from OUTFCB) + SPILLB->PAGEBOT
                    (evict the bottom back to the source / VIBACKUP$$$)

PGBKTST.MAC drives WM's own primitives the way the editor's paging does: with
the window shrunk (WINCAP), it loads a file larger than the window, walks the
window FORWARD to end-of-input (paging the head out to OUTFCB), then walks it
BACKWARD to the start (REWINDing the head back in while SPILLB evicts the
bottom), then saves.

With no edit, the round-trip must reproduce the ORIGINAL file byte-for-byte --
the same bytes have slid out to OUTFCB and back and been stitched together by
the deque marks.  This is the first battery to exercise the backward read/write
side of the pager.

Build first:   python3 build_vi.py PGBKTST
Then run:      python3 pgbktst.py
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

# Large enough that the load pages (window is ~6 KB after the reserve), so the
# forward walk really spills to OUTFCB and the backward walk really REWINDs it.
NLINES = 300

# Insert at the document END (after the forward walk exhausts the input) --
# mirrors PGBKTST.MAC's BLOCK (8 x 25 = 200 bytes).  These bytes belong to no
# source record, so the backward SPILLB that evicts them off the bottom must
# write them to VIBACKUP$$$ (PAGEBOT's backup-write branch).
INSERT = b"pgbk-misalign-insert-0123" * 8


def make_logical(nlines):
    lines = [b"// PGBKTST backward-paging line %04d -- the quick brown fox jumps" % i
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
    sym = load_sym(os.path.join(HERE, "PGBKTST.SYM"))
    need = ("SNTXTA", "SNTXTB", "SNOUTR", "SNOPOS", "SNTXB2", "SNOPO2",
            "NFW", "NBK", "SNBAK", "DONE", "ERRFLG")
    for n in need:
        if n not in sym:
            sys.exit(f"FAIL: symbol {n} missing from PGBKTST.SYM")

    logical = make_logical(NLINES)
    expect = logical + INSERT

    fails = []
    with AltairSim(MACHINE, cwd=HERE, disk=DISK) as sim:
        sim.boot()
        sim.cmd("ERA PGIN.*", timeout=30)
        sim.cmd("ERA VIBACKUP.*", timeout=30)   # stale backup scratch, if any
        with open(os.path.join(HERE, NAME), "wb") as f:
            f.write(pad_record(logical))
        sim.rfile(NAME)
        sim.cmd(f"PGBKTST {NAME}", timeout=180)

        sntxta = w16(sim, sym["SNTXTA"])
        sntxtb = w16(sim, sym["SNTXTB"])
        snoutr = w16(sim, sym["SNOUTR"])
        snopos = w16(sim, sym["SNOPOS"])
        sntxb2 = w16(sim, sym["SNTXB2"])
        snopo2 = w16(sim, sym["SNOPO2"])
        nfw = w16(sim, sym["NFW"])
        nbk = w16(sim, sym["NBK"])
        snbak = w16(sim, sym["SNBAK"])
        snbrdy = sim.mem(sym["SNBRDY"], 1)[0]
        done = sim.mem(sym["DONE"], 1)[0]
        errflg = sim.mem(sym["ERRFLG"], 1)[0]
        sim.wfile(NAME)

    out_logical = strip_eof(open(os.path.join(HERE, NAME), "rb").read())

    def check(cond, msg):
        print(("  OK   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    print(f"file {len(logical)}B + {len(INSERT)}B insert -> {len(expect)}B "
          f"({(len(expect)+127)//128} records), window ~{0x1800}B")
    print(f"  done={done:02X} errflg={errflg:02X}  forward calls={nfw} "
          f"backward calls={nbk}  BAKREC={snbak:04X} BAKRDY={snbrdy:02X}")
    print(f"  TXTBAS={sntxta:04X}  forward: TXTBEG={sntxtb:04X} "
          f"OUTREC={snoutr} OUTPOS={snopos}")
    print(f"                backward: TXTBEG={sntxb2:04X} OUTPOS={snopo2}")

    check(done == 0xFF, "PGBKTST reached the end")
    check(errflg == 0, "no ERRMSG fired")
    # forward walk actually paged the head out to OUTFCB
    check(snoutr > 0, "OUTREC > 0 after forward walk (head spilled to OUTFCB)")
    check(snopos > 0, "OUTPOS > 0 after forward walk (OUTFCB holds the head)")
    # backward walk actually pulled it all back from OUTFCB
    check(nbk > 0, "PAGEDIR-backward made progress (REWIND ran)")
    check(snopo2 == 0,
          f"OUTFCB fully drained back on rewind ({snopos} -> {snopo2}: every "
          f"spilled record re-read)")
    # the misaligning insert forced the disturbed tail through VIBACKUP$$$:
    # BAKRDY set FFH => WRREC actually wrote a $$B record (PAGEBOT's PBWBAK branch)
    check(snbrdy != 0,
          f"VIBACKUP$$$ written (BAKRDY={snbrdy:02X}: backward SPILLB->PAGEBOT->$$B)")
    # the file survives the two-way slide, WITH the misaligning insert, byte-exact
    check(out_logical == expect,
          f"save matches insert+original byte-exact ({len(out_logical)} vs {len(expect)})")
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
        sys.exit(f"PGBKTST FAILED ({len(fails)} check(s)): " + "; ".join(fails))
    print("PGBKTST OK")


if __name__ == "__main__":
    main()
