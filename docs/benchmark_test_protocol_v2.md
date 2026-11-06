# 真实源码 Benchmark：测试组织与运行协议 v2

- 日期：2026-11-02
- 范围：只修改真实源码 Benchmark 的测试选择、执行与资格记录方式。
- 未改动：MACE 核心算法、Agent、Qwen/MACE 模型运行、M1–M6 历史结果、历史实验日志、既有三题的任务定义、A/B 行、输入域与抽取代码。
- 未创建新题，未扩大 Benchmark，未做模型比较。

本轮把原先混在一起的“项目全量测试”和“当前任务相关测试”拆成两个独立概念：

- **`T_task`**：从项目原始测试中选出的、与目标函数/目标 A/相关路径直接相关的小测试集。日常 Benchmark 只跑它。
- **`T_project`**：项目适用的原始测试套件。只在建题/资格确认时完整跑一次并缓存，用于记录项目真实测试行为。

关键约束：`T_task` 必须在查看 P− 结果之前冻结；选择只依据源码关联、原测试结构和 P+ 覆盖。P− 通过/失败绝不能反向增删测试。

## 1. 产物与复现命令

新增文件：

- `benchmark_real_pilot/protocol_v2/config.py`
- `benchmark_real_pilot/protocol_v2/selection.py`
- `benchmark_real_pilot/protocol_v2/runner.py`
- `benchmark_real_pilot/protocol_v2/run.py`
- `benchmark_real_pilot/protocol_v2/task_selection.json`（P− 之前冻结的 T_task，不含 P− 结果）
- `benchmark_real_pilot/protocol_v2/task_runs/*.json`（每个题的 T_task P+/P− 原始结果）
- `benchmark_real_pilot/protocol_v2/task_manifest.json`（最终清单，含 P+/P−、标签、范围和限制）
- `benchmark_real_pilot/protocol_v2/project_suite_cache.json`（按源码/环境/测试范围/P± 变体绑定的 T_project 缓存）
- `tests/test_benchmark_test_protocol_v2.py`

命令：

```bash
cd <local-path>

# 1. 建题时冻结 T_task；只读 P+ trace，不读 P−
python -m benchmark_real_pilot.protocol_v2.run freeze

# 2. 日常 Benchmark：只跑冻结的 T_task
python -m benchmark_real_pilot.protocol_v2.run task
# 或只跑一个题
python -m benchmark_real_pilot.protocol_v2.run task --task real_click_truncate_visible

# 3. 建题/资格记录：从 T_task 结果 + T_project 缓存生成清单
python -m benchmark_real_pilot.protocol_v2.run manifest

# 4. 选择独立性回归测试
python -m pytest tests/test_benchmark_test_protocol_v2.py -q
```

`task` 命令不会调用 `T_project`；`manifest` 只读取缓存，不会重跑全量套件。只有建题或显式刷新时才需要重新跑项目套件。

## 2. T_task 的冻结规则

选择输入只有三类：

1. 源码关联：原测试文件是否覆盖目标函数/目标 A 所在的公开调用路径；
2. 原测试结构：保留原始测试文件、参数化和测试 ID，不移植、不改写断言；
3. P+ 覆盖：未删除 A 的版本中，`sys.settrace` 是否记录到目标行。

选择算法在 `selection.py` 中：

- `select_task_tests()` 没有 P− 参数；
- `load_plus_coverage()` 只读取 `upstream_runs.json` 的 `projects[project]["plus"]["trace"]["hits"]`；
- 规则是“允许的原测试文件中所有 P+ 命中 A 的测试全部保留”，不按 P− 结果删减；
- 冻结文件带 `p_minus_consulted: false` 和每条题的 `selection_hash`；
- 运行脚本读取冻结的 `original_test_ids`，不会在运行 P− 后重新选题。

冻结时间：`2026-11-02T00:54:25Z`；P− 运行在之后。三条题的 `selection_hash`：

| 题 | selection_hash |
|---|---|
| `real_click_truncate_visible` | `e45f4c867031768c22395ef35c9ecb14c51bdeced0527bb76d6747fc0b12fca9` |
| `real_werkzeug_headerset_update` | `8247c7ee67b72b315c9f722fcf6211f0b2c01d21e671d6193881c4b95fbd56ee` |
| `real_werkzeug_url_unparse` | `70b6f9f0d0a93b56f4e3ff948ad466d89263061dff4db8c16e35e6504ce28b90` |

回归测试 `tests/test_benchmark_test_protocol_v2.py` 用两份只有 P− 结果不同的合成覆盖文件调用 `build_selection()`，断言两边的测试 ID 与 selection hash 完全相同；另外断言选择函数的签名中没有任何 P− 输入。

## 3. 三个题的 T_task

### 3.1 数量与命中

| 题 | T_task 条数 | P+ 中实际执行 A 的条数 | 选择文件 |
|---|---:|---:|---|
| `real_click_truncate_visible` | 1 | 1 | `tests/test_formatting.py` |
| `real_werkzeug_headerset_update` | 3 | 3 | `tests/test_datastructures.py`、`tests/test_http.py`、`tests/test_wrappers.py` |
| `real_werkzeug_url_unparse` | 18 | 18 | `tests/test_urls.py` |

三个题合计 22 条 T_task；P+ 下 22/22 都命中目标 A 行。这里的“执行 A”指 P+ trace 在目标行记录到命中，不是仅断言测试调用了外层公开函数。

### 3.2 逐题说明

#### `real_click_truncate_visible`

- 唯一命中测试：
  `tests/test_formatting.py::test_wrap_text_visible_width[styled-long-word-breaks-on-visible-width]`
- 选择理由：P+ 全量 trace 中只有这一个原始测试命中 `_truncate_visible`。它通过公开 `wrap_text`/`_handle_long_word` 进入目标路径，不是直接调用私有函数。
- 为什么不凑到 5 条：其余 formatting 测试没有命中 A，加入它们会变成无关测试。按“不要为了凑数强行删掉必要测试”的同一原则，也不反向添加非必要测试。
- A 执行情况：该测试命中 A 2 次。
- 证据限制：这是 1 条测试、1 个见证；A 是绑定覆盖型，暴露方式是 `UnboundLocalError`，不能把它写成 defined-to-defined 值变化。

#### `real_werkzeug_headerset_update`

- 三个原始测试：
  - `tests/test_datastructures.py::TestHeaderSet::test_basic_interface`
  - `tests/test_http.py::TestHTTPUtility::test_set_header`
  - `tests/test_wrappers.py::test_common_response_descriptors`
- 选择理由：三条都是 P+ 全量 trace 中命中 `HeaderSet.update` 的全部原始测试；分别覆盖直接 `HeaderSet.add`、`http.parse_set_header` 后的 `add`、响应头 `Vary/Allow.add`。
- P+ 命中次数：2、1、5。
- 证据限制：T_task 中有 1 条 `test_set_header` 在 P− 下失败，因此 T_task 并不存活。该题不能用于“原测试漏掉删除风险”的论证。

#### `real_werkzeug_url_unparse`

- 18 条原始测试全部来自 `tests/test_urls.py`，例如：
  `test_iri_support`、`test_iri_safe_conversion`、`test_iri_safe_quoting`、
  `test_uri_iri_normalization`、`test_uri_to_iri_dont_unquote_space`、
  `test_iri_to_uri_dont_quote_reserved`、`test_quoting_of_local_urls`、
  `test_url_fixing`、`test_url_fixing_filepaths`、`test_url_fixing_qs`、
  `test_url_joining` 等。
- 选择理由：P+ 全量 trace 中 `tests/test_urls.py` 的全部命中测试都是公开 URL 转换接口的原测试；它们经 `iri_to_uri`、`uri_to_iri`、`url_fix`、`url_join` 间接到达 `url_unparse`。全量 trace 另外还有 201 条命中来自无关模块的间接消费者，不属于直接源码关联集，未纳入 T_task。
- 18 条略高于 5–15 的目标，但没有为了压到 15 条删除任何一条直接相关测试；删减会改变“完整源码关联池”的定义。
- 没有原始测试直接 `import url_unparse`；因此“直接”指公开接口路径直接，而不是测试文件按名字导入目标函数。
- 证据限制：18 条测试不是 18 个独立机制见证；它们共同覆盖同一目标函数的不同公开路径。A 的暴露多是 `UnboundLocalError`，仍不是 defined-to-defined 值变化。

## 4. T_task 的 P+ / P− 结果

| 题 | P+ | P− | T_task 存活 |
|---|---|---|---|
| `real_click_truncate_visible` | 1 passed | 1 passed | 是 |
| `real_werkzeug_headerset_update` | 3 passed | 1 failed, 2 passed | 否 |
| `real_werkzeug_url_unparse` | 18 passed | 6 failed, 12 passed | 否 |

具体失败：

- `HeaderSet.update`：`tests/test_http.py::TestHTTPUtility::test_set_header`，`UnboundLocalError: cannot access local variable 'inserted_any'`。
- `url_unparse`：以下 6 条失败，均在 `url_unparse` 的 `url` 读取处触发 `UnboundLocalError`：
  - `test_iri_safe_conversion`
  - `test_iri_support`
  - `test_iri_to_uri_dont_quote_reserved`
  - `test_quoting_of_local_urls`
  - `test_uri_to_iri_dont_unquote_space`
  - `test_url_joining`

P− 的失败不是环境错误，也不是测试被过滤；是删除 A 后真实发生的未绑定读取。

## 5. 五个资格标签

每个题都同时记录以下五个独立布尔字段，互不覆盖：

- `TASK_TESTS_SURVIVE`：冻结的 T_task 在 P− 下全部通过。
- `PROJECT_SUITE_SURVIVES`：声明的完整适用 T_project 在 P− 下通过。
- `PROJECT_SUITE_DETECTS`：T_project 检测到删除 A 的影响。
- `PROJECT_SUITE_NOT_FULLY_RUN`：声明的 T_project 至少一个变体没有完整执行。
- `ENVIRONMENT_BLOCKED`：因环境/依赖原因无法可靠判断。

| 题 | TASK_TESTS_SURVIVE | PROJECT_SUITE_SURVIVES | PROJECT_SUITE_DETECTS | PROJECT_SUITE_NOT_FULLY_RUN | ENVIRONMENT_BLOCKED |
|---|---|---|---|---|---|
| click `_truncate_visible` | true | true | false | false | false |
| Werkzeug `HeaderSet.update` | false | false | true | false | false |
| Werkzeug `url_unparse` | false | false | true | true | false |

`url_unparse` 的 `PROJECT_SUITE_NOT_FULLY_RUN=true` 是因为 P− 在 collection 阶段被删除 A 触发的 `UnboundLocalError` 中断，0 条测试实际运行；这不是环境阻塞，也不影响“project suite detects”结论。

## 6. T_project 的定义、范围和缓存

### 6.1 声明范围

| 题 | 声明的 T_project | 过滤/未执行 | 结果 |
|---|---|---|---|
| click | click 默认发布套件 `tests` | 无额外过滤；click 自己的 `pytest.ini` `addopts = -m 'not stress'` 排除 30000 条 stress | P+：1562 passed, 94 skipped, 30000 deselected, 1 xfailed；P− 相同 |
| HeaderSet | Werkzeug `tests -m "not dev_server"` | 因本机 Windows dev-server 环境不可用，排除 24 条 | P+：816 passed, 24 deselected；P−：1 failed, 815 passed, 24 deselected |
| url_unparse | Werkzeug `tests -m "not dev_server"` | 同上，排除 24 条 | P+：816 passed, 24 deselected；P−：24 deselected, 1 error（collection 中断，0 tests run） |

Werkzeug 的**未过滤完整套件**有 15 failed、8 errors，全部是 dev-server 的 `ConnectionRefusedError`，不用于资格结论。报告中没有把“适用套件通过”写成“整个 Werkzeug 项目全部测试通过”。

### 6.2 缓存键

`project_suite_cache.json` 的每个条目绑定：

- 项目/版本；
- `source_tree_sha256`（项目 `src/**/*.py` 的确定性树哈希）；
- 环境指纹（Python 可执行文件、Python 版本、pytest 版本、平台、`PYTHONHASHSEED`）；
- 测试范围（`tests`、过滤参数、deselect 数量）；
- 变体（P+ / P−：文件、行号、期望语句）。

任何一项变化都会生成不同 key。缓存条目记录 `fully_executed`；未完整执行的 P−（url_unparse collection 中断）被明确标为 false，不会被当成“完整套件通过”。

## 7. 既有资格结论是否改变

**没有改变。**

- click `_truncate_visible`：T_project P− 仍通过；仍只有它满足“项目原测试在 P− 下存活”。
- Werkzeug `HeaderSet.update`：T_project P− 仍因 `test_set_header` 失败；仍为 `would_be_caught`。
- Werkzeug `url_unparse`：T_project P− 仍在 collection 阶段失败；仍为 `would_be_caught`。

因此，原有 `docs/benchmark_real_qualification.md` 和 `three_task_qualification.json` 的结论不变：三道题中只有 click 通过项目测试存活资格。新增的 T_task/T_project 分层只是把证据记录得更清楚，没有推翻或美化旧结论。

## 8. Hidden validation 与 T_task 的隔离

Hidden validation 输入和 T_task 是两套东西：

- T_task 只包含原始上游测试 ID；hidden cases 在 `benchmark_real_pilot/specs.py` 中，是调用参数/边界输入，不是测试 ID。
- 两者没有交集；`task_manifest.json` 的 `hidden_validation.T_task_overlap` 为 `[]`。
- Hidden cases 覆盖：
  - 掩盖输入（`mask_*`）；
  - 删除风险暴露输入（`expose_*`）；
  - 合法边界/普通输入与“A 未执行”对照（如空串、纯 ANSI、空 iterable、类型混合等）。
- 操作干预组合：base + 已验证操作子集干预；证据在 scorer-only 的 `verifier_v2_real_tasks.json`。
- B/C/D/E 标签只存在于 specs/verifier 评分侧，不写进 T_task、不写进公开题面、不发给 MACE/Direct Qwen。
- 三个真实题只有 `independent` 关系；`cooperative`/`coexisting` 的覆盖来自既有受控 fixture `ctrl_02`/`ctrl_03`，它们是关系检查器的验证，不是新真实题，也不是这三个题的证据。
- 本轮没有运行 MACE 或 Direct Qwen，因此不存在模型看到 hidden answer 的路径；后续运行也必须只给公开题面和 T_task，不得给 hidden cases 或 B/C/D/E。

## 9. 成本对比

### 9.1 测试条数

| 场景 | 每次运行的测试结果记录 |
|---|---:|
| 旧：逐题跑项目套件 P+ | 3289（click 1657 + Werkzeug 816 + Werkzeug 816） |
| 旧：项目套件 P+ 和 P− 都跑 | 5762（P− 的 url_unparse 为 0） |
| 新：日常只跑冻结 T_task P+ | 22 |
| 新：T_task P+ 和 P− 都跑 | 44 |

### 9.2 实测墙钟时间

来自本轮实际运行（Windows 本机，非估算）：

| 场景 | 时间 |
|---|---:|
| 旧：三个项目套件 P+ 各一次 | 37.21 s |
| 旧：项目套件 P+ 与 P− 各一次 | 60.81 s |
| 新：三个 T_task P+ | 2.39 s |
| 新：三个 T_task P+ 与 P− | 4.97 s |

日常运行从“每次项目全量套件”降为“每次 22 条冻结测试”，按 P+ 计约减少 **93.6%** 墙钟时间；按 P+/P− 都跑计约减少 **91.8%**。建题时的完整项目套件仍需要跑一次，但结果按上述四元组缓存，后续不重复。

## 10. 证据边界与不能声称的内容

- 不能把 click 的 T_task 存活扩大成“click 的所有测试都覆盖了该删除风险”；T_task 只有 1 条，且该条测试本身走的是被掩盖路径。
- 不能把 `PROJECT_SUITE_DETECTS=true` 的 HeaderSet/url_unparse 写成“项目测试漏掉删除风险”；它们恰好被项目测试抓到。
- 不能把 `PROJECT_SUITE_SURVIVES=true` 只凭 T_task 通过就外推；click 的结论来自 T_project，而不是 T_task。
- 不能把 url_unparse 的 P− collection 中断写成“完整套件运行后通过”；标签中已单独记录 `PROJECT_SUITE_NOT_FULLY_RUN=true`。
- 不能把 18 条 url_unparse 测试写成 18 个独立操作关系见证；它们覆盖同一目标函数的不同公开路径。
- 不能把 Werkzeug 的适用套件结果写成未过滤完整套件结果；dev-server 的 15 failed/8 errors 仍单独保留，且不归因于任务或模型。
- 不能声称 cooperative/coexisting 已在真实题上验证；本轮三个真实题仍只有 independent。
- 本轮没有 Qwen/MACE 分数，不产生模型优劣结论。

## 11. 六个直接问题的回答

1. **每道题的 T_task 有多少条？** click 1 条；HeaderSet 3 条；url_unparse 18 条；合计 22 条。
2. **其中多少条真正执行 A？** P+ trace 下 22/22 都命中目标 A 行：1/1、3/3、18/18。
3. **T_task 上的 P+ / P− 结果？** click：1 passed / 1 passed；HeaderSet：3 passed / 1 failed + 2 passed；url_unparse：18 passed / 6 failed + 12 passed。
4. **既有 T_project 资格结论是否变化？** 不变：仍只有 click 通过项目套件存活；HeaderSet 和 url_unparse 仍被项目套件抓到。
5. **各题的测试范围与证据限制？** 见第 3、6、10 节：click 是 1 条测试 + 绑定覆盖型单见证；HeaderSet 是 3 条相关原测试且 P− 下被抓到；url_unparse 是 18 条公开接口原测试，P− 下 6 条失败，项目套件在 collection 阶段被抓到。
6. **修改前后的运行成本？** 旧项目套件 P+ 约 37.21 s（P+/P− 约 60.81 s），新 T_task P+ 约 2.39 s（P+/P− 约 4.97 s）；测试结果记录从 3289 条降到 22 条（P+），约减少 93.6% 墙钟时间。

## 12. 明确未做的事

- 未修改 MACE 核心算法、契约、提示词或验证器。
- 未新增 Agent，未调用 Qwen，未运行 MACE。
- 未新增任务，未扩大 Benchmark，未改变 A/B 行、输入域、抽取代码或既有三题定义。
- 未修改 M1–M6 历史结果、历史实验日志或旧资格 JSON。
- 未按 P− 结果挑选或删除 T_task 测试。
- 未把 hidden cases、B/C/D/E 标签或标准答案放入 T_task/公开题面。
