# M5 诊断报告：MACE 的分阶段失败定位

本报告对应 M5 任务：不再增加 Agent、Prompt 反馈字段或新功能，只做分阶段诊断、
2×2 能力上限检查和独立 held-out 泛化测试。所有结论均来自仓库中的实际运行记录
（`m5/`），没有重新编造任何数字。

**证据等级说明**：本文中的“正确/精确”一律指在声明的有限输入域上与真实删除
结果逐输入相等，证据状态为 `BOUNDED`（穷举）或 `TESTED`（采样）。
本原型没有无限域证明过程，因此**从不输出 `PROVEN`**。

---

## 0. 结论（先回答五个问题）

1. **主瓶颈是关系（尤其是条件）的生成，而不是组合。** 9 个 fixture 的
   `target_effect` 全部 `BOUNDED`（模型对 A 本身局部效应描述 9/9 正确）；
   8/9 的第一次失败落在 `upstream`，且只有 1/9 的契约所有非 guard 关系通过。
   决定性错误集中在：fixed-point 条件写反（`modulo_absorb`）、observer 条件
   过强（`sort_channel`、`dedup_channel`、`swap_channels`）、observer 表达式
   误用 A 前变量去读 A 后快照（`overwrite_channel`）。
2. **确定性组合并不比 Qwen 自由写 guard 更准，但更安全。** 同一份 Qwen 契约下
   A = 3/9、B = 3/9（正确的 case 不同）；B 从不产生 unsound guard（sound 5/9，
   A 为 4/9）。给定人工复核契约后，C = 5/9、D = 9/9，说明“关系正确时组合器是
   对的”；但 B 无法弥补错误关系，所以整体准确率没有提升。
3. **Qwen 自动发现且通过验证的正确关系很少**：`dead_flag` 是唯一 4/4 全通过的
   契约；`parity_snap` 的唯一 observer 条件（`even and sum(xs)%2==0`）是决定性的
   正确关系；`alt_masking`、`dict_slot` 的 guard 对，但契约不完整；
   `sort_channel`、`swap_channels` 只发现了正确的 observer 表达式（channel 0/1），
   条件仍然错误或缺失；`overwrite_channel`、`modulo_absorb` 没有任何决定性关系
   通过。
4. **M5 期间没有一例最终正确结果可以归因于工程性修复。** 重复 observer 的解析
   放宽让 `parity_snap` 第 1 轮的精确 guard 变得“合法可见”，但 repair 第 2–3 轮
   又把它改坏，最终准确率不变（A 3/9 → A3 3/9）。组合器“缺 channel 就不给
   guard”只改善了 soundness，没有增加 exact。变参 `min/max` 只影响复核用参考
   契约的编译，不进入任何模型运行。
5. **现有证据不支持按当前形态继续扩大 MACE 算法研究。** 在原始 6 个开发 fixture
   上，MACE 1/6（73.7k tokens，388 s），普通 direct 基线 3/6（13.5k tokens，61 s），
   12 轮 token 更多的 direct 基线也是 3/6（109.2k tokens，258 s）；在从未使用过的
   held-out 第二批上，**所有方法都是 0/2**。2×2 说明“关系正确 → 组合 → 精确”
   的链条是通的（D = 9/9），真正缺的是可靠的关系/条件归纳和单调的修复策略。
   最多值得做一个预注册的窄实验（单调修复 + 条件归纳），若仍打不过 direct
   基线，应停止这条路线。

---

## 1. 实验设置

| 项 | 值 |
|---|---|
| 模型 | `qwen2.5-coder:32b`（Ollama） |
| 解码 | temperature 0，seed 42，`num_ctx=8192` |
| 环境 | AutoDL GPU 主机；`OLLAMA_MODELS=/root/autodl-tmp/ollama_models` |
| 域 | 每个 fixture 声明的穷举有限域；通过的 verdict 为 `BOUNDED`，从不出现 `PROVEN` |
| 指标 | typed / sound / complete / exact（见 §1.2） |
| 主运行 | MACE 3 轮；direct/generic/fixed 3 轮；T = direct 12 轮 |
| 旧对照 | M1–M4 的 4 轮 full MACE（`m5/diag_before_32b.json`） |

### 1.1 数据划分

* **开发集（6 个原始 fixture）**：`alt_masking`, `dedup_channel`,
  `modulo_absorb`, `overwrite_channel`, `sort_channel`, `swap_channels`。
* **held-out 第一批（3 个）**：`dead_flag`, `dict_slot`, `parity_snap`。
  这 3 个在 M5 的解析器修复诊断中被使用过（A3/H2），**不是完全干净的泛化集**，
  因此下文单独标注。
* **held-out 第二批（2 个，真正独立）**：`clamp_absorb`, `toggle_pair`。
  生成于所有 M5 模型运行之前，从未参与任何调参；只在最后的 H3 批次中运行。

### 1.2 指标定义

* **typed**：guard 能被受限语言解析并通过类型检查。
* **sound**：typed 且在所有暴露输入上不误报“被遮蔽”（无假接受）。
* **complete**：typed 且在真正被遮蔽的输入上不误报“暴露”（无假拒绝）。
* **exact**：sound 且 complete，即在有界域上与真实 mask 完全一致。
* sound/complete 是单侧指标，即使整体 verdict 为 `REFUTED` 也单独报告，
  以免把“方向性正确”误记为零。
* **contract all-pass**：除 `mask_guard` 外所有关系均为 `BOUNDED/TESTED`。
* **attribution**：关系引用行与人工复核契约引用行的交集比例。这是**行级重叠**，
  不是逻辑支持证明；没有关系时记 `n/a`。
* tokens 为 Ollama 报告的 prompt tokens；s 为模型时间，不含本地验证。

### 1.3 本轮涉及的代码改动（仅修复，不新增系统能力）

| 改动 | 位置 | 影响 |
|---|---|---|
| 每字段变量域与明确报错 | `mace/verify.py` | Phase 1；错误信息区分 “entry arguments only / `_post` only in target_effects” |
| 同 channel 多 observer 合法 | `mace/contracts.py` | 解析器缺陷修复；A vs A3 的受控对比只差这一处 |
| 缺 channel 时不给 guard | `mace/compose.py` | 以前会退化成 `True`（unsound），现在返回 `INCOMPLETE` 且无表达式 |
| `min/max` 支持 1 或 2 个参数 | `mace/terms.py` | 语言完整性修复；**所有模型运行之后**才加入，不影响 M5 结果 |
| `cells.py` 支持无 bundle 的基线 | `mace/cells.py` | 仅分析工具，让 direct/generic/fixed 行能进 2×2 表 |

`docs/M1_report.md`、`docs/M2_M4_report.md` 描述的是更早的系统；本报告的
数字以 `m5/` 下的原始运行 JSON 为准。

### 1.4 预算的混杂

旧对照（M1–M4 full MACE）是 **4 轮**，M5 的 A/A3 是 **3 轮**。因此
“旧 2/6 vs 新 3/9”不能当作纯粹的 Phase 1 前后效果；§2 只对**能在同一轮预算下
比较的项**（最终 guard 的 INVALID 类型、每轮 INVALID 比例）下结论。

---

## 2. Phase 1：变量域规则

### 2.1 规则

每个契约字段只在自己的词表里求值（`mace/verify.py`）：

| 字段 | 可用名字 | 说明 |
|---|---|---|
| `target_effects` | 入口参数、A 之前的局部变量（plain）、`<name>_post` | 唯一允许 `_post` 的字段 |
| `upstream` | 入口参数 | 只能陈述入口上的事实 |
| `observers` | 入口参数、A 之后的快照（**plain 名字**） | 快照读 plain，不读 `_post` |
| `mask_guard` | 入口参数 | 局部变量、`_post`、最终输出一律不可用 |

两条额外的忠实性义务：

* observer 的表达式必须在 **P+ 与 P− 两侧**都等于该 channel 的真实输出
  （two-sided faithfulness），防止把“结果”复述成“观察”；
* fixed-point 关系的条件必须蕴含 `snap_plus == snap_minus`，否则降级。

### 2.2 单元测试

`tests/test_interface_rules.py` 覆盖：guard 不得出现 `_post`、不得使用 checker
输出字段、observer 条件不得读真实输出、observer 双侧忠实、同 channel 多
observer 合法、错误 fixed point 被降级且不进入组合、target effect 可同时看到
两个状态。完整测试集 126 项通过（`python -m pytest -q`）。

### 2.3 前后对比（最终 guard）

| 运行 | fixture | 轮数 | typed | exact | 最终 INVALID 类型 | typed 中的语义错误 |
|---|---|---|---|---|---|---|
| 旧 full MACE（M1–M4） | 6 开发 | 4 | 3/6 | 2/6 | 3 = 1 `_post` + 2 local | 1（unsound） |
| A（Phase 1 后、解析器修复前） | 9 | 3 | 7/9 | 3/9 | 2 = 1 `_post` + 1 local | 4 |
| A3（解析器修复后） | 9 | 3 | 7/9 | 3/9 | 2 = 1 sort + 1 other | 4 |

最终层面 `_post`/local 误用从 3/6 降到 0/9，但**这不是模型学会了规则**：
每轮 guard 尝试里的误用仍然很多。

### 2.4 每轮 guard 尝试中的 INVALID

| 运行 | guard 求值次数 | INVALID | `_post` | 局部变量 | 其他类型错误 | 比例 |
|---|---|---|---|---|---|---|
| A（Phase 1 后） | 25 | 5 | 2 | 3 | 0 | 20.0% |
| A3（解析器修复后） | 25 | 8 | 2 | 3 | 3（2 sort + 1 other） | 32.0% |
| H2（held-out 第一批，A3 同配置） | 7 | 0 | 0 | 0 | 0 | 0% |
| H3（held-out 第二批） | 24 | 12 | 7 | 5 | 0 | 50.0% |
| base（3 轮三基线，27 run） | 62 | 16 | 7 | 7 | 2 | 25.8% |
| T（direct，12 轮） | 58 | 8 | 4 | 3 | 1 | 13.8% |
| C（给定复核契约） | 13 | 1 | 1 | 0 | 0 | 7.7% |

结论：

* 规则和测试保证“写对的契约能合法编译”，也把错误信息变得可分类；
* 但没有消除模型的记法错误。held-out 第二批的 24 次尝试中 12 次 INVALID，
  其中 7 次再次使用 `_post`、5 次使用局部变量（`total`, `a`, `value`）。
  模型在 `_post`、局部名、输出名之间来回漂移；
* 最终准确率看起来比每轮好，是因为 loop 采用**最后一轮覆盖**：后一轮碰巧
  typed，就把前面的 INVALID 掩盖了。这会把“记法不稳定”误读成“已修复”。
  因此必须同时报告每轮比例，不能只看 final。

---

## 3. Phase 2：逐案例错误定位

### 3.1 总览

`mace.cli diagnose` 的“first bad stage”按字段顺序取最早失败，会把只起解释作用
的 `supporting` upstream（例如 `alt_masking` 里错误放置的 guard 公式）也算进去，
所以 8/9 显示 `upstream`。更有信息量的是**进入组合的 guard-relevant 关系**：

| fixture | target_effect | fixed_point 关系 | 覆盖的 channel | Qwen 最终 guard | 决定性第一错误 | exact |
|---|---|---|---|---|---|---|
| alt_masking | BOUNDED | 2 个均 REFUTED（把 guard 公式当事实） | 0 | `mode == 0 or mode == 1` | 无（guard 正确；upstream 放错槽） | 是 |
| dead_flag | BOUNDED | — | 0,1 | `True` | 无 | 是 |
| dedup_channel | BOUNDED | U1 `len(xs)==0` REFUTED | 0（条件过强） | 合法化失败 | observer 条件过强；后修成 `distinct(xs)` 布尔误用 | 否 |
| dict_slot | BOUNDED | U1 REFUTED | 1（channel 0 缺） | `mode` | observer O0 表达式错（快照语义） | 是 |
| modulo_absorb | BOUNDED | U2 `not cap` REFUTED | 无 | 类型错误 | fixed-point 条件写反 | 否 |
| overwrite_channel | BOUNDED | U2 `not keep` REFUTED | 无 | `keep or not keep` | observer 用 A 前名字读 A 后快照；fixed point 亦错 | 否 |
| parity_snap | BOUNDED | U1 条件写成 `even`（缺 `sum%2==0`） | 0 | `even and (...) or not even` | 关系正确（O0 已对），**repair 破坏 r1 精确解** | 否 |
| sort_channel | BOUNDED | U1 `True` REFUTED | 0,1（条件过强） | `xs == sorted(xs)` | observer 条件过强；缺 `pre` fixed point | 否 |
| swap_channels | BOUNDED | U1 `True` REFUTED | 0,1（channel 2 缺） | `True` | observer O2 条件缺失（`not show_gap or n==k`） | 否 |

`target_effect` 在 9/9 中全部 `BOUNDED`：模型对“A 把哪个局部量改成什么”没有
问题。所有决定性错误都在 A 之后的观察/条件上。

### 3.2 `overwrite_channel`：快照语义与 fixed point 同时错

源码（`fixtures/overwrite_channel.py`）：

```python
value = fn_0(xs)      # 9
value = 0             # 11  TARGET_A
if keep:
    value = fn_0(xs)  # 14
return value, value + 1
```

真实局部效应（Qwen 也写对了）：`value_post == 0`。正确 guard：
`keep or fn_0(xs) == 0`（keep 为真时下游重算；keep 为假时只有原 sum 为 0 才相等）。

| 轮 | Qwen guard | verdict | 关键错误 |
|---|---|---|---|
| 1 | `keep` | REFUTED，incomplete=12 | 漏掉 `fn_0(xs)==0` 分支；但 sound |
| 2 | `keep and value == fn_0(xs) or not keep` | INVALID（local `value`） | 用 A 前名字读快照 |
| 3 | `keep or not keep` | REFUTED，unsound=28 | 退化成 `True` |

关系层面：

* U2 被标为 `fixed_point` 且 `expr = not keep, condition = True`——错。keep 为假时
  A 把 `value` 从 `fn_0(xs)` 改成 0，并不是不动点。正确 fixed point 是
  `fn_0(xs) == 0`（此时 0 与 sum 相等）。
* O0/O1 写成 `value if keep else 0`、`value + 1 if keep else 1`。observer 求值时
  `value` 已经是 A 后的 0，所以 keep 分支返回 0 而不是 `fn_0(xs)`；P− 侧也不等。
  正确写法是 `fn_0(xs) if keep else value`。
* 正确 observer 条件：`keep or fn_0(xs) == 0`（源码行 8,10,12,13）。

可复现揭示输入：

* r1 漏判：`xs=[]`, `keep=False`，两侧输出都是 `[0,1]`，guard `keep` 拒绝 → incomplete；
* r3 误判：`xs=[-1]`, `keep=False`，`out+ = [0,1]`，`out- = [-1,0]`，guard `True`
  接受 → unsound。

### 3.3 `sort_channel`：条件“充分但不必需”

A 是 `xs = sorted(xs)`，下游两个 channel 分别是 `fn_1(xs) if use_left else xs[0]`
和 `fn_2(xs) if use_right else xs[-1]`。正确 guard（参考）：

```
pre or ((use_left or xs[0] == min(xs)) and (use_right or xs[-1] == max(xs)))
```

Qwen 的 observer **表达式**完全正确（`fn_1(...) if use_left else xs[0]` 等，
`BOUNDED`），但条件统一写成 `xs == sorted(xs)`：充分、非必要。只要 `use_left`
为真，channel 0 读的是最小值，排序与否都一样。

| 轮 | Qwen guard | verdict |
|---|---|---|
| 1 | `xs == sorted(xs)` | REFUTED，incomplete=7046 |
| 2 | `xs == xs_post` | INVALID（`_post` 不在 guard 词表） |
| 3 | `xs == sorted(xs)` | REFUTED，incomplete=7046 |

可复现揭示输入：`xs=[0,-1], pre=False, use_left=True, use_right=True`，
两侧输出都是 `[-1,0]`，guard 为假 → incomplete。正确条件只需要
`use_left or xs[0]==min(xs)`（源码行 33/34）。

这是“模型会写表达式、不会写**充要条件**”的典型：observer 表达式 2/2 通过，
条件 0/2 通过。组合器（B）也只能拿到这两个过强条件，因此 B 同样 incomplete。

### 3.4 `swap_channels`：缺一个析取项

A 交换 `a,b`；channel 0/1 是 `a+b`、`a*b`（恒不变），channel 2 是
`(a-b) if show_gap else 0`。正确 guard：`not show_gap or n == k`。

| 轮 | Qwen guard | verdict | 错误 |
|---|---|---|---|
| 1 | `a == b` | INVALID（local） | 词表 |
| 2 | `n == k` | REFUTED，incomplete=12 | 漏 `not show_gap` |
| 3 | `True` | REFUTED，unsound=12 | 过修 |

O0/O1 正确；O2 表达式 `0 if not show_gap else (a-b)` 在 P+/P− 两侧都忠实
（各自重算），但条件写成 `True`， invariance 检查立刻失败。模型从未写出
`not show_gap or n == k`（源码行 7,8）。

可复现输入：`n=-1, k=0, show_gap=False`（被遮蔽，`n==k` 拒绝 → incomplete）；
`n=-1, k=0, show_gap=True`（暴露，r3 的 `True` 接受 → unsound）。

### 3.5 `modulo_absorb`：fixed-point 条件方向反了

A 是 `total = total + 1`，然后 `if cap: total = total - total % 10`。正确的
吸收条件是 `cap and fn_0(xs) % 10 != 9`（+1 不跨十位）；参考 guard 只用一个
observer 条件即可（源码行 9,11,12）。

| 轮 | Qwen guard | verdict | 错误 |
|---|---|---|---|
| 1 | `cap` | REFUTED，unsound=47 | 只要 cap 就宣称遮蔽 |
| 2 | `cap and (total - total%10) if ...` | INVALID | 局部变量 |
| 3 | `cap and (...) == fn_0(xs)+1 if not cap else fn_0(xs)` | INVALID | 条件与分支类型混乱 |

U2 `fixed_point: not cap` 完全反了：not cap 时 A 必然改变 `total`。O0/O1 的
条件 `cap` / `not cap` 也太弱或错位。可复现输入：`xs=[-1], cap=True`，
P+ 输出 0，P− 输出 -10，guard `cap` 接受 → unsound。正确的 `%10 != 9`
在 3 轮中从未出现；模型在 `%10==9`、`%10==0`、`+1<=10` 之间摇摆。

### 3.6 `parity_snap`：关系对了，repair 把它改坏

正确关系：`even and sum(xs) % 2 == 0`（A +1 后被偶数舍入吸收）。
Qwen 第 1 轮就在 observer 中写出了这个条件：

| 轮 | Qwen guard | verdict |
|---|---|---|
| 1 | `even and sum(xs) % 2 == 0` | **BOUNDED exact** |
| 2 | `even and total_post % 2 == 0 or not even` | INVALID（`_post`） |
| 3 | `even and (sum%2==0 or sum%2==1) or not even` | REFUTED，unsound=127 |

可复现输入：`xs=[], even=False`，P+ 输出 1、P− 输出 0，r3 的 `or not even`
接受 → unsound。注意第 1 轮的正确解在修复前**会被解析器拒绝**（同 channel
有多个 observer 的合法写法），这是被修复的解析器 bug；但修复后最终仍然是
unsound，因为 repair 接受了一个更差的后续轮。H2 的独立重跑复现了同一现象
（r1 exact → 最终 unsound）。

### 3.7 `dedup_channel`：条件过强 + 布尔类型误用

正确 guard：`count(xs, xs[0] + 1) > 0`（追加的 `xs[0]+1` 已在列表中，
dedup 后长度不变）。

| 轮 | Qwen guard | verdict |
|---|---|---|
| 1 | `len(xs) == 0` | REFUTED，incomplete=100 |
| 2–3 | `len(xs)==0 or (pre and distinct(xs) and ...)` | INVALID（`distinct` 返回 int 当 bool 用） |

O0 表达式 `len(fn_0(xs))` 正确，但条件 `len(xs)==0` 过强（域里 len≥1，
等价于永假）。`distinct(xs)` 被当成布尔量使用是典型的语言类型错误；错误信息
会指出 sort，但模型没有改对。可复现输入：`xs=[0,1], pre=False`，
两侧输出都是 2，guard 拒绝 → incomplete。

### 3.8 其余三个（简短）

* **`alt_masking`**：guard `mode == 0 or mode == 1` 从第 1 轮就正确，3 轮保持；
  observer O0 第 1 轮误用 `v_post` 后修正。但 upstream 被写成
  `mode==0 or mode==1 / mode==2 / mode==3` 且 `condition=True`——把 guard 公式
  当成了入口事实，全部 REFUTED。这是“槽位误用”，对最终 guard 无害，却使
  `contract all-pass` 失败，也让组合器拿不到 fixed point。
* **`dict_slot`**：r1 `True`（unsound=40）→ r2/r3 `mode`，最终 exact。这说明
  guard 修复本身可以成功，但 observer O0 始终没写对（应为
  `7 if mode else d[0]`），契约 3/5。最终正确并不是因为关系对了。
* **`dead_flag`**：唯一 4/4 全通过；guard `True`，两个 observer 均为
  `len(xs)`, `len(xs)+1`。
* **H3 `clamp_absorb`**：所有方法都把极性写反。正确的
  `cap and sum(xs) >= 10` 被写成 `cap and sum+1 <= 10 or not cap`（MACE r2）、
  `cap or sum < 10`（fixed）、`sum+1 >= 10 if cap else True`（generic）等。
* **H3 `toggle_pair`**：正确 `flag or n == 0`。MACE 最终 `flag`
  （sound-incomplete），r2 修成 `flag or a_post == 0`（INVALID），r3 退回
  `flag`；两个基线最终写 `flag or a == 0`（local，INVALID）。模型知道
  “flag 打开时遮蔽”，但始终没想到 flag 关闭时 `n==0` 也可遮蔽。

### 3.9 跨案例发现

1. **A 的局部效应不是问题**：9/9 `target_effect` 通过，包括快照
   `value_post == 0`、`d_post[0] == 5` 这种看似容易写错的项。
2. **条件比表达式难**：`sort_channel` 的 observer 表达式 2/2 通过、条件 0/2；
   `swap_channels` 的 channel 0/1 表达式与条件都通过，channel 2 条件缺失；
   `dedup_channel` 表达式通过、条件永假。
3. **`upstream` 槽位被系统性误用**：模型把 guard 公式（`keep`、
   `mode==0 or mode==1`、`xs==sorted(xs)`）当作入口事实写进 upstream，
   `condition=True`，因此作为 universal fact 被 REFUTED。8/9 的 first-bad
   upstream 主要来自这里。单看 guard 无害，但它同时让组合器失去 fixed point。
4. **observer 快照语义**：observer 看到的是 A 之后的快照，必须用 plain 名字，
   且表达式要在 P+/P− 两侧都成立。`overwrite_channel` 的 O0/O1 正好在这里错。
5. **修复循环非单调**：A3 的 9 个运行中有 5 个最终比最好轮更差
   （dedup、modulo、overwrite、parity、swap），其中 1 个是从 exact 掉下来
   （parity）。H2 的 parity 同样 exact→unsound。`m5_report.py` 的
   best-round 对照：A3 最终 exact 3，最好轮 exact 4；H2 最终 2/3，最好轮 3/3。
6. **记法错误持续存在**（§2.4），且会被 last-write-wins 掩盖。

---

## 4. Phase 3：2×2 诊断

C/D 使用人工复核契约，**只用于诊断和能力上限检查，不是自动化系统的成绩**。
A/B 使用同一次 Qwen 运行的契约；B 只是把 guard 换成组合器的输出后重新验证，
不额外调用模型，因此 A/B 的差异完全来自 guard 生成方式。

### 4.1 开发集 6 个 fixture

| cell | 契约 | guard | typed | sound | complete | exact |
|---|---|---|---|---|---|---|
| A | Qwen | Qwen | 4/6 | 2/6 | 3/6 | 1/6 |
| B | Qwen | 组合器 | 3/6 | 3/6 | 1/6 | 1/6 |
| C | 复核 | Qwen | 6/6 | 4/6 | 3/6 | 3/6 |
| D | 复核 | 组合器 | 6/6 | 6/6 | 6/6 | 6/6 |

### 4.2 全部 9 个（含 held-out 第一批，仅作上限参考）

| cell | typed | sound | complete | exact |
|---|---|---|---|---|
| A | 7/9 | 4/9 | 6/9 | 3/9 |
| B | 5/9 | 5/9 | 3/9 | 3/9 |
| C | 9/9 | 6/9 | 6/9 | 5/9 |
| D | 9/9 | 9/9 | 9/9 | 9/9 |

### 4.3 解释

* **A vs B（同契约，换 guard）**：exact 相同（6 开发 1/6；9 个 3/9），但
  B 的 sound 更高（3/6 vs 2/6；5/9 vs 4/9），且**从不 unsound**。B 修好了
  `parity_snap`（O0 条件已验证，组合器直接用它），但丢掉了 `dict_slot`
  （Qwen 的 guard `mode` 对，契约里 channel 0 没有已验证 observer，组合器
  按设计拒绝给 guard）和 `swap/overwrite`（某些 channel 无已验证 observer）。
  → 确定性组合在“契约足够好”时更安全，但不能提高总体准确率。
* **C vs D（同复核契约，换 guard）**：3/6 vs 6/6（9 个 5/9 vs 9/9）。
  这是最强的单条证据：**关系正确时，组合器 100% 正确；自由写 guard 仍然丢一半**。
  C 的失败不是关系问题，而是布尔组合：`modulo_absorb` 漏了 `cap and` 且把
  exposed 条件当 masked；`sort_channel` 把两个 channel 的条件用错的 and/or 组合；
  `swap_channels` 只写 `not show_gap`，漏 `n==k`；`parity_snap` 漏 `even and`。
* **A vs C（同 guard 生成能力，换契约）**：1/6 vs 3/6（9 个 3/9 vs 5/9）。
  关系质量确实是限制项。
* 合起来：两个阶段都会漏，但**关系阶段漏得更多**（A→C 增益 +2/6，
  C→D 增益 +3/6；且 B 在 Qwen 契约下无法超过 A）。不存在“只要实现更强的
  关系传播就能解决”的证据，因为 C/D 的对比显示组合机制本身已经够强。

---

## 5. Phase 4：是否实现关系传播

**决定：不实现。** 理由：

1. 组合器在正确契约上 9/9，说明现有 fixed-point + per-channel observer 的
   组合语义已经足够；瓶颈不在“把关系沿数据流传播”这一层。
2. B 相比 A 没有准确率增益，且 B 的失败原因是**没有已验证 observer 覆盖某个
   channel**（overwrite、swap、modulo、dict），这属于关系发现失败；传播更多
   关系不会把错误条件变成正确条件。
3. 现有 `upstream` 关系大量是 `supporting` 且被 REFUTED（slot 误用），传播这些
   关系只会放大噪声。
4. 用户本轮明确要求不增加新功能；在诊断证明组合不是瓶颈后，增加传播会引入
   新的混杂，且没有可检验的收益假设。

---

## 6. Phase 5：泛化与 token 匹配基线

### 6.1 开发集（6 个原始 fixture）

| 方法 | cases | typed | sound | complete | exact | contract all-pass | attribution | tokens | s |
|---|---|---|---|---|---|---|---|---|---|
| MACE A（Qwen 契约 + Qwen guard） | 6 | 4 | 2 | 3 | 1 | 0 | 19/30 | 73,694 | 388 |
| MACE B（Qwen 契约 + 组合） | 6 | 3 | 3 | 1 | 1 | 0 | 19/30 | 73,694 | 388 |
| direct，3 轮 | 6 | 6 | 4 | 3 | 3 | 0 | n/a | 13,450 | 61 |
| generic，3 轮 | 6 | 4 | 1 | 3 | 1 | 0 | n/a | 20,113 | 143 |
| fixed，3 轮 | 6 | 5 | 3 | 4 | 2 | 0 | n/a | 15,775 | 68 |
| direct，12 轮（token 匹配或更高） | 6 | 6 | 3 | 3 | 3 | 0 | n/a | 109,206 | 258 |
| C 复核契约 + Qwen guard（仅诊断） | 6 | 6 | 4 | 3 | 3 | 6 | 19/19 | 10,345 | 49 |
| D 复核契约 + 组合（仅诊断） | 6 | 6 | 6 | 6 | 6 | 6 | 19/19 | 10,345 | 49 |

全部 9 个 fixture 的合计：

| 方法 | exact | tokens | s |
|---|---|---|---|
| MACE A | 3/9 | 99,802 | 542 |
| MACE B | 3/9 | 99,802 | 542 |
| direct 3 轮 | 5/9 | 17,566 | 81 |
| fixed 3 轮 | 4/9 | 20,245 | 85 |
| generic 3 轮 | 3/9 | 24,697 | 186 |
| direct 12 轮 | 5/9 | 137,009 | 323 |

### 6.2 held-out 第一批（3 个；曾用于解析器修复诊断）

| 方法 | typed | sound | complete | exact | tokens | s |
|---|---|---|---|---|---|---|
| MACE（修复前那批运行） | 2/3 | 2/3 | 2/3 | 2/3 | 21,482 | 150 |
| direct 3 轮（修复前） | 3/3 | 2/3 | 2/3 | 2/3 | 4,117 | 19 |
| generic 3 轮（修复前） | 2/3 | 2/3 | 2/3 | 2/3 | 4,636 | 45 |
| fixed 3 轮（修复前） | 2/3 | 2/3 | 2/3 | 2/3 | 4,292 | 17 |
| MACE A（修复后） | 3/3 | 2/3 | 3/3 | 2/3 | 26,316 | 156 |
| MACE B（修复后） | 2/3 | 2/3 | 2/3 | 2/3 | 26,316 | 156 |
| C（仅诊断） | 3/3 | 2/3 | 3/3 | 2/3 | 3,785 | 13 |
| D（仅诊断） | 3/3 | 3/3 | 3/3 | 3/3 | 3,785 | 13 |

三个 fixture 中 dead_flag、dict_slot 所有方法都对；parity_snap 上所有自动化方法
（A/B 与三条基线）最终都不对（MACE 在 r1 精确，但 repair 掉下来）。D 用复核契约
能把 parity 做对，但那是诊断上限，不是系统能力。因此这一批上的“2/3”没有区分度。

### 6.3 held-out 第二批（2 个，真正独立）

| 方法 | typed | sound | complete | exact | tokens | s |
|---|---|---|---|---|---|---|
| MACE A | 1/2 | 1/2 | 0/2 | **0/2** | 28,502 | 161 |
| direct 3 轮 | 2/2 | 0/2 | 0/2 | **0/2** | 4,680 | 22 |
| generic 3 轮 | 1/2 | 0/2 | 1/2 | **0/2** | 5,997 | 44 |
| fixed 3 轮 | 1/2 | 0/2 | 1/2 | **0/2** | 5,826 | 16 |

所有方法 0/2。MACE 的代价是 direct 的 6.1 倍 tokens、7.4 倍模型时间，
却没有准确率优势。失败形态高度一致：`clamp_absorb` 的极性全部写反；
`toggle_pair` 的 `flag or n == 0` 无人写出，且模型反复把 A 前参数 `n` 和
A 后局部 `a`/`a_post` 混用。

### 6.4 best-round 反事实与回归

`scripts/m5_report.py` 用“最好轮”重排每个 run：

| 运行 | 最终 exact | 最好轮 exact | exact 流失 | 备注 |
|---|---|---|---|---|
| A3 | 3/9 | 4/9 | 1（parity） | 另有 4 例从 sound→unsound/INVALID |
| H2 | 2/3 | 3/3 | 1（parity） | — |
| base 3 轮 | 5/9 | 5/9 | 0 | 也有 sound→unsound，但未损失 exact |
| T 12 轮 | 5/9 | 5/9 | 0 | 同上 |

即使采用单调修复（保留最好轮），9 个 fixture 上 MACE 也只有 4/9，仍低于 direct 的 5/9；
但 held-out 第一批会从 2/3 升到 3/3。单调修复是**必要但不充分**的工程修复。

---

## 7. 五个问题的直接回答

**Q1. 主要瓶颈是什么？**
关系/条件生成，具体按频率排序：
(a) observer 条件“充分但不必需”（sort、dedup、swap）；
(b) 把 A 前的局部变量当作 A 后快照读取（overwrite）；
(c) fixed-point 条件方向错误或缺失（modulo、sort 的 `pre`、swap 的 channel 2）；
(d) `upstream` 槽位误用（alt、modulo、sort、overwrite、parity）；
(e) 修复循环非单调（parity）。
`target_effect` 不是瓶颈（9/9 通过）。

**Q2. 确定性组合是否比 Qwen 自由写 guard 更准？**
同一份 Qwen 契约：不更准（开发 1/6 vs 1/6；9 个 3/9 vs 3/9），但更安全
（从不 unsound，sound 更高）。给定复核契约：显著更准（C 3/6 vs D 6/6；
9 个 5/9 vs 9/9）。所以答案是“关系正确时是，关系错误时不能”。

**Q3. Qwen 自动发现了哪些正确关系？**
* 完整正确的契约：只有 `dead_flag`（4/4）。
* 决定性的正确关系：`parity_snap` 的 observer 条件
  `even and sum(xs) % 2 == 0`。
* 部分正确：`alt_masking` 的 observer 条件；`sort_channel` 的 observer 表达式；
  `swap_channels` 的 channel 0/1 表达式与条件；`dedup_channel` 的 observer
  表达式（条件过强）；`dict_slot` 的 channel 1 observer（guard 另由修复得到）。
* 完全没有决定性正确关系：`overwrite_channel`、`modulo_absorb`；
  `clamp_absorb`、`toggle_pair` 也没有。

**Q4. 哪些正确结果只是工程 bug 修复带来的？**
没有一例最终 exact 是。解析器放宽只把 `parity_snap` 的 r1 精确解从“被拒绝”
变成“被接受”，最终仍被 repair 改坏；A 与 A3 的最终 exact 都是 3/9，且是同一组
（alt、dead、dict）。组合器“缺 channel 不给 guard”只提高 soundness；
`min/max` 变参只修参考契约；`cells` 的 sound/complete 拆分只影响测量。
因此 M5 的工程修复没有产生新的最终正确案例。

**Q5. 有没有证据支持继续做 MACE 算法研究？**
按当前形态没有：
* 开发集 MACE 1/6 vs direct 3/6；9 个 3/9 vs 5/9；
* 同 token 预算或更高的 12 轮 direct 仍是 3/6（109k tokens）和 5/9（137k）；
* 独立 held-out 第二批所有方法 0/2，MACE 贵 6–7 倍；
* 2×2 显示“正确关系 → 组合 → 精确”可行（D 9/9），但模型给不出足够多的
  正确条件，且 repair 会破坏已经正确的中间解。

若仍要继续，证据支持的只有一条预注册的窄路线：
**条件归纳（observer/fixed-point 的充要条件）+ 单调修复**，用新的 held-out
fixture 评估；如果它仍然打不过同预算的 direct 基线，就应停止这条路线，而不是
继续增加 Agent 或契约字段。当前数据不支持“加更多结构会更好”的假设。

---

## 8. 局限

1. **样本量与随机性**：6 个开发 + 3 个半 held-out + 2 个独立 held-out；
   单模型、单 seed、temperature 0。差异不能做显著性声明，只能作为方向性证据。
2. **held-out 第一批不干净**：`parity_snap` 的失败直接触发了重复 observer 的
   解析器修复，因此这 3 个 fixture 已被用于开发决策。真正独立的只有第二批
   2 个，且它们全部失败。
3. **预算混杂**：旧 full MACE 是 4 轮，新运行 3 轮；A vs A3 是受控的（同 prompt、
   同预算，只差解析器），但旧 2/6 与新 3/9 不可直接相减。
4. **指标是有限域上的**：`BOUNDED` 不是 `PROVEN`；域由 fixture 作者选择，
   存在构造效度风险。
5. **attribution 是行级重叠**：不能证明引用行逻辑上支持该关系；基线没有契约，
   该列记 n/a。C/D 的 attribution 100% 是人工契约自带的，无诊断价值。
6. **C/D 不是系统成绩**：复核契约进入 prompt，正是自动化协议禁止的做法。
7. **语言覆盖有限**：bool/int/list[int]/dict[int,int]；不支持循环内的 A、
   多目标、复杂对象。held-out 第二批的失败有一部分是语言/词表层面的
   （`a_post`、局部 `a`、`min(total+1,10)`），不完全是语义推理失败。
8. **单一模型**：只测了 qwen2.5-coder:32b；不能外推到更强模型或闭源模型。
9. **工程时间线**：变参 `min/max` 在所有模型运行之后才加入；C 的契约 prompt
   使用复核契约，C/D 的 token 数不能与 A/B 直接比较成本。

---

## 9. 复现

```bash
# 全量测试（126 项）
python -m pytest -q

# 2x2 表（只读存储的运行，无模型调用）
python -m mace.cli cells --runs m5/A3 --json m5/cells_A3.json
python -m mace.cli cells --runs m5/base --json m5/cells_base.json

# 分阶段诊断（first bad stage、INVALID vs 语义错误）
python -m mace.cli diagnose --runs m5/A3 --json m5/diag_A3.json --stages

# 最终轮 vs 最好轮、回归计数
python scripts/m5_report.py m5/A3 m5/H2 m5/base m5/T

# 汇总表（本报告 §6 的表格）
python scripts/m5_tables.py m5/tables.md
```

重新跑模型（AutoDL，localhost 绑定）：

```bash
bash scripts/run_m5_rerun.sh       # A3 + H2 + H3
bash scripts/run_m5_baselines_dev.sh  # 9 fixture 的 direct/generic/fixed
```

产物：

* `m5/A3/…/*.json`：每个 fixture 每轮的 raw response、bundle、逐关系 verdict、
  counterexample、token 与时间；
* `m5/base/`、`m5/T/`、`m5/H/`、`m5/H2/`、`m5/H3/`：基线与 held-out 运行；
* `m5/cells_*.json`、`m5/diag_*.json`、`m5/tables.md`：本报告所有表的机器可读
  来源；
* `experiments/hidden/*_reference.json`：人工复核契约，只用于 CPU 自检和评分，
  从未进入 prompt。

通过的 verdict 是有限域上的 `BOUNDED`；失败的是 `REFUTED`/`INVALID`。本工作
没有、也不会把有界等价标成 `PROVEN`。
