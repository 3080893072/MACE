# AST 能力边界审计（Phase 1–2）

审计日期：2026-11-03  
审计对象：`benchmark_baseline/ast_method.py` 与 `benchmark_baseline/runs/ast/*`  
冻结状态：未修改任何任务、隐藏答案、历史评分或原始日志。所有独立干预记录写入
`benchmark_baseline/audit/jinja_interventions.json`。

## 0. 结论摘要

1. AST 的真实能力边界是：**同文件、同裸变量名赋值 + P+ 执行行过滤 + 候选子集枚举**。
   它没有调用图、没有对象状态、没有异常/循环状态、没有分支条件分析。
2. 五个开发题中，AST 在 4 题上找到了参考 U 中的真实掩盖操作；在 jinja2 上提交了
   `loaders.py:119`。独立执行检查表明 **119 不是掩盖操作，137 才是**。因此六个
   `UNVERIFIED` 不是评分器缺陷，而是 AST 选中了语义错误的操作。
3. 独立分类：
   - `jinja2 loaders.py:119` → **FALSE**（不是合法掩盖关系；它是初始化语句，
     删除后 P− 直接 `UnboundLocalError`）。
   - `jinja2 loaders.py:137` → **VALID**（真实掩盖操作；单独删除即暴露）。
4. 静态候选集并不缺 137：137 本来就在 `candidate_operations` 返回的列表里。
   失败发生在**执行过滤/条件分析**阶段：AST 只用 P+ 的 trace，而 137 只在 P− 路径执行。
5. 1531.1 秒中约 75–95% 花在 `trace_lines.py` 的 `sys.settrace` 上（按输入数外推
   约 84%）；它不是变体构建，也不是探针执行。`trace_lines.py` 对每个 line event 调用
   `os.path.realpath`，单次 trace 实测 20.1–41.8 秒（单输入样本；早期 bind 样本 53.6 秒）。
6. AST 不回答 `test_gap`（`not attempted`），所以 node-ID 映射错误不影响 AST 分数；
   它只影响 Direct/Validator 的解释。

## 1. 审计方法

- 只读公开包：`benchmark_real_v3/release/PUBLIC/`。
- 独立干预：直接用 `variant_lab.build_variant` 构造 P+、P− 及删除变体，运行公开探针，
  记录 `returncode`、观察值和目标文件执行行。
- 隐藏参考仅在独立执行分类完成后用于对照 U，不用来提出候选。
- 原始 AST 日志与分数保持不变；本审计只新增文件。

复现：

```bash
python -m benchmark_baseline.audit_jinja_interventions
```

产物：`benchmark_baseline/audit/jinja_interventions.json`。

## 2. Q1：`jinja2 loaders.py:119` 是合法掩盖关系吗？

源码上下文（`jinja2-3.1.3/src/jinja2/loaders.py`）：

```python
119            code = None
...
132            code = bucket.code                     # A
...
136        if code is None:
137            code = environment.compile(source, name, filename)
```

独立执行结果（输入 `{"template": "{{ 6*7 }}"}`，公开探针）：

| 条件 | 删除 | P+ 观察 | P− 观察 | 结论 |
| --- | --- | --- | --- | --- |
| P+ | 无 | return `42` | — | 基线 |
| P− | A(132) | — | return `42` | 掩盖成立 |
| P+ del119 | 119 | return `42` | — | 119 在 P+ 不影响 |
| P− del119 | 119 | — | `UnboundLocalError: code` | 删除 119 使 P− 崩溃 |
| P+ del137 | 137 | return `42` | — | 137 在 P+ 不执行 |
| P− del137 | 137 | — | `AttributeError: 'NoneType' ...` | 删除 137 使 P− 崩溃 |
| P− del119+137 | 119,137 | — | `NameError: code` | 两条初始化/回退都被删 |

执行行证据（同一输入）：

- P+ 执行 `119, 132, 136, 142`，**不执行 137**。
- P− 执行 `119, 136, 137, 142`，**执行 137**。

分类：

- **119 = FALSE（作为掩盖关系）**。它在 A 之前执行，只把 `code` 初始化为 `None`；
  它不接收、不覆盖、不吸收 A 的差异。删除它导致 P− 崩溃，是“删掉必需初始化”的
  执行伪影，不是“删掉掩盖操作”。
- **137 = VALID**。P+ 在正常（缓存命中）输入上走 `bucket.code`，P− 在 A 删除后走
  `environment.compile(...)`；137 写入的编译结果正是 P− 侧维持等价的原因。删除 137
  后 P− 无法构造模板代码，因此暴露。
- 形式化提醒：若把 119 也放进候选宇宙 U，按纯执行定义“删除 119 使 P− 崩溃”确实会被
  算作 breaking。这说明 **MSMS/MMBS 的纯执行定义对 U 的语义边界敏感**；U 不能只按
  “同名赋值”机械扩张，必须排除 A 之前的初始化/前置配置。参考 U 只含 137 是正确的。

## 3. Q2：六个 U-out 关系为什么是 `UNVERIFIED`？

`benchmark_baseline/runs/ast/jinja2_bytecode_cache_read/work.json`：

- `candidate_operations` = `[119, 137]`。
- 五个输入中，`candidates_executed` 都只有 `[119]`；`a_executes` 都为 true。
- 三个 masked 输入各自枚举子集，得到 `msms=[[119]]`、`mmbs=[[119]]`。
- 提交 3 组 MSMS + 3 组 MMBS，共 6 条，全部指向 119。

评分器状态：

```text
operation is outside the declared candidate universe; the scorer cannot perform that exact intervention
```

这不是“评分器不会验证”，而是：

1. 119 不在参考 U（参考 U 只有 137）；
2. 独立执行已经证明 119 不是掩盖操作；
3. 所以评分器拒绝是**正确的**，不能把六条 UNVERIFIED 解释成 AST 的“待验证正确关系”。

## 4. Q3：候选集 U 是否不完整？

五个开发题对照（隐藏参考仅在分类后读取）：

| 任务 | 参考 U | AST 静态候选列表是否含 U | AST 实际提交 | 结果 |
| --- | --- | --- | --- | --- |
| jinja2_bytecode_cache_read | 137 | 是（含 119、137） | 119 | 错 |
| werkzeug_bind_server_name_lower | 219 | 是（含 219 等 5 条） | 219 | 对 |
| werkzeug_filestorage_stream_name | 2924 | 是（含 2924 等 4 条） | 2924 | 对 |
| werkzeug_get_host_default_empty | 85, 87 | 是（含 85/87 等 5 条） | 85, 87 | 对 |
| werkzeug_secure_filename_ascii_filter | 227–229 | 是（含 227–229 等 4 条） | 227–229 | 对 |

结论：

- **静态枚举不缺 U**。137 在 AST 的静态列表里。
- 缺的是**执行侧候选集**：`candidates_executed` 只由 P+ trace 决定，P− 独有的回退路径
  被排除。
- 因此这是 candidate filtering / condition analysis 的缺陷，不是“没有找到 137 这个
  赋值语句”的缺陷。

## 5. Q4：重复枚举、无效干预、重复执行

### 5.1 重复关系

AST 共 36 条 claims，30 条 `WITNESS_VERIFIED`，但只有 15 条唯一关系获得 credit：

| 任务 | claims | verified | credited unique | 重复原因 |
| --- | ---: | ---: | ---: | --- |
| jinja2 | 8 | 2 | 1 | 2 条 exposing 同一关系；6 条 U-out 重复 |
| bind | 8 | 8 | 3 | 3 组 219 重复 |
| filestorage | 6 | 6 | 3 | 2 组 2924 重复 |
| get_host | 7 | 7 | 5 | 85 重复 |
| secure | 7 | 7 | 3 | 3 组 227 重复 |
| 合计 | 36 | 30 | 15 | 15 条重复 credit |

这是“多输入重复提交同一关系”，不是错误；但 claim 数会高估实际能力。评分器按 relation key
去重，重复不增加 credit。

### 5.2 无效干预

- 五个开发题中，所有变体构建语法合法，未出现构建失败。
- 但存在结构性风险：`candidate_operations` 在整个文件收集同名赋值，`_build` 会**全局删除**
  这些行。若不同函数共享变量名，删除可能破坏与 A 无关的代码。开发题中 bind 的 219/231
  就来自另一个函数，只是子集验证恰好选中了 219。
- `_assignment_name` 只接受 `ast.Name`：`self.x = ...`、`obj[i] = ...` 完全不会成为候选。
- 因此“无效干预”在本轮未实际发生，但并非结构上不可能。

### 5.3 重复执行

- 变体按删除集合缓存（`builds` 统计唯一 root），同一删除集合不会重复构建。
- 但每个 masked row 的子集枚举都会重新执行 `EMPTY` 子集（plus/minus 基线），这与外层
  输入循环已经执行过的同一变体+输入重复。最多 3 个 masked row × 2 侧 = 6 次重复探针/
  题。相对 trace 成本可忽略，但属于可消除的工程浪费。

## 6. Q5：1531 秒花在哪？

AST 日志没有逐步计时字段，但每个题固定“每个输入一次 P+ trace”。按输入数把总时间分解，
并用独立单次 trace 实测校准（`benchmark_baseline/runs/ast/trace_timing.json`）：

| 任务 | 输入/ trace 次数 | wall (s) | 单次 trace 实测 (s) | 外推 trace (s) | trace 占比下限 | 变体构建 | 备注 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| jinja2 | 5 | 0.009 | 20.1 | ~101（重跑估计） | — | 4 | 本次运行 `resumed=true` |
| bind | 12 | 661.826 | 41.8（input 0） | ~502 | ≥76% | 8 | 输入 0 的 trace 较短；早期样本 53.6 s |
| filestorage | 5 | 241.596 | 35.2 | ~176 | ≥73% | 8 | |
| get_host | 6 | 274.834 | 36.1 | ~217 | ≥79% | 14 | |
| secure | 8 | 352.835 | 35.5 | ~284 | ≥81% | 16 | |
| 合计 | 36 | 1531.1 | — | ~1280 | ~84% | 50 | 不含 jinja2 重跑 |

独立实测：

- `trace_lines.py` on jinja2：单次 18.6–20.1 s；同样输入用高效 tracer
  （`diff_trace.py`）0.27 s/次。
- `trace_lines.py` on werkzeug bind：单次 41.8–53.6 s（随输入和机器负载变化）。
- 因此 tracing 是主导项，但**精确占比随输入变化，范围约 75–95%**；变体构建和探针
  只占小头（单题 build 0.07–0.20 s，probe 0.27–0.40 s）。
- 根因：`trace_lines.py` 在**每一个 line event** 上调用
  `os.path.realpath(frame.f_code.co_filename)`，对所有被调用帧都执行；这是纯工程开销，
  不是算法必要成本。

jinja2 的 0.009 s 是 `resumed=true`，不能与其它题直接比较；若重跑，预计约 100–105 s。

## 7. Q6：对循环、异常、跨函数状态、对象状态、控制前置条件的支持

| 能力 | AST 现状 | 证据/限制 |
| --- | --- | --- |
| 循环状态 | 只记录执行过的行集合，不记录迭代次数、循环变量值或循环携带状态 | `trace_lines.py` 只输出 `lines` 集合；同一行在循环中执行多次也只记一次 |
| 异常 | 没有 try/except 建模；P+ trace 与 P− trace 不区分异常路径；探针异常只作为观察值 | `_observe` 只看 returncode/dict；`_trace` 返回行集合，异常路径无状态 |
| 跨函数状态 | 能收集同文件其它函数的同名赋值，但没有调用图、参数/返回值传播或跨文件分析；删除是全局的 | bind 的 219 来自 `Map.bind`，AST 只靠子集验证选中，不能解释调用顺序 |
| 对象状态 | 不支持：`_assignment_name` 只接受 `ast.Name`，拒绝 `self.x`、`obj[i]` | `ast_method.py:105–118` |
| 控制前置条件 | 不支持：候选只按 P+ 是否执行过滤，不看分支条件、不可达路径或 P− 独有路径 | jinja2 137 是直接反例；bind 219 的静态行号在 A 之前，但动态在 A 之后 |

## 8. Q7：`test_gap` 的 node-ID 映射错误是否影响解释？

- AST 的 `work.json` 对每题都写：
  `"not attempted: this baseline targets operation relations, not per-test classification"`。
  AST 没有提交任何 test_gap 答案，因此 AST 的分数不受映射错误影响。
- 受影响的是 Direct/Validator 基线：
  - jinja2：模型用 `TestBytecodeCache`，真值是 `TestByteCodeCache`（大小写不一致）。
  - bind：模型给裸函数名，真值是完整 nodeid。
  - filestorage：模型给 `TestFileStorage::test_filename_is_set`，不在真值 10 个测试中。
  - get_host：模型未作答。
  - secure：唯一可映射的答案把 `masked` 判成 `assertion_gap`，是错的。
- 所以 `test_gap_correct: 0` 的正确解释是 **0/1 可映射答案正确**，不是 0/5 准确率；
  更不能用它推断 AST 的能力。

## 9. Phase 2：真实算法缺陷案例

### F1 — jinja2 bytecode cache fallback 未被发现

| 字段 | 内容 |
| --- | --- |
| A | `src/jinja2/loaders.py:132` `code = bucket.code` |
| 真实掩盖操作 | `src/jinja2/loaders.py:137` `code = environment.compile(source, name, filename)` |
| AST 是否提出 | 静态候选列表提出（137 在其中）；实际提交未提出 |
| 失败阶段 | **候选执行过滤 + 条件分析**：只用 P+ trace；137 只在 P− 执行 |
| 是否评分器限制 | 否。评分器 U 只有 137，119 被拒是正确的；独立执行已证明 119 非掩盖 |
| 语言/接口不支持 | 否。137 是普通赋值，现有执行干预接口完全可删 |
| 可复现证据 | `benchmark_baseline/audit/jinja_interventions.json` |
| 常规工程能否修复 | 能。见下 |

最小工程修复（无需新算法）：

1. 候选必须位于 A 的**动态下游**：在 P+ trace 中首次执行位置晚于 A；对 P− 独有回退，
   要求同函数且源码行号晚于 A。
2. 候选执行集合取 **P+ ∪ P−**，而不是只看 P+。
3. 排除 A 之前的初始化（119 自然被排除）。
4. 仍用现有单操作干预验证。

在五个开发题上，这一修复把 jinja2 的 119 替换为 137；不改变其它四题。

### F2 — 跨函数/静态行号陷阱（结构性，非本轮失分）

bind 的真实掩盖操作是 `map.py:219`，源码行号在 A（307）之前，但运行时在 A 之后。
任何“只保留源码行号 > A”的静态过滤都会漏掉它。开发题里 AST 没漏，是因为它没有按行号
过滤；但这说明“下游”必须按**动态执行顺序**判断，不能按静态行号。

### 是否宣布新算法问题？

不。当前证据支持的结论是：

- 一个明确的 candidate-filtering 缺陷（F1）；
- 一个跨函数/动态顺序的结构性限制（F2）；
- 没有证据表明需要“差异引导”这种新机制；F1 用常规过滤即可修复。

这正是 Phase 3 的前提：可以做一个最小差异引导实验，但必须与“仅修过滤”的工程对照公平比较。

## 10. 附：独立干预原始表

完整 JSON 见 `benchmark_baseline/audit/jinja_interventions.json`。关键观察：

| 条件 | input 0 | input 1（cached_source 不匹配） | input 3（for 循环模板） |
| --- | --- | --- | --- |
| P+ | return 42 | return 2 | return 012 |
| P− | return 42 | return 42 | return 012 |
| P+ del119 | return 42 | return 2 | return 012 |
| P− del119 | UnboundLocalError | UnboundLocalError | UnboundLocalError |
| P+ del137 | return 42 | return 2 | return 012 |
| P− del137 | AttributeError | AttributeError | AttributeError |
| P− del119+137 | NameError | NameError | NameError |

`P+ del137` 全部正常，证明 137 在 P+（缓存命中路径）上根本不承担作用；
`P− del137` 全部崩溃，证明它是 P− 侧唯一的回退路径。两者一起构成 137 的 VALID 证据。
