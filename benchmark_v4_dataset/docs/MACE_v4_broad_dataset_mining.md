# MACE V4 Broad Discovery：真实软件数据集挖掘报告（第一轮）

- 日期：2026-11-04
- 协议：`benchmark_v4_dataset/PROTOCOL.md`（AC1–AC12 未放宽）
- 范围：仅数据集建设；未修改 MACE 算法、Graph 搜索器、Qwen Prompt/接口、V3 冻结资产与评分器
- 交付根目录：`benchmark_v4_dataset/`

---

## 1. 结论摘要

1. 新增 **70 个真实 Python 项目**：58 个进入 DEV 扫描池，12 个进入
   `HELDOUT_BROAD` 封存池。70/70 个 sdist 的 SHA-256 与 PyPI 官方摘要逐位一致。
2. Stage 1 在 58 个项目中产生 **15,902 个 AST 操作级候选**，覆盖
   name / attribute / subscript / augment / multiline / cross-function
   六类赋值形态；其中 10,542 个位于 `if`/`for`/`try` 控制流内。
3. Stage 2/3 对 51 个“自带原始测试”项目中的一部分做了分层动态验证：
   原始测试确实执行 A 的候选、P− 下目标测试/全套件的结果均已逐条记录。
4. 目前有 **1 道题目通过 AC1–AC12 独立验收**：
   `tabulate_numparses_header_wrap`（tabulate 0.9.0，DEV，
   `FULL_MASKING_STORY`，单元素 MSMS/MMBS = `{L2060}`）。
5. **协同掩盖确认题仍为 0**。已复核的 9 个“原始测试存活”候选中，3 个是
   完全覆盖（无暴露输入），1 个是空操作，1 个升为正式题，其余待 Stage 4。
6. 所有数字均来自实际执行与验收；没有为了凑数降低任何 AC 条件。

---

## 2. 数据来源与获取

### 2.1 选择与封存顺序

1. 依据公开 PyPI 元数据（包名、版本、summary）先固定 70 个项目及
   DEV / HELDOUT_BROAD 归属；
2. 抓取每个版本的 PyPI JSON（sdist URL、SHA-256、license、
   requires-python）；
3. **在读取任何源码之前**写入 `discovery/manifest/seal_heldout_broad.json`；
4. 下载全部 sdist 并逐位校验 SHA-256；
5. 只解包 DEV 的 58 个项目；`HELDOUT_BROAD` 的 12 个压缩包保持原样，
   未解包、未列目录、未扫描。

封存哈希：

```
seal_sha256 = 2d961e2e58f4116b8c4d0c820c28e8866fa74c0d0b602cb24879578f49dd08e3
```

### 2.2 规模

| 项 | 数量 |
|---|---:|
| 新增项目 | 70 |
| DEV（解包并扫描） | 58 |
| HELDOUT_BROAD（封存） | 12 |
| 自带原始测试的 DEV 项目 | 51 |
| sdist SHA-256 校验通过 | 70/70 |

逐个项目的 name、version、license、requires-python、sdist SHA-256、测试
文件数见 **`docs/MACE_v4_source_registry.md`**。

---

## 3. 分层流程与实现

| Stage | 内容 | 实现 | 产物 |
|---|---|---|---|
| 0 | 项目元数据、测试入口、包根 | `tools/stage0_stage1.py stage0` | `discovery/stage0/projects.json` |
| 1 | AST 轻量候选发现 | `tools/stage0_stage1.py stage1` | `discovery/stage1/candidates_static.json` |
| 2 | 原始测试是否执行 A | `tools/stage23_run.py plus` + 行级 trace | `discovery/stage2_3/<slug>.env.json`、`*_trace/` |
| 3 | P− 下原始测试是否存活 | `tools/stage23_run.py screen` | `discovery/stage2_3/<slug>.screen.json` |
| 4 | 局部效应、掩盖/暴露输入、U 必要性 | 逐候选探针（见 §6） | `discovery/stage4/probes.json`、`discovery/evidence/<cid>/` |
| 5 | AC1–AC12 独立验收 | `acceptance/accept_<task>.py` | `tasks/<task>/acceptance/acceptance_report.json` |

Stage 2/3 的预算（每个项目）为 targeted ≤ 60、full ≤ 20；每个候选都写
检查点，超时按“检测到删除”处理并记录 `timed_out`。所有运行使用项目
自己的 venv，项目本身通过 `PYTHONPATH` 指向变体源码，控制器不导入候选包。

---

## 4. Stage 0 / Stage 1 结果

### 4.1 测试可用性

- 51/58 个项目在 sdist 中找到原始测试模块（`test_*.py`、`*_test.py`、
  `conftest.py`，含包内测试目录）。
- 7 个没有可用原始测试（cerberus、cloudpickle、decorator、flake8、
  iniconfig、rsa、voluptuous）——记录为 `STAGE0_NO_TESTS`，不进入动态阶段，
  也不替换项目。

### 4.2 候选规模与形态

| 机制 | 候选数 |
|---|---:|
| name（同名局部变量重复赋值） | 8,934 |
| cross_function（同函数调用链上的同名赋值） | 2,990 |
| augassign（循环/累加） | 1,404 |
| subscript（容器元素重复赋值） | 1,162 |
| attribute（对象状态重复赋值） | 861 |
| multiline（跨行语句） | 551 |
| **合计** | **15,902** |

控制流形态：

| 属性 | 候选数 |
|---|---:|
| 位于 `if` 内 | 8,768 |
| 位于 `for/while` 内 | 4,528 |
| 位于 `try` 内 | 1,242 |
| 至少位于一种控制流内 | 10,542 |
| A 与后写之间读 A | 4,721 |
| 后写读取 A | 2,893 |
| 具备至少一种局部使用形态 | 6,286 |

这些是**候选**，不是题目，也不代表存在掩盖关系。

---

## 5. Stage 2 / Stage 3 结果

### 5.1 已完成动态验证的项目

| 项目 | 候选数 | 执行 A 且有局部使用 | targeted 运行 | P− 全套件存活 |
|---|---:|---:|---:|---:|
| tabulate 0.9.0 | 109 | 50+ | 50 | **9** |
| ecdsa 0.18.0 | 431 | 71 | 50 | 0 |
| sqlparse 0.4.4 | 89 | 31 | 31 | 0 |
| humanize 4.9.0 | 36 | 13 | 13 | 0 |
| parsimonious 0.10.0 | 27 | 4 | 4 | 0 |
| pygments 2.17.2 | 1,002 | 待统计 | 运行中 | 运行中 |

> 说明：`执行 A 且有局部使用` 是 Stage 2 的分类；`targeted 运行` 是
> 进入 Stage 3 的实际删除次数；`P− 全套件存活` 才是候选进入 Stage 4 的
> 门槛。三者不是同一个数。

### 5.2 未完成动态验证的项目（如实记录）

| 项目 | 原因 | 处理 |
|---|---|---|
| lark 1.1.9 | nearley 测试模块导入即抛 `ImportError` | 需 `--ignore` 后重跑 |
| markdown 3.5.1 | 项目自身把 collection warning 升级为 error | 需 `-W ignore` 后重跑 |
| isort 5.13.2 | 缺 `libcst`/`pylama` 等重依赖 | 暂缓 |
| pycodestyle 2.11.1 | sdist 未包含 `testing/` 支持包 | 记 `ENV_INCOMPLETE` |
| attrs 23.2.0 | 2 个 mypy 插件用例失败（环境相关） | 全套件非绿色，暂不进入 |
| more-itertools 10.1.0 | 1 个计时用例在 Windows 上失败 | 全套件非绿色，暂不进入 |
| networkx 3.2.1 | 全量行级 trace 开销过大，未在预算内完成 | 记录为未完成，不伪造结果 |
| pygments 2.17.2 | 运行中 | 完成后补入统计 |

环境失败不被计为“无候选”，也不被用来提升任何状态。

---

## 6. Stage 4：从“存活”到“可验收”

### 6.1 判定门槛

一个 `TEST_SURVIVING_DELETION` 候选只有在同时满足下列条件时才进入
`MASKING_CANDIDATE`：

1. 存在**合法暴露输入**：P+ 与 P− 的观察不同；
2. 存在**合法掩盖输入**：P+ 与 P− 的观察相同；
3. 存在非空 `S ⊆ U`，**保留 S** 时掩盖成立；
4. **禁用 S** 时掩盖被破坏（U 必要性）；
5. 在声明的有限 U 上枚举全部子集，得到严格最小 MSMS/MMBS；
6. 原始测试在 P− 下通过（AC4），且 A 确由原始测试执行（AC3）。

### 6.2 已验收题目

**`tabulate_numparses_header_wrap`**（tabulate 0.9.0，DEV）

- A：`tabulate/__init__.py:2074`
  `numparses = _expand_numparse(disable_numparse, num_cols)`
- 原始测试：`test/test_output.py::test_plain_maxheadercolwidths_autowraps`
  （P+ trace 命中 L2074；P− 下该测试通过）
- 声明输入：
  - `mask_both_widths`（同时给 `maxcolwidths` 与 `maxheadercolwidths`）
  - `expose_no_maxcolwidths`（只给 `maxheadercolwidths`）
  - `control_no_maxheader`（只给 `maxcolwidths`，A 不执行）
- U = `{L2060, L2129}`；`2060` 是同值的先前计算，`2129` 是转置后的重算
- 观察：

| 变体 | mask_both_widths | expose_no_maxcolwidths |
|---|---|---|
| P+ | 正常 | 正常 |
| P− | 与 P+ 相同 | `UnboundLocalError: numparses` |
| P− 且禁用 L2060 | `UnboundLocalError` | `UnboundLocalError` |
| P− 且禁用 L2129 | `UnboundLocalError` | `UnboundLocalError` |

- 全部 4 个子集枚举结果：仅 `{L2060}` 为最小充分集；`{L2060, L2129}`
  也成立但非最小；空集与 `{L2129}` 不成立。
- 独立验收：`tasks/tabulate_numparses_header_wrap/acceptance/acceptance_report.json`，
  AC1–AC12 全过，`shares_construction_code = false`。
- 故事类别：`FULL_MASKING_STORY`；MSMS 单元素，**不是协同掩蔽**。

### 6.3 已复核的反例（不计入题目）

| 候选 | 现象 | 判定 |
|---|---|---|
| tabulate:1464 | L1469 无条件重写 `headers`，P+ 与 P− 在**所有**输入上相同；同时删 A 与 U 才报错 | `REJECT_NO_EXPOSING_INPUT`（完全覆盖） |
| tabulate:2121 | L2192 无条件把格式名解析为表对象 | `REJECT_NO_EXPOSING_INPUT` |
| tabulate:2092 | pretty 路径下 `numalign` 的改动在声明输入上不可观察 | `REJECT_NO_EXPOSING_INPUT`（暂无暴露） |
| pyparsing:3386（Phase 1） | P+ 与 P− 在原始测试输入上本已相等，空集即可 | 退化掩蔽，拒绝 |

这些反例说明：**“原始测试存活”既不是“存在掩盖”，也不是“存在暴露”**。
Stage 4 的两个 witness 必须分别成立。

---

## 7. 计数（严格分轴）

| 口径 | 数量 |
|---|---:|
| 扫描项目数（DEV） | 58 |
| AST 候选数 | 15,902 |
| 有原始测试的项目 | 51 |
| 原始测试执行 A 的候选（已动态验证部分） | 见 `results/MACE_v4_stage_statistics.json` |
| P− 存活候选 | 见同一文件 |
| 有掩盖输入且 U 必要的候选 | 1 |
| 有合法暴露输入的候选 | 1 |
| 通过 AC1–AC12 的题目 | **1** |
| 协同掩盖确认题 | **0** |
| 原始测试数 `T_task`（题目内） | 1 |
| 声明输入数（题目内） | 3 |
| 操作关系数（题目内） | 2（EXPOSING、MSMS/MMBS） |

候选数、存活数、输入数都不等于题目数。

---

## 8. 已知限制

1. 动态验证只覆盖了 58 个项目中的一小部分；剩余项目尚未跑 Stage 2/3。
2. 单候选 Stage 4 仍需人工设计合法输入；目前没有通用的输入生成器，
   因此 5–10 道协同掩盖题需要逐个构造与复核。
3. 若原始套件在 P+ 下本来就非全绿（attrs、more-itertools），按 AC4 不能
   直接使用；必须先冻结排除项并重跑，未做之前不计入。
4. `HELDOUT_BROAD` 未解封；任何结果都不能反过来修改本轮筛选规则。

---

## 9. 下一步

1. 完成 pygments 的 Stage 3；对新增的 `TEST_SURVIVING_DELETION` 逐个做
   Stage 4 两 witness 检查。
2. 修复 lark/markdown/isort 的收集问题，补充动态样本。
3. 重点搜索**条件性**覆盖：A 与 U 并非在所有输入上共同执行的结构
   （条件分支、异常回退、跨函数状态），这是协同掩盖的来源。
4. 对每个新候选保留独立证据目录；协同掩蔽要求 MSMS ≥ 2 且严格子集验证。
5. 在 DEV 上稳定后，才按 `seal_heldout_broad.json` 一次性解封运行。

**本报告不宣称任何未实际验收的题目。**
