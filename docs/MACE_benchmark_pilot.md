# MACE Benchmark Pilot：题库与独立评分机制

> **Status: Pilot only.** 本文的 5 道题参与过多轮协议审查，**不是全新独立测试
> 集**；其中的真实题是安全删除负例，不能外推为真实项目泛化能力。历史标签与
> 结论保持不变。v1 统一协议、公开/私有分离和新的盲测题见
> [MACE_benchmark_protocol_v1.md](MACE_benchmark_protocol_v1.md)。

日期：2026-11-01
分支：`benchmark-pilot`（从 `m7-feasibility` 的 `1b3fb72` 拉出）
范围：只构建题目与评分机制；不优化 MACE，不调用 Qwen，不训练，不重扫
site-packages，不运行 Direct/Full MACE。

## 0. 结论先行

本试点交付 5 道题：3 道受控题（独立掩盖、协同掩盖、回退/共存掩盖）+ 2 道真实
维护任务（pluggy 的两个真实删除 commit）。题库、执行真值、操作干预归因、独立
评分器、正/反例自检全部可复现。

**机制层面 GO，真实项目泛化层面 NO-GO。**

- GO：题目格式可执行、可冻结；评分不依赖人工写的 Guard 公式，而是重新执行
  P+/P− 与全部操作禁用组合；在**受控题**上 A（删除风险）、B（掩盖操作/组合）、
  C（回归反例）、D（测试缺口）四个维度都能由执行证据判定；真实题的 A/C/D 同样
  可执行判定，B 只能记为 `unconfirmed`（没有可安全干预的操作）。自检能抓住故意
  破坏的提交。
- NO-GO：真实题只有 2 道，来自同一个仓库，且都是“完全冗余”删除；其中
  `real_setdiff` 的 A 连局部值都不改变（退化），`real_formatdef` 的掩盖机制是
  外层 `%s` 隐式转换，没有可安全干预的独立操作，因果归因只能记为
  `unconfirmed`。因此当前真实题**不足以**支撑“真实项目中存在可发现的行为掩盖”
  这一论文主张，也不能把受控题成绩外推为真实项目泛化。

若要把本机制扩成 ICPC 论文数据集，建议把它定位为“受控掩盖基准 + 诚实的真实题
来源集/负结果”，并先满足第 6 节的扩展门槛；不要把它包装成真实项目泛化基准。

## 1. 是否构建了 3 道受控题 + 2 道真实题？

是。`benchmark_pilot/tasks.json` 的 5 个 `task_id`：

| 题 | 类型 | 结构 | 冻结域 | 掩盖 / 暴露 | A 有局部效应且被掩盖 |
|---|---|---|---|---|---|
| `ctrl_01` | 受控 | 独立掩盖：B 单独覆盖 A | 6 | 3 / 3 | 3 |
| `ctrl_02` | 受控 | 协同掩盖：C、D 单独都不够，合起来才够 | 24 | 5 / 19 | 5 |
| `ctrl_03` | 受控 | 回退/共存：B、E 各自掩盖，C&D 协同 | 20 | 14 / 6 | 14 |
| `real_formatdef` | 真实 | pluggy `0999f64a8c`，删除 `str()` | 8 | 8 / 0 | 8 |
| `real_setdiff` | 真实 | pluggy `98f1b58bf3`，删除 `set()` | 6 | 6 / 0 | 0（退化） |

受控题都满足“至少一个输入上 A 确实改变局部状态、但最终行为被掩盖”，不是
“A 什么都不做”的退化题。真实题按规范保留完全冗余与退化案例，并明确标注。

按四幕故事对照：三道受控题都完整覆盖第一幕（怀疑 A）、第二幕（删除后测试仍
通过）、第三幕（其他合法输入上暴露出差异）、第四幕（安全条件/掩盖者/测试缺口/
反例）；两道真实题只覆盖第一、二幕，第三幕**没有发生**——它们属于“删除确实安全”
的负例（`real_formatdef` 的 `%s` 对所有输入都吸收，`real_setdiff` 的 A 无局部
效应），不能算作“真实项目中的隐藏删除风险”正例。

## 2. 每道题的 A 为什么被选中？是否符合“怀疑冗余”的故事？

### ctrl_01：独立掩盖

```python
def program(mode, x):
    v = x
    v = v + 1  # TARGET_A
    if mode == 0:  # OP_B
        v = x
    return v
```

A 是 `v = v + 1`，开发者的怀疑是“下游 `mode == 0` 分支会覆盖 v，因此这一行可能
冗余”。这是最基础的删除安全场景：B 单独、且只需 B 就能吸收 A。域为
`mode ∈ {0,1}, x ∈ {0,1,2}`；`mode == 0` 时 P+ 被 B 重写为 `x`，与 P− 相同。
A 在局部确实把 v 从 x 变成 x+1，因此不是空操作。

现有测试只调用 `mode == 0`（`t_mode0_x0`、`t_mode0_x1`），正好全部落在被掩盖的
输入上，所以测试全绿而没有区分力。这就是“为什么现有测试没暴露风险”的可执行
证据。

### ctrl_02：协同掩盖

```python
def program(x, c, d):
    v = x
    v = v + 6  # TARGET_A
    if c == 0:  # OP_C
        v = v // 6 * 6
    if d == 0:  # OP_D
        v = v // 7 * 7
    return v
```

A 是 `v = v + 6`。单独的向下取整都不足以在冻结域上吸收 +6：

- 只启用 C：P+ 对 x=1..6 得到 6,6,6,6,6,12；P− 得到 0,0,0,0,0,6，全部不同；
- 只启用 D：P+ 得到 7,7,7,7,7,7；P− 得到 0,0,0,0,0,0，全部不同；
- C 与 D 同时启用：x=1..5 时两边都被压到 0，只有 x=6 暴露。

因此极小 absorber 集合是 `{C, D}`，kind=`cooperative`。这题专门验证评分器不会
把“C 或 D 单独”误判为掩盖来源，也不会把最终输出相同当成某个单操作的功劳。

现有测试 `t_rounds_x3`、`t_rounds_x5` 都取 `c=d=0` 且 x=3/5，全部落在被掩盖的
5 个输入里，故测试通过但没有覆盖 x=6 或任一取整分支单独启用的情形。

### ctrl_03：多重回退 / 共存掩盖

```python
def program(p, q, x, c, d):
    v = x
    v = v + 4  # TARGET_A
    if p == 0:  # OP_B
        v = x
    if q == 0:  # OP_E
        v = x
    if d == 0:  # OP_D
        v = v // 3 * 3
    if c == 0:  # OP_C
        v = v // 7 * 7
    return v
```

A 是 `v = v + 4`。冻结域是 5 种控制制度的并集（每种 4 个 x=3,4,5,6）：

| 制度 | 参数 | 结果 |
|---|---|---|
| B only | `p=0,q=1,c=1,d=1` | B 单独掩盖（4/4） |
| E only | `p=1,q=0,c=1,d=1` | E 单独掩盖（4/4） |
| B&E | `p=0,q=0,c=1,d=1` | B、E 各自掩盖；同时存在 |
| C&D | `p=1,q=1,c=0,d=0` | x=3,4 掩盖；x=5,6 暴露 |
| none | `p=1,q=1,c=1,d=1` | 全部暴露 |

得到 absorber 集合 `{B}`（independent）、`{E}`（independent）、`{C,D}`
（cooperative）；coexisting 集合 `{B,E}`：在 B&E 输入上，只禁用 B 时 E 仍掩盖，
只禁用 E 时 B 仍掩盖，同时禁用才暴露。这验证了“多个回退源同时存在时，只关掉
一个并不能暴露 A，必须测试共存来源”的要求。

域是**出题前**冻结的制度并集，不是看到结果后为了凑标签而缩域；完整笛卡尔积会
产生“B 与 C&D 同时启用”等混合制度，使归因退化为组合噪声，因此设计时排除了
这些制度。这一限制写在题面 `input_domain.note` 与 README 中。

现有测试 `t_b_only`、`t_e_only`、`t_coop`、`t_both_overwrite` 分别覆盖 B only、
E only、C&D（x=4）、B&E，全部是掩盖输入；没有任何测试覆盖 none 制度或 C&D 的
x=5/6，因此测试全绿。

### real_formatdef：pluggy 真实删除 `str()`

- 仓库：`https://github.com/pytest-dev/pluggy`，MIT。
- commit：`0999f64a8c2ab7c7d968ab2e8c8849629a6d891c`（2020-06-26，
  “Remove redundant str() in _formatdef”，作者 Ran Benita）。
- parent：`6011c43de0a1ba729e950f066a44ea8932cecb05`。
- 位置：`src/pluggy/manager.py:364`。
- 删除：`"%s%s" % (func.__name__, str(inspect.signature(func)))`
  → `"%s%s" % (func.__name__, inspect.signature(func))`。
- 为什么选它：提交消息本身就是“redundant”，是开发者自己的怀疑，不是重建的
  故事；一行删除、测试不变、纯 Python、测试可运行。
- 环境：Python 3.11.7 / pytest 7.4.0 / Windows 11；parent 与 child 上
  `PYTHONPATH=src python -m pytest testing -q` 均为 **79 passed**（日志见
  `benchmark_pilot/logs/real_formatdef_parent_pytest.log` 与
  `real_formatdef_child_commit_pytest.log`）。

执行结果：8/8 输入被掩盖；A 在每个输入上都改变中间值类型（`str` vs
`inspect.Signature`），但外层 `%s` 把两者格式化成同一字符串。因此这是“局部有
效应、最终被隐式转换吸收”的真实案例。归因状态是 `unconfirmed`：吸收者是外层
`%s` 格式化，不是一个可以安全开关的独立操作，无法做因果干预。

现有测试 `testing/test_helpers.py::test_formatdef` 覆盖 function1–4；两版都通过
且可观察量相同，gold verdict 为 `masked`。

### real_setdiff：pluggy 真实删除内层 `set()`

- commit：`98f1b58bf3650e529373dbcc203fcca9619637ec`（2020-06-29，
  “Remove redundant set() on dict keys view”，正文：
  “A dict keys view supports set-like operations.”）。
- parent：`656bc3d04d3b452d501cfd955c53c5e724a61bc5`。
- 位置：`src/pluggy/hooks.py:251`。
- 删除：`set(self.spec.argnames) - set(kwargs.keys())`
  → `set(self.spec.argnames) - kwargs.keys()`。
- 为什么选它：提交正文直接给出了冗余理由；这是开发者显式判断，而不是事后
  构造的“疑似冗余”。
- 测试：parent 与 child 上完整套件均 **79 passed**（日志见
  `real_setdiff_parent_pytest.log`、`real_setdiff_child_pytest.log`）。

执行结果：6/6 输入被掩盖，但 A **没有局部效应**：`set(declared) - set(keys)`
与 `set(declared) - keys` 的值和类型都相同。这是规范要求保留的“完全冗余/
退化”真实案例，不能用来论证掩盖。归因状态 `no_masking_relation`。

现有测试没有直接调用 `_HookCaller.__call__` 且传入缺失参数，因此 gold verdict
是 `not_covered`，而不是“测试通过”。

## 3. 评分器能否在没有 AI 主观判断的情况下检查删除风险 / Guard？

能，但要说清楚“能检查什么”：

1. **执行真值。** `engine.py` 独立于 `mace`，不 import 被评测引擎。它在冻结
   输入域上实际运行 P+ 与 P−，把返回值或异常规范化为可比较的观察值
   （`bool` 与 `int` 区分；异常按类型+消息记录）。
2. **Guard 只做语法白名单 + 逐输入求值。** 提交表达式只允许整数/布尔参数、
   常量、`and/or/not`、算术与比较；函数调用、属性、下标、未知名字全部拒绝。
   评分器给出 `sound`（没有假阳性）、`complete`（没有假阴性）、`exact`，
   并列出每个假阳/假阴输入。
3. **不拿人工 Guard 当标准答案。** 构建脚本里有一个私有设计 Guard，但它只用
   来自检“设计与执行是否一致”，评分器从不读取它；评分器的 gold 是执行矩阵。
4. **状态语义。** `BOUNDED` 只对冻结域成立；`PROVEN` 必须附假设与形式证明，
   但评分器明确标记 `proof_machine_checked=false`、`proof_review_required=true`
   ——有限枚举永远不会被写成全输入证明；`UNKNOWN/INVALID` 只有不给表达式时
   才是合法弃权。
5. **可复现。** `scripts/pilot_evaluate.py` 每次评分都重新执行 P+/P−、重新生成
   干预矩阵、重跑现有测试，并核对 `oracle.json`/`attribution.json`（逐输入
   观察、局部效应、测试结果与逐题归因）；漂移会抛 `ScorerError`，不会静默
   沿用旧标签。

边界：这是**有界执行判定**，不是定理证明；它不能证明“所有合法输入都不受影响”。
真实题的输入域是有限代表集，题面已标注这一点。

## 4. 受控题能否准确判断独立 / 协同 / 回退掩盖？

能，且评分器不是只比对一个最终 Guard，而是逐条验证提交声明的因果见证：

- **独立**：集合大小必须为 1；只启用该操作时该输入被掩盖，全部禁用时暴露。
- **协同**：集合大小 ≥2；每个单操作启用都不掩盖，全部启用才掩盖。
- **回退/共存**：集合大小 ≥2；只启用该集合时掩盖，禁用其中任何非空真子集仍
  掩盖，全部禁用才暴露。

实际结果：

| 题 | 提交应命中的集合 | 评分器验证 |
|---|---|---|
| ctrl_01 | `{B}` independent，witness `case_0000`（mode=0,x=0） | 通过 |
| ctrl_02 | `{C,D}` cooperative，witness `case_0000`（x=1,c=d=0） | 通过；`{C}`、`{D}` 单操作被拒 |
| ctrl_03 | `{B}`、`{E}` independent；`{C,D}` cooperative；`{B,E}` coexisting，witness `case_0008` | 通过；漏掉 `{B,E}` 会被记为 `missed_coexisting_relations` |

自检里的 `sabotaged` 提交故意把 ctrl_02 写成 `{C}`、把 ctrl_03 的 coexisting
清空，评分器分别报出 precision/recall 下降与漏报，说明它确实在检验组合关系，
而不是只看“最终输出相同”。

一个重要的**否定性保证**：评分器不会因为“某个操作在最终输出上无关”就把它当成
掩盖者。Score D 还要求提交为被掩盖的测试命名的操作集合确实是极小 absorber
集合，或者该集合包含一个极小 absorber 且其中每个操作单独都能掩盖；乱报
`B,C` 这类混入不相关操作的组合会被 `named_ops_valid=false` 拒绝。

## 5. 真实题中哪些掩盖原因被确认，哪些未确认？

| 题 | 状态 | 确认/未确认的原因 |
|---|---|---|
| `real_formatdef` | `unconfirmed` | 观察到吸收者是外层 `%s` 把 `str(signature)` 与 `Signature` 格式化成同一字符串；但没有一个可安全开关的独立操作，无法做因果干预，故不声称“某操作 B 掩盖了 A”。 |
| `real_setdiff` | `no_masking_relation` | A 连局部值都不改变（集合差值与类型均相同），不存在需要归因的掩盖关系；这是完全冗余退化案例。 |

规范允许真实题“完全冗余”或“无法确认掩盖”，本试点如实保留，没有为了凑“已确认
掩盖”而伪造操作或把最终输出相同说成因果掩盖。

## 6. 是否值得扩展成 ICPC 论文数据集？

**分两层回答。**

### 6.1 机制：GO

理由：

1. 题目格式完整（program / target_A / deletion / existing_tests / input_domain /
   observable / provenance），且 P+ 与 P− 都可执行。
2. 评分器完全由执行驱动，能抓假阳性、假阴性、无效见证、漏报的共存关系、
   伪造的“无反例”声明。评分器自检共 27 条：21 条是正例一致性检查（由同一
   执行真值构造，属于自洽性 fixture，不是独立答案），6 条是故意破坏检查；
   27 条全部通过。
3. 评分与出题分离：公开题面不含操作角色；oracle/attribution 只在评分侧使用；
   评分器重新执行而不是读取人工公式。
4. 它能回答评审最关心的问题：删除后是否真的改变可观察行为、是哪个操作/组合
   吸收的、现有测试为什么没发现、是否存在有效回归输入。

### 6.2 真实项目数据：当前 NO-GO

理由：

1. 只有 2 道真实题，且来自**同一个仓库**（pluggy），多样性不足。
2. 两道都是完全冗余删除；`real_setdiff` 还是退化（A 无局部效应）。没有一道
   真实题存在“已确认的掩盖操作/组合”。
3. 真实题的因果归因不可做：没有可安全干预的独立操作，只能记为 `unconfirmed`。
4. 候选筛选的失败率很高：在 jinja、packaging、click、requests、pip、pluggy 中
   只留下 2 个合格的真实删除；另外 6 个候选被拒（第 8 节表格 5 个，另加一个
   方法删除案例）。这说明“真实项目中的条件掩盖删除”供给很小，不是靠再扫
   一遍就能补足。
5. 真实题的测试覆盖也不理想：`real_setdiff` 根本没有测试覆盖被删除表达式所在
   路径，只能记 `not_covered`。
6. **筛选口径与故事错位。** 两道真实题都是从“提交信息自称 redundant”的删除里
   筛出的；这类提交本身就是开发者已判断、且测试确认安全的删除，天然偏向故事的
   负例（删除确实安全）。故事第三幕“测试绿、但别的合法输入暴露”在真实历史里更
   可能表现为“一次清理提交后来被回退/修复”，而不是 commit 自称 redundant。按
   `redundant` 关键词筛选会系统性漏掉正例。要挖真实正例，应改为从“回退/回归
   修复提交向前追溯被删代码”入手。

### 6.3 若要规模化，先满足这些门槛

- 至少 10 道真实题，来自 ≥5 个独立项目；
- 每题有可运行的原始测试、固定 commit、许可与日志；
- 至少 5 题有非退化的 A（局部有真实效应），并且其中至少 3 题能做安全操作干预、
  得到确认的 independent/cooperative/coexisting 归因；
- 受控题与真实题分开汇总，禁止相加；
- 冻结输入域后再评分，禁止为了让某方法通过而事后缩域；
- 若门槛达不到，论文应写成“受控基准 + 真实供给负结果”，而不是“真实项目
  泛化基准”。

## 7. 缺陷、局限与残余风险

1. **出题者偏差。** 5 道题与操作角色由本项目设计；评分器能验证提交与执行矩阵
   是否一致，但不能独立“发现”操作角色。它降低的是评分主观性，不是出题主观性。
2. **同一实现来源。** 构建脚本与评分器共用 `engine.py`（源码变换、观察值规范化）。
   评分器会重新执行并核对，避免读取旧标签，但无法完全排除执行原语的共同缺陷。
   若要发表，建议再用一份独立实现（例如直接用 `subprocess` 跑两份源码）做交叉
   验证。
3. **有界结论。** 所有 Guard 结论都只对冻结有限域成立；`BOUNDED` 不是证明。
4. **受控题域很小。** 6/24/20 个输入足以验证评分逻辑，但不足以估计方法在自然
   输入分布上的错误率。
5. **真实题退化。** 一道真实题的 A 没有局部效应；另一道的掩盖是隐式格式化，
   没有可干预操作。真实题只能验证来源、执行真值与流程，不能验证因果归因。
6. **测试环境单一。** 只在 Python 3.11.7 / pytest 7.4.0 / Windows 11 上跑过；
   `real_setdiff` 的 79 passed 是仓库整体套件，不是针对该表达式的测试。
7. **没有方法实验。** 本阶段没有运行 Direct Qwen、Full MACE、Pure Symbolic 或
   新 MACE；因此不能给出任何方法优劣、成本或 UNKNOWN 比例结论。
8. **`perfect` 查表 Guard 的误读风险。** 自检里的 perfect 提交用逐输入析取式，
   只是评分器自洽性 fixture，绝不是专家标注，也不是语义参考答案。
9. **`PROVEN` 无法机器检查。** 评分器只能检查是否附了假设与证明文本，不能验证
   证明正确性；这类提交仍需人工复核。
10. **域外的“无反例”声明。** `none_exists` 只对冻结域负责；真实题的有限代表集
    不能推出全输入域不存在反例。

## 8. 被拒绝的真实候选及原因

按“不得编造、不得把模拟案例冒充真实案例”的要求，以下候选全部保留记录：

| 候选 | 日期 | 变更 | 拒绝原因 |
|---|---|---|---|
| `pallets/jinja 76402dccca` | 2014-06-06 | `jinja2/filters.py` 删除 `result = []` | A 是死局部变量，无任何可观察差异；且 2014 版测试在 Python 3.11 + 当前 MarkupSafe 下无法启动（`ImportError: cannot import name 'soft_unicode'`），不能复现“项目原始测试”的证据。 |
| `pypa/packaging 4221ba034e` | 2022-12-08 | `DEFAULT_RULES` 删除 `"LPAREN"` 条目 | 模块级常量表的一项，不是函数内可执行操作序列中的语句；没有公共可观察行为变化，无法写成有运行时观察的 P+/P−。 |
| `pallets/click 94f17e276f` | 2026-08-31 | `_winconsole` 删除 `GetCommandLineW` 与 `STDIN/OUT/ERR_FILENO` | 模块级绑定/常量，Windows 控制台专用路径；项目测试不覆盖这些名字的行为，无法建立可执行的可观察差异，也不是单一操作 A。 |
| `psf/requests 28da72b616` | 2018-06-26 | 删除 `tests/test_requests.py` 中的未用 session 变量 | 改动只在测试文件里，不改变库的行为；没有“删除库代码 A”的双版本程序，不能作为维护任务。 |
| `pypa/pip 32b8a797cb` | 2018-10-02 | `except Exception as e:` → `except Exception:` | 删除的是异常绑定而不是可影响后续值的操作；没有可观察行为路径，且 pip 测试环境依赖重、不适合作为最小真实题。 |

另：`pytest-dev/pluggy 92e72be06e` 删除的是方法 `setmyprocessor`，不是赋值/表达式
操作，且同时删除其测试，无法构成“A 被其他操作掩盖”的题面，故未采用。

## 9. 复现与产物

```bash
python scripts/pilot_build.py
python scripts/pilot_evaluate.py --self-test
python scripts/pilot_evaluate.py --submission benchmark_pilot/submissions/perfect.json \
  --out benchmark_pilot/submissions/perfect_report.json \
  --log benchmark_pilot/logs/perfect_eval.log
python -m pytest
```

产物：

- 题库：[benchmark_pilot/tasks.json](../benchmark_pilot/tasks.json)
- 执行真值：[benchmark_pilot/oracle.json](../benchmark_pilot/oracle.json)
- 归因：[benchmark_pilot/attribution.json](../benchmark_pilot/attribution.json)
- 评分器：[scripts/pilot_evaluate.py](../scripts/pilot_evaluate.py)
- 构建器：[scripts/pilot_build.py](../scripts/pilot_build.py)
- 评分测试：[tests/test_pilot_evaluate.py](../tests/test_pilot_evaluate.py)
- 原始日志：[benchmark_pilot/logs/](../benchmark_pilot/logs/)
- 正/反例提交与报告：[benchmark_pilot/submissions/](../benchmark_pilot/submissions/)

加入 blind 协议完整性测试后的完整回归：`python -m pytest` → **182 collected，
exit 0**（日志 `benchmark_blind_v1/logs/pytest.log`）。Pilot 阶段的历史回归为
**175 passed**（日志 `benchmark_pilot/logs/pytest_all.log`），未改写。评分器
自检 27 条 PASS（日志 `benchmark_pilot/logs/self_test.log`）。
