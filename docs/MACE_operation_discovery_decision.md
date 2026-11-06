# MACE 操作级掩盖关系自动发现：最小实验决策（2026-11-02）

本文件回答任务五的六个问题。实验范围仅限已有开发控制题与三个既有真实源码题，不新增真实题，不减少原测试，不修改 M1–M6 历史结果。

## 0. 本轮实际做了什么

新增/扩展的代码：

- `open_ops/discover.py`
  - 保留原 `discover()` 的顶层反向切片基线；
  - 新增 `discover_expanded()`：把 `if` 整体作为操作单元，支持条件体内的赋值、覆盖写、`self.x` / `obj.attr` / `obj[key]` 的间接状态写，以及 `append/update/add/...` 等原地修改方法；
  - 每个候选记录稳定 `key`、源码行/列、`reads`、`writes`、`provenance`、`control_reads`；
  - 关系记录新增 `evidence`：P+、P− 的实际观测，禁用声明集合后的观测，禁用其他候选后的观测，proper-subset 最小性结果；
  - 区分 `VERIFIED`、`WITNESS_ONLY`、`FALSE`、`INVALID`、`UNVERIFIED`、`UNSUPPORTED`、`UNKNOWN`；
  - 对循环、`try/with`、提前返回、嵌套定义、跨函数/方法体等结构返回 `UNSUPPORTED`，不再把“没搜到”写成“不存在”。
- `open_ops/contracts.py`
  - 只读取已有 Full MACE bundle 的 `target_effects` / `upstream` / `observers` / `mask_guard` 中的 `source_lines`，作为候选提议；
  - 合同行本身不确认任何关系，确认只由执行验证器完成；
  - 没有记录 bundle 的任务明确标记为不可用，不伪造合同。
- `open_ops/run_development.py`
  - A 臂：无合同候选 + 独立验证；
  - B 臂：同样的候选上限与子集执行预算 + 合同行提示；
  - 结果写入 `open_ops/out/development.json` 与 `open_ops/out/development.log`。
- `tests/test_open_ops_contracts.py`
  - 9 条回归测试，覆盖扩展候选、C 控制 B 的反例、三类关系、合同无增益、真实题 UNSUPPORTED、状态分类、冻结分类、可评分提交。

本轮没有调用任何模型：`model_calls=0`，`model_tokens=0`。

## 1. MACE 是否能够自动提出源码操作集合？

**不能，至少现有 Full MACE 合同不能。**

- 现有 MACE bundle 的确能给出 `source_lines`，但在开发题上这些行要么就是 A 本身，要么已经被确定性扩展 AST 候选覆盖；B 臂没有增加任何候选，也没有新增任何已验证关系。
- 真正能自动提出操作集合的是 `open_ops` 的确定性原型，不是 MACE。该原型使用 AST 写集合、控制条件读取、覆盖写和间接状态写生成候选，再执行子集矩阵。
- 因此不能把本轮的候选生成能力记作“MACE 的新算法能力”。它是“MACE 合同辅助候选 + 确定性执行验证”的一次对照，且对照结果为无增益。

## 2. 各类操作关系能否通过独立验证？

在开发集上可以：

| 关系 | 开发案例 | 结果 |
|---|---|---|
| independent | `ctrl_01` 行 4 | `VERIFIED`，条件 `(mode < 1)` |
| cooperative | `ctrl_02` 行 4+6 | `VERIFIED`，两个 proper subset 单独都不掩盖 |
| independent | `ctrl_03` 行 4、行 6 | 两个 `VERIFIED` |
| cooperative | `ctrl_03` 行 8+10 | `VERIFIED`，行 8 或行 10 单独都不掩盖 |
| coexisting | `ctrl_03` 行 4+6 | `VERIFIED`，两条后备路径必须同时禁用才暴露 A |
| independent | C 改状态、B 受控 | 行 5 `VERIFIED`；行 4 被识别为 B 的控制前置，不作为竞争掩盖者 |
| independent（真实源码） | Werkzeug `url_unparse` 行 57 | witness 通过独立验证，但条件 `UNKNOWN`，只报 `WITNESS_ONLY` |

独立验证有两层：

1. `discover_expanded()` 内部的 P+/P− 子集矩阵；
2. `run_development._independent_verifier()` 用 `benchmark_pilot/verifier_v2.py` 重新建立矩阵并逐关系验证。

开发题的两层结果一致，`all_verified=True`。真实 `url_unparse` 的 witness 也通过 `verifier_v2`，`scope=single_witness`，没有被说成全局证明。

**但“单个 witness 成立”不等于“整个 condition 正确”。** 真实 `url_unparse` 的输入是 5 元字符串元组，现有条件语言只支持整数/布尔原子，无法表达条件，因此：

- 关系状态：`WITNESS_ONLY`；
- 条件状态：`UNKNOWN`（底层 `condition_check.status=ABSENT`，表示现有条件语言无法表达）；
- 输出 `condition=None`，不伪造 Guard。

## 3. 与不使用 MACE 合同的确定性基线相比，是否有新增的有效发现？

**没有。**

- `ctrl_01/02/03` 与反例题的 A/B 两臂候选数完全相同，候选集合相同，子集执行预算相同。
- 已验证关系集合完全相同。
- `new_verified_relations_from_contract` 均为空。
- `contract_only_candidates_used_by_verified_relation` 均为空。
- `contract_semantic_gain=false`。

合同唯一实际发生的作用是：`ctrl_01` 的合同行 4、`ctrl_02` 的合同行 4/5 被映射到已有候选，属于重复提议；`ctrl_03` 的合同只引用 A 所在行，过滤后没有可用提议。

## 4. 增益是否来自现有语义合同，而不是更多枚举或更大预算？

**本轮没有观察到任何来自合同的增益。**

为了排除“靠更多枚举/更大预算赢”的解释，B 臂被强制限制为与 A 臂相同的候选数；候选数相同意味着子集矩阵行数相同，程序执行预算也相同。实际执行次数：

- 总程序执行：5360 次（两臂 + 独立验证器）；
- 总墙钟时间：约 0.68 秒（CPU，本机）；
- 模型调用：0；Token：0；
- 独立验证矩阵错误：无（所有 `errors` 为空）。

因此本轮不存在“合同带来语义增量”的证据，也不存在“靠更大计算预算取得增益”的证据。

| 任务 | A 臂候选/关系 | A 臂程序执行 | 状态 |
|---|---|---|---|
| `ctrl_01` | 1 / 1 | 48 | OK |
| `ctrl_02` | 2 / 1 | 384 | OK |
| `ctrl_03` | 4 / 4 | 1280 | OK |
| `control_state_C_changes_state_B_controlled` | 2 / 1 | 72 | OK |
| `real_werkzeug_url_unparse` | 6 / 1 | 792 | PARTIAL（`WITNESS_ONLY`） |
| `real_werkzeug_headerset_update` | 3 / 0 | 80 | UNSUPPORTED |
| `real_click_truncate_visible` | 1 / 0 | 24 | UNSUPPORTED |

B 臂在开发题上的候选数、关系数、执行次数与 A 臂相同；真实题没有可用合同，B 臂与 A 臂相同。

## 5. 哪些程序结构仍不支持？

明确返回 `UNSUPPORTED` 或无法表达条件的结构：

- 循环：`for` / `while`（`real_click_truncate_visible` 的掩盖写在 `while` 内，返回 `UNSUPPORTED`）；
- `try` / `except` / `finally` / `with`；
- 提前返回、多个顶层返回、返回值不是单一最终 `return`；
- 嵌套函数/类定义；
- 跨函数或跨方法体的状态影响：例如 `real_werkzeug_headerset_update` 的掩盖写在 `HeaderSet.update()` 内部，入口函数只调用 `hs.update(...)`，本轮返回 `UNSUPPORTED`（记录了 `cross-function method effect`）；
- 目标 A 不是单行简单赋值；
- 候选数超过 `MAX_CANDIDATES=12`；
- 条件涉及非整数/布尔输入（如字符串元组、列表、对象），只能给 witness，不能给条件；
- 异常只作为“返回/抛出”的观测，不建模异常传播细节、别名分析、容器元素级别名、生成器/异步、装饰器改变行为等；
- “控制前置”只按语法识别（候选写入了被声明集合的 `if` 条件所读取的变量，并传递闭包），不建模数据前置、别名，也不处理“前置操作本身也掩盖 A”的情况；这类情况可能把 cooperative 误判/漏判，需要后续用依赖图修正。

一个重要限制：扩展候选目前是“A 之后所有受支持的写语句”，并没有做精确的 live-variable 反向切片。这样做提高了召回，但也放大了候选数；一旦超过 12 个候选就直接 `UNSUPPORTED`，而不是静默截断。

## 6. 是否值得继续构建复杂真实 Benchmark？

**不建议继续按“证明 MACE 合同能自动发现操作关系”的方向扩建真实 Benchmark。建议 STOP 这条路线，保留验证器与确定性原型作为小型评测工具。**

理由：

1. 本轮所有有效发现都来自确定性 AST + 执行矩阵，合同没有带来新增候选或新增关系；
2. 真实源码上唯一发现的关系是 `url_unparse` 行 57，且只能给 witness，不能给条件；
3. 另外两个真实题的关键掩盖结构分别在循环内和方法体内，当前实现直接 `UNSUPPORTED`，继续加题只会重复暴露同一结构缺口；
4. 在没有合同增益的前提下扩建真实题，会把“枚举 + 执行验证”的成本误记成“MACE 的能力”。

如果继续，优先级应是：

1. 先补结构支持（方法体提取、循环体的操作单元化、跨函数 effect 摘要），而不是加题；
2. 把 `open_ops` 定位为“操作级掩盖关系的可执行验证器/回归工具”，而不是 MACE 算法贡献；
3. 只有在合同能提出确定性候选没有提出的、且执行验证通过的操作集合时，才重新讨论 MACE 的语义增量；
4. 真实题继续保留现有分类：`real_click_truncate_visible` 属于 `TEST_SURVIVING_DELETION`；`real_werkzeug_headerset_update` 与 `real_werkzeug_url_unparse` 属于 `VERIFIED_MASKING_ONLY`。本轮没有把第二类写成第一类。

## 7. 状态与证据口径

关系状态：

- `VERIFIED`：witness 执行检查通过，且条件在有限合法域上精确；
- `WITNESS_ONLY`：witness 执行检查通过，但条件缺失、不完整或不健全；
- `FALSE`：关系在命名 witness 上不成立；
- `INVALID`：条件语言非法；
- `UNVERIFIED`：执行无法判定该 witness；
- `UNSUPPORTED`：程序结构或候选规模超出支持范围；
- `UNKNOWN`：在受支持结构内没有关系满足 witness 与最小性检查。

本轮实际输出的关系状态只有 `VERIFIED` 与 `WITNESS_ONLY`；结果状态出现 `OK`、`PARTIAL`、`UNSUPPORTED`、`UNKNOWN`。`FALSE` / `INVALID` / `UNVERIFIED` 的判定函数已实现并有单元测试，但本轮没有被提议为最终关系的组合触发。

每条关系的 `evidence` 至少包含：

- witness 案例与合法输入；
- P+ 与 P− 的观测（返回值或异常类型/消息）；
- A 在删除前后的局部快照是否存在；
- 禁用声明操作集合后的 P+/P− 观测；
- 禁用其他掩盖候选（保留控制前置）后的观测；
- proper-subset 的最小性结果及每个子集实际禁用的 key。

`cooperative` 与 `coexisting` 的证据语义不同：

- `cooperative`：声明集合整体掩盖，禁用整组暴露；每个 proper subset 单独都不掩盖；
- `coexisting`：声明集合整体禁用才暴露；每个 proper subset 单独禁用都不暴露。

## 8. 原始记录

- `open_ops/out/development.json`：完整候选、关系、evidence、合同元数据、预算与统计；
- `open_ops/out/development.log`：逐题一行摘要；
- `benchmark_real_pilot/protocol_v2/real_case_classification.json`：真实案例的两类用途冻结登记；
- `docs/MACE_experiment_freeze_2026-11-02.md`：冻结资产清单。

复现命令：

```bash
python open_ops/run_development.py
python -m pytest tests/test_open_ops_contracts.py tests/test_open_ops_discovery.py \
  tests/test_verifier_v2.py tests/test_pilot_evaluate.py \
  tests/test_benchmark_test_protocol_v2.py -q
```

本轮相关测试结果：73 条通过（新增 9 条 + 原相关测试 64 条）。
