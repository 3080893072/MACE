# MACE 算法可行性：差异引导候选发现的最小实验（Phase 3–5）

日期：2026-11-03  
范围：五个冻结开发题（jinja2 / werkzeug ×4）  
约束：无 GPU、无新模型调用、不扩大正式测试集、不修改 Full MACE 或历史记录。

## 0. 结论（先给判断）

**NO-GO：不建议把 Difference-Guided Masking Candidate Discovery 作为新的 MACE 算法组件做完整实现。**

理由不是“没有提升”，而是**提升可归因于常规工程，而不是差异引导语义**：

- 原 AST：15 个唯一 credited relations，6 条 `UNVERIFIED`（独立审计后为语义 FALSE）。
- 差异引导 B：17 个唯一 credited relations，0 条 `UNVERIFIED`/FALSE。
- 但一个不跟踪值、只做“动态下游 + P+∪P− 执行候选”的工程对照 `downstream_trace`
  同样得到 17/17，且**提交的操作与 B 逐条相同**。
- B 相对 `downstream_trace` 的额外“值收敛/吸收”判断，新增 credited relation = 0，
  只少建 8 个变体、少约 7 秒。

因此：**有效的修复是候选过滤 + 执行器优化；不是差异传播机制。**  
可以 GO 的是一个小型工程补丁（见 §6），不是新算法。

## 1. Phase 3 实现的方法

代码：

- `benchmark_baseline/diff_trace.py`：高效值感知 tracer。只匹配目标文件，记录目标变量的
  `bound/type/repr/hash`；每个 code object 只做一次路径匹配。
- `benchmark_baseline/diff_guided.py`：三种可切换方法：
  - `downstream_only`：静态源码行号 > A 的同名赋值；不看 trace。
  - `downstream_trace`：动态下游（P+ 中晚于 A，或 P− 同函数回退路径且行号 > A），
    且候选在 P+ 或 P− 执行。
  - `diff_guided`：在 `downstream_trace` 基础上，要求候选“差异承载”：
    - 只在 P− 回退路径执行（control divergence），或
    - P+/P− 两侧都执行，但操作前目标值不同、操作后收敛（overwrite/absorb）。
- 验证：每个候选单独做 `keep_only` / `delete_c` 两个干预，只有
  `base masked ∧ keep_only masked ∧ delete_c exposed` 才提交单操作 MSMS/MMBS。
- **不枚举候选子集**；不读取隐藏参考来提候选；无模型调用。

`diff_guided` 在五个题上选出的候选：

| 任务 | 过滤后候选 | 提交 | 证据 |
| --- | --- | --- | --- |
| jinja2 | 137 | 137 | 只在 P− 执行；119 在 P+ 早于 A，被 downstream 排除 |
| bind | 219 | 219 | 源码行 219 < A(307)，但 P+ 动态执行晚于 A；值收敛 |
| filestorage | 2921, 2924 | 2924 | 2921 P+ 独有但验证失败；2924 收敛 |
| get_host | 85 / 87 | 85, 87 | 85 与 87 在不同输入上收敛 |
| secure | 227 | 227 | 227–229 块收敛 |

## 2. Phase 4 公平对照

同一公开输入池、同一探针、同一 `build_variant` 干预、同一评分器；均 0 模型调用；
均不读隐藏参考提候选。未重跑原 AST，直接使用冻结分数。

### 2.1 主表

| 方法 | claims | WITNESS_VERIFIED | UNVERIFIED/FALSE | 唯一 credited | 变体构建 | wall (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A. AST original（冻结） | 36 | 30 | 6 | 15 | 50 | 1531.1（jinja resumed） |
| B. diff_guided | 36 | 36 | 0 | **17** | 24 | **64.2** |
| 对照：downstream_only | 30 | 30 | 0 | 15 | 60 | 100.9 |
| 对照：downstream_trace | 36 | 36 | 0 | **17** | 32 | 71.2 |

满分 = 17 个参考唯一关系（jinja 3 + bind 3 + filestorage 3 + get_host 5 + secure 3）。
B = 17/17；AST = 15/17。

### 2.2 逐题

| 任务 | AST credited | AST unverified | B credited | B 提交 | 变化 |
| --- | ---: | ---: | ---: | --- | --- |
| jinja2_bytecode_cache_read | 1 | 6 | 3 | 137 | **+2**（119→137） |
| werkzeug_bind_server_name_lower | 3 | 0 | 3 | 219 | 0 |
| werkzeug_filestorage_stream_name | 3 | 0 | 3 | 2924 | 0 |
| werkzeug_get_host_default_empty | 5 | 0 | 5 | 85, 87 | 0 |
| werkzeug_secure_filename_ascii_filter | 3 | 0 | 3 | 227–229 | 0 |

B 的 36 条 claims 全部 `WITNESS_VERIFIED`；重复关系仍只计一次 credit，
所以 17 是唯一关系数，不是 claim 数。

### 2.3 归因（必须分开）

| 变化 | 证据 | 归因 |
| --- | --- | --- |
| AST → B：+2 credited | jinja 137 取代 119 | **候选集扩张/过滤**：把只在 P− 执行的 137 纳入；把 A 之前的 119 排除 |
| downstream_only → downstream_trace：+2 | bind 从 1 回到 3 | **动态下游顺序**：219 源码在 A 前但运行在 A 后；静态行号过滤会漏 |
| downstream_trace → diff_guided：0 | 提交操作逐条相同 | **值收敛/吸收判断没有带来新关系**；只减少 8 个变体 |
| AST → downstream_trace：wall 1531 → 71 | 相同 17 credits（B/对照） | **执行优化**：高效 tracer（0.27 s vs 18.6 s/次）+ 不再枚举子集；不是语义发现 |
| any → scorer | 评分器未改，隐藏参考只用于评分 | **无评分器修复** |

## 3. 成本与搜索

- B 相对 AST：变体构建 50 → 24（−52%），wall 1531.1 → 64.2（约 23.8×）。
- 但 `downstream_trace` 已经用 32 个构建、71.2 秒拿到同样的 17 credits。
  B 的额外收益只有 24 vs 32 构建、64.2 vs 71.2 秒，**没有新增正确关系**。
- AST 的 1531 秒主因不是子集枚举，而是 `trace_lines.py` 的每行 `realpath`；
  这是工程开销。把它记为“搜索成本降低”会误导。
- B 不枚举子集，因此**不能发现多操作协同掩盖**。原 AST 在候选 ≤5 时能枚举组合。
  B 的“省成本”部分来自放弃组合搜索，不是免费收益。

## 4. GO/NO-GO 逐项回答

### Q1 原 AST 的真实能力边界？

- 能做：同文件、同裸变量名的赋值；P+ 行执行过滤；小候选集的子集枚举；执行干预验证。
- 不能做：P− 独有路径（jinja 137）；跨函数动态顺序（bind 219 靠巧合而非理解）；
  属性/下标状态（`self.x`、`obj[i]`）；循环携带状态；异常路径；分支前置条件。
- 五个开发题：4/5 题正确，15/17 唯一关系；jinja2 的 6 条 U-out 是语义错误，
  不是“评分器不会验证”。

### Q2 差异引导机制是否解决了真实失败？

- 它确实在 B 中选出了 137，修好了 jinja2。
- 但 `downstream_trace` 不跟踪值也选出了 137；所以**不是差异引导机制解决的**，
  而是“候选执行集合纳入 P− 回退路径”解决的。
- bind 的动态顺序也不是值跟踪解决的，而是 trace 的执行顺序解决的。

### Q3 是否发现了 AST 漏掉的关系？

- 是，137（MSMS + MMBS）。
- 但同一关系由 `downstream_trace` 同样发现；没有证据表明它只能由差异引导发现。

### Q4 是否降低了搜索成本？

- 是，B 比 AST 少 52% 变体、约 24× wall。
- 但大部分来自高效 tracer 和单候选验证；`downstream_trace` 已拿到同样分数。
- 且单候选验证牺牲了多操作组合覆盖。因此不能把成本下降归因于差异引导。

### Q5 提升是否来自新机制而非常规工程？

**否。** 关键证据：

- `diff_guided` 与 `downstream_trace` 的 claims 操作逐条相同（137、219、2924、85/87、227）。
- 值收敛判断没有新增任何 credited relation；它只把验证本就会拒绝的候选（如 231、2921）
  提前剪掉。
- 真正修好 jinja2 的是 P− 候选纳入；真正修好 bind 的是动态执行顺序；两者都是常规工程。

### Q6 是否建议集成进 MACE？

- **不建议集成 Difference-Guided Masking Candidate Discovery 作为新算法组件。**
- 建议把以下常规修复作为 baseline 补丁评估（不修改 Full MACE，仅建议）：
  1. 候选执行集合取 **P+ ∪ P−**；
  2. “下游”按**动态执行顺序**判断，不按静态行号；
  3. tracer 用 code-object 缓存匹配，去掉每行 `realpath`；
  4. 单候选验证优先；若同题有多个候选通过，再回退到小规模组合搜索，避免丢失多操作掩盖。
- 这些修复在五个开发题上可复现地把 15/17 提升到 17/17；但这是工程修复，
  不是新机制。

### 是否建议做完整实现？

**否。** 没有观察到“可复现的、可归因于差异引导机制”的有效提升。  
只有“可复现的、可归因于候选过滤/执行优化”的提升。

## 5. 失败与成功原因（逐题）

| 任务 | B 结果 | 原因 |
| --- | --- | --- |
| jinja2 | 成功 3/3 | P− 唯一回退 137 被纳入；A 前初始化 119 被动态下游排除 |
| bind | 成功 3/3 | 219 在 P+ 中晚于 A（跨函数动态顺序）；静态行号会漏 |
| filestorage | 成功 3/3 | 2924 在两侧执行且值收敛；2921 P+ 独有但干预不暴露，验证淘汰 |
| get_host | 成功 5/5 | 85/87 分别在对应输入上值收敛；90/93/95 干预不暴露，淘汰 |
| secure | 成功 3/3 | 227–229 块在两侧执行且值收敛；226 等干预不暴露，淘汰 |

B 没有失败题；`downstream_only` 在 bind 失败（只有 2 条 exposing，无 MSMS/MMBS，
universe 只含 311/313，均未通过验证），这是静态行号过滤的直接反例。

## 6. 限制

1. 只有五个开发题，**不是独立泛化评估**；不能外推到正式测试集。
2. 只有一个真实失败案例（jinja2 137）。结论强度有限，不能据此宣布广泛算法规律。
3. B 只跟踪一个局部变量；属性、下标、跨文件状态、循环/异常状态未实现。
4. B 只做单候选验证，不能发现多操作协同掩盖；原 AST 的子集枚举在候选 ≤5 时更完整。
5. AST 的 1531 秒含 `resumed=true` 的 jinja2；跨方法 wall 对比受机器负载影响，
   但变体数、claim 状态、credited relation 是确定性的。
6. 隐藏参考只在独立分类完成后用于评分对照；候选提出过程未读取。

## 7. 复现

```bash
# Phase 1 独立干预
python -m benchmark_baseline.audit_jinja_interventions

# Phase 3/4 三种方法
python -m benchmark_baseline.diff_guided --method downstream_only
python -m benchmark_baseline.diff_guided --method downstream_trace
python -m benchmark_baseline.diff_guided --method diff_guided

# 计时 + 评分
python -m benchmark_baseline.time_diff_guided
```

机器可读对照：`benchmark_baseline/runs/diff_guided/comparison.json`  
计时：`benchmark_baseline/runs/diff_guided/timing.json`  
原始结果与评分：`benchmark_baseline/runs/diff_guided/<method>/<task>.json` 与
`<task>.score.json`。

## 8. 最终建议

- **NO-GO（新机制）**：不把差异引导候选发现作为新 MACE 算法做完整实现。
- **GO（工程补丁，待批准）**：只做候选过滤（P+∪P−、动态下游）与 tracer 性能修复；
  保留组合搜索回退以覆盖多操作掩盖。
- 若未来要继续验证“差异引导”本身，需要新的开发题，且必须包含：
  多操作协同、跨函数/属性状态、循环/异常路径，以及“简单过滤不够、值传播才够”的
  可区分案例；当前五个开发题无法把 B 与 `downstream_trace` 区分开。
