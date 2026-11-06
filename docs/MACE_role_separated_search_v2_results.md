# MACE 角色分离搜索 v2：实现、测试与离线对照

- 日期：2026-11-04
- 分支：`research/mace-role-separated-search`（基于 `0ad980d`）
- 代码哈希：`runs/v3_role_separated/code_hashes.json`（改前 / 改后）
- 数据：`runs/v3_full_mace_audit/audit.json` +
  `runs/v3_full_mace_30min/tasks/<task>/result.json` 中已保存的 Qwen 原始响应
- 产物：`runs/v3_role_separated/offline_comparison.json`、
  `/d/tmp/rs_offline.log`

本轮只改搜索接线与 Qwen 适配层，**未改动** HIDDEN scorer、冻结 Benchmark、
原始实验数据、因果执行器、Verifier 语义、以及候选全集 U 中的任何操作。
C-fixed-1.1、Graph-only、旧 Full MACE 的代码路径仍保留（legacy 分支未删）。

## 1. 代码改动

### 1.1 `benchmark_v3_baselines/graph_search.py`

保留原 `search_relations`（426 行）逐字不变，新增：

- `search_relations_role_separated(executor, payload, universe, *,
  msms_scores, mmbs_scores, budget, hypotheses,
  max_hypothesis_probes_per_role, oracle)`；
- `_normalise_hypotheses`：未知 id 整条假设拒绝，空集拒绝，重复合并；
- `_role_score`：单角色分数 = 集合内操作分数之和。

关键语义：

| 项目 | 实现 |
|---|---|
| MSMS 队列 | 元素是 kept 集合 S；真正评估 D = U − S |
| MMBS 队列 | 元素是 disabled 集合 H；真正评估 D = H |
| 队列顺序 | `(是否已有 witness, |集合|, -round(role_score,9), 集合)` |
| 调度 | 先执行 D=∅；两个队列严格交替；某一队列耗尽后另一队列继续 |
| D=U | 不再被强制排在第 2 位，只按 `|H|=|U|` 落在 MMBS 队列末尾 |
| 假设门控 | 每角色最多 3 条；角色间交替探测；`status=="OK"` 且对应谓词为 True 才算 witness |
| 失败假设 | 不获得优先级，仍留在完整子集空间；probe 计入预算 |
| 证据复用 | 共享 `EvidenceStore`，按 disabled 集合去重；`duplicate_probes` 恒为 0 |
| 三态 | UNKNOWN/INVALID 只阻止确认，从不当作 False |
| 预算 | `limit = min(budget, 2^n)`；`budget=None`/`2^n` 时覆盖全部子集 |

返回新增 `queues`（两队列的完整顺序）、`schedule`（实际执行顺序，带角色标签）、
`hypotheses`（accepted/rejected/gate/witness_hits/witness_rate）、
`reused_evidence`、`duplicate_probes`。

### 1.2 `benchmark_v3_baselines/baseline_c.py`

- `run()` 新增 `msms_scores`、`mmbs_scores`、`hypotheses`、
  `max_hypothesis_probes_per_role`；
- `search` 允许 `"role_separated"`；
- 新分支把 v2 的 metrics（含 schedule/hypotheses/duplicate_probes）写入
  `search_runs` 与 `search` 汇总；穷举与旧 graph 分支未改。

### 1.3 `scripts/run_full_mace_comparison.py`

- 新结构化协议：`msms_hypotheses[].kept_ops` /
  `mmbs_hypotheses[].disabled_ops`，附 `condition`、`rationale`、
  `source_evidence`；支持单操作与多操作假设；
- **删除** `2.0/(1+rank)` 作为 v2 的排序奖励；只有通过证据门控的假设进入
  队列优先位；
- 未知 id 只拒绝该假设，不扩张/裁剪 U；
- 旧 `msms_rank`/`mmbs_rank` 输出仍可解析，但转换为单操作假设
  （`format="legacy_converted"`），走同一门控，不再有固定加成；
- `--mode legacy` 保留旧共享分数臂用于对照，默认 `v2`；
- v2 使用 `baseline_c.run(search="role_separated")`，不再调用旧 `graph_scores`
  作为排序先验（`graph_scores` 仍保留给 legacy/审计脚本）。

### 1.4 测试与离线脚本

- 新增 `tests/test_role_separated_search.py`（29 个用例）；
- 新增 `scripts/run_role_separated_offline.py`（本轮离线对照，CPU）。

## 2. 测试结果

命令：

```
python -m pytest tests/test_v3_baselines.py tests/test_subgraph_search.py \
  tests/test_budget_experiment.py tests/test_verify.py \
  tests/test_verifier_v2.py tests/test_evidence_gate.py \
  tests/test_role_separated_search.py -q
```

结果：**124 个用例全部通过，退出码 0**（本仓库 pytest 配置抑制汇总行，
只输出点阵）。其中新增 29 个，覆盖：

1. 角色分数独立（两个方向，比较 `queues`）；
2. D=∅ 第一个执行；
3. D=U 不再第二个执行；
4. 两角色严格交替、数量差 ≤1；
5. 错误假设无优先级且不改变队列相对顺序；
6. 正确单操作假设在第 2 次评估即获 witness；
7. 多操作协作假设被映射到正确 D 并通过 witness，但仍需严格子集检查；
8. 未被提到的操作仍在搜索空间中，全预算下关系与穷举一致；
9. hypothesis probe 计入预算、超预算标 `BUDGET_SKIPPED`；
10. 每角色最多 3 条优先验证；
11. 未知 id 被拒绝且不进入 U；
12. UNKNOWN 不当作 False；
13. INVALID 不当作 False；
14. 严格子集证据不全时，即使假设有 witness 也不确认（`first_msms is None`）；
15. 满预算（2^n）与穷举逐项一致（9 个合成场景参数化）；
16. 共享缓存不重复 probe（同一 D 只执行一次，`reused_evidence≥1`）；
17. 结构化协议解析、未知 id 拒绝、旧 rank 输出转换（3 个用例）。

## 3. 离线实验设计

- 预算：每个可搜索输入最多 16 次子集评估（与上一轮相同）。
- 无 GPU、无新 Qwen 调用。A/B 直接复用 `audit.json` 中已记录的执行；
  C/C0/D 在本机 CPU 上重放真实干预（与审计重放相同的执行器/探针）。
- 臂：

| 臂 | 含义 | 来源 |
|---|---|---|
| A_graph | 原 Graph-only，共享 `edge` 排序 | audit 记录 |
| B_shared_qwen | 旧 Full MACE，Qwen rank 折进同一张分表 | audit 记录 |
| C_role_qwen | v2 角色分离 + 门控，复用历史 Qwen 响应 | CPU 重放 |
| C0_role_no_hyp | v2 角色分离，无假设（确定性对照） | CPU 重放 |
| D_oracle | v2 + 逐输入已验证集合作为假设（上界，不可部署） | CPU 重放 |

C 使用历史响应的旧格式（`legacy_converted`）。**结构化协议本轮只经过单元
测试，没有新的模型输出**。

## 4. 结果

### 4.1 首确认成本（评估序号，1 起）

| 任务 | 臂 | 首 MSMS（逐输入） | 均值 | 首 MMBS（逐输入） | 均值 |
|---|---|---|---:|---|---:|
| get_host | A_graph | 4,5,4,4,4,5 | 4.33 | 3,4,3,3,3,4 | 3.33 |
| get_host | B_shared_qwen | 4,**10**,4,4,4,**10** | 6.00 | 3,**7**,3,3,3,**7** | 4.33 |
| get_host | C_role_qwen | 2,4,2,2,2,4 | **2.67** | 8,10,8,8,8,10 | 8.67 |
| get_host | C0_role_no_hyp | 2,4,2,2,2,4 | **2.67** | 3,5,3,3,3,5 | 3.67 |
| get_host | D_oracle | 2,2,2,2,2,2 | **2.00** | 3,3,3,3,3,3 | **3.00** |
| filestorage | A_graph | 4,6,4,4 | 4.50 | 3,3,3 | 3.00 |
| filestorage | B_shared_qwen | 8,5,8,8 | 7.25 | 7,7,7 | 7.00 |
| filestorage | C_role_qwen | 6,2,6,6 | 5.00 | 5,5,5 | 5.00 |
| filestorage | C0_role_no_hyp | 4,2,4,4 | 3.50 | 5,5,5 | 5.00 |
| filestorage | D_oracle | 2,2,2,2 | **2.00** | 3,3,3 | **3.00** |

按输入数加权合计（10 个有 MSMS 的输入 / 9 个有 MMBS 的输入）：

| 臂 | 首 MSMS 均值 | 首 MMBS 均值 |
|---|---:|---:|
| A_graph | 4.40 | 3.22 |
| B_shared_qwen | 6.50 | 5.22 |
| C_role_qwen | 3.60 | 7.45 |
| C0_role_no_hyp | **3.00** | 4.11 |
| D_oracle | **2.00** | **3.00** |

### 4.2 点名的两个真值

| 真值 | 输入 | A | B | C | C0 | D |
|---|---|---:|---:|---:|---:|---:|
| get_host `{87}` MSMS / MMBS | host_header=None（2 个输入） | 5/4 | 10/7 | **4**/10 | 4/5 | 2/3 |
| filestorage `{2924}` MSMS / MMBS | stderr + 2 个 named | 4/3 | 8/7 | **6**/5 | 4/5 | 2/3 |
| filestorage `{2924}` 证据出现位置 | stream=none | 6 | 8 | 6 | 4 | 2 |

- 旧 B 的 **角色混用** 把 get_host `{87}` 的 MSMS 推到第 10 次；v2 中
  MSMS 回到第 4 次（错误 MSMS 假设只浪费 1 次探测）。
- MMBS 侧在 C 中反而更慢（get_host 7→10）。原因不是优先级：Qwen 的 2 条
  MMBS 假设（`{93}`、`{95}`）都未通过 exposed 门控，**没有获得任何优先位**；
  但按协议它们仍各占 1 次预算，加上 3 条 MSMS 假设，前 5 次评估被探测占用。
  C0（不探测假设）在同一输入上是 5，说明这 5 次是门控成本，不是排序污染。
- filestorage 的 `{2924}`：B 8/7 → C 6/5，比旧版好，但仍比 C0 的 4/5 慢
  2/1 次，因为 Qwen 的 `{2926}`/`{2921}` 假设要先探测。

### 4.3 假设命中率与预算

| 任务 | 臂 | MSMS witness | MMBS witness | duplicate probes | reused evidence | UNKNOWN / INVALID |
|---|---|---|---:|---:|---:|---:|---|
| get_host | C | 6/18 = 33.3% | 0/12 = 0% | 0 | 30 | 0 / 0 |
| get_host | D | 6/6 = 100% | 6/6 = 100% | 0 | 12 | 0 / 0 |
| filestorage | C | 1/4 = 25% | 0/4 = 0% | 0 | 36 | 0 / 0 |
| filestorage | D | 4/4 = 100% | 3/3 = 100% | 0 | 32 | 0 / 0 |

- C 合计：MSMS 7/22（31.8%），MMBS **0/16**。
- 预算/实际：get_host 每输入 16 次，共 96/192 子集（50%，所有臂都标
  `complete=false`）；filestorage 每输入 8 次，共 32/32（完整）。
- probe 执行次数：get_host 194、filestorage 68，**五个臂完全相同**；
  v2 改变的是子集顺序，不是执行总量。
- 所有臂 `duplicate_probes=0`，`unknown_subsets=invalid_subsets=0`。

### 4.4 最终关系集合

- get_host（5 个操作）：所有臂 MSMS = `{85}`、`{87}`；MMBS = `{85}`、`{87}`。
- filestorage（3 个操作）：所有臂 MSMS = `{2921}`、`{2924}`、`{2926}`；
  MMBS = `{2924}`。
- 两任务上 A/B/C/C0/D 的关系集合逐输入一致；v2 没有多报、没有少报。

### 4.5 逐角色执行顺序示例

get_host，输入 `host_header=None`：

```
C_role_qwen
 1 baseline        D=[]                        masked
 2 msms_hypothesis D=U\{85}  (85)              exposed
 3 mmbs_hypothesis D={93}                      masked, not exposed  -> 拒绝
 4 msms_hypothesis D=U\{87}  (87)              masked   -> witness {87}
 5 mmbs_hypothesis D={95}                      masked, not exposed  -> 拒绝
 6 msms_hypothesis D=U\{90}  (90)              exposed
 7 msms            D=U\{93}
 8 mmbs            D={85}
 9 msms            D=U\{95}
10 mmbs            D={87}                      exposed -> 首 MMBS
```

```
C0_role_no_hyp
 1 baseline   D=[]
 2 msms       D=U\{85} (85)
 3 mmbs       D={85}
 4 msms       D=U\{87} (87)  -> 首 MSMS
 5 mmbs       D={87}         -> 首 MMBS
```

filestorage，输入 `stream=stderr`：

```
C_role_qwen                         C0_role_no_hyp
1 D=[]                              D=[]
2 D=U\{2926}  (Qwen MSMS, 未命中)    D=U\{2921}
3 D={2921}    (Qwen MMBS, 未命中)    D={2921}
4 D=U\{2921}                        D=U\{2924}  -> 首 MSMS(4)
5 D={2924}  -> 首 MMBS(5)           D={2924}    -> 首 MMBS(5)
6 D=U\{2924} -> 首 MSMS(6)          D=U\{2926}
```

## 5. 五个问题的直接回答

1. **角色混用是否修复？**
   **是。** v2 中 MSMS 只读 `msms_scores`、MMBS 只读 `mmbs_scores`，
   两个队列独立构造；测试验证任一角色的分数变化不改变另一队列的相对顺序。
   适配层不再把 id 排名换算成 `2.0/(1+rank)` 的共享分数。
2. **错误的 Qwen 假设是否被门控？**
   **是，但不是零成本。** witness 只在 `status=="OK"` 且
   `masked/exposed is True` 时成立；本轮 16 条 MMBS 假设全部未通过
   （0/16），22 条 MSMS 假设通过 7 条。失败假设不获得优先位，被拒绝的
   未知 id 也不进入 U。不过按协议，探测本身计入预算：get_host 上 5 条假设
   占掉前 5 次评估，这是 MMBS 首确认从 5 变为 8–10 的唯一原因。
3. **新顺序是否改善？**
   **部分改善，且方向取决于角色。** 纯角色分离（C0）把首 MSMS 均值从
   4.40 降到 3.00；首 MMBS 从 3.22 升到 4.11（D=U 不再占第 2 位，单操作
   MMBS 少了这一跳板）。带历史 Qwen 假设时，MSMS 3.60（比旧 B 的 6.50
   好很多），MMBS 7.45（比 C0 差 3.3 次，等于探测成本）。oracle 上界
   为 2.00/3.00，说明**只有假设正确时**才有实质空间；本轮 Qwen 的 MMBS
   命中率为 0，因此实际未获益。
4. **100% 预算下的正确性是否保持？**
   **是。** `budget=None` 或 `2^n` 时与穷举逐项一致（9 个合成场景 +
   参数化测试）；预算不足时 `complete=false`，不声称完整；严格子集检查
   未被省略；UNKNOWN/INVALID 从不变成 False；假设 probe 与队列共享同一
   EvidenceStore，没有重复 probe。
5. **是否值得重启 GPU 做真实 Qwen 验证？**
   **不建议现在重启。** 理由：(a) 复用的历史响应已显示 MSMS 7/22、
   MMBS 0/16，结构化输出不会改变模型对这两个任务的事实判断；(b) 32B 模型
   在 24GB 卡上仍有约 8% CPU offload，单次 52–139s；(c) oracle 上界只比
   C0 少约 1 次评估（MSMS 3.00→2.00，MMBS 4.11→3.00），收益接近噪声。
   若要做端到端验证，应换更大的 |U|/多操作任务（M1）并同时换更快的模型；
   本轮的两个 DEV-TUNED 小任务无法体现假设排序的价值。

## 6. 局限

- 仅 2 个 DEV-TUNED 任务，|U|=3/5，真值关系全部是单操作；
- C 复用旧格式 Qwen 输出，结构化协议只有单元测试，没有真实模型样本；
- 记账口径是“子集评估次数”；probe 执行次数被执行器隔离探针主导
  （194/68），不能用作搜索效率的细粒度指标；
- D_oracle 使用逐输入真值，只用于上界，不可部署；
- “角色分离 + 门控”在本轮把 MSMS 拉回确定性顺序的水平，但对 MMBS 的
  净效果为负，因为探测成本先于队列收益。若下一轮继续，建议把门控改为
  “每角色先探 1 条、随后与队列交替”，或按输入生成假设——这两点都**未在
  本轮实现**。

## 7. 产物与复现

- `benchmark_v3_baselines/graph_search.py`（v2 追加，legacy 未动）
- `benchmark_v3_baselines/baseline_c.py`（`search="role_separated"`）
- `scripts/run_full_mace_comparison.py`（结构化协议；`--mode legacy|v2`）
- `scripts/run_role_separated_offline.py`
- `tests/test_role_separated_search.py`
- `runs/v3_role_separated/offline_comparison.json`（逐输入顺序、队列、
  门控与真值检查）
- `runs/v3_role_separated/code_hashes.json`
- `runs/v3_role_separated/offline.log`、`runs/v3_role_separated/tests.log`

复现离线对照（CPU，无模型）：

```
python -m scripts.run_role_separated_offline
```

重跑 v2 全流程（需要 11434 上的 Qwen，本轮未执行）：

```
python -m scripts.run_full_mace_comparison --tasks <task> --budget 16 --mode v2
```
