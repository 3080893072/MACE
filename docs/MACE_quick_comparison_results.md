# MACE 30 分钟快速对比结果

- 日期：2026-11-04
- 模式：`quick_30min`
- 代码：`research/mace-role-separated-search`，HEAD `2f1ee01`
- 数据：`benchmark_v4_dataset/source_derived`，10 道已验收的
  `SOURCE_DERIVED_CONTROLLED`（V4-DEV）
- 结论先行：**确定性三臂中，C-fixed-1.1 与 Role-separated C0 的 MSMS
  主指标最好（5/15），Graph-only 为 3/15；三臂都没有识别双操作/三操作
  协同，也没有识别多路径替代。Full MACE 本轮 NOT_RUN：AutoDL 端点不可达，
  未产生任何 Qwen 调用或 GPU 结果。**

本报告只复用已冻结的确定性结果，不重复运行 C-fixed / Graph-only；
没有新增题目、没有运行 515 个旧目标、没有运行 SQLAlchemy coverage、
没有修改 HIDDEN scorer、冻结 Benchmark、执行器语义或数据集工作目录。

---

## 1. 冻结与复用

| 项 | 值 |
|---|---|
| 题目数 | 10 |
| 划分 | DEV |
| 轨迹 | `SOURCE_DERIVED_CONTROLLED`，研究者构造 |
| 复用结果 | `benchmark_v4_dataset/results/source_derived_v1_algorithm_scores.json` |
| 复用结果 SHA-256 | `711178d30ab613c098123b13909717b4…` |
| 验收注册表 | `benchmark_v4_dataset/registry/source_derived_accepted.json` |
| 本轮新增确定性运行 | 0 |

注意：这 10 题的 A 是真实上游语句，但“删除 A”和 U 是研究者构造的；
**不能当成自然上游缺陷**。

---

## 2. 三臂定义

| 臂 | 发现 | 搜索 | 模型调用 |
|---|---|---|---|
| C-fixed-1.1 | AST discovery + `rank_and_prune(max_ops=6)` | `search_relations(mode=exhaustive)` | 0 |
| Graph-only | `subgraph.build` + `candidate_selection(max_ops=6)` | `search_relations(mode=graph)` | 0 |
| Role-separated C0 | AST discovery + `rank_and_prune(max_ops=6)` | `search_relations_role_separated(budget=16, no hypotheses)` | 0 |

评分口径：

- **MSMS 独立评分**：算法输出的极小保留集族，经 span containment 投影到
  隐藏 U 块后，必须与隐藏 MSMS 族相等，且不能有 `stray` 操作。
- **最小性严格检查**：真子集证据不全或最小集不唯一时，按实际证据记录，
  不把 `UNKNOWN` 当 `FALSE`。
- **MMBS**：`NOT_SEPARABLE`，因为 `reference.json` 在每题每个输入上把
  MMBS 直接设成 MSMS；输出的 `mmbs_ids` 只记录，不参与打分。
- **条件**：三臂都不输出显式条件；逐输入门由冻结干预协议承担，记为
  `IMPLICIT_PER_INPUT`，不算条件推导成功。

---

## 3. 总表

| 方法 | 正确 A | U 全命中题数 | U 平均块召回 | MSMS 完全匹配 | 协同题识别 | 错误关系 | Probe | 墙钟 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C-fixed-1.1 | 10/10 | 5/10 | 0.583 | **5/15** | **0/2** | 11 | 102 | 21.85 s |
| Graph-only | 10/10 | 5/10 | **0.633** | 3/15 | **0/2** | 28 | 1280 | 58.80 s |
| Role-separated C0 | 10/10 | 5/10 | 0.583 | **5/15** | **0/2** | 11 | 102 | 25.27 s |
| Full MACE | — | — | — | — | — | — | — | **NOT_RUN** |

“正确 A”是题目公开信息，10/10 是构造使然，不是算法能力。
Probe 数是机器无关口径；墙钟来自已有冻结运行，跨机器不可直接比较。

补充诊断：`msms_exact_intervention`（更宽松的行为等价诊断，可能把
空保留集/全禁用答案算对）为 C-fixed 6/15、C0 6/15、Graph 0/15。
主表不使用这个口径。

---

## 4. 逐题结果

### 4.1 MSMS / Probe / 时间

格式：`MSMS 完全匹配 / 掩盖输入数 / Probe / 墙钟秒`。

| 题目 | 机制 | U | C-fixed-1.1 | Graph-only | C0 |
|---|---|---:|---|---|---|
| `sd_jsonschema_1145_pointer` | M1 | 1 | 2/2 / 6 / 2.51 | 0/2 / 128 / 6.40 | 2/2 / 6 / 2.48 |
| `sd_networkx_gexf448_slices` | M8 | 1 | 0/1 / 22 / 8.22 | 1/1 / 128 / 13.32 | 0/1 / 22 / 11.14 |
| `sd_pygments_bbcode64_color` | M4 | 2 | 0/1 / 12 / 1.72 | 0/1 / 128 / 2.81 | 0/1 / 12 / 1.87 |
| `sd_pygments_bbcode70_italic` | M2 | 2 | 0/2 / 6 / 1.41 | 0/2 / 128 / 3.04 | 0/2 / 6 / 1.40 |
| `sd_pygments_groff73_italic` | M3 | 3 | 0/1 / 6 / 1.26 | 0/1 / 128 / 2.85 | 0/1 / 6 / 1.24 |
| `sd_pygments_latex297_italic` | M6 | 1 | 0/2 / 20 / 2.13 | 0/2 / 128 / 3.35 | 0/2 / 20 / 2.24 |
| `sd_pygments_style95_cache` | M9 | 1 | 0/3 / 2 / 0.44 | 0/3 / 128 / 2.34 | 0/3 / 2 / 0.42 |
| `sd_tabulate_1052_strip_right` | M1 | 1 | 1/1 / 12 / 1.63 | 1/1 / 128 / 6.89 | 1/1 / 12 / 1.79 |
| `sd_tabulate_1056_strip_center` | M5 | 1 | 1/1 / 8 / 1.32 | 1/1 / 128 / 7.08 | 1/1 / 8 / 1.36 |
| `sd_tabulate_2557_curlen` | M7 | 1 | 1/1 / 8 / 1.21 | 0/1 / 128 / 10.72 | 1/1 / 8 / 1.33 |

### 4.2 U 覆盖

格式：`是否全命中 / 平均块召回`。

| 题目 | C-fixed-1.1 | Graph-only | C0 |
|---|---|---|---|
| `sd_jsonschema_1145_pointer` | Y / 1.00 | Y / 1.00 | Y / 1.00 |
| `sd_networkx_gexf448_slices` | Y / 1.00 | Y / 1.00 | Y / 1.00 |
| `sd_pygments_bbcode64_color` | N / 0.00 | N / 0.50 | N / 0.00 |
| `sd_pygments_bbcode70_italic` | N / 0.50 | N / 0.50 | N / 0.50 |
| `sd_pygments_groff73_italic` | N / 0.33 | N / 0.33 | N / 0.33 |
| `sd_pygments_latex297_italic` | N / 0.00 | N / 0.00 | N / 0.00 |
| `sd_pygments_style95_cache` | N / 0.00 | N / 0.00 | N / 0.00 |
| `sd_tabulate_1052_strip_right` | Y / 1.00 | Y / 1.00 | Y / 1.00 |
| `sd_tabulate_1056_strip_center` | Y / 1.00 | Y / 1.00 | Y / 1.00 |
| `sd_tabulate_2557_curlen` | Y / 1.00 | Y / 1.00 | Y / 1.00 |

---

## 5. 三个重点题

### 5.1 Pygments BBCode 双操作协同（M2）

`sd_pygments_bbcode70_italic`，U=2，隐藏 MSMS=`{U1,U2}`。

- 三臂 U 召回都只有 0.50，只覆盖两条腿中的一条；
- 三臂 MSMS 都是 **0/2**；
- C-fixed/C0 在掩盖输入上输出空保留集 `[[]]`（即禁用全部候选操作）：
  行为上确实掩盖，但输出集合里没有隐藏块，主指标判错；
- Graph-only 还产生 6 条错误关系。

**结论：三臂都没有识别双操作协同。**

### 5.2 Pygments Groff 三操作协同（M3）

`sd_pygments_groff73_italic`，U=3，隐藏 MSMS=`{U1,U2,U3}`。

- 三臂 U 召回都只有 0.33，只覆盖三条腿中的一条；
- 三臂 MSMS 都是 **0/1**；
- 三个真子集都不能恢复 P+，只有三元组可以；但候选池里根本没有完整三元组。

**结论：三臂都没有识别三操作协同。**

### 5.3 BBCode 多路径替代（M4）

`sd_pygments_bbcode64_color`，U=2，隐藏 MSMS 有两个不同的单元素极小集
`{U1}` 和 `{U2}`。

- C-fixed/C0 U 召回 0.00；
- Graph-only U 召回 0.50，找到了其中一条路径的块；
- 但三臂 MSMS 都是 **0/1**：Graph-only 仍留下 1 个未匹配集合和 3 条错误关系，
  没有给出隐藏要求的两个单元素极小集族。

**结论：多路径替代也没有被识别；Graph-only 的 U 覆盖优势没有转化为 MSMS 正确率。**

---

## 6. GPU 与 Full MACE

### 6.1 GPU 检查结果

本轮 **没有拿到任何可用 GPU 证据**，因此没有启动模型阶段：

| 检查项 | 结果 |
|---|---|
| `nvidia-smi` | 未执行成功，SSH 未接通 |
| Ollama 服务 | 未检查成功 |
| `qwen2.5-coder:32b` | 未验证 |
| GPU 实际使用比例 | 未知 |
| 本机 RTX 5060 | 未使用 |

连接尝试：

| 端点 | 结果 |
|---|---|
| `connect.cqa1.seetacloud.com:37377` | `ConnectionRefused (WinError 10061)` |
| `connect.cqa1.seetacloud.com:37376` | TCP 可连，但 `AuthenticationException` |
| `connect.cqa1.seetacloud.com:22` | `BadAuthenticationType`，不接受密码认证 |

后台端口转发也在本轮之前已断开：
`Socket exception ... (10054)` → `SSHException: SSH session not active`。

### 6.2 Full MACE 状态

**`NOT_RUN`**。

- 没有 Qwen 调用；
- 没有 Full MACE 结果；
- 没有把 Graph-only 结果冒充 Full MACE；
- 没有把历史 M11–M13 的四题结果搬到这 10 道题上；
- Full MACE 的 10 道题按方法级 `NOT_RUN` 记录，不伪造逐题 `INCOMPLETE`
  分数；确定性三臂 10/10 完成。

### 6.3 接口差异审计（未安装 adapter）

现有 v3 loader 与 SD public 包的差异：

| 维度 | v3 loader | SD public |
|---|---|---|
| 入口 | `PUBLIC/tasks/<task_id>/task.json`，带 `source_path` / `source_sha256` | `source_derived/tasks/<case>/task.json` + patched source |
| 输入 | 命名 payload + `legal_input_contract` | 不透明 `in1..inN` + `key_map` |
| 执行器 | `benchmark_v3_baselines.execution.Executor` + v3 probe | `SDExecutor` + 每题 probe / venv |
| 候选 U | `baseline_c` 的 v3 universe | AST discovery + `rank_and_prune`，或隐藏 U 块 |
| 驱动 | `run_full_mace_comparison.call_qwen` 调 `load_task(task_id)`；`run_arm` 调 `baseline_c.run(task_id, ...)` | 二者都绑定 v3 task id |

因此不能在 SD 题上直接调用现有 Full MACE 驱动；需要一个独立 adapter，
把 SD 的 public view、`SDExecutor`、hypothesis prompt 和 SD 评分器接起来。
本轮在 5 分钟连接窗口内没有拿到模型端点，按硬截止规则 **未继续实现/运行
adapter**，明确标记 `NOT_RUN`。

---

## 7. MMBS 状态

**`NOT_SEPARABLE`**。

`sd_harness.py` 在每题每个输入上把隐藏 MMBS 直接赋值为
`minimal_masking_sets`，即 MMBS ≡ MSMS。因此隐藏 MMBS 不是独立量，
不能做独立评分。算法输出的 `mmbs_ids` 是“最小暴露禁用集”，与隐藏 MMBS
语义不同，本报告只记录数量，不参与打分。

---

## 8. 五个必须回答的问题

### 8.1 哪个方法找到的正确 U 最多？

**按整题 U 全命中：三者并列 5/10。**  
**按平均块召回：Graph-only 最高，0.633 vs C-fixed/C0 的 0.583。**

但 Graph-only 的额外覆盖只出现在 `bbcode64_color` 的半条替代路径；
它同时产生 28 条错误关系（C/C0 为 11），并固定消耗 128 个 probe
（C/C0 为 102）。所以：
- “块召回均值最高”是 Graph-only；
- “整题正确 U 最多”三家相同；
- Graph-only 的额外覆盖没有转化为 MSMS 正确率。

### 8.2 哪个方法 MSMS 最准确？

**C-fixed-1.1 与 Role-separated C0 并列最好：5/15 个掩盖输入完全匹配。**
Graph-only 为 3/15。

更宽松的行为等价诊断 `msms_exact_intervention`：
C-fixed/C0 6/15，Graph 0/15。该诊断可能给空保留集/全禁用退化答案
虚高分，不作为主指标。

### 8.3 谁能发现双操作和三操作协同？

**没有方法发现。**

- 双操作 `bbcode70_italic`：三臂 MSMS 均 0/2；
- 三操作 `groff73_italic`：三臂 MSMS 均 0/1；
- 合并：协同题识别 **0/2 题、0/3 个掩盖输入**。

失败原因不是搜索预算，而是发现阶段的操作召回：候选池只覆盖
0.50 / 0.33 的协同腿，完整集合根本没有进入搜索空间。

### 8.4 Qwen 是否带来额外收益？

**本轮无法回答：Full MACE NOT_RUN，Qwen 调用 0 次。**

不能把历史 M11–M13 的四题结果当作这 10 题的结果；也不能把
Graph-only 的数字改名为 Full MACE。没有新的 Qwen 证据，就不做额外收益声明。

### 8.5 Full MACE 是否真正运行？

**没有。** 状态 `NOT_RUN`。

原因：
1. AutoDL SSH 端点不可达（端口拒绝/认证失败）；
2. 因此无法检查 `nvidia-smi`、Ollama、`qwen2.5-coder:32b` 和 GPU 比例；
3. 现有 v3 驱动与 SD public schema 不兼容，独立 adapter 尚未安装；
4. 按“5 分钟内无法接通即停止”的硬规则，未继续耗时。

---

## 9. 解读与边界

1. **C0 与 C-fixed 在本数据上不可区分。**  
   U 上界为 3，C0 的 budget=16 足以穷尽全部子集，所以 C0 退化为
   C-fixed；15/15 个掩盖输入输出一致，probe 同为 102。差异只在墙钟
   （25.27 s vs 21.85 s）；本轮未做重复计时，不能把这点差异归因于算法。
   这不是 C0 无效，而是本批题规模太小、预算从未被触发。

2. **真正的瓶颈是发现，不是搜索。**  
   5 道 U 全命中的题里，4 道 MSMS 完全匹配；5 道 U 未全命中的题全部失败。
   `style95_cache` 候选池为 0，`latex297_italic` 的 U 在另一个函数，
   协同题只覆盖部分腿（0.50 / 0.33）。

3. **Graph-only 更贵且更不准。**  
   每题的 probe 固定为 128（6 个操作的全子集族），是 C/C0 的 12.5 倍；
   MSMS 主指标反而更低，错误关系更多。

4. **不能把“行为等价”当成“找到隐藏块”。**  
   空保留集（禁用全部候选操作）在行为上可能等价于隐藏 MSMS，但集合里
   没有隐藏块；主指标按块族相等评分，避免这种虚高。`msms_exact_intervention`
   会把这类退化答案算对，因此只作为诊断，不作为主指标。

5. **本轮没有 Full MACE 结果，也没有 Qwen 额外收益结论。**  
   所有 Full MACE 单元格保持 `NOT_RUN`，不填 0，不推测。

---

## 10. 产物与复现

产物：

- `results/MACE_quick_comparison.json`
  - SHA-256：`ac5869b7f2b2bffe0be5d605c0e7d5dd5fe50cd536160e0393943a7fdc12147b`
- `docs/MACE_quick_comparison_results.md`
- `scripts/build_mace_quick_comparison.py`（只读汇总脚本）

上游冻结结果：

- `benchmark_v4_dataset/results/source_derived_v1_algorithm_scores.json`
- `benchmark_v4_dataset/registry/source_derived_accepted.json`

复现汇总：

```bash
python scripts/build_mace_quick_comparison.py
```

本轮没有新增模型请求、没有 GPU 运行、没有重跑 515 个旧目标、没有运行
SQLAlchemy coverage、没有新增题目、没有修改 HIDDEN scorer 或数据集。
