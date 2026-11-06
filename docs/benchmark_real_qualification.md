# 真实源码 Benchmark：资格确认与掩盖机制多样性实验

- 日期：2026-11-02
- 分支：`realbench-verifier-v2`（从 `benchmark-pilot` 的 `379fe11` 建立，未提交）
- 范围：只做资格确认、验证器独立分支、少量新机制候选；不运行 Qwen、Full MACE 或任何模型比较，不修改 M1–M6 历史数据。
- 结论先行：现有 3 道题中只有 **1 道**通过“上游原测试在 P− 下仍通过且测试确实执行 A”的资格确认；另外 2 道被上游测试直接抓到。新找到 **1 个**不同于“单次直接覆盖”的真实机制（`coexisting {B,C}`），但该函数同样被上游测试抓到，不能作为 Benchmark 题。因此独立 Benchmark 试点仍为 **NO-GO**。

## 0. 口径与“资格确认”定义

本轮把“通过上游原测试资格确认”定义为同时满足：

1. 上游版本、源码和抽取函数体一致；
2. 在隔离环境中运行上游 test suite，P+ 通过；
3. 同一 suite 在 P−（只把目标 A 替换为 `pass`）下仍通过；
4. 至少有一个上游测试在执行时确实命中 A 的行；
5. 该测试的通过不是因为 A 在更早的路径上根本没执行。

第 4 条用 `sys.settrace` 逐测试记录行命中；第 5 条单独检查 `target_A_hit`。`nonexecuted_n_zero` 这类“A 未执行”的见证不计入掩盖关系。

## 1. 三道既有题的资格确认结果

### 1.1 结果表

| 题 | A / B 行号（上游 / 本地） | 上游 P+ | 上游 P− | A 是否被上游测试执行 | 资格 |
|---|---|---|---|---|---|
| click `_truncate_visible` | 23 / 27；B 32 / 36 | 1562 passed, 94 skipped, 1 xfailed | **同样全部通过** | 是，1 个测试命中 A | **通过（1/3）** |
| Werkzeug `HeaderSet.update` | 2266 / 62；B 2272 / 68 | 816 passed | **1 failed**（`test_set_header`） | 是，3 个测试命中 A | 不通过，`would_be_caught` |
| Werkzeug `url_unparse` | 605 / 48；B 614 / 57 | 816 passed | **collection error**，0 tests run | 是，collection 时执行到 A 的后续读取 | 不通过，`would_be_caught` |

click 的完整输出为 `1562 passed, 94 skipped, 30000 deselected, 1 xfailed`；`30000 deselected` 来自 click 自己的 `addopts = -m 'not stress'`，不是本轮额外排除。P− 的统计与 P+ 完全相同。

用 v2 重跑三道题的抽取体，关系与旧记录一致：三道题的掩盖见证上均为 `independent [B]`，A 命中的基线行为 `target_A_hit=true`；click 的 `nonexecuted_n_zero` 仍为 `target_A_hit=false`，因此不作为关系见证。完整结果在 `out/verifier_v2_real_tasks.json`。

抽取语义方面，三道旧题的逐 AST 函数体比较均为 `body_equal=True`（忽略函数名、行号和注释；记录在 `benchmark_real_pilot/evidence/extraction_ast_check.md`）：`url_unparse` 上游 595 行、`HeaderSet.update` 2261 行、`_truncate_visible` 11 行。版本取自对应 sdist（Werkzeug 2.2.3、click 8.4.1），sdist 哈希记录在 `benchmark_real_pilot/provenance.json`。所有 P−/操作干预都只把目标行的语句替换为 `pass`，保留行号和其余代码；不是回滚历史 commit，也不改函数签名。

### 1.2 Werkzeug 两个失败的具体原因

- `HeaderSet.update`：P− 下 `pytest tests -q -m "not dev_server"` 得到 `1 failed, 815 passed`。失败为 `tests/test_http.py::TestHTTPUtility::test_set_header`：该测试先构造 `HeaderSet(['foo', ...])`，再执行 `hs.add("Foo")`；`key in self._set` 为真，循环内的 B 不执行，随后 `if inserted_any` 读取未绑定的局部名，抛 `UnboundLocalError`。因此 A 的删除被上游原测试直接抓到。
- `url_unparse`：P− 下 `tests/test_send_file.py` 在 **collection** 阶段失败。该模块顶层执行 `EnvironBuilder().get_environ()`，走到 `iri_to_uri` → `url_unparse`，最终在 `url += path` 处抛 `UnboundLocalError`。因此“旧记录里的 `not_covered`”是静态搜索漏掉了模块导入路径；新的上游执行证据覆盖旧结论。该题不是“测试没覆盖”，而是“测试在收集阶段就抓到”。

### 1.3 上游环境的限制

Werkzeug 的完整 suite 在本机 Windows 上有 23 个 dev-server 相关失败/错误（15 failed、8 errors，均为 `ConnectionRefusedError`），见 `benchmark_real_pilot/qualification/out/upstream_runs_full_suite.json`。因此正式比较使用 `-m "not dev_server"` 的适用套件（24 deselected），并在报告中保留完整套件结果，未把环境失败算到任务或模型头上。P+ 适用套件为 `816 passed, 24 deselected`，P− 结果如上。

## 2. 哪些题只有本地/移植证据

- `real_werkzeug_headerset_update`：原记录只有移植的 `test_basic_interface_add`。该移植断言在 P− 下确实通过，但完整上游套件中的 `test_set_header` 会失败。旧 `upstream_test_status = masked` 已被本轮资格证据推翻。
- `real_werkzeug_url_unparse`：原记录为 `not_covered`，依据是对测试树的静态搜索；本轮实际 collection 表明它被 `test_send_file.py` 执行并抓到。旧 `not_covered` 同样被推翻。
- `real_click_truncate_visible`：原记录只有移植断言；本轮补跑了完整上游 click 套件，P+/P− 均通过，且有一个上游测试命中 A。它不再只是“本地/移植证据”，但仍是单测试、单见证证据。

所以：**2/3 道题在旧记录中只有本地/移植证据；这 2 道经上游执行后均不合格。** 只有 click 进入“上游原测试资格通过”一栏。

## 3. 四种情况的区分

| 情况 | 本轮实例 | 证据 | 是否可算掩盖 |
|---|---|---|---|
| A 从未执行 | click `nonexecuted_n_zero`（`n=0` 提前返回） | `target_A_hit=false`，base row 仍可能显示 MASKED | **不算**，必须排除 |
| A 执行，变量绑定被下游覆盖 | click、HeaderSet、url_unparse、`is_resource_modified` 的 `mask_b_c` | A 行命中，P+/P− 输出相同；关闭覆盖操作后 P− 抛 `UnboundLocalError` | 算，单见证 |
| A 执行，具体值变化被掩盖 | 本轮未隔离出实例 | 现有见证都是“覆盖发生在读取之前”，不是“读取后结果被抵消” | 不声称 |
| 断言没有观察已存在的输出差异 | 本轮未发现 | click 的命中测试输入在 P+/P− 下 `wrap_text` 输出逐字符相同（见 `out/click_visible_width_compare.log`）；Werkzeug 两个测试直接失败 | 不声称 |

这个区分很重要：验证器把“P+ 与 P− 相同”记为 MASKED，但只有 `target_A_hit=true` 才能说明 A 真的执行过。`nonexecuted_n_zero` 只是“未执行”，不能拿来当掩盖证据。

## 4. 新机制搜索结果

### 4.1 搜索范围

- 对 Werkzeug 2.2.3、click 8.4.1、Jinja2 3.1.3 等已下载源码做静态扫描：同一函数内同一局部名至少 3 次赋值，得到 224 个函数级命中，保存在 `out/static_multi_assign_scan.json`。
- 人工先筛 3 个形状不符的函数并记录拒绝原因；只对 1 个候选做完整 P+/P−、操作干预和上游测试验证。
- 未按 Qwen/MACE 的可解性选题，本轮也没有运行它们。

被筛掉的 3 个形状：

| 函数 | 变量 | 拒绝原因 |
|---|---|---|
| Jinja2 `parser.parse_primary` | `node` | 赋值分布在互斥分支，没有“单一初始 A + 下游覆盖”；删一个分支赋值只会在该分支 `UnboundLocalError` |
| Werkzeug `routing._parse_rule` | `content` | 初始值会被后续读取和拼接（如 `content +=`），不满足“A 到 B 之间不读取 A” |
| click `core.get_help_extra` | `default_string` | 赋值全在互斥分支，没有支配性的初始 A，也没有下游覆盖操作 |

### 4.2 找到的真实新机制：`coexisting {B,C}`

候选：Werkzeug 2.2.3 `src/werkzeug/sansio/http.py::is_resource_modified`（上游 17–94 行；抽取文件 `benchmark_real_pilot/qualification/candidates/werkzeug_is_resource_modified.py`）。

- A（上游 49，本地 43）：`unmodified = False`
- B（上游 71，本地 65）：`unmodified = True`
- C（上游 78，本地 72）：`unmodified = parse_etags(if_range.etag).contains(etag)`
- D（上游 85，本地 79）：`unmodified = if_none_match.contains_weak(etag)`
- E（上游 92，本地 86）：`unmodified = not if_match.is_strong(etag)`

抽取函数体与上游逐 AST 比较（忽略 docstring）为 `body_equal=True`。上游文件 SHA-256 为 `9379d110…aced0`，抽取文件为 `fb9b101e…f5d8e`。

关键见证 `mask_b_c`：同时提供匹配的 `If-Range`/`ETag` 和一组满足时间条件的 `If-Modified-Since`/`Last-Modified`。B 和 C 先后执行，都写入 `True`，最终返回 `False`。

| 干预 | P+ | P− | 状态 |
|---|---|---|---|
| 不关闭操作 | `False` | `False` | MASKED |
| 只关闭 B | `False` | `False` | MASKED |
| 只关闭 C | `False` | `False` | MASKED |
| 关闭 B+C | `True` | `UnboundLocalError` | EXPOSED |
| 仅保留 B+C | — | — | MASKED（最小性检查） |

因此 `{B,C}` 是该见证上合法的 `coexisting` 关系：单独关闭任何一个仍掩盖 A，两个一起关闭才暴露；两个真子集（`{B}`、`{C}`）都仍 `MASKED`，满足最小性。验证器 v2 给出的结果是 `VERIFIED`、`minimal=true`、`scope=single_witness`。

这不是“一个 B 直接覆盖 A”的重复包装：两个条件赋值位于不同分支，单独任一个都能让删除不可观察；只有两个同时被关掉，`unmodified` 才没有绑定。它也不同于 `independent`，因为单个操作的关闭并不暴露 A。

### 4.3 为什么仍拒绝作为 Benchmark 题

该机制真实、可独立检查，但 **不能出题**：上游原测试会抓到删除。

- 目标测试 P+：`test_is_resource_modified` 和 `test_is_resource_modified_for_range_requests` 均为 `2 passed`。
- 同一两个测试 P−：`2 failed`，都在 `return not unmodified` 处抛 `UnboundLocalError`。
- 适用套件 P−：`34 failed, 782 passed, 24 deselected`；失败分布在 `test_http.py`、`test_send_file.py`、`test_wrappers.py`、`test_shared_data.py` 等。
- 适用套件 P+：`816 passed, 24 deselected`。

所以它的定位是“机制存在性证据”，不是可用题。`cooperative`（必须两个操作同时存在才掩盖，且任何真子集都不掩盖）在本轮没有找到；不能把 `coexisting` 写成 `cooperative`。

## 5. 验证器 v2 能否安全检查新机制

可以，且已在独立分支实现并测试。它是评测基础设施，不是 MACE 算法贡献。

新增 `benchmark_pilot/verifier_v2.py`，关键能力：

- 用 AST 把指定行语句替换为 `pass`，支持普通赋值、`AnnAssign`、`AugAssign`、`Expr`、`Return` 等，不再只能处理 `If`；
- 显式 `operation name → source line` 映射；拒绝重复名/重复行、目标行兼作操作行、无语句行、一行多语句、跨行非 `If` 语句；
- 用 `sys.settrace` 检测目标 A 在 baseline 是否真的执行；
- 运行 P+/P− × 操作启用/禁用矩阵，区分 `MASKED`、`EXPOSED`、`INVALID_INPUT`、`ILLEGAL_INTERVENTION`、`UNDECIDABLE`；
- 对 `independent`/`cooperative`/`coexisting` 做最小性检查；任何必要的子集检查不可判定时返回 `UNDECIDABLE`，不静默当作 false；
- Guard 使用受限 AST 解释器，只允许 int/bool 常量、名字、布尔/算术/比较，不允许 Call/Attribute/Subscript/Lambda，不调用 `eval`；
- `verify_guard_witness` 明确标 `scope=witness`；只有 `verify_guard_domain` 才报告有限域上的 sound/complete/exact，并注明“不是全输入证明”。

本轮验证：

- `tests/test_verifier_v2.py` 12 个测试通过，覆盖普通赋值禁用、非法输入、非法干预、`eval` 禁用、Guard 拒绝、witness/domain 区分、旧受控任务回归。
- 旧测试 + 新测试共 `55 passed`：`tests/test_pilot_evaluate.py tests/test_open_ops_discovery.py tests/test_verifier_v2.py`。
- 新候选的完整结果在 `out/verifier_v2_is_resource_modified.json`，重跑脚本为 `benchmark_real_pilot/qualification/verify_round2_candidate.py`。

限制仍然明确：`coexisting {B,C}` 只是 `mask_b_c` 这个见证上的结论，不是全输入证明；验证器能安全检查“这个见证上的关系”，不能替我们证明整个 Guard 条件或所有输入。受限 Guard 解释器本身也只支持 int/bool 表达式，不能求值含 `Call`/`Attribute` 的真实条件（如 `if_range.etag`）；本题的验证走的是显式行干预，不依赖 Guard 求值。也就是说，`scope=single_witness` 与“整个 Guard 条件正确”是两件事，报告中不把前者写成后者。

## 6. 五个问题的直接回答

1. **现有三道题中有几道通过上游原测试资格？** 1/3：只有 click 8.4.1 `_truncate_visible`。Werkzeug `HeaderSet.update` 和 `url_unparse` 都被上游测试在 P− 下抓到。
2. **哪些只有本地/移植测试证据？** `HeaderSet.update` 和 `url_unparse`。前者旧证据是移植断言，后者旧证据是静态 `not_covered`；本轮上游执行都推翻了旧状态。
3. **是否找到至少一个不同于直接覆盖的真实掩盖机制？** 是，`is_resource_modified` 的 `coexisting {B,C}`；但它被上游测试抓到，不能当题。
4. **验证器能否安全检查新机制？** 能。v2 已在不使用 `eval` 的情况下验证该关系及其最小性，且明确只报告单见证结论。
5. **条件是否足以开始独立 Benchmark 试点？** **NO-GO。** 上游资格只有 1/3；唯一的新机制题被上游套件抓到；`cooperative` 仍未找到。验证器变强不能弥补任务真值和测试缺口的不足。

## 7. 下一步（如果继续）

只有在找到新的真实任务，并同时满足以下条件时才重新评估 GO：

1. 上游测试确实执行 A，但 P− 的完整适用套件仍通过；
2. 至少有一个非 `independent` 的关系（`coexisting` 或 `cooperative`）在该任务上被独立验证；
3. 关系有明确见证、暴露见证、最小操作干预证据；
4. 上游测试缺口有具体解释，不使用移植断言替代完整套件；
5. 不根据 Qwen/MACE 的得分选题或改题。

本轮没有模型分数，因此也不能得出“MACE 优于 Qwen”的结论。当前结论仅是：现有真实源码任务不足以支撑独立 Benchmark，维持 **NO-GO**。

## 8. 复现与产物

```bash
cd <local-path>

# 上游资格（会复制 sdist 到隔离目录；不修改原 sdist）
python benchmark_real_pilot/qualification/run_upstream.py

# 新机制候选（使用 Werkzeug 测试 venv；脚本内部把上游 src 加入 sys.path）
<local-path> \
  benchmark_real_pilot/qualification/verify_round2_candidate.py

# 验证器回归
python -m pytest tests/test_pilot_evaluate.py tests/test_open_ops_discovery.py \
  tests/test_verifier_v2.py -q
```

主要产物：

- `benchmark_real_pilot/qualification/out/upstream_runs.json`
- `benchmark_real_pilot/qualification/out/upstream_runs_full_suite.json`
- `benchmark_real_pilot/qualification/out/three_task_qualification.json`
- `benchmark_real_pilot/qualification/out/verifier_v2_real_tasks.json`
- `benchmark_real_pilot/qualification/out/verifier_v2_is_resource_modified.json`
- `benchmark_real_pilot/qualification/out/click_visible_width_compare.log`
- `benchmark_real_pilot/qualification/candidates_round2.json`
- `benchmark_real_pilot/qualification/out/static_multi_assign_scan.json`
