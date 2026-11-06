# MACE Source-derived Benchmark v2：最终报告

- 生成日期：2026-11-05
- 范围：仅数据集建设（不涉及 MACE 算法、Graph、Qwen Prompt、Verifier 的任何修改）
- 结论：**正式题 50 道，全部通过独立验收**；DEV 25、HELDOUT 25；覆盖 23 个开源项目。

## 1. 正式数量与构成

| 项目 | 数量 |
|---|---:|
| 正式题总数 | **50** |
| DEV | **25**（原 10 道全部计入 DEV + 新增 15 道） |
| HELDOUT | **25**（全部新增） |
| 覆盖开源项目 | **23** |
| 通过独立验收 | **50 / 50** |
| 正式送验未通过 | **0** |
| 构造期被否决的候选 | 5（不计入正式数据集，见第 8 节） |

原 10 道（`results/MACE_source_derived_inventory.csv`）全部保留在 DEV，未作为
HELDOUT 复用。所有新增题目的 `researcher_constructed = true`，沿用 track C
（真实上游 sdist 文件 + 仅插入的研究者补丁）与原有独立验收标准。

## 2. 机制分布

| 机制 | 目标 | 已验收 | 差额 | DEV | HELDOUT |
|---|---:|---:|---:|---:|---:|
| M1_SINGLE_OPERATION | 6 | 8 | **+2** | 8 | 0 |
| M2_TWO_OPERATION_COOPERATIVE | 10 | 8 | **−2** | 5 | 3 |
| M3_THREE_OPERATION_COOPERATIVE | 6 | 6 | 0 | 3 | 3 |
| M4_ALTERNATIVE_PATHS | 5 | 5 | 0 | 2 | 3 |
| M5_CONDITIONAL_BRANCH | 5 | 5 | 0 | 2 | 3 |
| M6_CROSS_FUNCTION_STATE | 4 | 4 | 0 | 1 | 3 |
| M7_LOOP_STATE | 3 | 3 | 0 | 2 | 1 |
| M8_OBJECT_SHARED_STATE | 3 | 3 | 0 | 1 | 2 |
| M9_EXCEPTION_FALLBACK | 3 | 3 | 0 | 1 | 2 |
| M10_NEGATIVE_CONTROL | 5 | 5 | 0 | 0 | 5 |
| **合计** | **50** | **50** | 0 | **25** | **25** |

### 偏差说明

只有 M1 与 M2 偏离目标：M1 多 2 道、M2 少 2 道。原因是原 10 道 DEV 已固定为
M1=3、M2=4、M3=2、M7=1；在此基础上新增 DEV 15 道并补足 HELDOUT 时，M1 可用锚点
多于 M2，最终形成 M1=8、M2=8。其余 7 个机制全部精确命中目标。未为凑数而降低
任何题目的验收标准，也未把未通过题目计入正式数据集。

## 3. 项目分布

| 项目 | 合计 | DEV | HELDOUT |
|---|---:|---:|---:|
| docutils | 9 | 9 | 0 |
| Pygments | 5 | 5 | 0 |
| jsonschema | 3 | 1 | 2 |
| tabulate | 3 | 3 | 0 |
| toml | 3 | 1 | 2 |
| Markdown | 2 | 0 | 2 |
| attrs | 2 | 1 | 1 |
| isort | 2 | 1 | 1 |
| multidict | 2 | 0 | 2 |
| networkx | 2 | 2 | 0 |
| passlib | 2 | 0 | 2 |
| requests | 2 | 0 | 2 |
| simplejson | 2 | 0 | 2 |
| sqlparse | 2 | 0 | 2 |
| PyYAML | 1 | 0 | 1 |
| coverage | 1 | 1 | 0 |
| h11 | 1 | 0 | 1 |
| humanize | 1 | 1 | 0 |
| jedi | 1 | 0 | 1 |
| msgpack | 1 | 0 | 1 |
| parso | 1 | 0 | 1 |
| pycodestyle | 1 | 0 | 1 |
| urllib3 | 1 | 0 | 1 |
| **合计** | **50** | **25** | **25** |

23 个项目满足“至少 8–12 个不同开源项目”的要求。题目共涉及 41 个不同的
`(项目, 文件, 函数)` 组合；同一函数出现多次时使用不同的目标行或不同的候选
补丁（见第 7 节独立性说明）。

## 4. 验收状态

50 道题均有两份独立产物：`acceptance/<case>.json` 与 `evidence/<case>/`。
每份验收报告均满足：

| 检查项 | 结果 |
|---|---|
| `independent = true` | 50 / 50 |
| `shares_construction_code = false` | 50 / 50 |
| `all_checks_pass = true` | 50 / 50 |
| `AC1_sdist_matches_discovery` | 50 / 50 |
| `AC1_evidence_matches_source` | 50 / 50 |
| `AC1_A_line_text` | 50 / 50 |
| `patch_preserves_A` / `patch_only_inserts` | 50 / 50 |
| `U_blocks_outside_A` | 50 / 50 |
| `P_minus_only_deletes_A` | 50 / 50 |
| `patch_diff_does_not_remove_A` | 50 / 50 |
| `patch_diff_insert_count` | 50 / 50 |
| `enumeration_agrees` | 50 / 50 |
| `roles_declared` | 50 / 50 |
| `masking_inputs_satisfied` | 50 / 50 |
| `exposing_inputs_satisfied` | 50 / 50 |
| `control_inputs_satisfied` | 50 / 50 |
| `negative_control_inputs_satisfied` | 50 / 50 |
| `negative_control_no_masking_relation` | 50 / 50 |
| `u_necessary_in_minimal_sets` | 50 / 50 |

验收语义：PLUS = 保留 A 且启用全部 U；P_MINUS = 删除 A、保留全部 U；
KEEP_* = 删除 A 并停用未保留的 U。每个输入按“观测是否等于 PLUS”判定；MSMS 为
最小保留集，`mmbs = minimal`。

### 输入与结构统计

| 指标 | 数值 |
|---|---:|
| 声明的 masking 输入 | 50 |
| 声明的 exposing 输入 | 45 |
| 声明的 control 输入 | 47 |
| 声明的 negative-control 输入 | 10（5 道题 × 2） |
| U 块总数 | 75（31 道 1 块、13 道 2 块、6 道 3 块） |
| 协作型题（M2 + M3） | 14 |
| 替代路径题（M4，每个 masking 输入 2 个单元素 MSMS） | 5 |
| 每个 masking 输入的所有 U 均在某最小集中必要 | 40 / 45 道正题 |

5 道 M4 的 `u_necessary_all_masking = false` 是替代路径机制的正常性质：每个
单元素最小集单独即可复现 PLUS，任一 U 被移除后另一条路径仍成立，因此不存在
“所有 U 同时必要”的最小集。协作型 M2/M3 的全部真子集均已被枚举验证：任何
真子集都不能复现 PLUS。

## 5. 负向控制（M10）

5 道负向控制题全部位于 HELDOUT，覆盖 5 个不同项目：

| 题号 | 项目 | 目标操作 | 候选补丁的性质 |
|---|---|---|---|
| `sd_attrs_tobool_nc` | attrs 23.2.0 | `to_bool` 的大小写折叠 | 反向折叠，无法复现小写形式 |
| `sd_pycodestyle_paths_nc` | pycodestyle 2.11.1 | `normalize_paths` 的双侧裁剪 | 只裁左侧，保留尾随空格 |
| `sd_jsonschema_pointer_nc` | jsonschema 4.20.0 | JSON Pointer 转义还原 | 只还原 `~1`，遗留 `~0` |
| `sd_multidict_version_nc` | multidict 6.0.4 | 每实现版本号记录 | 填常数 `-1`，不是真实计数器 |
| `sd_toml_quote_nc` | toml 0.10.2 | 单引号字符串中的双引号转义 | 用反斜杠-单引号转义，产物不同 |

每道题的所有输入均以 `nc_*` 命名，验收额外执行 M10 严格检查：

- 每个声明输入 `exposing_witness = true`（P− ≠ P+）；
- `minimal_masking_sets` 为空（不存在任何保留子集复现 PLUS）；
- `empty_kept_masks = false`（空保留集也不复现 PLUS）。

10 个 nc 输入全部满足上述三条，因此这 5 道题证明的是“该候选补丁不存在掩盖
关系”，而不是“该操作不存在掩盖关系”。其中 jsonschema、multidict、toml 的
负向控制与同项目的正题使用同一目标行，这是有意的配对设计：同一操作上，换一个
候选补丁就不再构成掩盖关系。

## 6. HELDOUT 封存

HELDOUT 按项目与构造模板双轴分组封存，封存清单：

- `source_derived/heldout/seal/heldout_v2_seal.json`
- `source_derived/heldout/seal/heldout_v2_seal.md`

封存内容：25 道题、17 个项目、9 个构造模板；逐题的 case、evidence、
acceptance 与 task bundle 的 SHA-256；以及按项目、按模板的分组索引。

| 构造模板 | 机制 | 题数 |
|---|---|---:|
| guarded wrong alternative at A | M10 | 5 |
| guarded repair in another function | M6 | 3 |
| guarded shared-state write | M8 | 2 |
| loop-carried state update | M7 | 1 |
| single guarded branch at A | M5 | 3 |
| three limbs at A | M3 | 3 |
| try/except fallback at A | M9 | 2 |
| two guarded alternative paths at A | M4 | 3 |
| two one-shot limbs at A | M2 | 3 |

HELDOUT 题目包位于 `source_derived/heldout/tasks/`（25 个目录，每个含
`task.json`、`patch.diff`、`provenance.json`、`reference.json`、
`acceptance.json`）。封存清单与 `reference.json` 均属数据集侧产物，**不得复制
进算法开发窗口**；算法窗口只能接触任务输入与 probe，不得读取封存答案、输入
矩阵或标准关系。

## 7. 独立性与模板说明

- 50 道题来自 23 个项目，41 个不同的 `(项目, 文件, 函数)` 组合。
- 3 个目标行被多道题使用：
  - `jsonschema/validators.py:1145`：DEV M1、HELDOUT M4、HELDOUT M10；
  - `multidict/_multidict_py.py:47`：HELDOUT M6、HELDOUT M10；
  - `toml/encoder.py:97`：HELDOUT M4、HELDOUT M10。
- 这些复用均为“同一操作、不同候选补丁/不同机制”的配对，其中 M10 复用是负向
  控制的设计需要；每道题的 U 块、输入、MSMS 与验收报告仍各自独立生成，验收的
  `shares_construction_code` 均为 `false`。
- passlib 两道题同文件同函数但不同目标行（`digest.py:155` 与 `:195`），构造
  模板分别为 M3（裁剪/大小写/空格）与 M2（连字符），不构成重复题。

## 8. 构造期拒绝/替换的候选（不计入正式数据集）

| 候选 | 项目 | 位置 | 拟用机制 | 阶段 | 原因 |
|---|---|---|---|---|---|
| `sd_lark_anon_terminal_m4` | lark 1.1.9 | `lark/load_grammar.py:468` | M4 | 已跑正式验收 | 文件为 CRLF 行尾；验收按字节比较 A 行，行尾 `\r` 使 A_code 无法匹配（除非把 `\r` 嵌入 A_code）。整个 lark 文件因此弃用。 |
| `sd_parso_issue_dedup_m8` | parso 0.8.3 | `parso/python/diff.py:74` | M8 | 已跑正式验收 | 上游已有 `if issue not in self.issues:` 守卫，删除目标行对重复 issue 输入不可观测。改用同文件 `_NodesTreeNode.add_child_node` 的无条件 append 后通过。 |
| `dateutil_parser_token_comma` | python-dateutil 2.8.2 | `dateutil/parser/_parser.py:182` | M1/M4（未定型） | 构造期分析 | `_timelex("0,5")` 会把逗号切分成独立 token，目标行 `token = token.replace(',', '.')` 对可构造输入不可触发，给不出 exposing 输入。 |
| `h11_writer_reader_m6` | h11 0.14.0 | `h11/_connection.py:81` | M6 | 构造期分析 | SEND_BODY 的 `_get_io_object` 会调用 `_body_framing`，后者在 88 行断言事件类型必须是 Request/Response；U 无法只凭 `next_event`/`send` 重建 writer/reader。 |
| `passlib_hash_info_cache_m6` | passlib 1.7.4 | `passlib/crypto/digest.py:313` | M6 | 构造期分析 | 别名归一化缓存使删除单条缓存写入难以构造可观测的 exposing 输入。 |

这些候选从未通过验收，也未计入 50 道正式题。相关临时 case/probe/evidence/
acceptance 产物已删除。

## 9. 文件索引

| 产物 | 路径 |
|---|---|
| 题目清单（CSV） | `results/source_derived_v2_inventory.csv` |
| 统计（JSON） | `results/source_derived_v2_statistics.json` |
| 建设进度 | `docs/MACE_source_derived_v2_progress.md` |
| 最终报告 | `docs/MACE_source_derived_v2_final.md` |
| DEV 题目 | `source_derived/cases/`、`source_derived/probes/` |
| HELDOUT 题目 | `source_derived/heldout/cases/`、`source_derived/heldout/probes/` |
| 独立验收报告 | `source_derived/acceptance/`、`source_derived/heldout/acceptance/` |
| 逐题证据 | `source_derived/evidence/`、`source_derived/heldout/evidence/` |
| HELDOUT 封存（JSON） | `source_derived/heldout/seal/heldout_v2_seal.json` |
| HELDOUT 封存（MD） | `source_derived/heldout/seal/heldout_v2_seal.md` |
| HELDOUT 任务包 | `source_derived/heldout/tasks/` |

验收工具：`tools/sd_harness.py`、`tools/sd_acceptance.py`、
`tools/sd_build_tasks.py`。
