# What a command costs on a 100 K file

Written by `python3 timecost.py --write`; do not edit. Measured on a `VI.COM` of 21760 bytes, one fresh editor per row, on a file of 12800 lines of 8 bytes.

The seconds are the simulator's emulated clock (2 MHz 8080, 9600-baud console, the BIOS's disk loops). The simulated drive has no seek time and no rotation, so **these are a floor**: a real drive adds to every row that pages and to none that does not. The message is what the bottom row said afterwards.


## Moving

| command | seconds | characters sent | message |
|---|---|---|---|
| `^F` at line 6000 | 0.4 | 274 |  |
| `^B` at line 6000 | 0.5 | 275 |  |
| `200j` at line 6000 | 1.5 | 298 |  |
| `G` from the top | 44.7 | 298 |  |
| `gg` from the end | 30.8 | 296 |  |
| `6000G` from the top | 20.1 | 298 |  |
| `6100G` from line 6000 | 0.8 | 298 |  |
| `5900G` from line 6000 | 0.8 | 298 |  |
| `100G` from line 12000 | 27.6 | 298 |  |
| `G` again, after `G` `gg` | 28.4 | 298 |  |
| `gg` from the end, after `x` there | 49.2 | 296 |  |
| `'a` to line 100 from line 6000 | 12.5 | 298 |  |
| `^G` at the end | 0.4 | 44 | "TEST.TXT" line 12800 col 1 |
| `G` from the top, ESC 10 s into it | 16.7 | 52 | Interrupted |
| `/zzzz` from line 6000, never found | 96.3 | 56 | Pattern not found: zzzz |
| `/zzzz` from line 6000, ESC 10 s into it | 25.2 | 69 | Interrupted |
| `/012000` from the top | 40.9 | 316 |  |
| `/000100` from line 6000 (wraps) | 56.2 | 316 |  |
| `?000100` from line 6000 | 12.1 | 316 |  |

## Editing at line 6000

| command | seconds | characters sent | message |
|---|---|---|---|
| `x` | 0.0 | 4 |  |
| `ihello<Esc>` | 0.3 | 78 |  |
| `dd` | 0.3 | 56 |  |
| `u` after `dd` | 0.2 | 56 |  |
| `100dd` (800 bytes) | 1.2 | 298 |  |
| `u` after `100dd` | 2.8 | 298 |  |
| `500dd` (4 K) | 3.3 | 298 |  |
| `u` after `500dd` | 0.1 | 34 | Too large to undo |
| `P` after `500dd` | 1.5 | 298 |  |
| `2000dd` (16 K) | 8.4 | 298 |  |
| `P` after `2000dd` | 14.9 | 298 |  |
| `3000dd` (24 K) | 18.1 | 332 | Too large to yank |
| `5000dd` (40 K) | 18.1 | 332 | Too large to yank |
| `60yy` | 0.3 | 0 |  |
| `500yy` (4 K) | 3.2 | 298 |  |
| `2000yy` (16 K) | 19.6 | 298 |  |
| `5000yy` (40 K) | 17.5 | 332 | Too large to yank |
| `d6500G` (4 K) | 2.8 | 298 |  |
| `u` after `d6500G` | 0.1 | 34 | Too large to undo |
| `d9000G` (24 K) | 16.1 | 298 |  |
| `d'a`, the mark at line 9000 (24 K) | 8.4 | 298 |  |
| `dG` (54 K) | 47.3 | 298 |  |
| `dgg` (48 K) | 18.9 | 296 |  |
| `yG` (54 K) | 40.4 | 299 |  |
| `u` after `dd` `G` | 0.1 | 50 | Cannot undo: change has paged out |

## Substitute

| command | seconds | characters sent | message |
|---|---|---|---|
| `:6000,6100s/0/1/` | 2.3 | 325 |  |
| `:%s/0/1/` (12800 lines) | 230.2 | 317 |  |

## Files

| command | seconds | characters sent | message |
|---|---|---|---|
| `:w`, nothing changed | 51.8 | 343 | "TEST.TXT" written |
| `:w` after `x` at the top | 51.7 | 342 | "TEST.TXT" written |
| `:w` after `x` at line 6000 | 58.6 | 345 | "TEST.TXT" written |
| `:w` after `x` at the end | 53.0 | 345 | "TEST.TXT" written |
| `:e!` after `x` at the top | 3.1 | 336 | "TEST.TXT" |
| `:e!` after `x` at line 6000 | 25.3 | 339 | "TEST.TXT" |
| `:6000,6100w T.TXT` (800 bytes) | 3.8 | 67 | "T.TXT" written |
| `:6000,9000w T.TXT` (24 K) | 29.0 | 67 | "T.TXT" written |
| `:r T.TXT` of 800 bytes, at line 3000 | 1.9 | 317 |  |
| `:r T.TXT` of 24 K, at line 3000 | 27.5 | 317 |  |

## Memory and work files

| | |
|---|---|
| BDOS entry, the word at 0006H | B606H |
| arena, from the top of the program to the BDOS | 23026 bytes (5C13H-B605H) |
| text in memory when the file is opened | 2048 bytes |
| undo region, taken out of the arena | 1024 bytes |
| text in memory after `6000G` `G` `6000G` `gg` `G` | 12288, 10496, 20736, 20480, 18432 bytes |
| `TEST.$$$` after `G` from the top, nothing changed | 91904 bytes |
| `VIBACKUP.$$$` after `G` `x` `gg` | 86016 bytes |
