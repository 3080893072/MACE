# MACE Benchmark v3：五道真实题的独立验收、冻结与评分闭环

- 日期：2026-11-02
- 版本：`v3.0-dev-pilot-2026-11-02`
- 标签：**DEVELOPMENT/PILOT**
- 范围：只验收、打包、评分与冻结已有的 5 道题；不搜索新题，不运行 MACE/Qwen，不修改 Full MACE，不修改 M1–M6 历史结果。

---

## 0. 结论摘要

1. **5/5 通过独立验收**，0 道 `NEEDS_REVIEW`。
2. **5/5 可自动评分**；评分器重新执行 P+/P− 与子集枚举，不信任提交的期望状态。
3. 每道题都确认了至少一条暴露反例和一条执行确认的掩盖关系；共 18 条参考声明，其中 5 条暴露反例、6 条掩盖 witness 上的 MSMS、6 条对应 MMBS，外加 bind 的控制前置条件声明。
4. 所有结论都只在**声明的有限输入 + 声明的候选全集 U** 上成立；没有一道题获得 `PROVEN`，也没有任何全合法域声明。
5. 评分协议已可接收真实 MACE/Qwen 的 JSON 提交，但**本轮没有运行任何模型**，因此不声称任何模型分数。
6. 可以在获得明确授权后开始小规模基线试跑；这 5 道题是开发/试点题目，不是未来 held-out 测试集。

---

## 1. 独立验收

### 1.1 独立性边界

验收路径为 `benchmark_real_v3/acceptance_v3.py`，刻意不复用题目构造阶段的验证逻辑：

- 自己复制项目树；
- 自己做单行删除（A 替换为等缩进 `pass  # P-: target A deleted`，保持行号）；
- 自己运行 probe；
- 自己枚举 U 的全部子集并重算 masked/exposed/MSMS/MMBS；
- 自己调用 pytest 并解析 JUnit；
- 不导入 `verify_task`、`variant_lab`、`run_suite`。

补充验收 `benchmark_real_v3/acceptance_t_task_trace.py` 使用独立 pytest 插件与
`sys.settrace`，在冻结的 `T_task` 执行期间逐文件逐行确认 A 确实被执行；它同样不复用上述构造代码。

### 1.2 每题检查项

| 检查 | 含义 | 结果 |
|---|---|---|
| source_and_single_line_diff | P+ 与 P− 只在目标源文件、目标行不同 | 5/5 通过 |
| deletion_record | 原行与替换行逐字记录 | 5/5 通过 |
| candidate_universe_positions | U 的文件/行/代码与源码一致 | 5/5 通过 |
| target_execution | 每个声明 witness 输入下 A 都执行 | 5/5 通过 |
| matrix_reproduction | 独立重算的矩阵与存档矩阵完全一致 | 5/5 通过 |
| minimality | 枚举 U 的全部子集，无更小的有效子集 | 5/5 通过 |
| task_specific | Jinja2 备份路径、get_host 两条替代掩盖路径 | 5/5 通过 |
| p_minus_full_suite | P− 上项目适用套件通过 | 5/5 通过 |
| t_task_on_p_plus | 冻结 T_task 在 P+ 上通过 | 5/5 通过 |
| t_task_executes_A | T_task 实际执行 A（补充 trace） | 5/5 通过 |

### 1.3 每题验收数据

| task_id | 项目 | 难度 | A 位置 | P− 适用套件 | T_task | T_task 执行 A |
|---|---|---|---:|---:|---:|---|
| `jinja2_bytecode_cache_read` | Jinja2 3.1.3 | medium | `src/jinja2/loaders.py:132` | 845 passed | 1 passed | 是 |
| `werkzeug_bind_server_name_lower` | Werkzeug 2.2.3 | medium | `src/werkzeug/routing/map.py:307` | 816 passed, 24 deselected | 8 passed | 是 |
| `werkzeug_filestorage_stream_name` | Werkzeug 2.2.3 | easy-medium | `src/werkzeug/datastructures.py:2918` | 816 passed, 24 deselected | 10 passed | 是 |
| `werkzeug_get_host_default_empty` | Werkzeug 2.2.3 | medium | `src/werkzeug/sansio/utils.py:82` | 816 passed, 24 deselected | 118 passed | 是 |
| `werkzeug_secure_filename_ascii_filter` | Werkzeug 2.2.3 | medium | `src/werkzeug/utils.py:222` | 816 passed, 24 deselected | 1 passed | 是 |

Werkzeug 的 24 条 `dev_server` 测试是按协议排除的，不声称未过滤套件全部通过。
T_task 只来自 P+ 覆盖，未按模型结果挑选。

**关键专项结果：**

- **Jinja2**：`compile_fallback`（`loaders.py:137`）在 `mask_cache_benign` 上掩盖 A；
  `expose_cache_poisoned` 上 P+ 返回 `2`，P− 返回 `42`，可观察结果不同。
- **Werkzeug get_host**：两条互斥路径分别被验证为掩盖者：
  `overwrite_host_header:85` 掩盖 `mask_host_header`，
  `overwrite_server:87` 掩盖 `mask_server`；两者不是同一个操作。
- **Werkzeug bind**：`bind_relower:219` 在 `subdomain` 已提供时掩盖 A；
  `subdomain is None` 时 A 的值先被 subdomain 比较消费，暴露差异。
  这是控制前置条件，不是新的候选操作。
- **FileStorage**：`special_name_reset:2924` 在 `stream="stderr"` 时把
  `filename` 重置为 `None`，掩盖 A 的派生值。
- **secure_filename**：`sanitize_whitelist:227-229` 在 `"北京.txt"` 上把
  A 删除后留下的结果再次清洗为 `"txt"`。

---

## 2. 最终资格清单

| # | task_id | 项目/版本 | A（精确位置） | U 大小 | witness（暴露/掩盖） | 参考声明 | 资格 |
|---|---|---|---:|---:|---:|---:|---|
| 1 | `jinja2_bytecode_cache_read` | Jinja2 3.1.3 | `code = bucket.code` @ `loaders.py:132` | 1 | 1 / 1 | 3 | **QUALIFIED / PASS** |
| 2 | `werkzeug_bind_server_name_lower` | Werkzeug 2.2.3 | `server_name = server_name.lower()` @ `map.py:307` | 1 | 1 / 1 | 4 | **QUALIFIED / PASS** |
| 3 | `werkzeug_filestorage_stream_name` | Werkzeug 2.2.3 | `filename = getattr(stream, "name", None)` @ `datastructures.py:2918` | 1 | 1 / 1 | 3 | **QUALIFIED / PASS** |
| 4 | `werkzeug_get_host_default_empty` | Werkzeug 2.2.3 | `host = ""` @ `sansio/utils.py:82` | 2 | 1 / 2 | 5 | **QUALIFIED / PASS** |
| 5 | `werkzeug_secure_filename_ascii_filter` | Werkzeug 2.2.3 | ascii 过滤赋值 @ `utils.py:222` | 1 | 1 / 1 | 3 | **QUALIFIED / PASS** |

参考声明合计 18 条；另有一个 MSMS-only 补充案例被拒绝，证据保留在隐藏包
`evidence/werkzeug_parse_options_header_continuation_state_*`，不计入 5 题。

---

## 3. 已确认的部分真值

“已确认”在本包中只有两种含义：

- `WITNESS_VERIFIED`：在提交的具体输入上，P+ 与 P− 可执行且观察不同，或指定集合在 U 上满足 MSMS/MMBS；
- `FINITE_DOMAIN_EXACT`：提交了 2–12 个有限输入，每个都验证通过，且 U 的全部子集都枚举过。

两者都不是全合法输入域的证明。

### 3.1 逐题真值

| task_id | 暴露 witness（P+ vs P−） | 掩盖 witness（P+ = P−） | 确认的掩盖集合 |
|---|---|---|---|
| Jinja2 | poisoned cache：`2` vs `42` | benign template：均 `42` | `{compile_fallback}` |
| bind | `subdomain=None`：`example.com` vs `EXAMPLE.COM` | `subdomain="www"`：均 `example.com` | `{bind_relower}`，条件 `subdomain is not None` |
| FileStorage | 普通临时流：临时路径 vs `None` | `stderr`：均 `None` | `{special_name_reset}` |
| get_host | 无 Host 无 server：`""` vs `UnboundLocalError` | Host 头：均 `example.com`；server：均 `example.com:8080` | `{overwrite_host_header}`、`{overwrite_server}` |
| secure_filename | `a b`：`ab` vs `a_b` | `北京.txt`：均 `txt` | `{sanitize_whitelist}` |

### 3.2 每道题都没有被提升为命题

- 没有 `PROVEN`；
- 没有“所有合法输入”结论；
- 没有“U 外不存在其他 B/C/D/E”的结论；
- get_host 的两条路径只证明这两个 masker 在各自输入上有效，不证明没有第三条路径；
- bind 的前置条件只在两个提交点上验证，不是普遍蕴含；
- 单 witness 的 MSMS/MMBS 仍是 `WITNESS_VERIFIED`，只有多输入全通过才是
  `FINITE_DOMAIN_EXACT`，且 scope 明写“不是整个合法输入域”。

---

## 4. 公开包 / 隐藏包

### 4.1 公开包

`benchmark_real_v3/release/PUBLIC/`，14 个文件：

- 每题 `task.json`：标签、项目/版本、目标源文件与 SHA-256、A 的精确位置与代码、
  分析范围、测试范围、冻结 T_task、合法输入合同、观察合同、提交格式；
- 每题 `source/<target file>`：**原始上游源文件**，逐字节一致；
- `tasks/index.json`、`input_contracts.json`、`submission_format.md`、`README.md`。

公开包不包含：U 的位置/ID、witness ID/payload、矩阵、参考关系、隐藏证据路径。

### 4.2 隐藏包

`benchmark_real_v3/release/HIDDEN/`，41 个文件：

- 每题 `reference.json`：U、witness、参考关系、参考声明、部分真值、归因范围、验收摘要；
- `evidence/`：存档矩阵、独立重算矩阵、P− 全套件日志/JUnit、T_task 日志、
  验收报告、泄漏检查、T_task 执行 trace、结构化更正记录、资格注册表、
  漏斗汇总、项目源码哈希、被拒绝的补充案例。

### 4.3 泄漏检查

`benchmark_real_v3/leak_check.py` 对公开包做 22 项检查，结果 **通过，0 findings**：

- 公开文件清单与预期完全一致（14 个）；
- 每个公开源文件与冻结上游文件字节一致，且与 `task.json` 中的 SHA-256 一致；
- 公开元数据不含隐藏操作 ID、witness ID、隐藏路径、隐藏键名；
- 公开元数据不含非 A 的隐藏行号或隐藏操作代码（与 A 代码文本相同的重复语句除外，
  这不是额外披露）；
- 标签为 `DEVELOPMENT/PILOT`，不出现未来 held-out 的说法；
- `SHA256SUMS` 覆盖全部发布文件，manifest 的 bundle 摘要与文件计数一致。

报告：`benchmark_real_v3/evidence/acceptance/leak_report.json`。

---

## 5. 规范化评分器

### 5.1 入口

```bash
python -m benchmark_real_v3.scoring.score submission.json --out result.json
```

评分器对每个提交重新构造 P+/P−、重新运行 probe、重新枚举 U 的子集；
参考矩阵只用于出题和演示，不用于给分。

### 5.2 状态语义

| 状态 | 含义 | 是否计分 |
|---|---|---|
| `WITNESS_VERIFIED` | 具体 witness 上执行确认 | 是 |
| `FINITE_DOMAIN_EXACT` | 所有提交的有限输入均通过，且 U 全部子集枚举 | 是 |
| `PROVEN` | 保留状态；没有形式化证明检查器，**从不分配** | 否 |
| `FALSE` | 执行结果与声明矛盾 | 否 |
| `INVALID` | 声明格式错误或输入违反合同 | 否 |
| `UNVERIFIED` | 操作不在 U 内，或证明无法独立检查 | 否 |
| `UNSUPPORTED` | 未知声明类型 | 否 |
| `DUPLICATE` | 与较早声明完全重复 | 否 |

### 5.3 关系类型

- `EXPOSING_COUNTEREXAMPLE`：P+ 与 P− 都必须可执行，且观察不同；P+ 返回 / P− 抛异常也算观察不同。
- `MSMS`：非空 S，满足 `Only(S) = Masked_strict(U\S)`，且不存在更小的非空有效子集。
- `MMBS`：非空 S，满足 `Break(S) = Exposed(S)`，且不存在更小的有效子集（含空集）。
- `PREREQUISITE_BREAKING`：在 condition 输入上是最小 breaking set，在 control 输入上不 breaking。
- `CONDITIONAL_CORRECTNESS`：condition 输入上 breaking，conclusion/control 输入上不 breaking；
  只报告两个提交点的条件结果。
- `PROVEN`：语法接受，评分 `UNVERIFIED`。

### 5.4 防止空洞掩盖

评分器用 `acceptance_probe.py` + `sys.settrace` 检查 A 是否真的执行。
如果提交的输入使 A 不执行，MSMS/MMBS 不得通过；MSMS 还要求存在非空的 MMBS
证据，避免“A 根本没跑，所以删掉任何东西都看不出差别”的空洞关系。

### 5.5 去重与归因

- 完全重复的声明记为 `DUPLICATE`，不计分；
- 同一关系换一个输入重复提交，状态仍可验证，但第二次不增加信用；
- `score.credited_relations` 统计唯一关系键，不统计尝试次数；
- 操作位置按项目相对 `{file,line,end_line?,code?}` 解析；U 外位置为 `UNVERIFIED`，
  文件/行不存在或代码不匹配为 `INVALID`；
- 最小性只在声明的 U 和实际执行的有限输入上精确。

---

## 6. 端到端评分演示（无模型）

### 6.1 一条命令

```bash
python -m benchmark_real_v3.scoring.demo
```

输出目录：`<local-path>/`，报告：
`<local-path>`。

### 6.2 结果

5 道题 × 5 类人工提交，`all_expectations_met: true`：

| 类别 | 预期 | 实际 |
|---|---|---|
| correct | 全部 `WITNESS_VERIFIED` | 5/5 题全部通过；18 条唯一关系获得信用 |
| wrong | 用掩盖输入声称暴露、用暴露输入声称 MSMS | 每题两条均 `FALSE` |
| duplicate | 前半验证、后半 `DUPLICATE`，信用不翻倍 | 每题符合 |
| illegal | 非法输入、非法行号、`PROVEN`、未知类型 | `INVALID`×3、`UNVERIFIED`×1、`UNSUPPORTED`×1 |
| unverifiable | U 外操作、未检查证明 | `UNVERIFIED`×2 |

另有两个补充验证：

- Jinja2 两个不同的 benign 输入 → `FINITE_DOMAIN_EXACT`，scope 明写有限域；
- bind 的 `PREREQUISITE_BREAKING` 与 `CONDITIONAL_CORRECTNESS` → `WITNESS_VERIFIED`，
  condition 输入 breaking、control 输入不 breaking。

### 6.3 自动化回归测试

```bash
python -m unittest discover -s benchmark_real_v3/scoring/tests -v
```

结果：**9 tests, OK（37.1s）**。覆盖 5 题正确提交、get_host 两条掩盖路径、
有限域状态、重复声明、跨输入重复关系、非法/不可验证状态、A 未执行拒绝、
前置条件/条件正确性、`PROVEN` 从不分配。

---

## 7. 冻结版本与校验

| 项 | 值 |
|---|---|
| release version | `v3.0-dev-pilot-2026-11-02` |
| label | `DEVELOPMENT/PILOT` |
| public files | 14 |
| hidden files | 40 |
| bundle SHA-256 | `470f32fa7efd9a2db4e5ee203b4a374db93da4c907876c923f09dd07b49b80d3` |
| manifest | `benchmark_real_v3/release/manifest.json` |
| checksums | `benchmark_real_v3/release/SHA256SUMS` |

主要代码文件哈希（完整列表见 manifest）：

| 文件 | SHA-256 |
|---|---|
| `scoring/engine.py` | `4a5d80efcd1354b4d10cdc2e44811c59e38e83cb756b7d606cd169caaf48a076` |
| `scoring/contracts.py` | `e702128080eee691286aae9969ce53dd0347ce5b4ceac1b557278cd1435f95c9` |
| `scoring/demo.py` | `1b72f2b0540e646d79bb43d4c05827fe7e40cb43f08d339a1ae3da9480f6c1ea` |
| `scoring/score.py` | `1c72bc067caa7cd3c20f80f24809b557194f4f595957ba95ea5c0ffb9dc86bee` |
| `scoring/tests/test_scoring.py` | `f8c6686fc554f47b89ed82513b76e525c6e0e61fddc3884ce3d72a098e74d6d1` |
| `acceptance_v3.py` | `ae9d6fc8552a6827837552d3a6d759dde568f8bdc564712d521b0e37a8aa79db` |
| `acceptance_t_task_trace.py` | `8e5c8d7d7e27389eb8932eb0bd3436a6049766f22ce44ce4de047ad739c76714` |
| `leak_check.py` | `0a0199273bf1e295948c373862e6cd92f20173631ef3ecd3a2dd4e608ebf5713` |
| `release_build.py` | `1872e557267091ad5687521a74dd808577484c70390b1557d2f86755f3d0c70a` |

**冻结规则**：公开包与隐藏包一起冻结；未来 MACE/Qwen 分数不得用于修改隐藏答案。
任何更正必须另开版本化记录，并重新生成 manifest，不得静默覆盖。

---

## 8. 更正记录（本轮）

本轮没有降低任何题目的资格标签；以下问题都在最终报告前修正并重跑，旧中间结果不作为标签使用。

1. **空洞 MSMS（评分器）**：初版评分器允许 bind 的 `{}` 输入在 A 未执行时
   得到 `WITNESS_VERIFIED`。修正为：用 `sys.settrace` 要求 A 执行，且 MSMS
   必须有非空 MMBS 证据。影响仅限评分器；5 道题的隐藏标签未改，demo 重跑全部通过，
   回归测试 `test_non_executing_input_is_not_a_masking_witness` 固化该行为。
2. **验收实现错误**：子集 ID 一度被按字符串拆成字符列表；路径比较一度混用
   `jinja2/loaders.py` 与 `src/jinja2/loaders.py`；代码比较一度受换行/空白影响。
   均已修正，最终验收对 5 道题完整重跑，报告以
   `evidence/acceptance/acceptance_report.json` 为准。
3. **T_task trace 环境**：首次 trace 时 `PYTHONPATH` 覆盖了项目 `src/`，
   Werkzeug 复制树导入失败，Jinja2 则可能导入已安装包。修正为把复制树的
   `src/` 放在 `PYTHONPATH` 首位，5 道题重跑均确认 T_task 执行 A。

---

## 9. 六个问题的直接回答

### Q1：5 道题中有几道通过独立验收？

**5/5 通过**，0 道 `NEEDS_REVIEW`。独立路径重做了复制、删除、probe、子集枚举、
pytest 与 T_task 行执行 trace，结果与存档矩阵一致。

### Q2：有几道可以被评分？

**5/5 可以被规范化评分器评分**。评分器不依赖模型，重新执行 witness 与子集枚举；
5 题的 18 条参考声明全部 `WITNESS_VERIFIED`，错误/重复/非法/不可验证提交均得到预期状态。

### Q3：每题已确认的部分真值是什么？

每题都确认了：

- 至少一条合法暴露反例（P+ 与 P− 可执行且观察不同）；
- 至少一个掩盖 witness 上的最小掩盖集合（MSMS）与对应最小 breaking 集合（MMBS）；
- get_host 另有第二条互斥掩盖路径；bind 另有控制前置条件关系。

具体见 §3.1。确认级别是 `WITNESS_VERIFIED`，多输入时最多
`FINITE_DOMAIN_EXACT`，**不是 `PROVEN`，不是全合法域**。

### Q4：哪些仍然只是 witness 级？

- 所有 MSMS/MMBS 都只在提交的具体输入上成立；
- get_host 的两条路径只证明这两个 masker，不证明没有第三条；
- bind 的前置条件/条件正确性只在两个提交点上验证；
- U 之外的 B/C/D/E 没有被枚举，因此不声称已经找全；
- 没有形式化证明，`PROVEN` 从不分配。

### Q5：评分器现在能接收真实 MACE/Qwen 提交吗？

**协议与执行层可以，集成层尚未验证。** 评分器接受公开格式的 JSON，能解析操作位置、
执行 witness、枚举 U、给出 8 种状态并去重计分；真实模型输出需要一个薄适配器转换成
该 JSON。**本轮没有运行 MACE/Qwen**，因此没有任何模型分数，也不把“能接收”说成
“已经验证模型表现”。

### Q6：可以开始小规模基线试跑吗？

**可以，在明确授权后，以 DEVELOPMENT/PILOT 身份开始。** 建议：

- 固定 prompt、输入合同和提交适配器后一次冻结；
- 只在这 5 题上做小规模试跑，不据此增删题目；
- 不把试跑分数用于修改隐藏答案；
- 未运行的方法不得报告为 0%；
- 结果只作为试点信号，不作为 held-out 结论。

---

## 10. 范围与限制

- 5 题来自 2 个项目（Jinja2 1 题、Werkzeug 4 题），不是项目/机制的无偏样本；
- 题目从 403 个审查候选中选出，筛选漏斗不是随机抽样；
- U 很小（4 题大小为 1，get_host 为 2），最小性只在 U 内穷尽；
- Werkzeug 排除 24 条 `dev_server` 测试，不声称未过滤套件全部通过；
- 所有关系是有限输入上的执行事实，不是全合法域定理；
- 没有形式化证明检查器，`PROVEN` 保留但从不分配；
- 没有运行 MACE/Qwen，没有修改 Full MACE，没有修改 M1–M6 历史结果。

---

## 11. 产物索引

| 产物 | 路径 |
|---|---|
| 本验收文档 | `docs/MACE_benchmark_v3_acceptance.md` |
| 公开题目包 | `benchmark_real_v3/release/PUBLIC/` |
| 隐藏证据包 | `benchmark_real_v3/release/HIDDEN/` |
| 发布 manifest | `benchmark_real_v3/release/manifest.json` |
| 校验和 | `benchmark_real_v3/release/SHA256SUMS` |
| 独立验收报告 | `benchmark_real_v3/evidence/acceptance/acceptance_report.json` |
| T_task 执行 trace | `benchmark_real_v3/evidence/acceptance/t_task_execution.json` |
| 泄漏检查报告 | `benchmark_real_v3/evidence/acceptance/leak_report.json` |
| 结构化更正记录 | `benchmark_real_v3/evidence/acceptance/corrections.json` |
| 规范化评分器 | `benchmark_real_v3/scoring/` |
| 评分演示 | `benchmark_real_v3/scoring/demo.py`；输出 `<local-path>/` |
| 回归测试 | `benchmark_real_v3/scoring/tests/test_scoring.py` |
| 独立验收代码 | `benchmark_real_v3/acceptance_v3.py`、`acceptance_t_task_trace.py` |
| 发布构建 | `benchmark_real_v3/release_build.py` |
| 泄漏检查代码 | `benchmark_real_v3/leak_check.py` |
