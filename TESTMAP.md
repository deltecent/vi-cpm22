# What the acceptance tests reach

Written by `python3 covmap.py --write`; do not edit. Measured on a `VI.COM` of 20608 bytes by running `accept_vi.py` unchanged with a recorder in the simulator driver (`covmap.py` says how).

The suite started **1573 editors** and made **9260 checks** in **68557 emulated seconds**. `VI.COM` has **1947 basic blocks** of code (19012 bytes); the suite ran **1894** of them (97.3 %, 18769 bytes).

A block that ran is not a block that is tested: every bug in issue #3 was in code the suite ran on every pass, reached in a state no test put it in. So this table can show a test is NOT looking somewhere, and that two tests walk the same code; it cannot show that either of them is enough. The operator table below is the other half -- states, not code.

## Groups

"only here" is code no other group runs: what would go unrun if the group were dropped.

| group | editors | checks | emulated s | of the suite | blocks run | only here | bytes only here |
|---|---|---|---|---|---|---|---|
| `pgop` | 65 | 182 | 5040 | 7.4 % | 1233 | 8 | 86 |
| `opmx` | 245 | 1227 | 4978 | 7.3 % | 1196 | 3 | 23 |
| `undo` | 193 | 801 | 4868 | 7.1 % | 1313 | 1 | 7 |
| `subst` | 43 | 125 | 4599 | 6.7 % | 934 | 2 | 12 |
| `file` | 25 | 346 | 4591 | 6.7 % | 1149 | 14 | 112 |
| `ops` | 95 | 285 | 4445 | 6.5 % | 1119 | 0 | 0 |
| `marks` | 148 | 506 | 3084 | 4.5 % | 1318 | 0 | 0 |
| `srch` | 58 | 209 | 2919 | 4.3 % | 962 | 0 | 0 |
| `100k` | 18 | 101 | 2888 | 4.2 % | 1034 | 0 | 0 |
| `wrap` | 49 | 1447 | 2856 | 4.2 % | 1362 | 7 | 76 |
| `ins` | 44 | 156 | 2204 | 3.2 % | 930 | 3 | 33 |
| `after` | 21 | 792 | 2196 | 3.2 % | 1561 | 2 | 9 |
| `dot` | 37 | 145 | 1725 | 2.5 % | 1152 | 0 | 0 |
| `mot` | 37 | 514 | 1701 | 2.5 % | 850 | 1 | 2 |
| `40k` | 18 | 101 | 1647 | 2.4 % | 1039 | 0 | 0 |
| `scrolls` | 63 | 203 | 1588 | 2.3 % | 835 | 1 | 4 |
| `full` | 4 | 20 | 1563 | 2.3 % | 736 | 6 | 50 |
| `ndd` | 19 | 85 | 1444 | 2.1 % | 849 | 0 | 0 |
| `put` | 40 | 145 | 1388 | 2.0 % | 897 | 1 | 8 |
| `qfull` | 10 | 46 | 1347 | 2.0 % | 919 | 0 | 0 |
| `bs` | 12 | 69 | 1258 | 1.8 % | 906 | 0 | 0 |
| `cell` | 1 | 235 | 1243 | 1.8 % | 814 | 0 | 0 |
| `rdwr` | 18 | 128 | 1197 | 1.7 % | 1045 | 7 | 59 |
| `limits` | 36 | 80 | 1180 | 1.7 % | 1118 | 4 | 13 |
| `goto` | 29 | 92 | 896 | 1.3 % | 766 | 0 | 0 |
| `find` | 46 | 173 | 878 | 1.3 % | 864 | 0 | 0 |
| `arg` | 41 | 112 | 857 | 1.3 % | 905 | 7 | 41 |
| `hml` | 30 | 329 | 852 | 1.2 % | 830 | 0 | 0 |
| `2k` | 16 | 97 | 735 | 1.1 % | 1017 | 0 | 0 |
| `lnum` | 2 | 37 | 502 | 0.7 % | 967 | 0 | 0 |
| `brk` | 7 | 79 | 443 | 0.6 % | 1000 | 4 | 31 |
| `jk` | 27 | 128 | 372 | 0.5 % | 829 | 0 | 0 |
| `one` | 16 | 87 | 308 | 0.4 % | 893 | 0 | 0 |
| `resp` | 34 | 34 | 279 | 0.4 % | 701 | 0 | 0 |
| `ctrlg` | 12 | 57 | 220 | 0.3 % | 934 | 1 | 10 |
| `empty` | 10 | 35 | 170 | 0.2 % | 820 | 0 | 0 |
| `ex` | 4 | 52 | 95 | 0.1 % | 749 | 3 | 30 |

## Test functions

The same, per function `main()` calls. "needed" is how many of its editors a minimal set keeps -- see the next section.

| function | editors | checks | emulated s | blocks run | only here | needed | their emulated s |
|---|---|---|---|---|---|---|---|
| `pgop: pgop_cmds` | 65 | 182 | 5040 | 1233 | 8 | 6 | 469 |
| `subst: subst_like_vim` | 37 | 84 | 4286 | 873 | 0 | 0 | 0 |
| `ops: ops_like_vim` | 69 | 229 | 3311 | 1026 | 0 | 1 | 19 |
| `file: file_cmds` | 16 | 164 | 3245 | 971 | 13 | 6 | 299 |
| `undo: undo_at_vim` | 142 | 627 | 2805 | 1126 | 0 | 2 | 29 |
| `opmx: opmx_like_vim` | 127 | 991 | 2745 | 1187 | 2 | 4 | 83 |
| `wrap: wrap_like_vim` | 41 | 1113 | 2334 | 1011 | 4 | 5 | 196 |
| `srch: srch_like_vim` | 49 | 168 | 2244 | 794 | 0 | 1 | 18 |
| `after: after_cmds` | 21 | 792 | 2196 | 1561 | 2 | 5 | 371 |
| `marks: marks_cmds` | 95 | 216 | 2069 | 1287 | 0 | 11 | 79 |
| `opmx: word_like_vim` | 92 | 184 | 1743 | 997 | 1 | 1 | 19 |
| `mot: mot_like_vim` | 37 | 514 | 1701 | 850 | 1 | 5 | 43 |
| `undo: undo_like_vim` | 37 | 158 | 1618 | 1140 | 0 | 1 | 19 |
| `dot: dot_like_vim` | 31 | 139 | 1592 | 1144 | 0 | 1 | 63 |
| `scrolls: scrolls_like_vim` | 63 | 203 | 1588 | 835 | 1 | 6 | 95 |
| `full: disk_full` | 4 | 20 | 1563 | 736 | 6 | 2 | 35 |
| `ins: ins_like_vim` | 31 | 137 | 1490 | 895 | 1 | 3 | 105 |
| `ndd: ndd_like_vim` | 19 | 85 | 1444 | 849 | 0 | 0 | 0 |
| `put: put_like_vim` | 40 | 145 | 1388 | 897 | 1 | 3 | 44 |
| `qfull: qfull_cmds` | 10 | 46 | 1347 | 919 | 0 | 1 | 104 |
| `file: edit_like_vim` | 6 | 168 | 1313 | 968 | 0 | 0 | 0 |
| `bs: bs_like_vim` | 12 | 69 | 1258 | 906 | 0 | 0 | 0 |
| `cell: cell_paint` | 1 | 235 | 1243 | 814 | 0 | 0 | 0 |
| `limits: limits_cmds` | 36 | 80 | 1180 | 1118 | 4 | 5 | 79 |
| `ops: ops_cmds` | 26 | 56 | 1134 | 1047 | 0 | 4 | 27 |
| `marks: marks_like_vim` | 53 | 290 | 1014 | 993 | 0 | 0 | 0 |
| `100k: nav_and_save 100k` | 1 | 15 | 986 | 822 | 0 | 0 | 0 |
| `goto: goto_like_vim` | 29 | 92 | 896 | 766 | 0 | 0 | 0 |
| `100k: write_continue 100k` | 3 | 15 | 883 | 867 | 0 | 0 | 0 |
| `find: find_like_vim` | 45 | 169 | 871 | 857 | 0 | 2 | 39 |
| `hml: hml_like_vim` | 30 | 329 | 852 | 830 | 0 | 1 | 7 |
| `ins: ins_cmds` | 13 | 19 | 714 | 904 | 2 | 4 | 38 |
| `rdwr: rdwr_cmds` | 6 | 77 | 673 | 1005 | 3 | 2 | 46 |
| `40k: write_continue 40k` | 3 | 15 | 652 | 873 | 0 | 0 | 0 |
| `srch: srch_cmds` | 1 | 16 | 592 | 625 | 0 | 0 | 0 |
| `arg: plus_like_vim` | 31 | 76 | 548 | 712 | 5 | 2 | 12 |
| `rdwr: rdwr_like_vim` | 12 | 51 | 523 | 934 | 0 | 1 | 24 |
| `lnum: lnum_cmds` | 2 | 37 | 502 | 967 | 0 | 0 | 0 |
| `2k: write_continue 2k` | 3 | 15 | 469 | 865 | 0 | 0 | 0 |
| `undo: undo_cmds` | 14 | 16 | 445 | 921 | 1 | 1 | 115 |
| `brk: brk_cmds` | 7 | 79 | 443 | 1000 | 4 | 1 | 248 |
| `40k: nav_and_save 40k` | 1 | 15 | 399 | 827 | 0 | 0 | 0 |
| `wrap: wrap_paint` | 5 | 264 | 392 | 1009 | 0 | 1 | 42 |
| `jk: jk_like_vim` | 27 | 128 | 372 | 829 | 0 | 3 | 36 |
| `opmx: short_like_vim` | 17 | 34 | 319 | 937 | 0 | 0 | 0 |
| `subst: subst_cmds` | 6 | 41 | 313 | 829 | 2 | 3 | 23 |
| `arg: arg_cmds` | 10 | 36 | 310 | 795 | 2 | 1 | 7 |
| `resp: resp_cmds` | 34 | 34 | 279 | 701 | 0 | 2 | 17 |
| `100k: ndd 100k` | 3 | 8 | 274 | 769 | 0 | 0 | 0 |
| `100k: insert_bs 100k` | 3 | 6 | 233 | 845 | 0 | 0 | 0 |
| `100k: edit_deep 100k` | 3 | 4 | 184 | 805 | 0 | 0 | 0 |
| `ctrlg: ctrlg_like_vim` | 9 | 37 | 174 | 741 | 1 | 2 | 14 |
| `opmx: col1_like_vim` | 9 | 18 | 171 | 875 | 0 | 1 | 19 |
| `40k: insert_bs 40k` | 3 | 6 | 145 | 847 | 0 | 0 | 0 |
| `40k: ndd 40k` | 3 | 8 | 144 | 768 | 0 | 0 | 0 |
| `dot: dot_cmds` | 6 | 6 | 133 | 782 | 0 | 0 | 0 |
| `wrap: wrap_cmds` | 3 | 70 | 130 | 1016 | 1 | 1 | 82 |
| `100k: quit_semantics 100k` | 3 | 13 | 128 | 708 | 0 | 0 | 0 |
| `100k: wide_tabs 100k` | 1 | 30 | 117 | 781 | 0 | 0 | 0 |
| `40k: edit_deep 40k` | 3 | 4 | 95 | 805 | 0 | 0 | 0 |
| `ex: ex_like_vim` | 4 | 52 | 95 | 749 | 3 | 1 | 10 |
| `40k: wide_tabs 40k` | 1 | 30 | 89 | 781 | 0 | 0 | 0 |
| `srch: paint_cost` | 8 | 25 | 84 | 759 | 0 | 2 | 13 |
| `100k: hl_x_deep 100k` | 1 | 10 | 83 | 715 | 0 | 0 | 0 |
| `one: write_continue one` | 3 | 15 | 82 | 755 | 0 | 0 | 0 |
| `empty: write_continue empty` | 3 | 15 | 82 | 763 | 0 | 0 | 0 |
| `40k: quit_semantics 40k` | 3 | 13 | 68 | 714 | 0 | 0 | 0 |
| `2k: wide_tabs 2k` | 1 | 30 | 68 | 793 | 0 | 0 | 0 |
| `one: wide_tabs one` | 1 | 30 | 63 | 757 | 0 | 0 | 0 |
| `40k: hl_x_deep 40k` | 1 | 10 | 54 | 715 | 0 | 0 | 0 |
| `2k: edit_deep 2k` | 3 | 4 | 47 | 795 | 0 | 0 | 0 |
| `ctrlg: ctrlg_cmds` | 3 | 20 | 46 | 717 | 0 | 0 | 0 |
| `one: edit_deep one` | 3 | 4 | 44 | 726 | 0 | 0 | 0 |
| `2k: nav_and_save 2k` | 1 | 15 | 39 | 786 | 0 | 0 | 0 |
| `file: zz_cmds` | 3 | 14 | 32 | 691 | 0 | 1 | 6 |
| `2k: insert_bs 2k` | 2 | 4 | 32 | 766 | 0 | 0 | 0 |
| `2k: ndd 2k` | 2 | 6 | 32 | 706 | 0 | 0 | 0 |
| `one: insert_bs one` | 2 | 3 | 29 | 651 | 0 | 0 | 0 |
| `empty: insert_bs empty` | 2 | 3 | 28 | 648 | 0 | 0 | 0 |
| `2k: quit_semantics 2k` | 3 | 13 | 27 | 664 | 0 | 0 | 0 |
| `one: ndd one` | 2 | 4 | 27 | 578 | 0 | 0 | 0 |
| `one: quit_semantics one` | 3 | 13 | 24 | 634 | 0 | 0 | 0 |
| `empty: quit_semantics empty` | 3 | 13 | 24 | 603 | 0 | 0 | 0 |
| `2k: hl_x_deep 2k` | 1 | 10 | 23 | 711 | 0 | 0 | 0 |
| `one: hl_x_deep one` | 1 | 10 | 21 | 634 | 0 | 0 | 0 |
| `one: nav_and_save one` | 1 | 8 | 19 | 599 | 0 | 0 | 0 |
| `empty: ndd empty` | 1 | 2 | 18 | 497 | 0 | 0 | 0 |
| `empty: nav_and_save empty` | 1 | 2 | 18 | 475 | 0 | 0 | 0 |
| `find: find_cmds` | 1 | 4 | 7 | 490 | 0 | 1 | 7 |

## How few editors run the same code

**106 of the 1573 editors** between them run every block the whole suite runs, in **2999 of 68557 emulated seconds** (4.4 %). They are picked greedily, most new code per emulated second first.

That is a floor under the suite, not a suite: the other 1467 editors run no code of their own, but they run it on other text, at other sizes and in other orders, and that is where the bugs were.

## What file size adds

Blocks run at each size of file, and how many of them run at no other size.

| file | editors | emulated s | of the suite | blocks run | only at this size |
|---|---|---|---|---|---|
| empty | 38 | 2105 | 3.1 % | 1152 | 2 |
| under 2 K | 937 | 17636 | 25.7 % | 1707 | 41 |
| 2-24 K | 77 | 2765 | 4.0 % | 1536 | 8 |
| over 24 K | 521 | 46051 | 67.2 % | 1836 | 65 |

## The size sweeps

Five groups run the same eight functions on files of five sizes. For each function: the blocks each size runs that **no other size of the same function** runs, and what the two paging sizes run that the other does not.

| function | only at `empty` | only at `one` | only at `2k` | only at `40k` | only at `100k` | 40k not 100k | 100k not 40k |
|---|---|---|---|---|---|---|---|
| `nav_and_save` | 2 (18 s) | 0 (19 s) | 0 (39 s) | 0 (399 s) | 0 (986 s) | 5 | 0 |
| `edit_deep` | - | 7 (44 s) | 0 (47 s) | 0 (95 s) | 0 (184 s) | 0 | 0 |
| `hl_x_deep` | - | 1 (21 s) | 6 (23 s) | 0 (54 s) | 1 (83 s) | 1 | 1 |
| `wide_tabs` | - | 1 (63 s) | 18 (68 s) | 0 (89 s) | 0 (117 s) | 0 | 0 |
| `insert_bs` | 3 (28 s) | 0 (29 s) | 3 (32 s) | 1 (145 s) | 0 (233 s) | 2 | 0 |
| `ndd` | 2 (18 s) | 0 (27 s) | 4 (32 s) | 0 (144 s) | 1 (274 s) | 0 | 1 |
| `quit_semantics` | 32 (24 s) | 1 (24 s) | 1 (27 s) | 0 (68 s) | 0 (128 s) | 6 | 0 |
| `write_continue` | 3 (82 s) | 0 (82 s) | 14 (469 s) | 0 (652 s) | 0 (883 s) | 6 | 0 |

## The heaviest editors that run no code of their own

The twenty longest editors outside the minimal set above. Each is a candidate for a smaller file or a shorter range, never for deletion on this evidence alone: what it checks may be the text, the size or the order, which this table cannot see.

| emulated s | group | function | file bytes | keys (the first 50) |
|---|---|---|---|---|
| 2213 | `subst` | `subst_like_vim` | 109000 | `:%s/xx/Q/g\r:w\r\r\x1b\x1b:q!\r` |
| 1512 | `full` | `disk_full` | 102400 | `\r\x1b\x1b:q!\r` |
| 1397 | `file` | `file_cmds` | 0 | `iINS0000\rINS0001\rINS0002\rINS0003\rINS0004\rINS0005\rI` |
| 1243 | `cell` | `cell_paint` | 1073 | `2G0rZ\x0cu2G0RZYX\x1b\x0cu2G0RZY\x08\x08\x1b\x0cu2G0iZY\x08\x1b\x0cu2G0aZY\x08\x08\x1b\x0cu2` |
| 1051 | `file` | `file_cmds` | 102400 | `3000Gx:w b:copy.txt\r\x07Gdd:w b:copy.txt\r:w\r:q\r\r` |
| 986 | `100k` | `nav_and_save 100k` | 102400 | `Ggg\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06` |
| 887 | `after` | `after_cmds` | 102400 | `3600G2l/003100\rx\x07j\x07.\x072x\x07\x0c3620G2l/012000\rx\x07j\x07.\x072x\x07\x0c` |
| 592 | `srch` | `srch_cmds` | 102400 | `6000G/zzzz\r\x07\x0c6000G?zzzz\r\x07\x0c100G/zzzz\r\x07\x0c12700G?zzzz\r` |
| 475 | `100k` | `write_continue 100k` | 102400 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 441 | `mot` | `mot_like_vim` | 100650 | `99999wb99999B` |
| 399 | `40k` | `nav_and_save 40k` | 40960 | `Ggg\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06\x06` |
| 395 | `ins` | `ins_cmds` | 102400 | `10000GRQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ` |
| 390 | `lnum` | `lnum_cmds` | 102400 | `6000G6100G5900G6000Gd6500G\x073000G\x07G\x0712200G6000G300d` |
| 357 | `after` | `after_cmds` | 102400 | `3360G2lGx\x07j\x07.\x072x\x07\x0c3380G2lggx\x07j\x07.\x072x\x07\x0c3400G2l9000Gx` |
| 349 | `subst` | `subst_like_vim` | 102400 | `:%s/0/ZZ/\r:w\r\r\x1b\x1b:q!\r` |
| 336 | `100k` | `write_continue 100k` | 102400 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 336 | `subst` | `subst_like_vim` | 102400 | `:%s/0/Z/\r:w\r\r\x1b\x1b:q!\r` |
| 326 | `40k` | `write_continue 40k` | 40960 | `2994jx:w\rjxiINS0000\rINS0001\rINS0002\rINS0003\rINS000` |
| 321 | `file` | `edit_like_vim` | 102400 | `3000G:e\rG:e\r5G:e\r12G:e\r13G:e\r23G:e\r40G:e\r12790G:e\r` |
| 305 | `limits` | `limits_cmds` | 320 | `65535G\x07gg65536G\x07gg99999G\x07gg99999j\x0799999k\x075G99999l\x07` |

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

