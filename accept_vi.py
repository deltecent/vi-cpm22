#!/usr/bin/env python3
"""Editor-level acceptance test: the real VI.COM, driven through the simulator.

It stages real files of 0 bytes / one line / ~2 K / ~40 K / 100 K and drives
the REAL VI.COM through the simulator.  A command counts as proven only when it
works here on files far larger than the arena, so 40 K / 100 K force real
paging.

Per size it covers navigation and paging, deep edits, h/l/x at the line edges,
long lines (they wrap) and tabs, :q/:q!, and :w followed by more editing.
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

# What ':ve' must say: read from the source, so a version bump cannot leave the
# check behind (it sat at 'V1.0' through V1.1).
with open(os.path.join(HERE, 'CMD.MAC'), encoding='latin-1') as _f:
    VERSION = re.search(r"^SVER:\s+DB\s+'([^']+)',0", _f.read(), re.M).group(1)


def at_ccp(e, cmd):
    """Send *cmd* to the editor and report whether it returned to the CP/M
    prompt (True) or stayed in the editor (False), by scanning only the
    capture produced by this command."""
    before = len(e.cap.getvalue())
    e.key(cmd)
    return bool(PROMPT.search(e.cap.getvalue()[before:]))

PASS = [0]; FAIL = [0]; FAILED = []


def check(label, cond):
    if HOLD[0] is not None:             # a row held open: see holding()
        HOLD[0].append(bool(cond))
        return
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        FAILED.append(label)
        print(f'  FAIL {label}', flush=True)


# Rows of the vim tables held open against an issue: each is run and must
# still DIFFER from vim -- the day it matches, it comes out.  (Issue #25's
# rows, which waited on the scrolls counting screen rows, are all out.)
WRAP_OPEN = set()
HOLD = [None]


class holding:
    """Run a table row whose checks are known to fail (WRAP_OPEN): they are
    gathered instead of counted, and the row as a whole is one still_open()."""
    def __init__(self, f, keys):
        self.row = (f, tuple(keys))

    def __enter__(self):
        if self.row in WRAP_OPEN:
            HOLD[0] = []

    def __exit__(self, kind, *_):
        got, HOLD[0] = HOLD[0], None
        if got is not None and kind is None:
            still_open(25, f'vim {self.row[0]} {list(self.row[1])!r}', all(got))


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


def curs(e, v):
    """(the cursor's virtual column, the first screen row of its line), both
    0-based.  A line wider than the screen wraps, so the cursor of a long line
    is CURDCL // 80 rows into it, at column CURDCL % 80 -- and vim's
    virtcol('.')-1 is CURDCL itself.  The cell the terminal was sent to must
    agree with that, or the column comes back as -1 and no row matches."""
    dc = int.from_bytes(bytes(e.s.mem(SYM['CURDCL'], 2)), 'little')
    up = dc // 80 - skipped(e)
    if v.col != dc % 80 or v.row < up:
        return -1, v.row
    return dc, v.row - up


def skipped(e):
    """The rows of the top line that are off the top of the screen: a line
    taller than the screen is shown from the row that keeps the cursor on it."""
    return word(e, 'SKIPR') if 'SKIPR' in SYM else 0


def word(e, name):
    """The 16-bit value at the editor's symbol *name*, as it stands now."""
    return int.from_bytes(bytes(e.s.mem(SYM[name], 2)), 'little')


def register_lines(e):
    """How many 8-byte lines the yank register takes.  It shares the arena
    with the text and keeps 0D80H of it free, and the arena is whatever the
    image and its reserves leave -- so a count that must fit is worked out
    here, not written down."""
    return (word(e, 'BUFEND') - word(e, 'BUFBEG') - 0xD80 - 64) // 8


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
    """Type *k*.  After an ESC keep running until the editor is back in
    command mode.  Long text goes in 400-byte bursts."""
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
    """A 200-column line (it wraps) and a tab line, deep in the file: the
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
        e.key('100l'); at('100l onto its second row', WIDE, 100)
        e.key('99l');  at('99l to the end', WIDE, 199)
        e.key('150h'); at('150h back onto its first', WIDE, 49)
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
     ['44 38 10 0', '44 38 10 5', '51 51 0 0', '75 75 0 0', '74 62 20 0', '38 25 21 0']),
    ('wide', ['G', '2\x02', 'j', '$', '\x06'],
     ['1500 1488 20 0', '1475 1462 21 0', '1476 1464 20 0', '1476 1464 22 199', '1476 1476 0 0']),
    ('wide', ['G', '\x06', '\x02', '2\x06'],
     ['1500 1488 20 0', '1500 1500 0 0', '1499 1486 21 0', '1500 1500 0 0']),
    ('wide', ['G', '400\x02', '100\x06'],
     ['1500 1488 20 0', '14 1 21 0', '1261 1261 0 0']),
    ('wide', ['45G', '$', 'j', '\x02', '\x06'],
     ['45 39 10 0', '45 39 12 199', '46 39 13 5', '38 26 20 0', '39 39 0 0']),
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
     ['45 39 10 0', '45 39 12 199', '51 45 10 0', '52 45 13 0', '45 38 11 0', '44 38 10 0']),
    ('wide', ['44G', '$', '\x04', '\x15'],
     ['44 38 10 0', '44 38 10 5', '51 45 10 0', '44 38 10 0']),
    ('wide', ['G', '$', '7\x15', '\x04'],
     ['1500 1488 20 0', '1500 1488 22 199', '1497 1485 20 0', '1500 1488 20 0']),
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
            with holding(f, keys):
                for k, w in zip(keys, want):
                    e.key(k)
                    r = rows(e); v = e.screen()
                    dc, lr = curs(e, v)
                    num = lambda t: int(re.match(r' *(\d+)', t).group(1))
                    got = '%d %d %d %d' % (num(r[lr]), num(r[0]), v.row, dc)
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
    (['700G', '712G', '714G'], ['700 694 10', '712 700 20', '714 702 20']),
    (['700G', '725G'], ['700 694 10', '725 718 11']),
    (['700G', '680G', '679G'], ['700 694 10', '680 674 10', '679 674 9']),
    (['G', '\x06', '1490G', 'gg'], ['1500 1488 20', '1500 1500 0', '1490 1484 10', '1 1 0']),
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
            with holding(n, keys):
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
     [(10, 0, '000700', '000694'),
      (9, 199, '000699' + 'x' * 194 + '000700', '000694'),
      (10, 5, '000701', '000694'),
      (9, 205, '000699' + 'x' * 194 + '0007001', '000694')]),
    ('wide', ['700G', '11k', 'i\x08\x1b', 'i\x08\x08\x1b'], 'db21bbac1db90021',
     [(10, 0, '000700', '000694'),
      (0, 0, '000689', '000689'),
      (0, 5, '000688000689', '000688000689'),
      (0, 2, '0008000689', '0008000689')]),
    ('wide', ['700G', '11j', 'i\x7f\x1b', 'k', '99li\x08\x08\x1b'], '872032e2965474d7',
     [(10, 0, '000700', '000694'),
      (20, 0, '000711' + 'x' * 194, '000699xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (19, 5, '000710000711' + 'x' * 194, '000699xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (18, 5, '000709', '000699xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (18, 2, '0009', '000699xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('wide', ['G', 'i' + BS * 30 + '\x1b', 'gg', 'i\x08\x1b', 'lli' + BS * 5 + '\x1b'], 'c94249eb694509c5',
     [(20, 0, '001500' + 'x' * 194, '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (17, 184, '001497' + 'x' * 179 + '001500' + 'x' * 194, '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (0, 0, '000001', '000001'),
      (0, 0, '000001', '000001'),
      (0, 0, '0001', '0001')]),
    ('wide', ['701G', 'iAB' + BS * 4 + 'CD\x1b'], 'd3521979119502b8',
     [(10, 0, '000701', '000695'),
      (9, 6, '00070CD000701', '000695')]),
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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
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
     [(10, 0, '000700', '000694'),
      (10, 0, '000705' + 'x' * 194, '000694'),
      (13, 0, '000706', '000694')]),
    ('wide', ['699G', '3dd', 'k'], '2d65840179e6b988',
     [(10, 0, '000699' + 'x' * 194, '000693xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (10, 0, '000702' + 'x' * 194, '000693xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (9, 0, '000698', '000693xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('wide', ['700G', '11k', '30dd', 'j'], 'ff540c16a65cf8ae',
     [(10, 0, '000700', '000694'),
      (0, 0, '000689', '000689'),
      (0, 0, '000719', '000719'),
      (1, 0, '000720' + 'x' * 194, '000719')]),
    ('wide', ['700G', '11j', '4dd', 'k'], '7f16f46771a29af4',
     [(10, 0, '000700', '000694'),
      (20, 0, '000711' + 'x' * 194, '000699xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (20, 0, '000715', '000699xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (19, 0, '000710', '000699xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('wide', ['702G', '$', 'dd', 'k'], '4a8ed95d310e9a8c',
     [(10, 0, '000702' + 'x' * 194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (12, 199, '000702' + 'x' * 194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (10, 0, '000703', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (9, 0, '000701', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('wide', ['700G', '$', 'k', '3dd', 'j'], '2d65840179e6b988',
     [(10, 0, '000700', '000694'),
      (10, 5, '000700', '000694'),
      (9, 199, '000699' + 'x' * 194, '000694'),
      (7, 0, '000702' + 'x' * 194, '000694'),
      (10, 0, '000703', '000694')]),
    ('wide', ['G', '3dd', '9dd'], 'cf4987bfafeec1cc',
     [(20, 0, '001500' + 'x' * 194, '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (20, 0, '001500' + 'x' * 194, '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (20, 0, '001500' + 'x' * 194, '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
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
    (5120, ['2000G', '2000dd', 'j'], '997f1c02825424b7',
     [(11, 0, '002000', '001989'),
      (11, 0, '004000', '001989'),
      (12, 0, '004001', '001989')]),
    (5120, ['G', '3000k', '2000dd', 'k'], 'a7bd56567c097a82',
     [(22, 0, '005120', '005098'),
      (11, 0, '002120', '002109'),
      (11, 0, '004120', '002109'),
      (10, 0, '002119', '002109')]),
    (5120, ['gg', '5dd', 'G', '5dd'], '8941293b4a3a2c29',
     [(0, 0, '000001', '000001'),
      (0, 0, '000006', '000006'),
      (22, 0, '005120', '005098'),
      (22, 0, '005120', '005098')]),
    (12800, ['10000G', '2000dd', 'j'], '6edd513d8ef60796',
     [(11, 0, '010000', '009989'),
      (11, 0, '012000', '009989'),
      (12, 0, '012001', '009989')]),
    (12800, ['G', '3000k', '2000dd', 'k'], '9ae7eba6280bd003',
     [(22, 0, '012800', '012778'),
      (11, 0, '009800', '009789'),
      (11, 0, '011800', '009789'),
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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
                check(f'vim Ndd {f} {keys!r} {k!r}: {got} == {(wrow, wcol)} {wcur[:12]!r} {wtop[:12]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim Ndd {f} {keys!r}: file as vim wrote it ({got})', got == sha)
        finally:
            e.close()


# The ':' line as vim's: the bottom row shows ':' and each char typed, BS and
# DEL erase the last one, and BS/DEL on an empty line or ESC cancels it (vim
# 9.1 blanks the row on all three, prompt char included -- measured -- and so
# does this).  (setup keys, file).
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
                check(f'ex {f} {tag}: the cancelled line is gone from the row '
                      f'({scr[23].rstrip()!r}), as vim blanks it too',
                      scr[23].strip() == '')
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
      '4 1 3 41', '4 1 3 47', '4 1 3 53', '4 1 3 59', '4 1 3 65', '4 1 3 71', '4 1 3 77', '4 1 4 83']),
    ('wd', ['G'] + ['b'] * 14,
     ['3300 3282 22 0', '3299 3282 21 13', '3299 3282 21 10', '3299 3282 21 8', '3299 3282 21 2',
      '3298 3282 20 0', '3297 3282 19 0', '3296 3282 18 32', '3296 3282 18 24', '3296 3282 18 16',
      '3295 3282 17 8', '3295 3282 17 0', '3294 3282 16 200', '3294 3282 16 199', '3294 3282 16 197']),
    ('wd', ['G'] + ['B'] * 10,
     ['3300 3282 22 0', '3299 3282 21 13', '3299 3282 21 10', '3299 3282 21 8', '3299 3282 21 2',
      '3298 3282 20 0', '3297 3282 19 0', '3296 3282 18 32', '3296 3282 18 24', '3296 3282 18 16',
      '3295 3282 17 0']),
    ('wd', ['G', '$', 'w', 'w', 'b'],
     ['3300 3282 22 0', '3300 3282 22 23', '3300 3282 22 23', '3300 3282 22 23', '3300 3282 22 19']),
    ('wd', ['G', 'k', 'w', 'w', 'w', 'w', 'w', 'w'],
     ['3300 3282 22 0', '3299 3282 21 0', '3299 3282 21 2', '3299 3282 21 8', '3299 3282 21 10',
      '3299 3282 21 13', '3300 3282 22 0', '3300 3282 22 6']),
    ('wd', ['b', 'B', 'w', 'b', 'b'], ['1 1 0 0', '1 1 0 0', '2 1 1 10', '1 1 0 0', '1 1 0 0']),
    ('wd', ['500w', '500b'], ['41 32 11 0', '1 1 0 0']),
    ('wd', ['2000w', '3000W', '300B', '2000b'],
     ['161 152 11 0', '774 765 9 53', '714 705 9 17', '554 545 9 17']),
    ('wd', ['99999w', 'b', '99999B'], ['3300 3282 22 23', '3300 3282 22 19', '1 1 0 0']),
    ('wd', ['G', '99999b', 'w'], ['3300 3282 22 0', '1 1 0 0', '2 1 1 10']),
    ('wd', ['1500G', '400W', '800B', '7w'],
     ['1500 1491 11 0', '1584 1575 9 17', '1416 1407 11 24', '1419 1407 14 13']),
    ('wd', ['1203G', 'b', 'b', 'w', 'w'],
     ['1203 1194 11 2', '1202 1194 10 22', '1202 1194 10 20', '1202 1194 10 22', '1204 1194 12 0']),
    ('wd', ['5j', '0', '^', '$', '0', '$', 'j', 'k'],
     ['6 1 7 7', '6 1 7 7', '6 1 7 16', '6 1 7 34', '6 1 7 7', '6 1 7 34', '7 1 8 0', '6 1 7 34']),
    ('wd', ['3j', '^', '$', '0', '^', 'j'],
     ['4 1 3 0', '4 1 3 0', '4 1 5 201', '4 1 3 0', '4 1 3 0', '5 1 6 0']),
    ('wd', ['2j', '$', '^', '0', 'w', 'b', 'j'],
     ['3 1 2 0', '3 1 2 2', '3 1 2 2', '3 1 2 0', '4 1 3 0', '2 1 1 22', '3 1 2 2']),
    ('wd', ['4j', '$', '0', '$', 'w', 'b', 'B', 'b'],
     ['5 1 6 0', '5 1 6 8', '5 1 6 0', '5 1 6 8', '6 1 7 16', '5 1 6 8', '5 1 6 0', '4 1 5 200']),
    ('wd', ['4j', '$', 'j', 'k', '0', '12w', '^'],
     ['5 1 6 0', '5 1 6 8', '6 1 7 34', '5 1 6 8', '5 1 6 0', '10 1 11 6', '10 1 11 0']),
    ('wd', ['3$', '5$', '$', '100$', 'k'],
     ['3 1 2 2', '7 1 8 0', '7 1 8 0', '106 97 11 34', '105 97 10 8']),
    ('wd', ['G', '2$', 'k', 'j'],
     ['3300 3282 22 0', '3300 3282 22 0', '3299 3282 21 13', '3300 3282 22 23']),
    ('wd', ['G', 'k', '5$', 'k'],
     ['3300 3282 22 0', '3299 3282 21 0', '3300 3282 22 23', '3299 3282 21 13']),
    ('wd', ['1650G', '^', '$', '0', '3w'],
     ['1650 1641 11 0', '1650 1641 11 0', '1650 1641 11 23', '1650 1641 11 0', '1650 1641 11 10']),
    ('wd', ['1655G', '$', '0', '9$', '^'],
     ['1655 1646 11 0', '1655 1646 11 8', '1655 1646 11 0', '1663 1646 19 2', '1663 1646 19 2']),
    ('wd', ['2j', '4l', '0', 'j', '^', 'k'],
     ['3 1 2 0', '3 1 2 2', '3 1 2 0', '4 1 3 0', '4 1 3 0', '3 1 2 0']),
    ('wd', ['\r', '\r', '5\r', '30\r', '500\r', '\r', 'k'],
     ['2 1 1 10', '3 1 2 2', '8 1 9 0', '38 29 11 0', '538 529 11 0', '539 529 12 2', '538 529 11 0']),
    ('wd', ['G', '\r', '0', '\r'],
     ['3300 3282 22 0', '3300 3282 22 0', '3300 3282 22 0', '3300 3282 22 0']),
    ('wd', ['3295G', 'l', 'l', '\r', '99\r'],
     ['3295 3282 17 0', '3295 3282 17 1', '3295 3282 17 2', '3296 3282 18 16', '3300 3282 22 0']),
    ('wd', ['2j', '$', '\r', 'j', '\r'],
     ['3 1 2 0', '3 1 2 2', '4 1 3 0', '5 1 6 0', '6 1 7 16']),
    ('wd', ['4j', '$', '\r', '2\r', '3\r'],
     ['5 1 6 0', '5 1 6 8', '6 1 7 16', '8 1 9 0', '11 1 12 0']),
    ('wd', ['1500G', '23\r', '24\r', '12\r', '13\r'],
     ['1500 1491 11 0', '1523 1514 11 2', '1547 1538 11 0', '1559 1541 22 2', '1572 1563 11 10']),
    ('wd', ['3000G', '9999\r', 'gg', '3000\r'],
     ['3000 2991 11 0', '3300 3282 22 0', '1 1 0 0', '3001 2992 11 0']),
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
            with holding(f, keys):
                for k, w in zip(keys, want):
                    e.key(k)
                    v = e.screen()
                    dc, lr = curs(e, v)
                    scr = [''.join(r).rstrip() for r in v.screen]
                    show = lambda n: expand(lines[n - 1])[:80].rstrip()
                    ln, top, row, col = map(int, w.split())
                    got = '%d %d' % (v.row, dc)
                    check(f'vim {f} {keys!r} {k!r}: {got} == {row} {col}', got == '%d %d' % (row, col))
                    check(f'vim {f} {keys!r} {k!r}: rows show lines {top} and {ln}',
                          scr[0] == show(top) and scr[lr] == show(ln))
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
     ['5 1 6 0', '5 1 6 5', '5 1 6 0', '600 594 10 0', '600 594 12 199', '600 594 10 0',
      '1500 1488 20 0', '1500 1488 20 0', '1495 1488 13 0', '1495 1488 13 0']),
    ('ind', ['G', ':e\r', '3001G', 'l', ':e\r', '2G', ':e\r', '6000G', 'k', 'k', ':e\r'],
     ['6000 5978 22 10', '6000 5978 22 10', '3001 2990 11 4', '3001 2990 11 5', '3001 2990 11 4',
      '2 1 1 10', '2 1 1 10', '6000 5978 22 10', '5999 5978 21 9', '5998 5978 20 10',
      '5998 5978 20 10']),
    ('wd', ['1500G', '5w', ':e\r', '1505G', '$', ':e\r', '3299G', ':e\r'],
     ['1500 1491 11 0', '1500 1491 11 14', '1500 1491 11 0', '1505 1491 18 0', '1505 1491 18 8',
      '1505 1496 11 0', '3299 3282 21 2', '3299 3282 21 2']),
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
                dc, lr = curs(e, v)
                scr = [''.join(r).rstrip() for r in v.screen]
                show = lambda n: expand(lines[n - 1])[:80].rstrip()
                ln, top, row, col = map(int, w.split())
                got = '%d %d' % (v.row, dc)
                check(f'edit {f} {keys!r} {k!r}: {got} == {row} {col}', got == '%d %d' % (row, col))
                check(f'edit {f} {keys!r} {k!r}: rows show lines {top} and {ln}',
                      scr[0] == show(top) and scr[lr] == show(ln))
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
     ['700 694 10 0', '700 694 10 5', '694 694 0 0', '700 694 10 0', '707 694 21 0']),
    ('wide', ['700G', '$', '5L', '$', '5H'],
     ['700 694 10 0', '700 694 10 5', '703 694 15 0', '703 694 15 5', '698 694 6 0']),
    ('wide', ['G', 'H', 'M', 'L', '30H'],
     ['1500 1488 20 0', '1488 1488 0 0', '1494 1488 10 0', '1500 1488 20 0', '1500 1488 20 0']),
    ('wide', ['G', '$', 'H', 'M', 'L', '\x02', 'M'],
     ['1500 1488 20 0', '1500 1488 22 199', '1488 1488 0 0', '1494 1488 10 0', '1500 1488 20 0',
      '1487 1475 20 0', '1481 1475 10 0']),
    ('ind', ['3000G', 'H', 'M', 'L', '2H', '2L'],
     ['3000 2989 11 10', '2989 2989 0 4', '3000 2989 11 10', '3011 2989 22 4', '2990 2989 1 10',
      '3010 2989 21 10']),
    ('ind', ['G', 'M', 'H', '40L'],
     ['6000 5978 22 10', '5989 5978 11 4', '5978 5978 0 10', '5978 5978 0 10']),
    ('ind', ['3000G', 'L', 'j', 'H', 'k', 'M'],
     ['3000 2989 11 10', '3011 2989 22 4', '3012 2990 22 7', '2990 2990 0 10', '2989 2989 0 9',
      '3000 2989 11 10']),
    ('wd', ['1500G', 'H', 'M', 'L', '4H', '7L'],
     ['1500 1491 11 0', '1491 1491 0 0', '1500 1491 11 0', '1509 1491 22 2', '1494 1491 3 0',
      '1503 1491 14 2']),
    ('wd', ['G', 'H', 'M', 'L'],
     ['3300 3282 22 0', '3282 3282 0 10', '3291 3282 11 0', '3300 3282 22 0']),
    ('wd', ['1500G', '4H', 'j', 'j', 'k'],
     ['1500 1491 11 0', '1494 1491 3 0', '1495 1491 6 0', '1496 1491 7 7', '1495 1491 6 0']),
    ('wd', ['1500G', 'L', 'k', 'H', 'j'],
     ['1500 1491 11 0', '1509 1491 22 2', '1508 1491 21 0', '1491 1491 0 0', '1492 1491 1 7']),
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
            with holding(f, keys):
                for k, w in zip(keys, want):
                    e.key(k)
                    if k == 'dd':
                        del lines[int(w.split()[0])]
                    v = e.screen()
                    dc, lr = curs(e, v)
                    scr = [''.join(r).rstrip() for r in v.screen]
                    show = lambda n: expand(lines[n - 1])[:80].rstrip()
                    ln, top, row, col = map(int, w.split())
                    got = '%d %d' % (v.row, dc)
                    check(f'hml {f} {keys!r} {k!r}: {got} == {row} {col}', got == '%d %d' % (row, col))
                    check(f'hml {f} {keys!r} {k!r}: rows show lines {top} and {ln}',
                          scr[0] == show(top) and scr[lr] == show(ln))
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
     [(10, 0, '000700', '000694'),
      (10, 7, '000700QR', '000694')]),
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
     [(10, 0, '000700', '000694'),
      (10, 6, '000700Q', '000694')]),
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
     [(10, 0, '000700', '000694'),
      (10, 0, 'Q000700', '000694')]),
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
     [(10, 0, '000700', '000694'),
      (10, 5, '00070Q', '000694')]),
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
     [(10, 0, '000700', '000694'),
      (10, 5, '00070Q', '000694')]),
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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
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
            # (BS puts the originals back only while the typing has not made
            # the engine move the text out of its way -- CMD.MAC, REPLACE MODE
            # -- and how much it takes before that is whatever the arena has
            # free above the text here, so the run is cut to fit it)
            n = min(n, word(e, 'BUFEND') - word(e, 'TXTEND') - 64)
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
     [(10, 0, '000702' + 'x'*194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (12, 199, '000702' + 'x'*194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (13, 0, 'Q', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
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
     [(10, 0, '000702' + 'x'*194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (12, 200, '000702' + 'x'*194 + ' 000703', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('ind', ['3000G', 'J'], '58e2eef2f18a88f1',
     [(11, 10, '\t  003000', '    002989'),
      (11, 16, '\t  003000 003001', '    002989')]),
    ('wd', ['1500G', 'J', 'J'], '4e45768e95d4e83d',
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 23, '01500 foo.bar(baz) qux_1', ''),
      (11, 24, '01500 foo.bar(baz) qux_1 01502  x,y;;z  ', '')]),
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
     [(10, 0, '000702' + 'x'*194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (12, 199, '000702' + 'x'*194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (12, 199, '000702' + 'x'*193 + 'X', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('wd', ['1500G', '~', '~', '~'], '5c9f0580f938e2cb',
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 1, '01500 foo.bar(baz) qux_1', ''),
      (11, 2, '01500 foo.bar(baz) qux_1', ''),
      (11, 3, '01500 foo.bar(baz) qux_1', '')]),
    # ---- dw ----
    ('wd', ['1500G', 'dw', 'dw', 'dw'], 'c5d2a717a290dc3c',
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 0, 'foo.bar(baz) qux_1', ''),
      (11, 0, '.bar(baz) qux_1', ''),
      (11, 0, 'bar(baz) qux_1', '')]),
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
     [(10, 0, '000702' + 'x'*194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (10, 0, '', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('ind', ['3000G', 'dw'], 'bb0b522d3e0d95ef',
     [(11, 10, '\t  003000', '    002989'),
      (11, 9, '\t  ', '    002989')]),
    ('nl', ['G', 'dw'], 'e675420fb041e82b',
     [(3, 2, '  cc', '  aa'),
      (3, 1, '  ', '  aa')]),
    # ---- cw (vi's one special case: it changes to the word's end, like ce) ----
    ('wd', ['1500G', 'cwQQ\x1b'], '47b04577d05834c0',
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 1, 'QQ foo.bar(baz) qux_1', '')]),
    ('wd', ['1500G', 'w', 'cwZ\x1b'], '122462b1f502c37b',
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 6, '01500 foo.bar(baz) qux_1', ''),
      (11, 6, '01500 Z.bar(baz) qux_1', '')]),
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
     [(10, 0, '000702' + 'x'*194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (10, 0, 'Q', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
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
     [(10, 0, '000702' + 'x'*194, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (11, 99, '000702' + 'x'*94, '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('ind', ['3000G', 'D'], 'bb0b522d3e0d95ef',
     [(11, 10, '\t  003000', '    002989'),
      (11, 9, '\t  ', '    002989')]),
    ('wd', ['1500G', 'wD'], '86100573bd1e1f12',
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 5, '01500 ', '')]),
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
     [(10, 0, '000702xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (11, 100, '000702xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxX', '000696xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('ind', ['3000G', 'CX\x1b'], '2a20569df400bde3',
     [(11, 10, '\t  003000', '    002989'),
      (11, 10, '\t  X', '    002989')]),
    ('wd', ['1500G', 'wCX\x1b'], '1055620c9c3dec9a',
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 6, '01500 X', '')]),
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
      (20, 0, '001500xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (20, 0, '000001', '001489')]),
    ('wide', ['dd', 'G', 'p'], '8401b3e0a7c773ca',
     [(0, 0, '000002', '000002'),
      (20, 0, '001500xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (20, 0, '000001', '001489')]),
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
    # A yank on a PAGED file, which is where BOTH ways of taking one run.  The
    # copy that leaves the lines where they are (CMD.MAC's YNCOPY) needs the
    # span free in the arena and its count's lines inside the resident window;
    # where either fails they are taken out with dd's engine and put straight
    # back, the way every yank used to work.  Measured here at line 2500 of the
    # 40 K file, where the window leaves 7394 bytes free: 'yy' is copied and so
    # is '60yy' (480 bytes -- two chunks of the copy loop, so the source is
    # re-derived mid-copy), while '500yy' runs off the end of the resident text
    # and only the pager can say where its lines are, so it goes the old way.
    # 'G 2yy' is the count vim refuses on the last line, and at the end of a
    # paged file the text alone cannot say that this IS the last line -- the
    # input file is not known to be finished -- so that goes the old way too
    # and must still refuse, register untouched.  Same lines, same file, all
    # four ways.
    ('5120', ['2500G', 'yy', 'p'], '3e2806c1b9b1f3d6',
     [(11, 0, '002500', '002489'),
      (11, 0, '002500', '002489'),
      (12, 0, '002500', '002489')]),
    ('5120', ['2500G', '60yy', 'G', 'p'], 'f2387aaa0a5b29fc',
     [(11, 0, '002500', '002489'),
      (11, 0, '002500', '002489'),
      (22, 0, '005120', '005098'),
      (22, 0, '002500', '005099')]),
    ('5120', ['2500G', '500yy', 'G', 'p'], '11ff29f22fae3dfb',
     [(11, 0, '002500', '002489'),
      (11, 0, '002500', '002489'),
      (22, 0, '005120', '005098'),
      (22, 0, '002500', '005099')]),
    ('5120', ['G', '2yy', 'p'], 'c4c3ab9e6a003a32',
     [(22, 0, '005120', '005098'),
      (22, 0, '005120', '005098'),
      (22, 0, '005120', '005098')]),
    ('wide', ['700G', '3yy', 'p'], 'ea6a40360e421c1b',
     [(10, 0, '000700', '000694'),
      (10, 0, '000700', '000694'),
      (11, 0, '000700', '000694')]),
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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
                check(f'vim ops {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim ops {f} {keys!r}: file as vim wrote it ({got})', got == sha)
        finally:
            e.close()


# ---------------------------------------------------------------------------
# VIM_OPMX -- every operator over every motion it takes (issue #3).
#
# The operators were tested through 'dw', 'cw', 'dd' and the jumps, and ten of
# the eighteen charwise motions had never met one in any test ('d$', 'db',
# 'de', 'd0' ...; TESTMAP.md has the table).  This is the matrix, from vim:
# opmx_keys() is every (motion, place) pair, and each row runs the operators
# that take the motion --
#     charwise:  d{m}  u  c{m}77<Esc>  u  .
#     linewise:  y{m}  P  u  d{m}  u  .  p
# -- so the row also proves the undo, the repeat and the register after each.
# Every 'u' is typed with the keys that go back to the place.
# The inserted text is digits so that a 'c' vim refuses leaves them as a count
# the <Esc> then drops, not as commands.  The places are the middle of a line
# of words, the first character of the file, the last, an empty line and the
# end of a blank-only line; the counted rows put the count on the motion and
# then on the operator.
#
# The table is recorded (`python3 vimref.py --print opmx`); opmx_like_vim()
# refuses to run if its keys are not exactly opmx_keys().
OPMX_PLACES = [['4G', '7l'], ['gg', '0'], ['G', '$'], ['3G'], ['5G', '$']]
OPMX_MARKS = ['2G', '6l', 'ma', '7G', '9l', 'mb']
# (the motion's keys, the same with a count or None, linewise, needs marks,
#  the places it is run from beyond the first three)
OPMX_MOTIONS = [
    ('w', '2w', 0, 0, (3, 4)), ('W', '2W', 0, 0, (3, 4)),
    ('b', '2b', 0, 0, (3, 4)), ('B', '2B', 0, 0, (3, 4)),
    ('h', '2h', 0, 0, (3,)), ('l', '2l', 0, 0, (3,)),
    ('0', None, 0, 0, (3, 4)), ('^', None, 0, 0, (3, 4)),
    ('`a', None, 0, 1, ()), ('`b', None, 0, 1, ()),
    ('fa', '2fa', 0, 0, ()), ('ta', '2ta', 0, 0, ()),
    ('Fa', '2Fa', 0, 0, ()), ('Ta', '2Ta', 0, 0, ()),
    (';', '2;', 0, 0, ()), (',', '2,', 0, 0, ()),
    ('e', '2e', 0, 0, (3, 4)), ('E', '2E', 0, 0, (3, 4)),
    ('$', '2$', 0, 0, (3, 4)),
    ('j', '2j', 1, 0, (3,)), ('k', '2k', 1, 0, (3,)),
    ('G', '6G', 1, 0, ()), ('H', '2H', 1, 0, ()), ('M', None, 1, 0, ()),
    ('L', '2L', 1, 0, ()), ('gg', '2gg', 1, 0, ()),
    ("'a", None, 1, 1, ()), ("'b", None, 1, 1, ()),
]


def opmx_files():
    return {'ox': b'one two.three four five\r\n  ind (par) x,y; end\r\n\r\n'
                  b'a1 a2 a3 a4 a5 a6 a7\r\n    \r\n\ttab sep\tword\r\n'
                  b'seven: z z z z stop\r\nlast\r\n'}


def opmx_keys():
    """The key rows of the matrix, in the table's order.  Getting to the place
    is one step (it is not what is being tested), and every 'u' goes back to
    it in the same step, so that each operator starts from the same character
    whatever the undo did with the cursor."""
    out = []
    for m, counted, line, marks, more in OPMX_MOTIONS:
        pre = ''.join(OPMX_MARKS) if marks else ''
        find = 'fa' if m in (';', ',') else ''        # the find they repeat
        for p in (0, 1, 2) + tuple(more):
            at = ''.join(OPMX_PLACES[p]) + find
            if line:
                out.append([pre + at, 'y' + m, 'P', 'u' + at, 'd' + m,
                            'u' + at, '.', 'p'])
            else:
                out.append([pre + at, 'd' + m, 'u' + at, 'c' + m + '77\x1b',
                            'u' + at, '.'])
        if counted:
            at = ''.join(OPMX_PLACES[0]) + find
            last = 'y' + counted if line else 'c' + counted + '77\x1b'
            out.append([at, 'd' + counted, 'u' + at, '2d' + m, 'u' + at, '.',
                        'u' + at, last])
    return out


VIM_OPMX = [
    ('ox', ['4G7l', 'dw', 'u4G7l', 'cw77\x1b', 'u4G7l', '.'], '81407ff599d9be3d',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dw', 'ugg0', 'cw77\x1b', 'ugg0', '.'], '78d5cec920286bba',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'two.three four five', 'two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77 two.three four five', '77 two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77 two.three four five', '77 two.three four five')]),
    ('ox', ['G$', 'dw', 'uG$', 'cw77\x1b', 'uG$', '.'], '65ffc03561305911',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five')]),
    ('ox', ['3G', 'dw', 'u3G', 'cw77\x1b', 'u3G', '.'], 'f461a91dc96dfc60',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five')]),
    ('ox', ['5G$', 'dw', 'u5G$', 'cw77\x1b', 'u5G$', '.'], '6ae9c46b25b7bad3',
     [(4, 3, '    ', 'one two.three four five'),
      (4, 2, '   ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2w', 'u4G7l', '2dw', 'u4G7l', '.', 'u4G7l', 'c2w77\x1b'], '60c80ca4ca65dd12',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dW', 'u4G7l', 'cW77\x1b', 'u4G7l', '.'], '81407ff599d9be3d',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dW', 'ugg0', 'cW77\x1b', 'ugg0', '.'], '78d5cec920286bba',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'two.three four five', 'two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77 two.three four five', '77 two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77 two.three four five', '77 two.three four five')]),
    ('ox', ['G$', 'dW', 'uG$', 'cW77\x1b', 'uG$', '.'], '65ffc03561305911',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five')]),
    ('ox', ['3G', 'dW', 'u3G', 'cW77\x1b', 'u3G', '.'], 'f461a91dc96dfc60',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five')]),
    ('ox', ['5G$', 'dW', 'u5G$', 'cW77\x1b', 'u5G$', '.'], '6ae9c46b25b7bad3',
     [(4, 3, '    ', 'one two.three four five'),
      (4, 2, '   ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2W', 'u4G7l', '2dW', 'u4G7l', '.', 'u4G7l', 'c2W77\x1b'], '60c80ca4ca65dd12',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'db', 'u4G7l', 'cb77\x1b', 'u4G7l', '.'], '68fdb3430edad2ae',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 773 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'db', 'ugg0', 'cb77\x1b', 'ugg0', '.'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'db', 'uG$', 'cb77\x1b', 'uG$', '.'], '2d73a4bc04209ed9',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 1, '77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 1, '77t', 'one two.three four five')]),
    ('ox', ['3G', 'db', 'u3G', 'cb77\x1b', 'u3G', '.'], '417a6698ce99f513',
     [(2, 0, '', 'one two.three four five'),
      (1, 16, '  ind (par) x,y; ', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (1, 18, '  ind (par) x,y; 77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (1, 18, '  ind (par) x,y; 77', 'one two.three four five')]),
    ('ox', ['5G$', 'db', 'u5G$', 'cb77\x1b', 'u5G$', '.'], '60d60b2edf14ec01',
     [(4, 3, '    ', 'one two.three four five'),
      (3, 18, 'a1 a2 a3 a4 a5 a6  ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (3, 19, 'a1 a2 a3 a4 a5 a6 77 ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (3, 19, 'a1 a2 a3 a4 a5 a6 77 ', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2b', 'u4G7l', '2db', 'u4G7l', '.', 'u4G7l', 'c2b77\x1b'], '3f94a89a98fb94aa',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dB', 'u4G7l', 'cB77\x1b', 'u4G7l', '.'], '68fdb3430edad2ae',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 773 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dB', 'ugg0', 'cB77\x1b', 'ugg0', '.'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'dB', 'uG$', 'cB77\x1b', 'uG$', '.'], '2d73a4bc04209ed9',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 1, '77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 1, '77t', 'one two.three four five')]),
    ('ox', ['3G', 'dB', 'u3G', 'cB77\x1b', 'u3G', '.'], '417a6698ce99f513',
     [(2, 0, '', 'one two.three four five'),
      (1, 16, '  ind (par) x,y; ', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (1, 18, '  ind (par) x,y; 77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (1, 18, '  ind (par) x,y; 77', 'one two.three four five')]),
    ('ox', ['5G$', 'dB', 'u5G$', 'cB77\x1b', 'u5G$', '.'], '60d60b2edf14ec01',
     [(4, 3, '    ', 'one two.three four five'),
      (3, 18, 'a1 a2 a3 a4 a5 a6  ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (3, 19, 'a1 a2 a3 a4 a5 a6 77 ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (3, 19, 'a1 a2 a3 a4 a5 a6 77 ', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2B', 'u4G7l', '2dB', 'u4G7l', '.', 'u4G7l', 'c2B77\x1b'], '3f94a89a98fb94aa',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dh', 'u4G7l', 'ch77\x1b', 'u4G7l', '.'], '68fdb3430edad2ae',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 773 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dh', 'ugg0', 'ch77\x1b', 'ugg0', '.'], 'd58f6701e22750b1',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77one two.three four five', '77one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77one two.three four five', '77one two.three four five')]),
    ('ox', ['G$', 'dh', 'uG$', 'ch77\x1b', 'uG$', '.'], 'd2c9dba012594809',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'lat', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'la77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'la77t', 'one two.three four five')]),
    ('ox', ['3G', 'dh', 'u3G', 'ch77\x1b', 'u3G', '.'], 'f461a91dc96dfc60',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2h', 'u4G7l', '2dh', 'u4G7l', '.', 'u4G7l', 'c2h77\x1b'], '67fa09b7a2b05afc',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 5, 'a1 a23 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 5, 'a1 a23 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 5, 'a1 a23 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dl', 'u4G7l', 'cl77\x1b', 'u4G7l', '.'], '81407ff599d9be3d',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dl', 'ugg0', 'cl77\x1b', 'ugg0', '.'], 'c95d70bb0a61e62e',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'ne two.three four five', 'ne two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77ne two.three four five', '77ne two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77ne two.three four five', '77ne two.three four five')]),
    ('ox', ['G$', 'dl', 'uG$', 'cl77\x1b', 'uG$', '.'], '65ffc03561305911',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five')]),
    ('ox', ['3G', 'dl', 'u3G', 'cl77\x1b', 'u3G', '.'], 'f461a91dc96dfc60',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2l', 'u4G7l', '2dl', 'u4G7l', '.', 'u4G7l', 'c2l77\x1b'], '1c788ad03ae557f0',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'd0', 'u4G7l', 'c077\x1b', 'u4G7l', '.'], '9dca3151a5e417cb',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, '3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 1, '773 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 1, '773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'd0', 'ugg0', 'c077\x1b', 'ugg0', '.'], 'd58f6701e22750b1',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77one two.three four five', '77one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77one two.three four five', '77one two.three four five')]),
    ('ox', ['G$', 'd0', 'uG$', 'c077\x1b', 'uG$', '.'], '2d73a4bc04209ed9',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 1, '77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 1, '77t', 'one two.three four five')]),
    ('ox', ['3G', 'd0', 'u3G', 'c077\x1b', 'u3G', '.'], 'f461a91dc96dfc60',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five')]),
    ('ox', ['5G$', 'd0', 'u5G$', 'c077\x1b', 'u5G$', '.'], '54a48ae2e3c7e9ab',
     [(4, 3, '    ', 'one two.three four five'),
      (4, 0, ' ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 1, '77 ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 1, '77 ', 'one two.three four five')]),
    ('ox', ['4G7l', 'd^', 'u4G7l', 'c^77\x1b', 'u4G7l', '.'], '9dca3151a5e417cb',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, '3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 1, '773 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 1, '773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'd^', 'ugg0', 'c^77\x1b', 'ugg0', '.'], 'd58f6701e22750b1',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77one two.three four five', '77one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77one two.three four five', '77one two.three four five')]),
    ('ox', ['G$', 'd^', 'uG$', 'c^77\x1b', 'uG$', '.'], '2d73a4bc04209ed9',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 1, '77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 1, '77t', 'one two.three four five')]),
    ('ox', ['3G', 'd^', 'u3G', 'c^77\x1b', 'u3G', '.'], 'f461a91dc96dfc60',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five')]),
    ('ox', ['5G$', 'd^', 'u5G$', 'c^77\x1b', 'u5G$', '.'], '19cc384df4a9fef8',
     [(4, 3, '    ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77 ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77 ', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', 'd`a', 'u4G7l', 'c`a77\x1b', 'u4G7l', '.'], '67f19338af907fa5',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (p3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 9, '  ind (p773 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 9, '  ind (p773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', 'd`a', 'ugg0', 'c`a77\x1b', 'ugg0', '.'], 'cae4071e738d3ba6',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'ar) x,y; end', 'ar) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77ar) x,y; end', '77ar) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77ar) x,y; end', '77ar) x,y; end')]),
    ('ox', ['2G6lma7G9lmbG$', 'd`a', 'uG$', 'c`a77\x1b', 'uG$', '.'], '7603343c74e0c8d7',
     [(7, 3, 'last', 'one two.three four five'),
      (1, 8, '  ind (pt', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (1, 9, '  ind (p77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (1, 9, '  ind (p77t', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', 'd`b', 'u4G7l', 'c`b77\x1b', 'u4G7l', '.'], 'ee43876085c6fa1c',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 az z z stop', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77z z z stop', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', 'd`b', 'ugg0', 'c`b77\x1b', 'ugg0', '.'], '4bac1bafaa27d2a7',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'z z z stop', 'z z z stop'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77z z z stop', '77z z z stop'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77z z z stop', '77z z z stop')]),
    ('ox', ['2G6lma7G9lmbG$', 'd`b', 'uG$', 'c`b77\x1b', 'uG$', '.'], 'bec800e2c8e000ac',
     [(7, 3, 'last', 'one two.three four five'),
      (6, 9, 'seven: z t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (6, 10, 'seven: z 77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (6, 10, 'seven: z 77t', 'one two.three four five')]),
    ('ox', ['4G7l', 'dfa', 'u4G7l', 'cfa77\x1b', 'u4G7l', '.'], 'c320f48b0e0bc92c',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a774 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a774 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dfa', 'ugg0', 'cfa77\x1b', 'ugg0', '.'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'dfa', 'uG$', 'cfa77\x1b', 'uG$', '.'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2fa', 'u4G7l', '2dfa', 'u4G7l', '.', 'u4G7l', 'c2fa77\x1b'], '503968ffecb377fe',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a775 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dta', 'u4G7l', 'cta77\x1b', 'u4G7l', '.'], '1c788ad03ae557f0',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dta', 'ugg0', 'cta77\x1b', 'ugg0', '.'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'dta', 'uG$', 'cta77\x1b', 'uG$', '.'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2ta', 'u4G7l', '2dta', 'u4G7l', '.', 'u4G7l', 'c2ta77\x1b'], 'e6dda90a72006108',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dFa', 'u4G7l', 'cFa77\x1b', 'u4G7l', '.'], '68fdb3430edad2ae',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 773 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dFa', 'ugg0', 'cFa77\x1b', 'ugg0', '.'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'dFa', 'uG$', 'cFa77\x1b', 'uG$', '.'], '178bec976682b7b1',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 1, 'lt', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 2, 'l77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 2, 'l77t', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2Fa', 'u4G7l', '2dFa', 'u4G7l', '.', 'u4G7l', 'c2Fa77\x1b'], '3f94a89a98fb94aa',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dTa', 'u4G7l', 'cTa77\x1b', 'u4G7l', '.'], '5f8ff404aa9cec58',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a773 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dTa', 'ugg0', 'cTa77\x1b', 'ugg0', '.'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'dTa', 'uG$', 'cTa77\x1b', 'uG$', '.'], 'd2c9dba012594809',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'lat', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'la77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'la77t', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2Ta', 'u4G7l', '2dTa', 'u4G7l', '.', 'u4G7l', 'c2Ta77\x1b'], 'd8251456eb28c696',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 5, 'a1 a773 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7lfa', 'd;', 'u4G7lfa', 'c;77\x1b', 'u4G7lfa', '.'], 'c25ff71ad2eb58b1',
     [(3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 10, 'a1 a2 a3 775 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 10, 'a1 a2 a3 775 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0fa', 'd;', 'ugg0fa', 'c;77\x1b', 'ugg0fa', '.'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$fa', 'd;', 'uG$fa', 'c;77\x1b', 'uG$fa', '.'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['4G7lfa', 'd2;', 'u4G7lfa', '2d;', 'u4G7lfa', '.', 'u4G7lfa', 'c2;77\x1b'], 'f58fc9818944dc18',
     [(3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 10, 'a1 a2 a3 776 a7', 'one two.three four five')]),
    ('ox', ['4G7lfa', 'd,', 'u4G7lfa', 'c,77\x1b', 'u4G7lfa', '.'], '10ede53c9ec576c1',
     [(3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 77a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 77a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0fa', 'd,', 'ugg0fa', 'c,77\x1b', 'ugg0fa', '.'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$fa', 'd,', 'uG$fa', 'c,77\x1b', 'uG$fa', '.'], '178bec976682b7b1',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 1, 'lt', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 2, 'l77t', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 2, 'l77t', 'one two.three four five')]),
    ('ox', ['4G7lfa', 'd2,', 'u4G7lfa', '2d,', 'u4G7lfa', '.', 'u4G7lfa', 'c2,77\x1b'], '7dba28839e743037',
     [(3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, 'a1 a4 a5 a6 a7', 'one two.three four five'),
      (3, 9, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 77a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'de', 'u4G7l', 'ce77\x1b', 'u4G7l', '.'], '60c80ca4ca65dd12',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'de', 'ugg0', 'ce77\x1b', 'ugg0', '.'], '78d5cec920286bba',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, ' two.three four five', ' two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77 two.three four five', '77 two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77 two.three four five', '77 two.three four five')]),
    ('ox', ['G$', 'de', 'uG$', 'ce77\x1b', 'uG$', '.'], '65ffc03561305911',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five')]),
    ('ox', ['3G', 'de', 'u3G', 'ce77\x1b', 'u3G', '.'], '15555e283c50aad5',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, ' a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['5G$', 'de', 'u5G$', 'ce77\x1b', 'u5G$', '.'], '0a93bc877b557e1a',
     [(4, 3, '    ', 'one two.three four five'),
      (4, 3, '    sep\tword', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77 sep\tword', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77 sep\tword', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2e', 'u4G7l', '2de', 'u4G7l', '.', 'u4G7l', 'c2e77\x1b'], 'e45a379a72ebcd18',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dE', 'u4G7l', 'cE77\x1b', 'u4G7l', '.'], '60c80ca4ca65dd12',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'dE', 'ugg0', 'cE77\x1b', 'ugg0', '.'], '78d5cec920286bba',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, ' two.three four five', ' two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77 two.three four five', '77 two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77 two.three four five', '77 two.three four five')]),
    ('ox', ['G$', 'dE', 'uG$', 'cE77\x1b', 'uG$', '.'], '65ffc03561305911',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five')]),
    ('ox', ['3G', 'dE', 'u3G', 'cE77\x1b', 'u3G', '.'], '15555e283c50aad5',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, ' a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['5G$', 'dE', 'u5G$', 'cE77\x1b', 'u5G$', '.'], '0a93bc877b557e1a',
     [(4, 3, '    ', 'one two.three four five'),
      (4, 3, '    sep\tword', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77 sep\tword', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77 sep\tword', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2E', 'u4G7l', '2dE', 'u4G7l', '.', 'u4G7l', 'c2E77\x1b'], 'e45a379a72ebcd18',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'd$', 'u4G7l', 'c$77\x1b', 'u4G7l', '.'], 'c64e68dfd081b940',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77', 'one two.three four five')]),
    ('ox', ['gg0', 'd$', 'ugg0', 'c$77\x1b', 'ugg0', '.'], 'b6bc60388837af45',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77', '77'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 1, '77', '77')]),
    ('ox', ['G$', 'd$', 'uG$', 'c$77\x1b', 'uG$', '.'], '65ffc03561305911',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 4, 'las77', 'one two.three four five')]),
    ('ox', ['3G', 'd$', 'u3G', 'c$77\x1b', 'u3G', '.'], 'f461a91dc96dfc60',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 1, '77', 'one two.three four five')]),
    ('ox', ['5G$', 'd$', 'u5G$', 'c$77\x1b', 'u5G$', '.'], '6ae9c46b25b7bad3',
     [(4, 3, '    ', 'one two.three four five'),
      (4, 2, '   ', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (4, 4, '   77', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2$', 'u4G7l', '2d$', 'u4G7l', '.', 'u4G7l', 'c2$77\x1b'], '507b177f04a6f251',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, 'a1 a2 a77', 'one two.three four five')]),
    ('ox', ['4G7l', 'yj', 'P', 'u4G7l', 'dj', 'u4G7l', '.', 'p'], '5400481b7ba9dec8',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, '\ttab sep\tword', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, '\ttab sep\tword', 'one two.three four five'),
      (4, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'yj', 'P', 'ugg0', 'dj', 'ugg0', '.', 'p'], '8f4e36402ccb872b',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (1, 0, 'one two.three four five', '')]),
    ('ox', ['G$', 'yj', 'P', 'uG$', 'dj', 'uG$', '.', 'p'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['3G', 'yj', 'P', 'u3G', 'dj', 'u3G', '.', 'p'], 'd3264b965a6ce2a7',
     [(2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 3, '    ', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 3, '    ', 'one two.three four five'),
      (3, 0, '', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2j', 'u4G7l', '2dj', 'u4G7l', '.', 'u4G7l', 'y2j'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'seven: z z z z stop', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'seven: z z z z stop', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'seven: z z z z stop', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'yk', 'P', 'u4G7l', 'dk', 'u4G7l', '.', 'p'], 'd3264b965a6ce2a7',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 3, '    ', 'one two.three four five'),
      (3, 0, '', 'one two.three four five')]),
    ('ox', ['gg0', 'yk', 'P', 'ugg0', 'dk', 'ugg0', '.', 'p'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'yk', 'P', 'uG$', 'dk', 'uG$', '.', 'p'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (6, 18, 'seven: z z z z stop', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (5, 8, '\ttab sep\tword', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (5, 8, '\ttab sep\tword', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['3G', 'yk', 'P', 'u3G', 'dk', 'u3G', '.', 'p'], '8f7b6b5e8b18dfad',
     [(2, 0, '', 'one two.three four five'),
      (1, 0, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (1, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (1, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 2, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2k', 'u4G7l', '2dk', 'u4G7l', '.', 'u4G7l', 'y2k'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 7, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['4G7l', 'yG', 'P', 'u4G7l', 'dG', 'u4G7l', '.', 'p'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'yG', 'P', 'ugg0', 'dG', 'ugg0', '.', 'p'], '9a0987244708302a',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (1, 0, 'one two.three four five', '')]),
    ('ox', ['G$', 'yG', 'P', 'uG$', 'dG', 'uG$', '.', 'p'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['4G7l', 'd6G', 'u4G7l', '2dG', 'u4G7l', '.', 'u4G7l', 'y6G'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'seven: z z z z stop', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'yH', 'P', 'u4G7l', 'dH', 'u4G7l', '.', 'p'], 'db27943eb7d258c0',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (1, 0, 'one two.three four five', '    ')]),
    ('ox', ['gg0', 'yH', 'P', 'ugg0', 'dH', 'ugg0', '.', 'p'], '66b6278b0c4804d9',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 2, '  ind (par) x,y; end', '  ind (par) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 2, '  ind (par) x,y; end', '  ind (par) x,y; end'),
      (1, 0, 'one two.three four five', '  ind (par) x,y; end')]),
    ('ox', ['G$', 'yH', 'P', 'uG$', 'dH', 'uG$', '.', 'p'], '9a0987244708302a',
     [(7, 3, 'last', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (0, 0, '', ''),
      (7, 3, 'last', 'one two.three four five'),
      (0, 0, '', ''),
      (1, 0, 'one two.three four five', '')]),
    ('ox', ['4G7l', 'd2H', 'u4G7l', '2dH', 'u4G7l', '.', 'u4G7l', 'y2H'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['4G7l', 'yM', 'P', 'u4G7l', 'dM', 'u4G7l', '.', 'p'], '1e1b60fd8d7f2b79',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, '    ', 'one two.three four five'),
      (4, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'yM', 'P', 'ugg0', 'dM', 'ugg0', '.', 'p'], 'db27943eb7d258c0',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (1, 0, 'one two.three four five', '    ')]),
    ('ox', ['G$', 'yM', 'P', 'uG$', 'dM', 'uG$', '.', 'p'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'yL', 'P', 'u4G7l', 'dL', 'u4G7l', '.', 'p'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['gg0', 'yL', 'P', 'ugg0', 'dL', 'ugg0', '.', 'p'], '9a0987244708302a',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (1, 0, 'one two.three four five', '')]),
    ('ox', ['G$', 'yL', 'P', 'uG$', 'dL', 'uG$', '.', 'p'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2L', 'u4G7l', '2dL', 'u4G7l', '.', 'u4G7l', 'y2L'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'last', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'last', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'last', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'ygg', 'P', 'u4G7l', 'dgg', 'u4G7l', '.', 'p'], 'db27943eb7d258c0',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (1, 0, 'one two.three four five', '    ')]),
    ('ox', ['gg0', 'ygg', 'P', 'ugg0', 'dgg', 'ugg0', '.', 'p'], '66b6278b0c4804d9',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 2, '  ind (par) x,y; end', '  ind (par) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 2, '  ind (par) x,y; end', '  ind (par) x,y; end'),
      (1, 0, 'one two.three four five', '  ind (par) x,y; end')]),
    ('ox', ['G$', 'ygg', 'P', 'uG$', 'dgg', 'uG$', '.', 'p'], '9a0987244708302a',
     [(7, 3, 'last', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (0, 0, '', ''),
      (7, 3, 'last', 'one two.three four five'),
      (0, 0, '', ''),
      (1, 0, 'one two.three four five', '')]),
    ('ox', ['4G7l', 'd2gg', 'u4G7l', '2dgg', 'u4G7l', '.', 'u4G7l', 'y2gg'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', "y'a", 'P', 'u4G7l', "d'a", 'u4G7l', '.', 'p'], 'f3c4bfbb59c5c53a',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (2, 2, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', "y'a", 'P', 'ugg0', "d'a", 'ugg0', '.', 'p'], '8f4e36402ccb872b',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (1, 0, 'one two.three four five', '')]),
    ('ox', ['2G6lma7G9lmbG$', "y'a", 'P', 'uG$', "d'a", 'uG$', '.', 'p'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', "y'b", 'P', 'u4G7l', "d'b", 'u4G7l', '.', 'p'], 'dd23b7a362e98f89',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'last', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'last', 'one two.three four five'),
      (4, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', "y'b", 'P', 'ugg0', "d'b", 'ugg0', '.', 'p'], 'd3986311da7683f0',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'last', 'last'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'last', 'last'),
      (1, 0, 'one two.three four five', 'last')]),
    ('ox', ['2G6lma7G9lmbG$', "y'b", 'P', 'uG$', "d'b", 'uG$', '.', 'p'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (5, 8, '\ttab sep\tword', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (5, 8, '\ttab sep\tword', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five')]),
]


# Rows the editor does not do as vim does, as (the place, the first operator)
# -> the number of the issue each is waiting on.  They are still RUN, and the
# test fails if one of them stops differing: a fix has to take its rows out of
# here, which is what turns them into checks.  None is waiting now.
OPMX_OPEN = {}


def opmx_like_vim():
    """Every operator over every motion it takes puts the text, the cursor and
    the window where vim does, with 'u', '.' and the register after each, and
    writes the file vim wrote."""
    import hashlib
    check('the opmx table is the whole matrix: its keys are opmx_keys()',
          [r[1] for r in VIM_OPMX] == opmx_keys())
    check('every row waiting on an issue is a row of the table',
          set(OPMX_OPEN) <= set((r[1][0], r[1][1]) for r in VIM_OPMX))
    files = opmx_files()
    for f, keys, sha, want in VIM_OPMX:
        issue = OPMX_OPEN.get((keys[0], keys[1]))
        diffs = []

        def same(label, cond):
            if issue is None:
                check(label, cond)
            elif not cond:
                diffs.append(label)
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                if k.endswith('\x1b'):
                    send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
                r = rows(e); v = e.screen()
                got = (v.row, v.col, r[v.row], r[0])
                same(f'vim opmx {keys!r} {k!r}: {got[:2]} {got[2][:20]!r} '
                     f'== {(wrow, wcol)} {wcur[:20]!r}',
                     got == (wrow, wcol, expand(wcur).rstrip(),
                             expand(wtop).rstrip()))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            same(f'vim opmx {keys!r}: file as vim wrote it ({got})', got == sha)
            if issue is not None:
                check(f'vim opmx {keys!r}: still not vim\'s, as issue #{issue} '
                      f'says -- if this fails the issue is fixed: take the row '
                      f'out of OPMX_OPEN', bool(diffs))
        finally:
            e.close()



# A span that ends in a line's first column (vim ':help exclusive'): it stops
# at the end of the line before, and if it also starts at or before its own
# line's first non-blank it is whole lines.  (keys, the file vim 9.1 wrote,
# vim's cursor line and column), on COL1_TEXT; the mark rows are the same rule
# met by a jump, from either end.
COL1_TEXT = b'aa bb\r\n  word\r\n  Xy z\r\n'
VIM_COL1 = [
    (['G0', 'db'], b'aa bb\r\n  Xy z\r\n', (1, 2)),
    (['G0', 'cbqq\x1b'], b'aa bb\r\nqq\r\n  Xy z\r\n', (1, 1)),
    (['G0', 'd2b'], b'aa \r\n  Xy z\r\n', (0, 2)),
    (['G0', 'd3b'], b'  Xy z\r\n', (0, 2)),
    (['G0', 'ma', 'gg', 'd`a'], b'  Xy z\r\n', (0, 2)),
    (['G0', 'ma', 'gg3l', 'd`a'], b'aa \r\n  Xy z\r\n', (0, 2)),
    (['gg3l', 'ma', 'G0', 'd`a'], b'aa \r\n  Xy z\r\n', (0, 2)),
    (['gg', 'ma', 'G0', 'd`a'], b'  Xy z\r\n', (0, 2)),
    (['2G0', 'ma', 'G0', 'd`a'], b'aa bb\r\n  Xy z\r\n', (1, 2)),
]


# A motion that falls short at the end of a line or of the file: 'l' with no
# char left to step onto takes the one it is on, and 'w' on the file's last
# char takes that char; on an empty line neither has anything to take.  Same
# shape as VIM_COL1, on SHORT_TEXT.
SHORT_TEXT = b'aa bb\r\ncc dd\r\n\r\nee ff\r\n'
VIM_SHORT = [
    (['gg$', 'dl'], b'aa b\r\ncc dd\r\n\r\nee ff\r\n', (0, 3)),
    (['gg$', 'd3l'], b'aa b\r\ncc dd\r\n\r\nee ff\r\n', (0, 3)),
    (['gg$h', 'd3l'], b'aa \r\ncc dd\r\n\r\nee ff\r\n', (0, 2)),
    (['gg$', 'clqq\x1b'], b'aa bqq\r\ncc dd\r\n\r\nee ff\r\n', (0, 5)),
    (['gg$h', 'c3lqq\x1b'], b'aa qq\r\ncc dd\r\n\r\nee ff\r\n', (0, 4)),
    (['3G', 'dl'], b'aa bb\r\ncc dd\r\n\r\nee ff\r\n', (2, 0)),
    (['3G', 'clqq\x1b'], b'aa bb\r\ncc dd\r\nqq\r\nee ff\r\n', (2, 1)),
    (['3G', 'dw'], b'aa bb\r\ncc dd\r\nee ff\r\n', (2, 0)),
    (['G$', 'dw'], b'aa bb\r\ncc dd\r\n\r\nee f\r\n', (3, 3)),
    (['G$', 'd3w'], b'aa bb\r\ncc dd\r\n\r\nee f\r\n', (3, 3)),
    (['G$', 'cwqq\x1b'], b'aa bb\r\ncc dd\r\n\r\nee fqq\r\n', (3, 5)),
    (['G', 'd3w'], b'aa bb\r\ncc dd\r\n\r\n\r\n', (3, 0)),
    # 'b' with nowhere to go back to fails and its operator is dropped (the
    # '77' is then a count the ESC cancels); one that runs out of words at
    # the file's start has still moved, and its operator stands
    (['gg', 'cb77\x1b'], SHORT_TEXT, (0, 0)),
    (['gg', 'd5b'], SHORT_TEXT, (0, 0)),
    (['ggw', 'd5b'], b'bb\r\ncc dd\r\n\r\nee ff\r\n', (0, 0)),
    (['ggw', 'c5b77\x1b'], b'77bb\r\ncc dd\r\n\r\nee ff\r\n', (0, 1)),
    (['2G', 'd5b'], b'cc dd\r\n\r\nee ff\r\n', (0, 0)),
]

# A count on a word motion under an operator, and 'cw' on a word's last char.
# 'cw' is 'ce', except that from a word's last char it stays there (so 'cw' on
# a one-letter word changes that word, not the next one too) -- and only the
# count's FIRST word stays.  Under 'd' only the count's LAST word stops at its
# line's end; the ones before it run on over the line break.  A delete of more
# than one line that leaves only blanks before and after it takes the lines
# whole.  Same shape as VIM_COL1, on WORD_TEXT (a line with trailing blanks, an
# indented line, an empty line, a one-word line).
WORD_TEXT = b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n'
VIM_WORD = [
    (['gg0l', 'cwQ\x1b'], b'aQ bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 1)),
    (['gg0l', 'c2wQ\x1b'], b'aQ c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 1)),
    (['gg0l', 'cWQ\x1b'], b'aQ bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 1)),
    (['gg0l', 'c3wQ\x1b'], b'aQ\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 1)),
    (['gg$', 'cwQ\x1b'], b'aa bb Q\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 6)),
    (['gg$', 'c2wQ\x1b'], b'aa bb Q ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 6)),
    (['gg$', 'c3wQ\x1b'], b'aa bb Q  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 6)),
    (['gg0', 'c4wQ\x1b'], b'Q ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 0)),
    (['gg0w', 'c2wQ\x1b'], b'aa Q\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 3)),
    (['gg0w', 'c3wQ\x1b'], b'aa Q ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 3)),
    (['gg02l', 'cwQ\x1b'], b'aaQbb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['gg02l', 'c2wQ\x1b'], b'aaQc\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['gg02l', 'c3wQ\x1b'], b'aaQ\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['G0', 'cwQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nQ yy z\r\n', (5, 0)),
    (['G0', 'c2wQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nQ z\r\n', (5, 0)),
    (['G$', 'cwQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy Q\r\n', (5, 5)),
    (['G$', 'c2wQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy Q\r\n', (5, 5)),
    (['G0', 'c9wQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nQ\r\n', (5, 0)),
    (['2G0w', 'cwQ\x1b'], b'aa bb c\r\ndd Q  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 3)),
    (['2G0w', 'c2wQ\x1b'], b'aa bb c\r\ndd Q gg\r\n\r\nhh\r\nx yy z\r\n', (1, 3)),
    (['2G$', 'cwQ\x1b'], b'aa bb c\r\ndd ee Q\r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 6)),
    (['2G$', 'c2wQ\x1b'], b'aa bb c\r\ndd ee Qgg\r\n\r\nhh\r\nx yy z\r\n', (1, 6)),
    (['3G0', 'cwQ\x1b'], b'aa bb c\r\ndd ee  \r\nQff gg\r\n\r\nhh\r\nx yy z\r\n', (2, 0)),
    (['3G0', 'c2wQ\x1b'], b'aa bb c\r\ndd ee  \r\nQgg\r\n\r\nhh\r\nx yy z\r\n', (2, 0)),
    (['4G', 'cwQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\nQ\r\nhh\r\nx yy z\r\n', (3, 0)),
    (['4G', 'c2wQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\nQ\r\nx yy z\r\n', (3, 0)),
    (['3G$', 'c2wQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gQ\r\nx yy z\r\n', (2, 6)),
    (['3G$', 'c3wQ\x1b'], b'aa bb c\r\ndd ee  \r\n  ff gQ yy z\r\n', (2, 6)),
    (['gg0', 'd3w'], b'\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 0)),
    (['gg0', 'd4w'], b'ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 0)),
    (['gg0w', 'd2w'], b'aa \r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['gg0w', 'd3w'], b'aa ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 3)),
    (['gg$', 'dw'], b'aa bb \r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 5)),
    (['gg$', 'd2w'], b'aa bb ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 6)),
    (['gg$', 'd3w'], b'aa bb \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 5)),
    (['gg0w', 'd4w'], b'aa \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['gg0w', 'd5w'], b'aa gg\r\n\r\nhh\r\nx yy z\r\n', (0, 3)),
    (['gg0w', 'd6w'], b'aa \r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['gg0w', 'd7w'], b'aa \r\nhh\r\nx yy z\r\n', (0, 2)),
    (['2G0', 'dw'], b'aa bb c\r\nee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 0)),
    (['2G0', 'd2w'], b'aa bb c\r\n\r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 0)),
    (['2G0w', 'dw'], b'aa bb c\r\ndd \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 2)),
    (['2G0w', 'd2w'], b'aa bb c\r\ndd gg\r\n\r\nhh\r\nx yy z\r\n', (1, 3)),
    (['2G0w', 'd3w'], b'aa bb c\r\ndd \r\n\r\nhh\r\nx yy z\r\n', (1, 2)),
    (['2G0w', 'd4w'], b'aa bb c\r\ndd \r\nhh\r\nx yy z\r\n', (1, 2)),
    (['2G$', 'dw'], b'aa bb c\r\ndd ee \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 5)),
    (['2G$', 'd2w'], b'aa bb c\r\ndd ee gg\r\n\r\nhh\r\nx yy z\r\n', (1, 6)),
    (['3G0', 'dw'], b'aa bb c\r\ndd ee  \r\nff gg\r\n\r\nhh\r\nx yy z\r\n', (2, 0)),
    (['3G0', 'd2w'], b'aa bb c\r\ndd ee  \r\ngg\r\n\r\nhh\r\nx yy z\r\n', (2, 0)),
    (['3G0', 'd3w'], b'aa bb c\r\ndd ee  \r\n\r\n\r\nhh\r\nx yy z\r\n', (2, 0)),
    (['3G0', 'd4w'], b'aa bb c\r\ndd ee  \r\nhh\r\nx yy z\r\n', (2, 0)),
    (['3G$', 'd2w'], b'aa bb c\r\ndd ee  \r\n  ff g\r\nhh\r\nx yy z\r\n', (2, 5)),
    (['3G$', 'd3w'], b'aa bb c\r\ndd ee  \r\n  ff g\r\nx yy z\r\n', (2, 5)),
    (['3G$', 'd4w'], b'aa bb c\r\ndd ee  \r\n  ff gyy z\r\n', (2, 6)),
    (['4G', 'd2w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\nx yy z\r\n', (3, 0)),
    (['4G', 'd3w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\nyy z\r\n', (3, 0)),
    (['5G', 'dw'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\n\r\nx yy z\r\n', (4, 0)),
    (['5G', 'd2w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nyy z\r\n', (4, 0)),
    (['5G', 'd3w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nz\r\n', (4, 0)),
    (['5G', 'd4w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\n', (3, 0)),
    (['5G', 'd9w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\n', (3, 0)),
    (['G0', 'd3w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\n\r\n', (5, 0)),
    (['G0', 'd4w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\n\r\n', (5, 0)),
    (['G0w', 'd2w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx \r\n', (5, 1)),
    (['G0w', 'd3w'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx \r\n', (5, 1)),
    (['gg0w', 'd2W'], b'aa \r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['gg0w', 'd3W'], b'aa ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 3)),
    (['gg0w', 'c2WQ\x1b'], b'aa Q\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 3)),
    (['2G0', 'd3W'], b'aa bb c\r\ngg\r\n\r\nhh\r\nx yy z\r\n', (1, 0)),
    # the same rule for any delete of more than one line ('de', a mark), and
    # '.' and 'u' after these
    (['3G0', 'd3e'], b'aa bb c\r\ndd ee  \r\nx yy z\r\n', (2, 0)),
    (['3G0', 'd2e'], b'aa bb c\r\ndd ee  \r\n\r\n\r\nhh\r\nx yy z\r\n', (2, 0)),
    (['4G', 'de'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\nx yy z\r\n', (3, 0)),
    (['4G', 'd2e'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n yy z\r\n', (3, 0)),
    (['3G0', 'c3eQ\x1b'], b'aa bb c\r\ndd ee  \r\nQ\r\nx yy z\r\n', (2, 0)),
    (['2G$ma3G0', 'd`a'], b'aa bb c\r\ndd ee \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 5)),
    (['5G$ma3G0', 'd`a'], b'aa bb c\r\ndd ee  \r\nh\r\nx yy z\r\n', (2, 0)),
    (['3G0ma5G$', 'd`a'], b'aa bb c\r\ndd ee  \r\nh\r\nx yy z\r\n', (2, 0)),
    (['gg0', 'd2e'], b' c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 0)),
    (['gg0', 'd3e'], b'\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 0)),
    (['gg0', 'd5e'], b'  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['2G0', 'd2e'], b'aa bb c\r\n  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 0)),
    (['5G', 'd4e'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\n', (3, 0)),
    (['5G', 'de'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\n\r\nx yy z\r\n', (4, 0)),
    (['5G', 'd2e'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\n yy z\r\n', (4, 0)),
    (['gg0w', 'd4e'], b'aa   \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 3)),
    (['3G0', 'd4e'], b'aa bb c\r\ndd ee  \r\n yy z\r\n', (2, 0)),
    (['gg0', 'cwQ\x1b', 'w', '.'], b'Q Q c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 2)),
    (['gg$', 'cwQ\x1b', '2G0', '.'], b'aa bb Q\r\nQ ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (1, 0)),
    (['gg0w', 'd2w', 'u'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (0, 3)),
    (['gg0w', 'd3w', '2G0', '.'], b'aa ee  \r\n\r\n\r\nhh\r\nx yy z\r\n', (1, 0)),
    (['4G', 'd2w', 'u'], b'aa bb c\r\ndd ee  \r\n  ff gg\r\n\r\nhh\r\nx yy z\r\n', (3, 0)),
    (['4G', 'd2w', 'gg', '.'], b'c\r\ndd ee  \r\n  ff gg\r\nx yy z\r\n', (0, 0)),
]


def col1_like_vim():
    """A span ending in a line's first column goes as vim takes it."""
    span_table('col1', COL1_TEXT, VIM_COL1)


def short_like_vim():
    """An operator over a motion that fell short takes what vim takes."""
    span_table('short', SHORT_TEXT, VIM_SHORT)


def word_like_vim():
    """A counted word motion under an operator takes what vim takes."""
    span_table('word', WORD_TEXT, VIM_WORD)


def span_table(name, text, table):
    for keys, want, cur in table:
        e = Editor(text)
        try:
            for k in keys:
                if k.endswith('\x1b'):
                    send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
            v = e.screen()
            check(f'vim {name} {keys!r}: cursor {(v.row, v.col)} == {cur}',
                  (v.row, v.col) == cur)
            e.key(':w\r')
            got = saved_bytes(e)
            check(f'vim {name} {keys!r}: file {got!r} as vim wrote it',
                  got == want)
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
     [(10, 0, '000700', '000694'),
      (10, 5, '000700', '000694'),
      (10, 4, '00070', '000694'),
      (10, 3, '0007', '000694')]),
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
     [(10, 0, '000700', '000694'),
      (10, 0, '000701', '000694'),
      (10, 0, '000702xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '000694')]),
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
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 8, '01500 ZZZ', ''),
      (12, 0, '', ''),
      (12, 0, '', ''),
      (12, 2, 'ZZZ', '')]),
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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
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
     [(10, 0, '000700', '000694'),
      (10, 5, '000700', '000694'),
      (10, 4, '00070', '000694'),
      (10, 5, '000700', '000694')]),
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
     [(10, 0, '000700', '000694'),
      (10, 0, '000701', '000694'),
      (10, 0, '000700', '000694')]),
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
     [(11, 0, '01500 foo.bar(baz) qux_1', ''),
      (11, 8, '01500 ZZZ', ''),
      (11, 6, '01500 foo.bar(baz) qux_1', '')]),
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
# rather than quietly dropped.  'u' puts the cursor back where the CHANGE
# began, which for o O J dw x r ~ D cw R i and p is where the command began
# (VIM_UNDOAT below has the commands for which it is not).  'A' is the
# exception left: it moves the
# cursor to the line end before inserting, and vim's undo lands on that end
# (clamped into the restored line) rather than on the column 'A' was typed at.
# Honouring both would need the snapshot taken at two different moments; the
# text and the file it writes are still checked on this row.
UNDO_SKIP = {('2', ('0', 'A!\x1b', 'u')): 'col'}


# VIM_UNDOAT -- where 'u' leaves the cursor and the marks, recorded from vim
# 9.1 by vimref.py ('undoat') on opmx_files()['ox'], in VIM_OPMX's shape: the
# cursor's row and column, its line and the top line after every key, and the
# file vim wrote.  What these rows pin:
#   * the cursor goes to where the CHANGE began, which is not where the
#     command began when the motion ran backward: 'db' 'dh' 'd0' 'dFa' 'cb'
#     leave it at the start of what came back, 'dk' 'dgg' 'dH' where the
#     motion landed;
#   * ONE whole line taken ('dd', 'dG' on the last line) comes back with the
#     cursor on its first non-blank, unless it was already left of that; two
#     ('2dd', 'dj') leave the column alone;
#   * every mark that was set when the change began is back where it was then,
#     the ones the delete ran over and one moved since alike; a mark first set
#     AFTER the change stays with its text.
# The last three rows are a second 'u': vim has nothing more to undo there and
# this editor redoes, so undo_at_vim() leaves them to undo_cmds().
VIM_UNDOAT = [
    ('ox', ['4G7l', 'db', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dB', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dh', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'd3h', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 4, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'd0', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, '3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'd^', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, '3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dFa', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dTa', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dk', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 3, '    ', 'one two.three four five'),
      (2, 0, '', 'one two.three four five')]),
    ('ox', ['4G7l', 'd2k', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (1, 7, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['4G7l', 'dgg', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['4G7l', 'dH', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['4G7l', 'dM', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, '    ', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dL', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'cbQ\x1b', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 Q3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'c0Q\x1b', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'Q3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dw', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aa4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dl', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dj', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, '\ttab sep\tword', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dG', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'd$', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'de', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'dd', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 3, '    ', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', '2dd', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 8, '\ttab sep\tword', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'x', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['4G7l', 'D', 'u'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 6, 'a1 a2 a', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['2G6l', 'db', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 7, '  ind (ar) x,y; end', 'one two.three four five'),
      (1, 7, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dB', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 6, '  ind ar) x,y; end', 'one two.three four five'),
      (1, 6, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dh', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 7, '  ind (ar) x,y; end', 'one two.three four five'),
      (1, 7, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'd3h', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 5, '  indar) x,y; end', 'one two.three four five'),
      (1, 5, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'd0', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, 'ar) x,y; end', 'one two.three four five'),
      (1, 0, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'd^', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 2, '  ar) x,y; end', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dFa', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dTa', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dk', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 8, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['2G6l', 'd2k', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 8, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['2G6l', 'dgg', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['2G6l', 'dH', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['2G6l', 'dM', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dL', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'cbQ\x1b', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 7, '  ind (Qar) x,y; end', 'one two.three four five'),
      (1, 7, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'c0Q\x1b', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, 'Qar) x,y; end', 'one two.three four five'),
      (1, 0, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dw', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (p) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dl', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (pr) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dj', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dG', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'd$', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 7, '  ind (p', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'de', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (p) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'dd', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, '', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', '2dd', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'x', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (pr) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6l', 'D', 'u'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 7, '  ind (p', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['G$', 'db', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dB', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dh', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'lat', 'one two.three four five'),
      (7, 2, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'd3h', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'd0', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'd^', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 't', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dFa', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 1, 'lt', 'one two.three four five'),
      (7, 1, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dTa', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'lat', 'one two.three four five'),
      (7, 2, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dk', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (5, 8, '\ttab sep\tword', 'one two.three four five'),
      (6, 18, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['G$', 'd2k', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['G$', 'dgg', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'dH', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['G$', 'dM', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (2, 0, '', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['G$', 'dL', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'cbQ\x1b', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 'Qt', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'c0Q\x1b', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 0, 'Qt', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dw', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dl', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dj', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dG', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'd$', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'de', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'dd', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (7, 0, 'last', 'one two.three four five')]),
    ('ox', ['G$', '2dd', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'x', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['G$', 'D', 'u'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (7, 2, 'las', 'one two.three four five'),
      (7, 3, 'last', 'one two.three four five')]),
    ('ox', ['6G$', 'db', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 16, '\ttab sep\td', 'one two.three four five'),
      (5, 16, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dB', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 16, '\ttab sep\td', 'one two.three four five'),
      (5, 16, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dh', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 18, '\ttab sep\twod', 'one two.three four five'),
      (5, 18, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'd3h', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 16, '\ttab sep\td', 'one two.three four five'),
      (5, 16, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'd0', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 0, 'd', 'one two.three four five'),
      (5, 7, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'd^', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 8, '\td', 'one two.three four five'),
      (5, 8, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dFa', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 9, '\ttd', 'one two.three four five'),
      (5, 9, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dTa', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 10, '\ttad', 'one two.three four five'),
      (5, 10, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dk', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (4, 0, 'seven: z z z z stop', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five')]),
    ('ox', ['6G$', 'd2k', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (3, 0, 'seven: z z z z stop', 'one two.three four five'),
      (3, 19, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['6G$', 'dgg', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (0, 0, 'seven: z z z z stop', 'seven: z z z z stop'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['6G$', 'dH', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (0, 0, 'seven: z z z z stop', 'seven: z z z z stop'),
      (0, 0, 'one two.three four five', 'one two.three four five')]),
    ('ox', ['6G$', 'dM', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (3, 0, 'seven: z z z z stop', 'one two.three four five'),
      (3, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five')]),
    ('ox', ['6G$', 'dL', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'cbQ\x1b', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 16, '\ttab sep\tQd', 'one two.three four five'),
      (5, 16, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'c0Q\x1b', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 0, 'Qd', 'one two.three four five'),
      (5, 7, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dw', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 18, '\ttab sep\twor', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dl', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 18, '\ttab sep\twor', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dj', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 0, 'last', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dG', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'd$', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 18, '\ttab sep\twor', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'de', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 19, '\ttab sep\twor: z z z z stop', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'dd', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 0, 'seven: z z z z stop', 'one two.three four five'),
      (5, 8, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', '2dd', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 0, 'last', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'x', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 18, '\ttab sep\twor', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['6G$', 'D', 'u'], '4cfaf3b00a212827',
     [(5, 19, '\ttab sep\tword', 'one two.three four five'),
      (5, 18, '\ttab sep\twor', 'one two.three four five'),
      (5, 19, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', 'd`a', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (p3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', 'd`b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 az z z stop', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', "d'a", 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 3, '    ', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', "d'b", 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 0, 'last', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', 'c`aQ\x1b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (pQ3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmb4G7l', 'c`bQ\x1b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (3, 7, 'a1 a2 aQz z z stop', 'one two.three four five'),
      (3, 7, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', 'd`a', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'ar) x,y; end', 'ar) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', 'd`b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'z z z stop', 'z z z stop'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', "d'a", 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, '', ''),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', "d'b", 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'last', 'last'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', 'c`aQ\x1b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'Qar) x,y; end', 'Qar) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbgg0', 'c`bQ\x1b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'Qz z z stop', 'Qz z z stop'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbG$', 'd`a', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (1, 8, '  ind (pt', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbG$', 'd`b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (6, 9, 'seven: z t', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbG$', "d'a", 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbG$', "d'b", 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (5, 8, '\ttab sep\tword', 'one two.three four five'),
      (6, 0, 'seven: z z z z stop', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbG$', 'c`aQ\x1b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (1, 8, '  ind (pQt', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma7G9lmbG$', 'c`bQ\x1b', 'u', '`a', '`b'], '4cfaf3b00a212827',
     [(7, 3, 'last', 'one two.three four five'),
      (6, 9, 'seven: z Qt', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (6, 9, 'seven: z z z z stop', 'one two.three four five')]),
    ('ox', ['2G6lma', '2Gdd', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, '', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '3Gdk', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 0, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '4Gdgg', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '2G6lx', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (pr) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '2G4ldw', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 6, '  ind par) x,y; end', 'one two.three four five'),
      (1, 6, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '2G0D', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, '', 'one two.three four five'),
      (1, 0, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', 'ggdd', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 2, '  ind (par) x,y; end', '  ind (par) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', 'ggx', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 0, 'ne two.three four five', 'ne two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '2G0x', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, ' ind (par) x,y; end', 'one two.three four five'),
      (1, 0, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '2GJ', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 19, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', 'ggJ', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 23, 'one two.three four five ind (par) x,y; end', 'one two.three four five ind (par) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['ggdd', '4Gmb', 'u', '`b'], '4cfaf3b00a212827',
     [(0, 2, '  ind (par) x,y; end', '  ind (par) x,y; end'),
      (3, 3, '    ', '  ind (par) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (4, 3, '    ', 'one two.three four five')]),
    ('ox', ['2Gdd', '5G3lmb', 'u', '`b'], '4cfaf3b00a212827',
     [(1, 0, '', 'one two.three four five'),
      (4, 11, '\ttab sep\tword', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (5, 11, '\ttab sep\tword', 'one two.three four five')]),
    ('ox', ['4Gdgg', 'G2lmb', 'u', '`b'], '4cfaf3b00a212827',
     [(0, 3, '    ', '    '),
      (3, 2, 'last', '    '),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (7, 2, 'last', 'one two.three four five')]),
    ('ox', ['2G6lma', 'ggdd', '5G2lma', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 2, '  ind (par) x,y; end', '  ind (par) x,y; end'),
      (4, 10, '\ttab sep\tword', '  ind (par) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '2Gdd', '5Gma', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, '', 'one two.three four five'),
      (4, 8, '\ttab sep\tword', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '4Gdgg', 'ma', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 3, '    ', '    '),
      (0, 3, '    ', '    '),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '3Gdd', "2Gd'a", 'u', '`a'], 'aa54b14a90c49a8a',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (2, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 0, 'a1 a2 a3 a4 a5 a6 a7', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '4G2ldj', 'ggd`a', 'u', '`a'], 'd7178acc1ad95c9f',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (3, 8, '\ttab sep\tword', 'one two.three four five'),
      (0, 0, 'ar) x,y; end', 'ar) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '2Gdd', 'u', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, '', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', '2Gdd', 'u', 'u', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 0, '', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 2, '  ind (par) x,y; end', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
    ('ox', ['2G6lma', 'ggd`a', 'u', 'u', '`a'], '4cfaf3b00a212827',
     [(1, 8, '  ind (par) x,y; end', 'one two.three four five'),
      (0, 0, 'ar) x,y; end', 'ar) x,y; end'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (0, 0, 'one two.three four five', 'one two.three four five'),
      (1, 8, '  ind (par) x,y; end', 'one two.three four five')]),
]


def undo_at_vim():
    """After 'u' the cursor and the marks are where vim puts them."""
    import hashlib
    text = opmx_files()['ox']
    for f, keys, sha, want in VIM_UNDOAT:
        if keys.count('u') > 1:
            continue                    # a redo here: undo_cmds() has those
        e = Editor(text)
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                if k.endswith('\x1b'):
                    send_keys(e, k[:-1])
                    send_keys(e, '\x1b')
                else:
                    e.key(k)
                r = rows(e); v = e.screen()
                got = (v.row, v.col, r[v.row], r[0])
                check(f'vim undo-at {keys!r} {k!r}: {got[:2]} {got[2][:20]!r} '
                      f'== {(wrow, wcol)} {wcur[:20]!r}',
                      got == (wrow, wcol, expand(wcur).rstrip(),
                              expand(wtop).rstrip()))
            e.key(':w\r')
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim undo-at {keys!r}: file as vim wrote it ({got})',
                  got == sha)
        finally:
            e.close()

    # ---- a second 'u' is a redo here (vim's undoes further back, so it is
    #      no reference): the marks go with the text both ways ----
    e = Editor(text)
    try:
        for k in ('2G6lma', '2Gdd'):
            e.key(k)
        e.key('gg'); e.key('`a')
        gone = (e.screen().row, e.screen().col)
        e.key('u'); e.key('gg'); e.key('`a')
        check(f"dd over a mark, u: the mark is back ({e.screen().row}, "
              f"{e.screen().col})", (e.screen().row, e.screen().col) == (1, 8))
        e.key('u'); e.key('gg'); e.key('`a')
        check(f"... u again (redo): the mark is where the dd left it {gone}",
              (e.screen().row, e.screen().col) == gone and gone == (1, 0))
        e.key('u'); e.key('gg'); e.key('`a')
        check("... and a third u puts it back again",
              (e.screen().row, e.screen().col) == (1, 8))
    finally:
        e.close()

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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
                if UNDO_SKIP.get((f, tuple(keys))) == 'col' and k == 'u':
                    wcol = dc          # see UNDO_SKIP above
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
    # --- a change too big from its FIRST step leaves no record at all, and
    #     that is still 'too large', not 'nothing to undo': it rang the bell
    e = Editor(big)
    try:
        e.key('6000G'); e.key('2000dd')
        e.s.run_until_quiet(quiet=1.5, timeout=120)
        e.key('u')
        check(f"undo: a 16 K 'dd' says it is too large ({bottom(e)!r})",
              bottom(e) == 'Too large to undo')
        e.key(':w\r'); ex_settled(e)
        got = saved_bytes(e)
        check('undo: ... and the lines stay deleted',
              got == big[:5999 * 8] + big[7999 * 8:])
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


def idle(e, confirms=4, slices=20000):
    """Run the guest until it is waiting on the keyboard.  ``run_until_quiet``
    takes a slice that timed out drawing nothing for a settled one, and a
    command paging through 100 K draws nothing for most of a minute; only
    slices that stop IDLE count here, several in a row because an editor
    between two phases of one command idles briefly too."""
    n = 0
    for _ in range(slices):
        r = e.s._run()
        if r.get('stopped') == 'idle' and not r.get('output'):
            n += 1
            if n >= confirms:
                return
        else:
            n = 0
    raise RuntimeError('the guest never came back to the keyboard')


def stays_put(e, keys, msg, ln, tag):
    """*keys* page through the file and come to nothing: *msg* on the bottom
    row, the screen as it was -- and the cursor really on line *ln*, which the
    screen cannot show: nothing was repainted, so it would look right with the
    cursor anywhere.  '^G' says where it is, and a '^L' has to draw the same
    screen again from the text."""
    v0 = e.screen()
    scr0 = [''.join(r) for r in v0.screen]
    e.s.send(keys)
    idle(e)
    v = e.screen()
    scr = [''.join(r) for r in v.screen]
    check(f'{tag}: {keys!r} shows {msg!r} ({bottom(e)!r})', bottom(e) == msg)
    check(f'{tag}: {keys!r} keeps the screen and the cursor',
          scr[:23] == scr0[:23] and (v.row, v.col) == (v0.row, v0.col))
    e.s.send('\x07')
    idle(e)
    check(f'{tag}: {keys!r} leaves the cursor on line {ln} ({bottom(e)!r})',
          f'line {ln} ' in bottom(e))
    e.s.send('\x0c')
    idle(e)
    v = e.screen()
    scr = [''.join(r) for r in v.screen]
    check(f'{tag}: {keys!r} and a repaint draws the same screen',
          scr[:23] == scr0[:23] and (v.row, v.col) == (v0.row, v0.col))


def srch_cmds():
    """A search that finds nothing puts the cursor back where it started, in
    the FILE: the sweep has paged the window to the far end and round again by
    then, so the place cannot be kept as an offset into the window."""
    e = Editor(make(12800))
    try:
        for start, keys in ((6000, '/zzzz\r'), (6000, '?zzzz\r'),
                            (100, '/zzzz\r'), (12700, '?zzzz\r')):
            e.s.send(f'{start}G')
            idle(e)
            stays_put(e, keys, 'Pattern not found: zzzz', start,
                      f'srch miss from {start}')
    finally:
        e.close()


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
     [(21, 0, '001500QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ', '001484')]),
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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
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
    # --- ... and so does a miss over a file the walk has to page through ---
    e = Editor(make(12800))
    try:
        e.s.send('6000G')
        idle(e)
        stays_put(e, ':%s/zzzz/Q/\r', 'Pattern not found: zzzz', 6000,
                  'subst paged miss')
        stays_put(e, ':100,200s/zzzz/Q/\r', 'Pattern not found: zzzz', 6000,
                  'subst paged ranged miss')
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
      (4, 83, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 89, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 95, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 101, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '')]),
    ('wd', ['/ab-cd\r', '15n'], '5c9f0580f938e2cb',
     [(3, 11, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 101, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '')]),
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
      (4, 83, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 89, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 95, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 101, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 95, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', ''),
      (4, 89, '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '')]),
    ('wd', ['/x,y\r', 'n', 'n'], '5c9f0580f938e2cb',
     [(1, 17, '\t  00002  x,y;;z  ', ''),
      (13, 17, '\t  00012  x,y;;z  ', ''),
      (22, 17, '\t  00022  x,y;;z  ', '(00004)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd')]),
    # ('wide', /xxx ...) is deliberately NOT here: 'xxx' can overlap itself,
    # and in a run of x's vim tiles matches NON-OVERLAPPING from the line's
    # first one (searchpos from column 8 answers 9, not 9-because-of-cursor+1;
    # 'xx' steps by 2 and 'xxx' by 3) where this editor finds every match.
    # See COMMANDS.md.  The long-line rows below use 'ab-cd', which cannot
    # overlap itself, so they still cover the pan past the right screen edge.
    ('wide', ['/001497\r'], 'cf4987bfafeec1cc',
     [(15, 0, '001497xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('wide', ['G', '?000501\r'], 'cf4987bfafeec1cc',
     [(20, 0, '001500xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '001488xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
      (10, 0, '000501xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '000495xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]),
    ('wd', ['G', '?ab-cd\r', 'n'], '5c9f0580f938e2cb',
     [(22, 0, '03300 foo.bar(baz) qux_1', '\t  03282  x,y;;z  '),
      (16, 197, '(03294)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '\t  03282  x,y;;z  '),
      (16, 191, '(03294)--> ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd ab-cd', '\t  03282  x,y;;z  ')]),
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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
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
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
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

    # ... and a match past the right edge is on the line's next row: there is
    # no pan to repaint for, so that is a cursor move like any other.
    e = Editor(files['wd'])
    try:
        e.key('/ab-cd\r')
        near = wire(e, 'n')                  # column 17
        for _ in range(11):
            e.key('n')                       # ... up to column 83: past the edge
        row = e.screen().row
        far = wire(e, 'n')
        v = e.screen()
        dc, lr = curs(e, v)
        check(f'wd: the n that crosses column 80 is a cursor move too ({far} '
              f'bytes vs {near}), onto the next row ({v.row}, {v.col})',
              far < 64 and dc >= 80 and v.row == lr + 1)
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
            send_keys(e, '\x1b')
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
    # --- '%' is not a motion in this editor, and an operator on it must
    #     cancel like 'cq' above.  A key left in OPCTAB with no CMDTAB row is
    #     not inert: OPPEND takes the class, VSCAN finds no handler so the
    #     cursor does not move, and the inclusive INX H turns the empty span
    #     into one character -- 'df' became 'x' and 'cf' became 's', silently,
    #     for exactly as long as 'f F t T ; , %' stayed classed here after
    #     their handlers were cut.  f F t T are built again now (group 'find'),
    #     and build_vi.py's check_tables refuses any link where an OPCTAB key
    #     has no CMDTAB row, so this case is the last one left: '%'. ---
    for op in 'dc':
        for mot in '%':
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
    # --- ';' and ',' ARE motions now, but a repeat with nothing to repeat is
    #     refused, and it has to take the operator with it: the find that never
    #     happened must not leave 'd' pending to eat the next key. ---
    for op in 'dc':
        for mot in ';,':
            e = Editor(files['bl'])
            try:
                send_keys(e, op + mot)
                check(f'{op}{mot}: no find to repeat, so nothing is deleted '
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



# ---------------------------------------------------------------------------
# Long lines WRAP, as vi's and vim's do: a line wider than the screen goes on
# down the rows under it, and a line that will not fit whole at the bottom of
# the screen is not shown at all -- its rows hold '@'.
# ---------------------------------------------------------------------------
def wrap_files():
    """'w1' fits one screen whatever is done to it here: a 200-column line, one
    exactly as wide as the screen, one a column wider, TABs across the edge,
    words across the edge.  'w2' ends in a line the screen has no room for."""
    w1 = ['one', WIDE, 'three', 'x' * 80, 'five', 'y' * 81,
          '\t' * 11 + 'tab', 'eight', 'a\tb' + ' word' * 30, 'ten']
    w2 = ['L%02d' % i for i in range(1, 22)] + [WIDE, 'end']
    return {'w1': ''.join(l + '\r\n' for l in w1).encode(),
            'w2': ''.join(l + '\r\n' for l in w2).encode(),
            'w3': ''.join(l + '\r\n' for l in prose_lines()).encode(),
            'w4': ''.join(l + '\r\n' for l in tall_lines()).encode(),
            'w5': ''.join(l + '\r\n' for l in [rows_of('F', 40), 'mid',
                                               rows_of('G', 30)[:-10]]).encode(),
            'w6': ''.join(l + '\r\n' for l in tall_paged()).encode()}


def rows_of(tag, n):
    """A line *n* screen rows long, every row saying which one it is."""
    return ''.join('%s%03d.' % (tag, r) + 'x' * 75 for r in range(n))


def tall_lines():
    """Lines taller than the screen among short ones: 30 rows, 60, 24 with one
    character on the last, and 30 rows of TABs."""
    out = ['S%02d short' % i for i in range(1, 6)]
    out.append(rows_of('A', 30)[:-40])
    out += ['S07 short', 'S08 short', rows_of('B', 60), 'S10 short',
            rows_of('C', 24)[:-79]]
    out += ['S%02d short' % i for i in range(12, 20)]
    out.append(''.join('\tD%03d' % i for i in range(300)))
    out += ['S%02d short' % i for i in range(21, 40)]
    return out


def tall_paged():
    """86 K of them, 24 to 45 rows each with a short line between, so the
    lines above and below the one on the screen are out on the disk."""
    out = []
    for i in range(1, 31):
        out += [rows_of('%c%02d' % (65 + i % 26, i), 24 + (i * 7) % 22), 'short %02d' % i]
    return out


# Paragraphs typed as one line each, as prose is: 1 to 22 rows tall, so a
# screen holds anything from two lines to twenty and no two screens alike.
PROSE = [60, 330, 0, 700, 95, 1200, 40, 160, 480, 80, 81, 950, 20, 1700, 240, 5, 1040, 400]


def prose_lines(n=200):
    """*n* lines of PROSE's widths in turn, each starting with its number
    (75 K at 200 lines, so it pages)."""
    out = []
    for i in range(1, n + 1):
        w = PROSE[(i - 1) % len(PROSE)]
        t = 'P%04d ' % i + ''.join('w%d ' % (j % 97) for j in range(w // 3 + 1))
        out.append(t[:w])
    return out


def wrapped(lines, top=1, n=23, w=80, skip=0):
    """The edit rows a screen starting at line *top* (1-based) shows.  With
    *skip*, that line's first *skip* rows are off the top, and '<<<' over the
    first cells says so."""
    out = []
    for l in lines[top - 1:]:
        x = expand(l)
        chunks = [x[i:i + w] for i in range(0, len(x), w)] or ['']
        if skip:
            chunks = chunks[skip:]
            chunks[0] = '<<<' + chunks[0][3:]
            skip = 0
        if len(out) + len(chunks) > n:
            # the top line is shown as far as the screen goes; any other
            # that does not fit is not shown at all
            out += chunks[:n] if not out else ['@'] * (n - len(out))
            break
        out += chunks
    out += ['~'] * (n - len(out))
    return [c.rstrip() for c in out]


# (file, keys, [cursor line, top line, cursor row, cursor column after each
# key]) from vim 9.1 (-u NONE -N, 24 lines, 'wrap'), regenerable with
# `python3 vimref.py --print wrap`.  The row is the cursor's own screen row,
# so it counts the rows a wrapped line has above the cursor, and the column is
# the virtual one: 80 and up is the line's second row.
VIM_WRAP = [
    ('w1', ['j', '$', '0', '79l', 'l', '80l', 'h', 'j', 'k', 'j', 'j', '$', 'j', '$', 'j', '$'],
     ['2 1 1 0', '2 1 3 199', '2 1 1 0', '2 1 1 79', '2 1 2 80', '2 1 3 160', '2 1 2 159',
      '3 1 4 4', '2 1 2 159', '3 1 4 4', '4 1 5 79', '4 1 5 79', '5 1 6 3', '5 1 6 3',
      '6 1 8 80', '6 1 8 80']),
    ('w1', ['G', 'k', '$', 'b', '0', 'w', 'w', 'k', 'k', '$', '0', 'l', 'k', '$', 'gg'],
     ['10 1 14 0', '9 1 12 0', '9 1 13 158', '9 1 13 155', '9 1 12 0', '9 1 12 8', '9 1 12 10',
      '8 1 11 4', '7 1 9 15', '7 1 10 90', '7 1 9 7', '7 1 9 15', '6 1 7 15', '6 1 8 80',
      '1 1 0 0']),
    ('w1', ['2G', '150l', 'j', 'j', 'j', 'j', 'j', 'j', 'j', 'k', 'k', 'k', 'k', 'k', 'k', 'k'],
     ['2 1 1 0', '2 1 2 150', '3 1 4 4', '4 1 5 79', '5 1 6 3', '6 1 8 80', '7 1 10 90',
      '8 1 11 4', '9 1 13 150', '8 1 11 4', '7 1 10 90', '6 1 8 80', '5 1 6 3', '4 1 5 79',
      '3 1 4 4', '2 1 2 150']),
    ('w1', ['/Z\r', 'n', 'n', 'n', 'n', 'N', '/word\r', 'n', '10n', '?tab\r'],
     ['2 1 1 25', '2 1 1 51', '2 1 1 77', '2 1 2 103', '2 1 2 129', '2 1 2 103', '9 1 12 10',
      '9 1 12 15', '9 1 12 65', '7 1 10 88']),
    ('w1', ['L', 'H', 'M', '7G', 'w', '$', 'M', '4G', '$', 'j', 'k', '6G', '$', 'h', 'h'],
     ['10 1 14 0', '1 1 0 0', '6 1 7 0', '7 1 10 88', '8 1 11 0', '8 1 11 4', '6 1 7 0', '4 1 5 0',
      '4 1 5 79', '5 1 6 3', '4 1 5 79', '6 1 7 0', '6 1 8 80', '6 1 7 79', '6 1 7 78']),
    ('w2', ['G', 'gg', '20j', 'j', 'j', 'k', 'k'],
     ['23 3 22 0', '1 1 0 0', '21 1 20 0', '22 2 20 0', '23 3 22 0', '22 3 19 0', '21 3 18 0']),
    ('w3', ['\x06', '\x06', '\x06', '\x06', '\x06', '\x06', '\x06', '\x06', '\x02', '\x02', '\x02', '\x02', '\x02', '\x02', '\x02', '\x02'],
     ['6 6 0 0', '9 9 0 0', '14 14 0 0', '15 15 0 0', '18 18 0 0', '23 23 0 0', '27 27 0 0',
      '32 32 0 0', '31 27 21 0', '26 23 18 0', '23 18 21 0', '19 15 22 0', '14 13 1 0',
      '12 8 11 0', '8 5 18 0', '5 1 16 0']),
    ('w3', ['\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15'],
     ['4 4 0 0', '6 6 0 0', '7 7 0 0', '11 11 0 0', '12 12 0 0', '13 13 0 0', '14 14 0 0',
      '15 15 0 0', '17 17 0 0', '18 18 0 0', '17 17 0 0', '15 15 0 0', '14 14 0 0', '13 13 0 0',
      '12 12 0 0', '8 8 0 0', '7 7 0 0', '6 6 0 0', '4 4 0 0', '1 1 0 0']),
    ('w3', ['3\x06', '2\x02', '5\x04', '\x04', '\x15', '9\x15', 'M', 'H', 'L', 'M'],
     ['14 14 0 0', '8 5 18 0', '9 7 3 0', '9 9 0 0', '7 7 0 0', '6 6 0 0', '6 6 0 0', '6 6 0 0',
      '8 6 16 0', '6 6 0 0']),
    ('w3', ['G', '\x02', '\x02', 'M', '\x06', '\x06', '\x15', '\x04', '\x04', '\x04'],
     ['200 198 6 0', '199 195 22 0', '194 193 1 0', '194 193 1 0', '195 195 0 0', '198 198 0 0',
      '197 197 0 0', '200 198 6 0', '200 198 6 0', '200 198 6 0']),
    ('w3', ['150G', 'M', '10j', '10j', '10j', '5k', '5k', '5k', '5k', 'M', '\x04', 'M', '\x15', 'M'],
     ['150 149 2 0', '150 149 2 0', '160 159 3 0', '170 169 1 0', '180 179 13 0', '175 175 0 0',
      '170 170 0 0', '165 165 0 0', '160 160 0 0', '161 160 1 0', '161 161 0 0', '161 161 0 0',
      '159 159 0 0', '161 159 4 0']),
    ('w3', ['40G', '45G', '50G', '56G', '70G', '64G', '60G', '58G', '90G', '79G'],
     ['40 38 6 0', '45 43 3 0', '50 49 1 0', '56 54 6 0', '70 69 3 0', '64 64 0 0', '60 60 0 0',
      '58 58 0 0', '90 89 13 0', '79 78 15 0']),
    ('w3', ['100G', '\x06', 'k', '\x02', 'j', '\x04', 'L', 'j', 'j', 'j', 'H', 'k', 'k', 'k'],
     ['100 98 8 0', '102 102 0 0', '101 101 0 0', '101 97 10 0', '102 98 11 0', '102 102 0 0',
      '103 102 12 0', '104 103 1 0', '105 105 0 0', '106 105 3 0', '105 105 0 0', '104 104 0 0',
      '103 103 0 0', '102 102 0 0']),
    ('w3', ['G', '50\x02', '30\x06', '20\x02', '7\x06', '\x04', '\x04', '\x04', '\x04'],
     ['200 198 6 0', '19 15 22 0', '126 126 0 0', '59 54 21 0', '84 84 0 0', '85 85 0 0',
      '86 86 0 0', '87 87 0 0', '89 89 0 0']),
    ('w3', ['G', '\x02', '\x04', '\x04', '\x04', '\x04', '\x15', '\x15', '\x15'],
     ['200 198 6 0', '199 195 22 0', '200 198 6 0', '200 198 6 0', '200 198 6 0', '200 198 6 0',
      '197 197 0 0', '195 195 0 0', '194 194 0 0']),
    ('w3', ['\x04', '\x15', '\x15', '\x06', '\x02', '\x02', '5j', '\x15', '\x15'],
     ['4 4 0 0', '1 1 0 0', '1 1 0 0', '6 6 0 0', '5 1 16 0', '5 1 16 0', '10 8 8 0', '9 7 3 0',
      '6 6 0 0']),
    ('w3', ['30G', '$', '\x04', '$', '\x04', '$', '\x15', '$', '\x15', '$', '\x06', '$', '\x02'],
     ['30 29 2 0', '30 29 13 949', '32 31 1 0', '32 31 22 1699', '33 33 0 0', '33 33 2 239',
      '32 32 0 0', '32 32 21 1699', '32 31 1 0', '32 31 22 1699', '33 33 0 0', '33 33 2 239',
      '32 31 1 0']),
    ('w3', ['/P0123\r', '/P0131\r', '/P0140\r', '?P0128\r', '?P0120\r', '/P0199\r', 'n'],
     ['123 123 0 0', '131 130 9 0', '140 139 1 0', '128 126 6 0', '120 120 0 0', '199 198 5 0',
      '199 198 5 0']),
    ('w3', ['60G', '12\x04', '\x04', '3\x15', '\x15', '23\x04', '\x04', '99\x15', '\x15'],
     ['60 59 2 0', '60 60 0 0', '61 61 0 0', '60 60 0 0', '59 59 0 0', '63 63 0 0', '68 68 0 0',
      '63 63 0 0', '59 59 0 0']),
    ('w3', ['77G', 'L', '\x06', 'H', '\x02', 'L', '\x02', 'H', '\x06', 'M'],
     ['77 77 0 0', '80 77 18 0', '81 81 0 0', '81 81 0 0', '80 77 18 0', '80 77 18 0',
      '77 72 21 0', '72 72 0 0', '77 77 0 0', '78 77 2 0']),
    # --- lines taller than the screen ('w4' 'w5'), and a file of them ('w6') ---
    # (No row shortens a line from 24 rows to 23 with the cursor on its last:
    # vim then shows all of it but reports winline() a row too high for one
    # key.  wrap_cmds checks that case against the screen itself.  And none
    # moves along a line with a big counted 'l': that is slow, issue #26.)
    ('w4', ['6G', '$', '0', '/A010\r', '/A020\r', '/A029\r', '80h', '?A021\r', '?A011\r', '?A001\r', '0', 'j', 'j', 'j', '$', 'k', 'k', 'k', 'k'],
     ['6 6 0 0', '6 6 22 2359', '6 6 0 0', '6 6 10 800', '6 6 20 1600', '6 6 22 2320',
      '6 6 21 2240', '6 6 14 1680', '6 6 4 880', '6 6 0 80', '6 6 0 0', '7 7 0 0', '8 7 1 0',
      '9 9 0 0', '9 9 22 4799', '8 8 0 8', '7 7 0 8', '6 6 22 2359', '5 5 0 8']),
    ('w4', ['6G', '\x04', '\x04', '\x04', '\x15', '\x15', '\x15', '$', '\x04', '\x15', '\x15', '\x04'],
     ['6 6 0 0', '7 7 0 0', '9 9 0 0', '10 10 0 0', '9 9 0 0', '7 7 0 0', '6 6 0 0', '6 6 22 2359',
      '9 9 0 0', '7 7 0 0', '6 6 0 0', '7 7 0 0']),
    ('w4', ['\x06', '\x06', '\x06', '\x06', '\x06', '\x06', '\x02', '\x02', '\x02', '\x02', '\x02', '\x02'],
     ['6 6 0 0', '7 7 0 0', '9 9 0 0', '10 10 0 0', '11 11 0 0', '12 12 0 0', '11 11 0 0',
      '10 10 0 0', '9 9 0 0', '8 7 1 0', '6 6 0 0', '5 1 4 0']),
    ('w4', ['9G', '$', '\x06', '\x02', '\x02', '\x02', 'G', '\x02', '\x02', '\x02', '\x02', '\x02', '\x02'],
     ['9 9 0 0', '9 9 22 4799', '10 10 0 0', '9 9 0 0', '8 7 1 0', '6 6 0 0', '39 21 18 0',
      '20 20 0 8', '19 12 7 0', '11 11 0 0', '10 10 0 0', '9 9 0 0', '8 7 1 0']),
    ('w4', ['6G', '/A012\r', '/A020\r', '/A029\r', '?A003\r', 'n', 'N', '/B050\r', '?A011\r', '/B02\r', 'n', 'n', 'n', 'n', 'N'],
     ['6 6 0 0', '6 6 12 960', '6 6 20 1600', '6 6 22 2320', '6 6 0 240', '6 6 0 240', '6 6 0 240',
      '9 9 22 4000', '6 6 11 880', '9 9 20 1600', '9 9 21 1680', '9 9 22 1760', '9 9 22 1840',
      '9 9 22 1920', '9 9 21 1840']),
    ('w4', ['4G', '11G', '6G', '9G', '20G', '$', '0', 'w', '$', 'b', 'b', 'j', 'k', '30G', '20G'],
     ['4 1 3 0', '11 11 0 0', '6 6 0 0', '9 9 0 0', '20 20 0 8', '20 20 22 2403', '20 20 0 7',
      '20 20 0 8', '20 20 22 2403', '20 20 22 2400', '20 20 21 2392', '21 21 0 8', '20 20 22 2392',
      '30 21 9 0', '20 20 0 8']),
    ('w4', ['6G', '$', 'H', '6G', '$', 'M', '6G', '$', 'L', '9G', '$', '0', '$', '^'],
     ['6 6 0 0', '6 6 22 2359', '6 6 0 0', '6 6 0 0', '6 6 22 2359', '6 6 0 0', '6 6 0 0',
      '6 6 22 2359', '6 6 0 0', '9 9 0 0', '9 9 22 4799', '9 9 0 0', '9 9 22 4799', '9 9 0 0']),
    ('w4', ['11G', '$', 'j', 'k', '0', '$', '0', '12G', 'k', '$', 'k', 'j'],
     ['11 11 0 0', '11 11 22 1840', '12 12 0 8', '11 11 22 1840', '11 11 0 0', '11 11 22 1840',
      '11 11 0 0', '12 12 0 0', '11 11 0 0', '11 11 22 1840', '10 10 0 8', '11 11 22 1840']),
    ('w4', ['\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15'],
     ['6 6 0 0', '7 7 0 0', '9 9 0 0', '10 10 0 0', '11 11 0 0', '12 12 0 0', '20 20 0 8',
      '12 12 0 0', '11 11 0 0', '10 10 0 0', '9 9 0 0', '7 7 0 0', '6 6 0 0', '1 1 0 0']),
    ('w4', ['9G', '/B010\r', '5\x04', '\x15', '\x15', '/B010\r', '\x15', '\x04', '\x04', '20G', '$', '\x04', '\x15', '$', '3\x15', '\x04'],
     ['9 9 0 0', '9 9 10 800', '11 11 0 0', '10 10 0 0', '9 9 0 0', '9 9 10 800', '9 9 0 0',
      '10 10 0 0', '11 11 0 0', '20 20 0 8', '20 20 22 2403', '39 21 18 0', '20 20 0 8',
      '20 20 22 2403', '20 20 0 8', '21 21 0 0']),
    ('w4', ['20G', '100w', '100w', '60w', '60w', '100b', '100b', '$', '100b', '0'],
     ['20 20 0 8', '20 20 10 808', '20 20 20 1608', '20 20 22 2088', '31 21 10 0', '20 20 22 1768',
      '20 20 12 968', '20 20 22 2403', '20 20 12 1608', '20 20 0 7']),
    ('w5', ['\x04', '\x04', '\x04', '\x04', '\x15', '\x15', '\x15', '\x15', '$', '\x04', '\x04', '\x15', '\x15'],
     ['2 2 0 0', '3 3 0 0', '3 3 0 0', '3 3 0 0', '2 2 0 0', '1 1 0 0', '1 1 0 0', '1 1 0 0',
      '1 1 22 3199', '3 3 0 0', '3 3 0 0', '2 2 0 0', '1 1 0 0']),
    ('w5', ['G', '/G005\r', '\x04', '\x04', '\x15', '\x15', '\x15', '\x15', 'G', '$', '5\x15', '\x15', '\x15'],
     ['3 3 0 0', '3 3 5 400', '3 3 0 0', '3 3 0 0', '2 2 0 0', '1 1 0 0', '1 1 0 0', '1 1 0 0',
      '3 3 0 0', '3 3 22 2389', '3 3 0 0', '2 2 0 0', '1 1 0 0']),
    ('w5', ['\x06', '\x06', '\x06', '\x02', '\x02', '\x02', 'G', '$', '\x02', '\x02', '\x06', '\x06', '/G015\r', '\x06', '\x02'],
     ['2 2 0 0', '3 3 0 0', '3 3 0 0', '2 2 0 0', '1 1 0 0', '1 1 0 0', '3 3 0 0', '3 3 22 2389',
      '2 2 0 0', '1 1 0 0', '2 2 0 0', '3 3 0 0', '3 3 15 1200', '3 3 0 0', '2 2 0 0']),
    ('w5', ['$', '0', '$', 'j', 'j', '$', 'k', 'k', 'gg', 'G', '$', 'gg', '/G02\r', 'n', 'n', 'n', 'n', 'n', '?F03\r', 'n', 'n', 'N'],
     ['1 1 22 3199', '1 1 0 0', '1 1 22 3199', '2 2 0 2', '3 3 22 2389', '3 3 22 2389', '2 2 0 2',
      '1 1 22 3199', '1 1 0 0', '3 3 0 0', '3 3 22 2389', '1 1 0 0', '3 3 20 1600', '3 3 21 1680',
      '3 3 22 1760', '3 3 22 1840', '3 3 22 1920', '3 3 22 2000', '1 1 22 3120', '1 1 21 3040',
      '1 1 20 2960', '1 1 21 3040']),
    ('w6', ['\x06', '\x06', '\x06', '\x06', '\x06', '\x06', '\x06', '\x06', '\x02', '\x02', '\x02', '\x02', '\x02', '\x02', '\x02', '\x02'],
     ['2 2 0 0', '3 3 0 0', '4 4 0 0', '5 5 0 0', '6 6 0 0', '7 7 0 0', '8 8 0 0', '9 9 0 0',
      '8 8 0 0', '7 7 0 0', '6 6 0 0', '5 5 0 0', '4 4 0 0', '3 3 0 0', '2 2 0 0', '1 1 0 0']),
    ('w6', ['\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x04', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15', '\x15'],
     ['2 2 0 0', '3 3 0 0', '4 4 0 0', '5 5 0 0', '6 6 0 0', '7 7 0 0', '8 8 0 0', '9 9 0 0',
      '8 8 0 0', '7 7 0 0', '6 6 0 0', '5 5 0 0', '4 4 0 0', '3 3 0 0', '2 2 0 0', '1 1 0 0']),
    ('w6', ['G', '\x02', '\x02', '\x02', '\x06', '\x06', '\x06', '20G', '$', '40G', '$', 'k', '$', 'j', 'j', '$'],
     ['60 60 0 0', '59 59 0 0', '58 58 0 0', '57 57 0 0', '58 58 0 0', '59 59 0 0', '60 60 0 0',
      '20 20 0 0', '20 20 0 7', '40 40 0 0', '40 40 0 7', '39 39 22 2623', '39 39 22 2623',
      '40 40 0 7', '41 41 22 3197', '41 41 22 3197']),
    ('w6', ['$', 'j', 'j', '$', 'j', 'j', '$', '0', '10j', '$', '10j', '$', '10k', '$', 'gg'],
     ['1 1 22 2541', '2 2 0 7', '3 3 22 3115', '3 3 22 3115', '4 4 0 7', '5 5 22 3689',
      '5 5 22 3689', '5 5 0 0', '15 15 0 0', '15 15 22 2951', '25 25 22 2213', '25 25 22 2213',
      '15 15 22 2951', '15 15 22 2951', '1 1 0 0']),
    ('w6', ['/K10020\r', '/O14030\r', '?E04010\r', '/B27035\r', 'n', '?short 05\r', '/Y24\r', 'n', 'n'],
     ['19 19 20 1640', '27 27 22 2460', '7 7 10 820', '53 53 22 2870', '53 53 22 2870',
      '10 10 0 0', '47 47 0 0', '47 47 1 82', '47 47 2 164']),
    ('w6', ['30G', 'M', 'L', 'H', '31G', 'M', 'L', 'H', '$', 'M'],
     ['30 30 0 0', '30 30 0 0', '30 30 0 0', '30 30 0 0', '31 31 0 0', '31 31 0 0', '31 31 0 0',
      '31 31 0 0', '31 31 22 2131', '31 31 0 0']),
]


def wrap_like_vim():
    """Motions over wrapped lines put the cursor on vim's row and column, and
    the screen holds every line whole, across as many rows as it needs."""
    files = wrap_files()
    for f, keys, want in VIM_WRAP:
        lines = files[f].decode().split('\r\n')[:-1]
        e = Editor(files[f])
        try:
            for k, w in zip(keys, want):
                e.key(k)
                v = e.screen()
                dc, lr = curs(e, v)
                scr = [''.join(r).rstrip() for r in v.screen]
                ln, top, row, col = map(int, w.split())
                got = '%d %d' % (v.row, dc)
                tag = f'wrap {f} {keys!r} {k!r}'
                check(f'{tag}: {got} == {row} {col}', got == '%d %d' % (row, col))
                # a line taller than the screen: vim shows it from the row
                # that keeps the cursor on the screen
                skip = col // 80 - row if ln == top else 0
                check(f'{tag}: the screen is the file from line {top}, wrapped'
                      + (f', less {skip} rows' if skip else ''),
                      scr[:23] == wrapped(lines, top, skip=skip))
            check(f'wrap {f} {keys!r}: motions leave the file unmodified',
                  at_ccp(e, ':q\r'))
        finally:
            e.close()


def wrap_cmds():
    """Editing where a line meets the right edge: the screen is re-wrapped
    whenever a line gains or loses a row, the cursor follows its character
    onto the next row, and what is written back is the text."""
    files = wrap_files()
    lines = files['w1'].decode().split('\r\n')[:-1]

    def frame(e, tag, row, col):
        v = e.screen()
        scr = [''.join(r).rstrip() for r in v.screen]
        check(f'wrap: {tag}: cursor at ({v.row}, {v.col}) == ({row}, {col})',
              (v.row, v.col) == (row, col))
        check(f'wrap: {tag}: the screen is the text, wrapped',
              scr[:23] == wrapped(lines))

    e = Editor(files['w1'])
    try:
        frame(e, 'as loaded', 0, 0)
        # --- a line exactly as wide as the screen is one row; a char more and
        #     it is two, and everything under it moves down a row ---
        e.key('4G$'); frame(e, '$ on the 80-column line', 5, 79)
        e.key('aQ'); lines[3] += 'Q'
        frame(e, 'a 81st char typed: the cursor is on the next row', 6, 1)
        send_keys(e, '\x1b'); frame(e, '... and ESC steps back onto it', 6, 0)
        e.key('x'); lines[3] = lines[3][:-1]
        frame(e, 'x takes the row away again', 5, 79)
        # --- appending at the end of a line that fills its row: the cursor has
        #     nowhere to stand but the next row, which the line then owns ---
        e.key('A')
        v = e.screen()
        check(f'wrap: A on a full row: the cursor waits on the next row '
              f'({v.row}, {v.col})', (v.row, v.col) == (6, 0))
        check('wrap: ... and the lines under it have moved down to make it',
              [''.join(r).rstrip() for r in v.screen][7] == 'five')
        send_keys(e, '\x1b'); frame(e, 'ESC gives the row back', 5, 79)
        # --- typing in the middle pushes the tail across the edge ---
        e.key('1GA' + '-' * 77); lines[0] += '-' * 77
        send_keys(e, '\x1b'); frame(e, 'a short line typed out to 80', 0, 79)
        e.key('0iab'); lines[0] = 'ab' + lines[0]
        send_keys(e, '\x1b'); frame(e, 'two chars inserted at its start', 0, 1)
        e.key('$'); frame(e, '... its end is on the second row', 1, 1)
        # --- a wrapped line deleted, joined, split and put back ---
        e.key('2Gdd'); gone = lines.pop(1); frame(e, 'dd of a 3-row line', 2, 0)
        e.key('P'); lines.insert(1, gone); frame(e, 'P puts the 3 rows back', 2, 0)
        e.key('J'); lines[1:3] = [lines[1] + ' ' + lines[2]]
        frame(e, 'J onto a wrapped line', 4, 40)
        e.key('0'); e.key('99li\r'); lines[1:2] = [lines[1][:99], lines[1][99:]]
        send_keys(e, '\x1b'); frame(e, '<CR> inside a wrapped line', 4, 0)
        e.key('u'); lines[1:3] = [lines[1] + lines[2]]
        frame(e, 'u joins them up again', 3, 19)
        # --- TABs keep their stops in the LINE's columns across the edge ---
        k = lines.index('\t' * 11 + 'tab') + 1
        e.key('%dG0' % k)
        r0 = sum(len(c) for c in [[x for x in range(0, max(len(expand(l)), 1), 80)]
                                   for l in lines[:k - 1]])
        frame(e, 'on the first TAB: its last column', r0, 7)
        e.key('10l'); frame(e, 'on the 11th TAB: column 87, the next row', r0 + 1, 7)
        e.key('ix'); lines[k - 1] = '\t' * 10 + 'x\t' + 'tab'
        send_keys(e, '\x1b'); frame(e, 'a char typed before it', r0 + 1, 0)
        e.key(':w\r'); e.key(':q\r')
        check('wrap: the edits are written back byte-exact',
              saved_bytes(e) == ''.join(l + '\r\n' for l in lines).encode())
    finally:
        e.close()

    # --- a line the bottom of the screen has no room for is '@' rows, and a
    #     move onto it gives up just enough lines at the top to show it ---
    lines = files['w2'].decode().split('\r\n')[:-1]
    e = Editor(files['w2'])
    try:
        scr = rows(e)
        check(f'wrap: the line that does not fit is two @ rows ({scr[20:23]!r})',
              scr[20:23] == ['L21', '@', '@'])
        e.key('21j')
        scr = rows(e)
        check(f'wrap: on it, it is all there ({scr[0]!r} .. {scr[22][:8]!r})',
              scr[:23] == wrapped(lines, 2))
        # --- a move that changes nothing on the screen sends no frame, long
        #     lines or not ---
        before = len(e.cap.getvalue())
        e.key('$')
        sent = len(e.cap.getvalue()) - before
        v = e.screen()
        check(f'wrap: $ along a wrapped line is a cursor move ({sent} bytes) '
              f'to ({v.row}, {v.col})', sent < 64 and (v.row, v.col) == (22, 39))
        check('wrap: nothing was modified (:q exits)', at_ccp(e, ':q\r'))
    finally:
        e.close()

    # --- a line taller than the screen is shown from the row that keeps the
    #     cursor on it ('<<<' over its first cells), and stays that way while
    #     it is edited; one that an edit brings back to the screen's height
    #     is shown whole again ---
    lines = files['w4'].decode().split('\r\n')[:-1]

    def tall(e, tag, top, skip, row, col):
        v = e.screen()
        scr = [''.join(r).rstrip() for r in v.screen]
        check(f'wrap: {tag}: cursor at ({v.row}, {v.col}) == ({row}, {col})',
              (v.row, v.col) == (row, col))
        check(f'wrap: {tag}: the screen is line {top} on, less {skip} rows',
              scr[:23] == wrapped(lines, top, skip=skip))

    e = Editor(files['w4'])
    try:
        e.key('11G'); e.key('$')
        tall(e, '$ on a 24-row line', 11, 1, 22, 0)
        e.key('x'); lines[10] = lines[10][:-1]
        tall(e, 'x leaves it 23 rows: all of it is shown', 11, 0, 22, 79)
        e.key('aQ'); lines[10] += 'Q'
        tall(e, 'a char typed makes it 24 again', 11, 1, 22, 1)
        send_keys(e, '\x1b'); tall(e, '... and ESC steps back onto it', 11, 1, 22, 0)
        e.key('0'); tall(e, '0 shows it from its first row', 11, 0, 0, 0)
        e.key('6G'); e.key('$')
        tall(e, '$ on a 30-row line', 6, 7, 22, 39)
        e.key('iZ'); lines[5] = lines[5][:-1] + 'Z' + lines[5][-1]
        send_keys(e, '\x1b'); tall(e, 'a char typed on its last row', 6, 7, 22, 39)
        e.key('?A015\r'); e.key('iab'); lines[5] = lines[5][:1200] + 'ab' + lines[5][1200:]
        send_keys(e, '\x1b')
        tall(e, 'two typed in the middle of it: the rows under them shift', 6, 7, 8, 1)
        e.key('u'); lines[5] = lines[5][:1200] + lines[5][1202:]
        tall(e, 'u takes them back', 6, 7, 8, 0)
        e.key('$'); e.key('dd'); gone = lines.pop(5)
        tall(e, 'dd of it: the next line is the top one', 6, 0, 0, 0)
        e.key('P'); lines.insert(5, gone)
        tall(e, 'P puts all 30 rows back, from the first', 6, 0, 0, 0)
        e.key('k'); tall(e, 'k: the line above, and @ where it will not fit', 5, 0, 0, 0)
        e.key('J'); lines[4:6] = [lines[4] + ' ' + lines[5]]
        tall(e, 'J makes one line of the two', 5, 0, 0, 9)
        e.key('$'); tall(e, '... 30 rows, and $ is on the last', 5, 7, 22, 50)
        e.key(':w\r'); e.key(':q\r')
        check('wrap: edits to lines taller than the screen are written back '
              'byte-exact', saved_bytes(e) == ''.join(l + '\r\n' for l in lines).encode())
    finally:
        e.close()


def paint_lines():
    """Lines of 1 to 5 rows, every screen row saying which line's which row it
    is -- so a row on the screen after a key is either one that was there
    before it or one the key had to draw, and there is no mistaking them."""
    hs = [1, 3, 1, 2, 1, 1, 4, 1, 2, 1, 5, 1, 1, 3, 2, 1]
    out = []
    for i in range(1, 61):
        h = hs[(i - 1) % len(hs)]
        t = ''.join(('L%02d.%02d ' % (i, r)).ljust(80, 'x') for r in range(h))
        out.append(t[:len(t) - 71 + (7 * i) % 60])
    return out


def new_rows(old, new):
    """The rows of *new* that a longest common subsequence with *old* leaves
    out: what a painter free to shift rows up and down would still draw."""
    n, m = len(old), len(new)
    L = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            L[i][j] = (L[i + 1][j + 1] + 1 if old[i] == new[j]
                       else max(L[i + 1][j], L[i][j + 1]))
    i = j = 0
    out = []
    while j < m:
        if i < n and old[i] == new[j]:
            i += 1; j += 1
        elif i < n and L[i + 1][j] >= L[i][j + 1]:
            i += 1
        else:
            out.append(j); j += 1
    return out


def wrap_paint():
    """With wrapped lines on the screen a key still sends only the rows it
    changed: the text above and below is moved by the terminal, not sent
    again.  After every key the screen is what a full repaint ('^L') draws,
    and the bytes sent are held to the rows that are new -- for an edit, with
    the rest of the cursor's line from the row the cursor was on."""
    def edit_rows(v):
        return [''.join(r).rstrip() for r in v.screen[:23]]

    def step(e, tag, keys, edit=False):
        v0 = e.screen()
        s0 = edit_rows(v0)
        before = len(e.cap.getvalue())
        for k in re.split('(\x1b)', keys):
            if k == '\x1b':
                send_keys(e, k)
            elif k:
                e.key(k)
        sent = len(e.cap.getvalue()) - before
        v1 = e.screen()
        s1 = edit_rows(v1)
        new = set(new_rows(s0, s1))
        if edit:
            # the cursor line's rows, from the one the cursor was on
            last = v1.row - e.s.mem(SYM['CSUB'])[0] + e.s.mem(SYM['HTAB'] + e.s.mem(SYM['HTCUR'])[0])[0]
            new |= set(range(min(v0.row, v1.row), min(last, 23)))
        # (an insert shows and clears the mode message as well)
        budget = 96 + 64 * keys.count('\x1b') + sum(len(s1[r]) + 12 for r in new)
        check(f'{tag} {keys!r}: {sent} bytes sent, the rows that changed are '
              f'{budget}', sent <= budget)
        e.key('\x0c')
        v2 = e.screen()
        check(f'{tag} {keys!r}: the screen is what a full repaint draws',
              edit_rows(v2) == s1 and (v2.row, v2.col) == (v1.row, v1.col))

    data = ''.join(l + '\r\n' for l in paint_lines()).encode()
    w2 = wrap_files()['w2']
    for name, text, runs in [
        ('moves', data, ['j'] * 30 + ['k'] * 30 + ['\x04', '\x04', '\x15', '\x15',
                                              '12j', '\x04', '\x15', 'G', 'k', 'k',
                                              '\x15', 'gg']),
        ('@ rows', w2, ['20j', 'j', 'j', 'k', 'k', '5k', '4j', 'j', 'j']),
    ]:
        e = Editor(text)
        try:
            for k in runs:
                step(e, f'paint {name}', k)
        finally:
            e.close()
    for name, text, runs in [
        ('edits', data, ['x', 'j', 'x', '$', 'x', '0', '3x', 'rZ', '~', 'dw', 'j',
                         'dd', 'P', 'j', 'dd', 'p', 'J', 'j', 'J', 'D', 'k',
                         'ia\x1b', 'A-\x1b', 'ocd\x1b', 'Oef\x1b', '7G', '100l',
                         'i\r\x1b', 'k', 'J', 'cwq\x1b', 'yyP', '18G', 'dd', 'j',
                         'J', 'ogh\x1b', 'dd']),
        ('edits by @ rows', w2, ['x', '19j', 'x', 'dd', 'P', 'ozz\x1b', 'dd', 'k',
                                 'J', 'iq\x1b']),
    ]:
        e = Editor(text)
        try:
            for k in runs:
                step(e, f'paint {name}', k, edit=True)
        finally:
            e.close()

    # --- prose typed at the bottom of the screen: a char is a char, and the
    #     one that takes the line onto a new row moves the screen up a row ---
    e = Editor(data)
    try:
        e.key('G')
        e.key('o')
        worst = edge = 0
        for i in range(170):
            before = len(e.cap.getvalue())
            e.key('abcdefghij'[i % 10])
            sent = len(e.cap.getvalue()) - before
            if i % 80 in (79, 0):
                edge = max(edge, sent)
            else:
                worst = max(worst, sent)
        check(f'paint typing: a char at the end of a wrapped line is {worst} '
              f'bytes', worst <= 2)
        check(f'paint typing: the char that fills a row, and the next, are at '
              f'most {edge} bytes', edge <= 200)
        send_keys(e, '\x1b')
        v1 = e.screen()
        e.key('\x0c')
        v2 = e.screen()
        check('paint typing: the screen is what a full repaint draws',
              edit_rows(v2) == edit_rows(v1) and (v2.row, v2.col) == (v1.row, v1.col))
        # --- x is the terminal's delete-character, not a row sent again ---
        e.key('k')
        e.key('0')
        before = len(e.cap.getvalue())
        e.key('x')
        out = e.cap.getvalue()[before:]
        check(f'paint x: delete-character and nothing else ({out!r})',
              out == '\x1b[1P')
        before = len(e.cap.getvalue())
        e.key('3x')
        out = e.cap.getvalue()[before:]
        check(f'paint 3x: three cells ({out!r})', out.endswith('\x1b[3P'))
        e.key('$')
        before = len(e.cap.getvalue())
        e.key('x')
        out = e.cap.getvalue()[before:]
        v1 = e.screen()
        e.key('\x0c')
        v2 = e.screen()
        check(f'paint x: at the line end ({out!r})',
              len(out) <= 32 and edit_rows(v2) == edit_rows(v1)
              and (v2.row, v2.col) == (v1.row, v1.col))
    finally:
        e.close()


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
    """ESC, run until the bottom row has changed: the mode message going is
    what says the insert has ended."""
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
                          (':ve\r', VERSION),
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
    ('wide', ['+700'], ['700 694 10 0']),
    ('wide', ['+700', '$'], ['700 694 10 0', '700 694 10 5']),
    ('wd', ['+1500'], ['1500 1491 11 0']),
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
                dc, lr = curs(e, v)
                scr = [''.join(r).rstrip() for r in v.screen]
                ln, top, row, col = map(int, w.split())
                got = '%d %d' % (v.row, dc)
                tag = 'plus %s %r %r' % (f, keys, k)
                check(f'{tag}: {got} == {row} {col}', got == '%d %d' % (row, col))
                if lines:
                    show = lambda n: expand(lines[n - 1])[:80].rstrip()
                    check(f'{tag}: rows show lines {top} and {ln}',
                          scr[0] == show(top) and scr[lr] == show(ln))
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
        cnt = min(2900, register_lines(e))      # (as many as will fit)
        e.key('G'); e.key('3000k'); e.key('%ddd' % cnt)
        cur = n - 3000
        want = make(n)[:(cur - 1) * 8] + make(n)[(cur + cnt - 1) * 8:]
        v = e.screen()
        check(f'{label}: {cnt}dd past the window lands on line {cur + cnt}',
              rows(e)[v.row] == txt(cur + cnt))
        e.key(':w\r')
        check(f'{label}: {cnt}dd :w byte-exact', saved_bytes(e) == want)
    finally:
        e.close()

    # Issue #27: back from the end, a delete that leaves a whole number of
    # records.  G wrote more records to name.$$$ than the text now has, and
    # with no ^Z in a full last record the save kept the old ones as text.
    # 800dd is the same with the last record in another extent.
    if n != 5120:
        return
    for cnt in (1600, 800):
        e = Editor(make(n))
        try:
            e.key('G'); e.key('3000k'); e.key('%ddd' % cnt)
            cur = n - 3000
            want = make(n)[:(cur - 1) * 8] + make(n)[(cur + cnt - 1) * 8:]
            e.key(':w\r')
            e.key('G')
            check(f'{label}: G 3000k {cnt}dd :w, the text read back ends '
                  f'at the last line', rows(e)[e.screen().row] == txt(n))
            check(f'{label}: G 3000k {cnt}dd :w byte-exact',
                  saved_bytes(e) == want)
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



def find_files():
    """What f F t T ; , need beyond hml_files()/ins_files(): a line carrying
    the same target many times over, a line of punctuation for 'dt)' and 'df,',
    a line the target is NOT on (the refusal), and a WIDE line whose later
    targets sit past the right screen edge, so a find has to pan to land on
    one."""
    wide = (b'aXbXcX' + b'-' * 70 + b'dXeX' + b'-' * 60 + b'fX')
    return dict(hml_files(), **ins_files(),
                fd=b'foo bar baz bar qux bar end\r\n'
                   b'func(arg1, arg2, arg3);\r\n'
                   b'no targets on this line\r\n'
                   + wide + b'\r\n'
                   b'last\r\n')


# ---------------------------------------------------------------------------
# VIM_FIND -- f F t T ; , against vim 9.1, recorded by vimref.py ('find')
# BEFORE they were written.  Shape is VIM_MARKS's: (file, keys, the sha1 of the
# file vim wrote, [(cursor row, column, cursor line, top line) after each key]).
#
# What the rows have to pin down, because none of it is guessable:
#   - a find that does not find stays put, and takes the pending operator with
#     it ('dfz' deletes nothing at all)
#   - 't' when the target is already the next char, and what ';' does after a
#     't' (vim special-cases exactly this -- it is the one place where ';' is
#     not simply "the same find again")
#   - counts on the find AND on ';' / ','
#   - ',' is the find reversed, not the last direction repeated
#   - f/t never leave the line, whatever is on the next one
#   - the operator spans: 'f' and 't' are INCLUSIVE, 'F' and 'T' exclusive
VIM_FIND = [
    ('fd', ['gg', 'fb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '2fb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 8, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '3fb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 12, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '9fb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'fb', ';'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 8, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'fb', ';', ';'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 8, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 12, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'fb', ';', ','], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 8, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'fb', '2;'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 12, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '$', 'Fb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 26, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 20, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '$', '2Fb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 26, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 12, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '$', 'Fb', ';'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 26, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 20, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 12, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '$', 'Fb', ','], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 26, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 20, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 20, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'tb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 3, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'tb', ';'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 3, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 7, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '2tb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 7, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'tb', ';', ';'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 3, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 7, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 11, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '$', 'Tb'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 26, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 21, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '$', 'Tb', ';'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 26, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 21, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 13, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'fz'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 10, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'fb', 'fz'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 10, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['3G', 'fq'], '58c62356825b5646',
     [(2, 0, 'no targets on this line', 'foo bar baz bar qux bar end'),
      (2, 0, 'no targets on this line', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'ft'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', 'df,'], '10d8555e6dca283a',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 0, ' arg2, arg3);', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', 'dt)'], '9fb55cd198d1cdcc',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 0, ');', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', 'd2f,'], '97260f7358c2c1b3',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 0, ' arg3);', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', 'dfz'], '58c62356825b5646',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', 'ct)new\x1b'], '26d8ad421c336c3b',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 2, 'new);', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', 'cf,Y\x1b'], '3b4ee88b473e553b',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 0, 'Y arg2, arg3);', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', 'dfa', '.'], 'c23ff6ee451d1134',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 0, 'rg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 0, 'rg2, arg3);', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', 'dTf'], '58c62356825b5646',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end')]),
    ('fd', ['2G', '$', 'dF,'], '7de51e44193da861',
     [(1, 0, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 22, 'func(arg1, arg2, arg3);', 'foo bar baz bar qux bar end'),
      (1, 15, 'func(arg1, arg2;', 'foo bar baz bar qux bar end')]),
    ('fd', ['4G', 'fX'], '58c62356825b5646',
     [(3, 0, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 1, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end')]),
    ('fd', ['4G', '3fX'], '58c62356825b5646',
     [(3, 0, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 5, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end')]),
    ('fd', ['4G', '7fX'], '58c62356825b5646',
     [(3, 0, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 0, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end')]),
    ('fd', ['4G', '$', 'FX'], '58c62356825b5646',
     [(3, 0, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (4, 141, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 79, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end')]),
    ('fd', ['4G', 'fX', ';', ';', ';', ';'], '58c62356825b5646',
     [(3, 0, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 1, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 3, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 5, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 77, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 79, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end')]),
    ('fd', ['4G', '2tX'], '58c62356825b5646',
     [(3, 0, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end'),
      (3, 2, 'aXbXcX----------------------------------------------------------------------dXeX------------------------------------------------------------fX', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'tb', ';', ','], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 3, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 7, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 5, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', '$', 'Tb', ','], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 26, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 21, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 21, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', ';'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'd;'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'fb', 'd;'], '59cb89f3b89f2f25',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo az bar qux bar end', 'foo az bar qux bar end')]),
    ('fd', ['gg', 'fb', '2,'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'fb', ',', ','], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 4, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
    ('fd', ['gg', 'd,'], '58c62356825b5646',
     [(0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end'),
      (0, 0, 'foo bar baz bar qux bar end', 'foo bar baz bar qux bar end')]),
]



def find_like_vim():
    """f F t T ; , land where vim lands them, and the operator forms leave the
    file byte-exact."""
    import hashlib
    files = find_files()
    for f, keys, sha, want in VIM_FIND:
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                e.key(k)
                if '\x1b' in k:
                    e.s.run_until_quiet(quiet=1.5, timeout=40)
                r = rows(e); v = e.screen()
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
                check(f'vim find {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            ex_settled(e)
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim find {f} {keys!r}: file as vim wrote it ({got})',
                  got == sha)
        finally:
            e.close()


def find_cmds():
    """Where vim cannot be the reference, because this editor's 'y' takes
    LINEWISE motions only (COMMANDS.md): 'yf' is dropped -- and the character
    it was going to look for must be SWALLOWED with it.  An orphan target
    dispatched as a command is the 'df'-was-an-'x' bug of 0f9837f wearing the
    other shoe: 'yfd' would yank nothing and then run 'd' as the next command.
    """
    e = Editor(find_files()['fd'])
    try:
        e.key('gg')
        e.key('yfb')            # dropped: 'y' takes linewise motions only
        r = rows(e); v = e.screen()
        check(f'yfb: dropped, cursor stays at 0,0 (got {v.row},{v.col})',
              (v.row, v.col) == (0, 0))
        check('yfb: the target was swallowed, not run as a command',
              r[0] == 'foo bar baz bar qux bar end')
        e.key('yf')             # ... and the same with the target in a
        e.key('d')              #     separate keystroke
        r = rows(e)
        check('yf then d: still no command ran',
              r[0] == 'foo bar baz bar qux bar end')
        # f/t never leave the line: the '(' is on the NEXT line, not this one
        e.key('gg')
        e.key('f(')
        v = e.screen()
        check(f'f(: the ( is on the next line, cursor unmoved '
              f'(got {v.row},{v.col})', (v.row, v.col) == (0, 0))
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
# NOT HERE: a mark following its text through an edit, and through paging.
# Those are asserted in marks_cmds(), which also holds the three places this
# editor is documented not to match vim (COMMANDS.md).
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
                    # A repaint RPOLL aborted because this ESC was waiting
                    # may not have been made good yet: wait for the editor
                    # rather than read the screen mid-keystroke.
                    e.s.run_until_quiet(quiet=1.5, timeout=40)
                r = rows(e); v = e.screen()
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
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
    """Marks beyond the recorded vim rows: a mark follows its text through
    every kind of edit and through paging, on small files and on 100 K; where
    its own text is deleted it closes up to the delete, which is not vim's
    answer (COMMANDS.md).  A jump to a mark that will not answer -- never set,
    or a key that names none -- moves nothing and says 'Mark not set' on the
    bottom row, vim's E20 without the number; like every message here it does
    not ring.  'm' with a key that names no mark only rings."""
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

    def notset(e, keys, tag):
        """*keys* must say 'Mark not set' -- the whole bottom row, nothing run
        on after it -- without a bell, and move and redraw nothing."""
        e.key('\x0c')                            # no message on the row yet
        v = e.screen(); before = (v.row, v.col)
        scr0 = [''.join(r) for r in v.screen[:23]]
        n = len(e.cap.getvalue())
        e.key(keys)
        out = e.cap.getvalue()[n:]
        v = e.screen()
        check(f'{tag}: says {bottom(e)!r}', bottom(e) == 'Mark not set')
        check(f'{tag}: no bell with the message', '\x07' not in out)
        check(f'{tag}: the cursor did not move ({v.row},{v.col})',
              (v.row, v.col) == before)
        check(f'{tag}: the text rows are untouched',
              [''.join(r) for r in v.screen[:23]] == scr0)

    # ---- a mark that was never set, and a key that names none ----
    e = Editor(files['mk'])
    try:
        notset(e, '`a', 'a mark never set: `a')
        notset(e, "'b", "a mark never set: 'b")
        notset(e, "'c", "a mark never set: 'c")
        notset(e, "'z", "a letter past 'c': 'z")
        notset(e, '`1', 'a digit: `1')
        e.key('j')
        check('the message stays until another replaces it',
              bottom(e) == 'Mark not set')
        e.key('ma'); e.key('G'); e.key('`a')
        v = e.screen()
        check(f'a set mark still answers, and says nothing new ({v.row},{v.col})',
              (v.row, v.col) == (1, 0))
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

    big = make(12800)

    def landed(e, tag, n, col, at=None):
        at = n if at is None else at             # the line ^G should count
        v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
        check(f'{tag}: on line {n}, column {col} ({scr[v.row]!r}, {v.col})',
              scr[v.row] == txt(n) and v.col == col)
        e.key('\x0c')
        v2 = e.screen(); scr2 = [''.join(r).rstrip() for r in v2.screen[:23]]
        check(f'{tag}: the screen is what ^L draws (top {scr[0]!r}, '
              f'^L {scr2[0]!r})',
              scr == scr2 and (v.row, v.col) == (v2.row, v2.col))
        g = ctrlg(e)
        check(f'{tag}: ^G agrees ({g!r})', f'line {at} ' in g + ' ')

    # ---- a mark FOLLOWS its text: an edit above it moves it, it is not lost.
    #      The mark is on 'epsilon zeta' (line 3), four characters in, and
    #      after each edit '`a' must find that same 'o' and ''a' that line.
    def follows(setup, tag, row, col, line='epsilon zeta', f='mk', nb=0):
        for q in ('`', "'"):
            e = Editor(files[f])
            try:
                e.key('3G'); e.key('4l'); e.key('ma')
                for k in setup:
                    e.key(k)
                    if '\x1b' in k or k.endswith('\r'):
                        e.s.run_until_quiet(quiet=1.5, timeout=40)
                e.key('\x0c')                    # no message on the row yet
                e.key(q + 'a')
                v = e.screen(); r = rows(e)
                want = (row, col if q == '`' else nb)  # ''': the first non-blank
                check(f'{tag}: {q}a lands at {want} on {line[:12]!r} '
                      f'({(v.row, v.col)} {r[v.row][:12]!r}, {bottom(e)!r})',
                      (v.row, v.col) == want and r[v.row] == line
                      and bottom(e) == '')
            finally:
                e.close()

    follows(['gg', 'x'],              'x above',                 2, 4)
    follows(['gg', 'dd'],             'dd above',                1, 4)
    follows(['gg', '2dd'],            '2dd above',               0, 4)
    follows(['gg', 'Onew\x1b'],       'O above',                 3, 4)
    follows(['gg', 'onew\x1b'],       'o above',                 3, 4)
    follows(['gg', 'ione\rtwo\x1b'],  'a typed line break above', 3, 4)
    follows(['Onew\x1b'],             'O on the marked line',    3, 4)
    follows(['gg', 'yy', '3G', 'P'],  'P on the marked line',    3, 4)
    follows(['gg', 'yy', 'p'],        'p above',                 3, 4)
    follows(['gg', 'J'],              'J above',                 1, 4)
    follows(['gg', 'dw'],             'dw above',                2, 4)
    follows(['gg', 'cwXYZZY\x1b'],    'cw above',                2, 4)
    follows(['gg', 'D'],              'D above',                 2, 4)
    follows(['gg', '~'],              '~ above (nothing moves)', 2, 4)
    follows(['gg', 'x', 'j', '.'],    'x and . above',           2, 4)
    follows(['gg', 'dd', 'u'],        'dd above, undone',        2, 4)
    follows(['gg', 'dd', 'u', 'u'],   'dd above, undone, redone', 1, 4)
    follows(['gg', 'Onew\x1b', 'u'],  'O above, undone',         2, 4)
    follows([':1s/alpha/A/\r'],       ':s above',                2, 4)
    follows([':1,2s/a/AAA/g\r'],      ':s growing two lines above', 2, 4)
    follows(['G', 'x'],               'x below',                 2, 4)
    follows(['G', 'dd'],              'dd below',                2, 4)
    # ... and on the marked line itself, the mark stays with its CHARACTER
    follows(['0', 'x'],               'x before it on the line', 2, 3,
            line='psilon zeta')
    follows(['0', 'iab\x1b'],         'an insert before it on the line', 2, 6,
            line='abepsilon zeta')
    follows(['$', 'x'],               'x after it on the line',  2, 4,
            line='epsilon zet')
    follows(['rX'],                   'r on the marked character', 2, 4,
            line='epsiXon zeta')
    follows(['~'],                    '~ on the marked character', 2, 4,
            line='epsiLon zeta')
    follows(['RXY\x1b'],              'R over the marked character', 2, 4,
            line='epsiXYn zeta')
    follows(['iab\x1b'],              'an insert AT the mark: it stays there',
            2, 4, line='epsiablon zeta')
    follows(['2G', 'J'],              'J joins the marked line up', 1, 18,
            line='  gamma delta epsilon zeta', nb=2)

    # ---- text deleted from UNDER a mark: the mark closes up to where the
    #      delete was (vim deletes the mark with its line; COMMANDS.md) ----
    follows(['dd'],                   'dd on the marked line',   2, 0, line='')
    follows(['0', 'D'],               'D through the mark',      2, 0, line='')
    follows(['2G', '3dd'],            '3dd through the marked line', 1, 0,
            line='  last line here', nb=2)

    # ---- the same on a 100 K file, with the mark and the edit in different
    #      windows: 'a at line 6000, the edit at the top or the end ----
    for q, col in (("'", 0), ('`', 3)):
        e = Editor(big)
        try:
            e.key('6000G'); e.key('3l'); e.key('ma')
            e.key('gg'); e.key('3dd')
            e.key(q + 'a'); landed(e, f'3dd at the top, {q}a', 6000, col, 5997)
            e.key('40G'); e.key('Otwo\rlines\x1b')
            e.s.run_until_quiet(quiet=1.5, timeout=40)
            e.key(q + 'a'); landed(e, f'O far above, {q}a', 6000, col, 5999)
            e.key('G'); e.key('dd')
            e.key(q + 'a'); landed(e, f'dd far below, {q}a', 6000, col, 5999)
            e.key(':w\r'); ex_settled(e)
            e.key('gg'); e.key(q + 'a')
            landed(e, f'after :w, {q}a', 6000, col, 5999)
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
            check(f'{tag}: says {bottom(e)!r}', bottom(e) == 'Mark not set')
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
        check(f"d' then ESC says nothing ({bottom(e)!r})",
              'Mark' not in bottom(e))
    finally:
        e.close()

    # ---- '.' after "d'a" repeats it, to the mark where it now is.  The
    #      delete took the marked line, so the mark sits where the delete was
    #      (vim drops it and says so): the repeat takes that one line ----
    e = Editor(files['mk'])
    try:
        e.key('3G'); e.key('ma'); e.key('gg')
        e.key("d'a")
        after = rows(e)[:3]
        e.key('.')
        check(f"'.' after \"d'a\" repeats it: one more line goes "
              f"({rows(e)[:2]!r})", rows(e)[:2] == after[1:3])
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

    # ---- a jump to a line that is off the screen must REDRAW it.  The file
    #      fits the window, so nothing pages and the mark survives the 'G';
    #      the jump places its line as 'G' does, which measures the target
    #      against the screen's top line -- and that has to be noted afresh,
    #      not left over from the 'G'.  Each screen is held against the one a
    #      '^L' draws: a jump that moves only the cursor leaves the two apart.
    far = b''.join(b'line %03d %s\r\n' % (i, b'x' * 20) for i in range(1, 129))
    for jump in ("'a", '`a'):
        e = Editor(far)
        try:
            def drawn(tag, want):
                v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
                check(f'{tag}: the cursor is on {want!r} ({scr[v.row][:8]!r})',
                      scr[v.row][:8] == want)
                e.key('\x0c')
                v2 = e.screen(); scr2 = [''.join(r).rstrip() for r in v2.screen[:23]]
                check(f'{tag}: the screen is what ^L draws (top {scr[0][:8]!r}, '
                      f'^L {scr2[0][:8]!r})',
                      scr == scr2 and (v.row, v.col) == (v2.row, v2.col))
            e.key('8j'); e.key('ma'); e.key('G')
            e.key(jump)
            drawn(f'G then {jump}', 'line 009')
            e.key('G'); e.key(jump); e.key('1G')
            drawn(f'G {jump} then 1G', 'line 001')
            e.key('G'); e.key('d' + jump)        # an operator over the same jump
            # "d'a" takes lines 9 to 128 whole; "d`a" takes the span between
            # the two points, so line 128's text joins up where line 9 began
            drawn(f'G then d{jump}', 'line 008' if jump == "'a" else 'line 128')
        finally:
            e.close()

    # ---- a mark is a place in the FILE, not in the window: paging away from
    #      it and back does not lose it, and a jump pages to wherever it is.
    #      100 K, so every jump here crosses the resident window; each landing
    #      is held to the line's text, '^G's line number and the screen a '^L'
    #      draws.
    for q, col in (("'", 0), ('`', 3)):
        e = Editor(big)
        try:
            e.key('40G'); e.key('3l'); e.key('ma')       # near the top
            e.key('6000G'); e.key('3l'); e.key('mb')     # the middle
            e.key('G'); e.key('3l'); e.key('mc')         # the last line
            e.key(q + 'a'); landed(e, f'from the end, {q}a', 40, col)
            e.key(q + 'c'); landed(e, f'from the top, {q}c', 12800, col)
            e.key(q + 'b'); landed(e, f'from the end, {q}b', 6000, col)
            e.key(q + 'a'); landed(e, f'from the middle, {q}a', 40, col)
            e.key(q + 'b'); landed(e, f'from the top, {q}b', 6000, col)
            e.key(q + 'b'); landed(e, f'already there, {q}b', 6000, col)
            e.key('9000G'); e.key('x')           # an edit BELOW a and b
            e.key(q + 'a'); landed(e, f'after an edit below, {q}a', 40, col)
            e.key(':w\r'); ex_settled(e)         # the write keeps them too
            e.key(q + 'b'); landed(e, f'after :w, {q}b', 6000, col)
        finally:
            e.close()

    # ---- the jump pages with a count of its own, and must not leave it for
    #      the next command: 'x' after a paged jump took the rest of the line
    for q in ("'", '`'):
        e = Editor(big)
        try:
            e.key('40G'); e.key('2l'); e.key('ma'); e.key('G')
            e.key(q + 'a'); e.key('x')
            e.s.run_until_quiet(quiet=1.5, timeout=40)
            v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
            want = '00040'
            check(f'x after a paged {q}a deletes ONE character '
                  f'({scr[v.row]!r})', scr[v.row] == want)
        finally:
            e.close()

    # ---- only a LINE DELETE can take a span the window does not hold whole,
    #      so any other operator over a mark that is paged out is refused --
    #      the bell, nothing taken -- and the mark is still there for a jump
    for op in ('d`a', "y'a"):                    # ("d'a" is not: pgop)
        e = Editor(big)
        try:
            e.key('40G'); e.key('ma'); e.key('G')
            n = len(e.cap.getvalue())
            e.key(op)
            v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
            check(f'{op} over a paged-out mark: rings',
                  '\x07' in e.cap.getvalue()[n:])
            check(f'{op} over a paged-out mark: takes nothing '
                  f'({scr[v.row]!r})', scr[v.row] == txt(12800))
            check(f'{op} over a paged-out mark: not modified ({ctrlg(e)!r})',
                  'Modified' not in ctrlg(e))
            e.key("'a"); landed(e, f"{op} refused, then 'a", 40, 0)
        finally:
            e.close()



def pgop_cmds():
    """An operator over a motion that PAGES.  The span's start is kept as a
    place in the file, so 'dG', 'dgg', 'd{n}G', a counted 'dj' / 'dk' and
    "d'a" take the lines they name however far apart the two ends are, on
    40 K and 100 K, and write back byte-exact.  What cannot be done over a
    span the window does not hold -- a yank, a charwise delete -- rings, takes
    nothing and leaves the cursor where it was.  A delete that large is not
    kept for 'u', which says so.  And on a file that fits, 'dgg' is a motion
    at all, where it used to be dropped."""
    def L(a, b):
        return b''.join(line(i) for i in range(a, b + 1))

    def after(e, tag, want, n, at, text=True):
        """The file is *want*; the cursor is on old line *n*, now line *at*."""
        e.s.run_until_quiet(quiet=1.5, timeout=240)
        v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
        if text:
            check(f'{tag}: the cursor is on {txt(n)} ({scr[v.row]!r}, {v.col})',
                  scr[v.row] == txt(n) and v.col == 0)
            e.key('\x0c')
            v2 = e.screen()
            scr2 = [''.join(r).rstrip() for r in v2.screen[:23]]
            check(f'{tag}: the screen is what ^L draws (top {scr[0]!r}, '
                  f'^L {scr2[0]!r})',
                  scr == scr2 and (v.row, v.col) == (v2.row, v2.col))
            g = ctrlg(e)
            check(f'{tag}: ^G agrees ({g!r})',
                  f'line {at} ' in g + ' ' and 'Modified' in g)
        e.key(':w\r'); ex_settled(e)
        got = saved_bytes(e)
        check(f'{tag}: the file is byte-exact ({len(got)} bytes, '
              f'{len(want)} wanted; ends {got[-8:]!r})', got == want)

    for size, tall, mid in (('100 K', 12800, 6000), ('40 K', 5120, 2500)):
        big = make(tall)
        for keys, want, n, at in (
                (['%dG' % mid, 'dG'], L(1, mid - 1), mid - 1, mid - 1),
                (['%dG' % mid, 'dgg'], L(mid + 1, tall), mid + 1, 1),
                (['%dG' % mid, 'd1G'], L(mid + 1, tall), mid + 1, 1),
                (['G', 'd1G'], b'', None, None),
                (['dG'], b'', None, None),
                (['G', 'dgg'], b'', None, None),
                (['%dG' % mid, 'd%dG' % (mid + 5)],
                 L(1, mid - 1) + L(mid + 6, tall), mid + 6, mid),
                (['%dG' % mid, 'd%dG' % (mid - 5)],
                 L(1, mid - 6) + L(mid + 1, tall), mid + 1, mid - 5),
                (['%dG' % mid, 'd%dG' % (tall - 100)],
                 L(1, mid - 1) + L(tall - 99, tall), tall - 99, mid),
                (['%dG' % mid, 'd40G'],
                 L(1, 39) + L(mid + 1, tall), mid + 1, 40),
                (['%dG' % mid, 'd2000j'],
                 L(1, mid - 1) + L(mid + 2001, tall), mid + 2001, mid),
                (['%dG' % mid, 'd2000k'],
                 L(1, mid - 2001) + L(mid + 1, tall), mid + 1, mid - 2000),
                (['%dG' % mid, 'ma', 'G', "d'a"], L(1, mid - 1),
                 mid - 1, mid - 1),
                (['%dG' % mid, 'ma', 'gg', "d'a"], L(mid + 1, tall),
                 mid + 1, 1)):
            e = Editor(big)
            try:
                for k in keys:
                    e.key(k)
                after(e, f'{size}, {" ".join(keys)}', want, n, at,
                      text=n is not None)
            finally:
                e.close()

    big = make(12800)

    # ---- what the window cannot hold whole and is not a line delete: the
    #      bell, nothing taken, the cursor back where it started ----
    #      (every charwise motion a count can take past the window, issue #3:
    #      TESTMAP.md had none of them over a paged span)
    for setup, op in ((['6000G', '3l'], 'yG'), (['6000G', '3l'], 'ygg'),
                      (['40G', 'ma', '6000G', '3l'], 'd`a'),
                      (['40G', 'ma', '6000G', '3l'], "y'a"),
                      (['4000G', 'ma', '6000G', '3l'], "y'a"),
                      (['6000G', '3l'], 'y2000j'),
                      (['6000G', '3l'], 'd3000w'), (['6000G', '3l'], 'd3000W'),
                      (['6000G', '3l'], 'c3000w'),
                      (['6000G', '3l'], 'd3000b'), (['6000G', '3l'], 'd3000B'),
                      (['6000G', '3l'], 'd2000$'), (['6000G', '3l'], 'c2000$')):
        e = Editor(big)
        try:
            for k in setup:
                e.key(k)
            n = len(e.cap.getvalue())
            e.key(op)
            e.s.run_until_quiet(quiet=1.5, timeout=240)
            v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
            check(f'{op} past the window: rings',
                  '\x07' in e.cap.getvalue()[n:])
            check(f'{op} past the window: the cursor is where it was '
                  f'({scr[v.row]!r}, {v.col})',
                  scr[v.row] == txt(6000) and v.col == 3)
            g = ctrlg(e)
            check(f'{op} past the window: takes nothing ({g!r})',
                  'Modified' not in g and 'line 6000 ' in g)
            e.key('x'); e.key(':w\r'); ex_settled(e)
            got = saved_bytes(e)
            check(f'{op} past the window: the next command is its own '
                  f'({len(got)} bytes)',
                  got == L(1, 5999) + b'00600\r\n' + L(6001, 12800))
        finally:
            e.close()

    # ---- a yank whose 'G' pages away and comes back is still a yank ----
    e = Editor(big)
    try:
        e.key('6000G'); e.key('y6002G'); e.key('p')
        e.s.run_until_quiet(quiet=1.5, timeout=240)
        e.key(':w\r'); ex_settled(e)
        got = saved_bytes(e)
        check(f'y6002G then p puts the three lines ({len(got)} bytes)',
              got == L(1, 6000) + L(6000, 6002) + L(6001, 12800))
    finally:
        e.close()

    # ---- a yank that pages BACKWARD is taken, and a put that pages puts the
    #      lines where they belong and leaves the cursor on the first of
    #      them, on the screen row vim leaves it on (the row it was on for
    #      'P', the next for 'p': recorded from vim 9.1) ----
    for keys, want, at, row, put1 in (
            (['6000G', '3l', 'y2000k', 'P'],
             L(1, 3999) + L(4000, 6000) + L(4000, 12800), 4000, 11, 4000),
            (['6000G', '2000yy', 'P'],
             L(1, 5999) + L(6000, 7999) + L(6000, 12800), 6000, 11, 6000),
            (['6000G', '2000yy', 'p'],
             L(1, 6000) + L(6000, 7999) + L(6001, 12800), 6001, 12, 6000),
            (['6000G', '2000dd', 'P'], L(1, 12800), 6000, 11, 6000)):
        e = Editor(big)
        try:
            for k in keys:
                tap(e, k)
            g = ctrlg(e)
            check(f'{" ".join(keys)}: the cursor is on the first '
                  f'line put, {at} ({g!r})', f' line {at} ' in g + ' ')
            v = e.screen()
            r = rows(e)
            check(f'{" ".join(keys)}: ... on row {row}, column 0, and the '
                  f'screen is drawn from there ({v.row}, {v.col}, '
                  f'{r[v.row - 1:v.row + 2]!r})',
                  (v.row, v.col) == (row, 0) and r[v.row:v.row + 2] ==
                  ['%06d' % put1, '%06d' % (put1 + 1)])
            tap(e, ':w\r')
            got = saved_bytes(e)
            check(f'{" ".join(keys)}: byte-exact ({len(got)} bytes)', got == want)
        finally:
            e.close()

    # ---- 'e' pages as 'w' does (it once stopped for good at the last line
    #      the window held), and under an operator a span the window cannot
    #      hold is refused, as it is for 'w', not cut short ----
    for at, n, ends in (('6000G', '300e', 6299), ('6000G', '3000e', 8999),
                        ('6000G3l', '300e', 6299), ('6000G', '300E', 6299),
                        ('12700G', '3000e', 12800)):
        e = Editor(big)
        try:
            tap(e, at); tap(e, n)
            g = ctrlg(e)
            check(f'{at} {n} ends on the last char of line {ends} ({g!r})',
                  f' line {ends} col 6' in g + ' ')
        finally:
            e.close()
    for op in ('d3000e', 'c3000e', 'd3000E'):
        e = Editor(big)
        try:
            tap(e, '6000G3l'); tap(e, op)
            g = ctrlg(e)
            check(f'6000G3l {op} is refused: the cursor is back on line 6000 '
                  f'column 4 ({g!r})', ' line 6000 col 4' in g + ' ')
            tap(e, ':w\r')
            got = saved_bytes(e)
            check(f'6000G3l {op} is refused: the file is untouched '
                  f'({len(got)} bytes)', got == big)
        finally:
            e.close()

    # ---- a counted 'dw' goes on into the next line (issue #22) ----
    e = Editor(make(40))
    try:
        tap(e, '5G3l'); tap(e, 'd2w'); tap(e, ':w\r')
        got = saved_bytes(e)
        check(f'5G3l d2w takes the rest of the line and the next '
              f'({len(got)} bytes)',
              got == L(1, 4) + b'000\r\n' + L(7, 40))
    finally:
        e.close()

    # ---- a delete that size is not kept for 'u', and 'u' says so ----
    e = Editor(big)
    try:
        e.key('6000G'); e.key('dG')
        e.s.run_until_quiet(quiet=1.5, timeout=240)
        e.key('u')
        check(f"u after a paged dG says why not ({bottom(e)!r})",
              bottom(e) == 'Too large to undo')
        e.key(':w\r'); ex_settled(e)
        got = saved_bytes(e)
        check(f'u after a paged dG changes nothing ({len(got)} bytes)',
              got == L(1, 5999))
    finally:
        e.close()

    # ---- the same commands on a file that fits ----
    small = make(20)
    for keys, want in ((['10G', 'dgg'], L(11, 20)),
                       (['10G', 'dG'], L(1, 9)),
                       (['10G', 'd12G'], L(1, 9) + L(13, 20)),
                       (['10G', 'd3gg'], L(1, 2) + L(11, 20)),
                       (['10G', 'dgg', 'u'], L(1, 20)),
                       (['10G', 'dgx'], L(1, 20)),
                       (['10G', 'cgg'], L(1, 20)),
                       (['10G', 'ygg', 'G', 'p'], L(1, 20) + L(1, 10)),
                       (['dG'], b'')):
        e = Editor(small)
        try:
            for k in keys:
                e.key(k)
            e.s.run_until_quiet(quiet=1.5, timeout=40)
            e.key(':w\r'); ex_settled(e)
            got = saved_bytes(e)
            check(f'20 lines, {" ".join(keys)}: byte-exact ({got[:8]!r}.. '
                  f'{len(got)} bytes)', got == want)
        finally:
            e.close()


# ---------------------------------------------------------------------------
# What a command leaves behind (issue #3).
#
# The tests above check each command and then stop.  A count the command did
# not spend, a pending operator it did not drop, a stale screen or a window the
# engine no longer agrees with all show only in the NEXT command -- 'x' after a
# paged "'a" once deleted the rest of the line, with every jump test green,
# because each of them followed its jump with 'G', ':w' or '^G'.
#
# So: after every kind of command -- the ones that work, the ones that are
# refused, the ones dropped half-typed -- the same probe: 'x' takes exactly the
# character under the cursor, 'j' moves exactly one line, '.' repeats that 'x',
# '2x' takes exactly two, and '^L' draws the screen that is already there.
# AFTER is (what the commands have in common, the commands); each list runs in
# ONE editor on the 100 K file, every command from a line of its own, so the
# commands also follow each other.  AFTER_FRESH are the ones that mean
# something only as the first command typed.
AFTER = [
    ('a motion', ['5j', '3k', '2l', '$', '0', 'w', '3w', 'b', 'e', 'H', 'M',
                  'L', '\x06', '\x02', '\x04', '\x15', '\r']),
    ('a jump', ['G', 'gg', '9000G', '12G', '99999G', 'ma9000G\'a',
                'mb100G`b', "'c", "'z", '`z', 'mz', "3'a"]),
    ('a search or a find', ['/003100\r', '/012000\r', '/zzzz\r', 'n', 'N',
                            '3n', '?000100\r', '/\r', 'f0', 'fz', '3fz', ';',
                            ',', 'tz', 'F0', '3;']),
    ('a command dropped half-typed',
     ['7\x1b', 'd\x1b', '3d\x1b', 'dz', '3dz', 'd3z', 'y\x1b', 'yz', 'c\x1b',
      'cz', 'r\x1b', '5r\x1b', 'g\x1b', 'gx', '3gx', 'm\x1b', "'\x1b",
      '`\x1b', 'f\x1b', '/\x1b', ':\x1b', '5:\x1b', '7Q', '3K', '9&', '\x03',
      '5\x03', '5\x07', '5\x0c']),
    ('an ex command', [':nosuch\r', ':5000\r', ':s/zz/y/\r', ':1,2s/zz/y/\r',
                       ':e\r', ':q\r', ':r NOSUCH.TXT\r',
                       ':3000,3001w T.TXT\r', ':r T.TXT\r', ':w\r']),
    ('a yank, a put or a refusal',
     ['yy', '3yy', 'p', 'P', '3p', 'yj', "ma9000Gy'a", 'yG', '5000yy',
      '5000dd', 'p']),
    ('a change', ['x', '3x', 'dd', '3dd', 'dw', 'D', 'J', '~', 'iab\x1b',
                  '3iab\x1b', 'aab\x1b', 'Aab\x1b', 'Iab\x1b', 'oab\x1b',
                  'Oab\x1b', 'Rab\x1b', 'rz', 'cwab\x1b', 'Cab\x1b', 'u',
                  'xuu', '.', '3.']),
]
AFTER_FRESH = ['u', '.', '3.', 'p', 'P', 'n', 'N', ';', ',', "'a", '`a', '\x0c',
               '\x07', '\x1b']


def tap(e, keys):
    """Type *keys* and wait for the editor to be back at the keyboard."""
    for part in re.split('(\x1b)', keys):
        if part == '\x1b':
            escaped(e)
        elif part:
            e.s.send(part)
            idle(e)
            ex_settled(e)


def still_open(issue, label, cond):
    """A check that is known to fail, under the issue it is waiting on.  It
    passes while *cond* is false and FAILS when it turns true: the fix has to
    make it an ordinary check()."""
    check(f'{label}: still as issue #{issue} says -- if this fails the issue '
          f'is fixed: make it a check()', not cond)


def after_cmds():
    """After any command the next one is its own: 'x' takes one character,
    'j' moves one line, '.' repeats the 'x', '2x' takes two, and the screen is
    the one '^L' draws."""
    def where(e):
        """(^G's line, the screen row, the column, that row's text)."""
        m = re.search(r'line (\d+) col (\d+)', ctrlg(e))
        v = e.screen()
        return (int(m.group(1)) if m else None, v.row, v.col,
                ''.join(v.screen[v.row]).rstrip())

    def less(t, col, n):
        return t[:col] + t[col + n:]

    def at(e):
        """The cursor, off the screen as it stands: no key is typed for it."""
        v = e.screen()
        return v.row, v.col, ''.join(v.screen[v.row]).rstrip()

    def probe(e, tag, last):
        # the 'x' is the FIRST key after the command: a '^G' typed to find the
        # line would itself take whatever the command left behind
        row, col, t = at(e)
        tap(e, 'x')
        row1, col1, t1 = at(e)
        check(f'{tag}: x takes the one character under the cursor '
              f'({t!r} col {col} -> {t1!r})',
              (row1, t1) == (row, less(t, col, 1)))
        ln = where(e)[0]
        check(f'{tag}: the editor answers ^G', ln is not None)
        if ln is None:
            return
        tap(e, 'j')
        ln2, row2, col2, t2 = where(e)
        check(f'{tag}: j moves one line (line {ln} -> {ln2})',
              ln2 == (ln if ln == last else ln + 1))
        tap(e, '.')
        ln3, row3, col3, t3 = where(e)
        check(f'{tag}: . repeats the x ({t2!r} col {col2} -> {t3!r})',
              (ln3, t3) == (ln2, less(t2, col2, 1)))
        tap(e, '2x')
        ln4, row4, col4, t4 = where(e)
        check(f'{tag}: 2x takes two ({t3!r} col {col3} -> {t4!r})',
              (ln4, t4) == (ln3, less(t3, col3, 2)))
        scr = [''.join(r).rstrip() for r in e.screen().screen[:23]]
        tap(e, '\x0c')
        v = e.screen()
        check(f'{tag}: the screen is the one ^L draws',
              scr == [''.join(r).rstrip() for r in v.screen[:23]]
              and (v.row, v.col) == (row4, col4))

    big = make(12800)
    line_no = 3000
    for what, cmds in AFTER:
        e = Editor(big)
        try:
            for c in cmds:
                line_no += 20
                tap(e, f'{line_no}G2l')
                tap(e, c)
                probe(e, f'after {what}, {c!r}', 12800)
        finally:
            e.close()

    small = make(40)
    for c in AFTER_FRESH:
        e = Editor(small)
        try:
            tap(e, c)
            probe(e, f'as the first command, {c!r}', 40)
        finally:
            e.close()


# ---------------------------------------------------------------------------
# Limits (issue #3): every bounded thing just under, at and over its bound.
# Five of the seven bugs in that issue were a command run past a limit no test
# went near.  Over the limit the editor must still be running and must have
# said or shown what it did -- or the check is a still_open() under an issue.
def limits_cmds():
    """The ex line (40), the search pattern (30), the '.' recording (128
    keys), the undo region (1024 bytes), a count (65535), type-ahead (31 keys
    in the ring), '+{n}', the terminal's size, and the length of a line."""
    def alive(e, tag):
        """The editor takes a command and answers ^G."""
        tap(e, '\x1b')
        check(f'{tag}: the editor is still running ({ctrlg(e)!r})',
              ' line ' in ctrlg(e))

    # ---- the ex line: EXMAX characters, the rest not taken ----
    e = Editor(make(40))
    try:
        for n in (39, 40, 45):
            tap(e, ':' + 'x' * n)
            b = bottom(e)
            check(f'ex line, {n} typed: the row holds {min(n, 40)} ({len(b) - 1})',
                  b == ':' + 'x' * min(n, 40))
            tap(e, '\x1b')
        alive(e, 'ex line')
    finally:
        e.close()

    # ---- the search pattern: 30 characters, the rest not taken.  The line
    #      has 30 x's then a y, so a pattern cut to 30 still finds it ----
    e = Editor(b'abc\r\n' + b'x' * 30 + b'y\r\nend\r\n')
    try:
        for n in (29, 30, 35):
            tap(e, 'gg/' + 'x' * n)
            b = bottom(e)
            check(f'search, {n} typed: the row holds {min(n, 30)} ({len(b) - 1})',
                  b == '/' + 'x' * min(n, 30))
            tap(e, '\r')
            v = e.screen()
            check(f'search, {n} typed: found on line 2 ({v.row}, {v.col})',
                  (v.row, v.col) == (1, 0))
        tap(e, 'gg/' + 'x' * 30 + 'z\r')
        check(f'search, 31 typed that are not there: the 30 are looked for '
              f'({bottom(e)!r})', e.screen().row == 1)
        alive(e, 'search')
    finally:
        e.close()

    # ---- '.': a change of up to 128 keys is repeated, a longer one is not
    #      (and nothing else happens).  'i' + n + ESC is n + 2 keys ----
    for n in (125, 126, 127, 140):
        e = Editor(b'one\r\ntwo\r\n')
        try:
            tap(e, 'i' + 'a' * n + '\x1b')
            tap(e, 'j0.')
            alive(e, f'. after {n + 2} keys')
            tap(e, ':w\r')
            want = b'a' * n + b'one\r\n' + (b'a' * n if n + 2 <= 128 else b'') + b'two\r\n'
            got = saved_bytes(e)
            check(f'. after a change of {n + 2} keys: '
                  f'{"repeats it" if n + 2 <= 128 else "does nothing"} '
                  f'({len(got)} bytes)', got == want)
        finally:
            e.close()

    # ---- undo: 1024 bytes are kept, one line more is not, and 'u' says so ----
    for n in (127, 128, 129):
        e = Editor(make(400))
        try:
            tap(e, f'5G{n}dd')
            tap(e, 'u')
            said = bottom(e)
            tap(e, ':w\r')
            got = saved_bytes(e)
            if n * 8 <= 1024:
                check(f'u after {n}dd ({n * 8} bytes): the lines are back '
                      f'({len(got)} bytes, {said!r})', got == make(400))
            else:
                check(f'u after {n}dd ({n * 8} bytes): says why not ({said!r})',
                      said == 'Too large to undo')
                check(f'u after {n}dd: and changes nothing ({len(got)} bytes)',
                      got == b''.join(line(i) for i in range(1, 401)
                                      if not 5 <= i < 5 + n))
        finally:
            e.close()

    # ---- a count: held at 65535, and one too big for the text runs out ----
    e = Editor(make(40))
    try:
        for keys, ln, col in (('65535G', 40, 1), ('gg65536G', 40, 1),
                              ('gg99999G', 40, 1), ('gg99999j', 40, 1),
                              ('99999k', 1, 1), ('5G99999l', 5, 6),
                              ('99999h', 5, 1), ('3G99999x', 3, 1),
                              ('10G99999dd', 9, 1)):
            tap(e, keys)
            g = ctrlg(e)
            check(f'count {keys}: line {ln} col {col} ({g!r})',
                  g.endswith(f' line {ln} col {col}'))
        tap(e, ':w\r')
        got = saved_bytes(e)
        check(f'count: 99999x took one line\'s text and 99999dd the rest of '
              f'the file ({len(got)} bytes)',
              got == line(1) + line(2) + b'\r\n'
              + b''.join(line(i) for i in range(4, 10)))
    finally:
        e.close()

    # ---- type-ahead: the ring holds 31 keys, and more than that typed
    #      behind a jump that pages are not lost ----
    for n in (31, 32, 100):
        e = Editor(make(12800))
        try:
            e.s.send('6000G' + 'j' * n)
            idle(e)
            g = ctrlg(e)
            check(f'{n} keys typed behind a paged jump all arrive ({g!r})',
                  g.endswith(f' line {6000 + n} col 1'))
        finally:
            e.close()

    # ---- '+{n}': past the last line, and past 16 bits, is the last line ----
    for a in ('+65535', '+65536', '+99999', '+100000'):
        e = Editor(make(40), args=' ' + a)
        try:
            g = ctrlg(e)
            check(f'{a} on 40 lines is the last line ({g!r})',
                  g.endswith(' line 40 col 1'))
        finally:
            e.close()

    # ---- the terminal: what it answers is taken up to 200 x 132, and an
    #      answer too small to edit in is not taken at all ----
    for term, want in (((60, 132), (60, 132)), ((100, 255), (100, 132)),
                       ((255, 255), (200, 132)), ((5, 20), (24, 80)),
                       ((1, 1), (24, 80)), ((0, 0), (24, 80))):
        e = Editor(make(400), term=term)
        try:
            check(f'a terminal of {term} is used as {want} ({e.geom()})',
                  e.geom() == want)
            tap(e, 'jx')
            check(f'a terminal of {term}: :q! exits', at_ccp(e, ':q!\r'))
        finally:
            e.close()

    # ---- the length of a line: any length the window can hold ----
    for n in (255, 256, 257, 2048, 5000, 20000):
        e = Editor(b'ab\r\n' + b'x' * n + b'\r\ncd\r\n')
        try:
            tap(e, 'j$')
            g = ctrlg(e)
            check(f'a line of {n}: $ is col {n} ({g!r})',
                  g.endswith(f' line 2 col {n}'))
            tap(e, 'x'); tap(e, 'k'); tap(e, 'j0x')
            tap(e, ':w\r')
            got = saved_bytes(e)
            check(f'a line of {n}: an x at each end, byte-exact ({len(got)} bytes)',
                  got == b'ab\r\n' + b'x' * (n - 2) + b'\r\ncd\r\n')
        finally:
            e.close()

    # a line can be yanked and put while the copies fit ...
    e = Editor(b'ab\r\n' + b'x' * 5000 + b'\r\ncd\r\n')
    try:
        tap(e, 'jyypp')
        alive(e, 'a line of 5000, yy p p')
        tap(e, ':w\r')
        got = saved_bytes(e)
        check(f'a line of 5000, yy p p: three of it ({len(got)} bytes)',
              got == b'ab\r\n' + (b'x' * 5000 + b'\r\n') * 3 + b'cd\r\n')
    finally:
        e.close()

    # ... and when they do not, the editor has to refuse and keep running.
    # A yank and a put of such a line no longer take the editor down -- the
    # screen used to need the whole line in memory to paint the row under it,
    # and with long lines wrapped it needs one screenful.
    for n, keys in ((13000, 'jyypp'), (20000, 'jyy')):
        e = Editor(b'ab\r\n' + b'x' * n + b'\r\ncd\r\n')
        try:
            before = len(e.cap.getvalue())
            e.s.send(keys)
            idle(e)
            check(f'a line of {n}, {keys}: the editor keeps running',
                  not PROMPT.search(e.cap.getvalue()[before:]))
            if 'p' in keys:
                # ... but the put goes in where the RESIDENT text ends, not
                # where the line does: the line is cut in two (issue #21)
                e.key(':w\r')
                got = [len(l) for l in saved_bytes(e).split(b'\r\n')]
                still_open(21, f'a line of {n}, {keys}: three whole lines '
                           f'written ({got})', got == [2, n, n, n, 2, 0])
        finally:
            e.close()
    # Running to the end of a line the arena cannot hold still exits to CP/M
    # with the work lost (issue #21).
    # (The typed text is 2000 characters so that the line passes the arena by
    # a margin whatever the image's size has done to it: 400 sat on the edge,
    # and stopped overflowing when the arena moved by 74 bytes.)
    for n, keys in ((26000, 'j$a' + 'y' * 2000), (30000, 'j$')):
        e = Editor(b'ab\r\n' + b'x' * n + b'\r\ncd\r\n')
        try:
            before = len(e.cap.getvalue())
            e.s.send(keys)
            idle(e)
            still_open(21, f'a line of {n}, {keys[:6]}: the editor keeps running',
                       not PROMPT.search(e.cap.getvalue()[before:]))
        finally:
            e.close()

    # a line the arena cannot hold at all opens all the same: the screen
    # shows the line above it and '@' rows where it will not fit, and nothing
    # of it has to be in memory until the cursor goes there
    for n in (30000, 45000):
        data = b'ab\r\n' + b'x' * n + b'\r\ncd\r\n'
        e = Editor(data)
        try:
            r = rows(e)
            check(f'a line of {n}: the file opens, the line as @ rows '
                  f'({r[0]!r} {r[1]!r} .. {r[22]!r})',
                  r[0] == 'ab' and r[1:23] == ['@'] * 22)
            e.key('j')
            r = rows(e)
            check(f'a line of {n}: the cursor on it, its first rows are shown',
                  r[:23] == ['x' * 80] * 23)
            check(f'a line of {n}: :q exits', at_ccp(e, ':q\r'))
            got = saved_bytes(e)
            check(f'a line of {n}: the file is untouched ({len(got)} bytes)',
                  got == data)
        finally:
            e.close()


def tstates(e):
    """The emulated 8080's T-state clock (2 MHz), from the simulator's monitor.
    It counts the CPU, the 9600-baud console and the BIOS's disk polling; the
    drive model has no seek or rotation, so a real floppy is slower still."""
    raw = e.s._rpc("tools/call", {"name": "monitor",
                                  "arguments": {"command": "SHOW CLOCK"}})
    out = "".join(b.get("text", "") for b in raw.get("content", []))
    return int(re.search(r'\((\d+) T-states\)', out).group(1))


def run_for(e, seconds):
    """Let the guest run for *seconds* of its own clock, mid-command."""
    until = tstates(e) + int(seconds * 2e6)
    while tstates(e) < until:
        e.s._run(timeout_ms=100)


def resp_lines(n):
    """*n* lines of the kind this editor is for: assembler source, TABs in
    it, 5 to 79 columns wide.  A screen of these is about 1,100 bytes."""
    out = []
    for i in range(n):
        m = i % 6
        if m == 0:
            out.append(';----- routine %05d: move the block and count what '
                       'is left ----------' % i)
        elif m == 1:
            out.append('LBL%05d:\tLXI\tH,BUFFER+%d\t; point at the next '
                       'record in the table' % (i, i % 200))
        elif m == 2:
            out.append('\tMOV\tA,M\t\t; fetch the byte and test it')
        elif m == 3:
            out.append('\tCPI\t%d\t\t; is it the end marker for this pass?'
                       % (i % 250))
        elif m == 4:
            out.append('\tJNZ\tLBL%05d\t; no -- go round again until the '
                       'count runs out' % (i - 3))
        else:
            out.append('\tRET')
    return ''.join(l + '\r\n' for l in out).encode()


# What a key may take, in emulated seconds on the 2 MHz 8080 at 9600 baud,
# with a full screen of ordinary lines (resp_lines).  The clock runs from the
# key to the editor asking for the next one, as the harness sees it: that
# reads about 0.06 s for a key that does nothing at all, so a budget of 0.10
# is 0.04 s of the editor's own time.  (setup keys, the key, the budget)
RESP = [
    ('j', ['3j'], 'j', 0.10),
    ('k', ['3j'], 'k', 0.10),
    ('l', ['3j', '5w'], 'l', 0.10),
    ('h', ['3j', '$'], 'h', 0.10),
    ('w', ['3j', '5w'], 'w', 0.10),
    ('b', ['3j', '$'], 'b', 0.10),
    ('$', ['3j'], '$', 0.10),
    ('0', ['3j', '$'], '0', 0.10),
    ('j, eight lines down the screen', ['12j'], 'j', 0.10),
    ('k, on the bottom row', ['L'], 'k', 0.10),
    ('a char typed mid-line', ['3j', '5w', 'i'], 'Z', 0.10),
    ('a char typed at the line end', ['3j', 'A'], 'Z', 0.10),
    ('a second char typed', ['3j', '5w', 'iQ'], 'Z', 0.10),
    ('x', ['3j', '5w'], 'x', 0.10),
    ('r', ['3j', '5w'], 'rZ', 0.12),
    ('BS in insert', ['3j', '5w', 'iQQ'], '\x08', 0.10),
    ('ESC from insert', ['3j', '5w', 'iQ'], '\x1b', 0.10),
    ('j off the bottom row', ['L'], 'j', 0.25),
    ('j off the bottom row again', ['L', 'j'], 'j', 0.25),
    ('k off the top row', ['40j', 'H'], 'k', 0.25),
    ('k off the top row again', ['40j', 'H', 'k'], 'k', 0.25),
    ('a char typed before a TAB', ['3j', 'w', 'i'], 'Z', 0.10),
    ('x before a TAB', ['3j', 'w'], 'x', 0.10),
    ('BS before a TAB', ['3j', 'w', 'iQQ'], '\x08', 0.10),
    # a line comes or goes: the rows under it move, one is new.  ('G' 'gg'
    # first, so that the file's end is not read for the first time here.)
    ('dd', ['G', 'gg', '3j'], 'dd', 0.55),
    ('dd, low on the screen', ['G', 'gg', '18j'], 'dd', 0.55),
    ('o', ['G', 'gg', '3j'], 'o', 0.40),
    ('O', ['G', 'gg', '3j'], 'O', 0.40),
    ('<CR> typed mid-line', ['G', 'gg', '3j', '5w', 'i'], '\r', 0.40),
    ('J', ['G', 'gg', '3j'], 'J', 0.45),
    ('p of a line', ['G', 'gg', '3j', 'yy'], 'p', 0.45),
    ('u of an x', ['3j', '5w', 'x'], 'u', 0.25),
    ('u again (the redo)', ['3j', '5w', 'x', 'u'], 'u', 0.25),
    ('u of a word changed', ['3j', '5w', 'cwNEW\x1b'], 'u', 0.30),
    # whole lines put back or taken again: rows open or close, as for 'P'
    ('u of a dd', ['G', 'gg', '3j', 'dd'], 'u', 0.50),
    ('u again (the dd redone)', ['G', 'gg', '3j', 'dd', 'u'], 'u', 0.35),
    # a span out of the line: the terminal closes the cells up
    ('dw', ['3j', '5w'], 'dw', 0.20),
    ('D', ['3j', '5w'], 'D', 0.15),
    ('cw', ['3j', '5w'], 'cw', 0.25),
]


def resp_cmds():
    """A key answers in the time its own work takes -- not the time it takes
    to read the screen over again, and not longer in a big file.  The moves
    leave the text and the window where they were; the edits change one line
    and none of its rows."""
    for label, data in (('3 K', resp_lines(60)), ('116 K', resp_lines(2350))):
        for name, setup, key, budget in RESP:
            e = Editor(data)
            try:
                for k in setup:
                    e.s.send(k)
                    idle(e)
                took = 0
                for ch in key:
                    t0 = tstates(e)
                    e.s._run(input=ch)
                    took += tstates(e) - t0
                idle(e)
                took /= 2e6
                print(f'  {label:>6} {name!r:36} {took:.3f} s', flush=True)
                check(f'resp {label}: {name!r} answers in {budget:.2f} s '
                      f'(took {took:.3f})', took <= budget)
            finally:
                e.close()


def cell_paint():
    """The one-cell paints: 'r', a char typed over another in replace mode,
    and insert's BS send the cell and no more -- and what they leave on the
    screen is what a full repaint ('^L') draws, at the right edge of the
    screen, on a wrapped line and beside a TAB as well as mid-line."""
    lines = (['plain line %02d of ordinary text, nothing special about it' % i
              for i in range(4)]
             + ['E' * 78, 'F' * 79, 'G' * 80, 'H' * 81, 'W' * 200,
                '\tMOV\tA,M\t\t; a comment after two tabs', 'x', '',
                'ABCDEFG\tX\tthe TAB is one cell wide',
                'ABCDEFGH\tX\tthe TAB is eight wide',
                '\tJNZ\tLBL00001\t; no -- go round again until it is done',
                'LBL1:\tLXI\tH,BUFFER+1\t; point at it']
             + ['tail %02d' % i for i in range(30)])
    data = ''.join(l + '\r\n' for l in lines).encode()

    def rows(v):
        return [''.join(r).rstrip() for r in v.screen[:23]]

    cases = []
    for ln, tag in ((2, 'plain'), (5, '78 wide'), (6, '79 wide'), (7, '80 wide'),
                    (8, '81 wide'), (9, 'wrapped'), (10, 'tabs'), (11, 'one char'),
                    (12, 'empty')):
        for at in ('0', '$', '0w', '078l', '079l'):
            cases += [(ln, tag, at, 'rZ', 32),
                      (ln, tag, at, 'RZYX\x1b', 96),
                      (ln, tag, at, 'RZY\x08\x08\x1b', None),
                      (ln, tag, at, 'iZY\x08\x1b', None),
                      (ln, tag, at, 'aZY\x08\x08\x1b', None)]
            # a span taken out of the line: the terminal closes the cells up
            # (from the line's last char '2dw' and 'de' take the break too;
            # 'cw' pays for the mode word coming and going, as 'i' does)
            inl = 32 if at in ('0', '0w') else None
            cases += [(ln, tag, at, 'dw', 32), (ln, tag, at, 'D', 32),
                      (ln, tag, at, '2dw', inl), (ln, tag, at, 'de', inl),
                      (ln, tag, at, 'd3l', 48), (ln, tag, at, 'db', None),
                      (ln, tag, at, 'd0', None), (ln, tag, at, 'cwQ\x1b', 96)]
    # a char typed or deleted in front of a TAB: the TAB takes up the
    # difference, or (at a tab stop) cannot
    for ln, tag in ((10, 'tabs'), (13, 'TAB 1 wide'), (14, 'TAB 8 wide'),
                    (15, 'asm'), (16, 'label')):
        for at in ('0', '0l', '03l', '0w', '0ww', '$'):
            cases += [(ln, tag, at, 'x', 40 if at == '0w' else None),
                      (ln, tag, at, '3x', None),
                      (ln, tag, at, '9x', None),
                      (ln, tag, at, 'iZ\x1b', 112 if at == '0w' else None),
                      (ln, tag, at, 'iZY\x08\x1b', None),
                      (ln, tag, at, 'iZYXWVUTS\x1b', None),
                      (ln, tag, at, 'aZ\x08\x08\x1b', None)]
    e = Editor(data)
    try:
        for ln, tag, at, keys, budget in cases:
            e.key(f'{ln}G')
            e.key(at)
            before = len(e.cap.getvalue())
            for k in re.split('(\x1b)', keys):
                if k == '\x1b':
                    send_keys(e, k)
                elif k:
                    for ch in k:
                        e.key(ch)
            sent = len(e.cap.getvalue()) - before
            v1 = e.screen()
            s1 = rows(v1)
            e.key('\x0c')
            v2 = e.screen()
            name = f'cell {tag} at {at!r} {keys!r}'
            check(f'{name}: the screen is what a full repaint draws '
                  f'(cursor {v1.row},{v1.col}, ^L {v2.row},{v2.col})',
                  rows(v2) == s1 and (v2.row, v2.col) == (v1.row, v1.col))
            if budget and tag in ('plain', 'asm'):
                check(f'{name}: {sent} bytes sent, not the row ({budget})',
                      sent <= budget)
            e.key('u')
    finally:
        e.close()


def undo_paint():
    """'u' paints what it changed.  A change that stayed inside one line, with
    the cursor still on that line, is that line and no more; and whatever
    'u' puts back, the screen is then what a full repaint ('^L') draws --
    for the undo and for the redo, on a wrapped line and beside TABs, with
    the cursor moved along the line or off it first."""
    lines = (['plain line %02d of ordinary text, nothing special about it' % i
              for i in range(4)]
             + ['W' * 70 + ' wide words ' * 12,
                '\tMOV\tA,M\t\t; a comment after two tabs',
                'LBL1:\tLXI\tH,BUFFER+1\t; point at it', 'x', '']
             + ['tail %02d of the file, an ordinary line again' % i
                for i in range(30)])
    data = ''.join(l + '\r\n' for l in lines).encode()

    def rows(v):
        return [''.join(r).rstrip() for r in v.screen[:23]]

    changes = ['x', '3x', 'X', 'dw', 'D', 'd0', 'rZ', '~', 'cwNEW\x1b',
               'iin\x1b', 'Aend\x1b', 'R123\x1b', ':s/a/QQQ/\r', 'J', 'dd',
               'otext\x1b', 'yyp', '2dd', 'i\r\x1b', 'yyP', '3dd',
               'Onew\x1b', 'yy2P']
    cases = []
    for ln, tag, ats in ((2, 'plain', ('0w', '$')), (5, 'wrapped', ('0w', '$')),
                         (6, 'tabs', ('0w',)), (8, 'one char', ('0',)),
                         (9, 'empty', ('0',))):
        for at in ats:
            for ch in changes:
                cases.append((ln, tag, at, ch, ''))
            if tag in ('plain', 'wrapped') and at == '0w':
                for ch in ('x', 'd0', 'cwNEW\x1b', 'dd'):
                    for between in ('$', '0', 'j', '3k'):
                        cases.append((ln, tag, at, ch, between))
    e = Editor(data)
    try:
        for ln, tag, at, ch, between in cases:
            e.key(f'{ln}G')
            e.key(at)
            for k in re.split('(\x1b)', ch):
                if k:
                    send_keys(e, k)
            if between:
                e.key(between)
            for what in ('undo', 'redo'):
                before = len(e.cap.getvalue())
                e.key('u')
                sent = len(e.cap.getvalue()) - before
                v1 = e.screen()
                s1 = rows(v1)
                e.key('\x0c')
                v2 = e.screen()
                name = f'u {tag} at {at!r} {ch!r} {between!r} {what}'
                check(f'{name}: the screen is what a full repaint draws '
                      f'(cursor {v1.row},{v1.col}, ^L {v2.row},{v2.col})',
                      rows(v2) == s1 and (v2.row, v2.col) == (v1.row, v1.col))
                if (tag == 'plain' and between in ('', '$', '0')
                        and ch in ('x', '3x', 'X', 'dw', 'D', 'rZ', '~',
                                   'cwNEW\x1b', 'iin\x1b', 'Aend\x1b')):
                    check(f'{name}: {sent} bytes sent, the line and not the '
                          f'screen (120)', sent <= 120)
                # whole lines put back or taken: the rows under them move,
                # and the lines put back are all that is sent
                lim = {('dd', 'undo'): 200, ('dd', 'redo'): 200,
                       ('yyP', 'undo'): 200, ('yyP', 'redo'): 200,
                       ('2dd', 'undo'): 300, ('3dd', 'undo'): 400,
                       ('yy2P', 'redo'): 300}.get((ch, what))
                if tag == 'plain' and between == '' and lim:
                    check(f'{name}: {sent} bytes sent, the lines and not '
                          f'the screen ({lim})', sent <= lim)
            e.key('u')                  # (the text as it was, for the next)
            if e.screen().row == 23:    # (a refusal on the bottom row)
                e.key('\x1b')
    finally:
        e.close()


def step_lines(n=149):
    """Lines for the one-line scroll: ordinary ones, with lines of two and
    three rows, one just as wide as the screen and empty ones among them."""
    out = []
    for i in range(n):
        m = i % 11
        if m == 3:
            out.append('W%03d ' % i + 'wide line of words ' * (5 + i % 7))
        elif m == 6:
            out.append('')
        elif m == 8:
            out.append(('E%03d' % i).ljust(79 + i % 3, '='))
        elif m == 9:
            out.append('\tMOV\tA,M\t\t; line %03d, with TABs in it' % i)
        else:
            out.append('line %03d of ordinary text' % i)
    return out


def step_scroll():
    """'j' on the bottom line and 'k' on the top one move the screen by as
    little as shows the cursor's line whole, as vim does, and what is on the
    screen then is the text from that top line down: the lines that fit, '@'
    on the rows of one that does not, '~' past the end.  The whole file, down
    and back, a line at a time; with and without a line end on the last line;
    and with other keys between the steps."""
    def cells(l):
        return l.expandtabs(8)

    def height(l):
        return max(1, -(-len(cells(l)) // 80))

    def lay(L, top):
        out = []
        for l in L[top:]:
            c = cells(l)
            r = [c[i:i + 80] for i in range(0, len(c), 80)] or ['']
            if len(out) + len(r) > 23:
                out += ['@'] * (23 - len(out))
                break
            out += r
        return [x.rstrip() for x in out + ['~'] * (23 - len(out))]

    def run(tag, L, data, keys):
        e = Editor(data)
        bad = []
        try:
            top = cur = 0
            for n, k in enumerate(keys):
                e.key(k)
                if k == 'j' and cur < len(L) - 1:
                    cur += 1
                    while sum(height(l) for l in L[top:cur + 1]) > 23:
                        top += 1
                elif k == 'k' and cur > 0:
                    cur -= 1
                    top = min(top, cur)
                elif k == 'x':
                    L[cur] = L[cur][1:] if len(L[cur]) > 1 else L[cur]
                v = e.screen()
                got = [''.join(r).rstrip() for r in v.screen[:23]]
                row = sum(height(l) for l in L[top:cur])
                if got != lay(L, top) or not row <= v.row < row + height(L[cur]):
                    bad.append((n, k, cur, top, v.row))
                    break
            check(f'step {tag}: {len(keys)} keys, each screen is the text '
                  f'from its top line down (first wrong: {bad[:1]})', not bad)
            return e, top, cur
        except Exception:
            e.close()
            raise

    for tag, tail in (('ended', '\r\n'), ('no line end on the last', '')):
        L = step_lines()
        data = ('\r\n'.join(L) + tail).encode()
        n = len(L)
        e, top, cur = run(tag, L, data, ['j'] * (n + 2) + ['k'] * (n + 2))
        e.close()
    # a file the arena does not hold: the pager moves the text on the way
    L = step_lines(1000)
    data = ('\r\n'.join(L) + '\r\n').encode()
    e, top, cur = run(f'{len(data) // 1024} K, paged', L, data,
                      ['j'] * 1001 + ['k'] * 1001)
    e.close()
    # other keys between the steps: an edit, a move along the line, a step
    # back the other way
    L = step_lines()
    data = ('\r\n'.join(L) + '\r\n').encode()
    keys = ['j'] * 30 + ['j', 'x', 'j', 'k', 'k', 'j', 'j', 'j'] * 20 \
        + ['k'] * 40 + ['k', 'x', 'k', 'j', 'j', 'k', 'k', 'k'] * 20
    e, top, cur = run('with other keys between', L, data, keys)
    try:
        e.key(':w\r')
        check('step with other keys between: :w byte-exact',
              saved_bytes(e) == ('\r\n'.join(L) + '\r\n').encode())
    finally:
        e.close()


def brk_cmds():
    """ESC abandons a search or a long move: the cursor and the screen go back
    to where the command started, the bottom row says so, and whatever was
    typed ahead is thrown away with it.  Only commands that change no text are
    stopped; a delete that pages runs to its end, ESC or not.  The ESC is
    answered the moment it is seen ('Interrupting...'), and 'Interrupted'
    replaces that once the cursor is back.  '^C' is not the
    key for it, and a key that SENDS an ESC sequence (an arrow, PgDn) is not
    decoded: its bytes are keystrokes like any others."""
    big = make(12800)

    def start(e, ln):
        e.s.send(f'{ln}G')
        idle(e)

    def cancel(e, keys, ln, tag, after=4.0, ahead='', limit=30):
        """*keys* from line *ln*, 'ESC' *after* seconds into them."""
        v0 = e.screen()
        scr0 = [''.join(r) for r in v0.screen]
        idle(e)
        t0 = tstates(e)
        e.s.send(keys)
        run_for(e, after)
        sent = len(e.cap.getvalue())
        e.s.send(ahead + '\x1b')
        idle(e)
        took = (tstates(e) - t0) / 2e6
        out = e.cap.getvalue()[sent:]
        check(f'{tag}: {keys!r} ESC is answered before the way back '
              f'({out[-60:]!r})',
              'Interrupting...' in out
              and out.index('Interrupting...') < out.rindex('Interrupted'))
        v = e.screen()
        scr = [''.join(r) for r in v.screen]
        check(f'{tag}: {keys!r} ESC says so ({bottom(e)!r})',
              bottom(e) == 'Interrupted')
        check(f'{tag}: {keys!r} ESC keeps the screen and the cursor',
              scr[:23] == scr0[:23] and (v.row, v.col) == (v0.row, v0.col))
        check(f'{tag}: {keys!r} ESC is back in {took:.1f} s ({limit} allowed)',
              took < limit)
        e.s.send('\x07')
        idle(e)
        check(f'{tag}: {keys!r} ESC leaves the cursor on line {ln} '
              f'({bottom(e)!r})', f'line {ln} ' in bottom(e))
        e.s.send('\x0c')
        idle(e)
        v = e.screen()
        scr = [''.join(r) for r in v.screen]
        check(f'{tag}: {keys!r} ESC and a repaint draws the same screen',
              scr[:23] == scr0[:23] and (v.row, v.col) == (v0.row, v0.col))

    # --- the moves and the searches, each stopped part of the way there.
    #     Uncancelled these take 22 to 65 s (TIMECOST.md). ---
    e = Editor(big)
    try:
        start(e, 6000)
        e.s.send('ma')
        idle(e)
        cancel(e, 'G', 6000, 'brk G')
        cancel(e, 'gg', 6000, 'brk gg')
        cancel(e, '12000G', 6000, 'brk 12000G')
        # ('/' has come back in 27 to 31 s over many runs: the moment the ESC
        #  lands is not exact.  Left alone it takes 65.)
        cancel(e, '/zzzz\r', 6000, 'brk /', limit=45)
        cancel(e, '?zzzz\r', 6000, 'brk ?')
        cancel(e, 'n', 6000, 'brk n')
        cancel(e, 'N', 6000, 'brk N')
        # ... in the pass AFTER the wrap, which is a second sweep
        cancel(e, '/zzzz\r', 6000, 'brk / wrapped', after=40.0, limit=110)
        # the editor is whole afterwards: the same commands, left to finish
        e.s.send('/012000\r')
        idle(e)
        v = e.screen()
        got = ''.join(v.screen[v.row]).rstrip()
        check(f'brk: a search left alone still finds its line ({got!r})',
              got == txt(12000))
        cancel(e, "'a", 12000, "brk 'a")
        cancel(e, '`a', 12000, 'brk `a')
        e.s.send("'a")
        idle(e)
        v = e.screen()
        got = ''.join(v.screen[v.row]).rstrip()
        check(f"brk: 'a left alone still goes to its mark ({got!r})",
              got == txt(6000))
        # --- what was typed ahead goes with it: an 'x' before the ESC and one
        #     while the window pages back are both dropped ---
        v0 = e.screen()
        e.s.send('G')
        run_for(e, 4.0)
        e.s.send('xx\x1b')
        run_for(e, 0.5)
        e.s.send('x')
        idle(e)
        check(f"brk: G xxESC x says Interrupted ({bottom(e)!r})",
              bottom(e) == 'Interrupted')
        e.s.send('\x07')
        idle(e)
        check(f"brk: G xxESC x changed nothing ({bottom(e)!r})",
              'line 6000 ' in bottom(e) and '[+]' not in bottom(e)
              and 'Modified' not in bottom(e))
        # ... and a key typed once it is back is a key again
        e.s.send('j')
        idle(e)
        v = e.screen()
        got = ''.join(v.screen[v.row]).rstrip()
        check(f'brk: j afterwards moves a line ({got!r})', got == txt(6001))
        # --- an arrow key's first byte is an ESC, so it stops the move too,
        #     and the rest of it goes with the type-ahead: the 'A' that ends
        #     a cursor-up must not open an insert ---
        e.s.send('6000G')
        idle(e)
        e.s.send('G')
        run_for(e, 4.0)
        e.s.send('\x1b[A')
        idle(e)
        check(f"brk: G then an arrow key says Interrupted ({bottom(e)!r})",
              bottom(e) == 'Interrupted')
        e.s.send('j\x07')
        idle(e)
        check(f"brk: ... and its last byte opened no insert ({bottom(e)!r})",
              'line 6001 ' in bottom(e) and 'Modified' not in bottom(e))
        # --- '^C' is not the key: the move runs to its end ---
        e.s.send('6000G')
        idle(e)
        e.s.send('G')
        run_for(e, 4.0)
        e.s.send('\x03')
        idle(e)
        check(f"brk: G ^C is not interrupted ({bottom(e)!r})",
              bottom(e) != 'Interrupted')
        e.s.send('\x07')
        idle(e)
        check(f"brk: G ^C still went to the last line ({bottom(e)!r})",
              'line 12800 ' in bottom(e) and 'Modified' not in bottom(e))
        check('brk: nothing was changed (:q exits)', at_ccp(e, ':q\r'))
    finally:
        e.close()

    # --- a command that changes text is NOT stopped: 'dG' takes its lines ---
    e = Editor(big)
    try:
        start(e, 6000)
        e.s.send('dG')
        run_for(e, 4.0)
        e.s.send('\x1b')
        idle(e)
        check(f"brk: dG ESC is not interrupted ({bottom(e)!r})",
              bottom(e) != 'Interrupted')
        e.s.send('\x07')
        idle(e)
        check(f"brk: dG ESC still deleted to the end ({bottom(e)!r})",
              'line 5999 ' in bottom(e))
        e.s.send(':w\r')
        idle(e)
        got = saved_bytes(e)
        check(f'brk: dG ESC saved {len(got)} bytes, the first 5999 lines',
              got == big[:5999 * 8])
    finally:
        e.close()

    # --- 'ESC' with nothing running is no cancel waiting to happen: the next
    #     move goes where it is sent ---
    e = Editor(big)
    try:
        e.s.send('\x1b')
        idle(e)
        e.s.send('300G')
        idle(e)
        v = e.screen()
        got = ''.join(v.screen[v.row]).rstrip()
        check(f'brk: ESC at rest, then 300G goes to line 300 ({got!r})',
              got == txt(300) and bottom(e) != 'Interrupted')
        # ... and one that arrives after a short move is done cancels nothing
        e.s.send('310G')
        idle(e)
        e.s.send('\x1b')
        idle(e)
        v = e.screen()
        got = ''.join(v.screen[v.row]).rstrip()
        check(f'brk: 310G then ESC stays on line 310 ({got!r})',
              got == txt(310) and bottom(e) != 'Interrupted')
    finally:
        e.close()

    # --- no key that starts with an ESC is decoded.  An up-arrow is ESC, '[',
    #     'A': nothing, nothing, append at the line's end.  PgDn is ESC, '[',
    #     '6', '~': a count for '~', which takes none.  Home is ESC, '[', 'H'. ---
    small = b'abcdefgh\r\nsecond line\r\nthird\r\n'
    for keys, more, want, what in (
            ('\x1b[A', 'Q\x1b', b'abcdefghQ\r\nsecond line\r\nthird\r\n',
             'an up-arrow appends'),
            ('\x1bOB', 'Q\x1b', b'BQ\r\nabcdefgh\r\nsecond line\r\nthird\r\n',
             'a keypad down-arrow opens a line above and types a B'),
            ('\x1b[6~', '', b'Abcdefgh\r\nsecond line\r\nthird\r\n',
             'PgDn is 6~, and ~ takes no count'),
            ('j\x1b[H', 'x', b'bcdefgh\r\nsecond line\r\nthird\r\n',
             'Home is H, the top line of the screen')):
        e = Editor(small)
        try:
            tap(e, keys)
            if more:
                tap(e, more)
            tap(e, ':w\r')
            got = saved_bytes(e)
            check(f'brk: {keys!r} is typed keys -- {what} ({got[:24]!r})',
                  got == want)
        finally:
            e.close()


def lnum_cmds():
    """The line feeds behind the window are COUNTED as the pager moves them
    (PAGE.MAC TOPLF), so the cursor's line number never costs a disk read:
    '^G' answers at once anywhere in a 100 K file, and '{n}G' -- with every
    command built on it, ':N,Ms' and 'd{n}G' included -- moves from where the
    cursor is instead of going back to line 1 first.  Each bound is emulated
    seconds; before the count was kept they were 30 s, 14 s, 80 s and 31 s."""
    def at(e):
        v = e.screen()
        return ''.join(v.screen[v.row]).rstrip()

    def timed(e, keys, settle=None):
        e.s.run_until_quiet(quiet=1.5, timeout=120)
        t0 = tstates(e)
        e.key(keys)
        e.s.run_until_quiet(quiet=1.5, timeout=600)
        if settle:
            settle(e)
        return (tstates(e) - t0) / 2e6

    big = make(12800)
    L = [line(i) for i in range(1, 12801)]

    def want(n):
        return L[n - 1].decode()[:6]

    def go(e, keys):
        e.key(keys)
        e.s.run_until_quiet(quiet=1.5, timeout=300)
    e = Editor(big)
    try:
        e.key('6000G')
        e.s.run_until_quiet(quiet=1.5, timeout=300)
        check(f'lnum 6000G: on its line ({at(e)!r})', at(e) == txt(6000))
        for keys, ln, limit in (('6100G', 6100, 6), ('5900G', 5900, 6),
                                ('6000G', 6000, 6)):
            s = timed(e, keys)
            check(f'lnum {keys}: on its line ({at(e)!r})', at(e) == txt(ln))
            check(f'lnum {keys}: moves from the cursor, not from line 1 '
                  f'({s:.1f} s, {limit} allowed)', s < limit)
        # (a line delete that pages takes its lines without yanking them)
        s = timed(e, 'd6500G')
        del L[5999:6500]
        g = ctrlg(e)
        check(f'lnum d6500G: took its 501 lines ({at(e)!r}, {g!r})',
              at(e) == want(6000) and 'line 6000 ' in g)
        check(f'lnum d6500G: costs what the delete costs ({s:.1f} s, 10 allowed)',
              s < 10)

        go(e, '3000G')
        g = ctrlg(e)
        check(f'lnum 3000G: paged back to its line ({at(e)!r}, {g!r})',
              at(e) == want(3000) and 'line 3000 ' in g)
        go(e, 'G')
        s = timed(e, '\x07')
        g = bottom(e)
        check(f'lnum G ^G: the last line ({g!r})', f'line {len(L)} ' in g)
        check(f'lnum G ^G: without reading the file back ({s:.1f} s, 3 allowed)',
              s < 3)
        s = timed(e, '12200G')
        check(f'lnum 12200G from the end: on its line ({at(e)!r})',
              at(e) == want(12200))
        check(f'lnum 12200G from the end: moves from the cursor '
              f'({s:.1f} s, 6 allowed)', s < 6)

        # ---- the count follows the text as edits move line ends about ----
        go(e, '6000G'); go(e, '300dd')
        reg = L[5999:6299]
        del L[5999:6299]
        go(e, '9000G')
        g = ctrlg(e)
        check(f'lnum 300dd 9000G: 300 lines fewer above it ({at(e)!r}, {g!r})',
              at(e) == want(9000) and 'line 9000 ' in g)
        go(e, '6000G'); go(e, 'P')
        L[5999:5999] = reg
        go(e, '9000G')
        check(f'lnum P 9000G: and back again ({at(e)!r})', at(e) == want(9000))
        go(e, '6000G')
        e.key('oabc\rdef'); escaped(e)
        L[6000:6000] = [b'abc\r\n', b'def\r\n']
        go(e, '1G'); go(e, '6003G')
        check(f'lnum o 1G 6003G: two lines more above it ({at(e)!r})',
              at(e) == want(6003))
        go(e, '7000G')
        check(f'lnum 7000G: ({at(e)!r})', at(e) == want(7000))
        e.key('dd')
        del L[6999]
        go(e, '12000G')
        g = ctrlg(e)
        check(f'lnum dd 12000G: ({at(e)!r}, {g!r})',
              at(e) == want(12000) and 'line 12000 ' in g)

        # ---- ':N,Ms' starts from the cursor too ----
        go(e, '6000G')
        s = timed(e, ':6003,6102s/0/9/\r', settle=ex_settled)
        for i in range(6002, 6102):
            L[i] = L[i].replace(b'0', b'9', 1)
        g = ctrlg(e)
        check(f'lnum :6003,6102s: ends on its last line ({at(e)!r}, {g!r})',
              at(e) == want(6102) and 'line 6102 ' in g)
        check(f'lnum :6003,6102s: costs its hundred lines ({s:.1f} s, 12 allowed)',
              s < 12)

        # ---- ':w' reloads the file and seeks back: the count is rebuilt ----
        n = len(e.cap.getvalue())
        e.key(':w\r'); ex_settled(e)
        e.s.run_until_quiet(quiet=1.5, timeout=300)
        check('lnum :w: the editor is still running',
              not PROMPT.search(e.cap.getvalue()[n:]))
        g = ctrlg(e)
        check(f'lnum :w ^G: the line it was on ({g!r})', 'line 6102 ' in g)
        s = timed(e, '6200G')
        check(f'lnum :w 6200G: on its line ({at(e)!r})', at(e) == want(6200))
        # (a page of the file may come in on the way, as the arena falls:
        #  9 s then; from line 1 it is over 20)
        check(f'lnum :w 6200G: moves from the cursor ({s:.1f} s, 12 allowed)',
              s < 12)
        go(e, 'gg')
        g = ctrlg(e)
        check(f'lnum gg: line 1 ({at(e)!r}, {g!r})',
              at(e) == txt(1) and 'line 1 ' in g)
        go(e, '99999G')
        last = f'line {len(L)} '
        g = ctrlg(e)
        check(f'lnum 99999G: past the end is the last line ({at(e)!r}, {g!r})',
              at(e) == txt(12800) and last in g)
        e.key(':e!\r'); ex_settled(e)
        e.s.run_until_quiet(quiet=1.5, timeout=300)
        g = ctrlg(e)
        check(f'lnum :e!: reloaded onto the same line ({g!r})', last in g)
        got = saved_bytes(e)            # (leaves the editor: it comes last)
        check(f'lnum :w: byte-exact ({len(got)} bytes)', got == b''.join(L))
    finally:
        e.close()

    # ---- lines past the right edge: 109 K in 1500 lines ----
    e = Editor(make_wide())
    try:
        e.key('G'); e.s.run_until_quiet(quiet=1.5, timeout=300)
        s = timed(e, '\x07')
        g = bottom(e)
        check(f'lnum wide G ^G: ({g!r}, {s:.1f} s, 3 allowed)',
              'line 1500 ' in g and s < 3)
        for keys, ln in (('1400G', 1400), ('1450G', 1450), ('700G', 700),
                         ('760G', 760), ('2gg', 2)):
            s = timed(e, keys)
            g = ctrlg(e)
            check(f'lnum wide {keys}: ({at(e)[:6]!r}, {g!r})',
                  at(e)[:6] == txt(ln) and f'line {ln} ' in g)
            if keys in ('1450G', '760G'):
                check(f'lnum wide {keys}: moves from the cursor '
                      f'({s:.1f} s, 6 allowed)', s < 6)
    finally:
        e.close()


def rdwr_files():
    """What ':r' and a ranged ':w' need beyond hml_files(): numbered lines with
    three unlike ones after them -- the first indented, the last with no line
    end -- so ':61,63w' makes a file whose first non-blank is not column 0 and
    which ends without a line end."""
    return dict(hml_files(), rw=make(60) + b'  ind\r\nbb\r\ncc')


# ---------------------------------------------------------------------------
# VIM_RDWR -- ':N,Mw {file}' and ':r {file}' against vim 9.1, recorded by
# vimref.py ('rdwr') BEFORE either was written.  Shape is VIM_MARKS's: (file,
# keys, the sha1 of the file vim wrote, [(cursor row, column, cursor line, top
# line) after each key]).  Every row makes the file it reads with a ranged
# write of its own, so the two commands are held together.
#
# What the rows pin down:
#   - a ranged write moves nothing: the cursor, the column and the window are
#     where they were.
#   - ':r' puts the text in below the cursor's line and lands on the FIRST line
#     read, on its first non-blank; ':{n}r' below line n, ':0r' above line 1,
#     ':N,Mr' below line M.  The window is placed as a jump to that line is.
#   - a file that ends without a line end still reads in as whole lines when
#     text follows it, and below a last line that has no line end the missing
#     break goes in first.
#   - 'u' takes a read back out and puts the cursor back where the ':' was typed.
#   - a file that is not there changes nothing and moves nothing.
#   - lines wider than the screen (the wide file, 'nowrap').
VIM_RDWR = [
    ('rw', [':61,63w! R.TXT\r', '30G', '3l', ':r R.TXT\r', 'u'], 'e37ad572aa155c38',
     [(0, 0, '000001', '000001'),
      (22, 0, '000030', '000008'),
      (22, 3, '000030', '000008'),
      (22, 2, '  ind', '000009'),
      (21, 3, '000030', '000009')]),
    ('rw', [':61,63w! R.TXT\r', '30G', ':0r R.TXT\r'], '099b1c5b547071c0',
     [(0, 0, '000001', '000001'),
      (22, 0, '000030', '000008'),
      (0, 2, '  ind', '  ind')]),
    ('rw', [':61,63w! R.TXT\r', '30G', ':10r R.TXT\r'], '9a276d45fb80e230',
     [(0, 0, '000001', '000001'),
      (22, 0, '000030', '000008'),
      (3, 2, '  ind', '000008')]),
    ('rw', [':61,63w! R.TXT\r', '30G', ':25r R.TXT\r'], 'fa315d2a54a6ee8f',
     [(0, 0, '000001', '000001'),
      (22, 0, '000030', '000008'),
      (18, 2, '  ind', '000008')]),
    ('rw', [':61,63w! R.TXT\r', '30G', ':40r R.TXT\r'], '6d6fc83403abba68',
     [(0, 0, '000001', '000001'),
      (22, 0, '000030', '000008'),
      (22, 2, '  ind', '000019')]),
    ('rw', [':61,63w! R.TXT\r', '30G', ':63r R.TXT\r'], 'f4aaf69f76eec9f4',
     [(0, 0, '000001', '000001'),
      (22, 0, '000030', '000008'),
      (20, 2, '  ind', '000044')]),
    ('rw', [':61,63w! R.TXT\r', '30G', ':5,7r R.TXT\r'], '9e847263301e7926',
     [(0, 0, '000001', '000001'),
      (22, 0, '000030', '000008'),
      (0, 2, '  ind', '  ind')]),
    ('rw', ['30G', '3l', ':r NOSUCH.TXT\r'], 'e37ad572aa155c38',
     [(22, 0, '000030', '000008'),
      (22, 3, '000030', '000008'),
      (22, 3, '000030', '000008')]),
    ('rw', [':5,7w! R.TXT\r', 'G', ':r R.TXT\r'], '36794535ef43faf4',
     [(0, 0, '000001', '000001'),
      (22, 0, 'cc', '000041'),
      (22, 0, '000005', '000042')]),
    ('wide', [':3,4w! R.TXT\r', '5G', ':r R.TXT\r', '$'], '1838ff637584f537',
     [(0, 0, '000001', '000001'),
      (6, 0, '000005', '000001'),
      (7, 0, '000003xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '000001'),
      (9, 199, '000003xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', '000001')]),
    ('ind', [':500,502w! R.TXT\r', '1000G', ':r R.TXT\r'], '277689c3ecf3a029',
     [(0, 0, '    000001', '    000001'),
      (11, 10, '\t  001000', '    000989'),
      (12, 10, '\t  000500', '    000989')]),
    ('num', [':6000,6002w! R.TXT\r', '12000G', ':100r R.TXT\r'], 'd854c59d30956d6f',
     [(0, 0, '000001', '000001'),
      (11, 0, '012000', '011989'),
      (11, 0, '006000', '000090')]),]


def rdwr_like_vim():
    """':N,Mw {file}' and ':r {file}' land where vim lands them and leave the
    file byte-exact."""
    import hashlib
    files = rdwr_files()
    for f, keys, sha, want in VIM_RDWR:
        e = Editor(files[f])
        try:
            for k, (wrow, wcol, wcur, wtop) in zip(keys, want):
                e.key(k)
                if k.startswith(':'):
                    ex_settled(e)
                r = rows(e); v = e.screen()
                dc, lr = curs(e, v)
                shown = lambda t: expand(t)[:80].rstrip()
                got = (v.row, dc, r[lr], r[0])
                check(f'vim rdwr {f} {keys!r} {k!r}: {got[:2]} {got[2][:14]!r} '
                      f'== {(wrow, wcol)} {wcur[:14]!r}',
                      got == (wrow, wcol, shown(wcur), shown(wtop)))
            e.key(':w\r')
            ex_settled(e)
            got = hashlib.sha1(saved_bytes(e)).hexdigest()[:16]
            check(f'vim rdwr {f} {keys!r}: file as vim wrote it ({got})',
                  got == sha)
        finally:
            e.close()


def rdwr_cmds():
    """':N,Mw {file}' and ':r {file}' beyond the recorded vim rows: what each
    refuses and how it says so, what the files hold afterwards, an empty file,
    an empty buffer, and the reason both exist -- a block bigger than the yank
    register moved through a file on 100 K, and on the wide file, with the
    line number, a mark and the modified flag right afterwards.

    Where this is NOT vim (COMMANDS.md): a ranged write never goes to the
    buffer's own file, '!' or not; ':r' with no name reads nothing; a write
    whose last line is past the end stops at the end; and ':0r' into an empty
    buffer leaves exactly the file read, without vim's empty last line."""
    def L(a, b):
        return b''.join(line(i) for i in range(a, b + 1))

    def at(e):
        v = e.screen()
        return ''.join(v.screen[v.row]).rstrip()

    def ex(e, keys, timeout=600):
        e.key(keys)
        e.s.run_until_quiet(quiet=1.5, timeout=timeout)
        ex_settled(e)

    def again(e, name):
        """Back into the editor from the CCP, on *name*."""
        e.cap.seek(0); e.cap.truncate(0)
        e.s.send(f'VI {name}\r')
        e.s.run_until_quiet(quiet=1, timeout=40)

    rw = rdwr_files()['rw']
    e = Editor(rw)
    try:
        e.key('30G'); e.key('3l')
        v0 = e.screen(); scr0 = [''.join(r) for r in v0.screen][:23]
        ex(e, ':5,7w OUT.TXT\r')
        v = e.screen()
        check(f'rdwr :5,7w OUT.TXT: says so ({bottom(e)!r})',
              bottom(e) == '"OUT.TXT" written')
        check('rdwr :5,7w OUT.TXT: the cursor and the text are where they were',
              (v.row, v.col) == (v0.row, v0.col)
              and [''.join(r) for r in v.screen][:23] == scr0)
        g = ctrlg(e)
        check(f'rdwr :5,7w OUT.TXT: on the same line, nothing modified ({g!r})',
              'line 30 ' in g and 'Modified' not in g)
        refused(e, ':5,7w OUT.TXT\r', 'File exists (! to force)', 'rdwr')
        ex(e, ':8,9w! OUT.TXT\r')
        check(f'rdwr :8,9w! OUT.TXT: says so ({bottom(e)!r})',
              bottom(e) == '"OUT.TXT" written')
        for keys, msg in ((':5,7w\r', 'No file name'),
                          (':5,7w TEST.TXT\r', 'File exists'),
                          (':5,7w! TEST.TXT\r', 'File exists'),
                          (':70,80w N.TXT\r', 'Invalid range'),
                          (':7,5w N.TXT\r', 'Invalid range'),
                          (':0,3w N.TXT\r', 'Invalid range'),
                          (':2,3wq N.TXT\r', 'Invalid command: 2,3wq N.TXT'),
                          (':2,3e N.TXT\r', 'Invalid command: 2,3e N.TXT'),
                          (':r\r', 'No file name'),
                          (':r NOSUCH.TXT\r', "Can't open file NOSUCH.TXT"),
                          (':99r OUT.TXT\r', 'Invalid range'),
                          (':r OUT.TXT extra\r', 'Invalid file name')):
            refused(e, keys, msg, 'rdwr')
        ex(e, ':62,99w TAIL.TXT\r')
        check(f'rdwr :62,99w: stops at the last line ({bottom(e)!r})',
              bottom(e) == '"TAIL.TXT" written')
        ex(e, ':%w ALL.TXT\r')
        ex(e, ':63,63w LAST.TXT\r')
        ex(e, ':1w ONE.TXT\r')
        g = ctrlg(e)
        check(f'rdwr: after all of them, line 30 still, unmodified ({g!r})',
              'line 30 ' in g and 'Modified' not in g)
        check('rdwr: OUT.TXT holds lines 8 and 9', disk(e, 'OUT.TXT') == L(8, 9))
        check('rdwr: TAIL.TXT holds the text from line 62 on',
              disk(e, 'TAIL.TXT') == b'bb\r\ncc')
        check('rdwr: ALL.TXT holds the whole text', disk(e, 'ALL.TXT') == rw)
        check('rdwr: LAST.TXT holds the last line', disk(e, 'LAST.TXT') == b'cc')
        check('rdwr: ONE.TXT holds line 1', disk(e, 'ONE.TXT') == L(1, 1))
        d = cpm_dir(e)
        check('rdwr: a refused write made no file', not listed(d, 'N.TXT'))
        check(f'rdwr: no work files left {work_files(d)}', not work_files(d))

        # ---- a file with nothing in it (the CCP's SAVE 0 makes one) ----
        e.s.cmd('SAVE 0 E.TXT')
        again(e, 'TEST.TXT')
        e.key('30G'); e.key('3l')
        ex(e, ':r E.TXT\r')
        g = ctrlg(e)
        check(f'rdwr :r of an empty file: the next line, nothing modified ({g!r})',
              'line 31 ' in g and 'Modified' not in g and at(e) == txt(31))
        e.key('G')
        ex(e, ':r E.TXT\r')
        g = ctrlg(e)
        check(f'rdwr :r of an empty file on the last line: stays ({g!r})',
              'line 63 ' in g and 'Modified' not in g)
        # ---- a buffer with nothing in it ----
        check('rdwr: :q', at_ccp(e, ':q\r'))
        again(e, 'NEW1.TXT')
        ex(e, ':r OUT.TXT\r')
        g = ctrlg(e)
        check(f'rdwr :r into an empty buffer: below its one empty line ({g!r})',
              'line 2 ' in g and 'Modified' in g and at(e) == txt(8))
        ex(e, ':w\r')
        check('rdwr: :q', at_ccp(e, ':q\r'))
        again(e, 'NEW2.TXT')
        ex(e, ':0r OUT.TXT\r')
        g = ctrlg(e)
        check(f'rdwr :0r into an empty buffer: line 1 ({g!r})',
              'line 1 ' in g and at(e) == txt(8))
        ex(e, ':w\r')
        check('rdwr: NEW1.TXT is an empty line and then the file',
              disk(e, 'NEW1.TXT') == b'\r\n' + L(8, 9))
        check('rdwr: NEW2.TXT is the file', disk(e, 'NEW2.TXT') == L(8, 9))
    finally:
        e.close()

    # ---- the reason for both: a block the yank register cannot hold ----
    big = make(12800)
    e = Editor(big)
    try:
        ex(e, '9000G'); e.key('ma')
        ex(e, '6000G'); e.key('3l')
        v0 = e.screen()
        t0 = tstates(e)
        ex(e, ':3000,7999w BLK.TXT\r')
        s = (tstates(e) - t0) / 2e6
        v = e.screen()
        g = ctrlg(e)
        check(f'rdwr big :3000,7999w: 40 K written ({bottom(e)!r}, {s:.0f} s)',
              'line 6000 ' in g and 'Modified' not in g)
        check(f'rdwr big :3000,7999w: the cursor is back where it was '
              f'({(v.row, v.col)}, {at(e)!r})',
              (v.row, v.col) == (v0.row, v0.col) and at(e) == txt(6000))
        check(f'rdwr big :3000,7999w: in the time the paging takes '
              f'({s:.0f} s, 90 allowed)', s < 90)
        ex(e, '3000G'); ex(e, 'd7999G')
        g = ctrlg(e)
        check(f'rdwr big d7999G: the block is out ({at(e)!r}, {g!r})',
              at(e) == txt(8000) and 'line 3000 ' in g)
        ex(e, '1000G')
        t0 = tstates(e)
        ex(e, ':r BLK.TXT\r')
        s = (tstates(e) - t0) / 2e6
        g = ctrlg(e)
        check(f'rdwr big :r: on the first line read ({at(e)!r}, {g!r}, {s:.0f} s)',
              at(e) == txt(3000) and 'line 1001 ' in g and 'Modified' in g)
        check(f'rdwr big :r: in the time the paging takes ({s:.0f} s, 90 allowed)',
              s < 90)
        e.key('u')
        check(f'rdwr big :r: too much to undo, and u says so ({bottom(e)!r})',
              bottom(e) in ('Too large to undo',
                            'Cannot undo: change has paged out'))
        ex(e, '6000G')
        g = ctrlg(e)
        check(f'rdwr big 6000G: the last line read ({at(e)!r}, {g!r})',
              at(e) == txt(7999) and 'line 6000 ' in g)
        e.key("'a")
        e.s.run_until_quiet(quiet=1.5, timeout=300)
        g = ctrlg(e)
        check(f"rdwr big 'a: the mark followed its line ({at(e)!r}, {g!r})",
              at(e) == txt(9000) and 'line 9000 ' in g)
        ex(e, 'G')
        g = ctrlg(e)
        check(f'rdwr big G: as many lines as before ({g!r})', 'line 12800 ' in g)
        ex(e, ':w\r')
        got = saved_bytes(e)
        check(f'rdwr big: the block moved, nothing else did ({len(got)} bytes)',
              got == L(1, 1000) + L(3000, 7999) + L(1001, 2999) + L(8000, 12800))
        check('rdwr big: BLK.TXT is the block',
              disk(e, 'BLK.TXT') == L(3000, 7999))
        d = cpm_dir(e)
        check(f'rdwr big: no work files left {work_files(d)}', not work_files(d))
    finally:
        e.close()

    # ---- lines past the right screen edge (109 K) ----
    wide = make_wide()
    W = wide.split(b'\r\n')[:-1]
    e = Editor(wide)
    try:
        ex(e, '1400G')
        ex(e, ':700,1100w W.TXT\r')
        g = ctrlg(e)
        check(f'rdwr wide :700,1100w: back on line 1400 ({at(e)!r}, {g!r})',
              at(e) == W[1399].decode()[:80] and 'line 1400 ' in g)
        ex(e, ':r W.TXT\r')
        g = ctrlg(e)
        check(f'rdwr wide :r: on the first line read ({at(e)[:10]!r}, {g!r})',
              at(e) == W[699].decode()[:80] and 'line 1401 ' in g)
        ex(e, ':200r W.TXT\r')
        g = ctrlg(e)
        check(f'rdwr wide :200r: paged back to it ({at(e)[:10]!r}, {g!r})',
              at(e) == W[699].decode()[:80] and 'line 201 ' in g)
        ex(e, ':w\r')
        blk = W[699:1100]
        want = b''.join(x + b'\r\n' for x in
                        W[:200] + blk + W[200:1400] + blk + W[1400:])
        got = saved_bytes(e)
        check(f'rdwr wide: both copies are in, whole ({len(got)} bytes)',
              got == want)
    finally:
        e.close()


def qfull_cmds():
    """A 'dd' or 'yy' whose lines the yank register cannot hold is REFUSED:
    'Too large to yank' on the bottom row, the editor still running, the file,
    the cursor, the marks and the modified flag as they were, and the register
    left empty.  It used to raise WordMaster's fatal 'QBUF FULL' and drop to
    CP/M with the work lost.  A count that does fit still goes in and comes
    back out whole, a put of 22 K included.

    The register's ceiling is the arena less a reserve, so every byte the image
    grows comes off it: 2976 lines of this file fit at 18,304 bytes of VI.COM,
    where 3000 did 512 bytes earlier.  FIT is the count the "does fit" rows
    use: what the register holds on this build (register_lines), less a
    hundred lines -- and each of those rows says it was not refused, because a
    refused 'dd' then 'P', or a refused yank, leaves the file right as well."""
    FIT = None
    def L(a, b):
        return b''.join(line(i) for i in range(a, b + 1))

    big = make(12800)
    whole = L(1, 5999) + b'00600\r\n' + L(6001, 12800)
    for op in ('5000dd', '5000yy', '6801dd', '9999yy'):
        e = Editor(big)
        try:
            if FIT is None:
                FIT = min(2800, register_lines(e) - 100)
                TAIL = 12800 - FIT          # from here to the end: FIT + 1 lines
            e.key('6100G'); e.key('ma'); e.key('6000G'); e.key('3l')
            n = len(e.cap.getvalue())
            e.key(op)
            e.s.run_until_quiet(quiet=1.5, timeout=300)
            check(f'{op}: the editor is still running',
                  not PROMPT.search(e.cap.getvalue()[n:]))
            check(f'{op}: says why not ({bottom(e)!r})',
                  bottom(e) == 'Too large to yank')
            v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
            check(f'{op}: the cursor is where it was ({scr[v.row]!r}, {v.col})',
                  scr[v.row] == txt(6000) and v.col == 3)
            g = ctrlg(e)
            check(f'{op}: nothing is changed ({g!r})',
                  'Modified' not in g and 'line 6000 ' in g)
            e.key('p'); e.key('u')
            e.s.run_until_quiet(quiet=1.5, timeout=120)
            g = ctrlg(e)
            check(f'{op}: the register is empty and there is nothing to undo '
                  f'({g!r})', 'Modified' not in g and 'line 6000 ' in g)
            e.key("'a")
            e.s.run_until_quiet(quiet=1.5, timeout=120)
            v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
            check(f'{op}: a mark inside the lines is still on its line '
                  f'({scr[v.row]!r})', scr[v.row] == txt(6100))
            e.key('6000G'); e.key('3l'); e.key('x'); e.key(':w\r'); ex_settled(e)
            got = saved_bytes(e)
            check(f'{op}: the file is whole and the next command is its own '
                  f'({len(got)} bytes)', got == whole)
        finally:
            e.close()

    # ---- what does fit still goes in, and comes back out ----
    for keys, want in (
            (['6000G', f'{FIT}dd', 'P'], big),
            (['6000G', f'{FIT}dd', 'gg', 'P'],
             L(6000, 5999 + FIT) + L(1, 5999) + L(6000 + FIT, 12800))):
        e = Editor(big)
        try:
            n = len(e.cap.getvalue())
            said = []
            for k in keys:
                e.key(k)
                e.s.run_until_quiet(quiet=1.5, timeout=300)
                said.append(bottom(e))
            check(f'{" ".join(keys)}: it fits ({said!r})',
                  'Too large to yank' not in said)
            check(f'{" ".join(keys)}: the editor is still running',
                  not PROMPT.search(e.cap.getvalue()[n:]))
            e.key(':w\r'); ex_settled(e)
            got = saved_bytes(e)
            check(f'{" ".join(keys)}: byte-exact ({len(got)} bytes, '
                  f'{len(want)} wanted)', got == want)
        finally:
            e.close()

    # ---- a yank whose lines run past the window takes them out and puts
    #      them back: where they came from, and the cursor where it was ----
    for keys, want, at in (
            (['6000G', '3l', f'{FIT}yy'], big, 6000),
            (['6000G', '3l', f'{FIT}yy', 'p'],
             L(1, 6000) + L(6000, 5999 + FIT) + L(6001, 12800), None),
            ([f'{TAIL}G', '3l', f'{FIT + 1}yy'], big, TAIL),
            ([f'{TAIL}G', '3l', '9999yy', 'gg', 'P'], L(TAIL, 12800) + big, None)):
        e = Editor(big)
        try:
            said = []
            for k in keys:
                e.key(k)
                e.s.run_until_quiet(quiet=1.5, timeout=300)
                said.append(bottom(e))
            check(f'{" ".join(keys)}: it fits ({said!r})',
                  'Too large to yank' not in said)
            if at:
                v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen[:23]]
                check(f'{" ".join(keys)}: the cursor is where it was '
                      f'({scr[v.row]!r}, {v.col})',
                      scr[v.row] == txt(at) and v.col == 3)
                g = ctrlg(e)
                check(f'{" ".join(keys)}: nothing is changed ({g!r})',
                      'Modified' not in g and f'line {at} ' in g)
                e.key('x'); e.key('u')
            e.key(':w\r'); ex_settled(e)
            got = saved_bytes(e)
            check(f'{" ".join(keys)}: byte-exact ({len(got)} bytes, '
                  f'{len(want)} wanted)', got == want)
        finally:
            e.close()


def disk_full():
    """A fatal disk error leaves the editor the way a quit does: the terminal
    restored, the message on the bottom row rather than over the text at the
    cursor, and no name.$$$ on the disk.  The drive is filled through the guest
    (the CCP's SAVE, 64 K a file, until it says 'No space'), so a 100 K file
    cannot spill a single record: 'G' has to page and fails, and so does ':w'
    after a change.  The file itself must come through both untouched."""
    content = make(12800)
    e = Editor(content)
    try:
        e._ensure_ccp()
        n = 0
        while 'NO SPACE' not in e.s.cmd('SAVE 255 F%d.BIN' % n).upper():
            n += 1
            if n > 200:
                break
        check(f'full: the drive filled up ({n} files of 64 K)', 0 < n <= 200)
        e.s.cmd('ERA F%d.BIN' % n)               # the one that did not fit
        # ... which leaves up to 64 K free again: the rest goes a block (4 K)
        # at a time, so that not one record more will fit anywhere
        m = 0
        while 'NO SPACE' not in e.s.cmd('SAVE 16 G%d.BIN' % m).upper():
            m += 1
            if m > 20:
                break
        check(f'full: ... to the last block ({m} files of 4 K)', m <= 20)
        e.s.cmd('ERA G%d.BIN' % m)

        def fatal(tag, keys):
            e.cap.seek(0); e.cap.truncate(0)
            e.s.send('VI TEST.TXT\r')
            e.s.run_until_quiet(quiet=1, timeout=40)
            for k in keys[:-1]:
                e.key(k)
            top = [r.rstrip() for r in rows(e)]
            e.key(keys[-1], idle=6000)
            v = e.screen(); scr = [''.join(r).rstrip() for r in v.screen]
            check(f'full {tag}: DISK FULL on the row above the prompt '
                  f'({scr[22]!r} / {scr[23]!r})',
                  scr[22] == 'DISK FULL' and PROMPT.fullmatch(scr[23]) is not None)
            check(f'full {tag}: the cursor is after the prompt, bottom row '
                  f'{(v.row, v.col)}', (v.row, v.col) == (23, len(scr[23])))
            check(f'full {tag}: the text rows are as they were, one row up '
                  f'(the prompt\'s line feed), with nothing written over them',
                  scr[:22] == top[1:23])
            check(f'full {tag}: the scroll region is reset (ESC[r) before the '
                  f'message', '\x1b[r' in e.cap.getvalue()
                  and e.cap.getvalue().rindex('\x1b[r')
                  < e.cap.getvalue().rindex('DISK FULL'))
            d = cpm_dir(e)
            check(f'full {tag}: no work files left {work_files(d)}',
                  not work_files(d))
            check(f'full {tag}: TEST.TXT still listed', listed(d, 'TEST.TXT'))

        # a ranged write that the drive has no room for is refused, not fatal:
        # the text is all in the window, so nothing has to page for it
        e.cap.seek(0); e.cap.truncate(0)
        e.s.send('VI TEST.TXT\r')
        e.s.run_until_quiet(quiet=1, timeout=40)
        e.key('5G')
        refused(e, ':1,100w N.TXT\r', 'Disk full', 'full :1,100w')
        check('full :1,100w: :q leaves', at_ccp(e, ':q\r'))
        check('full :1,100w: the part written is not left behind',
              not listed(cpm_dir(e), 'N.TXT'))

        fatal('paging (G)', ['G'])
        fatal(':w', ['x', ':w\r'])
        check('full: TEST.TXT is byte for byte what it was',
              disk(e, 'TEST.TXT') == content)
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
        srch_cmds()
        paint_cost()
    if not args or 'vim' in args or 'ops' in args:
        print('\n=== o O J ~ dw cw D  ^L vs vim ===', flush=True)
        ops_like_vim()
        ops_cmds()
    if not args or 'vim' in args or 'opmx' in args:
        print('\n=== every operator over every motion vs vim ===', flush=True)
        opmx_like_vim()
        col1_like_vim()
        short_like_vim()
        word_like_vim()
    if not args or 'vim' in args or 'dot' in args:
        print('\n=== . (repeat) vs vim ===', flush=True)
        dot_like_vim()
        dot_cmds()
    if not args or 'vim' in args or 'undo' in args:
        print('\n=== u (undo) vs vim ===', flush=True)
        undo_like_vim()
        undo_at_vim()
        undo_cmds()
    if not args or 'vim' in args or 'subst' in args:
        print('\n=== :s / :%s / :N,Ms vs vim ===', flush=True)
        subst_like_vim()
        subst_cmds()
    if not args or 'vim' in args or 'marks' in args:
        print('\n=== m / ` / \' (marks) vs vim ===', flush=True)
        marks_like_vim()
        marks_cmds()
    if not args or 'vim' in args or 'pgop' in args:
        print('\n=== operators over a motion that pages ===', flush=True)
        pgop_cmds()
    if not args or 'vim' in args or 'after' in args:
        print('\n=== what a command leaves behind ===', flush=True)
        after_cmds()
    if not args or 'vim' in args or 'limits' in args:
        print('\n=== every limit: under, at and over ===', flush=True)
        limits_cmds()
    if not args or 'vim' in args or 'qfull' in args:
        print('\n=== dd / yy past the yank register ===', flush=True)
        qfull_cmds()
    if not args or 'vim' in args or 'rdwr' in args:
        print('\n=== :N,Mw {file} / :r {file} vs vim ===', flush=True)
        rdwr_like_vim()
        rdwr_cmds()
    if not args or 'vim' in args or 'lnum' in args:
        print('\n=== the line number, kept as the window pages ===', flush=True)
        lnum_cmds()
    if not args or 'vim' in args or 'brk' in args:
        print('\n=== ESC abandons a search or a long move ===', flush=True)
        brk_cmds()
    if not args or 'vim' in args or 'resp' in args:
        print('\n=== a key answers at once ===', flush=True)
        resp_cmds()
    if not args or 'vim' in args or 'step' in args:
        print('\n=== a step past the screen moves it a line ===', flush=True)
        step_scroll()
    if not args or 'vim' in args or 'cell' in args:
        print('\n=== a cell changed is a cell sent ===', flush=True)
        cell_paint()
    if not args or 'vim' in args or 'upnt' in args:
        print('=== u paints what it changed ===')
        undo_paint()
    if not args or 'vim' in args or 'wrap' in args:
        print('\n=== long lines wrap ===', flush=True)
        wrap_like_vim()
        wrap_cmds()
        wrap_paint()
    if not args or 'vim' in args or 'find' in args:
        print('\n=== f F t T ; , vs vim ===', flush=True)
        find_like_vim()
        find_cmds()
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
    if not args or 'vim' in args or 'full' in args:
        print('\n=== DISK FULL ===', flush=True)
        disk_full()

    print(f'\n{PASS[0]} passed, {FAIL[0]} failed', flush=True)
    if FAILED:
        print('FAILED:\n  ' + '\n  '.join(FAILED), flush=True)
    sys.exit(1 if FAIL[0] else 0)


if __name__ == '__main__':
    main()
