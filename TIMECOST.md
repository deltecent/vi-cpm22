# What a command costs on a 100 K file

Written by `python3 timecost.py --write`; do not edit. Measured on a `VI.COM` of 22912 bytes, one fresh editor per row, on a file of 12800 lines of 8 bytes.

The seconds are the simulator's emulated clock (2 MHz 8080, 9600-baud console, the BIOS's disk loops). The simulated drive has no seek time and no rotation, so **these are a floor**: a real drive adds to every row that pages and to none that does not. The message is what the bottom row said afterwards.


## Moving

| command | seconds | characters sent | message |
|---|---|---|---|
| `^F` at line 6000 | 0.4 | 274 |  |
| `^B` at line 6000 | 0.5 | 275 |  |
| `200j` at line 6000 | 1.7 | 298 |  |
| `G` from the top | 21.9 | 298 |  |
| `gg` from the end | 1.7 | 296 |  |
| `6000G` from the top | 9.9 | 298 |  |
| `6100G` from line 6000 | 2.0 | 298 |  |
| `5900G` from line 6000 | 0.8 | 298 |  |
| `100G` from line 12000 | 2.0 | 298 |  |
| `G` again, after `G` `gg` | 22.0 | 298 |  |
| `gg` from the end, after `x` there | 52.2 | 296 |  |
| `'a` to line 100 from line 6000 | 1.4 | 298 |  |
| `^G` at the end | 0.4 | 44 | "TEST.TXT" line 12800 col 1 |
| `G` from the top, ESC 10 s into it | 11.7 | 52 | Interrupted |
| `/zzzz` from line 6000, never found | 36.2 | 56 | Pattern not found: zzzz |
| `/zzzz` from line 6000, ESC 10 s into it | 23.6 | 69 | Interrupted |
| `/012000` from the top | 22.0 | 316 |  |
| `/000100` from line 6000 (wraps) | 14.9 | 316 |  |
| `?000100` from line 6000 | 13.5 | 316 |  |

## Editing at line 6000

| command | seconds | characters sent | message |
|---|---|---|---|
| `x` | 0.1 | 4 |  |
| `ihello<Esc>` | 0.3 | 78 |  |
| `dd` | 0.3 | 56 |  |
| `u` after `dd` | 0.2 | 56 |  |
| `100dd` (800 bytes) | 2.2 | 298 |  |
| `u` after `100dd` | 3.0 | 298 |  |
| `500dd` (4 K) | 2.8 | 298 |  |
| `u` after `500dd` | 0.1 | 34 | Too large to undo |
| `P` after `500dd` | 1.0 | 298 |  |
| `2000dd` (16 K) | 6.7 | 298 |  |
| `P` after `2000dd` | 18.7 | 298 |  |
| `3000dd` (24 K) | 20.3 | 332 | Too large to yank |
| `5000dd` (40 K) | 20.3 | 332 | Too large to yank |
| `60yy` | 0.2 | 0 |  |
| `500yy` (4 K) | 3.3 | 298 |  |
| `2000yy` (16 K) | 24.6 | 298 |  |
| `5000yy` (40 K) | 20.4 | 332 | Too large to yank |
| `d6500G` (4 K) | 2.3 | 298 |  |
| `u` after `d6500G` | 0.1 | 34 | Too large to undo |
| `d9000G` (24 K) | 14.1 | 298 |  |
| `d'a`, the mark at line 9000 (24 K) | 7.9 | 298 |  |
| `dG` (54 K) | 35.3 | 298 |  |
| `dgg` (48 K) | 8.6 | 296 |  |
| `yG` (54 K) | 28.9 | 299 |  |
| `u` after `dd` `G` | 0.1 | 50 | Cannot undo: change has paged out |

## Substitute

| command | seconds | characters sent | message |
|---|---|---|---|
| `:6000,6100s/0/1/` | 3.5 | 325 |  |
| `:%s/0/1/` (12800 lines) | 233.7 | 317 |  |

## Files

| command | seconds | characters sent | message |
|---|---|---|---|
| `:w`, nothing changed | 50.7 | 343 | "TEST.TXT" written |
| `:w` after `x` at the top | 50.7 | 342 | "TEST.TXT" written |
| `:w` after `x` at line 6000 | 62.9 | 345 | "TEST.TXT" written |
| `:w` after `x` at the end | 67.3 | 345 | "TEST.TXT" written |
| `:e!` after `x` at the top | 3.1 | 336 | "TEST.TXT" |
| `:e!` after `x` at line 6000 | 12.5 | 339 | "TEST.TXT" |
| `:6000,6100w T.TXT` (800 bytes) | 4.8 | 67 | "T.TXT" written |
| `:6000,9000w T.TXT` (24 K) | 26.2 | 67 | "T.TXT" written |
| `:r T.TXT` of 800 bytes, at line 3000 | 4.9 | 317 |  |
| `:r T.TXT` of 24 K, at line 3000 | 27.7 | 317 |  |

## Memory and work files

| | |
|---|---|
| BDOS entry, the word at 0006H | B606H |
| arena, from the top of the program to the BDOS | 21743 bytes (6116H-B605H) |
| text in memory when the file is opened | 2048 bytes |
| undo region, taken out of the arena | 1024 bytes |
| text in memory after `6000G` `G` `6000G` `gg` `G` | 11904, 12928, 19072, 2048, 1536 bytes |
| `TEST.$$$` after `G` from the top, nothing changed | 0 bytes |
| `VIBACKUP.$$$` after `G` `x` `gg` | 86016 bytes |
