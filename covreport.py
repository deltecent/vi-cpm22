#!/usr/bin/env python3
"""The report covmap.py's run is read into (see covmap.py; issue #3)."""
import collections
import glob
import json
import os
import sys

import covmap

HERE = covmap.HERE
CANPAGE = set("wWbBeE$`jkGg'")       # motions a count or a mark can take far
SIZES = [(0, 'empty'), (1, 'under 2 K'), (2048, '2-24 K'), (24576, 'over 24 K')]


def sizeclass(n):
    name = SIZES[0][1]
    for lo, s in SIZES:
        if n >= lo:
            name = s
    return name


def load(out):
    cases, sections, head = [], [], None
    for path in sorted(glob.glob(os.path.join(out, '*.jsonl'))):
        group = os.path.basename(path)[:-6]
        for line in open(path):
            r = json.loads(line)
            r['group'] = group
            if r['kind'] == 'head':
                head = head or r
                if r['sha'] != head['sha']:
                    sys.exit('the groups were not all run on one VI.COM')
            elif r['kind'] == 'case':
                r['hit'] = frozenset(r['hit'])
                cases.append(r)
            else:
                sections.append(r)
    if not cases:
        sys.exit(f'no data in {out}: run covmap.py first')
    return head, cases, sections


def opctab():
    """-> {key: class} read out of the binary, as build_vi.py reads it."""
    img, pub = covmap.image(), covmap.publics()
    i, tab = pub['OPCTAB'] - 0x100, {}
    while img[i]:
        tab[chr(img[i])] = img[i + 1]
        i += 2
    return tab


def secs(t):
    return t / covmap.CLOCK_HZ


def by(cases, key):
    d = collections.OrderedDict()
    for c in cases:
        d.setdefault(c[key], []).append(c)
    return d


def union(cs):
    u = set()
    for c in cs:
        u |= c['hit']
    return u


def only_here(parts):
    """parts: {name: set}.  -> {name: the blocks no OTHER part reaches}."""
    seen = collections.Counter()
    for s in parts.values():
        seen.update(s)
    return {n: {b for b in s if seen[b] == 1} for n, s in parts.items()}


def cover(cases):
    """Greedy set cover, cheapest emulated time per new block first.
    -> the cases that between them reach everything any case reaches."""
    need, left, kept = set(union(cases)), list(cases), []
    while need:
        best = max(left, key=lambda c: (len(c['hit'] & need) / (c['t'] + 1.0)))
        gain = best['hit'] & need
        if not gain:
            break
        kept.append(best)
        need -= gain
        left.remove(best)
    return kept


def table(out, head, rows):
    out.append('| ' + ' | '.join(head) + ' |')
    out.append('|' + '|'.join('---' for _ in head) + '|')
    for r in rows:
        out.append('| ' + ' | '.join(str(x) for x in r) + ' |')
    out.append('')


def report(out_dir):
    head, cases, sections = load(out_dir)
    blocks, _ = covmap.read_blocks()
    if covmap.hashlib.sha1(covmap.image()).hexdigest() != head['sha']:
        sys.exit('the data in _covmap is from another VI.COM: run covmap.py')
    size = lambda b: blocks[b][1] - blocks[b][0]
    total_bytes = sum(size(b) for b in range(len(blocks)))
    reached = union(cases)
    T = sum(c['t'] for c in cases)
    nchecks = sum(s['checks'] for s in sections)
    o = []
    o.append('# What the acceptance tests reach')
    o.append('')
    o.append('Written by `python3 covmap.py --write`; do not edit. Measured on a '
             f'`VI.COM` of {len(covmap.image())} bytes by running `accept_vi.py` '
             'unchanged with a recorder in the simulator driver (`covmap.py` says how).')
    o.append('')
    o.append(f'The suite started **{len(cases)} editors** and made '
             f'**{nchecks} checks** in **{secs(T):.0f} emulated seconds**. '
             f'`VI.COM` has **{len(blocks)} basic blocks** of code '
             f'({total_bytes} bytes); the suite ran **{len(reached)}** of them '
             f'({100 * len(reached) / len(blocks):.1f} %, '
             f'{sum(size(b) for b in reached)} bytes).')
    o.append('')
    o.append('A block that ran is not a block that is tested: every bug in '
             'issue #3 was in code the suite ran on every pass, reached in a '
             'state no test put it in. So this table can show a test is NOT '
             'looking somewhere, and that two tests walk the same code; it '
             'cannot show that either of them is enough. The operator table '
             'below is the other half -- states, not code.')
    o.append('')

    # ---- groups
    o.append('## Groups')
    o.append('')
    o.append('"only here" is code no other group runs: what would go unrun '
             'if the group were dropped.')
    o.append('')
    g = by(cases, 'group')
    gparts = {n: union(cs) for n, cs in g.items()}
    gonly = only_here(gparts)
    gchecks = collections.Counter()
    for s in sections:
        gchecks[s['group']] += s['checks']
    rows = []
    for n, cs in sorted(g.items(), key=lambda kv: -sum(c['t'] for c in kv[1])):
        t = sum(c['t'] for c in cs)
        rows.append((f'`{n}`', len(cs), gchecks[n], f'{secs(t):.0f}',
                     f'{100 * t / T:.1f} %', len(gparts[n]), len(gonly[n]),
                     sum(size(b) for b in gonly[n])))
    table(o, ['group', 'editors', 'checks', 'emulated s', 'of the suite',
              'blocks run', 'only here', 'bytes only here'], rows)

    # ---- sections
    o.append('## Test functions')
    o.append('')
    o.append('The same, per function `main()` calls. "needed" is how many of '
             'its editors a minimal set keeps -- see the next section.')
    o.append('')
    kept = cover(cases)
    keptn = set(c['n'] for c in kept if False)
    keptid = set(id(c) for c in kept)
    for c in cases:
        c['sec'] = c['group'] + ': ' + c['section']
    s = by(cases, 'sec')
    sparts = {n: union(cs) for n, cs in s.items()}
    sonly = only_here(sparts)
    schecks = collections.Counter()
    for r in sections:
        schecks[r['group'] + ': ' + r['section']] += r['checks']
    rows = []
    for n, cs in sorted(s.items(), key=lambda kv: -sum(c['t'] for c in kv[1])):
        t = sum(c['t'] for c in cs)
        k = [c for c in cs if id(c) in keptid]
        rows.append((f'`{n}`', len(cs), schecks[n], f'{secs(t):.0f}',
                     len(sparts[n]), len(sonly[n]), len(k),
                     f"{secs(sum(c['t'] for c in k)):.0f}"))
    table(o, ['function', 'editors', 'checks', 'emulated s', 'blocks run',
              'only here', 'needed', 'their emulated s'], rows)

    # ---- the minimal set
    kt = sum(c['t'] for c in kept)
    o.append('## How few editors run the same code')
    o.append('')
    o.append(f'**{len(kept)} of the {len(cases)} editors** between them run '
             f'every block the whole suite runs, in **{secs(kt):.0f} of '
             f'{secs(T):.0f} emulated seconds** ({100 * kt / T:.1f} %). They '
             'are picked greedily, most new code per emulated second first.')
    o.append('')
    o.append('That is a floor under the suite, not a suite: the other '
             f'{len(cases) - len(kept)} editors run no code of their own, but '
             'they run it on other text, at other sizes and in other orders, '
             'and that is where the bugs were.')
    o.append('')

    # ---- sizes
    o.append('## What file size adds')
    o.append('')
    o.append('Blocks run at each size of file, and how many of them run at no '
             'other size.')
    o.append('')
    for c in cases:
        c['sz'] = sizeclass(c.get('size') or 0)
    z = by(cases, 'sz')
    zparts = {n: union(cs) for n, cs in z.items()}
    zonly = only_here(zparts)
    rows = []
    for _, n in SIZES:
        if n in z:
            t = sum(c['t'] for c in z[n])
            rows.append((n, len(z[n]), f'{secs(t):.0f}', f'{100 * t / T:.1f} %',
                         len(zparts[n]), len(zonly[n])))
    table(o, ['file', 'editors', 'emulated s', 'of the suite', 'blocks run',
              'only at this size'], rows)

    # ---- the size sweeps
    sweeps = ('empty', 'one', '2k', '40k', '100k')
    sw = collections.OrderedDict()
    for c in cases:
        if c['group'] in sweeps:
            d = sw.setdefault(c['section'].split()[0], {})
            d.setdefault(c['group'], [set(), 0])
            d[c['group']][0] |= c['hit']
            d[c['group']][1] += c['t']
    if sw:
        o.append('## The size sweeps')
        o.append('')
        o.append('Five groups run the same eight functions on files of five '
                 'sizes. For each function: the blocks each size runs that '
                 '**no other size of the same function** runs, and what the '
                 'two paging sizes run that the other does not.')
        o.append('')
        rows = []
        for f, d in sw.items():
            row = [f'`{f}`']
            for g in sweeps:
                if g in d:
                    others = set().union(*[x[0] for h, x in d.items() if h != g])
                    row.append(f'{len(d[g][0] - others)} ({secs(d[g][1]):.0f} s)')
                else:
                    row.append('-')
            a, b = d.get('40k', [set()])[0], d.get('100k', [set()])[0]
            row += [len(a - b), len(b - a)]
            rows.append(row)
        table(o, ['function'] + [f'only at `{g}`' for g in sweeps]
              + ['40k not 100k', '100k not 40k'], rows)

    # ---- the heaviest editors outside the minimal set
    spare = sorted((c for c in cases if id(c) not in keptid),
                   key=lambda c: -c['t'])[:20]
    o.append('## The heaviest editors that run no code of their own')
    o.append('')
    o.append('The twenty longest editors outside the minimal set above. Each '
             'is a candidate for a smaller file or a shorter range, never for '
             'deletion on this evidence alone: what it checks may be the '
             'text, the size or the order, which this table cannot see.')
    o.append('')
    table(o, ['emulated s', 'group', 'function', 'file bytes',
              'keys (the first 50)'],
          [(f"{secs(c['t']):.0f}", f"`{c['group']}`", f"`{c['section']}`",
            c.get('size') or 0,
            '`' + ascii(c['keys'][:50])[1:-1].replace('|', '\\|').replace('`', "'") + '`')
           for c in spare])

    # ---- operators
    o.append('## Operator x motion x paging')
    o.append('')
    o.append('Every time an operator met a motion in the editor (`OPPEND`), '
             'read out of the editor itself: the operator, the key after it, '
             'and whether the window paged before the next key was read. Each '
             'cell is the number of times it happened in the whole suite; '
             '**0** is a cell no test enters, `-` a pair the editor does not '
             'accept (`c` takes no linewise motion, `y` takes only linewise '
             'ones), and `.` a motion that cannot leave the window, so cannot '
             'page. A "paged" cell can stay at 0 with a test on it: a charwise '
             'span the window does not hold is refused before the window '
             'moves (`pgop` checks the refusals), and `e` does not page at '
             'all (#23).')
    o.append('')
    tab = opctab()
    cells = collections.Counter()
    for c in cases:
        for op in c['ops']:
            cells[(op['op'], op['key'], bool(op.get('paged')))] += 1
    names = {'`': '`` ` ``{a-c}', "'": "`'`{a-c}", 'g': '`gg`'}
    legal = {'d': lambda k: True, 'c': lambda k: tab[k] != 2,
             'y': lambda k: tab[k] == 2}
    rows, zero = [], []
    order = list(tab) + ['(doubled)']
    for k in order:
        row = [names.get(k, f'`{k}`') if k != '(doubled)' else '`dd` `yy`']
        for op in 'dcy':
            for paged in (False, True):
                if k == '(doubled)':
                    n = cells[(op, op, paged)] if op != 'c' else None
                elif not legal[op](k):
                    n = None
                elif paged and k not in CANPAGE:
                    n = '.'
                else:
                    n = cells[(op, k, paged)]
                row.append('-' if n is None else '**0**' if n == 0 else n)
                if n == 0:
                    zero.append((op, k, paged))
        rows.append(row)
    table(o, ['motion', '`d`', '`d` paged', '`c`', '`c` paged', '`y`',
              '`y` paged'], rows)
    known = set((op, k) for op in 'dcy' for k in tab) | {('d', 'd'), ('y', 'y')}
    other = sorted((k, n) for k, n in cells.items() if (k[0], k[1]) not in known)
    if other:
        o.append('Operator and key pairs that are NOT motions (the operator '
                 'is dropped) and how often the suite typed one: '
                 + ', '.join(f'`{op}{key}` {n}' for (op, key, _), n in other)
                 + '.')
        o.append('')

    # ---- the stack
    deep = sorted((c for c in cases if c.get('stack') is not None),
                  key=lambda c: -c['stack'])
    if deep:
        o.append('## The stack')
        o.append('')
        o.append(f'The stack is {covmap.STACK} bytes with the image directly '
                 'below it. It is filled before each editor starts and read '
                 'when the editor is done; the deepest any test took it is '
                 f"**{deep[0]['stack']} bytes**. The five deepest:")
        o.append('')
        table(o, ['bytes used', 'group', 'function', 'keys (the first 60)'],
              [(c['stack'], f"`{c['group']}`", f"`{c['section']}`",
                '`' + ascii(c['keys'][:60])[1:-1].replace('|', '\\|') + '`')
               for c in deep[:5]])

    # ---- unreached
    o.append('## Code no test runs')
    o.append('')
    miss = [b for b in range(len(blocks)) if b not in reached]
    o.append(f'{len(miss)} blocks, {sum(size(b) for b in miss)} bytes. Listed '
             'under the label above each, with the first instruction of the '
             'block; several blocks under one label are listed once with a '
             'count.')
    o.append('')
    for m in covmap.MODS:
        mine = [b for b in miss if blocks[b][2] == m]
        if not mine:
            continue
        o.append(f'### {m}.MAC -- {len(mine)} blocks, '
                 f'{sum(size(b) for b in mine)} bytes')
        o.append('')
        lab = collections.OrderedDict()
        for b in mine:
            lab.setdefault(blocks[b][3], []).append(b)
        rows = []
        for name, bs in lab.items():
            rows.append((f'`{name}`', len(bs), sum(size(b) for b in bs),
                         f'`{blocks[bs[0]][4]}`'))
        table(o, ['label', 'blocks', 'bytes', 'first unrun instruction'], rows)
    return '\n'.join(o) + '\n'


def main(out_dir, write=False):
    text = report(out_dir)
    if write:
        with open(os.path.join(HERE, 'TESTMAP.md'), 'w') as f:
            f.write(text)
        print('TESTMAP.md written')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(covmap.OUT, write='--write' in sys.argv))
