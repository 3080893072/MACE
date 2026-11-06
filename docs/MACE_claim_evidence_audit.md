# MACE 论文贡献审查表与证据一致性审计

日期：2026-11-03
审计对象：`docs/MACE_paper_draft.md`（804 行，审计前版本）
产出：`docs/MACE_paper_draft_final.md`（修订版）、本文件

本轮不做新算法、不调用模型、不修改历史评分与数据集。所有结论仅依据仓库内已冻结的日志、replay 与源码。

---

## 0. 总结论

**现有证据不足以支持“新算法优于强基线”的主张。** 具体地：

- Direct Qwen 5/11，Full MACE 3/11，确定性组合器 3/11，证据门组合器 3/11；证据门的精确数增益为 **0**、损失为 **0**。
- 2x2 中 Full MACE 没有任何“独有正确”的 fixture，两者最终 guard 的 oracle union 仍是 **5/11**。
- Direct-First 的 **6/11** 是在固定提案、已检查过 fixture 上的**离线模拟**：只多 1 例（`parity_snap`），多出的这一例来自组合器，不是 Full MACE 的最终 guard；代价是 4.66x token、5.17x 墙钟；不构成在线算法结果。
- 同一批 11 个 fixture 上，纯符号方法 **7/11**（0 token）、符号 + **人工撰写** helper 摘要 **11/11**、有界归纳充分方向 **10/11**（0 token，25.2 s）。在准确率与成本上都优于所有 LLM 路线。

因此最终稿的定位只能是：**有界、可审计的契约框架 + 明确的负结果 + 证据清单**，不能写成“更强的 masking 分析器”。

---

## 1. 逐项审计（对应任务 10 点）

### 1.1 核对每个算法模块是否真实实现和运行

| 模块 | 实现位置 | 真实实现 | 实际运行 | 运行证据 |
|---|---|---|---|---|
| 类型化关系语言、作用域、解析/类型检查 | `mace/terms.py`, `mace/contracts.py` | 是 | 是 | 每次 `verify` 都解析 bundle；运行日志中 7 条 `INVALID` 关系、3 个 `INVALID` guard 证明拒绝路径真的执行过 |
| 声明域与 P+/P- 配对执行 | `mace/domain.py`, `mace/program.py`, `mace/runner.py` | 是 | 是 | `evidence_gate/replay.json` 的 `domain_size`、`channels`、`domain_exhaustive`；11 个域全部 `exhaustive=true` |
| 有界验证（target effect / upstream / fixed point / 双侧 faithfulness / invariance / guard / observer soundness / composition / behaviour classes） | `mace/verify.py` | 是 | 是 | 所有 M5/M6 存储报告的 `relations`、`guard`、`soundness`、`behaviour` 字段；`verify.py` 第 214 行起逐项实现 |
| 确定性组合器 | `mace/compose.py` | 是 | 是 | replay 的 `compose`/`gated` 两列；cell D 9/9 |
| 证据门（W/R/U 三态） | `mace/evidence_gate.py` | 是 | 是 | replay 对 59 条关系逐条分类：24 WITNESS_VERIFIED、27 REFUTED、8 UNVERIFIED |
| 反例修复循环（≤3 轮、patch、反馈） | `mace/loop.py`, `mace/prompts.py` | 是 | 是 | 存储的 M5 多轮运行；`m6/repair.json` 回放 77 个槽位 |
| 模型接口与 prompt 隔离 | `mace/qwen.py`, `mace/prompts.py` | 是 | 是 | prompt 文件头明确“never sees B1/B2 labels, reference formulas, or any file from experiments/hidden”；M5 运行可复现 |
| 符号执行引擎 | `mace/symbolic.py`, `scripts/m6_symbolic.py` | 是 | 是 | `m6/symbolic.json` |
| 有界谓词归纳 | `mace/induct.py`, `scripts/m6_induct.py` | 是 | 是 | `m6/induct_dev.json`, `m6/induct_held.json` |
| 证据门 replay | `scripts/evidence_gate_replay.py` | 是 | 是 | `evidence_gate/replay.json`, `replay.md` |
| Direct-First 可行性模拟 | `scripts/direct_first_feasibility.py` | 是 | 是（离线） | `direct_first/feasibility.json` |

唯一需要特别标注的“已实现但未在线运行”的路径：**证据门对修复反馈的影响**。`mace/loop.py` 在 `evidence_gate=True` 时会把非 `WITNESS_VERIFIED` 关系列为失败（`_failures`），逻辑已实现；但本轮没有开启 gate 重跑模型，因此“门控反馈会改变修复轨迹”只有代码，没有实验证据。最终稿 §4.7 与 §7 已明确说明。

未发现“论文里写了、代码里没有”的模块。

### 1.2 将 Full MACE Guard 推导任务与 AST 操作级掩盖发现任务严格分开

最终稿的处理：

- §2 只用 O1（`reliable_ast_v1` 1.0.1）案例作为动机，并明确“不是本文 Guard 评估的一部分”；
- §3.2 定义 G1（单个标记赋值、输出一个布尔输入 guard、在有限域上等于真实 mask）；
- §3.4 单独说明 O1 的单位是“每个候选操作是否被掩盖/暴露”，输出不是输入 guard，17/17 是另一个语料、另一条流水线、另一个分析单位的结果；
- Appendix B 明确禁止把 O1 的 17/17 写成 MACE/Guard 结果。

修订版没有任何一处把 O1 的数字放进 RQ 表。

### 1.3 将 Direct-First 6/11 明确标记为 fixed-proposal offline simulation

最终稿新增 **RQ6**，并在 Abstract、Contribution 5、§5.3、§7、§9、Appendix B 六处标注：

- 只有 2x2 + oracle union + 策略模拟；没有在线运行；
- 选择只使用候选 guard 的有界检查；不读取 reference bundle/guard；
- MACE 关系来自已存储运行，不重新生成；11 个 fixture 已被多轮检查；
- 结果 6/11：保留 5 个 Direct exact，`parity_snap` 由组合器补上；0 损失；
- 增益归属是**组合器替换**，不是 Full MACE 最终 guard；
- 代价 110,029 tokens / 528.45 s（4.66x token、5.17x 墙钟）；
- 失败定位：G0 错误 6/6 可被检测，但完整修复仅 1/6，部分 2/6，仅检测 3/6；瓶颈是候选生成；
- 明确结论：不足以证明 Direct-First 是新的有效算法。

### 1.4 将 Pure Symbolic 7/11 与 Symbolic + 人工摘要 11/11 区分

最终稿 RQ5 的处理：

- 明确写成两行：“Pure Symbolic (no helper summaries) 7/11, 0 token, 0.012 s”和“Symbolic + **human-written** helper summaries 11/11, 0 token, 0.016 s”；
- 正文明确指出 7/11 才是全自动结果；11/11 的 helper 摘要是**人手写的输入**，不是引擎发现的，因此不是自主结果；
- 列出 4 个纯符号 `ABSENT/UNKNOWN` 的 fixture（`dedup_channel`、`modulo_absorb`、`overwrite_channel`、`sort_channel`）；
- Appendix B 禁止把两者当作同一结果，禁止把 11/11 写成自主结果。

### 1.5 人工模板条件归纳的效果与泛化限制分别说明

效果（有证据）：

- 充分方向，full 池在 `eval` 划分上 **10/11**（dev 6/6，held 4/5）；0 token；25.2 s（dev 23.45 + held 1.77）；
- 必要方向 **0/11**；
- 只针对“A 的 mask guard”这一子义务，不是全部 MACE 义务。

限制（有证据）：

- 谓词模板库是**人工设计**的；full 池 dev 6/6，generic 池 dev 只有 **2/6**，差额就是模板家族；
- 归纳的选择/学习/修复只用 learn/tune/fit，eval 只计分；但 `dead_flag` 在 `fit` 上 exact、在 `eval` 上失败，说明小样本下仍有 fit/eval 差距；
- 不覆盖其他义务，也不能外推到模板词汇之外；
- 不是 LLM 语义发现，不能算作 LLM+MACE 的贡献。

最终稿 RQ5 与 §7 分别写了效果与限制。

### 1.6 检查 Figure、Table、Algorithm 1、RQ 结论与实际日志

- **Figure**：原稿没有任何 Figure（无图号、无图片引用），最终稿保持无图；因此不存在图文不一致。
- **Table**：
  - 11 个 fixture 的 channels/domain size 与 `evidence_gate/replay.json` 完全一致（1/160、1/240、1/518、2/80、2/10912、3/32、2/40、2/80、1/170、1/170、2/18）；
  - RQ1 四行计数与 replay 一致；
  - per-fixture 表与 replay 一致；
  - RQ4 成本与 `m6/symbolic.json` 的 direct/mace 行一致（23,626 / 141,081；102.31 / 704.51 s）；
  - RQ5 的 7/11、11/11、10/11、0/11 与 `m6/symbolic.json`、`m6/induct_*.json`、`docs/M6_decision.md` 一致。
- **Algorithm 1**：原稿有三处与 `mace/loop.py` 不完全一致，已改：
  1. 原稿写“if all_relations_pass and guard_ok: return”，实际代码先判断 `report.status != "OK"` 就停止；

     修订为两步停止条件（25-28 行）；
  2. 原稿没有写“derived guard 替换后会再 verify 一次”，修订为第 21-23 行；
  3. 原稿没有写“gate off 且 composer 无表达式时保留模型 guard”，修订为正文说明。
- **RQ 结论**：见第 2 节的数字修正表；修正后每条结论都能指向日志或明确的非冻结本地测量。

### 1.7 对没有优势的实验如实报告，不删除负面结果

最终稿保留并显式报告：

- Direct 5/11 优于 Full MACE 3/11；MACE token 5.97x、墙钟 6.9x；
- 证据门 0 增益、0 损失；
- 组合器 6/11 `UNKNOWN`（以覆盖率换 soundness）；
- 3 个 Full MACE `INVALID` guard；
- 修复回放 35/77 → 37/77，只有 2 个 `parity_snap` 回归，收益仅 +2/77；
- 11 个 fixture 上的历史 0/2（held2 早期结果）保留；
- Direct-First 仅 +1 例、4.66x 成本、离线模拟；
- 符号方法全面优于 LLM 路线。

没有删除任何负面结果，也没有把未运行的方法写成 0%。

### 1.8 明确说明 11 个 Guard fixture 已用于多轮开发诊断，不是独立保留测试集

最终稿在以下位置明确说明：

- Abstract：“eleven exploratory programs”；
- §5.1：**“All eleven have been used in multiple rounds of development and diagnostic analysis (M5 and M6). None is an independent retained test set.”**
- §7 External validity：程序是本研究自行编写、早期里程碑中检查过，不是 fresh benchmark；
- Appendix B：禁止写成 independent held-out benchmark。

### 1.9 不宣称已证明全域掩盖条件，不把 WITNESS_VERIFIED 标为 PROVEN

最终稿的处理：

- §4.4：状态只有 `BOUNDED`/`TESTED`/`REFUTED`/`INVALID`/`UNKNOWN`，实现中“no path that emits `PROVEN`”；
- §4.6：门证据仍受 `D` 限制；`WITNESS_VERIFIED` is not `PROVEN`；
- §7：`BOUNDED` 不是 `PROVEN`，域外可能失效；
- Abstract/§9：只说 bounded equality，不说 proof；
- Appendix B：禁止把 bounded 结果写成 proof，禁止把 `WITNESS_VERIFIED` 写成 `PROVEN`；
- 全文没有“proves masking”“verified on all inputs”之类措辞。

### 1.10 生成论文贡献审查表（已实现 / 已实验验证 / 尚未证明）

见第 3 节。

---

## 2. 数字与措辞修正表

| 原稿 | 修订版 | 原因 / 依据 |
|---|---|---|
| “composer exact on 9/9 diagnostic cases”（未说明是哪 9 个） | “9/9 (the six `dev6` plus the three `held1`; `held2` not run)” | `m5/cells_C.json` 只有 9 条；held2 不在其中 |
| RQ4 “1.21 ms / 1.38 ms per fixture” | 撤回；改为“frozen replay 不记录 CPU；本地审计单次测量 0.15 ms（ungated）/ 0.42 ms（gated）全部 11 个，非冻结” | 原数字无存储 artifact；本地 `compose_ungated` / `gate_report+compose_gated` 实测 |
| §5.5 “16.02 ms all eleven (1.46 ms per fixture)” | 撤回，理由同上 | 无存储 artifact |
| “composer never looks at the input domain” | “does not read individual domain rows, real outputs, or the model's guard; consumes the per-relation verdicts already computed from those rows” | `mace/compose.py` 读取 `report` 中的 `BOUNDED/TESTED` 状态，状态来自域执行 |
| “8/9 first failures upstream” | 保留，但加 caveat：该计数包含被误用的 `supporting` upstream 槽位，不是 8 个独立 fixed-point 失败 | `docs/M5_diagnosis.md` §3.1 明确说明 |
| “Direct-First” 未出现 | 新增 RQ6，6/11 标注为 fixed-proposal offline simulation | `direct_first/feasibility.json`；本轮任务要求 |
| RQ5 “Pure 7/11 (4 UNKNOWN)” | “7/11 (4 UNKNOWN/ABSENT)” | `m6/symbolic.json` 中这 4 例的 status 是 `ABSENT` |
| “Symbolic + helper summaries 11/11” | 明确加 **human-written**，并说明不是自主结果 | 任务要求；helper 摘要为人工撰写 |
| 归纳 “25 s” | “25.2 s (dev 23.45 + held 1.77)” | `docs/M6_decision.md` 第 296 行 |
| 归纳 “10/11” 未说明口径 | 明确为 `eval` 划分；补 `dead_flag` fit-exact 但 eval-fail | `m6/induct_dev.json`, `m6/induct_held.json` |
| `sound` 列未解释 | 明确 `sound = exact + incomplete` | 指标定义 |
| “Five contributions” | “Six contributions”，加入 Direct-First 的诚实处理 | 新增 RQ6 |
| Algorithm 1 停止条件不精确 | 按 `mace/loop.py` 修正为 `status != OK` 与 `all_relations_pass` 两步 | 源码 |
| 成本表 “extra program executions: 0” 含义不清 | 改为 “extra model calls / extra program executions”，并说明是 gate/composer 相对已存储关系的增量 | 避免把 MACE 自身验证执行误读为 0 |

---

## 3. 论文贡献审查表

| # | 贡献 | 已实现 | 已实验验证 | 尚未证明 |
|---|---|---|---|---|
| C1 | 类型化契约语言 + 有界验证器（9 类义务） | 是：`terms.py`, `contracts.py`, `verify.py` | 是：59 条关系逐条状态；7 条 INVALID、27 REFUTED；9 类义务均有字段 | 域外正确性；语言覆盖完备性；与真实仓库的适用性 |
| C2 | 确定性组合器 + 显式 INCOMPLETE | 是：`compose.py` | 是：系统结果 3/11；人工契约诊断 9/9；11 例无 unsound | 一般性 soundness 保证（目前只是这 11 例的经验）；不丢 channel 的完备性 |
| C3 | Evidence-Gated Local Relations | 是：`evidence_gate.py` | 是：59 条中拒 1 条（`dedup_channel/O0`）；精确数 0 增益 0 损失；0 额外调用/执行 | 门控反馈在在线修复中的效果；准确率收益；域外非空洞性 |
| C4 | 受控实证 + 负结果 | 是：M5/M6/replay | 是：Direct 5/11、MACE 3/11、Composer 3/11、Gated 3/11；token/墙钟 | 11 例之外的可推广性；单次运行的方差 |
| C5 | Direct-First 的诚实处理 | 是：`direct_first_feasibility.py` | 是（离线）：6/11；2x2；oracle union 5/11；4.66x 成本 | 在线运行；独立测试；算法优越性 |
| C6 | 可复现证据清单与审计 | 是：`MACE_paper_evidence_inventory.md`、本文件、Appendix C | 是：脚本可重跑；230 tests | 独立第三方复现 |
| C7 | 符号/归纳对照 | 是：`symbolic.py`, `induct.py`, `m6_*.py` | 是：Pure 7/11；Symbolic+人工摘要 11/11；归纳 10/11 / 0/11 | 全自动 11/11；其他义务；模板库外泛化；与 LLM 路线的公平在线对比 |
| C8 | G1 与 O1 任务分离 | 是：§2/§3.4/Appendix B | 是：两类日志从未混用 | 统一的“掩盖”理论（本文不主张） |

---

## 4. 明确不支持的主张

以下句子**不得**出现在投稿版本或 rebuttal 中，除非未来有新的独立实验：

1. “MACE / Full MACE outperforms Direct Qwen.” —— 方向相反（3/11 vs 5/11）。
2. “Evidence-Gated Local Relations improves accuracy.” —— 0 增益、0 损失。
3. “Direct-First is a new effective algorithm.” —— 6/11 是离线固定提案模拟，+1 例，4.66x 成本，且被符号方法支配。
4. “The eleven fixtures are a held-out benchmark.” —— 全部用于多轮开发诊断。
5. “MACE proves the mask condition.” / “WITNESS_VERIFIED means PROVEN.” —— 只有 `BOUNDED`。
6. “The model has learned the masking semantics.” —— 负结果明确反对。
7. “The symbolic 11/11 is an autonomous result.” —— 依赖人工 helper 摘要；纯符号是 7/11。
8. “Bounded induction 10/11 is automatic semantic discovery.” —— 依赖人工模板库，且只覆盖 mask-guard 子义务。
9. “The AST 1.0.1 17/17 is a MACE result.” —— 不同任务、不同语料。
10. “9/9 human-reviewed contracts is a system result.” —— 诊断上限，不是系统结果。

---

## 5. 仍存在的证据缺口（按重要性）

1. **独立测试集**：11 个 fixture 全部被开发过程污染。任何“泛化”主张都需要新 fixture，且在新 fixture 上冻结 prompt/阈值后再跑。
2. **在线 gate 实验**：门控反馈会改变修复轨迹，但没有 gate-on 的新模型运行；目前只能说“固定提案下无增益”。
3. **Direct-First 在线化**：离线模拟的选择规则本身可在线计算（有界检查），但 MACE 关系需要现场生成；成本与收益（尤其只有 `parity_snap` 一例）不支持继续投入。
4. **方差**：每个 fixture 单次运行（temperature 0, seed 42），无法给出 run-to-run 区间。
5. **符号/归纳的自主性**：11/11 与 10/11 都有人工输入（helper 摘要 / 模板库）；需要区分“程序分析的潜力”与“本文方法的贡献”。
6. **O1 与 G1 的桥接**：目前只是任务分离；把操作级干预机制接到 Guard 循环是未来工作，未实现、未评估。

---

## 6. 交付物与复现

- 修订论文：`docs/MACE_paper_draft_final.md`
- 本审计：`docs/MACE_claim_evidence_audit.md`
- 复现命令：

```bash
cd <local-path>
python -m pytest -q
python scripts/evidence_gate_replay.py
python scripts/m6_symbolic.py
python scripts/direct_first_feasibility.py
```

- 结果 artifact：`evidence_gate/replay.json`、`m5/cells_C.json`、`m6/symbolic.json`、`m6/induct_dev.json`、`m6/induct_held.json`、`m6/repair.json`、`direct_first/feasibility.json`。

本轮未新增算法模块、未调用模型、未修改任何冻结结果或数据集。
