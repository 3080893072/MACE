# M6 决策报告：条件归纳瓶颈验证与算法决策

本报告对应 M6 任务。范围严格限定为：不新增 Agent、不扩大 Prompt 反馈字段、不重新设计
架构；只做冻结、非单调修复回放、Symbolic Engine 独立评测、最小条件归纳实验，以及在
此基础上的研究决策。所有数字来自仓库中的实际运行记录（`m6/`、`m5/`），没有任何预先
编写或事后补造的结果。

**证据等级**：本文的“精确 / 正确”一律指在声明的有限输入域上与真实删除结果逐输入
相等，证据状态为 `BOUNDED`（穷举该域）或 `TESTED`（采样），**从不输出 `PROVEN`**。
人工参考契约（`experiments/hidden/*_reference.json`）只用于 CPU 自检、计分和 C/D
诊断，从未进入任何自动 Prompt 或归纳器。

---

## 0. 结论（先回答五个问题）

1. **非单调修复回放能挽回的真实失败很小：77 个历史运行槽位中只有 2 个（2.6%）**
   出现“后面一轮把前面通过验证的 guard 覆盖成错误 guard”。在线保留策略把精确数从
   35/77 提到 37/77（+2 例），达到了事后 best-ever 上限的 37/77；但这 2 例是同一个
   fixture（`parity_snap`）的两次运行，实际只有一种失败模式；M5 所说 “5/9 运行比最好轮
   更差”里其余 4 例在 fit 上从未 exact，不属于该策略的可救范围。M5 中 8/9 的首个失败在
   upstream 关系，保留策略对此无能为力。
2. **在同一 11 个 fixture 上，Pure Symbolic 比原始 Full MACE 更准确、更便宜。**
   Symbolic+helper summaries 为 11/11 精确；Pure Symbolic（禁用 helper 摘要）为 7/11
   精确、4/11 明确 `UNKNOWN`；Full MACE 3/11；Direct Qwen 5/11。MACE 的 token 消耗是
   Direct 的 5.97 倍（141,081 vs 23,626），墙钟 6.9 倍（704.5 s vs 102.3 s）。纯符号
   方法 0 token、总计约 0.016 s。**但这是程序分析的收益，不能算作 LLM+MACE 的创新。**
3. **条件归纳在“A 的 mask guard”这一子义务上确实独立优于 Direct Qwen：10/11 精确
   vs 5/11，且 0 token。** 这个提升不是 token 换来的，也不是修复策略带来的；但它依赖
   人工设计的受限谓词模板库（dev 上 generic 池 2/6，full 池 6/6），且只覆盖 M5 失败的
   下游一半——upstream 关系归纳没有被这项机制触及。
4. **改进不能归因于 LLM 的语义发现。** Symbolic 的改进来自源码级符号执行 + 人工编写的
   helper 摘要（真实但属于程序分析）；归纳器的改进来自谓词模板库 + 有界搜索（generic
   消融直接证明模板是主因）。保留策略只贡献 2 例。没有一项证据支持“模型通过语义推理
   掌握了条件”这一说法。
5. **不建议继续把 Full MACE 作为 ICPC Research Track 的主要算法贡献。建议 STOP。**
   在相同 fixture 上它不如同预算 Direct Qwen，更不如 0 token 的符号方法；其唯一可辩护
   的组件是被验证器约束的符号/归纳管线，而这本身不是 LLM+MACE 的贡献。继续无目标的
   Prompt 调优不会改变这个结论。建议把论文定位改为“有界验证 + 反例驱动的条件学习”，
   把 LLM 作为被对照的失败基线，而不是主方法。

---

## 1. 冻结与实验边界

### 1.1 版本冻结

| 项目 | 值 |
|---|---|
| M5 冻结提交 | `b4b0a90`，tag `m5-freeze` |
| M6 实现冻结提交 | `7599e20`，tag `m6-induct-freeze` |
| M6 分支 | `m6`（`master` 与 `m5-freeze` 未改动） |
| held-out 运行时记录的实现哈希 | `7b514fda833186ebff50a87c0ce1b9a616819136a56e5739212dc99106875b54` |
| held-out 运行时记录的 git HEAD | `7599e20bb0faf06ad64d385b0f02e1b8f8099829` |
| 测试 | 139 项全部通过（冻结前） |

`m5/` 下的历史运行记录没有修改。M6 的所有新日志在 `m6/` 下。

### 1.2 数据划分

* fit / eval：按 `SHA-256(seed + repr(case))` 的奇偶对半划分，seed `20261030`，
  两者不相交且覆盖整个声明域。
* learn / tune：在 fit 内部再用 seed `20261031` 对半划分。
* 归纳器的谓词选择、子句学习和反例修复只使用 learn/tune/fit；eval 只用于最后计分。
  eval 标签从未参与候选选择。
* fixture 划分保持 M5 不变：dev6 = `alt_masking, dedup_channel, modulo_absorb,
  overwrite_channel, sort_channel, swap_channels`；held1 = `dead_flag, dict_slot,
  parity_snap`；held2 = `clamp_absorb, toggle_pair`。

### 1.3 关于“独立 Symbolic Engine 补丁”

任务说明中提到可能存在一个独立的 “Step 5 symbolic relation derivation patch”。实际
检查了全部分支、tag 和提交历史（`git log --all`，仅 `b4b0a90` 与 `7599e20`），
**仓库中不存在这样的独立补丁**。因此第 3 节的 Symbolic Engine 是在 M6 分支上重新实现
的（`mace/symbolic.py`），不是对第三方实现的复评。这一点必须在论文中如实说明：它削弱
了“独立实现交叉验证”的强度，但不影响“符号方法本身能做什么”的结论。

### 1.4 未做的事（按任务要求）

* 没有新增 Agent，没有扩大 Prompt 反馈字段。
* 没有枚举 B 的删除子集；归纳只回答“把 A 换成 `pass` 是否可观测”。
* 没有把人工参考 guard 输入合成器。
* 没有把有限域穷举通过写成 `PROVEN`。
* M6 期间没有新的模型调用；Qwen 行全部复用 M5 的存档运行。

---

## 2. 非单调修复能挽回多少实际失败？

### 2.1 方法

回放 M5 已有的多轮 guard 生成记录（`m6/repair.py`），对每一轮 guard 在 fit 半区
重新判定是否“fit-valid”，然后在互不相交的 eval 半区计分。比较四种策略：

* **First-Round**：第一轮 guard。
* **Final-Round**：最后一轮 guard（M5 现行 last-write-wins）。
* **Online Best-Validated**：在线保留策略。当前 incumbent 在 fit 上通过验证时，后续
  INVALID 候选不能覆盖它；只有两种情况允许替换：还没有 incumbent，或 incumbent 被
  新发现的 fit 反例撤销（revocation）。选择过程不看 eval。
* **Best-Ever**：事后从所有轮次里挑 eval 最好的 guard，**使用 eval 标签，仅作诊断
  上限**，不是可部署策略。

### 2.2 结果（77 个 (method, fixture) 运行槽位）

| 策略 | eval 精确数 | 说明 |
|---|---|---|
| First-Round | 26/77 | 只取第一轮 |
| Final-Round（M5 现状） | 35/77 | 最后一轮覆盖 |
| Online Best-Validated（本修复） | **37/77** | 不替换 fit-valid incumbent |
| Best-Ever（诊断上限，用 eval 选） | 37/77 | 在线策略已达到该上限 |

发生“final 比早先 fit-valid guard 更差”的槽位只有 2 个：

| method | fixture | fit 中有效轮数 | final eval | online eval |
|---|---|---|---|---|
| `A3/qwen` | `parity_snap` | 1 | 错（unsound=62） | 精确 |
| `H2/qwen` | `parity_snap` | 1 | 错（unsound=41） | 精确 |

### 2.3 解读

* 工程修复是**正确且有效**的：它精确消除了观测到的非单调覆盖，且不需要 eval 标签。
* 但收益只有 **+2/77（+2.6 个百分点）**，而且两次都是 `parity_snap` 的重复运行，
  实际只恢复了一种失败模式。
* 与 M5 报告的 “A3 有 5 个运行最终比最好轮更差” 对齐：那 5 个里只有 `parity` 一例是
  “fit-exact 的 guard 被后续覆盖”；另外 4 例（dedup、modulo、overwrite、swap）的早期
  最好轮在 fit 上本来就不是 exact，保留策略按定义不会把它们当作 incumbent，因此**这 4 例
  不是本修复能救的对象**。M6 的 77 槽位回放确认了这一点。
* 策略的 valid 判据是 fit **exact**。若放宽成 fit-sound，可能保留更多“不精确但不
  unsound”的 guard，但那是另一个策略，本次冻结未验证，不能算进收益。
* M5 的核心失败（8/9 首个失败在 upstream 关系/条件生成）在 guard 已经生成错误的前提下
  发生，保留策略无法凭空产生正确关系，因此**不能指望它拯救整体准确率**。
* 结论：把该策略作为工程正确性修复保留（它没有副作用），但不应把它写成准确率贡献。

---

## 3. 原始 MACE 与 Pure Symbolic：相同 fixture 上谁更准确？

### 3.1 设置

`scripts/m6_symbolic.py` 在所有 11 个 fixture 上，把每个 guard 在完整声明域上重新
检查（`BOUNDED`）。四个被比较的对象：

* **Direct Qwen**：M5 存档的 direct guard prompt 运行。
* **Full MACE (A)**：M5 存档的 A 配置（Qwen 契约 + Qwen guard）。
* **Pure Symbolic**：源码级符号执行，禁用 helper 摘要。遇到无法建模的 helper 时返回
  `UNKNOWN`，而不是猜。
* **Symbolic + summaries**：允许人工编写的 helper 摘要（sum、min/max fold、dedup、
  insertion sort 等）。

### 3.2 汇总（11 个 fixture）

| method | 精确 | sound | complete | UNKNOWN | tokens | 墙钟 s |
|---|---|---|---|---|---|---|
| Direct Qwen | 5/11 | 6 | 5 | 0 | 23,626 | 102.3 |
| Full MACE (A) | 3/11 | 5 | 6 | 0 | 141,081 | 704.5 |
| Pure Symbolic | 7/11 | 7 | 7 | 4 | **0** | **0.016** |
| Symbolic + summaries | **11/11** | 11 | 11 | 0 | **0** | **0.016** |

分集合：

| 集合 | Direct | Full MACE | Pure Symbolic | Symbolic+summaries |
|---|---|---|---|---|
| dev6 | 3/6 | 1/6 | 2/6（4 UNKNOWN） | 6/6 |
| held1 | 2/3 | 2/3 | 3/3 | 3/3 |
| held2 | 0/2 | 0/2 | 2/2 | 2/2 |

### 3.3 典型对照

| fixture | Direct Qwen | Full MACE | Symbolic+summaries |
|---|---|---|---|
| `dedup_channel` | 精确 | `INVALID`（引用了 helper 调用） | 精确：`count(xs, xs[0] + 1) > 0` |
| `modulo_absorb` | `REFUTED`（unsound 47） | `INVALID` | 精确：`cap and sum(xs) % 10 != 9` |
| `overwrite_channel` | 精确 | `REFUTED`（`keep or not keep`，unsound 28） | 精确：`keep or sum(xs) == 0` |
| `sort_channel` | `REFUTED`（unsound 1134） | `REFUTED`（unsound 0，incomplete 7046） | 精确（88 节点，8 条路径） |
| `swap_channels` | `REFUTED`（incomplete 4） | `REFUTED`（`True`，unsound 12） | 精确：`not show_gap or k == n` |
| `parity_snap` | `REFUTED` | `REFUTED` | 精确：`even and sum(xs) % 2 == 0` |
| `clamp_absorb` | `REFUTED` | `INVALID` | 精确：`cap and sum(xs) >= 10` |
| `toggle_pair` | `REFUTED` | `REFUTED` | 精确：`flag or n == 0` |

### 3.4 成本与解释能力

* **Token**：Direct 23,626；MACE 141,081（5.97×）；符号方法 0。
* **墙钟**：Direct 102.3 s；MACE 704.5 s（6.9×）；符号方法总计 0.016 s。
* **源码覆盖**：符号引擎报告每个 fixture 的到达行/路径数与源码语句覆盖率。例如
  `dedup_channel` 9/11、`modulo_absorb` 9/11、`sort_channel` 25/27；Pure Symbolic 在
  `dedup_channel` 只覆盖 1/11（无法进入 helper）。MACE 的“解释”是 free-text
  relrationale；符号方法的解释是可直接对照源码行的 channel rule 和路径。
* **诚实性**：Pure Symbolic 的 4 个 `UNKNOWN` 全部来自 helper 摘要缺失（`dedup`、
  `modulo`、`overwrite`、`sort`），不是错误答案。它“知道自己不知道”；MACE 在这 4 个
  用例上都给出了错误 guard。

### 3.5 结论

在相同 fixture、相同验证器下，**Pure Symbolic 明显优于 Full MACE**（7/11 vs 3/11，
0 token vs 141k）。但必须把结论限定为：这是一个**源码级程序分析引擎**在自己的适用
范围内打败了一个通用 LLM 流水线。它证明的是“这个子问题应该交给符号方法”，而不是
“LLM + MACE 的语义契约有独立价值”。论文不得把符号方法的成功计入 LLM+MACE 的创新。

---

## 4. 条件归纳是否比直接 Qwen 有独立提升？

### 4.1 方法与范围

`mace/induct.py` 针对 A 的局部义务：把 A 替换成 `pass`，看返回通道是否改变。

1. 在声明域上执行配对程序，得到每个输入的 `(masked, pre, post, effect)` 见证。
2. 用类型化受限谓词语言构造候选（bool 恒等、int 比较/取模、列表长度/和/计数/去重/
   有序极值、字典值求和等）。full 池额外包含列表内容模板。
3. 用 bitset 在 learn 半区学习覆盖正例的 DNF 子句，负例不覆盖；再做单文字规范化和
   吸收化简。
4. 用 tune 半区的假接受/假拒绝触发反例修复：只对反例收紧或扩展，不删除 B 的任意子集。
5. 在 fit 上判定充分性（sound）与必要性（complete）；在 eval 上只计分。
6. 用验证器在完整声明域上复核，状态只写 `BOUNDED`。

### 4.2 开发集结果（冻结前，`m6/induct_dev.md`）

| method | 精确 | sound | complete | tokens | 墙钟 s |
|---|---|---|---|---|---|
| Direct Qwen | 3/6 | 4 | 3 | 14,222 | 61.48 |
| Full MACE | 1/6 | 2 | 3 | 80,507 | 387.69 |
| 归纳 full，充分方向 | **6/6** | 6 | 6 | 0 | 23.45 |
| 归纳 full，必要方向 | 0/6 | 0 | 0 | 0 | 23.45 |
| 归纳 generic，充分方向 | 2/6 | 5 | 2 | 0 | 3.59 |
| 归纳 generic，必要方向 | 0/6 | 0 | 3 | 0 | 3.59 |

full 池学到的 guard：

| fixture | guard | 节点 | eval 类型 |
|---|---|---|---|
| `alt_masking` | `mode <= 1` | 5 | exact |
| `dedup_channel` | `(count(xs, xs[0] + 1) > 0) if len(xs) > 0 else False` | 26 | exact |
| `modulo_absorb` | `(cap) and (sum(xs) % 10 != 9)` | 15 | exact |
| `overwrite_channel` | `(keep) or (sum(xs) == 0)` | 12 | exact |
| `sort_channel` | 5 条子句的 DNF（极值条件 + 标志组合） | 134 | exact |
| `swap_channels` | `(n == k) or (not show_gap)` | 12 | exact |

generic 池（去掉列表内容模板）只有 2/6 精确：`alt_masking`、`swap_channels`。这说明
**提升主要来自列表内容模板**（`count`、`sum`、`min/max` 的比较），而不是通用的
反例搜索。`dedup`/`modulo`/`overwrite` 的 generic 结果分别是 `False`、`len(xs) == 0`
（既非充分也非必要）、`keep`（充分但不必要）。

### 4.3 保留集结果（冻结后只评测一次）

冻结提交 `7599e20`（tag `m6-induct-freeze`），实现哈希
`7b514fda…`，full 池，held1+held2 一次性运行，总计 1.77 s：

| 集合 | Direct Qwen | Full MACE | 归纳（充分） | 归纳（必要） |
|---|---|---|---|---|
| held1 | 2/3 | 2/3 | 2/3 | 0/3 |
| held2 | 0/2 | 0/2 | **2/2** | 0/2 |
| 合计 5 | 2/5 | 2/5 | **4/5** | 0/5 |

逐例：

| fixture | 归纳 guard | 状态 | 结果 | Direct Qwen |
|---|---|---|---|---|
| `dead_flag` | `len(xs) > 0` | `BOUNDED` | sound 但 incomplete（1 个假拒绝） | 精确 `True` |
| `dict_slot` | `mode` | `BOUNDED` | 精确 | 精确 |
| `parity_snap` | `(even) and (sum(xs) % 2 != 1)` | `BOUNDED` | 精确 | `REFUTED` |
| `clamp_absorb` | `(cap) and (sum(xs) >= 10)` | `BOUNDED` | 精确（1 次反例修复） | `REFUTED` |
| `toggle_pair` | `(flag) or (n < 1)` | `BOUNDED` | 精确（1 次反例修复） | `REFUTED` |

合计：归纳 **10/11 精确**（dev 6/6 + held 4/5），0 token；Direct Qwen 5/11，23,626
token；Full MACE 3/11，141,081 token。

### 4.4 失败与限制（必须写进论文）

1. **必要方向全面失败**：dev 0/6、held 0/5。学“未掩盖”的 DNF 再取反后，在完整域上
   全部 `REFUTED`，且表达式爆炸（`parity_snap` 1216 节点、`dead_flag` 165 节点）。
   归纳器目前只能可靠给出**充分条件**，不能可靠给出精确等价，也不能可靠给出必要条件。
2. **`dead_flag` 的 held-out 失败**：该 fixture 的 40 个见证全部 masked（没有反例）。
   learn 半区没有负例，学习器从点式子句泛化出 `len(xs) > 0`，而不是 `True`；在域上
   sound 但不 complete。这是“需要双极性样本”的真实限制，不是调参能解决的。
3. **模板依赖**：full 池包含人工设计的列表内容模板，generic 消融从 6/6 掉到 2/6。
   因此不能说“系统自主发现了条件”；更准确的说法是“在受限谓词语言中做了有界搜索，
   模板库是领域知识”。
4. **范围只有下游一半**：归纳只处理 A 的 mask guard。M5 的 8/9 首个失败在 upstream
   关系（fixed-point 条件、observer 条件），本机制没有触及，不能据此宣称解决了 M5
   的瓶颈。
5. **fit/eval 同域**：两半来自同一个声明有限域，只是互不相交。它证明的是域内泛化，
   不是跨分布泛化。
6. **`sort_channel` 的见证数 10,912**，占 dev 归纳总时间的绝大部分；谓词池对列表
   内容的枚举在更大域上会膨胀，成本不能忽略。

---

## 5. 成本汇总

| 方法 | 11 个 fixture 的 token | 墙钟 | 备注 |
|---|---|---|---|
| Direct Qwen | 23,626 | 102.3 s | 单模型、单 seed、temperature 0 |
| Full MACE | 141,081 | 704.5 s | 5.97× token、6.9× 墙钟 |
| Pure Symbolic | 0 | 0.012 s | 4/11 返回 UNKNOWN |
| Symbolic + summaries | 0 | 0.016 s | 11/11，但摘要由人编写 |
| 归纳（full，充分） | 0 | 25.2 s（dev 23.45 + held 1.77） | 10/11；必要方向 0/11 |

MACE 的成本不是主要问题——即使不计成本，它的准确率也低于 Direct Qwen 和符号方法。
成本问题只是让“继续投入”更不划算。

---

## 6. 有效性威胁

* **证据状态**：所有“精确”都是有限域穷举，不是定理证明。域外的行为未知。
* **held1 不是干净保留集**：M5 期间它被用于诊断 parser bug（见 M5 报告），只有 held2
  是真正未触碰的。held2 只有 2 个 fixture，统计功效很低。
* **回放泄漏**：第 2 节的回放使用 M5 存档日志，eval 半区与 fit 半区来自同一有限域，
  不是真正的新输入；它能证明策略机制正确，不能证明跨分布收益。
* **单模型、单 seed、temperature 0**：所有 Qwen 结论只对 `qwen2.5-coder:32b` 成立。
* **无独立符号补丁**：第 3 节的符号引擎是 M6 新实现，不是第三方交叉验证。
* **C/D 只是诊断上限**：人工复核契约的 5/9、9/9 不能作为系统准确率报告。
* **模板与摘要的人工成分**：helper 摘要和 full 谓词池都含人工领域知识；论文必须披露，
  否则会把“人工模板”误读成“模型语义发现”。

---

## 7. 研究决策

### 7.1 是否继续以 Full MACE 为主要算法贡献？

**不建议。建议 STOP。**

理由是直接的、可复现的：

* 在 11 个相同 fixture 上，Full MACE 3/11 精确，低于 Direct Qwen 的 5/11，更低于
  Pure Symbolic 的 7/11 和 Symbolic+summaries 的 11/11。
* MACE 花 5.97× token、6.9× 墙钟，却没有换来准确率；在唯一真正保留的 held2 上，
  MACE 与 Direct 都是 0/2，符号方法 2/2。
* M5 已经定位瓶颈在 upstream 关系/条件归纳；M6 的归纳实验只覆盖 mask guard，且依赖
  人工模板。继续在现有 Prompt 上做无目标调优，不会改变“关系生成本身不可靠”这一根因。
* 唯一稳定有效的是验证器约束下的符号执行和反例驱动学习；它们不是 LLM+MACE 的贡献，
  不能用来支撑原论文主张。

### 7.2 建议保留与不建议保留的内容

**保留（作为工具/工程贡献）**：

* 有界验证器和 `BOUNDED/TESTED/REFUTED/INVALID/UNKNOWN` 的证据分级；
* 源码级符号执行 + 显式 helper 摘要（适用时 11/11 精确，0 token）；
* 反例驱动的受限条件归纳（充分方向 10/11，0 token）；
* 在线 guard 保留策略（正确性修复，+2/77）。

**不建议保留为“主算法”**：

* “LLM 生成语义契约 → 组合器 → guard”的整条链路；
* 以 MACE 为主贡献的论文叙事；
* 任何“模型学会了条件归纳”的表述。

### 7.3 如果还要写论文，诚实的定位

可行的定位是**负结果 + 方法边界**：在条件掩盖问题上，32B 代码模型的关系/条件归纳
不可靠；把可判定的子问题交给有界符号方法，可以在 0 token 下达到 11/11（有摘要）或
10/11（归纳），而 LLM 流水线只有 5/11。贡献是“什么时候不该用 LLM”和“验证器如何约束
候选”，不是“LLM+MACE 更强”。这比继续调 Prompt 更可辩护，也更符合已有证据。

### 7.4 停止条件

如果后续仍要尝试 LLM 路线，必须先满足：在 held2 这种真正未触碰的集合上，MACE 严格
超过同预算 Direct Qwen，并且提升不能由模板、token 或工程修复解释。在现有证据下，
该条件不成立；本报告建议不再投入。

---

## 8. 复现命令

```bash
cd /d/4_____/mace_qwen_pilot_kit

# 环境与测试
python -m pytest -q                      # 139 passed（M6 冻结前）

# 阶段 2：非单调修复回放（使用 M5 存档日志，无模型调用）
python scripts/m6_repair.py --json m6/repair.json --md m6/repair.md

# 阶段 3：符号引擎与存档 Qwen/MACE 对比（无模型调用）
python scripts/m6_symbolic.py --json m6/symbolic.json --md m6/symbolic.md

# 阶段 4a：开发集诊断（冻结前）
python scripts/m6_induct.py --sets dev6 --pool both \
    --json m6/induct_dev.json --md m6/induct_dev.md

# 阶段 4b：保留集一次性评测（冻结后；本次只运行一次）
python scripts/m6_induct.py --sets held1,held2 --pool full \
    --json m6/induct_held.json --md m6/induct_held.md

# 版本核对
git rev-parse HEAD          # 7599e20bb0faf06ad64d385b0f02e1b8f8099829
git tag --points-at HEAD    # m6-induct-freeze
```

`m6/induct_held.md` 顶部记录了实现 SHA-256 与 git HEAD，可与 `m6-induct-freeze`
逐位核对。
