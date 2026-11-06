# MACE：EXP-1 与 Subgraph-Guided Causal Search 原型结果

分支：`research/mace-subgraph-search`
运行目录：`runs/v3_subgraph_ablation/`
配置哈希：`a3dec6e2cd76fe9ef85e9622068bb2ebf0b268d65dd649317808c93968364853`
全量测试：`297 passed in 69.41s`

本文件只报告本轮实际执行的内容。所有数字来自最后一次（修复执行层命名缺陷后）
的重跑；此前一次含污染变体的运行结果全部作废，未在本文件中使用。

**结论先行**：在五道 DEV-TUNED 开发题上，子图机制**没有**带来任何一条新增的
被评分器确认的关系，也没有减少总 probe 数；它带来的唯一可测收益是在**同一候选
全集**内把首个有效 MSMS 的发现提前（4/5 题 3.1×–11.6×），代价是 MMBS 发现变慢
（4/5 题）和总耗时上升。EXP-1 与执行层修复合起来也没有改变 23 条 credited 关系，
只修正了错误诊断与一个会污染冻结结果的执行缺陷。

---

## 1. EXP-1 实际结果与 H1 / H2 状态

### 1.1 实现

`benchmark_v3_baselines/baseline_c.py:48` 新增模块级函数

```python
def emission_allowed(sets, active, emission_mode="active_filtered"):
    if emission_mode == "minimality_only":
        return [list(item) for item in sets]      # 只去掉成员活跃过滤
    return [list(item) for item in sets if set(item) <= set(active)]
```

`run()` 的 `allowed(sets, active)` 改为委托它（`baseline_c.py:225`）。开关只影响
提交层；下列检查一处未动：

| 检查 | 位置 | EXP-1 下是否保留 |
|---|---|---|
| 干预合法性（unknown operation → INVALID） | `execution.py` / `graph_search.ExecutorOracle` | 保留 |
| A 实际执行与局部效应（`a_executes`、`masked_empty`） | `baseline_c.py:147-158` | 保留 |
| 掩盖谓词（P+ == P-） | `executor.relations` / oracle | 保留 |
| MSMS/MMBS 严格子集最小性 | `execution._minimal_masked/_minimal_exposed` | 保留 |
| UNKNOWN / INVALID 三值分类 | `graph_search` | 保留（仅 graph 模式有三值） |
| 成员活跃性 | `_active_ops` | 仍计算（诊断 + 可比的 probe 计数），不再决定提交 |

### 1.2 五题开发回归（C-original vs C-fixed）

| 题 | 提交 claims | credited | 参考关系 | FALSE | INVALID | UNVERIFIED | probes |
|---|---|---|---|---|---|---|---|
| jinja2_bytecode_cache_read | 4 → 4 | 4 → 4 | 3/3 → 3/3 | 0 → 0 | 0 → 0 | 0 → 0 | 24 → 24 |
| werkzeug_bind_server_name_lower | 4 → 4 | 4 → 4 | 4/4 → 4/4 | 0 → 0 | 0 → 0 | 0 → 0 | 76 → 76 |
| werkzeug_filestorage_stream_name | 4 → 4 | 4 → 4 | 3/3 → 3/3 | 0 → 0 | 0 → 0 | 0 → 0 | 80 → 80 |
| werkzeug_get_host_default_empty | 7 → 7 | 7 → 7 | 5/5 → 5/5 | 0 → 0 | 0 → 0 | 0 → 0 | 396 → 396 |
| werkzeug_secure_filename_ascii_filter | 4 → 4 | 4 → 4 | 3/3 → 3/3 | 0 → 0 | 0 → 0 | 0 → 0 | 120 → 120 |
| **合计** | **23 → 23** | **23 → 23** | **18/18 → 18/18** | **0** | **0** | **0** | **696 → 696** |

在五道题上，C-original 与 C-fixed 的 submission **逐字节相同**。EXP-1 没有新增
任何多元素 MSMS/MMBS，也没有新增 FALSE。

过滤器实际丢弃的已验证最小集（`filter_stats`，逐 input 计数）：

| 题 | MSMS 丢弃/总数 | MMBS 丢弃/总数 |
|---|---|---|
| jinja | 0/4 | 0/4 |
| bind | 1/4 | 0/2 |
| filestorage | 3/6 | 0/3 |
| get_host | 0/6 | 0/6 |
| secure | 10/17 | 0/2 |

其中 **14 个 (set, input) 对属于“成员单独不活跃”**（bind 1、filestorage 3、
secure 10，涉及 7 个不同集合）。这些集合全部出现在**没有 MMBS 见证的 input** 上，而 C 的分组规则
要求同一 input 上先有 MMBS 才能收 MSMS（`baseline_c.py:252`），因此即使放开过滤
也不会变成 claim。这是本轮唯一观察到的 M1 型证据，但它来自 DEV-TUNED 任务，不是
独立验收题。

诊断层的差别是真实存在的：C-original 在 bind/filestorage/secure 上报告
`EXP-1 emission filter dropped verified minimal sets`，并在 filestorage/secure
上报告 `masked input with no causally active minimal sufficient set`；C-fixed
下这些 UNKNOWN 全部消失，因为“没有最小集”的诊断本身是错的——最小集存在，只是
成员单独不活跃。

### 1.3 H1 / H2 状态

预注册（`docs/MACE_next_stage_research_readiness.md` §7）：

- **H1（协同恢复）**：冻结的 M1 协同分层 3 题上，改动后 ≥2/3 题获得 ≥1 条被
  评分器确认的多元素 MSMS/MMBS。
- **H2（开发集回归）**：五道 DEV-TUNED 题上不新增 FALSE/INVALID/UNVERIFIED，
  且 18 条参考关系仍全部确认。

判定：

- **H1 = `H1_PENDING_INDEPENDENT_M1_CASES`**。独立的 M1 验收题不存在；开发集上
  的 14 个 M1 型丢弃项没有一条转化为 claim，且开发集本身不可作为泛化证据。
  合成测试（§7）不能替代它们。
- **H2 = 成立（仅限开发集回归）**：0 FALSE / 0 INVALID / 0 UNVERIFIED，
  18/18 参考关系确认，credited 23 不变，probes 696 不变。这不是泛化准确率。

EXP-1 的收益只能记为**基线缺陷修复**：它把“已验证最小集被静默丢弃并误报为
UNKNOWN”改成如实报告。它不产生新关系。

---

## 2. 旧 C 的问题及最小修复

### 2.1 问题一：提交层丢弃已验证最小集

`allowed(sets, active)` 要求集合的每个成员单独删除时都能改变观察。对真正协同的
操作（单独无效、联合才掩盖）这是错误的过滤条件。它不影响枚举与最小性计算，只
影响提交，因此修复是一行级开关（§1.1）。本轮证明：在现有五题上它不改变任何
claim，只改变诊断。

### 2.2 问题二：变体目录命名碰撞（本轮消融中发现并修复的执行缺陷）

**现象**：第一次完整消融中，Graph-candidates 与 Graph-full 在**同样完整枚举**
的情况下给出不同的 masked 图，且同一子集的观测在两次构建之间发生变化。

**根因**：`execution.Executor.variant()` 用

```python
name = f"{prefix}_{side}_{sanitize(key)}"[:110]
```

做变体目录名。操作 id 形如
`src/werkzeug/datastructures.py:2924-2924`（43 字符），两个 id 的 key 就超过
110 字符，截断后**不同子集得到同一目录名**。`Executor._variants` 又按禁用集合
缓存路径，于是后写入的变体覆盖前一个，后续 probe 读到的是**别的子集**的源码树。

对冻结 C 的候选全集做碰撞审计：

| 题 | U | 子集数 | 碰撞组 | 落在碰撞目录里的子集 |
|---|---|---|---|---|
| jinja | 1 | 2 | 0 | 0 |
| bind | 2 | 4 | 0 | 0 |
| filestorage | 3 | 8 | 1 | 3 |
| get_host | 5 | 32 | 3 | 13 |
| secure | 3 | 8 | 0 | 0 |

filestorage 的碰撞组是 `{2921,2924}`、`{2921,2926}`、`{2921,2924,2926}` 共用同一
目录。对图候选（U=6）碰撞更严重：128 个 (side, subset) 目录名只有 64/44/24/56 个
不同名字（jinja/bind/filestorage/get_host），secure（U=5）为 64→44。

**修复**（`benchmark_v3_baselines/execution.py:33`）：

```python
def _variant_name(prefix, side, disabled):
    digest = hashlib.sha1(_key(disabled).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{side}_{digest}"[:110]
```

并新增回归测试 `test_variant_names_are_unique_after_truncation`
（`tests/test_subgraph_search.py:87`），对 6 个真实 id 的全部 64 个子集 × 2 side
断言目录名互不相同。

**对冻结产物的影响**（必须披露）：

- `runs/v3_baseline_pilot` 下的历史文件未改动；四个模式都只在
  `runs/v3_subgraph_ablation/` 下写新文件。
- 修复后重跑 C-original：jinja / bind / get_host / secure 的 submission 与冻结
  版本**完全相同**；filestorage **不同**。
- filestorage 差异：冻结版本把 `MSMS {2924}` 记为 `WITNESS_VERIFIED`（单 input），
  修复后同一关系在 3 个 input 上成立，记为 `FINITE_DOMAIN_EXACT`。逐 input 比较
  显示，冻结结果在 input 4/5 上多出两条**不存在**的 MSMS：`{2921,2924}`、
  `{2924,2926}`。它们当时被成员活跃过滤器丢掉，所以没有进入冻结 submission；
  但 masked 图本身是错的。
- 因此：**冻结 pilot 的 filestorage per-input 证据不可信**；submission 层面的
  23 条 credited 与 18/18 参考关系不受影响（修复后仍为 23 与 18/18）。
- **重要交互**：如果没有先修执行层，EXP-1 放开过滤器后会直接提交这两条污染
  关系。也就是说，EXP-1 的安全性依赖该执行修复。这一点是由上述数据推导出的
  结论，本轮没有实际执行“未修复 + EXP-1”的组合。

**冻结清单状态**：`python scripts/v3_freeze_manifest.py --verify runs/v3_baseline_freeze`
现在报 `FREEZE VERIFY FAILED - section changed: code_files`，因为
`baseline_c.py` 与 `execution.py` 的函数体变了：

| 文件 | 冻结 SHA-256 | 当前 SHA-256 |
|---|---|---|
| baseline_c.py | `747423a018e99b561bd6c698a242c69b556f6f5041a4622dfeed0805d41ca8b6` | `422356d645bc364300cc0de76f2781a508da01a70e1beae192c93fcdd5a3cb6a` |
| execution.py | `a66dfaaca27287c122a62a103724327749834c6a95b40a6b6e1e1a8f2709d74c` | `7d4bab5a737badb234c523b5af587250b93d06f35ec4b742f7f6d43f31d6b5ac` |

这是有意的、单独记录的分支偏离，不是静默改写。冻结 pilot 仍需保留旧代码哈希；
是否重新冻结由后续决定，本轮不做。

---

## 3. 子图数据结构和构建规则

实现：`benchmark_v3_baselines/subgraph.py`（796 行）。schema
`mace-a-centered-subgraph-0.1`。

### 3.1 节点

语句节点（`ast.stmt`，排除 `FunctionDef/AsyncFunctionDef/ClassDef` 本身）：

```json
{"id": "<file>:<first>-<last>", "file": ..., "first_line": ..., "last_line": ...,
 "kind": "assign|if|for|return|expr|...", "code": "...",
 "function": "...", "contains_target": bool, "deletable": bool,
 "defs": [...], "attr_defs": [...], "uses": [...], "calls": [...],
 "guards": [...], "in_loop": bool}
```

A 所在语句是非删除锚点。`deletable=False` 的节点（A 本身）不能进候选。

### 3.2 边

```json
{"src": ..., "dst": ..., "kind": "data|control|alias|call",
 "confidence": "MUST|MAY|UNKNOWN", "evidence": "...", "guard": "..."}
```

- **data**：函数内同名的 def→use（定义在后为 `MUST`；循环回边为 `MAY`）；
  同名变量的多个定义之间的竞争定义边（用于发现后面覆盖前面的 fallback 赋值）；
  函数间通过参数/返回值的传播。
- **control**：`if/for/while/except` 节点到其语句体，`guard` 记录谓词文本。
  控制节点只拥有自己的谓词事实，**不继承体内语句的 defs/uses**（有测试固定）。
- **alias**：`alias = total` 这类赋值绑定；属性别名（`self.x`）；容器元素
  传播。`alias` 权重 1.2。
- **call**：同文件、同类作用域、可解析的同名调用；跨类同名方法不算（否则
  `__init__` 互相污染，曾导致 filestorage 的错误候选 332）。
- 无法解析的调用、跨类同名调用、动态属性：写成 `UNKNOWN` 边或 `unknowns`
  条目，**不剪枝**。

边权 `data 1.0 / control 0.7 / alias 1.2 / call 1.5`，`MAY ×1.2`，
`UNKNOWN ×1.5`。

### 3.3 函数选择

从 A 所在函数出发，沿同文件可解析调用向前（有界），并向后取至多两层调用者；
`max_functions=16`。类作用域感知：同名方法只在同一 enclosing class 内匹配。

### 3.4 候选打分与输出

```python
score = 1.0/(1+dist_to_A) + 0.5/(1+dist_to_observation)
        + 0.25*min(shared_state,3)
        + 0.25*min(writes_target,1)      # 直接重写 A 写的变量
        + 0.10*same_function
        - 0.05*min(unresolved_calls,2)
```

`candidate_selection(graph, max_ops)` 输出 `ops / eligible / selected /
truncated / omitted`。截断是资源限制，不是证据剪枝：被省略的节点仍留在
`graph["candidates"]` 里。

每个候选带来源证据：`path`（到 A 的最短依赖路径，逐边 kind/confidence/
guard）、`distance_to_A`、`distance_to_observation`、`shared_state`、
`writes_target`、`same_function`。

### 3.5 五题实际规模

| 题 | 节点 | 边 | data | control | alias | call | MUST | MAY | UNKNOWN | 可删除节点 | 候选选中/可用 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| jinja | 19 | 100 | 21 | 7 | 62 | 10 | 28 | 66 | 6 | 11 | 6/11 |
| bind | 70 | 706 | 169 | 39 | 410 | 88 | 205 | 476 | 25 | 49 | 6/49 |
| filestorage | 17 | 67 | 20 | 11 | 32 | 4 | 31 | 32 | 4 | 10 | 6/10 |
| get_host | 40 | 151 | 30 | 39 | 71 | 11 | 69 | 79 | 3 | 21 | 6/19 |
| secure | 10 | 103 | 15 | 4 | 76 | 8 | 19 | 76 | 8 | 5 | 5/5 |

`unknowns` 记录了每个无法静态确认的调用（jinja 12、bind 20、filestorage 3、
get_host 3、secure 8 条）。

---

## 4. Graph-Guided Search 伪代码

实现：`benchmark_v3_baselines/graph_search.py`。

```
SEARCH_RELATIONS(executor, payload, U, scores, mode, budget):
    store ← EvidenceStore(oracle)                # 三值证据缓存
    dynamic[op] ← 0 for op in U
    pending ← all 2^|U| subsets
    first_msms ← first_mmbs ← None
    while pending and store.evaluations < budget:
        if mode == "graph":
            D ← argmin_{S∈pending} ( min(|S|, |U\S|),        # 对称前沿
                                     -role_score(S),          # 图相关性
                                     |S|, S )                 # 确定性 tie-break
        else:
            D ← argmin_{S∈pending} (|S|, S)                   # 原始枚举序
        pending.remove(D)
        rec ← store.evaluate(D)
            # KeyError            → INVALID（干预不合法）
            # probe 无可用观测     → UNKNOWN（保留，不当 False）
            # 否则                → OK(masked, exposed)
        if rec.status == OK:
            if rec.masked:  boost ops ∉ D
            if rec.exposed: boost ops ∈ D     # 每 op +0.05，上限 0.25
        record first_msms / first_mmbs when minimal sets first become confirmable
    return MINIMAL_MASKED(U, store), MINIMAL_EXPOSED(U, store),
           complete, evidence_complete

MINIMAL_MASKED(U, store):                 # MSMS
    for S ⊆ U, S ≠ ∅:
        v ← store.get(U \ S).masked       # Masked_strict(U \ S)
        if v is not True: continue
        for S' ⊂ S, S' ≠ ∅:
            if store.get(U \ S').masked is True: drop S
            if UNKNOWN: S is "minimality-unknown", never confirmed
        else confirm S

MINIMAL_EXPOSED(U, store):                # MMBS
    for D ⊆ U, D ≠ ∅:
        if store.get(D).exposed is not True: continue
        for D' ⊂ D, 含空集:
            if exposed(D') is True: drop D
            if UNKNOWN: block
        else confirm D
```

`role_score`：当 `|D| ≤ |U\D|` 时用 MMBS 侧得分（D 上分数和），否则用 MSMS 侧
（补集上分数和）。图分数只用于排序；自适应 boost 只用于排序；两者都不改变
候选集合。

`profile_from_maps()` 是给原始枚举用的**事后**首次有效成本重建：用同一批已算出
的 masked/exposed 映射，按枚举顺序逐个子集喂进同一个最小性判定器，不额外执行
probe。C 的真实运行不会早停，所以它的“首次有效”是反事实量。

---

## 5. 搜索正确性、完整性及限制

### 5.1 正确性

- 三值语义：`UNKNOWN` 永远不是 `False`。`minimal_masked_sets` /
  `minimal_exposed_sets` 把“最小性比较遇到 UNKNOWN”的集合放进 `msms_unknown`
  / `mmbs_unknown`，不放进 confirmed。
- 非法干预（`KeyError`）→ `INVALID`，不参与任何关系。
- 无安全剪枝：代码里没有任何“已掩盖则超集也掩盖”的推理。`graph` 模式在无预算
  时**枚举全部子集**，只改顺序。`budget` 小于 2^|U| 时结果标 `complete=False`。
- 最小性按公开定义逐严格子集检查；MMBS 的子集检查包含空集。
- 图只提供候选和排序。静态边从不直接产生 claim（`test_static_dependence_is_not_a_causal_claim`）。

### 5.2 完整性

- `complete` = 所有子集都有证据记录。
- `evidence_complete` = `complete` 且无 UNKNOWN/INVALID 且无最小性被阻断。
  两个字段分开，避免把“枚举完了”说成“证据齐了”。
- 本轮五题 24 个 masked input，Graph-full 全部 `complete=True`、
  `evidence_complete=True`、UNKNOWN/INVALID = 0。
- C-original/C-fixed/Graph-candidates 走原始枚举，把 probe 失败折叠成
  not-masked/not-exposed，因此 `evidence_complete` 记为 `None`（不声称），
  这是既有限制，不是本轮引入的。

### 5.3 限制

1. **候选全集不同**：C 的 U 是 AST 发现 + 效应剪枝（1–5 个），Graph 的 U 是
   子图 top-k（5–6 个）。因此 C 与 Graph 的 credited 数**不是同一候选全集下的
   比较**。
2. **评分器的 U 是隐藏参考声明的 U**。子图选出的、不在该 U 内的操作一律
   `UNVERIFIED`（scorer 契约），不是 FALSE。本轮 Graph 模式的 7 条
   UNVERIFIED 全部属于这一类。
3. **最小性依 U 而变**。扩大 U 会让原本单元素最小的关系不再最小（见 §9 的
   universe-change 效应），这是定义的结果，不是错误。
4. **顺序启发式没有正确性保证**。首个有效关系的提前量不承诺在所有题上成立；
   本轮 MMBS 侧反而是 4/5 题变慢。
5. **子图静态分析保守但不完备**：动态属性、跨模块调用、容器元素仍记为
   MAY/UNKNOWN；缺失这些边不会剪枝，但会降低排序质量。
6. **全部结果 DEV-TUNED**，不可作为泛化证据。

---

## 6. 新增测试和源码位置

| 文件 | 行数 | 作用 |
|---|---|---|
| `benchmark_v3_baselines/graph_search.py` | 426 | 三值证据、最小性、排序、预算、成本剖析 |
| `benchmark_v3_baselines/subgraph.py` | 796 | A 为中心的依赖子图与候选打分 |
| `benchmark_v3_baselines/synthetic_cases.py` | 151 | 9 个合成场景与 truth table |
| `benchmark_v3_baselines/baseline_c.py` | 408 | EXP-1 开关、四种模式接线、诊断字段 |
| `benchmark_v3_baselines/execution.py` | 284 | 变体命名修复（§2.2） |
| `tests/test_subgraph_search.py` | 261 | 35 个算法测试 |
| `scripts/run_subgraph_ablation.py` | 368 | 四模式消融驱动（先跑完再评分） |

测试覆盖（35 个）：

- EXP-1：联合才掩盖、成员独立掩盖、非法干预、UNKNOWN 阻断最小性、非单调。
- 9 个合成场景与手推期望逐一比对；graph 与 exhaustive 结果等价；预算不足
  标为不完整。
- 子图：data/control/alias/call 边、UNKNOWN 边、控制节点不继承体内事实、
  类作用域隔离、候选截断如实上报、静态依赖不产生因果 claim。
- 回归：变体目录名唯一性。

运行：

```bash
python -m pytest -q                                  # 297 passed
python -m scripts.run_subgraph_ablation              # 四模式 + 评分
```

---

## 7. 四组消融结果

### 7.1 总量

| 模式 | 候选全集合计 | claims | credited | 参考关系 | FALSE | INVALID | UNVERIFIED | 已验证 MSMS/MMBS | 子集评估 | probes | 变体 | 总耗时 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-original | 14 | 23 | 23 | 18/18 | 0 | 0 | 0 | 37 / 17 | 300 | 696 | 112 | 198.4 |
| C-fixed | 14 | 23 | 23 | 18/18 | 0 | 0 | 0 | 37 / 17 | 300 | 696 | 112 | 197.3 |
| Graph-candidates | 29 | 24 | 17 | 14/18 | 0 | 0 | 7 | 50 / 21 | 1312 | 2644 | 576 | 724.1 |
| Graph-full | 29 | 24 | 17 | 14/18 | 0 | 0 | 7 | 50 / 21 | 1312 | 2644 | 576 | 738.1 |

`候选全集合计` 是逐题 |U| 之和。Graph-full 记录的 executor cache hit 为 273；
Graph-candidates/C 走原始枚举，同一批缓存命中存在但未计数（不可比）。

### 7.2 逐题：覆盖与证据等级

| 题 | C 的 U | Graph 的 U | C credited | Graph credited | C 参考 | Graph 参考 | Graph UNVERIFIED | 候选覆盖 C 全集 |
|---|---|---|---|---|---|---|---|---|
| jinja | 1 | 6 | 4 | 2 | 3/3 | 2/3 | 2 | 1/1 |
| bind | 2 | 6 | 4 | 2 | 4/4 | 2/4 | 1 | 2/2 |
| filestorage | 3 | 6 | 4 | 2 | 3/3 | 2/3 | 1 | 3/3 |
| get_host | 5 | 6 | 7 | 7 | 5/5 | 5/5 | 0 | 5/5 |
| secure | 3 | 5 | 4 | 4 | 3/3 | 3/3 | 3 | 3/3 |

**候选覆盖 15/15**：子图候选完整包含 C 经过效应剪枝后保留的全部操作，并且每题
多出 1–5 个操作（合计 15 个）。多出的操作全部被评分器判为
`outside the declared candidate universe` → UNVERIFIED。

### 7.3 逐题：成本与首次有效关系

`fMS/fMM` 是首次可确认 MSMS/MMBS 时的子集评估序号（均值，跨该题 masked
input）；每次评估 = 2 个 probe。

| 题 | 模式 | 评估 | 子集总数 | fMS | fMM | probes | 变体 | 耗时 s |
|---|---|---|---|---|---|---|---|---|
| jinja | C-original | 8 | 8 | 1.0 | 2.0 | 24 | 4 | 5.8 |
| jinja | C-fixed | 8 | 8 | 1.0 | 2.0 | 24 | 4 | 5.7 |
| jinja | Graph-candidates | 256 | 256 | 63.0 | 2.0 | 516 | 128 | 103.1 |
| jinja | Graph-full | 256 | 256 | 62.0 | 3.0 | 516 | 128 | 104.0 |
| bind | C-original | 12 | 12 | 2.7 | 2.0 | 76 | 12 | 23.9 |
| bind | C-fixed | 12 | 12 | 2.7 | 2.0 | 76 | 12 | 24.1 |
| bind | Graph-candidates | 192 | 192 | 192.0 | 2.0 | 392 | 128 | 138.1 |
| bind | Graph-full | 192 | 192 | 23.0 | 8.0 | 392 | 128 | 140.0 |
| filestorage | C-original | 32 | 32 | 5.8 | 3.0 | 80 | 16 | 23.7 |
| filestorage | C-fixed | 32 | 32 | 5.8 | 3.0 | 80 | 16 | 24.2 |
| filestorage | Graph-candidates | 256 | 256 | 59.5 | 5.0 | 516 | 128 | 154.3 |
| filestorage | Graph-full | 256 | 256 | 19.0 | 3.0 | 516 | 128 | 162.9 |
| get_host | C-original | 192 | 192 | 30.7 | 2.3 | 396 | 64 | 111.7 |
| get_host | C-fixed | 192 | 192 | 30.7 | 2.3 | 396 | 64 | 109.7 |
| get_host | Graph-candidates | 384 | 384 | 61.7 | 3.3 | 770 | 128 | 208.3 |
| get_host | Graph-full | 384 | 384 | 5.3 | 4.3 | 770 | 128 | 209.9 |
| secure | C-original | 56 | 56 | 5.3 | 3.0 | 120 | 16 | 33.4 |
| secure | C-fixed | 56 | 56 | 5.3 | 3.0 | 120 | 16 | 33.7 |
| secure | Graph-candidates | 224 | 224 | 27.3 | 4.0 | 450 | 64 | 120.3 |
| secure | Graph-full | 224 | 224 | 7.3 | 11.0 | 450 | 64 | 121.4 |

Graph-full 首次有效的实际耗时（均值，秒）：jinja MSMS 22.3 / MMBS 0.41；
bind 14.2 / 2.14；filestorage 8.9 / 1.03；get_host 1.62 / 1.08；
secure 1.64 / 4.77。

### 7.4 唯一同候选全集的比较：Graph-candidates vs Graph-full

两者 U 相同、probes 相同、最终 submission **逐字节相同**（5/5 题）、
credited 相同（17）。差别只在顺序与成本计量：

| 题 | fMS 评估（cand → full） | 倍数 | fMM 评估（cand → full） | 倍数 |
|---|---|---|---|---|
| jinja | 63.0 → 62.0 | 1.02× | 2.0 → 3.0 | 0.67×（变慢） |
| bind | 192.0 → 23.0 | 8.3× | 2.0 → 8.0 | 0.25×（变慢） |
| filestorage | 59.5 → 19.0 | 3.1× | 5.0 → 3.0 | 1.7× |
| get_host | 61.7 → 5.3 | 11.6× | 3.3 → 4.3 | 0.8×（变慢） |
| secure | 27.3 → 7.3 | 3.7× | 4.0 → 11.0 | 0.36×（变慢） |

图排序对 MSMS 侧有效（4/5 题 3.1×–11.6×，jinja 基本持平），对 MMBS 侧 4/5 题
变慢。原因是 sym-frontier 先展开空集与全集、再展开单元素层；而原始枚举本来
就把单元素删除排在很前面，MMBS 往往在第 2–4 次评估就出现。

### 7.5 重复 probe 与缓存

- Graph-full 记录 273 次 executor cache hit（`_active_ops` 隔离阶段的单操作
  probe 被搜索复用）。
- 但每次评估仍是 plus+minus 两个 probe，总 probe 数 = 2×评估数 + 隔离/基线
  probe，与 Graph-candidates 完全相同（2644）。
- 结论：在保留完整枚举的前提下，图排序**不减少总 probe**；它只改变顺序。
  这与 §六的提醒一致。

---

## 8. 哪些收益来自 Bug 修复

| 修复 | 对 claim 的影响 | 对诊断的影响 | 对成本的影响 |
|---|---|---|---|
| EXP-1 过滤器开关 | 五题 0 新增、0 删除、0 FALSE | 去掉 3 条错误 UNKNOWN（bind/filestorage/secure），不再把 14 个已验证最小集说成“没有最小集” | 0（probe 数 696 不变） |
| 变体目录命名（§2.2） | filestorage 的 `MSMS {2924}` 由 `WITNESS_VERIFIED` 变为 `FINITE_DOMAIN_EXACT`（3 inputs）；credited 仍 23；参考仍 18/18 | 移除 filestorage input 4/5 上两条不存在的 MSMS | 0（变体数/probe 数不变） |

**没有任何一条 credited 关系来自这两处修复。** 冻结的 23 条 credited / 18 条
参考关系在修复前后一致。修复的价值是**证据正确性**与**避免未来误报**，不是分数。

需要特别记录的负向事实：如果没有变体命名修复，EXP-1 会把 filestorage 的两条
污染 MSMS 直接提交；这会让 EXP-1 的“收益”看起来更大，但其中至少部分是假的。
本轮先修执行层、再评 EXP-1，顺序不可颠倒。

---

## 9. 哪些收益来自新子图机制

可分三层回答（对应 §六的四个问题）：

1. **子图能否发现 C 没找到的候选？**
   能：15/15 覆盖 C 全集，另有 15 个 C 未保留的操作。但在评分器声明的 U 之外，
   这些操作只能得到 UNVERIFIED，**新增 credited = 0**。

2. **图引导能否在相同候选全集下减少成本？**
   不能减少总成本：同一 U 下 Graph-full 与 Graph-candidates 的评估数、probe 数、
   变体数完全相同（1312 / 2644 / 576），submission 相同。
   它能减少的是**首个有效 MSMS 的发现成本**：4/5 题 3.1×–11.6×。这是顺序收益，
   不是候选收益，而且 MMBS 侧反而变慢。

3. **新的搜索顺序是否会遗漏协同关系？**
   在本轮设置下不会：graph 与 exhaustive 在 9 个合成场景上结果完全一致，在五题
   上 submission 与 Graph-candidates 逐字节相同。因为它保留全枚举，没有安全剪枝。

4. **原来的性能损失来自什么 Bug？**
   来自两处，且都不解释 credited 的下降：提交层过滤（不影响现有五题）与变体
   命名碰撞（只影响 filestorage 的证据等级）。Graph 模式的 credited 从 23 降到
   17 **不是 bug**，而是候选全集扩大后最小性定义改变： jinja `{137}` 不再单独
   最小、bind `{219}` 变为 `{219,344}`、filestorage `{2924}` 变为
   `{2924,2928}`。这些扩展集合落在评分器 U 之外 → UNVERIFIED，同时原来的单元素
   集合又因为不再最小而不再提交。

**净结论**：在五道 DEV-TUNED 题上，子图机制相对修正后的确定性基线 C-fixed 的
独立、可验证算法收益为 **0 条 credited 关系**；唯一正向可测量的是同 U 下 MSMS
首次发现成本，代价是 MMBS 首次发现变慢、总 probe 增加 3.8×、总耗时增加 3.7×。
这不足以支持“子图引导带来算法收益”的结论；它支持的是“图候选会扩大 U，而扩大
U 在固定声明 U 的评分协议下会稀释最小性”。

---

## 10. 尚未解决的问题及独立验证所需证据

1. **独立 M1 验收题缺失**。H1 仍是 pending。需要 3 道非 DEV-TUNED、预先冻结的
   协同题，至少 2/3 出现多元素最小集；本轮不得用合成题代替。
2. **候选全集与评分器声明 U 的关系未定义**。当前子图候选天然会越界，越界只能
   UNVERIFIED。需要二选一：
   (a) 评分协议允许提交方声明 U 并在此 U 内评分（须防“U 挑选”作弊）；
   (b) 子图候选必须约束到声明的 U 内（则子图发现能力无法体现）。
   在这个问题解决前，Graph 模式的 credited 不可能公平反映其发现能力。
3. **预算受限搜索未评估**。本轮没有安全剪枝，所以预算内只能改变顺序。要证明
   图引导“省 probe”，需要在有正确性依据的受限搜索（例如带证明的分支界）上做，
   而不是在完整枚举上做。
4. **MMBS 排序策略需要单独设计**。sym-frontier 让 MMBS 变慢；可考虑按角色分层
   或对 MMBS 使用独立的单元素优先前沿。
5. **候选排序的真实增益未分离**。本轮 `writes_target` 加分是为了把 C 的 231
   纳入候选而加的；它属于启发式调参，必须在独立题上重新检验，不能计入机制收益。
6. **冻结清单偏离未处理**。`code_files` 已与冻结清单不一致。需要决定是保留
   旧哈希 + 单独记录修复，还是发布新的冻结版本。
7. **预注册的 10 项目 / 15 题规划未动**。本轮没有新增、替换或挑选测试项目；
   跨项目结论仍无证据。
8. **LLM 候选源未实验**。Graph-only / Graph+LLM 接口保留但未运行，本轮无 GPU、
   无 Agent、无 Prompt 阶段。

---

## 附：产物、哈希与复现

```
runs/v3_subgraph_ablation/
  config.json                  # 任务哈希、模式定义、代码 SHA-256、环境
  config.sha256                # a3dec6e2cd76fe9ef85e9622068bb2ebf0b268d65dd649317808c93968364853
  summary.json                 # 四模式汇总 + 逐题 summary/score
  refmatch/<mode>/reference_match.json   # 评估侧参考关系比对（18 条）
  tasks/<task>/
    subgraph.json              # 子图（节点/边/候选/unknowns）
    candidates.json            # 选中的 top-k 与图分数
    <mode>/result.json         # 完整运行记录（含 per_input 证据）
    <mode>/submission.json     # 提交
    <mode>/summary.json        # 逐题成本
    <mode>/score.json          # 评分器原始输出
    <mode>/score_summary.json  # 状态计数
```

代码哈希（本轮实际运行版本）：

| 文件 | SHA-256 |
|---|---|
| baseline_c.py | `422356d645bc364300cc0de76f2781a508da01a70e1beae192c93fcdd5a3cb6a` |
| execution.py | `7d4bab5a737badb234c523b5af587250b93d06f35ec4b742f7f6d43f31d6b5ac` |
| graph_search.py | `d4b5ae764dc6d7973b1b597b38063be5a084899c729bf28b3b38beeefa2b0dd2` |
| subgraph.py | `9257c9eb1d6a27fbb0611ed51c0cad90e41634fe938e7a356ddf0422c6849771` |
| synthetic_cases.py | `2679c930005bde3c9610d6d920f82e993f34a45dc0fff57f77af5f92334741c6` |
| tests/test_subgraph_search.py | `3a2e52599f6f98174a07fede6870b3a87677dbf83fc248771adb4c01f42461a4` |
| run_subgraph_ablation.py | `b350b5b930398d78faffc403c3157329c16ba932879db90fa392776b9ed7f197` |

基准提交：`e53e58716f5f08d342798747a27e69eef6722000`。本轮改动在运行时尚为
未提交工作树，因此以文件哈希为准；`config.json` 中的 `git_status_short` 也记录了
这一点（其中 `benchmark_blind_v1/*` 等条目是本轮之前就存在的未跟踪/已修改文件）。

复现：

```bash
python -m scripts.run_subgraph_ablation            # 约 18 分钟，CPU
python -m pytest -q                                # 297 passed
python scripts/v3_reference_match.py \
  --run runs/v3_subgraph_ablation/refmatch/C-fixed  # 评估侧比对
```

本轮未使用 GPU、未调用任何模型、未读取 HIDDEN 数据修改逻辑；评分与参考比对都在
全部运行结束之后独立执行。
