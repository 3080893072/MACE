# MACE：真实掩盖机制与删除风险的分层可行性检查

- 日期：2026-11-02
- 分支：`realbench-verifier-v2`（未提交）
- 范围：只做分类、定向真实源码筛选、只读算法审计和决策；不扩展正式 Benchmark，不运行 Qwen/Full MACE，不修改 M1–M6 或既有实验结果。
- 结论先行：**Full MACE + 真实 Benchmark 扩展仍为 NO-GO。** 但本轮找到 1 个新的 A 类真实用例：click 8.4.1 `Choice.normalize_choice` 的 A（上游 333 行）删除后，完整上游 click 套件仍通过，且存在“P+ / P− 都正常返回但结果不同”的暴露输入。该用例是 **defined-to-defined 的具体值变化 + independent 关系**，不是 cooperative/coexisting。它不足以把整体结论改为 GO，因为 A 类复杂多操作关系仍然缺失，且 Full MACE 没有操作级发现路径。

## 0. 分类口径

本轮只回答“删除 A 后原测试是否仍通过”和“掩盖机制是否存在”两个不同问题，不把它们混在一起。

### A 类：`TEST_SURVIVING_DELETION`

定义：删除 A 后，预先指定的原始上游测试集仍通过；同时存在一个暴露反例，使 P+ 与 P− 的观察不同。

- 可以用于支持“原测试没有抓到该删除风险”。
- 暴露反例不要求正常返回；`UnboundLocalError` 也可以作为暴露证据，但此时不能同时声称是 defined-to-defined。

### B 类：`VERIFIED_MASKING_ONLY`

定义：真实源码中存在执行验证过的掩盖关系，但不满足原始测试存活。

- 只证明“机制存在”。
- **不得**用来支持“现有测试漏掉删除风险”。

完整分类数据在 `benchmark_real_pilot/qualification/classes.json`。旧的三题结果和 `docs/benchmark_real_qualification.md` 保持不改；本轮新增内容单独记录。

## 1. 最终分类

| 用例 | A 行 / B 行 | 关系 | 原测试 P− | 类别 |
|---|---|---|---|---|
| click `_truncate_visible` | 23 / 32 | independent [B] | 通过 | A 类（绑定覆盖，非值变化） |
| click `Choice.normalize_choice` | 333 / 336 | independent [B] | 通过 | **A 类（具体值变化）** |
| Werkzeug `HeaderSet.update` | 2266 / 2272 | independent [B] | `1 failed` | B 类 |
| Werkzeug `url_unparse` | 605 / 614 | independent [B] | collection error | B 类 |
| Werkzeug `is_resource_modified` | 49 / 71,78 | **coexisting {B,C}** | `2 failed` / 套件大面积失败 | B 类 |

因此：

- A 类共 2 个；其中只有 `normalize_choice` 是 defined-to-defined 的具体值变化。
- B 类共 3 个，均不得用于“测试缺口”论证。
- A 类中没有 cooperative 或 coexisting；`coexisting {B,C}` 只存在于 B 类的 `is_resource_modified`。

## 2. 新找到的 A 类值变化用例

### 2.1 源码与语句

- 项目：click 8.4.1
- 文件：`src/click/types.py`
- 符号：`Choice.normalize_choice`
- A（上游 333 行）：`normed_value = ctx.token_normalize_func(normed_value)`
- B（上游 336 行）：`normed_value = normed_value.casefold()`

A 不是“先把变量绑上、随后在读取前被覆盖”的死绑定。A 调用外部归一化函数并产生新的字符串；B 读取这个值再做 casefold，最后返回。删除 A 会改变真实的值语义。

### 2.2 掩盖见证与暴露见证

掩盖见证 `mask_ascii`：

- 输入：`choice="ABC"`，`token_normalize_func=str.lower`，`case_sensitive=False`
- P+：A 得到 `"abc"`，B 得到 `"abc"`，返回 `"abc"`
- P−：A 被删除，B 直接 casefold，返回 `"abc"`
- 两者都正常返回，观察相同；`target_A_hit=true`

暴露见证 `expose_mapping`：

- 输入：`choice="A-B"`，归一化函数为 `replace("-", "_")`，`case_sensitive=False`
- P+：A 得到 `"A_B"`，B 得到 `"a_b"`，返回 `"a_b"`
- P−：B 直接 casefold `"A-B"`，返回 `"a-b"`
- 两者都正常返回，观察不同；`target_A_hit=true`

另一个暴露见证 `expose_case_sensitive`：

- `choice="ABC"`，归一化函数 `str.lower`，`case_sensitive=True`
- P+ 返回 `"abc"`；P− 返回 `"ABC"`；两者都正常返回。

### 2.3 关系与最小性

验证器 v2 在 `mask_ascii` 上得到：

- 基础状态：`MASKED`
- 只禁用 B（336 行）：P+ 为 `"abc"`，P− 为 `"ABC"`，状态 `EXPOSED`
- 结论：`independent [B]`，`minimal=true`，`scope=single_witness`

这不是 `coexisting` 或 `cooperative`：只有一个操作 B，且单独禁用 B 就足以暴露 A。报告中不把它写成复杂多操作关系。

### 2.4 上游原测试资格

在隔离 copy 中运行 click 8.4.1 完整套件：

- P+：`1562 passed, 94 skipped, 30000 deselected, 1 xfailed`
- P−（只把 333 行替换为 `pass`）：完全相同，`1562 passed, 94 skipped, 30000 deselected, 1 xfailed`
- 命中 A 的测试：`tests/test_normalization.py::test_choice_normalization`，命中 23 次，P+ / P− 均通过。

为什么原测试没抓到：

- 上游测试使用 `token_normalize_func=lambda x: x.lower()`，且输入/选项都是 ASCII。
- 在这个配置下，后面的 `casefold()` 会复现 `lower()` 的结果，删除 A 在观察上不可见。
- 暴露配置需要非“仅大小写”的归一化函数（例如把 `-` 映射为 `_`），上游套件没有覆盖这种配置。

这正是 A 类定义中的“原测试存活 + 暴露反例存在”，不是 B 类。

### 2.5 产物

- `benchmark_real_pilot/qualification/candidates/click_normalize_choice.py`
- `benchmark_real_pilot/qualification/verify_normalize_choice.py`
- `benchmark_real_pilot/qualification/run_upstream_normalize_choice.py`
- `benchmark_real_pilot/qualification/out/upstream_normalize_choice.json`
- `benchmark_real_pilot/qualification/out/click_normalize_choice_plus.log`
- `benchmark_real_pilot/qualification/out/click_normalize_choice_minus.log`
- `benchmark_real_pilot/qualification/out/verifier_v2_click_normalize_choice.json`

## 3. 定向搜索结果与拒绝记录

预先固定的筛选规则、全部候选和拒绝原因在 `benchmark_real_pilot/qualification/candidates_round3.json`。本轮没有按代码行数、Qwen 得分或 MACE 可解性选题；代码行数只用于生成候选，最终必须有过名见证和执行矩阵。

### 3.1 执行后拒绝的主要候选

| 候选 | A | 观察 | 拒绝原因 |
|---|---|---|---|
| click `wrap_text` | 90 `indent = None` | 掩蔽 `'a\n\nb'`；暴露 `'  a\n\nb'` | 有 defined-to-defined 掩蔽，但没有操作关系；禁用 B（95 行）后 P+/P− 仍相同，无法用操作干预暴露 A |
| Jinja2 `urlize` | 282 `middle = middle[match.end():]` | A 执行即暴露：P+ `(abc)` vs P− `((abc)` | 唯一掩蔽输入是 A 未执行的 `"abc"`；没有“A 执行且被掩盖”的见证 |
| packaging `_parse_letter_version` | 464 `letter = letter.lower()` | 小写输入掩蔽，但 A 是 no-op；大写输入暴露 | 掩蔽发生在 A 没有产生值变化时；B（470 行）在另一分支，不构成掩盖操作 |
| Werkzeug `_find_common_roots` | 148 `node = node.setdefault(...)` | P− 在测试输入上抛 `TypeError: join() missing ... 'path'` | 不满足 P+/P− 都正常返回；不是 defined-to-defined |

### 3.2 静态筛选拒绝的主要候选

- packaging `platform_tags`：A 在 x86 上被 B 在读取前覆盖，属于绑定差异；其他架构删除即未绑定。
- Werkzeug `_clean_status`、Jinja2 `do_xmlattr`、packaging `interpreter_version`：删除 A 后下一次读取即 `UnboundLocalError`。
- Jinja2 `make_attrgetter`、packaging `mac_platforms`：循环/闭包中首次迭代未绑定，没有稳定的 defined-to-defined 见证。
- Werkzeug `_process_traceback`：`hidden` 的循环赋值是条件性的，首帧可能未绑定。
- click `open_url`：A 位于嵌套 helper，直接改变返回值；平台分支互斥，没有下游掩盖操作。
- Werkzeug `unquote_etag`：A 的值立即被后续条件读取，删除会直接改变返回；没有验证过的掩蔽见证。
- Werkzeug `parse_converter_args`：B 只在 A 的值为 `None` 时覆盖，其他分支删除即未绑定；属于绑定覆盖。
- click `echo`：A 与 B 位于互斥的 `if/elif` 分支，不能形成单一关系。
- click `version_option`：B 只在 A 产生的值满足条件时执行；删除 A 后参数为 `None`，没有下游重算。
- click `_resolve_context`：循环内重算，需完整 Click context；未建立见证，不升级。

### 3.3 搜索结论

- 新接受：1 个（`normalize_choice`，independent）。
- 执行后拒绝：4 个。
- 静态形状拒绝：13 个。
- cooperative：0。
- 本轮新增 coexisting：0；已有的 `coexisting {B,C}` 仍是 B 类，且 A 是绑定覆盖，不是值变化。

## 4. Full MACE 操作发现能力的只读审计

### 4.1 现有语义契约能做什么

- `mace/contracts.py:45` 只有 `target_effect`、`upstream`、`observer` 三类关系，加上 `mask_guard`。`Relation`（53–68 行）字段是 `expr`、`condition`、`source_lines`、`rationale`、`channel`、`role`，**没有 operation-set 字段**。
- `mace/prompts.py:23` 的 SYSTEM 明确要求“不要猜测还要删除哪些语句，不要枚举源码操作子集”。`SCHEMA_TEXT`（69 行起）和 `LANGUAGE_SPEC` 都是公式级：变量是入口参数、A 前局部快照、`<name>_post`，不是“操作集合”。
- `mace/verify.py:563-564` 把关系组合成 Guard：固定点条件取 OR，观察者条件取 AND；源码里明确写着“relations are composed, never enumerated as source-operation subsets”。
- `mace/symbolic.py:696-700` 能做路径枚举、分支条件、状态摘要和目标行定位（`# TARGET_A`），可复用为“A 前后状态/路径”的来源，但不是操作发现。
- `mace/induct.py:55-74` 能取目标行以及 A 前后的状态（`pre` / `post`），可复用为 target-effect 快照。
- `benchmark_pilot/verifier_v2.py` 能独立做语句行干预、P+/P− 矩阵、最小性检查和单见证关系验证；它是评测基础设施，不是 MACE 算法。

### 4.2 必须新实现的能力

要自动发现本轮这类操作级关系，仅靠现有 MACE 契约不够，至少需要：

1. **稳定的操作单元模型**：不只支持 A 之后的简单顶层赋值，还要覆盖分支、循环、嵌套调用、属性/状态更新、跨函数辅助函数。
2. **候选生成**：从返回值/观察通道反向切片，处理调用副作用、异常、别名和容器变异；不能只靠“同一局部变量多次赋值”。
3. **干预执行**：把候选操作映射到可替换的源码行/语句，运行 P+/P− × 操作启用/禁用矩阵，区分非法输入、非法干预和不可判定。
4. **关系发现与最小性**：独立、cooperative、coexisting 的子集枚举；必要子集不可判定时返回 `UNDECIDABLE`，不能静默当 false。
5. **见证搜索**：在合法输入域中寻找“A 执行、P+/P− 都返回、观察相同/不同”的对照；不能只靠默认参数。
6. **跨函数/状态语义**：本轮 `normalize_choice` 的关键是 A 调用外部归一化函数、B 读取同一状态；这不是纯局部变量绑定问题。

### 4.3 纯 AST + 枚举 + 验证能做到什么

现有 `open_ops/discover.py` 是确定性 baseline，不是 Full MACE：

- 从最终返回值做局部变量反向活跃切片；
- 只支持 A 之后的顶层语句、一个顶层 return、无提前/多 return（`discover.py:261-267`）；
- 不支持嵌套 def（159 行）、调用/表达式副作用语句（210–212 行）；
- `If` 作为一个操作单元整体禁用（193 行）；
- `MAX_CANDIDATES = 12`（29 行）；
- 用 paired executor 做子集执行，发现 independent/cooperative/coexisting。

因此它能处理小规模、结构规整的受控任务，但不能覆盖本轮真实源码里的跨函数/状态更新机制，也没有证据表明它能稳定扩展到真实项目。它可作为评测/候选生成基线，不能替代 Full MACE 的操作发现核心。

### 4.4 结论

Full MACE 现有语义信息可以复用“A 前后状态、路径条件、公式检查”，但**不能通过改提示词得到操作集合**：契约结构和提示词都明确禁止操作枚举，验证器也是公式组合而非操作子集。要获得操作级发现能力，必须重新设计核心机制（或在 Full MACE 外增加独立的 operation-discovery 层）。这不是本轮可以声称已经完成的工作。

## 5. 五个问题的直接回答

### 5.1 是否存在真实源码中的 defined-to-defined 值变化掩盖？

**是，找到一个。** click `Choice.normalize_choice`：

- A 是具体值变化（调用归一化函数），不是死绑定；
- 掩蔽见证 `"ABC"` + `lower` + `case_sensitive=False`：P+/P− 都返回 `"abc"`；
- 暴露见证 `"A-B"` + 非大小写归一化：P+ 返回 `"a_b"`，P− 返回 `"a-b"`，两者都正常返回；
- 关系为 `independent [B]`，`minimal=true`，`scope=single_witness`。

但它**不是** cooperative/coexisting。

### 5.2 是否有独立验证的复杂多操作关系？

**有一个，但不是 A 类。** Werkzeug `is_resource_modified` 的 `coexisting {B,C}`：

- 单独禁用 B 或 C 仍掩蔽；
- 同时禁用 B+C 暴露；
- 两个真子集检查均仍掩蔽，最小性成立。

但 A 是 `unmodified = False` 的初始绑定，属于“绑定被下游覆盖”，不是具体值变化；且上游测试在 P− 下失败，所以它是 B 类，不能用于测试缺口论证。A 类中没有任何 cooperative/coexisting；`cooperative` 本轮仍为 0。

### 5.3 哪些用例同时满足原测试存活？

- `click Choice.normalize_choice`：是（新，A 类，值变化）。
- `click _truncate_visible`：是（旧，A 类，绑定覆盖；暴露是 `UnboundLocalError`，不是 defined-to-defined）。
- Werkzeug `HeaderSet.update`、`url_unparse`、`is_resource_modified`：否，均为 B 类。

所以“原测试存活”的用例只有 2 个，其中只有 1 个是值变化型。

### 5.4 Full MACE 能否用现有语义信息发现操作，还是必须重做核心？

**不能靠现有语义契约直接发现操作，必须新增/重做操作级机制。** 现有 `target_effects` / `upstream` / `observers` / `mask_guard` 是公式级，`Relation` 没有 operations 字段，提示词明确禁止枚举源码操作子集，`verify.py` 也只做公式组合。可复用的是状态快照、路径摘要、公式检查和 v2 干预矩阵；必须新实现的是操作单元、候选生成、子集执行、关系最小性和见证搜索。把提示词改成“请给出操作集合”不构成算法能力，也没有被本轮实验验证。

### 5.5 是否值得继续扩展真实 Benchmark？

**NO-GO（不建议按当前路线继续扩展）。** 理由：

1. 只新增了 1 个 A 类值变化用例，且关系是 independent；没有一个 A 类 cooperative/coexisting。
2. 唯一的 coexisting 关系来自 B 类用例，A 还是绑定覆盖，不能支撑“复杂多操作删除风险”的 Benchmark 主张。
3. Full MACE 没有操作级发现路径；继续堆题只会增加评测数据，不会让 MACE 具备自动发现能力。
4. 上游测试缺口很窄（`normalize_choice` 的缺口依赖非大小写归一化配置），继续扩展容易变成围绕个别用例调参。
5. 本轮没有 Qwen/Full MACE 分数，因此不能得出“MACE 优于 Qwen”或相反的模型比较结论。

如果以后重新评估 GO，最低门槛应是：

- 至少 1 个 A 类 **coexisting 或 cooperative** 的真实用例，且 A 是具体值变化；
- 该关系有独立见证、暴露见证、最小操作干预证据；
- 完整上游套件 P− 通过，命中的测试确实执行 A；
- Full MACE 或独立 operation-discovery 层能在不看 hidden labels 的情况下自动提出操作候选；
- 不按 Qwen/MACE 得分选题或改题。

## 6. 产物与复现

新增：

- `benchmark_real_pilot/qualification/classes.json`
- `benchmark_real_pilot/qualification/candidates_round3.json`
- `benchmark_real_pilot/qualification/candidates/click_normalize_choice.py`
- `benchmark_real_pilot/qualification/verify_normalize_choice.py`
- `benchmark_real_pilot/qualification/run_upstream_normalize_choice.py`
- `benchmark_real_pilot/qualification/screen_round3.py`
- `benchmark_real_pilot/qualification/out/upstream_normalize_choice.json`
- `benchmark_real_pilot/qualification/out/verifier_v2_click_normalize_choice.json`
- `benchmark_real_pilot/qualification/out/round3_screening.json`

复现命令：

```bash
cd <local-path>

python benchmark_real_pilot/qualification/run_upstream_normalize_choice.py
python benchmark_real_pilot/qualification/verify_normalize_choice.py
python benchmark_real_pilot/qualification/screen_round3.py
python -m pytest tests/test_pilot_evaluate.py tests/test_open_ops_discovery.py \
  tests/test_verifier_v2.py -q
```

未改动：M1–M6、既有三题结果、`docs/benchmark_real_qualification.md`、`candidates_round2.json`。未运行 Qwen/Full MACE；未使用任何 hidden label、私有真值或标准答案作为输入。
