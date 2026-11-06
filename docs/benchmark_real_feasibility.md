# 真实源码操作级掩盖可行性实验报告

- 日期：2026-11-02
- 范围：只构建和审查真实源码任务；不运行 Qwen、Full MACE 或任何性能比较。
- 产物：`benchmark_real_pilot/`、本报告。
- 结论先行：审查 18 个候选，建成 3 道真实源码题，3 道题各有 1 条执行确认的 `independent` 关系；但上游完整测试套件未执行，证据等级为 `PARTIAL_GROUND_TRUTH`。正式扩大为 Benchmark：**NO-GO**；下一轮 10 题左右的小规模试点：**有条件 GO**。

## 0. 预先固定的筛选规则

在看具体候选之前固定以下口径，避免按“模型能不能做出来”选题：

1. 每题一个目标语句 A，是单行赋值，写在函数/方法体内。
2. 后面有一条 B，对同一局部名赋值；B 的右侧不读取该名。
3. 在至少一条可执行路径上，A 到 B 之间没有读取 A。
4. A 删除后必须在某个合法输入上可观察；否则只是死存储，不进入本题。
5. B 必须能由公开输入触发，不依赖网络、GPU、私有 fixture 或真实终端。
6. 优先选上游已有测试的函数；没有直接测试时明确记为 `not_covered`。
7. 抽取必须保留目标函数体；改名、支持代码、删掉的无关方法都要记录。
8. 每题只固定审查一个 B，不把“没找到其他关系”当作不存在其他关系。

原始扫描只是候选生成器，不是结论。`scan_top_if.py` 产生 18 条，`scan_paths.py` 产生 158 条；去重并人工核对后，正式记录 18 个候选，接受 3 个，拒绝 15 个。

## 1. 审查了多少候选

- 下载并检查 7 个公开 PyPI 包：Werkzeug 2.2.3、click 8.4.1、Jinja2 3.1.3、packaging 23.1、pyparsing 3.0.9、itsdangerous 2.0.1、six 1.16.0。
- 记录 18 个候选：3 个接受，15 个拒绝。
- 拒绝原因分布：`would_be_caught`、`dead_store`、`guard_reads_A`、`rhs_reads_A`、`environment_gated`、`not_masking`。
- 完整记录见 `benchmark_real_pilot/candidates.json`。

接受率 3/18。这个数字本身说明：真实代码里“A 被下游覆盖”很容易扫到，但“覆盖后仍值得作为掩盖题、且测试没有兜住”并不常见。

## 2. 建成了几道真实源码题

建成 3 道，均为假设删除（不是历史 commit 的回滚）：

| 题 | 项目/版本 | 目标 A | 下游操作 B | 关系 |
|---|---|---|---|---|
| `real_werkzeug_url_unparse` | Werkzeug 2.2.3 | `urls.py:605` `url = s("")` | `urls.py:614` `url = s("//") + ...` | independent |
| `real_werkzeug_headerset_update` | Werkzeug 2.2.3 | `datastructures.py:2266` `inserted_any = False` | `datastructures.py:2272` `inserted_any = True` | independent |
| `real_click_truncate_visible` | click 8.4.1 | `_textwrap.py:23` `cut = 0` | `_textwrap.py:32` `cut = i` | independent |

三道题的抽取体都用 AST 与上游函数体逐语句比对，结果为 `body_equal=True`。本地行号与上游行号分开记录；详情见 `benchmark_real_pilot/provenance.json` 和 `evidence/extraction_ast_check.md`。

### 2.1 `url_unparse`

- 合法输入：5 元组 `(scheme, netloc, path, query, fragment)`。
- 掩盖见证：`("http", "example.com", "a", "q=1", "frag")`。
  - P+：`http://example.com/a?q=1#frag`
  - P−：`http://example.com/a?q=1#frag`
  - 两边都正常返回，观察相同。
- 暴露见证：`("", "", "/a", "", "")`。
  - P+：`/a`
  - P−：`UnboundLocalError: cannot access local variable 'url'`
- 关闭 B 后再比较同一见证：P+ 返回 `http:?q=1#frag`，P− 抛 `UnboundLocalError`，说明 B 单独承担了掩盖。
- A 在掩盖见证上执行，P+ 局部快照有 `url`，P− 没有；局部写存在，但被 B 覆盖。
- 上游测试：`tests/test_urls.py` 没有直接调用 `url_unparse` 或 `URL.to_url()`，记为 `not_covered`。

### 2.2 `HeaderSet.update`

- 合法输入：初始 header 列表 + 可迭代 header。
- 掩盖见证：初始 `["foo"]`，更新 `["bar"]`。
  - P+、P− 都返回 `(["foo", "bar"], [2])`，正常返回且相同。
- 暴露见证：初始 `["foo"]`，更新 `["foo", "FOO"]`（大小写重复）。
  - P+：`(["foo"], [])`
  - P−：`UnboundLocalError: cannot access local variable 'inserted_any'`
- 空 iterable 同样暴露。
- 关闭 B 后再比较掩盖见证：P+ 返回 `(["foo", "bar"], [])`，P− 抛 `NameError`，说明 B 单独掩盖 A。
- 上游测试 `tests/test_datastructures.py::TestHeaderSet::test_basic_interface` 只通过 `add()` 添加新 header，每次都会执行 B；没有空更新或全重复更新。移植该断言后 P+、P− 都通过。

### 2.3 `_truncate_visible`

- 合法输入：文本 + 可见字符预算 `n`。
- 掩盖见证：`"abcdefghij", 3`。
  - P+、P− 都返回 `"abc"`。
- 暴露见证：`"", 3` 或纯 ANSI 串 `"\x1b[31m\x1b[0m", 3`。
  - P+：`""`
  - P−：`UnboundLocalError: cannot access local variable 'cut'`
- 关闭 B 后再比较 `"abcdefghij", 3`：P+ 返回 `""`，P− 抛 `NameError`，说明 B 单独掩盖 A。
- 上游 `tests/test_formatting.py::test_wrap_text_visible_width` 的 styled long-word 用例有可见字符，B 会执行；没有空串或纯 ANSI 用例。移植该用例的前缀断言后 P+、P− 都通过。

## 3. 有几道题有执行确认的操作级掩盖关系

3 道。每题 1 条，全部是 `independent`：

- 空操作集下，P+ 与 P− 在见证输入上正常返回且观察相同；
- 只关闭 B 后，同一见证上 P+ 与 P− 出现差异；P− 抛 `UnboundLocalError` 或 `NameError`；
- B 是单元素集合，唯一真子集为空集，空集不暴露，因此满足最小性；
- A 在见证上执行，P+ 局部快照包含目标变量，P− 不包含，局部写确实发生。

没有找到 `cooperative` 或 `coexisting`，也没有做全关系枚举。因此“只有 independent”是本次审查范围的结果，不是“其他关系不存在”的证明。三道题都标为 `PARTIAL_GROUND_TRUTH`。

## 4. 为什么原测试没有暴露删除风险

| 题 | 测试缺口类型 | 具体原因 |
|---|---|---|
| `url_unparse` | `not_covered` | 上游测试树没有调用该函数或 `URL.to_url()`；路径型输入上的 P− 异常不会被测到 |
| `HeaderSet.update` | `masked` | 唯一相关测试只 `add()` 新 header，B 每次执行；空 iterable 和全重复 iterable 没测 |
| `_truncate_visible` | `masked` | 测试覆盖 styled long-word，但都有可见字符；空串和纯 ANSI 片段没测 |

这三类正对应题目要求的区分：`url_unparse` 是“改动能到输出但测试没断言/没覆盖”；后两题是“A 有局部写，但被下游 B 覆盖，测试输入恰好总走覆盖分支”。注意，这不等于“整个上游套件都通过”已由本实验执行确认，见第 6 节。

## 5. 长代码里验证器处理不了什么

现有 `benchmark_pilot/engine.py` 和 `scripts/check_open_interface.py` 主要在受控小程序上工作，真实代码暴露了四个具体阻断：

1. **只能禁用 `If`，不能禁用普通赋值。** 本题三个掩盖操作 B 都是普通赋值（`url = ...`、`inserted_any = True`、`cut = i`）。`_disable_if_lines` 和 `run_variant_pairs` 无法表达“只关闭 B”。本次新增了 `disable_statement_lines`，只替换指定行的语句为 `pass`，没有改语义。
2. **条件语法不支持真实 guard。** `validate_guard` 只允许有限节点，且常量只能是 int/bool；真实条件含 `path.startswith(s("/"))`、`self.state == State.PREAMBLE`、`value is UNSET` 这类 Call/Attribute/常量名，条件合成与 exactness 检查直接报 unsupported。即使把操作表示成 `If`，也无法复用原 Verifier 的条件检查。
3. **`_build_line_map` 只把 `If` 行和其 body 映射到一个操作。** 对普通赋值 B 没有对应表示；强行映射会把整个 `If` body 一起禁用，改变任务语义。
4. **抽取需要类状态和外部支持。** `HeaderSet` 需要 `_headers/_set/on_update`，`url_unparse` 需要两个内部 helper，ANSI 截断需要正则；整个模块还牵扯 `Context`、`Headers`、异常和导入链。若直接导入上游包，又会触发“执行外部代码”的沙箱限制。

因此本轮没有把旧 Verifier 包装成新算法，也没有改任务语义去适配它；而是用独立小 runner 做 P+/P− 和操作级检查，并把上述限制记录为正式 Benchmark 的工程债。

## 6. 实际工作量与执行成本

本轮实际完成的操作：

- 下载/解压 7 个 sdist（约 3.7 MB 压缩包），静态扫描 176 条原始命中（18 + 158，含重复）。
- 人工逐函数核对 18 个候选，接受 3 个，拒绝 15 个。
- 抽取 3 个函数体（39–132 行/文件，含支持代码），写 262 行 runner 和 216 行 frozen specs。
- 3 道题全部运行一次：**0.15 秒**（本机 Python 3.11.7，CPU，无网络，不导入上游包）。
- 上游 pytest 套件：**未执行**。原因是环境把“在下载的 PyPI sdist 内运行 pytest/导入包”判定为执行未获点名的外部代码；用户本轮没有点名具体项目和版本，因此没有绕过限制。已执行的是抽取体上的 P+/P−、操作禁用矩阵，以及 2 个移植的上游断言；`url_unparse` 没有直接上游测试可移植。
- 若由人复现，每题大约 0.75–1.5 人时（选题与覆盖核对、抽取与依赖隔离、测试移植、P+/P− 检查），不含下载与写报告；这是估算，不是计时工资数据。

## 7. 是否值得扩大为正式 Benchmark

**正式扩大：NO-GO。** 理由：

- 18 个候选中只有 3 个同时满足“真正掩盖 + 有合法见证 + 测试缺口可用”，接受率低，且 15 个拒绝原因高度集中在“测试会抓到”和“guard 读 A”。
- 3 道题都只有一条 `independent` 关系；没有 `cooperative`/`coexisting` 证据，关系覆盖太窄。
- 上游完整套件没有执行，“原版测试通过”目前只有移植断言和静态覆盖证据，证据等级不足。
- 旧 Verifier 不能直接处理普通赋值 B 和真实 guard，正式化需要先改执行/检查层，成本不低。

**小规模试点：有条件 GO。** 建议下一轮只做 10–15 题，并先满足：

1. 明确点名项目/版本并取得运行上游 pytest 的许可，或由 CI 在隔离环境执行；
2. 给 runner 增加“任意语句行禁用 + 真实 guard 求值”，不改变任务语义；
3. 每题至少保留一个掩盖见证、一个暴露见证、一个测试缺口说明；
4. 继续记录 `PARTIAL_GROUND_TRUTH`，不把“未找到其他关系”写成不存在；
5. 不把 Qwen/Full MACE 的得分用于选题或改题。

如果上述条件不能满足，则维持 NO-GO，不把 3 道题包装成“正式 Benchmark”。

## 8. 未决与 UNKNOWN

- 未执行上游完整测试套件；无法断言 3 个版本的全部测试在 P− 下通过。
- 未做全关系枚举；其他 `cooperative`/`coexisting` 关系可能存在。
- 抽取体不是整个模块；跨函数/跨文件交互未覆盖。
- 本地行号是抽取体行号，上游行号另记；重构后需重新核对。
- 未运行 Qwen、Full MACE 或任何模型；本轮没有性能结论。
- `url_unparse` 的 `not_covered` 是“测试树无直接调用”的静态结论，不等于全仓库绝对没有间接路径；这里只记录已检查的测试目录。
- 三个任务都只覆盖单进程、无 I/O、确定性输入；真实程序中的文件、网络、环境变量路径未进入本轮。

## 9. 复现

```bash
cd <local-path>
python -I benchmark_real_pilot/run.py
```

输出：`benchmark_real_pilot/results/results.json`。摘要应为：

```text
candidates_reviewed: 18
real_tasks_built: 3
tasks_with_verified_masking_relation: 3
relation_counts: {"independent": 3}
upstream_suite_executed: false
```
