# MACE Task B：开发集基线试跑报告

日期：2026-11-02  
工作目录：`<local-path>`  
性质：**DEVELOPMENT / PILOT**，5 道开发题；不是独立泛化评估。

---

## 1. 结论先行

1. **Direct Qwen**：5 题共 1 个有效关系（filestorage 的合法 EXPOSING），1/5 题有正确关系；MSMS/MMBS 一条也没有。其余是格式错误（2 题）、无法给出合法反例（1 题）、反例不暴露（1 题）。
2. **Qwen + 状态反馈 validator**：与 Direct 完全相同的 5 条最终 claim，仍然是 1 个有效关系；3 轮反馈只改了 submission id 和 token 消耗，没有修正 jinja2/bind/secure_filename 的错误。调用 11 次、token 53,655，约为 Direct 的 2.2 倍。
3. **Deterministic AST + 操作干预**：36 条 claim，30 条执行状态正确，15 条**唯一关系**得分；5/5 题都给出了至少 1 个 verified EXPOSING；4/5 题给出 verified MSMS/MMBS；jinja2 的 6 条 MSMS/MMBS 指向候选 U 之外（`loaders.py:119`），全部 `UNVERIFIED`，不是 FALSE。它没有回答 test_gap。
4. **Full MACE**：原实现没有关系级 `operations` 字段，也没有“每条关系一个合法输入”的接口，状态 `UNSUPPORTED_INTERFACE`，**不给 0%**。
5. **能力边界**：在这个开发集上，Qwen 1.5B 的直接推理只能偶尔命中“有一个合法暴露输入”，不能稳定做操作级归因；状态反馈不提供操作/标签信息，无法把错误变成正确；确定性 AST 在候选 U 内很强，但 U 不完整时会把真实掩盖操作判成 `UNVERIFIED`，且完全不做 test_gap。5 题中只有 jinja2 真正区分了 AST 与 LLM；其余 4 题 AST 全对，开发集无法估计泛化。

---

## 2. 冻结协议

| 项目 | 冻结值 |
| --- | --- |
| 标签 | `DEVELOPMENT/PILOT` |
| 发布版本 | `v3.0-dev-pilot-2026-11-02` |
| 任务数 | 5 |
| 公开包 bundle sha256 | `470f32fa7efd9a2db4e5ee203b4a374db93da4c907876c923f09dd07b49b80d3` |
| prompt 版本 | `mace-v3-baseline-prompt-1.1` |
| prompt sha256 | `fa9fd88c6e09403ed51fbf5dc3dead4d895b880c09320971a647f1773f22eb7a` |
| submission format sha256 | `d0b40861963ca5a9339688ec4349788ece965fb365b0db89a6046a59f07b29d4` |
| 模型 | `Qwen2.5-Coder-1.5B-Instruct`，本地只读 checkpoint |
| checkpoint sha256 | `18d06447b1b5ad8e620210bb4798d343076883c69095e70461882d3ffbe6b68f` |
| 解码 | `do_sample=false`，temperature 0，seed 42，bfloat16 |
| 上下文/生成长度 | 32,768 / 1,536 new tokens |
| Direct 预算 | 1 次模型调用/题，0 轮 validator |
| Validator 预算 | 最多 3 轮/3 次调用/题；反馈只含执行状态，不含隐藏标签/操作列表 |
| AST 预算 | 0 次模型调用；最多 32 个候选操作、12 个输入、64 次变体构建/题 |
| 评分 | 每个保存的 submission 只评分 1 次 |

### 2.1 v1.0 中止说明

v1.0 冻结后在第一次 direct 调用时中止：本地 RTX 5060 的 torch 构建只有 math SDPA kernel，14.5k token 的 prefill 耗尽 8 GiB。v1.1 只缩短了确定性源码窗口（A 前后 ±120 行、20k 字符），**未改任务、契约或提交接口**。v1.0 的目录 `runs/direct_prompt_1.0_aborted/` 已归档，不参与评分。

### 2.2 泄漏规则

- prompt 只读 `release/PUBLIC` 内的文件；
- hidden reference、矩阵、story label、witness 从不进入 prompt；
- validator 反馈只带状态；
- 没有用私有真值修改模型输出后再提交。

---

## 3. 五道开发题与逐题结果

### 3.1 总表

`claims` 是提交的 claim 数；`有效` 是 `credited_relations`（唯一关系数）；`正确状态` 是执行验证为 `WITNESS_VERIFIED`/`FINITE_DOMAIN_EXACT` 的 claim 数；`错误/未验证` 包含 `INVALID`、`FALSE`、`UNVERIFIED`。

| 任务 | Direct claims / 有效 / 错误 | Validator claims / 有效 / 错误 | AST claims / 正确状态 / 有效 / 错误 |
| --- | --- | --- | --- |
| `jinja2_bytecode_cache_read` | 1 / 0 / 1 INVALID | 1 / 0 / 1 INVALID | 8 / 2 / 1 / 6 UNVERIFIED |
| `werkzeug_bind_server_name_lower` | 2 / 0 / 2 INVALID | 2 / 0 / 2 INVALID | 8 / 8 / 3 / 0 |
| `werkzeug_filestorage_stream_name` | 1 / 1 / 0 | 1 / 1 / 0 | 6 / 6 / 3 / 0 |
| `werkzeug_get_host_default_empty` | 0 / 0 / 0 | 0 / 0 / 0 | 7 / 7 / 5 / 0 |
| `werkzeug_secure_filename_ascii_filter` | 1 / 0 / 1 FALSE | 1 / 0 / 1 FALSE | 7 / 7 / 3 / 0 |
| **合计** | **5 / 1 / 4** | **5 / 1 / 4** | **36 / 30 / 15 / 6** |

### 3.2 Direct Qwen

| 任务 | 提交内容 | 结果 | 判定 |
| --- | --- | --- | --- |
| jinja2 | `{"input": {"src/jinja2/loaders.py": [123,132]}, "type": "EXPOSING_COUNTEREXAMPLE"}` | `INVALID`：`unknown input field(s)` | 把文件路径当成了输入字段，不是合法输入 |
| bind | 两条只有 `operation`、没有 `type` 的 dict | `INVALID`：`claim.type must be a string` | 没有形成 claim；提到了 map.py:219/307，但格式不支持 |
| filestorage | `{"data": "", "name": "example.txt", "stream": "named"}` | `WITNESS_VERIFIED`，EXPOSING 得分 1 | 唯一正确关系 |
| get_host | `claims=[]`，completion 1,536 tokens | 无 claim | 触发生成长度上限，未给出答案 |
| secure_filename | `{"filename": "<home>\\Documents\\secret\\password.txt"}` | `FALSE`：P+ 与 P− 观测相同 | 合法输入，但不暴露该删除 |

**Direct 合法暴露反例：1/5**（只有 filestorage）。没有提交任何 MSMS/MMBS。

### 3.3 Qwen + validator

最终提交与 Direct **逐题相同**：

- jinja2：同一个非法 input；
- bind：同样两条无 type 的 operation；
- filestorage：同一个已验证输入；
- get_host：空 claims；
- secure_filename：同一个不暴露的 Windows 路径。

validator 在 jinja2、bind、secure_filename 上各跑了 3 轮；filestorage 和 get_host 只跑 1 轮。3 轮状态反馈没有带来任何关系修正。**Validator 相对 Direct 没有增益，成本更高。**

### 3.4 Deterministic AST + 操作干预

| 任务 | AST 的 36 条 claim 明细 | 有效关系 |
| --- | --- | --- |
| jinja2 | 2 条 EXPOSING verified；6 条 MSMS/MMBS 全部指向 `loaders.py:119`，在声明 U 之外，`UNVERIFIED` | 1（仅 EXPOSING） |
| bind | 2 EXPOSING + 3×MSMS + 3×MMBS，全部 verified | 3 |
| filestorage | 2 EXPOSING + 2×MSMS + 2×MMBS，全部 verified | 3 |
| get_host | 1 EXPOSING + 3×MSMS + 3×MMBS，全部 verified | 5（两个不同的 MSMS 关系 + 两个 MMBS + EXPOSING） |
| secure_filename | 1 EXPOSING + 3×MSMS + 3×MMBS，全部 verified | 3 |

- **合法暴露反例：5/5 题**，共 8 条 verified EXPOSING claim（jinja2 2、bind 2、filestorage 2、get_host 1、secure 1）。
- **MSMS/MMBS：4/5 题**（jinja2 除外）。
- 36 条 claim 中只有 15 条拿到唯一关系分：同一关系在不同输入上重复提交，执行正确但后续重复不再计分。所以“30 条正确状态”与“15 条有效关系”不矛盾。
- AST 不生成 `test_gap`；它的 submission 明确写“not attempted”。

**AST 在 jinja2 上的边界**：它确实找到了 2 个能暴露删除的合法输入，但把掩盖操作归到 `src/jinja2/loaders.py:119`，而该行不在声明的候选 U 里，评分器只能判 `UNVERIFIED`。这不是“AST 完全错”，而是“AST 的归因依赖候选 U 的完整性；U 不包含真实掩盖行时，它不会自己扩展 U”。

### 3.5 Full MACE

原 Full MACE 输出的是参数/效果级归因（`target_effects`、`upstream`、`observers`、`mask_guard`），没有本 benchmark 需要的关系级 `operations` 字段，也没有“每条关系配一个合法输入”的接口。因此：

- 状态：`UNSUPPORTED_INTERFACE`
- 分数：`null`
- **不报 0%**，也不把它当作“失败方法”计入分母。

---

## 4. test_gap：0/5 是记录伪影，不是 0/5 准确率

Direct 与 Validator 都回答了 5 条 test_gap，但只有 1 条能与真值按完整 node id 对上：

| 任务 | 模型回答 | 真值 | 是否可映射 | 判定 |
| --- | --- | --- | --- | --- |
| jinja2 | `TestBytecodeCache::test_simple` | `TestByteCodeCache::test_simple` | 否（大小写 C 不同） | 无法计分 |
| bind | `test_server_name_casing`、`test_server_name_interpolation` | 完整 node id | 否（裸函数名） | 无法计分 |
| filestorage | `TestFileStorage::test_filename_is_set` | 该任务 10 个测试中没有这个 id | 否 | 无法计分 |
| get_host | 未回答 | 有 118 条 | 否 | 未覆盖 |
| secure_filename | `assertion_gap` | `masked` | 是 | **错误** |

所以汇总里的 `test_gap_correct: 0` 应读作：

- 可映射 1/5；
- 可映射中正确 0/1；
- **不是 0/5 的判定准确率**。

AST 不回答 test_gap（`test_gap_answered=0`），因此这一列不能拿来比较 AST。

---

## 5. 原测试为什么没发现：逐题分类

数据来自 `benchmark_real_v3/evidence/story_validation/<task>_tests.json`，是每个原测试在 A 所在函数返回处的局部观测分类。

| 任务 | 原测试分类 | 含义 |
| --- | --- | --- |
| jinja2 | `NO_LOCAL_EFFECT=1` | 唯一执行 A 的测试里，A 的赋值在返回处没有可观测变化 |
| bind | `NO_LOCAL_EFFECT=8` | 8 个测试都执行 A，但局部返回处看不到 A 的效果 |
| filestorage | `NO_LOCAL_EFFECT=9`，`ASSERTION_GAP=1` | 9 个无局部效果；`test_save_to_pathlib_dst` 是断言间隙 |
| get_host | `MASKED_EFFECT=118` | 118 个测试里 A 确实改变了局部变量，但后续 U 把它覆盖，普通断言在 P+ 和 P− 下都通过 |
| secure_filename | `MASKED_EFFECT=1` | 唯一测试里 A 的局部效果被后续赋值覆盖 |

解释：

- `NO_LOCAL_EFFECT`：A 执行了，但在函数返回处没有留下可观测差异；普通测试断言的是最终行为，不是 A 的局部变量。
- `ASSERTION_GAP`：测试的断言点与 A 的局部效果之间隔着其他状态/调用，无法用该断言区分 P+/P−。
- `MASKED_EFFECT`：A 的局部效果真实存在，但后续同名/同属性写入把它盖掉；这是最接近“语义掩盖”的原测试漏检形态，也是 get_host 118 条和 secure_filename 1 条的情况。

这解释了为什么“测试通过”不能推出“A 可删”：原测试检查的是最终行为，而 A 的效果可能只在函数内部短暂存在。

---

## 6. 计算成本

| 方法 | 模型调用 | prompt+completion tokens | 总墙钟（秒） | 说明 |
| --- | ---: | ---: | ---: | --- |
| Direct | 5 | 24,229 | 148.854 | 单题 8.3–86.0 秒；get_host 触发生成长度上限 |
| Validator | 11 | 53,655 | 421.786 | 约为 Direct 的 2.83× 墙钟、2.21× token、2.2× 调用 |
| AST | 0 | 0 | 1,531.1 | 变体构建/测试执行；jinja2 是 `resumed=true`（0.009 秒复用旧结果），其余 4 题 241.6–661.8 秒 |
| Full MACE | — | — | — | `UNSUPPORTED_INTERFACE`，未运行 |

AST 的墙钟最高，但没有模型 token 成本；它的耗时主要花在多次变体构建和测试执行，不是“推理更慢”。Direct 与 Validator 的 token 统计包含 prompt 和 completion。

---

## 7. 能力边界与正式实验需要多少机制

### 7.1 当前边界

1. **Direct Qwen 1.5B**：能生成“看起来像输入”的 JSON，但 5 题只有 1 题真正合法且暴露；不能稳定区分“合法输入”“合法但不暴露”“格式合法但 type 错”。它没有提交任何 MSMS/MMBS，说明关系级操作归因基本没有建立。
2. **状态反馈 validator**：反馈只告诉模型 claim 的执行状态，不告诉它正确操作、正确输入或标签；模型没有利用状态修正任何一条关系。3 轮反馈的收益为 0，成本约 2.2 倍。这个结论只适用于“只给状态”的 validator，不外推到“给操作/反例”的 validator。
3. **确定性 AST**：在候选 U 完整、任务属于已建模机制时，能给出 5/5 暴露反例和 4/5 MSMS/MMBS，且 0 条 FALSE；但 U 不完整时（jinja2）只能 `UNVERIFIED`，不会自动发现 U 外的掩盖行。它是“强但封闭”的基线。
4. **test_gap**：两个模型方法都没有可靠回答；AST 不回答。当前没有任何方法能在 5 题上证明会做逐测试判定。
5. **开发集区分度不足**：5 题里只有 jinja2 把 AST 与 LLM 拉开；其余 4 题 AST 全对。5 题不能用于估计泛化，也不能据此排名方法。

### 7.2 正式实验的建议规模

这不是从 5 题统计出来的效应量，而是由“机制覆盖 + 每题至少一个合法暴露反例 + 至少一个负控制”的实验设计推出的最低建议：

- **至少 6 个独立机制族，每族 3 道真实题 = 18 道**；
- 另加 **每族 1 道负控制/边界题**（有 A、有 U，但没有合法暴露反例，或 MSMS/MMBS 不成立）= **6 道**；
- 合计 **约 24 道**，来自 **≥4 个独立项目**，避免 click/pyparsing 两个项目主导。

6 个机制族应至少覆盖：

1. 条件回调/条件分支覆盖（本轮的 click 2482/3428）；
2. 容器归一化后被通配/清空路径覆盖（click 63）；
3. 构造器属性优先级覆盖（pyparsing 3371）；
4. 后处理阶段覆盖（pyparsing 823）；
5. **循环携带状态**（同一变量在循环内多次写，后一次掩盖前一次）；
6. **跨函数/对象状态 setter**（A 所在函数返回时看不到，后续对象状态写入才覆盖；这类题必须把观测点定义清楚，否则只能得到 `ASSERTION_GAP`）。

如果正式实验要声称“覆盖用户点名的机制”，还应再加第 7 族：**多条 fallback 掩盖路径**（同一 A 在不同合法分支上被不同 U 覆盖），每族 2–3 题，总数约 **20–27 道**。少于 6 族时，只能声称“在若干覆盖类机制上有效”，不能声称跨机制泛化。

### 7.3 评估集隔离

- Task B 的 5 道开发题来自 jinja2 / werkzeug；
- Task A 的 5 道新题来自 click / pyparsing；
- 项目不重叠，但 Task A 仍是**构造集**，不是未触碰的独立评估集。正式实验必须另建独立评估集，且不得用模型分数反选题目。

---

## 8. 原始日志与产物

### 8.1 汇总

- `benchmark_baseline/freeze.json`
- `benchmark_baseline/runs/baseline_summary.json`
- `benchmark_baseline/runs/baseline_summary_stdout.txt`
- `benchmark_baseline/reports/baseline_report.md`（本报告的基线侧副本/索引）

### 8.2 Direct

- `benchmark_baseline/runs/direct/run_summary.json`
- `benchmark_baseline/runs/direct_resume.log`
- `benchmark_baseline/runs/direct/<task>/final_submission.json`
- `benchmark_baseline/runs/direct/<task>/final_score.json`
- `benchmark_baseline/runs/direct_prompt_1.0_aborted/`（归档，不评分）

### 8.3 Validator

- `benchmark_baseline/runs/validator/run_summary.json`
- `benchmark_baseline/runs/validator.log`
- `benchmark_baseline/runs/validator/<task>/final_submission.json`
- `benchmark_baseline/runs/validator/<task>/final_score.json`

### 8.4 AST

- `benchmark_baseline/runs/ast/run_summary.json`
- `benchmark_baseline/runs/ast_resume.log`
- `benchmark_baseline/runs/ast/<task>/submission.json`
- `benchmark_baseline/runs/ast/<task>/score.json`
- `benchmark_baseline/runs/ast/<task>/work.json`

### 8.5 原测试分类

- `benchmark_real_v3/evidence/story_validation/jinja2_bytecode_cache_read_tests.json`
- `benchmark_real_v3/evidence/story_validation/werkzeug_bind_server_name_lower_tests.json`
- `benchmark_real_v3/evidence/story_validation/werkzeug_filestorage_stream_name_tests.json`
- `benchmark_real_v3/evidence/story_validation/werkzeug_get_host_default_empty_tests.json`
- `benchmark_real_v3/evidence/story_validation/werkzeug_secure_filename_ascii_filter_tests.json`

---

## 9. 合规声明

- 日志、提示、仓库中没有 API key/token/密码/`.env`/凭据。
- prompt 中没有私有 oracle、隐藏标签或真值答案。
- 没有用私有真值修改模型输出后再提交。
- 未运行的方法（Full MACE）标为 `UNSUPPORTED_INTERFACE`，没有报 0%。
- 未修改 Full MACE 算法；未大规模跑 Qwen；未修改 M1–M6 历史结果。
- 未修改冻结的原证据或隐藏答案。
- 未根据模型分数改题、改指标或改评测集。
