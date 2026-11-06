# MACE Benchmark V4 数据集建设协议

- 版本：`v4.1-dev-2026-11-04`（v4.0 → v4.1：新增 §3.1 退化掩盖排除；
  AC1–AC12 不变，判定更严。变更记录见 §9）
- 状态：**协议冻结中（DEV 可用，HELDOUT 未开封）**
- 适用范围：本目录 `benchmark_v4_dataset/` 下的全部题目、候选、证据与统计。
- 与 V3 的关系：V3 冻结包只读、只作回归与格式参考；V4 不修改、不覆盖、不重新解释 V3
  的任何题目、HIDDEN 答案或评分器。

---

## 0. 目标与非目标

### 0.1 目标

1. 扩大真实开源项目题目数量。
2. 为每道题找到真实的单语句删除场景与目标操作 A。
3. 区分并记录独立、协同、后备/共存语义掩盖。
4. 建立 MSMS / MMBS 标准答案与可复现执行证据。
5. 分析原始测试、合法输入与删除风险。
6. 建立 **V4-DEV** 与 **V4-HELDOUT** 两个互不泄漏的集合。
7. 完成独立验收、统计与文档。

### 0.2 非目标（本会话不做）

- 不修改 MACE 核心算法、Graph 搜索器、Qwen Prompt 或模型接口。
- 不做算法优化、消融或基线调参。
- 不修改 V3 冻结数据、HIDDEN 答案、评分器。
- **不为了增加题目数量降低本协议 §3 的任何验收条件。**
- 不把候选、探针行、输入数或操作关系数当作题目数。

---

## 1. 术语与计数口径

| 术语 | 定义 |
|---|---|
| 题目（task） | 通过 §3 全部验收条件、并完成独立验收的一条记录 |
| 目标操作 A | 真实源码中的单条语句；删除方式为替换为等缩进 `pass  # P-: target A deleted`，行号保持不变 |
| 候选全集 U | 与 A 同一语义位置上、可独立启用/禁用的有限操作集合；**不是**全代码库操作 |
| P+ / P− | 原源码 / 删除 A 后的源码 |
| 声明的有限输入 | `task.json` 中列出的合法输入；每题独立冻结 |
| 暴露 witness | 某输入上 P+ 与 P− 的可观察结果不同 |
| 掩盖 witness | 某输入上 P+ 与 P− 的可观察结果相同，且存在非空 `S ⊆ U` 使“删除 A 且禁用 S”恢复相同 |
| MSMS | 最小充分掩盖集：`S` 能恢复相等，且 `S` 的任意真子集不能 |
| MMBS | 最小破坏集：`S` 能恢复相等，且禁用 `S` 后再次暴露（即 `S` 是必要集合） |
| 独立验收 | 不复用构造代码的重新实现：自己的项目副本、删除、probe、子集枚举、pytest 调用 |

**四类数量必须分开报告，禁止互相替代：**

1. 题目数；
2. 原始测试数 `T_task`；
3. 声明输入数 / 搜索输入数；
4. 操作关系数（EXPOSING / MSMS / MMBS / PREREQUISITE_BREAKING claim）。

---

## 2. 语义类别

每道题必须且只能归入以下一类；分类由**原始测试级**执行结果决定，
witness 级结果不能单独升级类别。

| 类别 | 判定 |
|---|---|
| `FULL_MASKING_STORY` | ≥1 条原始测试在 P− 下仍通过，且其输入上 P+ = P− 并存在 MSMS；同时存在合法暴露 witness |
| `ASSERTION_GAP_STORY` | 没有原始测试满足 `FULL_MASKING_STORY`，但 ≥1 条原始测试对 A 相关值只做了弱断言（删除后断言仍通过），且存在掩盖 witness |
| `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED` | 原始测试在 P− 下通过，但没有任何原始测试输入能建立掩盖关系；掩盖只在额外 witness 输入上成立 |
| `REJECT_*` | 不满足 §3；按拒绝原因编码（见 §5） |

`INCONCLUSIVE` 不是类别，是状态：证据不足，不得计入任何一类题目。

---

## 3. 验收条件（全部满足才算题目）

| ID | 条件 | 证据要求 |
|---|---|---|
| AC1 | 真实上游源码，A 为单条可定位语句 | sdist/tarball URL、版本、源码 SHA-256、文件:行、原始行文本 |
| AC2 | 合法输入契约明确、有限、可执行 | `task.json` 的 `legal_input_contract` + 冻结输入列表 |
| AC3 | A 在 P+ 的原始测试执行路径上确实执行 | `sys.settrace` 逐行证据 + JUnit |
| AC4 | 原始适用测试套件在 P− 下通过 | 完整 P− JUnit / log；排除项必须逐条记录 |
| AC5 | 存在合法暴露 witness | P+ / P− 观察值逐字记录，可执行 |
| AC6 | 存在掩盖 witness 与至少一个非空 MSMS | 子集枚举记录；P+ = P−；禁用 S 后恢复相等 |
| AC7 | MSMS / MMBS 在声明的 U 上严格最小 | 枚举 U 的**全部**子集；真子集检查；记录 `FINITE_DOMAIN_EXACT` 或 `WITNESS_VERIFIED` |
| AC8 | 至少一条 MMBS 或前置关系有控制输入 | 控制输入上同一集合不成立；或明确标注无前置关系 |
| AC9 | 独立验收通过 | 独立重实现报告；不得调用构造代码 |
| AC10 | 声明的测试集必须是**原始测试** | `DESIGNED` 测试只能作补充证据，不能作为 AC4 的声明测试集 |
| AC11 | 类别、范围、未声明项完整 | `story`、`scope`、`not_claimed` 字段 |
| AC12 | 统计与证据路径登记 | `registry/accepted.json`、`evidence/<task_id>/` |

**任何一条不满足 → 最多是候选，不是题目。**

### 3.1 退化掩盖排除（v4.1，DEV 校准）

形式上的 MSMS 存在**不足以**成为题目。若 `P+ = P−` 只是因为该输入不触发 A 的
效果（A 的产物在该输入上本就不可观察），而所保留的 `S` 与 A 的效果无关
（禁用 `S` 只是改变观察本身），则判 `REJECT_NO_MASKING_RELATION`，不得计为题目。

判定为“真实掩盖”必须至少满足下列一条：

1. **同值重算**：`S` 中某操作在同一路径上重新计算 A 所写的值（可为 A 之前或之后）；
2. **替代路径**：`S` 中某操作是 A 的 fallback / alternative path，且产生等价状态；
3. **协同重建**：`S` 中 ≥2 个操作联合重建 A 的效果，且缺一不可。

只有 1/2/3 至少一条成立，才允许声明 MSMS；否则按退化掩盖拒绝并记录理由。
该规则只提高标准，不放宽 AC1–AC12，也不改变任何已验收题目。

禁止事项：

- 禁止用“测试在 P− 下通过”直接推出“存在掩盖关系”；
- 禁止把 `MASKED_EFFECT` 测试数当作题目数；
- 禁止把 `U` 中的操作数当作关系数；
- 禁止把单元素 MSMS 称为协同掩蔽；
- 禁止对 HELDOUT 题目做任何结果驱动的重筛、改 U、改输入、改测试。

---

## 4. DEV / HELDOUT 分离

### 4.1 划分单位

**以项目（project + version）为单位划分，不按候选划分。**
同一项目的所有候选只能属于 DEV 或 HELDOUT 之一，避免同源泄漏。

### 4.2 V4-DEV

- 已在本会话之前检查过的项目；
- 允许反复筛选、构造、调试、修改候选；
- 允许用于校准筛选规则与验收工具；
- 题目状态标记 `DEV`，不得用于泛化声明。

当前 DEV 项目（见 `split/projects.json`）：

- click 8.4.1
- itsdangerous 2.0.1
- packaging 23.1
- pyparsing 3.0.9
- six 1.16.0

V3 的 Jinja2 3.1.3、Werkzeug 2.2.3 只作**回归参考**，不计入 V4 题目数。

### 4.3 V4-HELDOUT

- 项目列表、版本、sdist URL 与 SHA-256 必须在**任何候选检查之前**写入
  `split/projects.json` 并封存到 `split/seal.json`；
- 封存后只允许运行一次预先声明的流水线；
- 允许的运行结果包括拒绝；**所有结果必须登记，不能只保留通过的**；
- 封存后禁止：改项目列表、改版本、改筛选规则、改 U 构造规则、改输入生成规则；
- HELDOUT 题目在最终发布前对算法开发者不可见。

当前 HELDOUT 项目（8 个，待下载与封存）：

- markupsafe、filelock、platformdirs、sortedcontainers、chardet、idna、tomli、wcwidth

### 4.4 泄漏检查

- HELDOUT 项目的源码、测试、候选不得进入 DEV 的任何 prompt、输入网格或筛选缓存；
- 运行 HELDOUT 时使用独立工作目录与独立 venv；
- 发布前运行 `tools/check_leak.py`（待实现）比对 DEV 与 HELDOUT 的文件哈希。

---

## 5. 候选状态机

| 状态 | 含义 | 可升级到 |
|---|---|---|
| `STATIC_CANDIDATE` | 静态发现，尚未执行 | `SCREENED_*` |
| `SCREENED_REJECT_DEAD_BEFORE_READ` | 删除后是死存储 | 终止 |
| `SCREENED_REJECT_NO_A_EXECUTION` | 无原始测试执行 A | 终止 |
| `SCREENED_REJECT_TEST_DETECTS_DELETION` | 原始测试在 P− 下失败 | 终止 |
| `SCREENED_SURVIVOR` | 原始套件在 P− 下通过 | `MASKING_CANDIDATE` / `REJECT_NO_MASKING` |
| `MASKING_CANDIDATE` | 找到掩盖 witness | `ELIGIBLE_EVIDENCE_PENDING` |
| `ELIGIBLE_EVIDENCE_PENDING` | 还缺 MSMS/MMBS/独立验收 | `ACCEPTED_DEV` / `ACCEPTED_HELDOUT` |
| `DESIGNED_TESTS_ONLY` | 只有自建测试，无原始测试存活 | 终止（可作补充证据） |
| `REJECT_NO_EXPOSING_INPUT` | 无合法暴露反例 | 终止 |
| `REJECT_NO_MASKING_RELATION` | 无掩盖关系 | 终止 |
| `REJECT_NO_LOCAL_EFFECT` | 删除 A 不改变任何观察 | 终止 |
| `REJECT_NOT_MINIMAL` | 存在更小的有效集合 | 终止 |
| `INCONCLUSIVE` | 证据不足或执行失败 | 重跑或终止 |
| `EVIDENCE_LOST` | 证据丢失，明确不可用 | 终止 |

状态记录在 `registry/candidates.json`；每次状态变化附证据路径与时间。

---

## 6. 任务包格式

通过 AC1–AC12 后，在 `tasks/<task_id>/` 生成：

```
task.json           # 公开：项目、A、合法输入契约、原始测试、观察契约
reference.json      # 隐藏：U、witness、MSMS/MMBS、参考 claim、scope
provenance.json     # sdist URL、SHA-256、源码文件哈希、构建命令
evidence/           # P+ / P− JUnit、trace、子集枚举、probe 输出
acceptance/         # 独立验收报告与原始日志
```

`task_id` 命名：`<project>_<function>_<short_operation>`，全小写、下划线。

---

## 7. 统计规则

`stats/dataset_stats.json` 必须分开记录：

- `tasks_total`、`tasks_by_story`、`tasks_by_split`；
- `original_tests_total`（仅 `T_task`）；
- `declared_inputs_total`、`search_inputs_total`；
- `operations_total`（U 的大小之和）；
- `claims_total`、`claims_by_type`；
- `msms_sets_total`、`mmbs_sets_total`、`multi_element_msms_total`；
- `independent_acceptance_passed`；
- `rejected_candidates_by_reason`；
- `evidence_lost`、`inconclusive`。

禁止在文档中把上述任一数字简写成“题数”。

---

## 8. 冻结与变更控制

- 协议版本改变必须新增版本号，不覆盖旧版本。
- 已验收题目的 A、U、输入、测试、MSMS/MMBS 不得因模型分数而修改。
- 任何更正必须以 `corrections/<date>-<id>.json` 记录，并保留旧证据。
- HELDOUT 解封只能由用户明确授权；解封记录写入 `split/seal.json` 的 `unsealed` 字段。

---

## 9. 变更记录

| 版本 | 日期 | 变更 | 影响 |
|---|---|---|---|
| v4.0-dev | 2026-11-04 | 初版 | — |
| v4.1-dev | 2026-11-04 | 新增 §3.1 退化掩盖排除 | 仅收紧判定；AC1–AC12 文本未变；已验收的 `tabulate_numparses_header_wrap` 满足同值重算，结论不变 |
