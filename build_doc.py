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
comes from CMDTAB / EXTAB in CMD.MAC rather than from memory.  When
a command is added or removed, this file is part of the change.

The NUMBERS are not typed in at all.  Every time in the LARGE FILES section
is read out of TIMECOST.md, which timecost.py measures on the built editor,
and the memory figures are worked out from VI.SYM and BUF.MAC's equates (the
arena starts where the image ends, so they move whenever the image grows).
A figure this file cannot find is a refusal to write, like a line too wide;
and because a new build or a new measurement changes what this would write,
`--check` then says VI.DOC is stale until it is rebuilt.
"""
import os
import re
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
you move.  100K files are normal, but a jump from one end of one to the
other takes most of a minute: see LARGE FILES below.


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
    f{c} F{c}       forward / back to the character c, on this line
    t{c} T{c}       the same, but stopping just short of it
    ;  ,            that find again / the same find reversed

ESC stops a G, a gg or a search that is taking too long, and puts the
cursor back where it was: see LARGE FILES.

The arrow keys, Home, End, PgUp, PgDn, Ins and Del are NOT supported.
A terminal sends each of them as ESC followed by other characters, and
the editor takes those one at a time as if they had been typed: the
up-arrow is ESC [ A, so it ends up appending at the end of the line.
Press ESC, then u if the text was changed, and use h j k l ^B ^F.

f F t T and their repeats look on THIS LINE only, take counts (3fx), and
ring the bell without moving when the character is not there.


SCROLLING AND THE SCREEN ---------------------------------------------------

    ^F ^B           forward / back one screenful
    ^D ^U           down / up half a screenful
    ^L              redraw the screen
    ^G              show the file name, flags, line and column

The bottom row is a message line, blank until something is said on it.
It is not a permanent status line -- use ^G when you want to know where
you are.

A line wider than the screen wraps onto the rows under it, as in vi.  A
line the bottom of the screen has no room for is not shown in part: the
rows it would start on show @.  A line taller than the whole screen is
shown about the cursor, with <<< at the top left when its start is off
the screen.


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
    df,  dt)  d;                        ... and to a character on the line
    cw  C  ct)                          change
    yy  Y  5yy  y'a                     yank whole lines

cw changes to the END of the word, which is what vi's ce does -- vi's one
special case, and it is kept here.  dd, yy, D and C are the short spellings
of the common ones.  cc and S are not here, and cc does nothing at all.
The register holds whole lines, so y`a and yf, -- part of a line -- are
refused.  f and t take the character they land on; F and T stop short of
it, so df, deletes the comma and dF, leaves it.


YANK AND PUT ---------------------------------------------------------------

    yy   Y          yank this line   (5yy: five lines)
    p    P          put the yanked lines after / before this line
    3p              put three copies

There is one register and it holds whole lines.  A yank fills it and so
does dd; no other delete does.  It holds about @REGK@ K: a dd or yy of more
than that is refused with "Too large to yank" and changes nothing.  To
delete more, use dG, d{n}G or d'a, which keep nothing.  To MOVE more,
write the lines to a file and read them back in where they belong:

    :100,900w TMP.TXT       lines 100 to 900 to a file ('!' to overwrite)
    100G  d900G             delete them
    :r TMP.TXT              read the file in below this line
    :0r TMP.TXT             ... or above line 1,  :50r  below line 50


MARKS ----------------------------------------------------------------------

    m{a-c}          set mark a, b or c here
    `{a-c}          back to the exact spot
    '{a-c}          back to that line's first non-blank
    d'a  d`a  y'a   operate from here to the mark

Only three marks.  A mark follows its text when lines above it come and
go.  If the marked text itself is deleted, the mark moves to where the
delete was, and u puts it back.  A jump to a mark never set says "Mark
not set".  d'a works however far off the mark is; d`a and y'a over a
mark far off in a large file are refused.


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
    :5,9w FILE.TXT  write only lines 5 to 9 to a file
    :r FILE.TXT     read a file in below this line
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


@LARGE@


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


TIMES = os.path.join(HERE, "TIMECOST.md")


def measured():
    """TIMECOST.md as {row name: cells}, the backquotes taken off the name."""
    try:
        with open(TIMES) as f:
            text = f.read()
    except OSError as e:
        raise ValueError(f"TIMECOST.md cannot be read ({e}) -- "
                         "run `python3 timecost.py --write`")
    rows = {}
    for l in text.split("\n"):
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if l.startswith("|") and len(cells) >= 2:
            rows[cells[0].replace("`", "")] = cells[1:]
    return rows


def equate(name):
    """An `EQU` of BUF.MAC's, as a number."""
    with open(os.path.join(HERE, "BUF.MAC"), newline="") as f:
        m = re.search(r"^%s\s+EQU\s+([0-9A-F]+)H" % name, f.read(), re.M)
    if not m:
        raise ValueError(f"BUF.MAC has no `{name} EQU ...H`")
    return int(m.group(1), 16)


def symbol(name):
    toks = open(os.path.join(HERE, "VI.SYM")).read().split()
    for addr, sym in zip(toks[0::2], toks[1::2]):
        if sym == name:
            return int(addr, 16)
    raise ValueError(f"VI.SYM has no {name}")


def figures():
    """Every number the document quotes: (lookup of a time, dict of sizes)."""
    rows = measured()
    missing = []

    def cell(name, i=0):
        if name not in rows:
            missing.append(name)
            return "0"
        return rows[name][i]

    def t(name):
        """A measured time as the text reads it: '46 s', '4.0 s'."""
        s = float(cell(name))
        return "%d s" % round(s) if s >= 10 else "%.1f s" % s

    def k(n):
        return "%d K" % round(n / 1024)

    bdos = int(cell("BDOS entry, the word at 0006H").rstrip("H"), 16)
    arena = bdos - 1 - symbol("RSVTOP")
    held = [int(n) for n in re.findall(
        r"\d+", cell("text in memory after 6000G G 6000G gg G"))] or [0]
    sizes = {
        "arena": arena,
        "ARENAK": k(arena),
        # QFIT refuses unless MORE than RESVMEM is left: BUF.MAC
        "REGK": k(arena - equate("RESVMEM") - 1),
        "undo": equate("UNDCAP"),
        "WINK": k(max(held)),
        "OPENK": k(int(cell("text in memory when the file is opened")
                       .split()[0])),
        "OUTK": k(int(cell("TEST.$$$ after G from the top, nothing changed")
                      .split()[0])),
        "BAKK": k(int(cell("VIBACKUP.$$$ after G x gg").split()[0])),
        # the whole 100 K file, end to end
        "RATEK": k(102400 / (float(cell("G from the top")) or 1)),
    }
    # the messages the section names must be the ones the editor gave
    for name, said in (("3000dd (24 K)", "Too large to yank"),
                       ("u after 500dd", "Too large to undo"),
                       ("u after d6500G", "Too large to undo"),
                       ("u after dd G", "Cannot undo: change has paged out")):
        if cell(name, 2) != said:
            missing.append(f"{name} (which no longer says {said!r})")
    for name, said in (("G from the top, ESC 10 s into it", "Interrupted"),
                       ("/zzzz from line 6000, ESC 10 s into it",
                        "Interrupted"),
                       ("/zzzz from line 6000, never found",
                        "Pattern not found: zzzz")):
        if cell(name, 2) != said:
            missing.append(f"{name} (which no longer says {said!r})")
    for name in ("u after 100dd", "2000dd (16 K)", "2000yy (16 K)",
                 "yG (54 K)"):
        if cell(name, 2):
            missing.append(f"{name} (which now says {cell(name, 2)!r})")
    return t, sizes, missing


def large_files():
    """The LARGE FILES section, every figure in it measured or derived."""
    t, z, missing = figures()

    def two(a, ta, b=None, tb=None):
        l = "    %-26s%6s" % (a, t(ta))
        return l + ("       %-22s%6s" % (b, t(tb)) if b else "")

    def cut(what, size, name, note=""):
        return "    %-9s%5s%8s%s" % (what, size, t(name), note)

    text = f"""
LARGE FILES ----------------------------------------------------------------

A file bigger than memory is edited through a window: part of it is in
memory and the rest is paged to and from the disk as you move.  A command
that stays inside the window costs what it costs in a small file.  One
that has to page costs disk time, some big ones are refused, and some
cannot be undone.  This section says which, and what to use instead.

The times are for a 100 K file of 12800 short lines, on a 2 MHz 8080 and a
9600-baud terminal.  They leave out the drive's head seeks and the wait
for a sector to come round, so on a real drive every time over a second
or two is LONGER than shown.  Nothing is drawn while a long command runs.
The editor has not hung; the cursor comes back when it is done, and ESC
stops a move or a search before then (see below).

The limits:

    Memory      The text in memory, the yank register and the undo share
                {z['arena']} bytes (about {z['ARENAK']}, with a 56 K CP/M).  About {z['OPENK']} of
                the file is read when it is opened, and up to {z['WINK']} is in
                memory at once.
    Register    One, of whole lines, about {z['REGK']}.  What it holds is taken
                from the text's share, so after a big yank less of the
                file is in memory and every move pages sooner.
    Undo        One change, of up to {z['undo']} bytes.
    Lines       A long line wraps and is edited like any other.  The
                one limit is a line of about 13,000 characters or more,
                which is over half the memory.  A put into such a line
                can land in the middle of it, and going to the end of
                one of 26,000 or more ENDS THE EDITOR, and what was not
                written is lost.  Write the file first.
    CPU, disk   The file moves through the window 128 bytes at a time, at
                about {z['RATEK']} a second.  Text that has left the window is in
                two work files on the file's own drive, NAME.$$$ and
                VIBACKUP.$$$.
    Terminal    960 characters a second: a full repaint is a second and
                a half.

Quick, wherever you are in the file:

    ^F  ^B                    under a second
    200j                    {t('200j at line 6000'):>8}
    x                       {t('x'):>8}
    dd                      {t('dd'):>8}       u after it   {t('u after dd'):>8}
    60yy                    {t('60yy'):>8}
    ^G                      {t('^G at the end'):>8}
    6100G from line 6000    {t('6100G from line 6000'):>8}

A jump costs the distance moved, not the size of the line number.

Slow, because the file has to go through the window:

{two('G from line 1', 'G from the top', 'gg from the last line', 'gg from the end')}
{two('6000G from line 1', '6000G from the top', '100G from line 12000', '100G from line 12000')}
{two('/text, 94 K further on', '/012000 from the top', '?text, 46 K back', '?000100 from line 6000')}
{two('/text, wrapping round', '/000100 from line 6000 (wraps)', "'a, 46 K back", "'a to line 100 from line 6000")}
{two(':w', ':w, nothing changed')}   all of it, however little changed
{two(':e! at line 6000', ':e! after x at line 6000')}   {t(':e! after x at the top')} at line 1
{two(':%s/0/1/', ':%s/0/1/ (12800 lines)')}   every line; over 100 lines, {t(':6000,6100s/0/1/')}

ESC stops a move or a search -- G, gg, {{n}}G, 'a, `a, / ? n and N.  Within
a second or two the bottom row says "Interrupting...", and when the
cursor and the screen are back where the command began it says
"Interrupted".  Anything typed ahead is dropped.  That includes an
insert typed ahead of the move: the ESC that ends it stops the move, so
wait for the cursor before typing one.  Going back has to page too, so
it is not instant:

{two('G from line 1, ESC at 10 s', 'G from the top, ESC 10 s into it')}   in all
{two('/text, not in the file', '/zzzz from line 6000, never found')}
{two('  ... ESC at 10 s', '/zzzz from line 6000, ESC 10 s into it')}   in all

A command that changes the text is not stopped: dG, :s, a put and :w run
to the end, and the ESC is taken afterwards as a key that does nothing.

Going BACK costs more once something has been changed: gg from the last
line is {t('gg from the end, after x there')} after an x there, because the text passed over
is then written to VIBACKUP.$$$.

Big deletes and yanks, at line 6000:

{cut('500dd', '4 K', '500dd (4 K)')}          {cut('500yy', '4 K', '500yy (4 K)').strip()}
{cut('2000dd', '16 K', '2000dd (16 K)')}          {cut('2000yy', '16 K', '2000yy (16 K)').strip()}
{cut('d6500G', '4 K', 'd6500G (4 K)')}
{cut('d9000G', '24 K', 'd9000G (24 K)')}
{cut('dG', '54 K', 'dG (54 K)')}
{cut('dgg', '48 K', 'dgg (48 K)')}

What is refused:

  * A dd or yy of more than the register holds says "Too large to yank"
    and changes nothing -- but 3000dd (24 K) takes {t('3000dd (24 K)')} to say so,
    because the lines are taken and then put back.
  * A yank, or a delete of part of a line, between two places that are
    not both in memory rings the bell and does nothing.  yG at line 6000
    takes {t('yG (54 K)')} to find that out.
  * u after a change of more than {z['undo']} bytes says "Too large to undo".
    100dd of 8-byte lines can be undone; 500dd and d6500G (4 K each)
    cannot.
  * u after the window has moved off the change (dd, then G) says "Cannot
    undo: change has paged out".
  * A :w clears the undo.

What to do instead:

  * To DELETE a big range use dG, d{{n}}G or d'a.  They keep nothing, so
    no size is refused -- and nothing but :e! brings the lines back.
  * To MOVE or COPY a big block, write it to a file and read it back in
    (see YANK AND PUT).  :6000,9000w T.TXT is {t(':6000,9000w T.TXT (24 K)')} for 24 K and
    :r T.TXT is {t(':r T.TXT of 24 K, at line 3000')}.  That is any size, with the block still on the
    disk afterwards.  To move a block that fits the register, 2000dd
    and P are quicker ({t('2000dd (16 K)')} and {t('P after 2000dd')}); to copy one, 2000yy is not.
  * Type :w before a change that cannot be undone.  The file on the disk
    is not touched until the next :w, so :e! then throws the change away,
    and each :w leaves the version before it in NAME.BAK.
  * A :w is {t(':w, nothing changed')} even with nothing changed.  :x and ZZ write only
    a changed text, so use them to leave.
  * Work from the top of the file down, and go by line number when you
    know it: ^G says where you are, and a line close by costs a second.
  * Split a file you need only part of.  :1,6000w A.TXT and
    :6001,12800w B.TXT make two that each page half as far.

Disk space.  The work files need room on the file's own drive.  On the
100 K file NAME.$$$ reached {z['OUTK']} and VIBACKUP.$$$ {z['BAKK']}, besides the file
and its .BAK, so allow twice the file's size free before you start.  If the
drive fills while the editor is paging or writing, it stops with DISK
FULL and the changes since the last :w are lost; the file on the disk
is as that :w left it.
"""
    if missing:
        raise ValueError("TIMECOST.md does not hold what LARGE FILES quotes "
                         "-- run `python3 timecost.py --write`:\n  "
                         + "\n  ".join(missing))
    return text.strip("\n"), z


def render():
    """DOC as the bytes a CP/M text file holds, or ValueError saying why not.

    Every complaint is collected before raising, so one run names every bad
    line rather than making the author find them one at a time.
    """
    large, sizes = large_files()
    text = DOC.replace("@LARGE@", large).replace("@REGK@",
                                                 sizes["REGK"].split()[0])
    lines = [l.rstrip() for l in text.strip("\n").split("\n")]
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
