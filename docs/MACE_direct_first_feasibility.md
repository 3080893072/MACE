# Direct-First Full MACE 可行性审查（离线重放）

**范围**：使用 M5/M6 已冻结的 11 道 Guard 任务与原始运行记录，检查“先运行 Direct Qwen，再用现有验证器 / MACE 局部关系证据检查并修复其 Guard”的离线可行性。

**这不是在线 Direct-First 实验。** 本报告没有调用任何模型，没有生成新的候选，没有修改评分器、任务定义或冻结历史。所有 Guard 都来自 `m5/` 下的已存运行；候选选择只使用有界验证器在声明有限域上的成对执行结果，**从未读取 `experiments/hidden/*_reference.json`**。参考语义只在计分和事后解释中使用。11 道题在 M5/M6 中已被查看和调试，因此这是探索性证据，不是 held-out 测试；所有“正确”均指在声明有限域上逐输入相等（`BOUNDED`），不是 `PROVEN`。

产物：

* **`direct_first/feasibility.json`** — 本报告的全部逐题数字，由 [scripts/direct_first_feasibility.py](<local-path> 生成。
* **`evidence_gate/replay.json`** — 固定的 Direct / MACE / 组合器候选及其验证结果。

复现（无模型调用）：

```bash
python scripts/evidence_gate_replay.py          # 生成 evidence_gate/replay.json
python scripts/direct_first_feasibility.py      # 生成 direct_first/feasibility.json
```

---

## 0. 结论（先回答五个问题）

1. **有没有互补正确案例？** 没有。Direct 精确 5/11，Full MACE 精确 3/11，两者都精确 3 例；**MACE 单独正确而 Direct 错误的案例为 0**。两套最终 Guard 的事后 oracle union 上限是 **5/11**，而且这 5 例全部已经由 Direct 覆盖。
2. **MACE 能否在不使用参考答案的情况下识别 Direct 的实际错误？** 能识别“G0 错了”，但多数不能定位到可执行的修复。有界验证器对 6/6 个 Direct 错误题给出明确的 false accept / false reject、反例和最小对比对；但关系级证据只在 **1/6**（`parity_snap`）直接产出一个精确替代 Guard，另外 **2/6**（`sort_channel`、`toggle_pair`）只指出部分缺失条件，**3/6**（`modulo_absorb`、`swap_channels`、`clamp_absorb`）无法给出可执行修复。
3. **能否修复且不破坏 Direct 原本正确的案例？** 可以，但只多修好 1 例。策略“G0 验证精确则保留，否则用组合器候选”得到 **6/11**（+`parity_snap`），Direct 原本正确的 5 例 **0 损失**。若不加验证门、无条件换成组合器，则降为 3/11（丢掉 `dedup_channel`、`overwrite_channel`，`dict_slot` 变为 unknown）。
4. **当前验证器的双向检查是否足够？** 对“验证/选择”足够：Guard 级检查同时统计 false accept（`unsound`）和 false reject（`incomplete`），能在声明域上认证一个候选是否精确。对“修复”不够：它只能否证候选，不能生成候选；关系级的 observer 检查只验证“在该条件下不变”，不验证“该条件是否已经覆盖所有可掩蔽输入”，因此发现不了缺失的析取项（`sort_channel`、`toggle_pair`）。此外 `incomplete` 在一般情况下混合了 false reject 与 Guard 求值错误。
5. **是否值得实现一个最小的在线 Direct-First 版本？** 技术上可行且改动很小，但**不建议作为新的算法贡献实现**。收益是 1/11（5→6），代价是在 6 个被否证的题上额外跑 Full MACE 关系归纳：**+86,403 tokens、+426.14 s，合计 110,029 tokens / 528.45 s**，约为 Direct 的 4.7 倍。唯一增益来自确定性组合器，而不是 Direct-First 的选择机制或 Evidence Gate；M6 已报告同一组合器在 `parity_snap` 上精确、确定性归纳在 10/11 上精确且 0 token。Direct-First 被现有组件支配。

**决策：不做在线实现。** 若论文需要一个“验证器门控回退”的对照行，可以引用本离线重放的 6/11，但必须标注为 fixed-proposal replay，不能写成在线结果。

---

## 1. 数据与口径

| 集合 | fixtures |
|---|---|
| dev6 | `alt_masking`, `dedup_channel`, `modulo_absorb`, `overwrite_channel`, `sort_channel`, `swap_channels` |
| held1 | `dead_flag`, `dict_slot`, `parity_snap` |
| held2 | `clamp_absorb`, `toggle_pair` |

* Direct 候选 G0：`m5/base/{f}/direct_seed42.json`（held2 为 `m5/H3/{f}/direct_seed42.json`）的 `final_guard`。
* Full MACE 候选：`m5/A3/{f}/mace_seed42.json`（held1 为 `m5/H2`，held2 为 `m5/H3`）的 `final_guard` 与 `final_bundle`。
* 组合器候选：对同一份 MACE 关系与验证报告运行确定性组合器（`compose_ungated` / `compose_gated`），不额外调用模型。
* 检查器：`scripts.m6_symbolic.check_guard`，在完整声明域上重新检查每个候选，输出 `BOUNDED` / `REFUTED` / `INVALID`。
* false accept（FA）= `unsound`：Guard 判 True，但 P+ 与 P- 输出不同。
* false reject（FR）= `incomplete`：Guard 判 False，但 P+ 与 P- 输出相同。
* 6 个 Direct 错误题的 `checked == usable_rows`，因此这些题的 `incomplete` **全部是 false reject，没有 Guard 求值错误**。

注意：Direct 运行本身已包含验证反馈，并会在 Guard 通过时提前停止。5 个精确题的状态都是 `GUARD_VERIFIED`（1–3 轮），6 个错误题的状态都是 `ROUNDS_EXHAUSTED`（3/3）——**Direct 自己的循环已经知道它失败了**，不需要额外的检测机制。这里的 G0 是它的最终输出，不是一次盲写。

---

## 2. 逐题互补性

### 2.1 2×2 矩阵

| | MACE 正确 | MACE 错误 |
|---|---|---|
| **Direct 正确** | 3：`alt_masking`, `dead_flag`, `dict_slot` | 2：`dedup_channel`, `overwrite_channel` |
| **Direct 错误** | **0** | 6：`modulo_absorb`, `sort_channel`, `swap_channels`, `parity_snap`, `clamp_absorb`, `toggle_pair` |

* Direct 精确：5/11。
* Full MACE 精确：3/11。
* 两者都精确：3/11。
* **互补正确案例：0。**

### 2.2 逐题 Guard、状态与失败原因

| fixture | Direct G0 | Direct 状态 | FA / FR | MACE Guard / 状态 | 组合器 | 失败原因 |
|---|---|---|---|---|---|---|
| `alt_masking` | `mode == 0 or mode == 1` | BOUNDED | 0 / 0 | `mode == 0 or mode == 1` / BOUNDED | exact | 无 |
| `dedup_channel` | `distinct(xs) == distinct(xs + [xs[0] + 1])` | BOUNDED | 0 / 0 | `len(xs) == 0 or (...)` / INVALID | incomplete | MACE 自己的 Guard 含 `distinct`/`fn_0` 组合，类型检查失败；Direct 精确 |
| `modulo_absorb` | `cap and (fn_0(xs) + 1) % 10 == 0` | REFUTED | 47 / 212 | `cap and (...) if not cap else ...` / INVALID | unknown | Direct 把条件写反了：真条件是 `cap and fn_0(xs) % 10 != 9`，Direct 恰是它的补 |
| `overwrite_channel` | `fn_0(xs) == 0 if not keep else True` | BOUNDED | 0 / 0 | `keep or not keep` / REFUTED | unknown | MACE 给出恒真 Guard，28 个 false accept；Direct 精确 |
| `sort_channel` | `use_left == False and use_right == False` | REFUTED | 1134 / 6452 | `xs == sorted(xs)` / REFUTED | incomplete | Direct 只看 flags，忽略 `pre` 和“首尾恰为 min/max”的条件；MACE 的 `sorted` 只是充分条件，仍漏 7046 例 |
| `swap_channels` | `not show_gap` | REFUTED | 0 / 4 | `True` / REFUTED | unknown | Direct 漏掉 `n == k`（swap 不影响 gap）；MACE 恒真，12 个 false accept |
| `dead_flag` | `True` | BOUNDED | 0 / 0 | `True` / BOUNDED | exact | 无 |
| `dict_slot` | `mode` | BOUNDED | 0 / 0 | `mode` / BOUNDED | unknown | 无（组合器因关系缺口返回 unknown） |
| `parity_snap` | `sum(xs) % 2 == 0 and not even` | REFUTED | 43 / 43 | `even and sum(xs) % 2 == 0 or not even` / REFUTED | **exact** | Direct 把 `even` 写反；MACE 多加了 `or not even`，85 个 false accept；组合器得到 `even and sum(xs) % 2 == 0`，精确 |
| `clamp_absorb` | `sum(xs) + 1 == min(sum(xs) + 1, 10) if cap else sum(xs) + 1 == sum(xs)` | REFUTED | 74 / 11 | `total_post <= 10 or not cap` / INVALID | unknown | Direct 在 `cap` 内写反；真条件是 `cap and sum(xs) >= 10`；MACE 在 Guard/observer 作用域使用了 `total_post`，全部 INVALID |
| `toggle_pair` | `not flag` | REFUTED | 6 / 9 | `flag` / REFUTED | unknown | Direct 把 `flag` 写反且漏掉 `n == 0`；真条件是 `flag or n == 0`；MACE 修好了 `flag` 一侧，但仍漏 `n == 0`（3 个 false reject） |

“失败原因”一列使用真值语义解释，只用于本报告的分析；它没有参与任何候选选择。

### 2.3 oracle union

* **Direct ∪ Full MACE 的事后 oracle union = 5/11**（`alt_masking`, `dead_flag`, `dict_slot`, `dedup_channel`, `overwrite_channel`）。
* 这是一个**使用参考答案计分的事后上限**，不是任何方法的成绩；因为 MACE-only 集合为空，它等于 Direct 的 5/11。
* 若把组合器也视为候选，事后 union 为 **6/11**（多出 `parity_snap`）。这个 6 是本报告第 3 节策略实际达到的数，但在线选择只依赖验证器，不依赖参考答案。

---

## 3. Direct-First 策略模拟

策略定义（全部只使用运行时信息）：

1. 运行 Direct，得到 G0；
2. 在声明有限域上验证 G0；
3. 若 G0 精确（FA = FR = 0），保留 G0；
4. 否则取 MACE 关系上的确定性组合器候选，验证；若精确则采用；
5. 若仍不精确，回退到 G0 并标注“未修复”（不计为精确）。

| 策略 | 精确 | 相对 Direct | 说明 |
|---|---|---|---|
| Direct only | 5/11 | — | 基线 |
| Full MACE only | 3/11 | −2 | 最终 Guard 质量更差 |
| 组合器 only | 3/11 | −2 | `alt_masking`, `dead_flag`, `parity_snap`；丢掉 `dedup`, `overwrite`, `dict` |
| **Direct-First（G0 精确则保留，否则组合器）** | **6/11** | **+1** | 新增 `parity_snap`；Direct 的 5 例 0 损失 |
| Direct-First（gated 组合器） | 6/11 | +1 | 与上一行相同；Evidence Gate 在此题不改变结果 |

关键点：

* **增益只有 `parity_snap` 一例**。组合器候选 `even and sum(xs) % 2 == 0` 与真值逐输入一致；它来自 MACE observer `O0` 的 BOUNDED 条件，不是 Direct 的修正。
* **不破坏 Direct 正确案例**：策略在 G0 精确时不替换，因此 `alt_masking`、`dedup_channel`、`overwrite_channel`、`dead_flag`、`dict_slot` 全部保留。模拟结果确认 5/5 无损。
* **验证门是必需的**：无条件使用组合器会降到 3/11；无条件使用 MACE 也是 3/11。
* 选择 `compose` 还是 `gated` 不影响结果；`parity_snap` 在两个组合器下都精确。

### 3.1 成本

| 方法 | tokens | model wall s |
|---|---|---|
| Direct（11 题） | 23,626 | 102.31 |
| Full MACE（11 题） | 141,081 | 704.51 |
| Direct-First（Direct 全部 + 仅 6 个被否证题跑 MACE） | **110,029** | **528.45** |

* 额外验证成本：组合与重新检查是确定性的，0 token；上述差异全部来自 MACE 关系归纳。
* Direct-First 相对 Direct 约 4.7× tokens；相对 Full MACE 省约 31k tokens，但精确数从 3 提到 6。
* M6 的确定性归纳在同一 11 题上是 **10/11、0 token**；符号引擎（带 helper 摘要）是 **11/11、0 token**。Direct-First 的 +1 在这两者面前没有竞争力。

---

## 4. MACE 证据能否定位具体错误

对 6 个 Direct 错误题逐一检查关系级证据（全部来自已存 `final_report`；没有参考 Guard）：

| fixture | Direct 错误 | 关系级证据 | 能否定位到可执行修复 |
|---|---|---|---|
| `modulo_absorb` | 47 FA / 212 FR；`cap` 内条件写反 | `O0`（cond `cap`）faithful failures = 341；`O1`（cond `not cap`）faithful = 216、faithful_minus = 475；`U2` fixed-point REFUTED | **否**。所有 observer 都被否证或不可信；没有任何关系提出 `fn_0(xs) % 10 != 9`。验证器只能说明“cap 不是充分条件”，不能给出正确谓词 |
| `sort_channel` | 1134 FA / 6452 FR；忽略 `pre` 与首尾条件 | `O0`/`O1` 在 `xs == sorted(xs)` 下 BOUNDED（invariance 1000/0）；组合器得到 `sorted` | **部分**。它指出 `sorted` 是充分条件，修掉 1134 个 FA，但仍漏 7046 个 FR；真条件 `pre or ((use_left or xs[0]==min) and (use_right or xs[-1]==max))` 没有任何关系表达 |
| `swap_channels` | 0 FA / 4 FR；漏 `n == k` | `O2`（gap）REFUTED，invariance 32/12 | **否**。这 12 个失败是 MACE 自己恒真 Guard 的 false accept（`show_gap and n != k`），不是 Direct 的 false reject（`n == k`） |
| `parity_snap` | 43 FA / 43 FR；`even` 写反 | `O0`（cond `even and sum(xs) % 2 == 0`）BOUNDED，invariance 43/0，faithful 0；组合器即该条件 | **是**。组合器给出精确 Guard，验证器确认 0 FA / 0 FR |
| `clamp_absorb` | 74 FA / 11 FR；`cap` 内写反 | `U1`,`U2`,`O0`,`O1`,`O2` 全部 INVALID（在 observer/upstream/Guard 作用域使用 `total_post`） | **否**。作用域错误本身是有效诊断（模型用错了变量），但没有给出 `cap and sum(xs) >= 10` |
| `toggle_pair` | 6 FA / 9 FR；`flag` 写反且漏 `n == 0` | `U1`,`U2`,`O0`,`O1` REFUTED；MACE Guard `flag` 只剩 3 FR | **部分**。`flag` 修掉 6 FA 和 6 FR，但 `n == 0` 不在任何关系里；组合器 unknown |

汇总：**1/6 完整修复，2/6 部分定位，3/6 只能检测“G0 错”而不能修复。**

---

## 5. 五个问题的正式回答

### Q1. 两套方法有没有互补正确案例？

没有。矩阵为 3（都对）/ 2（仅 Direct 对）/ 0（仅 MACE 对）/ 6（都错）。Direct 精确 5，MACE 精确 3，MACE 的正确集合是 Direct 正确集合的真子集。事后 oracle union 上限 5/11，且全部由 Direct 覆盖。

### Q2. MACE 能否在不使用参考答案的情况下识别 Direct 的实际错误？

分两层：

* **检测层：能，6/6。** 有界验证器用 P+/P- 成对执行即可判定 G0 的 false accept 与 false reject，并给出反例、最小对比对和 `A_changed_local_state`。这些全部是运行时信息，不读参考 Guard。
* **定位/修复层：只能覆盖 1/6。** `parity_snap` 的关系证据 + 组合器直接给出精确候选；`sort_channel` 和 `toggle_pair` 只能指出一个缺失条件；`modulo_absorb`、`swap_channels`、`clamp_absorb` 没有可执行修复。原因不是验证器不够强，而是**候选生成**不够：错误类型包括条件取反、缺失析取项、作用域错误，现有关系/组合器模板无法从反例自动构造这些修正。

### Q3. 是否能修复错误，同时不破坏 Direct 原本正确的案例？

能，但只多修 1 例。门控策略“G0 精确则保留，否则用组合器；组合器不精确则回退”得到 6/11，Direct 的 5 个正确案例全部保留（0 损失）。若去掉门控、无条件替换，则降到 3/11。因此“不破坏”依赖于**只在验证失败时替换**，而不是候选本身更好。

### Q4. 当前验证器的双向检查是否足够？

* **对验证/选择：足够。** Guard 级 `unsound`（false accept）与 `incomplete`（false reject）是双向的，能在声明有限域上认证候选是否精确；本批 6 个错误题的 `checked == usable_rows`，因此 `incomplete` 没有混入求值错误。
* **对修复：不够。** 它只回答“这个候选在域上是否精确”，不回答“下一个候选从哪里来”。关系级 observer 检查是“在声明条件下不变 + 双向 faithfulness”，但并不检查条件的**完整性/极大性**：一个条件可以 BOUNDED 通过，却漏掉大量可掩蔽输入（`sort_channel` 的 `sorted`、`toggle_pair` 的 `flag`）。因此缺失析取项在关系层是不可见的。
* **一般性限制：** `incomplete` 在一般情况下混合 false reject 与 Guard 求值错误；本批恰好可以分离。所有结论是 `BOUNDED`，不是 `PROVEN`。选择与评估使用同一完整域，属于 in-sample 选择；若要作为在线结论，必须按 M6 的 fit/eval 划分重新做。
* 结论：**双向检查足以“判卷”，不足以“改卷”。**

### Q5. 是否值得实现一个最小的在线 Direct-First 版本？

**不建议作为研究贡献实现。** 理由：

1. **收益极小且孤立**：5→6（+1 题），且唯一增益来自确定性组合器；Direct-First 的选择逻辑没有贡献额外正确案例。
2. **成本高**：在 6 个被否证题上跑 MACE 关系归纳，额外 86,403 tokens / 426.14 s，总计 110,029 tokens / 528.45 s，约为 Direct 的 4.7 倍。
3. **被现有组件支配**：M6 的确定性归纳 10/11、0 token；符号引擎 11/11、0 token；同一组合器单独在 `parity_snap` 上已经精确。把 Direct-First 写成新算法会与这些已冻结结果冲突。
4. **可复现性有限**：只有 seed 42 的一次存储运行；`parity_snap` 的修复依赖模型恰好提出了 `O0` 的条件，不能保证在线重跑复现。

如果论文确实需要一个“先 Direct、失败再验证回退”的对照，可以报告本离线重放的 **6/11** 与成本，并明确标注 fixed-proposal replay；但不应据此宣称在线 Direct-First 系统或算法优势。

---

## 6. 决策与停止

* **Direct-First 作为新算法：NO-GO。** 互补案例为 0；关系级可修复案例仅 1/11；增益被 M6 的确定性归纳和符号引擎支配。
* **Direct-First 作为离线诊断/对照行：可用。** 6/11，0 损失，成本已测量；必须标注为 fixed-proposal replay，且 11 题均为已查看的探索性样本。
* **不再开发在线 Direct-First。** 本轮完成可行性审查后停止，不开启新的 M7/M8 里程碑，不修改冻结历史，不把 Evidence Gate 重放或本次重放冒充在线算法实验。
