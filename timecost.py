#!/usr/bin/env python3
"""What each command costs on a 100 K file, in emulated seconds -- and what
the editor's memory and work files hold while it runs.

    python3 timecost.py                # every row, printed as it is measured
    python3 timecost.py dd yy          # only rows whose name matches
    python3 timecost.py --write        # every row, then rewrite TIMECOST.md

paintcost.py counts the characters a keystroke sends, which is the whole cost
of a command that stays inside the window.  This is the other half: the
commands that PAGE, where the 8080 and the disk are the clock.  The "Large
files" section of VI.DOC (build_doc.py) quotes these figures, so they are kept
where they can be measured again: TIMECOST.md is this script's own output, and
is rewritten only by --write on a full run.

Each row is a fresh editor on the 100 K test file (12800 lines of 8 bytes).
The figure is the simulator's own clock (`SHOW CLOCK`, T-states at 2 MHz)
across the keys, less what the harness spends finding the guest idle, which is
measured on each editor before its keys are typed.

That clock counts the 8080's work, the console at 9600 baud, and the BIOS's
disk loops as the simulated 88-DCDD answers them.  It does NOT count head
seeks or waiting for the platter, because the drive model has neither.  So
every figure is a FLOOR: a real drive adds mechanical time to each row that
pages, and nothing to a row that does not.

Build first: python3 build_vi.py VI.  Never run this beside a test battery.
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "TIMECOST.md")
SANDBOX = os.path.join(HERE, "_timecost")

# A sandbox of its own, as fastcheck.py gives each worker: the simulator's
# working directory is where the guest's `W` writes host files, and it must
# not be the repo.  It has to exist before smoke_vi is imported.
shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX)
for _f in ("vi.toml", "VI.COM"):
    shutil.copy(os.path.join(HERE, _f), SANDBOX)
os.environ["VI_SIMDIR"] = SANDBOX
os.environ.pop("VI_WORK", None)
sys.path.insert(0, HERE)

from smoke_vi import Editor, SYM                           # noqa: E402

CLOCK_HZ = 2e6
NLINES = 12800
BIG = b"".join(b"%06d\r\n" % i for i in range(1, NLINES + 1))
ESC, CR = "\x1b", "\r"

# (section, name, keys typed first, keys measured)
ROWS = [
    ("Moving", "`^F` at line 6000", ["6000G"], ["\x06"]),
    ("Moving", "`^B` at line 6000", ["6000G"], ["\x02"]),
    ("Moving", "`200j` at line 6000", ["6000G"], ["200j"]),
    ("Moving", "`G` from the top", [], ["G"]),
    ("Moving", "`gg` from the end", ["G"], ["gg"]),
    ("Moving", "`6000G` from the top", [], ["6000G"]),
    ("Moving", "`6100G` from line 6000", ["6000G"], ["6100G"]),
    ("Moving", "`5900G` from line 6000", ["6000G"], ["5900G"]),
    ("Moving", "`100G` from line 12000", ["12000G"], ["100G"]),
    ("Moving", "`G` again, after `G` `gg`", ["G", "gg"], ["G"]),
    ("Moving", "`gg` from the end, after `x` there", ["G", "x"], ["gg"]),
    ("Moving", "`'a` to line 100 from line 6000",
     ["100G", "ma", "6000G"], ["'a"]),
    ("Moving", "`^G` at the end", ["G"], ["\x07"]),
    ("Moving", "`G` from the top, ESC 10 s into it", [],
     ["G", (10, ESC)]),
    ("Moving", "`/zzzz` from line 6000, never found", ["6000G"],
     ["/zzzz" + CR]),
    ("Moving", "`/zzzz` from line 6000, ESC 10 s into it", ["6000G"],
     ["/zzzz" + CR, (10, ESC)]),
    ("Moving", "`/012000` from the top", [], ["/012000" + CR]),
    ("Moving", "`/000100` from line 6000 (wraps)", ["6000G"],
     ["/000100" + CR]),
    ("Moving", "`?000100` from line 6000", ["6000G"], ["?000100" + CR]),

    ("Editing at line 6000", "`x`", ["6000G"], ["x"]),
    ("Editing at line 6000", "`ihello<Esc>`", ["6000G"], ["i", "hello", ESC]),
    ("Editing at line 6000", "`dd`", ["6000G"], ["dd"]),
    ("Editing at line 6000", "`u` after `dd`", ["6000G", "dd"], ["u"]),
    ("Editing at line 6000", "`100dd` (800 bytes)", ["6000G"], ["100dd"]),
    ("Editing at line 6000", "`u` after `100dd`", ["6000G", "100dd"], ["u"]),
    ("Editing at line 6000", "`500dd` (4 K)", ["6000G"], ["500dd"]),
    ("Editing at line 6000", "`u` after `500dd`", ["6000G", "500dd"], ["u"]),
    ("Editing at line 6000", "`P` after `500dd`", ["6000G", "500dd"], ["P"]),
    ("Editing at line 6000", "`2000dd` (16 K)", ["6000G"], ["2000dd"]),
    ("Editing at line 6000", "`2800dd` (22 K)", ["6000G"], ["2800dd"]),
    ("Editing at line 6000", "`P` after `2800dd`",
     ["6000G", "2800dd"], ["P"]),
    ("Editing at line 6000", "`3000dd` (24 K)", ["6000G"], ["3000dd"]),
    ("Editing at line 6000", "`5000dd` (40 K)", ["6000G"], ["5000dd"]),
    ("Editing at line 6000", "`60yy`", ["6000G"], ["60yy"]),
    ("Editing at line 6000", "`500yy` (4 K)", ["6000G"], ["500yy"]),
    ("Editing at line 6000", "`2800yy` (22 K)", ["6000G"], ["2800yy"]),
    ("Editing at line 6000", "`5000yy` (40 K)", ["6000G"], ["5000yy"]),
    ("Editing at line 6000", "`d6500G` (4 K)", ["6000G"], ["d6500G"]),
    ("Editing at line 6000", "`u` after `d6500G`",
     ["6000G", "d6500G"], ["u"]),
    ("Editing at line 6000", "`d9000G` (24 K)", ["6000G"], ["d9000G"]),
    ("Editing at line 6000", "`d'a`, the mark at line 9000 (24 K)",
     ["9000G", "ma", "6000G"], ["d'a"]),
    ("Editing at line 6000", "`dG` (54 K)", ["6000G"], ["dG"]),
    ("Editing at line 6000", "`dgg` (48 K)", ["6000G"], ["dgg"]),
    ("Editing at line 6000", "`yG` (54 K)", ["6000G"], ["yG"]),
    ("Editing at line 6000", "`u` after `dd` `G`", ["6000G", "dd", "G"],
     ["u"]),

    ("Substitute", "`:6000,6100s/0/1/`", ["6000G"],
     [":6000,6100s/0/1/" + CR]),
    ("Substitute", "`:%s/0/1/` (12800 lines)", [], [":%s/0/1/" + CR]),

    ("Files", "`:w`, nothing changed", [], [":w" + CR]),
    ("Files", "`:w` after `x` at the top", ["x"], [":w" + CR]),
    ("Files", "`:w` after `x` at line 6000", ["6000G", "x"], [":w" + CR]),
    ("Files", "`:w` after `x` at the end", ["G", "x"], [":w" + CR]),
    ("Files", "`:e!` after `x` at the top", ["x"], [":e!" + CR]),
    ("Files", "`:e!` after `x` at line 6000", ["6000G", "x"], [":e!" + CR]),
    ("Files", "`:6000,6100w T.TXT` (800 bytes)", ["6000G"],
     [":6000,6100w T.TXT" + CR]),
    ("Files", "`:6000,9000w T.TXT` (24 K)", ["6000G"],
     [":6000,9000w T.TXT" + CR]),
    ("Files", "`:r T.TXT` of 800 bytes, at line 3000",
     ["6000G", ":6000,6100w T.TXT" + CR, "3000G"], [":r T.TXT" + CR]),
    ("Files", "`:r T.TXT` of 24 K, at line 3000",
     ["6000G", ":6000,9000w T.TXT" + CR, "3000G"], [":r T.TXT" + CR]),
]


def tstates(e):
    raw = e.s._rpc("tools/call", {"name": "monitor",
                                  "arguments": {"command": "SHOW CLOCK"}})
    out = "".join(b.get("text", "") for b in raw.get("content", []))
    return int(re.search(r"\((\d+) T-states\)", out).group(1))


def settle(e, confirms=4, slices=20000):
    """Run the guest until it is waiting on the keyboard.

    Not run_until_quiet: that takes a slice which timed out drawing nothing
    for a settled one, and a command paging through 100 K is silent for most
    of a minute.  Only slices that stop IDLE count here, several in a row
    because an editor between two phases of one command idles briefly too."""
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


def run_for(e, seconds):
    """Let the guest run for *seconds* of its own clock, mid-command."""
    until = tstates(e) + int(seconds * CLOCK_HZ)
    while tstates(e) < until:
        e.s._run(timeout_ms=5)


def type_(e, keys):
    for i, k in enumerate(keys):
        if isinstance(k, tuple):            # (seconds, key): typed that far
            run_for(e, k[0])                #   into the command before it
            k = k[1]
        was = bottom(e) if k == ESC else None
        e.s.send(k)
        if i + 1 < len(keys) and isinstance(keys[i + 1], tuple):
            continue                        # ... which is still running
        settle(e)
        # An ESC that ends an insert: wait for the mode message to go,
        # which is when the user sees the insert end.
        for _ in range(50):
            if was is None or bottom(e) != was:
                break
            settle(e)


def word(e, addr):
    m = e.s.mem(addr, 2)
    return m[0] | m[1] << 8


def bottom(e):
    return "".join(e.screen().screen[23]).strip()


def measure(setup, keys):
    """(seconds, characters sent, the message row) for *keys*."""
    e = Editor(BIG)
    try:
        type_(e, setup)
        t = tstates(e)
        settle(e)                           # what finding it idle costs ...
        idle = tstates(e) - t
        chars = len(e.cap.getvalue())
        t = tstates(e)
        type_(e, keys)
        waits = sum(not isinstance(k, tuple) for k in keys)
        took = tstates(e) - t - idle * waits            # ... per key waited on
        return (max(took, 0) / CLOCK_HZ, len(e.cap.getvalue()) - chars,
                bottom(e))
    finally:
        e.close()


def memory():
    """The arena and the work files, read out of the running editor."""
    out = []
    e = Editor(BIG)
    try:
        def resident():
            return ((word(e, SYM["GAPBEG"]) - word(e, SYM["TXTBEG"]))
                    + (word(e, SYM["TXTEND"]) - word(e, SYM["GAPEND"])))

        def work():
            return (word(e, SYM["OUTFCB"] + 0x22) * 128,
                    word(e, SYM["BAKFCB"] + 0x22) * 128)

        base = word(e, SYM["TXTBAS"]) - 1
        top = word(e, SYM["BUFEND"])
        out.append(("BDOS entry, the word at 0006H", "%04XH" % word(e, 6)))
        out.append(("arena, from the top of the program to the BDOS",
                    "%d bytes (%04XH-%04XH)" % (top - base, base, top)))
        out.append(("text in memory when the file is opened",
                    "%d bytes" % resident()))
        seen = []
        for keys in ("6000G", "G", "6000G", "gg", "G"):
            type_(e, [keys])
            seen.append(resident())
            if keys == "G" and len(seen) == 2:
                first_g = work()
        out.append(("undo region, taken out of the arena",
                    "%d bytes" % (word(e, SYM["UEND"]) - word(e, SYM["UBEG"]))))
        out.append(("text in memory after `6000G` `G` `6000G` `gg` `G`",
                    ", ".join(str(n) for n in seen) + " bytes"))
        out.append(("`TEST.$$$` after `G` from the top, nothing changed",
                    "%d bytes" % first_g[0]))
        type_(e, ["x", "gg"])
        out.append(("`VIBACKUP.$$$` after `G` `x` `gg`", "%d bytes" % work()[1]))
    finally:
        e.close()
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    write = "--write" in sys.argv
    if write and args:
        print("--write measures every row; give it no names")
        return 1
    rows = [r for r in ROWS if not args or any(a in r[1] for a in args)]
    if not rows:
        print("no row matches %s" % " ".join(args))
        return 1

    size = os.path.getsize(os.path.join(HERE, "VI.COM"))
    doc = ["# What a command costs on a 100 K file", "",
           "Written by `python3 timecost.py --write`; do not edit. Measured "
           "on a `VI.COM` of %d bytes, one fresh editor per row, on a file "
           "of %d lines of 8 bytes." % (size, NLINES), "",
           "The seconds are the simulator's emulated clock (2 MHz 8080, "
           "9600-baud console, the BIOS's disk loops). The simulated drive "
           "has no seek time and no rotation, so **these are a floor**: a "
           "real drive adds to every row that pages and to none that does "
           "not. The message is what the bottom row said afterwards.", ""]
    section = None
    for sec, name, setup, keys in rows:
        if sec != section:
            section = sec
            doc += ["", "## %s" % sec, "",
                    "| command | seconds | characters sent | message |",
                    "|---|---|---|---|"]
            print("\n%s" % sec, flush=True)
        secs, chars, said = measure(setup, keys)
        doc.append("| %s | %.1f | %d | %s |"
                   % (name, secs, chars, said.replace("|", "\\|")))
        print("  %-42s %7.1f s %6d chars  %s" % (name, secs, chars, said),
              flush=True)

    if not args:
        doc += ["", "## Memory and work files", "", "| | |", "|---|---|"]
        print("\nMemory and work files", flush=True)
        for what, value in memory():
            doc.append("| %s | %s |" % (what, value))
            print("  %-52s %s" % (what, value), flush=True)

    if write:
        with open(OUT, "w") as f:
            f.write("\n".join(doc) + "\n")
        print("\n%s written" % os.path.basename(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
