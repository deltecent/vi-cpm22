#!/usr/bin/env python3
"""Regenerate (and re-check) the vim 9.1 reference tables accept_vi.py holds.

The editor is not compared with a description of vi -- every "vs vim" table in
accept_vi.py was produced by replaying the same key sequence in real vim and
asking it, after each key, for

    line('.')   line('w0')   winline()-1   virtcol('.')-1

the cursor's line, the window's top line, and the cursor's screen row and
column (0-based) -- exactly the four numbers the accept tests read off VI's
screen.  vim runs on a 24x80 pty with 'nowrap' (this editor pans a long line,
it never wraps) and no user configuration:

    vim -n -u NONE -N -i NONE -c 'set lines=24 columns=80' -s keys.vim FILE

This script is that harness, kept with the tests so the numbers can be checked
or extended instead of being taken on trust.

    python3 vimref.py                  # re-check every group against vim
    python3 vimref.py hml goto         # only these groups
    python3 vimref.py --print hml      # print the table rows to paste in

The cases and the files they run on are accept_vi.py's own: this script reads
that file and runs its top-level definitions (it does NOT import it -- that
would run smoke_vi's module body, which clears the test disks out from under a
test run in progress), so a table and its reference input cannot drift apart.
Files are staged with LF, which vim reads as its 'unix' format where the editor
reads the CRLF that CP/M writes.  The reference file is written back with
':set ff=dos' first, so the bytes hashed are the ones vim itself put on disk
for CP/M's line endings -- this editor is meant to be vim with 'ff=dos', so the
comparison is against that and not against a reconstruction of it.  The switch
goes in immediately before the write, after every key of the row has run: it
marks the buffer modified, which has no business anywhere near the 'undo'
group's recording.

One difference is folded in on the way out: vim restores a missing line end at
the end of a file, where this editor writes the text back exactly as it read
it.  So for a file staged
without a final line end the hash is taken over vim's output less that one
line end -- what the editor is expected to write.

A table whose rows also carry text (the cursor and top lines, and a hash of the
file vim wrote, as the editing groups need) is replayed the same way, with
'getline' and a ':w' added to the recording -- VIM_INS is such a group.  VIM_BS
and VIM_NDD are not driven from here.
"""
import ast
import fcntl
import hashlib
import json
import os
import pty
import select
import shutil
import struct
import sys
import tempfile
import termios
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REC = (":call add(g:r, printf('%d %d %d %d', line('.'), line('w0'), "
       "winline()-1, virtcol('.')-1))\r")
# the ^G group records what vim's ^G reports: the line, and the byte and
# screen columns (1-based, as ^G prints them -- not 0-based like the rest)
RECG = (":call add(g:r, printf('%d %d %d', line('.'), col('.'), "
        "virtcol('.')))\r")
# a text group records the cursor and top lines with the four numbers
RECT = (":call add(g:r, printf('%d %d %d %d ', line('.'), line('w0'), "
        "winline()-1, virtcol('.')-1) . "
        "json_encode([getline('.'), getline(line('w0'))]))\r")

# group -> (the table in accept_vi.py, the file when a row does not name one)
GROUPS = {
    'scrolls': ('VIM_SCROLLS', None),
    'goto': ('VIM_GOTO', None),
    'goto_wide': ('VIM_GOTO_WIDE', 'wide'),
    'goto_ind': ('VIM_GOTO_INDENT', 'ind'),
    'jk': ('VIM_JK', None),
    'mot': ('VIM_MOT', None),
    'edit': ('VIM_EDIT', None),
    'hml': ('VIM_HML', None),
    'ins': ('VIM_INS', None),
    'ops': ('VIM_OPS', None),
    'dot': ('VIM_DOT', None),
    'undo': ('VIM_UNDO', None),
    'subst': ('VIM_SUBST', None),
    'plus': ('VIM_PLUS', None),
    'put': ('VIM_PUT', None),
    'srch': ('VIM_SRCH', None),
    'ctrlg': ('VIM_CTRLG', None),
    'marks': ('VIM_MARKS', None),
}
TEXT = {'ins', 'ops', 'put', 'srch', 'dot', 'undo', 'subst', 'marks'}  # rows carrying text + a file hash

# Rows the final-line-end fold must NOT be applied to.  The fold exists because
# this editor writes a file back as it read it, without the line end vim
# restores -- but where the keys OPEN A LINE at the end of the text the editor
# terminates that new line itself (CMD.MAC ENDBRK; an empty last line's
# terminator and a restored final line end are the same byte, so without it the
# line could not exist).  For these the editor writes exactly what vim wrote,
# so the hash is taken over vim's output whole.
NOFOLD = {('nl', ('G', 'oX\x1b')), ('mt', ('oX\x1b',))}


def accept():
    """accept_vi.py's top-level names (tables and file builders), run without
    importing it: its own imports run, the smoke_vi one is stubbed out."""
    with open(os.path.join(HERE, 'accept_vi.py')) as f:
        tree = ast.parse(f.read())
    body = [n for n in tree.body
            if not (isinstance(n, ast.ImportFrom) and n.module == 'smoke_vi')
            and not isinstance(n, ast.If)]          # not the __main__ tail
    ns = dict.fromkeys(['Editor', 'SYM', 'rows', 'HERE', 'TEMPLATE', 'WORK'])
    exec(compile(ast.Module(body=body, type_ignores=[]), 'accept_vi.py', 'exec'), ns)
    return ns


A = accept()
_HML = None


def lf(data):
    """A staged CP/M file as vim reads it."""
    return data.replace(b'\r\n', b'\n')


def joined(lines, final=True):
    return ('\n'.join(lines) + ('\n' if final else '')).encode()


def content(name):
    """The file a case names, built the way accept_vi.py stages it."""
    global _HML
    if _HML is None:
        _HML = dict(A['hml_files']())               # num wide ind wd 3 2 1 nl
        _HML.update(A['ins_files']())               # + bl mt
        _HML.update(A['ops_files']())               # + jp
        _HML.update(A['plus_files']())              # + an empty one ('0')
        _HML.update(A['subst_files']())             # + rep
        _HML.update(A['marks_files']())             # + mk
    if name in _HML:
        return lf(_HML[name])
    if name == 'indent':
        return lf(A['make_indent']())
    if name == 'tabs':
        return joined(A['TABJK_LINES'])
    if name in A['MOT_FILES']:                      # wd ws one
        return joined(A['MOT_FILES'][name], final=name != 'ws')
    return lf(A['make'](int(name)))                 # a row naming a line count


# Scripted input never lets vim sync its undo blocks, so every change in a
# whole run lands in ONE block and a single 'u' takes the lot back -- nothing
# like what the same keys do at a keyboard.  This is vim's own documented way
# to force a sync point, and it goes after every key of the 'undo' group so
# each command becomes its own block, as an interactive vim would have it.
USYNC = ":let &undolevels = &undolevels\r"


def run(path, keys, timeout=30, rec=REC, wrote=None, arg=None, start=False,
        sync=''):
    """Replay *keys* in vim on *path*; return its numbers after each key.  With
    *wrote*, vim also writes the buffer there (the file a text group hashes).
    *arg* is one more vim argument, placed last so it runs with the window
    already 24x80 ('+{n}' is such an argument); *start* records the numbers
    once before any key, which is where a '+{n}' left the cursor."""
    d = os.path.dirname(path)
    script, out = os.path.join(d, 'keys.vim'), os.path.join(d, 'out.txt')
    save = f":set ff=dos\r:w! {wrote}\r" if wrote else ''
    with open(script, 'w') as f:
        f.write((rec if start else '') + ''.join(k + rec + sync for k in keys) + save
                + f":call writefile(g:r, '{out}')\r:qa!\r")
    if os.path.exists(out):
        os.remove(out)
    pid, fd = pty.fork()
    if pid == 0:                                    # the child is vim itself
        os.environ['TERM'] = 'vt100'
        os.execvp('vim', ['vim', '-n', '-u', 'NONE', '-N', '-i', 'NONE',
                          '--cmd', 'set nowrap',
                          '-c', 'let g:r=[]', '-c', 'set lines=24 columns=80']
                         + ([arg] if arg else []) + ['-s', script, path])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                if not os.read(fd, 65536):
                    break
            except OSError:
                break
    else:
        os.kill(pid, 9)
    os.waitpid(pid, 0)
    if not os.path.exists(out):
        raise RuntimeError(f'vim did not finish: {path} {keys!r}')
    with open(out) as f:
        return f.read().split('\n')


def replay(group, work):
    """Every row of *group* through vim: (file, keys, committed, vim)."""
    name, deflt = GROUPS[group]
    text = group in TEXT
    for row in A[name]:
        if group == 'plus':
            # keys[0] is vim's own command-line argument, not a key: the first
            # recording is where opening the file with it left the cursor.
            f, keys, want = row
            path = os.path.join(work, 'ref_%s.txt' % f)
            with open(path, 'wb') as fh:
                fh.write(content(str(f)))
            got = run(path, list(keys[1:]), arg=keys[0], start=True)
            yield f, keys, want, [g for g in got if g]
            continue
        if text:
            f, keys, csha, want = row
        else:
            f, keys, want = (deflt,) + row if len(row) == 2 else row
        path = os.path.join(work, 'ref_%s.txt' % f)
        with open(path, 'wb') as fh:
            fh.write(content(str(f)))
        if group == 'ctrlg':
            yield f, keys, want, run(path, [':set nowrap\r'] + list(keys),
                                     rec=RECG)[1:]
            continue
        if not text:
            yield f, keys, want, run(path, [':set nowrap\r'] + list(keys))[1:]
            continue
        wrote = os.path.join(work, 'wrote.txt')
        got = run(path, [':set nowrap\r'] + list(keys), rec=RECT, wrote=wrote,
                  sync=USYNC if group in ('undo', 'subst') else '')[1:]
        with open(wrote, 'rb') as fh:
            out = fh.read()         # already CRLF: the write set 'ff=dos'
        if (not content(str(f)).endswith(b'\n') and out.endswith(b'\r\n')
                and (str(f), tuple(keys)) not in NOFOLD):
            out = out[:-2]      # see the final-line-end note at the top
        sha = hashlib.sha1(out).hexdigest()[:16]
        rows = []
        for g in [x for x in got if x]:
            nums, js = g.split(' ', 4)[:4], g.split(' ', 4)[4]
            cur, top = json.loads(js)
            rows.append((int(nums[2]), int(nums[3]), cur, top))
        yield f, keys, (csha, want), (sha, rows)


def main():
    show = '--print' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--print']
    groups = [g for g in GROUPS if not args or g in args]
    if not groups:
        sys.exit('groups: ' + ' '.join(GROUPS))
    work = tempfile.mkdtemp(prefix='vimref.')
    bad = 0
    try:
        for g in groups:
            print(f'=== {g} ===', flush=True)
            for f, keys, want, got in replay(g, work):
                if g in TEXT:
                    sha, rows = got
                    if show:
                        print(f'    ({f!r}, {keys!r}, {sha!r},\n     [' +
                              ',\n      '.join(repr(r) for r in rows) + ']),', flush=True)
                        continue
                    if (sha, rows) != want:
                        bad += 1
                        print(f'  DIFF {f} {keys!r}: committed {want!r} vim {got!r}',
                              flush=True)
                    continue
                if show:
                    print(f'    ({f!r}, {keys!r},\n     {got!r}),', flush=True)
                    continue
                for k, w, v in zip(keys, want, got):
                    v = ' '.join(v.split()[:len(w.split())])    # some hold fewer
                    if v != w:
                        bad += 1
                        print(f'  DIFF {f} {keys!r} {k!r}: committed {w!r} vim {v!r}',
                              flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not show:
        print('MATCH: vim agrees with every committed row' if not bad else f'{bad} DIFF')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
