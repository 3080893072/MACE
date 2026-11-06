# MACE Candidate Discovery v2：Qwen 辅助候选扩展

- 日期：2026-11-05
- 模型：`qwen2.5-coder:32b`（Q4_K_M，digest `b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41`）
- 硬件：AutoDL RTX 4090 D，24,564 MiB；`ollama ps` 显示 `100% GPU`、ctx 16,384、占用 23,261 MiB
- 范围：只跑 4 道冻结题（BBCode 70、BBCode 64、Groff 73、NetworkX GEXF 448）
- 本轮没有修改数据集、HIDDEN scorer、C0 universe、Graph-only 结果或搜索算法核心；没有新增题目，没有跑旧 515 目标。

## 0. 结论先行

1. **Qwen 真的扩展了 U，但只扩展了 4 题中的 3 题，而且 BBCode 64 只扩了一半。** 新增且落在隐藏块内的操作：BBCode 70 加 1 个（line 72），BBCode 64 加 1 个（line 67），Groff 73 加 2 个（line 75、78）。NetworkX 新增 **0** 个（Qwen 只重提已在 U_graph 的 451 和 456）。U_union 召回：BBCode 70 从 0.5 到 1.0，BBCode 64 从 0.0 到 0.5，Groff 73 从 0.333 到 1.0，NetworkX 维持 1.0。BBCode 64 的 Qwen 还提了已在 U_graph 的错误行 71，并漏掉第二条替代路径 line 88。
2. **BBCode 双操作协同第一次被 Full MACE 解出：2/2。** Qwen 提出 `{72,76}`，因果执行确认它 masked 且严格最小，正好是隐藏的 U1+U2。
3. **Groff 三操作协同第一次被解出：1/1。** Qwen 提出 `{75,78,82}`，因果执行确认三操作集合 masked 且最小，正好是 U1+U2+U3。
4. **NetworkX 的“剪枝把正确候选剪掉了”这个前提不成立，因此没有可修的剪枝 bug。** 451 一直在 C0 universe 里（C0 = 404、451、456）；真正的错误是 404 这个 stray 也被保留，搜索输出 `{404,451}`，投影为 U1 + stray 404。Graph-only universe 的辅助诊断能在 in1 上得到 `{451}` 且 exact 1/1，说明失败点是多出来的 AST 候选 404，不是 rank_and_prune 丢了 451。
5. **Full MACE 第一次在这四题上超过 C0。** 新方法 strict exact 3/5，C0 0/5；present 4/5 vs C0 1/5。它和 Direct Qwen 的 exact 同为 3/5，但噪声更低：false 4 vs 9，unmatched 2 vs 6。

必须明说的两个限制：

- **BBCode 64 的 strict exact 是 0/1，present 也是 0。** Qwen 找到了 U1（line 67），但没找到 U2（line 88）；U_graph 的 bold/underline 候选 71、77 仍被因果确认成 minimal，输出里只有 U1 和 stray。两轮前（带相关函数、但不带“无法解释的行为变化”段落）它曾同时命中 67 和 88；最终合规 prompt 下出现回归，见第 9 节披露。
- **NetworkX 仍未修复。** 404 是正式并集的一部分，没有被删除。

---

## 1. 冻结边界与协议

| 项 | 本轮做法 |
|---|---|
| C0 / Graph-only / 旧 Full MACE | 只读复用，不重跑、不覆盖 |
| C0 universe | `runs/sd_v1_algorithm_pilot/<task>__c0.json`，原样作为 U_graph |
| Graph-only universe | `runs/sd_v1_algorithm_pilot/<task>__graph.json`，只作诊断字段 `u_graph_only` |
| HIDDEN reference | prompt 构造、搜索、验证阶段都不读；只在最后评分时读 |
| 模型调用 | 每题 1 次，4 题共 4 次；temp 0，seed 42，retries 0 |
| 上下文 | `num_ctx=16384`，`num_predict=4096`（NetworkX prompt 约 13.3k tokens，8192 放不下） |
| 搜索 | 现有 `search_relations_role_separated`，budget 16/输入，不修改 |
| 评分 | 现有 strict block-family equality + span containment；stray 判错；UNKNOWN 不计 FALSE |
| MMBS | `NOT_SEPARABLE`，只记录，不评分 |

`U_graph` 在本报告里指 **旧 Full MACE 实际消费的冻结 C0 候选池**，不是 Graph-only 的原始六候选。两者都逐题记录了：`u_graph` 与 `u_graph_only`。否则会把“旧方法本来就能看到 451”误判成“剪枝丢了 451”。

---

## 2. U_ast：可执行语句目录

构建方式（`build_catalog`，四题实测计数）：

| 题目 | executable | control_context | function_boundary | unsupported |
|---|---:|---:|---:|---:|
| BBCode 70 | 11 | 6 | 1 | 1 |
| BBCode 64 | 15 | 9 | 1 | 1 |
| Groff 73 | 15 | 6 | 1 | 1 |
| NetworkX 448 | 154 | 70 | 11 | 9 |

- `executable`：Assign / AnnAssign / AugAssign / Delete / Return / Raise / Assert / Expr(Call)，且不包含目标 A。
- `control_context`：If / While / For / AsyncFor / Try / With / AsyncWith / Match。它们**不是可删除操作**，只作为上下文；每个记录条件文本和其内部可执行语句 id。
- `function_boundary`：函数边界，不可删除。
- `unsupported`：无法安全当作单语句删除的节点，显式列为 unsupported。
- 每个 executable 记录 `file`、`first/last_line`、`kind`、`function`、`guards`、`defs`、`uses`、`calls`、`in_loop`、`contains_target`。

NetworkX 的 U_ast 有 154 条，不能全部塞进 prompt。prompt 里对 18 条重点操作给出完整元数据，其余只列精确 id；完整目录在 JSON 的 `u_ast` 字段。

---

## 3. Qwen 看到什么、输出什么

### 3.1 输入

每次调用的 user prompt 包含：

1. 任务 id、文件、目标 A 的行号与代码、删除规则（该行替换为同缩进 `pass`）；
2. 合法输入的不透明标签 `in1..inN`，不告诉模型角色或参数；
3. 目标函数源码（以 A 为中心，最多 42 行）；
4. 同文件相关函数的有界源码（最多 2 个、每个 16 行）。NetworkX 展示了 `alter_graph_mode_timeformat` 和 `add_spells`；三个 Pygments 题的可达目录里只有 `_make_styles` 一个函数，所以没有额外函数可展示；
5. U_base（冻结 C0 候选池）的 id、行号、kind、code；
6. U_ast 的可执行语句 id 与元数据；
7. 控制上下文、函数边界、unsupported 节点（都标注“不可删除”）；
8. 与 U_base 或 A 相关的 data/control dependency 边（最多 8 条）；
9. 每个输入的动态执行 trace、`plus`/`minus` 观察、`A-deletion=same/different`；
10. **无法解释的行为变化**：`executed_only_plus`、`executed_only_minus`、`u_graph_single_delete_changes`、`unexplained_by_u_base`。最后一个为 `true` 表示 A 删除造成的行为变化没有任何单个 U_base 删除能复现；
11. 输出 schema。

**没有提供**：HIDDEN 参考答案、真实 MSMS/MMBS、隐藏 witness、输入的真实角色或参数值。

### 3.2 输出字段

Qwen 被要求只返回一个 JSON 对象：

```json
{
  "candidates": [{
    "operation_id": "<exact U_ast executable id>",
    "source_span": "<file>:<first>-<last>",
    "relation_type": "cooperative_leg|alternative_path|shared_state|control_flow|exception_fallback",
    "related_operations": ["<id>"],
    "masking_condition": "<boolean expression or true>",
    "semantic_rationale": "<one sentence>",
    "supporting_execution_evidence": "<one sentence>"
  }],
  "candidate_sets": [{
    "kept_operations": ["<id>"],
    "relation_type": "...",
    "masking_condition": "...",
    "rationale": "..."
  }]
}
```

模型输出只是候选，不是最终关系。所有最终集合都必须经过真实执行。

### 3.3 映射规则

`map_token` 接受：

- 精确 U_ast id；
- 精确 U_graph/C0 id；
- `file:first-last` 且与某条 executable 完全一致；
- 唯一匹配某行的行号。

拒绝：

- 未知 id；
- 整段控制节点（If/For/Try…），并返回其内部可执行语句列表，要求模型改用这些 id；
- 函数边界；
- 无法唯一落地的跨度。

本轮 4 次调用全部 JSON 解析成功，映射失败 0 条。NetworkX 的 Qwen 输出是 `{451}`（`cooperative_leg`）和 `{456}`（`shared_state`），两者都已在 U_graph，所以并集没有变大。

### 3.4 U_union 与 provenance

`U_union = U_graph ∪ U_qwen`。每条候选都带：

- `sources`: `["graph"]`、`["qwen"]` 或两者；
- 是否零效应（单删是否改变任一公开探针观察）；
- `retained_reason`。

v2 **不做任何基于低模型分/低图分的剪枝**；U_graph 的每一条都保留。`rank_and_prune` 本身没有改动，它产出的 C0 universe 作为冻结输入。

---

## 4. 逐题结果

`U_graph` / `U_ast` / `U_qwen` / `U_union` 的括号内是：`隐藏块召回率 / 落在隐藏块外的候选数`。U_ast 是目录，不是候选集，所以它的“wrong”只表示目录里大多数语句与本题无关。

| 题目 | U_graph | U_ast | U_qwen（新增） | U_union | 正确候选召回 | exact | present | false | unmatched | probes | 模型墙钟 | prompt/completion tokens |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BBCode 70 | 1（0.5 / 0） | 11（1.0 / 9） | 2（+1） | 2 | **1.0** | **2/2** | 2/2 | 0 | 0 | 8 | 27.3 s | 4,416 / 460 |
| BBCode 64 | 2（0.0 / 2） | 15（1.0 / 9） | 2（+1） | 3 | 0.5 | 0/1 | 0/1 | 3 | 2 | 16 | 29.3 s | 4,981 / 520 |
| Groff 73 | 1（0.333 / 0） | 15（1.0 / 12） | 3（+2） | 3 | **1.0** | **1/1** | 1/1 | 0 | 0 | 16 | 36.3 s | 5,103 / 646 |
| NetworkX 448 | 3（1.0 / 2） | 154（1.0 / 153） | 2（+0） | 3 | 1.0 | 0/1 | 1/1 | 1 | 0 | 16 | 33.2 s | 13,302 / 499 |

合计：5 个 masking 输入；exact **3/5**，present **4/5**，false **4**，unmatched **2**，probe **56**，4 次模型调用，模型墙钟 **126.1 s**，prompt **27,802** tokens，completion **2,125** tokens。所有输入的 role-separated 搜索都是 `complete=true`，`SEARCH_INCOMPLETE=0`。

---

## 5. 四题细节

### 5.1 BBCode 70：双操作协同，2/2

- 隐藏：A=line 70；U1=line 72（`_sd_i = bool(ndef['italic']) and not ndef['color']`），U2=line 74-76（`if _sd_i ...` / `end = '[/i]' + end`）。
- U_graph 只有 line 76，召回 0.5。
- Qwen 提议 line 72、76，relation_type 是 `shared_state` / `control_flow`，并给出 `{72}`、`{76}`、`{72,76}` 三个集合。
- 因果验证：
  - `{76}` 单独不 masked；
  - `{72}` 单独不 masked；
  - `{72,76}` 在两个 masking 输入上 masked 且严格最小（任何非空真子集都不 masked）。
- 结果：两个输入都 exact，stray 0，false 0，unmatched 0。**这是 Full MACE 第一次解出该题。**

### 5.2 BBCode 64：只找到 U1，漏掉 U2

- 隐藏：U1=line 65-67（`if ndef['color'] ...` / `end = '[/color]' + end`），U2=line 77-88（重建整个 closing-tag 序列，含 line 88 `_sd_close += '[/color]'`）。
- U_graph 是 line 71（bold 分支）和 77（underline 分支），召回 0.0，两条都是错的。
- Qwen 提议 line 67（U1，novel）和 line 71（bold，已在 U_graph，错误的替代路径），给出 `{67}`、`{71}` 两个集合；**没有提 line 88**。
- 因果验证：
  - `{67}` 被确认 masked + minimal，投影到 U1；
  - `{71}`、`{77}` 也被确认 masked + minimal，但都是 stray；
  - 没有集合覆盖 U2。
- 结果：`hidden_msms_present=0`（只找到 U1，缺 U2），exact 0/1，false 3，unmatched 2。**这是最终合规 prompt 下的真实回归。** 上一轮（有相关函数、但没有“无法解释的行为变化”段）Qwen 曾同时提出 67 和 88；加上该段后输出变为 67 + 71。没有隐藏答案泄漏，也没有为了结果好看而回退 prompt。

### 5.3 Groff 73：三操作协同，1/1

- 隐藏：U1=line 75（`_sd_it = bool(ndef['italic']) and self.monospaced`），U2=line 78（`_sd_tag = regular if _sd_it else ''`），U3=line 80-82（`if _sd_it ...` / `end = _sd_tag + end`）。
- U_graph 只有 line 82，召回 0.333。
- Qwen 一次提出 75、78、82 三条，`related_operations` 互相指向，并给出 `{75,78,82}` 三操作集合，以及三个 singleton。
- 因果验证：
  - 三个 singleton 都不 masked；
  - `{75,78,82}` 在 masking 输入上 masked；
  - 所有非空真子集都不 masked（严格最小）。
- 结果：exact 1/1，stray 0，false 0，unmatched 0。**这是三操作协同第一次被任何 Full MACE 变体解出。**

### 5.4 NetworkX 448：剪枝不是根因，404 是 stray

- 隐藏：U1=line 450-451（`if not G.is_directed() and not edge_element.findall("slices"):` / `edge_data = self.add_slices(...)`）。
- C0 universe：`404, 451, 456`。C0 discovery 记录：`candidate_ops=6, kept=3, dropped_no_effect=3, dropped_duplicate_effect=0, truncated=0`。**451 在 kept 里，没有被剪掉。**
- Qwen 本轮提议 451 和 456，都在 U_graph 中，`qwen_novel_operations=[]`，并集仍是 3 条。
- 搜索在 in1 上返回 `{404,451}`；投影得到 U1，但 404 是 stray，因此 strict exact=0、false=1、present=1。
- 为什么 404 有害：它是 `edge_data = data.copy()`，单删签名 changed_cells=8，在 C0 排序里排第一，被保留。删掉 404 会改变该输入的观察，因此 `{451}` 在 C0 基底下不是 masked 集合，`{404,451}` 才是。
- 辅助诊断（**不是**主协议）：把 universe 换成 Graph-only 的六候选（451、454、455、456、380、393），不跑 Qwen，in1 上确认集合正好是 `{451}`，exact 1/1、stray 0。这说明 404 来自 AST 发现，而不是 graph 模块；也说明 rank_and_prune 没有丢 451。
- 但 Graph-only 基底不能作为正式修复：在三个 Pygments 题上，删除 454/455/380/393 这类图候选会改变执行语义，最小性验证全部失败/产生 stray。因此 v2 仍以 C0 为正式基底，NetworkX 的问题如实记为未解决。

---

## 6. A / B / C 三方对比（只这 5 个 masking 输入）

| 指标 | A：冻结 C0 | B：Direct Qwen 32B | C：v2 Candidate Expansion |
|---|---:|---:|---:|
| strict MSMS exact | 0/5 | **3/5** | **3/5** |
| 隐藏集合被包含（present） | 1/5 | 3/5 | **4/5** |
| 错误关系 | 7 | 9 | **4** |
| 未匹配集合 | 2 | 6 | **2** |
| 候选发现 | 上限即 C0 | 无候选池 | 3 题扩池成功 |
| 双操作协同 BBCode 70 | 0/2 | 2/2 | **2/2** |
| 多路径替代 BBCode 64 | 0/1 | 1/1 | 0/1（只找到 U1） |
| 三操作协同 Groff 73 | 0/1 | 0/1 | **1/1** |
| NetworkX 448 | 0/1 | 0/1 | 0/1（stray 404） |
| prompt tokens | — | 10,544 | 27,802 |
| completion tokens | — | 2,570 | **2,125** |
| 模型墙钟 | — | 140.6 s | **126.1 s** |

读法：

- **相对 C0**：v2 在 exact（3 vs 0）、present（4 vs 1）和正确候选召回上都赢了，且没有牺牲噪声（false 4 vs 7）。
- **相对 Direct**：exact 打平，present 更高（4/5 vs 3/5），false 和 unmatched 更低；代价是 prompt 更长（多给了 U_ast、U_graph、trace、依赖、无法解释的变化），但 completion 更少。
- **v2 仍然输 Direct 的题**：BBCode 64（0 vs 1），因为 Qwen 漏了 U2。
- **v2 赢 Direct 的题**：Groff 73（1 vs 0），三操作协同只有 v2 解出。

---

## 7. rank_and_prune 检查结论

检查对象：`benchmark_v3_baselines/ast_discovery.py::rank_and_prune`。

规则是：

1. 对每个候选计算单删行为签名；
2. `changed == 0` 的候选丢弃；
3. 相同签名的候选按 (`span`, `first_line`) 去重；
4. 按 `(-changed, span, first_line)` 排序，截断到 `max_ops`。

NetworkX 448 的实际记录：

| 项 | 值 |
|---|---:|
| candidate_ops | 6 |
| kept | 3（404、451、456） |
| dropped_no_effect | 3 |
| dropped_duplicate_effect | 0 |
| truncated | 0 |
| 正确操作 451 是否保留 | **是** |
| 404 单删 changed_cells | 8 |

因此：

- “rank_and_prune 把 451 剪掉”不成立；
- “NetworkX 的失败是剪枝”不成立；
- 正确的诊断是：**AST 发现把一个高效应但不在隐藏块里的 404 放进了候选池，它和 451 一起构成 C0 基底下真正的最小 masking 集合。**

本轮没有为了制造“修复”而改动 rank_and_prune，也没有删除 U_graph 中的 404。v2 只把这条候选的 `changed_cells`、是否零效应、保留原因记录下来，并把 Graph-only 诊断作为旁证。

---

## 8. 真实性证据

- 远端 GPU：`NVIDIA GeForce RTX 4090 D, 24564 MiB, 23261 MiB, 0 %`
- `ollama ps`：`qwen2.5-coder:32b`，23 GB，`100% GPU`，`CONTEXT=16384`，runner `llamacpp`
- `llama-server` 命令行：`-c 16384 -np 1 --flash-attn auto`
- 模型 digest：`b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41`
- 量化：Q4_K_M；参数 32.8B
- 未使用本机 RTX 5060；未用 CPU 冒充 GPU；没有伪造 GPU 层数

证据文件：`runs/candidate_discovery_v2/gpu_evidence.json`。

4 次调用都有完整 prompt、raw response、token 统计、墙钟和 attempt=0；没有重试。原始响应在 `runs/candidate_discovery_v2/raw/<task>.json`。

---

## 9. 偏差与限制

1. **只有 4 题、5 个 masking 输入。** 方向性证据，不是稳定排名；不能外推为自然缺陷检测率。
2. **BBCode 64 在最终 prompt 下回归。** Qwen 只找到 U1（67），漏了 U2（88），还提了错误的 71；strict exact 和 present 都是 0。候选发现部分成功，但不足以解出该题。
3. **NetworkX 未修复。** Qwen 没有带来新候选；404 仍在正式并集里。Graph-only 诊断的 exact 1/1 只是定位证据，不能当作方法结果。
4. **U_ast 的“wrong candidates”不是精度指标。** NetworkX 的 U_ast 有 154 条，153 条不在隐藏块内，这是目录的固有性质；真正的候选精度看 U_qwen。
5. **prompt 比 Direct 长。** v2 多了 U_ast 目录、U_graph 代码、依赖边、完整 trace 和无法解释的变化；NetworkX 的 prompt 约 13.3k tokens，因此本轮把 ctx 从 8192 提到 16384。这是方法输入差异，不是调参刷分。
6. **单次生成。** temp=0、seed=42、每臂 1 次；没有多次采样或置信区间。Qwen 对 prompt 措辞敏感，BBCode 64 的回归就是证据。
7. **MMBS 仍不可分。** 没有评分，也没有用 MMBS 反推 MSMS。
8. **本轮特殊披露：最终结果前共跑了三轮 prompt。**
   - 第一轮：目标函数源码、无“相关函数”段、无“无法解释的行为变化”段；结果 `results/MACE_candidate_discovery_v2_run1_no_related.json`，不参与评分。
   - 第二轮：加“相关函数”段，仍无“无法解释的行为变化”段；结果 `results/MACE_candidate_discovery_v2_run2_related_no_unexplained.json`。这一轮 BBCode 64 同时找到 67、88，present 5/5；但它不满足“Qwen 必须看到无法解释的行为变化”的要求。
   - 第三轮：加“无法解释的行为变化”段，是**唯一进入最终结果**的一轮。BBCode 64 因此回归到只找到 67。
   
   三轮的 exact 都是 3/5；差别在 present（5/5 → 4/5）和 BBCode 64 的候选召回。没有根据结果回退 prompt，也没有把第二轮冒充最终结果。

---

## 10. 产物与复现

主结果：

- `results/MACE_candidate_discovery_v2.json`（含每题完整 prompt、raw response、mapping、U_ast/U_graph/U_qwen/U_union、验证记录、评分、GPU 证据；sha256 `25cbf2ab548306a0a11bb7be79304332c3e5b6088d07ac139423f9c8ef08deeb`）
- `docs/MACE_candidate_discovery_v2_results.md`

内部运行：

- `runs/candidate_discovery_v2/results.json`
- `runs/candidate_discovery_v2/raw/<task>.json`
- `runs/candidate_discovery_v2/scores/<task>.json`
- `runs/candidate_discovery_v2/gpu_evidence.json`
- `runs/candidate_discovery_v2/networkx_graph_only_diagnostic.json`
- `runs/candidate_discovery_v2_run.log`

被弃用的前两轮（只作审计，不参与结果）：

- `results/MACE_candidate_discovery_v2_run1_no_related.json`
- `results/MACE_candidate_discovery_v2_run2_related_no_unexplained.json`

复现：

```bash
cd <local-path>
python -I scripts/run_candidate_discovery_v2.py --dry-run
python -I scripts/run_candidate_discovery_v2.py
```

本轮完成后停止，不做额外 prompt 迭代，不扩题，不跑旧目标。
