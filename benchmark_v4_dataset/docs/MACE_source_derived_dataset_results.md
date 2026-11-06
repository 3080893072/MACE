# MACE 真实源码最小改造与扩展任务：第一批结果

- 日期：2026-11-04
- 范围：`benchmark_v4_dataset/source_derived/`（DEV）
- 结论：第一批 10 个候选全部通过验收，**合格 10 道、失败 0 道**。
  全部属于 `SOURCE_DERIVED_CONTROLLED`（轨迹 C），标记
  `RESEARCHER_CONSTRUCTED = true`，**不得当作自然缺陷题目**使用。
- 未改动：MACE 核心算法、Graph 搜索器、Qwen Prompt/接口、V3 冻结数据、
  HIDDEN 答案与评分器均未修改；HELDOUT 源码与测试未被读取或改动；未使用 GPU。

---

## 1. 计数口径（四类数量分开报告）

| 类别 | 数量 | 说明 |
|---|---|---|
| 题目数（本批 source-derived） | **10** | 全部通过独立验收（AC9 等价检查） |
| 其中协同掩盖（MSMS 大小 ≥ 2） | **2** | 二元协同 1 道、三元协同 1 道 |
| 自然题目（V4-DEV，AC1–AC12） | 1 | `tabulate_numparses_header_wrap`，本批未新增 |
| Source-preserving（轨迹 B） | 0 | 本轮无一通过验收，见 §7 |
| V3 冻结参考题 | 5 | 只读，不计入 V4 题目数 |
| 原始测试数 `T_task` | 191（去重后的通过测试项；两题共用 `test_output.py`，重复执行计 349 次） | 6 题有覆盖测试；4 题项目本身无对应测试 |
| 声明输入数 | 38 | mask 15 / expose 10 / control 13 |
| 操作关系数 | 见 §4 | 独立 8、协同 2、替代路径 1 |

“候选数 / 探针行数 / U 中操作数”均未计入题目数。

## 2. 数据集划分

- 全部 10 题位于 **V4-DEV**，所在项目（tabulate、Pygments、networkx、jsonschema）
  均不在此前封存的 `HELDOUT_BROAD` 12 项目清单内（已核对
  `discovery/manifest/seal_heldout_broad.json`）。
- V4-HELDOUT 未开封：未读取其源码、未运行其测试、未生成任何候选。

## 3. 构造规则（每题一致）

1. **A 是真实上游语句**：从 PyPI sdist 解包后的原始文件逐字定位，记录
   sdist URL、SHA-256、文件:行、原始行文本。
2. **删除方式**：将 A 行替换为等缩进的
   `pass  # P-: target A deleted`，行号保持不变。
3. **补丁只插入、不替换**：U 操作块以
   `# SD:U:<id>:begin/end` 注释界定，插入到显式锚点之后；补丁不得覆盖 A。
4. **U 与 A 的偏序关系**：U 在 P+ 上必须幂等/守卫化（`startswith`、`setdefault`、
   `findall`、缓存成员判断、重新 strip 等），保证 P+ 观察值不被补丁改变；
   同时 U 只覆盖部分输入域，使“合法暴露输入”存在（满足 AC5）。
5. **全部关系通过程序干预证明**：枚举 U 的全部子集，逐子集运行 probe；
   MSMS 由“恢复 P+ 观察值”的子集族取极小元得到，而不是由设计意图宣布。
6. **独立验收**：`tools/sd_acceptance.py` 不复用 `tools/sd_harness.py` 的任何构造代码
   （重新解包 sdist、独立组装补丁、独立扫描块边界、位掩码枚举、`runpy` 启动 probe），
   重算全部子集结果并与构造报告逐项比对。

### 3.1 为什么每题都需要“部分守卫”

若 U 能完全补偿 A，则 P− 在所有输入上都等于 P+，AC5（暴露 witness）无法成立。
因此每题都构造了一个**声明的修复域**：域内输入被掩盖，域外的合法输入暴露。
这一偏序关系在 `task.json` 的 `construction_rationale` /
`masking_conditions` 中逐题写明。

## 4. 九类机制覆盖

| 机制 | 题数 | 题目 | MSMS |
|---|---|---|---|
| M1 单操作独立掩盖 | 2 | `sd_tabulate_1052_strip_right`、`sd_jsonschema_1145_pointer` | 1 |
| M2 二操作协同 | 1 | `sd_pygments_bbcode70_italic` | 2 |
| M3 三操作协同 | 1 | `sd_pygments_groff73_italic` | 3 |
| M4 多路替代掩盖 | 1 | `sd_pygments_bbcode64_color` | 1（两个不同的单元素极小集） |
| M5 条件分支掩盖 | 1 | `sd_tabulate_1056_strip_center` | 1 |
| M6 跨函数状态掩盖 | 1 | `sd_pygments_latex297_italic` | 1 |
| M7 循环状态掩盖 | 1 | `sd_tabulate_2557_curlen` | 1 |
| M8 对象/共享状态掩盖 | 1 | `sd_networkx_gexf448_slices` | 1 |
| M9 异常回退掩盖 | 1 | `sd_pygments_style95_cache` | 1 |

协同判定依据严格子集枚举：M2 中 `{U1}`、`{U2}` 均不能恢复相等，只有
`{U1,U2}` 可以；M3 中 6 个真子集全部不能恢复相等，只有 `{U1,U2,U3}` 可以
（表见 `reference.json` 的 `minimality.subsets`）。
M4 的两个单元素极小集分别对应“增量前置”与“重排重建”两条替代路径，
因此该题 `u_necessary = false`，这是替代路径机制的正确结果，而不是缺陷。

## 5. 逐题清单

| # | 题目 | 项目@版本 | 文件:行 | A（原文） | 机制 | U | MSMS | 暴露输入 | 原始测试（P+ 结果） |
|---|---|---|---|---|---|---|---|---|---|
| 1 | sd_tabulate_1052_strip_right | tabulate@0.9.0 | tabulate/__init__.py:1052 | `strings = [s.strip() for s in strings]` | M1 | 1 | [U1] | expose_tabs | test/test_output.py（158 passed, 19 skipped） |
| 2 | sd_tabulate_1056_strip_center | tabulate@0.9.0 | tabulate/__init__.py:1056 | `strings = [s.strip() for s in strings]` | M5 | 1 | [U1] | expose_alpha | test/test_output.py（158 passed, 19 skipped） |
| 3 | sd_tabulate_2557_curlen | tabulate@0.9.0 | tabulate/__init__.py:2557 | `cur_len -= self._len(cur_line[-1])` | M7 | 1 | [U1] | expose_three_lines | test/test_textwrapper.py（8 passed, 3 skipped） |
| 4 | sd_pygments_bbcode70_italic | Pygments@2.17.2 | pygments/formatters/bbcode.py:70 | `end = '[/i]' + end` | M2 | 2 | [U1,U2] | expose_italic_color | 无（发行版无 bbcode 测试） |
| 5 | sd_pygments_bbcode64_color | Pygments@2.17.2 | pygments/formatters/bbcode.py:64 | `end = '[/color]' + end` | M4 | 2 | [U1] / [U2] | expose_color_underline | 无（发行版无 bbcode 测试） |
| 6 | sd_pygments_groff73_italic | Pygments@2.17.2 | pygments/formatters/groff.py:73 | `end = regular + end` | M3 | 3 | [U1,U2,U3] | expose_italic_nonmono | tests/test_groff_formatter.py（2 passed） |
| 7 | sd_pygments_latex297_italic | Pygments@2.17.2 | pygments/formatters/latex.py:297 | `cmndef += r'\let\$$@it=\textit'` | M6 | 1 | [U1] | expose_full_italic | tests/test_latex_formatter.py（3 passed） |
| 8 | sd_pygments_style95_cache | Pygments@2.17.2 | pygments/style.py:95 | `_styles[token] = ndef` | M9 | 1 | [U1] | expose_keyword | 无（无直接覆盖 style_for_token 的测试） |
| 9 | sd_networkx_gexf448_slices | networkx@3.2.1 | networkx/readwrite/gexf.py:448 | `edge_data = self.add_slices(edge_element, edge_data)` | M8 | 1 | [U1] | expose_directed_slices | networkx/readwrite/tests/test_gexf.py（20 passed, 1 skipped） |
| 10 | sd_jsonschema_1145_pointer | jsonschema@4.20.0 | jsonschema/validators.py:1145 | `part = part.replace("~1", "/").replace("~0", "~")` | M1 | 1 | [U1] | expose_tilde1 | 无（无直接覆盖 resolve_fragment 的测试） |

9 道题另有 1–2 条控制输入（A 在该输入上不执行，或执行后无可观察差异），
控制输入上“空集即掩盖”（`empty_kept_masks = true`），与 §3.1 的退化掩盖
排除一致，**不计为掩盖证据**。

例外：`sd_pygments_style95_cache` 没有控制输入。该题的 A 位于 Style 元类的
类构造循环中，`STANDARD_TYPES` 的每个 token 在类定义时必然经过 A；删除 A 后
`_styles` 为空，任何查询都会 KeyError，必须由 U1 兜底才能观察到任何结果。
因此不存在“A 不执行且空集即可相等”的输入。该题按 AC8 的替代条件处理：
**不声明任何前置关系**，并在 `reference.json` 的 `not_claimed` 中记录。

## 6. 验收证据

每题目录 `source_derived/tasks/<case_id>/`：

- `task.json`：题目陈述、A、删除方式、合法输入契约、声明输入、原始测试、范围声明；
- `reference.json`：U、逐输入 P+/P−、MSMS/MMBS、严格子集表、`not_claimed`；
- `provenance.json`：sdist URL/SHA-256、源码/补丁 SHA-256、venv、证据与验收指针；
- `patch.diff`：仅插入的 unified diff（独立校验“补丁未删除 A 行”）；
- `acceptance.json`：独立验收报告（逐项 checks + 重算的 MSMS）。

独立验收对每题执行以下检查（全部为 true 才合格）：

| 检查 | 含义 |
|---|---|
| `AC1_sdist_matches_discovery` / `AC1_evidence_matches_source` / `AC1_A_line_text` | 从 sdist 重新解包的源码与证据逐字节一致；A 行文本一致 |
| `patch_preserves_A` / `patch_only_inserts` / `patch_diff_does_not_remove_A` | 补丁只插入、A 行未被替换 |
| `U_blocks_outside_A` / `P_minus_only_deletes_A` | U 块不与 A 重叠；P− 只改 A 行 |
| `enumeration_agrees` | 独立重算的子集枚举与构造报告逐项一致 |
| `masking_inputs_satisfied` | P+=P−、非空 MSMS、无空集掩盖 |
| `exposing_inputs_satisfied` | P+≠P−（A 的局部作用可观察） |
| `control_inputs_satisfied` | 控制输入上 P+=P− |
| `u_necessary_in_minimal_sets` | 每个极小集中去掉任一操作即失效（M4 按构造为 false，单列） |

结果：10/10 题 `all_checks_pass = true`，0 项失败。

原始测试（P+ 树）结果：6 题有覆盖测试且全部通过；4 题上游发行版本身没有
覆盖该路径的测试，已在 `test_map.json` 与 `evidence/original_test_suite.json`
中如实记录（`passed: null`），**未用 DESIGNED 测试替代原始测试**。

## 7. 失败与未采用案例

本批 10 个构造候选全部合格，失败数为 0。构造过程中主动放弃的案例及原因：

| 案例 | 放弃原因 |
|---|---|
| simplejson `decoder.py:200`（`end = end[:-1]`） | 完全冗余：所有测试输入上删除 A 后输出不变，找不到任何合法暴露输入（AC5 不成立） |
| toml `encoder.py:96`（`v = v.replace(...)`） | 只能靠“引号内容”构造部分性，暴露/掩盖边界依赖字符串字面量细节，解释力弱，未采用 |
| V3/V4 既有 P− 幸存者中的若干 | 只有“测试在 P− 下通过”，无法建立 P+=P− 且非空 S 的掩盖关系（§3.1 退化掩盖） |
| 轨迹 B（source-preserving） | 本轮检查的候选要么没有合法暴露输入，要么新增输入无法证明构成对 A 的真实补偿，**0 道合格** |

上述放弃记录用于说明“未通过验证的题必须拒绝”，不是题目数的一部分。

## 8. 未声明事项与风险

- 本批全部为**研究者构造**：A 是真实语句，但“删除 A”是人为操作，不代表上游存在缺陷。
- 不声明覆盖声明输入之外的输入，也不声明 U 之外的任何操作关系。
- AC3/AC4/AC10 是自然题目（轨迹 A）的条件；轨迹 C 只要求“原始版本 + 补丁 +
  修改理由 + 执行证据”，本批不冒充自然题目满足 AC3/AC4。
- 原始测试覆盖不足的 4 题（bbcode×2、style、jsonschema）其删除风险在于：
  上游测试完全无法发现该删除；这一事实本身正是题目价值，但**不能**据此
  声称上游有 bug。
- 所有题目仅在 DEV；未对 HELDOUT 做任何结果驱动的重筛或改动。

## 9. 复现

```bash
# 构造 + 子集枚举（写出 evidence/）
python -I benchmark_v4_dataset/tools/sd_harness.py \
    --case benchmark_v4_dataset/source_derived/cases/<case>.json

# 独立验收（不复用构造代码）
python -I benchmark_v4_dataset/tools/sd_acceptance.py \
    --case benchmark_v4_dataset/source_derived/cases/<case>.json

# 原始测试（P+ 树）
python -I benchmark_v4_dataset/tools/sd_suite_check.py

# 生成题目包与统计
python -I benchmark_v4_dataset/tools/sd_build_tasks.py
python -I benchmark_v4_dataset/tools/sd_build_reports.py
```

产物：

- `results/MACE_source_derived_inventory.csv`
- `results/MACE_source_derived_statistics.json`
- `registry/source_derived_accepted.json`（与自然题目的 `registry/accepted.json` 分开登记）
- `source_derived/tasks/<case_id>/`（10 个题目包）
- `source_derived/evidence/<case_id>/`（原始文件、补丁文件、diff、子集枚举）
- `source_derived/acceptance/<case_id>.json`（独立验收）
- `source_derived/evidence/original_test_suite.json`（P+ 原始测试结果）
