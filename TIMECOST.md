# What a command costs on a 100 K file

Written by `python3 timecost.py --write`; do not edit. Measured on a `VI.COM` of 21888 bytes, one fresh editor per row, on a file of 12800 lines of 8 bytes.

The seconds are the simulator's emulated clock (2 MHz 8080, 9600-baud console, the BIOS's disk loops). The simulated drive has no seek time and no rotation, so **these are a floor**: a real drive adds to every row that pages and to none that does not. The message is what the bottom row said afterwards.


## Moving

| command | seconds | characters sent | message |
|---|---|---|---|
| `^F` at line 6000 | 0.4 | 274 |  |
| `^B` at line 6000 | 0.5 | 275 |  |
| `200j` at line 6000 | 1.6 | 343 |  |
| `G` from the top | 48.1 | 304 |  |
| `gg` from the end | 38.8 | 315 |  |
| `6000G` from the top | 21.8 | 352 |  |
| `6100G` from line 6000 | 0.9 | 356 |  |
| `5900G` from line 6000 | 0.9 | 356 |  |
| `100G` from line 12000 | 35.1 | 343 |  |
| `G` again, after `G` `gg` | 36.5 | 304 |  |
| `gg` from the end, after `x` there | 56.1 | 315 |  |
| `'a` to line 100 from line 6000 | 15.7 | 304 |  |
| `^G` at the end | 0.4 | 63 | "TEST.TXT" line 12800 col 1 |
| `G` from the top, ESC 10 s into it | 19.3 | 58 | Interrupted |
| `/zzzz` from line 6000, never found | 116.6 | 61 | Pattern not found: zzzz |
| `/zzzz` from line 6000, ESC 10 s into it | 27.5 | 74 | Interrupted |
| `/012000` from the top | 43.6 | 321 |  |
| `/000100` from line 6000 (wraps) | 65.7 | 321 |  |
| `?000100` from line 6000 | 15.1 | 321 |  |

## Editing at line 6000

| command | seconds | characters sent | message |
|---|---|---|---|
| `x` | 0.0 | 4 |  |
| `ihello<Esc>` | 0.3 | 109 |  |
| `dd` | 0.4 | 69 |  |
| `u` after `dd` | 0.2 | 56 |  |
| `100dd` (800 bytes) | 1.4 | 356 |  |
| `u` after `100dd` | 2.1 | 304 |  |
| `500dd` (4 K) | 4.0 | 356 |  |
| `u` after `500dd` | 0.1 | 40 | Too large to undo |
| `P` after `500dd` | 1.7 | 304 |  |
| `2000dd` (16 K) | 9.9 | 369 |  |
| `P` after `2000dd` | 16.8 | 304 |  |
| `3000dd` (24 K) | 30.0 | 409 | Too large to yank |
| `5000dd` (40 K) | 30.0 | 409 | Too large to yank |
| `60yy` | 0.4 | 52 |  |
| `500yy` (4 K) | 3.9 | 356 |  |
| `2000yy` (16 K) | 24.6 | 369 |  |
| `5000yy` (40 K) | 29.4 | 409 | Too large to yank |
| `d6500G` (4 K) | 3.0 | 369 |  |
| `u` after `d6500G` | 0.1 | 40 | Too large to undo |
| `d9000G` (24 K) | 18.1 | 369 |  |
| `d'a`, the mark at line 9000 (24 K) | 10.6 | 317 |  |
| `dG` (54 K) | 52.9 | 317 |  |
| `dgg` (48 K) | 22.2 | 315 |  |
| `yG` (54 K) | 46.0 | 318 |  |
| `u` after `dd` `G` | 0.1 | 56 | Cannot undo: change has paged out |

## Substitute

| command | seconds | characters sent | message |
|---|---|---|---|
| `:6000,6100s/0/1/` | 2.4 | 330 |  |
| `:%s/0/1/` (12800 lines) | 232.3 | 322 |  |

## Files

| command | seconds | characters sent | message |
|---|---|---|---|
| `:w`, nothing changed | 51.7 | 354 | "TEST.TXT" written |
| `:w` after `x` at the top | 51.7 | 353 | "TEST.TXT" written |
| `:w` after `x` at line 6000 | 48.2 | 356 | "TEST.TXT" written |
| `:w` after `x` at the end | 53.3 | 356 | "TEST.TXT" written |
| `:e!` after `x` at the top | 3.1 | 347 | "TEST.TXT" |
| `:e!` after `x` at line 6000 | 26.9 | 350 | "TEST.TXT" |
| `:6000,6100w T.TXT` (800 bytes) | 3.8 | 78 | "T.TXT" written |
| `:6000,9000w T.TXT` (24 K) | 30.9 | 78 | "T.TXT" written |
| `:r T.TXT` of 800 bytes, at line 3000 | 2.0 | 322 |  |
| `:r T.TXT` of 24 K, at line 3000 | 29.3 | 322 |  |

## Memory and work files

| | |
|---|---|
| BDOS entry, the word at 0006H | B606H |
| arena, from the top of the program to the BDOS | 23388 bytes (5AA9H-B605H) |
| text in memory when the file is opened | 2048 bytes |
| undo region, taken out of the arena | 1024 bytes |
| text in memory after `6000G` `G` `6000G` `gg` `G` | 12288, 10496, 20736, 20480, 18432 bytes |
| `TEST.$$$` after `G` from the top, nothing changed | 91904 bytes |
| `VIBACKUP.$$$` after `G` `x` `gg` | 86016 bytes |
