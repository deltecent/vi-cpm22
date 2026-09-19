#!/usr/bin/env python3
"""Smoke test for VI.COM on the altairsim simulator (MCP driver).

Boots VI on a test file, renders the VT100 screen, drives command-mode keys,
and checks the screen + a save round-trip -- all through the simulator over MCP.

Build first:  python3 build_vi.py VI
Then run:     python3 smoke_vi.py

Two driver capabilities make full-screen driving work (see mcpdrive.py):
  * enable_dsr() answers the editor's ESC[6n terminal-size probe
  * run_until_quiet() pumps `run` slices until the guest idles polling the
    keyboard (the screen has settled)
"""
import os
import sys
import hashlib
import io
import shutil
import atexit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcpdrive import AltairSim
from vt100 import VT100

MACHINE = "vi.toml"
TEMPLATE = os.path.join(HERE, "CPM22-8MB-56K-VI.DSK")

# SIMDIR is the simulator's working directory, which is also the hostbridge's
# root: `R` reads from it and `W` writes into it.  It is the repo by default,
# but a parallel runner gives each worker its own sandbox (holding vi.toml
# and VI.COM) so two guests cannot collide over the same host TEST.TXT.
SIMDIR = os.environ.get("VI_SIMDIR") or HERE

PASS = [0]; FAIL = [0]
def check(label, cond):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print(f'  FAIL {label}')

# Symbol table (NAME -> address) from VI.SYM so tests can read editor globals.
SYM = {}
_toks = open(os.path.join(HERE, "VI.SYM")).read().replace('\t', ' ').split()
for _i in range(0, len(_toks) - 1, 2):
    try:
        SYM[_toks[_i + 1]] = int(_toks[_i], 16)
    except ValueError:
        pass

WORK = os.environ.get("VI_WORK") or os.path.join(SIMDIR, "_smoke_work")
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)
_LIVE = []
_PREP = {}                      # sha1(content) -> a disk already carrying it


def _prepared(content):
    """A disk image that already has THIS build's VI.COM and the test file
    on it, made once per distinct file and then just copied.

    Measured on a 100 KB case: the CP/M boot is 0.07 s but `R VI.COM` is
    0.12 s and staging TEST.TXT is 0.55 s -- 81% of a case's setup is pushing
    bytes through the guest's serial bridge.  VI.COM is the worse offender
    of the two because it is pure waste: build_vi.py assembles and links on
    this very disk, IN PLACE, so the template already carries the binary and
    every case was re-sending a byte-identical copy of it (~550 times a run,
    about a minute).  It is still sent once here rather than trusted, so the
    binary under test is provably the one just built and never a stale image.
    """
    key = 'none' if content is None else hashlib.sha1(content).hexdigest()
    path = _PREP.get(key)
    if path is not None and os.path.exists(path):
        return path
    path = os.path.join(WORK, 'tpl%03d.DSK' % len(_PREP))
    shutil.copy(TEMPLATE, path)
    sim = AltairSim(MACHINE, cwd=SIMDIR, disk=os.path.relpath(path, SIMDIR),
                    logfile=io.StringIO(), timeout=30)
    try:
        sim.boot()
        sim.rfile("VI.COM")
        if content is not None:
            sim.put("TEST.TXT", content, convert=False)
            sim.rfile("TEST.TXT")
    finally:
        try:
            sim.quit()
        except Exception:
            pass
    _PREP[key] = path
    return path

@atexit.register
def _cleanup():
    for ed in list(_LIVE):
        ed.close()
    shutil.rmtree(WORK, ignore_errors=True)


class Editor:
    _n = 0

    def __init__(self, content, args='', fname='TEST.TXT', term=(24, 80), idle=3000):
        self.s = None
        n = Editor._n; Editor._n += 1
        self.disk = os.path.join(WORK, f"disk{n}.DSK")
        shutil.copy(_prepared(content), self.disk)
        self.cap = io.StringIO()
        self.quiet = min(5.0, max(0.3, idle / 6000.0))
        self.s = AltairSim(MACHINE, cwd=SIMDIR, disk=os.path.relpath(self.disk, SIMDIR),
                           logfile=self.cap, timeout=30)
        _LIVE.append(self)
        try:
            self.s.boot()
            # VI.COM and TEST.TXT are already on the copied disk: see
            # _prepared().  Staging them per case was 81% of this setup.
            if term is not None:
                self.s.enable_dsr(term[0], term[1])
            self.cap.seek(0); self.cap.truncate(0)          # capture = VI only
            cmd = 'VI' + (' ' + fname if fname else '') + args
            self.s.send(cmd + '\r')
            self.s.run_until_quiet(quiet=self.quiet, timeout=40)
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            _LIVE.remove(self)
        except ValueError:
            pass
        s, self.s = self.s, None
        if s is not None:
            try:
                s.quit()
            except Exception:
                pass
        p = getattr(self, "disk", None)
        if p:
            try:
                os.remove(p)
            except OSError:
                pass

    def __del__(self):
        self.close()

    def key(self, text, idle=2000):
        self.s.send(text)
        self.s.run_until_quiet(quiet=min(5.0, max(0.3, idle / 6000.0)), timeout=40)

    def screen(self, rows=24, cols=80):
        v = VT100(rows, cols)
        v.feed(self.cap.getvalue())
        return v

    def geom(self):
        return (self.s.mem(SYM['NROWS'])[0], self.s.mem(SYM['NCOLS'])[0])

    def _ensure_ccp(self):
        self.s.send("\r")
        try:
            self.s.expect(self.s.prompt, timeout=3)
            return
        except Exception:
            pass
        self.s.send("\x1b\x1b:q!\r")
        self.s.expect(self.s.prompt, timeout=20)

    def diskfile(self, name, ext):
        self._ensure_ccp()
        self.s.wfile(f"{name}.{ext}", "T")
        with open(os.path.join(SIMDIR, f"{name}.{ext}"), "rb") as f:
            return f.read()


def rows(ed, r=24, c=80):
    return ed.screen(r, c).render().split('\n')


def doc_checks():
    """VI.DOC: generated, well-formed, and still the one on the disk image.

    The last of those is the point.  build_doc.py can prove the repo's VI.DOC
    is the file it would write, but nothing on this side can prove the copy
    inside CPM22-8MB-56K-VI.DSK was refreshed with it -- that is a
    separate, easily-forgotten step (`build_doc.py --disk`).  So this boots
    CP/M and runs the command a user would run, TYPE VI.DOC, and compares
    what the terminal receives with the repo's file.  It catches a stale doc
    on the image, and it catches a doc that TYPEs badly: a wrapped line, a
    stray control byte, a missing ^Z running on into the next record.
    """
    import subprocess
    host = os.path.join(HERE, 'VI.DOC')
    if not os.path.exists(host):
        check('VI.DOC exists', False)
        return
    r = subprocess.run([sys.executable, os.path.join(HERE, 'build_doc.py'),
                        '--check'], capture_output=True, text=True, cwd=HERE)
    check(f'VI.DOC is what build_doc.py writes ({r.stderr.strip()[:60]})',
          r.returncode == 0)

    want = open(host, 'rb').read().split(b'\x1a')[0].decode('ascii')
    want = [l for l in want.replace('\r\n', '\n').strip('\n').split('\n')]

    disk = os.path.join(WORK, 'doc.DSK')
    shutil.copy(TEMPLATE, disk)
    cap = io.StringIO()
    sim = AltairSim(MACHINE, cwd=SIMDIR, disk=os.path.relpath(disk, SIMDIR),
                    logfile=cap, timeout=60)
    try:
        sim.boot()
        cap.seek(0); cap.truncate(0)
        sim.send('TYPE VI.DOC\r')
        sim.expect(sim.prompt, timeout=120)
        body = cap.getvalue()
        body = body.split('TYPE VI.DOC', 1)[-1].rsplit('A0>', 1)[0]
        got = [l.strip('\r') for l in body.replace('\r\n', '\n').split('\n')]
        while got and not got[0].strip():
            got.pop(0)
        while got and not got[-1].strip():
            got.pop()
    finally:
        try:
            sim.quit()
        except Exception:
            pass
        try:
            os.remove(disk)
        except OSError:
            pass

    check(f'TYPE VI.DOC emits every line ({len(got)} vs {len(want)})',
          len(got) == len(want))
    first = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), None)
    check('the disk image VI.DOC is the repo VI.DOC'
          + ('' if first is None else f' (line {first + 1}: {got[first]!r})'),
          first is None)
    # TYPE hands the terminal the bytes as they are: anything unprintable in
    # the output is unprintable in the file, whatever a host-side reader says.
    stray = sorted({c for c in body} - set(
        ''.join(chr(n) for n in range(32, 127)) + '\r\n'))
    check(f'TYPE VI.DOC sends no control characters ({stray!r})', not stray)
    wide = [l for l in got if len(l) > 78]
    check(f'no line wraps on an 80-column terminal ({len(wide)} too wide)',
          not wide)


def main():
    content = (b'first line\r\nsecond line\r\nthird line\r\n'
               b'fourth line\r\nfifth line\r\n')

    # --- 1. boots and paints the file, cursor home ---------------------------
    e = Editor(content)
    r = rows(e)
    check('row 1 = first line', r[0] == 'first line')
    check('row 2 = second line', r[1] == 'second line')
    check('row 5 = fifth line', r[4] == 'fifth line')
    v = e.screen()
    check('cursor home (1,1)', (v.row, v.col) == (0, 0))
    # rows past EOF show tildes on the edit area
    check('tilde past EOF (row 6)', r[5] == '~')
    e.close()

    # --- 2. geometry autodetect ---------------------------------------------
    e = Editor(content, term=(24, 80)); check('geom 24x80', e.geom() == (24, 80)); e.close()
    e = Editor(content, term=(30, 100)); check('geom 30x100', e.geom() == (30, 100)); e.close()
    e = Editor(content, term=(50, 132)); check('geom 50x132', e.geom() == (50, 132)); e.close()
    e = Editor(content, term=(250, 200)); check('geom clamps hi', e.geom() == (200, 132)); e.close()
    e = Editor(content, term=(10, 40)); check('geom clamps lo', e.geom() == (24, 80)); e.close()

    # --- 3. motions move the terminal cursor --------------------------------
    e = Editor(content)
    e.key('j')
    v = e.screen(); check('j -> row 2', (v.row, v.col) == (1, 0))
    e.key('$')
    v = e.screen(); check('$ -> end of "second line"', (v.row, v.col) == (1, len('second line') - 1))
    e.key('G')
    v = e.screen(); check('G -> last line', v.row == 4 and v.col == 0)
    e.key('gg')
    v = e.screen(); check('gg -> first line', (v.row, v.col) == (0, 0))
    e.close()

    # --- 4. x deletes a char, screen updates --------------------------------
    e = Editor(content)
    e.key('x')
    check('x deletes first char', rows(e)[0] == 'irst line')
    e.close()

    # --- 5. insert then ESC --------------------------------------------------
    e = Editor(content)
    e.key('i'); e.key('AB'); e.key('\x1b')
    check('insert AB at BOL', rows(e)[0] == 'ABfirst line')
    e.close()

    # --- 6. :wq round-trips the edit to disk --------------------------------
    e = Editor(content)
    e.key('x')            # delete 'f'
    e.key(':wq\r')
    saved = e.diskfile('TEST', 'TXT').rstrip(b'\x1a')
    check(':wq saved edited file',
          saved == b'irst line\r\nsecond line\r\nthird line\r\nfourth line\r\nfifth line\r\n')
    e.close()

    # --- 7. a file taller than the screen scrolls ---------------------------
    tall = b''.join(b'line%02d\r\n' % i for i in range(1, 31))   # 30 lines
    e = Editor(tall)
    r = rows(e)
    check('tall: top shows line01', r[0] == 'line01')
    e.key('G')
    r = rows(e); v = e.screen()
    check('tall G: bottom edit row shows line30', r[22] == 'line30')
    check('tall G: cursor on last edit row', v.row == 22)
    check('tall G: top scrolled past line01', r[0] != 'line01')
    e.close()

    # --- 8. scroll + screen-relative motions (NEDIT=23, 30 lines, maxtop=7) --
    e = Editor(tall)
    def topln():                        # top line off the screen (no TOPLN)
        return int(rows(e)[0][4:]) - 1
    check('scroll start TOPLN=0', topln() == 0)
    e.key('\x06')                       # ^F: forward NEDIT-2=21 (vim: may pass EOF)
    r = rows(e); v = e.screen()
    check('^F TOPLN=21', topln() == 21)
    check('^F top row = line22', r[0] == 'line22')
    check('^F cursor at top row', v.row == 0)
    e.key('\x02')                       # ^B: back to the top, cursor on bottom row (vim)
    r = rows(e); v = e.screen()
    check('^B TOPLN=0', topln() == 0)
    check('^B top row = line01', r[0] == 'line01')
    check('^B cursor bottom edit row', v.row == 22)
    e.key('gg')
    e.key('\x04')                       # ^D: down NEDIT/2=11; window pins at maxtop=7
    r = rows(e); v = e.screen()
    check('^D TOPLN=7', topln() == 7)
    check('^D cursor on line12', r[v.row] == 'line12')
    e.key('\x15')                       # ^U: back up 11 -> top
    r = rows(e); v = e.screen()
    check('^U TOPLN=0', topln() == 0)
    check('^U cursor on line01', r[v.row] == 'line01')
    e.key('L')                          # bottom visible line = line23 (index 22)
    r = rows(e); v = e.screen()
    check('L -> line23', r[v.row] == 'line23')
    e.key('M')                          # middle of [0..22] = index 11 = line12
    r = rows(e); v = e.screen()
    check('M -> line12', r[v.row] == 'line12')
    e.key('H')                          # top visible line = line01
    r = rows(e); v = e.screen()
    check('H -> line01', r[v.row] == 'line01')
    e.close()

    # --- 9. delete operator: d{motion}, dd, dj, dG, D, counts ---------------
    #     (an operator over a key that is not a motion, such as 'd%', is an
    #      accept_vi.py ops case)
    para = b'abc def ghi\r\njkl mno pqr\r\nxyz\r\n'

    def op(keys, at=''):
        e = Editor(para)
        if at:
            e.key(at)
        e.key(keys)
        r = rows(e)
        e.close()
        return r

    check('dw at BOL -> "def ghi"',      op('dw')[0] == 'def ghi')
    check('de at BOL -> " def ghi"',     op('de')[0] == ' def ghi')
    check('d$ at BOL -> empty line',     op('d$')[0] == '')
    check('d0 from col4 -> "def ghi"',   op('d0', at='llll')[0] == 'def ghi')
    check('dd -> line1 gone',            op('dd')[0] == 'jkl mno pqr')
    check('dj -> lines 1&2 gone',        op('dj')[0] == 'xyz')
    check('2dd -> two lines gone',       op('2dd')[0] == 'xyz')
    check('dG -> whole file gone',       op('dG')[0] in ('', '~'))
    check('D from col4 -> "abc"',        op('D', at='llll')[0] == 'abc')
    check('dw line 2 unaffected',        op('dw')[1] == 'jkl mno pqr')

    doc_checks()

    print(f'\n{PASS[0]} passed, {FAIL[0]} failed')
    sys.exit(1 if FAIL[0] else 0)


if __name__ == '__main__':
    main()
