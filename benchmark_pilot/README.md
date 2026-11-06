# MACE Benchmark Pilot

> **Status: Pilot only.** 本目录的 5 道题（`ctrl_01/02/03`、
> `real_formatdef`、`real_setdiff`）参与过多轮协议审查，**不是全新独立测试集**，
> 不能作为 v1 盲测结果或真实项目泛化证据。历史数据、提交记录与标签保持不变。
> 新的冻结题面与盲测见
> [docs/MACE_benchmark_protocol_v1.md](../docs/MACE_benchmark_protocol_v1.md)
> 和 `benchmark_blind_v1/`。

本目录是 MACE 研究的**题库与独立评分机制**试点，不是 MACE 算法本身。

目标：验证“开发者怀疑某段代码 A 冗余、准备删除它”这一任务能否被表述成可执行、
可冻结、可由第三方评分器独立判定的题目；并验证评分器能否区分

- 独立掩盖（一个操作 B 单独就能掩盖 A）；
- 协同掩盖（C、D 单独都不够，合起来才掩盖 A）；
- 回退/共存掩盖（B 与 E 各自掩盖；同时存在时只关掉一个并不会暴露 A）；
- 真实维护任务中的删除风险、现有测试为何没发现、以及是否存在回归反例。

本阶段**没有**调用 Qwen、没有训练、没有修改 MACE Prompt、没有运行 Direct/Full
MACE、没有重新扫描 site-packages。这里的所有标签都由实际执行 P+/P− 与操作
干预变体得到，不依赖人工写的 Guard 公式。

## 目录

```
benchmark_pilot/
  specs.py            公开题目元数据（受控题源码、域、测试、真实题来源）
  private/controlled.py  受控题的操作角色（私有，不进入 tasks.json）
  generators.py       输入域生成器（可执行、可复现）
  engine.py           执行原语：源码变换、P+/P− 执行、观察值规范化、Guard AST 白名单
  real_tasks.py       真实题输入构造与局部效应检查
  tasks.json          5 道公开题（程序、目标 A、删除、现有测试、输入域、观察、来源）
  oracle.json         逐输入的 P+/P− 观察、相等性、局部效应（BOUNDED，非证明）
  attribution.json    操作干预矩阵得到的 absorber/coexisting 归因与真实题归因
  submissions/        self-test 生成的正例/反例提交及其评分报告
  logs/               构建、pytest、评分、真实仓库测试的原始日志
  README.md           本文件
scripts/
  pilot_build.py      从 specs + 执行结果生成 tasks/oracle/attribution
  pilot_evaluate.py   独立评分器（A/B/C/D）与 self-test
tests/
  test_pilot_evaluate.py  题库结构、泄漏、执行漂移、评分语义的回归测试
docs/
  MACE_benchmark_pilot.md  方法、逐题证据、局限与 GO/NO-GO
```

`tasks.json` 是公开信息；`oracle.json` 与 `attribution.json` 是评分器私有的
真值材料。被评测方法只能读 `tasks.json`。

## 快速复现

```bash
# 1. 重建题库与执行真值（需要 Python 3.11，不联网）
python scripts/pilot_build.py

# 2. 评分器自检：生成正例/反例并检查 27 条判定
python scripts/pilot_evaluate.py --self-test

# 3. 对任意提交评分
python scripts/pilot_evaluate.py \
  --submission benchmark_pilot/submissions/perfect.json \
  --out benchmark_pilot/submissions/perfect_report.json \
  --log benchmark_pilot/logs/perfect_eval.log

# 4. 全部回归测试（含 M1–M6 既有测试）
python -m pytest
```

构建脚本会重新执行所有 P+/P−、全部操作禁用组合、以及现有测试，任何题面/标签
不一致都会直接报错，而不是静默覆盖。

## 题目格式（`tasks.json` 的每个 `tasks[i]`）

| 字段 | 含义 |
|---|---|
| `task_id` | 题目 ID；`ctrl_*` 受控，`real_*` 真实维护任务 |
| `kind` | `controlled` / `real` |
| `entry` | 可执行入口函数名（全部为 `program`） |
| `program.source` | P+ 源码；包含唯一的 `# TARGET_A` 行 |
| `program.target_A` | 目标操作的行号、文本、种类（assignment/call） |
| `deletion.kind` | 受控题为 `delete_statement`；真实题为 `reverse_commit_patch` |
| `deletion.diff` | 明确的一行删除/替换规则 |
| `deletion.p_minus_source` | 删除 A 后的 P− 源码 |
| `existing_tests` | 原测试源码 + 在原程序上的实际 +/− 结果 |
| `input_domain` | 冻结的有限输入集及其生成器；真实题明确标注“有限代表集，不是全输入域” |
| `observable_behavior` | 可观察量：返回值，异常也作为一种观察 |
| `why_suspected_redundant` | 不含操作角色的“开发者为什么怀疑冗余”叙述 |
| `provenance` | 真实题的仓库、MIT 许可、commit/parent、日期、消息、作者、路径行号、diff、环境与测试日志 |

受控题的 `# OP_X` 注释在构建时被剥除，公开题面只保留 A 的标记与普通代码；
操作角色、absorber 集合、coexisting 集合、私有设计 Guard 只在
`private/controlled.py` 与 `attribution.json` 中。

## 提交格式

评分器接受如下 JSON（见 `submissions/perfect.json`）：

```json
{
  "submissions": [
    {
      "task_id": "ctrl_02",
      "guard": {"expr": "x >= 1 and x <= 5 and c == 0 and d == 0",
                "status": "BOUNDED"},
      "masking": {
        "absorber_sets": [
          {"ops": ["C", "D"], "kind": "cooperative",
           "witness": {"case_id": "case_0000"}}
        ],
        "coexisting": []
      },
      "witnesses": [{"case_id": "case_0001"}],
      "witness_claim": "exists",
      "test_gap": {
        "verdict": "masked",
        "tests": [{"name": "t_rounds_x3", "verdict": "masked",
                   "masking_ops": ["C", "D"]}]
      }
    }
  ]
}
```

- `guard.expr` 只允许整数/布尔参数、常量、`and/or/not`、算术、比较；函数调用、
  属性、下标、未知名字一律拒绝，防止提交代码在评分器里执行。
- `guard.status` ∈ `BOUNDED | PROVEN | UNKNOWN | INVALID`。
  - `BOUNDED`：只在冻结输入域上成立，评分器接受并给出 sound/complete/exact。
  - `PROVEN`：必须同时给 `assumptions` 与非空 `formal_proof`；评分器**无法机器
    检查证明**，因此只标记“需人工复核”，有限枚举永远不算证明。
  - `UNKNOWN/INVALID`：只有**不给表达式**时才是合法弃权；同时给表达式视为
    状态不一致。
- `witness` 可用 `case_id`，也可直接给参数（受控题按规范化参数匹配）。
- `witness_claim` ∈ `exists | none_exists | none_found`；声称 `none_exists` 会被
  执行结果直接反驳或确认。
- 受控题的 `masking.absorber_sets` 指“只启用该集合、禁用其余全部可控制操作时
  足以掩盖 A”的极小集合；`kind` 为 `independent`（大小 1）或 `cooperative`
  （大小 ≥2）。`coexisting` 指“在已掩盖输入上同时禁用该集合会暴露 A，而禁用
  任何真子集仍掩盖”的极小集合。

## 评分语义

**A. 删除风险 / Guard。** 在冻结输入域上执行 P+ 与 P−，按题面指定的可观察量
比较；把提交表达式逐输入求值，报告：

- `false_accept`（表达式为真但实际未掩盖）→ soundness 失败；
- `false_reject`（表达式为假但实际掩盖）→ completeness 失败；
- `sound` / `complete` / `exact`；
- 所有结果都带 `evidence_level: BOUNDED`，不会把有限枚举写成全输入证明。

**B. 掩盖操作与组合。** 只对受控题启用。评分器重新执行全部“禁用若干操作”的
配对变体，逐条验证提交声明的 witness：

- `independent`：恰好一个操作；只启用它时掩盖，全部禁用时暴露；
- `cooperative`：≥2 个操作；每个单操作启用都不掩盖，全部启用才掩盖；
- `coexisting`：≥2 个操作；只启用该集合时掩盖，禁用其中任何非空真子集仍掩盖，
  全部禁用才暴露。

同时报告集合的 precision/recall/exact、被判错/漏报的集合、kind 准确率、
evidence 准确率与漏掉的 coexisting 关系。真实题没有可安全干预的操作，
`applicable=false`，只记录归因状态（不伪造因果）。

**C. 回归反例。** 对提交的每个输入实际运行 P+/P−，只有可观察量真的不同才算
有效反例；异常也是可观察量。区分：

- 声称有反例但全部无效（`invalid_witnesses_only` /
  `claimed_exists_without_valid_witness`）；
- 声称 `none_exists` 但实际存在（`wrong_none_exists_claim`）；
- 实际不存在且明确声称（`correctly_none_exists`）才得分；沉默不给满分。

**D. 现有测试为什么没发现。** 评分器重新运行原测试，并在测试输入上执行 P+/P−：

- 测试在 P+ 或 P− 上直接失败 → `test_broken`；
- 两版测试结果不同 → `would_be_caught`；
- 两版都通过但输出不同 → `assertion_gap`；
- 两版都通过且输出相同 → `masked`；
- 没有测试覆盖该路径 → `not_covered`。

对声明为 `masked` 的测试，还要求提交命名的操作集合确实在相关路径上：集合必须是
一个极小 absorber 集合，或者包含一个极小 absorber 且其中每个操作单独都能掩盖；
仅凭最终输出相同而乱报操作不得分。评分器同时报告 `named_ops_valid` 与
`named_ops_minimal`。

受控题与真实题在 `summary` 中**分开汇总**，并显式注明不得把两者相加冒充
“真实项目泛化能力”。

## oracle 与 attribution 的定位

- `oracle.json`：逐输入的 P+/P− 观察值、是否相等、A 是否有局部效应、现有测试的
  实际结果。`evidence_level=BOUNDED`；它是对冻结域的穷举记录，不是形式证明。
- `attribution.json`：对受控题，记录全部禁用子集的配对执行结果所导出的极小
  absorber 集合与 coexisting 集合，以及每条集合的见证输入；对真实题，记录
  `masking.status`（`unconfirmed` / `no_masking_relation`）与原因。
- 评分器在加载时会重新执行并核对上述文件；任何漂移都会抛 `ScorerError`，
  防止“改了题面却继续用旧标签”。

## 自检

`--self-test` 用评分器自身构造两个提交：

- `perfect`：逐输入查表式 Guard + 实际执行得到的集合与见证；
- `sabotaged`：改错 Guard、把协同集合写成单操作、漏掉 coexisting、给真实题
  伪造无效反例、改错测试归因。

自检检查“正例全对、反例被抓”，并输出 27 条 PASS/FAIL：其中 21 条是正例
一致性检查（用同一份执行真值构造，属于自洽性 fixture），6 条是故意破坏检查。
注意：`perfect` 的
查表 Guard 只是**评分器自洽性 fixture**，不是语义参考答案，也不能当作人工标注
或专家真值。

## 环境

- Python 3.11.7，pytest 7.4.0，Windows 11。
- 受控题与真实题提取程序均为纯标准库，不联网。
- 真实题原始仓库的测试在各自 parent/child 版本上运行，命令与结果记录在
  `tasks.json.provenance.existing_tests` 与 `logs/`。

## 已知限制

1. 受控题的输入域是人工冻结的有限集合；`BOUNDED` 只对该集合成立。
2. `ctrl_03` 的域被限定为 5 种控制制度（B only / E only / B&E / C&D / none）
   的并集，这是**出题前**的设计决定，不是看到结果后缩小域；目的是避免
   “B 与 C&D 同时启用”这类混合制度把归因问题变成组合爆炸。
3. 两道真实题都是**完全冗余**的删除：`real_formatdef` 的 A 改变中间值类型但被
   外层 `%s` 吸收；`real_setdiff` 的 A 连局部值都不改变（退化案例）。它们只
   覆盖“怀疑冗余→删除→测试仍通过”的前两幕，第三幕（其他合法输入暴露差异）
   没有发生，属于安全删除的**负例**，不能用来声称“发现了真实项目中的掩盖”。
   另外，用 `redundant` 关键词筛选提交会系统性偏向这类安全删除；真实正例应从
   回退/回归修复提交向前追溯。
4. 真实题没有可安全干预的独立操作，因果归因记录为 `unconfirmed`；不得把
   “最终输出相同”直接当成“某个操作 B 掩盖了 A”。
5. 本试点没有运行任何 MACE / LLM 方法；它只冻结题目与评分机制，不能给出
   方法优劣结论。
