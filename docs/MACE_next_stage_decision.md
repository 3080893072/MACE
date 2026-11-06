# MACE 下一阶段决策：可靠分析基础与复杂语义瓶颈

- 日期：2026-11-03
- 分析器：`mace-reliable-ast-analyzer` **1.0.1**
- 代码位置：`reliable_ast_v1/`
- 本轮约束：无 GPU、无 Qwen/GLM 调用、未修改 Full MACE、M1–M6、`benchmark_real_v3`/`benchmark_real_v4` 历史证据与冻结结果；只新增 `reliable_ast_v1/` 下的文件。
- 结论性质：小规模机制可行性审查，不是独立测试集，不是全局关系完备性证明。

---

## 0. 结论摘要（六个问题）

| # | 问题 | 结论 |
|---|---|---|
| 1 | 工程补丁是否安全、可复现？ | **是，但仅限声明范围**。独立包、只写新目录；5 个开发任务 17/17 credited；现有 220 项测试通过；三处 1.0.1 修正后可重复得到同一组 claim。不是全局正确性证明。 |
| 2 | 修好的 AST 仍解决不了哪些语义机制？ | 跨文件/动态分派/别名、非终止干预下的循环携带状态、干预诱发的异常溯源、高阶/探针内定义的回调、组合搜索上界、v4 测试通过语义与严格观测语义的对齐。 |
| 3 | 找到多少个有真实执行证据的困难案例？ | 审查 **5** 个：**2** 个 C 类（对象属性、跨函数返回值）确认并复现；**1** 个 D 类（循环携带状态）有真实执行证据但干预后不终止；**2** 个 A/B 候选被 v4 自身资格检查否决。**0** 个确认的 A 类协同掩蔽、**0** 个确认的 B 类多回退路径、**0** 个真实算法失败。 |
| 4 | 这些失败是否需要新算法而非普通工程修复？ | **否**。3228 是空洞 MSMS 的关系分析 bug（已用工程 guard 修复）；607/3228 是探针/测试语义口径不一致；3310 是执行验证接口无法处理非终止，而当前 scorer 明确不接受 `PROVEN`，改指标被禁止。 |
| 5 | 哪个新机制最值得最小实验？ | **前置条件不成立，本轮不应启动任何新机制**。若未来出现满足条件的案例，**方案 1（确定性循环/路径敏感语义摘要，无 LLM）** 优先；方案 2（LLM 辅助的可验证摘要）仅保留接口设计。 |
| 6 | 是否已经有理由调用 Qwen/GLM？ | **否**。0 次模型调用、0 GPU；没有观察到任何“语义歧义”型失败。现有失败都能确定性定位。 |

### 明确决议

- **NO-GO**：不启动新的语义机制；不实现/不调用 Qwen/GLM 实验；不扩大正式测试集；不修改 scorer 或指标。
- **GO（仅限工程冻结）**：把 1.0.1 冻结为后续可靠分析基线；可选的工程修补（异常溯源标记、跨文件候选发现、探针—资格一致性检查）留待下一轮，不作为本轮成果。
- 本轮在本文档完成后停止。

---

## 1. Task 1：可靠确定性分析基础

### 1.1 独立版本与冻结边界

- 包名：`mace-reliable-ast-analyzer`，版本 `1.0.1`。
- 新文件全部位于 `reliable_ast_v1/`：
  - `analyzer.py`：候选发现、动态资格、关系枚举、观测分类、Runner。
  - `tracer.py`：高效有序事件 tracer。
  - `cases.py`：5 个开发任务 + 5 个审查案例。
  - `regress.py` / `run_cases.py`：回归与案例执行入口。
  - `probes/`：为审查案例编写的公开 API 探针。
  - `runs/`：`regression.json`、`cases.json`、逐案例 JSON。
- 未写入 `benchmark_real_v3/`、`benchmark_real_v4/`、`m1/`–`m6/` 或任何历史 run 目录。
- v4 变体只复制到 `D:/tmp/relv1_variants/<case>/<side>_<span>/`，不修改上游项目源树。
- `regression.json` 明确记录：`global_relation_completeness: false`。

### 1.2 候选发现：P+ 与 P− 两条轨迹

- 对每个输入分别运行 P+（保留 A）与 P−（删除 A），并分别 trace。
- 候选集合来自目标文件 AST 中与 A 状态键相同、但不是 A 本身的赋值节点。
- 资格判定同时使用 P+ 与 P− 事件：
  - P+：候选事件序列号大于 A 的首次事件序列号 → 动态下游。
  - P−：候选只在 P− 执行、P+ 不执行 → 由删除 A 动态启用，作为回退候选。
- 1.0.1 删除了 P− 侧残留的 `line > target_line` 静态行号条件。当前代码不再用源码行号判断下游关系；`_eligibility` 只看事件序列与是否出现。

### 1.3 高效 tracer

- 代码对象 → 文件路径匹配结果缓存一次，不在每行做 `realpath`。
- 只记录目标文件的 line / return / exception 事件，带单调递增 `seq`、`call_id`、`func`。
- 只快照显式列出的局部变量；不对属性/下标求值，避免 tracer 产生副作用。
- 对 `SystemExit(0)` 不记录为错误。

### 1.4 单操作优先 + 有界组合搜索

- 对 U 中每个候选先做单操作验证：
  - MSMS：只保留该操作（删除 U\S），比较 P+/P−。
  - MMBS：只删除该操作，比较 P+/P−。
- 只有在没有任何单操作解释关系时，才做组合搜索；上限 5 个操作、每行最多 24 个子集。
- 自身删除会超时/崩溃的候选被排除在 MSMS 组合之外，因为它属于干预伪影。

### 1.5 精确 AST 身份与删除审计

- 每个候选记录：`node_sha1`、`line`、`end_line`、列偏移、源代码片段。
- `candidate_audit` 报告：
  - `same_key_nodes_in_file`：同状态键节点数；
  - `covering_assignments`：覆盖该位置的赋值；
  - `collateral_risk`：同一行是否可能包含多个语句，按行删除是否会误删。
- 当前按行/跨度删除仍可能在同一行多语句时产生连带删除；审计只标记风险，不自动阻止。这是已知工程限制。

### 1.6 观测分类

`classify_run` 区分：

| 类别 | 含义 |
|---|---|
| `RETURN` | 进程 0 退出，观测为 `outcome=return`。 |
| `LEGAL_RAISE` | 进程 0 退出，观测为 `outcome=raise`；属于可执行观测。 |
| `PROBE_CRASH` | 观测缺失或带 `probe_crash`。 |
| `NONZERO` | 进程非 0。 |
| `TIMEOUT` | 超过 30 秒。 |
| `BAD_OBSERVATION` | 有观测但 outcome 不是 return/raise。 |

严格语义：

- `masked_strict`：两侧都可执行、P+ 为 `RETURN`、观测相等。
- `exposed_strict`：两侧都可执行、观测不等。
- `BROKEN_INTERVENTION`：候选删除本身导致 hang/crash，不当作 exposed 关系。

**已知边界**：`LEGAL_RAISE` 目前与正常 `RETURN` 一样算“可执行暴露”，但没有区分“程序本来就会抛的合法异常”和“只有 A 与候选同时删除才出现的 AttributeError”。3371 的 MMBS 就落在这一边界，详见 §2.3。

### 1.7 状态语义与反空洞修正

1.0.1 增加了两个 correctness guard：

1. **空洞 MSMS guard**：如果所有已评估候选删除都没有产生任何 `EXPOSED`，则基础 P+/P− 已经是 MASKED，此时任意保留子集都会“真空地”满足 `Masked_strict`。这种 MSMS 必须丢弃。scorer 对这类输入的原话是 `no observable local effect to mask`。
2. **非终止行状态**：如果没有任何关系，但已有评估出现 `BROKEN_INTERVENTION`，行状态必须是 `UNVERIFIED`，不能写成 `FALSE`。`FALSE` 只用于穷尽已声明 U 后确实没有关系的情况。

这两个修正直接来自案例审查，而不是预先设计。

### 1.8 回归结果

命令：`python -m reliable_ast_v1.regress`

| 任务 | claims | credited | builds | executions | wall (s) |
|---|---:|---:|---:|---:|---:|
| jinja2_bytecode_cache_read | 8 | 3 | 4 | 16 | 6.325 |
| werkzeug_bind_server_name_lower | 8 | 3 | 6 | 36 | 22.222 |
| werkzeug_filestorage_stream_name | 6 | 3 | 6 | 18 | 10.661 |
| werkzeug_get_host_default_empty | 7 | 5 | 10 | 22 | 13.781 |
| werkzeug_secure_filename_ascii_filter | 7 | 3 | 6 | 28 | 15.315 |
| **合计** | **36** | **17** | **32** | **120** | **68.304** |

- 36 条 claim 全部为 `WITNESS_VERIFIED`；17 条是去重后的 credited relation；其余 19 条是同一 relation key 在不同输入上的重复见证。
- 0 条 `FALSE`、0 条 `UNVERIFIED`、0 条 `INVALID`、0 条 `DUPLICATE`（scorer 状态计数）。
- 现有测试：`python -m pytest -q` → **220 项通过，退出码 0**。这不是新增测试，也不是独立基准。
- 17/17 的含义：五个已知开发任务里的已知关系全部被 credit；**不是**全局关系完备性，也不是独立泛化结果。

### 1.9 工程补丁安全性评估

**安全的部分**

- 独立包、独立版本号；只写 `reliable_ast_v1/runs/` 与 `D:/tmp/relv1_variants/`。
- 不读私有真值、不读隐藏标签、不调用模型、不联网。
- 固定 `PYTHONHASHSEED=0`、`PYTHONDONTWRITEBYTECODE=1`；claim 不含时间戳；重复运行得到相同的 claim/状态（wall 时间会变）。
- v3 走 `variant_lab.build_variant`；v4 只复制项目树后按 span 替换为 `pass  # reliable_ast_v1 intervention`。

**风险与限制**

- 同一行多语句时，按行删除可能连带删除；`collateral_risk` 只报警不阻止。
- v4 每个变体复制整棵项目树，且每个超时 30 秒；3310 一个案例就用了 186.9 秒（3 个输入 × P+/P− 两侧 × 30 秒）。
- 探针在项目 cwd 下执行，拥有进程权限；本轮只运行公开探针。
- 回归只覆盖 5 个开发任务与 5 个诊断案例；不能外推为“所有项目上都安全”。

**结论**：在声明的项目、探针与输入范围内，补丁安全且可复现；不构成全局正确性证明。

---

## 2. Task 2：复杂语义案例审查

### 2.1 选择口径与诚实声明

- 案例来自 v4 资格证据中“同一状态键的后续赋值”与两个已晋升的 DESIGNED 案例，不按新方法的表现挑选。
- 5 个案例全部是**开发/诊断案例**，不是独立测试集；`cases.json` 记录 `independent_test_set: false`。
- 3371、2482 的测试是 v4 的 **DESIGNED** 测试，不是上游原始测试；不能表述为“上游测试漏检”。
- 607、3228、3310 使用上游原始测试做资格检查，但我们的探针是自写的公开 API 探针；两者的差异单独记录。
- 607、3228、3310 都不是 v4 的 promoted release candidate；3371、2482 是。

### 2.2 案例 A 候选：click 607（多操作协同掩蔽）

| 字段 | 内容 |
|---|---|
| 项目/位置 | click 8.4.1，`src/click/shell_completion.py:607` |
| A | `args = ctx._protected_args + ctx.args` |
| v4 候选 U | 626 `args = sub_ctx.args`；629 `args = [*sub_ctx._protected_args, *sub_ctx.args]` |
| v4 原始测试证据 | 9 条测试全部 `NO_LOCAL_EFFECT`；`EMPTY`/`plus` returncode 0；`L626`、`L629`、`L626+L629` returncode 1（测试失败） |
| 我们的探针 | DESIGNED，4 个 shell 补全输入；4 个输入基础 P+/P− 均为 MASKED |
| 动态轨迹 | 输入 `['get','full']`：626 在 seq 118、629 在 seq 122、A 在 seq 134；候选全部早于 A 的首次事件 |
| 动态 U | 空（没有任何候选在 A 之后执行，也没有只在 P− 出现的候选） |
| 分析器输出 | 0 claims，case `UNVERIFIED`；有 A 执行的那一行分析为 `FALSE`（U 为空） |
| 失败位置 | 候选发现/资格口径：v4 用“静态后续赋值”，本分析器用“动态下游事件”。但 v4 自身的资格检查已判 NO_LOCAL_EFFECT，因此这不是一个真实关系 |
| 分类 | 普通工程/口径对齐；**不是 A 类协同掩蔽** |
| MSMS/MMBS 参考 | v4 无参考关系（NO_LOCAL_EFFECT）；无可复现的 [626,629] |

**结论**：该案例不能支持“多操作协同掩蔽”的算法缺口。v4 的候选删除会让测试失败，说明它们不是掩蔽操作；我们的探针下 A 本身没有可观测效应。

### 2.3 案例 B 候选：pyparsing 3228（多条回退掩蔽路径）

| 字段 | 内容 |
|---|---|
| 项目/位置 | pyparsing 3.0.9，`pyparsing/core.py:3228` |
| A | `ret = ret.replace(wslit, wschar)`（`ws_map` 循环内） |
| v4 候选 U | 3232 `ret = re.sub(self.escCharReplacePattern, ...)`；3236 `ret = ret.replace(self.escQuote, self.endQuoteChar)` |
| v4 原始测试证据 | 12 条测试全部 `NO_LOCAL_EFFECT`；`L3232`、`L3236`、`L3232+L3236` returncode 1（测试失败） |
| 我们的探针 | DESIGNED，2 个 QuotedString 输入；输入 1 基础 MASKED，A 执行 4 次（循环） |
| 动态 U | [3232, 3236] |
| 评估结果 | 删除 3232、删除 3236、删除两者：全部 MASKED；没有任何候选删除产生 EXPOSED |
| 分析器 1.0.0 | 错误地给出 2 条 MSMS `[3232]`、`[3236]`（空洞关系） |
| 分析器 1.0.1 | 0 claims，case `UNVERIFIED`，行状态 `FALSE`（U=2 已穷尽，无暴露） |
| 失败位置 | 关系分析：把“基础已 MASKED”当成“候选掩蔽 A”；已由 `exposed_any` guard 修复 |
| 分类 | 关系分析 bug，普通工程修复；**不是 B 类多回退路径** |
| MSMS/MMBS 参考 | v4 无参考关系（NO_LOCAL_EFFECT） |

**结论**：这是本轮唯一确认的错误关系类别。1.0.0 的 2 条 MSMS 会在严格 scorer 下被判 `FALSE`（`mmbs_ids` 为空）；1.0.1 不再发出。该案例不支持 B 类多回退路径缺口。

### 2.4 案例 C1：pyparsing 3371（对象属性状态）

| 字段 | 内容 |
|---|---|
| 项目/位置 | pyparsing 3.0.9，`pyparsing/core.py:3371`，`__init__` |
| A | `self.maxLen = max` |
| 动态候选 U | 3376 `self.maxLen = exact`（3373 是 else 分支，当前输入不执行，动态 U 不含它；v4 静态 U 含 3373/3376） |
| v4 证据 | DESIGNED、promoted；3 个设计测试；MSMS/MMBS `[L3376]`；exposing 输入 exact=0 |
| 我们的探针 | DESIGNED，输入 exact=2 与 exact=0 |
| exact=2 证据 | 基础 P+/P− 均 RETURN `['  ']`（MASKED）；删除 3376：P+ RETURN `['    ']`，P− `LEGAL_RAISE` AttributeError `'White' object has no attribute 'maxLen'` → EXPOSED |
| exact=0 证据 | 基础 EXPOSED，A 执行 → `EXPOSING_COUNTEREXAMPLE` |
| 分析器输出 | 3 claims：MSMS [3376]、MMBS [3376]、EXPOSING；case `WITNESS_VERIFIED_LOCAL` |
| 失败位置 | 无；对象属性状态可处理 |
| 分类 | C 类（对象属性）；成功 |
| 参考 | 与 v4 的 `[L3376]` 一致 |

**重要边界**：MMBS 的暴露是“A 与 3376 同时删除”后触发的 AttributeError，不是正常返回差异。按 scorer 语义它是可执行的合法观测；但按语义审计，应标记为“干预共删诱发的异常”，而不是程序正常异常路径。当前分析器没有这个溯源标记，属于普通工程可补项。

### 2.5 案例 C2：click 2482（跨函数与返回值传播）

| 字段 | 内容 |
|---|---|
| 项目/位置 | click 8.4.1，`src/click/core.py:2482` |
| A | `value = self.type_cast_value(ctx, value)` |
| 动态候选 U | 2497 `value = self.callback(ctx, self, value)`（v4 静态 U 还含 2491、2512） |
| v4 证据 | DESIGNED、promoted；3 个设计测试；MSMS/MMBS `[L2497]`；exposing 输入 callback=echo |
| 我们的探针 | DESIGNED，callback=const 与 callback=echo |
| const 证据 | 基础 P+/P− 均 MASKED；删除 2497：P+ RETURN `42`（int），P− RETURN `'42'`（str）→ EXPOSED |
| echo 证据 | 基础 EXPOSED，A 执行 → `EXPOSING_COUNTEREXAMPLE` |
| 分析器输出 | 3 claims：MSMS [2497]、MMBS [2497]、EXPOSING；case `WITNESS_VERIFIED_LOCAL` |
| 失败位置 | 无；跨函数回调返回值可处理 |
| 分类 | C 类（跨函数/参数/返回值）；成功 |
| 参考 | 与 v4 的 `[L2497]` 一致 |

**声明**：这是 DESIGNED 输入，不是上游 `test_arguments.py` 的漏检。v4 的 25 条上游测试记录为 `NO_LOCAL_EFFECT`，因为上游输入没有让 A 产生局部差异；我们的输入是专门构造的。

### 2.6 案例 D：pyparsing 3310（循环携带状态）

| 字段 | 内容 |
|---|---|
| 项目/位置 | pyparsing 3.0.9，`pyparsing/core.py:3310`，`CharsNotIn.parseImpl` |
| A | `loc += 1`（while 循环之前） |
| v4 候选 U | 3313 `loc += 1`（循环体） |
| v4 原始测试证据 | 25 条测试 `INCONCLUSIVE`；`L3313` 超时（None） |
| 我们的探针 | DESIGNED，3 个 CharsNotIn 输入 |
| 基础证据 | 3 个输入基础 P+/P− 均 RETURN，结果相同（MASKED） |
| 删除 3313 | P+ 与 P− 都在 30 秒后 TIMEOUT；6 次超时 ≈ 180 秒，实际 wall 186.9 秒 |
| 分析器输出 | 0 claims，case `UNVERIFIED`；3 行状态均为 `UNVERIFIED`（1.0.1 修正后） |
| 失败位置 | 验证接口：执行验证无法处理非终止干预；关系分析也没有循环不动点摘要 |
| 分类 | D 类（循环携带状态）+ 验证接口限制 |
| MSMS/MMBS 参考 | v4 INCONCLUSIVE；无参考关系 |

**诚实结论**：原程序中 3313 确实会掩盖 A 的效果（循环把 `loc` 继续推进），但删除 3313 后程序不再终止。当前执行型验证无法给出 P+/P− 观测，所以只能保持 `UNVERIFIED`。这不是“分析器算错”，而是“执行验证接口决定不了”。

### 2.7 案例汇总

| 案例 | 类型 | 真实执行证据 | 关系 | 分析器结果 | 是否算法缺口 |
|---|---|---|---|---|---|
| click 607 | A 候选 | 有（v4 测试 + 探针） | 无（NO_LOCAL_EFFECT / 动态 U 空） | 0 claims, UNVERIFIED | 否 |
| pyparsing 3228 | B 候选 | 有（v4 测试 + 探针） | 无（无暴露候选） | 1.0.0 错 2 条；1.0.1 0 条 | 否（工程 bug） |
| pyparsing 3371 | C 对象属性 | 有 | MSMS/MMBS [3376] | 3 claims, VERIFIED | 否（已解决） |
| click 2482 | C 跨函数 | 有 | MSMS/MMBS [2497] | 3 claims, VERIFIED | 否（已解决） |
| pyparsing 3310 | D 循环 | 有（超时） | 无法判定 | 0 claims, UNVERIFIED | 验证接口限制，不是新算法需求 |

- 确认的 A 类协同掩蔽：**0**
- 确认的 B 类多回退路径：**0**
- 确认的 C 类：**2**
- 有真实执行证据但无法判定的 D 类：**1**
- 被 v4 自身资格检查否决的候选：**2**
- 真实、可复现、需要新算法才能解决的分析器失败：**0**

因此，Task 3 的“存在真实可复现算法能力缺口”前置条件**不成立**。

---

## 3. Task 3：最小语义机制（预注册预案，本轮不启动）

> 由于 §2 未找到真实算法缺口，以下两份方案只作为**条件预案**保留，不实现、不训练、不调用模型。它们的作用是：如果未来出现满足条件的案例，可以直接按同一口径做最小实验，而不是临时拼接 AST + LLM + validator。

### 3.1 方案 1：确定性循环/路径敏感语义摘要（无 LLM）

**输入**

- A 的 AST 节点、状态键、动态候选 U。
- 目标文件的 AST + 控制流图（CFG）。
- P+/P− 的 tracer 事件（seq、line、call_id、被监视局部变量快照）。
- 公开探针输入。

**输出**

- 每个候选集合的关系判定：`PROVEN`（带机器可检查的证明项）或 `UNKNOWN`（带未完成义务）。
- 执行见证仍作为主要证据；`PROVEN` 只作为执行不可行时的补充，不替代 scorer 的 `WITNESS_VERIFIED`。

**新增中间表示**

`StateEffectSummary`：

- `key`：变量/属性状态键；
- `guards`：到达该写入的路径条件；
- `update`：写入表达式及其对旧值的依赖（独立/拷贝/算术/未知）；
- `exception_edges`：可能抛出的异常类型与条件；
- `loop_summary`：循环体的迭代摘要（至少支持“同一键的单调推进/幂等覆盖”两类）；
- `provenance`：该写入是否只在 A 被删除后才可达。

`ProofTerm`：

- `dominator`：从 A 到函数出口的所有路径都经过的写入；
- `path_condition`：路径可行性约束；
- `loop_fixpoint`：循环摘要与 A 写入的吸收关系；
- `exception_provenance`：异常是否在基础运行中可达。

**推理规则**

- **R1 覆盖支配**：若从 A 到出口的每条路径都经过一个对 `key` 的写入，且该写入的右值不依赖 A 写入的值，则包含该写入的集合是充分掩蔽集。
- **R2 循环不动点**：把 while 循环体摘要为对 `loc` 的推进；若 A 的推进被循环的首次测试/更新吸收（例如循环从同一字符继续推进到同一上界），则 A 被掩蔽。证明必须同时给出终止条件，避免把非终止当成掩蔽。
- **R3 回退并集**：若 A 之后有多条互斥分支分别写入 `key`，且每个分支的右值都独立于 A，则这些写入的并集是充分集；这对应 B 类多回退路径。
- **R4 异常溯源**：异常分为“基础运行可达的合法异常”和“只有共删才可达的异常”；只有前者可作为正常暴露证据，后者标记为 `INTERVENTION_INDUCED_EXCEPTION`。

**相对 AST / 程序切片 / 执行干预新增了什么**

- AST 能给出支配关系，但不能判断路径可行性与循环吸收。
- 切片能给出依赖，但不能证明循环不动点，也不能证明异常溯源。
- 执行干预能给出真实观测，但不能处理非终止干预，也不能证明“没有其它路径”。
- 本方案新增的是**带证明项的路径可行性 + 循环摘要 + 异常溯源**，不是“再跑一次 AST”。

**为什么可能解决已观察失败**

- 3310：无需执行删除 3313 后的非终止变体，直接证明循环摘要吸收 A 的推进；输出 `PROVEN`，而不是 `UNVERIFIED`。
- 3371：把共删诱发的 AttributeError 标成 `INTERVENTION_INDUCED_EXCEPTION`，避免把它当作正常暴露。
- 3228：R1 会要求存在真实暴露路径；没有暴露路径时不会产生 MSMS。

**如何验证候选语义**

- 独立的小检查器逐条验证 `ProofTerm`：
  - 路径条件用有界符号执行检查；
  - 循环摘要用有界展开 + 不变式检查；
  - 异常溯源用基础运行事件检查异常类型是否可达。
- 任一义务失败 → 该候选返回 `UNKNOWN`，不进入 claim。
- 与现实执行交叉检查：`PROVEN` 的集合若能在某一合法输入上执行，必须与执行观测一致；不一致直接判证明器错误。

**何时返回 UNKNOWN**

- 别名/动态属性/`getattr`/字典键无法精确对应；
- 动态分派、猴子补丁、跨文件未摘要的 callee；
- 非线性算术、不可判定循环条件；
- 检查器超时或证明项不完整。

**消融**

- 关闭 R2（循环不动点）→ 只应影响 3310 类；观察 claim 数、错误关系数、UNKNOWN 数。
- 关闭 R3（回退并集）→ 只应影响多路径案例；若没有此类案例，应显示 0 差异。
- 关闭 R4（异常溯源）→ 观察 3371 是否多出 MMBS。
- 保持同一 U、同一输入、同一组合上界；另设“仅把组合上界/超时调大”的工程基线，证明增益不是搜索范围扩大带来的。
- 报告：正确关系、错误关系、UNKNOWN、builds、executions、wall。

**为什么本轮不启动**

- 当前 scorer 明确拒绝 `PROVEN`：`PROVEN is reserved for a formally checked proof; this scorer has no proof checker and does not assign it from execution.` 即使证明器正确，也不能在现有指标上获得 credit；改 scorer 被本轮约束禁止。
- 除 3310 外，没有观察到需要该机制的失败；而 3310 的“正确”输出在当前协议下也只能是 `UNVERIFIED`。

### 3.2 方案 2：可验证语义摘要接口（LLM 仅作候选生成器，本轮不调用）

**输入**

- 分析器返回 `UNKNOWN` 的 callee：其源码切片、调用点、参数/返回值的运行时类型与观测。
- 调用点的路径条件与状态键。

**输出**

- 类型化摘要记录（JSON），不是自然语言解释：

```json
{
  "callee": "module.func",
  "signature": "(ctx, value) -> value",
  "pre": [{"expr": "isinstance(value, str)", "sort": "Bool"}],
  "post": [{"key": "return", "relation": "int(value) if value.isdigit() else value"}],
  "effect": {"key": "value", "sort": "Int|Str|List|Custom", "relation": "..."},
  "may_raise": [{"type": "ValueError", "condition": "..."}],
  "path_condition": "...",
  "evidence_spans": [["file", 100, 120]],
  "confidence": "low|medium|high",
  "check": {"kind": "executable_assertion|symbolic_obligation", "body": "..."}
}
```

**新增内容**

- 只对确定性分析无法摘要的 callee 生成候选摘要；模型不直接产出关系 claim。
- 每条摘要必须带 `check`，由 validator 转成可执行断言或符号义务；不能验证的摘要一律丢弃。
- 这不是“AST + LLM + validator”的拼接：模型只填补 callee 语义，关系判定、最小性、执行见证仍由确定性分析器完成。

**为什么可能解决已观察失败**

- 2482 的回调是在探针内定义的；如果未来出现“候选语义只在项目外定义、无法执行”的情况，摘要可以提供返回值关系。
- 但本轮 2482 已经通过真实执行回调解决，不需要摘要。

**如何验证**

- 在公开输入上执行 `check`；
- 与 tracer 观测的参数/返回类型对照；
- 对 `may_raise` 用基础运行事件验证可达性；
- 任一项失败 → `UNKNOWN`，不进入 claim。

**何时返回 UNKNOWN**

- 摘要缺少可执行检查；
- 检查器无法表达该语义；
- 与观测冲突；
- 摘要依赖未提供的上下文。

**消融**

- 对比 AST+机制 vs AST+机制+LLM：同一 U、同一输入、同一预算；
- 单独报告“生成的摘要数 / 通过验证数 / 被拒绝数”；
- 记录 token、模型调用、程序执行、wall；
- 若 LLM 只增加候选但验证通过率为 0，则判定无增益。

**本轮状态**

- 仅接口设计；**0 次模型调用，0 GPU**。
- 没有观察到需要它的真实失败；调用它只会增加成本与混淆变量。

---

## 4. Task 4：未来 Qwen/GLM 实验协议（只定协议，不调用）

### 4.1 统一操作级输出格式

```json
{
  "task_id": "string",
  "analyzer_version": "string",
  "target": {
    "file": "project-relative path",
    "line": 0,
    "end_line": 0,
    "code": "exact source segment",
    "state_key": "name or self.attr"
  },
  "universe": [
    {"id": "L626", "file": "...", "line": 626, "end_line": 626,
     "code": "...", "node_sha1": "..."}
  ],
  "claims": [
    {
      "type": "MSMS|MMBS|EXPOSING_COUNTEREXAMPLE|PREREQUISITE_BREAKING|CONDITIONAL_CORRECTNESS",
      "input": {},
      "control_input": {},
      "operations": [{"file": "...", "line": 0, "end_line": 0}],
      "status": "WITNESS_VERIFIED|FINITE_DOMAIN_EXACT|UNVERIFIED|UNKNOWN|FALSE|...",
      "evidence": {
        "plus_observation": {},
        "minus_observation": {},
        "plus_class": "RETURN|LEGAL_RAISE|...",
        "minus_class": "...",
        "witness_ids": ["..."]
      },
      "scope": "declared inputs only"
    }
  ],
  "unknowns": [
    {"operation": "...", "reason": "...", "needed": "loop_summary|callee_summary|alias|..."}
  ]
}
```

### 4.2 给模型的源码与上下文范围

- 目标函数完整源码；A 前后各 20 行；A 的精确 AST span。
- 声明的候选 U 及其源码片段（不含其它任务的候选）。
- 公开探针的输入 schema 与观测 schema。
- 不提供：隐藏测试、私有真值、scorer 内部实现、其它任务答案、模型历史分数。
- 不提供：可用于反推评测集的 per-task 调参信号。

### 4.3 类型化语义摘要

- 使用 §3.2 的 JSON schema。
- 每个字段必须有确定类型；自然语言只允许出现在 `note` 字段，且 validator 不读取 `note`。
- `check` 必须可执行或可符号检查；否则摘要无效。

### 4.4 validator 能反馈的信息

- 每条摘要/claim 的接受或拒绝；
- 反例输入；
- 期望观测与实际观测；
- 最小性违反（哪个真子集已满足）；
- `UNKNOWN` 的具体义务（缺少循环摘要、缺少 callee 摘要、别名冲突等）；
- 不反馈标量分数，避免模型针对分数过拟合。

### 4.5 Direct / AST / AST+新机制 / AST+新机制+LLM 对比

| 臂 | 候选发现 | 关系判定 | 见证 |
|---|---|---|---|
| Direct | 模型直接给 claim | 模型 | 由 scorer 验证 |
| AST | AST + 动态资格 | 确定性枚举 | 执行 |
| AST+新机制 | AST + 动态资格 + 方案 1 | 确定性 + 证明项 | 执行 + 证明 |
| AST+新机制+LLM | 同上 + 方案 2 摘要 | 确定性 + 证明项 + 验证过的摘要 | 执行 + 证明 |

- 同一批冻结任务、同一输入预算、同一 scorer、同一超时。
- 报告：正确关系、错误关系、UNKNOWN、builds、executions、wall、tokens、模型调用次数。
- 不能因为某一臂在开发集上更好就换任务或换指标。

### 4.6 成本记录

每个任务记录：

- prompt tokens、completion tokens、总 tokens；
- 模型调用次数、重试次数、失败次数；
- 程序执行次数、变体构建次数；
- wall time（分阶段：候选发现、关系分析、验证、模型）；
- 缓存命中。

### 4.7 开发集与未来独立评测集隔离

- 开发集：本轮 5 个冻结开发任务 + 5 个诊断案例（全部已在本轮暴露）。
- 未来评测集：未参与提示设计、阈值选择、案例挑选；在分析器与提示模板冻结后才可运行。
- 开发集与评测集分开报告，不合并平均。
- 不把开发/调试案例说成独立测试集；不把 DESIGNED 测试说成上游漏检。
- 不根据模型分数改任务、改指标、改评测集。

---

## 5. 六个问题的详细回答

### Q1. 工程补丁是否安全、可复现？

**是，限声明范围。**

- 独立包 `mace-reliable-ast-analyzer 1.0.1`；只写新目录。
- 回归 17/17；36 claims 全部 WITNESS_VERIFIED；32 builds / 120 executions / 68.304 s。
- 现有 220 项测试通过。
- 固定 hash seed、无时间戳 claim；重复运行 claim/状态一致。
- 已知风险：同行多语句的连带删除、v4 整树复制、30 秒超时、3310 的 186.9 秒 wall。
- **不是**全局正确性证明；`global_relation_completeness: false`。

### Q2. 修好的 AST 仍无法解决哪些语义机制？

1. **跨文件/动态分派/别名**：候选只扫描目标文件，状态键用精确 `ast.unparse`；`getattr`、字典键、属性别名、monkey-patching、其它模块的写入不可见。
2. **非终止干预 / 循环携带状态**：执行验证无法给出 P+/P− 观测；没有循环不动点摘要。3310 是实例。
3. **干预诱发的异常溯源**：合法 `raise` 与“只有共删才出现的异常”未区分；3371 的 MMBS 是边界。
4. **高阶/探针内定义的回调**：若 A 与候选都在项目外定义，项目源码里没有候选；只能靠显式声明的 U 与执行验证。
5. **组合搜索上界**：>5 个操作或 >24 个子集/行不搜索；本轮没有证据表明需要更大上界。
6. **测试通过语义 vs 严格观测语义**：v4 资格用 pytest 通过/失败，本分析器用 P+/P− 观测；607/3228 上两者结论不同。没有自动对齐机制。
7. **同行多语句的删除连带**：审计只标记 `collateral_risk`，不阻止。

这些是**限制**，不是本轮已证实的失败。除 3310 的验证接口限制外，其余都没有造成错误关系。

### Q3. 找到多少个有真实执行证据的困难案例？

- 审查 5 个，全部有真实执行证据。
- 确认并复现的关系：2 个（3371 对象属性；2482 跨函数返回值），且都与 v4 的 DESIGNED promoted 证据一致。
- 有真实执行证据但无法判定：1 个（3310，循环；删除候选后超时）。
- A/B 候选被否决：2 个（607 协同；3228 回退），v4 自身判 NO_LOCAL_EFFECT，且删除候选会让上游测试失败。
- 确认的 A 类：0；B 类：0；真实算法失败：0。

### Q4. 这些失败是否需要新算法，而不是普通工程修复？

**否。**

- 3228 的 2 条错误 MSMS：关系分析 bug，`exposed_any` guard 即可修复（已修）。
- 607/3228 与 v4 的差异：探针/测试语义口径不同，属于工程对齐，不是新语义。
- 3310：执行验证无法处理非终止；方案 1 可以证明，但当前 scorer 不接受 `PROVEN`，且改指标被禁止。因此在本轮协议下，正确输出就是 `UNVERIFIED`，不是“必须上新算法”。
- 3371/2482：现有 AST + 动态资格 + 执行验证已经解决。
- 没有观察到“语言支持/候选发现/关系分析”层面必须靠新算法才能跨过的真实失败。

### Q5. 哪个新机制最值得最小实验？

- **本轮：没有。前置条件不成立，不应启动。**
- 若未来出现满足条件的案例：**方案 1** 优先。
  - 它针对唯一有真实证据的硬限制（非终止干预 + 循环携带状态），且不引入 LLM 成本/混淆。
  - 方案 2 只有在“callee 语义无法执行、只能摘要”时才有价值；本轮没有这种失败。
- 方案 1 的最小实验也必须先解决 scorer 不接受 `PROVEN` 的问题；在该问题解决前，实验只能产出 `UNKNOWN`，不具备评测意义。

### Q6. 是否已经有理由调用 Qwen/GLM？

**没有。**

- 0 次模型调用、0 GPU。
- 观察到的失败都能确定性定位：空洞 MSMS、动态顺序、非终止干预、探针口径。
- 没有“语义歧义”型失败；模型摘要无法提供执行见证，scorer 也不会接受未验证摘要。
- 现在调用模型只会增加成本、引入混淆变量，并可能污染开发/评测隔离。

---

## 6. 最终决议

### NO-GO

- 不启动新的语义机制（方案 1 不实现）。
- 不实现/不调用 Qwen/GLM 实验（方案 2 仅保留接口）。
- 不扩大正式测试集；不修改 scorer、指标或 Full MACE 历史。
- 不声称全局关系完备性；不把开发/诊断案例说成独立测试集；不把 DESIGNED 测试说成上游漏检。

### GO（仅限工程冻结）

- 将 `mace-reliable-ast-analyzer 1.0.1` 冻结为后续可靠分析基线。
- 下一轮如继续，只做普通工程项：
  1. 异常溯源标记（区分正常 raise 与共删诱发异常）；
  2. 跨文件候选发现（仅在出现真实案例时）；
  3. 探针—v4 资格一致性检查（解释测试通过语义与观测语义的差异）；
  4. 非终止干预的显式 `UNVERIFIED` 记录（已完成）。
- 这些不是新算法，也不是本轮成果。

### 停止

本文档完成后停止本轮工作。不调用模型、不使用 GPU、不修改历史实验。

---

## 7. 复现命令与产物

```bash
cd <local-path>
python -m reliable_ast_v1.regress       # 5 个开发任务
python -m reliable_ast_v1.run_cases     # 5 个诊断案例
python -m pytest -q                     # 现有测试
```

产物：

- `reliable_ast_v1/runs/regression.json`
- `reliable_ast_v1/runs/cases.json`
- `reliable_ast_v1/runs/case_<case_id>.json`
- `reliable_ast_v1/analyzer.py`（1.0.1 的三处修正）
- `reliable_ast_v1/__init__.py`（版本号）

关键修正位置：

- `_eligibility`：P− 侧不再使用源码行号；只用“只在 P− 执行”的动态证据。
- `analyze_row`：`exposed_any` guard，拒绝空洞 MSMS。
- `analyze_row`：出现 `BROKEN_INTERVENTION` 且无关系时，行状态为 `UNVERIFIED`，不是 `FALSE`。
