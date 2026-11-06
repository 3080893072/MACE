| fixture | model | mode | guard ok | unsound/incomplete | round1 -> final | failing rels | parse err | prompt tok | out tok | s |
|---|---|---|---|---|---|---|---|---|---|---|
| dedup_channel | qwen2.5-coder:14b | direct | no | 0/0 | 0 -> 0 | 0 | 0 | 3964 | 320 | 13.0 |
| dedup_channel | qwen2.5-coder:14b | fixed | yes | 0/0 | 0 -> 0 | 0 | 0 | 1730 | 139 | 6.5 |
| dedup_channel | qwen2.5-coder:14b | generic | no | 6/100 | 106 -> 106 | 0 | 0 | 4921 | 342 | 13.7 |
| dedup_channel | qwen2.5-coder:14b | mace | no | 73/50 | 123 -> 123 | 3 | 0 | 19937 | 1547 | 58.1 |
| sort_channel | qwen2.5-coder:14b | direct | no | 2866/1364 | 2866 -> 4230 | 0 | 0 | 5519 | 95 | 10.7 |
| sort_channel | qwen2.5-coder:14b | fixed | no | 2866/1364 | 0 -> 4230 | 0 | 0 | 5593 | 153 | 16.8 |
| sort_channel | qwen2.5-coder:14b | generic | no | 2866/1364 | 2866 -> 4230 | 0 | 0 | 7393 | 492 | 27.2 |
| sort_channel | qwen2.5-coder:14b | mace | no | 0/7171 | 0 -> 7171 | 5 | 3 | 18178 | 2742 | 95.2 |
| swap_channels | qwen2.5-coder:14b | direct | no | 0/12 | 12 -> 12 | 0 | 0 | 3944 | 94 | 5.9 |
| swap_channels | qwen2.5-coder:14b | fixed | yes | 0/0 | 12 -> 0 | 0 | 0 | 4451 | 91 | 8.1 |
| swap_channels | qwen2.5-coder:14b | generic | no | 0/12 | 12 -> 12 | 0 | 0 | 4682 | 262 | 12.2 |
| swap_channels | qwen2.5-coder:14b | mace | no | 0/4 | 4 -> 4 | 1 | 0 | 20849 | 992 | 42.8 |
| alt_masking | qwen2.5-coder:14b | direct | yes | 0/0 | 0 -> 0 | 0 | 0 | 648 | 63 | 4.3 |
| alt_masking | qwen2.5-coder:14b | fixed | no | 28/0 | 0 -> 28 | 0 | 0 | 4293 | 270 | 12.2 |
| alt_masking | qwen2.5-coder:14b | generic | yes | 0/0 | 0 -> 0 | 0 | 0 | 943 | 156 | 7.3 |
| alt_masking | qwen2.5-coder:14b | mace | yes | 0/0 | 0 -> 0 | 3 | 0 | 17762 | 1334 | 44.0 |
| modulo_absorb | qwen2.5-coder:14b | direct | no | 259/212 | 471 -> 471 | 0 | 0 | 4583 | 167 | 8.9 |
| modulo_absorb | qwen2.5-coder:14b | fixed | no | 259/212 | 0 -> 471 | 0 | 0 | 4806 | 283 | 15.8 |
| modulo_absorb | qwen2.5-coder:14b | generic | no | 0/0 | 471 -> 0 | 0 | 0 | 5163 | 279 | 14.9 |
| modulo_absorb | qwen2.5-coder:14b | mace | no | None/None | 0 -> 0 | 0 | 4 | 8060 | 1556 | 52.4 |
| overwrite_channel | qwen2.5-coder:14b | direct | no | 0/52 | 12 -> 52 | 0 | 0 | 4287 | 195 | 11.0 |
| overwrite_channel | qwen2.5-coder:14b | fixed | no | 28/28 | 0 -> 56 | 0 | 0 | 4533 | 296 | 14.2 |
| overwrite_channel | qwen2.5-coder:14b | generic | no | 28/40 | 68 -> 68 | 0 | 0 | 5062 | 311 | 15.1 |
| overwrite_channel | qwen2.5-coder:14b | mace | no | 28/40 | 68 -> 68 | 4 | 3 | 14946 | 1447 | 46.2 |
