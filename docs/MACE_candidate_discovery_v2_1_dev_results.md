# MACE Candidate Discovery v2.1 — DEV 扩展评测

- 日期：2026-11-05
- 运行窗口：01:17:09–01:30:25（约 13.2 分钟，远早于 45 分钟硬截止）
- 模型：`qwen2.5-coder:32b`，Q4_K_M，digest `b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41`
- 推理参数：temperature 0，seed 42，`num_ctx=16384`，`num_predict=4096`，retries 0，每题 1 次调用
- 数据：`benchmark_v4_dataset/source_derived`，25 道 DEV 题中排除已被 v2 正式测过的 4 道，其余 21 道全部执行
- 对照：A = Role-separated C0；B = Full MACE + Candidate Discovery v2
- **未读取 HELDOUT；未修改数据集、标准答案、Prompt、C0 universe 或搜索预算；v2 结果未被覆盖。**

## 结论先行

1. **Qwen 确实在更多题上扩了 U**：13/21 题出现新候选，共 22 个新操作；其中 8 题的新候选至少有一个落在隐藏 MSMS 块内，5 题只新增了错误候选。
2. **但严格收益不是“全面碾压”**：21 题、25 个可评测 masking 输入上，严格 MSMS 从 C0 的 **12/25** 提升到 **17/25**；逐题看是 **6 题更好、12 题持平、1 题更差、2 题不可评测**。
3. **双操作/三操作协同是稳定收益**：M2 双操作 **4/4**，M3 三操作 **2/2**；加上冻结的 Groff 73，三操作协同模式在 v2 体系里是 **3/3**。M4 替代路径 **1/1**。
4. **失败仍集中在跨函数机制**：M6 跨函数状态 **0/2**，M9 异常回退 **0/3**。C0 和 Qwen 都停留在 A 所在函数，隐藏块在另一个方法里（latex 330–353、style95 126–138）。
5. **M1 有一个真实回退**：`smartquotes_strip` 从 C0 的 1/1 掉到 0/1；Qwen 多提的 line 277 是让 probe 能返回的“保活”操作，被严格评分记为 stray。
6. **两个 M5/M7 题因 harness 路径缺陷不可评测**（attrs、humanize）：两者都是 `src/` 布局，探针实际 import 了已安装包而不是 variant；已做一次定位，未重构，按规则标记 `INCOMPLETE`。
7. **建议**：值得在修好这一处 harness 缺陷后，进入一次 HELDOUT 确认；但不应宣称普遍优于 C0，收益主要集中在 M2/M3/M4 和“隐藏块是单行”的 M1 题。

---

## 1. 冻结与范围

| 项 | 状态 |
|---|---|
| Candidate Discovery v2 Prompt | 冻结；v2.1 runner 的 `build_prompt`/`map_token`/`collect_qwen`/`union_ops` 与 v2 完全一致（diff 无对应 hunk） |
| Qwen 32B 版本 | 冻结；运行后 `/api/ps` 复核 digest `b92d6a0b…`、Q4_K_M、ctx 16384、size_vram 23,930,978,958 B |
| AST operation mapping | 冻结 |
| Candidate Union | 冻结；`U_union = U_graph ∪ U_qwen`，不删除 U_graph |
| C0 | 冻结；6 道正式题复用 `runs/sd_v1_algorithm_pilot` 的历史 C0，15 道 DEV 题用同一 `discover`/`rank_and_prune`/role-separated 搜索现场计算 |
| Causal Search / Core Verifier | 冻结；budget 16/输入，严格子集最小性，`UNKNOWN ≠ FALSE` |
| BBCode 64 的合规 Prompt 版本 | 保留在 `results/MACE_candidate_discovery_v2.json`（每题的 prompt 与 `prompt_sha256` 均在） |
| v2 历史结果 | 未覆盖；sha256 `25cbf2ab548306a0a11bb7be79304332c3e5b6088d07ac139423f9c8ef08deeb` |

v2.1 只改了三类非算法内容：任务清单、输出路径、以及为 15 道没有历史 C0 的 DEV 题补算 baseline。`reference_for()` 从 `acceptance/<cid>.json` 派生 DEV 的 masking/exposing/control 角色与 MSMS；该派生在 10 道正式题上与 `reference.json` 逐项一致（0 处不一致），之后才用于 DEV。

## 2. 覆盖面（M1–M9）

| 机制 | v2.1 题数 | 可评测题 | 可评测输入 | C0 exact | v2.1 exact | 备注 |
|---|---:|---:|---:|---:|---:|---|
| M1 单操作 | 8 | 8 | 11 | 9 | 8 | 1 题回退（smartquotes）；2 题双方均 0（make_id_lower 为 UNKNOWN） |
| M2 双操作协同 | 4 | 4 | 4 | 1 | **4** | 全部严格正确 |
| M3 三操作协同 | 2 | 2 | 2 | 0 | **2** | 三条腿均被确认 |
| M4 替代路径 | 1 | 1 | 1 | 0 | **1** | isort 两条替代路径 |
| M5 条件分支 | 2 | 1 | 1 | 1 | 1 | humanize 不可评测 |
| M6 跨函数状态 | 1 | 1 | 2 | 0 | 0 | 隐藏块在另一个方法 |
| M7 循环状态 | 2 | 1 | 1 | 1 | 1 | attrs 不可评测 |
| M8 对象共享状态 | 0 | — | — | — | — | 仅在冻结的 v2（NetworkX 448）中测过 |
| M9 异常回退 | 1 | 1 | 3 | 0 | 0 | 隐藏块在 `style_for_token` |
| **合计** | **21** | **19** | **25** | **12** | **17** | +5 严格正确 |

M8 本轮没有新题；它在 25 道 DEV 中只有 NetworkX 448 一道，已在 v2 测过并冻结。因此 v2.1 的机制覆盖是 M1–M7、M9；M8 的证据来自 v2。

## 3. 总体指标

| 指标 | C0 | Full MACE + CD v2 |
|---|---:|---:|
| 严格 MSMS 完全匹配 | 12/25 | **17/25** |
| 隐藏 MSMS 被包含（辅助） | 未记录 | 18/25 |
| 错误关系 | 9 | **5** |
| 未匹配集合 | 未记录 | 2 |
| 候选块召回（逐题平均） | 0.643 | 0.905（U_union） |
| 全对候选覆盖的题数 | 11/21 | 19/21（U_union） |
| Probe 次数 | 70（含 6 道复用 baseline） | 258 |
| 运行墙钟 | 未记录 | 794.64 s |
| Prompt tokens | 未记录 | 145,939 |
| Completion tokens | 未记录 | 11,288 |
| Qwen 调用 | 0 | 21（1/题，0 重试） |
| `SEARCH_INCOMPLETE` 输入 | — | 3（全部在 latex297） |

**口径说明**：候选块召回是“候选操作的行跨度是否落在隐藏 MSMS 块内”的投影指标，不等于因果正确性；严格 exact 才要求投影后的块族完全相等且无 stray。25 个可评测输入对应 27 个参考 masking 输入，差的 2 个是 attrs/humanize（harness 缺陷，见第 8 节）。

## 4. 逐题结果

`U_q (novel)` = Qwen 候选数（其中不在 U_graph 的数量）；`exact (C0)` = 严格 exact / 可评测输入（C0 同口径）。

| task | mech | U_g | U_q (novel) | U_u | exact (C0) | false | vs C0 | probes | wall s | comp tok | status |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|
| `sd_attrs_asdict_loop_m7` | M7 | 0 | 2 (2) | 2 | 0/0 (0/0) | 0 | not_evaluable | 6 | 36.25 | 448 | INCOMPLETE |
| `sd_coverage_glob_backslash_m2` | M2 | 1 | 2 (1) | 2 | 1/1 (0/1) | 0 | better | 8 | 31.35 | 448 | OK |
| `sd_docutils_backticks_m1` | M1 | 1 | 2 (1) | 2 | 1/1 (1/1) | 0 | equal | 8 | 33.22 | 537 | OK |
| `sd_docutils_educate_dashes_m2` | M2 | 2 | 2 (1) | 3 | 1/1 (0/1) | 0 | better | 16 | 51.45 | 890 | OK |
| `sd_docutils_ellipsis_m3` | M3 | 1 | 3 (2) | 3 | 1/1 (0/1) | 0 | better | 16 | 45.54 | 766 | OK |
| `sd_docutils_language_tag_m3` | M3 | 2 | 4 (2) | 4 | 1/1 (0/1) | 0 | better | 32 | 56.84 | 951 | OK |
| `sd_docutils_make_id_lower` | M1 | 3 | 2 (0) | 3 | 0/2 (0/2) | 0 | equal | 16 | 36.0 | 494 | OK |
| `sd_docutils_make_id_nonid_m2` | M2 | 2 | 2 (0) | 2 | 1/1 (1/1) | 0 | equal | 8 | 36.38 | 462 | OK |
| `sd_docutils_smartquotes_strip_m1` | M1 | 1 | 2 (1) | 2 | 0/1 (1/1) | 1 | **worse** | 8 | 34.59 | 518 | OK |
| `sd_docutils_stupefy_emdash_m2` | M2 | 1 | 2 (1) | 2 | 1/1 (0/1) | 0 | better | 8 | 49.2 | 826 | OK |
| `sd_docutils_stupefy_endash_m1` | M1 | 1 | 1 (0) | 1 | 1/1 (1/1) | 0 | equal | 4 | 19.46 | 285 | OK |
| `sd_humanize_filesize_gnu_m5` | M5 | 0 | 1 (1) | 1 | 0/0 (0/0) | 0 | not_evaluable | 4 | 18.25 | 266 | INCOMPLETE |
| `sd_isort_format_strip_m4` | M4 | 0 | 2 (2) | 2 | 1/1 (0/1) | 0 | better | 8 | 31.21 | 478 | OK |
| `sd_jsonschema_1145_pointer` | M1 | 1 | 1 (0) | 1 | 2/2 (2/2) | 0 | equal | 4 | 25.14 | 270 | OK |
| `sd_networkx_adjlist_strip_m1` | M1 | 1 | 1 (0) | 1 | 2/2 (2/2) | 0 | equal | 4 | 25.05 | 271 | OK |
| `sd_pygments_latex297_italic` | M6 | 2 | 4 (4) | 6 | 0/2 (0/2) | 4 | equal | 64 | 74.41 | 1002 | OK |
| `sd_pygments_style95_cache` | M9 | 0 | 3 (3) | 3 | 0/3 (0/3) | 0 | equal | 16 | 52.73 | 810 | OK |
| `sd_tabulate_1052_strip_right` | M1 | 2 | 0 (0) | 2 | 1/1 (1/1) | 0 | equal | 8 | 24.25 | 224 | OK |
| `sd_tabulate_1056_strip_center` | M5 | 1 | 0 (0) | 1 | 1/1 (1/1) | 0 | equal | 4 | 41.96 | 593 | OK |
| `sd_tabulate_2557_curlen` | M7 | 2 | 1 (0) | 2 | 1/1 (1/1) | 0 | equal | 8 | 36.64 | 290 | OK |
| `sd_toml_strict_num_strip_m1` | M1 | 1 | 2 (1) | 2 | 1/1 (1/1) | 0 | equal | 8 | 34.72 | 459 | OK |

## 5. Qwen 扩 U：收益与噪声

- 13/21 题有新增候选，共 **22 个新操作**。
- 按隐藏 MSMS 块投影，**10/22 落在正确块内（45.5%）**，12/22 在块外。
- 8 题的新候选至少有一个正确；5 题（backticks、smartquotes、latex297、style95、toml）只新增了错误候选。
- 在 U_graph 已经覆盖隐藏块的 8 题上，扩 U 不改变召回，但可能改变搜索/最小性结果（smartquotes 就是反例）。
- 在 U_graph 完全没覆盖的 4 题上（attrs、humanize、isort、style95）：isort 靠 Qwen 拿到 1/1；style95 的 Qwen 候选仍全部落在 A 所在函数，0/3；attrs/humanize 因 harness 缺陷不可验证，但 Qwen 候选的块投影召回为 1.0（只说明行跨度对，不是因果证明）。

候选池层面的平均召回：U_graph 0.643（11/21 题全对）→ U_qwen 0.810（17/21）→ U_union 0.905（19/21）。仍未全对的 2 题是 latex297、style95，都是跨函数。

## 6. 与 C0 的逐题比较

| 关系 | 题数 | 题 |
|---|---:|---|
| v2.1 更好 | 6 | coverage、educate_dashes、ellipsis、language_tag、isort、stupefy_emdash |
| 持平 | 12 | backticks、make_id_nonid、stupefy_endash、jsonschema、nx_adjlist、tabulate×3、toml、make_id_lower、latex297、style95 |
| v2.1 更差 | 1 | smartquotes_strip（0/1 vs 1/1） |
| 不可评测 | 2 | attrs、humanize |

净收益 +5 严格正确，全部来自 M2（+3）、M3（+2）、M4（+1），减去 M1 的 1 个回退。**因此“Full MACE 是否稳定优于 C0”的准确回答是：在协同/替代机制上稳定更好；在 M1 上与 C0 基本持平且有一个回退；在 M6/M9 上两边都失败。**

## 7. 双操作、三操作与替代路径

- **M2 双操作协同：4/4 严格正确。** coverage（334+337）、educate_dashes（765+768）、make_id_nonid（2241+2244）、stupefy_emdash（829+832）都被 Qwen 以成对集合提出并被严格最小性确认；C0 只有 make_id_nonid 的 1/4。
- **M3 三操作协同：2/2 严格正确。** ellipsis 确认 `{812,815,818}`；language_tag 的模型提出 4 个操作 `{706,709,712,715}`，严格最小性去掉 715，确认 `{706,709,712}`。两者投影后都正好是 `{U1,U2,U3}`。
- **M4 替代路径：1/1。** isort 的两条路径 24、28 分别单独确认，对应 `{U1}`、`{U2}`。
- 加上冻结的 Groff 73（三操作 `{75,78,82}` 确认，1/1），三操作协同在 v2 体系里是 **3/3**；双操作是 **4/4**；替代路径是 **1/1**。

## 8. 失败机制与两个 harness 缺陷

### 8.1 `sd_docutils_make_id_lower`（M1，0/2，C0 也 0/2）

隐藏 U1 是 `if string.isascii(): id = string.lower()`（2232–2234）。U_graph 包含 2234、2240–2241、2243，Qwen 只提 2234、2243；**没有候选提出 2233 这行 guard**。搜索结果里 `{2234}` 是 `UNKNOWN`（禁用其余候选时 probe 报错），任何含 2234 的配对都是 `masked=True` 但 `MINIMALITY_UNKNOWN`（禁用 2234 后 UNKNOWN）。按规则 `UNKNOWN ≠ FALSE`，没有 CONFIRMED 集合，所以记 0/2，但这不等于“确定没有关系”。

### 8.2 `sd_docutils_smartquotes_strip_m1`（M1，0/1，唯一回退）

隐藏 U1 是 272–275 的两行 patch。C0 的 `{275}` 精确命中（1/1）。Qwen 新增 line 277（`multichar_quotes = quotes.split(':')`）。加入 U_union 后，搜索确认的是 `{275,277}`：单独 275 是 `NOT_MASKED`，因为删掉 277 后 probe 不能正常返回；277 因此成为“保活”操作。评分把 277 记作 stray，0/1、1 条错误关系。这是 Qwen 扩 U 引入的真实回退，不是评分口径变化。

### 8.3 `sd_pygments_latex297_italic`（M6，0/2）

隐藏 U1 在 `get_style_defs` 的 **330–353**；A 在 297。U_graph 是 320、307–308；Qwen 提出的 295/299/301/303 全在 A 所在方法。四个 Qwen 候选都不在隐藏块内（块投影错误），U_union 召回 0.0。搜索在 3/3 输入上 `SEARCH_INCOMPLETE`（16/64 子集），所以 0/2 是预算受限的负结果，不是“证明不存在”。

### 8.4 `sd_pygments_style95_cache`（M9，0/3）

隐藏 U1 在 `style_for_token` 的 **126–138**；A 在 95 的 `_styles` 构建方法。U_graph 为空；Qwen 只提 90/92/94，全部围绕 A 的局部状态，未跨到 126–138。搜索在 3/3 输入上完整（8 子集），确认集合为空，0/3。这是候选发现的结构性失败，不是预算问题。

### 8.5 `sd_attrs_asdict_loop_m7` / `sd_humanize_filesize_gnu_m5`（INCOMPLETE）

两题都是 `src/` 布局（`src/attr/_funcs.py`、`src/humanize/filesize.py`）。`SDExecutor._run_probe` 把 variant 根目录放进 `sys.path`，但可导入的包在 `<variant>/src/<pkg>` 下，于是探针 import 的是**已安装包**，不是 variant：

- attrs：in1/in2 的 plus 与 minus 完全相同，`a_executes=False`，U_graph=0；
- humanize：in1/in2/in3 同样 plus==minus，`a_executes=False`，U_graph=0。

因此 C0 与 v2.1 都找不到可执行 public masking 输入，双方都不可评测。按“最多一次定位、不做大规模重构”的要求，只做了定位，未改共享 executor；两题标记 `INCOMPLETE`，不进入准确率分母。21 道题里只有这 2 道是 `src/` 布局，缺陷对两种方法影响相同。

## 9. 专项跟踪（复用冻结 v2 结果）

### 9.1 BBCode 64：67 / 71 / 88

v2 结果：U_graph = `{71,77}`；U_qwen = `{67,71}`；U_union = `{71,77,67}`；隐藏 U1 = 64–67，U2 = 80–89；严格 0/1，false 3，unmatched 2。

| 行 | 映射 | 来源 | 结论 | 原因 |
|---|---|---|---|---|
| 67 | U1 | Qwen | 正确 | 恢复第一条 colour close，单例被确认 |
| 71 | U1/U2 之外（stray） | C0 + Qwen | 错误关系 | bold close 在探针上确实可单独 mask，但不是隐藏替代路径的一部分 |
| 88 | U2（80–89） | **仅 U_ast；C0 和 Qwen 都未提出** | 漏检 | 模型把 67 当成 colour 的替代路径，没有再提出 82–89 的第二条 `self.styles` 覆盖；且 88 单独不最小，必须带上 89（或 82+88+89）。88 与 88→89 依赖边都在 prompt 里，所以是推理/粒度漏检，不是上下文缺失 |

也就是说：**v2 找到了 U1 的替身（67），但没有找到 U2 的替身（88/89）**；71 是探针上真实可 mask、但不是隐藏答案的第三条路。

### 9.2 NetworkX 448：404 / 451 / 456

v2 结果：U_graph = `{404,451,456}`；U_qwen = `{451,456}`；隐藏 U1 = 448–451；严格 0/1，present 1，false 1。

| 行 | 映射 | 来源 | 结论 | 原因 |
|---|---|---|---|---|
| 404 | U1 之外；保活操作 | 仅 C0 | stray | `edge_data = data.copy()` 不在隐藏块内。删掉它下游 `edge_data.pop` 就没有定义，probe 不能返回；keep-set 搜索必须保留它才能观察到 mask，于是确认集合是 `{404,451}`，404 投影成 stray，严格判错 |
| 451 | U1 | C0 + Qwen | 正确腿 | U1 内真正的 guarded `add_slices` |
| 456 | U1 之外；下游 | C0 + Qwen | 被拒绝的错误关系 | Qwen 声称 shared-state 补偿；验证结果：`{456}` NOT_MASKED、`{451,456}` NOT_MASKED、`{404,451,456}` NOT_MINIMAL。它从不 mask A |

错误关系的形成方式因此有两层：**Qwen 的 456 是语义误判，被 causal verification 拒绝；404 不是 Qwen 提的，而是 C0 候选池里的“保活”上游定义，最小性搜索被迫带上它，评分再把它记成 stray。**

### 9.3 Groff 73：三操作协同是否稳定

v2：U_graph = `{82}`，U_qwen = `{75,78,82}`，确认 `{75,78,82}`，严格 **1/1**。v2.1 的两个 M3：

- ellipsis：Qwen 提出 `{812,815,818}`，确认同一个三元组，**1/1**；
- language_tag：Qwen 提出 `{706,709,712,715}`，严格最小性去掉 715，确认 `{706,709,712}`，**1/1**。

**三操作协同模式在 Groff73 + 两个新 M3 题上是 3/3。** 它不是 Groff 的孤立现象；模型能稳定提出三条腿并被严格验证收敛。language_tag 的 715 说明模型有时会多提一条，但严格最小性会把它剔掉，不影响块级 exact。

## 10. 六个问题

### Q1. Qwen 是否在更多 DEV 题上扩了 U？

是。13/21 题新增，22 个新操作；8 题的新候选至少一个正确，5 题只新增错误候选。U_union 的块召回从 0.643（U_graph）升到 0.905，19/21 题全对。

### Q2. 新增候选有多少是真正确？

按隐藏 MSMS 块投影，**10/22（45.5%）**落在正确块内，12/22 在块外。注意这是行跨度投影，不是因果证明；attrs/humanize 两题连因果验证都没跑成。

### Q3. Full MACE 是否稳定优于 C0？

不是“稳定优于”，是“总体更好、局部持平、一处回退”：严格 exact **17/25 vs 12/25**，false **5 vs 9**；逐题 6 好、12 平、1 差、2 不可评测。收益集中在 M2/M3/M4；M1 与 C0 基本持平（8/11 vs 9/11）；M6/M9 两边都 0。

### Q4. 双操作、三操作协同是否被稳定识别？

是。M2 **4/4**；M3 **2/2**（加上 Groff73 为 **3/3**）；M4 **1/1**。这是本轮最强的正面结果。

### Q5. 还有哪些机制失败？

- **M6 跨函数状态 0/2**、**M9 异常回退 0/3**：候选池和 Qwen 都停留在 A 所在函数，隐藏块在另一个方法。
- **M1 两个残余失败**：make_id_lower 0/2（guard 行未进候选，严格最小性停在 UNKNOWN）、smartquotes 0/1（277 保活操作造成 stray，且是唯一回退）。
- **M5/M7 各有一个 harness 不可评测题**（attrs、humanize），不是方法失败。

### Q6. 是否值得冻结算法、进入 HELDOUT？

值得做**一次** HELDOUT 确认，但要带条件：

1. 先修 `src/` 布局的 `sys.path` 缺陷（一行级），用已记录的 Qwen 响应离线复验 attrs/humanize，**不新增模型调用**；
2. 把 M6/M9 当作已知失败带入 HELDOUT，不要为了这两类题在 DEV 上调 prompt；
3. 结论表述限定为“在协同/替代机制上稳定优于 C0，在跨函数机制上没有改善”，不要写成普遍优于 C0；
4. HELDOUT 只看一次，避免用同一批题反复迭代。

## 11. 限制与必须披露

1. **两个 INCOMPLETE**：attrs、humanize 因 `src/` 布局 harness 缺陷不可评测；C0 与 v2.1 同等受影响。
2. **latex297 的 0/2 是预算受限**：3/3 输入 `SEARCH_INCOMPLETE`（16/64 子集），没有扩大预算。
3. **块召回是投影指标**：候选行落在隐藏块内不等于因果充分；strict exact 才是主指标。
4. **C0 的 6 道正式题复用历史结果，15 道 DEV 题现场计算**；两者用的是冻结的同一套 C0 代码，但并非同一次进程。
5. **Direct Qwen 不参与本轮**：结果 JSON 里的 `direct_exact`/`old_full_exact` 只是 10 题旧对照的遗留字段，不能与 21 题总数比较。
6. **单次生成**：每题 1 次、temp 0、无重采样；差异是方向性证据，不是稳定排名。
7. **GPU 证据**：本轮没有重新拍 `nvidia-smi`；运行后 `/api/ps` 复核了同一 digest、Q4_K_M、ctx 16384、模型全量驻显存。AutoDL RTX 4090 D 的完整显存快照来自同一会话的 v2 运行（`runs/sd_direct_vs_full/gpu_evidence.json`），未用本机 RTX 5060 冒充。

## 12. 产物与复现

主结果：

- **`results/MACE_candidate_discovery_v2_1_dev.json`** — sha256 `338a64957bdf6c69a665d1de65e2df2fbf4185b9d4f327f074879bf56ff97f55`
- **`results/MACE_candidate_discovery_v2_1_per_task.csv`** — sha256 `41de9faf19987a6de8b8afbcd25050f49e0c8bd83da2bea16c9b3e07753331d2`
- **`docs/MACE_candidate_discovery_v2_1_dev_results.md`** — 本文件

逐题原始输出与评分：

- `runs/candidate_discovery_v2_1/raw/<task>.json`（21 个，含完整 messages、raw response、token、墙钟）
- `runs/candidate_discovery_v2_1/scores/<task>.json`
- `runs/candidate_discovery_v2_1/baselines/<task>__c0.json`、`__graph.json`（15 道新 DEV 题的现场 baseline）
- `runs/candidate_discovery_v2_1/results.json`（运行中的增量快照）
- `runs/candidate_discovery_v2_1_run.log`

冻结的 v2：

- `results/MACE_candidate_discovery_v2.json` — sha256 `25cbf2ab548306a0a11bb7be79304332c3e5b6088d07ac139423f9c8ef08deeb`（未改动）
- `scripts/run_candidate_discovery_v2.py`（只读，未修改）

复现：

```bash
cd <local-path>
python -I scripts/run_candidate_discovery_v2_1.py
python -I scripts/analyze_candidate_discovery_v2_1.py
```

## 13. 停止

本轮按 45 分钟硬截止执行，实际 13.2 分钟完成 21/21 道题；没有超时、没有自动延长、没有读取 HELDOUT、没有修改 v2 历史结果。除两处已定位的 harness 缺陷（attrs/humanize 的 `src/` 路径）外，全部题目完成；latex297 的搜索不完整已显式记录为 `SEARCH_INCOMPLETE`。到此停止。
