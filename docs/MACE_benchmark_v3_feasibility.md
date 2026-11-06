# MACE Benchmark v3：真实复杂题目构建可行性报告

日期：2026-11-02

本轮只做题目构造与资格验证。未运行 MACE/Qwen 比较，未修改 M1–M6 历史结果，未把评分器改动当作算法贡献，也没有根据任何模型分数挑选题目。

## 0. 结论摘要

| 项目 | 实际数字 |
|---|---:|
| 固定版本真实项目 | 3 个（click 8.4.1、Jinja2 3.1.3、Werkzeug 2.2.3） |
| 去重后的静态候选 | 799 |
| 有 P+ 原测试覆盖且静态形状合格的候选 | 403 |
| 实际做 targeted deletion screening 的候选 | 403（预算 403） |
| targeted 测试直接抓住删除的候选 | 374 |
| targeted 测试与适用全套件都存活的候选 | 29（全套件 P− 运行 29 次，预算 60） |
| 经执行确认同时具备暴露 witness 与操作级掩盖关系的题目 | **5** |
| 涉及的真实项目来源 | 2 个（Jinja2、Werkzeug）；click 本轮未产出合格题 |
| 不同的执行确认掩盖机制 | 5 类 |

五个合格题目全部满足：A 可在真实源码定位；P− 下项目适用套件通过；A 至少被一条原测试执行；存在合法暴露输入；存在执行确认的操作级掩盖输入；版本、测试范围、环境与双版本结果可复现。

## 1. 固定项目、环境与测试范围

项目树只读位于 `<local-path>/`，实验副本位于 `<local-path>/`。源码树的 SHA-256（按源文件路径 + 内容计算）记录在 `benchmark_real_v3/evidence/project_source_hashes.json`。

| id | 版本 | 源码哈希（前 16 位） | Python / pytest | 适用测试范围 |
|---|---|---|---|---|
| click-8.4.1 | 8.4.1 | `522f6d29daf1a273` | `D:/Anaconda3/python.exe`, 7.4.0 | 项目自带默认套件；其配置自行 deselect 30000 条 stress 测试。P+：1562 passed、94 skipped、1 xfailed、30000 deselected |
| jinja2-3.1.3 | 3.1.3 | `76a289afb2a1fbb6` | `D:/Anaconda3/python.exe`, 7.4.0 | 无协议级排除。P+：845 passed |
| werkzeug-2.2.3 | 2.2.3 | `4d80b206cdf7e3d1` | `<local-path>`, 7.2.0 | 协议排除 24 条 `dev_server` 测试（本机不能起本地 dev server）。P+：816 passed、24 deselected；不声称未过滤套件全部通过 |

因此，本报告中的“P− 适用套件通过”始终指上表的适用范围，不等于“项目所有测试通过”。被排除、跳过或 xfail 的部分均保留在上表与原始日志中。

## 2. 删除与判定口径

* A 是真实源码中的一条可定位语句。
* P− 用等缩进的 `pass  # P-: target A deleted` 替换 A，保持行号不变（`benchmark_real_v3/run_suite.py::delete_line`）。
* `Masked_strict(D)`：P+ 正常返回，且 P+ 与 P− 的观测完全相等。两侧相同地崩溃不算掩盖。
* `Exposed(D)`：两侧都可执行，且观测不同；P+ 正常返回而 P− 抛出异常也算暴露。
* `Only(S) = Masked_strict(U\S)`。
* `MSMS`：非空 S ⊆ U，满足 `Only(S)`，且没有更小的非空真子集满足；本轮枚举 U 的全部子集，因此在声明 U 内是穷尽的。
* `Break(S) = Exposed(S)`；`MMBS`：非空 S ⊆ U，满足 `Break(S)`，且没有更小的子集（包括空集）暴露。
* 五个合格题都要求 MSMS 与 MMBS 同时存在。仅 MSMS、没有 MMBS 的候选单列为补充案例，不计入合格题。
* 精确性只覆盖“已执行的有限输入 + 声明的候选全集 U”，不覆盖整个合法输入域，也不覆盖 U 之外的语句。

## 3. 筛选漏斗与协议披露

### 3.1 最终漏斗

```
799 个去重静态候选
├─ 151  NO_ORIGINAL_TEST_EXECUTES_A      P+ 全套件逐测试覆盖中没有任何测试执行 A
├─ 245  STATIC_REJECT_DEAD_BEFORE_READ   A 的值在下次写入前从未被读取，删除是死存储
└─ 403  STATIC_ELIGIBLE
   ├─ 374  TARGETED_TEST_DETECTS_DELETION  原测试在 P− 上失败或超时
   └─  29  TEST_SURVIVING_DELETION         targeted 测试与适用全套件在 P− 上均通过
        ├─  5  QUALIFIED
        ├─  8  REJECT_NO_EXPOSING_INPUT
        └─ 16  REJECT_NO_MASKING_RELATION（其中 1 个是 MSMS-only 补充案例）
```

候选审查预算为 403，targeted P− 运行 403 次，全套件 P− 运行 29 次（上限 60）。403 个合格静态候选全部审查，选择顺序只由确定性的 round-robin 决定，不按任何 P− 结果挑选。`T_task` 只从 P+ 覆盖确定，绝不使用 P− 结果。

### 3.2 版本化披露：被废弃的第一轮

第一轮筛选存在扫描器缺陷：嵌套函数的赋值被同时记到外层函数，产生 852 行 / 815 个不同 id；同时协议声明 targeted 子预算 140，但代码没有强制，实际用了 160 次。该轮全部 568 个日志/JUnit/覆盖文件保存在 `benchmark_real_v3/evidence/superseded_scanning_round1/`，**不作为最终结果**。

修正后扫描器只把赋值记给最内层函数，得到 799 个不同候选；协议改为 403 / 403 / 60，并由代码强制。最终结果只使用修正后的数据。

### 3.3 无限循环与恢复

删除 `jinja2/debug.py:52`（`tb = tb.tb_next`，位于 `if ...: continue` 中）会把循环变成无限循环。旧实现使用 `subprocess.run`，超时后仍被持有管道的子进程拖住。修复为 `Popen` + `taskkill /F /T` 杀进程树，并设置 targeted 120 秒、全套件 600 秒超时。本轮共有 10 次 targeted 运行以超时计为“原测试抓住删除”，均记录 `timed_out: true`，没有把超时静默当作通过。

修复前已完成下标 0–276 的 277 个观察，其 JUnit、日志和 select 文件完整；`salvage_rows.py` 只从这些已完成证据重建检查点，没有重跑。恢复运行从下标 277 继续到 402。最终 277 + 126 = 403，全部有检查点。

## 4. 六个问题

### 问题 1：审查了多少候选，多少通过测试筛选？

* 静态去重候选 799 个。
* 进入 targeted P− 审查 403 个（151 个无覆盖、245 个死存储被静态阶段排除，均记录原因）。
* 原测试在 P− 上抓住 374 个。
* targeted 命中测试与适用全套件都存活 29 个；29 次全套件 P− 运行全部完成，无预算耗尽漏跑。
* 因此“通过测试筛选”的比例是 29/403 = 7.2%（占全部静态候选 29/799 = 3.6%）。

### 问题 2：多少候选存在真实可观察的删除风险？

只把“执行了合法 witness，并观察到 P+ 与 P− 不同”计为真实风险：

* **5 个**：五个合格题目的暴露输入均实际执行，观测差异见矩阵。
* **8 个**没有暴露输入：其中 4 个是运行时恒等的类型转换或等价替换（`t.cast` ×2、`BytesIO(None)`、`MultiDict(None)`），4 个是死存储或冗余同值赋值（`word=None`、`best_specificity=(-1,)`、两个已经由后续同值来源保证的 `source=`）。这些是语义等价或不可观察，不是“测试没覆盖但可能有风险”。
* **16 个**缺少执行确认的掩盖关系。其中 1 个（`http.py:440`）已执行确认 MSMS，但 MMBS 为空，单列为补充案例；其余 15 个没有通过本轮的“操作级掩盖”资格线。它们**不**被宣称为无风险；本报告只声明“本轮没有建立可用的掩盖题”。

因此，可签发的真实风险题数是 5，另有 1 个部分成立的 MSMS-only 案例。

### 问题 3：多少候选有执行确认的操作级掩盖关系？

* **5 个题目**同时有非空 MSMS 与非空 MMBS。
* 共涉及 **6 个**被声明为掩盖操作的 U 成员：`get_host` 一题有两条互斥的覆盖路径，分别在不同输入上成为唯一掩盖者；其余四题各 1 个。
* 另有 1 个 MSMS-only 案例（`parse_options_header` 的 `continued_encoding=None`），其掩盖输入上 MSMS 非空、MMBS 为空，未计入 5 个合格题。

### 问题 4：是否找到了简单赋值覆盖之外的机制？

是。先保留简单覆盖基线：374 个候选被原测试直接抓住，它们证明“A 被测试执行”本身不构成复杂题；只有 29 个全套件存活候选进入机制验证。五个合格题对应五类机制，没有一题只是“A 被执行且被测试覆盖”：

1. **共存备份路径**：`BaseLoader.load` 的缓存读取被编译回退路径掩住；缓存命中与未命中在合法输入上可区分。
2. **条件覆盖**：`FileStorage` 从流对象取文件名，随后的特殊流名（`<...>`）重置将其抹掉。
3. **跨函数再推导 + 控制前置条件**：`Map.bind_to_environ` 的小写化被 `Map.bind` 再次小写化掩住，且只在显式提供 subdomain、跳过比较块时成立。
4. **两条互斥的替代覆盖路径**：`get_host` 的空串默认值分别被 Host 头和 server 地址两个分支掩盖；同一输入上最多一条路径生效。
5. **下游规范化吸收**：`secure_filename` 的 ASCII 过滤被后续白名单清洗吸收；只在残留字符不是 Unicode 空白时成立。

尚未产出合格题的复杂度方向：循环携带状态（只有 MSMS-only 的 `continued_encoding` 案例接近）、对象状态相互依赖、多操作同时协作的 U（现有最大 U=2，且两条路径互斥）。这些是扩展时的优先方向，不是本轮已完成的成果。

### 问题 5：每题有多少条原测试实际执行 A？

T_task 全部来自 P+ 全套件逐测试覆盖，从未使用 P− 结果。

| task_id | A 的执行测试数 | 具体 T_task |
|---|---:|---|
| `jinja2_bytecode_cache_read` | 1 | `tests/test_bytecode_cache.py::TestByteCodeCache::test_simple` |
| `werkzeug_filestorage_stream_name` | 10 | `tests/test_datastructures.py` 中 10 条 FileStorage 测试 |
| `werkzeug_bind_server_name_lower` | 8 | `tests/test_routing.py` 中 8 条绑定/子域测试 |
| `werkzeug_get_host_default_empty` | 118 | `test_get_host`、`test_proxy_fix`、`test_test`、`test_routing` 等 |
| `werkzeug_secure_filename_ascii_filter` | 1 | `tests/test_utils.py::test_secure_filename` |

5/5 满足“A 至少被一条原测试执行”。注意：测试执行 A 不等于测试能抓住删除；29 个存活候选的定义正是这些测试在 P− 上仍然通过。

### 问题 6：现有证据是否支持扩大为正式 benchmark？

**有条件支持，但当前规模不足以直接称为正式 benchmark。**

支持扩大的证据：

* 403 个候选可以完全自动地走完“静态提取 → P+ 覆盖 → targeted P− → 全套件 P− → witness/masking 验证”的漏斗，且有 29 个存活、5 个合格的真实产出。
* 5 个题覆盖 2 个真实项目、5 类机制；每题都有可复现的源码位置、删除方法、暴露 witness、掩盖 witness、MSMS/MMBS 矩阵和 P− 套件结果。
* 筛选不依赖人工随机搜索；所有拒绝理由都有记录，资格判定没有按模型分数调整。

限制与必须披露的风险：

* 合格率低：403 → 5（1.2%）；29 个存活里只有 5 个同时满足 MSMS 与 MMBS。扩大规模的主要成本在 witness 设计和操作级验证，不在候选提取。
* 来源不均衡：5 题中 4 题来自 Werkzeug，Jinja2 只有 1 题，click 为 0。两个来源满足最低要求，但不足以证明跨项目可扩展性。
* 机制覆盖不全：没有合格的循环状态、对象状态或多操作同时协作题；现有 U 最大为 2 且两条路径互斥。若正式 benchmark 要求这些复杂度，需要补充新的候选形状与验证预算。
* 精确性范围窄：MSMS/MMBS 只在声明 U 和已执行输入上穷尽；不能把单输入结论写成“整个合法域精确”。所有题目都保留 `scope.not_claimed`。
* 使用限制：每增加一个项目都要重新固定版本、解释器、排除项和全套件结果；不能把不同项目的“passed 数”直接相加。

结论：**可以按本轮协议扩大生产，但不能跳过逐题 witness 验证；在达到更多项目（建议 ≥5）与更多机制（建议覆盖循环/对象状态）之前，不应把当前 5 题称为正式 benchmark 的最终规模。** 若只能扩大候选数量、不能同步增加人工或半自动的操作级验证，则合格题数不会随候选数线性增长。

## 5. 五个合格题目

所有题目目录为 `benchmark_real_v3/tasks/<task_id>/spec.json`，矩阵为 `benchmark_real_v3/evidence/<task_id>_matrix.json`。

### 5.1 `jinja2_bytecode_cache_read`

* A：`src/jinja2/loaders.py:132`，`code = bucket.code`。
* U：`compile_fallback`（第 137 行，缓存未命中时的编译回退）。
* 暴露输入：合法 `BytecodeCache` 返回由不同源码编译的字节码。P+ 渲染缓存值 `2`；P− 重新编译实际模板，渲染 `42`。
* 掩盖输入：缓存返回与源码一致的字节码。两侧都渲染 `42`；禁用编译回退后，P+ 仍从缓存得到可执行代码并渲染 `42`，P− 因 `code` 未绑定而抛异常，因此该掩盖被打破。
* MSMS = MMBS = `[compile_fallback]`。
* T_task：1 条；P− 适用套件：845 passed。

### 5.2 `werkzeug_filestorage_stream_name`

* A：`src/werkzeug/datastructures.py:2918`，`filename = getattr(stream, "name", None)`。
* U：`special_name_reset`（第 2924 行，把 `<...>` 特殊流名重置为 `None`）。
* 暴露输入：临时文件流。P+ 的 `filename` 是路径；P− 为 `None`。
* 掩盖输入：`<stderr>` 流。两侧都为 `None`；禁用重置后，P+ 为 `"<stderr>"`，P− 为 `None`。
* MSMS = MMBS = `[special_name_reset]`。
* T_task：10 条；P− 适用套件：816 passed、24 deselected。

### 5.3 `werkzeug_bind_server_name_lower`

* A：`src/werkzeug/routing/map.py:307`，`server_name = server_name.lower()`。
* U：`bind_relower`（第 219 行，`Map.bind` 再次小写化）。
* 暴露输入：显式 `server_name="EXAMPLE.COM"` 且不提供 subdomain。P+ 的 subdomain 为 `""`；P− 为 `"<invalid>"`。
* 掩盖输入：显式提供 subdomain=`"www"`，跳过子域比较块。两侧 `server_name` 都是 `"example.com"`；禁用 `Map.bind` 的再次小写化后，P+ 仍为 `"example.com"`，P− 为 `"EXAMPLE.COM"`。
* MSMS = MMBS = `[bind_relower]`；掩盖依赖控制前置条件“subdomain 已显式提供”，该条件不在 U 内。
* T_task：8 条；P− 适用套件：816 passed、24 deselected。

### 5.4 `werkzeug_get_host_default_empty`

* A：`src/werkzeug/sansio/utils.py:82`，`host = ""`。
* U：`overwrite_host_header`（第 85 行）、`overwrite_server`（第 87 行）。
* 暴露输入：Host 头与 server 都不提供。P+ 返回 `""`；P− 在第一次使用 `host` 时抛 `UnboundLocalError`。
* 掩盖输入 1：提供 Host 头。两侧都是 `"example.com"`；禁用 `overwrite_host_header` 后，P− 因 `host` 未绑定而抛异常。MSMS = MMBS = `[overwrite_host_header]`。
* 掩盖输入 2：只提供 server 地址。两侧都是 `"example.com:8080"`；禁用 `overwrite_server` 后同样暴露。MSMS = MMBS = `[overwrite_server]`。
* 两条掩路径互斥，同一输入上最多一条生效；但它们是两个独立的合法输入上的独立掩盖路径。
* T_task：118 条；P− 适用套件：816 passed、24 deselected。

### 5.5 `werkzeug_secure_filename_ascii_filter`

* A：`src/werkzeug/utils.py:222`，`filename = filename.encode("ascii", "ignore").decode("ascii")`。
* U：`sanitize_whitelist`（第 227–229 行，后续白名单清洗块）。
* 暴露输入：`"a b"`（U+1680 OGHAM SPACE MARK，NFKD 不分解、非 ASCII 且是 Python 空白）。P+ 为 `"ab"`；P− 为 `"a_b"`。
* 掩盖输入：`"北京.txt"`。后续白名单把非 ASCII 字母删掉，两侧都是 `"txt"`；禁用白名单后，P+ 为 `".txt"`，P− 为 `"北京.txt"`。
* MSMS = MMBS = `[sanitize_whitelist]`。
* T_task：1 条；P− 适用套件：816 passed、24 deselected。

## 6. 29 个存活候选的判定

完整逐候选理由在 `benchmark_real_v3/evidence/qualification_registry.json`；筛选原始记录在 `benchmark_real_v3/evidence/screening_rows/`。

| verdict | 数量 | 含义 |
|---|---:|---|
| `QUALIFIED` | 5 | 暴露与掩盖均有执行确认，MSMS/MMBS 非空 |
| `REJECT_NO_EXPOSING_INPUT` | 8 | 运行时恒等、等价替换或死存储；没有合法输入能区分 P+/P− |
| `REJECT_NO_MASKING_RELATION` | 16 | 未建立操作级掩盖；其中 1 个是 MSMS-only，15 个没有执行确认的掩盖 |

`REJECT_NO_MASKING_RELATION` 不等于“A 无风险”。例如：

* `debug.py:42` 删除会改变异常 traceback，存在可构造的暴露输入；但 `Template.render` 不在 `internal_code` 中，后续帧过滤不会吸收差异。
* `datastructures.py:2921` 的 `fsdecode` 在 bytes 流名上会改变公开 `filename`；但特殊名重置只在 `<...>` 上生效，那里是暴露而不是掩盖。
* `datastructures.py:339` 的 `list(value)` 删除会暴露列表别名差异；但同一分支没有后续操作重新供应或吸收该值。

这些候选保留为“有删除风险、尚未找到操作级掩盖”的记录，不用它们凑题。

### 6.1 MSMS-only 补充案例（不计入 5 题）

`werkzeug-2.2.3:src/werkzeug/http.py:440:continued_encoding`：

* 暴露输入：`attachment; filename*0*=utf-8''%E4%B8%AD; foo=bar; size*1*=%E6%96%87`。P+ 的 `size` 为原始 `%E6%96%87`；P− 继续沿用先前的 UTF-8 编码并解码为 `文`。
* 掩盖输入：`... foo=bar; size*0*=utf-8''%E6%96%87; size*1*=%E5%AD%97`。P+ 与 P− 都是 `文字`；MSMS = `[write_state]`（第 444 行）。
* MMBS = 空：禁用第 444 行后，P+ 与 P− 都不再有非 None 的 `continued_encoding` 来源，删除 A 不再可观察。这是一个“被掩盖但不可被该 U 打破”的真实案例，故不满足本轮的 both-direction 资格线。
* 对称候选（A=第 444 行，U=第 440 行）在纸面上可能得到非空 MMBS，但第 444 行不是静态候选，且 403 次 targeted 预算已用完，本轮**未筛查、未验证**，状态为 UNVERIFIED；不得当作合格题引用。

## 7. 答案语义与证明边界

每题的可签发答案必须包含：

1. 源码位置与删除方法（`spec.target_operation`、`deletion_method`）。
2. 暴露 witness 与合法输入说明（`spec.inputs[].role = exposing`）。
3. 掩盖 witness 与执行观察（`role = masking`）。
4. 启用/禁用矩阵：`evidence/<task_id>_matrix.json` 中每个 U 子集的 P+/P− 观测。
5. 最小性检查：MSMS/MMBS 由 U 的全部子集枚举得到，最小性在 U 内穷尽。
6. 候选全集与已知范围：`candidate_universe`、`universe_notes`、`scope.not_claimed`。
7. 验证范围与 UNKNOWN：只对已执行输入和声明 U 作精确声明；U 之外、未执行输入、未筛查的对称候选均为 UNKNOWN/UNVERIFIED。

不能在单个输入上观察成功就宣称“整个合法域精确”。本报告所有“精确”字样都限定为“声明 U 内的全部子集 + 已执行输入”。

## 8. 交付物与复现

目录：`benchmark_real_v3/`

| 内容 | 路径 |
|---|---|
| 固定项目/环境/预算 | `config.py`、`config.py:BUDGET` |
| 静态候选（799） | `candidates/candidates_static.json` |
| 全候选与筛选/资格合并视图 | `candidates/candidates_full.json` |
| 筛选漏斗 | `evidence/screening_funnel.json`、`evidence/funnel_summary.json` |
| 每题检查点 | `evidence/screening_rows/*.json` |
| 29 个存活候选逐条判定 | `evidence/qualification_registry.json` |
| 合格题目清单 | `tasks/qualified_tasks.json` |
| 题目 spec | `tasks/<task_id>/spec.json` |
| 启用/禁用矩阵 | `evidence/<task_id>_matrix.json` |
| 源码哈希 | `evidence/project_source_hashes.json` |
| 被废弃的第一轮 | `evidence/superseded_scanning_round1/` |
| MSMS-only 补充案例 spec/矩阵 | `evidence/rejected_tasks/`、`evidence/werkzeug_parse_options_header_continuation_state_matrix.json` |

复现命令：

```bash
cd <local-path>
python -m benchmark_real_v3.run_all scan
python -m benchmark_real_v3.run_all trace
python -m benchmark_real_v3.run_all screen
python -m benchmark_real_v3.run_all verify
python -m benchmark_real_v3.run_all report
```

（`screen` 会按检查点恢复；`verify` 对每个题目的 U 枚举全部子集并重新执行声明的输入。）

本轮没有运行 MACE 或 Qwen，没有用任何模型输出修正题目，也没有修改 M1–M6 的历史结果。

后续的独立验收、公开/隐藏包、规范化评分器、回归测试与冻结结果见
`docs/MACE_benchmark_v3_acceptance.md`。
