# What the acceptance tests reach

Written by `python3 covmap.py --write`; do not edit. Measured on a `VI.COM` of 18560 bytes by running `accept_vi.py` unchanged with a recorder in the simulator driver (`covmap.py` says how).

The suite started **1019 editors** and made **4740 checks** in **88757 emulated seconds**. `VI.COM` has **1750 basic blocks** of code (16993 bytes); the suite ran **1650** of them (94.3 %, 16468 bytes).

A block that ran is not a block that is tested: every bug in issue #3 was in code the suite ran on every pass, reached in a state no test put it in. So this table can show a test is NOT looking somewhere, and that two tests walk the same code; it cannot show that either of them is enough. The operator table below is the other half -- states, not code.

## Groups

"only here" is code no other group runs: what would go unrun if the group were dropped.

| group | editors | checks | emulated s | of the suite | blocks run | only here | bytes only here |
|---|---|---|---|---|---|---|---|
| `ops` | 95 | 285 | 9483 | 10.7 % | 1014 | 1 | 2 |
| `subst` | 43 | 125 | 7000 | 7.9 % | 829 | 3 | 36 |
| `marks` | 148 | 506 | 6466 | 7.3 % | 1187 | 4 | 28 |
| `srch` | 58 | 209 | 6239 | 7.0 % | 838 | 8 | 51 |
| `ins` | 44 | 156 | 5880 | 6.6 % | 804 | 9 | 106 |
| `file` | 25 | 346 | 5545 | 6.2 % | 991 | 15 | 119 |
| `pgop` | 43 | 122 | 5537 | 6.2 % | 913 | 3 | 24 |
| `undo` | 51 | 174 | 5023 | 5.7 % | 1037 | 2 | 18 |
| `dot` | 37 | 145 | 3926 | 4.4 % | 1030 | 6 | 43 |
| `put` | 40 | 145 | 3901 | 4.4 % | 795 | 1 | 8 |
| `100k` | 18 | 101 | 3760 | 4.2 % | 887 | 0 | 0 |
| `find` | 46 | 173 | 3553 | 4.0 % | 764 | 33 | 293 |
| `ndd` | 19 | 85 | 2667 | 3.0 % | 703 | 0 | 0 |
| `40k` | 18 | 101 | 2372 | 2.7 % | 892 | 0 | 0 |
| `rdwr` | 18 | 128 | 2181 | 2.5 % | 934 | 29 | 282 |
| `bs` | 12 | 69 | 1955 | 2.2 % | 773 | 0 | 0 |
| `qfull` | 10 | 46 | 1883 | 2.1 % | 823 | 7 | 58 |
| `mot` | 37 | 514 | 1712 | 1.9 % | 724 | 23 | 145 |
| `full` | 4 | 20 | 1658 | 1.9 % | 659 | 7 | 67 |
| `scrolls` | 63 | 203 | 1361 | 1.5 % | 652 | 6 | 59 |
| `2k` | 16 | 97 | 1340 | 1.5 % | 864 | 0 | 0 |
| `arg` | 41 | 112 | 1022 | 1.2 % | 779 | 18 | 122 |
| `goto` | 29 | 92 | 863 | 1.0 % | 619 | 0 | 0 |
| `hml` | 30 | 329 | 833 | 0.9 % | 670 | 0 | 0 |
| `one` | 16 | 87 | 612 | 0.7 % | 776 | 0 | 0 |
| `lnum` | 2 | 37 | 565 | 0.6 % | 867 | 0 | 0 |
| `brk` | 3 | 61 | 395 | 0.4 % | 789 | 4 | 31 |
| `empty` | 10 | 35 | 359 | 0.4 % | 711 | 0 | 0 |
| `jk` | 27 | 128 | 348 | 0.4 % | 691 | 0 | 0 |
| `ctrlg` | 12 | 57 | 222 | 0.3 % | 818 | 1 | 10 |
| `ex` | 4 | 52 | 97 | 0.1 % | 608 | 5 | 47 |

## Test functions

The same, per function `main()` calls. "needed" is how many of its editors a minimal set keeps -- see the next section.

| function | editors | checks | emulated s | blocks run | only here | needed | their emulated s |
|---|---|---|---|---|---|---|---|
| `ops: ops_like_vim` | 69 | 229 | 7504 | 914 | 0 | 3 | 220 |
| `subst: subst_like_vim` | 37 | 84 | 6687 | 762 | 0 | 0 | 0 |
| `srch: srch_like_vim` | 49 | 168 | 5553 | 667 | 7 | 3 | 253 |
| `pgop: pgop_cmds` | 43 | 122 | 5537 | 913 | 3 | 3 | 372 |
| `marks: marks_like_vim` | 53 | 290 | 4427 | 877 | 1 | 1 | 79 |
| `file: file_cmds` | 16 | 164 | 4225 | 858 | 13 | 5 | 380 |
| `put: put_like_vim` | 40 | 145 | 3901 | 795 | 1 | 2 | 90 |
| `undo: undo_like_vim` | 37 | 158 | 3752 | 1009 | 1 | 1 | 120 |
| `find: find_like_vim` | 45 | 169 | 3546 | 757 | 23 | 5 | 392 |
| `ins: ins_like_vim` | 31 | 137 | 3519 | 772 | 1 | 2 | 219 |
| `dot: dot_like_vim` | 31 | 139 | 3436 | 1026 | 6 | 2 | 239 |
| `ndd: ndd_like_vim` | 19 | 85 | 2667 | 703 | 0 | 0 | 0 |
| `ins: ins_cmds` | 13 | 19 | 2361 | 784 | 2 | 6 | 112 |
| `marks: marks_cmds` | 95 | 216 | 2039 | 1153 | 2 | 16 | 213 |
| `ops: ops_cmds` | 26 | 56 | 1978 | 964 | 1 | 5 | 34 |
| `bs: bs_like_vim` | 12 | 69 | 1955 | 773 | 0 | 1 | 80 |
| `qfull: qfull_cmds` | 10 | 46 | 1883 | 823 | 7 | 3 | 532 |
| `mot: mot_like_vim` | 37 | 514 | 1712 | 724 | 23 | 6 | 44 |
| `full: disk_full` | 4 | 20 | 1658 | 659 | 7 | 2 | 36 |
| `scrolls: scrolls_like_vim` | 63 | 203 | 1361 | 652 | 6 | 5 | 58 |
| `file: edit_like_vim` | 6 | 168 | 1288 | 812 | 0 | 0 | 0 |
| `undo: undo_cmds` | 14 | 16 | 1271 | 801 | 1 | 1 | 169 |
| `rdwr: rdwr_like_vim` | 12 | 51 | 1264 | 823 | 0 | 1 | 87 |
| `100k: nav_and_save 100k` | 1 | 15 | 1239 | 685 | 0 | 0 | 0 |
| `100k: write_continue 100k` | 3 | 15 | 1143 | 764 | 0 | 0 | 0 |
| `rdwr: rdwr_cmds` | 6 | 77 | 917 | 900 | 3 | 2 | 121 |
| `40k: write_continue 40k` | 3 | 15 | 913 | 770 | 0 | 0 | 0 |
| `goto: goto_like_vim` | 29 | 92 | 863 | 619 | 0 | 1 | 9 |
| `hml: hml_like_vim` | 30 | 329 | 833 | 670 | 0 | 1 | 6 |
| `2k: write_continue 2k` | 3 | 15 | 763 | 754 | 0 | 0 | 0 |
| `srch: srch_cmds` | 1 | 16 | 601 | 537 | 0 | 0 | 0 |
| `lnum: lnum_cmds` | 2 | 37 | 565 | 867 | 0 | 0 | 0 |
| `arg: plus_like_vim` | 31 | 76 | 540 | 595 | 5 | 2 | 12 |
| `40k: nav_and_save 40k` | 1 | 15 | 536 | 690 | 0 | 1 | 536 |
| `dot: dot_cmds` | 6 | 6 | 490 | 676 | 0 | 0 | 0 |
| `arg: arg_cmds` | 10 | 36 | 483 | 692 | 3 | 1 | 7 |
| `brk: brk_cmds` | 3 | 61 | 395 | 789 | 4 | 1 | 222 |
| `100k: ndd 100k` | 3 | 8 | 393 | 668 | 0 | 0 | 0 |
| `100k: insert_bs 100k` | 3 | 6 | 354 | 741 | 0 | 0 | 0 |
| `jk: jk_like_vim` | 27 | 128 | 348 | 691 | 0 | 2 | 13 |
| `subst: subst_cmds` | 6 | 41 | 313 | 731 | 2 | 3 | 22 |
| `100k: edit_deep 100k` | 3 | 4 | 297 | 697 | 0 | 0 | 0 |
| `40k: insert_bs 40k` | 3 | 6 | 263 | 743 | 0 | 0 | 0 |
| `40k: ndd 40k` | 3 | 8 | 242 | 668 | 0 | 0 | 0 |
| `40k: edit_deep 40k` | 3 | 4 | 209 | 697 | 0 | 0 | 0 |
| `ctrlg: ctrlg_like_vim` | 9 | 37 | 177 | 630 | 1 | 1 | 8 |
| `2k: edit_deep 2k` | 3 | 4 | 166 | 687 | 0 | 0 | 0 |
| `one: edit_deep one` | 3 | 4 | 160 | 647 | 0 | 0 | 0 |
| `100k: quit_semantics 100k` | 3 | 13 | 129 | 603 | 0 | 0 | 0 |
| `100k: wide_tabs 100k` | 1 | 30 | 121 | 662 | 0 | 0 | 0 |
| `2k: nav_and_save 2k` | 1 | 15 | 102 | 655 | 0 | 0 | 0 |
| `ex: ex_like_vim` | 4 | 52 | 97 | 608 | 5 | 1 | 9 |
| `2k: insert_bs 2k` | 2 | 4 | 95 | 666 | 0 | 0 | 0 |
| `40k: wide_tabs 40k` | 1 | 30 | 94 | 662 | 0 | 0 | 0 |
| `2k: ndd 2k` | 2 | 6 | 91 | 618 | 0 | 0 | 0 |
| `empty: ndd empty` | 1 | 2 | 91 | 444 | 0 | 0 | 0 |
| `one: ndd one` | 2 | 4 | 90 | 520 | 0 | 0 | 0 |
| `one: insert_bs one` | 2 | 3 | 89 | 568 | 0 | 0 | 0 |
| `empty: insert_bs empty` | 2 | 3 | 89 | 565 | 0 | 1 | 8 |
| `srch: paint_cost` | 8 | 25 | 85 | 652 | 0 | 2 | 13 |
| `100k: hl_x_deep 100k` | 1 | 10 | 84 | 606 | 0 | 0 | 0 |
| `one: write_continue one` | 3 | 15 | 81 | 659 | 0 | 0 | 0 |
| `empty: write_continue empty` | 3 | 15 | 81 | 654 | 0 | 0 | 0 |
| `one: nav_and_save one` | 1 | 8 | 80 | 541 | 0 | 0 | 0 |
| `empty: nav_and_save empty` | 1 | 2 | 75 | 422 | 0 | 0 | 0 |
| `2k: wide_tabs 2k` | 1 | 30 | 73 | 678 | 0 | 0 | 0 |
| `one: wide_tabs one` | 1 | 30 | 67 | 644 | 0 | 1 | 67 |
| `40k: quit_semantics 40k` | 3 | 13 | 60 | 609 | 0 | 1 | 45 |
| `40k: hl_x_deep 40k` | 1 | 10 | 55 | 606 | 0 | 0 | 0 |
| `ctrlg: ctrlg_cmds` | 3 | 20 | 46 | 624 | 0 | 0 | 0 |
| `file: zz_cmds` | 3 | 14 | 32 | 613 | 0 | 1 | 6 |
| `2k: quit_semantics 2k` | 3 | 13 | 26 | 559 | 0 | 0 | 0 |
| `one: quit_semantics one` | 3 | 13 | 24 | 542 | 0 | 0 | 0 |
| `empty: quit_semantics empty` | 3 | 13 | 23 | 534 | 0 | 1 | 9 |
| `2k: hl_x_deep 2k` | 1 | 10 | 23 | 603 | 0 | 1 | 23 |
| `one: hl_x_deep one` | 1 | 10 | 20 | 543 | 0 | 0 | 0 |
| `find: find_cmds` | 1 | 4 | 7 | 417 | 0 | 1 | 7 |

## How few editors run the same code

**98 of the 1019 editors** between them run every block the whole suite runs, in **4872 of 88757 emulated seconds** (5.5 %). They are picked greedily, most new code per emulated second first.

That is a floor under the suite, not a suite: the other 921 editors run no code of their own, but they run it on other text, at other sizes and in other orders, and that is where the bugs were.

## What file size adds

Blocks run at each size of file, and how many of them run at no other size.

| file | editors | emulated s | of the suite | blocks run | only at this size |
|---|---|---|---|---|---|
| empty | 38 | 3958 | 4.5 % | 1027 | 2 |
| under 2 K | 506 | 28353 | 31.9 % | 1489 | 66 |
| 2-24 K | 26 | 1533 | 1.7 % | 1020 | 4 |
| over 24 K | 449 | 54913 | 61.9 % | 1570 | 84 |

## Operator x motion x paging

Every time an operator met a motion in the editor (`OPPEND`), read out of the editor itself: the operator, the key after it, and whether the window paged before the next key was read. Each cell is the number of times it happened in the whole suite; **0** is a cell no test enters, `-` a pair the editor does not accept (`c` takes no linewise motion, `y` takes only linewise ones), and `.` a motion that cannot leave the window, so cannot page.

| motion | `d` | `d` paged | `c` | `c` paged | `y` | `y` paged |
|---|---|---|---|---|---|---|
| `w` | 25 | **0** | 16 | **0** | - | - |
| `W` | **0** | **0** | **0** | **0** | - | - |
| `b` | **0** | **0** | **0** | **0** | - | - |
| `B` | **0** | **0** | **0** | **0** | - | - |
| `h` | **0** | . | **0** | . | - | - |
| `l` | **0** | . | **0** | . | - | - |
| `0` | **0** | . | **0** | . | - | - |
| `^` | **0** | . | **0** | . | - | - |
| `` ` ``{a-c} | 11 | **0** | 3 | **0** | - | - |
| `f` | 5 | . | 1 | . | - | - |
| `t` | 1 | . | 1 | . | - | - |
| `F` | 1 | . | **0** | . | - | - |
| `T` | 1 | . | **0** | . | - | - |
| `;` | 3 | . | 1 | . | - | - |
| `,` | 2 | . | 1 | . | - | - |
| `e` | **0** | **0** | **0** | **0** | - | - |
| `E` | **0** | **0** | **0** | **0** | - | - |
| `$` | **0** | **0** | **0** | **0** | - | - |
| `j` | **0** | 2 | - | - | 2 | **0** |
| `k` | 1 | 1 | - | - | 2 | **0** |
| `G` | 10 | 13 | - | - | 3 | 1 |
| `H` | **0** | . | - | - | 1 | . |
| `M` | **0** | . | - | - | **0** | . |
| `L` | **0** | . | - | - | 1 | . |
| `gg` | 5 | 3 | - | - | 1 | 1 |
| `'`{a-c} | 14 | 2 | - | - | 13 | **0** |
| `dd` `yy` | 120 | 7 | - | - | 42 | 7 |

Operator and key pairs that are NOT motions (the operator is dropped) and how often the suite typed one: `c%` 1, `cc` 1, `cq` 1, `d%` 1.

## The stack

The stack is 128 bytes with the image directly below it. It is filled before each editor starts and read when the editor is done; the deepest any test took it is **66 bytes**. The five deepest:

| bytes used | group | function | keys (the first 60) |
|---|---|---|---|
| 66 | `dot` | `dot_like_vim` | `0dw..:w\r\r\x1b\x1b:q!\r` |
| 66 | `dot` | `dot_like_vim` | `0dwj.:w\r\r\x1b\x1b:q!\r` |
| 66 | `dot` | `dot_like_vim` | `3000Gdw.:w\r\r\x1b\x1b:q!\r` |
| 66 | `dot` | `dot_like_vim` | `0cwZZZ\x1b.:w\r\r\x1b\x1b:q!\r` |
| 66 | `find` | `find_like_vim` | `2Gdfa.:w\r\r\x1b\x1b:q!\r` |

## Code no test runs

100 blocks, 525 bytes. Listed under the label above each, with the first instruction of the block; several blocks under one label are listed once with a count.

### SCRN.MAC -- 3 blocks, 6 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `RDB_LP` | 1 | 2 | `STC` |
| `CLP_MIN` | 1 | 2 | `MOV A,B` |
| `CLP_MAX` | 1 | 2 | `MOV A,C` |

### CMD.MAC -- 19 blocks, 132 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `UCL_BK` | 1 | 2 | `DCX H` |
| `SG_LP` | 1 | 4 | `INR D` |
| `COL` | 1 | 9 | `PUSH H` |
| `CLASSF` | 1 | 3 | `JMP CLS2` |
| `NXLN` | 1 | 3 | `DCX H` |
| `VCBGE` | 1 | 5 | `MVI A,1` |
| `ES_CL` | 2 | 10 | `LHLD WKN` |
| `OPG_PG` | 1 | 13 | `DCX H` |
| `OPC_EXC` | 1 | 2 | `XRA A` |
| `OPY_LO` | 1 | 6 | `LXI H,YSPAN` |
| `YSPAN` | 1 | 44 | `CALL GLSTAL` |
| `YS_LP` | 2 | 16 | `CALL LOGLEN` |
| `YS_END` | 1 | 3 | `JMP MARKMOD` |
| `YNROOM` | 2 | 5 | `JZ YNR_OK` |
| `AS_TOK` | 1 | 1 | `RET` |
| `AS_POV` | 1 | 6 | `LXI D,PLUSB` |

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

### PAGE.MAC -- 11 blocks, 63 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `SAVEFIL` | 2 | 26 | `CALL SAVCLO` |
| `SKMORE` | 1 | 10 | `LHLD TXTBEG` |
| `WRCLP` | 1 | 3 | `JMP DSKERR` |
| `MEMSHT` | 1 | 3 | `CALL ERRMSG` |
| `MKROOM` | 1 | 3 | `JMP SPILLB` |
| `PBBAK` | 1 | 6 | `CALL RECINC` |
| `FATAL` | 1 | 3 | `JMP ERRMSG` |
| `CLOSEF` | 1 | 3 | `CALL FATAL` |
| `DIRFUL` | 1 | 3 | `CALL FATAL` |
| `RENF` | 1 | 3 | `CALL FATAL` |

### BUF.MAC -- 32 blocks, 134 bytes

| label | blocks | bytes | first unrun instruction |
|---|---|---|---|
| `INSCNT` | 1 | 6 | `MOV C,A` |
| `MKGAPL` | 1 | 3 | `CALL ERRMSG` |
| `QROOM` | 1 | 3 | `CALL ERRMSG` |
| `PEEKLX` | 1 | 3 | `INX SP` |
| `LINEPOS` | 1 | 3 | `POP PSW` |
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

