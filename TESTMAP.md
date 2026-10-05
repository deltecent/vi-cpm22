# What the acceptance tests reach

Written by `python3 covmap.py --write`; do not edit. Measured on a `VI.COM` of 18560 bytes by running `accept_vi.py` unchanged with a recorder in the simulator driver (`covmap.py` says how).

The suite started **1215 editors** and made **6416 checks** in **62102 emulated seconds**. `VI.COM` has **1750 basic blocks** of code (16995 bytes); the suite ran **1670** of them (95.4 %, 16593 bytes).

A block that ran is not a block that is tested: every bug in issue #3 was in code the suite ran on every pass, reached in a state no test put it in. So this table can show a test is NOT looking somewhere, and that two tests walk the same code; it cannot show that either of them is enough. The operator table below is the other half -- states, not code.

## Groups

"only here" is code no other group runs: what would go unrun if the group were dropped.

| group | editors | checks | emulated s | of the suite | blocks run | only here | bytes only here |
|---|---|---|---|---|---|---|---|
| `file` | 25 | 346 | 5547 | 8.9 % | 991 | 14 | 112 |
| `subst` | 43 | 125 | 4564 | 7.3 % | 829 | 2 | 12 |
| `ops` | 95 | 285 | 4402 | 7.1 % | 1014 | 0 | 0 |
| `pgop` | 57 | 163 | 4227 | 6.8 % | 1079 | 6 | 81 |
| `ins` | 44 | 156 | 3542 | 5.7 % | 804 | 9 | 106 |
| `100k` | 18 | 101 | 3335 | 5.4 % | 887 | 0 | 0 |
| `marks` | 148 | 506 | 3041 | 4.9 % | 1187 | 0 | 0 |
| `srch` | 58 | 209 | 2901 | 4.7 % | 838 | 0 | 0 |
| `opmx` | 127 | 771 | 2740 | 4.4 % | 1066 | 2 | 7 |
| `after` | 21 | 792 | 2268 | 3.7 % | 1391 | 1 | 6 |
| `limits` | 34 | 72 | 2243 | 3.6 % | 1005 | 8 | 26 |
| `undo` | 51 | 174 | 2035 | 3.3 % | 1037 | 1 | 7 |
| `40k` | 18 | 101 | 1958 | 3.2 % | 892 | 0 | 0 |
| `mot` | 37 | 514 | 1712 | 2.8 % | 724 | 2 | 4 |
| `dot` | 37 | 145 | 1703 | 2.7 % | 1030 | 0 | 0 |
| `full` | 4 | 20 | 1594 | 2.6 % | 659 | 6 | 50 |
| `ndd` | 19 | 85 | 1384 | 2.2 % | 703 | 0 | 0 |
| `put` | 40 | 145 | 1363 | 2.2 % | 795 | 1 | 8 |
| `scrolls` | 63 | 203 | 1361 | 2.2 % | 652 | 3 | 24 |
| `qfull` | 10 | 46 | 1321 | 2.1 % | 823 | 1 | 3 |
| `bs` | 12 | 69 | 1235 | 2.0 % | 773 | 0 | 0 |
| `rdwr` | 18 | 128 | 1197 | 1.9 % | 934 | 7 | 59 |
| `2k` | 16 | 97 | 1038 | 1.7 % | 864 | 0 | 0 |
| `find` | 46 | 173 | 866 | 1.4 % | 764 | 0 | 0 |
| `goto` | 29 | 92 | 863 | 1.4 % | 619 | 0 | 0 |
| `arg` | 41 | 112 | 846 | 1.4 % | 779 | 7 | 41 |
| `hml` | 30 | 329 | 833 | 1.3 % | 670 | 0 | 0 |
| `lnum` | 2 | 37 | 507 | 0.8 % | 867 | 0 | 0 |
| `jk` | 27 | 128 | 348 | 0.6 % | 691 | 0 | 0 |
| `brk` | 3 | 61 | 331 | 0.5 % | 787 | 4 | 31 |
| `one` | 16 | 87 | 310 | 0.5 % | 776 | 0 | 0 |
| `ctrlg` | 12 | 57 | 222 | 0.4 % | 818 | 0 | 0 |
| `empty` | 10 | 35 | 168 | 0.3 % | 711 | 0 | 0 |
| `ex` | 4 | 52 | 97 | 0.2 % | 608 | 3 | 30 |

## Test functions

The same, per function `main()` calls. "needed" is how many of its editors a minimal set keeps -- see the next section.

| function | editors | checks | emulated s | blocks run | only here | needed | their emulated s |
|---|---|---|---|---|---|---|---|
| `subst: subst_like_vim` | 37 | 84 | 4251 | 762 | 0 | 0 | 0 |
| `pgop: pgop_cmds` | 57 | 163 | 4227 | 1079 | 6 | 4 | 395 |
| `file: file_cmds` | 16 | 164 | 4226 | 858 | 13 | 5 | 381 |
| `ops: ops_like_vim` | 69 | 229 | 3197 | 914 | 0 | 2 | 37 |
| `opmx: opmx_like_vim` | 127 | 771 | 2740 | 1066 | 2 | 5 | 106 |
| `after: after_cmds` | 21 | 792 | 2268 | 1391 | 1 | 4 | 203 |
| `limits: limits_cmds` | 34 | 72 | 2243 | 1005 | 8 | 6 | 1226 |
| `srch: srch_like_vim` | 49 | 168 | 2215 | 667 | 0 | 2 | 36 |
| `ins: ins_cmds` | 13 | 19 | 2113 | 784 | 2 | 4 | 37 |
| `marks: marks_cmds` | 95 | 216 | 2039 | 1153 | 0 | 12 | 84 |
| `mot: mot_like_vim` | 37 | 514 | 1712 | 724 | 2 | 6 | 47 |
| `full: disk_full` | 4 | 20 | 1594 | 659 | 6 | 2 | 35 |
| `undo: undo_like_vim` | 37 | 158 | 1590 | 1009 | 0 | 0 | 0 |
| `dot: dot_like_vim` | 31 | 139 | 1565 | 1026 | 0 | 1 | 62 |
| `ins: ins_like_vim` | 31 | 137 | 1428 | 772 | 1 | 3 | 105 |
| `ndd: ndd_like_vim` | 19 | 85 | 1384 | 703 | 0 | 0 | 0 |
| `put: put_like_vim` | 40 | 145 | 1363 | 795 | 1 | 3 | 45 |
| `scrolls: scrolls_like_vim` | 63 | 203 | 1361 | 652 | 3 | 5 | 60 |
| `qfull: qfull_cmds` | 10 | 46 | 1321 | 823 | 1 | 3 | 343 |
| `file: edit_like_vim` | 6 | 168 | 1288 | 812 | 0 | 0 | 0 |
| `bs: bs_like_vim` | 12 | 69 | 1235 | 773 | 0 | 1 | 19 |
| `ops: ops_cmds` | 26 | 56 | 1206 | 964 | 0 | 4 | 26 |
| `100k: nav_and_save 100k` | 1 | 15 | 1176 | 685 | 0 | 0 | 0 |
| `100k: write_continue 100k` | 3 | 15 | 1143 | 764 | 0 | 0 | 0 |
| `marks: marks_like_vim` | 53 | 290 | 1002 | 877 | 0 | 0 | 0 |
| `40k: write_continue 40k` | 3 | 15 | 914 | 770 | 0 | 0 | 0 |
| `goto: goto_like_vim` | 29 | 92 | 863 | 619 | 0 | 0 | 0 |
| `find: find_like_vim` | 45 | 169 | 859 | 757 | 0 | 2 | 38 |
| `hml: hml_like_vim` | 30 | 329 | 833 | 670 | 0 | 1 | 6 |
| `2k: write_continue 2k` | 3 | 15 | 764 | 754 | 0 | 0 | 0 |
| `rdwr: rdwr_cmds` | 6 | 77 | 671 | 900 | 3 | 3 | 66 |
| `srch: srch_cmds` | 1 | 16 | 601 | 537 | 0 | 0 | 0 |
| `arg: plus_like_vim` | 31 | 76 | 540 | 595 | 5 | 2 | 12 |
| `rdwr: rdwr_like_vim` | 12 | 51 | 526 | 823 | 0 | 1 | 24 |
| `lnum: lnum_cmds` | 2 | 37 | 507 | 867 | 0 | 0 | 0 |
| `40k: nav_and_save 40k` | 1 | 15 | 470 | 690 | 0 | 1 | 470 |
| `undo: undo_cmds` | 14 | 16 | 445 | 801 | 1 | 1 | 110 |
| `jk: jk_like_vim` | 27 | 128 | 348 | 691 | 0 | 2 | 13 |
| `brk: brk_cmds` | 3 | 61 | 331 | 787 | 4 | 1 | 217 |
| `subst: subst_cmds` | 6 | 41 | 313 | 731 | 2 | 3 | 22 |
| `arg: arg_cmds` | 10 | 36 | 306 | 692 | 2 | 1 | 7 |
| `100k: ndd 100k` | 3 | 8 | 272 | 668 | 0 | 0 | 0 |
| `100k: insert_bs 100k` | 3 | 6 | 233 | 741 | 0 | 0 | 0 |
| `100k: edit_deep 100k` | 3 | 4 | 178 | 697 | 0 | 0 | 0 |
| `ctrlg: ctrlg_like_vim` | 9 | 37 | 177 | 630 | 0 | 1 | 8 |
| `40k: insert_bs 40k` | 3 | 6 | 143 | 743 | 0 | 0 | 0 |
| `dot: dot_cmds` | 6 | 6 | 138 | 676 | 0 | 0 | 0 |
| `100k: quit_semantics 100k` | 3 | 13 | 129 | 603 | 0 | 0 | 0 |
| `40k: ndd 40k` | 3 | 8 | 128 | 668 | 0 | 0 | 0 |
| `100k: wide_tabs 100k` | 1 | 30 | 121 | 662 | 0 | 0 | 0 |
| `ex: ex_like_vim` | 4 | 52 | 97 | 608 | 3 | 1 | 9 |
| `40k: edit_deep 40k` | 3 | 4 | 94 | 697 | 0 | 0 | 0 |
| `40k: wide_tabs 40k` | 1 | 30 | 94 | 662 | 0 | 0 | 0 |
| `srch: paint_cost` | 8 | 25 | 85 | 652 | 0 | 2 | 13 |
| `100k: hl_x_deep 100k` | 1 | 10 | 85 | 606 | 0 | 0 | 0 |
| `one: write_continue one` | 3 | 15 | 82 | 659 | 0 | 0 | 0 |
| `empty: write_continue empty` | 3 | 15 | 81 | 654 | 0 | 0 | 0 |
| `2k: wide_tabs 2k` | 1 | 30 | 73 | 678 | 0 | 0 | 0 |
| `one: wide_tabs one` | 1 | 30 | 68 | 644 | 0 | 0 | 0 |
| `40k: quit_semantics 40k` | 3 | 13 | 60 | 609 | 0 | 0 | 0 |
| `40k: hl_x_deep 40k` | 1 | 10 | 55 | 606 | 0 | 0 | 0 |
| `ctrlg: ctrlg_cmds` | 3 | 20 | 46 | 624 | 0 | 0 | 0 |
| `2k: edit_deep 2k` | 3 | 4 | 46 | 687 | 0 | 0 | 0 |
| `one: edit_deep one` | 3 | 4 | 43 | 647 | 0 | 0 | 0 |
| `2k: nav_and_save 2k` | 1 | 15 | 42 | 655 | 0 | 0 | 0 |
| `2k: insert_bs 2k` | 2 | 4 | 32 | 666 | 0 | 0 | 0 |
| `file: zz_cmds` | 3 | 14 | 32 | 613 | 0 | 1 | 6 |
| `2k: ndd 2k` | 2 | 6 | 31 | 618 | 0 | 0 | 0 |
| `one: insert_bs one` | 2 | 3 | 29 | 568 | 0 | 0 | 0 |
| `empty: insert_bs empty` | 2 | 3 | 28 | 565 | 0 | 0 | 0 |
| `2k: quit_semantics 2k` | 3 | 13 | 26 | 559 | 0 | 0 | 0 |
| `one: ndd one` | 2 | 4 | 26 | 520 | 0 | 0 | 0 |
| `one: quit_semantics one` | 3 | 13 | 24 | 542 | 0 | 0 | 0 |
| `empty: quit_semantics empty` | 3 | 13 | 23 | 534 | 0 | 1 | 9 |
| `2k: hl_x_deep 2k` | 1 | 10 | 23 | 603 | 0 | 1 | 23 |
| `one: hl_x_deep one` | 1 | 10 | 20 | 543 | 0 | 0 | 0 |
| `one: nav_and_save one` | 1 | 8 | 19 | 541 | 0 | 0 | 0 |
| `empty: ndd empty` | 1 | 2 | 18 | 444 | 0 | 0 | 0 |
| `empty: nav_and_save empty` | 1 | 2 | 18 | 422 | 0 | 0 | 0 |
| `find: find_cmds` | 1 | 4 | 7 | 418 | 0 | 1 | 7 |

## How few editors run the same code

**98 of the 1215 editors** between them run every block the whole suite runs, in **4307 of 62102 emulated seconds** (6.9 %). They are picked greedily, most new code per emulated second first.

That is a floor under the suite, not a suite: the other 1117 editors run no code of their own, but they run it on other text, at other sizes and in other orders, and that is where the bugs were.

## What file size adds

Blocks run at each size of file, and how many of them run at no other size.

| file | editors | emulated s | of the suite | blocks run | only at this size |
|---|---|---|---|---|---|
| empty | 38 | 3101 | 5.0 % | 1027 | 2 |
| under 2 K | 662 | 10991 | 17.7 % | 1504 | 31 |
| 2-24 K | 41 | 1720 | 2.8 % | 1132 | 8 |
| over 24 K | 474 | 46290 | 74.5 % | 1621 | 66 |

## The size sweeps

Five groups run the same eight functions on files of five sizes. For each function: the blocks each size runs that **no other size of the same function** runs, and what the two paging sizes run that the other does not.

| function | only at `empty` | only at `one` | only at `2k` | only at `40k` | only at `100k` | 40k not 100k | 100k not 40k |
|---|---|---|---|---|---|---|---|
| `nav_and_save` | 1 (18 s) | 0 (19 s) | 0 (42 s) | 0 (470 s) | 0 (1176 s) | 5 | 0 |
| `edit_deep` | - | 6 (43 s) | 0 (46 s) | 0 (94 s) | 0 (178 s) | 0 | 0 |
| `hl_x_deep` | - | 1 (20 s) | 6 (23 s) | 0 (55 s) | 1 (85 s) | 1 | 1 |
| `wide_tabs` | - | 1 (68 s) | 17 (73 s) | 0 (94 s) | 0 (121 s) | 0 | 0 |
| `insert_bs` | 2 (28 s) | 0 (29 s) | 4 (32 s) | 1 (143 s) | 0 (233 s) | 2 | 0 |
| `ndd` | 1 (18 s) | 0 (26 s) | 4 (31 s) | 0 (128 s) | 0 (272 s) | 0 | 0 |
| `quit_semantics` | 42 (23 s) | 1 (24 s) | 1 (26 s) | 0 (60 s) | 0 (129 s) | 6 | 0 |
| `write_continue` | 2 (81 s) | 0 (82 s) | 6 (764 s) | 0 (914 s) | 0 (1143 s) | 6 | 0 |

## The heaviest editors that run no code of their own

The twenty longest editors outside the minimal set above. Each is a candidate for a smaller file or a shorter range, never for deletion on this evidence alone: what it checks may be the text, the size or the order, which this table cannot see.

| emulated s | group | function | file bytes | keys (the first 50) |
|---|---|---|---|---|
| 2310 | `file` | `file_cmds` | 0 | `iINS0000\rINS0001\rINS0002\rINS0003\rINS0004\rINS0005\rI` |
| 2210 | `subst` | `subst_like_vim` | 109000 | `:%s/xx/Q/g\r:w\r\r\x1b\x1b:q!\r` |
| 1711 | `ins` | `ins_cmds` | 102400 | `10000GRQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ` |
| 1543 | `full` | `disk_full` | 102400 | `\r\x1b\x1b:q!\r` |
| 1176 | `100k` | `nav_and_save 100k` | 102400 | `Ggg\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06` |
| 1044 | `file` | `file_cmds` | 102400 | `3000Gx:w b:copy.txt\r\x07Gdd:w b:copy.txt\r:w\r:q\r\r` |
| 917 | `after` | `after_cmds` | 102400 | `3600G2l/003100\rx\x07j\x07.\x072x\x07\x0c3620G2l/012000\rx\x07j\x07.\x072x\x07\x0c` |
| 605 | `100k` | `write_continue 100k` | 102400 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 601 | `srch` | `srch_cmds` | 102400 | `6000G/zzzz\r\x07\x0c6000G?zzzz\r\x07\x0c100G/zzzz\r\x07\x0c12700G?zzzz\r` |
| 468 | `100k` | `write_continue 100k` | 102400 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 458 | `40k` | `write_continue 40k` | 40960 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 442 | `mot` | `mot_like_vim` | 100650 | `99999wb99999B` |
| 412 | `40k` | `write_continue 40k` | 40960 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 395 | `lnum` | `lnum_cmds` | 102400 | `6000G6100G5900G6000Gd6500G\x073000G\x07G\x0712200G6000G300d` |
| 377 | `2k` | `write_continue 2k` | 2048 | `250jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS0004` |
| 366 | `2k` | `write_continue 2k` | 2048 | `250jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS0004` |
| 356 | `after` | `after_cmds` | 102400 | `3360G2lGx\x07j\x07.\x072x\x07\x0c3380G2lggx\x07j\x07.\x072x\x07\x0c3400G2l9000Gx` |
| 347 | `subst` | `subst_like_vim` | 102400 | `:%s/0/ZZ/\r:w\r\r\x1b\x1b:q!\r` |
| 330 | `subst` | `subst_like_vim` | 102400 | `:%s/0/Z/\r:w\r\r\x1b\x1b:q!\r` |
| 319 | `file` | `edit_like_vim` | 102400 | `3000G:e\rG:e\r5G:e\r12G:e\r13G:e\r23G:e\r40G:e\r12790G:e\r` |

## Operator x motion x paging

Every time an operator met a motion in the editor (`OPPEND`), read out of the editor itself: the operator, the key after it, and whether the window paged before the next key was read. Each cell is the number of times it happened in the whole suite; **0** is a cell no test enters, `-` a pair the editor does not accept (`c` takes no linewise motion, `y` takes only linewise ones), and `.` a motion that cannot leave the window, so cannot page. A "paged" cell can stay at 0 with a test on it: a charwise span the window does not hold is refused before the window moves (`pgop` checks the refusals), and `e` does not page at all (#23).

| motion | `d` | `d` paged | `c` | `c` paged | `y` | `y` paged |
|---|---|---|---|---|---|---|
| `w` | 35 | 1 | 28 | **0** | - | - |
| `W` | 8 | 1 | 11 | **0** | - | - |
| `b` | 8 | 1 | 11 | **0** | - | - |
| `B` | 8 | 1 | 11 | **0** | - | - |
| `h` | 7 | . | 9 | . | - | - |
| `l` | 7 | . | 9 | . | - | - |
| `0` | 5 | . | 10 | . | - | - |
| `^` | 5 | . | 10 | . | - | - |
| `` ` ``{a-c} | 17 | **0** | 15 | **0** | - | - |
| `f` | 11 | . | 6 | . | - | - |
| `t` | 7 | . | 6 | . | - | - |
| `F` | 7 | . | 6 | . | - | - |
| `T` | 7 | . | 6 | . | - | - |
| `;` | 9 | . | 6 | . | - | - |
| `,` | 8 | . | 7 | . | - | - |
| `e` | 9 | **0** | 11 | **0** | - | - |
| `E` | 8 | **0** | 11 | **0** | - | - |
| `$` | 8 | 1 | 11 | 1 | - | - |
| `j` | 11 | 2 | - | - | 8 | 1 |
| `k` | 12 | 1 | - | - | 7 | 1 |
| `G` | 19 | 13 | - | - | 7 | 2 |
| `H` | 9 | . | - | - | 5 | . |
| `M` | 6 | . | - | - | 3 | . |
| `L` | 9 | . | - | - | 5 | . |
| `gg` | 14 | 3 | - | - | 5 | 1 |
| `'`{a-c} | 26 | 2 | - | - | 21 | **0** |
| `dd` `yy` | 127 | 7 | - | - | 46 | 11 |

Operator and key pairs that are NOT motions (the operator is dropped) and how often the suite typed one: `c%` 1, `cc` 1, `cq` 1, `cz` 1, `d%` 1, `dz` 3, `yz` 1.

## The stack

The stack is 128 bytes with the image directly below it. It is filled before each editor starts and read when the editor is done; the deepest any test took it is **68 bytes**. The five deepest:

| bytes used | group | function | keys (the first 60) |
|---|---|---|---|
| 68 | `limits` | `limits_cmds` | `jyypp` |
| 66 | `dot` | `dot_like_vim` | `0dw..:w\r\r\x1b\x1b:q!\r` |
| 66 | `dot` | `dot_like_vim` | `0dwj.:w\r\r\x1b\x1b:q!\r` |
| 66 | `dot` | `dot_like_vim` | `3000Gdw.:w\r\r\x1b\x1b:q!\r` |
| 66 | `dot` | `dot_like_vim` | `0cwZZZ\x1b.:w\r\r\x1b\x1b:q!\r` |

## Code no test runs

80 blocks, 402 bytes. Listed under the label above each, with the first instruction of the block; several blocks under one label are listed once with a count.

### SCRN.MAC -- 1 blocks, 2 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `RDB_LP` | 1 | 2 | `STC` |

### CMD.MAC -- 6 blocks, 31 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `UCL_BK` | 1 | 2 | `DCX H` |
| `COL` | 1 | 9 | `PUSH H` |
| `CLASSF` | 1 | 3 | `JMP CLS2` |
| `NXLN` | 1 | 3 | `DCX H` |
| `OPG_PG` | 1 | 13 | `DCX H` |
| `AS_TOK` | 1 | 1 | `RET` |

### KEY.MAC -- 35 blocks, 190 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `GK_CSI` | 4 | 34 | `MVI A,0` |
| `GKCSIF` | 14 | 71 | `CPI 'A'` |
| `GK_SS3` | 6 | 30 | `CALL GK_POLL` |
| `GKCUUP` | 1 | 5 | `MVI C,ACT_CURUP` |
| `GKCUDN` | 1 | 5 | `MVI C,ACT_CURDN` |
| `GKCURT` | 1 | 5 | `MVI C,ACT_CURRT` |
| `GKCULT` | 1 | 5 | `MVI C,ACT_CURLT` |
| `GKLNST` | 1 | 5 | `MVI C,ACT_LINST` |
| `GKLNEN` | 1 | 5 | `MVI C,ACT_LINEN` |
| `GK_INS` | 1 | 5 | `MVI C,ACT_INS` |
| `GK_DEL` | 1 | 5 | `MVI C,ACT_DEL` |
| `GK_PGUP` | 1 | 5 | `MVI C,ACT_PGUP` |
| `GK_PGDN` | 1 | 5 | `MVI C,ACT_PGDN` |
| `GK_NONE` | 1 | 5 | `MVI B,KT_NONE` |

### PAGE.MAC -- 8 blocks, 51 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `SAVEFIL` | 2 | 26 | `CALL SAVCLO` |
| `SKMORE` | 1 | 10 | `LHLD TXTBEG` |
| `WRCLP` | 1 | 3 | `JMP DSKERR` |
| `FATAL` | 1 | 3 | `JMP ERRMSG` |
| `CLOSEF` | 1 | 3 | `CALL FATAL` |
| `DIRFUL` | 1 | 3 | `CALL FATAL` |
| `RENF` | 1 | 3 | `CALL FATAL` |

### BUF.MAC -- 30 blocks, 128 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `INSCNT` | 1 | 6 | `MOV C,A` |
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

