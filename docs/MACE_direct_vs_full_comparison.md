# Direct Qwen 32B vs Full MACE：10 道 Source-derived 任务公平对比

- 日期：2026-11-05
- 模型：`qwen2.5-coder:32b`（Q4_K_M，digest `b92d6a0b…`）
- 硬件：AutoDL RTX 4090 D，24,564 MiB；实测 65/65 层 offload，模型 18,508 MiB，KV 2,048 MiB，ctx 8,192
- 数据：`benchmark_v4_dataset/source_derived`，10 道已验收 `SOURCE_DERIVED_CONTROLLED`（V4-DEV）
- 结论先行：**按严格 MSMS，Full MACE 5/15，Direct Qwen 3/15，Full MACE 总体更好；但在最难的发现题上 Direct Qwen 更好：双操作协同 2/2 vs 0/2，多路径替代 1/1 vs 0/1。三操作协同两边都是 0/1。Full MACE 与 C0 在 15 个掩盖输入上逐输入完全相同，Qwen 没有带来可测量的最终收益。**

这 10 题的 A 是真实上游语句，但删除和 U 是研究者构造的；不能当成自然上游缺陷。

---

## 1. 协议：两边到底同不同

| 项 | Direct Qwen 32B | Full MACE |
|---|---|---|
| 公开源码 | 同一份 patched source，行号一致 | 同一份 |
| 目标 A | 同一行、同一删除规则 | 同一行 |
| 合法输入 | 同一组不透明标签 `in1..inN` | 同一组 |
| 候选 U | 不提供 | 提供冻结 C0 universe |
| 模型 | `qwen2.5-coder:32b` | 同 |
| 调用次数 | 1 次/题 | 1 次/题 |
| 生成参数 | temp 0，seed 42，ctx 8192，num_predict 4096，retries 0 | 同 |
| 搜索 | 无 | role-separated，budget 16/输入 |
| MSMS 评分 | 严格块族相等 + stray 判错 | 同 |
| MMBS | 不评分 | 记录但不评分（`NOT_SEPARABLE`） |

**输入层面的差异**：Full MACE 多拿到冻结的 C0 候选集合 U；Direct Qwen 可以引用源码里的任意语句。**方法层面的差异**：Full MACE 用因果执行验证假设，Direct 直接输出关系。两者都是各自方法的定义，不是额外调参；Full 的 U 不是 HIDDEN 答案，只是 C0 的公开候选池。

两边的 prompt 都只含公开 patched source、目标 A、合法输入的不透明标签；**不含 HIDDEN 参考答案、真实 MSMS/MMBS 或隐藏 witness**。Full MACE 的 93 次搜索评估是方法内部的因果执行，不是额外模型调用；两边模型调用都是 1 次/题。

### 评分口径

- 主指标：算法输出的 MSMS 集合，经 span containment 投影到隐藏 U 块后，必须与隐藏块族**完全相等**；任何 stray 操作都判错。
- 最小性：严格按隐藏枚举检查；不把 `UNKNOWN` 当 `FALSE`。
- 辅助诊断 `hidden_msms_present`：隐藏块族是否被输出块族**包含**（允许额外集合）。这只说明“找到了正确集合”，不代表严格精确。
- `false_relations` / `unmatched_sets` 按每个 masking 输入累计；同一操作在多组输出中重复出现会计多次，因此它们是噪声量，不是唯一操作数。
- MMBS：`reference.json` 在每题每个输入上把 MMBS 设成 MSMS，隐藏 MMBS 不是独立量；本报告只记录 Full MACE 提出的 MMBS 假设（10 题共 13 条），不参与准确率。
- 条件：两边都输出 condition，但本轮不评条件；这 10 题的隐藏 MSMS 在所有 masking 输入上相同，所以 Direct 不按 condition 路由也不会改变 MSMS exact 口径。

---

## 2. 总表

| 指标 | Direct Qwen 32B | Full MACE |
|---|---:|---:|
| 严格 MSMS 完全匹配 | **3/15** | **5/15** |
| 隐藏 MSMS 被包含（辅助） | **9/15** | 6/15 |
| 错误关系 | 60 | **11** |
| 未匹配集合 | 42 | **4** |
| 覆盖的题 | 2/10（bbcode64、bbcode70） | 4/10（jsonschema、tabulate×3） |
| 双操作协同 | **2/2** | 0/2 |
| 三操作协同 | 0/1 | 0/1 |
| 多路径替代 | **1/1** | 0/1 |
| Prompt tokens | 34,340 | 34,411 |
| Completion tokens | 11,102 | **7,270** |
| 模型墙钟 | 596.5 s | **403.6 s** |
| Full 搜索评估 | — | 93 |
| Full 与 C0 逐输入相同 | — | **10/10 题** |

一句话：**Full MACE 更准、更安静；Direct Qwen 更能发现 C0 候选池漏掉的操作，但输出更吵。**

---

## 3. 逐题结果

格式：`严格 exact / 正确集合被包含 / 错误关系`。

| 题目 | 机制 | masking 输入 | Direct | Full MACE |
|---|---|---:|---:|---:|
| `sd_jsonschema_1145_pointer` | M1 单操作 | 2 | 0 / 2 / 14 | **2 / 2 / 0** |
| `sd_networkx_gexf448_slices` | M8 对象共享状态 | 1 | 0 / 0 / 7 | 0 / 1 / 1 |
| `sd_pygments_bbcode64_color` | M4 多路径替代 | 1 | **1 / 1 / 0** | 0 / 0 / 3 |
| `sd_pygments_bbcode70_italic` | M2 双操作协同 | 2 | **2 / 2 / 0** | 0 / 0 / 2 |
| `sd_pygments_groff73_italic` | M3 三操作协同 | 1 | 0 / 0 / 2 | 0 / 0 / 1 |
| `sd_pygments_latex297_italic` | M6 跨函数状态 | 2 | 0 / 0 / 22 | 0 / 0 / 4 |
| `sd_pygments_style95_cache` | M9 异常回退 | 3 | 0 / 3 / 6 | 0 / 0 / 0 |
| `sd_tabulate_1052_strip_right` | M1 单操作 | 1 | 0 / 0 / 0 | **1 / 1 / 0** |
| `sd_tabulate_1056_strip_center` | M5 条件分支 | 1 | 0 / 0 / 0 | **1 / 1 / 0** |
| `sd_tabulate_2557_curlen` | M7 循环状态 | 1 | 0 / 1 / 9 | **1 / 1 / 0** |

### 关键读法

- Direct 的 3 个严格正确**全部来自难发现题**：`bbcode70`（2 个输入）和 `bbcode64`（1 个输入）。
- Full MACE 的 5 个严格正确**全部来自候选 U 已经包含正确块的题**：`jsonschema`（2 个输入）和 3 道 tabulate。
- Direct 在 `jsonschema`、`style95`、`tabulate_2557` 上也命中了正确集合，但附带多余集合或 stray，严格口径判错；这就是“present 9/15，exact 3/15”的差距。
- `networkx`：Full 找到正确块 U1，但同一集合里还带一个 stray（404），严格判错；Direct 完全没进正确块。

---

## 4. 三个重点题

### 4.1 BBCode 双操作协同：Direct 赢

`sd_pygments_bbcode70_italic`，隐藏 MSMS=`{U1,U2}`，两个 masking 输入。

- **Direct Qwen：2/2 严格正确。**  
  它输出 `{line 72, line 75-76, line 76}`，投影后正好是 `{U1,U2}`；两个输入都命中。
- **Full MACE：0/2。**  
  C0 候选 U 只有 `line 76`（U2 一条腿），模型也只能在 U 内提假设；搜索输出 `{U2}`，缺 U1。
- **差距根因：** 不是搜索预算，而是 Full MACE 的候选池只有一条腿。Direct 不受 U 限制，反而把两条腿都找到了。

### 4.2 Groff 三操作协同：两边都输

`sd_pygments_groff73_italic`，隐藏 MSMS=`{U1,U2,U3}`。

- **Direct：0/1。**  
  它提出的是外层 `if` 跨度 `71-82`，覆盖多个隐藏块，投影为 stray；没有把三条腿拆开。
- **Full MACE：0/1。**  
  C0 候选 U 只有 `line 82`（U3 一条腿），只能输出 `{U3}`。
- **结论：** 三操作协同仍然没有方法能解；Direct 的“看到更多源码”没有自动变成正确的三操作集合。

### 4.3 BBCode 多路径替代：Direct 赢

`sd_pygments_bbcode64_color`，隐藏 MSMS=`{U1}`、`{U2}` 两条替代路径。

- **Direct：1/1。**  
  它的两个 relation 跨度分别落在 `66-67` 和 `82-89`，投影正好是 `{U1}`、`{U2}`。
- **Full MACE：0/1。**  
  C0 候选 U 是 `line 71`、`line 77`，都是错的（bold/underline 路径）；搜索输出的两个集合全部 stray。
- **差距根因：** C0 discovery 选错了操作；Full MACE 原样继承，Qwen 也只在错误 U 内提假设。

---

## 5. Qwen 到底带来了什么？

**在 Full MACE 内部：没有带来可测量的最终收益。**

逐输入对比：

- Full MACE 与冻结 C0 在 **10/10 题、15/15 个 masking 输入**上的 MSMS 块集合和 stray 完全一致；
- 两边都是 **5/15 exact、11 条错误关系、4 个未匹配集合**；
- Qwen 的 hypotheses 被解析、被 gating、被搜索使用（Full 搜索共 93 次评估），但没有改变最终输出的 MSMS。

**在 Direct Qwen 这一侧：有发现收益，但没有精度收益。**

- 它找到了 C0/Full 完全漏掉的 U1/U2 和替代路径，`present` 达到 9/15；
- 但它同时输出大量多余关系（60 条错误、42 个未匹配），严格 exact 只有 3/15；
- 在简单题上反而不如 Full MACE：jsonschema 2 个输入、3 道 tabulate 全部 0。

所以本轮不能笼统说“Qwen 更好”或“Full MACE 更好”：

- **要的是严格、低噪声的 MSMS：Full MACE 更好（5 vs 3）。**
- **要的是发现 C0 候选池外的协同/替代操作：Direct Qwen 更好（3 个难输入 vs 0）。**
- **要的是两者兼得：目前没有。**

---

## 6. Full MACE 的瓶颈在哪里

本轮把瓶颈定位得很清楚：

1. **候选池是硬上限。**  
   Full MACE 不扩 U。`bbcode70` 的 U 只有 U2，`groff73` 的 U 只有 U3，`bbcode64` 的 U 甚至是错误的 bold/underline 行。模型再对，也只能在错误/不完整的 U 内搜索。

2. **Qwen 的 hypothesis 没有改变排序结果。**  
   15 个输入上 Full 与 C0 完全相同；这说明在当前 gating + role-separated 搜索下，Qwen 提的假设没有把正确集合提前到足以改变最终输出，或者正确集合根本不在 U 里。

3. **Direct 的“发现能力”是真的，但“隔离能力”不足。**  
   它能命中 9/15 的正确集合，却只严格精确 3/15；多余集合和 stray 是主要误差来源。

---

## 7. GPU 与真实性证据

- 远端：`NVIDIA GeForce RTX 4090 D`，24,564 MiB。
- 运行前后显存：21,203 MiB → 21,205 MiB；模型常驻。
- Ollama：`qwen2.5-coder:32b`，32.8B，Q4_K_M，digest `b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41`。
- 日志：`offloaded 65/65 layers to GPU`；`CUDA0 model buffer size = 18508.35 MiB`；`KV buffer size = 2048.00 MiB`；`n_ctx = 8192`。
- 未使用本机 RTX 5060；未用 CPU 冒充 GPU。

原始证据：`runs/sd_direct_vs_full/gpu_evidence.json`。

---

## 8. 偏差、限制与必须披露的问题

1. **adapter 调试调用。**  
   第一次冒烟在 `bbcode70` 上因 adapter 的 `key_map` 变量错误，在两次模型调用完成后崩溃；输出未落盘、未参与评分。修复后重新调用。因此 `bbcode70` 实际发生了 **2 次/臂** 调用，只有第 2 次进入结果；其余 9 题各 1 次/臂。这是适配器 bug，不是模型重试。  
   随后用 `sd_tabulate_1052_strip_right` 做冒烟，成功；该题结果保留进正式结果。`run.log` 只覆盖之后的 9 题，`results.json` 是含 1052 的合并后 10 题。

2. **输出数量预算不完全对称。**  
   两边都只调用 1 次、都用 4,096 completion token 上限；但 Direct prompt 允许最多 12 条 relation，Full MACE prompt 允许 3 条 MSMS + 3 条 MMBS。这是两套既有 prompt 的接口差异，本轮没有中途改 prompt。它可能放大了 Direct 的多余集合数量。

3. **条件未评分。**  
   两边都输出 condition，但本轮只评 MSMS 集合。Direct 的 condition 没有用于逐输入路由；由于这 10 题的隐藏 MSMS 在所有 masking 输入上相同，这一简化不影响 exact 口径，但不能外推到 MSMS 随输入变化的题。

4. **MMBS 不可分。**  
   `reference.json` 在每个输入上令 MMBS=MSMS，隐藏 MMBS 不是独立量；Full 输出 11 个 MMBS 集合，仅记录，不评分。

5. **数据是研究者构造的。**  
   A 是真实上游语句，但删除和 U 是构造的；这些数字不能当成自然缺陷检测率。

6. **单次生成。**  
   没有多次采样或置信区间；10 题、15 个 masking 输入，差异应视为方向性证据，不是稳定排名。

---

## 9. 最终回答

### 谁更好？

- **总体严格 MSMS：Full MACE 更好。** 5/15 vs 3/15；错误关系 11 vs 60；未匹配 4 vs 42；completion tokens 7,270 vs 11,102；墙钟 403.6 s vs 596.5 s。
- **难发现题：Direct Qwen 更好。** 双操作协同 2/2 vs 0/2；多路径替代 1/1 vs 0/1；正确集合被包含 9/15 vs 6/15。
- **三操作协同：都不行。** 两边 0/1。

### 差距在哪里？

1. **Full MACE 的上限是 C0 候选池。** 它在 15/15 个输入上与 C0 完全相同；Qwen 没有改变最终 MSMS。候选池漏掉 U1 或选错行时，Full MACE 无法自救。
2. **Direct Qwen 能越过候选池，但不会收敛。** 它找到了 `bbcode70` 的两条腿和 `bbcode64` 的两条替代路径，却常把正确集合埋在大量多余集合里，导致严格 exact 只有 3/15。
3. **真正的下一步不是换模型，而是修 discovery。** 若要让 Full MACE 同时具备 Direct 的发现力和自己的低噪声，需要让 U 覆盖 Direct 能找到的块（或允许受控扩展 U 后再做身份映射），而不是继续在错误 U 内加更多 Qwen 假设。

---

## 10. 产物与复现

主结果：

- `results/MACE_direct_vs_full.json`（1.5 MB，含每题 prompt、raw response、token、时间、评分；sha256 `00a05ff8569bb3f796d742a10b7bc0c5f41c6a7a828dc1414640fb0c4a8a351a`）
- `docs/MACE_direct_vs_full_comparison.md`

逐题原始输出：

- `runs/sd_direct_vs_full/raw/<task>__direct.json`
- `runs/sd_direct_vs_full/raw/<task>__full.json`

逐题独立评分：

- `runs/sd_direct_vs_full/scores/<task>.json`

内部完整运行：

- `runs/sd_direct_vs_full/results.json`
- `runs/sd_direct_vs_full/gpu_evidence.json`
- `runs/sd_direct_vs_full/run.log`

复现命令：

```bash
python scripts/run_sd_direct_vs_full.py \
  --resume --out runs/sd_direct_vs_full/results.json \
  --tasks <task_id> ...
python scripts/build_sd_direct_vs_full_artifact.py
```

本轮未修改数据集、隐藏答案、C0 universe 或算法核心；只新增 SD adapter 和聚合脚本。45 分钟硬截止内完成 10 题，未超时。
