| fixture | model | mode | guard ok | unsound/incomplete | round1 -> final | failing rels | parse err | prompt tok | out tok | s |
|---|---|---|---|---|---|---|---|---|---|---|
| alt_masking | qwen2.5-coder:32b | direct | yes | 0/0 | 0 -> 0 | 0 | 0 | 648 | 53 | 3.0 |
| alt_masking | qwen2.5-coder:32b | fixed | yes | 0/0 | 0 -> 0 | 0 | 0 | 782 | 67 | 5.8 |
| alt_masking | qwen2.5-coder:32b | generic | yes | 0/0 | 0 -> 0 | 0 | 0 | 980 | 203 | 12.1 |
| alt_masking | qwen2.5-coder:32b | mace | yes | 0/0 | 0 -> 0 | 4 | 3 | 15048 | 2083 | 109.1 |
| modulo_absorb | qwen2.5-coder:32b | direct | no | 47/212 | 47 -> 259 | 0 | 0 | 4103 | 268 | 19.6 |
| modulo_absorb | qwen2.5-coder:32b | fixed | no | 259/169 | 0 -> 428 | 0 | 0 | 4323 | 275 | 16.9 |
| modulo_absorb | qwen2.5-coder:32b | generic | no | 259/212 | 0 -> 471 | 0 | 0 | 5252 | 517 | 31.3 |
| modulo_absorb | qwen2.5-coder:32b | mace | no | 0/0 | 0 -> 0 | 1 | 1 | 14667 | 1636 | 86.5 |
| overwrite_channel | qwen2.5-coder:32b | direct | no | 28/40 | 68 -> 68 | 0 | 0 | 4672 | 241 | 17.9 |
| overwrite_channel | qwen2.5-coder:32b | fixed | no | 0/0 | 68 -> 0 | 0 | 0 | 4803 | 92 | 8.0 |
| overwrite_channel | qwen2.5-coder:32b | generic | no | 28/28 | 68 -> 56 | 0 | 0 | 5465 | 536 | 32.1 |
| overwrite_channel | qwen2.5-coder:32b | mace | yes | 0/0 | 12 -> 0 | 2 | 0 | 18580 | 1282 | 72.1 |
| dedup_channel | qwen2.5-coder:32b | direct | yes | 0/0 | 0 -> 0 | 0 | 0 | 1438 | 135 | 10.0 |
| dedup_channel | qwen2.5-coder:32b | fixed | yes | 0/0 | 120 -> 0 | 0 | 0 | 1920 | 123 | 9.4 |
| dedup_channel | qwen2.5-coder:32b | generic | no | 0/0 | 106 -> 0 | 0 | 0 | 5210 | 401 | 23.5 |
| dedup_channel | qwen2.5-coder:32b | mace | no | 0/100 | 100 -> 100 | 2 | 3 | 13375 | 1588 | 82.8 |
| sort_channel | qwen2.5-coder:32b | direct | no | 2866/2728 | 7046 -> 5594 | 0 | 0 | 5510 | 221 | 26.2 |
| sort_channel | qwen2.5-coder:32b | fixed | no | 0/7046 | 0 -> 7046 | 0 | 0 | 5945 | 303 | 27.6 |
| sort_channel | qwen2.5-coder:32b | generic | no | 1134/6452 | 7046 -> 7586 | 0 | 0 | 6870 | 509 | 36.2 |
| sort_channel | qwen2.5-coder:32b | mace | no | 0/0 | 7046 -> 0 | 1 | 0 | 18931 | 872 | 59.4 |
| swap_channels | qwen2.5-coder:32b | direct | no | 0/4 | 0 -> 4 | 0 | 0 | 3718 | 185 | 12.9 |
| swap_channels | qwen2.5-coder:32b | fixed | no | 0/4 | 0 -> 4 | 0 | 0 | 4395 | 281 | 17.9 |
| swap_channels | qwen2.5-coder:32b | generic | no | 0/4 | 0 -> 4 | 0 | 0 | 4568 | 397 | 23.5 |
| swap_channels | qwen2.5-coder:32b | mace | no | 0/0 | 0 -> 0 | 1 | 0 | 18954 | 1287 | 76.8 |
