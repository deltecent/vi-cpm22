# What a command costs on a 100 K file

Written by `python3 timecost.py --write`; do not edit. Measured on a `VI.COM` of 18560 bytes, one fresh editor per row, on a file of 12800 lines of 8 bytes.

The seconds are the simulator's emulated clock (2 MHz 8080, 9600-baud console, the BIOS's disk loops). The simulated drive has no seek time and no rotation, so **these are a floor**: a real drive adds to every row that pages and to none that does not. The message is what the bottom row said afterwards.


## Moving

| command | seconds | characters sent | message |
|---|---|---|---|
| `^F` at line 6000 | 0.8 | 553 |  |
| `^B` at line 6000 | 0.6 | 434 |  |
| `200j` at line 6000 | 1.6 | 343 |  |
| `G` from the top | 45.8 | 304 |  |
| `gg` from the end | 40.6 | 315 |  |
| `6000G` from the top | 22.0 | 352 |  |
| `6100G` from line 6000 | 1.0 | 356 |  |
| `5900G` from line 6000 | 1.0 | 356 |  |
| `100G` from line 12000 | 38.3 | 343 |  |
| `G` again, after `G` `gg` | 38.2 | 304 |  |
| `gg` from the end, after `x` there | 55.3 | 315 |  |
| `'a` to line 100 from line 6000 | 15.8 | 304 |  |
| `^G` at the end | 0.6 | 63 | "TEST.TXT" line 12800 col 1 |
| `G` from the top, `^C` 10 s into it | 20.9 | 33 | Interrupted |
| `/zzzz` from line 6000, never found | 117.0 | 61 | Pattern not found: zzzz |
| `/zzzz` from line 6000, `^C` 10 s into it | 17.2 | 49 | Interrupted |
| `/012000` from the top | 45.7 | 321 |  |
| `/000100` from line 6000 (wraps) | 65.0 | 321 |  |
| `?000100` from line 6000 | 15.2 | 321 |  |

## Editing at line 6000

| command | seconds | characters sent | message |
|---|---|---|---|
| `x` | 0.1 | 34 |  |
| `ihello<Esc>` | 0.7 | 204 |  |
| `dd` | 0.5 | 68 |  |
| `u` after `dd` | 0.4 | 304 |  |
| `100dd` (800 bytes) | 1.4 | 356 |  |
| `u` after `100dd` | 2.0 | 304 |  |
| `500dd` (4 K) | 4.0 | 356 |  |
| `u` after `500dd` | 0.1 | 40 | Too large to undo |
| `P` after `500dd` | 1.6 | 304 |  |
| `2000dd` (16 K) | 10.8 | 369 |  |
| `2800dd` (22 K) | 13.1 | 369 |  |
| `P` after `2800dd` | 9.3 | 304 |  |
| `3000dd` (24 K) | 26.9 | 409 | Too large to yank |
| `5000dd` (40 K) | 26.9 | 409 | Too large to yank |
| `60yy` | 0.5 | 52 |  |
| `500yy` (4 K) | 4.0 | 356 |  |
| `2800yy` (22 K) | 38.1 | 369 |  |
| `5000yy` (40 K) | 26.3 | 409 | Too large to yank |
| `d6500G` (4 K) | 3.1 | 369 |  |
| `u` after `d6500G` | 0.1 | 40 | Too large to undo |
| `d9000G` (24 K) | 17.9 | 369 |  |
| `d'a`, the mark at line 9000 (24 K) | 6.4 | 317 |  |
| `dG` (54 K) | 49.8 | 317 |  |
| `dgg` (48 K) | 22.0 | 315 |  |
| `yG` (54 K) | 43.4 | 318 |  |
| `u` after `dd` `G` | 0.1 | 56 | Cannot undo: change has paged out |

## Substitute

| command | seconds | characters sent | message |
|---|---|---|---|
| `:6000,6100s/0/1/` | 2.6 | 330 |  |
| `:%s/0/1/` (12800 lines) | 266.9 | 322 |  |

## Files

| command | seconds | characters sent | message |
|---|---|---|---|
| `:w`, nothing changed | 50.9 | 354 | "TEST.TXT" written |
| `:w` after `x` at the top | 50.9 | 353 | "TEST.TXT" written |
| `:w` after `x` at line 6000 | 50.0 | 356 | "TEST.TXT" written |
| `:w` after `x` at the end | 52.1 | 356 | "TEST.TXT" written |
| `:e!` after `x` at the top | 3.1 | 347 | "TEST.TXT" |
| `:e!` after `x` at line 6000 | 21.0 | 350 | "TEST.TXT" |
| `:6000,6100w T.TXT` (800 bytes) | 3.8 | 78 | "T.TXT" written |
| `:6000,9000w T.TXT` (24 K) | 31.1 | 78 | "T.TXT" written |
| `:r T.TXT` of 800 bytes, at line 3000 | 1.9 | 322 |  |
| `:r T.TXT` of 24 K, at line 3000 | 26.3 | 322 |  |

## Memory and work files

| | |
|---|---|
| BDOS entry, the word at 0006H | B606H |
| arena, from the top of the program to the BDOS | 27065 bytes (4C4CH-B605H) |
| text in memory when the file is opened | 2048 bytes |
| undo region, taken out of the arena | 1024 bytes |
| text in memory after `6000G` `G` `6000G` `gg` `G` | 12288, 16640, 24832, 24576, 22528 bytes |
| `TEST.$$$` after `G` from the top, nothing changed | 85760 bytes |
| `VIBACKUP.$$$` after `G` `x` `gg` | 81920 bytes |
