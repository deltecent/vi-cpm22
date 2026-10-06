# What the acceptance tests reach

Written by `python3 covmap.py --write`; do not edit. Measured on a `VI.COM` of 18816 bytes by running `accept_vi.py` unchanged with a recorder in the simulator driver (`covmap.py` says how).

The suite started **1483 editors** and made **7518 checks** in **68659 emulated seconds**. `VI.COM` has **1792 basic blocks** of code (17312 bytes); the suite ran **1710** of them (95.4 %, 16903 bytes).

A block that ran is not a block that is tested: every bug in issue #3 was in code the suite ran on every pass, reached in a state no test put it in. So this table can show a test is NOT looking somewhere, and that two tests walk the same code; it cannot show that either of them is enough. The operator table below is the other half -- states, not code.

## Groups

"only here" is code no other group runs: what would go unrun if the group were dropped.

| group | editors | checks | emulated s | of the suite | blocks run | only here | bytes only here |
|---|---|---|---|---|---|---|---|
| `file` | 25 | 346 | 5547 | 8.1 % | 998 | 14 | 112 |
| `pgop` | 65 | 182 | 5014 | 7.3 % | 1120 | 6 | 81 |
| `opmx` | 245 | 1227 | 4942 | 7.2 % | 1091 | 3 | 23 |
| `undo` | 193 | 801 | 4810 | 7.0 % | 1191 | 1 | 7 |
| `subst` | 43 | 125 | 4571 | 6.7 % | 838 | 2 | 12 |
| `ops` | 95 | 285 | 4382 | 6.4 % | 1022 | 0 | 0 |
| `ins` | 44 | 156 | 3534 | 5.1 % | 814 | 9 | 106 |
| `100k` | 18 | 101 | 3334 | 4.9 % | 899 | 0 | 0 |
| `marks` | 148 | 506 | 3041 | 4.4 % | 1216 | 0 | 0 |
| `limits` | 34 | 72 | 2954 | 4.3 % | 1018 | 8 | 26 |
| `srch` | 58 | 209 | 2907 | 4.2 % | 849 | 0 | 0 |
| `after` | 21 | 792 | 2269 | 3.3 % | 1413 | 1 | 6 |
| `40k` | 18 | 101 | 1956 | 2.8 % | 904 | 0 | 0 |
| `mot` | 37 | 514 | 1712 | 2.5 % | 737 | 1 | 2 |
| `dot` | 37 | 145 | 1704 | 2.5 % | 1042 | 0 | 0 |
| `full` | 4 | 20 | 1628 | 2.4 % | 664 | 6 | 50 |
| `ndd` | 19 | 85 | 1387 | 2.0 % | 717 | 0 | 0 |
| `put` | 40 | 145 | 1374 | 2.0 % | 816 | 1 | 8 |
| `qfull` | 10 | 46 | 1371 | 2.0 % | 833 | 0 | 0 |
| `scrolls` | 63 | 203 | 1363 | 2.0 % | 654 | 3 | 24 |
| `bs` | 12 | 69 | 1230 | 1.8 % | 783 | 0 | 0 |
| `rdwr` | 18 | 128 | 1195 | 1.7 % | 942 | 7 | 59 |
| `2k` | 16 | 97 | 1038 | 1.5 % | 876 | 0 | 0 |
| `find` | 46 | 173 | 866 | 1.3 % | 775 | 0 | 0 |
| `goto` | 29 | 92 | 863 | 1.3 % | 621 | 0 | 0 |
| `arg` | 41 | 112 | 848 | 1.2 % | 782 | 7 | 41 |
| `hml` | 30 | 329 | 834 | 1.2 % | 677 | 0 | 0 |
| `lnum` | 2 | 37 | 505 | 0.7 % | 881 | 0 | 0 |
| `jk` | 27 | 128 | 349 | 0.5 % | 704 | 0 | 0 |
| `brk` | 3 | 61 | 333 | 0.5 % | 794 | 4 | 31 |
| `one` | 16 | 87 | 310 | 0.5 % | 788 | 0 | 0 |
| `ctrlg` | 12 | 57 | 223 | 0.3 % | 835 | 1 | 10 |
| `empty` | 10 | 35 | 168 | 0.2 % | 717 | 0 | 0 |
| `ex` | 4 | 52 | 97 | 0.1 % | 613 | 3 | 30 |

## Test functions

The same, per function `main()` calls. "needed" is how many of its editors a minimal set keeps -- see the next section.

| function | editors | checks | emulated s | blocks run | only here | needed | their emulated s |
|---|---|---|---|---|---|---|---|
| `pgop: pgop_cmds` | 65 | 182 | 5014 | 1120 | 6 | 4 | 424 |
| `subst: subst_like_vim` | 37 | 84 | 4257 | 771 | 0 | 0 | 0 |
| `file: file_cmds` | 16 | 164 | 4227 | 865 | 13 | 6 | 389 |
| `ops: ops_like_vim` | 69 | 229 | 3183 | 921 | 0 | 2 | 37 |
| `limits: limits_cmds` | 34 | 72 | 2954 | 1018 | 8 | 9 | 2050 |
| `undo: undo_at_vim` | 142 | 627 | 2776 | 1020 | 0 | 2 | 28 |
| `opmx: opmx_like_vim` | 127 | 991 | 2736 | 1082 | 2 | 6 | 124 |
| `after: after_cmds` | 21 | 792 | 2269 | 1413 | 1 | 4 | 204 |
| `srch: srch_like_vim` | 49 | 168 | 2221 | 674 | 0 | 2 | 36 |
| `ins: ins_cmds` | 13 | 19 | 2112 | 789 | 2 | 4 | 37 |
| `marks: marks_cmds` | 95 | 216 | 2039 | 1181 | 0 | 13 | 89 |
| `opmx: word_like_vim` | 92 | 184 | 1722 | 908 | 1 | 1 | 19 |
| `mot: mot_like_vim` | 37 | 514 | 1712 | 737 | 1 | 5 | 39 |
| `full: disk_full` | 4 | 20 | 1628 | 664 | 6 | 2 | 37 |
| `undo: undo_like_vim` | 37 | 158 | 1590 | 1033 | 0 | 0 | 0 |
| `dot: dot_like_vim` | 31 | 139 | 1566 | 1038 | 0 | 1 | 63 |
| `ins: ins_like_vim` | 31 | 137 | 1422 | 782 | 1 | 3 | 105 |
| `ndd: ndd_like_vim` | 19 | 85 | 1387 | 717 | 0 | 0 | 0 |
| `put: put_like_vim` | 40 | 145 | 1374 | 816 | 1 | 4 | 63 |
| `qfull: qfull_cmds` | 10 | 46 | 1371 | 833 | 0 | 1 | 107 |
| `scrolls: scrolls_like_vim` | 63 | 203 | 1363 | 654 | 3 | 5 | 60 |
| `file: edit_like_vim` | 6 | 168 | 1288 | 819 | 0 | 0 | 0 |
| `bs: bs_like_vim` | 12 | 69 | 1230 | 783 | 0 | 1 | 19 |
| `ops: ops_cmds` | 26 | 56 | 1199 | 958 | 0 | 5 | 34 |
| `100k: nav_and_save 100k` | 1 | 15 | 1176 | 686 | 0 | 0 | 0 |
| `100k: write_continue 100k` | 3 | 15 | 1144 | 771 | 0 | 0 | 0 |
| `marks: marks_like_vim` | 53 | 290 | 1003 | 899 | 0 | 0 | 0 |
| `40k: write_continue 40k` | 3 | 15 | 913 | 777 | 0 | 0 | 0 |
| `goto: goto_like_vim` | 29 | 92 | 863 | 621 | 0 | 0 | 0 |
| `find: find_like_vim` | 45 | 169 | 859 | 768 | 0 | 1 | 19 |
| `hml: hml_like_vim` | 30 | 329 | 834 | 677 | 0 | 1 | 6 |
| `2k: write_continue 2k` | 3 | 15 | 764 | 761 | 0 | 0 | 0 |
| `rdwr: rdwr_cmds` | 6 | 77 | 669 | 904 | 3 | 3 | 66 |
| `srch: srch_cmds` | 1 | 16 | 601 | 537 | 0 | 0 | 0 |
| `arg: plus_like_vim` | 31 | 76 | 540 | 594 | 5 | 2 | 12 |
| `rdwr: rdwr_like_vim` | 12 | 51 | 525 | 831 | 0 | 1 | 24 |
| `lnum: lnum_cmds` | 2 | 37 | 505 | 881 | 0 | 0 | 0 |
| `40k: nav_and_save 40k` | 1 | 15 | 470 | 691 | 0 | 1 | 470 |
| `undo: undo_cmds` | 14 | 16 | 444 | 810 | 1 | 1 | 108 |
| `jk: jk_like_vim` | 27 | 128 | 349 | 704 | 0 | 2 | 14 |
| `brk: brk_cmds` | 3 | 61 | 333 | 794 | 4 | 1 | 220 |
| `opmx: short_like_vim` | 17 | 34 | 315 | 847 | 0 | 0 | 0 |
| `subst: subst_cmds` | 6 | 41 | 313 | 740 | 2 | 3 | 22 |
| `arg: arg_cmds` | 10 | 36 | 308 | 696 | 2 | 1 | 7 |
| `100k: ndd 100k` | 3 | 8 | 271 | 673 | 0 | 0 | 0 |
| `100k: insert_bs 100k` | 3 | 6 | 231 | 746 | 0 | 0 | 0 |
| `100k: edit_deep 100k` | 3 | 4 | 177 | 703 | 0 | 0 | 0 |
| `ctrlg: ctrlg_like_vim` | 9 | 37 | 177 | 643 | 1 | 2 | 14 |
| `opmx: col1_like_vim` | 9 | 18 | 169 | 799 | 0 | 1 | 19 |
| `40k: insert_bs 40k` | 3 | 6 | 143 | 748 | 0 | 0 | 0 |
| `dot: dot_cmds` | 6 | 6 | 139 | 681 | 0 | 0 | 0 |
| `100k: quit_semantics 100k` | 3 | 13 | 129 | 609 | 0 | 0 | 0 |
| `40k: ndd 40k` | 3 | 8 | 128 | 673 | 0 | 0 | 0 |
| `100k: wide_tabs 100k` | 1 | 30 | 121 | 672 | 0 | 0 | 0 |
| `ex: ex_like_vim` | 4 | 52 | 97 | 613 | 3 | 1 | 9 |
| `40k: edit_deep 40k` | 3 | 4 | 94 | 703 | 0 | 0 | 0 |
| `40k: wide_tabs 40k` | 1 | 30 | 94 | 672 | 0 | 0 | 0 |
| `srch: paint_cost` | 8 | 25 | 85 | 656 | 0 | 2 | 13 |
| `100k: hl_x_deep 100k` | 1 | 10 | 84 | 616 | 0 | 0 | 0 |
| `one: write_continue one` | 3 | 15 | 82 | 665 | 0 | 0 | 0 |
| `empty: write_continue empty` | 3 | 15 | 81 | 660 | 0 | 0 | 0 |
| `2k: wide_tabs 2k` | 1 | 30 | 73 | 688 | 0 | 0 | 0 |
| `one: wide_tabs one` | 1 | 30 | 68 | 654 | 0 | 0 | 0 |
| `40k: quit_semantics 40k` | 3 | 13 | 60 | 615 | 0 | 0 | 0 |
| `40k: hl_x_deep 40k` | 1 | 10 | 55 | 616 | 0 | 0 | 0 |
| `ctrlg: ctrlg_cmds` | 3 | 20 | 46 | 629 | 0 | 0 | 0 |
| `2k: edit_deep 2k` | 3 | 4 | 46 | 693 | 0 | 0 | 0 |
| `one: edit_deep one` | 3 | 4 | 43 | 653 | 0 | 0 | 0 |
| `2k: nav_and_save 2k` | 1 | 15 | 42 | 656 | 0 | 0 | 0 |
| `2k: insert_bs 2k` | 2 | 4 | 32 | 671 | 0 | 0 | 0 |
| `file: zz_cmds` | 3 | 14 | 32 | 617 | 0 | 1 | 6 |
| `2k: ndd 2k` | 2 | 6 | 31 | 622 | 0 | 0 | 0 |
| `one: insert_bs one` | 2 | 3 | 29 | 572 | 0 | 0 | 0 |
| `empty: insert_bs empty` | 2 | 3 | 28 | 569 | 0 | 0 | 0 |
| `2k: quit_semantics 2k` | 3 | 13 | 26 | 565 | 0 | 0 | 0 |
| `one: ndd one` | 2 | 4 | 26 | 520 | 0 | 0 | 0 |
| `one: quit_semantics one` | 3 | 13 | 24 | 548 | 0 | 0 | 0 |
| `empty: quit_semantics empty` | 3 | 13 | 23 | 540 | 0 | 1 | 9 |
| `2k: hl_x_deep 2k` | 1 | 10 | 23 | 613 | 0 | 1 | 23 |
| `one: hl_x_deep one` | 1 | 10 | 21 | 553 | 0 | 0 | 0 |
| `one: nav_and_save one` | 1 | 8 | 19 | 541 | 0 | 0 | 0 |
| `empty: ndd empty` | 1 | 2 | 18 | 444 | 0 | 0 | 0 |
| `empty: nav_and_save empty` | 1 | 2 | 18 | 422 | 0 | 0 | 0 |
| `find: find_cmds` | 1 | 4 | 7 | 418 | 0 | 1 | 7 |

## How few editors run the same code

**107 of the 1483 editors** between them run every block the whole suite runs, in **5030 of 68659 emulated seconds** (7.3 %). They are picked greedily, most new code per emulated second first.

That is a floor under the suite, not a suite: the other 1376 editors run no code of their own, but they run it on other text, at other sizes and in other orders, and that is where the bugs were.

## What file size adds

Blocks run at each size of file, and how many of them run at no other size.

| file | editors | emulated s | of the suite | blocks run | only at this size |
|---|---|---|---|---|---|
| empty | 38 | 3102 | 4.5 % | 1038 | 2 |
| under 2 K | 922 | 15995 | 23.3 % | 1544 | 41 |
| 2-24 K | 41 | 1704 | 2.5 % | 1152 | 8 |
| over 24 K | 482 | 47857 | 69.7 % | 1652 | 63 |

## The size sweeps

Five groups run the same eight functions on files of five sizes. For each function: the blocks each size runs that **no other size of the same function** runs, and what the two paging sizes run that the other does not.

| function | only at `empty` | only at `one` | only at `2k` | only at `40k` | only at `100k` | 40k not 100k | 100k not 40k |
|---|---|---|---|---|---|---|---|
| `nav_and_save` | 1 (18 s) | 0 (19 s) | 0 (42 s) | 0 (470 s) | 0 (1176 s) | 5 | 0 |
| `edit_deep` | - | 6 (43 s) | 0 (46 s) | 0 (94 s) | 0 (177 s) | 0 | 0 |
| `hl_x_deep` | - | 1 (21 s) | 6 (23 s) | 0 (55 s) | 1 (84 s) | 1 | 1 |
| `wide_tabs` | - | 1 (68 s) | 17 (73 s) | 0 (94 s) | 0 (121 s) | 0 | 0 |
| `insert_bs` | 2 (28 s) | 0 (29 s) | 4 (32 s) | 1 (143 s) | 0 (231 s) | 2 | 0 |
| `ndd` | 1 (18 s) | 0 (26 s) | 4 (31 s) | 0 (128 s) | 0 (271 s) | 0 | 0 |
| `quit_semantics` | 42 (23 s) | 1 (24 s) | 1 (26 s) | 0 (60 s) | 0 (129 s) | 6 | 0 |
| `write_continue` | 2 (81 s) | 0 (82 s) | 6 (764 s) | 0 (913 s) | 0 (1144 s) | 6 | 0 |

## The heaviest editors that run no code of their own

The twenty longest editors outside the minimal set above. Each is a candidate for a smaller file or a shorter range, never for deletion on this evidence alone: what it checks may be the text, the size or the order, which this table cannot see.

| emulated s | group | function | file bytes | keys (the first 50) |
|---|---|---|---|---|
| 2311 | `file` | `file_cmds` | 0 | `iINS0000\rINS0001\rINS0002\rINS0003\rINS0004\rINS0005\rI` |
| 2212 | `subst` | `subst_like_vim` | 109000 | `:%s/xx/Q/g\r:w\r\r\x1b\x1b:q!\r` |
| 1710 | `ins` | `ins_cmds` | 102400 | `10000GRQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ` |
| 1572 | `full` | `disk_full` | 102400 | `\r\x1b\x1b:q!\r` |
| 1176 | `100k` | `nav_and_save 100k` | 102400 | `Ggg\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06` |
| 1044 | `file` | `file_cmds` | 102400 | `3000Gx:w b:copy.txt\r\x07Gdd:w b:copy.txt\r:w\r:q\r\r` |
| 918 | `after` | `after_cmds` | 102400 | `3600G2l/003100\rx\x07j\x07.\x072x\x07\x0c3620G2l/012000\rx\x07j\x07.\x072x\x07\x0c` |
| 606 | `100k` | `write_continue 100k` | 102400 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 601 | `srch` | `srch_cmds` | 102400 | `6000G/zzzz\r\x07\x0c6000G?zzzz\r\x07\x0c100G/zzzz\r\x07\x0c12700G?zzzz\r` |
| 468 | `100k` | `write_continue 100k` | 102400 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 457 | `40k` | `write_continue 40k` | 40960 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 442 | `mot` | `mot_like_vim` | 100650 | `99999wb99999B` |
| 412 | `40k` | `write_continue 40k` | 40960 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 392 | `lnum` | `lnum_cmds` | 102400 | `6000G6100G5900G6000Gd6500G\x073000G\x07G\x0712200G6000G300d` |
| 378 | `2k` | `write_continue 2k` | 2048 | `250jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS0004` |
| 367 | `2k` | `write_continue 2k` | 2048 | `250jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS0004` |
| 356 | `after` | `after_cmds` | 102400 | `3360G2lGx\x07j\x07.\x072x\x07\x0c3380G2lggx\x07j\x07.\x072x\x07\x0c3400G2l9000Gx` |
| 348 | `subst` | `subst_like_vim` | 102400 | `:%s/0/ZZ/\r:w\r\r\x1b\x1b:q!\r` |
| 329 | `subst` | `subst_like_vim` | 102400 | `:%s/0/Z/\r:w\r\r\x1b\x1b:q!\r` |
| 319 | `file` | `edit_like_vim` | 102400 | `3000G:e\rG:e\r5G:e\r12G:e\r13G:e\r23G:e\r40G:e\r12790G:e\r` |

## Operator x motion x paging

Every time an operator met a motion in the editor (`OPPEND`), read out of the editor itself: the operator, the key after it, and whether the window paged before the next key was read. Each cell is the number of times it happened in the whole suite; **0** is a cell no test enters, `-` a pair the editor does not accept (`c` takes no linewise motion, `y` takes only linewise ones), and `.` a motion that cannot leave the window, so cannot page. A "paged" cell can stay at 0 with a test on it: a charwise span the window does not hold is refused before the window moves (`pgop` checks the refusals).

| motion | `d` | `d` paged | `c` | `c` paged | `y` | `y` paged |
|---|---|---|---|---|---|---|
| `w` | 87 | 1 | 60 | 1 | - | - |
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
| `'`{a-c} | 33 | 2 | - | - | 21 | **0** |
| `dd` `yy` | 143 | 8 | - | - | 45 | 12 |

Operator and key pairs that are NOT motions (the operator is dropped) and how often the suite typed one: `c%` 1, `cc` 1, `cq` 1, `cz` 1, `d%` 1, `dz` 3, `yz` 1.

## The stack

The stack is 128 bytes with the image directly below it. It is filled before each editor starts and read when the editor is done; the deepest any test took it is **66 bytes**. The five deepest:

| bytes used | group | function | keys (the first 60) |
|---|---|---|---|
| 66 | `dot` | `dot_like_vim` | `0dw..:w\r\r\x1b\x1b:q!\r` |
| 66 | `dot` | `dot_like_vim` | `0dwj.:w\r\r\x1b\x1b:q!\r` |
| 66 | `dot` | `dot_like_vim` | `3000Gdw.:w\r\r\x1b\x1b:q!\r` |
| 66 | `find` | `find_like_vim` | `2Gdfa.:w\r\r\x1b\x1b:q!\r` |
| 66 | `marks` | `marks_cmds` | `3Gmaggd'a.` |

## Code no test runs

82 blocks, 409 bytes. Listed under the label above each, with the first instruction of the block; several blocks under one label are listed once with a count.

### SCRN.MAC -- 1 blocks, 2 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `RDB_LP` | 1 | 2 | `STC` |

### CMD.MAC -- 7 blocks, 35 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `UCL_BK` | 1 | 2 | `DCX H` |
| `COL` | 1 | 9 | `PUSH H` |
| `CLASSF` | 1 | 3 | `JMP CLS2` |
| `NXLN` | 1 | 3 | `DCX H` |
| `OPG_PG` | 1 | 13 | `DCX H` |
| `OPA_F` | 1 | 4 | `XCHG` |
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

### PAGE.MAC -- 9 blocks, 54 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `SAVEFIL` | 2 | 26 | `CALL SAVCLO` |
| `SKMORE` | 1 | 10 | `LHLD TXTBEG` |
| `WRCLP` | 1 | 3 | `JMP DSKERR` |
| `FILLBF2` | 1 | 3 | `JMP POPRET` |
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

