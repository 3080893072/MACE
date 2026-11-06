# MACE Source-derived 第一批 10 题：算法快速验证（v1 pilot）

- 日期：2026-11-04
- 范围：`benchmark_v4_dataset/source_derived/` 中已验收的 10 道
  `SOURCE_DERIVED_CONTROLLED`（V4-DEV）
- 本轮性质：**只测试算法**。未修改算法、未修改 Graph 搜索器、未修改 Qwen
  Prompt/接口、未修改 V4 数据集/HIDDEN/评分器；未重新构造题目、未重新枚举
  标准答案、未运行 515 个旧目标、未运行 SQLAlchemy coverage；未使用 GPU。
- 结果文件：`benchmark_v4_dataset/results/source_derived_v1_algorithm_scores.json`

---

## 0. 一句话结论

在冻结的 4 个方法臂中，**A/B/C 三个可运行臂没有一个能在协同掩盖题
（M2/M3）上复现隐藏 MSMS**；单操作题（M1/M5/M7/M8）在 U 被发现的前提下可被
正确解出。主要瓶颈是**发现阶段（discovery）的操作召回**，而不是搜索阶段：
一旦 U 全部进入候选池，穷举搜索对单操作题是可靠的。D（Full MACE）本轮
**接口不可运行**，状态为 `NOT_RUN`，原因见 §6。

| 方法 | 正确 A | 找到正确 U（题） | MSMS 完全匹配 | 协同题识别 | 探针数 | 耗时 |
|---|---|---|---|---|---|---|
| A. C-fixed-1.1 | 10/10 | 5/10 | 5/15 输入 | **0/2** | 102 | 21.85 s |
| B. Graph-only | 10/10 | 5/10 | 3/15 输入 | **0/2** | 1280 | 58.80 s |
| C. Role-separated C0 | 10/10 | 5/10 | 5/15 输入 | **0/2** | 102 | 25.27 s |
| D. Full MACE | — | — | — | — | — | NOT_RUN |

“正确 A”是题目本身的公开信息（A 在 `task.json` 中给出），因此 10/10 是**构造
使然，不是算法能力**；它只用于确认接口没有把 A 弄错。

---

## 1. 协议：算法看到什么、看不到什么

### 1.1 算法可见（只来自冻结的 PUBLIC task package）

- `P+` 的目标文件源码（与 `source_derived/tasks/<case>/` 中的公开包一致）
- 公开的目标操作 `A`（文件、行号、代码文本）
- 不透明输入网格 `in1..inN`：只暴露输入 id 与可执行入口，**不暴露角色**

关键处理：U 块的 `# SD:U:<id>:begin/end` 分隔注释在交给算法的源码中被
**按行置空（保持行数不变）**，因此块边界不对算法泄漏。已验证置空前后的
universe / scoring / detail 三个字段逐字节相同，说明方法从未依赖这些标记。

### 1.2 算法不可见（严格隐藏）

`reference.json`（U、MSMS、MMBS、输入角色）、`enumeration.json`、子集执行矩阵、
块边界与行映射、标准答案。评分器在**所有方法跑完之后**才读取这些数据，且
只用于对照打分，从不回灌给搜索过程。

### 1.3 执行契约

适配器 `tools/sd_algorithm_pilot.py` 复用冻结的 `benchmark_v3_baselines`
执行器契约：`observation(disabled, "plus"|"minus", payload)`、按
`(subset_key, side, payload_key)` 缓存的 `_runs`、以及 `a_executes` 的
`settrace` 判定。每个变体（不同的操作子集）通过**硬链接包树 + 重写目标文件**
构造，不做任何数据集改动。探针以 `-I` 隔离模式在项目 venv 中 `runpy` 启动。

---

## 2. 指标定义（与 JSON 中 `protocol` 字段一一对应）

| 编号 | 指标 | 定义 |
|---|---|---|
| 1 | 找到正确 A | 算法使用的 A 与隐藏 A 一致（本轮由题目直接给出） |
| 2 | 找到正确 U | 每个隐藏 U 块都被至少一个**被保留操作**的代码区间包含（containment），全部块命中才算该输入 U 命中 |
| 3 | MSMS 完全匹配 | 算法输出的极小保留集族，经 containment 投影到隐藏块 id 后，与该输入隐藏 MSMS 族**相等**，且没有操作落在所有块之外（`stray`） |
| 4 | MMBS 完全匹配 | 见 §5：本数据集中 MMBS 与 MSMS 定义重合，**不可分离评分** |
| 5 | 协同关系识别 | M2/M3 题上 MSMS 完全匹配的输入数（协同题的 MSMS 大小 ≥2） |
| 6 | 成立条件推导 | 无方法输出显式条件；条件处理为 `IMPLICIT_PER_INPUT`（P+=P− 且 A 执行的逐输入门由冻结协议承担），不记为推导成功 |
| 7 | 错误关系 | 输出集合与隐藏 MSMS 族不匹配，且不属于“漏报”的计数 |
| 8 | Probe 数量 / 运行时间 | 算法自身发起的探针进程数与墙钟时间；评分探针单独计，实测为 0（一次探针运行返回全部声明输入） |

两个辅助诊断（不进入主表）：

- `msms_exact_intervention`（更严）：被保留集合在**全部声明输入上的 minus 侧
  观察向量**等于隐藏集合的向量。它比主指标更贴近行为等价，但对“行为上是同一
  块、字面区间略有出入”的情况过严（tabulate 1056 即此类）。
- `got_msms_blocks_identity`：块区间**逐字节一致**，仅作诊断。

---

## 3. 逐题结果

`U` = 隐藏 U 块数；`U found` = 全部 U 块被候选池覆盖；`MSMS` 列为
“匹配输入数/掩盖输入数”。

| 题目 | 机制 | U | 方法 | U found | U 召回 | MSMS | 错误关系 |
|---|---|---|---|---|---|---|---|
| sd_jsonschema_1145_pointer | M1 | 1 | A/B/C | YES | 1.00 | 2/2 / 0/2 / 2/2 | 0 / 10 / 0 |
| sd_networkx_gexf448_slices | M8 | 1 | A/B/C | YES | 1.00 | 0/1 / 1/1 / 0/1 | 1 / 0 / 1 |
| sd_pygments_bbcode64_color | M4 | 2 | A/B/C | no | 0.00 / 0.50 / 0.00 | 0/1 / 0/1 / 0/1 | 3 / 3 / 3 |
| sd_pygments_bbcode70_italic | M2 | 2 | A/B/C | no | 0.50 | 0/2 / 0/2 / 0/2 | 2 / 6 / 2 |
| sd_pygments_groff73_italic | M3 | 3 | A/B/C | no | 0.33 | 0/1 / 0/1 / 0/1 | 1 / 3 / 1 |
| sd_pygments_latex297_italic | M6 | 1 | A/B/C | no | 0.00 | 0/2 / 0/2 / 0/2 | 4 / 4 / 4 |
| sd_pygments_style95_cache | M9 | 1 | A/B/C | no | 0.00 | 0/3 / 0/3 / 0/3 | 0 / 0 / 0 |
| sd_tabulate_1052_strip_right | M1 | 1 | A/B/C | YES | 1.00 | 1/1 | 0 |
| sd_tabulate_1056_strip_center | M5 | 1 | A/B/C | YES | 1.00 | 1/1 | 0 |
| sd_tabulate_2557_curlen | M7 | 1 | A/B/C | YES | 1.00 | 1/1 / 0/1 / 1/1 | 0 / 2 / 0 |

（每个格子的三值按 A/B/C 顺序；单值表示三方法相同。）

### 3.1 逐题成本

| 题目 | 探针数 A/B/C | 时间 A/B/C (s) |
|---|---|---|
| jsonschema_1145 | 6 / 128 / 6 | 2.51 / 6.40 / 2.48 |
| networkx_gexf448 | 22 / 128 / 22 | 8.22 / 13.32 / 11.14 |
| bbcode64_color | 12 / 128 / 12 | 1.72 / 2.81 / 1.87 |
| bbcode70_italic | 6 / 128 / 6 | 1.41 / 3.04 / 1.40 |
| groff73_italic | 6 / 128 / 6 | 1.26 / 2.85 / 1.24 |
| latex297_italic | 20 / 128 / 20 | 2.13 / 3.35 / 2.24 |
| style95_cache | 2 / 128 / 2 | 0.44 / 2.34 / 0.42 |
| tabulate_1052 | 12 / 128 / 12 | 1.63 / 6.89 / 1.79 |
| tabulate_1056 | 8 / 128 / 8 | 1.32 / 7.08 / 1.36 |
| tabulate_2557 | 8 / 128 / 8 | 1.21 / 10.72 / 1.33 |

合计：A = 102 探针 / 21.85 s；B = 1280 探针 / 58.80 s；C = 102 探针 / 25.27 s。
10 题 × 3 方法的端到端墙钟为 **105.9 s**，低于 15 分钟目标（12 路并行预取；
探针数是机器无关口径，墙钟跨机器不可比）。

---

## 4. 主要发现

### 4.1 瓶颈在发现阶段，不在搜索阶段

第一瓶颈是发现阶段的操作召回。5 道 U 全命中的题里，4 道
（jsonschema、tabulate ×3）MSMS 完全匹配；其余 5 道全部是 U 根本没进池：

- `style95_cache`：候选池 **0 个操作**（A 位于元类构造循环，静态 AST 发现看不到）。
- `latex297_italic`：U 在**另一个函数**中（跨函数状态），候选池未覆盖。
- `bbcode64` / `bbcode70` / `groff73`：候选池分别只覆盖 0/2、1/2、1/3 个隐藏块。

第二瓶颈是剪枝：`networkx_gexf448` 的 U 块已进池，但 `rank_and_prune` 把它
连同正确调用一起剪掉，最终输出的极小集不含该块（MSMS 0/1）。也就是说，
“发现到了”不等于“留到了搜索阶段”。

### 4.2 协同（M2/M3）三臂全部失败，且失败方式是“退化为 keep-all”

C 的 `rank_and_prune(max_ops=6)` 按**单操作删除效果**排序，而协同题里每条腿
单独删除都无效果（这正是协同的定义），因此协同腿被剪掉。结果 C-fixed 与
Graph 在掩盖输入上输出的是**平凡的全保留极小集**：它确实“掩盖”（保留全部 U
当然掩盖），因此在过去的口径下会拿到虚高的分，但对隐藏 MSMS 没有任何辨识力。

在协同题上：
- `bbcode70_italic`（M2，MSMS=2）：三臂 U 召回均 0.50，MSMS 0/2。
- `groff73_italic`（M3，MSMS=3）：三臂 U 召回均 0.33，MSMS 0/1。

**协同掩盖识别率 = 0/2（三臂）**。

这也是为什么主指标必须是“块族相等”而不是“行为等价”：若按
`msms_exact_intervention` 评，C-fixed/C0 在这两题上会拿到 **2/2 与 1/1**——
因为 keep-all 在行为上确实与隐藏 MSMS 等价，但输出的集合里根本没有隐藏块。
两个口径的差距本身就是“keep-all 退化”的量化证据。

### 4.3 C0 与 C-fixed 完全等价（在本数据上不可区分）

C0 要求 `search_relations_role_separated(budget=16)`，但本题集 U 上界为 3，
预算 16 足以让角色分离搜索**穷尽**全部候选，于是 C0 退化为与 C-fixed 相同的
结果（15/15 掩盖输入输出一致，探针数同为 102）。差异只在墙钟
（25.27 s vs 21.85 s），属调度噪声。**这不是 C0 无效的证据，而是本批题规模
太小、预算从未被触发的证据。**

### 4.4 Graph-only 更贵且更不准

Graph 的候选池放宽到 6 个操作后，得到的是**多个极小集 + 落在块外的杂散操作**：

- 每题的探针数恒为 128（6 操作空间的完整子集族），是 A/C 的 12.5 倍。
- MSMS 完全匹配反而更少（3/15 vs 5/15），错误关系 28 vs 11。
- 典型如 `jsonschema_1145`：Graph 在每个掩盖输入上输出 **5 个极小集**
  （空集、正确块 U1、以及 3 个块外操作），其中 4 个操作落在所有隐藏块之外，
  被计为 stray 而不是“漏报”——块确实找到了，但被同族的伪极小集稀释。

### 4.5 M4 多路替代没有被识别

`bbcode64_color` 有两个不同的单元素极小集（对应两条替代路径）。三臂 U 召回
0.00/0.50/0.00，均未找到任何一条路径，MSMS 0/1。M4 是本题集中唯一
`u_necessary = false` 的机制，它的失败与 §4.1 的召回问题同源。

### 4.6 控制输入上的退化行为（不计为错误关系）

13 条控制输入在三臂上**全部被搜索、全部非空输出**（A 13/13、B 13/13、
C 13/13），而 10 条暴露输入全部被跳过（`masked_empty = false`，符合预期）。
控制输入“空集即掩盖”是数据集的既定退化设计（`empty_kept_masks = true`），
因此这些输出**不计为错误关系**，但如实记录在 `per_input` 明细里。

### 4.7 没有任何方法输出“成立条件”

所有方法只输出“极小保留集”，不输出“在哪些输入上成立”的显式条件。
逐输入门（P+=P− 且 A 执行）由冻结的干预协议承担。因此指标 6 记作
`IMPLICIT_PER_INPUT`，**未记为推导成功**。

---

## 5. MMBS：不可分离评分

`sd_harness.py:289` 中，MMBS 被直接赋值为 `minimal_masking_sets`，即**每个
输入上 MMBS ≡ MSMS**。因此隐藏 MMBS 不是独立量，无法构成独立评分维度。

处理方式：`mmbs_exact` 记为 `null`，`mmbs_status = "NOT_SEPARABLE"`，并如实
记录各臂输出的 `mmbs_ids` 计数——那是“最小**暴露禁用**集”，与隐藏 MMBS 的
语义不同，**不参与打分**：

| 方法 | 输出 mmbs 集合总数（12 个声明掩盖输入） |
|---|---|
| A. C-fixed | 11 |
| B. Graph | 12 |
| C. C0 | 11 |

需要对 MMBS 做独立评估，前提是数据集把 MSMS 与 MMBS 分别构造（本轮不允许
改数据集）。

---

## 6. D. Full MACE：NOT_RUN

**未运行，未使用 GPU。** 代码级原因：

`scripts/run_full_mace_comparison.py` 的 `call_qwen(task_id, ...)` 通过
`benchmark_v3_baselines.public_io.load_task(task_id)` 加载题目，即该驱动**绑定
在 v3 的 public task id、探针与 fixture 模式上**；SD 包用的是另一套 public
schema。要跑通必须二选一：

1. 改驱动接口（本轮禁止“修改算法/接口”）；
2. 把 SD 题重建为 v3 形式（本轮禁止“重新构造题目”）。

另外，本地 Qwen 端点不可达；autodl 上有 ollama 与 qwen2.5-coder 权重但**没有
正在运行的服务**。A/B/C 均为纯 CPU，不需要 GPU，故未开卡。

---

## 7. 局限性（必须与数字一起阅读）

1. **全部 10 题都是研究者构造（track C）**。这里的失败说明算法在“构造出的
   掩盖题”上的表现，**不能**推断上游存在缺陷。
2. MSMS 等价只在**有限声明输入网格 + 声明块宇宙**上评分；算法在网格外的行为
   未被检验。
3. 主指标用 containment（语句落在块内即视为到达该块），比逐字节区间一致更
   宽松；后者作为 `got_msms_blocks_identity` 单列。
4. 探针数可跨机器比较；墙钟依赖 12 路并行，不可跨机器比较。
5. U 召回是**块级**的上界指标：它回答“块是否被候选池碰到”，不回答
   “算法是否理解该块”。
6. 本批只有 10 题 / 15 个掩盖输入，任何比率的分母都很小（例如 MSMS 5/15），
   不应做显著性断言。

---

## 8. 复现

```bash
KIT=/d/4_____/mace_qwen_pilot_kit
cd "$KIT"

# 1) 跑三臂（A/B/C），可重复 --case 只跑子集
PYTHONIOENCODING=utf-8 python -I benchmark_v4_dataset/tools/sd_algorithm_pilot.py \
    --methods c_fixed graph c0
#    重点三题可单独跑：
#    --case sd_pygments_bbcode70_italic --case sd_pygments_groff73_italic \
#    --case sd_pygments_bbcode64_color

# 2) 汇总为发布用 scores JSON（不重跑探针、不重枚举答案）
PYTHONIOENCODING=utf-8 python -I benchmark_v4_dataset/tools/sd_pilot_scores.py
```

产物：

- **`benchmark_v4_dataset/results/source_derived_v1_algorithm_scores.json`**（发布口径，含 protocol/methods/per_case/totals/caveats）
- `runs/sd_v1_algorithm_pilot/raw_results.json`（30 条原始记录）
- `runs/sd_v1_algorithm_pilot/<case>__<method>.json`（逐题逐臂明细）
- `runs/sd_v1_algorithm_pilot_run.log`（运行日志）
- `benchmark_v4_dataset/tools/sd_algorithm_pilot.py`（适配器，不修改任何算法）
- `benchmark_v4_dataset/tools/sd_pilot_scores.py`（汇总器）
