# MACE 核心逻辑修复结果

本文件是 [`MACE_logic_and_run_provenance_audit.md`](MACE_logic_and_run_provenance_audit.md)
的修复交付。修复在独立分支 `fix/mace-core-logic-repair` 上完成，历史默认路径
保留为 `core_logic="legacy"`，新路径为 `bugs` / `candidates` / `full`。

**证据标签：** 本文所有逐例结果都是 `FIXED_PROPOSAL_REPLAY`。它们用冻结的 M5
`raw_response` 字符串驱动一个假客户端，**没有调用任何模型**，不是新的在线 Qwen
实验。所有成功标签都是有限域上的 `BOUNDED` / `TESTED` / `EXACT`，不是形式化
`PROVEN`。

**未改动：** `m5/` 冻结数据、参考 Guard、评分器、既有 `request` /
`raw_response`、历史 Token 与耗时记录。运行时选择不读取参考 Guard 或离线
exact 标签。

---

## 1. 审计发现 → 修复提交对照

提交：

| 提交 | 内容 |
|---|---|
| `18aac79` | `core_logic.py`、`compose.py`、`evidence_gate.py`：候选池、失败分类、witness 边界 |
| `8368196` | `verify.py`：作用域、重复 observer、fixed-point 聚合、评估错误、derived 状态 |
| `a9d0c10` | `loop.py` / `sandbox.py` / `runner.py` / `cli.py`：四种修复级别与 CLI |
| `05ffcdd` | `tests/test_core_logic_repair.py`、`scripts/core_logic_replay.py` |
| 本文档提交 | 本文档与 `runs/core_logic_replay/replay.json` |

| 审计编号 | 缺陷 | 修复位置 | 生效级别 | 回归测试 |
|---|---|---|---|---|
| C1 | observer `condition` 用 `_post` 作用域编译、用 entry 值求值 | `verify.py:301` | B/C/D | `test_observer_condition_post_name_is_invalid_in_core_not_refuted_legacy` |
| C2 | 同一 channel 多个 observer 时 soundness 被误判 `UNKNOWN` | `verify.py:439-499` | B/C/D | `test_duplicate_observers_keep_soundness_in_core` |
| C3 / A2 | fixed-point 聚合只看 failures，成员 `REFUTED` 仍报 `BOUNDED/checked=0` | `verify.py:522-550` | B/C/D | `test_fixed_point_aggregate_reports_unknown_without_witness` |
| C4 / A1 | 无 witness 的 observer 进入 Composer | `compose.py:46-103`；`verify.py:553` | 仅 D（`full`） | `test_composer_excludes_no_witness_observer`、`test_full_witness_gate_changes_composition_not_bugs_or_candidates` |
| C5 | `_same_relations` 不比较 `role` / `channel` | `loop.py:127-148` | 全部（比较函数本身） | `test_same_relations_detects_role_and_channel_changes` |
| C8 | Composer 无表达式时 derived 外层固定 `UNKNOWN` | `verify.py:557-565` | B/C/D | `test_derived_guard_reports_incomplete_when_a_channel_has_no_witness` |
| C9 | gated adapter 把 `INVALID` / `REFUTED` 都压成 `UNVERIFIED` | `evidence_gate.py:159-185` | 全部（gate 开启时） | `test_gated_report_preserves_invalid_and_refuted` |
| B4 / B6 | Guard 已 exact 仍被后续轮次覆盖；Guard 状态与辅助关系耦合 | `loop.py:498-511`；`core_logic.py:137-239` | B/C/D | `test_candidate_pool_does_not_replace_exact_with_invalid`、`test_core_stops_when_guard_is_exact_even_if_auxiliary_relation_fails` |
| B4（撤销） | exact Guard 不能被新反例保护 | `core_logic.py:160-178` | C/D | `test_candidate_pool_revokes_an_exact_guard_on_new_counterexample` |
| 新鲜度 | derived / selected Guard 替换后沿用旧报告 | `loop.py:397-413`、`loop.py:389` | C/D | 同上两条候选池测试 + 回放中的逐轮 fresh verify |
| 分类 | `FALSE_ACCEPT` / `FALSE_REJECT` / `EVALUATION_ERROR` / `INVALID_CONTRACT` / `UNVERIFIED_RELATION` / `UNKNOWN` 混用 | `core_logic.py:52-123` | B/C/D | `test_guard_failure_taxonomy`（5 例）、`test_relation_without_witness_is_unverified_not_bounded` |
| B1 | 只能生成充分条件，不能生成必要条件 | 未修复 | — | 记录为 `OPEN_ALGORITHM_LIMITATION` |
| B2 | Composer 布尔表达力不足（不能合取 fixed-point、不能表达跨 channel 相关分支、不能取反） | 未修复 | — | `OPEN_ALGORITHM_LIMITATION` |
| B3 / C6 | 补丁不能新增 upstream fixed_point、不能改 `role` / `channel` | 未修复 | — | `OPEN_ALGORITHM_LIMITATION` |
| B5 | 没有 coverage-directed synthesis，不会自动发现新析取分支 | 未修复 | — | `OPEN_ALGORITHM_LIMITATION` |
| C7 | generic 基线的 summary 调用没有独立 exchange | 未修复（不在核心循环范围） | — | 仍须在 provenance 层标注 |

---

## 2. 实际改动源码位置

新增：

- [`mace/core_logic.py`](../mace/core_logic.py)：
  - `guard_exact` / `guard_sound` / `classify_guard_report` /
    `classify_relation_evidence`（52-123 行）；
  - `CandidatePool`（137 行）：`offer`、`recheck`、`select`、`history`。
- [`tests/test_core_logic_repair.py`](../tests/test_core_logic_repair.py)：19 个测试。
- [`scripts/core_logic_replay.py`](../scripts/core_logic_replay.py)：无模型 A/B/C/D 回放。

修改：

- [`mace/verify.py`](../mace/verify.py)
  - 级别归一化与 witness 边界：229-237 行；
  - observer `condition` 的 entry 作用域：291-301 行；
  - observer INVALID 计数与评估错误：303-360、384-432 行；
  - 重复 observer 的 soundness：439-499 行；
  - fixed-point 聚合：522-550 行；
  - Composer witness 参数与 derived `INCOMPLETE`：553-565 行。
- [`mace/compose.py`](../mace/compose.py)
  - `_has_witness`：46 行；
  - `compose_guard(..., require_witness=...)`：76 行；
  - `semantics=sufficient_only`、`necessary_conditions=[]`、
    `exact_equivalence=not_established`、`complete=False`：158-180 行。
- [`mace/loop.py`](../mace/loop.py)
  - `CORE_LEVELS` 与参数校验：183-213 行；
  - `verify(..., core_logic=...)` 与 `_evaluate_guard`：55-70 行；
  - candidate pool / derived 候选 / 逐候选 recheck / selected 重新验证：
    307-413 行；
  - exact Guard 停止与 `ALL_VERIFIED` / `GUARD_VERIFIED` 区分：498-511 行；
  - `candidate_rounds` / `candidate_history` / `candidate_selection`：610-613 行。
- [`mace/sandbox.py`](../mace/sandbox.py)：75、86 行；
  [`mace/runner.py`](../mace/runner.py)：93 行；
  [`mace/cli.py`](../mace/cli.py)：245、267 行（`--core-logic`）。
- [`mace/evidence_gate.py`](../mace/evidence_gate.py)：`filtered_report` 保留
  `INVALID` / `REFUTED` / `UNVERIFIED` 的区别（159-185 行）。

调用入口：

```bash
# 历史行为（默认）
python -m mace.cli run --mode mace --core-logic legacy ...

# 只修实现缺陷
python -m mace.cli run --mode mace --core-logic bugs ...

# 修复 + 候选保留
python -m mace.cli run --mode mace --core-logic candidates ...

# 完整核心逻辑修复（含 witness-gated Composer）
python -m mace.cli run --mode mace --core-logic full ...
```

---

## 3. 新失败复现与回归测试

### 3.1 修复前的失败

- 新测试模块首次运行时，`mace.core_logic` 尚不存在：
  `ModuleNotFoundError: No module named 'mace.core_logic'`，测试收集失败。
- 每个测试内部同时断言 `legacy` 的旧行为，旧行为就是审计中的缺陷证据，例如：
  - C1：`legacy` 的 `O0.condition="total > 0"` 被判 `REFUTED`；修复后为
    `INVALID`，理由包含 “entry arguments”。
  - C2：加入重复 observer 后，`legacy` soundness 为 `UNKNOWN`；修复后为
    `BOUNDED` / `TESTED` 且 `checked > 0`。
  - C3：fixed-point 条件永假时，`legacy` 聚合为 `BOUNDED` 且 `checked=0`；修复后
    为 `UNKNOWN`，理由包含 “witness”。
  - A1：`legacy` Composer 把 condition 永假的 `O0` 收入组合；`full` 将其列入
    `unverified_relations` 并拒绝组合。
- 历史路径回放本身也是修复前基线：A 级别在 11/11 个 fixture 上逐字复现冻结
  M5 的 `final_guard` 与 `status`（见第 5 节），其中 `parity_snap` 的 A 最终
  Guard `unsound=127`，而它的第 1 轮候选是 exact。

### 3.2 修复后的回归

```text
tests/test_core_logic_repair.py   19 passed
full suite                        249 passed
```

19 个测试覆盖：

1. observer condition 作用域；
2. 重复 observer soundness；
3. fixed-point 聚合；
4. Composer 排除无 witness 关系；
5. Composer 只声明充分条件；
6. 候选池不覆盖 exact；
7. 新反例可撤销 exact 候选；
8. Guard exact 时不被辅助关系失败拖住；
9-13. 五类 Guard 失败分类；
14. 无 witness 关系是 `UNVERIFIED_RELATION`；
15. 非法 `core_logic` 级别拒绝；
16. derived 缺 channel 报 `INCOMPLETE`；
17. gated adapter 保留 `INVALID` / `REFUTED`；
18. `candidates` 与 `full` 在 witness 边界上的差异；
19. `_same_relations` 能识别 `role` / `channel` 变化。

---

## 4. 当前算法流程

```text
fixture + finite domain + Qwen proposal (or FIXED_PROPOSAL_REPLAY)
        |
        v
parse_bundle:  typed scopes
        |
        v
verify_bundle(core_logic = legacy | bugs | candidates | full)
  |
  |-- target_effects: condition => expr
  |-- upstream:       condition => supporting / fixed_point
  |-- observers:      condition (entry args) => two-sided channel invariance
  |-- duplicate observers: legal; one verified observer per channel for soundness
  |-- fixed_point aggregate: member status + checked>0 required
  |-- guard: status, checked, unsound, incomplete, evaluation_errors, exact
  |
  v
failure taxonomy
  FALSE_ACCEPT / FALSE_REJECT / EVALUATION_ERROR /
  INVALID_CONTRACT / UNVERIFIED_RELATION / UNKNOWN
        |
        v
compose_guard (sufficient-only, never a proof of equivalence)
  fixed_point OR  +  AND over channels of observer OR
  candidates: witness not required (historical composition policy)
  full:       require witness = checked>0 and invariance_checked>0 /
              fixed_point_checked>0
  output: semantics=sufficient_only
          necessary_conditions=[]
          exact_equivalence=not_established
          complete=False
          unverified_relations=[...]
        |
        v
CandidatePool (candidates / full)
  offer Qwen Guard
  offer derived Guard (if one was produced)
  recheck every candidate on the CURRENT domain
  select: exact preferred; else soundest partial; else least unsound
  exact incumbent is kept; only a new counterexample can revoke it
        |
        v
fresh verify of the selected bundle
        |
        +-- selected exact & all relations pass -> ALL_VERIFIED
        +-- selected exact & auxiliary fails   -> GUARD_VERIFIED
        +-- otherwise -> feedback / next proposal
        +-- proposals exhausted -> ROUNDS_EXHAUSTED
```

`legacy` 走原有分支，不进入 CandidatePool，也不改变 Composer 的 witness 策略。

---

## 5. 11 例离线重放（`FIXED_PROPOSAL_REPLAY`）

### 5.1 统计汇总

输入：冻结的 M5 提案字符串。`m5/A3/*` 9 例，`m5/H3/*` 2 例。
A/B/C/D 分别对应 `legacy` / `bugs` / `candidates` / `full`。
所有指标由 bounded checker 在当前 fixture 域上计算；未读取参考 Guard。

| 级别 | Exact | Sound | Invalid | Unknown | 候选劣化 | 仍无法合成 exact |
|---|---:|---:|---:|---:|---:|---:|
| A `legacy` | 3 | 3 | 3 | 0 | 1 | 7 |
| B `bugs` | 4 | 4 | 3 | 0 | 0 | 7 |
| C `candidates` | 4 | 4 | 3 | 0 | 0 | 7 |
| D `full` | 4 | 4 | 3 | 0 | 0 | 7 |

- A 的 11/11 `final_guard` + `status` 与冻结 M5 完全一致，说明回放路径没有漂移。
- A→B 的唯一 Exact 增益是 `parity_snap`：A 第 1 轮已经是 exact
  `even and sum(xs) % 2 == 0`，后续轮次把它覆盖成 `unsound=127`；B 在 Guard
  exact 时立即停止。
- B→C 在 11 例上没有额外 Exact 增益。原因是 B 的 exact-stop 已经消除了本批数据
  中唯一一次“正确候选被后轮覆盖”。C 的候选保留由单元测试单独证明：exact 候选
  不会被后续 `INVALID` 覆盖；新反例或新域可以让它被撤销。
- C→D 在 11 例上没有额外 Exact 增益，但改变了一个实际组合：
  `dedup_channel` 的 `O0` 在域上 `invariance_checked=0`。C 仍会把它组合成
  `len(xs) == 0`（bounded 后 `REFUTED`）；D 拒绝组合，derived Guard 为 `None`、
  状态 `INCOMPLETE`。这是证据边界的变化，不是精度收益。

### 5.2 逐例结果

格式：`分类(u/i)`，`u` = false accepts，`i` = false rejects。
`INVALID` 表示 Guard 本身无法在 entry-arg 作用域编译/取值。

| fixture | A legacy | B bugs | C candidates | D full | 最优轮 exact | 最终 exact |
|---|---|---|---|---|---|---|
| `alt_masking` | EXACT (0/0) | EXACT (0/0) | EXACT (0/0) | EXACT (0/0) | 是 | 是 |
| `clamp_absorb` | INVALID_CONTRACT | INVALID_CONTRACT | INVALID_CONTRACT | INVALID_CONTRACT | 否 | 否 |
| `dead_flag` | EXACT (0/0) | EXACT (0/0) | EXACT (0/0) | EXACT (0/0) | 是 | 是 |
| `dedup_channel` | INVALID_CONTRACT | INVALID_CONTRACT | INVALID_CONTRACT | INVALID_CONTRACT | 否 | 否 |
| `dict_slot` | EXACT (0/0) | EXACT (0/0) | EXACT (0/0) | EXACT (0/0) | 是 | 是 |
| `modulo_absorb` | INVALID_CONTRACT | INVALID_CONTRACT | INVALID_CONTRACT | INVALID_CONTRACT | 否 | 否 |
| `overwrite_channel` | FALSE_ACCEPT (28/0) | FALSE_ACCEPT (28/0) | FALSE_ACCEPT (28/0) | FALSE_ACCEPT (28/0) | 否 | 否 |
| `parity_snap` | **FALSE_ACCEPT (127/0)** | **EXACT (0/0)** | **EXACT (0/0)** | **EXACT (0/0)** | 是 | 是 |
| `sort_channel` | FALSE_REJECT (0/7046) | FALSE_REJECT (0/7046) | FALSE_REJECT (0/7046) | FALSE_REJECT (0/7046) | 否 | 否 |
| `swap_channels` | FALSE_ACCEPT (12/0) | FALSE_ACCEPT (12/0) | FALSE_ACCEPT (12/0) | FALSE_ACCEPT (12/0) | 否 | 否 |
| `toggle_pair` | FALSE_REJECT (0/3) | FALSE_REJECT (0/3) | FALSE_REJECT (0/3) | FALSE_REJECT (0/3) | 否 | 否 |

### 5.3 候选劣化

- A：`parity_snap` 第 1 轮 exact，第 2 轮 `INVALID`，第 3 轮
  `unsound=127`，最终采用第 3 轮。这是唯一一次实际劣化。
- B/C/D：0 次。B 的 exact-stop 阻止了 `parity_snap` 的后续轮次；C/D 另有
  候选池作为第二道保险。
- 回放中的候选历史、逐轮分类、淘汰理由保存在
  [`runs/core_logic_replay/replay.json`](../runs/core_logic_replay/replay.json)
  的 `cells[].rounds` 与 `cells[].selection` 中。

### 5.4 仍无法合成正确 Guard 的 7 例

这 7 例不是“修复没生效”，而是修复后的 checker 如实报告：这些固定提案中没有
任何一轮产生 exact Guard。

| fixture | 最终 Guard | 主要失败 | 归因 |
|---|---|---|---|
| `clamp_absorb` | `total_post <= 10 or not cap` | `INVALID`：`total_post` 不在 `mask_guard` 作用域 | 模型把 target-effect 的 `_post` 名字写进 Guard；需要模型语义修复，不是检查器 bug |
| `dedup_channel` | `len(xs) == 0 or (pre and ...)` | `INVALID`：`expected bool, got int` | Guard 的类型错误 |
| `modulo_absorb` | `cap and (...) if not cap else fn_0(xs)` | `INVALID`：条件分支 bool/int 不一致 | Guard 的类型错误 |
| `overwrite_channel` | `keep or not keep` | `FALSE_ACCEPT` 28 | 模型给出的恒真式；固定提案未出现可用的 channel 条件 |
| `sort_channel` | `xs == sorted(xs)` | `FALSE_REJECT` 7046 | 只表达了“已排序”，缺少 `pre` 等无条件分支；当前补丁语言不能新增 upstream fixed_point（B3/C6） |
| `swap_channels` | `True` | `FALSE_ACCEPT` 12 | 模型没有表达 channel 交换；Composer 也没有可用关系 |
| `toggle_pair` | `flag` | `FALSE_REJECT` 3 | 缺少 `not flag` 分支；没有自动发现新析取项（B5） |

---

## 6. 已修复的逻辑缺陷

1. **正确候选被覆盖**：`CandidatePool.select` 优先保留 exact；后续候选只有在新
   反例使 incumbent 失效时才能取代它。`legacy` 不进入该池，保持历史覆盖行为。
2. **Guard 状态与辅助关系耦合**：B/C/D 在 Guard 本身 exact 时停止。全部关系都
   通过时记 `ALL_VERIFIED`；只有 Guard 通过、辅助关系失败时记
   `GUARD_VERIFIED`，并保留 `all_relations_pass=False`，不再把两者混为一个状态。
3. **`_post` 作用域不一致**：observer `condition` 改为与求值一致的 entry-arg
   作用域；越界名字报 `INVALID_CONTRACT`，而不是伪装成 `REFUTED`。
4. **重复 observer 误判**：soundness 允许同一 channel 多个 observer，只要每个
   channel 至少有一个 verified observer；组合仍保留该 channel 的全部条件 OR。
5. **fixed-point 聚合 `checked=0` 仍报 `BOUNDED`**：聚合现在要求成员状态良好且
   `fixed_point_checked>0`；否则 `UNKNOWN`，有失败则 `REFUTED`。
6. **无 witness 关系进入 Composer**：`full` 要求 observer 的
   `invariance_checked>0`、fixed-point 的 `fixed_point_checked>0`；不满足者列入
   `unverified_relations`，不进入 OR/AND。B/C 保留历史组合策略，用于对照。
7. **derived Guard 替换后状态过期**：C/D 每轮对所有候选重新求值；选中候选再用
   其 bundle 做一次 fresh verify。`candidate_source` / `candidate_round` 随报告
   记录，避免把旧轮次的状态挂到新 Guard 上。
8. **反馈分类混用**：新增 `FALSE_ACCEPT`、`FALSE_REJECT`、
   `FALSE_ACCEPT_AND_FALSE_REJECT`、`EVALUATION_ERROR`、`INVALID_CONTRACT`、
   `UNVERIFIED_RELATION`、`UNKNOWN`；`checked=0` 不会被写成成功。
9. **Composer 语义边界**：返回值显式声明 `semantics="sufficient_only"`、
   `necessary_conditions=[]`、`exact_equivalence="not_established"`、
   `complete=False`。充分条件通过不等于完整 Guard，更不等于等价证明。
10. **gated 统计丢失原因**：`filtered_report` 保留 `INVALID` / `REFUTED` /
    `UNVERIFIED`，不再把它们压成同一个标签。

---

## 7. 未解决的算法能力缺口（`OPEN_ALGORITHM_LIMITATION`）

以下问题**没有**被本次修复解决，也不能靠改状态标签宣称解决：

1. **必要条件生成**：合同语言仍只有 `condition => expr` /
   `condition => invariance` 的充分条件，没有反向覆盖、否定或必要条件推理。
   Composer 仍可能给出 `INCOMPLETE` 的充分 Guard。
2. **Composer 的一般布尔表达力**：仍不能合取两个分别验证的 fixed-point 条件，
   不能表达跨 channel 的相关分支，不能取反。11 个参考 Guard 恰好落在现有结构内，
   不代表对更大程序完备。
3. **新析取分支发现**：没有 coverage-directed synthesis；当反例指向一个合同里
   不存在的分支（如 `sort_channel` 的 `pre`、`toggle_pair` 的 `not flag`）时，
   系统不会自动合成新关系。
4. **补丁语言限制**：`apply_patch` 仍只能 `revise` 已有 id 和
   `add_observers`，不能新增 upstream fixed_point，也不能修改 `role` /
   `channel`。`sort_channel` 的 `pre` 缺口属于这一类。
5. **`all_relations_pass` 的聚合口径**：本次只把“最终 Guard 是否保留”与辅助
   关系解耦，没有重新定义“哪些关系算完成证据”。未被 Composer 使用的
   `supporting` 关系仍会影响这个布尔值。
6. **模型语义错误**：`clamp_absorb` 的 `_post` 误用、`dedup_channel` 的
   bool/int 错误、`modulo_absorb` 的分支类型不一致，属于模型输出问题；检查器只能
   如实报 `INVALID_CONTRACT`，不能替模型修正。
7. **有界性**：所有 `BOUNDED` / `TESTED` / `EXACT` 都只对声明域成立。本文没有
   任何 `PROVEN` 结论；域外泛化仍需独立验证。

---

## 8. 真实在线 Qwen 对照仍需要的证据

当前 A/B/C/D 结果**不能**替代在线实验。要声称“修复改善了 Qwen 的端到端表现”，
至少需要：

1. **新的在线运行**：固定模型、量化、prompt、temperature、seed、上下文长度和
   轮数；A/B/C/D 在同一模型和同一 fixture 上各跑一次或多次。
2. **完整原始记录**：每次调用保存 `request`、`raw_response`、prompt/completion
   tokens、耗时、模型摘要、endpoint 与启动日志；不能只保留汇总。
3. **独立环境证据**：GPU 型号/显存、Ollama 或服务端日志、模型 digest；如果声称
   AutoDL，需要能与运行时间对齐的实例证据。
4. **运行时选择审计**：证明 CandidatePool 的选择日志只引用 bounded checker 的
   当前域结果，没有读取参考 Guard、离线 exact 标签或评分器。
5. **域外复核**：在同一批 fixture 上再构造一个 held-out 有限域，检查 exact
   Guard 是否只是拟合了开发域；撤销机制也需要在带新反例的域上测试。
6. **未解决项的单独实验**：必要条件生成、新析取分支、`add_upstream` 补丁语言
   支持，都需要新的算法/接口工作；本轮没有新增 Agent、Prompt 阶段或架构。
7. **统计口径**：按 `FALSE_ACCEPT`、`FALSE_REJECT`、`EVALUATION_ERROR`、
   `INVALID_CONTRACT`、`UNVERIFIED_RELATION`、`UNKNOWN` 分开报告，并同时给出
   `Exact` / `Sound` / `Incomplete` / `Unsound` / `Invalid` / `Unknown`；不能
   只报一个“准确率”。

在此之前，本文的结论仅限于：**在冻结提案的离线重放上，历史实现缺陷已被修复并
有回归测试覆盖；11 例中 1 例的 exact 候选不再被覆盖，7 例仍受算法/模型能力
限制。**
