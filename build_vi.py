#!/usr/bin/env python3
"""Build a VI target with M80 + L80 on the altairsim simulator.

Drives the `altairsim` binary through its MCP interface (see mcpdrive.py):
  * sources move onto the CP/M disk with the **R** utility (altairsim's
    hostbridge card, port 0xB0), and TARGET.COM/.SYM come back with **W** --
    no DSK-image surgery
  * builds directly on CPM22-8MB-56K-VI.DSK, which carries M80/L80 and the
    R/W/HDIR hostbridge utilities; there is no per-build working copy, so the
    committed image always holds the current sources

Modules use short names so the single L80 command line stays under CP/M's
~127-char console limit.

Default target is VI.COM.  Pass a target name to build a test stub instead.

Self-contained: sources live flat beside this file, mcpdrive.py sits alongside,
and `altairsim` must be on PATH.  Run from this directory:

    python3 build_vi.py            # VI.COM
    python3 build_vi.py BUFTST     # a test stub
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcpdrive import AltairSim

MACHINE = "vi.toml"                                   # altairsim machine (delta on `default`)
DISK = os.path.join(HERE, "CPM22-8MB-56K-VI.DSK")     # the CP/M disk: M80/L80 + hostbridge; built on in place

# Build targets: TARGET -> link order of modules.  RSV links last of all: it
# emits no bytes, so its base is the top of the image, and it names the reserve
# block that sits in the RAM immediately above (see RSV.MAC).  BUF links just
# before it and points PBEGMEM -- the gap-buffer arena -- past that block.
# Module set is kept small enough that the single L80 command line stays under
# CP/M's ~127-char limit.
TARGETS = {
    # The editor.  VI links FIRST so START sits at the TPA base 0100H; BUF links
    # LAST so MEMBAS (top of its CSEG) is the top of the image = base of the gap-
    # buffer arena.  Screen layer (SCRN) + vi core (CMD) + key decoder (KEY) +
    # file-I/O/paging (PAGE) + buffer (BUF) in between.
    "VI": ["VI", "SCRN", "CMD", "KEY", "PAGE", "BUF", "RSV"],
    # Buffer exerciser: WordMaster's gap buffer (BUF) transcribed verbatim,
    # driven by BUFTST on text that fits in RAM (see buftst.py).  BUF's disk
    # seam (MKGAP->MKROOM, CKLOW->REWIND, the deque marks) is in PAGE, so PAGE
    # links too.
    "BUFTST": ["BUFTST", "PAGE", "BUF", "RSV"],
    # File-I/O exerciser: the same verbatim gap buffer (BUF) plus
    # WordMaster's file-I/O layer (PAGE) -- record engine + open/save drivers,
    # on a file that fits (nothing evicts).  PGTST loads a real file, checksums it,
    # saves it back; pgtst.py byte-compares the round-trip (see pgtst.py).
    # BUF links last (arena at the image top); PAGE's data sits below it.
    "PGTST": ["PGTST", "PAGE", "BUF", "RSV"],
    # Paging exerciser: same modules as PGTST, but the driver shrinks the
    # window (WINCAP) so an over-large file forces real eviction -- MKROOM/SPILL
    # on load-overflow and SAVCLO's FLUSHTX/FILLBF2 multi-batch write-behind on
    # save.  pgxtst.py byte-compares the paged round-trip (see pgxtst.py).
    "PGXTST": ["PGXTST", "PAGE", "BUF", "RSV"],
    # Insert-overflow exerciser: shrinks the window, then inserts far more
    # than it holds so MKGAP->MKROOM->SPILL evicts the TXTBEG side to OUTFCB
    # mid-edit; pgxins.py byte-compares the reassembled file (see pgxins.py).
    "PGXINS": ["PGXINS", "PAGE", "BUF", "RSV"],
    # Backward-paging exerciser: forces a forward spill (as PGXINS), then
    # scrolls back via PAGEDIR (DIRFLG<0) so REWIND re-reads OUTFCB records and
    # SPILLB/PAGEBOT evicts the bottom (incl. VIBACKUP$$$) -- the backward
    # read/write path; pgbktst.py byte-compares the round-trip.
    "PGBKTST": ["PGBKTST", "PAGE", "BUF", "RSV"],
    # Command-layer exerciser: the key decoder (KEY) + the vi command core
    # (CMD) driven headlessly by scripted console I/O.  CMDTST
    # replays a vi session (motions, x, dd, insert, :wq) over a resident file and
    # checks the frozen cursor snapshot + byte-exact saved text (see cmdtst.py).
    # BUF links last (arena at the image top); PAGE/CMD/KEY sit below it.
    "CMDTST": ["CMDTST", "CMD", "KEY", "PAGE", "BUF", "RSV"],
    # Motion exerciser: walks the cursor through the motion set (l w $ 0 e j k
    # G gg W b h / n, counts, goal-column tracking, H M L and the scrolls) and
    # snapshots the landing offset after each, so mottst.py checks every one.
    "MOTTST": ["MOTTST", "CMD", "KEY", "PAGE", "BUF", "RSV"],
}


def check_reserves():
    """RSV.MAC holds storage on behalf of other modules, so a size it declares
    has to agree with the module that uses it.  Sizes shared through VI.INC
    (DOTMAX, KBRSIZ, EXMAX) cannot drift -- there is only one of each.  A size
    that cannot be shared, because its owner does not INCLUDE VI.INC, carries a
    `;CHECK <file> <expr> = <n>` line in RSV.MAC instead, and this evaluates it
    against that file's own equates on every build.  A reserve quietly going
    short would be a buffer overrun into the arena, so it fails the build."""
    src = open(os.path.join(HERE, "RSV.MAC"), encoding="latin-1", newline="").read()
    for owner, expr, want in re.findall(r";CHECK\s+(\S+)\s+(\S+)\s*=\s*(\d+)", src):
        text = open(os.path.join(HERE, owner), encoding="latin-1", newline="").read()
        eq = {}
        for name, val in re.findall(r"^([A-Z0-9$_]{1,8})\s+EQU\s+([0-9A-F]+H?)\b",
                                    text, re.M):
            eq[name] = int(val[:-1], 16) if val.endswith("H") else int(val)
        try:
            got = eval(expr, {"__builtins__": {}}, eq)
        except Exception as exc:
            sys.exit(f"BUILD FAILED: RSV.MAC asks for {owner}'s {expr}, which "
                     f"cannot be read there ({exc}).")
        if got != int(want):
            sys.exit(f"BUILD FAILED: RSV.MAC reserves {want} bytes where {owner} "
                     f"now says {expr} = {got}.  Correct the size in RSV.MAC.")


def run_build(target):
    modules = TARGETS[target]
    check_reserves()

    console = []
    def cmd(c, timeout=600):
        out = sim.cmd(c, timeout=timeout)
        console.append(out)
        return out

    # Build directly on the tracked CP/M disk (no working copy): it carries
    # M80/L80 and altairsim's hostbridge R/W/HDIR utilities, and the R step
    # below refreshes it with the current sources -- so the committed image
    # always holds them and a fresh clone can mount it and SUBMIT the build.
    with AltairSim(MACHINE, cwd=HERE, disk=os.path.basename(DISK)) as sim:
        sim.boot()

        # Move every source onto the CP/M disk via R (host -> guest).
        # VI.INC is INCLUDEd; the rest are assembled + linked.
        # VI.SUB rides along so an in-CP/M `SUBMIT VI` build works too.
        print("  R *.INC, *.MAC, VI.SUB -> CP/M disk")
        sim.rfile("*.INC")
        sim.rfile("*.MAC")
        sim.rfile("VI.SUB")

        for mod in modules:
            cmd(f"ERA {mod}.REL", timeout=60)
        for mod in modules:
            print(f"  M80 {mod}...")
            cmd(f"M80 {mod},{mod}={mod}")

        # Single-line L80.  CP/M's console input line is capped near 127 chars,
        # so the whole command must fit -- this is the constraint that bounds how
        # many modules the editor may be split into.  Guard it so an over-long
        # command fails loudly here instead of being silently truncated.
        link = ",".join(modules)
        l80 = f"L80 {link},{target}/Y/N/E"
        if len(l80) > 127:
            sys.exit(f"BUILD FAILED: L80 command is {len(l80)} chars (> 127 limit).\n"
                     f"  Reduce the {target} module count (merge feature modules).\n  {l80}")
        print(f"  L80 {link},{target}/Y/N/E  [{len(l80)} chars]")
        cmd(l80)

        # Pull the artifacts back to the host via W (guest -> host).
        sim.wfile(f"{target}.COM")        # .COM implies binary
        sim.wfile(f"{target}.SYM", "T")   # symbol table is text

        # Also pull each module's M80 listing (.PRN, text) alongside the sources.
        for mod in modules:
            sim.wfile(f"{mod}.PRN", "T")

    text = "\n".join(console)
    up = text.upper()

    ok = True
    # L80 prefixes EVERY diagnostic with '%' (e.g. "%Mult. Def. Global",
    # "%Undefined Global", "%Overlapping ...").  These are warnings, not fatal --
    # L80 still writes a .COM -- so treat them all as build failures.
    warns = [ln.strip() for ln in text.splitlines() if ln.lstrip().startswith("%")]
    if warns:
        ok = False
        print("=== L80 warnings (treated as build failure) ===")
        for ln in warns:
            print("  " + ln)
    if "UNDEFINED GLOBAL" in up:
        ok = False
    for n in re.findall(r"(\d+)\s+FATAL ERROR", up):
        if int(n) > 0:
            ok = False

    com = os.path.join(HERE, f"{target}.COM")
    if os.path.exists(com) and os.path.getsize(com) > 0:
        print(f"  {target}.COM written ({os.path.getsize(com)} bytes)")
    else:
        print(f"ERROR: {target}.COM was not produced")
        ok = False

    if not ok:
        print("=== CP/M output ===")
        print(text)
        sys.exit("BUILD FAILED")

    print(f"  {target}.COM, {target}.SYM and .PRN listings written here")
    print("BUILD OK")


if __name__ == "__main__":
    run_build(sys.argv[1] if len(sys.argv) > 1 else "VI")
