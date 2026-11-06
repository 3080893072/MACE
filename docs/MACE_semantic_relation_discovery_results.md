# MACE 语义关系发现实验结果

- 日期：2026-11-04
- 分支：`research/mace-role-separated-search`
- 基线 commit：`3daac28`（角色分离搜索 v2 冻结版）
- 审计依据：`docs/MACE_full_mace_wiring_audit.md`
- 本轮新增代码：`open_ops/semantic_relations.py`、`open_ops/pilot_oracle.py`、
  `scripts/run_semantic_relation_discovery.py`、`tests/test_semantic_relation_discovery.py`
- 产物：`runs/v3_semantic_relations/`（`results.json`、`pilot_only.json`、
  `prompts/`、`run.log`、`tests.log`、`code_hashes.json`）

## 0. 结论先行

本轮完成的是**代码适配 + CPU 单元测试 + CPU 最小实验**。真实模型的新协议
（C 臂）**没有运行**：本机 `127.0.0.1:11434` 无 Ollama，AutoDL 的
`37377`、`22099` 端口均拒绝连接；按既有约定不在本机 GPU 上跑模型，
也不允许伪造模型输出。因此：

1. **旧协议（B 臂）可测且已测**：四个任务上，旧 Qwen 输出没有发现任何
   Graph 之外的操作，确认的关系集合与 Graph-only 完全相同；首次确认成本
   在 ctrl_02 持平、其余三个任务全部变慢。
2. **新协议（C 臂）未测**：提示词已生成并落盘，AST 映射、角色翻译、假设门控
   都有单元测试和 CPU 端到端测试，但**没有一条真实的 Qwen 语义关系样本**。
3. **fixture 正向控制可测**：把 Graph 自己发现的关系改写成新协议格式后，
   五条关系全部通过同一个因果验证器（含条件 exact/sound/complete），且在
   ctrl_03 上把首 MSMS 均值从 6.00 降到 3.71、首 MMBS 从 7.86 降到 5.29。
   这证明**管线能利用正确语义关系**，但 fixture 不是模型输出，不能算 Qwen 的功劳。
4. **结论**：现有证据不足以支持"把语义关系发现作为 Full MACE 核心机制"。
   建议保留为可选路径，先做一次有真实 32B 样本的定向验证（见 §7）。

## 1. 实验配置

预算：每个可搜索输入最多 16 次子集评估；两/三臂共享同一 `U`、同一执行器、
同一最小性判据、同一证据缓存。`ctrl_02`/`ctrl_03` 与 `filestorage` 的
`2^|U|` 不超过预算，因此自然穷举；`get_host` 的 `2^5=32 > 16`，两臂都只覆盖
96/192 个子集，**不能声称穷尽**。

| 任务 | 类型 | \|U_graph\| | 可搜索输入 | B 臂模型与来源 |
|---|---|---:|---:|---|
| ctrl_02 | pilot | 2 | 5 | Qwen1.5B，历史 direct-relation 原始输出 |
| ctrl_03 | pilot | 4 | 14 | Qwen1.5B，历史 direct-relation 原始输出 |
| werkzeug_get_host_default_empty | 冻结 v3 | 5 | 6 | qwen2.5-coder:32b，30 分钟运行的真实排序输出 |
| werkzeug_filestorage_stream_name | 冻结 v3 | 3 | 4 | qwen2.5-coder:32b，30 分钟运行的真实排序输出 |

**重要口径差异**：v3 的 B 臂是用户定义的"旧 Qwen 排序"；pilot 没有历史排序
输出，只有旧协议的 direct-relation 输出，因此 pilot 的 B 臂是"Graph + 旧协议
关系假设"，不是排序。两者不能当作同一个方法的严格同质样本，表中分别标注。

`U_qwen = 0`、`U_union = U_graph` 对全部四个任务成立。这不是模型"没提新操作"
的证明——C 臂根本没跑；它只说明旧输出（pilot 的关系、v3 的排序）没有越出
Graph 候选集。

## 2. 旧协议（B）vs Graph-only（A）

### 2.1 首确认成本

| 任务 | 臂 | 首 MSMS 均值 | 首 MMBS 均值 | 子集评估 | probes | 已确认集合是否相同 |
|---|---|---:|---:|---:|---:|---|
| ctrl_02 | A | 3.00 | 2.00 | 20 | 240 | — |
| ctrl_02 | B | 3.00 | 2.00 | 20 | 240 | 是 |
| ctrl_03 | A | 6.00 | 7.86 | 224 | 680 | — |
| ctrl_03 | B | **7.71** | **9.00** | 224 | 680 | 是 |
| get_host | A | 4.33 | 3.33 | 96 | 194 | — |
| get_host | B | **6.00** | **4.33** | 96 | 194 | 是 |
| filestorage | A | 4.50 | 3.00 | 32 | 68 | — |
| filestorage | B | **7.25** | **7.00** | 32 | 68 | 是 |

相对变化：ctrl_03 MSMS +28.6% / MMBS +14.5%；get_host +38.5% / +30.0%；
filestorage +61.1% / +133.3%；ctrl_02 持平。逐输入值见 `results.json` 的
`summaries.*.first_msms_values` / `first_mmbs_values`。

两臂的 `probe_executions` 相同，因为预算内最终执行了同样多的子集；差别只在
**顺序**。也就是说，B 臂不是"多做了验证"，而是把错误先验排到了前面。

### 2.2 旧输出的候选质量

| 任务 | 映射操作数 | 新操作 | Precision | Recall | 备注 |
|---|---:|---:|---:|---:|---|
| ctrl_02 | 2 | 0 | 1.00 | 1.00 | C、D 都在 U_graph；两条 independent 关系均为 FALSE |
| ctrl_03 | 2 | 0 | 1.00 | 0.50 | 只提到 C、D，漏掉 B、E；两条关系均为 FALSE |
| get_host | 5（仅排序） | 0 | — | — | MSMS 提议 85/87/90：85、87 命中已确认集合，90 未命中；MMBS 提议 93/95 全未命中 |
| filestorage | 3（仅排序） | 0 | — | — | MSMS 提议 2926 命中；MMBS 提议 2921 未命中（已确认 MMBS 为 2924） |

v3 的"命中"是与预算内搜索确认集合比较，不是与真值比较；get_host 本身不完整，
因此只能当下界看。旧排序接口**结构上只能重排 U**，不可能提出新操作。

### 2.3 门控统计（仅 pilot）

| 任务 | 假设见证 MSMS/MMBS | 实际探测 MSMS/MMBS | 结果 |
|---|---:|---:|---|
| ctrl_02 | 0 / 10 | 10 / 10 | 关系本身 FALSE；MMBS 侧因"禁用后暴露"偶然见证 |
| ctrl_03 | 0 / 4 | 28 / 28 | 关系 FALSE；28 次 MSMS 假设探测全部未见证 |

v3 的 B 臂来自审计回放，只有搜索轨迹，没有门控计数器，因此不填。

## 3. 新协议（C）的实现与状态

实现在 `open_ops/semantic_relations.py`，覆盖用户第二节的全部要求：

- 模型输出必须是结构化 relation：`kind ∈ {independent, cooperative, fallback,
  coexisting}`，每个操作带 `file/line/text`，另含 `condition`、
  `data_dependence`、`control_dependence`、`source_evidence`、`rationale`。
- 每个提案先过 AST 身份与源码跨度映射。接受条件：命中真实 `ast.stmt` 且有
  span；±1/±2 行偏移仅在文本匹配时恢复；多行 Graph 操作体内部的行折叠回该
  Graph 操作；目标行永远拒绝。无法映射的提案进入 `rejected`，不静默丢弃。
- `U_graph`、`U_qwen`、`U_union` 分开保存；Graph 操作从不因模型未提及而删除。
- 所有关系初始 `status = "HYPOTHESIS"`；只有 `status == "OK"` 且谓词为真的
  见证才获得优先，最多每角色 3 次、交替进行，探测计入预算；失败的假设仍留在
  搜索空间里。
- 角色翻译：`independent/cooperative/fallback` → MSMS 的 kept 集合与 MMBS 的
  disabled 集合；`coexisting` → 仅 MMBS；不可执行的操作标
  `HYPOTHESIS_UNEXECUTABLE`，不交给搜索器。

**状态：NOT_RUN。** 本机与 AutoDL 均无可用模型端点（TCP 全部 refused），
本轮没有产生任何新协议模型输出。`runs/v3_semantic_relations/prompts/` 下
四个提示词已按绝对行号生成：

| 任务 | 提示词字符数 | sha256（前 16 位） |
|---|---:|---|
| ctrl_02 | 3625 | 见 `prompts.json` |
| ctrl_03 | 4310 | 见 `prompts.json` |
| get_host | 6012 | 见 `prompts.json` |
| filestorage | 5134 | 见 `prompts.json` |

由于没有调用，**token 数和模型 wall time 均为 0 / 未测**；不能从字符数反推
token 数并冒充实测。

## 4. 正向控制：fixture（不是模型输出）

`graph_fixture` 把 Graph 自己的 `discover` 关系改写成新协议格式（provenance
写 `graph discovery: <case>`，rationale 明说"pipeline fixture, not a model"），
走完全相同的解析、映射、门控和验证路径。用途是回答"如果语义关系是对的，
管线能不能用起来"，**不回答 Qwen 准不准**。

### 4.1 因果验证（同一验证器、best-of 全部合法输入）

| 任务 | 关系 | 状态 | 见证输入 | 条件检查 |
|---|---|---|---|---|
| ctrl_02 | cooperative {C,D} | VERIFIED | case_0000 | VALID, exact/sound/complete |
| ctrl_03 | independent {B} | VERIFIED | case_0000 | VALID, exact/sound/complete |
| ctrl_03 | independent {E} | VERIFIED | case_0004 | VALID, exact/sound/complete |
| ctrl_03 | cooperative {C,D} | VERIFIED | case_0012 | VALID, exact/sound/complete |
| ctrl_03 | coexisting {B,E} | VERIFIED | case_0008 | VALID, exact/sound/complete |

（修复前 `verify_pilot_relations` 固定取第一个 masked 输入做见证，导致
ctrl_03 的 E、C&D、B&E 被误判 FALSE；本轮已改为遍历全部合法输入并取最优状态，
`attempts` 分别记录 1/5/13/9 次。）

### 4.2 搜索效果

| 任务 | 臂 | 首 MSMS 均值 | 首 MMBS 均值 | 相对 A |
|---|---|---:|---:|---|
| ctrl_02 | A | 3.00 | 2.00 | — |
| ctrl_02 | C_fixture | 4.00 | 3.00 | **更慢** +33% / +50% |
| ctrl_03 | A | 6.00 | 7.86 | — |
| ctrl_03 | C_fixture | 3.71 | 5.29 | **更快** −38.1% / −32.7% |

这个对比说明了两个必须同时报告的事实：

1. 正确的多操作假设能把首确认显著提前（ctrl_03）。
2. 假设不是免费的：假设探测优先于直接搜索，在 `|U|` 很小、正确关系又很大的
   任务上会额外消耗预算（ctrl_02 的 MSMS 必须同时保留 {C,D} 才能见证，且确认
   还要等严格子集证据）。

另有一个**见证 ≠ 确认**的细节：ctrl_03 最后一个输入上，正确的 {C,D} 假设在第 6
步就产生 masked 见证并获得优先，但 `firstMSMS` 记在第 10 步，因为严格最小性
要求先评估 {C}、{D} 两个真子集。这是契约要求，不是搜索 bug；也意味着
"关系正确"并不自动等于"首确认立刻发生"。

## 5. 评价指标汇总

| 指标 | 旧协议 B | 新协议 C | fixture（非模型） |
|---|---|---|---|
| 发现的新真实操作 | 0（四任务） | **未测** | 0（按构造全在 U_graph） |
| 候选 Precision / Recall | ctrl_02 1.00/1.00；ctrl_03 1.00/0.50；v3 无新操作 | **未测** | ctrl_02 1.00/1.00；ctrl_03 1.00/1.00 |
| independent 正确性 | 2 条提议，0 条 VERIFIED（2 FALSE） | **未测** | 2 条 VERIFIED |
| cooperative 正确性 | 0 条提议 | **未测** | 2 条 VERIFIED |
| coexisting 正确性 | 0 条提议 | **未测** | 1 条 VERIFIED |
| MSMS/MMBS 正确性 | 确认集合与 A 完全相同（无新增、无错误新增） | **未测** | 与 A 相同 |
| 条件推断正确性 | 未被评分：关系在条件检查前已 FALSE；`True` 与 `p!=0 and q!=0` 都不可信 | **未测** | 5/5 VALID 且 exact/sound/complete |
| 子集评估 / probes | 20/224/96/32；probes 240/680/194/68 | 0 | 与 A 相同 |
| token 数 | pilot 1655、2085（1.5B）；v3 539、429（32B） | 0 | 0 |
| 模型 wall time | pilot 6.60s、8.60s；v3 55.99s、52.45s | 0 | 0 |

关于"条件推断正确性"必须说清楚：旧协议的两条 ctrl_02 关系声明
`condition = "True"`，ctrl_03 声明 `p != 0 and q != 0`，但四条关系在
`only_set_masks` / `disabling_set_exposes` 阶段就判 FALSE，验证器**没有进入**
条件评分分支。所以不能把这四条条件算作"预测错误"或"预测正确"——它们是
**未被检验**，而且一个 FALSE 关系上的条件本来也无法靠条件本身救活。

## 6. 直接回答五个问题

### Q1. Qwen 是否发现了 Graph 漏掉的操作？

**旧协议：没有。** 四个任务上 `U_qwen = 0`。pilot 的模型输出可以自由给任意
行号，但它只给了 Graph 已有的 C/D（ctrl_02）和 D/C（ctrl_03）；v3 的旧接口
按设计只接受 `U` 内的 id，结构上不可能新增。因此"旧 Qwen 没发现新操作"是
可测结论，不是实现限制造成的假象（pilot 侧）。

**新协议：未测。** AST 管线本身能接受 Graph 外的操作（单测
`test_new_operation_appears_in_the_operation_report`），但没有一条真实模型
样本来证明 Qwen 会用这个能力。

### Q2. 是否正确发现了 cooperative masking？

**旧协议：没有提出任何 cooperative 关系。** pilot 只输出 independent；v3 的
旧接口只输出排序。ctrl_02 的真实关系恰恰是 cooperative {C,D}，旧模型把它拆成
两条独立关系，结果两条都 FALSE。

**新协议：未测。** 管线支持 cooperative 的 MSMS kept 集与 MMBS disabled 集，
fixture 的 cooperative {C,D} 在 ctrl_02/ctrl_03 上都 VERIFIED；但这是管线能力，
不是模型能力。

### Q3. 是否准确预测了关系成立的条件？

**旧协议：无法支持"准确"的判断。** 见 §5：四条关系都在条件检查前失败；
`True`（ctrl_02）在事实上不可能成立（没有任何单操作能独立 mask），
`p != 0 and q != 0`（ctrl_03）也没有被验证器评分。

**新协议：未测。** 验证器能给出 exact/sound/complete 与 false_accept/
false_reject；fixture 的五条条件全部 exact。但缺少模型样本。

### Q4. 是否比旧 Qwen 排序策略更有价值？

**在已测范围内，旧排序策略是持平到有害的；新协议还没有可比的实测数字。**
四个任务上 B 与 A 的确认集合完全相同，B 在三个任务上把首确认推后
（最多 +133%），在 ctrl_02 上持平。新协议唯一可量化的是 fixture 上界：
关系全对时 ctrl_03 首 MSMS −38.1%、首 MMBS −32.7%，但 ctrl_02 反而变慢。
所以正确表述是：**新协议的潜力有正向控制支撑，但"比旧排序更有价值"尚未被
真实模型样本证明。**

### Q5. 是否值得把语义关系发现作为 Full MACE 的核心机制？

**当前证据不支持。** 理由：

1. 核心收益（发现 Graph 漏掉的操作、正确 cooperative 关系、可迁移条件）
   一条都没有真实模型样本。
2. 已有旧协议证据显示模型语义先验在 `|U| ≤ 5` 时收益为负，且固定调用成本
   无法摊销；新协议只是把"猜排序"换成"猜关系"，没有消除模型不可靠这一根因。
3. fixture 说明即使假设全对，小 `|U|` 上假设探测本身也可能是净成本。

**建议（不在本轮执行）**：保留新协议为可选路径；下一次只做一次定向验证：
四个开发题各 1 次真实 32B 调用（同一提示词、temperature 0、seed 42），
在相同预算下比较 C 与 A，并重点记录 `U_qwen` 是否非空、cooperative 关系是否
VERIFIED、条件是否 exact。只有当"新真实操作 > 0 且至少一条 cooperative
VERIFIED"时，才值得讨论把它升为核心机制。不要在本轮自动扩大实验。

## 7. 限制与未完成项

- **C 臂 NOT_RUN**：无模型端点；0 token、0 wall time、0 模型关系。
- **B 臂不同质**：pilot 是 Qwen1.5B 的旧 direct-relation 输出，v3 是
  qwen2.5-coder:32b 的旧排序输出；不能合并成单一"旧 Qwen"估计。
- **get_host 不完整**：预算 16 只覆盖 96/192 个子集，确认集合只是下界。
- **fixture 不是模型**：所有 VERIFIED 的 cooperative/条件都来自 Graph 自身
  关系，不能计入 Qwen 的指标。
- **旧条件未被评分**：关系在条件分支前已 FALSE。
- **v3 B 臂门控计数缺失**：审计回放没有保留 witness/probed 计数器。
- **只有 4 个开发题**，全部 DEV-TUNED；没有 held-out，也没有统计显著性。
- 未重跑 515 个目标，未重跑 SQLAlchemy coverage，未修改冻结 Benchmark、
  HIDDEN scorer、Graph 权重或最小性判据。

## 8. 复现

```bash
# 单元测试 + 全量回归（373 个用例，退出码 0）
python -m pytest tests -q

# 四个任务的 CPU 实验（无模型调用）
python -u -m scripts.run_semantic_relation_discovery \
  --out runs/v3_semantic_relations/results.json

# 只跑 pilot
python -u -m scripts.run_semantic_relation_discovery \
  --tasks ctrl_02 ctrl_03 --out runs/v3_semantic_relations/pilot_only.json

# 只生成提示词
python -u -m scripts.run_semantic_relation_discovery \
  --emit-prompts runs/v3_semantic_relations/prompts \
  --out runs/v3_semantic_relations/prompt_only.json

# 有真实端点时（本轮未运行）
python -u -m scripts.run_semantic_relation_discovery --live \
  --endpoint http://127.0.0.1:11434 --model qwen2.5-coder:32b \
  --out runs/v3_semantic_relations/results_live.json
```

代码与产物哈希：`runs/v3_semantic_relations/code_hashes.json`。
`results.json` sha256 = `5d18a9ee…668bac6aa`。`tests.log` 记录 373 个用例全部
通过（pytest 配置抑制了汇总行，只输出点阵；退出码 0）。
