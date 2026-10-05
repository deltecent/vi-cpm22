#!/usr/bin/env python3
"""What does each acceptance test actually reach?  (issue #3)

    python3 covmap.py                 # every group, in parallel; then the report
    python3 covmap.py srch ops        # only these groups
    python3 covmap.py --write         # every group, and write TESTMAP.md
    python3 covmap.py --report        # the report again, from the last run's data

The suite is organised by command, and it has been green with bugs in the
editor that lived where two things meet.  This measures the suite rather than
the editor: it runs accept_vi.py unchanged, and for every editor a test starts
it records

  * which BASIC BLOCKS of VI.COM ran -- a block is a run of instructions
    entered only at its top, taken from the M80 listings (a label, or the
    instruction after a conditional jump/call/return);
  * every OPERATOR that met a motion: which of d c y, which motion key, the
    count, and whether the window PAGED while it ran (PGTOPM moved);
  * the keys typed, the size of the file, the emulated time it took, and how
    deep the stack went (its 128 bytes are filled first and read afterwards).

From those the report says which blocks no test reaches, which groups and
which cases reach nothing that another does not, and which cells of
operator x motion x paging have a check.

HOW A BLOCK IS SEEN.  altairsim has no coverage counter, and a breakpoint per
block slows it 27x (1750 of them; the cost is linear in their number).  So the
blocks not yet seen are armed as RANGES -- one breakpoint over each unbroken
run of them.  A stop inside a range marks one block, and the range is split
round it.  Hot code is seen in the first few hundred stops and what stays
armed is the cold code, in a few long ranges.

A stop is only believed if the bytes at PC are VI.COM's: a test that leaves the
editor runs other programs in the same memory.
"""
import argparse
import bisect
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_covmap")
MODS = ['VI', 'SCRN', 'CMD', 'KEY', 'PAGE', 'BUF']
DATA = {'DB', 'DW', 'DS', 'EQU'}
COND = re.compile(r'^(J|C|R)(N?Z|N?C|P[OE]?|M)$')
STOP = {'JMP', 'RET', 'PCHL'}
CLOCK_HZ = 2_000_000
STACK = 128                 # RSV.MAC RVSTKN: the bytes below VISTK
SENTRY = 0xA5
SLOWER = 3                  # how much longer a run slice is under the recorder


# --------------------------------------------------------------- the blocks

def image():
    return open(os.path.join(HERE, 'VI.COM'), 'rb').read()


def publics():
    d = {}
    text = open(os.path.join(HERE, 'VI.SYM'), errors='replace').read()
    for a, n in re.findall(r'([0-9A-F]{4}) (\S+)', text):
        d[n] = int(a, 16)
    return d


def read_module(m, pub, img):
    """-> (blocks, symbols) of one module, at their linked addresses.

    A block is [start, end, module, label, source]; `label` is the nearest
    label at or above it.  The module's base is found from a PUBLIC it defines
    (the listing has it module-relative, VI.SYM has it linked), and every
    instruction's first byte is then checked against VI.COM -- a listing that
    is not this binary's stops the run here."""
    text = open(os.path.join(HERE, m + '.PRN'), errors='replace').read()
    text = text.replace('\r', '')
    body, _, table = text.rpartition('Symbols:')
    rel = dict((n, int(a, 16)) for a, n in
               re.findall(r"([0-9A-F]{4})I?'\s+([A-Z0-9_$?@.]+)", table))
    bases = collections.Counter(pub[n] - rel[n] for n in rel if n in pub)
    # VI.MAC exports nothing: it is linked first, behind L80's 3-byte JMP
    base = bases.most_common(1)[0][0] if bases else 0x103
    sym = dict((n, base + a) for n, a in rel.items())
    blocks, lead, label, cur = [], True, None, None
    for ln in body.split('\n'):
        mm = re.match(r"^  ([0-9A-F]{4})'   ([0-9A-F]{2})", ln)
        src = ln[32:] if len(ln) > 32 else ''
        lab = re.match(r'^([A-Za-z_$?@.][\w$?@.]*):', src)
        if lab:
            label = lab.group(1)
        if not mm:
            continue
        code = re.sub(r'^[\w$?@.]+:', '', src).split(';')[0].split()
        if not code:
            continue
        addr = base + int(mm.group(1), 16)
        op = code[0].upper()
        if op in DATA:
            if cur:
                cur[1] = addr
                cur = None
            lead = True
            continue
        if img[addr - 0x100] != int(mm.group(2), 16):
            sys.exit(f'{m}.PRN is not this VI.COM: {addr:04X} {ln.strip()}')
        if lead or lab:
            if cur:
                cur[1] = addr
            cur = [addr, None, m, label, ' '.join(code)]
            blocks.append(cur)
        lead = bool(COND.match(op)) or op in STOP
    if cur:
        cur[1] = blocks[-1][0] + 3
    return blocks, sym


def read_blocks():
    pub, img = publics(), image()
    blocks, sym = [], {}
    for m in MODS:
        b, s = read_module(m, pub, img)
        blocks += b
        for k, v in s.items():
            sym.setdefault(k, v)
            sym[m + '.' + k] = v
    for k, v in pub.items():                  # RSV.MAC's are EQUs: in VI.SYM
        sym.setdefault(k, v)                  #   and in no listing's table
    blocks.sort()
    for i in range(len(blocks) - 1):          # a module's last block ends
        if blocks[i][1] is None or blocks[i][1] > blocks[i + 1][0]:
            blocks[i][1] = blocks[i + 1][0]   #   where the next one starts
    return blocks, sym


# ------------------------------------------------------- the worker's hooks

class Recorder:
    """Hooks mcpdrive.AltairSim and smoke_vi.Editor; one record per editor."""

    def __init__(self, path):
        self.blocks, self.sym = read_blocks()
        self.starts = [b[0] for b in self.blocks]
        self.img = image()
        self.f = open(path, 'w')
        self.section = '?'
        self.pending = {}
        self.ncase = 0
        self.oppend = self.sym['CMD.OPPEND']
        self.mloop = self.sym['VI.MLOOP']
        self.emit(dict(kind='head', blocks=len(self.blocks),
                       sha=hashlib.sha1(self.img).hexdigest()))

    def emit(self, rec):
        self.f.write(json.dumps(rec) + '\n')
        self.f.flush()

    # -- breakpoints ------------------------------------------------------
    def text(self, sim, command):
        r = self.tool(sim, 'monitor', {'command': command})
        try:
            return r['content'][0]['text']
        except (KeyError, IndexError, TypeError):
            return r.get('output', '') if isinstance(r, dict) else str(r)

    def brk(self, sim, lo, hi=None):
        # '$' forces hex: a bare 0B01 is read as a BINARY literal
        spec = f'${lo:04X}' if hi is None or hi == lo else f'${lo:04X}-${hi:04X}'
        m = re.search(r'breakpoint (\d+)', self.text(sim, 'BREAK ' + spec))
        if not m:
            raise RuntimeError('BREAK ' + spec + ' was not accepted')
        return int(m.group(1))

    def arm_run(self, sim, i, j):
        """Arm blocks i..j (both unseen, and everything between) as one range."""
        if i > j:
            return
        st = sim._cov
        st['runs'][self.brk(sim, self.blocks[i][0], self.blocks[j][1] - 1)] = (i, j)

    def start(self, sim, cmd):
        self.finish(sim)
        self.text(sim, 'NOBREAK')
        sim._cov = dict(runs={}, hit=set(), keys=[], t=0, t0=time.time(),
                        cmd=cmd.strip(), ops=[], op=None, stray=0,
                        info={k: v for k, v in self.pending.items() if k != 'live'},
                        section=self.section)
        self.arm_run(sim, 0, len(self.blocks) - 1)
        sim._cov['probe'] = self.brk(sim, self.oppend)
        sim._cov['probe2'] = None

    def finish(self, sim, gone=False):
        st = getattr(sim, '_cov', None)
        if not st:
            return
        sim._cov = None
        self.close_op(sim, st)
        if st.get('filled'):
            st['info']['stack'] = self.stack(sim)
        self.ncase += 1
        keys = ''.join(st['keys'])
        self.emit(dict(kind='case', n=self.ncase, section=st['section'],
                       cmd=st['cmd'], keys=keys[:4000], nkeys=len(keys),
                       t=st['t'], wall=round(time.time() - st['t0'], 2),
                       ops=st['ops'], stray=st['stray'],
                       hit=sorted(st['hit']), **st['info']))

    def stack(self, sim):
        """How many of the stack's bytes have been written since the fill."""
        top = self.sym['VISTK']
        r = self.tool(sim, 'mem_dump', {'lo': top - STACK, 'hi': top - 1})
        by = r.get('bytes') or []
        clean = 0
        while clean < len(by) and by[clean] == SENTRY:
            clean += 1
        return len(by) - clean

    # -- the operator probe ------------------------------------------------
    def word(self, sim, name):
        r = self.tool(sim, 'mem_dump', {'lo': self.sym[name],
                                        'hi': self.sym[name] + 1})
        b = (r.get('bytes') or [0, 0]) + [0, 0]
        return b[0] | b[1] << 8

    def close_op(self, sim, st):
        if st['op'] is None:
            return
        op, st['op'] = st['op'], None
        try:
            op['paged'] = self.word(sim, 'PGTOPM') != op.pop('pg')
        except Exception:
            op['paged'] = None
            op.pop('pg', None)
        st['ops'].append(op)

    def probe(self, sim, st, pc):
        if pc == self.oppend:
            self.close_op(sim, st)
            r = self.tool(sim, 'regs')
            reg = r.get('registers', {}) if isinstance(r, dict) else {}
            key = reg.get('BC', 0) & 0xFF
            st['op'] = dict(op=chr(self.word(sim, 'CMD.PSAVE') & 0xFF),
                            key=chr(key) if 32 <= key < 127 else f'^{key:02X}',
                            count=self.word(sim, 'CMDCNT'),
                            pg=self.word(sim, 'PGTOPM'))
            if st['probe2'] is None:           # ... and it ends at the next key
                st['probe2'] = self.brk(sim, self.mloop)
        elif pc == self.mloop and st['probe2'] is not None:
            self.close_op(sim, st)
            self.text(sim, f"NOBREAK {st['probe2']}")
            st['probe2'] = None

    # -- one stop ---------------------------------------------------------
    def stopped(self, sim, pc):
        """A breakpoint stop at pc.  False if it was not one of ours."""
        st = sim._cov
        r = self.tool(sim, 'mem_dump', {'lo': pc, 'hi': pc + 2})
        got = bytes(r.get('bytes') or [])
        if pc < 0x100 or got != self.img[pc - 0x100:pc - 0x100 + 3]:
            self.text(sim, 'NOBREAK')          # not the editor any more
            self.finish(sim)                   # (its stack is still as it left it)
            return True
        if not st.get('filled'):
            # The stack's 128 bytes, filled so its low-water mark can be read.
            # Here and not before the `VI`: the first stop is the editor's
            # first instruction, and loading VI.COM's last record writes over
            # the bottom of the stack.
            st['filled'] = True
            top = self.sym['VISTK']
            self.text(sim, f'FILL ${top - STACK:04X}-${top - 1:04X} ${SENTRY:02X}')
        ours = pc in (self.oppend, self.mloop)
        if ours:
            self.probe(sim, st, pc)
        a = bisect.bisect_right(self.starts, pc) - 1
        for bid, (i, j) in list(st['runs'].items()):
            if not (self.blocks[i][0] <= pc < self.blocks[j][1]):
                continue
            self.text(sim, f'NOBREAK {bid}')
            del st['runs'][bid]
            if self.blocks[a][0] <= pc < self.blocks[a][1]:
                st['hit'].add(a)
                self.arm_run(sim, i, a - 1)
            else:                              # between two blocks: not code
                st['stray'] += 1               #   this tool knows
                self.arm_run(sim, i, a)
            self.arm_run(sim, a + 1, j)
            return True
        return ours

    # -- the hooks --------------------------------------------------------
    def install(self):
        import mcpdrive
        import smoke_vi
        rec = self
        real_tool = mcpdrive.AltairSim._tool
        real_quit = mcpdrive.AltairSim.quit
        real_init = smoke_vi.Editor.__init__
        self.tool = real_tool

        def tool(sim, name, args=None):
            st = getattr(sim, '_cov', None)
            if name == 'send':
                text = (args or {}).get('text', '')
                if re.match(r'^VI( .*)?\r$', text) and rec.pending.get('live') is sim:
                    rec.start(sim, text)
                elif st and not re.match(r'^\x1b\[\d+;\d+R$', text):
                    st['keys'].append(text)       # (not the size probe's answer)
            if name != 'run' or not st:
                return real_tool(sim, name, args)
            # The harness decides a key is finished by slices of WALL time in
            # which nothing was drawn, and the armed ranges slow the guest: a
            # slice has to be longer by as much, or a disk write reads as done.
            args = dict(args or {})
            if args.get('timeout_ms'):
                args['timeout_ms'] *= SLOWER
            total = None
            while True:
                r = real_tool(sim, name, args)
                if total is None:
                    total = dict(r)
                else:
                    total['output'] = total.get('output', '') + r.get('output', '')
                    for k in ('steps', 't_states'):
                        total[k] = (total.get(k) or 0) + (r.get(k) or 0)
                    for k in ('stopped', 'pc'):
                        total[k] = r.get(k)
                st = getattr(sim, '_cov', None)
                if st:
                    st['t'] += r.get('t_states') or 0
                if not st or r.get('stopped') != 'breakpoint':
                    return total
                if not rec.stopped(sim, r.get('pc', 0)):
                    return total
                args = {k: v for k, v in (args or {}).items()
                        if k not in ('input', 'from')}

        def quit(sim):
            try:
                rec.finish(sim)
            except Exception:
                pass
            return real_quit(sim)

        def init(ed, content, args='', fname='TEST.TXT', *a, **kw):
            n = len(content) if content else 0
            rec.pending = dict(size=n, lines=content.count(b'\n') if content else 0,
                               args=args, fname=fname)
            # the editor's own simulator is the one whose `VI ...` is a case:
            # _prepared()'s staging simulator never types it
            real_new = mcpdrive.AltairSim.__init__

            def new(sim, *a2, **kw2):
                real_new(sim, *a2, **kw2)
                rec.pending['live'] = sim
            mcpdrive.AltairSim.__init__ = new
            try:
                real_init(ed, content, args, fname, *a, **kw)
            finally:
                mcpdrive.AltairSim.__init__ = real_new

        mcpdrive.AltairSim._tool = tool
        mcpdrive.AltairSim.quit = quit
        smoke_vi.Editor.__init__ = init


def worker(group):
    """Run one accept_vi.py group with the recorder in."""
    os.makedirs(os.environ['VI_COV'], exist_ok=True)
    rec = Recorder(os.path.join(os.environ['VI_COV'], group + '.jsonl'))
    rec.install()
    import accept_vi as A

    def wrap(name, fn):
        def run(*a, **kw):
            was = rec.section
            label = name + ''.join(f' {x}' for x in a if isinstance(x, str))
            rec.section = label
            t0, p0, f0 = time.time(), A.PASS[0], A.FAIL[0]
            try:
                return fn(*a, **kw)
            finally:
                rec.emit(dict(kind='section', section=label,
                              checks=A.PASS[0] - p0 + A.FAIL[0] - f0,
                              failed=A.FAIL[0] - f0,
                              wall=round(time.time() - t0, 1)))
                rec.section = was
        return run

    import inspect
    called = set(re.findall(r'^\s+(\w+)\(', inspect.getsource(A.main), re.M))
    for name in called:
        fn = getattr(A, name, None)
        if callable(fn) and getattr(fn, '__module__', '') == A.__name__:
            setattr(A, name, wrap(name, fn))
    sys.argv = ['accept_vi.py', group]
    try:
        A.main()
    finally:
        rec.f.close()


# ------------------------------------------------------------------ driver

def run_groups(groups, jobs):
    import shutil
    import fastcheck
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    shutil.rmtree(fastcheck.SANDBOX, ignore_errors=True)
    os.makedirs(fastcheck.SANDBOX, exist_ok=True)
    queue, running, bad = list(groups), {}, []
    t0 = time.time()
    while queue or running:
        while queue and len(running) < jobs:
            g = queue.pop(0)
            env = fastcheck.worker_env(g)
            env['VI_COV'] = OUT
            log = open(os.path.join(OUT, g + '.log'), 'wb')
            running[g] = (subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), '--worker', g],
                cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT),
                log, time.time())
        time.sleep(0.25)
        for g, (p, log, started) in list(running.items()):
            if p.poll() is None:
                continue
            log.close()
            del running[g]
            out = open(os.path.join(OUT, g + '.log')).read()
            m = re.search(r'(\d+) passed, (\d+) failed', out)
            tail = f'{m.group(1)} passed {m.group(2)} failed' if m else 'NO RESULT'
            if p.returncode != 0:
                bad.append(g)
            print(f"  {'ok  ' if p.returncode == 0 else 'FAIL'} {g:8} {tail:26} "
                  f'{time.time() - started:6.0f}s', flush=True)
    print(f'\n{time.time() - t0:.0f}s wall', flush=True)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('groups', nargs='*')
    ap.add_argument('-j', type=int, default=0)
    ap.add_argument('--worker')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    if a.worker:
        return worker(a.worker)
    if not a.report:
        import fastcheck
        bad = run_groups(a.groups or fastcheck.GROUPS,
                         a.j or max(2, (os.cpu_count() or 4) - 2))
        if bad:
            print('groups that FAILED under the recorder: ' + ' '.join(bad))
    import covreport
    return covreport.main(OUT, write=a.write)


if __name__ == '__main__':
    sys.exit(main())
