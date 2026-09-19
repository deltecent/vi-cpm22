#!/usr/bin/env python3
"""Build and run the test suite, and fail loudly if any part fails.

The suite has two batteries:

  * buffer/paging gate -- BUFTST, PGTST, PGXTST, PGXINS, PGBKTST
        the gap buffer + WordMaster's record/paging/deque/save layer, in
        isolation.  These link only {test, PAGE, BUF}; an unresolved external
        here is silently bound to 0000H/WBOOT by L80 (a harness that forgets a
        stub warm-boots mid-run), so after a change to that layer they MUST be
        run.
  * vi layer -- MOTTST, CMDTST, VI(accept)
        motions, the command core, and the editor-level acceptance test
        (accept_vi.py: 0/1-line/2K/40K/100K on the real editor).

WHICH BATTERY FOR WHICH CHANGE.  The batteries are not interchangeable and
running both every time is not free -- the accept suite alone is several
hundred editor cases, each a cold CP/M boot, and it is the GUEST that is slow
(fastcheck.py runs its groups in parallel).  Run what the change can actually be seen by:

    change to                       run
    ---------------------------     -----------------------------------------
    CMD.MAC / VI.MAC / SCRN.MAC     run_tests.py --vi   + smoke_vi.py
    KEY.MAC                         run_tests.py --vi   + smoke_vi.py
    BUF.MAC / PAGE.MAC              run_tests.py        (everything)
    a gate binary's link line       run_tests.py        (everything)
    a vim table or vimref.py        vimref.py <group>
    comments only                   rebuild, compare the .COM sha1

The buffer gate cannot observe a vi-layer change: BUFTST and the four PG*
drivers link {test, PAGE, BUF} and nothing else, so a CMD.MAC or VI.MAC edit
is invisible to them.  Only MOTTST, CMDTST and VI link CMD.MAC.

While iterating on one command, drive accept_vi.py directly -- it takes group
and size arguments, so `accept_vi.py ops file` is the part that can see the
change and takes a few minutes instead of the whole suite.  Run the battery once, on
the way to the commit, not after every edit.

NOT COVERED HERE, and part of the gate before a commit: `smoke_vi.py` (50
checks, ~5 s -- run it always, it catches "does it still boot, paint, edit and
save" for nothing) and `vimref.py` (re-checks every recorded vim table against
real vim; needed only when a table or the recorder changed).

Each entry builds its target on the tracked CP/M disk (build_vi.py) and then
runs its Python driver, which exits non-zero on failure.  This runner keeps
going past a failure so one red test does not hide the others, then prints a
summary and exits 1 if anything failed.

    python3 run_tests.py                 # everything
    python3 run_tests.py buftst mottst   # just these (by driver name)
    python3 run_tests.py --gate          # just the buffer/paging gate
    python3 run_tests.py --vi            # just the vi layer

NOTE: `--vi` and a bare run BOTH end with the full accept_vi.py -- it is this
runner's 8th step, so never chain `run_tests.py` and `accept_vi.py` in one
command (that runs the whole accept suite twice).

The sim runs one guest at a time and every build rewrites the shared .DSK, so
the steps run strictly sequentially -- do not parallelize.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# (driver-name, build-target, driver-script).  Order: prove the buffer gate
# first (nothing above it is trustworthy if it is red), then the vi layer.
GATE = [
    ("buftst",  "BUFTST",  "buftst.py"),
    ("pgtst",   "PGTST",   "pgtst.py"),
    ("pgxtst",  "PGXTST",  "pgxtst.py"),
    ("pgxins",  "PGXINS",  "pgxins.py"),
    ("pgbktst", "PGBKTST", "pgbktst.py"),
]
VI = [
    ("mottst",  "MOTTST",  "mottst.py"),
    ("cmdtst",  "CMDTST",  "cmdtst.py"),
    ("accept",  "VI",      "accept_vi.py"),
]
ALL = GATE + VI


def run(cmd):
    """Run cmd (list) in HERE, streaming its output live; return (rc, tail)."""
    print(f"    $ {' '.join(cmd)}", flush=True)
    p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    lines = []
    for ln in p.stdout:
        sys.stdout.write("    " + ln)
        sys.stdout.flush()
        lines.append(ln.rstrip("\n"))
    p.wait()
    tail = next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    return p.returncode, tail


def main():
    args = [a for a in sys.argv[1:]]
    if "--gate" in args:
        suite = GATE
    elif "--vi" in args:
        suite = VI
    elif args:
        want = set(args)
        suite = [e for e in ALL if e[0] in want]
        unknown = want - {e[0] for e in ALL}
        if unknown:
            sys.exit(f"unknown test(s): {', '.join(sorted(unknown))}\n"
                     f"choices: {', '.join(e[0] for e in ALL)}")
    else:
        suite = ALL

    results = []          # (name, phase, rc, tail)   phase in {"build","test"}
    t0 = time.time()
    for name, target, script in suite:
        print(f"\n=== {name}  (build {target} + {script}) ===", flush=True)
        rc, tail = run(["python3", "build_vi.py", target])
        if rc != 0:
            print(f"    !! BUILD FAILED for {target} (rc={rc})", flush=True)
            results.append((name, "build", rc, tail))
            continue
        rc, tail = run(["python3", script])
        results.append((name, "test", rc, tail))

    dt = time.time() - t0
    print("\n" + "=" * 60)
    print(f"SUITE SUMMARY  ({len(results)} test(s), {dt:.0f}s)")
    print("=" * 60)
    failed = []
    for name, phase, rc, tail in results:
        status = "PASS" if rc == 0 else f"FAIL ({phase} rc={rc})"
        print(f"  {status:<18} {name:<8} {tail}")
        if rc != 0:
            failed.append(name)

    if failed:
        print(f"\n{len(failed)} FAILED: {', '.join(failed)}")
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    main()
