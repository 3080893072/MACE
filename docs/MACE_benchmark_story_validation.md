# MACE Benchmark v3：原测试掩盖证据关联与首次试点评估

- 版本：`v3.0-dev-pilot-2026-11-02`
- 日期：2026-11-02
- 范围：只检查现有 5 道已冻结题目的原测试输入，不新增题目，不修改 MACE
  算法，不修改已冻结的原始证据、隐藏答案或评分器。
- 结论标签：`DEVELOPMENT/PILOT`

本文件回答一个具体问题：**现有原测试为什么没有发现删除 A 的风险？** 对每题
冻结的 `T_task`，在 P+、P− 以及 P− 的每个 U 子集变体上重新执行，记录 A 的
每次执行、局部变量前后值、U 的每次执行、目标函数的返回/异常观察，再按
`NOT_EXECUTED / NO_LOCAL_EFFECT / MASKED_EFFECT / ASSERTION_GAP /
INCONCLUSIVE` 分类。所有关系都从**该测试自己的输入**重新计算，不复制旧
witness 的结论。

## 0. 结论摘要

| 题目 | T_task | A 执行总次数 | 有局部效应的测试 | MASKED_EFFECT | NO_LOCAL_EFFECT | ASSERTION_GAP | NOT_EXECUTED | INCONCLUSIVE | 标签 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `jinja2_bytecode_cache_read` | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED` |
| `werkzeug_bind_server_name_lower` | 8 | 12 | 0 | 0 | 8 | 0 | 0 | 0 | `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED` |
| `werkzeug_filestorage_stream_name` | 10 | 16 | 1 | 0 | 9 | 1 | 0 | 0 | `ASSERTION_GAP_STORY` |
| `werkzeug_get_host_default_empty` | 118 | 268 | 118 | 118 | 0 | 0 | 0 | 0 | `FULL_MASKING_STORY` |
| `werkzeug_secure_filename_ascii_filter` | 1 | 5 | 1 | 1 | 0 | 0 | 0 | 0 | `FULL_MASKING_STORY` |
| **合计** | **138** | **302** | **120** | **119** | **18** | **1** | **0** | **0** | — |

核心结论：

1. **2/5 题目真正满足 `FULL_MASKING_STORY`**：`get_host` 与
   `secure_filename`。
2. 119 个原测试出现 `MASKED_EFFECT`：`get_host` 118 个，
   `secure_filename` 1 个。
3. 18 个原测试只是执行了 A，却没有局部状态差异：Jinja2 1 个、bind 8 个、
   FileStorage 9 个。它们不能算作“掩盖导致测试漏检”。
4. 断言缺口只有 1 个原测试：FileStorage 的 `test_save_to_pathlib_dst`。
   没有哪道题以断言缺口为多数；FileStorage 按优先级标为
   `ASSERTION_GAP_STORY`，但 9/10 的测试其实属于“A 无局部效应”。
5. 五道题都有冻结的公开/隐藏包、可执行暴露见证和可评分操作关系，可以进入
   **首次开发集基线试跑**；但汇总时必须按标签分层，不能把五题都记作“掩盖
   导致原测试漏检”。
6. 没有发现必须修复的评分接口问题。原版 Full MACE 没有操作级输出接口，
   这应记为 `UNSUPPORTED_INTERFACE`，不是语义错误，也不是 0% 正确率。

## 1. 方法与判定规则

### 1.1 逐测试追踪

新增 `benchmark_real_v3/story_trace_plugin.py`，通过 pytest
`pytest_runtest_protocol` hook 在整个 setup/call/teardown 期间安装
`sys.settrace`。追踪只覆盖 A、U 和目标观察函数所在的源文件，避免把整个
pytest 和项目源码都逐行追踪。

对每个测试记录：

- **A**：源码位置、所在函数、`before`（A 行执行前）、`after`（同帧下一次
  事件时，通常是下一条可执行源码行）、`after_lineno`、`changed`、执行序号。
  循环或重复调用会为每次执行各记一条，不只记第一次。
- **U**：每个操作的执行次数、`before/after`、改变与否。单行 U 在下一事件
  收尾；块 U（`secure_filename` 的 227–229 行）在离开该行区间或函数返回时
  收尾，避免多行语句的重复行事件造成二次记录。
- **观察**：目标函数每次 `return` 的值或异常（类型、消息），形成有序序列。
  Jinja2 观察 `Template.render`；bind 观察 `Map.bind_to_environ` 返回的
  adapter；FileStorage 观察 `FileStorage.__init__` 结束时的 `self.filename`；
  `get_host` 观察返回值/异常；`secure_filename` 观察返回值/异常。
- **测试输入**：`callspec.id`、`callspec.params`、fixture 参数和源码片段。

P− 变体里 A 所在行是 `pass` 占位符，因此追踪器在 P− 中**不把该占位符记成
A 的执行**（`minus_execution_count` 为 0 是正确结果，不是漏记）。

### 1.2 变体矩阵

对每道题运行：

- `plus`：P+，A 与 U 全部启用；
- `EMPTY`：P−，A 删除，U 全部启用；
- 每个非空 U 子集 `S`：P−，A 删除，同时禁用 `S`。

因此共 17 组变体运行：

| 题目 | U 大小 | 变体 |
|---|---:|---|
| Jinja2 | 1 | plus, EMPTY, `compile_fallback` |
| bind | 1 | plus, EMPTY, `bind_relower` |
| FileStorage | 1 | plus, EMPTY, `special_name_reset` |
| get_host | 2 | plus, EMPTY, `overwrite_host_header`, `overwrite_server`, 两者 |
| secure_filename | 1 | plus, EMPTY, `sanitize_whitelist` |

所有变体都只运行该题冻结的 `T_task` node id；环境、解释器、pytest 版本与
v3 验收阶段一致。变体日志和 trace 见
`benchmark_real_v3/evidence/story_validation/runs/`。

### 1.3 分类规则

对每个测试，按以下顺序判定：

1. `NOT_EXECUTED`：P+ 中 A 一次也没有执行。
2. `NO_LOCAL_EFFECT`：A 执行了，但每次执行的目标变量 `before == after`。
3. `INCONCLUSIVE`：有局部效应，但 P+ 或 P− 没有观察、测试在任一侧未通过，
   或 P+/P− 观察相同但找不到非空 U 子集满足最小充分关系。
4. `ASSERTION_GAP`：有局部效应，P+/P− 的最终观察不同，但原测试在两侧都
   通过。
5. `MASKED_EFFECT`：有局部效应，P+/P− 观察相同，原测试两侧都通过，并且
   存在非空最小充分集（MSMS）。

这里的 `MASKED_EFFECT` 额外要求“A 真的有局部效应”。仅有非空 MSMS/MMBS
不足以判定掩盖：如果 A 在该输入上什么都没改变，删除它当然也可能看不出
差别，但这不是“A 的效果被后续操作吸收”。

### 1.4 原测试输入上的关系重算

对每个测试的观察序列 `obs(D)`（`D` 为被禁用的 U 子集）：

- `masked_at_empty`：`obs(∅) == obs_plus`；
- 保留集 `S` 充分（sufficient）：`obs(U \ S) == obs_plus`；
- 破除集 `D`（breaking）：`obs(D) != obs_plus`；
- MSMS：最小的非空充分保留集；
- MMBS：最小的非空破除集（要求 `masked_at_empty`）。

最小性只在声明的候选全集 U 上穷尽检查。每题报告里的
`observed_relations` 来自该测试自己的输入；`reference_masking_witness`
只作为旧证据并列展示，并明确标注“不复制结论”。

## 2. 逐题证据

### 2.1 `werkzeug_get_host_default_empty` — `FULL_MASKING_STORY`

- A：`src/werkzeug/sansio/utils.py:82`，`host = ""`。
- U：`overwrite_host_header`（85 行，`host = host_header`）、
  `overwrite_server`（87 行，`host = server[0]`）。
- T_task：118 个；A 共执行 268 次，268 次都有局部效应
  （`<unbound>` → `""`）。
- 结果：118/118 测试为 `MASKED_EFFECT`，0 个 `NO_LOCAL_EFFECT`，0 个
  `ASSERTION_GAP`，0 个 `INCONCLUSIVE`。

关系分布：

| 原测试数 | 原测试实际执行的 U | 该测试上的 MSMS | 该测试上的 MMBS |
|---:|---|---|---|
| 108 | 只有 Host 头覆盖 | `{overwrite_host_header}` | `{overwrite_host_header}` |
| 8 | 只有 server 覆盖 | `{overwrite_server}` | `{overwrite_server}` |
| 2 | 两类调用都出现 | `{overwrite_host_header, overwrite_server}` | 两个单元素集都最小 |

可复现的原测试证据：

1. **Host 头路径**：
   `tests/sansio/test_utils.py::test_get_host[http-spam-None-spam]`，
   参数 `scheme=http, host_header="spam", server=None, expected="spam"`。
   - A 执行 1 次：`before="<unbound>"`，`after=""`，`changed=true`；
   - P+ 观察：`return "spam"`；P− 观察：`return "spam"`；
   - 禁用 `overwrite_host_header`：`UnboundLocalError`，测试失败；
   - 禁用 `overwrite_server`：仍返回 `"spam"`，测试通过；
   - 原测试在 P+ 与 P− 都通过。
2. **server 路径**：
   `tests/sansio/test_utils.py::test_get_host[http-None-server10-spam:8080]`，
   参数 `scheme=http, host_header=None, server=("spam", 8080)`。
   - P+ / P− 都返回 `"spam:8080"`；
   - 禁用 `overwrite_server`：`UnboundLocalError`；
   - 禁用 `overwrite_host_header`：仍返回 `"spam:8080"`。
3. **两条路径同时出现**（2 个测试）：
   `tests/test_routing.py::test_server_name_casing` 先走 Host 头、再走
   server；`tests/test_wsgi.py::test_get_host_validate_trusted_hosts` 在 6 次
   `get_host` 调用里两种路径都出现。单禁任何一个都会让某次 `get_host` 抛
   `UnboundLocalError`，所以 MSMS 是两者同时保留，MMBS 是两个单元素集。
4. **循环/重复执行**：
   `tests/test_formparser.py::TestMultiPart::test_basic` 中 A 执行 15 次，
   JSON 里保留 15 条 `before/after` 记录，每一条都是
   `<unbound>` → `""`，没有被折叠成“第一次执行”。

暴露反例（矩阵中已有的 `expose_neither`）：
`{"scheme": "http", "host_header": null, "server": null}`。
P+ 返回 `""`；P− 在 `host.endswith(":80")` 处抛 `UnboundLocalError`。
这证明删除 A 在“两个来源都缺失”时是可观察的；118 个原测试之所以存活，
是因为它们每次 `get_host` 调用都至少有一个 U 覆盖。

验证范围：只覆盖 118 个冻结 T_task 及其实际调用序列；不声称覆盖
`get_host` 的全部合法输入，也不声称 U 之外没有其他操作。

### 2.2 `werkzeug_secure_filename_ascii_filter` — `FULL_MASKING_STORY`

- A：`src/werkzeug/utils.py:222`，
  `filename = filename.encode("ascii", "ignore").decode("ascii")`。
- U：`sanitize_whitelist`，227–229 行的块
  （`_filename_ascii_strip_re.sub(...)`）。
- T_task：1 个，`tests/test_utils.py::test_secure_filename`；该测试连续调用
  `secure_filename` 5 次。
- A 执行 5 次，只有第 3 次有局部效应：
  `"i contain cool ümläuts.txt"` → `"i contain cool umlauts.txt"`；
  其余 4 次输入本来就是 ASCII，`before == after`。
- U 执行 5 次，5 次都改变了 `filename`（例如
  `"My cool movie.mov"` → `"My_cool_movie.mov"`）。
- P+ 与 P− 的 5 次返回值完全相同：
  `My_cool_movie.mov`、`etc_passwd`、`i_contain_cool_umlauts.txt`、
  `filename`、`foobar`。
- 禁用 `sanitize_whitelist` 后测试失败；MSMS = MMBS =
  `{sanitize_whitelist}`。

针对原测试中真正触发 A 的那个子输入，单独重跑 probe：

| 变体 | `secure_filename("i contain cool ümläuts.txt")` |
|---|---|
| P+ | `i_contain_cool_umlauts.txt` |
| P−（A 删除，U 保留） | `i_contain_cool_umlauts.txt` |
| P− 且禁用 U | `i contain cool ümläuts.txt` |

第三行是重新执行得到的结果，不是复用旧 witness；它直接显示 U 的白名单
规范化吸收了 A 的 ASCII 过滤差异。证据文件：
`benchmark_real_v3/evidence/story_validation/werkzeug_secure_filename_ascii_filter_focused.json`。

矩阵中的暴露反例：`{"filename": "a b"}`。P+ 返回 `"ab"`；P− 返回
`"a_b"`（没有 ASCII 过滤删除 Ogham 空格，后续步骤把它变成下划线）。

注意：原测试是一个包含 5 次调用的序列；禁用 U 的变体在第 1 个断言就失败，
因此不可能在同一序列里观察到“只禁用第 3 次调用的 U”。上表的单输入 probe
补上了这个局部反事实；原测试序列本身则提供了 P+/P− 五次返回值逐项相同
的直接证据。两者合起来支持 `MASKED_EFFECT`，而不是只凭旧 witness 推断。

验证范围：1 个原测试的 5 次调用，加上 1 个来自测试输入的子输入 probe；
不覆盖 `secure_filename` 的全部合法输入。

### 2.3 `werkzeug_filestorage_stream_name` — `ASSERTION_GAP_STORY`

- A：`src/werkzeug/datastructures.py:2918`，
  `filename = getattr(stream, "name", None)`。
- U：`special_name_reset`（2924 行，`filename = None`，只对 `<...>` 名称）。
- T_task：10 个；A 共执行 16 次。
- 9 个测试的 stream 是 `io.BytesIO`、`SpooledTemporaryFile` 等没有
  `.name` 的对象，A 把 `filename` 从 `None` 赋成 `None`，属于
  `NO_LOCAL_EFFECT`。这些测试的 P+/P− 观察相同，U 也没有执行。
- 1 个测试是 **断言缺口**：
  `tests/test_datastructures.py::TestFileStorage::test_save_to_pathlib_dst`。
  输入是打开的文件对象 `f`（`tmp_path/src.txt`）：
  - A 执行 1 次：`before=None`，`after=<tmp_path>/src.txt`，`changed=true`；
  - P+ 的 `FileStorage.__init__` 观察：`filename` 是真实路径；
  - P− 的观察：`filename=None`；
  - U `special_name_reset` 执行 0 次（普通路径不以 `<` 开头）；
  - 原测试只断言 `dst.read_text() == "test"`，不检查 `storage.filename`；
  - 测试在 P+ 与 P− 都通过。
- 因此该测试是 `ASSERTION_GAP`：P+/P− 已经产生可观察差异，原测试没有检查
  这个差异。它不是 `MASKED_EFFECT`，因为没有任何后续操作把差异消除。

暴露反例：矩阵中的 `{"stream": "tempfile"}`。P+ 得到临时文件名，P− 得到
`None`；本题冻结的 T_task 中没有测试检查这个属性，所以删除仍能通过。

验证范围：10 个冻结 T_task；不声称所有 FileStorage 调用都如此。

结论：本题不存在可由原测试输入验证的 `MASKED_EFFECT`；唯一有局部效应的
原测试是断言缺口，其余 9 个没有局部效应。

### 2.4 `jinja2_bytecode_cache_read` — `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`

- A：`src/jinja2/loaders.py:132`，`code = bucket.code`。
- U：`compile_fallback`（137 行，`code = environment.compile(...)`）。
- T_task：1 个，`tests/test_bytecode_cache.py::TestByteCodeCache::test_simple`。
- 该测试使用一个新建的 `FileSystemBytecodeCache`，缓存初始为空：
  - A 执行 1 次，`bucket.code` 是 `None`，`before == after == None`；
  - U 执行 1 次，把 `code` 从 `None` 改成编译后的 code object；
  - P+ 与 P− 都渲染出 `"BAR"`；
  - 禁用 `compile_fallback` 后测试失败（没有 code 可执行）。
- 这是 `NO_LOCAL_EFFECT`：A 确实执行了，但这次读取没有产生任何局部状态
  差异。测试存活的原因是“缓存未命中时 fallback 会编译”，不是“A 的局部
  效果被 fallback 吸收”。
- 旧矩阵仍有暴露反例：`{"template": "{{ 6*7 }}", "cached_source":
  "{{ 1+1 }}"}`。P+ 从缓存读到 `{{ 1+1 }}` 的 code，返回 `"2"`；P− 删除
  缓存读取后重新编译模板，返回 `"42"`。这证明 A 在缓存命中时确实重要，但
  该输入不是原测试输入。
- 标签 `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`：原测试存活、存在暴露
  反例，但尚未证明原测试是因为“掩盖”而通过。

验证范围：1 个原测试；不覆盖有缓存命中的输入。

结论：本题不存在可由原测试输入验证的 `MASKED_EFFECT`；原测试输入上 A 没有
局部效应。

### 2.5 `werkzeug_bind_server_name_lower` — `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`

- A：`src/werkzeug/routing/map.py:307`，
  `server_name = server_name.lower()`（`Map.bind` 的 else 分支）。
- U：`bind_relower`（219 行，`bind_to_environ` 里的
  `server_name = server_name.lower()`）。
- T_task：8 个；A 共执行 12 次，全部 `before == after`。这些测试传入的
  `server_name` 都是小写（`example.org:5000`、`example.com`、
  `bar.example.com`、`localhost:80`、`localhost:443` 等），所以
  `lower()` 是空操作。
- U 在这些输入上同样不改变值；禁用 `bind_relower` 后 8 个测试仍然全部通过
  （MMBS 为空）。形式上 MSMS 是 `{bind_relower}`，但这只是因为在该输入上
  保留或删除 U 都看不出差别，不能据此声称“A 的效果被 U 掩盖”。
- 旧矩阵的暴露反例：`{"server_name": "EXAMPLE.COM", "subdomain": null}`。
  P+ 返回 `server_name="example.com"`、`subdomain=""`；P− 返回
  `server_name="example.com"`、`subdomain="<invalid>"`。该输入不是原测试
  输入，但它证明 A 在混合大小写时是必要的。
- 标签 `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`：原测试存活且有暴露反例，
  但原测试输入没有局部效应，不能证明掩盖。

验证范围：8 个原测试；不覆盖混合大小写 server_name。

结论：本题不存在可由原测试输入验证的 `MASKED_EFFECT`；8 个原测试的 A 都是
空操作。

## 3. 六个问题的直接回答

### Q1：五题中多少道真正满足 `FULL_MASKING_STORY`？

**2 道**：

- `werkzeug_get_host_default_empty`
- `werkzeug_secure_filename_ascii_filter`

其余 3 道不满足：

- `jinja2_bytecode_cache_read`：`TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`
- `werkzeug_bind_server_name_lower`：
  `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`
- `werkzeug_filestorage_stream_name`：`ASSERTION_GAP_STORY`

### Q2：各题有多少个原测试出现 `MASKED_EFFECT`？

| 题目 | `MASKED_EFFECT` 原测试数 |
|---|---:|
| `jinja2_bytecode_cache_read` | 0 |
| `werkzeug_bind_server_name_lower` | 0 |
| `werkzeug_filestorage_stream_name` | 0 |
| `werkzeug_get_host_default_empty` | 118 |
| `werkzeug_secure_filename_ascii_filter` | 1 |
| **合计** | **119** |

### Q3：哪些原测试只是执行了 A，却没有实际局部效应？

共 18 个，全部为 `NO_LOCAL_EFFECT`：

**Jinja2（1）**

- `tests/test_bytecode_cache.py::TestByteCodeCache::test_simple`

**bind（8）**

- `tests/test_routing.py::test_external_building_with_port_bind_to_environ`
- `tests/test_routing.py::test_external_building_with_port_bind_to_environ_wrong_servername`
- `tests/test_routing.py::test_http_host_before_server_name`
- `tests/test_routing.py::test_invalid_subdomain_warning`
- `tests/test_routing.py::test_server_name_casing`
- `tests/test_routing.py::test_server_name_interpolation`
- `tests/test_routing.py::test_server_name_match_default_port[http://localhost-localhost:80]`
- `tests/test_routing.py::test_server_name_match_default_port[https://localhost-localhost:443]`

**FileStorage（9）**

- `tests/test_datastructures.py::TestFileStorage::test_bytes_proper_sentinel[data0]`
- `tests/test_datastructures.py::TestFileStorage::test_bytes_proper_sentinel[data1]`
- `tests/test_datastructures.py::TestFileStorage::test_mimetype_always_lowercase`
- `tests/test_datastructures.py::TestFileStorage::test_proxy_can_access_stream_attrs[BytesIO]`
- `tests/test_datastructures.py::TestFileStorage::test_proxy_can_access_stream_attrs[SpooledTemporaryFile]`
- `tests/test_datastructures.py::TestFileStorage::test_save_to_bytes_io`
- `tests/test_datastructures.py::TestFileStorage::test_save_to_file`
- `tests/test_test.py::test_environ_builder_data`
- `tests/test_test.py::test_file_closing`

这些测试的 P+/P− 观察都相同，且两侧都通过；它们不能解释为“掩盖导致漏检”。

注意：同一个测试 node id 可以同时属于不同题目的 T_task。例如
`tests/test_routing.py::test_server_name_casing` 在 bind 题里对 A 没有局部
效应，在 get_host 题里却是一个 `MASKED_EFFECT`（它调用了两次 `get_host`，
两种 U 路径各一次）。分类必须按题目分别理解，不能跨题合并。

### Q4：哪些题主要属于断言缺口？

严格说，**没有一道题以断言缺口为多数**。

- 只有 `werkzeug_filestorage_stream_name` 含 1 个断言缺口测试
  （`test_save_to_pathlib_dst`），因此按优先级标为
  `ASSERTION_GAP_STORY`。
- 但该题 10 个原测试中，9 个是 `NO_LOCAL_EFFECT`，1 个是
  `ASSERTION_GAP`，0 个是 `MASKED_EFFECT`。所以它是“唯一含断言缺口的题”，
  不是“断言缺口为主的题”。

### Q5：五题能否用于首次开发集基线试跑？

**可以，判定为 `PILOT_READY`**，但必须分层报告：

- 五题都有冻结的 PUBLIC/HIDDEN 包、可执行的暴露见证、可评分的
  MSMS/MMBS 关系，以及确定性的 P+/P− 评分器。
- 只有 2 题支持“原测试因操作掩盖而漏检”的完整故事；
- 1 题（FileStorage）是断言缺口；
- 2 题（Jinja2、bind）是“测试存活但未建立掩盖”的对照题。

因此：

- 可以把五题一起送入首次开发集基线试跑，用于比较 Direct Qwen、确定性
  分析器和 Full MACE 的可评分输出；
- 汇总“掩盖导致测试漏检”的比例时，分母只能是 2 道
  `FULL_MASKING_STORY` 题，不能把 5 题都算进去；
- 对照题可以报告为单独类别，也可以用于说明“测试存活不等于掩盖”。

### Q6：是否存在必须修复的评分接口问题？

**没有必须修复的评分接口问题。** 已核实：

1. 公开包 14 个文件，隐藏包 41 个文件；公开包不包含隐藏文件路径或隐藏
   标识符，泄漏检查 22 项全部通过。
2. 提交格式明确支持 `EXPOSING_COUNTEREXAMPLE`、`MSMS`、`MMBS`、
   `PREREQUISITE_BREAKING`、`CONDITIONAL_CORRECTNESS` 和 `PROVEN` 的语法。
3. 评分器回归测试 9/9 通过，覆盖正确、错误、重复、非法、不可验证和
   `PROVEN` 永不自动授予；无模型 demo 的
   `all_expectations_met=true`。
4. 评分器重新执行 P+/P− 和 U 的全部子集，不信任提交的期望观察；A 未执行
   的输入不能成为掩盖见证（有专门回归测试）。
5. 原版 Full MACE 没有 `relations[].operations`、没有 per-relation
   `input`、没有 `independent/cooperative` 字段；这是
   `UNSUPPORTED_INTERFACE`，不是语义错误，不能记为 0% 正确率。

不构成阻塞的注意事项：

- 评分器评的是 probe 观察上的操作关系，不直接评“原测试为什么通过”。
  本文件的 story validation 是独立的证据层，不应被混入评分器的
  `FALSE`/`UNVERIFIED` 计数。
- Full MACE 将来若要有操作级输出，需要新增独立接口；本轮不修改算法。

## 4. 第一次基线试跑的接口条件（任务 4）

### 4.1 公开包与隐藏包

证据文件：`benchmark_real_v3/evidence/story_validation/task4_readiness.json`。

| 项目 | 结果 |
|---|---|
| 发布版本 | `v3.0-dev-pilot-2026-11-02` |
| PUBLIC 文件数 | 14 |
| HIDDEN 文件数 | 41 |
| bundle SHA-256（重算） | `470f32fa7efd9a2db4e5ee203b4a374db93da4c907876c923f09dd07b49b80d3` |
| 与 manifest 一致 | 是 |
| 泄漏检查 | 22/22 通过 |
| HIDDEN 位于 PUBLIC 之外 | 是 |

公开包包含：`README.md`、`input_contracts.json`、`submission_format.md`、
`tasks/index.json`、5 个 `task.json`、5 个目标源码文件。它不包含：隐藏
候选全集 U、隐藏 witness、矩阵、期望关系、隐藏路径。

注意：公开包按设计提供 A 的完整真实源码文件；U 就位于同一文件中，但 U 的
身份、最小集和 witness 不在公开元数据里。泄漏检查确认元数据没有泄漏
“哪个操作是 U”。

### 4.2 提交格式与评分器

- 操作位置格式支持 `file` + `line` + 可选 `end_line` / `code`；
- MSMS/MMBS 支持单输入 `input` 和多输入 `inputs`（2–12 个）；
- 状态词表：`WITNESS_VERIFIED`、`FINITE_DOMAIN_EXACT`、`PROVEN`、
  `FALSE`、`INVALID`、`UNVERIFIED`、`UNSUPPORTED`、`DUPLICATE`；
- 重复声明不重复计分；同一关系换输入也不重复计分；
- 无法验证的声明（U 之外的操作、无法执行的证明）记为 `UNVERIFIED`，
  不误记为 `FALSE`。

### 4.3 原版 Full MACE

- `docs/MACE_open_discovery_protocol.md` 记录：规范化后的 `final_bundle`
  只有 `target_effects`、`upstream`、`observers`、`mask_guard`、
  `uncertainty`；`relations[].kind` 只有 `target_effect`、`upstream`、
  `observer`；**没有 `relations[].operations`、per-relation `input`、
  `independent/cooperative`**。
- `docs/MACE_executability_and_baseline.md` 的能力矩阵把
  “掩盖操作与组合”和“测试缺口解释”都记为 `UNSUPPORTED_INTERFACE`。
- 因此本轮不把 Full MACE 的 `UNSUPPORTED` 写成答错或 0% 正确率。

## 5. 局限与不能确认的内容

1. **输入范围有限**：每题只执行冻结的 T_task 输入；关系的精确性只在 U
   和这些输入上成立，不覆盖全部合法输入。
2. **观察覆盖整个 pytest 协议**：setup、call、teardown 中的 `get_host` 等
   调用也会进入观察序列。这是该测试的真实执行轨迹，但读者不应把它理解
   为“只有测试函数体”的调用。
3. **局部效应的定义是机械的**：目标变量在 A 行前后发生变化即记为有局部
   效应；这不等同于“该赋值在语义上重要”。例如 `get_host` 的效应是
   `<unbound>` → `""`，FileStorage 的效应是 `None` → 路径。
4. **不声称覆盖整个项目测试套件**：每题的 T_task 是冻结的原测试子集；
   项目其他测试是否也掩盖删除，未在本题范围内逐一证明。
5. **不声称 U 是完备的**：U 是声明的候选全集；U 之外的操作没有被枚举，
   评分器对这种提交返回 `UNVERIFIED`。
6. **Jinja2 与 bind 的旧暴露 witness 不是原测试输入**：本文件明确把它们
   标为“旧矩阵反例”，没有用它们替代原测试结论。
7. **secure_filename 的序列限制**：原测试的 5 次调用序列在禁用 U 时提前
   失败；因此额外用原测试中的子输入做了单点 probe，二者结合支持
   `MASKED_EFFECT`，但仍不覆盖其他文件名。
8. **未修改冻结内容**：本轮没有修改 `release/PUBLIC`、`release/HIDDEN`、
   `tasks/*/spec.json`、`qualified_tasks.json`、矩阵或隐藏答案。新增的只有
   `evidence/story_validation/` 与四个新增脚本。

## 6. 证据索引与复现

新增脚本：

- `benchmark_real_v3/story_trace_plugin.py`：逐测试追踪插件；
- `benchmark_real_v3/story_validation.py`：变体矩阵、分类、per-test /
  per-task 报告；
- `benchmark_real_v3/story_summary.py`：机器可读汇总；
- `benchmark_real_v3/story_readiness.py`：任务 4 的只读检查。

机器可读证据：

- `benchmark_real_v3/evidence/story_validation/<task_id>_tests.json`：
  每个原测试的分类、A 的每次执行、U 的每次执行、观察序列、禁用子集结果、
  MSMS/MMBS；
- `benchmark_real_v3/evidence/story_validation/<task_id>_story.json`：
  每题标签、计数、代表测试、暴露反例、旧 witness（并列，不复制）；
- `benchmark_real_v3/evidence/story_validation/story_validation.json`：
  五题的标签与分类计数汇总；
- `benchmark_real_v3/evidence/story_validation/summary.json`：
  138 个测试的总计、18 个 no-local 清单、断言缺口、六个问题的答案；
- `benchmark_real_v3/evidence/story_validation/runs/<task>/<variant>/`：
  每个变体的 `trace.json`、`trace_config.json`、`pytest.log`；
- `benchmark_real_v3/evidence/story_validation/werkzeug_secure_filename_ascii_filter_focused.json`：
  原测试子输入的 P+/P−/无 U probe；
- `benchmark_real_v3/evidence/story_validation/task4_readiness.json`：
  公开/隐藏包、bundle、泄漏检查、评分器回归、demo、Full MACE 接口状态。

复现命令：

```bash
cd <local-path>

# 五题逐测试证据（会重建变体并运行冻结 T_task）
python -m benchmark_real_v3.story_validation

# 只重建汇总（不重跑 pytest）
python -m benchmark_real_v3.story_validation --aggregate
python -m benchmark_real_v3.story_summary

# 任务 4 只读检查（评分器回归 + demo + 包/哈希/泄漏）
python -m benchmark_real_v3.story_readiness
```

## 7. 最终判定

- `FULL_MASKING_STORY`：2/5
  （`werkzeug_get_host_default_empty`、`werkzeug_secure_filename_ascii_filter`）
- `ASSERTION_GAP_STORY`：1/5（`werkzeug_filestorage_stream_name`）
- `TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED`：2/5
  （`jinja2_bytecode_cache_read`、`werkzeug_bind_server_name_lower`）
- `MASKED_EFFECT` 原测试：119 个
- 无局部效应的原测试：18 个
- 未执行 / 证据不足：0 / 0
- 首次开发集基线：`PILOT_READY`
- 评分接口阻塞：无
