# MACE v2.1 — 真值与评分一致性核查

**范围**：只读离线核查。不调用 Qwen / GLM，不执行 MACE，不重跑探针，不改动任何既有结果、benchmark 或 HELDOUT seal。
**日期**：2026-11-05
**对象**：`run_candidate_discovery_v2_1.py` 使用 `source_derived`（旧 SD）而非 `source_derived_v2_1` 的完整影响。

---

## 0. 结论摘要

| 问题 | 结论 |
|---|---|
| 旧 SD 路径是否只影响 role？ | **不是只有 role。** role 有 2 处差异；MMBS 有 7/25 处差异；但 MSMS、执行源码、探针、block span、候选映射在 21 题上**全部一致**。 |
| 是否还有 MSMS / 执行来源不一致？ | **MSMS：没有**（25 个 scoring 输入逐项相同）。**执行来源：没有**（补丁文本 21/21 相同、探针 21/21 相同、`line_map`/`U` 21/21 相同）。**MMBS：有 7/25**，但 MMBS 不进入任何评分函数。 |
| 13/25、18/25 能否作为正式 v2.1 DEV 结果？ | **可以**，但只能表述为"21 题主队列、按 v2.1 role 重评分"。全 25 题 DEV（含 4 个 v2 复用题）是另一套混合来源的数字，不能混用。 |
| Direct GLM 5/25 是否同输入集/同评分语义？ | **是。** 25 个 masking 输入 ID 逐一相同；`score_sets` 与 `project_containment` 逻辑相同；spans 的 `line_map` 相同；MSMS GT 相同。 |
| 需要重跑还是离线重评分？ | **只需离线重评分。** 预测与探针结果都不变；被剔除的 2 个输入只是 role 口径问题。 |
| HELDOUT 如何保证用对 v2.1 路径？ | 新建 HELDOUT runner，显式指向 `source_derived_v2_1/heldout`，并加断言；**不要改冻结的 DEV runner / frozen config**。 |

---

## 1. 旧 SD 路径的静态影响面

### 1.1 读取点清单

| 读取点 | 代码位置 | 读取内容 | 影响的环节 | 与 v2.1 实测差异 |
|---|---|---|---|---|
| `SD` 常量 | `benchmark_v4_dataset/tools/sd_algorithm_pilot.py:40` | `DS / "source_derived"` | 下列全部读取的根 | 路径错，内容见下列各行 |
| `SD` 导入绑定 | `scripts/run_candidate_discovery_v2_1.py:43-46` | `from sd_algorithm_pilot import SD` | 运行期绑定为**独立名字** | 运行后改 `sd_algorithm_pilot.SD` 不会回写 `cd21.SD` |
| 任务规格 | `run_candidate_discovery_v2_1.py:1026` | `SD/cases/<cid>.json`：`inputs` 顺序、`base.file`、`A_line`、`A_code`、`probe` 路径 | 输入枚举、候选生成、探针执行 | **21/21 语义相同**（10 个文件仅 CRLF 字节差异） |
| 补丁源码 | `:1028` | `SD/evidence/<cid>/patched/<file>` | AST、执行、prompt | **21/21 文本相同**（见 1.3） |
| 项目根 | `:1036` | `DS/discovery/<root>`（非 SD） | 执行沙箱 | 共享，相同 |
| 探针脚本 | `:1037` | `KIT / spec["probe"]` → `source_derived/probes/...` | 探针执行 | **21/21 文本相同** |
| 枚举 | `:979`（C0 baseline）、`:1272`（主链） | `SD/evidence/<cid>/enumeration.json` 的 `line_map` | block spans → 候选映射 → MSMS 判定 | **21/21 `line_map`、`U`、`patched_sha256` 相同** |
| 隐藏参考·正式分支 | `:942` | `SD/tasks/<cid>/reference.json` | role / MSMS | 6 个任务走此分支 |
| 隐藏参考·回退分支 | `:945-958` | `SD/acceptance/<cid>.json` 的 `per_input` 推导 | role / MSMS | 15 个任务走此分支；2 个 control 在此被误判为 masking |
| 参考进入评分 | `:1271`、`:994` | `reference["inputs"][key]` 的 `role` / `msms` | 分母与 exact | 25 个 masking 全一致；2 个 control 被多算 |
| C0 基线计分 | `:980`、`:993-1000` | 同上 | C0 分母与 exact | 同上 |
| 收尾统计 | `scripts/finalize_candidate_discovery_v2_1.py:25,66,67` | `reference_for` + enumeration | `reference_masking_inputs`、`target_blocks`（novel 统计） | 分母含 2 个 control；`target_blocks` 不受影响 |
| 分析脚本 | `scripts/analyze_candidate_discovery_v2_1.py:19,63` | 枚举 `line_map` | 描述性统计 | 相同 |

**结论**：旧路径的影响面是 **role → 分母**，加上 **MMBS 字段缺失/取值不同**；它**没有**改变候选生成、探针执行、源码加载或 MSMS 判定。

### 1.2 模型侧与真值侧的分离

`run_candidate_discovery_v2_1.py` 在 `1268` 行之前只使用公开信息（cases、patched、C0 universe、探针）；`reference_for()` 与 `enumeration` 在 `1271-1273` 才被读取。因此 role 差异不可能"倒灌"到模型输出，只影响计分人口。

### 1.3 为什么 CRLF 差异不影响执行

`source_derived/` 与 `source_derived_v2_1/` 的补丁文件字节不同（前者 CRLF、后者 LF），但：

- 运行器用 `Path.read_text("utf-8")` 读取，Python 文本模式**自动把 CRLF 归一为 LF**；
- 21/21 题的 `read_text()` 结果**逐字符相同**；
- 21/21 题记录下来的 `public_source_sha256` 与 **v2.1 文件**计算出的哈希**完全一致**（与旧文件原始字节计算出的哈希不一致）；
- 21/21 探针脚本 `read_text()` 结果相同；
- 21/21 题 `enumeration.patched_sha256` 在两边相同，且等于"归一化后补丁文件"的 SHA-256。

即：**实际执行的就是 v2.1 的内容**，`source_derived` 只是磁盘上的位置名不同。

---

## 2. 最终 21 题逐输入核对

### 2.1 总体

| 项 | 数量 |
|---|---|
| 任务 | 21 |
| 输入总数 | 68（masking 25 / exposing 21 / control 22，按 v2.1 role） |
| 运行中被计分的输入 | 27（= 25 masking + 2 被误判的 control） |
| role 不一致 | **2 / 68** |
| masking 输入的 MSMS 不一致 | **0 / 25** |
| masking 输入的 MMBS 不一致（旧 enumeration vs v2.1 formal） | **7 / 25** |
| control 输入的 MSMS 表示差异（`[[]]` vs `[]`） | 20 / 22（不计分，无语义影响） |
| 补丁/源码/探针/line_map 不一致 | **0 / 21** |

### 2.2 逐任务汇总

| task | inputs | masking(v2.1) | role Δ | MSMS Δ(masking) | MMBS Δ(masking) | patched_sha256 一致 | 影响 |
|---|---|---|---|---|---|---|---|
| `sd_attrs_asdict_loop_m7` | 2 | 1 | 0 | 0 | 0 | 是 | — |
| `sd_coverage_glob_backslash_m2` | 3 | 1 | 0 | 0 | 1 | 是 | — |
| `sd_docutils_backticks_m1` | 3 | 1 | 0 | 0 | 0 | 是 | — |
| `sd_docutils_educate_dashes_m2` | 3 | 1 | 0 | 0 | 1 | 是 | — |
| `sd_docutils_ellipsis_m3` | 3 | 1 | 0 | 0 | 1 | 是 | — |
| `sd_docutils_language_tag_m3` | 3 | 1 | 0 | 0 | 1 | 是 | — |
| `sd_docutils_make_id_lower` | 3 | 1 | 1 | 0 | 0 | 是 | 分母 −1 |
| `sd_docutils_make_id_nonid_m2` | 3 | 1 | 0 | 0 | 1 | 是 | — |
| `sd_docutils_smartquotes_strip_m1` | 3 | 1 | 0 | 0 | 0 | 是 | — |
| `sd_docutils_stupefy_emdash_m2` | 3 | 1 | 0 | 0 | 1 | 是 | — |
| `sd_docutils_stupefy_endash_m1` | 3 | 1 | 0 | 0 | 0 | 是 | — |
| `sd_humanize_filesize_gnu_m5` | 3 | 1 | 0 | 0 | 0 | 是 | — |
| `sd_isort_format_strip_m4` | 3 | 1 | 0 | 0 | 1 | 是 | — |
| `sd_jsonschema_1145_pointer` | 4 | 2 | 0 | 0 | 0 | 是 | — |
| `sd_networkx_adjlist_strip_m1` | 3 | 1 | 1 | 0 | 0 | 是 | 分母 −1 |
| `sd_pygments_latex297_italic` | 4 | 2 | 0 | 0 | 0 | 是 | — |
| `sd_pygments_style95_cache` | 4 | 3 | 0 | 0 | 0 | 是 | — |
| `sd_tabulate_1052_strip_right` | 4 | 1 | 0 | 0 | 0 | 是 | — |
| `sd_tabulate_1056_strip_center` | 4 | 1 | 0 | 0 | 0 | 是 | — |
| `sd_tabulate_2557_curlen` | 4 | 1 | 0 | 0 | 0 | 是 | — |
| `sd_toml_strict_num_strip_m1` | 3 | 1 | 0 | 0 | 0 | 是 | — |

### 2.3 两个已知 control 的逐项核对

**`sd_docutils_make_id_lower : control_lowercase`**

| 字段 | 运行所用 | v2.1 formal | 是否一致 |
|---|---|---|---|
| role | `masking`（acceptance 回退推导） | `control` | **否** |
| MSMS | `[["U1"]]` | `[["U1"]]` | 是 |
| MMBS | 参考对象中缺失 | `[["U1"]]`，COMPUTED | 字段缺失（不评分） |
| 补丁 / line_map / patched_sha256 | — | — | 是 |
| 运行中是否计分 | 是 | 不应计分 | **应剔除** |
| 该输入上 Full 的结果 | 非 exact | — | 剔除后 Full 分子不变 |
| 该输入上 C0 的结果 | 该题 C0 = 0/2 | — | 剔除后 C0 分子不变 |

**`sd_networkx_adjlist_strip_m1 : control_plain`**

| 字段 | 运行所用 | v2.1 formal | 是否一致 |
|---|---|---|---|
| role | `masking`（acceptance 回退推导） | `control` | **否** |
| MSMS | `[["U1"]]` | `[["U1"]]` | 是 |
| MMBS | 参考对象中缺失 | `[["U1"]]`，COMPUTED | 字段缺失（不评分） |
| 补丁 / line_map / patched_sha256 | — | — | 是 |
| 运行中是否计分 | 是 | 不应计分 | **应剔除** |
| 该输入上 Full 的结果 | **exact** | — | **剔除后 Full 分子 −1** |
| 该输入上 C0 的结果 | 该题 C0 = 2/2（两个输入都 exact） | — | **剔除后 C0 分子 −1** |

> 注意：两个 control 在 v2.1 里仍然带 `msms: [["U1"]]`（control 只表示"不作为 masking 评分"，不表示"没有可枚举的最小集"）。因此判定必须按 `role` 过滤，不能按 `msms` 是否为空过滤。

### 2.4 MMBS 的 7 处差异（仅记录，不影响分数）

| task | input | 旧 enumeration | v2.1 formal |
|---|---|---|---|
| `sd_coverage_glob_backslash_m2` | `mask_two_backslashes` | `[["U1","U2"]]` | `[["U1"],["U2"]]` |
| `sd_docutils_educate_dashes_m2` | `mask_two_triple` | `[["U1","U2"]]` | `[["U1"],["U2"]]` |
| `sd_docutils_ellipsis_m3` | `mask_three_ellipses` | `[["U1","U2","U3"]]` | `[["U1"],["U2"],["U3"]]` |
| `sd_docutils_language_tag_m3` | `mask_two_separators` | `[["U1","U2","U3"]]` | `[["U1"],["U2"],["U3"]]` |
| `sd_docutils_make_id_nonid_m2` | `mask_two_runs` | `[["U1","U2"]]` | `[["U1"],["U2"]]` |
| `sd_docutils_stupefy_emdash_m2` | `mask_two_emdashes` | `[["U1","U2"]]` | `[["U1"],["U2"]]` |
| `sd_isort_format_strip_m4` | `mask_padded` | `[["U1"],["U2"]]` | `[["U1","U2"]]` |

- 这是 MMBS 关系本身的差异（"联合最小" vs "分别最小"），不是格式问题。
- `score_sets()` 只读 `hidden["msms"]`，从不读 `mmbs`；`run_direct_glm_v2_1.py` 也只把 MMBS 记为 `None`（direct 协议不请求）。**因此 7 处差异对 C0/Full/GLM 的任何分数都没有影响。**
- 若论文要报告 MMBS，只能用 v2.1 formal 的 7 处值，且必须重新说明这些数字来自参考文件而不是本次运行。

### 2.5 逐输入全表（68 行）

> `MSMS`/`MMBS` 列的 `same/diff` 指"运行所用参考 vs v2.1 formal"。control 行的 `diff` 只表示表示法（`[[]]` vs `[]`），不是语义差异；masking 行全部 `same`。`patch 一致` 是 task 级结论（`enumeration.patched_sha256` + 归一化补丁文本 + 探针文本三者的逐题比对）；同一 task 的全部输入共用同一个补丁文件，因此该列对 68 个输入逐个成立。

| # | task | input | role(run→v2.1) | MSMS | MMBS status | MMBS legacy→v2.1 | patch 一致 | 运行中计分 | 影响 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `sd_attrs_asdict_loop_m7` | `mask_single_attr` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 2 | `sd_attrs_asdict_loop_m7` | `expose_two_attrs` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 3 | `sd_coverage_glob_backslash_m2` | `mask_two_backslashes` | masking | same | COMPUTED | diff | 是 | 是（exact） |  |
| 4 | `sd_coverage_glob_backslash_m2` | `expose_three_backslashes` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 5 | `sd_coverage_glob_backslash_m2` | `control_posix` | control | diff | NONE | diff | 是 | 否 |  |
| 6 | `sd_docutils_backticks_m1` | `mask_one_backtick` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 7 | `sd_docutils_backticks_m1` | `expose_two_backticks` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 8 | `sd_docutils_backticks_m1` | `control_plain` | control | diff | NONE | diff | 是 | 否 |  |
| 9 | `sd_docutils_educate_dashes_m2` | `mask_two_triple` | masking | same | COMPUTED | diff | 是 | 是（exact） |  |
| 10 | `sd_docutils_educate_dashes_m2` | `expose_three_triple` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 11 | `sd_docutils_educate_dashes_m2` | `control_plain` | control | diff | NONE | diff | 是 | 否 |  |
| 12 | `sd_docutils_ellipsis_m3` | `mask_three_ellipses` | masking | same | COMPUTED | diff | 是 | 是（exact） |  |
| 13 | `sd_docutils_ellipsis_m3` | `expose_four_ellipses` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 14 | `sd_docutils_ellipsis_m3` | `control_plain` | control | diff | NONE | diff | 是 | 否 |  |
| 15 | `sd_docutils_language_tag_m3` | `mask_two_separators` | masking | same | COMPUTED | diff | 是 | 是（exact） |  |
| 16 | `sd_docutils_language_tag_m3` | `expose_three_separators` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 17 | `sd_docutils_language_tag_m3` | `control_single_subtag` | control | diff | NONE | diff | 是 | 否 |  |
| 18 | `sd_docutils_make_id_lower` | `mask_ascii_mixed_case` | masking | same | COMPUTED | same | 是 | 是（非 exact） |  |
| 19 | `sd_docutils_make_id_lower` | `expose_non_ascii` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 20 | `sd_docutils_make_id_lower` | `control_lowercase` | **masking→control** | same | COMPUTED | same | 是 | 是（非 exact） | **是：应剔除却计分** |
| 21 | `sd_docutils_make_id_nonid_m2` | `mask_two_runs` | masking | same | COMPUTED | diff | 是 | 是（exact） |  |
| 22 | `sd_docutils_make_id_nonid_m2` | `expose_three_runs` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 23 | `sd_docutils_make_id_nonid_m2` | `control_no_runs` | control | diff | NONE | diff | 是 | 否 |  |
| 24 | `sd_docutils_smartquotes_strip_m1` | `mask_space_padding` | masking | same | COMPUTED | same | 是 | 是（非 exact） |  |
| 25 | `sd_docutils_smartquotes_strip_m1` | `expose_tab_padding` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 26 | `sd_docutils_smartquotes_strip_m1` | `control_unpadded` | control | diff | NONE | diff | 是 | 否 |  |
| 27 | `sd_docutils_stupefy_emdash_m2` | `mask_two_emdashes` | masking | same | COMPUTED | diff | 是 | 是（exact） |  |
| 28 | `sd_docutils_stupefy_emdash_m2` | `expose_three_emdashes` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 29 | `sd_docutils_stupefy_emdash_m2` | `control_plain` | control | diff | NONE | diff | 是 | 否 |  |
| 30 | `sd_docutils_stupefy_endash_m1` | `mask_one_endash` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 31 | `sd_docutils_stupefy_endash_m1` | `expose_two_endashes` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 32 | `sd_docutils_stupefy_endash_m1` | `control_plain` | control | diff | NONE | diff | 是 | 否 |  |
| 33 | `sd_humanize_filesize_gnu_m5` | `mask_gnu_positive` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 34 | `sd_humanize_filesize_gnu_m5` | `expose_gnu_negative` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 35 | `sd_humanize_filesize_gnu_m5` | `control_decimal` | control | diff | NONE | diff | 是 | 否 |  |
| 36 | `sd_isort_format_strip_m4` | `mask_padded` | masking | same | COMPUTED | diff | 是 | 是（exact） |  |
| 37 | `sd_isort_format_strip_m4` | `expose_tab_newline` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 38 | `sd_isort_format_strip_m4` | `control_plain` | control | diff | NONE | diff | 是 | 否 |  |
| 39 | `sd_jsonschema_1145_pointer` | `mask_tilde0` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 40 | `sd_jsonschema_1145_pointer` | `mask_nested_tilde0` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 41 | `sd_jsonschema_1145_pointer` | `expose_tilde1` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 42 | `sd_jsonschema_1145_pointer` | `control_plain` | control | diff | NONE | diff | 是 | 否 |  |
| 43 | `sd_networkx_adjlist_strip_m1` | `mask_space_padding` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 44 | `sd_networkx_adjlist_strip_m1` | `expose_tab_padding` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 45 | `sd_networkx_adjlist_strip_m1` | `control_plain` | **masking→control** | same | COMPUTED | same | 是 | 是（exact） | **是：应剔除却计分** |
| 46 | `sd_pygments_latex297_italic` | `mask_inline_italic` | masking | same | COMPUTED | same | 是 | 是（非 exact） |  |
| 47 | `sd_pygments_latex297_italic` | `mask_inline_italic_color` | masking | same | COMPUTED | same | 是 | 是（非 exact） |  |
| 48 | `sd_pygments_latex297_italic` | `expose_full_italic` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 49 | `sd_pygments_latex297_italic` | `control_inline_bold` | control | diff | NONE | diff | 是 | 否 |  |
| 50 | `sd_pygments_style95_cache` | `mask_text` | masking | same | COMPUTED | same | 是 | 是（非 exact） |  |
| 51 | `sd_pygments_style95_cache` | `mask_name_other` | masking | same | COMPUTED | same | 是 | 是（非 exact） |  |
| 52 | `sd_pygments_style95_cache` | `expose_keyword` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 53 | `sd_pygments_style95_cache` | `mask_operator_inherited` | masking | same | COMPUTED | same | 是 | 是（非 exact） |  |
| 54 | `sd_tabulate_1052_strip_right` | `mask_spaces` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 55 | `sd_tabulate_1052_strip_right` | `expose_tabs` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 56 | `sd_tabulate_1052_strip_right` | `control_plain` | control | diff | NONE | diff | 是 | 否 |  |
| 57 | `sd_tabulate_1052_strip_right` | `control_center` | control | diff | NONE | diff | 是 | 否 |  |
| 58 | `sd_tabulate_1056_strip_center` | `mask_numeric` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 59 | `sd_tabulate_1056_strip_center` | `expose_alpha` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 60 | `sd_tabulate_1056_strip_center` | `control_right_numeric` | control | diff | NONE | diff | 是 | 否 |  |
| 61 | `sd_tabulate_1056_strip_center` | `control_no_space` | control | diff | NONE | diff | 是 | 否 |  |
| 62 | `sd_tabulate_2557_curlen` | `mask_two_lines` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 63 | `sd_tabulate_2557_curlen` | `expose_three_lines` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 64 | `sd_tabulate_2557_curlen` | `control_line_fits` | control | diff | NONE | diff | 是 | 否 |  |
| 65 | `sd_tabulate_2557_curlen` | `control_no_max_lines` | control | diff | NONE | diff | 是 | 否 |  |
| 66 | `sd_toml_strict_num_strip_m1` | `mask_space_padded_leading_zero` | masking | same | COMPUTED | same | 是 | 是（exact） |  |
| 67 | `sd_toml_strict_num_strip_m1` | `expose_tab_padded_leading_zero` | exposing | same | NOT_SEPARABLE | same | 是 | 否 |  |
| 68 | `sd_toml_strict_num_strip_m1` | `control_plain_integer` | control | diff | NONE | diff | 是 | 否 |  |

---

## 3. 最终论文数字复核

### 3.1 冻结值 → v2.1 role 重算

| 指标 | 冻结记录（27 分母） | v2.1 role 重算（25 分母） | 差异来源 | 结论 |
|---|---|---|---|---|
| C0 exact | **14 / 27** | **13 / 25** | adjlist `control_plain` 在 C0 判 exact 且被计分 | 确认 |
| Full MACE exact | **19 / 27** | **18 / 25** | adjlist `control_plain` 在 Full 判 exact 且被计分 | 确认 |
| C0 false relations | **9** | **9** | 两个 control 的 false 均为 0 | 不变 |
| Full false relations | **5** | **5** | 两个 control 的 false 均为 0 | 不变 |
| Full unmatched sets | **2** | **2** | 不受影响 | 不变 |
| Full MSMS present | 20 | **19** | adjlist `control_plain` 的 present | 派生量，需同步 |
| Full probe count | **276** | **276** | 探针不因 role 改变 | 确认 |
| C0 probe count | — | **72** | 主跑 70 + closure 2 | 确认 |
| Full wall | **747.53 s** | — | role 不影响耗时 | 确认 |
| Full tokens | **157,227**（145,939 + 11,288） | — | 同上 | 确认 |
| Direct GLM（同 21 题队列） | — | **5 / 25**，false 51，unmatched 11 | 逐输入 ID 吻合 | 确认 |

### 3.2 C0 13/25 的推导（不依赖逐输入明细）

C0 没有保存逐输入结果（`scores/*.json` 的 `baseline` 只有计数）。但：

- `sd_networkx_adjlist_strip_m1`：C0 记 `masking_inputs = 2`、`msms_exact = 2` → 两个输入**都** exact → 剔除 `control_plain` 后为 1/1。
- `sd_docutils_make_id_lower`：C0 记 `masking_inputs = 2`、`msms_exact = 0` → 剔除 `control_lowercase` 后仍 0/1。

因此 14 − 1 = **13**，分母 27 − 2 = **25**。该推导只用到"每个输入最多贡献 1 个 exact"，不依赖哪一个是 control。

### 3.3 Full 18/25 的推导（有逐输入明细）

`runs/candidate_discovery_v2_1/scores/sd_networkx_adjlist_strip_m1.json` 的 `detail`：

- `mask_space_padding`：`msms_exact = true`
- `control_plain`：`msms_exact = true` ← 剔除

`sd_docutils_make_id_lower`：两个输入均 false，剔除 `control_lowercase` 不改变分子。

因此 19 − 1 = **18**。

### 3.4 Direct GLM 5/25 的同口径验证

- 输入集合：v2.1 21 题 masking 输入 25 个，GLM `detail[].input` 恰好覆盖这 25 个（无缺、无多）。
- 评分语义：`run_direct_glm_v2_1.py:116-132` 的 `score_sets` 与 `run_candidate_discovery_v2_1.py:922-936` 的 `score_sets` 在 `msms_exact` / `false_relations` / `unmatched_sets` 上逻辑相同（前者多返回 precision/recall）。
- spans：GLM 用 v2.1 enumeration，MACE 用旧 enumeration；21/21 题 `line_map` 相同。
- GT：两边都用 v2.1 formal MSMS；25/25 与运行参考相同。

**结论：5/25 与 13/25、18/25 可以直接并列。**

### 3.5 不能混淆的数字

- `9/30`（GLM 全 25 题 DEV）≠ `18/25`（MACE 21 题主队列）。
- `19/27`、`14/27` 是旧 role 口径，不应再出现在正文主表。
- 全 25 题 DEV 的 `all_dev_descriptive` 含 4 个 v2 复用题，文件内已标注"descriptive only"，不能作为方法主张的分母。

---

## 4. 六个问题的直接回答

### Q1. 旧 SD 路径是否只影响 role？

**否。** 影响面分三层：

1. **role**：2 个输入（`make_id_lower:control_lowercase`、`adjlist:control_plain`）被旧 acceptance 回退逻辑判为 masking。
2. **MMBS**：15 个 acceptance 回退任务的参考对象**根本没有 `mmbs` 字段**；另有 7 个 masking 输入的 MMBS 取值与 v2.1 formal 不同（见 2.4）。
3. **其余全部一致**：cases、补丁源码、探针、`line_map`/`U`、候选 universe、MSMS（25/25）。

### Q2. 是否还有 MSMS / MMBS 或程序执行来源不一致？

- **MSMS：没有。** 25 个计分输入的 MSMS 逐一相同；control 的 `[[]]` vs `[]` 只是空集表示法，且不计分。
- **MMBS：有。** 7/25 取值不同；15/25 在运行参考中缺失（旧 enumeration 里其实存在，但不被 `reference_for` 读取）。MMBS 不进入任何评分。
- **程序执行来源：没有。** 补丁文本、探针脚本、执行行号、block 边界全部一致；记录下来的 `public_source_sha256` 与 v2.1 文件一致（21/21）。

### Q3. 13/25、18/25 能否作为正式 v2.1 DEV 结果？

**能，但必须带限定词。** 正确表述是：

> "21-task v2.1 primary DEV subset, re-scored under the formal v2.1 input roles: C0 13/25, Full MACE 18/25."

依据：25 个 masking 输入的 role、MSMS、源码、探针、block 映射与 v2.1 完全一致；被剔除的只有 2 个 v2.1 定义为 control 的输入，且它们不改变任何预测。

不应表述为"全 25 题 DEV"——全 25 题包含 4 个未在 v2.1 重跑的 v2 复用题；按 `MACE_v2_1_dev_final.json` 的 `all_dev_descriptive`，全 25 题为 **22/32**（masking 输入 32 = 27 + 5），文件内已标注 descriptive only。

### Q4. Direct GLM 5/25 是否与两种 MACE 方法使用完全相同的输入集合及评分语义？

**是。**

- 同 21 题、同 25 个输入 ID（逐一核对）。
- 同 `project_containment` + block-family strict scoring。
- 同 MSMS GT（v2.1 formal）。
- 同 `line_map`（因此 spans 相同）。
- 唯一差异是 GLM 用 v2.1 enumeration 而 MACE 用旧 enumeration，但两者 `line_map` 逐题相同。

### Q5. 现有 DEV 结果是否需要重新运行，还是只需离线重新评分？

**只需离线重新评分。**

- 模型输出、候选集合、探针执行全部不依赖被改动的字段。
- 只需把 2 个 control 从分母和分子中剔除：Full 用 `scores/*.json` 的逐输入明细；C0 用"2/2 全 exact"的计数推出减 1。
- 本轮**没有**生成新的结果文件；建议在论文里用派生汇总表述，不动 `MACE_v2_1_dev_final.json`。

### Q6. 在不破坏冻结结果的条件下，如何保证后续 HELDOUT 使用正确的 v2.1 数据加载路径？

见 §6。核心三点：**新脚本、显式 root、强制断言**。

---

## 5. 未修改声明与证据哈希

本轮只新建了本文件；未覆盖、删除或改写任何既有结果、benchmark、seal。所有哈希在本轮重新计算，并与文件内嵌哈希交叉核对一致。

| 文件 | SHA-256 |
|---|---|
| `results/MACE_v2_1_dev_final.json` | `5094ea44a16907665aab284dcf842ed67103ce1cb29ab686ab5f9e101ee3deb5` |
| `results/MACE_v2_1_frozen_config.json` | `8de843b2c32f9ab7b7b03e1da0c2f6cf31bfdf5ea70b357c323f4ef38879edec` |
| `results/MACE_candidate_discovery_v2_1_dev.json`（pre-closure） | `814b71f7cdf2f4e6c45027bde1d427cfcd8c0ddbca76dde7385639311bdeed18` |
| `runs/candidate_discovery_v2_1/results.json` | `c3322818eb2f0e0953bd452458716048519f2d309bba288afe268a371c48340f` |
| `runs/candidate_discovery_v2_1_closure/results.json` | `9be17d13da35f8e02ba3125cff0398deabdb46727b66e562d17928108f7c31a0` |
| `results/MACE_direct_GLM_v2_1_dev.json` | `c12a590eafc7925d9290cd4e631ba7f0252f2e0da376c9006b12e3fc4e65a6f8` |
| `results/MACE_direct_GLM_v2_1_heldout_predictions.json` | `b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f` |
| `benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json` | `482e67a61585196e0c06e2312b90425eb7746864d0cf40400fd089df99a0c0e9` |

补充说明：

- `results/MACE_v2_1_frozen_config.json` 的 `heldout_seal` 指向 `benchmark_v4_dataset/split/seal.json`（`070b8d53…`），**不是** v2.1 HELDOUT seal（`482e67a6…`）。做 HELDOUT 时必须显式使用后者。
- 本轮**未打开任何 HELDOUT `reference.json`**，未评分，未解封。

---

## 6. HELDOUT 的正确加载路径（建议方案，本轮不实施）

### 6.1 事实

- v2.1 的 HELDOUT 数据在 **`benchmark_v4_dataset/source_derived_v2_1/heldout/`**，其下有独立的 `cases/`、`evidence/`、`probes/`、`tasks/`、`acceptance/`、`seal/`。
- `reference_for()` 只认两个位置：`SD/tasks/<cid>/reference.json`（正式）与 `SD/acceptance/<cid>.json`（回退）。25 个 HELDOUT id 在旧 DEV 路径的 `source_derived/tasks/`（只有 10 个旧正式参考）和 `source_derived/acceptance/` 里**都是 0/25**。因此用 `SD=source_derived` 跑 HELDOUT 会直接 `FileNotFoundError`，不会静默算错。
- 25 个 HELDOUT 的正式参考位于 `source_derived_v2_1/heldout/tasks/<cid>/reference.json`（存在性 25/25；本轮只检查路径存在，未打开内容）。因此 HELDOUT runner 的 root 必须是 `source_derived_v2_1/heldout`。
- **陷阱**：旧树也有 `source_derived/heldout/`（同样 25 个任务、同样的目录结构）。指向它会静默使用旧数据。必须断言 `SD` 的父目录名是 `source_derived_v2_1` 且 `SD.name == "heldout"`。
- **v2.1 的 case 文件里的 `probe` 字段指向旧树**：DEV 指 `source_derived/probes/...`，HELDOUT 指 `source_derived/heldout/probes/...`。当前两边探针脚本 21/21（DEV）与 25/25（HELDOUT）内容相同，但这是隐式依赖，必须在 HELDOUT runner 里显式校验或改写。
- 25 个 HELDOUT 任务的 `base.slug` 都能在 `benchmark_v4_dataset/discovery/stage0/projects.json` 找到，且 discovery root 25/25 存在——执行链可行。

### 6.2 建议实现

新建 `scripts/run_candidate_discovery_v2_1_heldout.py`（**不改**现有 DEV runner），启动时：

```python
import benchmark_v4_dataset.tools.sd_algorithm_pilot as sap
sap.SD = KIT / "benchmark_v4_dataset" / "source_derived_v2_1" / "heldout"

import scripts.run_candidate_discovery_v2_1 as cd21
cd21.SD = sap.SD          # 关键：import 时已绑定旧值，必须回写
```

并加入硬断言：

1. `cd21.SD.name == "heldout"` 且 `cd21.SD.parent.name == "source_derived_v2_1"`（防止误指向 `source_derived/heldout`）。
2. 每个任务 `SD/tasks/<cid>/reference.json` 存在；`reference_for` 必须走**正式分支**（在 `reference_for` 里加一个 `"_source"` 字段，断言 `"tasks" in source`），禁止 acceptance 回退。
3. `spec["probe"]` 指向旧树时，改写为 `source_derived_v2_1/heldout/probes/<name>`，并断言两文件 SHA-256（归一化后）相同；不同则直接失败，不静默使用。
4. 断言 `enumeration["patched_sha256"] == sha256(read_text(patched))`，防止补丁/枚举错配。
5. 输出目录用 `runs/candidate_discovery_v2_1_heldout/`、结果文件用 `results/MACE_v2_1_heldout_*.json`，**不得写入 DEV 路径**。
6. 新建 `results/MACE_v2_1_heldout_frozen_config.json` 记录新 runner/harness 哈希；**不要**覆盖 `MACE_v2_1_frozen_config.json`。
7. 预测阶段只写预测；评分阶段在解封后单独运行，读取 `heldout/tasks/<cid>/reference.json`，仍用 `score_sets` + `block_spans`。

### 6.3 顺序约束

- 四种方法（C0、Full、Direct Qwen、Direct GLM）的预测都冻结后，才能解封评分。
- 评分必须用 `heldout` 树的 `enumeration.line_map`；不要复用 DEV 的 spans 字典（虽然同源代码，但 HELDOUT 是独立文件）。
- 现有 `MACE_direct_GLM_v2_1_heldout_predictions.json` 已冻结（`b1815476…`），评分时只读不改。

---

## 7. 本轮核查方法（可复现）

1. **静态追踪**：`grep -n "SD"` 覆盖 `scripts/run_candidate_discovery_v2_1.py`、`finalize_candidate_discovery_v2_1.py`、`analyze_candidate_discovery_v2_1.py`、`benchmark_v4_dataset/tools/sd_algorithm_pilot.py`；逐函数确认读取点。
2. **树对比**：对 `source_derived/` 与 `source_derived_v2_1/` 逐文件 SHA-256；对差异文件再做 `read_text` 归一化比较与 AST/JSON 语义比较。
3. **逐输入核对**：以 `MACE_v2_1_dev_final.json` 的 21 个 `task_id` 为入口；对每个任务比较 `cd21.reference_for(cid)` 与 `source_derived_v2_1/tasks/<cid>/reference.json`；role/MSMS/MMBS 全部字段化。
4. **执行来源**：对比 `public_source_sha256`（运行记录）、`patched_sha256`（枚举）、归一化补丁文本、探针文本。
5. **数字复核**：从 `MACE_v2_1_dev_final.json`、`scores/*.json`、closure `results.json`、`MACE_direct_GLM_v2_1_dev.json` 求和；GLM 用 `detail[].input` 与 v2.1 masking 集合做 ID 级集合比较。
6. **未读 HELDOUT 参考**：只列了 `heldout/` 的目录名，以及 case 的 `probe` / `base.slug` 字段（公开任务规格）；未打开 `heldout/tasks/*/reference.json`、未打开 `heldout/acceptance/*.json`、未评分、未解封。

**本轮未运行任何模型、探针或 MACE 流程。**
