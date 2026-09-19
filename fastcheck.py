#!/usr/bin/env python3
"""Run accept_vi.py's groups in parallel, one simulator per core.

The acceptance suite is slow because it drives a real editor inside an
emulated 8080 over files of up to 100 KB, and that work is the test.  Staging
is not repeated: smoke_vi._prepared() builds each distinct disk once, so
VI.COM and a test file cross the guest's serial bridge once, not per case.

The rest parallelises almost perfectly.  Every case runs in its own
`altairsim --mcp` subprocess against its own copy of the disk, so the only
shared thing is the simulator's working directory -- the hostbridge's root,
where `R` reads and `W` writes.  Give each worker its own sandbox (this script)
and the groups are independent:

    python3 fastcheck.py                 # every group, across all cores
    python3 fastcheck.py -j4             # four at a time
    python3 fastcheck.py srch ops        # only these

Each worker is a plain `accept_vi.py <group>` process with VI_SIMDIR set,
so a failure reproduces exactly by running that one command.  The full-suite
run this replaces is still the thing to use before a commit if anything about
the harness itself changed -- this proves the editor, not the runner.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX = os.path.join(HERE, "_fastcheck")

# The suite partitioned into disjoint, independently runnable pieces: the five
# size sweeps and the vim groups.  Together these are exactly what a bare
# `accept_vi.py` runs.  Longest first, so the tail of the run is short jobs filling in behind the
# long ones rather than one straggler holding the wall clock open.  Measured
# 2026-09-18: ops 361s, srch 269s, ins 263s ... ex 12s.  The wall time is
# whichever single group is longest, so that is what to split next.
GROUPS = ['ops', 'srch', 'subst', 'marks', 'ins', 'put', 'file', 'ndd', 'dot', 'undo', '100k',
          'ctrlg',
          'bs', 'goto', 'arg', 'mot', '40k', 'scrolls', '2k', 'hml', 'one',
          'jk', 'empty', 'ex']

# what a worker's sandbox needs: the machine file, and the binary `R` sends
NEEDS = ['vi.toml', 'VI.COM']


def worker_env(name):
    d = os.path.join(SANDBOX, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    for f in NEEDS:
        shutil.copy(os.path.join(HERE, f), os.path.join(d, f))
    env = dict(os.environ)
    env['VI_SIMDIR'] = d
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('groups', nargs='*', default=None)
    ap.add_argument('-j', type=int, default=0, help='workers (default: cores-2)')
    a = ap.parse_args()
    groups = a.groups or GROUPS
    jobs = a.j or max(2, (os.cpu_count() or 4) - 2)

    shutil.rmtree(SANDBOX, ignore_errors=True)
    os.makedirs(SANDBOX, exist_ok=True)
    print(f'{len(groups)} groups, {jobs} at a time\n')

    t0 = time.time()
    queue, running, results = list(groups), {}, {}
    while queue or running:
        while queue and len(running) < jobs:
            g = queue.pop(0)
            args = [g]
            log = open(os.path.join(SANDBOX, f'{g}.log'), 'wb')
            p = subprocess.Popen([sys.executable, 'accept_vi.py'] + args,
                                 cwd=HERE, env=worker_env(g),
                                 stdout=log, stderr=subprocess.STDOUT)
            running[g] = (p, log, time.time())
        time.sleep(0.25)
        for g, (p, log, started) in list(running.items()):
            if p.poll() is None:
                continue
            log.close()
            del running[g]
            out = open(os.path.join(SANDBOX, f'{g}.log')).read()
            m = re.search(r'(\d+) passed, (\d+) failed', out)
            ok, bad = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
            results[g] = (p.returncode, ok, bad, time.time() - started)
            flag = 'ok  ' if p.returncode == 0 else 'FAIL'
            print(f'  {flag} {g:8} {ok:5d} passed {bad:3d} failed '
                  f'{results[g][3]:6.1f}s')
            if p.returncode != 0:
                for line in out.splitlines():
                    if 'FAIL' in line or 'Error' in line:
                        print(f'         {line.strip()[:150]}')

    # A group that failed under load is re-run ALONE before it is believed.
    # The harness decides a keystroke is finished by detecting the guest going
    # idle, and that can read as settled while the guest is still mid-disk-
    # write -- writing to a freshly mounted 8 MB image with eight emulators
    # competing for ten cores is exactly the case.  A real failure fails again;
    # a contention artefact passes and is reported as one, never swallowed.
    flaky = []
    for g in [g for g, r in results.items() if r[0] != 0]:
        print(f'\n  re-running {g} alone to tell contention from a real failure...')
        log = open(os.path.join(SANDBOX, f'{g}.retry.log'), 'wb')
        p2 = subprocess.Popen([sys.executable, 'accept_vi.py', g], cwd=HERE,
                              env=worker_env(g), stdout=log,
                              stderr=subprocess.STDOUT)
        p2.wait()
        log.close()
        out = open(os.path.join(SANDBOX, f'{g}.retry.log')).read()
        m = re.search(r'(\d+) passed, (\d+) failed', out)
        ok, bad = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
        if p2.returncode == 0:
            flaky.append(g)
            results[g] = (0, ok, bad, results[g][3])
            print(f'  ok   {g:8} {ok:5d} passed alone -- CONTENTION, not a failure')
        else:
            results[g] = (p2.returncode, ok, bad, results[g][3])
            print(f'  FAIL {g:8} fails alone too -- a real failure')
            for line in out.splitlines():
                if 'FAIL' in line or 'Error' in line:
                    print(f'         {line.strip()[:150]}')
    if flaky:
        print(f'\n  note: {", ".join(flaky)} only failed under load; '
              f'use -j{max(2, jobs - 3)} if that keeps happening')

    total_ok = sum(r[1] for r in results.values())
    total_bad = sum(max(r[2], 0) for r in results.values())
    rc = 0 if all(r[0] == 0 for r in results.values()) else 1
    serial = sum(r[3] for r in results.values())
    wall = time.time() - t0
    print(f'\n{total_ok} passed, {total_bad} failed   '
          f'{wall:.0f}s wall ({serial:.0f}s of work, {serial / max(wall, 1):.1f}x)')
    return rc


if __name__ == '__main__':
    sys.exit(main())
