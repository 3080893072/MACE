# MACE：同候选全集预算实验与独立协同验证

- 日期：2026-11-03
- 分支：`research/mace-subgraph-search`
- 基线提交：`b16cf76`（EXP-1 emission switch + subgraph-guided search prototype）
- 本轮代码/实验提交：`c82dcea`
- 测试：`python -m pytest` → **314 passed**（其中 `tests/test_budget_experiment.py` 17 项）
- 本轮没有新增 Agent、Prompt 阶段、GPU 模型实验或算法架构；没有修改 HIDDEN 评分规则。

本文件对应四项任务。任务二的结果目录是 `runs/v3_graph_budget/`（派生表
`budget_tables.md`）；任务一的版本清单是
`runs/v3_baseline_c_fixed_v1_1/manifest.json`；任务三的冻结协议在
`runs/v3_m1_screening/`；任务四的独立复核在 `runs/v3_out_of_universe/`。

---

## 0. 四个问题的直接回答（详细论证见 §6）

1. **有限预算下，子图引导是否有稳定收益？**
   **视关系类型而定，不稳定。** 在固定的大候选全集 `U_graph`（|U|=6）上，
   MSMS 的早期发现收益显著且可复现：50% 预算时 Graph 序确认 46 个 MSMS，
   穷举序确认 0 个（10% 时 7 vs 0）。但对 MMBS 没有收益，甚至略差
   （首确认平均 16.1 vs 12.7 probes）；对 |S| 大的任务（jinja，|S|=4）没有收益；
   在 C 的小全集 `U_c` 上收益较小且不单调（75% 时 MSMS 22 vs 25）。
   收益可由“被禁集合的补集大小”解释（§3.7），不是普遍优势。
2. **是否更早发现已确认的 MSMS/MMBS？**
   **MSMS 是，MMBS 否。** `U_graph` 上 5 个任务中 4 个任务的首次 MSMS
   平均评估序号明显提前：bind/filestorage/get_host 从 59.5–61.7 降到
   5.3–23.0，secure 从 27.3 降到 7.3（jinja 63.0→62.0，无收益）；
   首确认 probes 从 102.9 降到 42.1（全体均值）。MMBS 反过来：
   10% 预算内 17/24 个输入由穷举序确认、Graph 序只有 13/24。
3. **能否发现 C 漏掉的真实协同关系？**
   **在同一 U 上不能；在声明的更大 U 上能，但那些关系不属于 HIDDEN 计分域。**
   同一 U 的 100% 预算下，两种顺序的 confirmed 集合逐输入完全相同（§3.4）。
   Graph 额外产生的 7 条 scorer-UNVERIFIED 声明，用独立实现的判据在
   本地 U 上全部复核通过（291 probes / 95 variants）；其中 5 条涉及 C 全集
   之外的算子，2 条在 C 全集内但不在 HIDDEN U 内。它们是**候选全集扩张**
   的产物，不是搜索顺序的产物。
4. **哪些收益来自旧 bug 修复，哪些来自新机制？**
   **filestorage 的证据/提交差异来自 bug 修复；Graph 只改变顺序。**
   变体目录命名冲突 + emission 过滤的修复，使 filestorage 两个输入的
   伪 MSMS/MMBS 被纠正、MSMS `{2924}` 的覆盖从 1 个输入扩到 3 个输入；
   在 100% 预算下 Graph 与穷举的 confirmed 集合完全一致，probe 数也相同
   （`U_graph` 2624 = 2624，`U_c` 600 = 600），因此新机制没有带来集合层面
   的新关系，只带来发现时间上的差异。

---

## 1. 本轮不变量与证据等级

- 数据集与任务：`benchmark_real_v3` 的 5 个 DEV-TUNED 任务
  （jinja2 / werkzeug×4），公开探针与公开输入网格，未读 HIDDEN 参考。
  预算实验的配置在 `runs/v3_graph_budget/config.json` 记录
  `hidden_data_in_scope: false`、`model_calls: 0`。
- 判据（与上一轮一致）：
  - `MSMS(U) = { S ⊆ U, S ≠ ∅ : Masked(U\S) 且对所有非空真子集 S' ⊂ S，¬Masked(U\S') }`
  - `MMBS(U) = { D ⊆ U, D ≠ ∅ : Exposed(D) 且对所有真子集 D' ⊂ D（含空集），¬Exposed(D') }`
- 证据等级只用两类：100% 预算且所有输入都被搜索完 =
  `evidence_complete`；有限预算下未覆盖全部 strict-subset 比较的集合一律记为
  **undecided**，绝不记为 confirmed，也不把部分结果说成“完整发现”。
- 所有结果都是程序干预的可执行证据；没有使用 fake Qwen、历史响应回放或
  模拟结果。本轮不涉及模型调用。

---

## 2. 任务一：基线版本管理（C-fixed-1.1）

产物：`runs/v3_baseline_c_fixed_v1_1/manifest.json`（sha256
`8b917f0bd3e75611f884495bd00b825fe609f45cad20477782544de46929c8c1`）、
`manifest.sha256`、`filestorage_per_input_diff.json`。
冻结 pilot 原样保留，未覆盖任何历史文件。

### 2.1 版本谱系

| 版本 | 状态 | emission | 搜索 | 代码哈希 |
|---|---|---|---|---|
| C-original-1.0-frozen（`a51faab7…`） | `ARCHIVED_DO_NOT_REUSE_CONTAMINATED_EVIDENCE` | active_filtered | exhaustive | baseline_c `747423a0…`，execution `a66dfaac…` |
| **C-fixed-1.1** | **`REPRODUCIBLE_BASELINE`** | minimality_only | exhaustive | baseline_c `422356d6…`，execution `7d4bab5a…` |

C-fixed-1.1 的回归属性（来自 `runs/v3_subgraph_ablation` 的 C-fixed 运行）：
23 条 credited 关系、18/18 reference 命中、0 false、0 invalid、696 probe
executions、112 variant builds。提交同一性分两层记录：
`same_submission_as_repaired_C_original_on_dev = true`（5/5 任务与修复运行内
的 C-original 相同），但 `same_submission_as_frozen_C_original_on_dev = false`
（filestorage 与冻结 pilot 不同，其余 4 个任务逐位相同）。清单策略明确规定：
以后任何对 `baseline_c.py` / `execution.py` 的修改都必须新增版本条目，不能
静默改写 1.1。

### 2.2 变体目录命名冲突审计

冻结版 `Executor.variant` 使用
`f"{prefix}_{side}_{sanitized key}"[:110]`，`prefix = c_<task_id>`；长算子 ID
在第 110 字符被截断后，不同子集共享目录，缓存会把先建的变体发给后一个子集。
审计按冻结前缀逐任务重放：

| task | 冻结 \|U\| | 冲突组 | 受影响子集 | Graph \|U\| | 最长未截断名 |
|---|---:|---:|---:|---:|---:|
| jinja2_bytecode_cache_read | 1 | 0 | 0 | 6 | 213 |
| werkzeug_bind_server_name_lower | 2 | 0 | 0 | 6 | 254 |
| werkzeug_filestorage_stream_name | 3 | 1 | 3 | 6 | 285 |
| werkzeug_get_host_default_empty | 5 | 3 | 13 | 6 | 250 |
| werkzeug_secure_filename_ascii_filter | 3 | 0 | 0 | 5 | 194 |

修复后命名为 `sha1(full disabled key)[:16]`。注意：Graph 的 |U|=6 全集在旧命名
下会冲突（4–10 组），所以该修复不仅影响历史 C 结果，也是后续 Graph 模式可
复现的前提。

### 2.3 旧/新结果差异（逐输入）

`get_host` 虽有 3 组/13 个子集的冲突，但逐输入结果与提交未变（审计受影响、
输出未受影响）。真正改变的是 filestorage：

| 输入 | 旧 MSMS | 新 MSMS | 旧 MMBS | 新 MMBS |
|---|---|---|---|---|
| `{stream:named, data:abc, name:"<stderr>"}` | `{2921,2924}`, `{2924,2926}` | `{2924}` | `{2921,2926}`, `{2924}` | `{2924}` |
| `{stream:named, data:abc, name:"<stdin>"}` | 同上 | 同上 | 同上 | 同上 |

提交层面：MSMS `{datastructures.py:2924}` 的 `input` 从单个 `{stream:stderr}`
变为 3 个输入的 `inputs` 列表；冻结提交与修复提交的 sha256 分别为
`53da6d23…` / `3e38e1cb…`。其余 4 个任务的逐输入结果与提交逐位相同。

**结论**：C-original-1.0 的 filestorage 逐输入证据是伪证据，不得作为真值引用；
但它的“提交仍与 reference 匹配”这一点成立（reference 只按关系引用计分，
不检查每输入覆盖）。C-fixed-1.1 是后续比较的唯一确定性基线。

---

## 3. 任务二：同一候选全集下的预算实验

### 3.1 设计

- 每个任务固定两个**预先声明**的候选全集，分面板报告：
  - `U_graph`：上一轮冻结的 subgraph top-k（`runs/v3_subgraph_ablation/tasks/<task>/candidates.json`），|U| = 6,6,6,6,5；
  - `U_c`：Baseline C 的 effect-pruned 全集（`runs/v3_baseline_pilot/.../baseline_c.json`），|U| = 1,2,3,5,3。
  两个 U 都在任何预算运行之前固定；不是按分数挑选的。
- 两种模式只改变**评估顺序**：
  - `exhaustive`：按 `(|D|, D)`；
  - `graph`：按 `(edge=min(|D|,|U\D|), -role_score, len(disabled), 0, disabled)`
    的对称前沿顺序，平局由子集元组确定性决定。
  候选集合、验证范围、证据规则完全相同；`graph_score` 来自冻结候选文件，
  运行时不读 HIDDEN、不按分数调整 U。
- 预算：完整子集预算的 10/25/50/75/100%，取整规则预先固定为
  `ceil(fraction * 2^|U|)` 并截断到 `[1, 2^|U|]`。每个 (task, panel, mode)
  只做一次冷启动的 100% 运行并逐子集计时；小预算是同一轨迹的确定性前缀。
- 首确认成本：只有当 witness 与它需要的**全部 strict-subset 比较**都落在
  前缀内时，才记录该集合的首次确认 probe 数；否则记 `null`
  （修正前代码会把预算外的确认也计入，`summary.pre_fix.json` 保留修正前摘要）。
- 运行中执行器缓存在同一 (task, panel, mode) 的多个输入之间共享；因此
  probe/墙钟是“实际新执行”的成本，会受缓存影响。评估次数（预算单位）是
  第一指标，发现序号不受缓存影响。这一点在 §3.9 单独说明。

### 3.2 预算上限（取整后的实际评估次数）

| task | panel | \|U\| | 全子集 | 10% | 25% | 50% | 75% | 100% |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| jinja2_bytecode_cache_read | U_graph | 6 | 64 | 7 | 16 | 32 | 48 | 64 |
| jinja2_bytecode_cache_read | U_c | 1 | 2 | 1 | 1 | 1 | 2 | 2 |
| werkzeug_bind_server_name_lower | U_graph | 6 | 64 | 7 | 16 | 32 | 48 | 64 |
| werkzeug_bind_server_name_lower | U_c | 2 | 4 | 1 | 1 | 2 | 3 | 4 |
| werkzeug_filestorage_stream_name | U_graph | 6 | 64 | 7 | 16 | 32 | 48 | 64 |
| werkzeug_filestorage_stream_name | U_c | 3 | 8 | 1 | 2 | 4 | 6 | 8 |
| werkzeug_get_host_default_empty | U_graph | 6 | 64 | 7 | 16 | 32 | 48 | 64 |
| werkzeug_get_host_default_empty | U_c | 5 | 32 | 4 | 8 | 16 | 24 | 32 |
| werkzeug_secure_filename_ascii_filter | U_graph | 5 | 32 | 4 | 8 | 16 | 24 | 32 |
| werkzeug_secure_filename_ascii_filter | U_c | 3 | 8 | 1 | 2 | 4 | 6 | 8 |

### 3.3 主结果（24 个可搜索输入汇总；MSMS/MMBS 为确认的极小集个数）

`U_graph`：

| 预算 | 穷举 MSMS/MMBS | Graph MSMS/MMBS | 首 MSMS probes（穷举/Graph） | 首 MMBS probes | 完成输入 |
|---:|---:|---:|---:|---:|---:|
| 10% | 0 / 21 | **7 / 17** | – / 17.6 | 12.7 / 14.9 | 0/24 |
| 25% | 0 / 21 | **20 / 19** | – / 17.2 | 12.7 / 15.3 | 0/24 |
| 50% | 0 / 21 | **46 / 21** | – / 25.7 | 12.7 / 16.1 | 0/24 |
| 75% | 0 / 21 | **46 / 21** | – / 25.7 | 12.7 / 16.1 | 0/24 |
| 100% | 50 / 21 | 50 / 21 | 102.9 / **42.1** | 12.7 / 16.1 | 24/24 |

`U_c`：

| 预算 | 穷举 MSMS/MMBS | Graph MSMS/MMBS | 首 MSMS probes（穷举/Graph） | 首 MMBS probes | 完成输入 |
|---:|---:|---:|---:|---:|---:|
| 10% | 4 / 6 | **8 / 6** | 4.0 / 9.8 | 11.5 / 13.5 | 0/24 |
| 25% | 4 / 6 | **10 / 6** | 4.0 / 10.9 | 11.5 / 13.5 | 0/24 |
| 50% | 5 / 13 | **10 / 11** | 4.2 / 10.9 | 9.3 / 11.9 | 0/24 |
| 75% | **25 / 17** | 22 / 17 | 8.5 / 11.3 | 8.1 / 9.6 | 4/24 |
| 100% | 37 / 17 | 37 / 17 | 21.7 / **11.0** | 8.1 / 9.6 | 24/24 |

总 probe 与墙钟（同一轨迹的前缀）：

| panel | 预算 | 穷举 probes / 墙钟 s | Graph probes / 墙钟 s |
|---|---:|---:|---:|
| U_graph | 10% | 314 / 92.6 | 399 / 116.9 |
| U_graph | 50% | 1312 / 376.9 | 1312 / 375.4 |
| U_graph | 100% | 2624 / 751.7 | 2624 / 744.3 |
| U_c | 10% | 181 / 54.8 | 200 / 60.7 |
| U_c | 50% | 313 / 90.5 | 340 / 100.5 |
| U_c | 100% | 600 / 170.6 | 600 / 174.3 |

100% 预算下两模式总 probe 完全相同、墙钟差 ≤2.2%，且逐输入的 confirmed
MSMS/MMBS 集合逐位相同（脚本复核：5 个任务 × 2 个 panel 全部 `same_sets=True`）。
这直接证明二者只差搜索顺序。

### 3.4 发现曲线（每任务确认数，MSMS/MMBS）

`U_graph`：

| task | 模式 | 10% | 25% | 50% | 75% | 100% |
|---|---|---:|---:|---:|---:|---:|
| jinja2 | 穷举 | 0/8 | 0/8 | 0/8 | 0/8 | 4/8 |
| jinja2 | Graph | 0/8 | 0/8 | 0/8 | 0/8 | 4/8 |
| bind | 穷举 | 0/2 | 0/2 | 0/2 | 0/2 | 3/2 |
| bind | Graph | **1/0** | 1/2 | 3/2 | 3/2 | 3/2 |
| filestorage | 穷举 | 0/3 | 0/3 | 0/3 | 0/3 | 4/3 |
| filestorage | Graph | 0/3 | **1/3** | 4/3 | 4/3 | 4/3 |
| get_host | 穷举 | 0/6 | 0/6 | 0/6 | 0/6 | 6/6 |
| get_host | Graph | **6/6** | 6/6 | 6/6 | 6/6 | 6/6 |
| secure | 穷举 | 0/2 | 0/2 | 0/2 | 0/2 | 33/2 |
| secure | Graph | 0/0 | **12/0** | **33/2** | 33/2 | 33/2 |

`U_c`：Graph 在 10–50% 的 MSMS 计数更高（8 vs 4、10 vs 4、10 vs 5），
但 75% 时穷举反超（25 vs 22），100% 持平（37/37）。MMBS 在 50% 时
穷举 13 vs Graph 11，75% 后持平（17/17）。

### 3.5 首次确认成本（100% 预算；同输入从 0 开始计）

| task | panel | \|S\| | 首 MSMS 评估序号（穷举/Graph） | 首 MSMS probes | 首 MMBS 序号 | 首 MMBS probes |
|---|---|---:|---:|---:|---:|---:|
| jinja2 | U_graph | 4 | 63.0 / 62.0 | 126.0 / 124.0 | 2.0 / 3.0 | 12.0 / 14.0 |
| bind | U_graph | 2 | 61.3 / **23.0** | 122.7 / **47.3** | 2.0 / 8.0 | 13.0 / 18.0 |
| filestorage | U_graph | 2 | 59.5 / **19.0** | 119.0 / **39.0** | 5.0 / 3.0 | 13.0 / 15.0 |
| get_host | U_graph | 1 | 61.7 / **5.3** | 123.3 / **17.5** | 3.3 / 4.3 | 13.5 / 15.5 |
| secure | U_graph | 1 | 27.3 / **7.3** | 54.6 / **15.9** | 4.0 / 11.0 | 11.0 / 22.0 |
| jinja2 | U_c | 1 | 1.0 / 1.0 | 4.0 / 4.0 | 2.0 / 2.0 | 4.0 / 4.0 |
| bind | U_c | 1 | 2.7 / 3.7 | 5.7 / 7.7 | 2.0 / 3.0 | 6.0 / 8.0 |
| filestorage | U_c | 1 | 5.8 / 5.2 | 11.5 / 12.0 | 3.0 / 4.0 | 8.0 / 10.0 |
| get_host | U_c | 1 | 30.7 / **4.3** | 61.3 / **15.5** | 2.3 / 3.3 | 11.5 / 13.5 |
| secure | U_c | 1 | 5.3 / 5.7 | 10.6 / 12.0 | 3.0 / 4.0 | 8.0 / 10.0 |

按输入计数（首确认落在预算内）：`U_graph` MSMS 在 10/25/50/75/100% 分别为
0/0/0/0/24（穷举）与 **7/15/20/20/24**（Graph）；MMBS 为
17/17/17/17/17（穷举）与 13/15/17/17/17（Graph）。

### 3.6 完整性状态与 UNKNOWN

- 100% 预算：所有 24 个输入 × 2 panel × 2 模式均 `evidence_complete`，
  undecided = 0，UNKNOWN = 0。
- 10–75%：未完成输入的差异全部是 **missing（未评估）**；所有已评估子集都
  返回了精确的 OK/INVALID 观测，所以 UNKNOWN = 0。部分预算下的 confirmed
  数只能读作“截至该预算的发现”，不能读作完整发现。

### 3.7 机理：Graph 序什么时候有帮助

设 |S| 为最小集合大小、|D|=|U\S| 为确认它所需的被禁集合大小。
- MSMS 的确认还需要 **D 的所有 strict 超集**（对应 S 的所有非空真子集）。
  Graph 序按 `edge=min(|D|,|U\D|)` 从两端向中间推进：|D| 接近 |U|（即 |S| 小）
  的超集层早在 edge 0/1 被访问；|S| 大时，D 小，但它需要的超集层
  `|D|+1…|U|` 中的中间层（edge≈|U|/2）被排到最后。
- 因此：|S|≤2 的 bind/filestorage、|S|=1 的 get_host/secure 收益大；
  |S|=4（jinja，|D|=2，必须访问 edge=3 的中间层）几乎无收益（63→62）。
- MMBS 的确认只需要 D 的所有真子集；穷举序天然从 |D|=0 开始，Graph 序在
  访问空集后先评估全集（edge=0，probe 成本最高），再进入 |D|=1，故 MMBS
  通常略慢。secure 的 MMBS 从 4.0 退到 11.0 即此原因。
- 这也解释了总 probe：10% 时 Graph 更贵（399 vs 314），因为它优先评估
  全集/大禁用集；到 50% 后两者相同。

### 3.8 复现

```
python -m pytest -q
python -m scripts.record_baseline_version
python -m scripts.run_budget_experiment --out runs/v3_graph_budget
python -m scripts.merge_budget_results
python -m scripts.summarize_budget
```

环境：Python 3.11.7，Windows 10.0.26200，20 核；全程约 35 分钟。
代码哈希（`config.json`）：`graph_search.py d4b5ae76…`、
`execution.py 7d4bab5a…`、`baseline_c.py 422356d6…`。
主运行的 `run_budget_experiment.py` 哈希为 `6a3cc459…`；secure 任务因首次
运行在 GBK 控制台打印中文文件名时 `UnicodeEncodeError` 中止（四个任务结果
已落盘，probe/搜索结果未受影响），单独重跑时加了一行 stdout/stderr
`reconfigure` 守卫，哈希为 `1d827c25…`。合并脚本把两次运行记录的哈希、
中止说明和“首确认不得越过预算”的修正都写入 `summary.json.provenance`，
修正前的摘要保留在 `summary.pre_fix.json`。

### 3.9 限制（必须随结果一起读）

- 执行器缓存跨输入共享：probe 与墙钟是实际新执行成本，不是每个输入独立的
  冷启动成本；评估序号/预算单位不受影响。
- 每个任务只有一个公开输入网格（3–7 个输入），24 个可搜索输入来自 5 个任务；
  结论不能外推到其他项目或未见的输入。
- 部分预算下的“首确认 probes 均值”只在**该模式已经确认**的输入上取平均；
  两模式的确认集合不同，所以该均值不能单独横向比较，确认计数与发现曲线
  才是主比较（100% 预算下所有输入都确认，均值才完全可比）。
- Graph 序的 `role_score` 来自上一轮冻结的候选图；本轮没有调权重，也没有
  用测试结果调整顺序。
- `U_graph` 上 100% 的 confirmed 集合与穷举完全相同，说明本实验测的是
  **发现顺序**，不是搜索能力上限。

---

## 4. 任务三：独立 M1 协同案例筛查

### 4.1 预注册协议（在任何候选被查看前冻结）

`runs/v3_m1_screening/protocol.json`：

- 项目池（10 个，排除开发用的 jinja2 / werkzeug，版本在冻结时从 PyPI 取
  最新稳定版并记录 sha256）：urllib3 2.8.0、requests 2.34.2、starlette 1.10.0、
  httpx 0.28.1、attrs 26.1.0、sqlalchemy 2.1.6、python-dateutil 4.0.0、
  rich 15.0.0、packaging 26.3、more-itertools 11.2.1。
- seed：`mace-m1-2026-11-03`；静态审查预算 2500；targeted P− 600–800；
  full-suite P− 100–150；目标 15 个合格任务（5 机制 × 3）；每机制取 3。
- 选择规则：在每个机制层内按 `sha256(seed:candidate_id)` 升序取前 3；
  **不允许跨层替代，不足就报告缺口**。
- 独立性：筛查期间不运行 C/A/B/Graph，不看任何算法分数；分类只用 M1 定义；
  哈希顺序在任何测试结果出现前固定。

### 4.2 静态漏斗

| 项目 | 函数/方法数 | 源文件数 |
|---|---:|---:|
| urllib3 | 513 | 33 |
| requests | 267 | 16 |
| starlette | 527 | 34 |
| httpx | 446 | 21 |
| attrs | 208 | 13 |
| sqlalchemy | 10126 | 193 |
| python-dateutil | 328 | 19 |
| rich | 912 | 70 |
| packaging | 476 | 20 |
| more-itertools | 280 | 2 |
| **合计** | **14083** | — |

按 seed 哈希排序后审查前 2500 个；其余 11583 个是**预算截断**，不是结论。
`funnel_ledger.json` 明确写着：枚举函数不是 M1 声明，一个候选仍需
P+ trace、P− 失败和联合掩蔽 witness。

### 4.3 Stage 2（P+ 覆盖）结果

对 10 个固定版本执行 `pytest --collect-only`（120 s 上限），结果
`runs/v3_m1_screening/stage2_survey.json`：

- 可收集：requests（633 tests）、sqlalchemy（38,973）、more-itertools（765）；
- 收集失败 7 个：urllib3（缺 `trustme`）、starlette（缺 `httpx2`）、
  httpx（配置需要 `trio`）、attrs、python-dateutil（插件 `no_cover` 未注册）、
  rich、packaging。失败原因都是测试依赖/插件环境，不是候选本身的性质。

### 4.4 结果：M1_SCREENING_INCOMPLETE_AT_STAGE2

- 进入 P+ trace 的候选：**0**；targeted P− 运行：**0**；合格 M1 任务：**0**。
- 因此本轮**没有 M1 判定**，H1（Graph 是否能发现 C 漏掉的真实协同关系）
  在本任务上仍待验证。
- 没有用合成案例替代真实独立案例，也没有跨机制层凑数；这是协议允许的
  诚实缺口。缺口原因与下一步在 §8 说明。

---

## 5. 任务四：候选全集与评分协议的冲突

### 5.1 A/B 分开评估（不合并成一个分数）

- **A. 固定公开候选全集下的关系搜索能力**：§3 的预算实验。同一 U 下
  Graph 与穷举在 100% 预算产生相同集合，Graph 只改善 MSMS 的发现时间。
- **B. 自动候选发现能力**：Graph 候选全集多出的算子是否真的参与协同掩蔽。
  用独立判据在**本地声明的 U** 上复核，而不是让 HIDDEN scorer 回答
  “对/错”：7 条 scorer-UNVERIFIED 声明全部 `ACCEPTED_LOCAL_UNIVERSE`
  （291 probe executions、95 variants；`runs/v3_out_of_universe/verification.json`）。

| task | 本地 \|U\| | C \|U\| | HIDDEN \|U\| | 声明 | 涉及 C 全集外算子 |
|---|---:|---:|---:|---:|---:|
| jinja2 | 6 | 1 | 1 | 2 | 2/2 |
| bind | 6 | 2 | 1 | 1 | 1/1 |
| filestorage | 6 | 3 | 1 | 1 | 1/1 |
| get_host | 6 | 5 | 2 | 0 | — |
| secure | 5 | 3 | 1 | 3 | 1/3 |

5/7 条声明的算子集合包含 C 全集之外的算子；secure 的 226、239 两条在 C 全集
内但不在 HIDDEN U 内——这直接证明 **scorer 的 U ≠ C 的 U**。复核实现只使用
公开输入与本地 U，按 §1 的定义逐项检查 `Masked/Exposed` 和全部真子集；
`outcome_scope` 明确写为“提交的有限输入 + 公开 Graph 候选全集”，不冒充
HIDDEN 域或全合法输入域。

### 5.2 为什么 U 扩张会改变 MSMS/MMBS（数学分析）

记 U' = U ∪ N。固定输入下 `Masked(D)`、`Exposed(D)` 只依赖被禁集合 D 与载荷。

**命题 1（MMBS 单调）**：`MMBS(U) ⊆ MMBS(U')`。
证明：对 D ⊆ U，`Exposed(D)` 不变；D 的真子集集合也不变，所以 D 在 U 中
极小 ⇔ 在 U' 中极小。新增算子只能产生新的极小集，不能删除旧的。

**命题 2（MSMS 非单调）**：`MSMS(U)` 与 `MSMS(U')` 互不包含。
证明要点：`Masked(U'\S)` 与 `Masked(U\S)` 是不同被禁集合上的两个谓词。
对 S ⊆ U，扩张后补集变大，`Masked` 可能从真变假（S 掉出），也可能从假变真
（S 进入）；S 的极小性只需比较 S 的子集，本身不变。因此两个方向都可能。

单元测试 `tests/test_budget_experiment.py`：
`test_mmbs_is_monotone_under_universe_expansion` 与
`test_msms_is_not_monotone_under_universe_expansion`（U={a,b} 时
`MSMS={a}`；U={a,b,c} 时变成 `{a,b}`，`{a}` 消失）。

真实数据中的同型现象（100% 预算）：

| task | U_c 的 MSMS | U_graph 的 MSMS |
|---|---|---|
| jinja2 | `{137}` | `{119,131,137,146-148}`（`{137}` 消失） |
| bind | `{219}` | `{219,344-353}` |
| filestorage | `{2924}` | `{2924,2928}` |
| get_host | `{85}` | `{85}`（不变） |
| secure | `{227-229}` | `{221}`, `{226}`, `{227-229}`, `{239}`（226/239 不含新算子却出现） |

MMBS 侧完全符合单调性：5 个任务的 `MMBS(U_c)` 都保留在 `MMBS(U_graph)` 中，
jinja 额外出现 `{119}`，其余不变。

**推论**：跨全集比较“同一个关系”在 MSMS 上没有定义；一条 MSMS 必须写成
(U, S)。这也解释了为什么 scorer 对 HIDDEN U 之外的算子只能给 UNVERIFIED：
它既不能判 FALSE，也不能判 TRUE。

### 5.3 没有改动 HIDDEN 规则

本轮没有修改 `benchmark_real_v3/scoring/engine.py`、HIDDEN reference 或任何
计分阈值；没有为了让 Graph 得分更高而做 post-hoc 调整。评分域的冲突以
“另开一套本地判据 + 明确 scope”的方式处理，并保留两套结论分开报告。

---

## 6. 四个问题的完整回答

### Q1 子图引导在有限预算下是否有稳定收益？

**MSMS：在大 U 上有条件地有；MMBS：没有；小 U：不稳定。**

- `U_graph`（|U|=6）MSMS：10/25/50% 预算的确认数是 7/20/46（Graph）
  对 0/0/0（穷举）；首确认均值 42.1 对 102.9 probes；5 个任务中 4 个
  首确认评估序号下降到原来的 8%–38%（get_host 61.7→5.3、secure 27.3→7.3、
  filestorage 59.5→19.0、bind 61.3→23.0）。
- 反例：jinja 的 |S|=4，Graph 没有收益（63.0→62.0）；MMBS 全部 5 个任务
  Graph 都更慢或持平（首确认 probes 16.1 vs 12.7；10% 内确认的输入
  13/24 vs 17/24）。
- `U_c` 上收益缩小且不单调：50% 时 MSMS 10 vs 5，但 75% 时 22 vs 25；
  get_host 仍大幅受益（30.7→4.3），bind/filestorage/secure 反而略慢。
- 机理（§3.7）是确定的：收益来自“小 |S| ⇒ 大 |D| ⇒ 需要的 strict 超集在
  Graph 序的 edge 0/1 层”；|S| 大时确认所需的中间层被排到最后，收益消失。
  所以不能把 Graph 序当通用加速器；它适合 MSMS 且预期 |S| 小的场景。

### Q2 是否更早发现已确认的 MSMS/MMBS？

- MSMS：是。`U_graph` 上 50% 预算内 20/24 个输入已有首个 confirmed MSMS，
  穷举 0/24；100% 时 24/24 对 24/24，但 Graph 的平均首确认 probes 少 59%。
- MMBS：否。穷举序在 10% 预算内就有 17/24 个输入确认首个 MMBS，Graph 只有
  13/24；100% 时全体均值 12.7 vs 16.1 probes。原因见 §3.7：MMBS 只需子集，
  而穷举序本来就从空集/单元素开始；Graph 序先评估昂贵的全集。
- 这里的“更早”均指**同一次 100% 运行的确定性前缀**，不是不同运行间的比较。

### Q3 能否发现 C 漏掉的真实协同关系？

分三层回答，避免把“U 扩张”混成“搜索更强”：

1. **同一 U 内：不能。** 100% 预算下 5 个任务 × 2 个 panel 的 confirmed
   MSMS/MMBS 集合逐输入相同，probe 总数也相同（2624/600）。Graph 没有在
   C 的 U 上多找出任何关系。
2. **声明的更大 U 上：能，且已独立复核。** 7 条被 scorer 判 UNVERIFIED 的
   声明在本地 U 上全部通过：2 条 MMBS、5 条 MSMS，涉及 map.py:344-353、
   datastructures.py:2928、loaders.py:119/131/146-148、utils.py:221 等
   C 全集外的算子。5/7 条至少含一个 C 全集外算子。
3. **能否算“C 漏掉”：要看定义。** secure 的 226/239 在 C 的 U 内，但在
   C 的 U 中它们不是 MSMS（禁掉补集 `{227-229}` 会解除掩蔽），扩张 U 后才
   成为极小集；所以它们不是“C 搜索漏了”，而是“C 的候选全集看不到”。
   这正是任务四要求把 A（固定 U 的搜索）与 B（候选发现）分开的原因。

结论：**Graph 的候选生成确实带出了真实的协同算子，但当前没有证据表明
Graph 的排序在固定 U 上有超越穷举的发现能力**；这两件事必须分开计分。

### Q4 哪些收益来自旧 bug 修复，哪些来自新机制？

| 变化 | 来源 | 证据 |
|---|---|---|
| filestorage 两个输入的伪 MSMS/MMBS 被纠正 | 变体命名冲突修复 | 旧 `{2921,2924}`/`{2924,2926}` → 新 `{2924}` |
| filestorage MSMS `{2924}` 覆盖 1→3 个输入 | emission + 命名修复 | 冻结/修复提交 sha256 不同；其余 4 任务逐位相同 |
| 同 U 的 confirmed 集合不变 | 无（Graph 只改顺序） | 100% 时逐输入集合相同、probe 相同 |
| MSMS 更早被发现 | Graph 排序 | 50% 时 46 vs 0；首确认 probes 42.1 vs 102.9 |
| 7 条本地真协同声明 | 候选全集扩张（Graph 候选生成，上一轮冻结） | 5/7 含 C 全集外算子；独立复核 7/7 通过 |
| DEV 上 credited 关系数不变（23） | — | Graph-full 没有新增 credited 关系 |

所以：**bug 修复改变的是证据正确性与提交覆盖；新机制改变的是发现顺序；
候选扩张改变的是可发现关系的集合。三者不能混为一个“Graph 更好”的结论。**

---

## 7. 交付物清单

| 路径 | 内容 |
|---|---|
| `runs/v3_baseline_c_fixed_v1_1/manifest.json` | 版本谱系、哈希、冲突审计、策略 |
| `runs/v3_baseline_c_fixed_v1_1/filestorage_per_input_diff.json` | 逐输入旧/新证据与提交差异 |
| `runs/v3_graph_budget/{config,summary}.json`, `budget_tables.md` | 预算实验配置、完整结果、派生表 |
| `runs/v3_graph_budget/tasks/<task>/result.json` | 每任务逐输入轨迹、预算前缀、首确认 |
| `runs/v3_graph_budget/summary.pre_fix.json` | 首确认修正前的摘要（审计用） |
| `runs/v3_graph_budget_secure/` | secure 任务独立重跑的原始结果 |
| `runs/v3_m1_screening/{protocol,releases,funnel_ledger,stage2_survey,static_candidates}.json` | M1 冻结协议与筛查账本 |
| `runs/v3_out_of_universe/verification.json` | 7 条声明的独立复核 |
| `scripts/record_baseline_version.py` | 任务一 |
| `scripts/run_budget_experiment.py`, `merge_budget_results.py`, `summarize_budget.py` | 任务二 |
| `scripts/m1_protocol_freeze.py`, `m1_stage2_survey.py` | 任务三 |
| `scripts/verify_out_of_universe.py` | 任务四 |
| `tests/test_budget_experiment.py` | 预算取整、前缀、极小性门控、U 扩张性质 |

复现命令（§3.8）之外，任务三/四：

```
python -m scripts.m1_protocol_freeze
python -m scripts.m1_stage2_survey
python -m scripts.verify_out_of_universe
```

---

## 8. 开放问题

1. **M1 筛查停在 stage 2**：7/10 项目的测试依赖无法在现有解释器里收集
   （`trustme`、`httpx2`、`trio`、`no_cover` 插件等）。需要为每个项目建
   独立 venv 并安装 test extras，才能进入 P+ trace 与 targeted P−；
   在此之前 H1 无判定，不能用合成案例填充。
2. **Graph 收益只覆盖小 |S| 的 MSMS**：需要把“中间层最后访问”的排序缺陷
   显式修掉（例如对 MSMS 目标优先访问需要的高层超集），但这属于新算法，
   本轮按约定没有做；本轮只报告现象与机理解释。
3. **MMBS 序**：穷举的 `(|D|, D)` 对 MMBS 已接近最优；若要用 Graph 序，
   应把空集/单元素层单独前置，而不是共用对称前沿。同样留待下一轮。
4. **候选发现的精度未测**：B 目前只有 7 条正例，没有负例/召回率；
   HIDDEN U 不能当作完整真值（它本身是受限全集）。需要一个人工标注的
   多算子真值集，或一个独立的全域判据。
5. **跨 U 的关系身份**：MSMS 非单调意味着 `(U, S)` 才是关系的完整标识；
   评分协议若要同时接受不同 U 的提交，需要显式声明 U 并按同一 U 复核，
   否则 UNVERIFIED 会被误读成错误。
6. **预算实验的缓存混淆**：probe/墙钟受跨输入缓存影响；若要把成本作为
   主指标，需要每个输入独立冷启动执行器（成本会显著上升）。
7. **样本规模**：5 个 DEV-TUNED 任务、24 个输入，只足以支持“有条件收益”
   的结论，不足以估计总体效应；需要在更多项目/输入上重复同一协议。
