# MACE 论文现有实验结果盘点与缺失表格核对

> 审计日期：2026-11-05
> 审计对象：`<local-path>`（12 页版）的 Table 7 / 8 / 13 / 14 / 15
> 本轮范围：只盘点本机已有结果并核对论文缺表。**未调用 Qwen / GLM，未重跑 MACE，未修改 benchmark、算法或任何既有结果文件，未解封 HELDOUT，未读取 HELDOUT 的 `reference.json`，未做任何 HELDOUT 评分。**
> 逐格矩阵：`results/MACE_paper_table_status_matrix.csv`（60 个数据格，每格一行）

---

## 0. 一句话结论

论文 5 张表里的空白，绝大多数不是"没做"，而是"没汇总"：Direct GLM 的 DEV 全部结果、Full MACE 的最终效率、C0 的探针总数、GLM 的 HELDOUT 计时，都已经在本地落盘。真正没做过的只有两类：**C0 / Full / Direct Qwen 的 HELDOUT 预测（以及全部 HELDOUT 评分）**，和 **C0 的 wall 计时**。另有 **6 个已测值（Direct Qwen 3 格、Direct GLM 3 格）因题集/协议不同，不能与 19/27 并列**，只能单列或加脚注。

---

## 1. 七个问题的直接回答

### Q1. Table 7 / 8 / 13 / 14 / 15 一共有多少格可以更新？

五张表共 **60 个数据格**（7: 8 格；8: 12 格；13: 12 格；14: 20 格；15: 8 格）。按 A–F 分类：

| 分类 | 含义 | 格数 |
|---|---|---|
| A | 有完整可用实测值 | 27 |
| B | 有实测值但只覆盖部分队列 | 3 |
| C | 已测，但题集/协议不同，不能并表 | 6 |
| D | 只有冻结预测，未评分 | 6 |
| E | 真正未运行 / 从未记录 | 13 |
| F | 协议不适用（N/A） | 5 |
| **合计** | | **60** |

- **18 格论文当前已经正确**：C0/Full 的 verifier 与 evidence、C0/Full 的 false（以及 Full 的 unmatched）、Table 13 的 C0 tokens（已是 N/A）、Table 14 的四个 N=25、Table 15 的四个 Tasks 计数。
- **17 格可以直接改写为数值或明确的 N/A**（A 类 10 格 + B 类 3 格 + F 类 4 格）。
- **11 格只能把 TBD 改成 NOT_RUN**（Table 14 的 C0/Full/Qwen 未运行项）；那是状态，不是测量值。
- **6 格（C）有实测值但不能并进 Table 8 主表**（Direct Qwen 3 格、Direct GLM 3 格）。
- **6 格（D）只能保持 TBD**：GLM 的 HELDOUT MSMS/False 2 格 + Table 15 的四个 MSMS exact。
- **2 格（E）无法恢复**：C0 wall（从未记录）、C0 unmapped（未保存逐输入）。

18 + 17 + 11 + 6 + 6 + 2 = 60，与逐格矩阵一致。

### Q2. Direct Qwen 是否有超过当前 10 题 / 15 输入的结果？

**没有。** 本地唯一的正式 Direct Qwen 结果就是 `results/MACE_direct_vs_full.json`：10 tasks / 15 masking inputs（`totals.tasks=10`，`totals.masking_inputs=15`）。`results/MACE_quick_comparison.json` 也是同一批 10 题/15 输入的另一组基线，不是新增题目。10 题中只有 **6 题 / 10 输入**属于最终 21 题队列；另外 4 题（gexf448、bbcode64、bbcode70、groff73）不在最终队列里，而 Qwen 的 3 个 exact 全部落在这 4 题上。

### Q3. C0 / Full MACE 的最终效率数据是否存在？

- **Full MACE：存在最终 21 题汇总。** 276 probes、747.53 s、157,227 tokens（145,939 prompt + 11,288 completion）。
- **C0：只有 probes，没有 wall。** 72 probes（主跑 70 + closure 2）；C0 执行链没有任何 wall/时间字段，所有 `runs/.../baselines/*__c0.json` 的 `cost` 里都只有 `probe_executions_algorithm`，离线无法恢复 wall。
- 论文脚注里的 **70 vs 258 是 closure 前的快照**（`MACE_candidate_discovery_v2_1_dev.json`：2 个 src-layout 题 INCOMPLETE，25 个已评估输入）。最终 21 题是 **C0 72 probes / Full 276 probes**，所以该脚注需要改写，不能继续用 70/258。

### Q4. 四种方法的 HELDOUT 预测完成度？

| 方法 | HELDOUT 状态 | 证据 |
|---|---|---|
| C0 | **NOT_RUN**（无任何 HELDOUT 预测文件） | 仅 `benchmark_v4_dataset/source_derived_v2_1/heldout/` 有题，无 `runs/` 产物 |
| Full MACE | **NOT_RUN** | 同上；`runs/` 下无任何 heldout 目录 |
| Direct Qwen | **NOT_RUN** | 只有 DEV 的 `MACE_direct_vs_full.json` |
| Direct GLM | **PREDICTIONS_FROZEN（未评分）** | 25/25 题预测，SHA-256 `b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f` |

### Q5. 哪些空白只是没汇总，哪些是真没测？

**只是没汇总（本地已有值）：**
1. Direct GLM DEV 的 9/30、53 false、12 unmatched、347.342 s、113,593 tokens（Table 7/8/13）。
2. Full MACE 最终效率 276 probes / 747.53 s / 157,227 tokens（Table 13）。
3. C0 最终 probes 72（Table 13 第一列）。
4. Direct GLM HELDOUT 生成时间 325.066 s（Table 14 的 Time 列）。
5. HELDOUT 四个分层的规模 25/19/16/14 及对应 masking 分母 20/17/16/14（Table 15 的分母列）。
6. Direct Qwen 与 Direct GLM 在同样 10 题/15 输入上的配对结果（Qwen 3/15、GLM 4/15）。
7. 按 v2.1 角色口径重算的 **C0 13/25、Full 18/25**（由现有逐输入记录直接得到，无需重跑）。

**真没测（或从未记录）：**
1. C0 的 wall 时间——从来没有计时字段。
2. C0 / Full / Direct Qwen 的 HELDOUT 预测——完全没跑。
3. 任何 HELDOUT 评分——封印，按设计不能做。
4. Direct Qwen 在其余 15 个 DEV 题上的结果——没跑，所以四方法 21 题同表做不出来。
5. Direct Qwen / Direct GLM 的 MMBS——协议不请求，是 N/A，不是"缺失的测量"。

### Q6. 真正还需要跑哪些实验？

1. **HELDOUT 预测**：C0、Full MACE、Direct Qwen（3 个方法）。全部冻结后，才能一次性解封并给四方法评分。
2. **Direct Qwen 补题**：在最终 21 题队列的其余 15 题上跑 direct 协议（或按 21 题重跑），才能构造四方法同队列 DEV 表。
3. **C0 wall 计时**：仅当论文要在 Table 13 里比较 wall 时才需要补测（CPU 侧，成本低）。
4. **（可选项，建议先决策）按 v2.1 角色重算全量并覆盖结果文件**：这会改写既有结果，不在本轮授权范围内。若不重算，就只能在论文里用 27 的口径并明确说明它包含 2 个 control。

### Q7. 不跑新实验，能否补齐 DEV 四方法同题配对表？

**不能补成 21 题完整表。** 能补的只有 **6 题 / 10 输入**的交集：

| 方法 | 6 题/10 输入 exact | false | 逐输入可得？ |
|---|---|---|---|
| C0 | 5/10 | 4 | 否（只存任务级 `c0_exact`，未存逐输入） |
| Full MACE | 5/10 | 4 | 是（`runs/.../scores/<cid>.json` 的 `detail`） |
| Direct Qwen | 0/10 | 51 | 是（`detail[].direct.msms_exact`） |
| Direct GLM | 0/10 | 6 | 是（`detail[].score.msms_exact`） |

因此可以做出"6 题/10 输入"的三方法逐输入 + C0 计数表，但**做不出四方法逐输入的 McNemar 表**（C0 缺逐输入身份），也**做不出 21 题四方法表**（Qwen 缺 15 题）。注意这 6 题上 C0 与 Full 都是 5/10，两个 direct 模型都是 0/10。这 6 题覆盖 M1/M5/M6/M7/M9，不是单一机制；但只有 10 个输入，不能外推成"direct 模型更差"的普适结论。

---

## 2. 必须先统一的三处口径

### 2.1 论文的 "27 MASKED inputs" 里有 2 个是 v2.1 的 control（27 → 25）

根因：`scripts/run_candidate_discovery_v2_1.py` 从 `sd_algorithm_pilot` 导入 `SD`，而 `benchmark_v4_dataset/tools/sd_algorithm_pilot.py:40` 写的是 `SD = DS / "source_derived"`，不是 `source_derived_v2_1`。`reference_for()`（`run_candidate_discovery_v2_1.py:939-959`）先找 `SD/tasks/<cid>/reference.json`，找不到就退回 `SD/acceptance/<cid>.json` 的 `per_input` 推导角色。`source_derived/tasks/` 只有 10 个旧 v2 题，所以 21 题队列中，6 个旧 v2 题走 formal `source_derived/tasks/.../reference.json`，其余 15 个 v2.1-only 题走 v2 acceptance 推导；两套来源的角色在本题集上只有下面 2 处不同。

v2.1 的 `reference.json` 把下面两个输入标为 `control`，旧推导把它们算成 `masking`：

| 任务 | 输入 | v2 推导 | v2.1 role | Full 结果 |
|---|---|---|---|---|
| `sd_docutils_make_id_lower` | `control_lowercase` | masking | **control** | inexact |
| `sd_networkx_adjlist_strip_m1` | `control_plain` | masking | **control** | exact |

影响（都可从现有记录重算，不需要新实验）：

| 口径 | C0 | Full MACE | C0 false | Full false | 分母 |
|---|---|---|---|---|---|
| as-run（v2 角色推导） | 14/27 = 51.9% | 19/27 = 70.4% | 9 | 5 | 27 inputs / 21 tasks |
| **v2.1 角色语义** | **13/25 = 52.0%** | **18/25 = 72.0%** | 9 | 5 | **25 inputs / 21 tasks** |

两个 control 的 `false_relations` 都是 0，所以 false 计数不变；exact 各减 1（adjlist 的 control_plain 原判 exact）。改善量仍是 **+5**，只是从 +5/27 变成 +5/25。

**连带受影响的论文位置**（若采用 25）：摘要的 19/27 与 14/27、§6 的 19/27 与 14/27、Table 9 的 12/25 与 17/25（应变为 **11/23 与 16/23**）、§7 结论的 19/27 与 14/27、以及"27 masked instances / 27 MASKED inputs"的表述。

**这是口径选择，不是测量错误**：as-run 的 14/27、19/27 有完整记录，可复现；但论文声称 benchmark 是 v2.1，而 v2.1 的角色表明确把这两个输入定为 control，同表的 Direct GLM 又只统计 `role == "masking"`。同一张表里混用两种角色语义，才是问题所在。

### 2.2 70 vs 258 是 closure 前快照，不是最终值

- `results/MACE_candidate_discovery_v2_1_dev.json`（pre-closure）：21 tasks，其中 **2 题 INCOMPLETE**（attrs、humanize），25 个已评估输入，C0 70 probes，Full 258 probes，wall 794.64 s。
- closure 修复了这 2 题（`runs/candidate_discovery_v2_1_closure/results.json`）：attrs 18 probes / 4.26 s，humanize 10 probes / 3.13 s。
- 最终 `results/MACE_v2_1_dev_final.json`：**Full 276 probes / 747.53 s / 27 inputs**；C0 **72 probes**（70 + closure 的 0 + 2）。

所以论文 Table 13 的脚注 "Earlier 19-complete-task snapshot: 70 vs 258 probes; not substituted into final 21-task totals" 现在应当改成"最终汇总已存在：Full 276、C0 72"，而不是继续把最终值标为 pending。

### 2.3 模型生成时间 ≠ 因果验证耗时

- Full MACE 的 747.53 s 包含：21 次 Qwen 调用、候选落地、变体构造、**276 次探针执行**、沙箱与管理开销。
- Direct Qwen 的 596.46 s 是 10 次调用的**纯生成时间**，0 探针。
- Direct GLM 的 347.342 s 是 25 次调用的**纯生成时间**，0 探针。

三者不能当作同一种成本指标直接比大小。Table 13 要么把 "model generation" 与 "causal verification" 分列，要么在表注里明确每个数字覆盖了哪些阶段。同理，GLM 的 325.066 s 是 HELDOUT 生成时间，不是"HELDOUT 评分成本"。

### 2.4 统计单位

- `14/27`、`19/27` 是**输入级** exact-family 计数，按题聚类（21 tasks）；不是任务级（21 题里 Full 全对的任务远少于 19），也不是关系级。
- `false relations` 是**关系级**计数（9 / 5）；`unmatched sets` 是**集合级**计数（2）。
- C0 只保存了每题的 `c0_exact`/`c0_false` 计数，没有逐输入身份；Full 保存了逐输入 `detail`；Qwen/GLM 保存了逐输入 `detail`。
- Direct 协议不请求 MMBS，所以 Direct 行的 MMBS 是 **N/A**，不能写成 0 或 TBD 后当缺失值处理。

---

## 3. 分表结论

### Table 7（方法执行状态）

- C0、Full 两行正确：都确实在 21 题上评分。
- **Direct Qwen 行已过时**："No matched score" 应改为"10 题 / 15 输入已评分；仅 6 题属最终队列"。
- **Direct GLM 行已过时**："Not deployed / run" 应改为"DEV 25 题 / 30 输入已评分；HELDOUT 25/25 预测已冻结、未评分"。
- 两行的 causal verifier 仍应为 No（direct 协议无 verifier），这一列不用改。

按 §1 要求的字段展开：

| 方法 | 实际运行（DEV / HELDOUT） | 实际计分输入 | 预测冻结 | 最终计分 | 仅历史 pilot | 结果文件（SHA-256） |
|---|---|---|---|---|---|---|
| C0（Graph/AST） | DEV 21 题；HELDOUT 未跑 | DEV 27 输入（v2.1 口径 25）；HELDOUT 0 | N/A（确定性执行，无模型预测） | DEV 是；HELDOUT 否 | 否 | `MACE_v2_1_dev_final.json`（`5094ea44…`）；`runs/candidate_discovery_v2_1/results.json`（`c3322818…`） |
| Full MACE（+Qwen） | DEV 21 题；HELDOUT 未跑 | DEV 27 输入（v2.1 口径 25）；HELDOUT 0 | N/A（Qwen 输出随 run 落盘，2 题 cache replay） | DEV 是；HELDOUT 否 | 否 | 同上 + `MACE_v2_1_dev_per_task.csv`（`fd420483…`）+ closure（`9be17d13…`） |
| Direct Qwen 32B | DEV 10 题；HELDOUT 未跑 | DEV 15 输入；HELDOUT 0 | 部分：`raw_response` 与 `parsed_sets` 已落盘，但无独立冻结哈希 | DEV 是（旧 10 题队列）；HELDOUT 否 | **是**（不属于最终 21 题队列） | `MACE_direct_vs_full.json`（`00a05ff8…`）；内部 run（`1906fcfb…`） |
| Direct GLM | DEV 25 题；HELDOUT 25 题预测 | DEV 30 输入；HELDOUT 0（20 个 masking inputs 待评分） | **是**：HELDOUT 预测文件 25/25，`heldout_unscored: true` | DEV 是；HELDOUT 否 | 否 | `MACE_direct_GLM_v2_1_dev.json`（`c12a590e…`）；`..._heldout_predictions.json`（`b1815476…`）；`..._config.json`（`0ec929fe…`） |

### Table 8（DEV 严格准确率）

- C0/Full 的 exact 需要按 2.1 修正为 **13/25 / 18/25**（或保留 27 分母但明确说明含 2 个 control）。
- Direct Qwen 的 3/15、60 false、42 unmatched 是**真值**，但题集是 10 题旧队列，只能单列/脚注，不能塞进同一张 21 题配对表。
- Direct GLM 的 9/30、53 false、12 unmatched 同理（25 题队列）；在 **同一 21 题队列**上重算为 **5/25、51 false、11 unmatched**。
- 结论：**不能把 9/30 与 19/27 当成同分母比较**；同分母只有 13/25、18/25、5/25（Qwen 在 21 题队列上无法给出）。

对 §2 四个子问题的直接回答：

1. **没有完整的 25 题 DEV Direct Qwen 结果**；只有 10 题 / 15 输入。
2. **四方法共同输入集建不起来**；最大交集是 6 题 / 10 输入，且 C0 只有任务级计数。
3. **完整逐输入配对表取不回来**：Full / Qwen / GLM 有逐输入 `detail`，C0 只存了 `c0_exact / c0_false` 计数，没有逐输入身份。
4. **现有统计是输入级 + 关系级混合**：14/27、19/27 是输入级 exact-family 计数（按题聚类）；false relations 是关系级计数；unmatched sets 是集合级计数。

### Table 13（效率）

- Full 行三格可全部填入：276 / 747.53 s / 157,227 tokens。
- C0 行只能填 probes 72；wall 是 **NOT_RECORDED**；tokens 是 N/A。
- Direct Qwen 行：probes N/A；wall 596.46 s、tokens 45,442，但仅覆盖 10 题。
- Direct GLM 行：probes N/A；wall 347.342 s（DEV 25 题）、325.066 s（HELDOUT）；tokens 113,593 DEV / 116,402 HELDOUT。

### Table 14（HELDOUT 主比较）

- 四行的 N 都可写 25 tasks（GLM 的评分分母是 20 个 masking inputs）。
- **只有 Direct GLM 有预测**：状态 = PREDICTIONS_FROZEN，MSMS/MMBS/False 必须保持 TBD，Time = 325.066 s。
- C0 / Full / Direct Qwen 三行 = **NOT_RUN**，不能写成 TBD 后暗示"跑了但没算"。
- MMBS 对 Direct 两行是 N/A（协议不请求）。

### Table 15（HELDOUT 分层）

- 四个 Tasks 计数 25/19/16/14 与 seal 一致，正确。
- 四个 MSMS exact 都必须保持 TBD：GLM 预测覆盖了全部 25 题（project-disjoint 19/19、template-disjoint 16/16、交集 14/14），但未解封、未评分；C0/Full/Qwen 连预测都没有。
- 建议在分母列加上真实评分分母：**20 / 17 / 16 / 14 个 masking inputs**（不是 25/19/16/14 个任务）。

---

## 4. 逐格矩阵

> 表中 "实际状态" 前缀是 A–F 分类；完整 CSV 见 `results/MACE_paper_table_status_matrix.csv`。

| 表格 | 方法/指标 | 论文旧状态 | 实际状态 | 已有实测值 | 分母 | 证据文件 | 是否可直接填论文 |
|---|---|---|---|---|---|---|---|
| 7 | C0 · causal verifier | Yes | A｜确证：确定性探针，无模型 | Yes | — | results/MACE_v2_1_frozen_config.json | 无需改动 |
| 7 | C0 · evidence status | Scored on 21 tasks | A｜确证 | 21 tasks；27 输入（v2.1 口径 25） | 21 tasks | results/MACE_v2_1_dev_final.json | 无需改动（分母见 Table 8 行） |
| 7 | Full MACE · causal verifier | Yes | A｜确证 | Yes | — | results/MACE_v2_1_frozen_config.json | 无需改动 |
| 7 | Full MACE · evidence status | Scored on 21 tasks | A｜确证 | 21 tasks；27 输入（v2.1 口径 25） | 21 tasks | results/MACE_v2_1_dev_final.json | 无需改动（分母见 Table 8 行） |
| 7 | Direct Qwen 32B · causal verifier | No | A｜确证 | No（direct 协议无 verifier） | — | results/MACE_direct_vs_full.json | 无需改动 |
| 7 | Direct Qwen 32B · evidence status | No matched score | B｜已测但仅部分队列 | 10 tasks / 15 inputs 已评分；其中仅 6 tasks / 10 inputs 属最终 21 题队列 | 10 tasks / 15 inputs | results/MACE_direct_vs_full.json | 是（须注明子集，不能写成 21 题） |
| 7 | Direct GLM · causal verifier | No | A｜确证 | No（direct 协议无 verifier） | — | results/MACE_direct_GLM_v2_1_config.json | 无需改动 |
| 7 | Direct GLM · evidence status | Not deployed / run | A｜已测（DEV），HELDOUT 冻结 | DEV 25 tasks / 30 inputs 已评分；HELDOUT 25/25 预测冻结、未评分 | 25 tasks / 30 inputs | results/MACE_direct_GLM_v2_1_dev.json; results/MACE_direct_GLM_v2_1_heldout_predictions.json | 是 |
| 8 | C0 · exact | 14/27 (51.9%) | A｜可重算（按 v2.1 角色剔除 2 个 control） | 13/25 = 52.0%（as-run 14/27；差额 1 = sd_networkx_adjlist_strip_m1 的 control_plain，旧口径计为 masking 且判 exact） | 25 masking inputs / 21 tasks | results/MACE_v2_1_dev_final.json; runs/candidate_discovery_v2_1/scores/<cid>.json | 是（须同步改分母、摘要与 Table 9） |
| 8 | C0 · false relations | 9 | A｜确证（剔 control 后不变） | 9 | 25 masking inputs | results/MACE_v2_1_dev_final.json | 无需改动（数值不变；分母由表头改） |
| 8 | C0 · unmapped | not logged | E｜未记录 | not logged（C0 未保存逐输入结果，无法补） | — | results/MACE_v2_1_dev_final.json | 否（未记录，无法恢复） |
| 8 | Full MACE · exact | 19/27 (70.4%) | A｜可重算（按 v2.1 角色剔除 2 个 control） | 18/25 = 72.0%（as-run 19/27；差额 1 = control_plain 判 exact） | 25 masking inputs / 21 tasks | results/MACE_v2_1_dev_final.json; runs/candidate_discovery_v2_1/scores/<cid>.json | 是（须同步改分母、摘要与 Table 9） |
| 8 | Full MACE · false relations | 5 | A｜确证（剔 control 后不变） | 5 | 25 masking inputs | results/MACE_v2_1_dev_final.json | 无需改动（数值不变；分母由表头改） |
| 8 | Full MACE · unmapped | 2 | A｜确证（剔 control 后不变） | 2 | 25 masking inputs | results/MACE_v2_1_dev_final.json | 无需改动（数值不变；分母由表头改） |
| 8 | Direct Qwen · exact | not run | C｜已测；题集/协议不同 | 3/15 = 20.0%（10 题队列，非 21 题队列） | 15 inputs / 10 tasks | results/MACE_direct_vs_full.json | 否（口径不可比） |
| 8 | Direct Qwen · false relations | not run | C｜已测；题集/协议不同 | 60 | 15 inputs / 10 tasks | results/MACE_direct_vs_full.json | 否（口径不可比） |
| 8 | Direct Qwen · unmatched | not run | C｜已测；题集/协议不同 | 42 | 15 inputs / 10 tasks | results/MACE_direct_vs_full.json | 否（口径不可比） |
| 8 | Direct GLM · exact | not run | C｜已测；题集/协议不同 | 9/30 = 30.0%（25 题队列）；同 21 题队列为 5/25 | 30 inputs / 25 tasks | results/MACE_direct_GLM_v2_1_dev.json | 否（口径不可比） |
| 8 | Direct GLM · false relations | not run | C｜已测；题集/协议不同 | 53（同 21 题队列 51） | 30 inputs / 25 tasks | results/MACE_direct_GLM_v2_1_dev.json | 否（口径不可比） |
| 8 | Direct GLM · unmatched | not run | C｜已测；题集/协议不同 | 12（同 21 题队列 11） | 30 inputs / 25 tasks | results/MACE_direct_GLM_v2_1_dev.json | 否（口径不可比） |
| 13 | C0 · probes | pending | A｜已汇总 | 72（主跑 70 + closure 2） | 21 tasks | runs/candidate_discovery_v2_1/results.json; runs/candidate_discovery_v2_1_closure/results.json | 是 |
| 13 | C0 · wall time | pending | E｜从未记录 | NOT_RECORDED（C0 执行链无 wall 计时字段，无法离线恢复） | — | runs/candidate_discovery_v2_1/results.json; runs/candidate_discovery_v2_1_closure/results.json | 否（需补测；无法离线恢复） |
| 13 | C0 · tokens | N/A | F｜协议不适用 | N/A（无模型调用） | — | results/MACE_v2_1_frozen_config.json | 无需改动（论文已是 N/A） |
| 13 | Full MACE · probes | pending | A｜已汇总 | 276 | 21 tasks | results/MACE_v2_1_dev_final.json | 是 |
| 13 | Full MACE · wall time | pending | A｜已汇总 | 747.53 s（模型生成 + 候选扩展 + 探针 + 沙箱） | 21 tasks | results/MACE_v2_1_dev_final.json | 是（须与 Direct 生成时间分栏说明） |
| 13 | Full MACE · tokens | pending | A｜已汇总 | 157,227（145,939 prompt + 11,288 completion） | 21 tasks | results/MACE_v2_1_dev_final.json | 是 |
| 13 | Direct Qwen · probes | not run | F｜协议不适用 | N/A（direct 无探针） | — | results/MACE_direct_vs_full.json | 是（写 N/A） |
| 13 | Direct Qwen · wall time | not run | B｜已测但仅部分队列 | 596.46 s（10 题 / 15 输入） | 10 tasks | results/MACE_direct_vs_full.json | 是（须注明 10 题，非 21 题） |
| 13 | Direct Qwen · tokens | not run | B｜已测但仅部分队列 | 45,442（34,340 prompt + 11,102 completion） | 10 tasks | results/MACE_direct_vs_full.json | 是（须注明 10 题） |
| 13 | Direct GLM · probes | not run | F｜协议不适用 | N/A（direct 无探针） | — | results/MACE_direct_GLM_v2_1_config.json | 是（写 N/A） |
| 13 | Direct GLM · wall time | not run | A｜已测（DEV 25 题） | 347.342 s（DEV）；HELDOUT 325.066 s | 25 tasks | results/MACE_direct_GLM_v2_1_config.json | 是（标注本地 4090D 生成时间） |
| 13 | Direct GLM · tokens | not run | A｜已测（DEV 25 题） | 113,593 DEV（98,370+15,223）；HELDOUT 116,402（102,377+14,025） | 25 tasks | results/MACE_direct_GLM_v2_1_config.json | 是 |
| 14 | C0 · N | 25 | A｜已确定 | 25 tasks | 25 tasks | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 无需改动 |
| 14 | C0 · MSMS exact | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | C0 · MMBS exact | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | C0 · false relations | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | C0 · time | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | Full MACE · N | 25 | A｜已确定 | 25 tasks | 25 tasks | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 无需改动 |
| 14 | Full MACE · MSMS exact | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | Full MACE · MMBS exact | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | Full MACE · false relations | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | Full MACE · time | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | Direct Qwen · N | 25 | A｜已确定 | 25 tasks | 25 tasks | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 无需改动 |
| 14 | Direct Qwen · MSMS exact | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | Direct Qwen · MMBS exact | TBD | F｜协议不适用 | N/A（direct 协议不请求 MMBS） | — | results/MACE_direct_vs_full.json | 是（写 N/A） |
| 14 | Direct Qwen · false relations | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | Direct Qwen · time | TBD | E｜未运行（无 HELDOUT 预测） | NOT_RUN | — | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（只能写 NOT_RUN） |
| 14 | Direct GLM · N | 25 | A｜已确定 | 25 tasks / 20 masking inputs | 20 masking inputs | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 无需改动 |
| 14 | Direct GLM · MSMS exact | TBD | D｜预测已冻结、未评分 | TBD（25/25 预测冻结，sha b1815476…2597f） | 20 masking inputs | results/MACE_direct_GLM_v2_1_heldout_predictions.json | 否（须解封） |
| 14 | Direct GLM · MMBS exact | TBD | F｜协议不适用 | N/A（direct 协议不请求 MMBS） | — | results/MACE_direct_GLM_v2_1_heldout_predictions.json | 是（写 N/A） |
| 14 | Direct GLM · false relations | TBD | D｜预测已冻结、未评分 | TBD（未解封） | 20 masking inputs | results/MACE_direct_GLM_v2_1_heldout_predictions.json | 否（须解封） |
| 14 | Direct GLM · time | TBD | A｜已测（生成时间） | 325.066 s（25 题） | 25 tasks | results/MACE_direct_GLM_v2_1_config.json | 是（仅生成时间，非因果验证） |
| 15 | All formal held-out · Tasks | 25 | A｜确证（seal 固定） | 25 | 25 tasks | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 无需改动（可加 masking 分母 20） |
| 15 | All formal held-out · MSMS exact | TBD | D｜预测已冻结、未评分 | TBD（GLM 覆盖 25/25；C0/Full/Qwen 未运行） | 20 masking inputs | results/MACE_direct_GLM_v2_1_heldout_predictions.json; benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（须解封） |
| 15 | Project-disjoint · Tasks | 19 | A｜确证（seal 固定） | 19 | 19 tasks | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 无需改动（可加 masking 分母 17） |
| 15 | Project-disjoint · MSMS exact | TBD | D｜预测已冻结、未评分 | TBD（GLM 覆盖 19/19；C0/Full/Qwen 未运行） | 17 masking inputs | results/MACE_direct_GLM_v2_1_heldout_predictions.json; benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（须解封） |
| 15 | Template-disjoint · Tasks | 16 | A｜确证（seal 固定） | 16 | 16 tasks | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 无需改动（可加 masking 分母 16） |
| 15 | Template-disjoint · MSMS exact | TBD | D｜预测已冻结、未评分 | TBD（GLM 覆盖 16/16；C0/Full/Qwen 未运行） | 16 masking inputs | results/MACE_direct_GLM_v2_1_heldout_predictions.json; benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（须解封） |
| 15 | Project + template disjoint · Tasks | 14 | A｜确证（seal 固定） | 14 | 14 tasks | benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 无需改动（可加 masking 分母 14） |
| 15 | Project + template disjoint · MSMS exact | TBD | D｜预测已冻结、未评分 | TBD（GLM 覆盖 14/14；C0/Full/Qwen 未运行） | 14 masking inputs | results/MACE_direct_GLM_v2_1_heldout_predictions.json; benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json | 否（须解封） |

---

## 5. 论文中已过时的表述（逐条判定）

| 位置 | 论文旧表述 | 判定 | 证据 / 应改成 |
|---|---|---|---|
| 页眉 | "Sealed and GLM scores pending" | **B** | GLM 的 DEV 已评分；HELDOUT 仍封印。应改为 "HELDOUT sealed; Direct GLM DEV scored; HELDOUT predictions frozen" |
| 摘要 | "HELDOUT and Direct GLM results are not available." | **A/B** | Direct GLM DEV 结果已存在；应改为 "Direct GLM DEV results are reported; HELDOUT scores are not available" |
| Table 7 · Direct Qwen | "No matched score" | **B** | 10 tasks / 15 inputs 已评分；仅 6 题属最终队列 |
| Table 7 · Direct GLM | "Not deployed / run" | **A** | DEV 25 tasks / 30 inputs 已评分；HELDOUT 25/25 冻结 |
| Table 8 · Direct Qwen | "not run / – / –" | **C** | 有 3/15、60、42，但题集不同；只能单列或脚注 |
| Table 8 · Direct GLM | "not run / – / –" | **C** | 有 9/30、53、12；同 21 题队列为 5/25、51、11 |
| §6.1 | "A direct LLM row is a separate, as-yet-unmeasured protocol rather than an inferred number." | **B** | direct 协议已测（10/15 与 25/30），但仍不能与 MACE 同成本比较 |
| §6.1 | "Direct GLM is only a prospective standalone model baseline; if later run via API, remote latency must not be interpreted as local GPU generation speed." | **A** | 已在本地 4090D 跑完，不是 API、不是 future；本地生成时间仍不能与 Full 的因果验证时间等同 |
| Table 9 脚注 | "Exclude 2 cache-replayed tasks 12/25 17/25" | **A（口径）** | 若采用 v2.1 角色，应为 **11/23 与 16/23** |
| Table 13 | 四行 "pending / not run" | **A/B** | Full 三格、C0 probes、GLM 两格可填；Qwen 两格需注明 10 题；C0 wall 仍是 NOT_RECORDED |
| Table 13 脚注 | "Earlier 19-complete-task snapshot: 70 vs 258 probes; not substituted into final 21-task totals." | **A** | 最终汇总已存在：C0 72、Full 276；70/258 是 closure 前快照 |
| Table 14 | "Reserved sealed HELDOUT main comparison. No held-out outcomes have been asserted." | **D** | 仍成立（没有评分）；但应补一句 Direct GLM 预测已冻结 |
| Table 15 | "accuracies cannot yet be computed" | **D** | 仍成立；可补预测覆盖与 masking 分母 |
| §7 结论 | "Direct GLM is a proposed future baseline and HELDOUT remains sealed." | **B** | Direct GLM DEV 已完成；HELDOUT 仍封印 |

判定口径：A = 有完整可用实测值；B = 仅有部分队列/需要限定；C = 已测但协议/题集不可比；D = 只有冻结预测、未评分；E = 真没跑；F = N/A。

---

## 6. 证据文件与 SHA-256

下列哈希均在本轮重新计算，并与文件内嵌哈希交叉核对一致。

| 文件 | SHA-256 |
|---|---|
| `results/MACE_v2_1_dev_final.json` | `5094ea44a16907665aab284dcf842ed67103ce1cb29ab686ab5f9e101ee3deb5` |
| `results/MACE_v2_1_dev_per_task.csv` | `fd4204834d277fe3e13475ae61b5633ca6ccdb7d98d478a68333d7a9679de7de` |
| `results/MACE_v2_1_frozen_config.json` | `8de843b2c32f9ab7b7b03e1da0c2f6cf31bfdf5ea70b357c323f4ef38879edec` |
| `results/MACE_candidate_discovery_v2_1_dev.json`（pre-closure） | `814b71f7cdf2f4e6c45027bde1d427cfcd8c0ddbca76dde7385639311bdeed18` |
| `runs/candidate_discovery_v2_1/results.json` | `c3322818eb2f0e0953bd452458716048519f2d309bba288afe268a371c48340f` |
| `runs/candidate_discovery_v2_1_closure/results.json` | `9be17d13da35f8e02ba3125cff0398deabdb46727b66e562d17928108f7c31a0` |
| `results/MACE_direct_vs_full.json` | `00a05ff8569bb3f796d742a10b7bc0c5f41c6a7a828dc1414640fb0c4a8a351a` |
| `runs/sd_direct_vs_full/results.json` | `1906fcfb1b8c3e060a6636ce992542ce8c51be763db29da0b53914654d93b834` |
| `results/MACE_direct_GLM_v2_1_dev.json` | `c12a590eafc7925d9290cd4e631ba7f0252f2e0da376c9006b12e3fc4e65a6f8` |
| `results/MACE_direct_GLM_v2_1_heldout_predictions.json` | `b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f` |
| `results/MACE_direct_GLM_v2_1_config.json` | `0ec929fe26a3883e703eb80b1aaf66c4599acccdbcfa71e463f6625c274bef29` |
| `results/MACE_direct_GLM_v2_1_per_task.csv` | `4d2f6f26c4ecbef6004a96da289672add8741416fdaf11493fd63a38212d83f4` |
| `results/MACE_direct_GLM_v2_1_efficiency.csv` | `0a4d468d927ee1367ac0e32ffb497d2c4d4a8aa4c43e57d7ae0221b2d7340031` |
| `results/MACE_direct_GLM_v2_1_paper_tables.csv` | `b5c133a3ef85e887bad63702a5c832dc41c3f39219e6383181ebb353d9f9b5fc` |
| `docs/MACE_v2_1_dev_closure.md` | `36141b0eac5ae818bc96f175674673213f3c9a89f3607154916806cd8dd15da9` |
| `docs/MACE_direct_GLM_v2_1_report.md` | `856feeda3486ead68c49097d230a1b541e854205511761a379ec66a100ce6dad` |
| `benchmark_v4_dataset/source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json` | `482e67a61585196e0c06e2312b90425eb7746864d0cf40400fd089df99a0c0e9` |

交叉核对：
- `MACE_v2_1_frozen_config.json` 内嵌 `final_json_sha256` = `5094ea44…`、`per_task_csv_sha256` = `fd420483…`，与实际文件一致。
- `MACE_direct_GLM_v2_1_config.json` 内嵌 `dev_json` = `c12a590e…`、`heldout_predictions` = `b1815476…`，与实际文件一致。
- 该 config 的 `heldout_seal` 字段是 `benchmark_v4_dataset/split/seal.json`（`070b8d53…`），**不是** v2.1 HELDOUT seal（`482e67a6…`），两者不要混用。

逐输入证据位置：
- Full MACE：`runs/candidate_discovery_v2_1/scores/<cid>.json` 的 `detail[].score`；closure 的两题在 `runs/candidate_discovery_v2_1_closure/scores/<cid>.json`。
- Direct Qwen：`results/MACE_direct_vs_full.json` 的 `tasks.<cid>.detail[].direct.msms_exact`。
- Direct GLM：`results/MACE_direct_GLM_v2_1_dev.json` 的 `tasks.<cid>.detail[].score.msms_exact`。
- C0：`results/MACE_v2_1_dev_final.json` 的 `per_task[].c0_exact / c0_false / c0_scored_inputs`（只有计数，没有逐输入身份）。

---

## 7. 仍需运行的实验（按优先级）

| 优先级 | 实验 | 为什么必须跑 | 规模 / 备注 |
|---|---|---|---|
| 1 | C0 / Full / Direct Qwen 的 HELDOUT 预测 | Table 14/15 现在只有 GLM 有预测；另外三方没有预测，连"冻结"都谈不上 | 25 题 × 3 方法；只写预测、不读 reference、不评分 |
| 2 | Direct Qwen 在其余 15 个 DEV 题 | 没有它就没有 21 题四方法同表；现有 Qwen 只有 10 题，且 4 题不在最终队列 | 15 题；direct 协议、同 prompt/parser/scorer |
| 3 | C0 wall 计时 | Table 13 的 C0 wall 是唯一"从未记录"的效率格 | CPU 侧；若论文不需要 C0 wall 可跳过 |
| 4（决策项） | 以 v2.1 角色重算 C0/Full 并覆盖结果文件 | 消除 27 与 25 的双口径 | **会改写既有结果，本轮明确不做**；建议先在论文里统一口径，再决定是否重算 |

不需要跑：Direct GLM DEV（已完成）、Direct GLM HELDOUT 预测（已完成且冻结）、MACE 算法本身、benchmark 修改。

---

## 8. 本次重算的方法（可复现）

1. **角色差异**：用 `run_candidate_discovery_v2_1.reference_for(cid)` 与 `benchmark_v4_dataset/source_derived_v2_1/tasks/<cid>/reference.json` 逐输入比较 `role`。结果：只有 2 个任务不同（`sd_docutils_make_id_lower:control_lowercase`、`sd_networkx_adjlist_strip_m1:control_plain`），均为 v2 推导 `masking` → v2.1 `control`。
2. **Full 18/25**：最终 json 的 `msms_exact` 合计 19；adjlist 的 `detail` 显示 `control_plain` 判 exact，按 v2.1 剔除后 18；分母 21 题的 `reference_masking_inputs` 合计 27，剔除 2 个 control 后 25。
3. **C0 13/25**：最终 json 的 `c0_exact` 合计 14；adjlist 的 `c0_exact=2` 且 `c0_scored_inputs=2`（两个输入都 exact），剔除 control_plain 后 1，故 13；`c0_false` 合计 9 不变。
4. **GLM 同队列 5/25**：对 21 题队列求和 `scoring.masking_inputs` = 25、`scoring.exact` = 5、`scoring.false_relations` = 51、`scoring.unmatched_sets` = 11（25 题全量是 30 / 9 / 53 / 12）。
5. **Qwen 交集**：`set(MACE_v2_1_dev_final.per_task) ∩ set(MACE_direct_vs_full.tasks)` = 6 题；逐输入 `detail[].direct.msms_exact` 求和 = 0/10；C0/Full 用最终 json 的 `c0_exact` 与 scores `detail`，均为 5/10。
6. **HELDOUT 覆盖**：seal 的 `project_disjoint_from_dev` / `template_seen_in_dev` 标志得到 25/19/16/14；预测文件 25/25 全有；非空映射集 11/25；`input_roles.masking` 合计 20/17/16/14。**未读取任何 HELDOUT `reference.json`，未评分。**
7. **哈希**：对上述文件逐字节 SHA-256；与 `MACE_v2_1_frozen_config.json` 和 `MACE_direct_GLM_v2_1_config.json` 的内嵌哈希核对一致。

本轮只新建了两个文件（本报告与 CSV），没有覆盖、删除或改写任何既有结果。
