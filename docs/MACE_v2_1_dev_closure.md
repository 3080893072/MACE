# MACE Candidate Discovery v2.1 — DEV Final Closure

- 日期：2026-11-05
- 范围：仅 DEV。**未读取 HELDOUT reference、隐藏答案、隐藏子集枚举或评分反馈。**
- 冻结对象：Candidate Discovery v2 Prompt、Qwen 32B、AST/Graph 候选构造、Candidate Union、Causal Search、Verifier、搜索预算、评测协议。
- 最终判定：**READY_FOR_HELDOUT = YES**（依据见 §5）。

---

## 1. 两道 INCOMPLETE 的修复

### 1.1 根因

`SDExecutor._run_probe`、`a_executes` 以及 runner 的 `trace_run` 只把 `<variant>` 放进 `sys.path`。`sd_attrs_asdict_loop_m7` 和 `sd_humanize_filesize_gnu_m5` 是 src-layout 包，可导入包在 `<variant>/src/<pkg>`，探针因此导入**已安装的包**而不是变体包：P+ 与 P− 观测相同、`a_executes=False`、C0 与 v2.1 都没有可用的 MASKED 输入。

### 1.2 修复方式（只修评测路径）

- 在 `benchmark_v4_dataset/tools/sd_algorithm_pilot.py` 的 `_run_probe`、`a_executes` 中，以及 `scripts/run_candidate_discovery_v2_1.py` 的 `trace_run` 中，同时插入 `<variant>` 和 `<variant>/src`。
- 未改动 Candidate Discovery Prompt、搜索器、Verifier、数据集、标准答案、搜索预算。
- 对另外 19 道非 src-layout 题，`<variant>/src` 不存在，新增的 `sys.path` 条目不产生导入遮蔽，成绩不受影响。
- 该修复已落在**冻结代码**中（不是只存在于一次性脚本），HELDOUT 会走同一条修正路径。

### 1.3 模型调用与缓存复用

- 新增 Qwen 调用：**0**。
- 两道题均复用 `runs/candidate_discovery_v2_1/raw/<cid>.json` 中已缓存的原始响应与 token 统计，用 `CachedQwen` 回放。
- 缓存包含完整模型输入（messages）、输出（raw_response）、`prompt_sha256` 和 stats，证据充分，因此可以评分，不再标记 INCOMPLETE。
- **必须披露的偏差**：`prompt_matches_cached = False`（两题皆是）。缓存响应是在缺陷 harness 下生成的（当时 U_graph 为空）；修复后 U_graph 非空，重建 Prompt 与缓存 Prompt 不同。我们**没有**重发请求、没有改 Prompt，模型输出按原样回放。因此这两题的分数应理解为“缓存输出 + 修正后的候选并集/验证路径”，而不是“修正 Prompt 下的新模型输出”。

### 1.4 修复后结果

| task | inputs | Full exact | C0 exact | false | status |
|---|---|---|---|---|---|
| sd_attrs_asdict_loop_m7 | 1 | 1 | 1 | 0 | OK |
| sd_humanize_filesize_gnu_m5 | 1 | 1 | 1 | 0 | OK |

两道题均与 C0 持平，未改变 C0/Full 的优劣方向。

---

## 2. 总体成绩核对

### 2.1 统计口径

| 项目 | 数值 | 说明 |
|---|---|---|
| DEV 题目总数 | **25** | 10 道正式（split=None）+ 15 道 split=DEV |
| 本轮 v2.1 主集题目数 | **21** | 25 − 4 道已在 v2 测过 |
| 实际完整评测题目数 | **21 / 21** | 修复后无 INCOMPLETE |
| MASKED 输入总数 | **27** | 仅统计 v2.1 主集 |
| MSMS Exact Match 分母 | **27** | 每个输入等权，不是每题等权 |
| 先前 4 道 DEV 是否计入本聚合 | **否** | 单列为描述性 all-25 视图，不与主集混算 |
| C0 与 Full 是否同一 v2.1 reference | **是** | 同一题、同一输入共用同一份由 acceptance 导出的 roles/MSMS；已对 10 道正式题与 `reference.json` 校验，0 处不一致 |
| INCOMPLETE 是否从准确率分母排除 | **是** | 本轮已无 INCOMPLETE；若有则保留在 CSV、不计入分母 |
| 搜索未完成输入 | 3 | `sd_pygments_latex297_italic` 3/3 输入触发 16/64 子集预算上限，按协议不扩预算；0/2 是预算受限的阴性，不是“不存在掩盖集”的证明 |
| MMBS | 不参与评分 | 仍为 NOT_SEPARABLE |

### 2.2 结果集 1：全部 DEV 完成状态与严格评分（v2.1 主集）

- 题目：21/21 完成，0 INCOMPLETE。
- 输入：27。
- C0：**14/27** exact，false relations **9**。
- Full MACE + CD v2：**19/27** exact，false relations **5**，unmatched sets **2**。
- 任务级：better **6**、equal **14**、worse **1**。
- 成本：probes **276**，wall **747.53 s**，prompt tokens **145,939**，completion tokens **11,288**（合计 157,227）。

### 2.3 结果集 2：仅在完整可评配对样本上比较 C0 vs Full

本轮 21 题、27 个输入全部可评，因此配对样本就是全部 27 个；两套结果数值相同，但口径不同（结果集 1 回答“完成度与严格评分”，结果集 2 只回答“同一样本上谁更好”）：

| method | exact | false | 说明 |
|---|---|---|---|
| A = Role-separated C0 | 14/27 | 9 | 只用 C0 候选宇宙 |
| B = Full MACE + CD v2 | **19/27** | **5** | U_graph ∪ U_qwen，同一搜索/验证器 |
| 差值 | **+5** | **−4** | 6 题更好、14 题持平、1 题更差 |

Qwen 候选扩展：novel candidates 20，其中命中目标因果族 8、错误 12；12 题发生扩展，6 题至少有一个正确扩展。

### 2.4 all-25 描述性视图（不与主集混算）

4 道 v2 冻结题（`sd_pygments_bbcode70_italic`、`sd_pygments_bbcode64_color`、`sd_pygments_groff73_italic`、`sd_networkx_gexf448_slices`）**未在本轮重跑**，只做描述性合并：

| 集合 | tasks | inputs | C0 exact | Full exact | false | unmatched | probes | runtime s |
|---|---|---|---|---|---|---|---|---|
| v2.1 主集 | 21 | 27 | 14 | 19 | 5 | 2 | 276 | 747.53 |
| v2 冻结 4 题 | 4 | 5 | 0 | 3 | 4 | 2 | 56 | 154.25 |
| all-25（描述性） | 25 | 32 | 14 | 22 | 9 | 4 | 332 | 901.78 |

**方法结论只使用主集 21 题 / 27 输入。** all-25 不得用于声称“25 题上的正式成绩”。

### 2.5 逐题明细

| task | mech | exact/inputs | false | probes | tokens p/c | s | status | vs C0 |
|---|---|---|---|---|---|---|---|---|
| sd_attrs_asdict_loop_m7 | M7 | 1/1 | 0 | 18 | 5504/448 | 4.26 | OK | equal |
| sd_coverage_glob_backslash_m2 | M2 | 1/1 | 0 | 8 | 5874/448 | 31.35 | OK | better |
| sd_docutils_backticks_m1 | M1 | 1/1 | 0 | 8 | 3481/537 | 33.22 | OK | equal |
| sd_docutils_educate_dashes_m2 | M2 | 1/1 | 0 | 16 | 3556/890 | 51.45 | OK | better |
| sd_docutils_ellipsis_m3 | M3 | 1/1 | 0 | 16 | 3664/766 | 45.54 | OK | better |
| sd_docutils_language_tag_m3 | M3 | 1/1 | 0 | 32 | 5261/951 | 56.84 | OK | better |
| sd_docutils_make_id_lower | M1 | 0/2 | 0 | 16 | 13743/494 | 36.0 | OK | equal |
| sd_docutils_make_id_nonid_m2 | M2 | 1/1 | 0 | 8 | 13919/462 | 36.38 | OK | equal |
| sd_docutils_smartquotes_strip_m1 | M1 | 0/1 | 1 | 8 | 7694/518 | 34.59 | OK | worse |
| sd_docutils_stupefy_emdash_m2 | M2 | 1/1 | 0 | 8 | 4233/826 | 49.2 | OK | better |
| sd_docutils_stupefy_endash_m1 | M1 | 1/1 | 0 | 4 | 4046/285 | 19.46 | OK | equal |
| sd_humanize_filesize_gnu_m5 | M5 | 1/1 | 0 | 10 | 3496/266 | 3.13 | OK | equal |
| sd_isort_format_strip_m4 | M4 | 1/1 | 0 | 8 | 3154/478 | 31.21 | OK | better |
| sd_jsonschema_1145_pointer | M1 | 2/2 | 0 | 4 | 10897/270 | 25.14 | OK | equal |
| sd_networkx_adjlist_strip_m1 | M1 | 2/2 | 0 | 4 | 4758/271 | 25.05 | OK | equal |
| sd_pygments_latex297_italic | M6 | 0/2 | 4 | 64 | 7914/1002 | 74.41 | OK | equal |
| sd_pygments_style95_cache | M9 | 0/3 | 0 | 16 | 7446/810 | 52.73 | OK | equal |
| sd_tabulate_1052_strip_right | M1 | 1/1 | 0 | 8 | 8194/224 | 24.25 | OK | equal |
| sd_tabulate_1056_strip_center | M5 | 1/1 | 0 | 4 | 8194/593 | 41.96 | OK | equal |
| sd_tabulate_2557_curlen | M7 | 1/1 | 0 | 8 | 16132/290 | 36.64 | OK | equal |
| sd_toml_strict_num_strip_m1 | M1 | 1/1 | 0 | 8 | 4779/459 | 34.72 | OK | equal |

按机制汇总：

| mech | tasks | inputs | Full exact | C0 exact | false |
|---|---|---|---|---|---|
| M1 | 8 | 11 | 8 | 9 | 1 |
| M2 | 4 | 4 | 4 | 1 | 0 |
| M3 | 2 | 2 | 2 | 0 | 0 |
| M4 | 1 | 1 | 1 | 0 | 0 |
| M5 | 2 | 2 | 2 | 2 | 0 |
| M6 | 1 | 2 | 0 | 0 | 4 |
| M7 | 2 | 2 | 2 | 2 | 0 |
| M9 | 1 | 3 | 0 | 0 | 0 |

增益集中在 M2/M3/M4（协同/替代路径），代价是 M6 的 4 条 false relations；M9 与 M1 的失败样本没有改善。

---

## 3. 错误案例诊断（不修改答案）

**策略：不编辑 reference、不删除失败样本、不调整评分器。** 以下两例在现行严格评分下继续计为失败。

### 3.1 `sd_docutils_smartquotes_strip_m1`：stray = `docutils/frontend.py:277-277`

- 输入 in1（`mask_space_padding`）：隐藏 MSMS block 为 `U1`；Qwen 组合保留 `[275,277]`，验证为 masked + minimal（候选级），但隐藏族仅由 275 覆盖，**277 是多余的 kept 操作**，因此严格最小性失败、false relations = 1。
- 输入 in3：`[277]` 单独即 masked + minimal；`[275,277]` 被判 NOT_MINIMAL，witness 为 277。也就是说 277 在 in3 上是真正的目标操作。
- 是否为保持 probe 可执行而引入：**否**。所有候选集合都能正常执行并产生观测/比较；277 是 Qwen 在 in1 上的过度保留，不是执行脚手架。
- 对严格最小性/可执行性的影响：严格最小性在 in1 失败；可执行性不受影响。答案、reference、评分器均未改动。

### 3.2 `sd_networkx_gexf448_slices`：stray = `networkx/readwrite/gexf.py:404-404`

- 来源：v2 冻结运行（本轮未重跑）。
- 输入 in1（`mask_undirected_slices`）：隐藏 MSMS block 为 `U1`；保留 `[404,451]` 被判 masked + minimal，但 404 仍计为 stray，严格最小性失败、false relations = 1。
- 证据：只保留 `[451]`（禁用 404、456）时结果为 NOT_MASKED；C0 cell diagnostic 显示 404 的 changed_cells = 8/8（非零效应）。而 451 单独覆盖 U1 族。
- 是否为保持 probe 可执行而引入：**否**。`[451]` 集合本身可执行（且给出 NOT_MASKED），404 不是执行前提；它是让该输入上掩盖现象可观测所需的前置赋值，但不属于隐藏目标 block 族。
- 对严格最小性/可执行性的影响：按 block-family 规则严格最小性失败（操作上必要、族上 stray）；可执行性不受影响。答案、reference、评分器均未改动。

---

## 4. Full MACE 冻结记录

### 4.1 代码与配置

| 项目 | 值 |
|---|---|
| git HEAD | `2f1ee017b8edbc966283abbb240559fe7e09d55d` |
| 冻结配置 | `results/MACE_v2_1_frozen_config.json` |
| 最终结果 | `results/MACE_v2_1_dev_final.json` |
| 逐题结果 | `results/MACE_v2_1_dev_per_task.csv` |
| 最终结果 SHA-256 | `5094ea44a16907665aab284dcf842ed67103ce1cb29ab686ab5f9e101ee3deb5` |
| 逐题 CSV SHA-256 | `fd4204834d277fe3e13475ae61b5633ca6ccdb7d98d478a68333d7a9679de7de` |
| 冻结配置 SHA-256 | `8de843b2c32f9ab7b7b03e1da0c2f6cf31bfdf5ea70b357c323f4ef38879edec` |

关键文件 SHA-256（完整表在 frozen_config）：

| file | SHA-256 |
|---|---|
| scripts/run_candidate_discovery_v2_1.py | `3e73ac4989709562e838f63dc349838e8f8a8e916a2023dbbd31011ae0adddd8` |
| benchmark_v4_dataset/tools/sd_algorithm_pilot.py | `fcc9501a9276adcd2857b5ef2ee3fc5faf57fd039c73d720f9d8183bc3b3699d` |
| benchmark_v3_baselines/graph_search.py | `6bae819c0676a717b30e079fa70a173a3784f8ad7d6ab3001a86dd7873dad6fa` |
| benchmark_v3_baselines/ast_discovery.py | `681ee3a693e6b127da7cd6e6c8c7fbb448971e6742409503cac5f2ea4793443e` |
| benchmark_v3_baselines/subgraph.py | `9257c9eb1d6a27fbb0611ed51c0cad90e41634fe938e7a356ddf0422c6849771` |
| mace/qwen.py | `763315c39883b807b4317b0834d07bf76e5d819d358f0c969feeaa53e2f57c39` |

### 4.2 算法与模型

- Candidate Discovery Prompt：v2 冻结版，**v2.1 未改动**；`build_prompt` 源码 SHA-256 记录在 frozen_config。
- Qwen：Ollama `qwen2.5-coder:32b`，Q4_K_M，digest `b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41`。
- 解码：temperature 0、seed 42、retries 0、`num_ctx=16384`、`num_predict=4096`、timeout 900 s；每题至多 1 次调用。
- 候选：U_graph（C0 discover → rank_and_prune，max_ops=6）∪ U_qwen，保留 provenance。
- 搜索：role-separated，每输入预算 16；Verifier 与 MSMS 严格 block-family 判定不变；UNKNOWN ≠ FALSE；MMBS 不计分。
- 评测协议：仅完整可评 MASKED 输入进入分母；INCOMPLETE 保留在 CSV 但不计分。

---

## 5. HELDOUT 准备检查

本轮只读取了：

- `benchmark_v4_dataset/split/seal.json`（封条本身）
- `benchmark_v4_dataset/PROTOCOL.md`（公开规范）

未读取：HELDOUT reference、隐藏标准答案、隐藏子集枚举结果、任何用于调参的 HELDOUT 评分反馈。

检查结论：

| 项目 | 结果 |
|---|---|
| 封条状态 | `unsealed = null`，仍处于未开封状态 |
| 封条版本 | `v4.0-dev-2026-11-04`，sealed_at `2026-11-04T00:27:21Z` |
| 封内项目数（公开于封条） | 8 |
| seal 内容 SHA-256 | `106069cd615aef1b5e40e7888371d36d714a30d99151f083cee4d6ab1aaa7382` |
| seal 文件 SHA-256 | `070b8d535cd7bca2581a0cf41889958b67b5709d162b6f58ba48fa235a28182c` |
| v2.1 DEV 数据可用 | 是（21 题 / 27 输入全部完成） |
| 独立评分环境保持 | 是（未改 HIDDEN scorer、reference、数据集；DEV 评测与评分器分离） |
| 评测路径缺陷 | 已修复并进入冻结代码，HELDOUT 不会复现 src-layout 导入错误 |

HELDOUT 运行前置条件：使用 `results/MACE_v2_1_frozen_config.json` 记录的代码哈希、模型 digest、Prompt、预算与协议；一旦任一代码文件哈希变化，必须重新冻结，不能沿用本报告的分数。

---

## 6. 交付物

- `docs/MACE_v2_1_dev_closure.md`（本文件）
- `results/MACE_v2_1_dev_final.json` — 两套结果口径、逐题明细、诊断、冻结与 HELDOUT 检查
- `results/MACE_v2_1_dev_per_task.csv` — 21 题逐题 exact/false/probes/tokens/runtime/status
- `results/MACE_v2_1_frozen_config.json` — commit、文件 SHA-256、模型 digest、预算、协议、最终结果哈希

**READY_FOR_HELDOUT = YES**
