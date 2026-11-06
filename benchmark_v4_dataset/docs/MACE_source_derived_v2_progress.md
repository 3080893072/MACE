# MACE Source-derived v2：建设进度

- 更新日期：2026-11-05
- 已验收正式题：**50**（正式送验 50，通过 50，未通过 0）
- 另有 5 个候选在构造/验收阶段被否决，不计入正式数据集（见文末）。
- DEV：**25**；HELDOUT：**25**
- 目标：DEV 25（原 10 + 新 15）、HELDOUT 25

## 机制分布（已验收）

| 机制 | 已验收 | 目标 | 差额 |
|---|---:|---:|---:|
| M1_SINGLE_OPERATION | 8 | 6 | -2 |
| M2_TWO_OPERATION_COOPERATIVE | 8 | 10 | 2 |
| M3_THREE_OPERATION_COOPERATIVE | 6 | 6 | 0 |
| M4_ALTERNATIVE_PATHS | 5 | 5 | 0 |
| M5_CONDITIONAL_BRANCH | 5 | 5 | 0 |
| M6_CROSS_FUNCTION_STATE | 4 | 4 | 0 |
| M7_LOOP_STATE | 3 | 3 | 0 |
| M8_OBJECT_SHARED_STATE | 3 | 3 | 0 |
| M9_EXCEPTION_FALLBACK | 3 | 3 | 0 |
| M10_NEGATIVE_CONTROL | 5 | 5 | 0 |

## 项目分布（已验收）

| 项目 | 题数 |
|---|---:|
| docutils | 9 |
| Pygments | 5 |
| jsonschema | 3 |
| tabulate | 3 |
| toml | 3 |
| Markdown | 2 |
| attrs | 2 |
| isort | 2 |
| multidict | 2 |
| networkx | 2 |
| passlib | 2 |
| requests | 2 |
| simplejson | 2 |
| sqlparse | 2 |
| PyYAML | 1 |
| coverage | 1 |
| h11 | 1 |
| humanize | 1 |
| jedi | 1 |
| msgpack | 1 |
| parso | 1 |
| pycodestyle | 1 |
| urllib3 | 1 |

## 题目清单

| 题号 | 机制 | 项目 | 版本 | split | U | 输入(m/e/c/nc) | 验收 |
|---|---|---|---|---|---:|---|---|
| 1 | M7 | attrs | 23.2.0 | DEV | 1 | 1/1/0/0 | PASS |
| 2 | M2 | coverage | 7.4.0 | DEV | 2 | 1/1/1/0 | PASS |
| 3 | M1 | docutils | 0.20.1 | DEV | 1 | 1/1/1/0 | PASS |
| 4 | M2 | docutils | 0.20.1 | DEV | 2 | 1/1/1/0 | PASS |
| 5 | M3 | docutils | 0.20.1 | DEV | 3 | 1/1/1/0 | PASS |
| 6 | M3 | docutils | 0.20.1 | DEV | 3 | 1/1/1/0 | PASS |
| 7 | M1 | docutils | 0.20.1 | DEV | 1 | 1/1/1/0 | PASS |
| 8 | M2 | docutils | 0.20.1 | DEV | 2 | 1/1/1/0 | PASS |
| 9 | M1 | docutils | 0.20.1 | DEV | 1 | 1/1/1/0 | PASS |
| 10 | M2 | docutils | 0.20.1 | DEV | 2 | 1/1/1/0 | PASS |
| 11 | M1 | docutils | 0.20.1 | DEV | 1 | 1/1/1/0 | PASS |
| 12 | M5 | humanize | 4.9.0 | DEV | 1 | 1/1/1/0 | PASS |
| 13 | M4 | isort | 5.13.2 | DEV | 2 | 1/1/1/0 | PASS |
| 14 | M1 | jsonschema | 4.20.0 | DEV | 1 | 2/1/1/0 | PASS |
| 15 | M1 | networkx | 3.2.1 | DEV | 1 | 1/1/1/0 | PASS |
| 16 | M8 | networkx | 3.2.1 | DEV | 1 | 1/1/2/0 | PASS |
| 17 | M4 | Pygments | 2.17.2 | DEV | 2 | 1/1/1/0 | PASS |
| 18 | M2 | Pygments | 2.17.2 | DEV | 2 | 2/1/1/0 | PASS |
| 19 | M3 | Pygments | 2.17.2 | DEV | 3 | 1/1/1/0 | PASS |
| 20 | M6 | Pygments | 2.17.2 | DEV | 1 | 2/1/1/0 | PASS |
| 21 | M9 | Pygments | 2.17.2 | DEV | 1 | 3/1/0/0 | PASS |
| 22 | M1 | tabulate | 0.9.0 | DEV | 1 | 1/1/2/0 | PASS |
| 23 | M5 | tabulate | 0.9.0 | DEV | 1 | 1/1/2/0 | PASS |
| 24 | M7 | tabulate | 0.9.0 | DEV | 1 | 1/1/2/0 | PASS |
| 25 | M1 | toml | 0.10.2 | DEV | 1 | 1/1/1/0 | PASS |
| 26 | M10 | attrs | 23.2.0 | HELDOUT | 1 | 0/0/0/2 | PASS |
| 27 | M5 | h11 | 0.14.0 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 28 | M5 | isort | 5.13.2 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 29 | M2 | jedi | 0.19.1 | HELDOUT | 2 | 1/1/1/0 | PASS |
| 30 | M4 | jsonschema | 4.20.0 | HELDOUT | 2 | 1/1/1/0 | PASS |
| 31 | M10 | jsonschema | 4.20.0 | HELDOUT | 1 | 0/0/0/2 | PASS |
| 32 | M3 | Markdown | 3.5.1 | HELDOUT | 3 | 1/1/1/0 | PASS |
| 33 | M2 | Markdown | 3.5.1 | HELDOUT | 2 | 1/1/1/0 | PASS |
| 34 | M9 | msgpack | 1.0.7 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 35 | M6 | multidict | 6.0.4 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 36 | M10 | multidict | 6.0.4 | HELDOUT | 1 | 0/0/0/2 | PASS |
| 37 | M8 | parso | 0.8.3 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 38 | M2 | passlib | 1.7.4 | HELDOUT | 2 | 1/1/1/0 | PASS |
| 39 | M3 | passlib | 1.7.4 | HELDOUT | 3 | 1/1/1/0 | PASS |
| 40 | M10 | pycodestyle | 2.11.1 | HELDOUT | 1 | 0/0/0/2 | PASS |
| 41 | M3 | PyYAML | 6.0.1 | HELDOUT | 3 | 1/1/1/0 | PASS |
| 42 | M8 | requests | 2.31.0 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 43 | M7 | requests | 2.31.0 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 44 | M6 | simplejson | 3.19.2 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 45 | M4 | simplejson | 3.19.2 | HELDOUT | 2 | 1/1/1/0 | PASS |
| 46 | M9 | sqlparse | 0.4.4 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 47 | M5 | sqlparse | 0.4.4 | HELDOUT | 1 | 1/1/1/0 | PASS |
| 48 | M4 | toml | 0.10.2 | HELDOUT | 2 | 1/1/1/0 | PASS |
| 49 | M10 | toml | 0.10.2 | HELDOUT | 1 | 0/0/0/2 | PASS |
| 50 | M6 | urllib3 | 2.1.0 | HELDOUT | 1 | 1/1/1/0 | PASS |

## 本轮说明

- 所有数字由 `results/source_derived_v2_inventory.csv` 汇总，拒绝题不计入正式数据集。
- 新增题目的独立验收沿用原 AC 标准；负向控制题额外要求每个声明输入满足 P−≠P+ 且不存在任何保留子集复现 P+。

## 构造期拒绝/替换的候选（不计入）

| 候选 | 项目 | 位置 | 拟用机制 | 阶段 | 原因 |
|---|---|---|---|---|---|
| sd_lark_anon_terminal_m4 | lark 1.1.9 | `lark/load_grammar.py:468` | M4_ALTERNATIVE_PATHS | formal_acceptance_run | 文件为 CRLF 行尾；验收按字节比较 A 行，行尾 \r 使 A_code 无法匹配，除非在 A_code 中嵌入 \r。整个 lark 文件因此弃用。 |
| sd_parso_issue_dedup_m8 | parso 0.8.3 | `parso/python/diff.py:74` | M8_OBJECT_SHARED_STATE | formal_acceptance_run | 上游在第 74 行已有 `if issue not in self.issues:` 守卫，删除目标行对重复 issue 输入不可观测；换成同文件 _NodesTreeNode.add_child_node 的无条件 append 后通过。 |
| dateutil_parser_token_comma | python-dateutil 2.8.2 | `dateutil/parser/_parser.py:182` | M1/M4（未定型） | construction_analysis | `_timelex("0,5")` 会把逗号切分成独立 token，目标行 `token = token.replace(',', '.')` 对可构造输入不可触发，无法给出 exposing 输入。 |
| h11_writer_reader_m6 | h11 0.14.0 | `h11/_connection.py:81` | M6_CROSS_FUNCTION_STATE | construction_analysis | SEND_BODY 的 `_get_io_object` 会调用 `_body_framing`，后者在第 88 行断言事件类型必须是 Request/Response；U 无法只凭 next_event/send 重建 writer/reader，故放弃。 |
| passlib_hash_info_cache_m6 | passlib 1.7.4 | `passlib/crypto/digest.py:313` | M6_CROSS_FUNCTION_STATE | construction_analysis | 别名归一化缓存（第 313 行 `cache[digest] = info`）使删除单条缓存写入难以构造出可观测的 exposing 输入；放弃该锚点。 |
