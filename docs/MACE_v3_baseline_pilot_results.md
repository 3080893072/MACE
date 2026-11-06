# MACE Benchmark v3 公平基线试跑结果

- 版本：`v3.0-dev-pilot-2026-11-02`
- 日期：2026-11-03
- 阶段：DEVELOPMENT / PILOT（5 道冻结题，18 条参考关系）
- 运行目录：`runs/v3_baseline_pilot/`
- 标签：`LIVE_MODEL_RUN` / `NO_MODEL_DETERMINISTIC_RUN` / `NOT_RUN` /
  `UNSUPPORTED_INTERFACE`

本文件只报告本轮实际执行的证据。**A/B 在线实验因本机没有可用的真实
Qwen 服务而记为 `NOT_RUN`，没有用 fake client 冒充在线运行**；C 完整执行
并交由冻结评分器打分。任何“Qwen 能做什么”的结论在本轮都不成立，只能等
真实服务可用后补跑。

---

## 1. 实验分支与提交

| 项 | 值 |
|---|---|
| 修复阶段分支 | `fix/mace-core-logic-repair` @ `a39fa01` |
| 基线实验分支 | `baseline/mace-v3-pilot` |
| 基线代码提交 | `a51faab7075e6b0c58d93e4e86e50061f27360a5` |
| 实验配置 SHA-256 | `7cd4df5c0478ec7b84f01b557cc0e498767e5a786505459c39663e11d76b591b` |
| 配置记录 commit | 与 `a51faab` 一致（先提交、后重跑） |
| Benchmark release | `v3.0-dev-pilot-2026-11-02` |
| 运行标签 | DEVELOPMENT / PILOT |

隔离措施：

- 未修改 5 道冻结题、公开 `task.json`、原始测试选择、`T_task` 记录。
- 未修改 HIDDEN 参考数据与评分器；评分通过子进程调用冻结的
  `python -m benchmark_real_v3.scoring.score` 完成。
- 未修改 M1–M6 冻结运行记录及既有 request/raw_response。
- 基线包 `benchmark_v3_baselines/` 不 import 评分器、不读取 HIDDEN；
  有单测锁定这一点（`test_baseline_package_does_not_import_the_scorer`）。
- 参考关系比对只在实验结束后的评估侧脚本
  `scripts/v3_reference_match.py` 中读取 HIDDEN，不进入模型输入、候选生成
  或参数调整。
- 全部源文件在运行时按 `source_sha256` 重新校验；5 个 hash 与冻结发行版
  一致。

运行产物（均在本轮生成）：

```
runs/v3_baseline_pilot/
  config.json  config.sha256  availability.json  summary.json
  reference_match.json  no_model_checks.json
  tasks/<task_id>/baseline_c/{baseline_c.json,submission.json}
  tasks/<task_id>/scores/C.json
  tasks/<task_id>/baseline_b/verifier_on_C.json
```

上一轮（提交前代码，配置记录的是父提交）保存在
`runs/v3_baseline_pilot_precommit_a39fa01/`，仅作追溯，不用于结论。

---

## 2. 三个基线的实际实现与接口

三个基线共享同一套公开输入处理、合法输入域校验、探针和最终证据验证；
差异只在“如何产生 proposal”。

### 2.1 Baseline A：Direct Qwen

实现：`benchmark_v3_baselines/direct_qwen.py`

| 项 | 值 |
|---|---|
| prompt 版本 | `direct-qwen-v3-baseline-1.0` |
| 输入 | 冻结的公开 `task.json`（含合法输入合同、观察合同、目标操作）+ 公开源码文件 |
| 输出 | 同一份 `submission_format.md` 定义的 claims（EXPOSING / MSMS / MMBS / PREREQUISITE） |
| 生成参数 | temperature 0.0，seed 42，`num_ctx` 32768，`num_predict` 4096，JSON mode |
| 调用上限 | 3 次/题，15 次总计；4096 completion tokens/次 |
| 记录 | `request.json`、`raw_response.txt`、`submission.json`、usage、耗时、模型与服务端标识 |
| HIDDEN 反馈 | 无。A 的答案不能依据 HIDDEN 结果修改 |

实现里没有任何 HIDDEN 读取路径，也没有“先看分数再改答案”的分支。

### 2.2 Baseline B：Qwen + 同一个确定性 Verifier

实现：`benchmark_v3_baselines/verifier.py` + `run_pilot.py`

- **初始 proposal 与 A 完全同一份**：B 不在 A 之外重新采样。
- Verifier 只做执行验证，不做生成：
  - `EXPOSING_COUNTEREXAMPLE`：重跑 P+/P−，观察必须不同；
  - `MSMS` / `MMBS`：在 *proposal 自己命名的操作全集* 上枚举子集，检查
    提交集合是否为最小关系；支持单 `input` 与 `inputs` 有限列表；
  - `PREREQUISITE_BREAKING`：condition 输入上是最小破除集，control
    输入上不是；
  - 判定为 `VERIFIED` / `REFUTED` / `UNKNOWN`，只把 `VERIFIED` 的 claim
    放进 `verified_submission.json` 再评分。
- **纯验证优先**：本轮定义为只报告 verification 后的结果，不重生成。
  `b_conditions` 里预登记了第二个独立条件 `feedback_regeneration`（明确
  记录调用数/Token/成本），本轮 `NOT_RUN`。
- 结构性盲区（实现里显式记录）：verifier 的操作全集只来自 proposal 命名
  的操作（上限 6 个）。模型没提到的操作不会被枚举；因此“在 proposal
  全集上成立”不等于“在隐藏 U 上成立”。这不是可修的参数，而是接口本身
  的证据边界。
- 本轮额外做了一次无模型检查：把 B 的 verifier 应用到 C 的提交上
  （`no_model_checks.json`），用于验证管线一致性，**不作为模型能力证据**。

### 2.3 Baseline C：确定性 AST + 程序干预

实现：`benchmark_v3_baselines/ast_discovery.py`、
`execution.py`、`baseline_c.py`

固定规则（全部只用公开源码）：

1. 定位包含目标行的函数；
2. 沿同文件调用边（含 `self.method`）得到有界可达函数集；
3. 候选操作 = 写入与 A **同一普通变量**的赋值；A 自己函数内只取 A 之后
   的赋值，可达辅助函数不受位置限制；包含这类赋值且内部没有其他候选的
   `if` 块也算一个操作；
4. 用公开输入网格做单操作删除干预，按“观察是否改变”剪枝、按行为签名
   去重、按改变次数排序，保留至多 6 个；
5. 对每个输入枚举剩余操作的子集，计算 masked/exposed 图与最小集；
6. 只有“每个成员在该输入上单独删除都会改变观察”的最小集才被提交；
   其余记为 UNKNOWN，不提交“无证据关系”；
7. 证据等级：≥2 个不同输入支持 → `FINITE_DOMAIN_EXACT`（仅对提交的有限
   输入与 C 自己的操作全集）；单输入 → `WITNESS_VERIFIED`。

C 不调用任何模型，输出是普通 submission envelope，外加
`baseline_c.json` 中的发现过程、剪枝记录、逐输入观察和 unknowns。

### 2.4 旧 Full MACE

旧 Full MACE 的 run loop 输出代码级 guard，没有操作级 MSMS/MMBS 提交
接口。本轮统一记为 `UNSUPPORTED_INTERFACE`，**不记 0 分**。

---

## 3. 在线运行与非运行

### 3.1 可用性检查（2026-11-03T07:45:29Z）

`runs/v3_baseline_pilot/availability.json` 记录：

| 检查 | 结果 |
|---|---|
| `ollama` 可执行文件 | 不存在（`null`） |
| `http://127.0.0.1:11434/api/tags` | 不可达（`WinError 10061`，连接被拒绝） |
| 目标模型 `qwen2.5-coder:32b` | 不存在（端点不可达，无法列出） |
| DashScope key | 不存在 |
| 本机 Qwen 权重缓存 | 不存在 |
| 结论 | `available: false` |

### 3.2 运行标签

| 基线 | 标签 | 说明 |
|---|---|---|
| A Direct Qwen | `NOT_RUN` | 真实服务不可用；未用 fake client 替代 |
| B Qwen + Verifier | `NOT_RUN` | 同上；`feedback_regeneration` 条件同样未执行 |
| B 纯验证（无模型检查） | `NO_MODEL_VERIFIER_CHECK` | 只对 C 的提交做管线校验 |
| C AST + Intervention | `NO_MODEL_DETERMINISTIC_RUN` | 完整执行并评分 |
| 旧 Full MACE | `UNSUPPORTED_INTERFACE` | 接口不存在，不是 0 分 |

`fixtures/dry_run/` 只用于 `--dry-run` 的管线演练，若使用会被标为
`DRY_RUN`；本轮没有把它当作任何在线证据。`FIXED_PROPOSAL_REPLAY` 本轮
未使用。

### 3.3 未产生的记录

因为 A/B 是 `NOT_RUN`，所以不存在本轮的真实 `request.json` /
`raw_response.txt` / token 计数 / 模型端标识。报告中不会补写、推测或
用历史运行的响应顶替。

---

## 4. 五题逐题结果

公共约定：

- 每题最多 8 个公开输入（实际使用 6–8 个），最多 6 个候选操作；
- `U_hidden` 是冻结参考里的隐藏候选全集，`U_C` 是 C 从公开源码发现的
  操作全集；
- 评分状态只认 `WITNESS_VERIFIED` / `FINITE_DOMAIN_EXACT`；`PROVEN`
  在本发行版永远不会被授予；
- “credited”按 `relation_key` 去重计数，同一关系换输入不重复计分；
- 本轮全部 5 题：`FALSE = 0`、`UNVERIFIED = 0`、`INVALID = 0`、
  `DUPLICATE = 0`。这不是“已证明 C 不会出错”，而是“本轮提交的每条关系
  都被冻结评分器在有限输入上确认”。

### 4.1 `jinja2_bytecode_cache_read`（`NO_LOCAL_EFFECT`）

- 目标：`src/jinja2/loaders.py:132`；公开输入 6 个；
- `U_hidden` = `{137}`，`U_C` = `{137}`（完全一致）；
- 提交 4 条，credited 4 条：参考 3/3 + 额外 1 条前置关系；
- 证据等级：EXPOSING `WITNESS_VERIFIED`；MSMS `FINITE_DOMAIN_EXACT`；
  MMBS `FINITE_DOMAIN_EXACT`；PREREQUISITE `WITNESS_VERIFIED`；
- 资源：24 次探针执行，4 个变体，10.35 s；unknown 0；
- 原测试故事：原测试执行了 A，但 A 没有局部效应；C 在**其他公开输入**
  上仍找到了完整的 masking 关系，说明故事标签描述的是原测试，而不是
  关系是否存在。

### 4.2 `werkzeug_bind_server_name_lower`（`NO_LOCAL_EFFECT`）

- 目标：`src/werkzeug/routing/map.py:307`；公开输入 7 个；
- `U_hidden` = `{219}`，`U_C` = `{219, 311}`（C 多发现 1 个候选，但只有
  219 进入被提交的最小关系）；
- 提交 4 条，credited 4 条：参考 4/4 + 额外 0；
- 证据等级：EXPOSING `WITNESS_VERIFIED`；MSMS/MMBS
  `FINITE_DOMAIN_EXACT`；PREREQUISITE `WITNESS_VERIFIED`；
- 资源：76 次探针，12 个变体，28.96 s；unknown 0；
- 原测试故事同 4.1：8 个原测试都是 `NO_LOCAL_EFFECT`，关系来自其他输入。

### 4.3 `werkzeug_filestorage_stream_name`（`ASSERTION_GAP_STORY`）

- 目标：`src/werkzeug/datastructures.py:2918`；公开输入 6 个；
- `U_hidden` = `{2924}`，`U_C` = `{2924, 2921, 2926}`；
- 提交 4 条，credited 4 条：参考 3/3 + 额外 1 条前置关系；
- 证据等级：EXPOSING `WITNESS_VERIFIED`；MSMS 只有
  `WITNESS_VERIFIED`（只有一个输入同时满足“masked 且有最小破除集”）；
  MMBS `FINITE_DOMAIN_EXACT`；PREREQUISITE `WITNESS_VERIFIED`；
- 资源：80 次探针，16 个变体，30.04 s；**input 级 UNKNOWN 3 条**：
  `{"stream":"none","data":"abc"}`、`{"stream":"named","name":"<stderr>"}`、
  `{"stream":"named","name":"<stdin>"}` 都是 masked，但在 C 的操作全集上
  找不到“每个成员单独删除都改变观察”的最小充分集，因此不提交关系；
- 这 3 条 UNKNOWN 是本题 MSMS 停留在 witness 级、且没有第二输入的原因，
  也说明“有限域”在这里确实受限。

### 4.4 `werkzeug_get_host_default_empty`（`FULL_MASKING_STORY`）

- 目标：`src/werkzeug/sansio/utils.py:82`；公开输入 7 个；
- `U_hidden` = `{85, 87}`，`U_C` = `{85, 87, 90, 93, 95}`（多 3 个候选，
  但 85/87 的独立最小关系不受影响）；
- 提交 7 条，credited 7 条：参考 5/5 + 额外 2 条前置关系；
- 证据等级：EXPOSING `WITNESS_VERIFIED`；85 与 87 的 MSMS/MMBS 都是
  `FINITE_DOMAIN_EXACT`；两条 PREREQUISITE 都是 `WITNESS_VERIFIED`；
- 资源：396 次探针，64 个变体，124.43 s；unknown 0；
- 本题是五题中唯一真正 `FULL_MASKING_STORY` 且包含两个独立操作的题；
  C 把 85 和 87 都识别为独立最小集，没有错误合并。

### 4.5 `werkzeug_secure_filename_ascii_filter`（`FULL_MASKING_STORY`）

- 目标：`src/werkzeug/utils.py:222`；公开输入 8 个；
- `U_hidden` = `{227-229}`，`U_C` = `{227-229, 226, 239}`；
- 提交 4 条，credited 4 条：参考 3/3 + 额外 1 条前置关系；
- 证据等级：EXPOSING `WITNESS_VERIFIED`；MSMS/MMBS
  `FINITE_DOMAIN_EXACT`；PREREQUISITE `WITNESS_VERIFIED`；
- 资源：120 次探针，16 个变体，38.16 s；**input 级 UNKNOWN 1 条**：
  空文件名 `{"filename":""}` 是 masked，但没有满足因果活跃条件的非空
  最小充分集，C 不把它算成关系；
- 参考的 MSMS/MMBS 只要求 witness 级；C 在 2 个以上输入上验证，得到
  更强的有限域证据。

### 4.6 逐题汇总表

| 题目 | Story | 输入 | U_C | U_hidden | 提交 | credited | 匹配参考 | 额外 | W / F | 探针 | 变体 | 耗时(s) | UNKNOWN |
|---|---|---:|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| jinja2 | NO_LOCAL_EFFECT | 6 | 1 | 1 | 4 | 4 | 3/3 | 1 | 2 / 2 | 24 | 4 | 10.35 | 0 |
| bind | NO_LOCAL_EFFECT | 7 | 2 | 1 | 4 | 4 | 4/4 | 0 | 2 / 2 | 76 | 12 | 28.96 | 0 |
| filestorage | ASSERTION_GAP | 6 | 3 | 1 | 4 | 4 | 3/3 | 1 | 3 / 1 | 80 | 16 | 30.04 | 3 |
| get_host | FULL_MASKING | 7 | 5 | 2 | 7 | 7 | 5/5 | 2 | 3 / 4 | 396 | 64 | 124.43 | 0 |
| secure | FULL_MASKING | 8 | 3 | 1 | 4 | 4 | 3/3 | 1 | 2 / 2 | 120 | 16 | 38.16 | 1 |
| **合计** | — | **34** | — | **6** | **23** | **23** | **18/18** | **5** | **12 / 11** | **696** | **112** | **231.94** | **4** |

W = `WITNESS_VERIFIED`，F = `FINITE_DOMAIN_EXACT`。

### 4.7 评价项覆盖情况

| 评价项 | 本轮结果 |
|---|---|
| 正确发现的操作关系 | 23 条 credited，覆盖 18/18 参考关系 |
| 错误 masking 归因 | 0（本轮没有提交错误操作集） |
| 独立关系 | 每题都有；get_host 的 85、87 是两个独立最小集 |
| 协作关系 | 五题的参考与 C 提交的最小集都是单元素；本轮没有需要“协作集”的题 |
| 兜底关系 | 每题 1 条 `EXPOSING_COUNTEREXAMPLE`，均 `WITNESS_VERIFIED` |
| 前置关系 | 参考 1 条（bind），C 提交 5 条额外前置关系，全部被评分器确认 |
| MSMS/MMBS 正确性与最小性 | 23 条全部通过冻结评分器的最小性检查 |
| masking 条件与证据覆盖 | 12 条 witness 级、11 条有限域级；没有全域证明 |
| 暴露反例 | 5 个（每题一个） |
| 正确分类原测试为什么通过 | **接口不支持**：三基线都不输出测试级分类，submission format 也没有该 claim 类型；记为 N/A，不记 0 |
| unverified/UNKNOWN claim | claim 级 0；input 级 UNKNOWN 4 条（filestorage 3、secure 1） |
| tokens / 模型调用 | A/B `NOT_RUN` → 0 / 0；C → 0 / 0 |
| 程序执行 | C：696 次探针 + 112 个变体；B 无模型检查：116 次探针 |
| wall time | C 231.94 s；整个 run（含评分）约 234 s |

证据等级说明：

- `WITNESS_VERIFIED`：只在提交的 witness 上成立；
- `FINITE_DOMAIN_EXACT`：只在提交的有限输入列表上、且只在 C 的 `U_C`
  上枚举所有子集后成立；**不是 legal input domain 的全域结论**；
- `PROVEN`：本轮为 0，任何基线都没有形式化证明检查器。

---

## 5. 按故事线分层比较

| Story | 题 | 参考关系 | 匹配 | 额外真关系 | 证据等级分布 | 备注 |
|---|---|---:|---:|---:|---|---|
| `NO_LOCAL_EFFECT` | jinja、bind | 7 | 7 | 1 | W3 / F4 | 原测试对 A 无局部效应，但其他输入上有完整关系 |
| `ASSERTION_GAP_STORY` | filestorage | 3 | 3 | 1 | W3 / F1 | MSMS 只有 witness 级；3 条 input 级 UNKNOWN |
| `FULL_MASKING_STORY` | get_host、secure | 8 | 8 | 3 | W5 / F6 | 关系最完整，get_host 有两个独立操作 |

分层结论：

1. **故事标签不是难度标签**。两道 `NO_LOCAL_EFFECT` 题同样能被 C 完整
   恢复；它描述的是“原测试为什么没发现”，不是“关系是否可发现”。
2. **`FULL_MASKING_STORY` 的证据最扎实**：参考关系全部被匹配，且多数
   升级到 `FINITE_DOMAIN_EXACT`。
3. **`ASSERTION_GAP_STORY` 的覆盖受输入网格限制**：filestorage 的 masked
   输入里有 3 条找不到因果活跃的最小集，MSMS 只能停在 witness 级。这是
   条件/输入发现能力的缺口，不是关系不存在。
4. 本轮 n=5、且 C 的规则是在这 5 道公开题上迭代出来的（见第 7 节
   “有效性限制”），因此**不能**据此给三种方法排名，只能说明 C 在本开发
   集上可用、且没有产生错误归因。

---

## 6. 资源消耗

| 基线 | 模型调用 | Prompt/Completion tokens | 探针执行 | 变体构建 | wall time |
|---|---:|---:|---:|---:|---:|
| A Direct Qwen | 0（`NOT_RUN`） | 0 | 0 | 0 | 0 |
| B Qwen + Verifier | 0（`NOT_RUN`） | 0 | 0 | 0 | 0 |
| B 无模型检查（verifier on C） | 0 | 0 | 116 | 0 | < 1 s |
| C AST + Intervention | 0 | 0 | 696 | 112 | 231.94 s |
| 旧 Full MACE | — | — | — | — | `UNSUPPORTED_INTERFACE` |

预算使用（冻结配置）：

- 模型调用：上限 3/题、15 总计；实际 0。
- Completion tokens：上限 4096/次、12288/题；实际 0。
- 探针执行：上限 6000/题；实际最高 396（get_host），约 6.6%。
- 候选操作：上限 6；实际最高 5（get_host）。
- 输入：上限 8；实际 6–8。
- claim：上限 40/题；实际最高 7。
- 单探针超时 180 s；本轮没有超时。

评分器开销包含在整体 wall time 内：从 `config.json` 写入到
`summary.json` 落盘约 234 s，其中 C 自身记录 231.94 s。

---

## 7. 发现的算法能力缺口

先声明有效性限制：

- **A/B 没有数据**。本轮不能回答“Direct Qwen 已能解决什么”，也不能
  回答“Verifier 对模型 proposal 增加多少可靠性”。B 对 C 的 23/23 全票
  通过是**管线一致性检查**，因为 C 的 claim 与 verifier 使用同一套执行
  语义，预期就会一致，不构成独立证据。
- **C 是开发集内结果**。C 的发现规则（同一普通变量覆写、A 之后、可达
  辅助函数）是在这 5 道公开题的源码上调试出来的，HIDDEN 参考没有参与，
  但题目选择与规则设计有同源性。18/18 是开发集上限，不是留出集泛化率。
- **参考不是穷尽的**。C 找到 5 条参考之外的、被冻结评分器确认为真的
  前置关系；说明“匹配参考”只是下限。
- `FINITE_DOMAIN_EXACT` 的“exact”只对提交的有限输入和 `U_C` 成立。

### 7.1 已验证的能力

- 候选发现：对“同一变量被后续语句重新定义”这一类操作，AST + 可达性
  规则足以覆盖本开发集全部隐藏 U（`U_C ⊇ U_hidden`，5/5）。
- 关系判定：子集枚举 + 干预执行可以精确复现冻结评分器的 MSMS/MMBS
  最小性定义，包括多操作输入（get_host）。
- 条件发现：固定公开输入网格足以找出 4/5 题的前置条件；filestorage
  因网格不足只能给 witness 级。
- 证据分级：可以把 witness 级与有限域级分开报告，且不把局部结果冒充
  全域结论。

### 7.2 仍然缺失的关系

1. **非“同变量覆写”型候选**：控制流改写、别名/容器元素、跨文件调用、
   属性写入等都不在 C 的规则里。本开发集恰好都以变量覆写为主，因此
   覆盖率看起来很好；这不是一般性证据。
2. **协作关系**：C 要求最小集的每个成员在该输入上单独删除就改变观察，
   因此会漏掉“单独删除都无效、联合删除才有效”的协作集。本轮五题没有
   这种关系，所以没有暴露成错误；但机制上确实不支持。
3. **条件归纳/输入合成**：条件发现依赖固定网格。filestorage 的 3 条
   UNKNOWN 与 secure 的 1 条 UNKNOWN 都是网格没有覆盖到“有最小破除集”
   的输入。没有基于分支谓词或反例搜索的输入生成。
4. **隐藏 U 无关的最小性**：C 只能对 `U_C` 负责。若 `U_C` 漏掉隐藏 U
   中的操作，提交的“最小集”可能不最小。本轮 `U_C ⊇ U_hidden` 掩盖了
   这一点。
5. **全域证明**：没有 proof checker，`PROVEN` 始终为 0；所有结论都是
   有限点或有限域。
6. **测试级解释**：没有“原测试为什么通过”的 claim 类型。故事验证阶段
   的 `MASKED_EFFECT / NO_LOCAL_EFFECT / ASSERTION_GAP` 分类不能通过
   当前提交接口表达，因此本轮的逐题评价无法覆盖这一项。
7. **proposal 补全**：verifier 只在 proposal 命名的操作上枚举。它无法
   发现模型漏掉的操作，因此“验证通过”不能提升为“关系正确”。这是 B
   相对 A 的主要增量，也是它的主要边界。

### 7.3 是否存在值得新 MACE 机制的机会

只列机会，不宣称有效：

- **协作候选搜索**：针对“单独惰性、联合活跃”的操作集合做候选生成。
  这在机制上区别于 C 的“先按单操作活跃性过滤”。
- **谓词引导的输入合成**：从目标函数的分支条件生成能触发/阻断最小
  破除集的输入，替代固定网格；直接针对 filestorage/secure 的 UNKNOWN。
- **跨文件/别名感知的候选发现**：把“同变量覆写”扩展到属性、容器元素
  和跨文件调用边。
- **verifier 的 proposal 补全**：在公开源码上独立生成候选操作，再用
  模型 proposal 做选择，可能缓解“模型没提到就验证不到”的盲区。
- **测试级解释接口**：为“原测试为什么通过”增加一种 claim 类型，否则
  这块能力无法被 benchmark 评价。

这些都需要新的、预注册的实验来验证；本阶段不实现、不扩题、不新增
Agent 或 prompt 阶段。

---

## 8. 未来 MACE 机制研究建议

按优先级（仍是假设，不是结论）：

1. **先补真实 Qwen 基线**。A/B 的 `NOT_RUN` 是本报告最大的空白。服务
   可用后，用同一 `config.json`、同一 prompt、同一 verifier 重跑，才能
   回答“模型已能解决什么、verifier 增加什么”。
2. **把 C 从开发集规则变成可检验的通用基线**。在不动这 5 题的前提下，
   用新的公开源码题（未来发行版）测 `U_C ⊇ U_hidden` 的命中率；当前
   18/18 不能外推。
3. **优先研究条件/输入发现**。本开发集里 C 的 4 条 UNKNOWN 全部来自
   输入网格不足；这是确定性方法也能改进、且能直接转化为证据等级提升
   的方向。
4. **协作关系需要独立机制**。现有“单操作活跃性过滤”在定义上排除
   协作集；若要覆盖，必须把候选生成与活跃性判定解耦。
5. **verifier 的补全策略值得单独评估**。在不引入隐藏数据的前提下，
   用公开源码生成候选全集，再与模型 proposal 求交/求差，观察纯验证
   能多恢复多少、误报多少。
6. **评测口径保持分层**。继续把 witness 级、有限域级、全域证明分开
   计数；不要把同一题的多条输入算成多个任务，也不要把部分正确关系
   写成全域发现。

---

## 附：复现命令

```bash
python -m benchmark_v3_baselines.run_pilot
python scripts/v3_reference_match.py --run runs/v3_baseline_pilot \
    --out runs/v3_baseline_pilot/reference_match.json
python scripts/v3_no_model_checks.py --run runs/v3_baseline_pilot
python -m pytest tests/test_v3_baselines.py
```

`run_pilot` 在服务不可用时写 `NOT_RUN`，不会回退到 fake client；
只有显式 `--dry-run` 才会使用 `fixtures/dry_run/` 并标 `DRY_RUN`。

测试：`python -m pytest` 全量 262 项通过（0 failed / 0 error），其中
基线适配器单测 13 项。
