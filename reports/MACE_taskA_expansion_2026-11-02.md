# MACE Task A：真实掩盖题扩充报告

日期：2026-11-02  
工作目录：`<local-path>`  
结论先行：新增 5 道可发布的 `FULL_MASKING_STORY`，全部来自 click 8.4.1 与 pyparsing 3.0.9 的真实源码；5 道都使用显式标记的 DESIGNED 测试，不是上游原测试。原测试筛查得到的 26 个 survivor 没有一个能通过六条件晋升，0 个发布；5 道题全部是“原测试不能直接支撑掩盖结论、用 DESIGNED 测试补足后晋升”的恢复项——其中 3 道原测试会抓到删除（`TARGETED_TEST_DETECTS_DELETION`），2 道原测试根本不执行 A（`NO_ORIGINAL_TEST_EXECUTES_A`）。

---

## 1. 口径与边界

### 1.1 六条件

只有同时满足以下六条才写入 `release_candidates/`：

1. 真实上游源码，A 行明确，记录源码哈希；
2. 声明的测试集在 P−（删掉 A）下仍然全部通过；
3. A 在至少一个声明测试输入上产生**局部效果**（在 A 所在函数返回处观测）；
4. 掩盖成立：该输入上 P+ == P−，且某个非空 U 子集保留时仍相等（MSMS），删掉某个非空 U 子集后暴露（MMBS）；
5. 至少一个**合法暴露反例**：存在合法输入使 P+ != P−；
6. MSMS/MMBS 已在声明输入上执行验证，并写明 witness 作用域。

第 4 条使用修正后的语义：`sufficient(kept)` 比较的是删掉 `U \ kept` 的变体；只有某个 U 删除也会暴露时，保留全部 U 才允许；`mmbs` 为空则 `msms` 清空。局部观测取 A 所在函数的返回处，因此“稍后由另一个函数/方法 setter 覆盖”的跨函数路径只能得到 `ASSERTION_GAP`，不能算掩盖。

### 1.2 DESIGNED 标记

5 道题的测试全部是我们为验证机制而写的，文件名和测试 docstring 都写明 **DESIGNED**，节点 id 也带 `DESIGNED` 前缀。它们不是上游原测试，不能被表述为“上游测试本来就能发现”。每道题同时保留了“原测试为什么不够”的记录。

### 1.3 任务选择与模型结果隔离

Task A 的筛选、设计测试、晋升在 Task B 之前完成；Task B 的模型分数没有参与任何 Task A 的取舍。Task B 也没有修改题面、指标或隐藏答案。

---

## 2. 筛选漏斗

### 2.1 静态池

两个静态候选文件合计 **632** 个候选，来自 5 个真实项目：

| 项目 | 静态候选数 |
| --- | ---: |
| click 8.4.1 | 288 |
| pyparsing 3.0.9 | 244 |
| packaging 23.1 | 63 |
| itsdangerous 2.0.1 | 19 |
| six 1.16.0 | 18 |
| **合计** | **632** |

静态机制分布：`name-overwrite=417`、`attribute=89`、`cross_function=38`、`augassign=36`、`multiline=31`、`subscript=21`。

### 2.2 实际复核

三个正式漏斗加 1 条手工补充记录，共复核 **471** 个唯一候选（`screening_funnel.json` 206 行、`_more.json` 215 行、`_extra.json` 57 行，其中 3310/3386 重复；另加手工 `3428`）。其余 **161** 个静态候选未在本轮预算内复核，记为“未复核”，**不当作失败**。

| 状态 | 数量 | 含义 |
| --- | ---: | --- |
| `STATIC_REJECT_DEAD_BEFORE_READ` | 205 | 静态判定在读取前已死/无意义 |
| `TARGETED_TEST_DETECTS_DELETION` | 207 | 有针对性的原测试能发现删除 |
| `NO_ORIGINAL_TEST_EXECUTES_A` | 33 | 原测试根本不执行 A |
| `TEST_SURVIVING_DELETION` | 26 | 原测试在 P− 下仍通过，进入资格判定 |

按项目：

| 项目 | 静态拒绝 | 原测试可发现 | 原测试不执行 A | 原测试 survivor |
| --- | ---: | ---: | ---: | ---: |
| click 8.4.1 | 34 | 76 | 9 | 8 |
| pyparsing 3.0.9 | 127 | 87 | 14 | 16 |
| packaging 23.1 | 28 | 34 | 0 | 1 |
| itsdangerous 2.0.1 | 12 | 6 | 0 | 1 |
| six 1.16.0 | 4 | 4 | 10 | 0 |
| **合计** | **205** | **207** | **33** | **26** |

### 2.3 关键漏斗事实

- **26 个原测试 survivor，0 个晋升。** 它们分别卡在：无合法暴露输入（1460）、MMBS 为空（3970）、`INCONCLUSIVE`（1647、3310 等）、`NO_LOCAL_EFFECT`、`ASSERTION_GAP`。
- **5 个发布题不是 survivor。** 它们最初被标为 `TARGETED_TEST_DETECTS_DELETION` 或 `NO_ORIGINAL_TEST_EXECUTES_A`；由于允许“研究者预定的真实本地测试场景”，我们用 DESIGNED 测试重新声明测试集，再走六条件。
- 因此，**“原测试路线 0 个，DESIGNED 恢复 5 个”** 是这轮最重要的筛选结论；不能把 5 个发布题说成“原测试漏检后自动筛出来的”。

完整逐候选记录见 `benchmark_real_v4/reports/expansion_report.md`。

---

## 3. 五道发布题

### 3.1 总表

| # | 候选 | A | 掩盖 U | 机制族 | DESIGNED 测试 | 资格判定 | witness |
| ---: | --- | --- | --- | --- | ---: | --- | --- |
| 1 | `click-8.4.1:src/click/core.py:2482:value` | `value = self.type_cast_value(ctx, value)` | L2497 `value = self.callback(ctx, self, value)` | 条件回调覆盖 | 3 | `MASKED_EFFECT=3` | masked [0,2], exposing [1,3] |
| 2 | `click-8.4.1:src/click/core.py:3428:value` | `value = False` | L3431 回调覆盖 | 条件回调覆盖（bool flag/UNSET 分支） | 3 | `MASKED_EFFECT=3` | masked [0], exposing [1,2] |
| 3 | `click-8.4.1:src/click/parser.py:63:args` | `args = deque(args)` | L105 `args = []` | 容器归一化后被通配路径清空 | 3 | `MASKED_EFFECT=2, INCONCLUSIVE=1` | masked [0,1,2], exposing [3] |
| 4 | `pyparsing-3.0.9:pyparsing/core.py:3371:attribute:maxLen` | `self.maxLen = max` | L3376 `self.maxLen = exact` | 构造器优先级覆盖 | 3 | `MASKED_EFFECT=3` | masked [0,1], exposing [2] |
| 5 | `pyparsing-3.0.9:pyparsing/core.py:823:tokens` | `tokens = self.postParse(instring, loc, tokens)` | L856 `tokens = fn(instring, tokens_start, ret_tokens)` | 后处理阶段覆盖 | 3 | `MASKED_EFFECT=3` | masked [0,1,2], exposing [3,4] |

五道题的 MSMS 与 MMBS 都是同一个单元素集合（分别 L2497、L3431、L105、L3376、L856）。witness 的声明作用域均为：**仅限声明的 probe 输入，不对整个合法输入域作断言**。

### 3.2 题 1：click `Parameter.process_value` 的类型转换被回调覆盖

- 源码：click 8.4.1，`src/click/core.py`，`Parameter.process_value`。
- A（L2482）：`value = self.type_cast_value(ctx, value)`。
- U（L2497）：`value = self.callback(ctx, self, value)`，位于 `if self.callback is not None` 且 `if not unset_keys` 内。
- 机制：A 先把原始值转成声明类型；若用户给了 callback，callback 的返回值随后整体替换 `value`。因此 callback 不依赖入参时，A 的类型转换在返回处不可见。
- 原测试情况：原测试能执行 A（P+ 命中 1138 个测试），并且原始 targeted 测试在 P− 下会失败，所以候选状态是 `TARGETED_TEST_DETECTS_DELETION`。这不否定掩盖：在“callback 返回常量”的合法输入上，P− 仍然通过；只是原测试没有覆盖这个输入组合。发布依据是 DESIGNED 测试，不是原测试漏检。
- DESIGNED 测试（`benchmark_real_v4/designed_tests/click_process_value_masked.py`）：
  - `test_masked_constant_callback`：caller 传 `"42"`，callback 返回 `"CONST"`，断言 `process_value(...) == "CONST"`；
  - `test_masked_callback_uses_param_name`：callback 返回 `param.name.upper()`，断言 `"NUM"`；
  - `test_masked_second_constant`：callback 返回固定 tuple。
  三个测试在 P− 下全部通过（`returncode=0`）。
- 合法暴露反例：callback 返回 `["echo", value]`，value=`"42"` 时：
  - P+：`["int", 42]`（A 先转 int）；
  - P−：`["str", "42"]`（没有类型转换）。
  合法输入且 P+ != P−。
- 资格：3 个 `MASKED_EFFECT`；MSMS=MMBS=`[[L2497]]`。
- 说明：L2491（UNSET→None）和 L2512（unset_keys 分支的 callback）也在候选 U 中，但这组 witness 只用到 L2497；不对其他分支作断言。

### 3.3 题 2：click bool flag 的 `UNSET → False` 被回调覆盖

- 源码：click 8.4.1，`src/click/core.py`，`Option.process_value`。
- A（L3428）：`value = False`，条件为 `self.is_flag and not self.required and self.is_bool_flag and value is UNSET`。
- U（L3431）：`value = self.callback(ctx, self, value)`，在 `if self.callback is not None` 内。
- 机制：bool flag 收到 UNSET 时先落成 False；若配置 callback，callback 再次覆盖。callback 返回常量时，False 不可见。
- 原测试：没有原测试以 UNSET 调用 bool flag 的 `process_value`，所以候选状态是 `NO_ORIGINAL_TEST_EXECUTES_A`；这是“原测试不执行 A”，不是“A 没有效果”。
- DESIGNED 测试（`click_bool_flag_unset_masked.py`）：
  - `test_unset_constant_callback`：`process_value(ctx, UNSET) == "CONST"`；
  - `test_unset_callback_uses_param_name`：返回 `"FLAG"`；
  - `test_unset_second_constant`：返回固定 tuple。
  P− 下 3/3 通过。
- 合法暴露反例：
  - 无 callback：P+ 返回 `False`，P− 返回 `Sentinel.UNSET`；
  - callback 回显：P+ 返回 `["bool", False]`，P− 在 probe 序列化 UNSET 时报 `Sentinel is not JSON serializable`（库本身是返回 UNSET，不是库崩溃；probe 的 JSON 层失败）。用无 callback 的输入作为干净反例。
- 资格：3 个 `MASKED_EFFECT`；MSMS=MMBS=`[[L3431]]`。

### 3.4 题 3：click `_unpack_args` 的 deque 转换被通配分支清空

- 源码：click 8.4.1，`src/click/parser.py`，`_unpack_args`。
- A（L63）：`args = deque(args)`。
- U（L105）：`args = []`，在 `spos is not None` 的通配（`nargs=-1`）路径里，先 `rv[spos] = tuple(args)` 再清空。
- 机制：纯通配参数不会从 deque 里 `popleft/pop`；它只把剩余参数整体 `tuple(args)`，然后 `args=[]` 覆盖。列表和 deque 在这里结果相同，A 被 U 掩盖。非通配（如 `nargs=1`）会走 `_fetch` 的 `.popleft()`，此时 A 不可少。
- 原测试情况：原测试能执行 A（P+ 命中 1105 个测试），且原始 targeted 测试在 P− 下会失败（候选状态 `TARGETED_TEST_DETECTS_DELETION`）；原测试没有专门构造纯通配路径来观察“deque 转换被清空”这一掩盖组合。
- DESIGNED 测试（`click_parser_unpack_masked.py`）：
  - `test_variadic_two_values`：`files nargs=-1`，输出 `alpha,beta`；
  - `test_variadic_single_value`：输出 `one`；
  - `test_variadic_no_values`：输出空串。
  P− 下 3/3 通过。
- 合法暴露反例：`mode="single", values=["alpha"]`：
  - P+：exit 0，输出 `alpha\n`；
  - P−：`AttributeError`（list 没有 `popleft`），exit 1。
- 资格：2 个 `MASKED_EFFECT`，1 个 `INCONCLUSIVE`（空 variadic 在删掉 U 后仍相同，无法构成最小掩盖集）。按“至少一个测试输入有局部效果且至少一个合法暴露反例”发布；不把第 3 个测试算作掩盖证据。
- MSMS=MMBS=`[[L105]]`。

### 3.5 题 4：pyparsing `White` 的 `maxLen = max` 被 `exact` 覆盖

- 源码：pyparsing 3.0.9，`pyparsing/core.py`，`White.__init__`。
- A（L3371）：`self.maxLen = max`，在 `if max > 0` 内。
- U（L3376）：`self.maxLen = exact`，在 `if exact > 0` 内；同一块还把 `minLen` 设为 exact。
- 机制：同时给 `max` 和 `exact` 时，exact 的赋值覆盖 max；最终 `maxLen` 只看 exact。exact=0 时 U 不执行，A 的结果（max）才可见；若删掉 A，`maxLen` 根本没有被赋值，访问即 AttributeError。
- 原测试：没有原测试同时设置 max 与 exact，候选状态 `NO_ORIGINAL_TEST_EXECUTES_A`。
- DESIGNED 测试（`pyparsing_white_exact_masked.py`）：
  - `White(max=3, exact=2)` → `maxLen=2, minLen=2`；
  - `White(min=1, max=5, exact=3)` → `maxLen=3, minLen=3`；
  - `White(" ", max=4, exact=1)` → `maxLen=1, minLen=1`。
  P− 下 3/3 通过。
- 合法暴露反例：`max=3, exact=0`：
  - P+：`maxLen=3, minLen=1`；
  - P−：`AttributeError: 'White' object has no attribute 'maxLen'`。
- 资格：3 个 `MASKED_EFFECT`；MSMS=MMBS=`[[L3376]]`。

### 3.6 题 5：pyparsing `_parseNoCache` 的 postParse 被 parse action 覆盖

- 源码：pyparsing 3.0.9，`pyparsing/core.py`，`ParserElement._parseNoCache`。
- A（L823）：`tokens = self.postParse(instring, loc, tokens)`。
- U（L856）：`tokens = fn(instring, tokens_start, ret_tokens)`，在非 debug 的 parse action 循环内；L833 是 debug 分支的同形赋值。
- 机制：postParse 先把 token 列表做元素级归一化（Group 包一层、Combine 合并、Suppress 清空）；若同一 element 还挂了 parse action，action 的返回值随后整体替换 `tokens`。action 返回常量时，postParse 的结果在最终 ParseResults 中不可见。
- 原测试情况：原测试能执行 A（P+ 命中 1185 个测试），且原始 targeted 测试在 P− 下会失败，所以候选状态是 `TARGETED_TEST_DETECTS_DELETION`。原测试没有覆盖“同一 element 挂常量 parse action”这一合法组合；在该组合下 P− 通过。发布依据是 DESIGNED 测试。
- DESIGNED 测试（`pyparsing_postparse_action_masked.py`）：
  - `test_group_postparse_masked_by_constant_action`：Group + 常量 action；
  - `test_combine_postparse_masked_by_constant_action`：Combine + 常量 action；
  - `test_suppress_postparse_masked_by_constant_action`：Suppress + 常量 action。
  三个测试只断言最终 `["CONST"]`；P− 下 3/3 通过，因为 action 自己提供了该值。
- 合法暴露反例：
  - Group 无 action：P+ `[["abc"]]`，P− `["abc"]`；
  - Combine 无 action：P+ `["abcd"]`，P− `["ab","cd"]`。
- 资格：3 个 `MASKED_EFFECT`；MSMS=MMBS=`[[L856]]`。L833 是 debug 同形路径，未被这组 witness 使用；不对 debug 分支作断言。

---

## 4. 原测试 survivor：26 个全部未晋升

下表保留所有 26 个原测试 survivor 的处置。`-` 表示该候选没有完成资格判定文件（预算停止），按静态复核拒绝，不冒充“已证伪”。

| 候选 | 资格判定 | 未晋升原因 |
| --- | --- | --- |
| `click-8.4.1:src/click/_compat.py:505:cross_function:stream` | `ASSERTION_GAP=3` | 跨函数覆盖；A 所在函数返回处观测不到，不能算局部掩盖 |
| `click-8.4.1:src/click/_textwrap.py:123:augassign:cur_len` | `INCONCLUSIVE=6` | 未形成可验证的 MSMS/MMBS |
| `click-8.4.1:src/click/core.py:126:attribute:ctx` | `INCONCLUSIVE=1` | 未形成可验证的 MSMS/MMBS |
| `click-8.4.1:src/click/core.py:3383:source` | `NO_LOCAL_EFFECT=7` | A 在函数返回处无局部效果 |
| `click-8.4.1:src/click/core.py:3406:source` | `NO_LOCAL_EFFECT=1` | A 在函数返回处无局部效果 |
| `click-8.4.1:src/click/formatting.py:90:indent` | `ASSERTION_GAP=1, INCONCLUSIVE=3` | 断言间隙 + 不确定；无有效 MSMS/MMBS |
| `click-8.4.1:src/click/shell_completion.py:607:args` | `NO_LOCAL_EFFECT=9` | A 在函数返回处无局部效果 |
| `click-8.4.1:src/click/termui.py:315:cross_function:color` | `NO_LOCAL_EFFECT=7` | 跨函数路径；返回处无局部效果 |
| `itsdangerous-2.0.1:src/itsdangerous/jws.py:77:payload` | `NO_LOCAL_EFFECT=25` | A 在函数返回处无局部效果 |
| `packaging-23.1:src/packaging/version.py:476:letter` | `ASSERTION_GAP=25` | 覆盖发生在读取之后/跨路径；无局部掩盖 |
| `pyparsing-3.0.9:pyparsing/core.py:1460:other` | `MASKED_EFFECT=25` | **形式 MSMS/MMBS 成立，但无合法暴露反例**：所有 probe 输入 P+==P−，不满足第 5 条 |
| `pyparsing-3.0.9:pyparsing/core.py:1647:key` | `INCONCLUSIVE=6` | 无有效 MSMS/MMBS |
| `pyparsing-3.0.9:pyparsing/core.py:2107:success` | `ASSERTION_GAP=9, NO_LOCAL_EFFECT=16` | 多数无局部效果，少数为断言间隙 |
| `pyparsing-3.0.9:pyparsing/core.py:2606:subscript:results` | `ASSERTION_GAP=12` | 覆盖发生在状态读取路径；返回处不成立 |
| `pyparsing-3.0.9:pyparsing/core.py:3111:quote_char` | `NO_LOCAL_EFFECT=25` | A 在函数返回处无局部效果 |
| `pyparsing-3.0.9:pyparsing/core.py:3228:ret` | `NO_LOCAL_EFFECT=12` | A 在函数返回处无局部效果 |
| `pyparsing-3.0.9:pyparsing/core.py:3310:augassign:loc` | `INCONCLUSIVE=25` | 候选 U 只有 while 体内的 L3313 `loc += 1`；`loc += 1` 的效果被循环继续消费，现有局部观测无法形成可验证的赋值级 MSMS/MMBS |
| `pyparsing-3.0.9:pyparsing/core.py:3386:augassign:loc` | `-`（未跑完资格） | 与 3310 同形：`loc += 1` 后由 while 继续消费；静态复核拒绝 |
| `pyparsing-3.0.9:pyparsing/core.py:3603:attribute:exprs` | `-`（未跑完资格） | 纯类型注解 `self.exprs: List[...]`，删除无运行时效果 |
| `pyparsing-3.0.9:pyparsing/core.py:3605:exprs` | `ASSERTION_GAP=1` | 资格差异来自 generator repr 地址；进一步 probe 显示所有合法 generator 输入都会走后续 `exprs=list(exprs)`，**无合法暴露输入** |
| `pyparsing-3.0.9:pyparsing/core.py:3964:maxExcLoc` | `NO_LOCAL_EFFECT=6` | A 在函数返回处无局部效果 |
| `pyparsing-3.0.9:pyparsing/core.py:3970:maxExcLoc` | `ASSERTION_GAP=23, MASKED_EFFECT=2` | 有两个形式 MASKED_EFFECT，但 **MMBS 为空**：删任何 U 都不暴露 |
| `pyparsing-3.0.9:pyparsing/core.py:5524:subscript:tokenlist` | `-`（未跑完资格） | 循环内分支下标写；由后续分支/结构决定，静态复核拒绝 |
| `pyparsing-3.0.9:pyparsing/helpers.py:112:intExpr` | `NO_LOCAL_EFFECT=25` | A 在函数返回处无局部效果 |
| `pyparsing-3.0.9:pyparsing/results.py:223:augassign:i` | `-`（未跑完资格） | `i += mylen` 随后被 `i = slice(i, i+1)` 覆盖；`slice.indices` 又归一化负索引，无可观测效果 |
| `pyparsing-3.0.9:pyparsing/util.py:177:s` | `NO_LOCAL_EFFECT=25` | A 在函数返回处无局部效果 |

### 4.1 保留的三个“形式成立但不可发布”案例

- **1460**：25 个测试都是 `MASKED_EFFECT`，MSMS=`[[L1465,L1468]]`，MMBS 也非空；但 4 个 probe 输入全部 P+==P−，**没有任何合法暴露反例**，违反第 5 条。保留记录，不发布。
- **3970**：2 个 `MASKED_EFFECT`，但 MMBS 为空；无法证明删掉 U 会暴露，违反第 4/6 条。
- **3605**：资格中的唯一差异是 generator 的 `repr` 含内存地址（`<generator object ... at 0x...>`），不是语义差异；去掉该噪声后所有合法 generator 输入都相等，无合法暴露反例。记录为工具噪声 + 不发布。

---

## 5. 机制覆盖与不足

### 5.1 实际覆盖

5 道题落在 4 个机制形状：

1. **条件回调覆盖**：click 2482（普通值）、click 3428（bool flag/UNSET）——同一族的两条不同分支；
2. **容器归一化后被通配路径清空**：click 63；
3. **构造器属性优先级覆盖**：pyparsing 3371；
4. **后处理阶段覆盖**：pyparsing 823。

### 5.2 明确不足

- 只有 **2 个项目**（click、pyparsing）。packaging 与 itsdangerous 各只有 1 个原测试 survivor，且都未通过资格；six 没有 survivor。**没有完成“更多独立 Python 项目”的目标**。
- 没有拿到用户特别点名的另外三类真实机制：
  - 多个操作**协同**才构成掩盖（当前都是单个 U 覆盖）；
  - 多条 fallback 掩盖路径（当前每题只有一条主路径）；
  - 循环状态/复杂值语义（3310/3386 的候选 U 只有循环体内的同名增量，资格判定为 `INCONCLUSIVE`，现有局部观测无法把它形式化成可验证的 MSMS/MMBS）。
- 5 道题里，click 2482 与 3428 属于同一机制族，因此独立机制数应记为 **4**，不是 5。
- 5 道题全部依赖 DESIGNED 测试；这满足“显式标记”的要求，但不能证明上游原测试会漏掉它们。它们证明的是：**在研究者指定的合法输入上，A 的局部效果被后续操作完全覆盖**。

### 5.3 对后续正式实验的含义

这 5 道题适合作为**构造集/开发集**，不适合作为独立泛化评估集。正式实验至少需要把上述缺口补成独立机制族；建议的最低规模见 Task B 报告第 7 节。

---

## 6. 产物与复现

- 发布候选：`benchmark_real_v4/release_candidates/*.json`（5 个，`promoted: true`，六条件逐项为 `ok`）
- 资格证据：`benchmark_real_v4/evidence/qualification_designed/*.json`
- witness：`benchmark_real_v4/witnesses/*.json` 与 `benchmark_real_v4/evidence/witnesses/*.json`
- DESIGNED 测试：`benchmark_real_v4/designed_tests/*.py`（5 个文件，每个 3 个测试）
- probe：`benchmark_real_v4/probes/*.py`
- 漏斗与逐候选附录：`benchmark_real_v4/reports/expansion_report.md`
- 晋升检查器：`benchmark_real_v4/promote.py`
- 设计测试资格器：`benchmark_real_v4/designed_qualify.py`

复现入口（在 kit 根目录）：

```bash
python -m benchmark_real_v4.promote --all
python -m benchmark_real_v4.report
```

注意：`--all` 只遍历漏斗中 `TEST_SURVIVING_DELETION` 的行，5 个发布题是手工指定 + DESIGNED 资格，不在该列表中；复现时应逐个调用 `python -m benchmark_real_v4.promote <candidate_id>`（witness 按 slug 自动查找），或直接读取已保存的 release JSON 与资格文件。

---

## 7. 安全与留痕

- 未在日志、提示或仓库写入任何 API key/token/密码/`.env`/凭据。
- 未把私有 oracle、隐藏标签或真值答案放进 prompt。
- 未用私有真值修改模型输出后再提交。
- 未运行的方法没有报成 0%。
- 未修改 Full MACE 算法，未大规模跑 Qwen，未改 M1–M6 历史结果。
- 未修改冻结的原证据或隐藏答案。
- 未按模型分数改题或改指标。
