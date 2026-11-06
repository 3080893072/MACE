# 论文研究可行性审查与下一阶段决策

日期：2026-10-31
范围：M1–M6 冻结后的真实案例可行性审查。本阶段**没有进行任何模型调用**，没有修改 M5/M6 的原始日志，也没有继续优化 MACE。

---

## 0. 决策摘要

**主结论：NO-GO。** 以现有数据，不足以支撑一篇有意义的 ICPC 负结果论文。

**条件性 GO。** 只有在完成第 8 节列出的四个前置闸门后，才可以把"有界 MACE / 符号条件推导在真实代码上失效"作为一个可发表的负结果；届时论文的贡献也应是"工具适用边界与失效分类"，而不是"LLM 不能做程序理解"。

一句话依据：

> 11 个 fixture 已被重新归类为开发/探索性案例；10 个真实案例虽然都有人工可验证的精确 guard（10/10），但自动方法只有纯符号 2/10 精确、有界归纳 1/10 精确，且这 2 个符号精确结果是对返回表达式的重述而不是紧凑语义条件；Direct 与 Full MACE 在真实案例上**完全未测量**。因此当前证据只能说明"这个原型在真实代码上覆盖很窄"，不能说明"以 LLM 为中心的条件合成在一般情况下失败"。

---

## 1. M1–M6 冻结状态

| 项目 | 值 |
|---|---|
| 冻结内容提交 | `94912c12466054dcfc809e3bf45224137501ad9b`（`94912c1`，M6 决策报告） |
| 冻结清单提交 / tag | `7b3d2f5`，tag `m1-m6-freeze` |
| 清单覆盖 | 364 个文件，SHA-256 逐一记录；`m6/freeze_manifest.json`、`docs/FREEZE_MANIFEST.md` |
| 冻结时工作区 | `dirty=false`（只统计已跟踪文件） |
| Python | CPython 3.11.7（Windows 11，x86-64） |
| 模型 | `qwen2.5-coder:32b`（Ollama），temperature 0，seed 42；M6 与本审查均无模型调用 |
| 数据划分种子 | fit/eval `20261030`，learn/tune `20261031` |
| 既有里程碑 tag | `m5-freeze`（`b4b0a90`）、`m6-induct-freeze`（`7599e20`） |

M6 的 held-out 归纳运行只执行了一次，绑定到实现 SHA-256
`7b514fda833186ebff50a87c0ce1b9a616819136a56e5739212dc99106875b54` 与
git HEAD `7599e20`；该运行与本次审查无关，未被重跑或改动。

**冻结后的改动（必须与 M6 数字区分）：**

* `mace/symbolic.py`：目标定位原先只接受 `ast.Assign`，现在接受
  `AugAssign`/`AnnAssign`。这是覆盖修复，不是调参；11 个 M6 fixture 的目标全是普通
  `Assign`，所以 M6 的所有数字不变。当前文件 SHA-256
  `3d4c440bb51cbe440c860b4386d5cb01baab4f484ba6219cb5fc819f4b33fd6a`。
* 新增 `scripts/build_realcases.py`、`scripts/screen_realcases.py`、
  `scripts/realcase_audit.py`、`realcases/`、本报告。它们不在冻结范围内。
* 审计运行时已跟踪工作区为 dirty（`mace/symbolic.py` 覆盖修复，以及 `README_MACE.md`、`tests/test_symbolic.py` 的本阶段更新）；冻结清单本身没有被重新生成，冻结提交没有被改写。

---

## 2. 四组方法及其严格的输入要求

| 输入 | Direct Qwen | Full MACE (A) | Pure Symbolic | Symbolic + 人工摘要 |
|---|---|---|---|---|
| 程序源码 P、目标行 A | 需要 | 需要 | 需要 | 需要 |
| 声明的有限输入域 | 需要（用于检查和逐轮反例） | 需要（用于检查、反例、拟合） | 推导不需要；最终判定需要 | 推导不需要；最终判定需要 |
| 变量/函数类型签名 | 需要 | 需要 | 需要（仅支持片段内） | 需要 |
| 类型化合同词汇与 schema | 不需要 | 需要 | 不需要 | 不需要 |
| 验证器反例反馈 | 需要（每轮） | 需要（每轮，驱动修复） | 不需要 | 不需要 |
| 人工撰写的 helper 摘要 | 不需要 | 不需要（Qwen 自己写） | 不允许 | **需要**（人工、已逐条验证） |
| LLM 调用 | 需要 | 需要 | 无 | 无 |
| 最终 guard 选择 | 最后一轮（M5 协议） | 最后一轮（M5 协议） | 路径析取 | 路径析取 + 摘要 |

关键约束：

* Direct 的输入不是"只有源码"。它每轮都会收到 P+/P− 的具体反例，因此不能把它描述成零反馈基线。
* Full MACE 的合同、观察者和 guard 全部由 Qwen 生成；M6 的在线保留策略不在本阶段真实案例上使用（没有模型调用）。
* Pure Symbolic 只对源码做路径枚举，不读有限域来选 guard；有限域只用于事后判定。
* **Symbolic + 人工摘要不是自动方法。** 它的 helper 语义是人写的、逐条验证过的；在 M6 中它得到 11/11，但这个数字只能作为上界/诊断，不能计入自动方法的成功（第 6 条要求的落实）。
* 全部判定都是有界的（`BOUNDED`/`TESTED`），任何情况下都不输出 `PROVEN`。

---

## 3. 11 个 fixture 的重新归类

`fixtures/` 与 `experiments/` 中的 11 个案例（6 dev + 3 held-out batch 1 + 2 held-out batch 2）是**开发与探索性研究案例**，不是新的独立评价集。理由：

* 它们从 M2 到 M6 被反复用于设计、调试和修复；held-out batch 1 在 M5 期间还用于诊断解析器缺陷（半 held-out）。
* M6 的 held-out 归纳虽然只跑了一次，但运行在 held-out batch 1+2 上，后者此前已用于 M5 评估，因此不是全新的独立样本。
* README 与 `docs/M6_decision.md` 中的数字继续有效，但只能作为"有界、探索性"证据引用。

M6 在 11 个案例上的结果（供对照，不重复作为新证据）：

| 方法 | exact | tokens | wall |
|---|---|---|---|
| Direct Qwen | 5/11 | 23,626 | 102 s |
| Full MACE (A) | 3/11 | 141,081 | 705 s |
| Pure Symbolic | 7/11（4 UNKNOWN） | 0 | 0.01 s |
| Symbolic + 人工 helper 摘要 | 11/11（不可计为自动成绩） | 0 | 0.02 s |
| 有界条件归纳，充分方向 | 10/11 | 0 | 25 s |
| 有界条件归纳，必要方向 | 0/11 | 0 | 25 s |

---

## 4. 真实案例的构建与初筛

### 4.1 数据来源

从本机已安装的开源 Python 包与 CPython 标准库中抽取函数。每个案例保留真实项目、版本、许可证与源码位置；只做四类可披露的抽取改动：去掉无运行时语义的装饰器、删除域内不可达分支、把模块常量内联、限制输入域（仅 `median_low` 限制为长度 2–3）。每个案例声明一个有限输入域，A 为一条被标记的赋值语句；P+ 为原程序，P− 把 A 替换为 `pass`。

10 个案例见 `realcases/cases.json`，程序在 `realcases/programs/`。人工 guard 只用于评分/校验，不进入任何自动方法。

### 4.2 筛选漏斗（可复现）

`scripts/screen_realcases.py` 逐级筛：

1. 已安装标准库与 site-packages 中的全部 `.py`；
2. 可被 Python 3.11 解析；
3. 顶层函数（2–20 条语句），去装饰器后重命名为 `program`，通过 `mace.program.validate_subset`；
4. 含"`If` 直属赋值"（目标为普通局部名，且不在循环内）；
5. 目标名在该赋值之前已有定义（删除 A 不会直接 `NameError`）；
6. 附加统计：所有参数都带 `int`/`bool`/`list[int]` 注解。**这不是 10 个案例的来源**——真实函数大多没有类型注解，10 个案例的参数类型是人工阅读代码后确定的。该计数用来说明"即使通过语法子集，自动建域仍需要人工类型判断"。

本次实测计数：

| 阶段 | 计数 |
|---|---|
| 扫描文件 | 38,170 |
| 可解析 | 38,162 |
| 顶层函数（2–20 条语句） | 74,413 |
| 通过 MACE 语法子集（含同模块 helper 闭包） | 1,966 |
| 条件赋值候选 | 186 |
| 目标有前置定义 | 135 |
| 参数带可识别类型注解（附加统计） | 10 |

通过语法子集的函数只占顶层函数的 **2.6%**；再要求"条件赋值 + 目标有前置定义"后只剩 **135** 个；其中带可自动识别类型注解的只有 **10** 个。10 个案例正是从这 135 个里**人工挑选**的（参数类型由人工阅读确定，不依赖注解）：优先选择语义机制不同、P+/P− 差异真实、guard 可人工紧凑表述的案例。因此 10 个案例不是随机样本，不能用比例外推。

### 4.3 十个案例

| # | 案例 | 项目 / 版本 | 源码位置 | 目标 A | 域大小 | 掩盖机制 |
|---|---|---|---|---|---|---|
| 1 | `cpython_leapdays` | CPython 3.11.7 | `Lib/calendar.py::leapdays` | `y1 -= 1` | 55 | 整除边界位移 |
| 2 | `babel_cldr_modulo` | Babel 2.11.0 | `babel/plural.py::cldr_modulo` | `a *= -1` | 95 | 负数取模的符号恢复；半模数被吸收 |
| 3 | `fpdf2_int32` | fpdf2 2.8.7 | `fpdf/encryption.py::int32` | `n = n & 0xFFFFFFFF` | 11 | 32 位恒等窗口 |
| 4 | `fonttools_flagbest_xsame` | fontTools 4.63.0 | `fontTools/ttLib/tables/_g_l_y_f.py::flagBest` | `flag \|= flagXsame`（`x == 0` 分支） | 70 | 分支未进入 / 位已置 |
| 5 | `numba_adjust_indices` | Numba 0.59.0 | `numba/cpython/unicode.py::_adjust_indices` | `end += length` | 196 | 负索引 clamp 吸收 |
| 6 | `mpl_norm_angle` | Matplotlib 3.8.0 | `mpl_toolkits/mplot3d/art3d.py::_norm_angle` | `a = a - 360` | 17 | 模 360 后进入分支 |
| 7 | `scipy_range_prod_mid` | SciPy 1.11.4 | `scipy/special/_basic.py::_range_prod` | `mid = mid - ((mid - hi) % k)` | 60 | 递归分割对齐 |
| 8 | `condaindex_make_seconds` | conda-index 0.4.0 | `conda_index/index/__init__.py::_make_seconds` | `timestamp //= 1000` | 7 | 阈值分支未进入 |
| 9 | `cpython_median_low` | CPython 3.11.7 | `Lib/statistics.py::median_low` | `data = sorted(data)` | 36 | 排序对中位数不可观测 |
| 10 | `cpython_punycode_adapt` | CPython 3.11.7 | `Lib/encodings/punycode.py::adapt` | `delta += delta // numchars` | 328 | 增量被饱和非线性公式吸收 |

许可证：CPython 为 PSF-2.0；Babel、SciPy、conda-index 为 BSD-3-Clause；fpdf2 为 LGPL-2.1-only；fontTools 为 MIT；Numba 为 BSD-2-Clause；Matplotlib 为 PSF-based。每个案例的完整元数据在 `realcases/cases.json`。

人工 guard 的校验结果：**10/10 在各自声明的有限域上 BOUNDED 精确**（unsound=0，incomplete=0）。但这不等于"人工条件都紧凑"：

* 9/10 是紧凑的语义条件；
* `cpython_punycode_adapt` 的精确条件必须把增量前后的最终公式都写出来（输出等价重述），已标记 `human_guard_compact=false`。第一版"增量等于 0"是 sound 但不 complete 的，漏掉了 delta=10/11/16/17、first=False 的 6 个被吸收点。
* `babel_cldr_modulo` 的第一版 guard 也漏掉了"负数取模等于半个模数"的情况，修正后才精确。这说明人工写条件同样依赖穷举校验，不是一次直觉就能得到。

---

## 5. 十案例实测（本阶段唯一的新测量）

完整数据：`realcases/audit.json`、`realcases/audit.md`。全部为 CPU、0 token、无模型调用。

### 5.1 总表

| 方法 | 实测案例 | derived | exact | sound | complete | UNKNOWN | tokens | wall |
|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 0/10（未运行） | — | — | — | — | — | 未运行 | 未运行 |
| Full MACE (A) | 0/10（未运行） | — | — | — | — | — | 未运行 | 未运行 |
| Pure Symbolic | 10/10 | 5 | 2 | 2 | 2 | 5 | 0 | 0.51 s |
| Symbolic + 摘要 | 10/10 | 5 | 2 | 2 | 2 | 5 | 0 | 0.46 s |
| 人工 guard（参考，不是系统成绩） | 10/10 | — | 10 | 10 | 10 | 0 | 0 | 1.08 s |
| 归纳（generic 池，诊断） | 10/10 | 10 | 1 | 6 | 2 | 0 | 0 | 3.65 s |
| 归纳（full 池，诊断） | 10/10 | 10 | 1 | 5 | 2 | 0 | 0 | 3.44 s |

注意：

* **Direct 与 Full MACE 没有数字。** 本阶段禁止新模型调用，且这 10 个程序没有历史运行；任何填入的准确率都会是编造。
* Pure Symbolic 与 Symbolic + 摘要在真实案例上**完全相同**。原因不是"摘要无用"，而是这 10 个程序没有带声明签名的用户 helper：阻塞项是内建函数（`int`、`len`、`sorted`）或递归，摘要机制根本没有被触发。
* 归纳只是诊断行，不属于第 2 节的四组方法。

### 5.2 符号推导的 5 个 UNKNOWN 与 3 个 INVALID

| 案例 | 结果 | 原因 |
|---|---|---|
| `numba_adjust_indices` | UNKNOWN | A 改变控制流，P+/P− 路径条件不同 |
| `cpython_median_low` | UNKNOWN | 符号执行器报 "A changes control flow: path conditions differ" |
| `scipy_range_prod_mid` | UNKNOWN | 递归调用没有 helper 摘要 |
| `condaindex_make_seconds` | UNKNOWN | 内建 `int` 被当作无摘要 helper |
| `cpython_punycode_adapt` | UNKNOWN | 不支持 `While` |
| `babel_cldr_modulo` | DERIVED 但 INVALID | 推导式含 `... and 1 and ...`，布尔位置出现 int |
| `fpdf2_int32` | DERIVED 但 INVALID | 项语言不支持 `BitXor` |
| `fonttools_flagbest_xsame` | DERIVED 但 INVALID | 链式比较不支持；模块常量不在 guard 作用域 |

只有 `cpython_leapdays` 与 `mpl_norm_angle` 两个推导结果既 DERIVED 又在项语言中可判定为精确。它们的 guard 分别是：

* `leapdays`：`(y2-1)//4 - (y1-1)//4 - ... == (y2-1)//4 - y1//4 - ...`，即把原返回表达式在 A 前后各写一遍；
* `norm_angle`：`not (a+360)%360 > 180 or (360+a)%360 - 360 == (360+a)%360`。

两者都是**输出等价重述**，不是"为什么被吸收"的紧凑条件。也就是说：在 10 个真实案例上，自动方法产生的、既精确又紧凑的语义 guard 是 **0 个**。这是负结果的核心证据，但也正好说明该结果衡量的是"原型能否给出可读条件"，而不是"LLM 能否理解程序"。

来源归因（source attribution）：

* 符号推导：`leapdays` 1 条路径/1 条通道规则；`cldr_modulo` 8/8；`int32` 1/1；`flagBest` 32/64；`norm_angle` 2/2。UNKNOWN 案例的语句覆盖率只有 0.20–0.71。
* 归纳：只有 witness（成对执行的前/后快照），**没有源码行归因**；池大小 16–104，full 池相对 generic 池在 10 个案例上没有带来任何额外精确结果，反而在 `median_low` 上泄漏了 `distinct`/`sorted` 这类内部摘要并产生 3 个 unsound 判定。
* Direct / Full MACE：未测量，因此没有可从真实案例核对的 `source_lines` 归因。

### 5.3 成本

* 符号推导：约 0.05 s/案例（最慢 0.105 s），0 token。
* 有界归纳：约 0.35 s/案例（最慢 0.49 s），0 token；包含成对执行与全域复核。
* 人工 guard 复核：约 0.11 s/案例（每个案例启动一次隔离子进程）。
* 这些成本比 M6 表中的 Direct（23,626/11 ≈ 2.1k token/案例）与 Full MACE（141,081/11 ≈ 12.8k token/案例）低几个数量级；但本阶段没有模型侧成本可对照。

---

## 6. 有效性威胁

1. **核心对照缺失。** Direct 与 Full MACE 在真实案例上没有运行。M5/M6 的 5/11 与 3/11 来自开发 fixture，不能替代真实案例结果。任何"LLM 在真实代码上失败"的断言目前都没有数据。
2. **样本小且非随机。** 10 个案例是从 135 个"目标有前置定义"的候选里人工挑的，优先选择机制清晰、可执行、guard 可写的函数。漏斗比例只能说明"原型覆盖窄"，不能外推到一般程序。
3. **抽取改动。** 去装饰器、删不可达分支、内联模块常量、限制域（`median_low` 只保留长度 2–3）。这些改动都在案例里披露，但会改变"真实代码"的分布。
4. **guard 语言限制。** 项语言不支持 `BitXor`、链式比较、局部绑定，且 `and`/`or` **不短路**。`median_low` 的域被缩到长度 2–3，正是因为长度 1 时 `data[1]` 会越界。这些是工具限制，不是程序本身的困难。
5. **人工上界不独立。** 10 个人工 guard 由本审查撰写并反复用穷举修正（`cldr_modulo`、`punycode` 都改过）。它们不是独立标注者盲写的，因此 10/10 是乐观上界，不能当作人类基线。
6. **有界不等于证明。** 所有精确性都是有限域上的 `BOUNDED`；域最大 328 个点，没有无限域证明。
7. **两个符号臂在真实案例上不可区分。** 不是"人工摘要没用"，而是摘要路径没有被触发；不能据此评价 Symbolic + 人工摘要方法。
8. **`punycode` 的人工条件不是紧凑条件。** 它拉高了"人工可写"的比例，但按紧凑性只应算 9/10；报告同时给出两个口径。

---

## 7. 能否支撑有意义的 ICPC 负结果研究

### 7.1 现在能诚实支持的陈述

> 在一个 10 例、人工挑选、全部通过语法子集的小规模真实案例集上，有界符号推导对 2/10 给出精确 guard，有界归纳对 1/10 给出精确 guard；这两个精确结果都是输出等价重述，人工可写紧凑条件为 9/10。Direct 与 Full MACE 未测量。

这是一个有效的**试点观察**，但不是一般性结论。

### 7.2 为什么现在不能写成论文

* 负结果要成立，必须证明失败不是"我们的原型只支持一个狭窄片段"这一工程事实。当前漏斗显示绝大多数真实函数根本进不了子集；如果论文的主张是"LLM 条件合成失败"，审稿人首先会问：你在能进入子集的 10 个案例上测过 LLM 吗？答案是没有。
* 10 个案例、单一标注者、无随机抽样，无法支撑任何比例或显著性主张。
* 11 个 fixture 已明确是开发/探索性数据，不能充当独立评价集；把它们与 10 个真实案例混在一起会制造"21 个案例"的虚假规模。
* 现有自动精确结果都是重述；这支持"工具没有产生可读解释"，但不支持"方法在原理上不可行"。两者是不同强度的主张。

### 7.3 决策

**NO-GO（当前数据）/ 条件性 GO（完成闸门后）。**

条件性 GO 的四个闸门：

1. **抽样可辩护。** 预先注册来源仓库、纳入/排除标准与随机种子；从 ≥10 个真实项目抽 ≥50 个函数，而不是从候选里挑。漏斗本身作为一等结果报告。
2. **补齐核心对照。** 在同一 50 个案例上运行 Direct 与 Full MACE（需要 GPU/模型预算），协议、轮数、模型、温度、种子与 M5/M6 一致。
3. **人工上界独立。** 由未参与方法开发的标注者盲写 guard，至少双人，报告一致率；不允许用穷举反复修正后再称"人工基线"。
4. **预注册主指标。** 主指标是"全域精确 guard 率"；辅以 sound/completeness、UNKNOWN 分类、源码归因与成本。负结果的判定阈值必须在看到结果前写死。

只有四个闸门都通过，才建议投稿；否则应把本工作定位为内部工程报告，或把贡献改为"真实代码兼容性/失效分类"的短文（仍需闸门 1）。

---

## 8. 若走条件性 GO：最小下一阶段实验

**Phase A（CPU，无模型，约 1 周）**

* 用 `scripts/screen_realcases.py` 的漏斗，在预注册的 ≥10 个仓库上随机抽 50 个函数；
* 双人盲写并交叉校验 guard；
* 跑 Pure Symbolic 与两种归纳池；
* 闸门：至少 15 个案例有紧凑、精确、双人一致的人工 guard；否则停止（数据不足）。

**Phase B（GPU，需用户开启 autodl，约 1 周）**

* 同一 50 个案例跑 Direct 与 Full MACE，3 轮，`qwen2.5-coder:32b`，temperature 0，seed 42；
* 成本外推：M6 表中的 Direct 约 2.1k token/案例、Full MACE 约 12.8k token/案例；50 个案例约 0.1M 与 0.64M token，单卡数小时量级（不含重跑与失败重试）。实际预算以 Phase A 的案例长度为准。

**Phase C（分析，约 1 周）**

* 预注册主指标 + UNKNOWN 分类 + 成本；
* 若 Direct/Full MACE 在真实案例上达到或超过人工上界，负结果假设被推翻，应转向正结果或停止；
* 若自动方法仍 <20% 精确且失败集中在条件归纳，则可写成有边界的负结果。

---

## 9. 产物与复现

| 产物 | 路径 |
|---|---|
| 冻结清单 | `docs/FREEZE_MANIFEST.md`、`m6/freeze_manifest.json`、tag `m1-m6-freeze` |
| 真实案例目录与程序 | `realcases/cases.json`、`realcases/programs/*.py` |
| 案例审计 | `realcases/audit.json`、`realcases/audit.md` |
| 筛选漏斗 | `realcases/screening.json`（由 `scripts/screen_realcases.py` 生成） |
| 构建与审计脚本 | `scripts/build_realcases.py`、`scripts/realcase_audit.py` |

复现命令：

```bash
python scripts/build_realcases.py
python scripts/screen_realcases.py
python scripts/realcase_audit.py
python -m pytest -q
```

审计实现哈希（见 `realcases/audit.json` 的 `post_freeze_changes`）：

* `mace/symbolic.py`：`3d4c440b…`
* `scripts/realcase_audit.py`：`672c59b5…`
* `scripts/build_realcases.py`：`13698e43…`
* `realcases/cases.json`：`bf0278ad…`

---

## 10. 明确不声称的内容

* 不声称 Direct 或 Full MACE 在真实代码上失败——它们没有被测量。
* 不声称 10 个案例代表一般 Python 程序；它们是人工挑选的试点。
* 不声称符号推导/归纳在一般情况下不可行；只报告这 10 个案例上的覆盖与失效分类。
* 不把 Symbolic + 人工摘要的任何结果计入自动方法。
* 不把 11 个开发 fixture 当作独立评价集，也不把它们与 10 个真实案例合并成"更大样本"。
* 不输出 `PROVEN`；所有精确性都是声明有限域上的有界结论。
