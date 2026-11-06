# MACE V4 数据集建设 Phase 1：协议、划分与现有资产审计

- 日期：2026-11-04
- 版本：`v4.0-dev-2026-11-04`
- 范围：建立数据集协议与 DEV/HELDOUT 划分，只读审计既有探索性 v4 资产；
  **未修改 V3、未修改 MACE 算法/Graph/Qwen、未运行 HELDOUT。**
- 交付目录：[benchmark_v4_dataset/](../)

---

## 1. 结论摘要

1. V4 协议已建立：12 条验收条件（AC1–AC12），明确禁止用 `DESIGNED`
   测试充当原始测试证据（AC10）。
2. **当前已验收题目为 0。** 既有探索性 v4 的 5 个 release candidate
   全部依赖 `DESIGNED` 测试，按 V4 协议**一个都不能算题目**。
3. 既有 626 个去重候选中，只有 1 个同时具备原始测试级 masked 证据与
   合法 exposing witness 的潜质（`pyparsing:core.py:1460:other`），但它
   **没有合法暴露输入**，因此仍是 `REJECT_NO_EXPOSING_INPUT`。
4. 新补做的一道资格运行（`pyparsing:core.py:3386:augassign:loc`）出现
   18 条 `MASKED_EFFECT`，但经复核是**退化掩蔽**：在原始测试输入上
   P+ 已等于 P−，不需要 U 来恢复相等；在真正暴露的输入上 U 又不执行。
   按 V4 协议不能作为题目（见 §5）。
5. HELDOUT 已封存：8 个项目、PyPI sdist 官方 SHA-256 全部本地复算一致，
   `seal_sha256 = 106069cd615aef1b5e40e7888371d36d714a30d99151f083cee4d6ab1aaa7382`。
   开封前未阅读这些项目的源码。

---

## 2. 已建立的交付物

| 文件 | 内容 |
|---|---|
| `benchmark_v4_dataset/PROTOCOL.md` | 定义、语义类别、AC1–AC12、DEV/HELDOUT 规则、状态机、统计口径、变更控制 |
| `benchmark_v4_dataset/split/projects.json` | 5 个 DEV 项目 + 8 个 HELDOUT 项目（含 sdist URL/SHA-256） |
| `benchmark_v4_dataset/split/seal.json` | HELDOUT 封存记录与规范化哈希 |
| `benchmark_v4_dataset/registry/candidates.json` | 626 个候选的逐条 V4 状态与证据路径 |
| `benchmark_v4_dataset/registry/existing_v4_audit.json` | 既有资产汇总计数 |
| `benchmark_v4_dataset/registry/accepted.json` | 已验收题目（空） |
| `benchmark_v4_dataset/stats/dataset_stats.json` | 严格分口径统计 |
| `benchmark_v4_dataset/tools/audit_existing_v4.py` | 只读审计脚本 |
| `benchmark_v4_dataset/tools/run_qualification.py` | 复用现有资格工具、写入数据集目录的包装器 |

---

## 3. DEV / HELDOUT 划分

### 3.1 V4-DEV（允许反复检查与调试）

| 项目 | 版本 | 来源 |
|---|---|---|
| click | 8.4.1 | 既有探索性 v4 |
| itsdangerous | 2.0.1 | 既有探索性 v4 |
| packaging | 23.1 | 既有探索性 v4 |
| pyparsing | 3.0.9 | 既有探索性 v4 |
| six | 1.16.0 | 既有探索性 v4 |

V3 的 Jinja2 3.1.3、Werkzeug 2.2.3 只作回归参考，不计入 V4 题目数。

### 3.2 V4-HELDOUT（已封存，未开封）

| 项目 | 版本 | sdist SHA-256（前 16 位） |
|---|---|---|
| chardet | 5.2.0 | `1b3b6ff479a8c414` |
| filelock | 3.13.1 | `521f5f56c50f8426` |
| idna | 3.6 | `9ecdbbd083b06798` |
| MarkupSafe | 2.1.3 | `af598ed32d6ae86f` |
| platformdirs | 4.1.0 | `906d548203468492` |
| sortedcontainers | 2.4.0 | `25caa5a06cc30b6b` |
| tomli | 2.0.1 | `de526c12914f0c55` |
| wcwidth | 0.2.13 | `72ea0c06399eb286` |

封存规则：

- 项目/版本在**任何候选检查前**固定；
- 只允许一次预先声明的流水线运行；
- 所有结果（含拒绝）都要登记；
- 开封前不阅读源码、不生成候选、不进入 DEV 缓存。

---

## 4. 既有探索性 v4 资产审计

只读来源：`benchmark_real_v4/evidence/`。

### 4.1 漏斗与状态

| 筛选状态 | 行数 |
|---|---:|
| `STATIC_REJECT_DEAD_BEFORE_READ` | 323 |
| `TARGETED_TEST_DETECTS_DELETION` | 221 |
| `NO_ORIGINAL_TEST_EXECUTES_A` | 53 |
| `TEST_SURVIVING_DELETION` | 28 |
| 不在漏斗、手工加入 | 1 |
| **去重候选合计** | **626** |

### 4.2 按 V4 协议重新标注

| V4 状态 | 数量 | 含义 |
|---|---:|---|
| `SCREENED_REJECT_DEAD_BEFORE_READ` | 323 | 删除是死存储 |
| `SCREENED_REJECT_TEST_DETECTS_DELETION` | 218 | 原始测试在 P− 下失败 |
| `SCREENED_REJECT_NO_A_EXECUTION` | 53 | 没有原始测试执行 A |
| `REJECT_NO_LOCAL_EFFECT` | 11 | 删除不改变任何观察 |
| `REJECT_NO_MASKING_RELATION` | 5 | 只有 assertion gap / 无掩蔽关系 |
| `REJECT_NO_EXPOSING_INPUT` | 3 | 有 masked 证据但没有合法暴露 witness |
| `INCONCLUSIVE` | 5 | 证据不足 |
| `DESIGNED_TESTS_ONLY` | 4 | 只有自建测试，违反 AC10 |
| `SCREENED_SURVIVOR` | 4 | 原始套件存活，但尚无资格证据 |
| `MASKING_CANDIDATE` | **0** | — |
| **已验收题目** | **0** | — |

### 4.3 5 个探索性 release candidate 的真实状态

| 候选 | 原始套件 | 声明的测试 | V4 状态 |
|---|---|---|---|
| `click:core.py:2482:value` | 检测到删除 | `DESIGNED` | `DESIGNED_TESTS_ONLY` |
| `click:core.py:3428:value` | 不执行 A | `DESIGNED` | `DESIGNED_TESTS_ONLY` |
| `click:parser.py:63:args` | 检测到删除 | `DESIGNED` | `DESIGNED_TESTS_ONLY` |
| `pyparsing:core.py:3371:attribute:maxLen` | 不执行 A | `DESIGNED` | `SCREENED_REJECT_NO_A_EXECUTION` |
| `pyparsing:core.py:823:tokens` | 检测到删除 | `DESIGNED` | `DESIGNED_TESTS_ONLY` |

它们满足探索性 `promote.py` 的六条件，但 `condition 2` 明确标注
`test_set=DESIGNED`；V4 协议 AC10 不接受这一条作为原始测试证据。
**不能把它们计入题目数量。**

---

## 5. 新补资格运行：为什么 `MASKED_EFFECT` 仍然不是题目

对 `pyparsing-3.0.9:pyparsing/core.py:3386:augassign:loc`
（`White.parseImpl` 中的 `loc += 1`，U=`L3390`）补做资格：

- 18 条原始测试被分类为 `MASKED_EFFECT`；
- 每条测试的 `relations` 都是 `msms=[["L3390"]]`、`mmbs=[["L3390"]]`；
- 观察量是函数内局部变量 `loc` 的最终值。

复核源码：

```python
start = loc
loc += 1              # A @ 3386
maxloc = start + self.maxLen
maxloc = min(maxloc, len(instring))
while loc < maxloc and instring[loc] in self.matchWhite:
    loc += 1          # U @ 3390
```

- 在原始测试的输入上，P+ 与 P− 的**最终观察已经相等**（`masked_at_empty=true`）；
  空集就足够，不需要任何 U 来“恢复”相等；
- 在真正能暴露的输入上（例如只有一个空白字符），while 循环不执行，
  U 根本不参与。

因此这不是 V3 意义上的掩盖关系，而是“A 改了局部变量但没改最终观察”的
退化情形。按 V4 协议：

- AC6 要求“存在掩盖 witness，且禁用 S 后恢复相等”；这里 P− 本来就相等，
  无法证明 S 的必要性；
- 该候选记为 `REJECT_NO_EXPOSING_INPUT` / 退化掩蔽，不计入题目。

这条记录保留在
`benchmark_v4_dataset/evidence/qualification/pyparsing-3_0_9_pyparsing_core_py_3386_augassign_loc.json`，
作为后续筛选器必须排除的反例。

---

## 6. 当前数据集统计（严格分口径）

| 口径 | 数值 |
|---|---:|
| 已验收题目数 | **0** |
| 其中 DEV / HELDOUT | 0 / 0 |
| 原始测试数 `T_task` | 0 |
| 声明输入数 | 0 |
| 操作关系 claim 数 | 0 |
| MSMS / MMBS 集合数 | 0 / 0 |
| 独立验收通过 | 0 |
| 候选（去重） | 626 |
| 其中 `DESIGNED_TESTS_ONLY` | 4 |
| 协作掩蔽题目（真实项目） | 0 |

---

## 7. 对既有资产的关键判断

1. **探索性 v4 的定位是“候选发现器”，不是“题目来源”。**
   它放宽了测试来源条件，因此产生了 5 个看似完整的候选；V4 必须重新走
   原始测试路径。
2. **`MASKED_EFFECT` 计数不能直接升级为题目。**
   `pyparsing:3386` 说明局部变量级 masked 可能没有真正的 U 必要性。
3. **现有 626 个候选中没有已确认的真实掩蔽题。**
   唯一有原始测试级 masked + witness 的 `pyparsing:1460` 缺合法暴露输入。
4. **HELDOUT 尚未被污染。**
   8 个项目的源码、测试、候选均未进入任何 DEV 缓存。

---

## 8. 下一阶段（在本会话范围内）

1. 在 DEV 上继续构造：以“暴露输入 + 掩盖输入 + U 必要性”三件套为前置，
   而不是以 `MASKED_EFFECT` 计数为前置。
2. 对 `pyparsing:1460` 做合法输入搜索；若找不到暴露输入，永久拒绝。
3. 为通过三件套的候选建立公开 probe、冻结输入网格与 MSMS/MMBS。
4. 在 DEV 上把 AC1–AC12 的独立验收器跑通并可复现。
5. 协议与工具冻结后，才按 `split/seal.json` 一次性运行 HELDOUT；
   所有结果登记，不以结果反改规则。

**当前不宣称任何 V4 题目；不以候选数量替代验收。**
