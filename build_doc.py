#!/usr/bin/env python3
"""Build VI.DOC -- the editor's own terse manual -- for CP/M's TYPE.

    python3 build_doc.py              write VI.DOC here
    python3 build_doc.py --check      is VI.DOC the file this would write?
    python3 build_doc.py --disk       write it, then put it on the disk image

VI.DOC is GENERATED.  Edit DOC below, never VI.DOC: a hand edit is silently
overwritten by the next build and, worse, is not checked by anything.  What
is checked here is everything CP/M's TYPE cares about, because TYPE has no
pager, no wrap column of its own and no way to say a file is malformed -- it
just prints bytes at the terminal until it meets a ^Z:

  * no line past MAXCOL, so nothing wraps on an 80-column terminal (the
    margin is deliberate: a terminal that wraps AT 80 would fold a full line
    and throw every following row of a table out by one)
  * printable 7-bit ASCII only, so no high-bit character reaches a terminal
    that would read it as a control code
  * no TAB, so nothing depends on TYPE expanding tabs the way a terminal
    happens to
  * CRLF line ends, a ^Z terminator, and ^Z padding to a whole 128-byte
    record -- how a CP/M text file ends

A generator that only WRITES the file would still let it rot, so the checks
run on the way out and refuse to write rather than warn.  `--check` runs the
same comparison against the committed VI.DOC, and smoke_vi.py goes further:
it boots CP/M and runs TYPE VI.DOC on the DISK IMAGE, which is the one thing
neither this script nor a reader can verify by looking -- that the VI.DOC
shipping inside CPM22-8MB-56K-VI.DSK is still the VI.DOC in the repo.

The text itself is checked by hand against COMMANDS.md, and its command list
comes from CMDTAB / ACTTAB / EXTAB in CMD.MAC rather than from memory.  When
a command is added or removed, this file is part of the change.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "VI.DOC")
DISK = "CPM22-8MB-56K-VI.DSK"
MACHINE = "vi.toml"
MAXCOL = 78                     # 80 less a margin; see the module docstring
RECORD = 128
EOF_ = 0x1A

DOC = r"""

VI -- a vi-style screen editor for CP/M 2.2            Altair 8800 / VT100

    VI                      start with an empty buffer
    VI FILE.TXT             edit FILE.TXT (created on :w if it is new)
    VI FILE.TXT +500        start on line 500   ('+' alone: the last line)
    VI FILE.TXT -R          read only; a write needs '!'

The switches come AFTER the file name -- the CCP parses the first word of
the line into the FCB, so VI never sees it.  The screen size is detected
from the terminal; a VT100 (or anything that answers ESC [ 6 n) is assumed.

The file may be far larger than memory: text is paged to and from disk as
you move.  100K files are normal.  A big jump takes a few seconds.


MODES ----------------------------------------------------------------------

Command mode is where you start.  i a A I o O R C and c{motion} enter
insert mode; ESC leaves it.  Everything below is command mode unless it
says otherwise.  Most commands take a count typed first: 5j, 3dd, 20G.


MOVING ---------------------------------------------------------------------

    h l             left / right one character
    j k             down / up one line
    0               start of line
    ^               first non-blank of line
    $               end of line
    <CR>            down a line, to its first non-blank
    w b             forward / back one word
    W B             the same, but a word is anything between blanks
    e               forward to the end of a word
    G               last line, or line N with a count:  20G
    gg              first line, or line N:  20gg
    H M L           top / middle / bottom line of the screen

The arrow keys work as h j k l, and PgUp / PgDn as ^B / ^F.


SCROLLING AND THE SCREEN ---------------------------------------------------

    ^F ^B           forward / back one screenful
    ^D ^U           down / up half a screenful
    ^L              redraw the screen
    ^G              show the file name, flags, line and column

The bottom row is a message line, blank until something is said on it.
It is not a permanent status line -- use ^G when you want to know where
you are.


EDITING --------------------------------------------------------------------

    i a             insert before / after the cursor
    I A             insert at the first non-blank / at the end of the line
    o O             open a line below / above, and insert on it
    ESC             leave insert mode
    x               delete the character under the cursor  (3x: three)
    r{c}            replace the character under the cursor with c
    R               replace mode: type over, ESC to stop
    ~               change the case of a character, and step right
    J               join the next line onto this one
    dd              delete the whole line  (5dd: five lines)
    D               delete to the end of the line
    C               change to the end of the line
    u               undo
    .               repeat the last change

In insert mode, BS and DEL rub out, and will back over the start of the
insert and join to the line above, as vim does.


OPERATORS ------------------------------------------------------------------

d deletes, c changes and y yanks over the motion that follows:

    dw  dd  d$  dj  dG  d'a  d`a        delete to there
    cw  C                               change
    yy  Y  5yy  y'a                     yank whole lines

cw changes to the END of the word, which is what vi's ce does -- vi's one
special case, and it is kept here.  dd, yy, D and C are the short spellings
of the common ones.  cc and S are not here, and cc does nothing at all.
The register holds whole lines, so y`a -- part of a line -- is refused.


YANK AND PUT ---------------------------------------------------------------

    yy   Y          yank this line   (5yy: five lines)
    p    P          put the yanked lines after / before this line
    3p              put three copies

There is one register and it holds whole lines.  A delete does not fill
it -- only a yank does.


MARKS ----------------------------------------------------------------------

    m{a-c}          set mark a, b or c here
    `{a-c}          back to the exact spot
    '{a-c}          back to that line's first non-blank
    d'a  d`a  y'a   operate from here to the mark

Only three marks.  A mark is DROPPED, not moved, when the text above it
changes or the window pages away from it; a lost mark rings the bell.


SEARCH ---------------------------------------------------------------------

    /text<CR>       search forward
    ?text<CR>       search backward
    n  N            repeat the search, same / opposite direction

The pattern is a LITERAL string, not a regular expression: . * [ ] and ^
match themselves.  The search wraps round the end of the file.  An empty
pattern repeats the last one.  Case matters.


SUBSTITUTE -----------------------------------------------------------------

    :s/old/new/             the first match on this line
    :s/old/new/g            every match on this line
    :%s/old/new/g           every line in the file
    :2,40s/old/new/g        lines 2 through 40

old is literal here too, and new is the characters typed -- there is no &
and no \1.  A blank may follow the range (:2,40 s/old/new/), but not
inside it (:2, 40s is refused).  The whole substitute is one undo.
The ':' line holds 40 characters, which is the real limit on the size of
a substitute.


FILES AND QUITTING ---------------------------------------------------------

    :w              write
    :w FILE.TXT     write to another file  ('!' to overwrite it)
    :q              quit   (refused if the text was changed)
    :q!             quit, and throw the changes away
    :wq             write, then quit
    :x   ZZ         write only if changed, then quit
    :e              re-read the file  ('!' if the text was changed)
    :e FILE.TXT     edit another file
    :ve             show the version

A write leaves the previous contents in FILE.BAK.  A file read without a
line end after its last line is written back without one.


UNDO -----------------------------------------------------------------------

u undoes the last change, and u again puts it back -- there is one level,
as in real vi, not a whole history.  A very large change may not fit; u
then says so rather than doing half of it.  A :w clears the undo.


NOT IN THIS VI -------------------------------------------------------------

    f F t T ; ,     character search on a line
    %               matching bracket
    << >>           shift a line
    s S cc          substitute / change the whole line
    ^E ^Y           scroll one line
    :100            go to a line  (use 100G)
    named registers, multi-level undo, regular expressions,
    autoindent, :set, .exrc, multiple windows or buffers

A count before an insert (3ix) is ignored: it inserts once.  So is a count
on r and ~.
"""


def render():
    """DOC as the bytes a CP/M text file holds, or ValueError saying why not.

    Every complaint is collected before raising, so one run names every bad
    line rather than making the author find them one at a time.
    """
    lines = [l.rstrip() for l in DOC.strip("\n").split("\n")]
    bad = []
    for n, l in enumerate(lines, 1):
        if len(l) > MAXCOL:
            bad.append(f"line {n}: {len(l)} columns (max {MAXCOL}): {l!r}")
        if "\t" in l:
            bad.append(f"line {n}: has a TAB")
        for c in l:
            if not 32 <= ord(c) <= 126:
                bad.append(f"line {n}: {c!r} is not printable ASCII")
                break
    if bad:
        raise ValueError("VI.DOC would not be safe to TYPE:\n  "
                         + "\n  ".join(bad))
    data = "".join(l + "\r\n" for l in lines).encode("ascii")
    data += bytes([EOF_])
    if len(data) % RECORD:                      # pad the last record, as CP/M
        data += bytes([EOF_]) * (RECORD - len(data) % RECORD)
    return lines, data


def put_on_disk(path):
    """Copy VI.DOC onto the CP/M disk image, THROUGH THE GUEST.

    Never by parsing the .DSK on this side: the guest's own BDOS is the only
    thing that knows how this image is laid out, and a host-side writer that
    is subtly wrong is worse than no writer at all.
    """
    sys.path.insert(0, HERE)
    import io
    from mcpdrive import AltairSim
    sim = AltairSim(MACHINE, cwd=HERE, disk=DISK, logfile=io.StringIO(),
                    timeout=60)
    try:
        sim.boot()
        sim.rfile(os.path.basename(path))
    finally:
        try:
            sim.quit()
        except Exception:
            pass


def main(argv):
    check = "--check" in argv
    disk = "--disk" in argv
    try:
        lines, data = render()
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    if check:
        try:
            with open(OUT, "rb") as f:
                have = f.read()
        except OSError as e:
            print(f"VI.DOC cannot be read: {e}", file=sys.stderr)
            return 1
        if have != data:
            print("VI.DOC is NOT what build_doc.py would write "
                  f"({len(have)} bytes on disk, {len(data)} generated) -- "
                  "run `python3 build_doc.py`", file=sys.stderr)
            return 1
        print(f"VI.DOC is up to date ({len(lines)} lines, {len(data)} bytes)")
        return 0
    with open(OUT, "wb") as f:
        f.write(data)
    print(f"VI.DOC written: {len(lines)} lines, {len(data)} bytes, "
          f"{len(data) // RECORD} records, widest {max(len(l) for l in lines)}")
    if disk:
        put_on_disk(OUT)
        print(f"VI.DOC put on {DISK}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
