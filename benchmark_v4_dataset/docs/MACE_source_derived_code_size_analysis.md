# MACE Source-derived Benchmark 第一批 10 题：代码规模统计

- 统计日期：2026-11-05
- 范围：`source_derived/tasks/` 下已通过独立验收的 10 道 `SOURCE_DERIVED_CONTROLLED`（V4-DEV，第一批）
- 性质：**只读统计**。未修改任何题目、证据或验收文件。
- 数据来源：`source_derived/evidence/<case>/original|patched`、`tasks/<case>/{task,reference,provenance}.json`、`patch.diff`；逐文件实际读取并用 AST / tokenize 计数。
- 机器可读表：`results/source_derived_code_size.csv`

## 1. 统计口径

以下定义在生成脚本中逐条落实，**没有任何数值来自行号相减的推测**；行数一律为该文件的物理行数（`str.splitlines()`），包含空行与注释行。

| 编号 | 指标 | 实际测量对象 |
|---|---|---|
| 1 | 原始上游文件总行数 | `evidence/<case>/original/<basename>` 的物理行数；该文件的 SHA-256 与 `provenance.source_file_sha256` 逐题一致（10/10） |
| 2 | 原始目标函数 LOC | `task.json.target_operation.function` 所指函数在**原始文件**中的 AST 跨度（`end_lineno - lineno + 1`） |
| 3 | PUBLIC 源码 LOC | `evidence/<case>/patched/<basename>` 按 `tools/sd_algorithm_pilot.py` 的同一规则把 `# SD:U:…:begin/end` 标记行置空后的文本行数（行数不变，即算法实际读到的文件） |
| 4 | A 所在函数 LOC | PUBLIC 源码中包住 A 的**最内层** `FunctionDef/AsyncFunctionDef` 的 AST 跨度；另给出原始文件中的同一度量 |
| 5 | A 前后上下文 LOC | A 所在 PUBLIC 函数内部，A 之前 / 之后 / 两者之和的行数（不含 A 本身） |
| 6 | 涉及的函数数量 | PUBLIC 文件中，行跨度覆盖 A 或任一 U 块**正文**的 `FunctionDef/AsyncFunctionDef` 节点数；另给出文件内函数总数 |
| 7 | AST 可干预操作数量 | 冻结的 `benchmark_v3_baselines.ast_discovery.discover(task, public_text)` 在该题 PUBLIC 源码上实际返回的 `candidate_ops` 数量；与 v1 pilot 存档值逐题核对（10/10 相同） |
| 8 | 候选全集 U 的大小 | `reference.json.candidate_universe` 的条目数（即该题实际枚举子集的候选操作数） |
| 9 | Patch 新增行数 | `patch.diff` 中以 `+` 开头、排除 `+++` 的行数；同时校验 `patched 行数 − original 行数` 与之相等（10/10） |
| 10 | 注释和空行数量 | PUBLIC 源码：空行 = `strip()==''`；纯注释行 = tokenize 的 COMMENT 之前只有空白；行内注释单独计数 |

补充校验（全部通过）：A 行在原始与 patched 文件中逐字符等于 `task.json.target_operation.code`；把 `patch.diff` 的 `+` 行从 patched 文件中有序删除后逐行重构出原始文件（10/10）。

**难度分级是本报告自定义的分析口径，不是数据集元数据**：
- `hard`：存在某个 masking 输入，其极小掩盖集大小 ≥ 2（必须多操作协同时才成立）；
- `medium`：|U| > 1，但所有 masking 输入的极小掩盖集都是单元素（多路径可替代）；
- `easy`：|U| = 1 且极小掩盖集为单元素。

## 2. 逐题规模

| 题目 | 项目 | 机制 | 难度 | 原始文件行 | PUBLIC 行 | patch +行 | 原始声明函数 LOC | 原始 A 所在函数 LOC | PUBLIC A 所在函数 LOC | A 前 | A 后 | 上下文 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `sd_jsonschema_1145_pointer` | jsonschema 4.20.0 | M1 | easy | 1383 | 1386 | 3 | 53 | 53 | 56 | 38 | 17 | 55 |
| `sd_networkx_gexf448_slices` | networkx 3.2.1 | M8 | easy | 1065 | 1069 | 4 | 23 | 67 | 71 | 60 | 10 | 70 |
| `sd_pygments_bbcode64_color` | Pygments 2.17.2 | M4 | medium | 108 | 122 | 14 | 18 | 18 | 31 | 5 | 25 | 30 |
| `sd_pygments_bbcode70_italic` | Pygments 2.17.2 | M2 | hard | 108 | 115 | 7 | 18 | 18 | 25 | 11 | 13 | 24 |
| `sd_pygments_groff73_italic` | Pygments 2.17.2 | M3 | hard | 170 | 180 | 10 | 21 | 21 | 31 | 15 | 15 | 30 |
| `sd_pygments_latex297_italic` | Pygments 2.17.2 | M6 | easy | 521 | 545 | 24 | 6 | 44 | 44 | 18 | 25 | 43 |
| `sd_pygments_style95_cache` | Pygments 2.17.2 | M9 | easy | 203 | 216 | 13 | 14 | 65 | 65 | 35 | 29 | 64 |
| `sd_tabulate_1052_strip_right` | tabulate 0.9.0 | M1 | easy | 2716 | 2719 | 3 | 24 | 24 | 27 | 3 | 23 | 26 |
| `sd_tabulate_1056_strip_center` | tabulate 0.9.0 | M5 | easy | 2716 | 2720 | 4 | 24 | 24 | 28 | 7 | 20 | 27 |
| `sd_tabulate_2557_curlen` | tabulate 0.9.0 | M7 | easy | 2716 | 2720 | 4 | 110 | 110 | 114 | 68 | 45 | 113 |

`原始声明函数 LOC` 与 `原始 A 所在函数 LOC` 在三道题上不同：`task.json` 记录的是 A 所在外层函数内部的一个嵌套辅助函数名，而 A 语句本身不在该嵌套函数内（详见 §6）。

## 3. 逐题结构与代码纯净度

| 题目 | 文件内函数数 | 涉及函数数 | 涉及函数 | AST 可干预操作 | U 大小 | 声明输入 | PUBLIC 代码行 | 空行 | 纯注释 | 行内注释 | 注释合计 |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `sd_jsonschema_1145_pointer` | 40 | 1 | resolve_fragment | 2 | 1 | 4 | 1127 | 250 | 9 | 12 | 21 |
| `sd_networkx_gexf448_slices` | 33 | 1 | add_edges | 6 | 1 | 4 | 886 | 112 | 71 | 10 | 81 |
| `sd_pygments_bbcode64_color` | 3 | 1 | _make_styles | 4 | 2 | 3 | 95 | 26 | 1 | 0 | 1 |
| `sd_pygments_bbcode70_italic` | 3 | 1 | _make_styles | 2 | 2 | 4 | 88 | 26 | 1 | 0 | 1 |
| `sd_pygments_groff73_italic` | 7 | 1 | _make_styles | 2 | 3 | 3 | 132 | 48 | 0 | 0 | 0 |
| `sd_pygments_latex297_italic` | 12 | 2 | _create_stylesheet, get_style_defs | 8 | 1 | 4 | 427 | 73 | 45 | 0 | 45 |
| `sd_pygments_style95_cache` | 7 | 2 | __new__, style_for_token | 0 | 1 | 4 | 166 | 31 | 19 | 0 | 19 |
| `sd_tabulate_1052_strip_right` | 70 | 1 | _align_column_choose_padfn | 4 | 1 | 4 | 2169 | 378 | 172 | 42 | 214 |
| `sd_tabulate_1056_strip_center` | 70 | 1 | _align_column_choose_padfn | 3 | 1 | 4 | 2170 | 378 | 172 | 42 | 214 |
| `sd_tabulate_2557_curlen` | 70 | 1 | _wrap_chunks | 2 | 1 | 4 | 2170 | 378 | 172 | 42 | 214 |

`PUBLIC 代码行` 指非空且非纯注释的行（行内注释所在行仍计为代码行）。三个数量满足 `代码 + 空行 + 纯注释 = PUBLIC 行数`。

## 4. 汇总统计

| 指标 | 平均 | 中位数 | 最小 | 最大 | 合计 |
|---|---:|---:|---:|---:|---:|
| 原始上游文件总行数 | 1170.6 | 793.0 | 108 | 2716 | 11706 |
| PUBLIC 源码 LOC | 1179.2 | 807.0 | 115 | 2720 | 11792 |
| Patch 新增行数 | 8.6 | 5.5 | 3 | 24 | 86 |
| 原始目标函数 LOC（task.json 声明） | 31.1 | 22.0 | 6 | 110 | 311 |
| 原始 A 所在函数 LOC（AST 实际） | 44.4 | 34.0 | 18 | 110 | 444 |
| PUBLIC A 所在函数 LOC | 49.2 | 37.5 | 25 | 114 | 492 |
| A 前后上下文 LOC | 48.2 | 36.5 | 24 | 113 | 482 |
| PUBLIC 代码行（非空非纯注释） | 943.0 | 656.5 | 88 | 2170 | 9430 |

中位数为偶数个样本时取中间两值的算术平均（10 个样本）。

### 4.1 完整源文件长度 vs 实际交给算法的代码长度

| 题目 | 原始文件行 | PUBLIC 行 | 差值（=patch 新增） | 差值占比 | A 所在函数 / PUBLIC 行 |
|---|---:|---:|---:|---:|---:|
| `sd_jsonschema_1145_pointer` | 1383 | 1386 | +3 | 0.22% | 4.0% |
| `sd_networkx_gexf448_slices` | 1065 | 1069 | +4 | 0.38% | 6.6% |
| `sd_pygments_bbcode64_color` | 108 | 122 | +14 | 12.96% | 25.4% |
| `sd_pygments_bbcode70_italic` | 108 | 115 | +7 | 6.48% | 21.7% |
| `sd_pygments_groff73_italic` | 170 | 180 | +10 | 5.88% | 17.2% |
| `sd_pygments_latex297_italic` | 521 | 545 | +24 | 4.61% | 8.1% |
| `sd_pygments_style95_cache` | 203 | 216 | +13 | 6.40% | 30.1% |
| `sd_tabulate_1052_strip_right` | 2716 | 2719 | +3 | 0.11% | 1.0% |
| `sd_tabulate_1056_strip_center` | 2716 | 2720 | +4 | 0.15% | 1.0% |
| `sd_tabulate_2557_curlen` | 2716 | 2720 | +4 | 0.15% | 4.2% |

**口径提醒**：本数据集的 PUBLIC 源码是“目标文件全文”（标记行置空），不是函数片段。因此 `PUBLIC 行数` 与 `原始文件行数` 只差 patch 插入的行（+3 到 +24 行，最大 12.96%），两者高度接近；真正约束算法搜索空间的是 A 所在函数与 U 块的规模，而不是文件总长度。逐题 `A 所在函数 / PUBLIC 行` 的中位数只有 7.4%。绝对不能把文件总行数当作“算法需要分析的代码量”或“题目的上下文长度”。

## 5. 分布

### 5.1 难度分布（本报告自定义口径）

| 难度 | 题数 | 题目 | 原始文件行（平均 / 中位） | PUBLIC A 函数 LOC（平均 / 中位） | A 上下文 LOC（平均） |
|---|---:|---|---:|---:|---:|
| easy | 7 | `sd_jsonschema_1145_pointer`, `sd_networkx_gexf448_slices`, `sd_pygments_latex297_italic`, `sd_pygments_style95_cache`, `sd_tabulate_1052_strip_right`, `sd_tabulate_1056_strip_center`, `sd_tabulate_2557_curlen` | 1617.1 / 1383.0 | 57.9 / 56.0 | 56.9 |
| medium | 1 | `sd_pygments_bbcode64_color` | 108.0 / 108.0 | 31.0 / 31.0 | 30.0 |
| hard | 2 | `sd_pygments_bbcode70_italic`, `sd_pygments_groff73_italic` | 139.0 / 139.0 | 28.0 / 28.0 | 27.0 |

观察：难度与文件大小**不同向**。两道 hard 题的文件只有 108–170 行，A 上下文 24–30 行；7 道 easy 题反而横跨 203–2716 行。用“文件行数”代理难度会得到错误结论。

### 5.2 机制分布

| 机制 | 题数 | 题目 | 原始文件行（平均 / 中位） | PUBLIC A 函数 LOC（平均 / 中位） |
|---|---:|---|---:|---:|
| M1_SINGLE_OPERATION | 2 | `sd_jsonschema_1145_pointer`, `sd_tabulate_1052_strip_right` | 2049.5 / 2049.5 | 41.5 / 41.5 |
| M2_TWO_OPERATION_COOPERATIVE | 1 | `sd_pygments_bbcode70_italic` | 108.0 / 108.0 | 25.0 / 25.0 |
| M3_THREE_OPERATION_COOPERATIVE | 1 | `sd_pygments_groff73_italic` | 170.0 / 170.0 | 31.0 / 31.0 |
| M4_ALTERNATIVE_PATHS | 1 | `sd_pygments_bbcode64_color` | 108.0 / 108.0 | 31.0 / 31.0 |
| M5_CONDITIONAL_BRANCH | 1 | `sd_tabulate_1056_strip_center` | 2716.0 / 2716.0 | 28.0 / 28.0 |
| M6_CROSS_FUNCTION_STATE | 1 | `sd_pygments_latex297_italic` | 521.0 / 521.0 | 44.0 / 44.0 |
| M7_LOOP_STATE | 1 | `sd_tabulate_2557_curlen` | 2716.0 / 2716.0 | 114.0 / 114.0 |
| M8_OBJECT_SHARED_STATE | 1 | `sd_networkx_gexf448_slices` | 1065.0 / 1065.0 | 71.0 / 71.0 |
| M9_EXCEPTION_FALLBACK | 1 | `sd_pygments_style95_cache` | 203.0 / 203.0 | 65.0 / 65.0 |

### 5.3 项目分布

| 项目 | 题数 | 原始文件行（平均 / 中位） | AST 可干预操作（平均 / 范围） |
|---|---:|---:|---:|
| Pygments | 5 | 222.0 / 170.0 | 3.2 / 0–8 |
| jsonschema | 1 | 1383.0 / 1383.0 | 2.0 / 2–2 |
| networkx | 1 | 1065.0 / 1065.0 | 6.0 / 6–6 |
| tabulate | 3 | 2716.0 / 2716.0 | 3.0 / 2–4 |

### 5.4 其他计数

- 10 题原始文件行数合计 **11706**，PUBLIC 源码合计 **11792**，patch 共追加 **86** 行。
- AST 可干预操作合计 **33**，逐题范围 0–8，中位 2.5。
- 声明候选全集 U 合计 **14** 个操作；单题 1–3 个。
- PUBLIC 源码空行合计 **1700**，纯注释 **662**，行内注释 **148**。

## 6. 数据质量备注（只登记，不改动题目）

### 6.1 `task.json` 函数名与 A 的实际所属函数

以下 3 题的 `target_operation.function` 指向 A 所在外层函数内部的一个嵌套辅助函数，A 本身不在该嵌套函数内。统计时同时保留两个度量：

| 题目 | task.json 声明 | 原始 A 实际所属函数 | 声明函数 LOC | 实际函数 LOC |
|---|---|---|---:|---:|
| `sd_networkx_gexf448_slices` | `edge_key_data` | `add_edges` | 23 | 67 |
| `sd_pygments_latex297_italic` | `rgbcolor` | `_create_stylesheet` | 6 | 44 |
| `sd_pygments_style95_cache` | `colorformat` | `__new__` | 14 | 65 |

其余 7 题两者一致。本报告不修改 `task.json`；发布时若需要单一“目标函数”口径，应以 AST 实际所属函数为准，或同时披露两者。

### 6.2 `provenance.patched_sha256` 与落盘证据不一致

10/10 题的 `evidence/<case>/patched/<basename>` 的 SHA-256 都与 `provenance.patched_sha256` 不同；而 10/10 题的原始文件哈希与其 `source_file_sha256` 完全一致。对 patched 文件改用结构校验后全部通过：(a) A 行原文保留；(b) `patch.diff` 的 `+` 行有序删除后逐行重构出原始文件；(c) `+` 行数 = patched 与 original 的行数差。因此本报告的规模统计基于落盘且被算法实际读取的 patched 文件，不受该哈希字段影响；但该字段应在后续版本中修正或移除。

### 6.3 冻结发现器漏检

`sd_pygments_style95_cache` 的 AST 可干预操作为 **0**：冻结的 `ast_discovery.discover` 在该 PUBLIC 源码上没有返回任何候选操作，而题目本身有 1 个声明候选 U1。该题仍通过独立验收，但依赖“固定候选规则”的方法在这道题上无法从源码发现任何可干预点。

## 7. 字段说明（`results/source_derived_code_size.csv`）

| 字段 | 含义 |
|---|---|
| `case_id` | 题目 id |
| `project / version` | 上游项目与版本 |
| `mechanism` | 数据集声明的机制标签 |
| `difficulty_tier` | 本报告自定义难度分级（easy/medium/hard） |
| `orig_file_lines` | 原始上游目标文件物理行数 |
| `public_file_lines` | 交给算法的 PUBLIC 源码物理行数（标记行置空） |
| `patch_added_lines` | patch.diff 新增行数 |
| `orig_file_code_lines` | 原始文件非空非纯注释行数 |
| `public_code_lines` | PUBLIC 源码非空非纯注释行数 |
| `declared_function` | task.json 声明的目标函数名 |
| `orig_declared_func_loc` | 声明函数在原始文件中的 AST 行跨度 |
| `orig_declared_func_code_lines` | 声明函数在原始文件中的代码行数 |
| `orig_enclosing_func_name` | A 在原始文件中实际所属函数名 |
| `orig_enclosing_func_loc` | A 在原始文件中实际所属函数的 AST 行跨度 |
| `public_enclosing_func_name` | A 在 PUBLIC 源码中实际所属函数名 |
| `public_enclosing_func_loc` | A 在 PUBLIC 源码中实际所属函数的 AST 行跨度 |
| `public_enclosing_func_code_lines` | 该函数的代码行数 |
| `declared_matches_enclosing` | 声明函数名是否等于实际所属函数名 |
| `a_line` | A 的 1-based 行号（原始与 patched 相同） |
| `a_pre_context_loc / a_post_context_loc / a_context_loc` | A 前 / 后 / 合计上下文行数 |
| `functions_in_file` | PUBLIC 文件内函数节点总数 |
| `functions_involved` | 覆盖 A 或任一 U 块正文的函数节点数 |
| `functions_involved_names` | 上述函数名（分号分隔） |
| `ast_intervention_ops` | 冻结 AST 发现规则返回的候选操作数 |
| `declared_u_size` | reference.json 的候选全集大小 |
| `declared_inputs` | 声明的输入个数 |
| `public_blank_lines` | PUBLIC 源码空行数 |
| `public_comment_only_lines` | PUBLIC 源码纯注释行数 |
| `public_inline_comment_lines` | PUBLIC 源码含行内注释的行数 |
| `public_comment_lines_total` | 纯注释 + 行内注释 |
| `orig_blank_lines / orig_comment_only_lines / orig_inline_comment_lines / orig_comment_lines_total` | 原始文件对应计数 |
| `data_quality_notes` | 该题登记的元数据异常 |
