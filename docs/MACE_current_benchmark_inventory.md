# MACE 当前 Benchmark 题目库存审计（只读）

- 审计日期：2026-11-04
- 审计方式：只读取已冻结产物与已有运行记录；**未重跑探针、未重新筛题、未修改代码、未修改 HIDDEN/冻结数据/评分规则**。
- 审计对象：`benchmark_real_v3`（冻结发布）、`runs/v3_m1_screening`（协作掩蔽筛选）、
  `benchmark_pilot`（受控合成题）、`benchmark_real_v4`（设计候选）、
  `runs/v3_live_qwen` / `runs/v3_full_mace_30min`（基线对比）。
- 计数口径在全文严格区分：**题目数 / 原测试数 / 输入数 / 操作关系数**，互不替代。

---

## 0. 一句话结论

**当前真正冻结、可运行、可评分、且通过独立验收的真实项目题只有 5 道。**
其中只有 **2 道**（get_host、secure_filename）完整符合 `FULL_MASKING_STORY`；
**1 道**是 `ASSERTION_GAP_STORY`；**2 道**只能算 `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`。
**协作掩蔽（M1）已确认题目为 0 道**：515 个已选目标中只探针了 336 个，
46 个 `MASKED_FULL` 都还只是候选，13 个进入子集矩阵的目标全部未产出合格多元素最小集。
**独立测试集数量为 0**：5 道题全部标记 `DEV_TUNED`，`generalization_claim_permitted=false`。

---

## 1. v3 冻结题逐题账本

冻结版本：`v3.0-dev-pilot-2026-11-02`，标签 `DEVELOPMENT/PILOT`，
bundle SHA-256 `470f32fa7efd9a2db4e5ee203b4a374db93da4c907876c923f09dd07b49b80d3`。

### 1.1 逐题表

| task_id | 项目 / 函数 | 目标操作 A | 题目完整 | 合法暴露反例 | 真实掩蔽证据 | 操作关系（U / 参考 claim） | MSMS 最小性 | MMBS 最小性 | Direct Qwen | Graph-only | Full MACE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `jinja2_bytecode_cache_read` | Jinja2 3.1.3 / `BaseLoader.load` | [loaders.py:132](benchmark_real_v3/release/HIDDEN/tasks/jinja2_bytecode_cache_read/reference.json) `code = bucket.code` | 是（独立验收 PASS） | 是（1 个 witness 输入） | 仅 witness 级；**原始测试 0 条 masked** | U=1（`compile_fallback`）；1 EXPOSING + 1 MSMS + 1 MMBS | 是（有限全集枚举） | 是（有限全集枚举） | 已运行，credited 0 | 未运行 | 未运行（legacy 接口 UNSUPPORTED） |
| `werkzeug_bind_server_name_lower` | Werkzeug 2.2.3 / `Map.bind_to_environ` | [map.py:307](benchmark_real_v3/release/HIDDEN/tasks/werkzeug_bind_server_name_lower/reference.json) `server_name = server_name.lower()` | 是（独立验收 PASS） | 是（1 个 witness 输入） | 仅 witness 级；**原始测试 0 条 masked** | U=1（`bind_relower`）；1 EXPOSING + 1 MSMS + 1 MMBS + 1 PREREQUISITE_BREAKING | 是 | 是 | 已运行，credited 1 | 未运行 | 未运行 |
| `werkzeug_filestorage_stream_name` | Werkzeug 2.2.3 / `FileStorage.__init__` | [datastructures.py:2918](benchmark_real_v3/release/HIDDEN/tasks/werkzeug_filestorage_stream_name/reference.json) `filename = getattr(stream, "name", None)` | 是（独立验收 PASS） | 是（1 个 witness 输入） | witness 级是；原始测试 0 条 masked，另有 1 条 assertion gap | U=1（`special_name_reset`）；1 EXPOSING + 1 MSMS + 1 MMBS | 是 | 是 | 已运行，credited 1 | 已运行，credited 4 | 已运行，credited 4 |
| `werkzeug_get_host_default_empty` | Werkzeug 2.2.3 / `get_host` | [sansio/utils.py:82](benchmark_real_v3/release/HIDDEN/tasks/werkzeug_get_host_default_empty/reference.json) `host = ""` | 是（独立验收 PASS） | 是（1 个 witness 输入） | **118 条原始测试 masked** | U=2（`overwrite_host_header`, `overwrite_server`）；1 EXPOSING + 2 MSMS + 2 MMBS | 是 | 是 | 已运行，credited 0 | 已运行，credited 7 | 已运行，credited 7 |
| `werkzeug_secure_filename_ascii_filter` | Werkzeug 2.2.3 / `secure_filename` | [utils.py:222](benchmark_real_v3/release/HIDDEN/tasks/werkzeug_secure_filename_ascii_filter/reference.json) `filename = filename.encode("ascii", "ignore").decode("ascii")` | 是（独立验收 PASS） | 是（1 个 witness 输入） | **1 条原始测试 masked** | U=1（`sanitize_whitelist`）；1 EXPOSING + 1 MSMS + 1 MMBS | 是 | 是 | 已运行，credited 0 | 未运行 | 未运行 |

说明：

- “题目完整”指冻结题包含目标操作、P− 删除、合法输入契约、原测试、参考关系与评分入口；
  5/5 通过 `acceptance_v3.py` 的**独立重实现**验收（`accepted=5, needs_review=0`）。
- “真实掩蔽证据”分两层：**参考 witness 输入级**（5 道都有）与**原始测试级**
  （只有 get_host 118 条、secure 1 条；filestorage 0 条但有 1 条 assertion gap；
  jinja2/bind 0 条）。两层不能混为一谈。
- 所有 `MSMS` / `MMBS` 都是**单元素集合**，因此 v3 中没有任何协作（多元素）掩蔽关系。
- “未运行”一律表示**没有该方法的冻结运行结果**，不是该方法失败。

### 1.2 数量口径（五个不同的数）

| 口径 | 数量 | 证据 |
|---|---:|---|
| 题目数 | **5** | `benchmark_real_v3/release/PUBLIC/tasks/index.json` |
| 原始测试数 `T_task` | **138**（1 + 8 + 10 + 118 + 1） | 各题 `task.json` 的 `frozen_t_task_count` |
| HIDDEN 参考输入（witness）数 | **11**（2 + 2 + 2 + 3 + 2） | 各题 `reference.json` 的 `scope.inputs_executed`、`witnesses` |
| C 搜索输入网格 / 其中 masked | **34 / 26** | `docs/MACE_next_stage_research_readiness.md` §4.4 |
| 声明候选操作 `U` 总数 | **6**（1 + 1 + 1 + 2 + 1） | 各题 `candidate_universe` |
| 参考关系 claim 总数 | **18**（5 EXPOSING + 6 MSMS + 6 MMBS + 1 PREREQUISITE_BREAKING） | 各题 `reference_claims` |

C 的 34 个输入是**基线搜索网格**，不是 HIDDEN 的 11 个参考 witness；
两者不可互换，也不能把 34 当“题目输入数”。

### 1.3 四类 story 统计（仅 v3 的 5 道冻结真实题）

| 类别 | 题数 | task_id |
|---|---:|---|
| A `FULL_MASKING_STORY` | **2** | `werkzeug_get_host_default_empty`、`werkzeug_secure_filename_ascii_filter` |
| B `ASSERTION_GAP_STORY` | **1** | `werkzeug_filestorage_stream_name` |
| C `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED` | **2** | `jinja2_bytecode_cache_read`、`werkzeug_bind_server_name_lower` |
| D `INCONCLUSIVE / INVALID / 未完成` | **0** | — |
| **合计** | **5** | |

测试级汇总（同一 138 条原始测试的逐条执行结果）：

| 结果 | 条数 |
|---|---:|
| `MASKED_EFFECT` | **119**（118 + 1） |
| `NO_LOCAL_EFFECT` | **18**（1 + 8 + 9） |
| `ASSERTION_GAP` | **1** |
| `INCONCLUSIVE` | **0** |
| 未执行 | **0** |

注意：`MASKED_EFFECT` 119 条几乎全部来自 get_host 的 118 条；
“119 条 masked 测试”不等于“119 道题”，也不等于“119 条操作关系”。

### 1.4 独立验收

- 报告：`benchmark_real_v3/evidence/acceptance/acceptance_report.json`
- 方法：`Independent reimplementation: own project copies, own line deletion, own probe runner, own subset enumeration and own pytest invocation. No call to verify_task/variant_lab/run_suite.`
- 结果：`task_count=5, accepted=5, needs_review=0`
- 每题检查项全部为真：单行 diff、U 位置、A 在输入上确实执行、
  矩阵复现、最小性、题目特定检查；原始测试在 P+ 上全通过。
- 限制：只对**声明的有限输入 + 声明的 U** 成立，**没有任何 `PROVEN`**；
  5 道题全部 `DEV_TUNED`，`generalization_claim_permitted=false`
  （`runs/v3_baseline_freeze/manifest.json`）。

---

## 2. 协作掩蔽（M1）小账

证据根目录：`runs/v3_m1_screening/`

### 2.1 筛选漏斗（每一步都是不同对象，不能相加）

| 阶段 | 数量 | 文件 |
|---|---:|---|
| 静态枚举 | 14,083 | `static_candidates.json` |
| 实际人工/抽样复核 | **2,500** | `static_candidates.json` (`review_budget`) |
| 展开后的目标 | **4,501** | `screen/targets.json` |
| 其中 `U≥2` 的候选 | **1,396** | `screen/targets.json` (`eligible_u_ge_2`) |
| 选入探针 | **515** | `screen/selected.json` |
| 已探针 | **336** | `screen/probe.json` |
| 未探针 | **179** | 515 − 336 |

### 2.2 探针结果（336 行）

| 状态 | 行数 |
|---|---:|
| `EXPOSED` | 201 |
| `MASKED_FULL` | **46** |
| `NO_EXECUTION` | 36 |
| `NO_PASSING_TEST` | 32 |
| `NO_LOCAL_EFFECT` | 21 |

`MASKED_FULL` 46 行的构成：

| 子类 | 行数 |
|---|---:|
| 三态协议行 | 36 |
| `legacy_no_tri_state` 旧协议行 | 10 |

**46 是“候选目标行数”，不是 46 道题，也不是 46 个已确认协作掩蔽。**

### 2.3 子集矩阵（13 个目标进入）

| 状态 | 目标数 | 含义 |
|---|---:|---|
| `EVIDENCE_LOST` | 1 | 首次快速模式在 `qualified_sets` 过滤处崩溃，128 次评估丢失，**不算证据** |
| `STRUCTURAL_SKIP` | 8 | `U` 过大（8、8、11、12、13、15、33、37），被 `MAX_U=6` 跳过 |
| `SINGLE_OP_ONLY` | 2 | 实际只有一个单操作掩蔽者 |
| `NOT_M1_NO_INERT_MEMBER` | 2 | 有多元素集合，但没有“惰性成员”，不满足 M1 定义 |
| `CONFIRMED_M1_PENDING_FULL_SUITE` | **0** | — |
| **合计** | **13** | |

其它矩阵事实：

- `qualified_sets` 总数：**0**。
- 子集评估状态：**17 `OK` / 55 `INVALID`**（共 72 个评估单元，`INVALID` 指
  plus 运行失败，不能作为最小性证据）。
- 预算：211 / 250 次执行，运行被用户中止（`HALTED_BY_USER_FOR_30MIN_GPU_RUN`）。
- 46 个 `MASKED_FULL` 中，**33 个从未进入矩阵**（24 个三态行 + 9 个 legacy 行）；
  进入矩阵的 13 个也没有一个产出合格多元素最小集。
- 因此：**`CONFIRMED_M1 = 0`**；`scripts/m1_accept.py` 的五项检查没有任何输入。

### 2.4 协作掩蔽分项

| 项目 | 数量 |
|---|---:|
| 已确认 M1 协作题 | **0** |
| 仅单操作（`SINGLE_OP_ONLY`） | **2** |
| `MASKED_FULL` 候选但最小性未完成 | **46**（含 33 个未进矩阵） |
| 因 `U` 过大被跳过 | **8** |
| `UNKNOWN` / `EVIDENCE_BLOCKED` | **0** |
| `EVIDENCE_LOST` | **1**（128 次评估丢失） |
| `INVALID` 子集评估 | **55** |

结论：**当前没有可用的真实协作掩蔽题**。可用的协作掩蔽只存在于受控合成题
（见 §3 的 ctrl_02 / ctrl_03），且它们不是真实开源项目题。

---

## 3. 受控合成题（ctrl_01 / ctrl_02 / ctrl_03）

来源：`benchmark_pilot/tasks.json`、`oracle.json`、`attribution.json`。
证据等级：`BOUNDED`（对冻结有限域做完整枚举，不是证明；没有 `PROVEN`）。
**这三道是合成程序，不是真实开源项目题，不能与 v3 的 5 道混算。**

| 题目 | 操作 `U` | 定义域 | masked / exposed | 掩蔽结构 | 协作？ |
|---|---|---:|---|---|---|
| `ctrl_01` | 1（`B`） | 6 | 3 / 3 | `{B}` 独立吸收 | 否（单操作） |
| `ctrl_02` | 2（`C`,`D`） | 24 | 5 / 19 | `{C,D}` 协同；两者单独都不掩蔽 | **是**（5 个 case） |
| `ctrl_03` | 4（`B`,`C`,`D`,`E`） | 20 | 14 / 6 | `{B}`、`{E}` 独立；`{C,D}` 协同；`{B,E}` 共存 | **是**（2 个 case） |

- ctrl_03 的 14 个 masked case 中：12 个由单操作独立掩蔽，2 个由 `{C,D}` 协同掩蔽；
  `{B,E}` 是共存（coexisting）而不是协同。
- 设计自检（`design_guard_self_check.agrees_with_execution_on_all_cases=true`）
  只是私有构造检查，评分器不比较它。
- 独立验收：**无**。`benchmark_pilot` 的 oracle、attribution、评分器共享同一个
  `engine.py`，不是独立重实现。
- 评分可用性：有 `pilot_evaluate.py` 与 self-test 提交
  （`perfect_report.json` 三项 controlled 全 exact；`sabotaged_report.json`
  正确降级为 2/3、1/3、0.833），说明评分器能区分对错，但**不构成独立验证**。
- 与 Full MACE 的对比：`benchmark_blind_v1/executability/controlled_comparison.json`
  与 `benchmark_open_v1/interface/interface_summary.json` 显示
  **Full MACE 在 ctrl_01/02/03 上全部 `NO_RESULT`**（接口缺
  `relations[].operations` / `relations[].input`，`UNSUPPORTED`）；
  Direct Qwen 为 `GUARD_VERIFIED`（ctrl_01）或 `ROUNDS_EXHAUSTED`
  （ctrl_02/03），**关系数 0**。因此这三道题目前**不能用于 Full MACE 的有效对比**，
  只能用于“评分器/定义”层面的自测。

附带两道旧 pilot “真实”题，均**不合格**，不计入可用题：

| 题目 | 定义域 | masked | exposed | 结论 |
|---|---:|---:|---:|---|
| `real_formatdef` | 8 | 8 | **0** | 没有合法暴露反例；masking 状态 `unconfirmed` |
| `real_setdiff` | 6 | 6 | **0** | `masked_with_local_effect=0`，A 本身无局部效应，`no_masking_relation` |

---

## 4. v4 设计候选（不计入“已发布题目”）

`benchmark_real_v4/` 有 6 个 witness、5 个 `release_candidates`，全部
`promoted=true`，6 项条件在**自建 DESIGNED 测试**下全为 `true`：

| 候选 | 项目 | 文件:行 | 测试来源 | 状态 |
|---|---|---|---|---|
| `click-8.4.1:src/click/core.py:2482:value` | click | core.py:2482 | `DESIGNED` | 候选，未发布 |
| `click-8.4.1:src/click/core.py:3428:value` | click | core.py:3428 | `DESIGNED` | 候选，未发布 |
| `click-8.4.1:src/click/parser.py:63:args` | click | parser.py:63 | `DESIGNED` | 候选，未发布 |
| `pyparsing-3.0.9:pyparsing/core.py:3371:attribute:maxLen` | pyparsing | core.py:3371 | `DESIGNED` | 候选，未发布 |
| `pyparsing-3.0.9:pyparsing/core.py:823:tokens` | pyparsing | core.py:823 | `DESIGNED` | 候选，未发布 |

关键限制：

- `declared_test_set = DESIGNED`：测试是**我们自己为候选写的**，不是上游原始测试。
  因此“P− 下测试仍通过”在当前构造下不是独立证据，条件 2 的说服力有限。
- 没有 `PUBLIC` / `HIDDEN` 发布包，没有冻结 scorer，没有独立验收报告。
- 因此这 5 个只能算**候选**：可本地运行、暂不可评分、未独立验证。

---

## 5. 对比实验可用性

证据：`runs/v3_live_qwen/tasks/*/summary.json`、`runs/v3_full_mace_30min/tasks/*`。

| 方法 | 覆盖题数 | 具体 |
|---|---:|---|
| A Direct Qwen 32B | 5 / 5 | jinja2 0、bind 1、filestorage 1、get_host 0、secure 0（共 credited 2；15 条 claim） |
| B Qwen + Verifier | 5 / 5 | 与 A 相同的 credited：0 / 1 / 1 / 0 / 0 |
| C AST + 干预（C-fixed-1.1） | 5 / 5 | 4 / 4 / 4 / 7 / 4（共 **23** credited） |
| Graph-only | **2 / 5** | get_host 7、filestorage 4；jinja2/bind/secure 未运行 |
| Full MACE（Qwen 排序 + 图搜索 + 因果验证） | **2 / 5** | get_host 7、filestorage 4；与 Graph-only 逐关系相同，错误 0 |
| legacy Full MACE 接口 | 0 / 5 | 5 题全部 `UNSUPPORTED_INTERFACE` |

- **五方法齐全（A/B/C/Graph/Full）的题：2 道**（get_host、filestorage）。
- **至少 A/B/C 齐全的题：5 道。**
- Graph/Full 的 get_host 只覆盖 96 / 192 个子集（预算 16/输入），
  不能声称穷尽；filestorage 的 32/32 是完整的。
- Qwen 在 Full MACE 中没有带来净收益：关系集合与 Graph-only 相同，
  首 MSMS 5 个输入变慢、1 个略快、4 个持平。

---

## 6. 汇总表

| 题目类别 | 总数 | 可运行 | 可评分 | 独立验证完成 |
|---|---:|---:|---:|---:|
| v3 冻结真实题 | **5** | 5 | 5 | **5** |
| v4 设计候选 | 5 | 5 | **0** | **0** |
| 受控合成题（ctrl_01–03） | 3 | 3 | 3 | **0** |
| 旧 pilot 真实题（formatdef / setdiff） | 2 | 2 | 2 | **0**（且题目本身不合格） |
| M1 协作候选（探针行 / 候选 / 已确认） | 336 / 46 / **0** | — | — | **0** |
| 独立（held-out）题 | **0** | — | — | — |

“可评分”对 v4 记 0 是因为没有冻结 release/scoring 包；
对受控题与旧 pilot 记 3 / 2 是因为有本地评分器与 self-test，
但它们与构造共享 engine，不能算独立验证。

---

## 7. 直接回答五个问题

### (1) 有多少道可以直接用于算法开发？

- **真实项目题：5 道**（v3 全部通过独立验收，输入/评分/scorer 齐全）。
- 另有 **3 道受控合成题**可用于机制与评分器开发，但不能当作真实泛化证据。
- v4 的 5 个候选可以本地跑，但没有冻结发布包，不适合作为正式开发基准。

### (2) 有多少道可以用于公平对比实验？

- **A/B/C 三方法齐全：5 道。**
- **A/B/C + Graph-only + Full MACE 五方法齐全：2 道**
  （`werkzeug_get_host_default_empty`、`werkzeug_filestorage_stream_name`）。
- 受控题上 Full MACE 全部 `NO_RESULT`，**0 道**可用于 Full MACE 对比。

### (3) 有多少道真正符合完整 MACE story？

- **2 道**：`werkzeug_get_host_default_empty`、`werkzeug_secure_filename_ascii_filter`
  （`FULL_MASKING_STORY`，且有原始测试级 masked 证据）。
- `werkzeug_filestorage_stream_name` 是 `ASSERTION_GAP_STORY`（1 条断言缺口），
  不是完整 masking story。
- `jinja2` / `bind` 是 `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`：
  原始测试里 0 条 masked，掩蔽只在参考 witness 输入上成立。

### (4) 有多少道可以测试独立或协作掩蔽？

- **独立掩蔽**：v3 的 **5 道全部**（MSMS/MMBS 都是单元素集合）；
  受控题 ctrl_01、ctrl_03 也可测独立掩蔽。
- **协作掩蔽（真实项目）**：**0 道**。M1 筛选 0 个 `CONFIRMED_M1`。
- **协作掩蔽（合成）**：**2 道**（ctrl_02 的 `{C,D}`；ctrl_03 的 `{C,D}`），
  证据等级 `BOUNDED`，非真实项目、非独立验收。

### (5) 距离一个有说服力的独立测试集还有多远？

- 当前**独立（held-out）题目数 = 0**。
- 5 道 v3 题全部 `DEV_TUNED`，`generalization_claim_permitted=false`；
  它们参与过协议与基线调参，不能当 held-out。
- v4 的 5 个候选尚未发布/评分/独立验收；M1 的真实协作题仍为 0。
- 因此，现有资产足以支撑**开发集与机制验证**，但**不足以支撑独立测试集结论**。
  这是当前库存的硬边界，不是再跑一次筛题就能自动补上的数量问题。

---

## 8. 证据文件路径（逐题）

### v3 每题

- 公开题面：`benchmark_real_v3/release/PUBLIC/tasks/<task_id>/task.json`
- 隐藏参考：`benchmark_real_v3/release/HIDDEN/tasks/<task_id>/reference.json`
- 矩阵：`benchmark_real_v3/evidence/<task_id>_matrix.json`
- 独立验收矩阵：`benchmark_real_v3/release/HIDDEN/evidence/<task_id>_independent_matrix.json`
- P− 全量测试日志：`benchmark_real_v3/release/HIDDEN/evidence/<task_id>_p_minus_full.log`
- 目标执行日志：`benchmark_real_v3/release/HIDDEN/evidence/<task_id>_t_task.log`
- 独立验收：`benchmark_real_v3/evidence/acceptance/acceptance_report.json`
- 故事分类：`benchmark_real_v3/evidence/story_validation/story_validation.json`
- 资格与漏斗：`benchmark_real_v3/evidence/funnel_summary.json`、
  `benchmark_real_v3/evidence/qualification_registry.json`
- 冻结清单与 `DEV_TUNED`：`runs/v3_baseline_freeze/manifest.json`
- 发布清单与哈希：`benchmark_real_v3/release/MANIFEST.json`、
  `benchmark_real_v3/release/SHA256SUMS`

### M1 筛选

- `runs/v3_m1_screening/static_candidates.json`
- `runs/v3_m1_screening/screen/targets.json`
- `runs/v3_m1_screening/screen/selected.json`
- `runs/v3_m1_screening/screen/probe.json`
- `runs/v3_m1_screening/screen/matrix.json`
- `runs/v3_m1_screening/screen/matrix.checkpoint_halted.json`

### 受控题

- `benchmark_pilot/tasks.json`
- `benchmark_pilot/oracle.json`
- `benchmark_pilot/attribution.json`
- `benchmark_pilot/submissions/perfect_report.json`
- `benchmark_pilot/submissions/sabotaged_report.json`
- `benchmark_blind_v1/executability/controlled_comparison.json`
- `benchmark_open_v1/interface/interface_summary.json`

### v4 候选

- `benchmark_real_v4/release_candidates/*.json`
- `benchmark_real_v4/evidence/qualification_designed/*.json`
- `benchmark_real_v4/designed_tests/*.py`
- `benchmark_real_v4/evidence/witnesses/*`

### 基线对比

- `runs/v3_live_qwen/tasks/<task_id>/summary.json`
- `runs/v3_full_mace_30min/tasks/<task_id>/{graph_only,full_mace}_{submission,score}.json`
- `docs/MACE_30min_GPU_comparison.md`
- `docs/MACE_v3_live_qwen_baseline_results.md`

---

## 9. 未完成 / 无效项清单（避免把候选当题目）

| 项目 | 数量 | 为什么不计数 |
|---|---:|---|
| M1 已探针但未进矩阵的 `MASKED_FULL` | 24（三态）+ 9（legacy） | 没有完成最小性验证 |
| M1 进入矩阵但未确认 | 13 | 0 个 `qualified_sets`，0 个 `CONFIRMED_M1` |
| M1 `EVIDENCE_LOST` | 1 目标 / 128 次评估 | 崩溃丢失，明确“不算证据” |
| M1 `INVALID` 子集评估 | 55 | plus 侧运行失败 |
| v4 设计候选 | 5 | DESIGNED 测试、无发布/评分/独立验收 |
| 旧 pilot `real_formatdef` | 1 | 无暴露反例，masking `unconfirmed` |
| 旧 pilot `real_setdiff` | 1 | A 无局部效应，`no_masking_relation` |
| legacy Full MACE 接口 | 5 题 | `UNSUPPORTED_INTERFACE`，0 结果 |

**最终口径：可用真实题 5 道；完整 full-masking story 2 道；
可做五方法公平对比 2 道；已确认协作掩蔽 0 道；独立测试集 0 道。**
