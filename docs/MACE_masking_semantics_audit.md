# MACE 操作掩盖关系语义审计（2026-11-02）

## 0. 审计边界与结论

本轮只做语义审计，不增加功能，不调用 Qwen，不创建新题，不修改 M1–M6 历史结果，也不覆盖任何旧日志或旧标签。审计对象是：

- `open_ops/discover.py`
- `benchmark_pilot/verifier_v2.py`
- `scripts/check_open_interface.py`
- `tests/test_open_ops_discovery.py`
- `tests/test_open_ops_contracts.py`

审计执行只读脚本 `d:/tmp/audit_masking_semantics.py`，输出 `open_ops/out/semantics_audit.json`。该脚本不修改发现器、任务、合同或历史输出。相关测试本轮运行 29 条，全部通过；这说明下文记录的是现有实现的真实行为，而不是一次代码崩溃。

### 0.1 结论摘要

1. **当前三个关系名并不是两套集合定义中的任何一套的纯粹名称。**
   - `independent` 是“单元素充分 + 破除 + 控制前置豁免”的混合关系，不是完整的 independent MSMS，也不是纯粹的 MMBS。
   - `cooperative` 是 MSMS 意义上的“最小充分集合”，同时要求“禁用整组会暴露”，但不要求它是 MMBS。`ctrl_02` 的 MMBS 是 `{L4}`、`{L6}`，不是 `{L4,L6}`。
   - `coexisting` 在 `open_ops` 中是 MMBS 型关系；在 `verifier_v2` 中又额外要求“该集合单独启用也能掩盖”，因此比 MMBS 更强；在 `check_open_interface.verify_relation` 中则只要求 MMBS。三处定义不一致。

2. **条件合成是单边的。**
   - 对 `independent/cooperative`，条件只拟合 `Only(S)`（关闭其他候选、仅保留 S 时是否掩盖），不拟合 `Break(S)`，也不拟合最小性。
   - 对 `coexisting`，条件只拟合 `Break(S)`（禁用 S 时是否暴露），不拟合 `Only(S)`，也不拟合 proper-subset 最小性。
   - 因此 `condition_status=EXACT` 只表示“对合成时使用的那半边标签精确”，不表示完整关系在条件上精确。`ctrl_03` 的 `independent [L4]`、`cooperative [L8,L10]`、`coexisting [L4,L6]` 都能在有限案例上得到 `VERIFIED`，但完整关系在条件上存在大量假接受。

3. **`ctrl_02` 与 `ctrl_03` 给出了 MSMS 与 MMBS 不可互换的直接反例。**
   - `ctrl_02`：MSMS=`{L4,L6}`；MMBS=`{L4}`、`{L6}`。
   - `ctrl_03`，`p=q=0`：MSMS=`{L4}`、`{L6}`；MMBS=`{L4,L6}`。
   - 因而“两个操作一起才掩盖”与“两个操作必须一起禁用才暴露”不是同一句话；当前 `cooperative` 把前者和“整组禁用会暴露”绑在一起，容易被读成后者。

4. **C→B 反例不是单纯的“候选范围限定”，也不是单纯的关系定义错误，而是两者叠加。**
   - 全候选域 `U={C,B}` 下：MSMS=`{C,B}`，MMBS=`{B}`。
   - 当前 `discover_expanded()` 把 C 识别为 B 的控制前置，在 `Only({B})` 中保留 C，于是得到 `independent [B]`。这在**干预层面**是有意的前置豁免，但在**命名和状态层面**是定义错误：它不是全程序 independent，而是一个“带前置条件的单元素破除集”。
   - 若 C 在 A 之前，候选发现器根本看不到 C，结果仍返回 `OK`、`VERIFIED`，连前置豁免的证据都没有。这是候选完整性问题，不是可接受的范围限定。

5. **当前确定性原型不能作为“完整归因”或“精确 Guard”的可信基线。**
   - 它可以继续作为**声明候选域内的 witness 级、可执行回归工具**。
   - 要恢复为可信基线，必须先修语义与范围元数据；在这些修正完成前，不应把 `VERIFIED` 解读为全程序完整归因。

---

## 1. 形式定义：充分掩盖与破除掩盖

### 1.1 观测与干预

固定一个程序对 `(P+, P−)`：`P+` 是原程序，`P−` 是把目标操作 A 删除后的程序。固定一个候选操作全集 `U`。`U` 是“本次声明考虑的候选”，不是自动等于整个程序中的所有相关写操作；这一点后面单独审计。

对 `D ⊆ U`，记 `Disable(D)` 为把 `D` 中每个候选操作替换为 `pass`（或等价的无效语句）后的程序对。对输入 `a`，记：

```text
O+(D, a) = P+ 在 Disable(D) 下的观测
O−(D, a) = P− 在 Disable(D) 下的观测
```

“观测”可以是返回值，也可以是异常类型/消息。当前实现区分：

- **可执行**：两侧都返回或都抛出；异常本身是观测。
- **严格掩盖 `Masked_strict(D,a)`**：`P+` 必须正常返回，且 `O+ = O−`。两个相同的崩溃不算“掩盖”，这是当前 `masked_strict` 的规则。
- **弱掩盖 `Masked_weak(D,a)`**：两侧都可执行且观测相等。它允许 `P+` 抛出，只在“proper subset 是否暴露”的内部检查中使用。
- **暴露 `Exposed(D,a)`**：两侧都可执行且观测不相等。`P+` 返回、`P−` 抛出可以算暴露；`P+` 抛出、`P−` 返回也可以算暴露。

### 1.2 两个干预

```text
Only(S, a)  = Masked_strict(U \ S, a)      # 只保留 S 启用，关闭其他候选
Break(S, a) = Exposed(S, a)                # 关闭 S，其他候选保持启用
```

`Only` 与 `Break` 不是对称操作：

- `Only(S)` 问的是“S 是否足够掩盖”。
- `Break(S)` 问的是“S 是否对掩盖是必要的，关闭它就暴露”。
- `Only(S)` 关闭的是 `U \ S`，因此会把 S 之外的控制前置一起关掉；如果这些前置定义了 S 所依赖的分支条件，`Only(S)` 可能直接变成非法执行。这正是 C→B 反例的根源。
- `Break(S)` 只关闭 S，不会关闭 S 之外的控制前置，所以它没有同样的执行前提问题。

### 1.3 Minimal Sufficient Masking Set（MSMS）

在候选全集 `U` 和输入 `a` 上：

```text
MSMS_U(a) = {
    S ⊆ U, S ≠ ∅ :
        Only(S, a)
        且不存在非空真子集 T ⊂ S 使 Only(T, a)
}
```

它是“最小充分掩盖集合”：S 一起存在足以掩盖 A，且去掉 S 中任何一个非空子集都不足以掩盖。这里的“最小”是包含意义下的极小，不是基数最小；可能有多个大小不同的极小集合。

### 1.4 Minimal Mask-Breaking Set（MMBS）

```text
MMBS_U(a) = {
    S ⊆ U, S ≠ ∅ :
        Break(S, a)
        且不存在真子集 T ⊂ S（包括 T=∅）使 Break(T, a)
}
```

它是“最小破除集合”：关闭 S 会暴露 A，且关闭任何更小的子集都不会暴露。若原程序在 `a` 上本来就没有掩盖 A，则 `Break(∅,a)` 已经成立，空集是 S 的真子集，因此不存在非空 MMBS；所以 MMBS 只在“原程序确实掩盖 A”的输入上才有意义。

### 1.5 两个集合为什么不能混用

| 现象 | MSMS | MMBS |
|---|---|---|
| 单条独立掩盖 | 单元素集合 | 同一个单元素集合 |
| 多条路径各自都能掩盖 | 每个单元素都是 MSMS | 需要同时关闭所有路径，通常是较大的集合 |
| 多条路径必须合起来才掩盖 | 较大的集合 | 每个单元素都可能单独破除 |
| “必须共同存在” | 是，指充分性 | 不是；MMBS 问的是破除 |
| “必须共同关闭” | 不是 | 是，指破除性 |

`ctrl_02` 和 `ctrl_03` 的矩阵在本文第 3 节给出，直接证明两种集合可以互为“反向”：

- `ctrl_02`：MSMS 是二元组，MMBS 是两个一元组。
- `ctrl_03` 的 `p=q=0`：MSMS 是两个一元组，MMBS 是一个二元组。

### 1.6 控制前置豁免

如果 `C` 定义了 `B` 所读取的分支条件，那么：

```text
Only({B}) = Masked_strict(U \ {B})
```

会把 C 也关闭，可能使 `B` 无法执行。代码因此引入：

```text
Only_P(S) = Masked_strict(U \ (S ∪ P))
其中 P 是由 control_reads 闭包得到的控制前置集合。
```

这不是 `MSMS_U` 的定义，而是 `MSMS` 的一个**前置条件化变体**。必须单独命名，例如：

```text
MSMS_U^P(a) = 在保留 P 的干预下，S 是最小充分集合
```

相应地，`Only_P({B}) ∧ Break({B})` 也不等于 `independent_U({B})`。它表示“B 在 P 保持启用时是充分且破除的单元素集合”，而不是“B 单独就能掩盖 A”。

### 1.7 关系条件的正确语义

一个关系应写成：

```text
condition g(a)  ⇒  Rel_U(S, a)
```

其中 `Rel_U` 是该关系的完整定义，而不是只取一半。若还声称 `g` 是精确 Guard，则需要：

```text
g(a)  ⇔  Rel_U(S, a)   对所有声明合法输入 a
```

“有限案例上精确”只说明在样本集上 `g` 与标签一致；它不自动等于完整合法域精确，也不自动等于完整关系精确。当前实现把这两件事混在了一起。

---

## 2. 当前代码的正式定义与混淆

### 2.1 `open_ops/discover.py`

核心公式见 `open_ops/discover.py:1053-1084`：

```text
prereqs = control_prerequisites(S)
only    = only_masked(S, prereqs)          # Only_P(S)
exposes = disabled_exposes(S)              # Break(S)

independent:
    |S| = 1
    only ∧ exposes

cooperative:
    |S| ≥ 2
    only ∧ exposes
    ∧ 所有非空真子集 T 都不满足 Only_P(T)

coexisting:
    |S| ≥ 2
    exposes
    ∧ 所有非空真子集 T 都满足 Masked_weak(T)
```

因此：

- `independent` 是 `Only_P` + `Break` 的**双重单元素关系**，不是纯 MSMS，也不是纯 MMBS。
- `cooperative` 的充分性最小化使用 `Only_P`；它同时要求 `Break(S)`，但**没有要求** S 是 MMBS。它的 proper-subset 检查是“更小的集合不充分”，不是“更小的禁用集合不破除”。
- `coexisting` 只要求 `Break(S)` 和“所有非空真子集都不破除”，这是 MMBS 型；它不要求 S 自己充分，也不要求 `Only(S)`。但它的 proper-subset 判定用的是 `Masked_weak`，不是 `Masked_strict`。

条件合成见 `open_ops/discover.py:1091-1096`：

```text
if kind in ("independent", "cooperative"):
    labels = {cid: only[cid]}       # 只拟合充分半边
else:
    labels = {cid: exposes[cid]}    # 只拟合破除半边
```

因此 `condition_check["exact"]` 是“半边标签的样本内精确”，不是完整关系的精确。

### 2.2 `benchmark_pilot/verifier_v2.py`

`verify_relation()` 见 `benchmark_pilot/verifier_v2.py:391-478`。它对三类关系统一计算：

```text
only_key     = all_ops - claim     # 只保留 claim
disabled_key = claim               # 禁用 claim
only_status  = _mini(matrix, only_key)
disabled_status = _mini(matrix, disabled_key)
```

然后：

```text
independent:
    |claim| = 1
    only_claim_masks ∧ claim_disabled_exposes

cooperative:
    |claim| ≥ 2
    only_claim_masks ∧ claim_disabled_exposes
    ∧ 每个 proper subset 单独启用时不 MASKED

coexisting:
    |claim| ≥ 2
    only_claim_masks ∧ claim_disabled_exposes
    ∧ 每个 proper subset 单独禁用时 MASKED
```

关键点：

- `verifier_v2` 的 `only_key` **没有**控制前置豁免。若矩阵包含 C，`independent [B]` 会因为关闭 C 而变成 `INVALID_INPUT`，不会被接受。
- 但 `open_ops/run_development.py:_independent_verifier()` 只把“关系里出现的行”传给 `run_matrix()`，不传所有候选。于是 `verifier_v2` 的 `all_ops` 只有 B，C 根本不在矩阵里；`all_verified=True` 只证明“相对于关系自己声明的操作集合成立”，不能证明候选全集内的独立验证。这是候选完整性缺口，不是 `verifier_v2` 的公式错误。
- `coexisting` 在 `verifier_v2` 中要求 `only_claim_masks`，而 `open_ops` 的 `coexisting` 不要求。因此同一个 `coexisting` 名称在两个文件里不是同一个关系。

### 2.3 `scripts/check_open_interface.py`

提示词中的定义见 `scripts/check_open_interface.py:119-130`：

- `independent`：一个操作单独使 P+/P− 观测相等；
- `cooperative`：两个或更多一起使其相等，且没有 proper non-empty subset 使其相等；
- `coexisting`：两个或更多必须一起禁用才使其不同，且没有 proper subset 如此。

但条件评分函数 `actual_relation_holds()` 见 `scripts/check_open_interface.py:238-243`：

```text
independent/cooperative:  return only_equal(ops)
coexisting:               return not disabled_equal(ops)
```

它只取半边，不检查另一侧，也不检查最小性。`verify_relation()` 本身又检查双侧和最小性（`scripts/check_open_interface.py:299-328`）。于是同一文件里条件评分和关系验证使用的“实际关系”不是一个东西。

`verify_relation()` 的 `coexisting` 分支只要求：

```text
Break(S) ∧ 所有 proper subset 都不 Break
```

这与 `open_ops` 的 MMBS 型定义接近，但 `verifier_v2` 的 `coexisting` 还要额外要求 `Only(S)`。三处定义汇总如下。

### 2.4 三种实现的定义对照

| 关系 | `discover_expanded` | `benchmark_pilot/verifier_v2.py` | `check_open_interface.verify_relation` | 条件评分使用的半边 |
|---|---|---|---|---|
| `independent` | `Only_P(S) ∧ Break(S)`，S 为单元素 | `Only_U(S) ∧ Break(S)`，S 为单元素 | 同左 | `Only` |
| `cooperative` | `Only_P(S) ∧ Break(S) ∧ 所有 proper nonempty T 不 Only_P(T)` | `Only_U(S) ∧ Break(S) ∧ 所有 proper nonempty T 不 Only_U(T)` | 同左 | `Only` |
| `coexisting` | `Break(S) ∧ 所有 proper nonempty T Masked_weak(T)` | `Only_U(S) ∧ Break(S) ∧ 所有 proper nonempty T Masked_weak(T)` | `Break(S) ∧ 所有 proper nonempty T Masked_weak(T)` | `Break` |

若只问“这个标签属于充分掩盖还是破除掩盖”，应这样归类：

- `independent`：同时声称充分和破除，但充分性被 `Only_P` 前置豁免改写，因此不能归入单一集合；它是混合关系。
- `cooperative`：正式内容属于 **MSMS（充分掩盖）**；它额外的 `Break(S)` 只是“整组禁用会暴露”，不是 MMBS，因为不要求破除性极小。
- `coexisting`：`open_ops` 中正式内容属于 **MMBS（破除掩盖）**；`verifier_v2` 又额外要求充分性，所以是“MMBS + 充分”，不能直接称为纯 MMBS。

进一步结论：

- **`independent` 是混合关系，不是 MSMS 或 MMBS 的正式名称。** 当前最接近的描述是“带前置豁免的单元素充分且破除集合”。
- **`cooperative` 是 MSMS 加一个非最小的破除条件。** 把它读成“必须共同关闭”会错；`ctrl_02` 已经证明。
- **`coexisting` 在 `open_ops` 中是 MMBS 型，在 `verifier_v2` 中是“MMBS + 充分性”，在接口验证中是纯 MMBS。** 这是明确的三处不一致。

### 2.5 “充分”与“破除”的拆分表

| 标签 | 充分掩盖 | 破除掩盖 | 最小性类型 |
|---|---|---|---|
| `independent` | `Only_P(S)`，单元素 | 要求 `Break(S)` | 无（单元素） |
| `cooperative` | 要求 `Only_P(S)` | 要求 `Break(S)`，但不最小 | 充分性极小 |
| `coexisting`（`open_ops`） | 不要求 | 要求 `Break(S)` | 破除性极小 |
| `coexisting`（`verifier_v2`） | 要求 `Only_U(S)` | 要求 `Break(S)` | 破除性极小；不检查充分性极小 |
| `coexisting`（接口 verify） | 不要求 | 要求 `Break(S)` | 破除性极小 |

因此，**当前没有一个关系名同时等于 MSMS 或 MMBS 的正式定义**。`ctrl_01` 之所以看起来完全正确，是因为它的 MSMS 和 MMBS 恰好是同一个单元素集合；它不能证明其余关系名也正确。

---

## 3. 控制题的真值矩阵与两种最小集合

### 3.1 矩阵记号

- `S`：声明的候选集合。
- `Only(S)`：关闭 `U \ S`，只保留 S。
- `Disable(S)`：关闭 S，其他候选保持启用。
- `MASKED` / `EXPOSED` / `INVALID`：
  - `MASKED`：P+ 正常返回且 P+、P− 观测相等；
  - `EXPOSED`：两侧可执行但观测不同；
  - `INVALID`：P+ 未正常返回（例如控制变量未定义），不能作为“掩盖”证据。
- `∅` 行是原程序基线。
- 行标签 `L4` 表示源码第 4 行；完整 key 与操作文本的对应见 3.2。

所有矩阵均由执行得到，不依赖私有 attribution。矩阵按输入等价类合并：同一组内所有输入在全部子集上结果一致。

### 3.2 候选全集与行号

| 任务 | 候选全集 U | 操作 |
|---|---|---|
| `ctrl_01` | `{L4}` | `if mode == 0: v = x` |
| `ctrl_02` | `{L4, L6}` | `if c == 0: v = v // 6 * 6`；`if d == 0: v = v // 7 * 7` |
| `ctrl_03` | `{L4, L6, L8, L10}` | `if p == 0: v = x`；`if q == 0: v = x`；`if d == 0: v = v // 3 * 3`；`if c == 0: v = v // 7 * 7` |
| `control_state` | `{L4, L5}` | `flag = c == 0`；`if flag: v = x` |

### 3.3 最小集合汇总

| 任务 / 输入区域 | MSMS | MMBS |
|---|---|---|
| `ctrl_01`, `mode=0` | `{L4}` | `{L4}` |
| `ctrl_01`, `mode=1` | 无 | 无 |
| `ctrl_02`, `c=0,d=0,x∈{1..5}` | `{L4,L6}` | `{L4}`、`{L6}` |
| `ctrl_02`, 其余输入 | 无 | 无 |
| `ctrl_03`, `p=0,q=1` | `{L4}` | `{L4}` |
| `ctrl_03`, `p=1,q=0` | `{L6}` | `{L6}` |
| `ctrl_03`, `p=0,q=0` | `{L4}`、`{L6}` | `{L4,L6}` |
| `ctrl_03`, `p=q=1,c=d=0,x∈{3,4}` | `{L8,L10}` | `{L8}`、`{L10}` |
| `ctrl_03`, 其余输入 | 无 | 无 |
| `control_state`, `c=0` | `{L4,L5}` | `{L5}` |
| `control_state`, `c=1` | 无 | 无 |

这张表就是“两种集合不能混为一谈”的核心证据。特别是：

- `ctrl_02` 的 `cooperative [L4,L6]` 是 MSMS，不是 MMBS；关闭 L4 或关闭 L6 任一个都足以暴露 A。
- `ctrl_03` 的 `coexisting [L4,L6]` 是 MMBS，但不是极小充分集合；在 `p=q=0` 时 `{L4}` 和 `{L6}` 各自都能充分掩盖。
- `control_state` 的 `independent [L5]` 只是在保留 L4 的干预下成立；全候选域下 `{L5}` 既不是 MSMS 也不是完整 `Only` 下的独立关系。

### 3.4 `ctrl_01`：MSMS 与 MMBS 恰好重合

`mode=0`：

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | MASKED | EXPOSED |

`mode=1`：

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | EXPOSED |
| {L4} | EXPOSED | EXPOSED |

因此在 `mode=0` 上 MSMS=`{L4}`、MMBS=`{L4}`；`mode=1` 上两者都为空。当前 `independent [L4]` 的条件 `(mode < 1)` 对完整关系在供给案例和完整合法域上都没有假接受，是四道题中唯一完全干净的案例。

### 3.5 `ctrl_02`：MSMS 二元、MMBS 两个一元

`c=0,d=0,x∈{1..5}`：

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | EXPOSED | EXPOSED |
| {L6} | EXPOSED | EXPOSED |
| {L4,L6} | MASKED | EXPOSED |

`c=0,d=1` 或 `c=1`（共 19 个供给案例）：

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | EXPOSED |
| {L4} | EXPOSED | EXPOSED |
| {L6} | EXPOSED | EXPOSED |
| {L4,L6} | EXPOSED | EXPOSED |

所以：

- `Only({L4,L6})` 成立，且 `Only({L4})`、`Only({L6})` 都不成立 → MSMS=`{L4,L6}`。
- `Break({L4})` 与 `Break({L6})` 都成立，且更小的空集不成立 → MMBS=`{L4}`、`{L6}`。
- 当前 `cooperative [L4,L6]` 作为“最小充分集合”是对的；作为“必须一起禁用”是错的。当前关系同时要求 `Break({L4,L6})`，而该条件在 `c=0,d=0` 下也为真，所以它仍能通过，但这不改变它不是 MMBS 的事实。

### 3.6 `ctrl_03`：三种输入区域把两种集合彻底分开

**`p=0,q=1`（4 个输入）**

MSMS=`{L4}`，MMBS=`{L4}`。`L4` 单独充分且单独破除。

**`p=1,q=0`（4 个输入）**

MSMS=`{L6}`，MMBS=`{L6}`。

**`p=0,q=0`（4 个输入）**

MSMS=`{L4}`、`{L6}`；MMBS=`{L4,L6}`。因为两条路径各自都能充分掩盖，但关闭任意一条时另一条仍然掩盖，只有同时关闭才暴露。

**`p=q=1,c=d=0,x∈{3,4}`（2 个输入）**

MSMS=`{L8,L10}`；MMBS=`{L8}`、`{L10}`。两条取整操作必须一起才能把 A 的效果抹平；但关闭任意一条就足以暴露。

**其余 `p=q=1` 输入（6 个输入）**

MSMS 与 MMBS 都为空。

这些区域说明：

- `independent [L4]` 的 `p<1` 条件在 `p=0,q=1` 上是 MSMS/MMBS，但在 `p=0,q=0` 上只是 MSMS，不是 MMBS。
- `cooperative [L8,L10]` 在 `c=d=0,x∈{3,4}` 上是 MSMS，不是 MMBS。
- `coexisting [L4,L6]` 在 `p=q=0` 上是 MMBS，但不是极小充分集合。

完整逐子集矩阵见附录 A。

### 3.7 `control_state`：C 定义 B 的条件

`c=0`：

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | EXPOSED | INVALID |
| {L5} | INVALID | EXPOSED |
| {L4,L5} | MASKED | EXPOSED |

`c=1`：

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | EXPOSED |
| {L4} | EXPOSED | INVALID |
| {L5} | INVALID | EXPOSED |
| {L4,L5} | EXPOSED | EXPOSED |

`c=0` 时：

- `Only({L4,L5})` 成立，`Only({L4})`、`Only({L5})` 都不成立 → MSMS=`{L4,L5}`。
- `Break({L5})` 成立，空集不成立；`Break({L4})` 是 `INVALID`，不是暴露 → MMBS=`{L5}`。

`{L5}` 的 `Only` 是 `INVALID`：关闭 L4 后 `flag` 未定义。当前 `discover_expanded()` 通过 `control_prerequisites` 把 L4 保留下来，于是 `Only_P({L5})` 变成基线（不关闭任何东西），得到 `MASKED`。这不是 `Only({L5})`，而是 `Only_P({L5})`。

---

## 4. 条件审计：`VERIFIED` 目前只保证半边

### 4.1 审计方法

对每个关系的条件 `g(a)`，在两类输入上计算：

- 供给案例：`input_domain.cases`，也就是 `condition_check.exact` 实际看到的有限集；
- 完整合法域：由 `input_domain.args[*].legal_values` 笛卡尔积生成。`control_state` 没有 `legal_values`，退回使用供给案例。

对每个关系检查五个谓词：

- `only`：`Only(S)`；
- `expose`：`Break(S)`；
- `msms`：S 是 MSMS；
- `mmbs`：S 是 MMBS；
- `full`：当前该 `kind` 的完整关系（按第 2 节的公式）。

表中 `FA/FR` 分别表示 `g` 的假接受/假拒绝：`FA` 是条件为真但谓词为假，`FR` 是条件为假但谓词为真。对 Guard 而言，`FA` 是不健全（over-claim），`FR` 是不完整（under-claim）。

### 4.2 供给案例上的结果

| 任务 | 关系 | 条件 | only | expose | msms | mmbs | full |
|---|---|---|---|---|---|---|---|
| `ctrl_01` | independent L4 | `(mode < 1)` | 0/0 | 0/3 | 0/0 | 0/0 | 0/0 |
| `ctrl_02` | cooperative L4,L6 | `(c < 1) and (d < 1) and (x < 6)` | 0/0 | 0/19 | 0/0 | 5/0 | 0/0 |
| `ctrl_03` | independent L4 | `(p < 1)` | 0/0 | 4/6 | 0/0 | 4/0 | **4/0** |
| `ctrl_03` | independent L6 | `(q < 1)` | 0/0 | 4/6 | 0/0 | 4/0 | **4/0** |
| `ctrl_03` | cooperative L8,L10 | `(c < 1) and (x < 5)` | 0/0 | 0/6 | 0/0 | 2/0 | 0/0 |
| `ctrl_03` | coexisting L4,L6 | `not (c < 1) or not (x < 5)` | 6/0 | 0/0 | 18/0 | 14/0 | **14/0** |
| `control_state` | independent L5 | `(c < 1)` | 3/0 | 0/3 | 3/0 | 0/0 | **3/0** |

关键读法：

- `condition_status=EXACT` 只对应 `only`（independent/cooperative）或 `expose`（coexisting）这一列，不对应 `full` 列。
- `ctrl_03 independent [L4]` 的条件在 `p=0,q=0` 的 4 个供给案例上为真，但 `Break({L4})` 为假，因为 L6 仍然掩盖；因此完整关系有 4 个假接受。
- `ctrl_03 coexisting [L4,L6]` 的条件在供给案例上对 `expose` 精确，但完整 MMBS 有 14 个假接受：条件为真时，`{L4}` 或 `{L6}` 已经单独暴露，S 不是最小破除集。
- `control_state independent [L5]` 的条件对 `Break`/MMBS 精确，但对 `Only`/MSMS/完整关系有 3 个假接受；因为全候选域下 `Only({L5})` 是 `INVALID`。

### 4.3 完整合法域上的结果

| 任务 | 关系 | 条件 | only | expose | msms | mmbs | full |
|---|---|---|---|---|---|---|---|
| `ctrl_01` | independent L4 | `(mode < 1)` | 0/0 | 0/3 | 0/0 | 0/0 | 0/0 |
| `ctrl_02` | cooperative L4,L6 | `(c < 1) and (d < 1) and (x < 6)` | 0/0 | 0/19 | 0/0 | 5/0 | 0/0 |
| `ctrl_03` | independent L4 | `(p < 1)` | 0/0 | 18/14 | 0/0 | 18/0 | **18/0** |
| `ctrl_03` | independent L6 | `(q < 1)` | 0/0 | 18/14 | 0/0 | 18/0 | **18/0** |
| `ctrl_03` | cooperative L8,L10 | `(c < 1) and (x < 5)` | 8/0 | 12/12 | 8/0 | 16/0 | **14/0** |
| `ctrl_03` | coexisting L4,L6 | `not (c < 1) or not (x < 5)` | 12/12 | 0/8 | 48/0 | **36/2** | **36/2** |
| `control_state` | independent L5 | `(c < 1)` | 3/0 | 0/3 | 3/0 | 0/0 | **3/0** |

完整合法域把 `ctrl_03` 的供给案例偏差放大：

- `ctrl_03` 供给案例有 20 个，合法网格有 `2*2*4*2*2 = 64` 个。当前案例集里 `c=0` 几乎总是伴随 `d=0`，所以 `c<1` 的条件在样本内看起来足够；完整网格中的 `c=0,d=1` 暴露了缺失的 `d` 条件。
- `cooperative [L8,L10]` 的 `only`/MSMS 在完整网格上已经有 8 个假接受，`full` 有 14 个假接受；它不是“条件只在极端输入上略有误差”，而是缺少了合法域中的一整块区域。
- `coexisting [L4,L6]` 的 MMBS 在完整网格上有 36 个假接受和 2 个假拒绝；当前 `VERIFIED` 不能读作 MMBS 的精确 Guard。

### 4.4 为什么 `condition_check.exact=True` 仍会出现这些假接受

因为 `exact` 比较的是合成标签，而不是完整关系标签：

```text
independent/cooperative: labels = Only_P
coexisting:              labels = Break
```

所以：

- `ctrl_03 independent [L4]`：`p<1` 的 `Only_P` 精确，但 `Only_P ∧ Break` 不精确；
- `ctrl_03 cooperative [L8,L10]`：`c<1 ∧ x<5` 的 `Only_P` 在供给案例上精确，但不是完整合法域的 `Only_P`，也不是完整的 `Only_P ∧ Break ∧ 最小性`；
- `ctrl_03 coexisting [L4,L6]`：`Break` 在供给案例上精确，但 `Break ∧ proper subsets masked` 不精确。

这不是“条件语言表达力不足”的问题，而是**条件拟合目标少了一个合取项**的问题。即使条件语言足够强，当前实现也不会自动修正，因为标签本身只有半边。

### 4.5 状态命名的后果

当前 `VERIFIED` 的定义实际上接近：

```text
witness 上成立
+ 条件在供给案例上对“合成用半边”精确
+ 没有显式记录范围
```

它不等于：

```text
在声明合法域上对完整关系精确
+ 候选全集完整
```

因此：

- `ctrl_01` 的 `VERIFIED` 可以保留为完整关系精确的证据；
- `ctrl_02` 的 `VERIFIED` 可以保留为“MSMS + 整组破除”精确，但不能读成 MMBS；
- `ctrl_03` 的三个非平凡关系、以及 `control_state` 的 `independent [L5]`，都应降级或改名为半边验证，不能继续用同一个 `VERIFIED` 表示完整关系。

---

## 5. C→B 反例：候选范围限定还是关系定义错误？

### 5.1 全候选域下的真值

`control_state` 的 `c=0` 组：

```text
Only(∅)      = EXPOSED
Only({C})    = EXPOSED
Only({B})    = INVALID     # C 被关闭，flag 未定义
Only({C,B})  = MASKED

Break(∅)     = MASKED
Break({C})   = INVALID
Break({B})   = EXPOSED
Break({C,B}) = EXPOSED
```

所以：

```text
MSMS_U = {{C, B}}
MMBS_U = {{B}}
```

- `{B}` 不是 MSMS：它单独启用时 C 被关闭，执行非法。
- `{B}` 是 MMBS：关闭 B 会暴露，关闭空集不会。
- `{C,B}` 是 MSMS：两者一起启用时掩盖；去掉任何一个都不充分。
- `C` 是 B 的控制前置，不是 B 的“替代掩盖路径”。

### 5.2 当前输出

`discover_expanded()` 对 `control_state` 输出：

```text
independent [L5]  condition (c < 1)  VERIFIED
```

其 evidence 中：

```text
disable_other_masking_candidates.kept_prerequisites = [L4]
disable_other_masking_candidates.disabled_keys = []
```

也就是说，所谓“只保留 B”实际是“保留 C 和 B，关闭其他所有候选”；由于候选全集只有 C、B，这个干预就是不关闭任何东西，等于基线。于是 `Only_P({B})` 为真，`Break({B})` 为真，关系被接受。

### 5.3 这是有意的范围限定，还是定义错误？

两者都有，必须分开说：

1. **有意的部分**：`control_prerequisites()` 明确把 C 保留下来，代码注释也说明 C 是前置而不是竞争掩盖者。这是对“只保留 S”干预的一个**语义修正**，避免因为关闭 C 而制造非法执行。这个修正本身是合理的。
2. **定义错误的部分**：把修正后的 `Only_P({B}) ∧ Break({B})` 命名为 `independent`，并给出 `VERIFIED`，是错误的。它既不是全程序 `MSMS`，也不是全程序 `MMBS`，更不是 `Only({B})` 下的独立关系。它应该被命名为“前置条件化的单元素破除关系”，并显式携带 `P={C}` 与 `U={C,B}`。
3. **范围限定的部分**：当前输出没有把 `U`、`P`、`candidate_complete` 写进关系状态；消费者只能看到 `independent [5]`。因此它会被读成“B 单独就是 independent”，而不是“在 C 保持启用的前提下，B 是破除单元素”。
4. **更严重的变体**：如果 C 位于 A 之前，候选发现器根本不会看到 C，结果仍然返回 `OK`、`independent [B]`、`VERIFIED`。此时连 `kept_prerequisites` 都没有，范围限定完全不可见。这不能称为有意的候选范围限定，只能称为候选完整性缺口。

### 5.4 旧 `discover()` 的相反标签

旧 `discover()` 在同一个程序上输出：

```text
cooperative {L4, L5}  VERIFIED
```

它之所以能找到 C，是因为旧的顶层反向切片把 C 也纳入了候选；它输出的是 MSMS `{C,B}`。这与新 `discover_expanded()` 的 `independent [B]` 不是“新旧版本对同一事实的不同置信度”，而是**两个不同的关系定义**：

- 旧：`{C,B}` 是共同充分的，标签 `cooperative`（MSMS 意义正确）。
- 新：`{B}` 是前置豁免下的破除单元素，标签 `independent`（命名错误）。

两个测试同时通过，正好证明语义漂移没有被测试捕获：

- `tests/test_open_ops_discovery.py:114` 使用 `discover()`，期望 `cooperative {4,5}`；
- `tests/test_open_ops_contracts.py:50` 使用 `discover_expanded()`，期望 `independent {5}`。

### 5.5 建议的正确标签

在 v2 中，C→B 应至少输出两条记录：

```text
MSMS: {C, B}
      scope: U={C,B}, full candidate universe
      condition: c == 0
      evidence: Only({C,B}) = MASKED; Only({C})/Only({B}) 不成立

prerequisite_conditioned_breaking:
      S={B}, P={C}
      condition: c == 0
      evidence: Only_P({B}) = MASKED; Break({B}) = EXPOSED
      scope: U={C,B}, P 明示为前置
```

不应输出：

```text
independent: {B}
```

除非同时证明 `Only({B})` 在全候选域上成立；在本例中它不成立。

---

## 6. 候选范围完整性审计

### 6.1 形式问题

当前 `find_candidates_expanded()` 只扫描 A 之后的支持写语句，并把循环、`try/with`、嵌套定义等记为 `unsupported`。这有两个不同的问题：

1. **结构未支持**：`unsupported` 会记录，结果可降级为 `UNSUPPORTED/PARTIAL`。这是可见的。
2. **候选遗漏**：A 之前的合法写语句、控制前置、跨函数 effect 等，可能根本不会进入候选，也不会进入 `unsupported`。这是不可见的。

`verifier_v2.verify_relation()` 只能验证传入矩阵中的操作；它没有“候选是否完整”的输入。`run_development._independent_verifier()` 又只把关系自身的行传给矩阵，因此它连“同一发现过程中已找到的其他候选”都不一定看得到。故 `all_verified=True` 不是候选完整性的证据。

### 6.2 探针一：C 在 A 之前

```python
def program(x, c):
    flag = c == 0        # C，控制前置
    v = x
    v = v + 1            # TARGET_A
    if flag:             # B
        v = x
    return v
```

候选发现器只扫描 A 之后，得到：

```text
status = OK
candidates = [L5]
relations = [independent L5, condition (c < 1), VERIFIED]
unsupported = []
```

全候选域若包含 `{C,B}`：

```text
MSMS = {{C, B}}
MMBS = {{B}}
```

但 C 不在候选里，所以结果没有 `unsupported`，也没有 `PARTIAL`。这是最危险的情况：**局部候选验证被呈现为全程序完整归因，且没有任何范围标记。**

### 6.3 探针二：C 在 `try` 中

```python
def program(x, c):
    v = x
    v = v + 1            # TARGET_A
    try:
        flag = c == 0    # C
    except Exception:
        flag = False
    if flag:             # B
        v = x
    return v
```

结果为：

```text
status = PARTIAL
unsupported = [try ...]
relations = [independent L8, condition (c < 1), VERIFIED]
```

`PARTIAL` 只在结果层；关系层仍然是 `VERIFIED`。如果下游消费者只看关系，或只看 `all_verified`，仍然会把局部关系当作完整归因。`unsupported` 没有阻止关系输出，也没有在关系上写 `scope=candidate_incomplete`。

### 6.4 `verifier_v2` 的关系局部矩阵

`run_development._independent_verifier()`：

```python
lines = [rel.operations 中出现的行]
matrix = run_matrix(..., names={op_i: line}, ...)
```

它只把关系涉及的行交给 `verifier_v2`。因此：

- 对 `control_state`，它只看到 `{L5}`，看不到 `{L4}`；`only_claim_masks` 检查的是“关闭空集”，不是“关闭 C”。
- 即使 `verifier_v2` 的 `only_key = all_ops - claim` 公式正确地会关闭其他操作，它也没有其他操作可关。

所以 `all_verified=True` 的准确含义是：

```text
在“关系自己声明的操作集合”这个局部矩阵上，witness 通过
```

而不是：

```text
在发现器声明的候选全集上通过
```

更不是：

```text
在全程序所有相关操作上通过
```

### 6.5 结论与必须新增的范围字段

当前原型不能声称“完整归因”。至少需要显式字段：

```text
relation.scope = {
  candidate_universe: [...],
  candidate_source: "expanded_ast" | ...,
  candidate_complete: true | false | "unknown",
  omitted_constructs: [...],
  prerequisites: [...],
  finite_cases: n,
  legal_domain_exact: true | false | "unknown"
}
```

规则建议：

- 只要 `candidate_complete != true`，关系状态不能是裸 `VERIFIED`；应为 `VERIFIED_RELATIVE_TO_CANDIDATES` 或 `WITNESS_ONLY`。
- 只要存在 `unsupported`，关系级状态必须至少降为 `PARTIAL`，不能只在结果级降级。
- `verifier_v2` 应接收完整的发现候选全集，或者显式接收 `scope`；不能只接收关系行。
- 对 A 之前的控制前置，必须做前向候选扫描或数据依赖闭包；否则 `OK` 应改为 `INCOMPLETE_SCOPE`。

---

## 7. 历史标签与版本化处理

### 7.1 处理原则

- **不覆盖**：不修改 `open_ops/out/development.json`、`development.log`、`tests/test_open_ops_discovery.py` 中的旧断言，也不修改 M1–M6 的任何结果。
- **先报告**：本文件是报告；旧标签保持原样，只新增注释或 v2 输出。
- **版本化**：给语义定义加版本号；旧输出标记 `semantics_version="v1"`，新输出写 `development_v2.json` 等新文件。
- **测试分层**：旧测试保留为 v1 兼容测试；新增 v2 语义测试，不删除旧测试、不减少测试数量。

### 7.2 需要注释或重命名的旧标签

| 位置 | 旧标签 | 审计读法 | 建议 |
|---|---|---|---|
| `development.json` / 决策文档 | `ctrl_01 independent L4` | MSMS=MMBS={L4}，完整关系在样本/合法域精确 | 可保留，标 `v1` |
| `development.json` | `ctrl_02 cooperative L4,L6` | MSMS 正确；MMBS={L4}、{L6}；不是“必须一起禁用” | 注释“cooperative = 最小充分，不是 MMBS”；v2 增列 MMBS |
| `development.json` | `ctrl_03 independent L4/L6` | 在 `p<1` 上是 MSMS；在 `p=q=0` 上不是 MMBS；条件对完整关系有假接受 | v2 改为 `msms` 或 `single_masker`，并单列 MMBS |
| `development.json` | `ctrl_03 cooperative L8,L10` | 在 `p=q=1,c=d=0,x=3/4` 上是 MSMS；不是 MMBS；完整合法域条件缺 `d` | v2 重新合成条件；`VERIFIED` 降级或限定域 |
| `development.json` | `ctrl_03 coexisting L4,L6` | 在 `p=q=0` 上是 MMBS；不是极小充分集合；条件对 MMBS 有大量假接受 | v2 改名为 `mmbs`，条件按完整 MMBS 重合成 |
| `development.json` | `control_state independent L5` | 全候选域 MSMS={C,B}，MMBS={B}；当前是 `Only_P` 前的破除单元素 | v2 改名 `prerequisite_conditioned_breaking`，保留 C 为前置 |
| `development.json` | 真实题 `url_unparse independent L57` | `WITNESS_ONLY`，条件 `UNKNOWN`，候选完整性未知 | 保持 `WITNESS_ONLY`；不得升级为完整归因 |
| `development.json` | `headerset` / `click` `UNSUPPORTED` | 结构未支持，结论为空 | 保持，不得写成“无掩盖” |
| `docs/MACE_operation_discovery_decision.md` | “73 条通过”“条件 exact”“all_verified=True” | 测试通过，但 `exact` 是半边标签精确；`all_verified` 是关系局部矩阵 | 增加指向本审计的说明；不删除原文结论，但标注语义范围 |

`url_unparse` 的 `condition_status=UNKNOWN` 本身是正确的保守处理；问题不在它，而在于同批的 `ctrl_03` 关系被同一个 `VERIFIED` 名称覆盖了不同的证据强度。v2 应把“witness 通过但候选完整性未知”和“完整关系在声明域上精确”拆成两个状态。

### 7.3 建议的 v2 状态与字段

```text
relation_kind:
  msms
  mmbs
  prerequisite_conditioned_breaking
  (不再把 independent/cooperative/coexisting 当作形式定义名称；
   如保留旧名，只作为 v1 兼容别名)

status:
  WITNESS_ONLY
  FINITE_CASE_EXACT          # 仅供给案例
  LEGAL_DOMAIN_EXACT         # 声明合法域
  VERIFIED_RELATIVE_TO_CANDIDATES
  VERIFIED_COMPLETE          # 需要 candidate_complete=true

scope:
  candidate_universe
  candidate_complete
  omitted_constructs
  prerequisites
  finite_cases
  legal_domain
  domain_exact
  relation_half_exact
```

### 7.4 旧日志保留方式

- 保留 `open_ops/out/development.json`、`development.log` 原文件不动。
- 新增 `open_ops/out/development_v2.json`、`development_v2.log`；在 v2 中加 `semantics_version="v2"`。
- 新增 `docs/MACE_masking_semantics_v2.md`（或在本文件后续版本中）记录公式修订。
- 旧测试文件保留；新增 `tests/test_open_ops_semantics_v2.py`。
- 本审计的 `open_ops/out/semantics_audit.json` 作为只读快照保留；它不替代旧结果，也不作为新评分。

---

## 8. 研究决策：确定性原型还能不能作为可信基线？

### 8.1 结论

**可以继续作为“声明候选域内的 witness 级可执行回归工具”，但不能继续作为“完整归因”或“精确 Guard”的可信基线。**

具体分级：

| 用途 | 当前是否可信 | 说明 |
|---|---|---|
| 复现某个输入上的掩盖/暴露 witness | 是 | 执行矩阵与观测记录是真实的 |
| 在声明候选集合内做子集回归 | 是 | 需要显式 `candidate_universe` |
| 声称全程序 MSMS/MMBS 完整 | 否 | 候选遗漏不可检测，C→B 探针已证明 |
| 声称条件是全程序精确 Guard | 否 | 条件只拟合半边，且只对供给案例精确 |
| 支持 MACE 合同带来语义增益 | 否（与上一轮一致） | 合同未带来新候选/新关系；本轮不改变该结论 |
| 作为新 benchmark 评分 | 否 | 语义定义未统一，不能作为评分真值 |

### 8.2 恢复可信基线的最低修正

不动旧结果，按以下顺序做 v2：

1. **拆名**：`msms`、`mmbs`、`prerequisite_conditioned_breaking` 分开；不再用 `independent/cooperative/coexisting` 混装。
2. **条件拟合完整关系**：`independent/cooperative` 的标签必须是 `Only ∧ Break ∧ 最小性`；`coexisting` 必须是 `Break ∧ proper subset Masked`；条件检查必须在这个合取上做，而不是半边。
3. **完整合法域**：把 `legal_values` 网格作为条件精确性域；供给案例只作为 witness 来源。`exact` 必须区分 `finite_case_exact` 与 `legal_domain_exact`。
4. **候选完整性**：前向扫描 A 之前的控制前置，或至少把“未扫描区域”写入 `candidate_complete`；`verifier_v2` 接收完整候选全集，而不是只接收关系行。
5. **状态分级**：`VERIFIED` 仅在 `candidate_complete=true` 且 `legal_domain_exact=true` 时使用；否则 `WITNESS_ONLY` / `VERIFIED_RELATIVE_TO_CANDIDATES`。
6. **前置语义**：C→B 输出 `MSMS={C,B}` 与 `prerequisite_conditioned_breaking(B, P={C})` 两条，不输出 `independent B`。

在这些修正完成前，**不要扩建真实 Benchmark，不要用当前 `VERIFIED` 集合作为论文或评分中的“完整归因”证据，也不要把 MACE 合同臂解释为发现了新关系。** 这与上一轮“STOP 合同扩建”的结论一致，但本轮进一步说明：即使作为确定性基线，也必须先修语义，不能直接沿用旧标签。

### 8.3 对“是否继续 MACE 合同辅助发现”的回答

- 本轮没有运行 Qwen，没有新题，没有新合同实验。
- 基于已有结果，合同没有带来新增候选或新增已验证关系；本审计又表明当前“已验证”本身是半边/局部范围的。因此没有理由继续扩建合同辅助发现。
- 若继续研究，优先级应是“语义修正 + 候选完整性 + 条件完整域”，而不是“更多题、更大枚举、更多合同提示”。

---

## 附录 A：完整逐子集真值矩阵

以下矩阵与 `open_ops/out/semantics_audit.json` 一致。每一组内的输入在全部子集上结果相同；`∅` 是基线。`INVALID` 表示 P+ 未正常返回，不能当作掩盖。

### A.1 `ctrl_01`

**group 1：`mode=0`（3 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | MASKED | EXPOSED |

**group 2：`mode=1`（3 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | EXPOSED |
| {L4} | EXPOSED | EXPOSED |

### A.2 `ctrl_02`

**group 1：`c=0,d=0,x∈{1..5}`（5 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | EXPOSED | EXPOSED |
| {L6} | EXPOSED | EXPOSED |
| {L4,L6} | MASKED | EXPOSED |

**group 2：`c=0,d=1` 或 `c=1`（19 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | EXPOSED |
| {L4} | EXPOSED | EXPOSED |
| {L6} | EXPOSED | EXPOSED |
| {L4,L6} | EXPOSED | EXPOSED |

### A.3 `ctrl_03`

**group 1：`p=0,q=1`（4 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | MASKED | EXPOSED |
| {L6} | EXPOSED | MASKED |
| {L8} | EXPOSED | MASKED |
| {L10} | EXPOSED | MASKED |
| {L4,L6} | MASKED | EXPOSED |
| {L4,L8} | MASKED | EXPOSED |
| {L10,L4} | MASKED | EXPOSED |
| {L6,L8} | EXPOSED | MASKED |
| {L10,L6} | EXPOSED | MASKED |
| {L10,L8} | EXPOSED | MASKED |
| {L4,L6,L8} | MASKED | EXPOSED |
| {L10,L4,L6} | MASKED | EXPOSED |
| {L10,L4,L8} | MASKED | EXPOSED |
| {L10,L6,L8} | EXPOSED | MASKED |
| {L10,L4,L6,L8} | MASKED | EXPOSED |

**group 2：`p=1,q=0`（4 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | EXPOSED | MASKED |
| {L6} | MASKED | EXPOSED |
| {L8} | EXPOSED | MASKED |
| {L10} | EXPOSED | MASKED |
| {L4,L6} | MASKED | EXPOSED |
| {L4,L8} | EXPOSED | MASKED |
| {L10,L4} | EXPOSED | MASKED |
| {L6,L8} | MASKED | EXPOSED |
| {L10,L6} | MASKED | EXPOSED |
| {L10,L8} | EXPOSED | MASKED |
| {L4,L6,L8} | MASKED | EXPOSED |
| {L10,L4,L6} | MASKED | EXPOSED |
| {L10,L4,L8} | EXPOSED | MASKED |
| {L10,L6,L8} | MASKED | EXPOSED |
| {L10,L4,L6,L8} | MASKED | EXPOSED |

**group 3：`p=0,q=0`（4 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | MASKED | MASKED |
| {L6} | MASKED | MASKED |
| {L8} | EXPOSED | MASKED |
| {L10} | EXPOSED | MASKED |
| {L4,L6} | MASKED | EXPOSED |
| {L4,L8} | MASKED | MASKED |
| {L10,L4} | MASKED | MASKED |
| {L6,L8} | MASKED | MASKED |
| {L10,L6} | MASKED | MASKED |
| {L10,L8} | EXPOSED | MASKED |
| {L4,L6,L8} | MASKED | EXPOSED |
| {L10,L4,L6} | MASKED | EXPOSED |
| {L10,L4,L8} | MASKED | MASKED |
| {L10,L6,L8} | MASKED | MASKED |
| {L10,L4,L6,L8} | MASKED | EXPOSED |

**group 4：`p=q=1,c=d=0,x∈{3,4}`（2 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | EXPOSED | MASKED |
| {L6} | EXPOSED | MASKED |
| {L8} | EXPOSED | EXPOSED |
| {L10} | EXPOSED | EXPOSED |
| {L4,L6} | EXPOSED | MASKED |
| {L4,L8} | EXPOSED | EXPOSED |
| {L10,L4} | EXPOSED | EXPOSED |
| {L6,L8} | EXPOSED | EXPOSED |
| {L10,L6} | EXPOSED | EXPOSED |
| {L10,L8} | MASKED | EXPOSED |
| {L4,L6,L8} | EXPOSED | EXPOSED |
| {L10,L4,L6} | EXPOSED | EXPOSED |
| {L10,L4,L8} | MASKED | EXPOSED |
| {L10,L6,L8} | MASKED | EXPOSED |
| {L10,L4,L6,L8} | MASKED | EXPOSED |

**group 5：其余 `p=q=1` 输入（6 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | EXPOSED |
| {L4} | EXPOSED | EXPOSED |
| {L6} | EXPOSED | EXPOSED |
| {L8} | EXPOSED | EXPOSED |
| {L10} | EXPOSED | EXPOSED |
| {L4,L6} | EXPOSED | EXPOSED |
| {L4,L8} | EXPOSED | EXPOSED |
| {L10,L4} | EXPOSED | EXPOSED |
| {L6,L8} | EXPOSED | EXPOSED |
| {L10,L6} | EXPOSED | EXPOSED |
| {L10,L8} | EXPOSED | EXPOSED |
| {L4,L6,L8} | EXPOSED | EXPOSED |
| {L10,L4,L6} | EXPOSED | EXPOSED |
| {L10,L4,L8} | EXPOSED | EXPOSED |
| {L10,L6,L8} | EXPOSED | EXPOSED |
| {L10,L4,L6,L8} | EXPOSED | EXPOSED |

### A.4 `control_state_C_changes_state_B_controlled`

**group 1：`c=0`（3 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | MASKED |
| {L4} | EXPOSED | INVALID |
| {L5} | INVALID | EXPOSED |
| {L4,L5} | MASKED | EXPOSED |

**group 2：`c=1`（3 个输入）**

| S | Only(S) | Disable(S) |
|---|---|---|
| ∅ | EXPOSED | EXPOSED |
| {L4} | EXPOSED | INVALID |
| {L5} | INVALID | EXPOSED |
| {L4,L5} | EXPOSED | EXPOSED |

### A.5 候选遗漏探针的完整集合

`probe_C_before_A`：

```text
candidate universe seen by discover_expanded = {L5}
full relevant universe = {L2 (C), L5 (B)}
MSMS = {{L2, L5}}
MMBS = {{L5}}
reported = independent L5, condition (c < 1), VERIFIED
```

`probe_C_in_try`：

```text
candidate universe seen by discover_expanded = {L8}
full relevant universe = {L8, C in try}
reported = independent L8, condition (c < 1), VERIFIED
result status = PARTIAL (unsupported try)
```

两个探针都不修改任务文件；它们只用于本轮审计。

---

## 附录 B：复现与证据

- 审计脚本：`d:/tmp/audit_masking_semantics.py`（只读；不修改发现器）。
- 审计输出：`open_ops/out/semantics_audit.json`。
- 相关测试：

```bash
python -m pytest tests/test_open_ops_discovery.py \
  tests/test_open_ops_contracts.py tests/test_verifier_v2.py -q
```

本轮结果：29 passed。

- 本文件只新增审计结论；没有修改 `open_ops/discover.py`、`benchmark_pilot/verifier_v2.py`、`scripts/check_open_interface.py`、任务文件、M1–M6 输出或旧日志。
