# MACE-Bench v2.1 — Direct GLM 基线评测报告

- 日期：2026-11-05
- 范围：**仅 Direct GLM**。不运行 MACE + GLM，不使用 Graph/AST 候选扩展、因果搜索器或 Verifier。
- DEV：25 题 / 30 个 MASKED 输入，已严格评分。
- HELDOUT：25 题全部完成预测，**未读取 reference、隐藏答案、枚举结果或干预证据，未评分**。
- 数据集、标准答案、MACE 算法、既有 Qwen 结果：**本轮均未修改**。

---

## 0. 结论速览

| 项目 | 结果 |
|---|---|
| Direct GLM DEV 严格 MSMS Exact | **9 / 30 = 30.0%** |
| MSMS Precision / Recall（输入级平均） | **0.4933 / 0.6400** |
| False Relations / Unmatched Sets | **53 / 12** |
| 协作机制（M2+M3）Exact | **5 / 9** |
| 替代路径（M4）Exact | **2 / 2** |
| 同协议配对子集（10 题 / 15 输入） | Direct GLM **4/15** vs Direct Qwen **3/15** |
| 配对子集 False Relations | GLM **8** vs Qwen **60** |
| 配对子集总耗时 | GLM **172.5 s** vs Qwen **596.5 s** |
| 全部 25 题输出 | 25/25 合法 JSON，0 次超时，0 次 completion 截断 |
| HELDOUT | 25/25 预测已冻结，SHA-256 `b1815476…2597f`，未评分 |

一句话：纯 GLM 在 v2.1 DEV 上严格命中 **9/30**，显著低于 Full MACE 的 19/27，但在同题同协议下**不弱于** Direct Qwen（4/15 vs 3/15），且假关系少一个数量级、速度快 3.5 倍。主要失败来自**未给出任何关系**（10 例）与**空关系噪声**（7 例），而不是给出错误关系。

---

## 1. 模型部署

### 1.1 环境

| 项目 | 值 |
|---|---|
| 平台 | AutoDL，远程 Linux |
| GPU | NVIDIA GeForce RTX 4090 D，24564 MiB |
| 推理服务 | Ollama，`127.0.0.1:11434`，经 SSH 本地端口转发接入 |
| 模型放置 | `ollama ps` 显示 **100% GPU**，上下文 8192 |
| 峰值显存（实测） | **18909 MiB**（占 24564 MiB 的 77%） |
| 付费 API | **未使用** |

### 1.2 模型身份（可复现）

| 项目 | 值 |
|---|---|
| 标签 | `glm-4.7-flash:q4_K_M` |
| Ollama 模型 ID | `4475827791a2` |
| manifest SHA-256 | `e1e233835e36cd0ebaa63cd554eb14c4b2abd50480e11972f348fbe500195d7f` |
| 权重 blob SHA-256 | `9eba2761cf0b88b8bc11a065a7b5b47f1b13ce820e8e492cb1010b450f9ec950` |
| 权重大小 | 19,019,269,280 B（≈19 GB） |
| 架构 / 参数量 | `glm4moelite` / 29.9B |
| 量化 | Q4_K_M |
| 原生上下文 | 202752 |
| thinking | 模型默认 `true`，**本实验显式关闭**（`think: false`） |

### 1.3 部署与评测计时（分开记录）

| 阶段 | 时间 / 时长 |
|---|---|
| Ollama 服务启动 | 2026-11-05 15:14:59 (+08:00) |
| 模型下载完成、manifest 注册 | 2026-11-05 15:47:52 (+08:00) |
| **部署耗时** | **1973 s ≈ 32.9 min**（约 19 GB，平均 ~10 MB/s；中途掉速后重启续传，未切换模型版本） |
| **DEV 评测** | **347.3 s**（25 题，含 3 道冒烟题） |
| **HELDOUT 预测** | **325.1 s**（25 题） |
| 评测总耗时 | **672.4 s ≈ 11.2 min** |
| 硬截止 | 2700 s → **满足** |

### 1.4 关于 Qwen 32B

实例在部署前重启过，`~/.ollama` 模型库为空（12 KB），**Qwen 32B 在本轮开始前已不存在**。本实验**没有删除**任何 Qwen 模型，也没有重新下载 Qwen 32B；因此不存在两个大模型同时占用显存的窗口。Direct Qwen 的既有结果来自此前已冻结的运行，本轮直接引用，未重跑、未修改。

### 1.5 上下文与截断（必须披露的限制）

按冻结协议沿用 Direct Qwen 的 `num_ctx=8192`、`num_predict=4096`。实测 Ollama 为输出预留 4096 token，**可用 prompt 上限实为 ~4096 token**（所有超长 prompt 的 `prompt_eval_count` 均恰为 4098）。

- 判定依据：正常 prompt 的字符/token 比约 3.1–3.8；被截断的均为 9–28，界限清晰。
- **DEV：15/25 题、16/30 个 MASKED 输入受影响**（37K–113K 字符源码被截到 ~4096 token）。
- **HELDOUT：10/25 题受影响。**
- 这是与 Direct Qwen **完全相同的协议限制**，不是 GLM 特有的；但它确实压低了 GLM 的绝对分数，尤其是 tabulate / docutils / toml 这类长源码题。
- 未静默截断：所有受影响题目在 `per_task.csv` 的 `context_truncated` 列、`config.json` 的 `context_truncation` 块、以及 Table D 的备注中逐题列出。

---

## 2. 评测协议（与 Direct Qwen 完全一致）

- 每题 **1 次调用**，失败**不重试**；temperature 0、seed 42、timeout 900 s。
- 输入：仅 public view（cases + patched 证据源码，去掉内部 marker 行），同一 `direct_prompt` 模板、同一 system message、同一输出 JSON schema 与 parser。
- 输出：`{"relations":[{"operations":[{"file","line","text"}],"condition","rationale"}]}`，至多 12 组关系。
- 映射：同一 `SourceIndex` + `map_proposal(style="v3", exclude_lines=[A_line])`。
- 评分：同一 `family` / `project_containment` 严格 block-family 判等；stray op 计入 false；**UNKNOWN ≠ FALSE**。
- 候选宇宙、搜索、Verifier：**均未使用**——模型必须直接说出关系。
- MMBS：Direct 协议不请求，记为 **N/A**（不计为错误、不计为空）。
- 冒烟测试的 3 题（`sd_tabulate_1052_strip_right`、`sd_coverage_glob_backslash_m2`、`sd_humanize_filesize_gnu_m5`）**直接计入正式 DEV**，未重复调用。

---

## 3. DEV 正式结果

### 3.1 总体

| 指标 | 值 |
|---|---|
| 题目 | 25 / 25 完成 |
| MASKED 输入（分母） | **30** |
| 严格 MSMS Exact | **9（30.0%）** |
| Precision（输入级平均） | 0.4933 |
| Recall（输入级平均） | 0.6400 |
| False Relations | 53 |
| Unmatched Sets | 12 |
| 合法 JSON / 解析错误 | 25 / 0 |
| 超时 / completion 截断 | 0 / 0 |
| 非截断输入 Exact | 6/14（42.9%） |
| 被截断输入 Exact | 3/16（18.8%） |

**口径说明**：分母 30 来自 v2.1 reference 中 role=masking 的输入数。此前 21 题主集报告的 27 是另一口径，本轮不沿用、不混算。

### 3.2 逐题

| task | mech | inputs | exact | false | unmatched | pt | ct | 秒 | 截断 |
|---|---|---|---|---|---|---|---|---|---|
| sd_attrs_asdict_loop_m7 | M7 | 1 | **1** | 0 | 0 | 5854 | 178 | 5.6 | – |
| sd_coverage_glob_backslash_m2 | M2 | 1 | 0 | 14 | 3 | 7121 | 635 | 15.7 | – |
| sd_docutils_backticks_m1 | M1 | 1 | **1** | 0 | 0 | 4098 | 326 | 8.7 | ✔ |
| sd_docutils_educate_dashes_m2 | M2 | 1 | 0 | 2 | 0 | 4098 | 315 | 7.8 | ✔ |
| sd_docutils_ellipsis_m3 | M3 | 1 | 0 | 2 | 1 | 4098 | 258 | 6.6 | ✔ |
| sd_docutils_language_tag_m3 | M3 | 1 | **1** | 0 | 0 | 4098 | 310 | 8.1 | ✔ |
| sd_docutils_make_id_lower | M1 | 1 | 0 | 3 | 1 | 4098 | 236 | 6.1 | ✔ |
| sd_docutils_make_id_nonid_m2 | M2 | 1 | 0 | 0 | 0 | 4098 | 368 | 9.6 | ✔ |
| sd_docutils_smartquotes_strip_m1 | M1 | 1 | 0 | 0 | 0 | 4098 | 906 | 19.2 | ✔ |
| sd_docutils_stupefy_emdash_m2 | M2 | 1 | **1** | 0 | 0 | 4098 | 458 | 10.4 | ✔ |
| sd_docutils_stupefy_endash_m1 | M1 | 1 | 0 | 2 | 1 | 4098 | 463 | 10.6 | ✔ |
| sd_humanize_filesize_gnu_m5 | M5 | 1 | 0 | 15 | 0 | 1465 | 1403 | 29.2 | – |
| sd_isort_format_strip_m4 | M4 | 1 | **1** | 0 | 0 | 2368 | 274 | 6.5 | – |
| sd_jsonschema_1145_pointer | M1 | 2 | 0 | 4 | 2 | 4098 | 163 | 4.7 | ✔ |
| sd_networkx_adjlist_strip_m1 | M1 | 1 | 0 | 7 | 2 | 3689 | 333 | 7.4 | – |
| sd_networkx_gexf448_slices | M8 | 1 | 0 | 2 | 1 | 4098 | 256 | 6.7 | ✔ |
| sd_pygments_bbcode64_color | M4 | 1 | **1** | 0 | 0 | 1806 | 544 | 11.3 | – |
| sd_pygments_bbcode70_italic | M2 | 2 | **2** | 0 | 0 | 1724 | 567 | 12.1 | – |
| sd_pygments_groff73_italic | M3 | 1 | **1** | 0 | 0 | 2355 | 295 | 7.0 | – |
| sd_pygments_latex297_italic | M6 | 2 | 0 | 0 | 0 | 7580 | 1466 | 34.3 | – |
| sd_pygments_style95_cache | M9 | 3 | 0 | 0 | 0 | 2938 | 458 | 10.9 | – |
| sd_tabulate_1052_strip_right | M1 | 1 | 0 | 0 | 0 | 4098 | 290 | 7.4 | ✔ |
| sd_tabulate_1056_strip_center | M5 | 1 | 0 | 0 | 0 | 4098 | 3255 | 69.5 | ✔ |
| sd_tabulate_2557_curlen | M7 | 1 | 0 | 2 | 1 | 4098 | 322 | 8.6 | ✔ |
| sd_toml_strict_num_strip_m1 | M1 | 1 | 0 | 0 | 0 | 4098 | 1144 | 23.5 | ✔ |

### 3.3 按机制（Table B）

| mech | 说明 | tasks | inputs | GLM exact | false |
|---|---|---|---|---|---|
| M1 | 单操作 | 8 | 9 | **1/9** | 16 |
| M2 | 两操作协作 | 5 | 6 | **3/6** | 16 |
| M3 | 三操作协作 | 3 | 3 | **2/3** | 2 |
| M4 | 替代路径 | 2 | 2 | **2/2** | 0 |
| M5 | 条件分支 | 2 | 2 | **0/2** | 15 |
| M6 | 跨函数状态 | 1 | 2 | **0/2** | 0 |
| M7 | 循环状态 | 2 | 2 | **1/2** | 2 |
| M8 | 对象共享状态 | 1 | 1 | **0/1** | 2 |
| M9 | 异常回退 | 1 | 3 | **0/3** | 0 |

- **最好**：M4 替代路径 2/2；M3 三操作协作 2/3；M2 3/6。
- **最差**：M1 单操作 1/9；M5 条件分支 0/2（且 15 条假关系全部来自 humanize 一题）；M6/M8/M9 全 0。
- 一个反直觉现象：**协作机制（M2+M3）反而比单操作（M1）好**（5/9 vs 1/9）。原因是 M1 的多模板源码题大量被 prompt 截断且模型倾向于"不表态"，而 M2/M3 的若干题源码较短（pygments）能完整看到。

---

## 4. 与 Direct Qwen 的同协议对比（Table A）

**只有在相同题目、相同输入键上才能比较。** 此前 Direct Qwen 运行覆盖 10 道正式题 / 15 个 MASKED 输入，全部包含在本次 25 题中，因此做配对比较：

| 指标（10 题 / 15 输入） | Direct Qwen 32B | Direct GLM 4.7 Flash |
|---|---|---|
| 严格 MSMS Exact | **3/15（20.0%）** | **4/15（26.7%）** |
| False Relations | 60 | **8** |
| Unmatched Sets | 42 | **4** |
| Prompt tokens | 34,340 | 36,893 |
| Completion tokens | 11,102 | **7,616** |
| Wall time | 596.5 s | **172.5 s** |

逐题差异只有一处：`sd_pygments_groff73_italic`（Qwen 0/1，GLM 1/1）；其余 9 题逐输入完全同分。

**解释与边界**：

- GLM 在配对子集上**多命中 1 个输入、假关系少 52 条、快 3.5 倍**；但样本只有 15 个输入，差异（+1 题）**不具统计显著性**，不能写成"GLM 优于 Qwen"。
- 两者**不是同规模/同结构对照**：GLM-4.7-Flash 是 29.9B MoE（激活参数更少），Qwen2.5-Coder-32B 是 32B dense；训练数据、代码语料配比、推理栈均不同。论文中应表述为"两个不同规模与结构的开源模型在同一纯模型协议下的对照"。
- 两者共用同一 4096-token 有效 prompt 上限，因此截断偏差方向一致。
- 完整 25 题 / 30 输入口径下，**没有**可配对的 Direct Qwen 数字，Table A 中该格只能写本轮 GLM 成绩。

---

## 5. 失败分析（Table D）

### 5.1 失败类型分布（21 个未命中的输入）

| 类型 | 数量 | 含义 |
|---|---|---|
| CANDIDATE_OMISSION | **10** | 未给出任何可映射关系（空 `relations` 或全部被映射器拒绝） |
| EMPTY_SET_NOISE | **7** | 命中了正确的 block 族，但同时多给了一个空集合 `[]` → 严格判等失败 |
| WRONG_RELATION | 2 | 给出了关系，但 block 族完全不同（含只给空集合） |
| WRONG_COOPERATION | 1 | 把两操作协作拆成 `{U1}`、`{U2}`、`{U1,U2}` 三个候选 |
| STRAY_OPERATION | 1 | block 族正确但夹带 stray op（humanize，15 条假关系） |
| FORMAT_ERROR / TIMEOUT | **0 / 0** | 全部 25 题输出均为合法 JSON |

### 5.2 关键观察

1. **主要问题是"不敢说"，不是"说错"**：10/21 失败是完全空输出；另有 7 例是"答对 + 多一个空集合"。
2. **空集合是系统性格式偏差**：模型常额外输出一个 `operations: []` 的关系，映射后成为 unmatched set，直接破坏严格相等。这不是数据集问题，也不是评分器问题。
3. **humanize（M5）一题贡献 15 条假关系**（占全部 53 条的 28%）：模型围绕 `U1` 给出了大量额外 kept 操作。
4. **长源码题集中失败**：tabulate ×3、toml、smartquotes、make_id_nonid 均在被截断的 prompt 上给出空答案。

---

## 6. 效率（Table C）

| 指标（DEV 25 题） | 值 |
|---|---|
| 总耗时 | 347.3 s |
| 平均 / P50 / P95 | 13.9 / 8.7 / 33.3 s |
| Prompt tokens | 98,370 |
| Completion tokens | 15,223 |
| 生成速度 | 51.5 tok/s |
| 峰值显存 | 18,909 MiB / 24,564 MiB |
| 模型调用次数 | 25（1 次/题，0 重试） |

最慢：`sd_tabulate_1056_strip_center` 69.5 s（输出 3255 token）；最快：`sd_jsonschema_1145_pointer` 4.7 s。

配对 10 题的 Qwen/GLM 效率对比见 §4。

---

## 7. HELDOUT 盲测状态（Table E）

- **25/25 题预测完成**，文件：`results/MACE_direct_GLM_v2_1_heldout_predictions.json`
- SHA-256：`b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f`
- 全部为合法 JSON，`parse_error = 0`，`done_reason = stop`（无 completion 截断）。
- 11 题给出了至少 1 个可映射关系；14 题给出 0 个可映射关系（这与 DEV 的"空输出"模式一致，不是格式错误）。
- 共 24 组关系、69 条被映射器拒绝的 proposal。
- 10 题 prompt 被 4096 上限截断。
- **未读取** HELDOUT reference / 隐藏答案 / enumeration / acceptance，**未评分**。
- 固定子集（来自 v2.1 封条 flags，非隐藏统计）：full 25、project-disjoint 19、template-disjoint 16、both-disjoint 14，预测均已覆盖。

**解锁条件**：Direct Qwen、C0、Full MACE、Direct GLM 四方的 HELDOUT 预测全部冻结后，用独立 scorer 一次性开封评分。本轮不满足该条件（其余方法尚未产出 HELDOUT 预测），因此**只交付预测与哈希**。

---

## 8. 论文表 A–E

完整机器可读版本见 `results/MACE_direct_GLM_v2_1_paper_tables.csv`。

### Table A — Direct Model Comparison（DEV）

| method | MSMS exact | false | unmatched | 备注 |
|---|---|---|---|---|
| Direct GLM 4.7 Flash（本轮） | **9/30 (30.0%)** | 53 | 12 | 25 题全跑，严格 block-family |
| Direct Qwen 32B（配对子集） | 3/15 (20.0%) | 60 | 42 | 仅 10 题可配对 |
| Direct GLM（同配对子集） | 4/15 (26.7%) | 8 | 4 | 与上行同题同输入 |
| Direct Qwen 32B（全 25 题） | 待统一统计 | – | – | 无对应运行，不得外推 |
| C0 | 待统一统计 | – | – | 冻结 v2.1 运行（21 题/27 输入口径） |
| Full MACE | 待统一统计 | – | – | 同上 |

### Table B — 按机制
见 §3.3。Direct Qwen / C0 / Full MACE 列标为"待统一统计"，未用外推值填充。

### Table C — 效率
见 §6；含峰值显存 18,909 MiB。

### Table D — 失败分析
见 §5.1，逐输入明细在 paper_tables.csv 的 `D` 组。

### Table E — HELDOUT 子集预测覆盖（未评分）

| 子集 | 题数 | 已完成预测 |
|---|---|---|
| full heldout | 25 | 25 |
| project-disjoint | 19 | 全部覆盖 |
| template-disjoint | 16 | 全部覆盖 |
| both-disjoint | 14 | 全部覆盖 |

---

## 9. 报告要求的七个问题

**（1）纯 GLM 的 DEV 严格准确率是多少？**
**9/30 = 30.0%**（25 题全部完成，30 个 MASKED 输入，strict block-family）。Precision 0.4933，Recall 0.6400，False Relations 53，Unmatched Sets 12。

**（2）与同协议 Direct Qwen 相比如何？**
在可配对的 10 题 / 15 输入上：GLM **4/15 (26.7%)** vs Qwen **3/15 (20.0%)**；GLM 假关系 **8** vs Qwen **60**，耗时 **172.5 s** vs **596.5 s**。差异为 +1 个输入，**不显著**，只能说明 GLM 在同一纯模型协议下"至少不弱于"Qwen，而非优于。两者规模/结构不同（29.9B MoE vs 32B dense），不是严格等规模对照。

**（3）哪些机制最好 / 最差？**
最好：M4 替代路径 **2/2**、M3 三操作协作 **2/3**、M2 两操作协作 **3/6**。最差：M5 条件分支 **0/2**（15 条假关系）、M6 **0/2**、M8 **0/1**、M9 **0/3**、M1 单操作 **1/9**。

**（4）能否识别 2 操作 / 3 操作协作？**
**部分可以**：协作类合计 **5/9（55.6%）**，其中 M2 3/6、M3 2/3。失败不是"识别不出协作"，而是两种形式：完全空输出（`make_id_nonid`、`ellipsis` 等），以及把协作拆成多个单操作候选（`educate_dashes`：`{U1}`、`{U2}`、`{U1,U2}`）。因此它的协作识别能力**弱于**候选扩展 + 搜索的 Full MACE，但明显强于随机。

**（5）是否产生大量假关系？**
**有，但比 Qwen 少得多**：DEV 53 条，配对子集仅 8 条（Qwen 60 条）。假关系高度集中：humanize 一题 15 条、coverage 14 条、adjlist 7 条，三题占 36/53。另有一类特殊"假关系"是空集合噪声（7 例），会让严格判等失败但不代表模型给出了错误操作。

**（6）运行时间与 token 成本？**
DEV 25 题 **347.3 s**（13.9 s/题，P95 33.3 s），prompt 98,370 + completion 15,223 token，生成 51.5 tok/s，峰值显存 18,909 MiB。HELDOUT 25 题 **325.1 s**。评测总计 11.2 min，远低于 45 min 硬截止。配对 10 题上 GLM 的 wall time 是 Qwen 的 **29%**。

**（7）HELDOUT 预测是否已冻结、可用于盲测？**
**是。** 25/25 预测已保存，SHA-256 `b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f`；未读取任何 HELDOUT 参考答案，未评分，不会因 HELDOUT 结果修改 prompt 或重跑。

---

## 10. 限制与偏差声明

1. **Prompt 截断**：有效上限 ≈4096 token，DEV 15/25 题、HELDOUT 10/25 题受影响。这是与 Direct Qwen 相同的协议限制，但会系统性压低长源码题成绩。未静默处理，逐题记录。
2. **样本量**：配对比较仅 15 个输入，任何 +1 量级差异都不显著。
3. **模型差异**：GLM 与 Qwen 在规模、结构（MoE vs dense）、语料、推理栈上都不同，不构成受控的同规模对比。
4. **MMBS 不参与**：Direct 协议不请求 MMBS，记为 N/A，不计为错误或空。
5. **单次运行**：1 次/题、0 重试、temperature 0、seed 42；但仍存在推理栈层面的非确定性，重复运行可能有小幅波动。
6. **Direct 协议本身**：没有候选宇宙、搜索与验证器，模型必须"凭阅读直接说出关系"，因此它测的是模型的先验能力，不是 MACE 的能力。
7. **HELDOUT 未开封**：本轮只交付预测与哈希。

---

## 11. 交付物与哈希

| 文件 | SHA-256 |
|---|---|
| `results/MACE_direct_GLM_v2_1_dev.json` | `c12a590eafc7925d9290cd4e631ba7f0252f2e0da376c9006b12e3fc4e65a6f8` |
| `results/MACE_direct_GLM_v2_1_heldout_predictions.json` | `b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f` |
| `results/MACE_direct_GLM_v2_1_per_task.csv` | `4d2f6f26c4ecbef6004a96da289672add8741416fdaf11493fd63a38212d83f4` |
| `results/MACE_direct_GLM_v2_1_efficiency.csv` | `0a4d468d927ee1367ac0e32ffb497d2c4d4a8aa4c43e57d7ae0221b2d7340031` |
| `results/MACE_direct_GLM_v2_1_paper_tables.csv` | `b5c133a3ef85e887bad63702a5c832dc41c3f39219e6383181ebb353d9f9b5fc` |
| `results/MACE_direct_GLM_v2_1_config.json` | `0ec929fe26a3883e703eb80b1aaf66c4599acccdbcfa71e463f6625c274bef29` |
| `scripts/run_direct_glm_v2_1.py` | `c12e7ad757b520d2d29b89e3959b21966447ec86f8d928647effbe087d693560` |
| `scripts/analyze_direct_glm_v2_1.py` | `823193e78e7d94c47a1ce03cdfda3e8a73bcbdee8e16844e8ff308f6fc0f10a1` |

原始响应与调用统计：`runs/direct_glm_v2_1/dev/`（25 个）、`runs/direct_glm_v2_1/heldout/`（25 个），每题含完整 messages、raw_response、token 统计与 prompt SHA-256。

---

**本轮到此结束。** 未修改 MACE 算法、数据集、标准答案或既有 Qwen 结果；HELDOUT 保持未开封。
