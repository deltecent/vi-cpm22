# What the acceptance tests reach

Written by `python3 covmap.py --write`; do not edit. Measured on a `VI.COM` of 20224 bytes by running `accept_vi.py` unchanged with a recorder in the simulator driver (`covmap.py` says how).

The suite started **1538 editors** and made **8991 checks** in **72634 emulated seconds**. `VI.COM` has **1913 basic blocks** of code (18588 bytes); the suite ran **1860** of them (97.2 %, 18345 bytes).

A block that ran is not a block that is tested: every bug in issue #3 was in code the suite ran on every pass, reached in a state no test put it in. So this table can show a test is NOT looking somewhere, and that two tests walk the same code; it cannot show that either of them is enough. The operator table below is the other half -- states, not code.

## Groups

"only here" is code no other group runs: what would go unrun if the group were dropped.

| group | editors | checks | emulated s | of the suite | blocks run | only here | bytes only here |
|---|---|---|---|---|---|---|---|
| `file` | 25 | 346 | 6786 | 9.3 % | 1123 | 14 | 112 |
| `pgop` | 65 | 182 | 5059 | 7.0 % | 1209 | 8 | 86 |
| `opmx` | 245 | 1227 | 5003 | 6.9 % | 1172 | 3 | 23 |
| `undo` | 193 | 801 | 4872 | 6.7 % | 1281 | 1 | 7 |
| `ops` | 95 | 285 | 4760 | 6.6 % | 1095 | 0 | 0 |
| `subst` | 43 | 125 | 4597 | 6.3 % | 911 | 2 | 12 |
| `100k` | 18 | 101 | 3531 | 4.9 % | 1005 | 0 | 0 |
| `ins` | 44 | 156 | 3080 | 4.2 % | 901 | 9 | 106 |
| `marks` | 148 | 506 | 3071 | 4.2 % | 1286 | 0 | 0 |
| `wrap` | 49 | 1447 | 2968 | 4.1 % | 1331 | 7 | 76 |
| `srch` | 58 | 209 | 2917 | 4.0 % | 939 | 0 | 0 |
| `after` | 21 | 792 | 2328 | 3.2 % | 1529 | 1 | 6 |
| `40k` | 18 | 101 | 2286 | 3.1 % | 1010 | 0 | 0 |
| `dot` | 37 | 145 | 1729 | 2.4 % | 1121 | 0 | 0 |
| `mot` | 37 | 514 | 1727 | 2.4 % | 832 | 1 | 2 |
| `full` | 4 | 20 | 1590 | 2.2 % | 724 | 6 | 50 |
| `scrolls` | 63 | 203 | 1586 | 2.2 % | 817 | 1 | 4 |
| `ndd` | 19 | 85 | 1433 | 2.0 % | 825 | 0 | 0 |
| `qfull` | 10 | 46 | 1389 | 1.9 % | 898 | 1 | 3 |
| `put` | 40 | 145 | 1382 | 1.9 % | 878 | 1 | 8 |
| `bs` | 12 | 69 | 1338 | 1.8 % | 878 | 0 | 0 |
| `rdwr` | 18 | 128 | 1203 | 1.7 % | 1027 | 7 | 59 |
| `2k` | 16 | 97 | 1186 | 1.6 % | 988 | 0 | 0 |
| `limits` | 36 | 80 | 1186 | 1.6 % | 1093 | 4 | 13 |
| `goto` | 29 | 92 | 905 | 1.2 % | 748 | 0 | 0 |
| `find` | 46 | 173 | 881 | 1.2 % | 836 | 0 | 0 |
| `hml` | 30 | 329 | 862 | 1.2 % | 813 | 0 | 0 |
| `arg` | 41 | 112 | 850 | 1.2 % | 876 | 7 | 41 |
| `lnum` | 2 | 37 | 511 | 0.7 % | 944 | 0 | 0 |
| `brk` | 7 | 79 | 449 | 0.6 % | 973 | 4 | 31 |
| `jk` | 27 | 128 | 374 | 0.5 % | 790 | 0 | 0 |
| `one` | 16 | 87 | 308 | 0.4 % | 863 | 0 | 0 |
| `ctrlg` | 12 | 57 | 222 | 0.3 % | 903 | 1 | 10 |
| `empty` | 10 | 35 | 168 | 0.2 % | 790 | 0 | 0 |
| `ex` | 4 | 52 | 96 | 0.1 % | 725 | 3 | 30 |

## Test functions

The same, per function `main()` calls. "needed" is how many of its editors a minimal set keeps -- see the next section.

| function | editors | checks | emulated s | blocks run | only here | needed | their emulated s |
|---|---|---|---|---|---|---|---|
| `file: file_cmds` | 16 | 164 | 5459 | 945 | 13 | 6 | 497 |
| `pgop: pgop_cmds` | 65 | 182 | 5059 | 1209 | 8 | 6 | 469 |
| `subst: subst_like_vim` | 37 | 84 | 4284 | 850 | 0 | 0 | 0 |
| `ops: ops_like_vim` | 69 | 229 | 3314 | 1002 | 0 | 1 | 19 |
| `undo: undo_at_vim` | 142 | 627 | 2812 | 1095 | 0 | 2 | 29 |
| `opmx: opmx_like_vim` | 127 | 991 | 2783 | 1163 | 2 | 4 | 84 |
| `wrap: wrap_like_vim` | 41 | 1113 | 2379 | 993 | 4 | 5 | 203 |
| `after: after_cmds` | 21 | 792 | 2328 | 1529 | 1 | 4 | 212 |
| `srch: srch_like_vim` | 49 | 168 | 2239 | 776 | 0 | 1 | 18 |
| `marks: marks_cmds` | 95 | 216 | 2061 | 1255 | 0 | 11 | 78 |
| `opmx: word_like_vim` | 92 | 184 | 1734 | 968 | 1 | 1 | 19 |
| `mot: mot_like_vim` | 37 | 514 | 1727 | 832 | 1 | 5 | 36 |
| `ins: ins_cmds` | 13 | 19 | 1615 | 875 | 2 | 4 | 38 |
| `undo: undo_like_vim` | 37 | 158 | 1611 | 1108 | 0 | 1 | 19 |
| `dot: dot_like_vim` | 31 | 139 | 1595 | 1113 | 0 | 1 | 63 |
| `full: disk_full` | 4 | 20 | 1590 | 724 | 6 | 2 | 37 |
| `scrolls: scrolls_like_vim` | 63 | 203 | 1586 | 817 | 1 | 6 | 95 |
| `100k: write_continue 100k` | 3 | 15 | 1501 | 842 | 0 | 0 | 0 |
| `ins: ins_like_vim` | 31 | 137 | 1465 | 864 | 1 | 3 | 106 |
| `ops: ops_cmds` | 26 | 56 | 1446 | 1023 | 0 | 5 | 34 |
| `ndd: ndd_like_vim` | 19 | 85 | 1433 | 825 | 0 | 0 | 0 |
| `qfull: qfull_cmds` | 10 | 46 | 1389 | 898 | 1 | 2 | 234 |
| `put: put_like_vim` | 40 | 145 | 1382 | 878 | 1 | 3 | 43 |
| `bs: bs_like_vim` | 12 | 69 | 1338 | 878 | 0 | 1 | 19 |
| `file: edit_like_vim` | 6 | 168 | 1295 | 946 | 0 | 0 | 0 |
| `40k: write_continue 40k` | 3 | 15 | 1269 | 848 | 0 | 0 | 0 |
| `limits: limits_cmds` | 36 | 80 | 1186 | 1093 | 4 | 6 | 104 |
| `marks: marks_like_vim` | 53 | 290 | 1010 | 968 | 0 | 0 | 0 |
| `100k: nav_and_save 100k` | 1 | 15 | 987 | 804 | 0 | 0 | 0 |
| `2k: write_continue 2k` | 3 | 15 | 913 | 840 | 0 | 0 | 0 |
| `goto: goto_like_vim` | 29 | 92 | 905 | 748 | 0 | 0 | 0 |
| `find: find_like_vim` | 45 | 169 | 874 | 829 | 0 | 2 | 39 |
| `hml: hml_like_vim` | 30 | 329 | 862 | 813 | 0 | 1 | 6 |
| `rdwr: rdwr_cmds` | 6 | 77 | 677 | 987 | 3 | 2 | 48 |
| `srch: srch_cmds` | 1 | 16 | 592 | 602 | 0 | 0 | 0 |
| `arg: plus_like_vim` | 31 | 76 | 540 | 689 | 5 | 2 | 12 |
| `rdwr: rdwr_like_vim` | 12 | 51 | 526 | 916 | 0 | 1 | 24 |
| `lnum: lnum_cmds` | 2 | 37 | 511 | 944 | 0 | 0 | 0 |
| `undo: undo_cmds` | 14 | 16 | 450 | 886 | 1 | 1 | 115 |
| `wrap: wrap_paint` | 5 | 264 | 450 | 978 | 0 | 0 | 0 |
| `brk: brk_cmds` | 7 | 79 | 449 | 973 | 4 | 1 | 253 |
| `40k: nav_and_save 40k` | 1 | 15 | 400 | 809 | 0 | 0 | 0 |
| `jk: jk_like_vim` | 27 | 128 | 374 | 790 | 0 | 4 | 42 |
| `opmx: short_like_vim` | 17 | 34 | 316 | 908 | 0 | 0 | 0 |
| `subst: subst_cmds` | 6 | 41 | 313 | 806 | 2 | 3 | 23 |
| `arg: arg_cmds` | 10 | 36 | 309 | 766 | 2 | 1 | 7 |
| `100k: ndd 100k` | 3 | 8 | 275 | 750 | 0 | 0 | 0 |
| `100k: insert_bs 100k` | 3 | 6 | 251 | 818 | 0 | 0 | 0 |
| `100k: edit_deep 100k` | 3 | 4 | 184 | 775 | 0 | 0 | 0 |
| `ctrlg: ctrlg_like_vim` | 9 | 37 | 176 | 718 | 1 | 2 | 14 |
| `opmx: col1_like_vim` | 9 | 18 | 170 | 848 | 0 | 1 | 19 |
| `40k: insert_bs 40k` | 3 | 6 | 161 | 819 | 0 | 0 | 0 |
| `40k: ndd 40k` | 3 | 8 | 145 | 750 | 0 | 0 | 0 |
| `wrap: wrap_cmds` | 3 | 70 | 140 | 992 | 1 | 2 | 131 |
| `dot: dot_cmds` | 6 | 6 | 134 | 752 | 0 | 0 | 0 |
| `100k: quit_semantics 100k` | 3 | 13 | 127 | 679 | 0 | 0 | 0 |
| `100k: wide_tabs 100k` | 1 | 30 | 120 | 753 | 0 | 0 | 0 |
| `ex: ex_like_vim` | 4 | 52 | 96 | 725 | 3 | 1 | 9 |
| `40k: edit_deep 40k` | 3 | 4 | 95 | 775 | 0 | 0 | 0 |
| `40k: wide_tabs 40k` | 1 | 30 | 93 | 753 | 0 | 0 | 0 |
| `srch: paint_cost` | 8 | 25 | 85 | 736 | 0 | 2 | 13 |
| `100k: hl_x_deep 100k` | 1 | 10 | 85 | 686 | 0 | 0 | 0 |
| `one: write_continue one` | 3 | 15 | 82 | 733 | 0 | 0 | 0 |
| `empty: write_continue empty` | 3 | 15 | 82 | 737 | 0 | 0 | 0 |
| `2k: wide_tabs 2k` | 1 | 30 | 71 | 765 | 0 | 0 | 0 |
| `40k: quit_semantics 40k` | 3 | 13 | 68 | 685 | 0 | 0 | 0 |
| `one: wide_tabs one` | 1 | 30 | 65 | 729 | 0 | 0 | 0 |
| `40k: hl_x_deep 40k` | 1 | 10 | 56 | 686 | 0 | 0 | 0 |
| `2k: edit_deep 2k` | 3 | 4 | 47 | 765 | 0 | 0 | 0 |
| `ctrlg: ctrlg_cmds` | 3 | 20 | 46 | 686 | 0 | 0 | 0 |
| `one: edit_deep one` | 3 | 4 | 43 | 698 | 0 | 0 | 0 |
| `2k: nav_and_save 2k` | 1 | 15 | 39 | 768 | 0 | 0 | 0 |
| `2k: insert_bs 2k` | 2 | 4 | 34 | 738 | 0 | 0 | 0 |
| `file: zz_cmds` | 3 | 14 | 32 | 672 | 0 | 1 | 6 |
| `2k: ndd 2k` | 2 | 6 | 32 | 683 | 0 | 0 | 0 |
| `one: insert_bs one` | 2 | 3 | 29 | 627 | 0 | 0 | 0 |
| `empty: insert_bs empty` | 2 | 3 | 28 | 620 | 0 | 0 | 0 |
| `2k: quit_semantics 2k` | 3 | 13 | 27 | 635 | 0 | 0 | 0 |
| `one: ndd one` | 2 | 4 | 26 | 557 | 0 | 0 | 0 |
| `one: quit_semantics one` | 3 | 13 | 24 | 606 | 0 | 0 | 0 |
| `2k: hl_x_deep 2k` | 1 | 10 | 24 | 682 | 0 | 1 | 24 |
| `empty: quit_semantics empty` | 3 | 13 | 23 | 582 | 0 | 0 | 0 |
| `one: hl_x_deep one` | 1 | 10 | 21 | 607 | 0 | 0 | 0 |
| `one: nav_and_save one` | 1 | 8 | 19 | 578 | 0 | 0 | 0 |
| `empty: ndd empty` | 1 | 2 | 18 | 476 | 0 | 0 | 0 |
| `empty: nav_and_save empty` | 1 | 2 | 18 | 454 | 0 | 0 | 0 |
| `find: find_cmds` | 1 | 4 | 7 | 469 | 0 | 1 | 7 |

## How few editors run the same code

**109 of the 1538 editors** between them run every block the whole suite runs, in **3249 of 72634 emulated seconds** (4.5 %). They are picked greedily, most new code per emulated second first.

That is a floor under the suite, not a suite: the other 1429 editors run no code of their own, but they run it on other text, at other sizes and in other orders, and that is where the bugs were.

## What file size adds

Blocks run at each size of file, and how many of them run at no other size.

| file | editors | emulated s | of the suite | blocks run | only at this size |
|---|---|---|---|---|---|
| empty | 38 | 4314 | 5.9 % | 1119 | 2 |
| under 2 K | 936 | 16414 | 22.6 % | 1672 | 42 |
| 2-24 K | 60 | 3137 | 4.3 % | 1502 | 8 |
| over 24 K | 504 | 48769 | 67.1 % | 1801 | 66 |

## The size sweeps

Five groups run the same eight functions on files of five sizes. For each function: the blocks each size runs that **no other size of the same function** runs, and what the two paging sizes run that the other does not.

| function | only at `empty` | only at `one` | only at `2k` | only at `40k` | only at `100k` | 40k not 100k | 100k not 40k |
|---|---|---|---|---|---|---|---|
| `nav_and_save` | 2 (18 s) | 0 (19 s) | 0 (39 s) | 0 (400 s) | 0 (987 s) | 5 | 0 |
| `edit_deep` | - | 7 (43 s) | 0 (47 s) | 0 (95 s) | 0 (184 s) | 0 | 0 |
| `hl_x_deep` | - | 1 (21 s) | 6 (24 s) | 0 (56 s) | 1 (85 s) | 1 | 1 |
| `wide_tabs` | - | 1 (65 s) | 18 (71 s) | 0 (93 s) | 0 (120 s) | 0 | 0 |
| `insert_bs` | 2 (28 s) | 0 (29 s) | 3 (34 s) | 1 (161 s) | 0 (251 s) | 1 | 0 |
| `ndd` | 2 (18 s) | 0 (26 s) | 4 (32 s) | 0 (145 s) | 0 (275 s) | 0 | 0 |
| `quit_semantics` | 31 (23 s) | 1 (24 s) | 1 (27 s) | 0 (68 s) | 0 (127 s) | 6 | 0 |
| `write_continue` | 2 (82 s) | 0 (82 s) | 14 (913 s) | 0 (1269 s) | 0 (1501 s) | 6 | 0 |

## The heaviest editors that run no code of their own

The twenty longest editors outside the minimal set above. Each is a candidate for a smaller file or a shorter range, never for deletion on this evidence alone: what it checks may be the text, the size or the order, which this table cannot see.

| emulated s | group | function | file bytes | keys (the first 50) |
|---|---|---|---|---|
| 3413 | `file` | `file_cmds` | 0 | `iINS0000\rINS0001\rINS0002\rINS0003\rINS0004\rINS0005\rI` |
| 2213 | `subst` | `subst_like_vim` | 109000 | `:%s/xx/Q/g\r:w\r\r\x1b\x1b:q!\r` |
| 1534 | `full` | `disk_full` | 102400 | `\r\x1b\x1b:q!\r` |
| 1103 | `ins` | `ins_cmds` | 102400 | `10000GRQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ` |
| 1051 | `file` | `file_cmds` | 102400 | `3000Gx:w b:copy.txt\r\x07Gdd:w b:copy.txt\r:w\r:q\r\r` |
| 987 | `100k` | `nav_and_save 100k` | 102400 | `Ggg\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06` |
| 901 | `after` | `after_cmds` | 102400 | `3600G2l/003100\rx\x07j\x07.\x072x\x07\x0c3620G2l/012000\rx\x07j\x07.\x072x\x07\x0c` |
| 784 | `100k` | `write_continue 100k` | 102400 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 645 | `100k` | `write_continue 100k` | 102400 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 635 | `40k` | `write_continue 40k` | 40960 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 592 | `srch` | `srch_cmds` | 102400 | `6000G/zzzz\r\x07\x0c6000G?zzzz\r\x07\x0c100G/zzzz\r\x07\x0c12700G?zzzz\r` |
| 590 | `40k` | `write_continue 40k` | 40960 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 556 | `ops` | `ops_cmds` | 102400 | `6000GoINS0000\rINS0001\rINS0002\rINS0003\rINS0004\rINS0` |
| 452 | `2k` | `write_continue 2k` | 2048 | `250jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS0004` |
| 443 | `mot` | `mot_like_vim` | 100650 | `99999wb99999B` |
| 441 | `2k` | `write_continue 2k` | 2048 | `250jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS0004` |
| 400 | `40k` | `nav_and_save 40k` | 40960 | `Ggg\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06` |
| 395 | `lnum` | `lnum_cmds` | 102400 | `6000G6100G5900G6000Gd6500G\x073000G\x07G\x0712200G6000G300d` |
| 368 | `after` | `after_cmds` | 102400 | `3360G2lGx\x07j\x07.\x072x\x07\x0c3380G2lggx\x07j\x07.\x072x\x07\x0c3400G2l9000Gx` |
| 349 | `subst` | `subst_like_vim` | 102400 | `:%s/0/ZZ/\r:w\r\r\x1b\x1b:q!\r` |

## Operator x motion x paging

Every time an operator met a motion in the editor (`OPPEND`), read out of the editor itself: the operator, the key after it, and whether the window paged before the next key was read. Each cell is the number of times it happened in the whole suite; **0** is a cell no test enters, `-` a pair the editor does not accept (`c` takes no linewise motion, `y` takes only linewise ones), and `.` a motion that cannot leave the window, so cannot page. A "paged" cell can stay at 0 with a test on it: a charwise span the window does not hold is refused before the window moves (`pgop` checks the refusals).

| motion | `d` | `d` paged | `c` | `c` paged | `y` | `y` paged |
|---|---|---|---|---|---|---|
| `w` | 88 | 1 | 61 | 1 | - | - |
| `W` | 11 | 1 | 13 | **0** | - | - |
| `b` | 18 | 1 | 17 | **0** | - | - |
| `B` | 12 | 1 | 10 | **0** | - | - |
| `h` | 15 | . | 9 | . | - | - |
| `l` | 15 | . | 12 | . | - | - |
| `0` | 9 | . | 14 | . | - | - |
| `^` | 9 | . | 10 | . | - | - |
| `` ` ``{a-c} | 32 | **0** | 21 | **0** | - | - |
| `f` | 11 | . | 6 | . | - | - |
| `t` | 7 | . | 6 | . | - | - |
| `F` | 11 | . | 6 | . | - | - |
| `T` | 11 | . | 6 | . | - | - |
| `;` | 9 | . | 6 | . | - | - |
| `,` | 8 | . | 7 | . | - | - |
| `e` | 25 | 1 | 12 | 1 | - | - |
| `E` | 8 | 1 | 11 | **0** | - | - |
| `$` | 12 | 1 | 11 | 1 | - | - |
| `j` | 15 | 2 | - | - | 8 | 1 |
| `k` | 20 | 1 | - | - | 7 | 1 |
| `G` | 23 | 13 | - | - | 7 | 2 |
| `H` | 13 | . | - | - | 5 | . |
| `M` | 10 | . | - | - | 3 | . |
| `L` | 13 | . | - | - | 5 | . |
| `gg` | 21 | 3 | - | - | 5 | 1 |
| `'`{a-c} | 32 | 3 | - | - | 21 | **0** |
| `dd` `yy` | 151 | 8 | - | - | 46 | 12 |

Operator and key pairs that are NOT motions (the operator is dropped) and how often the suite typed one: `c%` 1, `cc` 1, `cq` 1, `cz` 1, `d%` 1, `dz` 3, `yz` 1.

## The stack

The stack is 128 bytes with the image directly below it. It is filled before each editor starts and read when the editor is done; the deepest any test took it is **68 bytes**. The five deepest:

| bytes used | group | function | keys (the first 60) |
|---|---|---|---|
| 68 | `100k` | `nav_and_save 100k` | `Ggg\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06` |
| 68 | `40k` | `nav_and_save 40k` | `Ggg\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06` |
| 68 | `scrolls` | `scrolls_like_vim` | `3000G$\x04\x15` |
| 68 | `wrap` | `wrap_like_vim` | `\x06\x06\x06\x06\x06\x06\x06\x06\x02\x02\x02\x02\x02\x02\x02\x02:q\r` |
| 68 | `wrap` | `wrap_like_vim` | `\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x15\x15\x15\x15\x15\x15\x15\x15\x15\x15:q\r` |

## Code no test runs

53 blocks, 243 bytes. Listed under the label above each, with the first instruction of the block; several blocks under one label are listed once with a count.

### SCRN.MAC -- 4 blocks, 13 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `RDB_LP` | 1 | 2 | `STC` |
| `SD_NS` | 1 | 4 | `XRA A` |
| `FT_OVR` | 1 | 4 | `POP H` |
| `HBMOR` | 1 | 3 | `JMP HB_NX` |

### CMD.MAC -- 9 blocks, 45 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `UCL_BK` | 1 | 2 | `DCX H` |
| `COL` | 1 | 9 | `PUSH H` |
| `CLASSF` | 1 | 3 | `JMP CLS2` |
| `KC_TB` | 2 | 10 | `CALL REWIND` |
| `NXLN` | 1 | 3 | `DCX H` |
| `OPG_PG` | 1 | 13 | `DCX H` |
| `OPA_F` | 1 | 4 | `XCHG` |
| `AS_TOK` | 1 | 1 | `RET` |

### PAGE.MAC -- 9 blocks, 54 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `SAVEFIL` | 2 | 26 | `CALL SAVCLO` |
| `SKMORE` | 1 | 10 | `LHLD TXTBEG` |
| `WRCLP` | 1 | 3 | `JMP DSKERR` |
| `MKROOM` | 1 | 3 | `JMP SPILLB` |
| `FATAL` | 1 | 3 | `JMP ERRMSG` |
| `CLOSEF` | 1 | 3 | `CALL FATAL` |
| `DIRFUL` | 1 | 3 | `CALL FATAL` |
| `RENF` | 1 | 3 | `CALL FATAL` |

### BUF.MAC -- 31 blocks, 131 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `INSCNT` | 1 | 6 | `MOV C,A` |
| `MKGAPL` | 1 | 3 | `CALL ERRMSG` |
| `QROOM` | 1 | 3 | `CALL ERRMSG` |
| `PEEKLX` | 1 | 3 | `INX SP` |
| `WCMATCH` | 3 | 16 | `INX D` |
| `WCSEP` | 1 | 9 | `MOV A,M` |
| `WCNO` | 1 | 2 | `ORA A` |
| `ISWBRK` | 1 | 5 | `CALL ISWHITE` |
| `ISALNUM` | 3 | 14 | `CALL ISDIGIT` |
| `ISDIGIT` | 2 | 7 | `CPI '0'` |
| `UPCASE` | 3 | 9 | `CPI 'a'` |
| `ISWHITE` | 4 | 12 | `CPI TAB` |
| `PUTCERR` | 1 | 3 | `CALL ERRMSG` |
| `PUTHERR` | 1 | 3 | `CALL ERRMSG` |
| `CKCOPY` | 1 | 3 | `CALL ERRMSG` |
| `SUBCLP` | 1 | 6 | `CALL CMP16` |
| `SCLPPO` | 1 | 7 | `PUSH H` |
| `ERMLP` | 1 | 12 | `PUSH H` |
| `ERMEND` | 1 | 6 | `CALL DISCRD` |
| `ERMGO` | 1 | 1 | `PCHL` |
| `ERMNUL` | 1 | 1 | `RET` |

