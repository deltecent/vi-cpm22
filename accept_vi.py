#!/usr/bin/env python3
"""Editor-level acceptance test: the real VI.COM, driven through the simulator.

It stages real files of 0 bytes / one line / ~2 K / ~40 K / 100 K and drives
the REAL VI.COM through the simulator.  A command counts as proven only when it
works here on files far larger than the arena, so 40 K / 100 K force real
paging.

Per size it covers navigation and paging, deep edits, h/l/x at the line edges,
long lines (horizontal pan) and tabs, :q/:q!, and :w followed by more editing.
Every other command is checked against vim 9.1 on recorded tables (regenerable
with vimref.py) -- motions, scrolls, inserts, operators, puts, search, :s,
marks, '.', 'u', ^G, the ex line and the command-line arguments -- plus the
deviations vim cannot referee, which are checked on their own.  The disk is
only ever read through the guest (CCP + host-bridge W).

    python3 build_vi.py VI && python3 fastcheck.py     # everything, in parallel
    python3 accept_vi.py 2k 100k        # subset, by size label
    python3 accept_vi.py ops            # or by group (fastcheck.py GROUPS
                                        #   lists them all)

Each line of every staged file is a fixed 8-byte record "NNNNNN\\r\\n" so the
true first line is always "000001" and the true last line is always the file's
line count, zero-padded -- distinctive text the screen assertions can pin to a
specific row even after paging.
"""
import os
import re
import shutil
import sys

from smoke_vi import Editor, SYM, rows, HERE, SIMDIR, TEMPLATE, WORK

PROMPT = re.compile(r'[A-P][0-9]*>')


def at_ccp(e, cmd):
    """Send *cmd* to the editor and report whether it returned to the CP/M
    prompt (True) or stayed in the editor (False), by scanning only the
    capture produced by this command."""
    before = len(e.cap.getvalue())
    e.key(cmd)
    return bool(PROMPT.search(e.cap.getvalue()[before:]))

PASS = [0]; FAIL = [0]; FAILED = []


def check(label, cond):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        FAILED.append(label)
        print(f'  FAIL {label}', flush=True)


def line(i):
    """The fixed 8-byte record for 1-based logical line *i*: 'NNNNNN\\r\\n'."""
    return b'%06d\r\n' % i


def make(nlines):
    return b''.join(line(i) for i in range(1, nlines + 1))


def txt(i):
    """The 6-char on-screen text of logical line *i* ('000001', ...)."""
    return '%06d' % i


def nedit(e):
    """Number of editable rows (edit area is rows 0 .. nedit-1)."""
    return e.s.mem(SYM['NEDIT'])[0]


def topln(e):
    """0-based logical line shown on screen row 0, read off the screen.

    The renderer is cursor-relative (WINROW) and keeps no window-top line
    number, so the top line is taken from the numbered text itself."""
    r0 = rows(e)[0]
    return int(r0) - 1 if r0.isdigit() else 0


def saved_bytes(e):
    """Read TEST.TXT back off the disk, stripped of CP/M ^Z record padding."""
    return e.diskfile('TEST', 'TXT').rstrip(b'\x1a')


# (label, nlines).  nlines chosen so the byte size straddles the ~36 KB arena.
SIZES = [
    ('empty', 0),        # 0 bytes
    ('one',   1),        # 8 bytes, single line
    ('2k',    256),      # 2048 bytes -- fits in the initial window
    ('40k',   5120),     # 40960 bytes -- just past the arena, must page
    ('100k',  12800),    # 102400 bytes -- deep paging, both directions
]


def nav_and_save(label, n):
    """Read-only navigation + a no-edit :w round-trip, on one editor."""
    content = make(n)
    e = Editor(content)
    try:
        bottom = nedit(e) - 1
        r = rows(e)
        last = txt(n) if n else None

        if n == 0:
            check(f'{label}: empty opens, row0 blank/tilde', r[0] in ('', '~'))
        else:
            check(f'{label}: gg row0 = first line', r[0] == txt(1))

        # --- G reaches the TRUE last line (not the resident edge) -----------
        if n >= 1:
            e.key('G')
            r = rows(e); v = e.screen()
            if n == 1:
                check(f'{label}: G one-line stays row0', r[0] == last and v.row == 0)
            elif n - 1 < bottom:               # whole file fits on screen
                check(f'{label}: G last line at row {n-1}', r[n - 1] == last)
            else:                               # file taller than window: paged
                check(f'{label}: G last line at bottom edit row', r[bottom] == last)
                check(f'{label}: G cursor on bottom edit row', v.row == bottom)
                check(f'{label}: G scrolled (TOPLN>0)', topln(e) > 0)

            # --- gg returns to the TRUE first line --------------------------
            e.key('gg')
            r = rows(e); v = e.screen()
            check(f'{label}: gg back to first line', r[0] == txt(1))
            check(f'{label}: gg TOPLN=0', topln(e) == 0)
            check(f'{label}: gg cursor home', (v.row, v.col) == (0, 0))

        # --- ^F pages forward to EOF, ^B back to BOF ------------------------
        if n - 1 > bottom:
            # ^F advances NEDIT-2 = bottom-1 lines; enough ^F to reach EOF
            pages = n // max(1, bottom - 1) + 3
            for _ in range(pages):
                e.key('\x06')                     # ^F
            r = rows(e)
            check(f'{label}: ^F chain reveals true last line',
                  any(row == last for row in r))
            for _ in range(pages):
                e.key('\x02')                     # ^B
            r = rows(e)
            check(f'{label}: ^B chain returns to first line', r[0] == txt(1))
            check(f'{label}: ^B chain TOPLN=0', topln(e) == 0)

        # --- count j / k cross the window edge (and page on big files) ------
        if n >= 40:
            target = min(n, 4000)                 # deep past the ~2 KB window
            e.key('gg')
            e.key('%dj' % (target - 1))           # land on logical line `target`
            r = rows(e); v = e.screen()
            check(f'{label}: {target-1}j lands on line {target}',
                  r[v.row] == txt(target))
            e.key('%dk' % (target - 1))           # back to line 1
            r = rows(e); v = e.screen()
            check(f'{label}: {target-1}k returns to line 1', r[v.row] == txt(1))

        # --- h l within a line (fixed 6-char records) -----------------------
        if n >= 1:
            e.key('gg')
            e.key('lll')
            v = e.screen(); check(f'{label}: lll -> col3', v.col == 3)
            e.key('h')
            v = e.screen(); check(f'{label}: h -> col2', v.col == 2)

        # --- :w byte-exact round-trip (no edits) ----------------------------
        e.key(':w\r')
        check(f'{label}: :w round-trip byte-exact', saved_bytes(e) == content)
    finally:
        e.close()


def edit_deep(label, n):
    """x/i/dd deep in the file, then :w byte-exact -- edits PAST the arena."""
    content = make(n)

    # x on the true LAST line, deep past the arena, then save byte-exact.
    e = Editor(content)
    try:
        e.key('G'); e.key('x')                    # x at col0 of last record
        # last record "NNNNNN\r\n" -> drop first char -> "NNNNN\r\n"
        expect = make(n - 1) + line(n)[1:]
        e.key(':w\r')
        got = saved_bytes(e)
        check(f'{label}: x on last line saved (deep edit past arena)', got == expect)
    finally:
        e.close()

    # i at BOF
    e = Editor(content)
    try:
        e.key('gg'); e.key('i'); e.key('ZZ'); e.key('\x1b')
        check(f'{label}: i at BOF inserts', rows(e)[0] == 'ZZ' + txt(1))
    finally:
        e.close()

    # dd at BOF removes the first logical line
    e = Editor(content)
    try:
        e.key('gg'); e.key('dd')
        if n == 1:                                # deleting the only line -> empty
            check(f'{label}: dd empties one-line file', rows(e)[0] in ('', '~'))
        else:
            check(f'{label}: dd at BOF drops first line', rows(e)[0] == txt(2))
        e.key(':w\r')
        check(f'{label}: dd :w byte-exact', saved_bytes(e) == make(n)[8:])
    finally:
        e.close()


def send_keys(e, k):
    """Type *k*.  A lone ESC is confirmed only after ESCTMO keyboard polls, which
    run_until_quiet reads as idle, so after an ESC keep running until the editor
    is back in command mode.  Long text goes in 400-byte bursts."""
    if k == '\x1b':
        e.key(k)
        for _ in range(200):
            if e.s.mem(SYM['EDMODE'])[0] == 0:
                break
            e.s._run()
        e.s.run_until_quiet()
        return
    for p in range(0, len(k), 400):
        e.key(k[p:p + 400])


def lines_of(n):
    return [l.decode() for l in make(n).split(b'\r\n')[:-1]]


def hl_x_deep(label, n):
    """h / l / x on a line deep in the file (past the arena on 40K/100K)."""
    tgt = min(n, 4000)
    t = txt(tgt)
    e = Editor(make(n))
    try:
        if tgt > 1:
            e.key('%dj' % (tgt - 1))

        def col():
            v = e.screen()
            return rows(e)[v.row], v.col
        e.key('h');   check(f'{label}: h at col0 stays', col() == (t, 0))
        e.key('3l');  check(f'{label}: 3l', col() == (t, 3))
        e.key('99l'); check(f'{label}: 99l stops on the last char', col() == (t, 5))
        e.key('l');   check(f'{label}: l at the end stays', col() == (t, 5))
        e.key('2h');  check(f'{label}: 2h', col() == (t, 3))
        e.key('99h'); check(f'{label}: 99h stops at col0', col() == (t, 0))
        e.key('3l'); e.key('x')
        check(f'{label}: x mid-line', col() == (t[:3] + t[4:], 3))
        e.key('99l'); e.key('x')
        check(f'{label}: x on the last char steps back', col()[1] == 3)
        e.key('3x')
        check(f'{label}: 3x stops at the line end', col() == (t[:3], 2))
        e.key(':w\r')
        e.key(':q\r')
        want = make(tgt - 1) + t[:3].encode() + b'\r\n' + \
            b''.join(line(i) for i in range(tgt + 1, n + 1))
        check(f'{label}: h/l/x :w byte-exact', saved_bytes(e) == want)
    finally:
        e.close()


BIGINS = ''.join('INS%04d\r' % k for k in range(600))    # 4800 bytes typed


def write_plan(n):
    """Keys and the matching model edits for write_continue.  'W' marks a :w
    checkpoint.  Model: {'lines': [...], 'i': cursor line index}."""
    if n == 0:
        # the <CR> at the end of the text opens a REAL empty last line
        # (ENDBRK), so the buffer is two lines and the file carries both
        def hello(m): m['lines'] = ['HELLO', '']; m['i'] = 1
        def x0(m): m['lines'][0] = 'ELLO'
        def dd0(m): m['lines'][:] = ['']
        def gg(m): m['i'] = 0
        return [('iHELLO\r', None), ('\x1b', hello), ('W', None), ('gg', gg),
                ('x', x0), ('W', None), ('dd', dd0), ('W', None)]
    if n == 1:
        def x1(m): m['lines'][0] = m['lines'][0][1:]
        def ab(m): m['lines'][0:0] = ['AB']; m['i'] = 1
        def dd1(m): m['lines'].pop(0); m['i'] = 0
        return [('x', x1), ('W', None), ('iAB\r', None), ('\x1b', ab),
                ('W', None), ('gg', None), ('dd', dd1), ('W', None)]
    i0 = min(n, 3000) - 1 - (5 if n > 30 else 0)

    def mv(m): m['i'] = i0
    def x(m): m['lines'][m['i']] = m['lines'][m['i']][1:]
    def j(m): m['i'] += 1
    def ins(m):
        m['lines'][m['i']:m['i']] = ['INS%04d' % k for k in range(600)]
        m['i'] += 600
    def gdd(m): del m['lines'][-1]; m['i'] = len(m['lines']) - 1
    def ggdd(m): del m['lines'][0]; m['i'] = 0
    return [('%dj' % i0, mv), ('x', x), ('W', None), ('j', j), ('x', x),
            ('i' + BIGINS, None), ('\x1b', ins), ('W', None),
            ('G', None), ('dd', gdd), ('gg', None), ('dd', ggdd), ('W', None)]


def write_continue(label, n):
    """:w keeps editing: after each :w the cursor, its row and the screen are
    unchanged, the file on disk is byte-exact, and :q then exits.  The disk is
    read only through the guest, so each checkpoint is a fresh session replaying
    the keys up to that :w."""
    plan = write_plan(n)
    cps = [k for k, (s, _) in enumerate(plan) if s == 'W']
    for num, cp in enumerate(cps, 1):
        m = {'lines': lines_of(n), 'i': 0}
        e = Editor(make(n))
        try:
            for s, fn in plan[:cp]:
                if s == 'W':
                    e.key(':w\r')
                    continue
                send_keys(e, s)
                if fn:
                    fn(m)
            v0 = e.screen()
            e.key(':w\r')
            r = rows(e); v = e.screen(); ne = nedit(e)
            L, i = m['lines'], m['i']
            cur = L[i] if i < len(L) else ''      # past the last newline: empty
            tag = f'{label}: :w#{num}'
            check(f'{tag} cursor stays on line {i + 1}', r[v.row] == cur)
            check(f'{tag} cursor keeps its row/col',
                  (v.row, v.col) == (v0.row, v0.col))
            top = i - v.row
            exp = [L[top + k] if 0 <= top + k < len(L) else
                   ('' if top + k == i else '~') for k in range(ne)]
            check(f'{tag} screen unchanged', r[:ne] == exp)
            check(f'{tag} :q exits (saved)', at_ccp(e, ':q\r'))
            want = ''.join(l + '\r\n' for l in L).encode()
            check(f'{tag} byte-exact on disk', saved_bytes(e) == want)
        finally:
            e.close()


def expand(text):
    out = ''
    for ch in text:
        out += ' ' * (8 - len(out) % 8) if ch == '\t' else ch
    return out


WIDE = ''.join(chr(ord('A') + k % 26) for k in range(200))     # 200 columns
TABL = 'a\tb\tcc\tddd\t' + 'x' * 90                             # tabs + long


def wide_tabs(label, n):
    """A 200-column line (horizontal pan) and a tab line, deep in the file: the
    screen cell under the cursor always shows the right char; on a TAB (command
    mode) the cursor sits on the tab's last column, as in vi."""
    k = min(n, 3000) - 1                  # the two lines go before line k+1
    L = lines_of(n)
    L[k:k] = [WIDE, TABL]
    e = Editor(''.join(l + '\r\n' for l in L).encode())
    try:
        if k:
            e.key('%dj' % k)

        def at(tag, text, b):
            v = e.screen()
            r = rows(e)[v.row]
            want = ' ' if text[b] == '\t' else text[b]
            got = r[v.col] if v.col < len(r) else ' '
            check(f'{label}: {tag}: cell {got!r} is {want!r}', got == want)
            check(f'{label}: {tag}: row is a slice of the line',
                  r.rstrip() != '' and r.rstrip() in expand(text))
        at('wide col 0', WIDE, 0)
        e.key('100l'); at('100l pans right', WIDE, 100)
        e.key('99l');  at('99l to the end', WIDE, 199)
        e.key('150h'); at('150h pans left', WIDE, 49)
        e.key('99h');  at('99h to col 0', WIDE, 0)
        e.key('120l'); e.key('j'); e.key('j'); e.key('k'); e.key('k')
        at('j j k k keep the goal column', WIDE, 120)
        e.key('j'); e.key('999h'); at('tab line col 0', TABL, 0)
        e.key('l'); at('onto a tab', TABL, 1)
        check(f'{label}: cursor on a tab is on its last column', e.screen().col == 7)
        e.key('l');  at('past the tab', TABL, 2)
        e.key('5l'); at('5l over tabs', TABL, 7)
        e.key('x'); t2 = TABL[:7] + TABL[8:]; at('x on a tab', t2, 7)
        e.key('iQ\t'); send_keys(e, '\x1b')
        t3 = t2[:7] + 'Q\t' + t2[7:]; at('insert Q TAB', t3, 8)
        e.key('99l'); at('end of the tab line', t3, len(t3) - 1)
        e.key('iZZZ'); send_keys(e, '\x1b')
        t4 = t3[:-1] + 'ZZZ' + t3[-1:]; at('insert at the far right', t4, len(t4) - 2)
        e.key(':w\r'); e.key(':q\r')
        L[k + 1] = t4
        check(f'{label}: wide/tab edits :w byte-exact',
              saved_bytes(e) == ''.join(l + '\r\n' for l in L).encode())
    finally:
        e.close()


# vim 9.1.1752 (-u NONE -N, 24-line terminal; 'nowrap' for the wide file):
# (cursor line, top line, cursor row, cursor column) after each key.  A count
# pages that many times; a page is NEDIT-2 lines, more at the end of the file.
# Files: a line count (make), 'wide' (make_wide), 'indent' (make_indent).
# ^D ^U move 'scroll' lines (a count sets it) and land on the first non-blank.
VIM_SCROLLS = [
    (30, ['\x06', '\x02'],
     ['22 22 0 0', '23 1 22 0']),
    (30, ['\x06', '\x06', '\x02', '\x02'],
     ['22 22 0 0', '30 30 0 0', '29 7 22 0', '23 1 22 0']),
    (30, ['\x06', '\x02', '\x06', '\x06', '\x06'],
     ['22 22 0 0', '23 1 22 0', '22 22 0 0', '30 30 0 0', '30 30 0 0']),
    (30, ['G', '\x02', '\x02'],
     ['30 8 22 0', '23 1 22 0', '23 1 22 0']),
    (30, ['\x04', '\x15'],
     ['12 8 4 0', '1 1 0 0']),
    (30, ['G', '\x04', '\x15', '\x15'],
     ['30 8 22 0', '30 8 22 0', '19 1 18 0', '8 1 7 0']),
    (5120, ['\x06', '\x06', '\x02'],
     ['22 22 0 0', '43 43 0 0', '44 22 22 0']),
    (5120, ['G', '\x02', '\x06', '\x06'],
     ['5120 5098 22 0', '5099 5077 22 0', '5098 5098 0 0', '5120 5120 0 0']),
    (5120, ['10j', '\x04', '\x15'],
     ['11 1 10 0', '22 12 10 0', '11 1 10 0']),
    (30, ['2\x06', '\x02'],
     ['30 30 0 0', '29 7 22 0']),
    (30, ['9\x06', '2\x02'],
     ['30 30 0 0', '23 1 22 0']),
    (30, ['\x06', '\x06', '2\x02'],
     ['22 22 0 0', '30 30 0 0', '23 1 22 0']),
    (30, ['G', '9\x02'],
     ['30 8 22 0', '23 1 22 0']),
    (50, ['G', '\x06', '2\x02'],
     ['50 28 22 0', '50 50 0 0', '26 4 22 0']),
    (50, ['\x06', '\x06', '5\x02'],
     ['22 22 0 0', '43 43 0 0', '23 1 22 0']),
    (5120, ['3\x06', '2\x02'],
     ['64 64 0 0', '44 22 22 0']),
    (5120, ['100\x06', '100\x02'],
     ['2101 2101 0 0', '23 1 22 0']),
    (5120, ['250\x06', '\x06', '\x02'],
     ['5120 5120 0 0', '5120 5120 0 0', '5119 5097 22 0']),
    (5120, ['G', '2\x02', '3\x06'],
     ['5120 5098 22 0', '5078 5056 22 0', '5119 5119 0 0']),
    (5120, ['G', '\x02', '2\x06'],
     ['5120 5098 22 0', '5099 5077 22 0', '5119 5119 0 0']),
    (5120, ['G', '300\x02', '\x02'],
     ['5120 5098 22 0', '23 1 22 0', '23 1 22 0']),
    (5120, ['3000G', '5\x06', '7\x02'],
     ['3000 2989 11 0', '3094 3094 0 0', '2969 2947 22 0']),
    (5120, ['G', '\x06', '\x02'],
     ['5120 5098 22 0', '5120 5120 0 0', '5119 5097 22 0']),
    (5120, ['G', '\x06', '3\x02'],
     ['5120 5098 22 0', '5120 5120 0 0', '5073 5051 22 0']),
    (5120, ['G', '\x06', 'k', '\x02'],
     ['5120 5098 22 0', '5120 5120 0 0', '5119 5119 0 0', '5119 5097 22 0']),
    (5120, ['G', '\x06', '2\x06', 'k', '2\x02'],
     ['5120 5098 22 0', '5120 5120 0 0', '5120 5120 0 0', '5119 5119 0 0', '5097 5075 22 0']),
    (5120, ['5078G', '2\x06', '\x06'],
     ['5078 5067 11 0', '5109 5109 0 0', '5120 5120 0 0']),
    (5120, ['99999\x06', '99999\x02'],
     ['5120 5120 0 0', '23 1 22 0']),
    (12800, ['G', '500\x02'],
     ['12800 12778 22 0', '2300 2278 22 0']),
    (12800, ['600\x06'],
     ['12601 12601 0 0']),
    (12800, ['555\x06', '555\x02'],
     ['11656 11656 0 0', '23 1 22 0']),
    ('wide', ['44G', '$', '\x06', '2\x06', '\x02', '3\x02'],
     ['44 33 11 0', '44 33 11 5', '54 54 0 0', '96 96 0 0', '97 75 22 0', '34 12 22 0']),
    ('wide', ['G', '2\x02', 'j', '$', '\x06'],
     ['1500 1478 22 0', '1458 1436 22 0', '1459 1437 22 0', '1459 1437 22 5', '1458 1458 0 0']),
    ('wide', ['G', '\x06', '\x02', '2\x06'],
     ['1500 1478 22 0', '1500 1500 0 0', '1499 1477 22 0', '1500 1500 0 0']),
    ('wide', ['G', '400\x02', '100\x06'],
     ['1500 1478 22 0', '23 1 22 0', '1500 1500 0 0']),
    ('wide', ['45G', '$', 'j', '\x02', '\x06'],
     ['45 34 11 0', '45 34 11 199', '46 34 12 5', '35 13 22 0', '34 34 0 0']),
    ('indent', ['2\x06', 'l', '\x02'],
     ['43 43 0 4', '43 43 0 5', '44 22 22 10']),
    ('indent', ['G', '3\x02'],
     ['6000 5978 22 10', '5937 5915 22 4']),
    ('indent', ['$', '5\x06', '$', '2\x02'],
     ['1 1 0 9', '106 106 0 10', '106 106 0 15', '86 64 22 10']),
    ('indent', ['3000G', '300\x06', '2\x02'],
     ['3000 2989 11 10', '6000 6000 0 10', '5976 5954 22 10']),
    (5120, ['5\x04', '\x04', '\x15', '3\x15', '\x15'],
     ['6 6 0 0', '11 11 0 0', '6 6 0 0', '3 3 0 0', '1 1 0 0']),
    (5120, ['G', '\x15', '30\x15', '\x15', '\x04'],
     ['5120 5098 22 0', '5109 5087 22 0', '5086 5064 22 0', '5063 5041 22 0', '5086 5064 22 0']),
    (5120, ['100\x04', '\x06', '\x04'],
     ['24 24 0 0', '45 45 0 0', '68 68 0 0']),
    (5120, ['G', '\x04'],
     ['5120 5098 22 0', '5120 5098 22 0']),
    (5120, ['\x15'],
     ['1 1 0 0']),
    (5120, ['G', 'k', '\x04', '\x04'],
     ['5120 5098 22 0', '5119 5098 21 0', '5120 5098 22 0', '5120 5098 22 0']),
    (5120, ['5100G', '\x04', '\x04', '\x04'],
     ['5100 5089 11 0', '5111 5098 13 0', '5120 5098 22 0', '5120 5098 22 0']),
    (5120, ['0\x04'],
     ['12 12 0 0']),
    (5120, ['50\x04', '50\x15', '50\x15'],
     ['24 24 0 0', '1 1 0 0', '1 1 0 0']),
    (5120, ['G', '\x06', '\x04', '\x15', '\x15'],
     ['5120 5098 22 0', '5120 5120 0 0', '5120 5120 0 0', '5109 5109 0 0', '5098 5098 0 0']),
    (30, ['20\x04', '\x04'],
     ['21 8 13 0', '30 8 22 0']),
    (30, ['G', '40\x15'],
     ['30 8 22 0', '7 1 6 0']),
    (10, ['\x04', '\x15'],
     ['10 1 9 0', '1 1 0 0']),
    (10, ['5j', '\x15', '\x04'],
     ['6 1 5 0', '1 1 0 0', '10 1 9 0']),
    (5120, ['1000\x04'],
     ['24 24 0 0']),
    (5120, ['9\x04', '\x02', '\x06'],
     ['10 10 0 0', '23 1 22 0', '22 22 0 0']),
    ('wide', ['45G', '$', '\x04', 'j', '\x15', 'k'],
     ['45 34 11 0', '45 34 11 199', '56 45 11 0', '57 45 12 0', '46 34 12 0', '45 34 11 0']),
    ('wide', ['44G', '$', '\x04', '\x15'],
     ['44 33 11 0', '44 33 11 5', '55 44 11 0', '44 33 11 0']),
    ('wide', ['G', '$', '7\x15', '\x04'],
     ['1500 1478 22 0', '1500 1478 22 199', '1493 1471 22 0', '1500 1478 22 0']),
    ('indent', ['3000G', '$', '\x04', '\x15'],
     ['3000 2989 11 10', '3000 2989 11 15', '3011 3000 11 4', '3000 2989 11 10']),
    ('indent', ['l', '\x04', 'j'],
     ['1 1 0 1', '12 12 0 10', '13 12 1 9']),
    ('indent', ['G', '$', '\x15', '4\x04', 'k'],
     ['6000 5978 22 10', '6000 5978 22 15', '5989 5967 22 4', '5993 5971 22 4', '5992 5971 21 7']),
]


def scrolls_like_vim():
    """^F ^B ^D ^U (with counts) leave the cursor and the window where
    vim does, on plain, wide (panned) and indented files."""
    for f, keys, want in VIM_SCROLLS:
        content = make_wide() if f == 'wide' else make_indent() if f == 'indent' else make(f)
        e = Editor(content)
        try:
            for k, w in zip(keys, want):
                e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                col = v.col + hs
                if hs:          # panned: the line numbers are off the screen
                    got = '%d %d' % (v.row, col)
                    w = ' '.join(w.split()[2:])
                else:
                    num = lambda t: int(re.match(r' *(\d+)', t).group(1))
                    got = '%d %d %d %d' % (num(r[v.row]), num(r[0]), v.row, col)
                check(f'vim {f} {keys!r} {k!r}: {got} == {w}', got == w)
        finally:
            e.close()
    e = Editor(b'')
    try:
        for k in ['\x06', '\x02', '\x04', '\x15', '3\x06', '3\x02']:
            e.key(k)
            v = e.screen()
            check(f'empty: {k!r} stays home', (v.row, v.col) == (0, 0))
        check('empty: scrolls leave it unmodified (:q exits)', at_ccp(e, ':q\r'))
    finally:
        e.close()


# vim 9.1 (-u NONE -N, 24-line terminal) for G / nG / gg / ngg: a line on the
# screen keeps the window, one a little below goes on the bottom row, a little
# above on the top row, anything farther mid-screen (clamped at the ends).
VIM_GOTO = [
    (3, ['G', 'gg'], ['3 1 2', '1 1 0']),
    (3, ['2G', '9G'], ['2 1 1', '3 1 2']),
    (3, ['3gg', '1gg'], ['3 1 2', '1 1 0']),
    (30, ['G', 'gg'], ['30 8 22', '1 1 0']),
    (30, ['\x06', '\x06', 'G'], ['22 22 0', '30 30 0', '30 30 0']),
    (30, ['\x06', '\x06', '20G', '\x06', '\x06', '21G'],
         ['22 22 0', '30 30 0', '20 8 12', '30 30 0', '30 30 0', '21 21 0']),
    (30, ['7G', '50G', '30gg'], ['7 1 6', '30 8 22', '30 8 22']),
    (5120, ['3000G', '3011G', '3012G'], ['3000 2989 11', '3011 2989 22', '3012 2990 22']),
    (5120, ['3000G', '3023G'], ['3000 2989 11', '3023 3001 22']),
    (5120, ['3000G', '3024G'], ['3000 2989 11', '3024 3013 11']),
    (5120, ['3000G', '2980G'], ['3000 2989 11', '2980 2980 0']),
    (5120, ['3000G', '2979G'], ['3000 2989 11', '2979 2968 11']),
    (5120, ['3000G', '5G', '3000G', '3gg'],
           ['3000 2989 11', '5 1 4', '3000 2989 11', '3 1 2']),
    (5120, ['35G', '36G', 'gg'], ['35 13 22', '36 14 22', '1 1 0']),
    (5120, ['G', '\x06', '5111G'], ['5120 5098 22', '5120 5120 0', '5111 5111 0']),
    (5120, ['G', '\x06', '5110G'], ['5120 5098 22', '5120 5120 0', '5110 5098 12']),
    (5120, ['G', '\x06', 'G', 'gg'], ['5120 5098 22', '5120 5120 0', '5120 5120 0', '1 1 0']),
    (5120, ['3000G', '20k', '3000G'], ['3000 2989 11', '2980 2980 0', '3000 2980 20']),
    (5120, ['5080G', '5104G', '99999G'], ['5080 5069 11', '5104 5093 11', '5120 5098 22']),
    (12800, ['G', '6400G', '6423G', '6424G'],
            ['12800 12778 22', '6400 6389 11', '6423 6401 22', '6424 6402 22']),
    (12800, ['6400G', '6380G', '6379G', '12800gg'],
            ['6400 6389 11', '6380 6380 0', '6379 6379 0', '12800 12778 22']),
    (12800, ['G', '\x06', '12790G', '1G'],
            ['12800 12778 22', '12800 12800 0', '12790 12778 12', '1 1 0']),
    (12800, ['12000G', '15j', '12010G', 'gg'],
            ['12000 11989 11', '12015 11993 22', '12010 11993 17', '1 1 0']),
]


def make_wide():
    """1500 lines, every third one 200 chars wide (109 K): lines, not bytes."""
    return b''.join(b'%06d' % i + (b'x' * 194 if i % 3 == 0 else b'') + b'\r\n'
                    for i in range(1, 1501))


# The same, on make_wide(), against vim with 'nowrap' (this editor pans, it
# never wraps).
VIM_GOTO_WIDE = [
    (['700G', '712G', '714G'], ['700 689 11', '712 690 22', '714 692 22']),
    (['700G', '725G'], ['700 689 11', '725 714 11']),
    (['700G', '680G', '679G'], ['700 689 11', '680 680 0', '679 679 0']),
    (['G', '\x06', '1490G', 'gg'], ['1500 1478 22', '1500 1500 0', '1490 1478 12', '1 1 0']),
]


def make_indent():
    """6000 indented lines (66 K): odd ones 4 spaces, even ones TAB + 2 spaces."""
    return b''.join((b'    ' if i % 2 else b'\t  ') + b'%06d\r\n' % i
                    for i in range(1, 6001))


# (cursor line, top line, cursor row, cursor column) on make_indent(): G and
# gg land on the first non-blank, as vim's do.
VIM_GOTO_INDENT = [
    (['G', 'gg', '3000G', '3gg', '\x06'],
     ['6000 5978 22 10', '1 1 0 4', '3000 2989 11 10', '3 1 2 4', '22 22 0 10']),
]


def goto_like_vim():
    """G nG gg ngg land where vim puts them; on an empty file they stay home."""
    cases = [(make(n), n, k, w) for n, k, w in VIM_GOTO]
    cases += [(make_wide(), 'wide', k, w) for k, w in VIM_GOTO_WIDE]
    for content, n, keys, want in cases:
        e = Editor(content)
        try:
            for k, w in zip(keys, want):
                e.key(k)
                r = rows(e); v = e.screen()
                got = '%d %d %d' % (int(r[v.row][:6]), int(r[0][:6]), v.row)
                check(f'vim {n} lines {keys!r} {k!r}: {got} == {w}', got == w)
        finally:
            e.close()
    for keys, want in VIM_GOTO_INDENT:
        e = Editor(make_indent())
        try:
            for k, w in zip(keys, want):
                e.key(k)
                r = rows(e); v = e.screen()
                got = '%d %d %d %d' % (int(r[v.row].strip()), int(r[0].strip()), v.row, v.col)
                check(f'vim indented {keys!r} {k!r}: {got} == {w}', got == w)
        finally:
            e.close()
    e = Editor(b'')
    try:
        for k in ['G', '5G', 'gg', '3gg']:
            e.key(k)
            v = e.screen()
            check(f'empty: {k} stays home', (v.row, v.col) == (0, 0))
        check('empty: G/gg leave it unmodified (:q exits)', at_ccp(e, ':q\r'))
    finally:
        e.close()


# Mixed tabs, for j/k: vim keeps the goal as a screen column (a TAB under the
# cursor counts at its last column) and lands on the char whose columns hold it.
TABJK_LINES = ['\tab', 'xyzuvwrstuvwxyz', 'a\tb\tc', '\t\tq', 'ab', '',
               '  \t  z', '0123456789abcdefghij']

# (keys, [(cursor line, top line, cursor row, cursor column) after each key])
# from vim 9.1 (-u NONE -N, 24 lines); files are CRLF here, LF for vim.
VIM_JK = [
    ('tabs', ['j', 'j', 'j', 'j', 'j', 'j', 'j'],
     ['2 1 1 7', '3 1 2 7', '4 1 3 7', '5 1 4 1', '6 1 5 0', '7 1 6 7', '8 1 7 7']),
    ('tabs', ['$', 'j', 'j', 'k'], ['1 1 0 9', '2 1 1 14', '3 1 2 16', '2 1 1 14']),
    ('tabs', ['l', 'j', 'j', 'j'], ['1 1 0 8', '2 1 1 8', '3 1 2 8', '4 1 3 15']),
    ('tabs', ['7l', 'k', 'j', 'j', 'j', 'j', 'j', 'j'],
     ['1 1 0 9', '1 1 0 9', '2 1 1 9', '3 1 2 15', '4 1 3 15', '5 1 4 1', '6 1 5 0', '7 1 6 9']),
    ('tabs', ['2j', 'l', 'l', 'j', 'k', 'k'],
     ['3 1 2 7', '3 1 2 8', '3 1 2 15', '4 1 3 15', '3 1 2 15', '2 1 1 14']),
    ('tabs', ['4j', 'j', 'j', 'j', 'k', 'k', 'k', 'k'],
     ['5 1 4 1', '6 1 5 0', '7 1 6 7', '8 1 7 7', '7 1 6 7', '6 1 5 0', '5 1 4 1', '4 1 3 7']),
    ('tabs', ['7j', '19l', 'k', 'k', 'k', 'k', 'k', 'k', 'k'],
     ['8 1 7 7', '8 1 7 19', '7 1 6 10', '6 1 5 0', '5 1 4 1', '4 1 3 16', '3 1 2 16', '2 1 1 14', '1 1 0 9']),
    ('tabs', ['7j', '$', 'k', 'k', 'k', 'k', 'k', 'k', 'k'],
     ['8 1 7 7', '8 1 7 19', '7 1 6 10', '6 1 5 0', '5 1 4 1', '4 1 3 16', '3 1 2 16', '2 1 1 14', '1 1 0 9']),
    ('indent', ['G', 'k', 'k', 'j', '0', 'k', 'j'],
     ['6000 5978 22 10', '5999 5978 21 9', '5998 5978 20 10', '5999 5978 21 9',
      '5999 5978 21 0', '5998 5978 20 7', '5999 5978 21 0']),
    ('indent', ['3001G', 'l', 'l', 'j', 'j', 'k', '$', 'j', 'k'],
     ['3001 2990 11 4', '3001 2990 11 5', '3001 2990 11 6', '3002 2990 12 7', '3003 2990 13 6',
      '3002 2990 12 7', '3002 2990 12 15', '3003 2990 13 9', '3002 2990 12 15']),
    ('indent', ['5999G', '5l', '5j', '3k', '2000k', 'j', 'j'],
     ['5999 5978 21 4', '5999 5978 21 9', '6000 5978 22 9', '5997 5978 19 9',
      '3997 3986 11 9', '3998 3986 12 9', '3999 3986 13 9']),
    ('indent', ['3000G', '3j', '500j', 'l', '500k', '0', '40j', '4000j'],
     ['3000 2989 11 10', '3003 2989 14 9', '3503 3492 11 9', '3503 3492 11 9',
      '3003 2992 11 9', '3003 2992 11 0', '3043 3032 11 0', '6000 5978 22 7']),
    ('tabs', ['$', 'x', 'j'], ['1 1 0 9', '1 1 0 8', '2 1 1 8']),
    ('tabs', ['j', '$', 'dd', 'j'], ['2 1 1 7', '2 1 1 14', '2 1 1 0', '3 1 2 7']),
    ('tabs', ['l', '$', 'x', 'k', 'j'], ['1 1 0 8', '1 1 0 9', '1 1 0 8', '1 1 0 8', '2 1 1 8']),
    ('tabs', ['$', 'i\x1b', 'j'], ['1 1 0 9', '1 1 0 8', '2 1 1 8']),
    ('tabs', ['3l', 'iQ\x1b', 'j'], ['1 1 0 9', '1 1 0 9', '2 1 1 9']),
    ('tabs', ['2j', '$', 'iQQ\x1b', 'k'], ['3 1 2 7', '3 1 2 16', '3 1 2 17', '2 1 1 14']),
    (5120, ['3000G', '23j'], ['3000 2989 11 0', '3023 3001 22 0']),
    (5120, ['3000G', '24j'], ['3000 2989 11 0', '3024 3013 11 0']),
    (5120, ['3000G', '20k'], ['3000 2989 11 0', '2980 2980 0 0']),
    (5120, ['3000G', '21k'], ['3000 2989 11 0', '2979 2968 11 0']),
    (5120, ['5100G', '30j'], ['5100 5089 11 0', '5120 5098 22 0']),
    (5120, ['40G', '50k'], ['40 29 11 0', '1 1 0 0']),
    (5120, ['40G', '30k'], ['40 29 11 0', '10 1 9 0']),
    (5120, ['3000G', '11j', '12j'], ['3000 2989 11 0', '3011 2989 22 0', '3023 3001 22 0']),
    (5120, ['3000G', '11j', '13j'], ['3000 2989 11 0', '3011 2989 22 0', '3024 3013 11 0']),
]


def jk_like_vim():
    """j k keep vim's screen-column goal over TABs and scroll as vim does."""
    tabs = b''.join(l.encode() + b'\r\n' for l in TABJK_LINES)
    for f, keys, want in VIM_JK:
        content = tabs if f == 'tabs' else make_indent() if f == 'indent' else make(f)
        e = Editor(content)
        try:
            for k, w in zip(keys, want):
                if k.endswith('\x1b'):
                    if k[:-1]:
                        send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
                r = rows(e); v = e.screen()
                if f == 'tabs':
                    lno, top = v.row + 1, 1
                else:
                    lno, top = int(r[v.row].strip()), int(r[0].strip())
                got = '%d %d %d %d' % (lno, top, v.row, v.col)
                check(f'vim j/k {f} {keys!r} {k!r}: {got} == {w}', got == w)
        finally:
            e.close()


BS = '\x08'

# Insert-mode BS (and DEL, which vim and WordMaster treat the same), from vim
# 9.1 (-u NONE -N, 24 lines, 'nowrap', backspace=indent,eol,start): BS at the
# start of a line joins it onto the one above, and BS goes back past where the
# insert began.  (file, keys, sha1 of the file vim wrote, [(cursor row, cursor
# column, cursor line, top line) after each key]).
VIM_BS = [
    ('wide', ['700G', 'i\x08\x1b', 'j', 'lllli' + BS * 6 + '\x1b'], 'a8d9840f52c599ae',
     [(11, 0, '000700', '000689'),
      (10, 199, '000699' + 'x' * 194 + '000700', '000689'),
      (11, 5, '000701', '000689'),
      (10, 205, '000699' + 'x' * 194 + '0007001', '000689')]),
    ('wide', ['700G', '11k', 'i\x08\x1b', 'i\x08\x08\x1b'], 'db21bbac1db90021',
     [(11, 0, '000700', '000689'),
      (0, 0, '000689', '000689'),
      (0, 5, '000688000689', '000688000689'),
      (0, 2, '0008000689', '0008000689')]),
    ('wide', ['700G', '11j', 'i\x7f\x1b', 'k', '99li\x08\x08\x1b'], '872032e2965474d7',
     [(11, 0, '000700', '000689'),
      (22, 0, '000711' + 'x' * 194, '000689'),
      (21, 5, '000710000711' + 'x' * 194, '000689'),
      (20, 5, '000709', '000689'),
      (20, 2, '0009', '000689')]),
    ('wide', ['G', 'i' + BS * 30 + '\x1b', 'gg', 'i\x08\x1b', 'lli' + BS * 5 + '\x1b'], 'c94249eb694509c5',
     [(22, 0, '001500' + 'x' * 194, '001478'),
      (19, 184, '001497' + 'x' * 179 + '001500' + 'x' * 194, '001478'),
      (0, 0, '000001', '000001'),
      (0, 0, '000001', '000001'),
      (0, 0, '0001', '0001')]),
    ('wide', ['701G', 'iAB' + BS * 4 + 'CD\x1b'], 'd3521979119502b8',
     [(11, 0, '000701', '000690' + 'x' * 194),
      (10, 6, '00070CD000701', '000690' + 'x' * 194)]),
    ('indent', ['3000G', 'i\x08\x1b', 'j', 'i\x08\x08\x1b', 'j', '0i\x08\x1b'], 'e66ad55dbc56941a',
     [(11, 10, '\t  003000', '    002989'),
      (11, 8, '\t 003000', '    002989'),
      (12, 8, '    003001', '    002989'),
      (12, 5, '    0001', '    002989'),
      (13, 7, '\t  003002', '    002989'),
      (12, 7, '    0001\t  003002', '    002989')]),
    (12800, ['10000G', 'i' + BS * 2500 + '\x1b', 'j'], 'e895f1e95da0b4ff',
     [(11, 0, '010000', '009989'),
      (0, 5, '009642010000', '009642010000'),
      (1, 5, '010001', '009642010000')]),
    (12800, ['G', 'i' + BS * 2000 + '\x1b'], '47edb8710f81c634',
     [(22, 0, '012800', '012778'),
      (0, 1, '01012800', '01012800')]),
    (3, ['i\x08\x1b', 'Gi\x08\x08\x1b', 'i' + BS * 20 + 'X\x1b'], 'b0a4d29fa4295aed',
     [(0, 0, '000001', '000001'),
      (1, 4, '00000000003', '000001'),
      (0, 0, 'X0000003', 'X0000003')]),
    (1, ['llli' + BS * 9 + '\x1b'], '9db5a85743e0ab1b',
     [(0, 0, '001', '001')]),
    (5120, ['G', '3000k', 'i' + BS * 650 + '\x1b', 'j', 'k'], '8c7bf0e05f968bd3',
     [(22, 0, '005120', '005098'),
      (11, 0, '002120', '002109'),
      (0, 0, '0002120', '0002120'),
      (1, 0, '002121', '0002120'),
      (0, 0, '0002120', '0002120')]),
    (12800, ['G', '3000k', 'i' + BS * 650 + '\x1b', 'j', 'k'], 'fe08f5be1a78f11d',
     [(22, 0, '012800', '012778'),
      (11, 0, '009800', '009789'),
      (0, 0, '0009800', '0009800'),
      (1, 0, '009801', '0009800'),
      (0, 0, '0009800', '0009800')]),
]


def bs_like_vim():
    """BS in insert mode leaves the text, the cursor and the window as vim does,
    on plain, wide (panned) and indented files, deep in 100 K."""
    import hashlib
    for f, keys, sha, want in VIM_BS:
        content = make_wide() if f == 'wide' else make_indent() if f == 'indent' else make(f)
        e = Editor(content)
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                if k.endswith('\x1b'):
                    send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim BS {f} {k[:12]!r}: {got} == {(wrow, wcol)} {wcur[:12]!r} {wtop[:12]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim BS {f} {keys[0]!r}..: file as vim wrote it ({got})', got == sha)
            check(f'vim BS {f} {keys[0]!r}..: :q exits after :w', at_ccp(e, ':q\r'))
        finally:
            e.close()


def insert_bs(label, n):
    """BS in insert mode on every size: a no-op at the start of the file (the
    file stays unmodified), a join deep in the file, BS over typed text, and a
    run of BS back past the start of the resident window; :w byte-exact."""
    e = Editor(make(n))
    try:
        e.key('i' + BS + BS); send_keys(e, '\x1b')
        v = e.screen()
        check(f'{label}: BS at the start of the file stays home', (v.row, v.col) == (0, 0))
        check(f'{label}: BS at the start of the file leaves it unmodified',
              at_ccp(e, ':q\r'))
    finally:
        e.close()

    L = lines_of(n)
    e = Editor(make(n))
    try:
        tgt = min(n, 4000)                        # 0-based line index to join
        if tgt >= 2:
            e.key('%dj' % (tgt - 1))
            e.key('i' + BS); send_keys(e, '\x1b')
            L[tgt - 2:tgt] = [L[tgt - 2] + L[tgt - 1]]
            v = e.screen()
            check(f'{label}: BS joins line {tgt} onto {tgt - 1}',
                  (rows(e)[v.row], v.col) == (L[tgt - 2], 5))
        e.key('iAB' + BS + 'C' + BS * 3 + 'D\r'); send_keys(e, '\x1b')
        at = max(tgt - 2, 0)
        c = 5 if tgt >= 2 else 0                  # insert point in line `at`
        t = L[at] if at < len(L) else ''
        L[at:at + 1] = [t[:c - 1] + 'D' if c else 'D', t[c:]] if c else ['D', t]
        if n == 0:
            L = ['D']                             # the empty buffer gets 'D\r\n'
        e.key('i' + BS * 20); send_keys(e, '\x1b')
        text = '\n'.join(L)
        cur = sum(len(l) + 1 for l in L[:at + 1])  # just after 'D\n'
        text = text[:max(cur - 20, 0)] + text[cur:]
        e.key(':w\r')
        want = (text + '\n').replace('\n', '\r\n').encode() if text else b''
        if n == 0:
            # here the insert ran at the END of the text, so its <CR> opened a
            # real empty last line and put a terminator AHEAD of the cursor --
            # where a BS, which deletes backward, can never reach it.  What is
            # left is that one empty line.  vim writes the same buffer as one
            # line end too (measured: a buffer of one empty line that has been
            # edited writes '\n', not nothing).
            want = b'\r\n'
        check(f'{label}: BS edits :w byte-exact', saved_bytes(e) == want)
    finally:
        e.close()

    # A run of BS back past the start of the resident window.  The run has to be
    # LONGER than the cursor's reach into the window or it never crosses the
    # start and the backward page is not exercised at all -- and how far in the
    # cursor lands moves with the arena, which every byte of the image shrinks
    # (it was 568 bytes, and a hard-coded 650, until the yank register's three
    # records pushed it to 696).  So the count is derived from the measurement.
    if n < 5120:
        return
    e = Editor(make(n))
    try:
        e.key('G'); e.key('3000k')
        word = lambda s: int.from_bytes(bytes(e.s.mem(SYM[s], 2)), 'little')
        back = word('GAPBEG') - word('TXTBEG')
        k = back + 100
        check(f'{label}: {k} BS crosses the window start ({back} bytes into it)',
              0 < back < k)
        e.key('i' + BS * k); send_keys(e, '\x1b')
        e.key(':w\r')
        cur = (n - 3000 - 1) * 8
        want = make(n)
        # bytes removed = the backspaces, plus one more for each line end they
        # cross (a line is 6 digits + its end = 7 of them, CR,LF = 2 bytes)
        want = want[:cur - k - (k + 6) // 7] + want[cur:]
        check(f'{label}: BS run past the window :w byte-exact', saved_bytes(e) == want)
    finally:
        e.close()


# Ndd, from vim 9.1 (-u NONE -N, 24 lines, 'nowrap'): the cursor goes to the
# first non-blank of the line that moved up, the window top stays put, a count
# past the end deletes to the end, and a count over 1 on the last line does
# nothing (vim's cursor_down fails there).  (file, keys, sha1 of the file vim
# wrote, [(cursor row, cursor column, cursor line, top line) after each key]).
VIM_NDD = [
    ('wide', ['700G', '5dd', 'j'], 'd774b04237a82db3',
     [(11, 0, '000700', '000689'),
      (11, 0, '000705' + 'x' * 194, '000689'),
      (12, 0, '000706', '000689')]),
    ('wide', ['699G', '3dd', 'k'], '2d65840179e6b988',
     [(11, 0, '000699' + 'x' * 194, '000688'),
      (11, 0, '000702' + 'x' * 194, '000688'),
      (10, 0, '000698', '000688')]),
    ('wide', ['700G', '11k', '30dd', 'j'], 'ff540c16a65cf8ae',
     [(11, 0, '000700', '000689'),
      (0, 0, '000689', '000689'),
      (0, 0, '000719', '000719'),
      (1, 0, '000720' + 'x' * 194, '000719')]),
    ('wide', ['700G', '11j', '4dd', 'k'], '7f16f46771a29af4',
     [(11, 0, '000700', '000689'),
      (22, 0, '000711' + 'x' * 194, '000689'),
      (22, 0, '000715', '000689'),
      (21, 0, '000710', '000689')]),
    ('wide', ['702G', '$', 'dd', 'k'], '4a8ed95d310e9a8c',
     [(11, 0, '000702' + 'x' * 194, '000691'),
      (11, 199, '000702' + 'x' * 194, '000691'),
      (11, 0, '000703', '000691'),
      (10, 0, '000701', '000691')]),
    ('wide', ['700G', '$', 'k', '3dd', 'j'], '2d65840179e6b988',
     [(11, 0, '000700', '000689'),
      (11, 5, '000700', '000689'),
      (10, 199, '000699' + 'x' * 194, '000689'),
      (10, 0, '000702' + 'x' * 194, '000689'),
      (11, 0, '000703', '000689')]),
    ('wide', ['G', '3dd', '9dd'], 'cf4987bfafeec1cc',
     [(22, 0, '001500' + 'x' * 194, '001478'),
      (22, 0, '001500' + 'x' * 194, '001478'),
      (22, 0, '001500' + 'x' * 194, '001478')]),
    ('indent', ['3000G', '3dd', 'j'], '127a3d86fe076c7a',
     [(11, 10, '\t  003000', '    002989'),
      (11, 4, '    003003', '    002989'),
      (12, 7, '\t  003004', '    002989')]),
    ('indent', ['5998G', '9dd', 'k'], '3146e1ed088add14',
     [(20, 10, '\t  005998', '\t  005978'),
      (19, 4, '    005997', '\t  005978'),
      (18, 7, '\t  005996', '\t  005978')]),
    ('indent', ['3001G', '$', '2dd', 'j'], '7512c2b640fa9f1d',
     [(11, 4, '    003001', '\t  002990'),
      (11, 9, '    003001', '\t  002990'),
      (11, 4, '    003003', '\t  002990'),
      (12, 7, '\t  003004', '\t  002990')]),
    ('tabs', ['j', '$', '2dd', 'j'], '05f425184b62e62c',
     [(1, 7, 'xyzuvwrstuvwxyz', '\tab'),
      (1, 14, 'xyzuvwrstuvwxyz', '\tab'),
      (1, 16, '\t\tq', '\tab'),
      (2, 1, 'ab', '\tab')]),
    (5120, ['2000G', '2500dd', 'j'], '4bc116034371114f',
     [(11, 0, '002000', '001989'),
      (11, 0, '004500', '001989'),
      (12, 0, '004501', '001989')]),
    (5120, ['G', '3000k', '2500dd', 'k'], '78aabab1b3eafaf7',
     [(22, 0, '005120', '005098'),
      (11, 0, '002120', '002109'),
      (11, 0, '004620', '002109'),
      (10, 0, '002119', '002109')]),
    (5120, ['gg', '5dd', 'G', '5dd'], '8941293b4a3a2c29',
     [(0, 0, '000001', '000001'),
      (0, 0, '000006', '000006'),
      (22, 0, '005120', '005098'),
      (22, 0, '005120', '005098')]),
    (12800, ['10000G', '2500dd', 'j'], '9b8c205224a3c13b',
     [(11, 0, '010000', '009989'),
      (11, 0, '012500', '009989'),
      (12, 0, '012501', '009989')]),
    (12800, ['G', '3000k', '2500dd', 'k'], 'd08c0331d39550ae',
     [(22, 0, '012800', '012778'),
      (11, 0, '009800', '009789'),
      (11, 0, '012300', '009789'),
      (10, 0, '009799', '009789')]),
    (12800, ['5000G', '12dd', '11dd', '23dd'], 'b43e0a2b5031a740',
     [(11, 0, '005000', '004989'),
      (11, 0, '005012', '004989'),
      (11, 0, '005023', '004989'),
      (11, 0, '005046', '004989')]),
    (3, ['2G', '5dd', '3dd'], 'f67066ff0df3c6d6',
     [(1, 0, '000002', '000001'),
      (0, 0, '000001', '000001'),
      (0, 0, '000001', '000001')]),
    (1, ['9dd'], 'f67066ff0df3c6d6',
     [(0, 0, '000001', '000001')]),
]


def ndd_like_vim():
    """Ndd leaves the text, the cursor and the window as vim does, on plain,
    wide (panned), indented and tabbed files, deep in 100 K."""
    import hashlib
    tabs = b''.join(l.encode() + b'\r\n' for l in TABJK_LINES)
    for f, keys, sha, want in VIM_NDD:
        content = (make_wide() if f == 'wide' else make_indent() if f == 'indent'
                   else tabs if f == 'tabs' else make(f))
        e = Editor(content)
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim Ndd {f} {keys!r} {k!r}: {got} == {(wrow, wcol)} {wcur[:12]!r} {wtop[:12]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim Ndd {f} {keys!r}: file as vim wrote it ({got})', got == sha)
        finally:
            e.close()


# The ':' line as vim's: the bottom row shows ':' and each char typed, BS and
# DEL erase the last one, and BS/DEL on an empty line or ESC cancels it (vim
# leaves the cancelled line on the row, and so does this).  (setup keys, file).
EX_FILES = [
    ([], 3),
    (['44G', '$'], 'wide'),               # a panned wide line
    (['G', '3000k'], 12800),              # deep in 100 K
]


def ex_like_vim():
    """Echo and editing on the ':' line, then the edited line is what runs."""
    for setup, f in EX_FILES:
        content = make_wide() if f == 'wide' else make(f)
        e = Editor(content)
        try:
            for k in setup:
                e.key(k)
            v0 = e.screen(); scr0 = [''.join(r) for r in v0.screen]
            cur0 = (v0.row, v0.col)

            def bottom():
                v = e.screen()
                return ''.join(v.screen[23]).rstrip(), (v.row, v.col)

            def cancelled(tag):
                v = e.screen(); scr = [''.join(r) for r in v.screen]
                check(f'ex {f} {tag}: text rows kept', scr[:23] == scr0[:23])
                check(f'ex {f} {tag}: the cancelled line stays on the row '
                      f'({scr[23].rstrip()!r}), as vim leaves it there too',
                      scr[23].lstrip()[:1] in (':', '/', '?'))
                check(f'ex {f} {tag}: cursor back {(v.row, v.col)} == {cur0}',
                      (v.row, v.col) == cur0)

            for k, want in ((':', ':'), ('q', ':q'), ('x', ':qx'), ('\x08', ':q'),
                            ('\x7f', ':')):
                e.key(k)
                got = bottom()
                check(f'ex {f} {k!r}: bottom row {got} == {want!r}',
                      got == (want, (23, len(want))))
            e.key('\x08')
            cancelled('BS on empty')
            e.key(':'); e.key('\x7f')
            cancelled('DEL on empty')
            e.key(':'); e.key('ab')
            check(f'ex {f} ab: echoed', bottom() == (':ab', (23, 3)))
            e.key('\x1b')
            for _ in range(200):
                if not bottom()[0].startswith(':'):
                    break
                e.s._run()
            e.s.run_until_quiet()
            cancelled('ESC')
            check(f'ex {f}: :qq BS runs :q (unmodified, exits)',
                  at_ccp(e, ':qq\x08\r'))
        finally:
            e.close()
    e = Editor(make_wide())
    try:
        e.key('x')
        check('ex: :q! BS runs :q (modified, refuses)', not at_ccp(e, ':q!\x08\r'))
        check('ex: :q refused shows vim\'s message', rows(e)[-1] == NWR)
        check('ex: :wq DEL DEL q! runs :q! (exits)', at_ccp(e, ':wq\x7f\x7fq!\r'))
        check('ex: :q! left the file unchanged', saved_bytes(e) == make_wide())
    finally:
        e.close()


def word_lines(n=3300):
    """Words for w b W B: word chars, punctuation, empty and blank-only lines,
    tabs, indents and 200-column lines (100 K at 3300 lines)."""
    return [['%05d foo.bar(baz) qux_1' % i, '', '\t  %05d  x,y;;z  ' % i, '   ',
             '(%05d)-->' % i + ' ab-cd' * 32, 'end%05d.' % i,
             '\t\t%05d\tTAB\tsep' % i, '', '', '  %05d a b  c' % i][i % 10]
            for i in range(1, n + 1)]


MOT_FILES = {
    'wd': word_lines(),
    'ws': ['  ab.cd  ef', '', '  ', 'gh'],        # no line end after the last
    'one': ['  hello world'],
}

# (file, keys, [(cursor line, top line, cursor row, cursor column) after each
# key]) from vim 9.1 (-u NONE -N, 24 lines, 'nowrap').
VIM_MOT = [
    ('wd', ['w'] * 22,
     ['2 1 1 10', '2 1 1 17', '2 1 1 18', '2 1 1 19', '2 1 1 20', '2 1 1 22', '4 1 3 0', '4 1 3 1',
      '4 1 3 6', '4 1 3 11', '4 1 3 13', '4 1 3 14', '4 1 3 17', '4 1 3 19', '4 1 3 20', '4 1 3 23',
      '4 1 3 25', '4 1 3 26', '4 1 3 29', '4 1 3 31', '4 1 3 32', '4 1 3 35']),
    ('wd', ['W'] * 16,
     ['2 1 1 10', '2 1 1 17', '4 1 3 0', '4 1 3 11', '4 1 3 17', '4 1 3 23', '4 1 3 29', '4 1 3 35',
      '4 1 3 41', '4 1 3 47', '4 1 3 53', '4 1 3 59', '4 1 3 65', '4 1 3 71', '4 1 3 77', '4 1 3 83']),
    ('wd', ['G'] + ['b'] * 14,
     ['3300 3278 22 0', '3299 3278 21 13', '3299 3278 21 10', '3299 3278 21 8', '3299 3278 21 2',
      '3298 3278 20 0', '3297 3278 19 0', '3296 3278 18 32', '3296 3278 18 24', '3296 3278 18 16',
      '3295 3278 17 8', '3295 3278 17 0', '3294 3278 16 200', '3294 3278 16 199', '3294 3278 16 197']),
    ('wd', ['G'] + ['B'] * 10,
     ['3300 3278 22 0', '3299 3278 21 13', '3299 3278 21 10', '3299 3278 21 8', '3299 3278 21 2',
      '3298 3278 20 0', '3297 3278 19 0', '3296 3278 18 32', '3296 3278 18 24', '3296 3278 18 16',
      '3295 3278 17 0']),
    ('wd', ['G', '$', 'w', 'w', 'b'],
     ['3300 3278 22 0', '3300 3278 22 23', '3300 3278 22 23', '3300 3278 22 23', '3300 3278 22 19']),
    ('wd', ['G', 'k', 'w', 'w', 'w', 'w', 'w', 'w'],
     ['3300 3278 22 0', '3299 3278 21 0', '3299 3278 21 2', '3299 3278 21 8', '3299 3278 21 10',
      '3299 3278 21 13', '3300 3278 22 0', '3300 3278 22 6']),
    ('wd', ['b', 'B', 'w', 'b', 'b'], ['1 1 0 0', '1 1 0 0', '2 1 1 10', '1 1 0 0', '1 1 0 0']),
    ('wd', ['500w', '500b'], ['41 30 11 0', '1 1 0 0']),
    ('wd', ['2000w', '3000W', '300B', '2000b'],
     ['161 150 11 0', '774 763 11 53', '714 703 11 17', '554 543 11 17']),
    ('wd', ['99999w', 'b', '99999B'], ['3300 3278 22 23', '3300 3278 22 19', '1 1 0 0']),
    ('wd', ['G', '99999b', 'w'], ['3300 3278 22 0', '1 1 0 0', '2 1 1 10']),
    ('wd', ['1500G', '400W', '800B', '7w'],
     ['1500 1489 11 0', '1584 1573 11 17', '1416 1405 11 24', '1419 1405 14 13']),
    ('wd', ['1203G', 'b', 'b', 'w', 'w'],
     ['1203 1192 11 2', '1202 1192 10 22', '1202 1192 10 20', '1202 1192 10 22', '1204 1192 12 0']),
    ('wd', ['5j', '0', '^', '$', '0', '$', 'j', 'k'],
     ['6 1 5 7', '6 1 5 7', '6 1 5 16', '6 1 5 34', '6 1 5 7', '6 1 5 34', '7 1 6 0', '6 1 5 34']),
    ('wd', ['3j', '^', '$', '0', '^', 'j'],
     ['4 1 3 0', '4 1 3 0', '4 1 3 201', '4 1 3 0', '4 1 3 0', '5 1 4 0']),
    ('wd', ['2j', '$', '^', '0', 'w', 'b', 'j'],
     ['3 1 2 0', '3 1 2 2', '3 1 2 2', '3 1 2 0', '4 1 3 0', '2 1 1 22', '3 1 2 2']),
    ('wd', ['4j', '$', '0', '$', 'w', 'b', 'B', 'b'],
     ['5 1 4 0', '5 1 4 8', '5 1 4 0', '5 1 4 8', '6 1 5 16', '5 1 4 8', '5 1 4 0', '4 1 3 200']),
    ('wd', ['4j', '$', 'j', 'k', '0', '12w', '^'],
     ['5 1 4 0', '5 1 4 8', '6 1 5 34', '5 1 4 8', '5 1 4 0', '10 1 9 6', '10 1 9 0']),
    ('wd', ['3$', '5$', '$', '100$', 'k'],
     ['3 1 2 2', '7 1 6 0', '7 1 6 0', '106 95 11 34', '105 95 10 8']),
    ('wd', ['G', '2$', 'k', 'j'],
     ['3300 3278 22 0', '3300 3278 22 0', '3299 3278 21 13', '3300 3278 22 23']),
    ('wd', ['G', 'k', '5$', 'k'],
     ['3300 3278 22 0', '3299 3278 21 0', '3300 3278 22 23', '3299 3278 21 13']),
    ('wd', ['1650G', '^', '$', '0', '3w'],
     ['1650 1639 11 0', '1650 1639 11 0', '1650 1639 11 23', '1650 1639 11 0', '1650 1639 11 10']),
    ('wd', ['1655G', '$', '0', '9$', '^'],
     ['1655 1644 11 0', '1655 1644 11 8', '1655 1644 11 0', '1663 1644 19 2', '1663 1644 19 2']),
    ('wd', ['2j', '4l', '0', 'j', '^', 'k'],
     ['3 1 2 0', '3 1 2 2', '3 1 2 0', '4 1 3 0', '4 1 3 0', '3 1 2 0']),
    ('wd', ['\r', '\r', '5\r', '30\r', '500\r', '\r', 'k'],
     ['2 1 1 10', '3 1 2 2', '8 1 7 0', '38 27 11 0', '538 527 11 0', '539 527 12 2', '538 527 11 0']),
    ('wd', ['G', '\r', '0', '\r'],
     ['3300 3278 22 0', '3300 3278 22 0', '3300 3278 22 0', '3300 3278 22 0']),
    ('wd', ['3295G', 'l', 'l', '\r', '99\r'],
     ['3295 3278 17 0', '3295 3278 17 1', '3295 3278 17 2', '3296 3278 18 16', '3300 3278 22 0']),
    ('wd', ['2j', '$', '\r', 'j', '\r'],
     ['3 1 2 0', '3 1 2 2', '4 1 3 0', '5 1 4 0', '6 1 5 16']),
    ('wd', ['4j', '$', '\r', '2\r', '3\r'],
     ['5 1 4 0', '5 1 4 8', '6 1 5 16', '8 1 7 0', '11 1 10 0']),
    ('wd', ['1500G', '23\r', '24\r', '12\r', '13\r'],
     ['1500 1489 11 0', '1523 1501 22 2', '1547 1536 11 0', '1559 1537 22 2', '1572 1561 11 10']),
    ('wd', ['3000G', '9999\r', 'gg', '3000\r'],
     ['3000 2989 11 0', '3300 3278 22 0', '1 1 0 0', '3001 2990 11 0']),
    ('ws', ['w', 'w', 'w', 'w', 'w', 'w', 'b', 'b', 'b', 'b', 'b', 'b'],
     ['1 1 0 2', '1 1 0 4', '1 1 0 5', '1 1 0 9', '2 1 1 0', '4 1 3 0', '2 1 1 0', '1 1 0 9',
      '1 1 0 5', '1 1 0 4', '1 1 0 2', '1 1 0 0']),
    ('ws', ['G', '$', 'w', '0', 'b', '^', 'W', 'B'],
     ['4 1 3 0', '4 1 3 1', '4 1 3 1', '4 1 3 0', '2 1 1 0', '2 1 1 0', '4 1 3 0', '2 1 1 0']),
    ('ws', ['$', '3$', '\r', '\r', '\r', '0', '9$'],
     ['1 1 0 10', '3 1 2 1', '4 1 3 0', '4 1 3 0', '4 1 3 0', '4 1 3 0', '4 1 3 0']),
    ('ws', ['2j', '^', '$', 'w', 'w', 'B', 'B', 'B'],
     ['3 1 2 0', '3 1 2 1', '3 1 2 1', '4 1 3 0', '4 1 3 1', '4 1 3 0', '2 1 1 0', '1 1 0 9']),
    ('one', ['w', 'w', 'w', 'b', 'b', 'b', '0', '^', '$', '\r', 'W', 'B'],
     ['1 1 0 2', '1 1 0 8', '1 1 0 12', '1 1 0 8', '1 1 0 2', '1 1 0 0', '1 1 0 0', '1 1 0 2',
      '1 1 0 12', '1 1 0 12', '1 1 0 12', '1 1 0 8']),
]


def mot_like_vim():
    """0 ^ $ <CR> w b W B (with counts) land where vim does and scroll as it
    does, on 0 / 1-line / small / 100 K files; the screen rows shown must be
    the file's lines (panned as the cursor's)."""
    for f, keys, want in VIM_MOT:
        lines = MOT_FILES[f]
        content = '\r\n'.join(lines).encode() + (b'' if f == 'ws' else b'\r\n')
        e = Editor(content)
        try:
            for k, w in zip(keys, want):
                e.key(k)
                v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                scr = [''.join(r).rstrip() for r in v.screen]
                show = lambda n: expand(lines[n - 1])[hs:hs + 80].rstrip()
                ln, top, row, col = map(int, w.split())
                got = '%d %d' % (v.row, v.col + hs)
                check(f'vim {f} {keys!r} {k!r}: {got} == {row} {col}', got == '%d %d' % (row, col))
                check(f'vim {f} {keys!r} {k!r}: rows show lines {top} and {ln}',
                      scr[0] == show(top) and scr[row] == show(ln))
            if f == 'wd' and keys[0] == '2000w':
                check('mot: motions leave the file unmodified (:q exits)', at_ccp(e, ':q\r'))
        finally:
            e.close()
    e = Editor(b'')
    try:
        for k in ['w', 'b', 'W', 'B', '0', '^', '$', '\r', '3w', '3B', '5\r', '9$']:
            e.key(k)
            v = e.screen()
            check(f'empty: {k!r} stays home', (v.row, v.col) == (0, 0))
        check('empty: motions leave it unmodified (:q exits)', at_ccp(e, ':q\r'))
    finally:
        e.close()


# (file, keys, [(cursor line, top line, cursor row, cursor column) after each
# key]) from vim 9.1 (-u NONE -N, 24 lines, 'nowrap'): ':e' reloads the file at
# the cursor's line, on the middle row (clamped at either end of the file), on
# the first non-blank; ':e!' drops the changes.
VIM_EDIT = [
    ('num', ['3000G', ':e\r', 'G', ':e\r', '5G', ':e\r', '12G', ':e\r', '13G', ':e\r', '23G',
             ':e\r', '40G', ':e\r', '12790G', ':e\r', 'gg', ':e\r'],
     ['3000 2989 11 0', '3000 2989 11 0', '12800 12778 22 0', '12800 12778 22 0', '5 1 4 0',
      '5 1 4 0', '12 1 11 0', '12 1 11 0', '13 1 12 0', '13 2 11 0', '23 2 21 0', '23 12 11 0',
      '40 18 22 0', '40 29 11 0', '12790 12778 12 0', '12790 12778 12 0', '1 1 0 0', '1 1 0 0']),
    ('num', ['6000G', '\x06', ':e\r', '\x02\x02', ':e\r', '11000G', 'k', ':e\r'],
     ['6000 5989 11 0', '6010 6010 0 0', '6010 5999 11 0', '5979 5957 22 0', '5979 5968 11 0',
      '11000 10989 11 0', '10999 10989 10 0', '10999 10988 11 0']),
    ('num', ['G', 'dd', 'dd', ':e!\r', '500G', '10dd', ':e!\r', 'G', 'i\r\x1b', ':e!\r'],
     ['12800 12778 22 0', '12799 12778 21 0', '12798 12778 20 0', '12798 12778 20 0',
      '500 489 11 0', '500 489 11 0', '500 489 11 0', '12800 12778 22 0', '12801 12779 22 0',
      '12800 12778 22 0']),
    ('wide', ['5G', '$', ':e\r', '600G', '$', ':e\r', 'G', ':e\r', '1495G', ':e\r'],
     ['5 1 4 0', '5 1 4 5', '5 1 4 0', '600 589 11 0', '600 589 11 199', '600 589 11 0',
      '1500 1478 22 0', '1500 1478 22 0', '1495 1478 17 0', '1495 1478 17 0']),
    ('ind', ['G', ':e\r', '3001G', 'l', ':e\r', '2G', ':e\r', '6000G', 'k', 'k', ':e\r'],
     ['6000 5978 22 10', '6000 5978 22 10', '3001 2990 11 4', '3001 2990 11 5', '3001 2990 11 4',
      '2 1 1 10', '2 1 1 10', '6000 5978 22 10', '5999 5978 21 9', '5998 5978 20 10',
      '5998 5978 20 10']),
    ('wd', ['1500G', '5w', ':e\r', '1505G', '$', ':e\r', '3299G', ':e\r'],
     ['1500 1489 11 0', '1500 1489 11 14', '1500 1489 11 0', '1505 1489 16 0', '1505 1489 16 8',
      '1505 1494 11 0', '3299 3278 21 2', '3299 3278 21 2']),
]


def edit_files():
    return {'num': make(12800), 'wide': make_wide(), 'ind': make_indent(),
            'wd': ('\r\n'.join(MOT_FILES['wd']) + '\r\n').encode()}


def edit_like_vim():
    """':e' / ':e!' put the file back where vim does, on 100 K, wide and
    indented files; the rows shown are the file's; the text is unmodified."""
    files = edit_files()
    for f, keys, want in VIM_EDIT:
        lines = files[f].decode().split('\r\n')
        e = Editor(files[f])
        try:
            for k, w in zip(keys, want):
                if k == 'i\r\x1b':
                    send_keys(e, 'i\r'); send_keys(e, '\x1b')
                    lines.insert(12799, '')
                else:
                    e.key(k)
                if k.startswith(':e'):
                    lines = files[f].decode().split('\r\n')
                if k == 'dd':
                    del lines[int(w.split()[0])]
                if k == '10dd':
                    del lines[499:509]
                v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                scr = [''.join(r).rstrip() for r in v.screen]
                show = lambda n: expand(lines[n - 1])[hs:hs + 80].rstrip()
                ln, top, row, col = map(int, w.split())
                got = '%d %d' % (v.row, v.col + hs)
                check(f'edit {f} {keys!r} {k!r}: {got} == {row} {col}', got == '%d %d' % (row, col))
                check(f'edit {f} {keys!r} {k!r}: rows show lines {top} and {ln}',
                      scr[0] == show(top) and scr[row] == show(ln))
                if k.startswith(':e'):
                    check(f'edit {f} {keys!r} {k!r}: ":e" names the file',
                          scr[23].rstrip() == '"TEST.TXT"')
            check(f'edit {f} {keys!r}: unmodified after :e (:q exits)', at_ccp(e, ':q\r'))
            check(f'edit {f} {keys!r}: the file is unchanged', saved_bytes(e) == files[f])
        finally:
            e.close()


# (file, keys, [(cursor line, top line, cursor row, cursor column) after each
# key]) from vim 9.1 (-u NONE -N, 24 lines, 'nowrap').  H / M / L go to a screen
# row -- the count'th from the top, the middle text row, the count'th up from the
# last text row -- on the first non-blank, and never scroll: a count past the
# window is clamped to the bottom / top row (vim's cursor_correct), and a count
# past the last text row (the '~' rows at the end of the file) to that row.
VIM_HML = [
    ('num', ['3000G', 'H', 'M', 'L'],
     ['3000 2989 11 0', '2989 2989 0 0', '3000 2989 11 0', '3011 2989 22 0']),
    ('num', ['3000G', '5H', '5L', 'M'],
     ['3000 2989 11 0', '2993 2989 4 0', '3007 2989 18 0', '3000 2989 11 0']),
    ('num', ['3000G', '22H', '23H', '22L', '23L'],
     ['3000 2989 11 0', '3010 2989 21 0', '3011 2989 22 0', '2990 2989 1 0', '2989 2989 0 0']),
    ('num', ['3000G', '30H', 'M', '30L', 'H'],
     ['3000 2989 11 0', '3011 2989 22 0', '3000 2989 11 0', '2989 2989 0 0', '2989 2989 0 0']),
    ('num', ['3000G', '100H', '100L', '999H'],
     ['3000 2989 11 0', '3011 2989 22 0', '2989 2989 0 0', '3011 2989 22 0']),
    ('num', ['G', 'H', 'M', 'L', '5H', '5L'],
     ['12800 12778 22 0', '12778 12778 0 0', '12789 12778 11 0', '12800 12778 22 0',
      '12782 12778 4 0', '12796 12778 18 0']),
    ('num', ['gg', 'H', 'L', 'M', '3H', '9L', '30L'],
     ['1 1 0 0', '1 1 0 0', '23 1 22 0', '12 1 11 0', '3 1 2 0', '15 1 14 0', '1 1 0 0']),
    ('num', ['G', '\x06', 'H', 'M', 'L', '3H', '3L', '99H'],
     ['12800 12778 22 0', '12800 12800 0 0', '12800 12800 0 0', '12800 12800 0 0',
      '12800 12800 0 0', '12800 12800 0 0', '12800 12800 0 0', '12800 12800 0 0']),
    ('num', ['G', '\x06', '5L', 'M'],
     ['12800 12778 22 0', '12800 12800 0 0', '12800 12800 0 0', '12800 12800 0 0']),
    ('num', ['6000G', '\x04', 'H', 'L', 'M', '12H'],
     ['6000 5989 11 0', '6011 6000 11 0', '6000 6000 0 0', '6022 6000 22 0', '6011 6000 11 0',
      '6011 6000 11 0']),
    ('num', ['12790G', 'H', 'M', 'L'],
     ['12790 12778 12 0', '12778 12778 0 0', '12789 12778 11 0', '12800 12778 22 0']),
    ('num', ['3000G', 'H', 'j', 'M', 'k', 'L', 'H'],
     ['3000 2989 11 0', '2989 2989 0 0', '2990 2989 1 0', '3000 2989 11 0', '2999 2989 10 0',
      '3011 2989 22 0', '2989 2989 0 0']),
    ('num', ['3000G', 'H', '\x06', 'M', '\x02', 'L'],
     ['3000 2989 11 0', '2989 2989 0 0', '3010 3010 0 0', '3021 3010 11 0', '3011 2989 22 0',
      '3011 2989 22 0']),
    ('num', ['G', 'dd', 'H', 'M', 'L'],
     ['12800 12778 22 0', '12799 12778 21 0', '12778 12778 0 0', '12788 12778 10 0',
      '12799 12778 21 0']),
    ('wide', ['700G', '$', 'H', 'M', 'L'],
     ['700 689 11 0', '700 689 11 5', '689 689 0 0', '700 689 11 0', '711 689 22 0']),
    ('wide', ['700G', '$', '5L', '$', '5H'],
     ['700 689 11 0', '700 689 11 5', '707 689 18 0', '707 689 18 5', '693 689 4 0']),
    ('wide', ['G', 'H', 'M', 'L', '30H'],
     ['1500 1478 22 0', '1478 1478 0 0', '1489 1478 11 0', '1500 1478 22 0', '1500 1478 22 0']),
    ('wide', ['G', '$', 'H', 'M', 'L', '\x02', 'M'],
     ['1500 1478 22 0', '1500 1478 22 199', '1478 1478 0 0', '1489 1478 11 0', '1500 1478 22 0',
      '1479 1457 22 0', '1468 1457 11 0']),
    ('ind', ['3000G', 'H', 'M', 'L', '2H', '2L'],
     ['3000 2989 11 10', '2989 2989 0 4', '3000 2989 11 10', '3011 2989 22 4', '2990 2989 1 10',
      '3010 2989 21 10']),
    ('ind', ['G', 'M', 'H', '40L'],
     ['6000 5978 22 10', '5989 5978 11 4', '5978 5978 0 10', '5978 5978 0 10']),
    ('ind', ['3000G', 'L', 'j', 'H', 'k', 'M'],
     ['3000 2989 11 10', '3011 2989 22 4', '3012 2990 22 7', '2990 2990 0 10', '2989 2989 0 9',
      '3000 2989 11 10']),
    ('wd', ['1500G', 'H', 'M', 'L', '4H', '7L'],
     ['1500 1489 11 0', '1489 1489 0 2', '1500 1489 11 0', '1511 1489 22 0', '1492 1489 3 10',
      '1505 1489 16 0']),
    ('wd', ['G', 'H', 'M', 'L'],
     ['3300 3278 22 0', '3278 3278 0 0', '3289 3278 11 2', '3300 3278 22 0']),
    ('wd', ['1500G', '4H', 'j', 'j', 'k'],
     ['1500 1489 11 0', '1492 1489 3 10', '1493 1489 4 2', '1494 1489 5 10', '1493 1489 4 2']),
    ('wd', ['1500G', 'L', 'k', 'H', 'j'],
     ['1500 1489 11 0', '1511 1489 22 0', '1510 1489 21 0', '1489 1489 0 2', '1490 1489 1 2']),
    ('3', ['H', 'M', 'L', '2H', '3H', '9H', '2L', '3L', '9L'],
     ['1 1 0 2', '2 1 1 0', '3 1 2 0', '2 1 1 0', '3 1 2 0', '3 1 2 0', '2 1 1 0', '1 1 0 2',
      '1 1 0 2']),
    ('2', ['H', 'M', 'L', '2H', '2L', '5L'],
     ['1 1 0 0', '1 1 0 0', '2 1 1 2', '2 1 1 2', '1 1 0 0', '1 1 0 0']),
    ('1', ['H', 'M', 'L', '5H', '5L'],
     ['1 1 0 3', '1 1 0 3', '1 1 0 3', '1 1 0 3', '1 1 0 3']),
    ('nl', ['H', 'M', 'L', '3H', '2L', 'G', 'H'],
     ['1 1 0 2', '2 1 1 0', '4 1 3 2', '3 1 2 0', '3 1 2 0', '4 1 3 2', '1 1 0 2']),
]


def hml_files():
    return {'num': make(12800), 'wide': make_wide(), 'ind': make_indent(),
            'wd': ('\r\n'.join(MOT_FILES['wd']) + '\r\n').encode(),
            '3': b'  aaa\r\n\r\nbbb\r\n', '2': b'ab\r\n  cd\r\n', '1': b'   one\r\n',
            'nl': b'  aa\r\n\r\nbb\r\n  cc'}          # no line end after the last


def hml_like_vim():
    """H / M / L (with counts) land where vim does on 1-line / small / 66 K /
    109 K / 100 K files, over '~' rows at the end of the file and after the
    scrolls, and leave the window where it was."""
    files = hml_files()
    for f, keys, want in VIM_HML:
        e = Editor(files[f])
        try:
            lines = files[f].decode().split('\r\n')
            if lines[-1] == '':
                lines.pop()
            for k, w in zip(keys, want):
                e.key(k)
                if k == 'dd':
                    del lines[int(w.split()[0])]
                v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                scr = [''.join(r).rstrip() for r in v.screen]
                show = lambda n: expand(lines[n - 1])[hs:hs + 80].rstrip()
                ln, top, row, col = map(int, w.split())
                got = '%d %d' % (v.row, v.col + hs)
                check(f'hml {f} {keys!r} {k!r}: {got} == {row} {col}', got == '%d %d' % (row, col))
                check(f'hml {f} {keys!r} {k!r}: rows show lines {top} and {ln}',
                      scr[0] == show(top) and scr[row] == show(ln))
            if f == 'num' and keys[0] == '12790G':
                check('hml: H/M/L leave the file unmodified (:q exits)', at_ccp(e, ':q\r'))
        finally:
            e.close()
    e = Editor(b'')
    try:
        for k in ['H', 'M', 'L', '5H', '5L', '99L', '99H']:
            e.key(k)
            v = e.screen()
            check(f'hml empty: {k!r} stays home', (v.row, v.col) == (0, 0))
        check('hml empty: unmodified (:q exits)', at_ccp(e, ':q\r'))
    finally:
        e.close()


def zz_cmds():
    """ZZ is vim's ':x': it writes a changed text and quits, and only 'Z' may
    follow the first 'Z'."""
    content = make(300)
    e = Editor(content)
    try:
        e.key('5G'); e.key('x')
        check('ZZ: x marks it modified',
              ctrlg(e).startswith('"TEST.TXT" [Modified]'))
        check('ZZ: Zj does not move the cursor',
              not at_ccp(e, 'Zj') and e.screen().row == 4)
        check('ZZ: gZ drops the Z (gZZ does not quit)', not at_ccp(e, 'gZZ'))
        e.key('h')                      # swallowed: the Z that gZZ left pending
        check('ZZ: it writes and exits', at_ccp(e, 'ZZ'))
        check('ZZ: TEST.TXT holds the change',
              disk(e, 'TEST.TXT') == content.replace(b'000005', b'00005', 1))
        check('ZZ: the buffer own file keeps a .BAK', listed(cpm_dir(e), 'TEST.BAK'))
        d = cpm_dir(e)
        check(f'ZZ: no work files left {work_files(d)}', not work_files(d))
    finally:
        e.close()
    e = Editor(content)
    try:                                # unmodified: no write, no backup
        check('ZZ: a count is ignored, it exits', at_ccp(e, '3ZZ'))
        check('ZZ: TEST.TXT untouched', disk(e, 'TEST.TXT') == content)
        d = cpm_dir(e)
        check('ZZ: an unmodified text is not written (no .BAK)', not listed(d, 'TEST.BAK'))
        check(f'ZZ: no work files left {work_files(d)}', not work_files(d))
    finally:
        e.close()
    e = Editor(None, fname='')
    try:                                # no name: vim's E32 text
        send_keys(e, 'ihello'); send_keys(e, '\x1b')
        refused(e, 'ZZ', 'No file name', 'ZZ noname')
    finally:
        e.close()


def ins_files():
    """What a A I r R need beyond hml_files(): a line of blanks only, a TAB
    indent, an empty line, no line end after the last line -- and an empty
    file."""
    return {'bl': b'ab\r\n    \r\n\tcd\r\n\r\nxy', 'mt': b''}


# (file, keys, sha1 of the file vim wrote, [(cursor row, cursor column, cursor
# line, top line) after each key]) from vim 9.1 (-u NONE -N, 24 lines,
# 'nowrap'), regenerable with `python3 vimref.py --print ins`.  Every case
# starts with a motion: vim opens a file at column 0, wherever the editor puts
# its own first cursor.  No case carries a count -- see ins_cmds() for those.
# The hash is of vim's file less the final line end vim restores on a file
# staged without one (this editor writes such a file back as it was).
VIM_INS = [
    # ---- a: after the cursor char (in place on the line's end) ----
    ('3', ['0', 'aXY\x1b', 'j', 'aQ\x1b', 'j', '$aZ\x1b'], 'c04e758cb3fe1a06',
     [(0, 0, '  aaa', '  aaa'),
      (0, 2, ' XY aaa', ' XY aaa'),
      (1, 0, '', ' XY aaa'),
      (1, 0, 'Q', ' XY aaa'),
      (2, 0, 'bbb', ' XY aaa'),
      (2, 3, 'bbbZ', ' XY aaa')]),
    ('nl', ['G', '$aZZ\x1b'], 'cae449598003ff9c',
     [(3, 2, '  cc', '  aa'),
      (3, 5, '  ccZZ', '  aa')]),
    ('bl', ['0', 'aX\x1b', 'j', 'aY\x1b', 'j', 'aQ\x1b'], '38cf40ea642a56e1',
     [(0, 0, 'ab', 'ab'),
      (0, 1, 'aXb', 'aXb'),
      (1, 1, '    ', 'aXb'),
      (1, 2, '  Y  ', 'aXb'),
      (2, 7, '\tcd', 'aXb'),
      (2, 8, '\tQcd', 'aXb')]),
    ('wide', ['700G', '$aQR\x1b'], '842a6ed8d2e4fc92',
     [(11, 0, '000700', '000689'),
      (11, 7, '000700QR', '000689')]),
    ('num', ['10000G', 'llaXY\x1b'], '7b9be2946618d34d',
     [(11, 0, '010000', '009989'),
      (11, 4, '010XY000', '009989')]),
    ('mt', ['aXY\x1b'], '034f1965ccdbdf9e',
     [(0, 1, 'XY', 'XY')]),
    # ---- A: at the line content end (past a blank-only line) ----
    ('3', ['0', 'AX\x1b', 'j', 'AY\x1b', 'j', 'AZ\x1b'], '7d0e1b2669a68d2d',
     [(0, 0, '  aaa', '  aaa'),
      (0, 5, '  aaaX', '  aaaX'),
      (1, 0, '', '  aaaX'),
      (1, 0, 'Y', '  aaaX'),
      (2, 0, 'bbb', '  aaaX'),
      (2, 3, 'bbbZ', '  aaaX')]),
    ('bl', ['0', 'AX\x1b', 'j', 'AY\x1b', 'j', 'AZ\x1b', 'G', 'AQ\x1b'], '87d2f5960601e660',
     [(0, 0, 'ab', 'ab'),
      (0, 2, 'abX', 'abX'),
      (1, 2, '    ', 'abX'),
      (1, 4, '    Y', 'abX'),
      (2, 7, '\tcd', 'abX'),
      (2, 10, '\tcdZ', 'abX'),
      (4, 0, 'xy', 'abX'),
      (4, 2, 'xyQ', 'abX')]),
    ('wide', ['700G', '0AQ\x1b'], 'eed66eec71ae4f4d',
     [(11, 0, '000700', '000689'),
      (11, 6, '000700Q', '000689')]),
    ('num', ['12800G', 'AZ\x1b'], '268e53b87bb6c68b',
     [(22, 0, '012800', '012778'),
      (22, 6, '012800Z', '012778')]),
    ('ind', ['3000G', 'AX\x1b'], '3d4aa2bfbcc6c94a',
     [(11, 10, '\t  003000', '    002989'),
      (11, 16, '\t  003000X', '    002989')]),
    ('mt', ['AX\x1b'], 'c032adc1ff629c9b',
     [(0, 0, 'X', 'X')]),
    # ---- I: at the first non-blank (vim skips a blank-only line) ----
    ('3', ['$', 'IX\x1b', 'j', 'IY\x1b', 'j', '$IZ\x1b'], '36452bddb4225b30',
     [(0, 4, '  aaa', '  aaa'),
      (0, 2, '  Xaaa', '  Xaaa'),
      (1, 0, '', '  Xaaa'),
      (1, 0, 'Y', '  Xaaa'),
      (2, 0, 'bbb', '  Xaaa'),
      (2, 0, 'Zbbb', '  Xaaa')]),
    ('bl', ['0', 'IX\x1b', 'j', 'IY\x1b', 'j', '$IZ\x1b', 'G', 'IQ\x1b'], '7a12f3e7abd5cee6',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'Xab', 'Xab'),
      (1, 0, '    ', 'Xab'),
      (1, 4, '    Y', 'Xab'),
      (2, 7, '\tcd', 'Xab'),
      (2, 8, '\tZcd', 'Xab'),
      (4, 0, 'xy', 'Xab'),
      (4, 0, 'Qxy', 'Xab')]),
    ('ind', ['3000G', '$IX\x1b'], 'a288a3d22dcd0c7b',
     [(11, 10, '\t  003000', '    002989'),
      (11, 10, '\t  X003000', '    002989')]),
    ('wide', ['700G', '$IQ\x1b'], '1f863c3c22239dea',
     [(11, 0, '000700', '000689'),
      (11, 0, 'Q000700', '000689')]),
    ('mt', ['IX\x1b'], 'c032adc1ff629c9b',
     [(0, 0, 'X', 'X')]),
    # ---- r: the next char replaces the one under the cursor ----
    ('bl', ['0rZ', 'j', 'rX', 'j', 'rY', 'j', 'rQ', 'G', '$rW'], '3074308ca93475af',
     [(0, 0, 'Zb', 'Zb'),
      (1, 0, '    ', 'Zb'),
      (1, 0, 'X   ', 'Zb'),
      (2, 7, '\tcd', 'Zb'),
      (2, 0, 'Ycd', 'Zb'),
      (3, 0, '', 'Zb'),
      (3, 0, '', 'Zb'),
      (4, 0, 'xy', 'Zb'),
      (4, 1, 'xW', 'Zb')]),
    ('3', ['0l', 'r\r'], 'f51f76bca433166d',
     [(0, 1, '  aaa', '  aaa'),
      (1, 0, 'aaa', ' ')]),
    ('wide', ['700G', '50lrQ'], 'f581db4bf8d8a526',
     [(11, 0, '000700', '000689'),
      (11, 5, '00070Q', '000689')]),
    ('num', ['10000G', 'rZ', 'j', 'r3'], 'c5f2419fa8a6b627',
     [(11, 0, '010000', '009989'),
      (11, 0, 'Z10000', '009989'),
      (12, 0, '010001', '009989'),
      (12, 0, '310001', '009989')]),
    ('nl', ['G', '$rZ'], 'ecebab07bbce8f78',
     [(3, 2, '  cc', '  aa'),
      (3, 3, '  cZ', '  aa')]),
    # ---- R: replace mode (BS puts the original chars back) ----
    ('3', ['0', 'RXY\x1b', 'j', 'RQ\x1b', 'j', 'RZZZZ\x1b'], '87d7eb3815a5d87d',
     [(0, 0, '  aaa', '  aaa'),
      (0, 1, 'XYaaa', 'XYaaa'),
      (1, 0, '', 'XYaaa'),
      (1, 0, 'Q', 'XYaaa'),
      (2, 0, 'bbb', 'XYaaa'),
      (2, 3, 'ZZZZ', 'XYaaa')]),
    ('3', ['0', 'RXYZ\x08\x08\x1b'], '2fb8a81f52f92b7a',
     [(0, 0, '  aaa', '  aaa'),
      (0, 0, 'X aaa', 'X aaa')]),
    ('bl', ['0', 'RX\x1b', 'j', 'RY\x08\x1b', 'j', 'RZ\x1b', 'G', '$RQQ\x1b'], 'bae09defbc38c14e',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'Xb', 'Xb'),
      (1, 0, '    ', 'Xb'),
      (1, 0, '    ', 'Xb'),
      (2, 7, '\tcd', 'Xb'),
      (2, 0, 'Zcd', 'Xb'),
      (4, 0, 'xy', 'Xb'),
      (4, 2, 'xQQ', 'Xb')]),
    ('wide', ['700G', '100lRQQQ\x08\x08\x1b'], 'f581db4bf8d8a526',
     [(11, 0, '000700', '000689'),
      (11, 5, '00070Q', '000689')]),
    ('num', ['10000G', 'RABC\x08\x08\x08\x1b', 'j'], '22c710eca7f26684',
     [(11, 0, '010000', '009989'),
      (11, 0, '010000', '009989'),
      (12, 0, '010001', '009989')]),
    ('ind', ['3000G', '$RXY\x08\x1b'], 'da147abd69bdc6c6',
     [(11, 10, '\t  003000', '    002989'),
      (11, 15, '\t  00300X', '    002989')]),
    ('1', ['0', 'RabcdefgX\x1b'], 'd7857b4804e53987',
     [(0, 0, '   one', '   one'),
      (0, 7, 'abcdefgX', 'abcdefgX')]),
    ('nl', ['G', '$RQQ\x1b'], '174d24528722ed67',
     [(3, 2, '  cc', '  aa'),
      (3, 4, '  cQQ', '  aa')]),
    ('mt', ['RXY\x1b'], '034f1965ccdbdf9e',
     [(0, 1, 'XY', 'XY')]),
]


def ins_like_vim():
    """a A I r R put the text, the cursor and the window where vim does, on
    small files (blank-only lines, TABs, an empty line, no final line end, an
    empty file), a 66 K indented file, a 109 K file of 200-column lines and
    100 K -- and write the file vim wrote."""
    import hashlib
    files = dict(hml_files(), **ins_files())
    for f, keys, sha, want in VIM_INS:
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                if k.endswith('\x1b'):
                    send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim ins {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim ins {f} {keys!r}: file as vim wrote it ({got})', got == sha)
        finally:
            e.close()


def ins_cmds():
    """The insert commands where they are not vim: a count is ignored (vim
    repeats the text / replaces count chars), 'r' takes any char and aborts on
    ESC, and R's BS stops at the line start.  Plus the paged proofs: a 3000-char
    R run and its 3000 BS restore the file byte-exact."""
    files = dict(hml_files(), **ins_files())
    # --- counts are ignored: one copy of the text, one char replaced ---
    for keys, want in [('0' + '3aZ\x1b', 'aZb'), ('0' + '3AZ\x1b', 'abZ'),
                       ('0' + '3IZ\x1b', 'Zab'), ('0' + '3rZ', 'Zb'),
                       ('0' + '3RZ\x1b', 'Zb')]:
        e = Editor(files['bl'])
        try:
            send_keys(e, keys[:-1] if keys.endswith('\x1b') else keys)
            if keys.endswith('\x1b'):
                send_keys(e, '\x1b')
            check(f'ins count {keys!r}: {rows(e)[0]!r} == {want!r} (count ignored)',
                  rows(e)[0] == want)
        finally:
            e.close()
    # --- r: ESC aborts, a control char is stored, a digit is not a count ---
    e = Editor(files['bl'])
    try:
        e.key('0'); e.key('r\x1b')
        check("r: ESC aborts (the text stays)", rows(e)[0] == 'ab')
        check('r: ESC aborts (nothing is modified)', '[Modified]' not in ctrlg(e))
        e.key('r7')
        check('r: a digit is the char, not a count', rows(e)[0] == '7b')
        check('r: it marks the text modified',
              ctrlg(e).startswith('"TEST.TXT" [Modified]'))
    finally:
        e.close()
    # --- R: BS with nothing typed stops at the line start (vim goes to the
    #     line above), and does not undo a line break typed in R.  One editor
    #     per file read: reading the disk ends the session. ---
    e = Editor(files['bl'])
    try:
        e.key('j'); send_keys(e, 'R\x08\x08'); send_keys(e, '\x1b')
        v = e.screen()
        check(f'R: BS before anything typed stays on the line ({v.row}, {v.col})',
              (v.row, v.col) == (1, 0))
        check('R: BS before anything typed leaves it unmodified (:q exits)',
              at_ccp(e, ':q\r'))
    finally:
        e.close()
    e = Editor(files['bl'])
    try:
        e.key('G'); send_keys(e, 'RQ\rW\x08\x08\x08'); send_keys(e, '\x1b')
        e.key(':w\r')                     # 'xy' -> 'Q' + 'y', the W put back
        check('R: BS puts the char back but does not rejoin a line break typed in R',
              saved_bytes(e) == b'ab\r\n    \r\n\tcd\r\n\r\nQ\r\ny')
    finally:
        e.close()
    # --- r on an empty file / an empty line: nothing happens ---
    for f, keys, tag in [('mt', ['rZ'], 'an empty file'), ('bl', ['3j', 'rZ'], 'an empty line')]:
        e = Editor(files[f])
        try:
            for k in keys:
                e.key(k)
            check(f'r on {tag}: nothing is modified', '[Modified]' not in ctrlg(e))
            check(f'r on {tag}: :q exits', at_ccp(e, ':q\r'))
        finally:
            e.close()
    # --- the paged proofs: a long R run, then BS back over all of it ---
    for f, at, n in [('wide', '700G', 199), ('num', '10000G', 3000)]:
        e = Editor(files[f])
        try:
            e.key(at)
            send_keys(e, 'R' + 'Q' * n)
            send_keys(e, '\x08' * n)
            send_keys(e, '\x1b')
            e.key(':w\r')
            check(f'R {f}: {n} chars typed and {n} BS restore the file byte-exact',
                  saved_bytes(e) == files[f])
        finally:
            e.close()
    # --- a long R run that is not undone: :w byte-exact ---
    e = Editor(files['wide'])
    try:
        e.key('700G')
        send_keys(e, 'R' + 'Q' * 250)          # 199 overwrites, then 51 appended
        send_keys(e, '\x1b')
        e.key(':w\r')
        lines = files['wide'].split(b'\r\n')
        lines[699] = b'Q' * 250
        check('R wide: 250 chars over a 200-column line :w byte-exact',
              saved_bytes(e) == b'\r\n'.join(lines))
    finally:
        e.close()


def ops_files():
    """What J needs beyond hml_files() / ins_files(): a next line whose first
    non-blank is ')' (vim joins that one without a space) and a line that ends
    in blanks (vim adds no space after it either)."""
    return {'jp': b'foo\r\n  )bar\r\nbaz  \r\n  qux\r\nlast\r\n'}


# (file, keys, sha1 of the file vim wrote, [(cursor row, cursor column, cursor
# line, top line) after each key]) from vim 9.1 (-u NONE -N, 24 lines,
# 'nowrap'), regenerable with `python3 vimref.py --print ops`.  Same shape and
# same final-line-end fold as VIM_INS above.  No case carries a count on o O J ~ dw cw D
# -- see ops_cmds() for those (they are ignored).
VIM_OPS = [
    # ---- o / O: open a line below / above, then insert ----
    ('3', ['0', 'oX\x1b', 'j', 'OY\x1b', 'G', 'oZ\x1b'], 'd4377e382f803ed9',
     [(0, 0, '  aaa', '  aaa'),
      (1, 0, 'X', '  aaa'),
      (2, 0, '', '  aaa'),
      (2, 0, 'Y', '  aaa'),
      (4, 0, 'bbb', '  aaa'),
      (5, 0, 'Z', '  aaa')]),
    ('bl', ['j', 'oX\x1b'], 'bc4105de0a09c6ab',
     [(1, 0, '    ', 'ab'),
      (2, 0, 'X', 'ab')]),
    ('bl', ['3j', 'OY\x1b'], 'b857f5c90dcb6d6a',
     [(3, 0, '', 'ab'),
      (3, 0, 'Y', 'ab')]),
    ('nl', ['G', 'oX\x1b'], 'a17e4a7ea4b7c57f',
     [(3, 2, '  cc', '  aa'),
      (4, 0, 'X', '  aa')]),
    ('1', ['OX\x1b'], '35208f15f225d4e2',
     [(0, 0, 'X', 'X')]),
    ('mt', ['oX\x1b'], '0eb1dcb4d99102bd',
     [(1, 0, 'X', '')]),
    ('mt', ['OX\x1b'], '0f7e2419b55ac43f',
     [(0, 0, 'X', 'X')]),
    ('num', ['10000G', 'oX\x1b'], 'c1efbdb1928689e7',
     [(11, 0, '010000', '009989'),
      (12, 0, 'X', '009989')]),
    ('wide', ['702G', '$', 'oQ\x1b'], '6481319929564c5f',
     [(11, 0, '000702' + 'x'*194, '000691'),
      (11, 199, '000702' + 'x'*194, '000691'),
      (12, 0, 'Q', '000691')]),
    ('ind', ['3000G', 'OX\x1b'], 'b113b0eedc77c046',
     [(11, 10, '\t  003000', '    002989'),
      (11, 0, 'X', '    002989')]),
    # ---- J: join the next line up ----
    ('3', ['0', 'J', 'J'], 'b984f1eeb643aeb7',
     [(0, 0, '  aaa', '  aaa'),
      (0, 4, '  aaa', '  aaa'),
      (0, 5, '  aaa bbb', '  aaa bbb')]),
    ('bl', ['0', 'J', 'J'], 'b37565056760d6d6',
     [(0, 0, 'ab', 'ab'),
      (0, 1, 'ab', 'ab'),
      (0, 2, 'ab cd', 'ab cd')]),
    ('bl', ['3j', 'J'], '6631e86bbb2b5c28',
     [(3, 0, '', 'ab'),
      (3, 0, 'xy', 'ab')]),
    ('nl', ['G', 'J'], 'e7f99afe3ca4c163',
     [(3, 2, '  cc', '  aa'),
      (3, 2, '  cc', '  aa')]),
    ('2', ['0', 'J'], 'e19715c63af02580',
     [(0, 0, 'ab', 'ab'),
      (0, 2, 'ab cd', 'ab cd')]),
    ('num', ['10000G', 'J'], '2756bfa20f903e29',
     [(11, 0, '010000', '009989'),
      (11, 6, '010000 010001', '009989')]),
    ('wide', ['702G', 'J'], '568ca7983aace255',
     [(11, 0, '000702' + 'x'*194, '000691'),
      (11, 200, '000702' + 'x'*194 + ' 000703', '000691')]),
    ('ind', ['3000G', 'J'], '58e2eef2f18a88f1',
     [(11, 10, '\t  003000', '    002989'),
      (11, 16, '\t  003000 003001', '    002989')]),
    ('wd', ['1500G', 'J', 'J'], '4e45768e95d4e83d',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 23, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 24, '01500 foo.bar(baz) qux_1 01502  x,y;;z  ', '  01489 a b  c')]),
    ('jp', ['0', 'J', 'J', 'J', 'J'], '804f70b417f6f220',
     [(0, 0, 'foo', 'foo'),
      (0, 3, 'foo)bar', 'foo)bar'),
      (0, 7, 'foo)bar baz  ', 'foo)bar baz  '),
      (0, 13, 'foo)bar baz  qux', 'foo)bar baz  qux'),
      (0, 16, 'foo)bar baz  qux last', 'foo)bar baz  qux last')]),
    ('jp', ['j$', 'J'], 'fb3651fa59b5af9c',
     [(1, 5, '  )bar', 'foo'),
      (1, 6, '  )bar baz  ', 'foo')]),
    # ---- ~: toggle the case of the char under the cursor, then step right ----
    ('3', ['0', '~', '~', '~', '~', '~'], 'e26fbdca3ec68ce5',
     [(0, 0, '  aaa', '  aaa'),
      (0, 1, '  aaa', '  aaa'),
      (0, 2, '  aaa', '  aaa'),
      (0, 3, '  Aaa', '  Aaa'),
      (0, 4, '  AAa', '  AAa'),
      (0, 4, '  AAA', '  AAA')]),
    ('bl', ['0', '~', '~', '~'], '60cda2d65665e701',
     [(0, 0, 'ab', 'ab'),
      (0, 1, 'Ab', 'Ab'),
      (0, 1, 'AB', 'AB'),
      (0, 1, 'Ab', 'Ab')]),
    ('bl', ['3j', '~'], '421b1eeda3ed597c',
     [(3, 0, '', 'ab'),
      (3, 0, '', 'ab')]),
    ('nl', ['G$', '~'], 'f17d3e0fc39cd65c',
     [(3, 3, '  cc', '  aa'),
      (3, 3, '  cC', '  aa')]),
    ('num', ['10000G', '~', '~'], '22c710eca7f26684',
     [(11, 0, '010000', '009989'),
      (11, 1, '010000', '009989'),
      (11, 2, '010000', '009989')]),
    ('wide', ['702G', '$', '~'], 'd7da3a82d6c8f712',
     [(11, 0, '000702' + 'x'*194, '000691'),
      (11, 199, '000702' + 'x'*194, '000691'),
      (11, 199, '000702' + 'x'*193 + 'X', '000691')]),
    ('wd', ['1500G', '~', '~', '~'], '5c9f0580f938e2cb',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 1, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 2, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 3, '01500 foo.bar(baz) qux_1', '  01489 a b  c')]),
    # ---- dw ----
    ('wd', ['1500G', 'dw', 'dw', 'dw'], 'c5d2a717a290dc3c',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 0, 'foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 0, '.bar(baz) qux_1', '  01489 a b  c'),
      (11, 0, 'bar(baz) qux_1', '  01489 a b  c')]),
    ('3', ['0', 'dw'], 'e1d71cbd6f06ce2a',
     [(0, 0, '  aaa', '  aaa'),
      (0, 0, 'aaa', 'aaa')]),
    ('3', ['$', 'dw'], '1742108dab41ed77',
     [(0, 4, '  aaa', '  aaa'),
      (0, 3, '  aa', '  aa')]),
    ('bl', ['j', 'dw'], '13e7957da40de001',
     [(1, 0, '    ', 'ab'),
      (1, 0, '', 'ab')]),
    ('bl', ['3j', 'dw'], '6631e86bbb2b5c28',
     [(3, 0, '', 'ab'),
      (3, 0, 'xy', 'ab')]),
    ('2', ['0', 'dw'], '970946eec846f24e',
     [(0, 0, 'ab', 'ab'),
      (0, 0, '', '')]),
    ('num', ['10000G', 'dw'], '4c968a6f4f2235cc',
     [(11, 0, '010000', '009989'),
      (11, 0, '', '009989')]),
    ('num', ['10000G', 'l', 'dw'], 'a6b990b345ba697a',
     [(11, 0, '010000', '009989'),
      (11, 1, '010000', '009989'),
      (11, 0, '0', '009989')]),
    ('wide', ['702G', 'dw'], '6a7a6f42971904e7',
     [(11, 0, '000702' + 'x'*194, '000691'),
      (11, 0, '', '000691')]),
    ('ind', ['3000G', 'dw'], 'bb0b522d3e0d95ef',
     [(11, 10, '\t  003000', '    002989'),
      (11, 9, '\t  ', '    002989')]),
    ('nl', ['G', 'dw'], 'e675420fb041e82b',
     [(3, 2, '  cc', '  aa'),
      (3, 1, '  ', '  aa')]),
    # ---- cw (vi's one special case: it changes to the word's end, like ce) ----
    ('wd', ['1500G', 'cwQQ\x1b'], '47b04577d05834c0',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 1, 'QQ foo.bar(baz) qux_1', '  01489 a b  c')]),
    ('wd', ['1500G', 'w', 'cwZ\x1b'], '122462b1f502c37b',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 6, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 6, '01500 Z.bar(baz) qux_1', '  01489 a b  c')]),
    ('3', ['0', 'cwX\x1b'], '31ee262b584c8de9',
     [(0, 0, '  aaa', '  aaa'),
      (0, 0, 'Xaaa', 'Xaaa')]),
    ('bl', ['0', 'cwQ\x1b'], 'ea20548cb925075d',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'Q', 'Q')]),
    ('bl', ['j', 'cwQ\x1b'], '2a25fac102bec869',
     [(1, 0, '    ', 'ab'),
      (1, 0, 'Q', 'ab')]),
    ('num', ['10000G', 'cwQ\x1b'], 'fbf2eeacadc43b0f',
     [(11, 0, '010000', '009989'),
      (11, 0, 'Q', '009989')]),
    ('wide', ['702G', 'cwQ\x1b'], '4f730ad114a59e99',
     [(11, 0, '000702' + 'x'*194, '000691'),
      (11, 0, 'Q', '000691')]),
    ('bl', ['3j', 'cwQ\x1b'], '51f1e8180c95c87d',
     [(3, 0, '', 'ab'),
      (3, 0, 'Q', 'ab')]),
    ('nl', ['G', 'cwQ\x1b'], '0059d76db9bc9773',
     [(3, 2, '  cc', '  aa'),
      (3, 2, '  Q', '  aa')]),
    ('ind', ['3000G', 'cwX\x1b'], '2a20569df400bde3',
     [(11, 10, '\t  003000', '    002989'),
      (11, 10, '\t  X', '    002989')]),
    # ---- D ----
    ('3', ['0l', 'D'], '72c5e5a4ef406342',
     [(0, 1, '  aaa', '  aaa'),
      (0, 0, ' ', ' ')]),
    ('3', ['$', 'D'], '1742108dab41ed77',
     [(0, 4, '  aaa', '  aaa'),
      (0, 3, '  aa', '  aa')]),
    ('bl', ['j', 'D'], '13e7957da40de001',
     [(1, 0, '    ', 'ab'),
      (1, 0, '', 'ab')]),
    ('bl', ['3j', 'D'], '421b1eeda3ed597c',
     [(3, 0, '', 'ab'),
      (3, 0, '', 'ab')]),
    ('nl', ['G', 'D'], 'e675420fb041e82b',
     [(3, 2, '  cc', '  aa'),
      (3, 1, '  ', '  aa')]),
    ('num', ['10000G', 'lD'], 'a6b990b345ba697a',
     [(11, 0, '010000', '009989'),
      (11, 0, '0', '009989')]),
    ('wide', ['702G', '100lD'], '3194053ea66ab66f',
     [(11, 0, '000702' + 'x'*194, '000691'),
      (11, 99, '000702' + 'x'*94, '000691')]),
    ('ind', ['3000G', 'D'], 'bb0b522d3e0d95ef',
     [(11, 10, '\t  003000', '    002989'),
      (11, 9, '\t  ', '    002989')]),
    ('wd', ['1500G', 'wD'], '86100573bd1e1f12',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 5, '01500 ', '  01489 a b  c')]),
    # ---- C: the same span as D, then an insert at the deletion point.  Every
    #      D case above with the change typed, plus 'C<Esc>' typing nothing --
    #      which leaves the truncated line, and hashes identical to plain 'D'. ----
    ('3', ['0l', 'CX\x1b'], 'd84039c942c4a992',
     [(0, 1, '  aaa', '  aaa'),
      (0, 1, ' X', ' X')]),
    ('3', ['$', 'CX\x1b'], 'dc828ad46c7b4b50',
     [(0, 4, '  aaa', '  aaa'),
      (0, 4, '  aaX', '  aaX')]),
    ('3', ['0', 'CX\x1b'], 'c6ab761803d3b903',
     [(0, 0, '  aaa', '  aaa'),
      (0, 0, 'X', 'X')]),
    ('3', ['0l', 'C\x1b'], '72c5e5a4ef406342',
     [(0, 1, '  aaa', '  aaa'),
      (0, 0, ' ', ' ')]),
    ('bl', ['j', 'CX\x1b'], '62f57d4172cc8333',
     [(1, 0, '    ', 'ab'),
      (1, 0, 'X', 'ab')]),
    ('bl', ['3j', 'CX\x1b'], 'df1ab032cec0948d',
     [(3, 0, '', 'ab'),
      (3, 0, 'X', 'ab')]),
    ('nl', ['G', 'CX\x1b'], '9c7e1ea38adf5041',
     [(3, 2, '  cc', '  aa'),
      (3, 2, '  X', '  aa')]),
    ('num', ['10000G', 'lCX\x1b'], '13d8bdaea5f8792b',
     [(11, 0, '010000', '009989'),
      (11, 1, '0X', '009989')]),
    ('wide', ['702G', '100lCX\x1b'], '28e1972ac24d0235',
     [(11, 0, '000702xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '000691'),
      (11, 100, '000702xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxX', '000691')]),
    ('ind', ['3000G', 'CX\x1b'], '2a20569df400bde3',
     [(11, 10, '\t  003000', '    002989'),
      (11, 10, '\t  X', '    002989')]),
    ('wd', ['1500G', 'wCX\x1b'], '1055620c9c3dec9a',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 6, '01500 X', '  01489 a b  c')]),
]

# yy / nyy / Y / p / P / np, recorded from vim (vimref.py group 'put') BEFORE
# any of it was written.  Each row is (file, keys, sha1 of the file vim wrote,
# [(screen row, screen column, the cursor's line, the top line) after each
# key]).  What the rows establish, which reasoning would not have:
#   * a linewise put leaves the cursor on the FIRST NON-BLANK of the FIRST line
#     it put, whatever the count -- '2dd' then 'p' lands on the first of the two
#   * 'yy' does not move the cursor at all
#   * a count on the put ('3p') repeats the text but the cursor still lands on
#     the first line of the first copy, so only the file differs from 'p'
#   * 'nyy' and 'ndd' CLAMP a count that runs past the last line ('5yy' on a
#     two-line file yanks the two), they do not refuse it
#   * 'p' with nothing yanked yet leaves the file byte-identical
#   * 'Y' is 'yy'
VIM_PUT = [
    ('3', ['yy', 'p'], '3a02a9f2e5058157',
     [(0, 0, '  aaa', '  aaa'),
      (1, 2, '  aaa', '  aaa')]),
    ('3', ['yy', 'P'], '3a02a9f2e5058157',
     [(0, 0, '  aaa', '  aaa'),
      (0, 2, '  aaa', '  aaa')]),
    ('3', ['j', 'yy', 'p'], '67929f20f9e567f0',
     [(1, 0, '', '  aaa'),
      (1, 0, '', '  aaa'),
      (2, 0, '', '  aaa')]),
    ('3', ['2yy', 'p'], 'c3c9de8939727825',
     [(0, 0, '  aaa', '  aaa'),
      (1, 2, '  aaa', '  aaa')]),
    ('3', ['2yy', 'P'], '36c8945a792277e4',
     [(0, 0, '  aaa', '  aaa'),
      (0, 2, '  aaa', '  aaa')]),
    ('3', ['yy', '3p'], 'c8bd9928208ab17c',
     [(0, 0, '  aaa', '  aaa'),
      (1, 2, '  aaa', '  aaa')]),
    ('3', ['Y', 'p'], '3a02a9f2e5058157',
     [(0, 0, '  aaa', '  aaa'),
      (1, 2, '  aaa', '  aaa')]),
    ('3', ['dd', 'p'], '041ce96efd432fe7',
     [(0, 0, '', ''),
      (1, 2, '  aaa', '')]),
    ('3', ['dd', 'P'], 'b3c36571c67a58cf',
     [(0, 0, '', ''),
      (0, 2, '  aaa', '  aaa')]),
    ('3', ['2dd', 'p'], '1a2d09a258486f5d',
     [(0, 0, 'bbb', 'bbb'),
      (1, 2, '  aaa', 'bbb')]),
    ('3', ['j', 'dd', 'p'], 'db5d519ff1e0faac',
     [(1, 0, '', '  aaa'),
      (1, 0, 'bbb', '  aaa'),
      (2, 0, '', '  aaa')]),
    ('1', ['yy', 'p'], '7ddbc01b8adde191',
     [(0, 0, '   one', '   one'),
      (1, 3, '   one', '   one')]),
    ('1', ['dd', 'p'], '58d6f7ba001a0bb2',
     [(0, 0, '', ''),
      (1, 3, '   one', '')]),
    ('3', ['G', 'yy', 'p'], 'fee239b7379a3fe5',
     [(2, 0, 'bbb', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (3, 0, 'bbb', '  aaa')]),
    ('3', ['G', 'dd', 'p'], 'b3c36571c67a58cf',
     [(2, 0, 'bbb', '  aaa'),
      (1, 0, '', '  aaa'),
      (2, 0, 'bbb', '  aaa')]),
    ('3', ['G', 'yy', 'P'], 'fee239b7379a3fe5',
     [(2, 0, 'bbb', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (2, 0, 'bbb', '  aaa')]),
    ('0', ['yy', 'p'], 'ba8ab5a0280b953a',
     [(0, 0, '', ''),
      (1, 0, '', '')]),
    ('3', ['p'], 'b3c36571c67a58cf',
     [(0, 0, '  aaa', '  aaa')]),
    ('nl', ['G', 'yy', 'p'], '332e18923ea4e6c9',
     [(3, 2, '  cc', '  aa'),
      (3, 2, '  cc', '  aa'),
      (4, 2, '  cc', '  aa')]),
    ('nl', ['G', 'dd', 'p'], 'e7f99afe3ca4c163',
     [(3, 2, '  cc', '  aa'),
      (2, 0, 'bb', '  aa'),
      (3, 2, '  cc', '  aa')]),
    ('wide', ['yy', 'p'], '6fcb4d249e3827d5',
     [(0, 0, '000001', '000001'),
      (1, 0, '000001', '000001')]),
    ('wide', ['j', 'yy', 'p'], '52a578944549b1f0',
     [(1, 0, '000002', '000001'),
      (1, 0, '000002', '000001'),
      (2, 0, '000002', '000001')]),
    ('wide', ['2yy', 'G', 'p'], '2c0652a41d902bc7',
     [(0, 0, '000001', '000001'),
      (22, 0, '001500xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '001478'),
      (22, 0, '000001', '001479xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('wide', ['dd', 'G', 'p'], '8401b3e0a7c773ca',
     [(0, 0, '000002', '000002'),
      (22, 0, '001500xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '001478'),
      (22, 0, '000001', '001479xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('ind', ['yy', 'p'], '6cd8eb7b005003bd',
     [(0, 0, '    000001', '    000001'),
      (1, 4, '    000001', '    000001')]),
    ('ind', ['3j', 'yy', 'P'], '2e8512694625e75e',
     [(3, 7, '\t  000004', '    000001'),
      (3, 7, '\t  000004', '    000001'),
      (3, 10, '\t  000004', '    000001')]),
    ('ind', ['2dd', 'G', 'p'], '44f87c1430f90062',
     [(0, 4, '    000003', '    000003'),
      (22, 10, '\t  006000', '\t  005978'),
      (22, 4, '    000001', '    005979')]),
    ('bl', ['yy', 'p'], '3fa62e1ca47e0b43',
     [(0, 0, 'ab', 'ab'),
      (1, 0, 'ab', 'ab')]),
    ('bl', ['3yy', 'G', 'p'], '500fadb4c695ae30',
     [(0, 0, 'ab', 'ab'),
      (4, 0, 'xy', 'ab'),
      (5, 0, 'ab', 'ab')]),
    ('mt', ['yy', 'p'], 'ba8ab5a0280b953a',
     [(0, 0, '', ''),
      (1, 0, '', '')]),
    ('2', ['5yy', 'p'], '2c6ff630f1f657f2',
     [(0, 0, 'ab', 'ab'),
      (1, 0, 'ab', 'ab')]),
    ('2', ['5dd', 'p'], '8834cb10f08baed4',
     [(0, 0, '', ''),
      (1, 0, 'ab', '')]),
    ('40', ['20yy', 'G', 'p'], '8ea65999aaa98533',
     [(0, 0, '000001', '000001'),
      (22, 0, '000040', '000018'),
      (22, 0, '000001', '000019')]),
    ('40', ['20dd', 'G', 'p'], 'e2dd4132c40cadd1',
     [(0, 0, '000021', '000021'),
      (19, 0, '000040', '000021'),
      (20, 0, '000001', '000021')]),
    # A count of more than one on the LAST line is refused, by 'dd' and by 'yy'
    # alike, and the register is left holding whatever the previous yank put
    # there.  'yy' took its lines OUT and put them back, so a refusal that still
    # put the register back spliced that earlier yank's line into the file --
    # silent corruption, and what YKGO's "nothing came out" guard is for.
    ('3', ['yy', 'G', '2yy', 'p'], '107c877c5bc9bb15',
     [(0, 0, '  aaa', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (3, 2, '  aaa', '  aaa')]),
    ('3', ['G', '2yy', 'p'], 'b3c36571c67a58cf',
     [(2, 0, 'bbb', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (2, 0, 'bbb', '  aaa')]),
    ('3', ['yy', 'G', '2dd', 'p'], '107c877c5bc9bb15',
     [(0, 0, '  aaa', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (3, 2, '  aaa', '  aaa')]),
]



def ops_like_vim():
    """o O J ~ dw cw D put the text, the cursor and the window where vim does,
    on the same files the inserts use (blank-only lines, TABs, an empty line, no
    final line end, an empty file, a ')' line start, a line ending in blanks), a
    66 K indented file, a 109 K file of 200-column lines, 100 K of words and
    100 K -- and write the file vim wrote."""
    import hashlib
    files = dict(hml_files(), **ins_files())
    files.update(ops_files())
    for f, keys, sha, want in VIM_OPS:
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                if k.endswith('\x1b'):
                    send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim ops {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim ops {f} {keys!r}: file as vim wrote it ({got})', got == sha)
        finally:
            e.close()


# ---------------------------------------------------------------------------
# VIM_DOT -- '.' against vim 9.1, recorded by vimref.py ('dot') BEFORE the
# repeat was written.  Same shape and same final-line-end fold as VIM_OPS above.
#
# What '.' has to get right, and what each case is here to pin down:
#   * it repeats the last CHANGE, not the last key -- a motion in between does
#     not become the thing repeated, it only says WHERE the repeat lands;
#   * the repeat carries the original count ('3x' then '.' deletes three), and
#     a count typed on the '.' REPLACES it ('3x' then '2.' deletes two);
#   * an insert is repeated with its text ('iXY<Esc>' then '.' types XY again),
#     which is why the recording has to run through the ESC that ends it;
#   * with nothing changed yet '.' does nothing at all.
# No count is used on i a A I r R o O J ~ : counts are a known gap on those
# (see COMMANDS.md), so a counted '.' on one of them would be testing the gap.
VIM_DOT = [
    # ---- nothing changed yet: vim beeps and the file is untouched ----
    ('3', ['0', '.'], 'b3c36571c67a58cf',
     [(0, 0, '  aaa', '  aaa'),
      (0, 0, '  aaa', '  aaa')]),
    # ---- x, with and without a count, and after a motion ----
    ('2', ['0', 'x', '.', '.'], '970946eec846f24e',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'b', 'b'),
      (0, 0, '', ''),
      (0, 0, '', '')]),
    ('num', ['5G', '3x', '.'], '672038a4b0962f2f',
     [(4, 0, '000005', '000001'),
      (4, 0, '005', '000001'),
      (4, 0, '', '000001')]),
    ('num', ['5G', '3x', '2.'], 'e7e0fd0462baee38',
     [(4, 0, '000005', '000001'),
      (4, 0, '005', '000001'),
      (4, 0, '5', '000001')]),
    ('num', ['5G', 'x', 'j', '.'], '7ce53949565ca91f',
     [(4, 0, '000005', '000001'),
      (4, 0, '00005', '000001'),
      (5, 0, '000006', '000001'),
      (5, 0, '00006', '000001')]),
    ('wide', ['700G', '$', 'x', '.'], '5d4221b56fe2df34',
     [(11, 0, '000700', '000689'),
      (11, 5, '000700', '000689'),
      (11, 4, '00070', '000689'),
      (11, 3, '0007', '000689')]),
    ('num', ['6000G', 'x', '.'], '212b3dfe638956da',
     [(11, 0, '006000', '005989'),
      (11, 0, '06000', '005989'),
      (11, 0, '6000', '005989')]),
    # ---- dd / Ndd, including a new count on the '.' ----
    ('num', ['100G', 'dd', '.', '.'], '8a699160ad7c8166',
     [(11, 0, '000100', '000089'),
      (11, 0, '000101', '000089'),
      (11, 0, '000102', '000089'),
      (11, 0, '000103', '000089')]),
    ('num', ['100G', '2dd', '.'], '79005cdfe472176c',
     [(11, 0, '000100', '000089'),
      (11, 0, '000102', '000089'),
      (11, 0, '000104', '000089')]),
    ('num', ['100G', '2dd', '3.'], 'ba40c6e7920b9ad8',
     [(11, 0, '000100', '000089'),
      (11, 0, '000102', '000089'),
      (11, 0, '000105', '000089')]),
    ('3', ['G', 'dd', '.'], '111feb192d28ca01',
     [(2, 0, 'bbb', '  aaa'),
      (1, 0, '', '  aaa'),
      (0, 2, '  aaa', '  aaa')]),
    ('num', ['6000G', 'dd', '.', '.'], '1eb4eb959e0e3bca',
     [(11, 0, '006000', '005989'),
      (11, 0, '006001', '005989'),
      (11, 0, '006002', '005989'),
      (11, 0, '006003', '005989')]),
    ('wide', ['700G', 'dd', '.'], '0ce8285ebff2b0b9',
     [(11, 0, '000700', '000689'),
      (11, 0, '000701', '000689'),
      (11, 0, '000702xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '000689')]),
    # ---- dw / D / cw ----
    ('wd', ['0', 'dw', '.', '.'], 'aa1aecdacbcf40c0',
     [(0, 0, '', ''),
      (0, 10, '\t  00002  x,y;;z  ', '\t  00002  x,y;;z  '),
      (0, 10, '\t  x,y;;z  ', '\t  x,y;;z  '),
      (0, 10, '\t  ,y;;z  ', '\t  ,y;;z  ')]),
    ('wd', ['0', 'dw', 'j', '.'], '20a65f32befed862',
     [(0, 0, '', ''),
      (0, 10, '\t  00002  x,y;;z  ', '\t  00002  x,y;;z  '),
      (1, 2, '   ', '\t  00002  x,y;;z  '),
      (1, 1, '  ', '\t  00002  x,y;;z  ')]),
    ('ind', ['3000G', 'dw', '.'], '4b19987f9ddf9263',
     [(11, 10, '\t  003000', '    002989'),
      (11, 9, '\t  ', '    002989'),
      (11, 8, '\t ', '    002989')]),
    ('2', ['j', 'D', '.'], '8eb0f881d55269a4',
     [(1, 0, '  cd', 'ab'),
      (1, 0, '', 'ab'),
      (1, 0, '', 'ab')]),
    ('2', ['j', 'CX\x1b', '.'], 'e8d6db41e1ef9b12',
     [(1, 0, '  cd', 'ab'),
      (1, 0, 'X', 'ab'),
      (1, 0, 'X', 'ab')]),
    ('wd', ['1500G', 'wCZZZ\x1b', 'j', '0', '.'], '13d0090d7e1a1af0',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 8, '01500 ZZZ', '  01489 a b  c'),
      (12, 0, '', '  01489 a b  c'),
      (12, 0, '', '  01489 a b  c'),
      (12, 2, 'ZZZ', '  01489 a b  c')]),
    ('wd', ['0', 'cwZZZ\x1b', '.'], 'b25a4e9f07b48009',
     [(0, 0, '', ''),
      (0, 2, 'ZZZ', 'ZZZ'),
      (0, 4, 'ZZZZZ', 'ZZZZZ')]),
    # ---- the inserts: the repeat has to carry the typed text ----
    ('2', ['0', 'iXY\x1b', '.'], 'cd37d38129214b31',
     [(0, 0, 'ab', 'ab'),
      (0, 1, 'XYab', 'XYab'),
      (0, 2, 'XXYYab', 'XXYYab')]),
    ('2', ['0', 'A!\x1b', 'j', '.'], 'ef895c3ce4eadfa2',
     [(0, 0, 'ab', 'ab'),
      (0, 2, 'ab!', 'ab!'),
      (1, 2, '  cd', 'ab!'),
      (1, 4, '  cd!', 'ab!')]),
    ('3', ['0', 'oQ\x1b', '.'], '387113885d26200a',
     [(0, 0, '  aaa', '  aaa'),
      (1, 0, 'Q', '  aaa'),
      (2, 0, 'Q', '  aaa')]),
    ('3', ['G', 'OP\x1b', '.'], 'dc153a9283d48cdc',
     [(2, 0, 'bbb', '  aaa'),
      (2, 0, 'P', '  aaa'),
      (2, 0, 'P', '  aaa')]),
    ('bl', ['0', 'IZ\x1b', 'j', '.'], '84d54a60561820b2',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'Zab', 'Zab'),
      (1, 0, '    ', 'Zab'),
      (1, 4, '    Z', 'Zab')]),
    ('wd', ['0', 'RQQ\x1b', '.'], 'cb226be1633a61ad',
     [(0, 0, '', ''),
      (0, 1, 'QQ', 'QQ'),
      (0, 2, 'QQQ', 'QQQ')]),
    # ---- r / ~ / J ----
    ('wd', ['j', 'rZ', 'l', '.'], '6854da20e5c8f274',
     [(1, 7, '\t  00002  x,y;;z  ', ''),
      (1, 0, 'Z  00002  x,y;;z  ', ''),
      (1, 1, 'Z  00002  x,y;;z  ', ''),
      (1, 1, 'ZZ 00002  x,y;;z  ', '')]),
    ('2', ['0', '~', '.', '.'], '6fe8b239eec3e7fd',
     [(0, 0, 'ab', 'ab'),
      (0, 1, 'Ab', 'Ab'),
      (0, 1, 'AB', 'AB'),
      (0, 1, 'Ab', 'Ab')]),
    ('3', ['0', 'J', '.'], 'b984f1eeb643aeb7',
     [(0, 0, '  aaa', '  aaa'),
      (0, 4, '  aaa', '  aaa'),
      (0, 5, '  aaa bbb', '  aaa bbb')]),
    # ---- p / P: the put is a change, so it repeats too ----
    ('num', ['100G', 'dd', 'G', 'p', '.'], '9bb12cb150b59b65',
     [(11, 0, '000100', '000089'),
      (11, 0, '000101', '000089'),
      (22, 0, '012800', '012778'),
      (22, 0, '000100', '012779'),
      (22, 0, '000100', '012780')]),
    ('2', ['0', 'yy', 'p', '.'], 'c605f2bbacb55add',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'ab', 'ab'),
      (1, 0, 'ab', 'ab'),
      (2, 0, 'ab', 'ab')]),

]


def dot_like_vim():
    """'.' repeats the last change where vim repeats it, carrying the original
    count unless the '.' brings its own, on the files the other edit groups use
    and deep in 100 K / 66 K indented / 109 K wide files -- and writes the file
    vim wrote."""
    import hashlib
    files = dict(hml_files(), **ins_files())
    files.update(ops_files())
    for f, keys, sha, want in VIM_DOT:
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                if k.endswith('\x1b'):
                    send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim dot {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim dot {f} {keys!r}: file as vim wrote it ({got})', got == sha)
        finally:
            e.close()


def dot_cmds():
    """'.' where vim cannot be the reference: our own recording limit, and the
    rule that only a CHANGE becomes the repeat -- a motion, a yank, a write or a
    key that is not a command must all leave the previous change in place."""
    # --- a yank between the change and the '.' must not become the repeat:
    #     'yy' takes its lines out with dd's engine and puts them back, so it
    #     runs through MARKMOD, and has to put the recorder's flag back too ---
    e = Editor(b'ab\r\ncd\r\nef\r\n')
    try:
        e.key('x')                      # the change: 'ab' -> 'b'
        e.key('j'); e.key('yy')         # a yank changes nothing
        e.key('j'); e.key('.')          # so this still repeats the x
        e.key(':w\r')
        check("dot: a 'yy' between does not become the repeat",
              saved_bytes(e) == b'b\r\ncd\r\nf\r\n')
    finally:
        e.close()
    # --- nor does a write, nor a key that is not a command at all ---
    for between, what in ((':w\r', 'a :w'), ('q', 'an unknown key')):
        e = Editor(b'ab\r\ncd\r\n')
        try:
            e.key('x'); e.key(between); e.key('j'); e.key('.')
            e.key(':w\r')
            check(f'dot: {what} between does not become the repeat',
                  saved_bytes(e) == b'b\r\nd\r\n')
        finally:
            e.close()
    # --- DEVIATION from vim: a change longer than the recording is not
    #     repeatable at all, and '.' after one rings the bell ---
    for n, fits in ((100, True), (200, False)):
        e = Editor(b'ab\r\ncd\r\n')
        try:
            send_keys(e, 'i' + 'Q' * n)
            send_keys(e, '\x1b')
            e.key('j'); e.key('0'); e.key('.')
            e.key(':w\r')
            want = (b'Q' * n + b'ab\r\n'
                    + (b'Q' * n if fits else b'') + b'cd\r\n')
            check(f'dot: an insert of {n} chars is '
                  f'{"repeatable" if fits else "past the recording limit"}',
                  saved_bytes(e) == want)
        finally:
            e.close()
    # --- '.' is only a command in command mode ---
    e = Editor(b'ab\r\n')
    try:
        send_keys(e, 'i.')
        send_keys(e, '\x1b')
        e.key(':w\r')
        check("dot: a '.' typed in insert mode is just a dot",
              saved_bytes(e) == b'.ab\r\n')
    finally:
        e.close()


# ---------------------------------------------------------------------------
# VIM_UNDO -- 'u' against vim 9.1, recorded by vimref.py ('undo') BEFORE the
# undo was written.  Same shape and same final-line-end fold as VIM_OPS above.
#
# Every row here undoes ONE change with ONE 'u', because that is the whole of
# what vim and a single-level undo agree about: a second 'u' walks vim further
# back down its undo tree where it returns us to where we started.  That
# deviation, and everything else vim cannot be the reference for, is in
# undo_cmds() below.
#
# What each case is here to pin down:
#   * the text comes back byte-exact -- the ':w' hash is the real assertion,
#     the screen rows only say the repaint agrees;
#   * the cursor lands where vim lands it, which for a restored line is its
#     first non-blank and for a restored char is that char;
#   * 'u' is not itself a change, so a following '.' still repeats the command
#     the undo took back.
VIM_UNDO = [
    # ---- nothing changed yet: vim says "Already at oldest change" ----
    ('3', ['0', 'u'], 'b3c36571c67a58cf',
     [(0, 0, '  aaa', '  aaa'),
      (0, 0, '  aaa', '  aaa')]),
    # ---- x, with a count, after moving away, and deep in a file ----
    ('2', ['0', 'x', 'u'], 'e27529c0f39f879a',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'b', 'b'),
      (0, 0, 'ab', 'ab')]),
    ('num', ['5G', '3x', 'u'], '22c710eca7f26684',
     [(4, 0, '000005', '000001'),
      (4, 0, '005', '000001'),
      (4, 0, '000005', '000001')]),
    ('num', ['5G', 'x', 'j', 'u'], '22c710eca7f26684',
     [(4, 0, '000005', '000001'),
      (4, 0, '00005', '000001'),
      (5, 0, '000006', '000001'),
      (4, 0, '000005', '000001')]),
    ('wide', ['700G', '$', 'x', 'u'], 'cf4987bfafeec1cc',
     [(11, 0, '000700', '000689'),
      (11, 5, '000700', '000689'),
      (11, 4, '00070', '000689'),
      (11, 5, '000700', '000689')]),
    ('num', ['6000G', 'x', 'u'], '22c710eca7f26684',
     [(11, 0, '006000', '005989'),
      (11, 0, '06000', '005989'),
      (11, 0, '006000', '005989')]),
    # ---- dd / Ndd ----
    ('num', ['100G', 'dd', 'u'], '22c710eca7f26684',
     [(11, 0, '000100', '000089'),
      (11, 0, '000101', '000089'),
      (11, 0, '000100', '000089')]),
    ('num', ['100G', '2dd', 'u'], '22c710eca7f26684',
     [(11, 0, '000100', '000089'),
      (11, 0, '000102', '000089'),
      (11, 0, '000100', '000089')]),
    ('3', ['G', 'dd', 'u'], 'b3c36571c67a58cf',
     [(2, 0, 'bbb', '  aaa'),
      (1, 0, '', '  aaa'),
      (2, 0, 'bbb', '  aaa')]),
    ('3', ['0', 'dd', 'j', 'u'], 'b3c36571c67a58cf',
     [(0, 0, '  aaa', '  aaa'),
      (0, 0, '', ''),
      (1, 0, 'bbb', ''),
      (0, 0, '  aaa', '  aaa')]),
    ('num', ['6000G', 'dd', 'u'], '22c710eca7f26684',
     [(11, 0, '006000', '005989'),
      (11, 0, '006001', '005989'),
      (11, 0, '006000', '005989')]),
    ('wide', ['700G', 'dd', 'u'], 'cf4987bfafeec1cc',
     [(11, 0, '000700', '000689'),
      (11, 0, '000701', '000689'),
      (11, 0, '000700', '000689')]),
    # ---- dw / D / cw ----
    ('wd', ['0', 'dw', 'u'], '5c9f0580f938e2cb',
     [(0, 0, '', ''),
      (0, 10, '\t  00002  x,y;;z  ', '\t  00002  x,y;;z  '),
      (0, 0, '', '')]),
    ('ind', ['3000G', 'dw', 'u'], '7909d212782c576e',
     [(11, 10, '\t  003000', '    002989'),
      (11, 9, '\t  ', '    002989'),
      (11, 10, '\t  003000', '    002989')]),
    ('2', ['j', 'D', 'u'], 'e27529c0f39f879a',
     [(1, 0, '  cd', 'ab'),
      (1, 0, '', 'ab'),
      (1, 0, '  cd', 'ab')]),
    ('2', ['j', 'CX\x1b', 'u'], 'e27529c0f39f879a',
     [(1, 0, '  cd', 'ab'),
      (1, 0, 'X', 'ab'),
      (1, 0, '  cd', 'ab')]),
    ('wd', ['1500G', 'wCZZZ\x1b', 'u'], '5c9f0580f938e2cb',
     [(11, 0, '01500 foo.bar(baz) qux_1', '  01489 a b  c'),
      (11, 8, '01500 ZZZ', '  01489 a b  c'),
      (11, 6, '01500 foo.bar(baz) qux_1', '  01489 a b  c')]),
    ('wd', ['0', 'cwZZZ\x1b', 'u'], '5c9f0580f938e2cb',
     [(0, 0, '', ''),
      (0, 2, 'ZZZ', 'ZZZ'),
      (0, 0, '', '')]),
    # ---- the inserts: the whole typed run goes back in one 'u' ----
    ('2', ['0', 'iXY\x1b', 'u'], 'e27529c0f39f879a',
     [(0, 0, 'ab', 'ab'),
      (0, 1, 'XYab', 'XYab'),
      (0, 0, 'ab', 'ab')]),
    ('2', ['0', 'A!\x1b', 'u'], 'e27529c0f39f879a',
     [(0, 0, 'ab', 'ab'),
      (0, 2, 'ab!', 'ab!'),
      (0, 1, 'ab', 'ab')]),
    ('3', ['0', 'oQ\x1b', 'u'], 'b3c36571c67a58cf',
     [(0, 0, '  aaa', '  aaa'),
      (1, 0, 'Q', '  aaa'),
      (0, 0, '  aaa', '  aaa')]),
    ('3', ['G', 'OP\x1b', 'u'], 'b3c36571c67a58cf',
     [(2, 0, 'bbb', '  aaa'),
      (2, 0, 'P', '  aaa'),
      (2, 0, 'bbb', '  aaa')]),
    ('bl', ['0', 'IZ\x1b', 'u'], '421b1eeda3ed597c',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'Zab', 'Zab'),
      (0, 0, 'ab', 'ab')]),
    ('wd', ['0', 'RQQ\x1b', 'u'], '5c9f0580f938e2cb',
     [(0, 0, '', ''),
      (0, 1, 'QQ', 'QQ'),
      (0, 0, '', '')]),
    ('num', ['3000G', 'iZZ\x1b', 'u'], '22c710eca7f26684',
     [(11, 0, '003000', '002989'),
      (11, 1, 'ZZ003000', '002989'),
      (11, 0, '003000', '002989')]),
    # ---- r / ~ / J ----
    ('wd', ['j', 'rZ', 'u'], '5c9f0580f938e2cb',
     [(1, 7, '\t  00002  x,y;;z  ', ''),
      (1, 0, 'Z  00002  x,y;;z  ', ''),
      (1, 7, '\t  00002  x,y;;z  ', '')]),
    ('2', ['0', '~', 'u'], 'e27529c0f39f879a',
     [(0, 0, 'ab', 'ab'),
      (0, 1, 'Ab', 'Ab'),
      (0, 0, 'ab', 'ab')]),
    ('3', ['0', 'J', 'u'], 'b3c36571c67a58cf',
     [(0, 0, '  aaa', '  aaa'),
      (0, 4, '  aaa', '  aaa'),
      (0, 0, '  aaa', '  aaa')]),
    # ---- p / P ----
    ('2', ['0', 'yy', 'p', 'u'], 'e27529c0f39f879a',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'ab', 'ab'),
      (1, 0, 'ab', 'ab'),
      (0, 0, 'ab', 'ab')]),
    ('2', ['0', 'yy', 'P', 'u'], 'e27529c0f39f879a',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'ab', 'ab'),
      (0, 0, 'ab', 'ab'),
      (0, 0, 'ab', 'ab')]),
    ('num', ['100G', 'dd', 'G', 'p', 'u'], '9853b0bc04ee59e7',
     [(11, 0, '000100', '000089'),
      (11, 0, '000101', '000089'),
      (22, 0, '012800', '012778'),
      (22, 0, '000100', '012779'),
      (21, 0, '012800', '012779')]),
    # ---- 'u' and '.' in each other's way ----
    ('2', ['0', 'x', 'u', '.'], 'ef977b6ebb0213a0',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'b', 'b'),
      (0, 0, 'ab', 'ab'),
      (0, 0, 'b', 'b')]),
    ('2', ['0', 'x', '.', 'u'], 'ef977b6ebb0213a0',
     [(0, 0, 'ab', 'ab'),
      (0, 0, 'b', 'b'),
      (0, 0, '', ''),
      (0, 0, 'b', 'b')]),
    ('3', ['0', 'x', 'G', 'x', 'u'], '09d309a78109fe7d',
     [(0, 0, '  aaa', '  aaa'),
      (0, 0, ' aaa', ' aaa'),
      (2, 0, 'bbb', ' aaa'),
      (2, 0, 'bb', ' aaa'),
      (2, 0, 'bbb', ' aaa')]),
    # ---- a command that changed nothing leaves the undo alone: 'x' on an
    #      empty line fails, so the 'u' after it has nothing to take back ----
    ('3', ['j', 'x', 'u'], 'b3c36571c67a58cf',
     [(1, 0, '', '  aaa'),
      (1, 0, '', '  aaa'),
      (1, 0, '', '  aaa')]),
    # ---- the file with no final line end: undo must put the bytes back
    #      without inventing one ----
    ('nl', ['G', 'x', 'u'], 'e7f99afe3ca4c163',
     [(3, 2, '  cc', '  aa'),
      (3, 2, '  c', '  aa'),
      (3, 2, '  cc', '  aa')]),
    ('nl', ['G', 'dd', 'u'], 'e7f99afe3ca4c163',
     [(3, 2, '  cc', '  aa'),
      (2, 0, 'bb', '  aa'),
      (3, 2, '  cc', '  aa')]),
]


# The one VIM_UNDO row whose cursor COLUMN is not held to vim, recorded here
# rather than quietly dropped.  'u' puts the cursor back where the command that
# changed the text BEGAN, which is what vim does for o O J dd dw x r ~ D cw R i
# and p -- measured over 14 probe cases, where the undo column tracks the
# PRE-COMMAND column and nothing else.  'A' is the exception: it moves the
# cursor to the line end before inserting, and vim's undo lands on that end
# (clamped into the restored line) rather than on the column 'A' was typed at.
# Honouring both would need the snapshot taken at two different moments; the
# text and the file it writes are still checked on this row.
UNDO_SKIP = {('2', ('0', 'A!\x1b', 'u')): 'col'}


def undo_like_vim():
    """'u' puts the text back byte-exact and leaves the cursor where vim leaves
    it, for one change of every kind -- delete, insert, replace, join, put --
    on the small edit files and deep in 100 K / 66 K indented / 109 K wide
    ones."""
    import hashlib
    files = dict(hml_files(), **ins_files())
    files.update(ops_files())
    for f, keys, sha, want in VIM_UNDO:
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                if k.endswith('\x1b'):
                    send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                if UNDO_SKIP.get((f, tuple(keys))) == 'col' and k == 'u':
                    wcol = v.col + hs          # see UNDO_SKIP above
                check(f'vim undo {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim undo {f} {keys!r}: file as vim wrote it ({got})', got == sha)
        finally:
            e.close()


def undo_cmds():
    """'u' where vim cannot be the reference: the single level (so 'u' undoes
    'u' where vim would walk further back), what does and does not count as the
    change to undo, the limits of the record table and the arena's spare room,
    and the pager moving the window off the change."""
    # --- DEVIATION from vim: ONE level, so the second 'u' puts it back ---
    e = Editor(b'ab\r\ncd\r\n')
    try:
        e.key('x')                      # 'ab' -> 'b'
        e.key('u')
        e.key(':w\r')
        check("undo: 'u' takes the change back", saved_bytes(e) == b'ab\r\ncd\r\n')
    finally:
        e.close()
    e = Editor(b'ab\r\ncd\r\n')
    try:
        e.key('x'); e.key('u'); e.key('u')
        e.key(':w\r')
        check("undo: a second 'u' puts it back (single level, as vi has it)",
              saved_bytes(e) == b'b\r\ncd\r\n')
    finally:
        e.close()
    e = Editor(b'ab\r\ncd\r\n')
    try:
        e.key('x')
        for _ in range(5):
            e.key('u')                  # odd number of undos: undone again
        e.key(':w\r')
        check("undo: 'u' keeps flipping between the two states",
              saved_bytes(e) == b'ab\r\ncd\r\n')
    finally:
        e.close()
    # --- nothing to undo yet: the text is untouched ---
    e = Editor(b'ab\r\ncd\r\n')
    try:
        e.key('u'); e.key('u')
        e.key(':w\r')
        check("undo: 'u' with nothing changed does nothing",
              saved_bytes(e) == b'ab\r\ncd\r\n')
    finally:
        e.close()
    # --- a command that changes nothing leaves the last change undoable ---
    for between, what in ((('j', 'yy'), 'a yank'),
                          (('q',), 'an unknown key'), (('j', 'k', '0'), 'motions')):
        e = Editor(b'ab\r\ncd\r\nef\r\n')
        try:
            e.key('0'); e.key('x')      # the change: 'ab' -> 'b'
            for k in between:
                e.key(k)
            e.key('u')
            e.key(':w\r')
            check(f'undo: {what} between does not become the change undone',
                  saved_bytes(e) == b'ab\r\ncd\r\nef\r\n')
        finally:
            e.close()
    # --- DEVIATION from vim: a ':w' CLEARS the undo.  The write rewinds the
    #     buffer through the pager (INIGAP), which rebuilds the window and with
    #     it every logical offset a record holds, so the honest thing is to
    #     forget the change rather than replay offsets into a new window ---
    e = Editor(b'ab\r\ncd\r\n')
    try:
        e.key('0'); e.key('x'); e.key(':w\r'); e.key('u')
        e.key(':w\r')
        check("undo: a ':w' clears the undo, and 'u' then does nothing",
              saved_bytes(e) == b'b\r\ncd\r\n')
    finally:
        e.close()
    # --- a whole typed insert goes back as ONE change, however long: the text
    #     is coalesced into a single record, so there is no '.'-style limit ---
    for n in (10, 200):
        e = Editor(b'ab\r\ncd\r\n')
        try:
            send_keys(e, 'i' + 'Q' * n)
            send_keys(e, '\x1b')
            e.key('u')
            e.key(':w\r')
            check(f'undo: an insert of {n} chars goes back in one u',
                  saved_bytes(e) == b'ab\r\ncd\r\n')
        finally:
            e.close()
    # --- DEVIATION from vim: a change of more PRIMITIVE steps than the record
    #     table holds is not undoable at all, and 'u' rings rather than doing
    #     half of it.  'R' is the one command that reaches this quickly: it
    #     deletes and inserts per character, so it costs two records each ---
    for n, fits in ((4, True), (40, False)):
        text = b'a' * 60 + b'\r\ncd\r\n'
        e = Editor(text)
        try:
            e.key('0')
            send_keys(e, 'R' + 'Z' * n)
            send_keys(e, '\x1b')
            e.key('u')
            e.key(':w\r')
            got = saved_bytes(e)
            if fits:
                check(f"undo: an 'R' of {n} chars is undoable", got == text)
            else:
                check(f"undo: an 'R' of {n} chars is past the record table, "
                      f"so 'u' leaves it alone",
                      got == b'Z' * n + b'a' * (60 - n) + b'\r\ncd\r\n')
        finally:
            e.close()
    # --- DEVIATION from vim: once the pager has moved the window off the
    #     change, 'u' says so instead of chasing it through the file ---
    big = make(12800)                   # 100 K: far more than the window holds
    e = Editor(big)
    try:
        e.key('x')                      # change line 1
        e.key('G')                      # ... and page all the way to the end
        e.key('u')
        # The TEXT, not just "it said something with 'undo' in it": that looser
        # check passed for 'Too large to undo' as well, so it could not tell the
        # two refusals apart -- and the message is the only way a reader learns
        # WHY the undo will not run.
        check(f"undo: past the resident window it says which refusal it is "
              f'({bottom(e)!r})',
              bottom(e) == 'Cannot undo: change has paged out')
        e.key('G')
        e.key(':w\r')
        got = saved_bytes(e)
        check('undo: ... and the text is left exactly as it was',
              got == b'00001\r\n' + big[8:])
    finally:
        e.close()


# Rows the editor is deliberately NOT held to, both recorded as deviations in
# COMMANDS.md rather than worked around here:
#   * an empty buffer -- vim's always holds one line and 'yy' yanks that phantom
#     empty line, so its 'p' adds a line; QPUTLN yanks a zero-byte span, the
#     register stays empty and 'p' rings the bell.  ('p' INTO an empty buffer was
#     made to match vim, so only the yank differs.)
#   * bl 3yy G p -- the source's last line has no line end, and whether the
#     file ends with one is a BUFFER-wide fact for vim: it writes the put's last
#     line without one even though that line came from a terminated source line,
#     while we write the bytes the register carried.  Ours is what vim itself
#     writes; only vimref.py's fold, which models this editor's write path,
#     disagrees.
PUT_SKIP = {('0', ('yy', 'p')): 'all',
            ('mt', ('yy', 'p')): 'all',
            ('bl', ('3yy', 'G', 'p')): 'sha'}


def ex_settled(e, tries=40):
    """Wait for an ex command to actually finish.

    ``run_until_quiet`` decides the guest has settled when a run slice draws
    nothing and stops idle-or-timeout -- exact for a guest waiting on the
    keyboard, but a COMPUTE-bound one draws nothing either.  A ':%s' over a
    paged file thinks for seconds (15 s for 48500 substitutions on the 109 K
    wide file) without a byte of output, so the screen is read while the ':'
    line is still up and the text still the old text.  Pump until that line has
    gone; every assertion is unchanged, the editor is just allowed to finish.
    """
    for _ in range(tries):
        if not ''.join(e.screen().screen[23]).lstrip().startswith(':'):
            return
        e.s.run_until_quiet(timeout=40)


# VIM_CTRLG -- what vim 9.1's ^G reports, recorded by vimref.py ('ctrlg')
# BEFORE any of this was written: the cursor's line, its BYTE column and its
# SCREEN column, all 1-based as ^G prints them.  vim writes one number when the
# two columns agree and 'col 1-8' when a TAB pushes them apart.
#
# The message itself is NOT vim's, and cannot be: vim's line carries the file's
# line total and a percentage of it ('line 2 of 4 --50%--'), and no line total
# is kept anywhere here -- counting one means sweeping the whole file out to
# EOF and paging it back, which costs the undo region as well as the wait.  So
# the numbers are vim's and the shape around them is ours.
VIM_CTRLG = [
    ('3', ('j', 'l', 'G', '$', 'gg'),
     ['2 1 1', '2 1 1', '3 1 1', '3 3 3', '1 3 3']),
    ('2', ('l', 'j', '$', '0'),
     ['1 2 2', '2 2 2', '2 4 4', '2 1 1']),
    ('1', ('$', '^', '0'),
     ['1 6 6', '1 4 4', '1 1 1']),
    ('nl', ('G', '$', 'k'),
     ['4 3 3', '4 4 4', '3 2 2']),
    ('bl', ('j', 'j', 'l', '$', 'G', '^'),
     ['2 1 1', '3 1 8', '3 2 9', '3 3 10', '5 1 1', '5 1 1']),
    ('mt', ('j', 'l'),
     ['1 1 1', '1 1 1']),
    ('wide', ('50l', '$', 'j', '0', '200G'),
     ['1 6 6', '1 6 6', '2 6 6', '2 1 1', '200 1 1']),
    ('ind', ('j', '^', '$', '500G', 'w'),
     ['2 1 8', '2 4 11', '2 9 16', '500 4 11', '501 5 5']),
    ('num', ('12800G', 'gg', '6400G', '$'),
     ['12800 1 1', '1 1 1', '6400 1 1', '6400 6 6']),
]


def ctrlg_like_vim():
    """^G reports the line and column vim reports, on every file the other
    groups use -- including the 66 K indented one, where a TAB makes the byte
    and screen columns differ and vim prints both."""
    files = dict(hml_files(), **ins_files())
    for f, keys, want in VIM_CTRLG:
        e = Editor(files[f])
        try:
            for k, w in zip(keys, want):
                e.key(k)
                ln, col, vcol = map(int, w.split())
                if f == 'mt':
                    exp = '"TEST.TXT" --Buffer empty--'
                else:
                    exp = '"TEST.TXT" line %d col %d' % (ln, col)
                    if vcol != col:
                        exp += '-%d' % vcol
                got = ctrlg(e)
                check('ctrlg %s %r %r: %r == %r' % (f, keys, k, got, exp), got == exp)
        finally:
            e.close()


def ctrlg_cmds():
    """The flags ^G carries, the load message, and what ':w' says -- each of
    them vim's own wording, recorded from vim 9.1."""
    e = Editor(b'one\r\ntwo\r\nthree\r\n')
    try:
        check('load: the file is named on the bottom row', bottom(e) == '"TEST.TXT"')
        e.key('j')
        check('load: the message survives a motion, as vim\'s does',
              bottom(e) == '"TEST.TXT"')
        e.key('x')
        check('load: and survives an edit', bottom(e) == '"TEST.TXT"')
        check('^G: [Modified] once the text has changed',
              ctrlg(e) == '"TEST.TXT" [Modified] line 2 col 1')
        e.key(':w\r')
        check(':w says what it wrote', bottom(e) == '"TEST.TXT" written')
        check('^G: [Modified] is gone after the write',
              ctrlg(e) == '"TEST.TXT" line 2 col 1')
        e.key('i')
        check('insert: vim\'s -- INSERT --', bottom(e) == '-- INSERT --')
        escaped(e)
        check('insert: ESC takes it away', bottom(e) == '')
        e.key('R')
        check('replace: vim\'s -- REPLACE --', bottom(e) == '-- REPLACE --')
        escaped(e)
        check('replace: ESC takes it away', bottom(e) == '')
        check('^G: :q exits (^G changed nothing)', at_ccp(e, ':q\r'))
    finally:
        e.close()

    # --- a file that is not there is [New], in the load line and in ^G -------
    e = Editor(None, fname='NEWF.TXT')
    try:
        check('ctrlg new: the load line says [New]', bottom(e) == '"NEWF.TXT" [New]')
        check('ctrlg new: ^G says [New] over an empty buffer',
              ctrlg(e) == '"NEWF.TXT" [New] --Buffer empty--')
        e.key('iab')
        escaped(e)
        check('ctrlg new: typed into, it is [Modified][New] as vim orders them',
              ctrlg(e) == '"NEWF.TXT" [Modified][New] line 1 col 2')
        e.key(':w\r')
        check('ctrlg new: written, and new no longer',
              ctrlg(e) == '"NEWF.TXT" line 1 col 2')
        check('ctrlg new: :q exits', at_ccp(e, ':q\r'))
    finally:
        e.close()

    # --- '-R' is vim's [readonly] -------------------------------------------
    e = Editor(b'one\r\ntwo\r\n', args=' -R')
    try:
        check('ctrlg -R: the load line says [readonly]',
              bottom(e) == '"TEST.TXT" [readonly]')
        check('ctrlg -R: ^G says it too',
              ctrlg(e) == '"TEST.TXT" [readonly] line 1 col 1')
        e.key('x')                      # -R does not stop the editing itself
        check('ctrlg -R: edited, the flags run together as vim writes them',
              ctrlg(e) == '"TEST.TXT" [Modified][readonly] line 1 col 1')
        check('ctrlg -R: :q! exits', at_ccp(e, ':q!\r'))
    finally:
        e.close()


def subst_files():
    """What ':s' needs beyond hml_files() and ins_files(): a file of repeats --
    three matches in one word, two spread over a line, an empty line, and an
    indented line whose last word matches."""
    return dict(hml_files(), **ins_files(),
                rep=b'a-a-a\r\nbb a a\r\n\r\n  a end a\r\n')


# ---------------------------------------------------------------------------
# VIM_SUBST -- ':s' against vim 9.1, recorded by vimref.py ('subst') BEFORE the
# substitute was written.  Same shape and same final-line-end fold as VIM_UNDO:
# (file, keys, the sha1 of the file vim wrote, [(cursor row, column, cursor
# line, top line) after each key]).
#
# Every pattern and replacement here is letters, digits and '-' only, so vim's
# regex and this editor's LITERAL match are the same thing.  The deviation is
# recorded in COMMANDS.md; a case needing '.' or '*' to tell the two apart
# would be testing a feature this editor does not have.
#
# What the rows are here to pin down:
#   - ':s' changes the FIRST match on the line, ':s...g' every match, and an
#     overlapping match is not re-scanned ('a-a-a' with /a-a/ gives 'Q-a').
#   - ':%s' walks the whole file and ':N,Ms' exactly that span.
#   - MEASURED, not assumed: the cursor lands on the FIRST NON-BLANK of the
#     LAST line changed -- not the column it was typed at ('j $ :s/a/Z/g' ends
#     at column 0) and not the line the command was typed on ('num' 200G then
#     ':100,105s' ends on line 105).  The window places that line exactly as
#     'G' does: centred, clamped at the file's end (':12800,12800s' leaves the
#     last line on row 22, top 012778).
#   - A pattern that is not there changes nothing and moves nothing -- on a
#     line, over a file, and on an empty file (which is written back empty).
#   - The text comes back byte-exact: the ':w' hash is the real assertion, and
#     it covers an empty replacement (shorter) and a longer one (the file
#     GROWS 12800 bytes on 'num' :%s/0/ZZ/).
#   - It works far past the window: 100 K numbered, 109 K wide (200-column
#     lines), 66 K indented.
#   - One substitute is ONE change, so a single 'u' takes it back -- and vim
#     leaves that undo on the FIRST line changed (line 100 for ':100,105s',
#     though the command was typed on line 1), which is NOT where this
#     editor's undo restores the cursor.  See subst_cmds().
# Left out deliberately: a backwards range (':100,99s'), where vim prompts
# "Backwards range given, OK to swap" and so cannot be scripted as a reference
# -- see subst_cmds() for what this editor does instead.
VIM_SUBST = [
    # ---- ':s' on the cursor's line ----
    ('rep', [':s/a/Z/\r'], 'c82d4e677f1a865e',
     [(0, 0, 'Z-a-a', 'Z-a-a')]),
    ('rep', [':s/a/Z/g\r'], '17ca86329d4e3418',
     [(0, 0, 'Z-Z-Z', 'Z-Z-Z')]),
    ('rep', ['j', ':s/a/Z/\r'], '1b7ab384181ee1d0',
     [(1, 0, 'bb a a', 'a-a-a'),
      (1, 0, 'bb Z a', 'a-a-a')]),
    ('rep', ['j', ':s/a/Z/g\r'], '9d41404279ded473',
     [(1, 0, 'bb a a', 'a-a-a'),
      (1, 0, 'bb Z Z', 'a-a-a')]),
    ('rep', ['3G', ':s/a/Z/\r'], '2f04c9d25e410425',  # an empty line: no match
     [(2, 0, '', 'a-a-a'),
      (2, 0, '', 'a-a-a')]),
    ('rep', ['4G', ':s/a/Z/g\r'], '98d76781c5066203',  # indented: the landing is the first non-blank
     [(3, 2, '  a end a', 'a-a-a'),
      (3, 2, '  Z end Z', 'a-a-a')]),
    ('rep', ['G', ':s/end/E/\r'], '9937dbcf3df2a8d7',
     [(3, 2, '  a end a', 'a-a-a'),
      (3, 2, '  a E a', 'a-a-a')]),
    ('rep', [':s/a//\r'], '584f7686598e7edf',  # an empty replacement deletes
     [(0, 0, '-a-a', '-a-a')]),
    ('rep', [':s/a/ZZZ/g\r'], '53e4132b871ed902',  # longer than the match
     [(0, 0, 'ZZZ-ZZZ-ZZZ', 'ZZZ-ZZZ-ZZZ')]),
    ('rep', [':s/a-a/Q/\r'], '7ba792ec2ac31266',  # the next match overlaps: not re-scanned
     [(0, 0, 'Q-a', 'Q-a')]),
    ('rep', [':s/zz/Q/\r'], '2f04c9d25e410425',  # not there: nothing changes, nothing moves
     [(0, 0, 'a-a-a', 'a-a-a')]),
    ('rep', ['j', '$', ':s/a/Z/g\r'], '9d41404279ded473',  # the cursor column is NOT kept
     [(1, 0, 'bb a a', 'a-a-a'),
      (1, 5, 'bb a a', 'a-a-a'),
      (1, 0, 'bb Z Z', 'a-a-a')]),
    # ---- ':%s' over the whole file ----
    ('rep', [':%s/a/Z/\r'], 'cd05ac6c2694357e',
     [(3, 2, '  Z end a', 'Z-a-a')]),
    ('rep', [':%s/a/Z/g\r'], '8d4b2c62858cf7ca',
     [(3, 2, '  Z end Z', 'Z-Z-Z')]),
    ('rep', [':%s/a//g\r'], 'd35514ffa29eb8b2',
     [(3, 3, '   end ', '--')]),
    ('2', [':%s/b/Q/g\r'], '5d0d533a0c257fc2',  # nothing on the last line
     [(0, 0, 'aQ', 'aQ')]),
    ('nl', [':%s/a/Z/g\r'], '59ab3682701fe1ef',  # no line end after the last
     [(0, 2, '  ZZ', '  ZZ')]),
    ('mt', [':%s/a/Z/\r'], 'da39a3ee5e6b4b0d',  # an empty file
     [(0, 0, '', '')]),
    ('3', [':%s/a/Z/g\r'], 'd2c351d35d8520d4',
     [(0, 2, '  ZZZ', '  ZZZ')]),
    # ---- ':N,Ms' ----
    ('num', [':100,105s/0/Z/\r'], '748231908766abe3',
     [(11, 0, 'Z00105', '000094')]),
    ('num', [':100,105s/00/QQ/g\r'], '8da5c28241b6ebc7',
     [(11, 0, 'QQ0105', '000094')]),
    ('num', [':1,1s/0/Z/\r'], 'f9606a8c109770af',
     [(0, 0, 'Z00001', 'Z00001')]),
    ('num', ['200G', ':100,105s/0/Z/\r'], '748231908766abe3',  # the cursor is pulled back to the range
     [(11, 0, '000200', '000189'),
      (11, 0, 'Z00105', '000094')]),
    ('num', [':12800,12800s/0/Z/\r'], '34866609463e7d8f',  # the last line
     [(22, 0, 'Z12800', '012778')]),
    # ---- a blank between the range and the command name.  ex has always taken
    #      ':2,4 s/a/Z/' as ':2,4s/a/Z/'; these rows are the same substitutes as
    #      above with the blank typed in, so the hash of each MUST come out
    #      identical to its no-blank twin -- which is the check. ----
    ('rep', [':1,4 s/a/Z/g\r'], '8d4b2c62858cf7ca',      # == ':%s/a/Z/g' above
     [(3, 2, '  Z end Z', 'Z-Z-Z')]),
    ('rep', [':% s/a/Z/g\r'], '8d4b2c62858cf7ca',
     [(3, 2, '  Z end Z', 'Z-Z-Z')]),
    ('rep', [':%  s/a/Z/g\r'], '8d4b2c62858cf7ca',       # more than one blank
     [(3, 2, '  Z end Z', 'Z-Z-Z')]),
    ('num', [':100,105 s/0/Z/\r'], '748231908766abe3',   # == ':100,105s/0/Z/'
     [(11, 0, 'Z00105', '000094')]),
    ('num', [':100,105 s/00/QQ/g\r'], '8da5c28241b6ebc7',
     [(11, 0, 'QQ0105', '000094')]),
    ('num', [':12800,12800 s/0/Z/\r'], '34866609463e7d8f',
     [(22, 0, 'Z12800', '012778')]),
    ('num', [':1,1 s/0/Z/\r'], 'f9606a8c109770af',
     [(0, 0, 'Z00001', 'Z00001')]),
    # ---- files far larger than the window ----
    ('num', [':%s/0/Z/\r'], '5b649151b930e71a',
     [(22, 0, 'Z12800', 'Z12778')]),
    ('num', [':%s/0/ZZ/\r'], 'd685e77537f05f80',  # ... and 12800 bytes bigger
     [(22, 0, 'ZZ12800', 'ZZ12778')]),
    ('wide', [':%s/xx/Q/g\r'], 'd494b66d58afe074',  # 200-column lines
     [(22, 0, '001500QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ', '001478')]),
    ('ind', [':%s/00/QQ/g\r'], '0af915954f2ca4bd',  # 66 K, indented
     [(22, 10, '\t  QQ6QQ0', '\t  QQ5978')]),
    # ---- one substitute is one change, so 'u' takes it back ----
    ('rep', [':%s/a/Z/g\r', 'u'], '2f04c9d25e410425',
     [(3, 2, '  Z end Z', 'Z-Z-Z'),
      (0, 0, 'a-a-a', 'a-a-a')]),
    ('num', [':100,105s/0/Z/\r', 'u'], '22c710eca7f26684',  # 'u' lands on the FIRST line changed, not line 1
     [(11, 0, 'Z00105', '000094'),
      (6, 0, '000100', '000094')]),
]


def subst_like_vim():
    """':s' / ':%s' / ':N,Ms' change what vim changes, write the file vim
    writes, and leave the cursor where vim leaves it -- on the small files and
    deep in the paged ones."""
    import hashlib
    files = subst_files()
    for f, keys, sha, want in VIM_SUBST:
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                e.key(k)
                if k.startswith(':'):
                    ex_settled(e)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim subst {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            ex_settled(e)
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim subst {f} {keys!r}: file as vim wrote it ({got})',
                  got == sha)
        finally:
            e.close()

def subst_cmds():
    """':s' where vim cannot be the reference: the ranges it refuses, the
    messages, the pattern it leaves behind for 'n', and the change that is too
    large for the undo region -- which is accepted, but SAYS so (COMMANDS.md)."""
    files = subst_files()
    # --- the ranges and forms this refuses, each with vim's own message ---
    e = Editor(files['num'])
    try:
        # vim ASKS to swap a backwards range; there is nowhere to ask from here
        refused(e, ':100,99s/0/Z/\r',
                'Invalid command: 100,99s/0/Z/', 'subst backwards')
        refused(e, ':0s/0/Z/\r', 'Invalid command: 0s/0/Z/', 'subst line 0')
        refused(e, ':s//Z/\r', 'No previous search pattern', 'subst empty pattern')
        refused(e, ':s\r', 'No previous search pattern', 'subst bare')
        refused(e, ':s/0/Z/x\r', 'Trailing chars: s/0/Z/x', 'subst trailing')
        # DEVIATION: ex takes a blank anywhere in a range; this takes one only
        # BEFORE the range and BETWEEN the range and the command name (both are
        # in VIM_SUBST, recorded from vim).  Inside the range, around the comma,
        # it does not -- the comma is read mid-number off DE and skipping there
        # costs more than the position is worth.  See COMMANDS.md.
        refused(e, ':100, 105s/0/Z/\r', 'Invalid command: 100, 105s/0/Z/',
                'subst blank after the comma')
        # a range walked through a paged file and found nothing: nothing moves
        e.key('200G')
        refused(e, ':100,105s/zz/Q/\r', 'Pattern not found: zz', 'subst ranged miss')
    finally:
        e.close()
    # --- a miss on the cursor's line leaves the COLUMN alone too ---
    e = Editor(files['rep'])
    try:
        e.key('j'); e.key('$')
        refused(e, ':s/zz/Q/\r', 'Pattern not found: zz', 'subst line miss')
    finally:
        e.close()
    # --- ':s' leaves its pattern behind, so 'n' repeats it (as vim's does) ---
    e = Editor(files['rep'])
    try:
        e.key('G')                     # ':s' is the CURSOR's line: go to it
        e.key(':s/end/X/\r')
        check("subst on the last line: ':s/end/X/' rewrote it",
              rows(e)[3] == '  a X a')
        e.key('gg'); e.key('/a\r'); e.key('n')
        v = e.screen()
        check(f"subst then '/a' n still searches ({v.row},{v.col})",
              rows(e)[v.row][v.col:v.col + 1] == 'a')
    finally:
        e.close()
    # --- the undo region: ~12 lines fit (2 records each of 24), more do not ---
    e = Editor(files['num'])
    try:
        e.key(':1,5s/0/Z/\r')
        check('subst 5 lines: line 1 changed', rows(e)[0] == 'Z00001')
        check('subst 5 lines: the cursor is on the last changed line',
              (e.screen().row, rows(e)[e.screen().row]) == (4, 'Z00005'))
        e.key('u')
        check("subst 5 lines: 'u' takes the whole substitute back",
              rows(e)[0] == '000001' and rows(e)[4] == '000005')
        check("subst 5 lines: 'u' said nothing", bottom(e) == '')
    finally:
        e.close()
    e = Editor(files['num'])
    try:
        e.key(':1,20s/0/Z/\r')
        check('subst 20 lines: it happened anyway', rows(e)[0] == 'Z00001')
        # DEVIATION, deliberate: it does not say so HERE.  EXMSG writes the
        # bottom row immediately and the full repaint a substitute needs blanks
        # it again, so the warning rides on 'u' instead -- the
        # moment the reader asks for the undo.  See COMMANDS.md.
        e.key('u')
        check(f"subst 20 lines: 'u' says why, it does not just ring "
              f'({bottom(e)!r})', bottom(e) == 'Too large to undo')
        check("subst 20 lines: 'u' changed nothing", rows(e)[0] == 'Z00001')
    finally:
        e.close()



# ---------------------------------------------------------------------------
# VIM_SRCH -- / ? n N against vim 9.1, recorded by vimref.py ('srch') before the
# search was written.  (file, keys, sha of the file vim wrote, [(row, col, cursor
# line, top line) after each key]).  The hash is of the file vim READ: a search
# must not change the buffer, and a row that hashes differently is one that did.
#
# What the rows establish:
#   - '/' starts one character past the cursor and lands ON the match's first
#     character; '?' finds the last match ending before it ('jp' /foo and /o).
#   - 'wrapscan': /a n n n cycles back to the first match, and 'n' on a file's
#     only match ('1' /one n, 'num' /012800 n) finds it again.
#   - 'n' keeps the last search's direction and 'N' reverses it -- including
#     after a '?', where 'n' goes backward and 'N' forward.
#   - '/' <CR> repeats the last pattern; '?' <CR> repeats it backward.
#   - Not found leaves the cursor exactly where it was, with or without a
#     previous pattern, and on an empty file.
#   - A count repeats the search ('2/a', '2n', '15n' = fifteen n's).
#   - The matched COLUMN is kept, and a match past the right screen edge pans
#     ('wd' /ab-cd then fifteen n's walks to column 101).
#   - A match far away centres the window, clamped at the file's ends, exactly
#     as 'G' and '+{n}' place it ('num' /001000, /012800, G /000001).
VIM_SRCH = [
    ('jp', ['/bar\r'], 'aca15c64e4cd0e26',
     [(1, 3, '  )bar', 'foo')]),
    ('jp', ['/baz\r'], 'aca15c64e4cd0e26',
     [(2, 0, 'baz  ', 'foo')]),
    ('jp', ['/last\r'], 'aca15c64e4cd0e26',
     [(4, 0, 'last', 'foo')]),
    ('jp', ['/foo\r'], 'aca15c64e4cd0e26',
     [(0, 0, 'foo', 'foo')]),
    ('jp', ['/o\r'], 'aca15c64e4cd0e26',
     [(0, 1, 'foo', 'foo')]),
    ('3', ['/bbb\r'], 'b3c36571c67a58cf',
     [(2, 0, 'bbb', '  aaa')]),
    ('2', ['/cd\r'], 'e27529c0f39f879a',
     [(1, 2, '  cd', 'ab')]),
    ('1', ['/one\r'], 'b895c60d83545247',
     [(0, 3, '   one', '   one')]),
    ('bl', ['/cd\r'], '421b1eeda3ed597c',
     [(2, 8, '\tcd', 'ab')]),
    ('jp', ['/a\r', 'n'], 'aca15c64e4cd0e26',
     [(1, 4, '  )bar', 'foo'),
      (2, 1, 'baz  ', 'foo')]),
    ('jp', ['/a\r', 'n', 'n'], 'aca15c64e4cd0e26',
     [(1, 4, '  )bar', 'foo'),
      (2, 1, 'baz  ', 'foo'),
      (4, 1, 'last', 'foo')]),
    ('jp', ['/a\r', 'n', 'n', 'n'], 'aca15c64e4cd0e26',
     [(1, 4, '  )bar', 'foo'),
      (2, 1, 'baz  ', 'foo'),
      (4, 1, 'last', 'foo'),
      (1, 4, '  )bar', 'foo')]),
    ('jp', ['/last\r', 'n'], 'aca15c64e4cd0e26',
     [(4, 0, 'last', 'foo'),
      (4, 0, 'last', 'foo')]),
    ('1', ['/one\r', 'n'], 'b895c60d83545247',
     [(0, 3, '   one', '   one'),
      (0, 3, '   one', '   one')]),
    ('jp', ['/a\r', '2n'], 'aca15c64e4cd0e26',
     [(1, 4, '  )bar', 'foo'),
      (4, 1, 'last', 'foo')]),
    ('jp', ['2/a\r'], 'aca15c64e4cd0e26',
     [(2, 1, 'baz  ', 'foo')]),
    ('jp', ['/a\r', 'N'], 'aca15c64e4cd0e26',
     [(1, 4, '  )bar', 'foo'),
      (4, 1, 'last', 'foo')]),
    ('jp', ['/a\r', 'n', 'N'], 'aca15c64e4cd0e26',
     [(1, 4, '  )bar', 'foo'),
      (2, 1, 'baz  ', 'foo'),
      (1, 4, '  )bar', 'foo')]),
    ('jp', ['G', '/a\r', 'N', 'N'], 'aca15c64e4cd0e26',
     [(4, 0, 'last', 'foo'),
      (4, 1, 'last', 'foo'),
      (2, 1, 'baz  ', 'foo'),
      (1, 4, '  )bar', 'foo')]),
    ('jp', ['G', '?bar\r'], 'aca15c64e4cd0e26',
     [(4, 0, 'last', 'foo'),
      (1, 3, '  )bar', 'foo')]),
    ('jp', ['G', '?a\r', 'n'], 'aca15c64e4cd0e26',
     [(4, 0, 'last', 'foo'),
      (2, 1, 'baz  ', 'foo'),
      (1, 4, '  )bar', 'foo')]),
    ('jp', ['G', '?a\r', 'N'], 'aca15c64e4cd0e26',
     [(4, 0, 'last', 'foo'),
      (2, 1, 'baz  ', 'foo'),
      (4, 1, 'last', 'foo')]),
    ('jp', ['?qux\r'], 'aca15c64e4cd0e26',
     [(3, 2, '  qux', 'foo')]),
    ('jp', ['?foo\r'], 'aca15c64e4cd0e26',
     [(0, 0, 'foo', 'foo')]),
    ('3', ['G', '?aaa\r'], 'b3c36571c67a58cf',
     [(2, 0, 'bbb', '  aaa'),
      (0, 2, '  aaa', '  aaa')]),
    ('jp', ['/a\r', '/\r'], 'aca15c64e4cd0e26',
     [(1, 4, '  )bar', 'foo'),
      (2, 1, 'baz  ', 'foo')]),
    ('jp', ['/a\r', '?\r'], 'aca15c64e4cd0e26',
     [(1, 4, '  )bar', 'foo'),
      (4, 1, 'last', 'foo')]),
    ('jp', ['/zzz\r'], 'aca15c64e4cd0e26',
     [(0, 0, 'foo', 'foo')]),
    ('jp', ['/bar\r', '/zzz\r'], 'aca15c64e4cd0e26',
     [(1, 3, '  )bar', 'foo'),
      (1, 3, '  )bar', 'foo')]),
    ('jp', ['/zzz\r', 'n'], 'aca15c64e4cd0e26',
     [(0, 0, 'foo', 'foo'),
      (0, 0, 'foo', 'foo')]),
    ('jp', ['n'], 'aca15c64e4cd0e26',
     [(0, 0, 'foo', 'foo')]),
    ('jp', ['N'], 'aca15c64e4cd0e26',
     [(0, 0, 'foo', 'foo')]),
    ('mt', ['/a\r'], 'da39a3ee5e6b4b0d',
     [(0, 0, '', '')]),
    ('0', ['/a\r', 'n'], 'da39a3ee5e6b4b0d',
     [(0, 0, '', ''),
      (0, 0, '', '')]),
    ('wd', ['/ab-cd\r'], '5c9f0580f938e2cb',
     [(3, 11, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '')]),
    ('wd', ['/ab-cd\r', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n'], '5c9f0580f938e2cb',
     [(3, 11, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 17, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 23, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 29, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 35, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 41, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 47, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 53, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 59, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 65, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 71, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 77, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 83, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 89, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 95, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 101, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '')]),
    ('wd', ['/ab-cd\r', '15n'], '5c9f0580f938e2cb',
     [(3, 11, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 101, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '')]),
    ('wd', ['/ab-cd\r', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'n', 'N', 'N'], '5c9f0580f938e2cb',
     [(3, 11, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 17, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 23, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 29, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 35, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 41, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 47, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 53, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 59, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 65, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 71, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 77, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 83, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 89, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 95, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 101, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 95, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (3, 89, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '')]),
    ('wd', ['/x,y\r', 'n', 'n'], '5c9f0580f938e2cb',
     [(1, 17, '\t  00002  x,y;;z  ', ''),
      (11, 17, '\t  00012  x,y;;z  ', ''),
      (21, 17, '\t  00022  x,y;;z  ', '')]),
    # ('wide', /xxx ...) is deliberately NOT here: 'xxx' can overlap itself,
    # and in a run of x's vim tiles matches NON-OVERLAPPING from the line's
    # first one (searchpos from column 8 answers 9, not 9-because-of-cursor+1;
    # 'xx' steps by 2 and 'xxx' by 3) where this editor finds every match.
    # See COMMANDS.md.  The long-line rows below use 'ab-cd', which cannot
    # overlap itself, so they still cover the pan past the right screen edge.
    ('wide', ['/001497\r'], 'cf4987bfafeec1cc',
     [(19, 0, '001497xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '001478')]),
    ('wide', ['G', '?000501\r'], 'cf4987bfafeec1cc',
     [(22, 0, '001500xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '001478'),
      (11, 0, '000501xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '000490')]),
    ('wd', ['G', '?ab-cd\r', 'n'], '5c9f0580f938e2cb',
     [(22, 0, '03300 foo.bar(baz) qux_1', ''),
      (16, 197, '(03294)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (16, 191, '(03294)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '')]),
    ('num', ['/001000\r'], '22c710eca7f26684',
     [(11, 0, '001000', '000989')]),
    ('num', ['/012800\r'], '22c710eca7f26684',
     [(22, 0, '012800', '012778')]),
    ('num', ['/012800\r', 'n'], '22c710eca7f26684',
     [(22, 0, '012800', '012778'),
      (22, 0, '012800', '012778')]),
    ('num', ['G', '/000001\r'], '22c710eca7f26684',
     [(22, 0, '012800', '012778'),
      (0, 0, '000001', '000001')]),
    ('num', ['G', '?000100\r'], '22c710eca7f26684',
     [(22, 0, '012800', '012778'),
      (11, 0, '000100', '000089')]),
    ('num', ['/006400\r', '?000100\r'], '22c710eca7f26684',
     [(11, 0, '006400', '006389'),
      (11, 0, '000100', '000089')]),
    ('num', ['/000002\r', 'n', 'n'], '22c710eca7f26684',
     [(1, 0, '000002', '000001'),
      (1, 0, '000002', '000001'),
      (1, 0, '000002', '000001')]),
]

def put_like_vim():
    """yy / nyy / Y / p / P / np put the text, the cursor and the window where
    vim does -- on indented files, blank and empty lines, a file with no final
    line end, an empty file, lines past the right screen edge, and a 40-line
    file put at its end -- and write the file vim wrote."""
    import hashlib
    files = dict(hml_files(), **ins_files())
    files.update(ops_files())
    files.update(plus_files())
    for f, keys, sha, want in VIM_PUT:
        skip = PUT_SKIP.get((f, tuple(keys)))
        if skip == 'all':
            continue
        data = files[f] if f in files else make(int(f))
        e = Editor(data)
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim put {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            if skip != 'sha':
                e.key(':w\r')
                got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
                check(f'vim put {f} {keys!r}: file as vim wrote it ({got})',
                      got == sha)
        finally:
            e.close()


def srch_like_vim():
    """/ ? n N put the cursor, the column and the window where vim does -- on a
    wrapped search, a repeat in both directions, an empty pattern, a pattern
    that is not there, an empty file, a match past the right screen edge, and a
    12800-line file the search has to page through -- and change nothing."""
    import hashlib
    files = dict(hml_files(), **ins_files())
    files.update(ops_files())
    files.update(plus_files())
    for f, keys, sha, want in VIM_SRCH:
        data = files[f] if f in files else make(int(f))
        e = Editor(data)
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                e.key(k)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim srch {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim srch {f} {keys!r}: the file is untouched ({got})',
                  got == sha)
        finally:
            e.close()


def paint_cost():
    """A key that moves the cursor inside the screen, or does nothing at all,
    must not repaint the screen.

    The vim tables read the screen, so they catch a repaint that was wrongly
    SKIPPED -- the rows come back stale.  They cannot catch a repaint that
    happened and did not need to, because the screen looks identical either
    way.  This measures what actually went down the wire, where at 9600 baud a
    byte is about a millisecond: a 24-row frame of 200-column lines is 806
    bytes, nearly a second of watching the screen crawl -- what pressing 'n'
    would cost if it repainted.

    The thresholds are deliberately loose -- this is testing an order of
    magnitude, not a byte count, so a renderer change that is merely different
    does not fail it."""
    files = dict(hml_files(), **ins_files())
    files.update(ops_files())

    def wire(e, key):
        before = len(e.cap.getvalue())
        e.key(key)
        return len(e.cap.getvalue()) - before

    for name, data, first in [('jp', files['jp'], '/bar\r'),
                              ('wide', files['wide'], '/00\r'),
                              ('num', make(12800), '/00\r')]:
        e = Editor(data)
        try:
            e.key(first)
            step = wire(e, 'n')              # the next match, still on the screen
            full = wire(e, '\x0c')           # ^L: that same frame, in full
            check(f'{name}: an on-screen n sends {step} bytes, not a repaint',
                  step < 64)
            check(f'{name}: ... and the full repaint it avoided is {full} '
                  f'({full // max(step, 1)}x)', full > 4 * step)
            # a key that is not a command at all runs no handler: draw nothing
            unk = wire(e, 'Q')
            check(f'{name}: an unknown key sends {unk} bytes', unk < 64)
        finally:
            e.close()

    # ...but a match that pans past the right edge MUST still repaint: the
    # renderer falls back to a full frame when HSCROL moves, and this is the
    # guard that the cheap path did not swallow that case too.
    e = Editor(files['wd'])
    try:
        e.key('/ab-cd\r')
        near = wire(e, 'n')                  # column 17: no pan
        for _ in range(11):
            e.key('n')                       # ... up to column 83: past the edge
        pan = wire(e, 'n')
        check(f'wd: the n that pans past column 80 repaints ({pan} bytes '
              f'vs {near} for one that does not)', pan > 4 * near)
    finally:
        e.close()

    # --- entering insert mode draws nothing: 'i a A I R' move the cursor at
    #     most, and the ESC that leaves insert steps it one left.  Both ends
    #     are a cursor reposition, not a frame.  (The mode word on the message
    #     row is drawn by MODEMS after the frame, so it is in these counts.) ---
    e = Editor(make(12800))
    try:
        e.key('6400G')
        full = wire(e, '\x0c')
        for k in 'iaAIR':
            got = wire(e, k)
            check(f'insert {k!r}: entering insert does not repaint ({got} '
                  f'bytes, the frame it skipped is {full})', got < 64)
            before = len(e.cap.getvalue())
            send_keys(e, '\x1b')         # a lone ESC settles on a timeout
            esc = len(e.cap.getvalue()) - before
            check(f'insert {k!r}: the ESC leaving insert does not repaint '
                  f'({esc} bytes)', esc < 64)
    finally:
        e.close()

    # --- a char typed at the END of a line has no tail to shift along, so it
    #     needs no ICH: the byte itself is the whole update.  One typed with
    #     text after it still opens a cell. ---
    e = Editor(files['bl'])
    try:
        e.key('$a')
        before = len(e.cap.getvalue())
        e.key('X')
        out = e.cap.getvalue()[before:]
        check(f'insert at the line end sends the char, not ICH ({out!r})',
              '[1@' not in out and len(out) <= 8)
        send_keys(e, '\x1b')
        e.key('0i')
        before = len(e.cap.getvalue())
        e.key('Y')
        out = e.cap.getvalue()[before:]
        check(f'insert before text opens a cell with ICH ({out!r})',
              '[1@' in out)
        send_keys(e, '\x1b')
        check(f'ICH: the text is as typed ({rows(e)[0]!r})',
              rows(e)[0] == 'YabX')
    finally:
        e.close()

    # --- a <CR> typed at the end of a line carries nothing away from it, so
    #     the row the cursor was on must not be re-sent; one typed inside the
    #     line does carry text away, and that row must be redrawn. ---
    for keys, split, label in [('0A', False, 'at the line end'),
                               ('0lli', True, 'inside the line')]:
        e = Editor(b'zzzzzzzzzzzzzzzz\r\nqqqq\r\n')
        try:
            e.key(keys)
            before = len(e.cap.getvalue())
            e.key('\r')
            out = e.cap.getvalue()[before:]
            check(f'<CR> {label}: the line above is '
                  f'{"redrawn" if split else "left alone"} ({out!r})',
                  ('zzz' in out) == split)
            send_keys(e, '\x1b')
        finally:
            e.close()


def ops_cmds():
    """The new commands where they are not vim, and the paged proofs: a count is
    ignored, 'cc' does nothing, '^L' repaints without changing anything, and
    o / J / ~ / dw / cw deep in a paged file write back byte-exact."""
    files = dict(hml_files(), **ins_files())
    files.update(ops_files())
    # --- counts are ignored (vim: 3o repeats the text, 3J joins 3 lines,
    #     3~ toggles 3 chars, 3dw deletes 3 words) ---
    # (the rows are as the screen shows them: a blank-only line reads blank and
    #  a TAB is expanded)
    for keys, want in [('0' + '3oX\x1b', ['ab', 'X', '']),
                       ('0' + '3OX\x1b', ['X', 'ab', '']),
                       ('0' + '3J', ['ab', '        cd']),
                       ('0' + '3~', ['Ab', ''])]:
        e = Editor(files['bl'])
        try:
            if keys.endswith('\x1b'):
                send_keys(e, keys[:-1]); send_keys(e, '\x1b')
            else:
                send_keys(e, keys)
            check(f'ops count {keys!r}: {rows(e)[:len(want)]} == {want} (count ignored)',
                  rows(e)[:len(want)] == want)
        finally:
            e.close()
    # --- 'cc' is not implemented: it must not delete the line, and must not
    #     leave the editor in insert mode either ---
    e = Editor(files['bl'])
    try:
        send_keys(e, 'cc')
        check(f'cc: nothing happens ({rows(e)[0]!r})', rows(e)[0] == 'ab')
        check('cc: it does not enter insert mode', e.s.mem(SYM['EDMODE'])[0] == 0)
        check('cc: the text is unmodified (:q exits)', at_ccp(e, ':q\r'))
    finally:
        e.close()
    # --- 'c' then a key that is not a motion cancels, as 'd' does ---
    e = Editor(files['bl'])
    try:
        send_keys(e, 'cq')
        check('c then a non-motion: cancelled, nothing modified (:q exits)',
              at_ccp(e, ':q\r'))
    finally:
        e.close()
    # --- 'f F t T ; , %' are not motions in this editor, and an operator on
    #     one must cancel like 'cq' above.  A key left in OPCTAB with no CMDTAB
    #     row is not inert: OPPEND takes the class, VSCAN finds no handler so
    #     the cursor does not move, and the inclusive INX H turns the empty span
    #     into one character -- 'df' becomes 'x' and 'cf' becomes 's',
    #     silently. ---
    for op in 'dc':
        for mot in 'fFtT;,%':
            e = Editor(files['bl'])
            try:
                send_keys(e, op + mot)
                check(f'{op}{mot}: not a motion, so nothing is deleted '
                      f'({rows(e)[0]!r})', rows(e)[0] == 'ab')
                check(f'{op}{mot}: and no insert mode',
                      e.s.mem(SYM['EDMODE'])[0] == 0)
                check(f'{op}{mot}: the text is unmodified (:q exits)',
                      at_ccp(e, ':q\r'))
            finally:
                e.close()
    # --- ^L: a full repaint that changes nothing (and clears an ex message) ---
    e = Editor(files['num'])
    try:
        e.key('10000G')
        was, v0 = [''.join(r) for r in e.screen().screen], e.screen()
        e.key(':nosuch\r')
        check('^L: the ex error is on the bottom row',
              bottom(e).startswith('Invalid command'))
        mark = len(e.cap.getvalue())
        e.key('l')                        # a still motion: the cursor only
        moved = len(e.cap.getvalue()) - mark
        mark = len(e.cap.getvalue())
        e.key('h')
        e.key('\x0c')
        out = e.cap.getvalue()[mark:]
        scr, v = [''.join(r) for r in e.screen().screen], e.screen()
        check(f'^L: it repaints in full ({len(out)} bytes out, a motion took '
              f'{moved})', len(out) > 10 * moved)
        check('^L: a full repaint blanks the message row, as vim clears its own',
              bottom(e) == '')
        check('^L: the text rows are unchanged', scr[:23] == was[:23])
        check(f'^L: the cursor does not move ({v.row}, {v.col})',
              (v.row, v.col) == (v0.row, v0.col))
        check('^L: nothing is modified (:q exits)', at_ccp(e, ':q\r'))
    finally:
        e.close()
    # --- the paged proofs: edit deep in 100 K, then :w byte-exact ---
    lines = [l.decode() for l in files['num'].split(b'\r\n')[:-1]]

    def joined_up(L):
        L[11999] = L[11999] + ' ' + L[12000]
        del L[12000]

    for keys, edit, tag in [
            ('12000G' + 'oNEW\x1b', lambda L: L.insert(12000, 'NEW'), 'o'),
            ('12000G' + 'ONEW\x1b', lambda L: L.insert(11999, 'NEW'), 'O'),
            ('12000G' + 'J', joined_up, 'J'),
            ('12000G' + 'dw', lambda L: L.__setitem__(11999, ''), 'dw'),
            ('12000G' + 'cwQQQ\x1b', lambda L: L.__setitem__(11999, 'QQQ'), 'cw'),
            ('12000G' + 'lD', lambda L: L.__setitem__(11999, '0'), 'D')]:
        e = Editor(files['num'])
        try:
            if keys.endswith('\x1b'):
                send_keys(e, keys[:-1]); send_keys(e, '\x1b')
            else:
                send_keys(e, keys)
            e.key(':w\r')
            want = list(lines)
            edit(want)
            check(f'ops {tag} deep in 100 K: :w byte-exact',
                  saved_bytes(e) == ('\r\n'.join(want) + '\r\n').encode())
        finally:
            e.close()
    # --- a burst typed on an opened line pages out and comes back byte-exact ---
    e = Editor(files['num'])
    try:
        e.key('6000G')
        send_keys(e, 'o' + BIGINS[:-1])          # 600 lines, 4.8 K, no last CR
        send_keys(e, '\x1b')
        e.key(':w\r')
        want = list(lines)
        want[6000:6000] = BIGINS[:-1].split('\r')
        check('ops o: a 4.8 K burst on an opened line is written byte-exact',
              saved_bytes(e) == ('\r\n'.join(want) + '\r\n').encode())
    finally:
        e.close()

    # --- an empty last line is a line.  vim keeps one whatever the text ends
    #     with (measured: a buffer of [abc, ""] reports line("$") == 2 with
    #     'endofline' off as well as on), and writes it as a second newline.
    #     This editor's text IS the file's bytes, so the break that ends the
    #     line the cursor was on is the only one there is unless a second goes
    #     in for the new empty line -- without it the row is painted but no
    #     motion can reach it, and ':w' loses it.  The terminated cases below
    #     already worked; the unterminated ones are the bug. ---
    for label, data, keys, want in [
            ('a new file',            b'',        'iabc\r',  b'abc\r\n\r\n'),
            ('no line end, <CR>',     b'abc',     '$a\r',    b'abc\r\n\r\n'),
            ('no line end, o',        b'abc',     'o',       b'abc\r\n\r\n'),
            ('a line end, <CR>',      b'abc\r\n', '$a\r',    b'abc\r\n\r\n'),
            ('a line end, o',         b'abc\r\n', 'o',       b'abc\r\n\r\n')]:
        e = Editor(data)
        try:
            send_keys(e, keys)
            send_keys(e, '\x1b')
            v = e.screen()
            check(f'empty last line ({label}): the cursor is on it '
                  f'({v.row}, {v.col})', (v.row, v.col) == (1, 0))
            e.key('k')
            e.key('j')
            v = e.screen()
            check(f'empty last line ({label}): k then j comes back to it '
                  f'({v.row}, {v.col})', (v.row, v.col) == (1, 0))
            e.key(':w\r')
            got = saved_bytes(e)
            check(f'empty last line ({label}): written as vim writes it '
                  f'({got!r})', got == want)
        finally:
            e.close()

    # ... and the second break belongs to the two insert paths, NOT to OPNBRK:
    # a put at the end of the text calls it too, and would gain a spurious
    # empty line of its own.
    e = Editor(b'abc')
    try:
        send_keys(e, 'yyp')
        check(f'a put at the end of an unterminated file opens no extra line '
              f'({rows(e)[:3]})', rows(e)[:3] == ['abc', 'abc', '~'])
        e.key(':w\r')
        got = saved_bytes(e)
        # the put's last line came from an UNterminated source line, so the
        # register carried no terminator and neither does the file -- this
        # editor writes the bytes it holds (the 'yy / p / P' section of
        # COMMANDS.md records the same thing for 'bl 3yy G p')
        check(f'... and writes both lines and nothing more ({got!r})',
              got == b'abc\r\nabc')
    finally:
        e.close()


NWR = 'File changed (! to force)'


def bottom(e):
    return ''.join(e.screen().screen[23]).rstrip()


def ctrlg(e):
    """What '^G' reports: the buffer's name, its flags and where the cursor is.
    The bottom row is vim's message line, not a status line, so '^G' is the
    only thing that names the buffer or says it has unsaved changes -- which is
    why the checks that need either ask '^G'."""
    e.key('\x07')
    return bottom(e)


def escaped(e):
    """ESC, plus the settle GETKEY's lone-ESC timeout needs before the screen
    can be read.  While that countdown runs the guest draws nothing, and
    run_until_quiet reads 'drew nothing' as 'settled' -- the same trap
    ex_settled covers for a compute-bound ':s'."""
    was = bottom(e)
    e.key('\x1b')
    for _ in range(25):
        if bottom(e) != was:
            return
        e.s.run_until_quiet(timeout=40)


def cpm_dir(e, drive=''):
    """The CCP's DIR listing (of *drive*), as one string."""
    e._ensure_ccp()
    return e.s.cmd('DIR ' + drive)


def work_files(d):
    """The editor's work files (name.$$$ of the files used here, a blank
    name's, VIBACKUP.$$$) in the DIR listing *d*."""
    return re.findall(r'(?:\b(?:TEST|VIBACKUP|OTHER|NEW\d?|NEWF|COPY|BIG)|: {9}) +\$\$\$', d)


def listed(d, name):
    """Is NAME.TYP in the DIR listing *d*?"""
    n, t = name.split('.')
    return re.search(r'\b%s +%s\b' % (re.escape(n), re.escape(t)), d) is not None


def disk(e, spec):
    """A file read back through the guest (W), ^Z padding stripped."""
    e._ensure_ccp()
    host = spec.split(':')[-1]
    e.s.wfile(f'{spec} {host}', 'T')
    # SIMDIR, not HERE: the hostbridge writes into the simulator's working
    # directory, which a parallel runner gives each worker its own of -- with
    # HERE two workers race over the same host TEST.TXT and read each other's
    with open(os.path.join(SIMDIR, host), 'rb') as fh:
        data = fh.read()
    os.remove(os.path.join(SIMDIR, host))
    return data.rstrip(b'\x1a')


def refused(e, keys, msg, tag):
    """*keys* leave the editor with *msg* on the bottom row, the text and the
    cursor where they were."""
    v0 = e.screen()
    scr0 = [''.join(r) for r in v0.screen]
    stayed = not at_ccp(e, keys)
    v = e.screen()
    scr = [''.join(r) for r in v.screen]
    check(f'{tag}: {keys!r} stays', stayed)
    check(f'{tag}: {keys!r} shows {msg!r} ({bottom(e)!r})', bottom(e) == msg)
    check(f'{tag}: {keys!r} keeps the text and the cursor',
          scr[:23] == scr0[:23] and (v.row, v.col) == (v0.row, v0.col))


def file_cmds():
    """:w name, :wq, :x, :e name, and a buffer with no name, as vim has them."""
    # --- no file name on the command line ---
    e = Editor(None, fname='')
    try:
        check('noname: no file, so no load message', bottom(e) == '')
        check('noname: ^G says [No Name]',
              ctrlg(e) == '"[No Name]" --Buffer empty--')
        check('noname: an empty buffer', rows(e)[0] in ('', '~') and rows(e)[1] == '~')
        refused(e, ':w\r', 'No file name', 'noname')
        refused(e, ':wq\r', 'No file name', 'noname')
        send_keys(e, 'iHELLO\rWORLD\r'); send_keys(e, '\x1b')
        check('noname: typed text marks it modified',
              ctrlg(e).startswith('"[No Name]" [Modified]'))
        refused(e, ':q\r', NWR, 'noname')
        refused(e, ':x\r', 'No file name', 'noname')
        refused(e, ':e\r', NWR, 'noname')
        refused(e, ':e!\r', 'No file name', 'noname')
        refused(e, ':w NEW.TXT extra\r', 'Invalid file name', 'noname')
        e.key(':w new.txt\r')
        check('noname: :w new.txt says so', bottom(e) == '"NEW.TXT" written')
        check('noname: :w new.txt names it NEW.TXT, unmodified',
              ctrlg(e).startswith('"NEW.TXT" line'))
        check('noname: :w keeps the cursor', (e.screen().row, e.screen().col) == (2, 0))
        e.key('gg'); e.key('x')
        check('noname: then x: modified',
              ctrlg(e).startswith('"NEW.TXT" [Modified]'))
        check('noname: :x writes and exits', at_ccp(e, ':x\r'))
        check('noname: NEW.TXT holds the text',
              disk(e, 'NEW.TXT') == b'ELLO\r\nWORLD\r\n\r\n')
        d = cpm_dir(e)
        check(f'noname: no work files left {work_files(d)}', not work_files(d))
    finally:
        e.close()
    e = Editor(None, fname='')
    try:                                # 48 K typed: the window pages out
        for _ in range(10):
            send_keys(e, 'i' + BIGINS); send_keys(e, '\x1b')
        check('noname big: [No Name], modified',
              ctrlg(e).startswith('"[No Name]" [Modified]'))
        e.key(':w BIG.TXT\r')
        check('noname big: :w BIG.TXT', bottom(e) == '"BIG.TXT" written')
        check('noname big: :q exits', at_ccp(e, ':q\r'))
        check('noname big: BIG.TXT', disk(e, 'BIG.TXT') ==
              BIGINS.replace('\r', '\r\n').encode() * 10 + b'\r\n')
        d = cpm_dir(e)
        check(f'noname big: no work files left {work_files(d)}', not work_files(d))
    finally:
        e.close()
    e = Editor(None, fname='')
    try:
        check('noname: :x unmodified exits', at_ccp(e, ':x\r'))
    finally:
        e.close()
    e = Editor(None, fname='')
    try:
        check('noname: :q unmodified exits', at_ccp(e, ':q\r'))
    finally:
        e.close()

    # --- a new file: :w makes it ---
    e = Editor(None, fname='NEWF.TXT')
    try:
        check('new file: the load message says [New]', bottom(e) == '"NEWF.TXT" [New]')
        e.key(':w\r')
        check('new file: :w says so', bottom(e) == '"NEWF.TXT" written')
        check('new file: :w stays unmodified, and it is not new any more',
              ctrlg(e) == '"NEWF.TXT" --Buffer empty--')
        check('new file: :q exits', at_ccp(e, ':q\r'))
        check('new file: :w made it', listed(cpm_dir(e), 'NEWF.TXT'))
    finally:
        e.close()

    # --- :w name keeps the buffer's name and its changes (100 K) ---
    base = make(12800)
    one = base[:2999 * 8] + b'03000\r\n' + base[3000 * 8:]      # line 3000 x'ed
    two = one[:-8]                                              # and the last line gone
    e = Editor(base)
    try:
        e.key('3000G'); e.key('x')
        v0 = e.screen(); scr0 = [''.join(r) for r in v0.screen]
        e.key(':w OTHER.TXT\r')
        v = e.screen(); scr = [''.join(r) for r in v.screen]
        check('w name: text and cursor kept', scr[:23] == scr0[:23] and
              (v.row, v.col) == (v0.row, v0.col))
        check('w name: still TEST.TXT, still modified',
              ctrlg(e).startswith('"TEST.TXT" [Modified]'))
        refused(e, ':q\r', NWR, 'w name')
        refused(e, ':w OTHER.TXT\r', 'File exists (! to force)', 'w name')
        refused(e, ':wq OTHER.TXT\r', 'File exists (! to force)', 'w name')
        e.key('G'); e.key('dd')
        e.key(':w! OTHER.TXT\r')
        check('w name: :w! overwrites, still modified',
              ctrlg(e).startswith('"TEST.TXT" [Modified]'))
        check('w name: :q! exits', at_ccp(e, ':q!\r'))
        check('w name: TEST.TXT unchanged', saved_bytes(e) == base)
        check('w name: OTHER.TXT has both edits', disk(e, 'OTHER.TXT') == two)
        d = cpm_dir(e)
        check(f'w name: no work files left {work_files(d)}', not work_files(d))
    finally:
        e.close()
    e = Editor(base)
    try:
        e.key('3000G'); e.key('x')
        e.key(':w OTHER.TXT\r')
        e.key('G'); e.key('dd')
        e.key(':w\r')
        check('w name then :w: unmodified', '[Modified]' not in ctrlg(e))
        check('w name then :w: :q exits', at_ccp(e, ':q\r'))
        check('w name then :w: TEST.TXT has both edits', saved_bytes(e) == two)
        check('w name then :w: OTHER.TXT has the first', disk(e, 'OTHER.TXT') == one)
    finally:
        e.close()

    # --- :wq / :x ---
    small = make(256)
    e = Editor(small)
    try:
        check(':x unmodified exits', at_ccp(e, ':x\r'))
        check(':x unmodified: no backup (nothing written)', not listed(cpm_dir(e), 'TEST.BAK'))
    finally:
        e.close()
    e = Editor(small)
    try:
        e.key('x')
        check(':x modified writes and exits', at_ccp(e, ':x\r'))
        check(':x modified: written', saved_bytes(e) == b'00001\r\n' + small[8:])
    finally:
        e.close()
    e = Editor(small)
    try:
        check(':wq NEW.TXT unmodified exits', at_ccp(e, ':wq new.txt\r'))
        check(':wq NEW.TXT: written', disk(e, 'NEW.TXT') == small)
        check(':wq NEW.TXT: TEST.TXT untouched', saved_bytes(e) == small)
    finally:
        e.close()
    e = Editor(small)
    try:
        e.key('x')
        refused(e, ':wq NEW.TXT\r', NWR, ':wq name modified')
        refused(e, ':x NEW2.TXT\r', NWR, ':x name modified')
        e.key('j'); e.key('x')
        check(':x! NEW3.TXT exits', at_ccp(e, ':x! NEW3.TXT\r'))
        check(':wq name modified: NEW.TXT written', disk(e, 'NEW.TXT') == b'00001\r\n' + small[8:])
        check(':x name modified: NEW2.TXT written', disk(e, 'NEW2.TXT') == b'00001\r\n' + small[8:])
        check(':x! name: NEW3.TXT written',
              disk(e, 'NEW3.TXT') == b'00001\r\n00002\r\n' + small[16:])
        check(':x! name: TEST.TXT untouched', saved_bytes(e) == small)
    finally:
        e.close()

    # --- :e name ---
    e = Editor(small)
    try:
        e.key('100G'); e.key('x')
        refused(e, ':e OTHER.TXT\r', NWR, ':e name')
        e.key(':e! other.txt\r')
        check(':e! new name: named on the bottom row', bottom(e) == '"OTHER.TXT"')
        check(':e! new name: empty', rows(e)[0] in ('', '~') and rows(e)[1] == '~')
        send_keys(e, 'i  one\rtwo'); send_keys(e, '\x1b')
        e.key(':w\r')
        e.key(':e test.txt\r')
        check(':e name: back on TEST.TXT, line 1', bottom(e) == '"TEST.TXT"' and
              rows(e)[0] == txt(1) and (e.screen().row, e.screen().col) == (0, 0))
        e.key(':e OTHER.TXT\r')
        check(':e name: OTHER.TXT on its first non-blank', bottom(e) == '"OTHER.TXT"' and
              rows(e)[0] == '  one' and (e.screen().row, e.screen().col) == (0, 2))
        check(':e name: :q exits', at_ccp(e, ':q\r'))
        check(':e name: TEST.TXT unchanged', saved_bytes(e) == small)
        check(':e name: OTHER.TXT written',
              disk(e, 'OTHER.TXT') == b'  one\r\ntwo\r\n')
        d = cpm_dir(e)
        check(f':e name: no work files left {work_files(d)}', not work_files(d))
    finally:
        e.close()

    # --- messages: one stays until another replaces it ---
    e = Editor(small)
    try:
        e.key('5G')
        for keys, msg in ((':ee\r', 'Invalid command: ee'),
                          (':  wx y\r', 'Invalid command: wx y'),
                          (':W\r', 'Invalid command: W'),
                          (':q x\r', 'Trailing chars: x'),
                          (':q! x\r', 'Trailing chars: x'),
                          (':ve\r', 'V1.0'),
                          (':ve x\r', 'Trailing chars: x'),
                          (':1ve\r', 'Invalid command: 1ve'),
                          (':ver\r', 'Invalid command: ver'),
                          (':w a*b\r', 'Invalid file name'),
                          (':w B:\r', 'Invalid file name'),
                          (':w .TXT\r', 'Invalid file name'),
                          (':w Q:X\r', 'Invalid file name'),
                          (':w 1:X\r', 'Invalid file name'),
                          (':w A_B\r', 'Invalid file name'),
                          (':e x y\r', 'Invalid file name')):
            refused(e, keys, msg, 'msg')
        e.key('j')
        check('msg: j leaves the message', bottom(e) == 'Invalid file name')
        e.key('x')
        check('msg: x leaves the message (vim replaces one only with another)',
              bottom(e) == 'Invalid file name')
        e.key(':\r')
        check('msg: an empty : line does nothing', bottom(e) == '')
        e.key(':w! A:TEST.TXT\r')
        check('msg: A:TEST.TXT is the buffer\'s own file',
              bottom(e) == '"TEST.TXT" written')
        check('msg: :q exits', at_ccp(e, ':q  \r'))
        check('msg: written', saved_bytes(e) == small[:40] + b'00006\r\n' + small[48:])
    finally:
        e.close()

    # --- another drive ---
    bdisk = os.path.join(WORK, 'drive_b.DSK')
    e = Editor(base)
    try:
        shutil.copy(TEMPLATE, bdisk)
        e.s.monitor('MOUNT dsk0:drive1 "%s"' % os.path.relpath(bdisk, SIMDIR))
        e.key('3000G'); e.key('x')
        e.key(':w b:copy.txt\r')
        check('drive B: :w names the drive, as vim names a path outside the cwd',
              bottom(e) == '"B:COPY.TXT" written')
        check('drive B: :w keeps the change',
              ctrlg(e).startswith('"TEST.TXT" [Modified]'))
        e.key('G'); e.key('dd')
        e.key(':w b:copy.txt\r')
        check('drive B: File exists', bottom(e) == 'File exists (! to force)')
        e.key(':w\r')
        check('drive B: then :w own', bottom(e) == '"TEST.TXT" written')
        check('drive B: :q exits', at_ccp(e, ':q\r'))
        check('drive B: COPY.TXT has the first edit', disk(e, 'B:COPY.TXT') == one)
        check('drive B: TEST.TXT has both', saved_bytes(e) == two)
        d = cpm_dir(e, 'B:')
        check(f'drive B: no work files on B {work_files(d)}', not work_files(d))
        # 'vi b:copy.txt' from A>: vim shows a path relative to the current
        # directory ("../x/VI.MAC", but a file in the cwd bare), and the
        # logged drive is CP/M's current directory -- so another drive's file
        # keeps its 'B:' in every message that names it.
        e.s.send('VI B:COPY.TXT\r')
        e.s.run_until_quiet(quiet=e.quiet, timeout=40)
        check('drive B: vi b:copy.txt names B: on load', bottom(e) == '"B:COPY.TXT"')
        check('drive B: ^G names B:', ctrlg(e) == '"B:COPY.TXT" line 1 col 1')
        e.key(':w\r')
        check('drive B: :w names B:', bottom(e) == '"B:COPY.TXT" written')
        check('drive B: vi b:copy.txt :q exits', at_ccp(e, ':q\r'))
    finally:
        e.close()
    e = Editor(None, fname='')
    try:
        shutil.copy(TEMPLATE, bdisk)
        e.s.monitor('MOUNT dsk0:drive1 "%s"' % os.path.relpath(bdisk, SIMDIR))
        send_keys(e, 'i' + BIGINS); send_keys(e, '\x1b')
        e.key(':w b:big.txt\r')
        check('drive B: noname takes BIG.TXT',
              ctrlg(e).startswith('"B:BIG.TXT" line'))
        e.key('gg'); e.key('x'); e.key(':w\r')
        check('drive B: :w BIG.TXT', bottom(e) == '"B:BIG.TXT" written')
        check('drive B: :q exits', at_ccp(e, ':q\r'))
        want = BIGINS.replace('\r', '\r\n').encode()[1:] + b'\r\n'
        check('drive B: BIG.TXT', disk(e, 'B:BIG.TXT') == want)
        check('drive B: no BIG.TXT on A', not listed(cpm_dir(e), 'BIG.TXT'))
    finally:
        e.close()
    try:
        os.remove(bdisk)
    except OSError:
        pass


def plus_files():
    """hml_files() plus an empty one, for '+n' on a file with no lines."""
    f = hml_files()
    f['0'] = b''
    return f


# (file, [the command-line argument, then keys], [the four numbers after the
# file is opened, then after each key]) from vim 9.1 (-u NONE -N, 24 lines,
# 'nowrap'), regenerable with `python3 vimref.py --print plus`.  keys[0] is
# vim's own '+{n}' / '+' argument -- where vim puts the line it starts on is
# recorded, not reasoned about.  VI takes it AFTER the file name (the CCP
# parses the first token into the FCB at 005CH), so the editor's command line
# is 'VI TEST.TXT +500' where vim's is 'vim +500 TEST.TXT'.
VIM_PLUS = [
    # ---- where the window lands: the minimum scroll near the top, centred
    #      when the line is far away (the boundary is +35 / +36 on 24 rows) ----
    ('num', ['+1'], ['1 1 0 0']),
    ('num', ['+2'], ['2 1 1 0']),
    ('num', ['+12'], ['12 1 11 0']),
    ('num', ['+23'], ['23 1 22 0']),
    ('num', ['+24'], ['24 2 22 0']),
    ('num', ['+25'], ['25 3 22 0']),
    ('num', ['+35'], ['35 13 22 0']),
    ('num', ['+36'], ['36 25 11 0']),
    ('num', ['+500'], ['500 489 11 0']),
    # ---- the ends: the last line, past it, '+' alone, and '+0' ----
    ('num', ['+12800'], ['12800 12778 22 0']),
    ('num', ['+99999'], ['12800 12778 22 0']),
    ('num', ['+'], ['12800 12778 22 0']),
    ('num', ['+0'], ['1 1 0 0']),
    ('num', ['+00'], ['1 1 0 0']),
    ('num', ['+007'], ['7 1 6 0']),
    ('num', ['+0012800'], ['12800 12778 22 0']),
    # ---- the window is left in a normal state to go on editing from ----
    ('num', ['+500', 'H', 'L', 'M'],
     ['500 489 11 0', '489 489 0 0', '511 489 22 0', '500 489 11 0']),
    ('num', ['+24', 'k', 'k'], ['24 2 22 0', '23 2 21 0', '22 2 20 0']),
    ('num', ['+', 'gg'], ['12800 12778 22 0', '1 1 0 0']),
    # ---- the column: the line's first non-blank, and no pan on a long line ----
    ('ind', ['+3000'], ['3000 2989 11 10']),
    ('ind', ['+2'], ['2 1 1 10']),
    ('wide', ['+700'], ['700 689 11 0']),
    ('wide', ['+700', '$'], ['700 689 11 0', '700 689 11 5']),
    ('wd', ['+1500'], ['1500 1489 11 0']),
    # ---- files shorter than the screen, one line, no last line end, empty ----
    ('3', ['+2'], ['2 1 1 0']),
    ('3', ['+9'], ['3 1 2 0']),
    ('1', ['+5'], ['1 1 0 3']),
    ('nl', ['+4'], ['4 1 3 2']),
    ('nl', ['+9'], ['4 1 3 2']),
    ('0', ['+5'], ['1 1 0 0']),
    ('0', ['+'], ['1 1 0 0']),
]

RO = "'-R' is set (! to force)"


def plus_like_vim():
    """'+{n}' and '+' on the command line leave the cursor and the window where
    vim's own do: the first non-blank of the line, the window scrolled the
    least it can be for a line near the top and centred on a far one, the last
    line for '+' alone or a number past the end, and line 1 for '+0'.  Every
    row of VIM_PLUS was recorded from vim -- see the table."""
    files = plus_files()
    for f, keys, want in VIM_PLUS:
        e = Editor(files[f], args=' ' + keys[0])
        try:
            lines = files[f].decode().split('\r\n')
            if lines[-1] == '':
                lines.pop()
            for i, (k, w) in enumerate(zip(keys, want)):
                if i:
                    e.key(k)                    # keys[0] is the argument, not a key
                v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                scr = [''.join(r).rstrip() for r in v.screen]
                ln, top, row, col = map(int, w.split())
                got = '%d %d' % (v.row, v.col + hs)
                tag = 'plus %s %r %r' % (f, keys, k)
                check(f'{tag}: {got} == {row} {col}', got == '%d %d' % (row, col))
                if lines:
                    show = lambda n: expand(lines[n - 1])[hs:hs + 80].rstrip()
                    check(f'{tag}: rows show lines {top} and {ln}',
                          scr[0] == show(top) and scr[row] == show(ln))
            if f == 'num' and keys[0] == '+500':
                check('plus: the argument does not modify the file (:q exits)',
                      at_ccp(e, ':q\r'))
        finally:
            e.close()


def arg_cmds():
    """The command line beyond the file name: '+{n}' deep in a paged file is a
    place to edit from, and '-R' refuses a write to the file it opened unless
    ':w!' overrides it (vim's E45), while ':w name' goes through.  '/R' is
    accepted as CP/M spells a switch, the CCP's upper casing makes '-r' the
    same, and anything else on the line is ignored."""
    content = make(12800)

    # --- '+{n}' deep in the 100 K file: the edit there is written byte-exact --
    e = Editor(content, args=' +6000')
    try:
        check('arg +6000: on line 6000', rows(e)[e.screen().row] == txt(6000))
        e.key('x')
        e.key(':w\r')
        want = content.replace(line(6000), b'%05d\r\n' % 6000, 1)
        check('arg +6000: the edit written byte-exact', saved_bytes(e) == want)
    finally:
        e.close()

    # --- an empty file paints the same as with no argument at all ------------
    e, f = Editor(b'', args=' +5'), Editor(b'')
    try:
        check('arg +5: an empty file paints as it does with no argument',
              rows(e) == rows(f) and e.screen().row == f.screen().row)
    finally:
        e.close()
        f.close()

    # --- -R: every write to the file it opened is refused ---------------------
    e = Editor(content, args=' -R')
    try:
        e.key('x')                              # -R does not stop the editing
        check('arg -R: x still edits the text', rows(e)[0] == txt(1)[1:])
        refused(e, ':w\r', RO, 'arg -R')
        refused(e, ':wq\r', RO, 'arg -R')
        refused(e, ':x\r', RO, 'arg -R')
        refused(e, 'ZZ', RO, 'arg -R')
        check('arg -R: :q! leaves', at_ccp(e, ':q!\r'))
        check('arg -R: the file on disk is untouched', saved_bytes(e) == content)
    finally:
        e.close()

    # --- -R: ':w!' overrides it, ':w name' was never refused -----------------
    e = Editor(content, args=' -R')
    try:
        e.key('x')
        e.key(':w!\r')
        check('arg -R: :w! writes', saved_bytes(e) == content.replace(
            line(1), b'%05d\r\n' % 1, 1))
    finally:
        e.close()
    e = Editor(content, args=' -R')
    try:
        e.key('x')
        e.key(':w OTHER.TXT\r')
        check('arg -R: :w name is not refused', bottom(e) != RO)
        check('arg -R: :q! leaves', at_ccp(e, ':q!\r'))
        check('arg -R: :w name wrote it', disk(e, 'OTHER.TXT') == content.replace(
            line(1), b'%05d\r\n' % 1, 1))
        check('arg -R: the file it opened is untouched',
              disk(e, 'TEST.TXT') == content)
    finally:
        e.close()

    # --- the spellings: '/R' as CP/M writes it, '-r' as the CCP upper cases ---
    for sw in (' /R', ' -r'):
        e = Editor(content, args=sw)
        try:
            refused(e, ':w\r', RO, 'arg%s' % sw)
        finally:
            e.close()

    # --- anything else on the line is ignored, and the two combine -----------
    e = Editor(content, args=' -Q +9')
    try:
        check('arg -Q: an unknown switch is ignored', rows(e)[e.screen().row] == txt(9))
        e.key('x')
        e.key(':w\r')
        check('arg -Q: the write goes through', saved_bytes(e) ==
              content.replace(line(9), b'%05d\r\n' % 9, 1))
    finally:
        e.close()
    e = Editor(content, args=' +500 -R')
    try:
        check('arg +500 -R: on line 500', rows(e)[e.screen().row] == txt(500))
        check('arg +500 -R: centred on row 11', e.screen().row == 11)
        refused(e, ':w\r', RO, 'arg +500 -R')
    finally:
        e.close()


def ndd(label, n):
    """Ndd on every size: at the start of the file, deep in it, a count past the
    end, and across the resident window on 40K/100K; :w byte-exact.  A count
    over 1 on the last line does nothing and leaves the file unmodified."""
    if n >= 1:
        e = Editor(make(n))
        try:
            e.key('G'); e.key('2dd')
            check(f'{label}: 2dd on the last line keeps it', rows(e)[e.screen().row] == txt(n))
            check(f'{label}: 2dd on the last line leaves it unmodified', at_ccp(e, ':q\r'))
        finally:
            e.close()

    L = lines_of(n)
    e = Editor(make(n))
    try:
        e.key('3dd')
        if n != 1:                                # the only line is the last one
            del L[0:3]
        check(f'{label}: 3dd at the start of the file',
              rows(e)[0] in ((L[0],) if L else ('', '~')))
        if len(L) >= 2:
            tgt = min(len(L) - 1, 4000)           # 1-based, not the last line
            e.key('%dG' % tgt); e.key('300dd'); del L[tgt - 1:tgt + 299]
            v = e.screen()
            check(f'{label}: 300dd deep at line {tgt}',
                  rows(e)[v.row] == L[min(tgt, len(L)) - 1])
        if len(L) >= 5:
            e.key('%dG' % (len(L) - 3)); e.key('50dd'); del L[-4:]
            v = e.screen()
            check(f'{label}: 50dd past the end drops to the new last line',
                  rows(e)[v.row] == L[-1])
        e.key(':w\r')
        want = ''.join(l + '\r\n' for l in L).encode()
        check(f'{label}: Ndd :w byte-exact', saved_bytes(e) == want)
    finally:
        e.close()

    # A big count back from G 3000k runs past the end of the resident window.
    if n < 5120:
        return
    e = Editor(make(n))
    try:
        e.key('G'); e.key('3000k'); e.key('2900dd')
        cur = n - 3000
        want = make(n)[:(cur - 1) * 8] + make(n)[(cur + 2899) * 8:]
        v = e.screen()
        check(f'{label}: 2900dd past the window lands on line {cur + 2900}',
              rows(e)[v.row] == txt(cur + 2900))
        e.key(':w\r')
        check(f'{label}: 2900dd :w byte-exact', saved_bytes(e) == want)
    finally:
        e.close()


def quit_semantics(label, n):
    content = make(n)

    # :q refuses when there are unsaved changes (stays in the editor)
    e = Editor(content)
    try:
        e.key('x' if n else 'iA')                 # modify
        send_keys(e, '\x1b')
        check(f'{label}: :q refuses on unsaved change', not at_ccp(e, ':q\r'))
    finally:
        e.close()

    # :q exits when nothing changed -- and it is the one key that repaints
    # nothing: the text already on the screen is what the editor leaves behind,
    # scrolled up one row by the CCP's own CR,LF, which puts the prompt on the
    # bottom row.  It writes nothing and, having spilled nothing, it does not
    # pay a directory scan either (a BDOS delete scans the whole directory
    # whether the name is there or not -- that was a second of dead time).
    e = Editor(content)
    try:
        was = [''.join(r) for r in e.screen().screen]
        mark, steps = len(e.cap.getvalue()), e.s.steps
        check(f'{label}: :q exits when unmodified', at_ccp(e, ':q\r'))
        tail, used = e.cap.getvalue()[mark:], e.s.steps - steps
        check(f'{label}: :q does not repaint ({len(tail)} bytes out)', len(tail) < 64)
        check(f'{label}: :q does not scan the directory ({used} steps)', used < 900000)
        scr = [''.join(r) for r in e.screen().screen]
        check(f'{label}: :q leaves the text on the screen', scr[:22] == was[1:23])
        check(f'{label}: :q clears its message row', scr[22].strip() == '')
        check(f'{label}: :q puts the prompt on the bottom row',
              PROMPT.search(scr[23]) is not None)
        check(f'{label}: :q writes nothing', disk(e, 'TEST.TXT') == content)
        d = cpm_dir(e)
        check(f'{label}: :q writes no .BAK', not listed(d, 'TEST.BAK'))
        check(f'{label}: :q leaves no work files {work_files(d)}', not work_files(d))
    finally:
        e.close()

    # :q! discards and exits to CCP; the file on disk is untouched, and the work
    # files a paged session did make are gone (the flag DISCRD tests must not be
    # one the pager clears while the file is still there).
    e = Editor(content)
    try:
        e.key('G'); e.key('dd'); e.key('gg'); e.key('x')
        check(f'{label}: :q! exits to CCP', at_ccp(e, ':q!\r'))
        check(f'{label}: :q! leaves the file unchanged', saved_bytes(e) == content)
        d = cpm_dir(e)
        check(f'{label}: :q! leaves no work files {work_files(d)}', not work_files(d))
    finally:
        e.close()


def marks_files():
    """What marks need beyond hml_files()/ins_files(): a file whose lines are
    distinct and unevenly indented, so `'a` (the line's first non-blank) and
    `` `a `` (the exact column) land in visibly different places, with an empty
    line among them."""
    return dict(hml_files(), **ins_files(),
                mk=b'alpha beta\r\n  gamma delta\r\nepsilon zeta\r\n'
                   b'\r\n  last line here\r\n')


# ---------------------------------------------------------------------------
# VIM_MARKS -- marks against vim 9.1, recorded by vimref.py ('marks') BEFORE
# they were written.  Shape is VIM_SUBST's: (file, keys, the sha1 of the file
# vim wrote, [(cursor row, column, cursor line, top line) after each key]).
#
# Only `a`-`c` are used: that is the whole set this editor builds (COMMANDS.md).
#
# What the rows pin down:
#   - `'a` goes to the marked line's FIRST NON-BLANK; `` `a `` restores the
#     exact column.  That is the one difference between them and most rows
#     here exist to hold it.
#   - a mark on an empty line, on the last line, and in a file with no final
#     line end.
#   - three marks live at once and do not disturb each other.
#   - an edit BELOW a mark leaves it alone -- the one edit case where vim and
#     this editor agree.
#
# DELIBERATELY NOT HERE, because this editor is documented to deviate: an edit
# ABOVE a mark (vim shifts the mark to follow the text, this editor drops it),
# and a mark whose window has paged away (vim jumps back, this editor drops
# it).  Both are asserted in marks_cmds() instead -- recording vim for them
# would be recording a reference this editor is designed not to match.
VIM_MARKS = [
    ('mk', ['ma', 'G', "'a"], 'd0c2cb8e681aa18f',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['ma', 'G', '`a'], 'd0c2cb8e681aa18f',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['2G', '5l', 'ma', 'G', "'a"], 'd0c2cb8e681aa18f',
     [(1, 2, '  gamma delta', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta')]),
    ('mk', ['2G', '5l', 'ma', 'G', '`a'], 'd0c2cb8e681aa18f',
     [(1, 2, '  gamma delta', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta')]),
    ('mk', ['3G', '4l', 'ma', 'gg', "'a"], 'd0c2cb8e681aa18f',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 4, 'epsilon zeta', 'alpha beta'),
      (2, 4, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta')]),
    ('mk', ['3G', '4l', 'ma', 'gg', '`a'], 'd0c2cb8e681aa18f',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 4, 'epsilon zeta', 'alpha beta'),
      (2, 4, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (2, 4, 'epsilon zeta', 'alpha beta')]),
    ('mk', ['4G', 'ma', 'gg', "'a"], 'd0c2cb8e681aa18f',
     [(3, 0, '', 'alpha beta'),
      (3, 0, '', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (3, 0, '', 'alpha beta')]),
    ('mk', ['4G', 'ma', 'gg', '`a'], 'd0c2cb8e681aa18f',
     [(3, 0, '', 'alpha beta'),
      (3, 0, '', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (3, 0, '', 'alpha beta')]),
    ('mk', ['G', 'ma', 'gg', "'a"], 'd0c2cb8e681aa18f',
     [(4, 2, '  last line here', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta')]),
    ('nl', ['G', 'ma', 'gg', "'a"], 'e7f99afe3ca4c163',
     [(3, 2, '  cc', '  aa'),
      (3, 2, '  cc', '  aa'),
      (0, 2, '  aa', '  aa'),
      (3, 2, '  cc', '  aa')]),
    ('nl', ['G', 'ma', 'gg', '`a'], 'e7f99afe3ca4c163',
     [(3, 2, '  cc', '  aa'),
      (3, 2, '  cc', '  aa'),
      (0, 2, '  aa', '  aa'),
      (3, 2, '  cc', '  aa')]),
    ('mk', ['ma', '2G', 'mb', '3G', 'mc', 'G', "'a", "'b", "'c"], 'd0c2cb8e681aa18f',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta')]),
    ('mk', ['2G', 'ma', '3G', 'mb', "'a", "'b"], 'd0c2cb8e681aa18f',
     [(1, 2, '  gamma delta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta')]),
    ('mk', ['ma', 'j', 'x', "'a"], '77242601eafa1920',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (1, 0, '  gamma delta', 'alpha beta'),
      (1, 0, ' gamma delta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['ma', 'G', 'x', '`a'], 'bf1f7a78fd57ceaa',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (4, 2, '  ast line here', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['ma', '3G', 'dd', "'a"], '85bcc3e4d42b35fa',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 0, '', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta')]),
    ('3', ['ma', 'G', "'a"], 'b3c36571c67a58cf',
     [(0, 0, '  aaa', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (0, 2, '  aaa', '  aaa')]),
    ('3', ['2G', 'ma', 'G', "'a"], 'b3c36571c67a58cf',
     [(1, 0, '', '  aaa'),
      (1, 0, '', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (1, 0, '', '  aaa')]),
    ('3', ['3G', 'ma', 'gg', "'a"], 'b3c36571c67a58cf',
     [(2, 0, 'bbb', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (0, 2, '  aaa', '  aaa'),
      (2, 0, 'bbb', '  aaa')]),
    ('2', ['2G', '3l', 'ma', 'gg', '`a'], 'e27529c0f39f879a',
     [(1, 2, '  cd', 'ab'),
      (1, 3, '  cd', 'ab'),
      (1, 3, '  cd', 'ab'),
      (0, 0, 'ab', 'ab'),
      (1, 3, '  cd', 'ab')]),
    ('2', ['2G', '3l', 'ma', 'gg', "'a"], 'e27529c0f39f879a',
     [(1, 2, '  cd', 'ab'),
      (1, 3, '  cd', 'ab'),
      (1, 3, '  cd', 'ab'),
      (0, 0, 'ab', 'ab'),
      (1, 2, '  cd', 'ab')]),
    ('1', ['4l', 'ma', '$', '`a'], 'b895c60d83545247',
     [(0, 4, '   one', '   one'),
      (0, 4, '   one', '   one'),
      (0, 5, '   one', '   one'),
      (0, 4, '   one', '   one')]),
    ('mk', ['3G', 'ma', 'gg', "d'a"], '0b7cd2b6cefd22c6',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, '', '')]),
    ('mk', ['ma', '3G', "d'a"], '0b7cd2b6cefd22c6',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (0, 0, '', '')]),
    ('mk', ['2G', 'ma', 'G', "d'a"], '631d6d5910675be3',
     [(1, 2, '  gamma delta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['G', 'ma', 'gg', "d'a"], 'da39a3ee5e6b4b0d',
     [(4, 2, '  last line here', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, '', '')]),
    ('3', ['2G', 'ma', 'G', "d'a"], '111feb192d28ca01',
     [(1, 0, '', '  aaa'),
      (1, 0, '', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (0, 2, '  aaa', '  aaa')]),
    ('mk', ['2G', '5l', 'ma', 'G', '2l', 'd`a'], '36d3de7c625df069',
     [(1, 2, '  gamma delta', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (4, 4, '  last line here', 'alpha beta'),
      (1, 7, '  gammast line here', 'alpha beta')]),
    ('mk', ['ma', '3G', '4l', 'd`a'], 'c5b842108147a002',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 4, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'lon zeta', 'lon zeta')]),
    ('mk', ['4l', 'ma', '$', 'd`a'], 'c05dd0475f87b351',
     [(0, 4, 'alpha beta', 'alpha beta'),
      (0, 4, 'alpha beta', 'alpha beta'),
      (0, 9, 'alpha beta', 'alpha beta'),
      (0, 4, 'alpha', 'alpha')]),
    ('mk', ['3G', '6l', 'ma', 'gg', 'd`a'], '4ebd07fd4c23bc8e',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 6, 'epsilon zeta', 'alpha beta'),
      (2, 6, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'n zeta', 'n zeta')]),
    ('2', ['3l', 'ma', 'j', '$', 'd`a'], '754502609922d336',
     [(0, 1, 'ab', 'ab'),
      (0, 1, 'ab', 'ab'),
      (1, 1, '  cd', 'ab'),
      (1, 3, '  cd', 'ab'),
      (0, 1, 'ad', 'ad')]),
    ('mk', ['ma', '2G', '3l', 'c`aXY\x1b'], 'f299d8db5ea8039f',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (1, 5, '  gamma delta', 'alpha beta'),
      (0, 1, 'XYma delta', 'XYma delta')]),
    ('mk', ['4l', 'ma', '$', 'c`aZ\x1b'], '80b238e879cb9f45',
     [(0, 4, 'alpha beta', 'alpha beta'),
      (0, 4, 'alpha beta', 'alpha beta'),
      (0, 9, 'alpha beta', 'alpha beta'),
      (0, 4, 'alphZa', 'alphZa')]),
    ('2', ['3l', 'ma', 'j', '$', 'c`aQ\x1b'], 'b4222d685f7af3c0',
     [(0, 1, 'ab', 'ab'),
      (0, 1, 'ab', 'ab'),
      (1, 1, '  cd', 'ab'),
      (1, 3, '  cd', 'ab'),
      (0, 1, 'aQd', 'aQd')]),
    ('mk', ['3G', 'ma', 'gg', "y'a", 'G', 'p'], '5d3d6f02f79fd78b',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['ma', '3G', "y'a", 'G', 'p'], '5d3d6f02f79fd78b',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['2G', 'ma', 'G', "y'a", 'gg', 'P'], '6eb055d86e950c73',
     [(1, 2, '  gamma delta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 2, '  gamma delta', '  gamma delta')]),
    ('mk', ['4G', 'ma', '2G', "y'a", 'G', 'p'], '0e8af665f8b55328',
     [(3, 0, '', 'alpha beta'),
      (3, 0, '', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 2, '  gamma delta', 'alpha beta')]),
    ('mk', ['2G', '5l', 'ma', 'G', "y'a"], 'd0c2cb8e681aa18f',
     [(1, 2, '  gamma delta', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta'),
      (1, 7, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta')]),
    ('mk', ['ma', "y'a", 'G', 'p'], '9fadbde1144dc30e',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 0, 'alpha beta', 'alpha beta')]),
    ('3', ['2G', 'ma', 'G', "y'a", 'p'], '57bbf2542cac8e62',
     [(1, 0, '', '  aaa'),
      (1, 0, '', '  aaa'),
      (2, 0, 'bbb', '  aaa'),
      (1, 0, '', '  aaa'),
      (2, 0, '', '  aaa')]),
    ('nl', ['G', 'ma', 'gg', "y'a", 'G', 'p'], '728b796d4a0b3a66',
     [(3, 2, '  cc', '  aa'),
      (3, 2, '  cc', '  aa'),
      (0, 2, '  aa', '  aa'),
      (0, 2, '  aa', '  aa'),
      (3, 2, '  cc', '  aa'),
      (4, 2, '  aa', '  aa')]),
    ('mk', ['yj', 'G', 'p'], '300ea944527e0fca',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['3G', 'yk', 'G', 'p'], '688b237310f1cd7b',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (1, 0, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 2, '  gamma delta', 'alpha beta')]),
    ('mk', ['2G', 'y2j', 'G', 'p'], '0e8af665f8b55328',
     [(1, 2, '  gamma delta', 'alpha beta'),
      (1, 2, '  gamma delta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 2, '  gamma delta', 'alpha beta')]),
    ('mk', ['yG', 'G', 'p'], '5c7000c694b9bf55',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['G', 'yH', 'gg', 'P'], '5c7000c694b9bf55',
     [(4, 2, '  last line here', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta')]),
    ('mk', ['gg', 'yL', 'G', 'p'], '5c7000c694b9bf55',
     [(0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 0, 'alpha beta', 'alpha beta')]),
    ('3', ['3G', 'yk'], 'b3c36571c67a58cf',
     [(2, 0, 'bbb', '  aaa'),
      (1, 0, '', '  aaa')]),
    ('mk', ['3G', 'ma', 'gg', 'yy', "'a"], 'd0c2cb8e681aa18f',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta')]),
    ('mk', ['3G', 'ma', 'gg', 'yG', "'a"], 'd0c2cb8e681aa18f',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta')]),
    ('mk', ['3G', 'ma', 'gg', 'yy', 'G', 'p'], '9fadbde1144dc30e',
     [(2, 0, 'epsilon zeta', 'alpha beta'),
      (2, 0, 'epsilon zeta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (0, 0, 'alpha beta', 'alpha beta'),
      (4, 2, '  last line here', 'alpha beta'),
      (5, 0, 'alpha beta', 'alpha beta')]),]


def marks_like_vim():
    """`m{a-c}`, `` `{a-c} `` and `'{a-c}` land where vim lands them, and leave
    the file byte-exact."""
    import hashlib
    files = marks_files()
    for f, keys, sha, want in VIM_MARKS:
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                e.key(k)
                if '\x1b' in k:
                    # A lone ESC parks GETKEY in GK_POLL waiting for a sequence
                    # continuation that is not coming, and that wait is SILENT.
                    # run_until_quiet's 0.33 s of quiet therefore expires while
                    # the key is still undispatched, so a repaint RPOLL aborted
                    # (because this very ESC was waiting) has not been made good
                    # yet.  Wait for the editor, rather than reading the screen
                    # mid-keystroke and calling the stale text a bug.
                    e.s.run_until_quiet(quiet=1.5, timeout=40)
                r = rows(e); v = e.screen()
                hs = int.from_bytes(bytes(e.s.mem(SYM['HSCROL'], 2)), 'little')
                shown = lambda t: expand(t)[hs:hs + 80].rstrip()
                got = (v.row, v.col + hs, r[v.row], r[0])
                check(f'vim marks {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            ex_settled(e)
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim marks {f} {keys!r}: file as vim wrote it ({got})',
                  got == sha)
        finally:
            e.close()



def marks_cmds():
    """Marks where vim cannot be the reference: this editor DROPS a mark as
    soon as it could no longer point at the same text, where vim shifts it to
    follow (COMMANDS.md).  A dropped mark rings the bell and moves nothing --
    the same answer '.' and 'u' give when they will not run."""
    files = marks_files()

    def refuses(e, keys, tag):
        """*keys* must ring the bell and leave the cursor exactly where it is."""
        v = e.screen(); before = (v.row, v.col)
        n = len(e.cap.getvalue())
        e.key(keys)
        out = e.cap.getvalue()[n:]
        v = e.screen()
        check(f'{tag}: rang the bell', b'\x07' in out.encode('latin-1')
              if isinstance(out, str) else b'\x07' in out)
        check(f'{tag}: the cursor did not move ({v.row},{v.col})',
              (v.row, v.col) == before)

    # ---- a mark that was never set ----
    e = Editor(files['mk'])
    try:
        refuses(e, '`a', 'a mark never set: `a')
        refuses(e, "'b", "a mark never set: 'b")
        refuses(e, "'c", "a mark never set: 'c")
    finally:
        e.close()

    # ---- 'm' followed by something that is not a mark letter ----
    e = Editor(files['mk'])
    try:
        refuses(e, 'mz', "'m' then a key that names no mark")
        refuses(e, 'm1', "'m' then a digit")
        e.key('ma')
        check("'mz' did not arm anything that 'a' could then trip over",
              rows(e)[0] == 'alpha beta')
    finally:
        e.close()

    # ---- an edit ABOVE a mark drops it (vim would shift it) ----
    e = Editor(files['mk'])
    try:
        e.key('3G'); e.key('ma')                 # mark line 3
        e.key('gg'); e.key('x')                  # edit line 1, above it
        check('an edit above a mark: the edit happened',
              rows(e)[0] == 'lpha beta')
        refuses(e, "'a", 'an edit above a mark drops it')
    finally:
        e.close()

    # ---- an edit BELOW a mark leaves it alone ----
    e = Editor(files['mk'])
    try:
        e.key('ma'); e.key('3G'); e.key('x')     # mark line 1, edit line 3
        e.key("'a")
        v = e.screen()
        check(f'an edit below a mark keeps it ({v.row},{v.col})',
              (v.row, v.col) == (0, 0))
    finally:
        e.close()

    # ---- re-setting a mark moves it ----
    e = Editor(files['mk'])
    try:
        e.key('ma'); e.key('3G'); e.key('ma'); e.key('G'); e.key("'a")
        v = e.screen()
        check(f'a second ma moves the mark ({v.row},{v.col})',
              (v.row, v.col) == (2, 0))
    finally:
        e.close()

    # ---- 'm' is not a change: MODF and '.' are untouched ----
    e = Editor(files['mk'])
    try:
        e.key('x')                               # a change, for '.' to repeat
        e.key('ma')
        e.key('j'); e.key('.')
        check("'m' is not a change: '.' still repeats the x",
              rows(e)[1] == ' gamma delta')
    finally:
        e.close()

    # ---- an operator whose mark will not answer must cancel WHOLE ----
    # An empty span is not harmless: a LINEWISE one still takes a line, so a
    # refused mark has to cancel the operator, not just decline to move.
    for setup, keys, tag in (
            (['3G', 'ma', 'gg'], "d'z",  "d'z -- no such mark letter"),
            (['3G', 'ma', 'gg'], 'd`z',  'd`z -- no such mark letter'),
            (['3G', 'mb', 'gg'], "d'a",  "d'a -- that mark was never set"),
            (['3G', 'mb', 'gg'], 'd`a',  'd`a -- that mark was never set')):
        e = Editor(files['mk'])
        try:
            for k in setup:
                e.key(k)
            e.key(keys)
            check(f'{tag}: deletes NOTHING', rows(e)[0] == 'alpha beta')
        finally:
            e.close()

    # ---- "c'a": 'c' drops a linewise motion, but the mark letter must still
    #      be swallowed -- an orphaned 'a' would open an insert and type into
    #      the buffer, which is data loss from a mistyped command ----
    e = Editor(files['mk'])
    try:
        e.key('3G'); e.key('ma'); e.key('gg')
        e.key("c'aXY\x1b")
        e.s.run_until_quiet(quiet=1.5, timeout=40)
        check("c'a is refused and does NOT type its mark letter into the text",
              rows(e)[0] == 'alpha beta')
    finally:
        e.close()

    # ---- ESC instead of a mark letter cancels ----
    e = Editor(files['mk'])
    try:
        e.key('3G'); e.key('ma'); e.key('gg')
        e.key("d'\x1b")
        e.s.run_until_quiet(quiet=1.5, timeout=40)
        check("d' then ESC cancels the operator", rows(e)[0] == 'alpha beta')
    finally:
        e.close()

    # ---- '.' after "d'a" refuses: the delete drops the mark, and the mark
    #      letter is read inside the command so it is never recorded ----
    e = Editor(files['mk'])
    try:
        e.key('3G'); e.key('ma'); e.key('gg')
        e.key("d'a")
        after = rows(e)[:2]
        e.key('.')
        check("'.' after \"d'a\" refuses rather than repeating",
              rows(e)[:2] == after)
    finally:
        e.close()

    # ---- the two spellings differ under an operator, as they do alone ----
    e = Editor(files['mk'])
    try:
        e.key('ma'); e.key('3G'); e.key('4l'); e.key('d`a')
        check('d`a is charwise: the two partial lines JOIN',
              rows(e)[0] == 'lon zeta')
    finally:
        e.close()
    e = Editor(files['mk'])
    try:
        e.key('ma'); e.key('3G'); e.key('4l'); e.key("d'a")
        check("d'a is linewise: whole lines go", rows(e)[0] == '')
    finally:
        e.close()

    # ---- 'y' takes LINEWISE motions only: a charwise one is dropped whole ----
    # There is no charwise register, so 'yw' must neither yank nor -- the trap
    # the old guard existed for -- DELETE the span the operator measured.
    e = Editor(files['mk'])
    try:
        e.key('yy')                              # the register: line 1
        e.key('2G'); e.key('yw')
        check('yw is dropped: it deletes nothing',
              rows(e)[1] == '  gamma delta')
        e.key('G'); e.key('p')
        check('yw is dropped: the register still holds what yy put there',
              rows(e)[5] == 'alpha beta')
    finally:
        e.close()

    # ---- "y`a": charwise, so dropped -- but the mark letter must still be
    #      swallowed, exactly as "c'a" swallows its own (an orphaned 'a' would
    #      open an insert and type into the buffer) ----
    e = Editor(files['mk'])
    try:
        e.key('3G'); e.key('ma'); e.key('gg')
        e.key('y`aXY\x1b')
        e.s.run_until_quiet(quiet=1.5, timeout=40)
        check('y`a is dropped and does NOT type its mark letter into the text',
              rows(e)[0] == 'alpha beta')
    finally:
        e.close()

    # ---- a yank whose mark will not answer cancels WHOLE, like "d'a" ----
    for setup, keys, tag in (
            (['3G', 'ma', 'gg'], "y'z", "y'z -- no such mark letter"),
            (['3G', 'mb', 'gg'], "y'a", "y'a -- that mark was never set")):
        e = Editor(files['mk'])
        try:
            e.key('yy')                          # the register: line 1
            for k in setup:
                e.key(k)
            e.key(keys)
            check(f'{tag}: yanks and deletes NOTHING',
                  rows(e)[0] == 'alpha beta' and rows(e)[2] == 'epsilon zeta')
            e.key('G'); e.key('p')
            check(f'{tag}: the register is untouched', rows(e)[5] == 'alpha beta')
        finally:
            e.close()

    # ---- a yank is not a change: '.' still repeats what came before it ----
    e = Editor(files['mk'])
    try:
        e.key('x')                               # a change, for '.' to repeat
        e.key('ma'); e.key('3G'); e.key("y'a")
        e.key('j'); e.key('.')
        check("y'a is not a change: '.' still repeats the x",
              rows(e)[1] == ' gamma delta')
    finally:
        e.close()

    # ---- the window paging away drops the mark ----
    e = Editor(make(12800))
    try:
        e.key('ma')
        e.key('G')                               # far past the resident window
        refuses(e, "'a", 'the window paged away: the mark is gone')
        e.key('ma')                              # ... and it can be set again here
        e.key('gg')
        refuses(e, "'a", 'paged the other way: still gone')
    finally:
        e.close()



def main():
    args = set(a.lower() for a in sys.argv[1:])
    sizes = [s for s in SIZES if not args or s[0] in args]

    for label, n in sizes:
        print(f'\n=== {label}  ({n} lines, {n*8} bytes) ===', flush=True)
        nav_and_save(label, n)
        if n >= 1:
            edit_deep(label, n)
            hl_x_deep(label, n)
            wide_tabs(label, n)
        insert_bs(label, n)
        ndd(label, n)
        quit_semantics(label, n)
        write_continue(label, n)

    # each of these is separately selectable so a parallel runner can partition
    # the suite exactly -- under 'vim' (or no argument) they all still run
    if not args or 'vim' in args or 'scrolls' in args:
        print('\n=== scrolls vs vim ===', flush=True)
        scrolls_like_vim()
    if not args or 'vim' in args or 'goto' in args:
        print('\n=== G / gg vs vim ===', flush=True)
        goto_like_vim()
    if not args or 'vim' in args or 'jk' in args:
        print('\n=== j / k vs vim ===', flush=True)
        jk_like_vim()
    if not args or 'vim' in args or 'bs' in args:
        print('\n=== insert BS vs vim ===', flush=True)
        bs_like_vim()
    if not args or 'vim' in args or 'ndd' in args:
        print('\n=== Ndd vs vim ===', flush=True)
        ndd_like_vim()
    if not args or 'vim' in args or 'ex' in args:
        print('\n=== ex line vs vim ===', flush=True)
        ex_like_vim()
    if not args or 'vim' in args or 'mot' in args:
        print('\n=== 0 ^ $ <CR> w b W B vs vim ===', flush=True)
        mot_like_vim()
    if not args or 'vim' in args or 'hml' in args:
        print('\n=== H / M / L vs vim ===', flush=True)
        hml_like_vim()
    if not args or 'vim' in args or 'ins' in args:
        print('\n=== a A I r R vs vim ===', flush=True)
        ins_like_vim()
        ins_cmds()
    if not args or 'vim' in args or 'put' in args:
        print('\n=== yy / p / P vs vim ===', flush=True)
        put_like_vim()
    if not args or 'vim' in args or 'srch' in args:
        print('\n=== / ? n N vs vim ===', flush=True)
        srch_like_vim()
        paint_cost()
    if not args or 'vim' in args or 'ops' in args:
        print('\n=== o O J ~ dw cw D  ^L vs vim ===', flush=True)
        ops_like_vim()
        ops_cmds()
    if not args or 'vim' in args or 'dot' in args:
        print('\n=== . (repeat) vs vim ===', flush=True)
        dot_like_vim()
        dot_cmds()
    if not args or 'vim' in args or 'undo' in args:
        print('\n=== u (undo) vs vim ===', flush=True)
        undo_like_vim()
        undo_cmds()
    if not args or 'vim' in args or 'subst' in args:
        print('\n=== :s / :%s / :N,Ms vs vim ===', flush=True)
        subst_like_vim()
        subst_cmds()
    if not args or 'vim' in args or 'marks' in args:
        print('\n=== m / ` / \' (marks) vs vim ===', flush=True)
        marks_like_vim()
        marks_cmds()
    if not args or 'vim' in args or 'ctrlg' in args:
        print('\n=== ^G / the message line vs vim ===', flush=True)
        ctrlg_like_vim()
        ctrlg_cmds()
    if not args or 'vim' in args or 'arg' in args:
        print('\n=== +n / -R on the command line vs vim ===', flush=True)
        plus_like_vim()
        arg_cmds()
    if not args or 'vim' in args or 'file' in args:
        print('\n=== :e vs vim ===', flush=True)
        edit_like_vim()
        print('\n=== :w name  :wq  :x  :e name  no name  ZZ ===', flush=True)
        file_cmds()
        zz_cmds()

    print(f'\n{PASS[0]} passed, {FAIL[0]} failed', flush=True)
    if FAILED:
        print('FAILED:\n  ' + '\n  '.join(FAILED), flush=True)
    sys.exit(1 if FAIL[0] else 0)


if __name__ == '__main__':
    main()
