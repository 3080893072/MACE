# M2 / M3 / M4 报告：合同引擎、传播与归因、未见程序

日期：2026-10-30。数据来自 `/root/m2_20261030_090315`（v1）、
`/root/m2_20261030_090957`（v2）、`/root/m4_20261030_091725`（14B 未见 fixture）、
`/root/m4_20261030_092722`（7B 未见 fixture）。全部用
`python -m mace.cli summarize --runs <dir>` 可复算。

---

## M2 合同引擎

**受限类型语言**（`mace/terms.py`）。模型输出的表达式用 `ast.parse` 解析后逐节点
走白名单，从不 `eval`。支持的排序只有 `bool / int / list[int] / dict[int,int]`；
支持算术、比较、`and/or/not`、条件表达式、下标、`len/min/max/sum/abs/sorted/vals/
distinct/count`，以及对已声明签名的程序函数的调用。白名单之外一律 `TermError`，
关系状态记为 `INVALID`，不会被静默接受。

**合同结构**：`target_effects`（A 如何改变局部状态，可引用 `<name>_post`）、
`upstream`（带 `role=fixed_point|supporting` 的入口条件）、
`observers`（每通道一个"从 A 之后的状态算出该通道值"的表达式 + 不变性条件）、
`mask_guard`、`uncertainty`。

**两个义务分离**（`mace/verify.py`）：

1. *观察者可靠性*：按观察值分组，若两组同观察不同输出则 `collisions>0` → `REFUTED`。
   这一项在 `overwrite_channel` 上真的抓到了问题：最初写的
   `expr = fn_0(xs) if keep else 0` 对 P+ 忠实，但对 P− 不忠实
   （`keep=False` 时 P− 返回 `value`），被 `collisions=28` 判定不成立。
2. *目标不变性*：条件成立时通道值不变，逐通道检查。

**反例引导修复**：每轮把失败关系连同真实反例（参数、两侧输出、A 前后的局部快照）
喂回模型，模型只回一个 patch（`revise` / `add_observers` / `mask_guard`），
不重写整体。两次修复轮都把程序源弄丢的 harness bug 已修（`tests/test_loop.py::
test_repair_round_still_sees_the_program`）。

**隔离**：`python -I runner.py`，空临时工作目录，清洗过的环境变量，墙钟超时，
AST 白名单 + 受限 `__builtins__`。这是进程隔离，不是容器沙箱。

## M3 传播与归因

| 机制 | 实现 | 输出字段 |
|---|---|---|
| 上游定点 | 条件成立 ⇒ `snap_plus == snap_minus` | `composition.upstream_fixed_point` |
| 逐通道不变性 | 条件成立 ⇒ 该通道 P+/P− 相等 | `relations[*]`（observer） |
| 组合（共享结构，不枚举子集） | `guard = (OR 定点条件) OR (AND 观察者条件)` | `composition.derived_guard`、`attribution.proof_dag` |
| 第二级：本次执行里差异在哪消失 | `sys.settrace` 记录两侧逐行局部变量，找"由差异值算出却相等"的语句 | `trace.aggregate` / `diff.absorbed` |
| 第三级：对比下的因果必要性 | 按"除一个参数外全部固定"分组，统计判定翻转 | `attribution.contrast` |
| 守卫归因 | 把误判记到具体顶层子项上 | `guard.blame` |
| 反例对比回注 | 每个参数最多给一对只差该参数、结论相反的真实执行 | `guard.contrasts` |

### 一个真实例子（`overwrite_channel`，输入 `xs=[2,3], keep=true`）

```
out_plus = [5, 6]   out_minus = [5, 6]
absorbed = [{"name": "value", "computed_at": 15, "from_differing": ["value"]}]
equalized = [{"name": "value", "differs_at": 13, "equal_at": 15}]
```
即：A 把 `value` 改成 0，差异一直存在到第 13/14 行，被第 15 行的重新赋值
（`value = fn_0(xs)`，分支内）抹掉。这是第二级归因，只说明这一次执行。

第三级在同一 fixture 上给出对比：`keep` 取真/假、其余不变，判定翻转。

### 归因反馈到底有没有用：三次消融

同一套 fixture、同一模型（14B）、`rounds=4`、`seed=42`，只改反馈内容：

| 版本 | 反馈内容 | guard 正确数（3 fixture × 4 模式） | MACE prompt tokens |
|---|---|---|---|
| v0 `m2_20261030_084711` | 只有反例 | 2 / 12 | 18.4k |
| v1 `m2_20261030_090315` | + 误判子项定位（blame） | 3 / 12 | 18.4k |
| v2 `m2_20261030_090957` | + 单参数对比见证（contrasts） | 2 / 12 | 20.8k |

**结论：没有可测的改善**，而且成本上升。差异（±1 格）在单次运行之间就不稳定
（v1 的 `swap/generic` 正确，v2 的同格失败）。这说明在这个模型规模上，
瓶颈不是"反馈不够具体"，而是语义推理本身：模型拿到"这两个输入只差 `show_gap`，
结论相反"之后，仍然不会去补上缺失的析取项。

这一点值得记录，因为它否证了一个自然的假设——"给更精准的反例就能修好关系"。

## M4 未见程序

三个新 fixture 在引擎冻结后编写，模型从未见过：

| fixture | 机制 | 参考 guard |
|---|---|---|
| `overwrite_channel` | 下游分支重算 | `keep or fn_0(xs) == 0` |
| `modulo_absorb` | 取整吸收 `+1` | `cap and fn_0(xs) % 10 != 9` |
| `alt_masking` | 两个不同的吸收分支 | `mode == 0 or mode == 1` |

14B：**3 / 12 正确**。

* `alt_masking`：`direct`、`generic`、`full MACE` 三种模式都给出
  `mode == 0 or mode == 1`，`BOUNDED`、0 误接受 0 误拒绝。
  MACE 这一格虽然有 3 条关系失败（`out` 不是 A 处的变量），guard 是对的。
* `modulo_absorb`：全部失败；`generic` 给出的 guard 无法编译。
* `overwrite_channel`：全部失败；`fixed` 给出 `keep == False or fn_0(xs) == 0`。

7B：**0 / 12**。

### 系统性的极性错误

三个互不相干的 fixture 上，模型都把分支条件写反：

| fixture | 正确 guard | 模型写的 |
|---|---|---|
| `overwrite_channel` | `keep or ...` | `keep == False or ...` |
| `modulo_absorb` | `cap and ...` | `cap == False` |
| `sort_channel` | `pre or ...` | `pre == False` |

改名对照（`pre→flag_0` 的 `sort_channel_neutral`）下 14B 仍写 `flag_0 == False`，
排除名字暗示。这与 `swap_channels`（正确答案恰好含 `show_gap == False`）
形成对照：模型似乎有一条"被掩盖 ⟺ 标志为假"的表面规则，
在标志语义相反时会稳定出错。这是本次实验里最可复现的失败模式。

## 基线对比（同模型 / 同上下文 / 同轮数 / 同 seed）

14B，6 个 fixture，guard 正确数：

| 模式 | 正确 | 平均 prompt tokens | 平均 completion tokens | 平均耗时 |
|---|---|---|---|---|
| direct（直接问 guard） | 1 / 6 | 4.0k | 0.15k | 10 s |
| generic（通用函数摘要） | 1 / 6 | 4.7k | 0.31k | 15 s |
| fixed（固定关系菜单） | 2 / 6 | 4.2k | 0.24k | 12 s |
| **full MACE** | 1 / 6 | 16.6k | 1.60k | 56 s |

**MACE 没有赢。** 它在同一个预算下多花约 4 倍 prompt token、5 倍墙钟时间，
正确率还不如 `fixed` 基线。在 `alt_masking` 上它给出正确 guard，
但在 `dedup_channel`、`swap_channels` 上输给 `fixed`。

## 为什么

合同要求一组**互相一致**的关系：观察者表达式必须在 P+ 和 P− 两个状态下都忠实，
上游条件必须真的蕴含定点，然后才允许组合出 guard。7B/14B 能写对
`target_effects`（3 个 fixture 中 2 个 `BOUNDED`）和个别观察者
（`a + b`、`a * b`），但写不对观察者条件与分支极性。一旦关系错误，
组合步骤没有可用的输入，guard 就退回模型的猜测——此时 MACE 退化成
"更贵、更容易格式出错的 direct"。

这说明 MACE 的价值不在这个模型规模上：组合只有在关系对时才成立，
而关系正确率取决于模型的语义能力。

## 32B 补测

`qwen2.5-coder:32b`（Q4_K_M，19 GB，100% GPU，ctx 8192）在**同一套引擎、
同一预算**下重跑全部六个 fixture：
`/root/m4_20261030_093648`（未见）与 `/root/m4_20261030_094431`（原有）。

| fixture | direct | generic | fixed | MACE |
|---|---|---|---|---|
| `alt_masking` | ✓ | ✓ | ✓ | ✓ |
| `overwrite_channel` | ✗ `not keep` | ✗ `not keep or fn_0(xs) == 0` | ✗ INVALID | **✓ `keep or fn_0(xs) == 0`** |
| `modulo_absorb` | ✗ `cap and fn_0(xs) % 10 == 9` | ✗ `not cap` | ✗ | ✗ (INVALID) |
| `dedup_channel` | **✓ `distinct(xs) == distinct(xs + [xs[0] + 1])`** | ✗ INVALID | ✓ | ✗ `len(xs) == 0` |
| `sort_channel` | ✗ | ✗ | ✗ | ✗ (INVALID) |
| `swap_channels` | ✗ `show_gap == False` | ✗ | ✗ | ✗ (INVALID) |
| **合计** | **2/6** | **1/6** | **2/6** | **2/6** |

**MACE 与最好的基线持平，没有整体优势。** 差异是定性的：MACE 是唯一解出
`overwrite_channel` 的模式，而这一格需要把"上游定点"和"观察者条件"拼起来；
反过来它在 `dedup_channel`、`swap_channels` 上输给基线，失败原因很具体——
在 guard 里用了 `<name>_post`（`a == b_post and b == a_post`、`xs == xs_post`），
编译为 INVALID。这个错误在 7B/14B 上也出现过，是合同格式本身的陷阱。

`overwrite_channel` 的 MACE 合同（唯一一处三条关系都被独立验证、guard 正确）：

```
T1  BOUNDED  value_post == 0
O0  BOUNDED  fn_0(xs) if keep else 0
O1  BOUNDED  fn_0(xs) + 1 if keep else 1
U1  INVALID  keep and value == fn_0(xs)          # 上游只能用入口参数，这里用了 value
U2  INVALID  not keep and value == 0
G   BOUNDED  keep or fn_0(xs) == 0               # 与人工参考逐字相同
```

成本（6 fixture 平均）：

| 模式 | guard 正确 | prompt tokens | completion tokens | 墙钟 |
|---|---|---|---|---|
| direct | 2/6 | 3.3k | 0.18k | 15 s |
| generic | 1/6 | 4.7k | 0.43k | 27 s |
| fixed | 2/6 | 3.7k | 0.19k | 14 s |
| MACE | 2/6 | 16.6k | 1.46k | 81 s |

结论：**在 32B 上 MACE 付出约 5 倍代价换来与基线相同的正确率**，
只在"需要组合多种机制"的那一个 fixture 上体现出差别。要支持"语义合同比直接推理
更准"这一假设，需要更多 fixture、多次重复，以及把 `<name>_post` 这类格式陷阱
从合同里去掉（例如让 guard 也能引用后置状态，或在 schema 里把它标成错误）。
本次实验不支持该假设。

## 复现

```bash
python -m mace.cli run --fixture overwrite_channel.json --mode all \
    --model qwen2.5-coder:14b --rounds 4 --seed 42 --num-ctx 8192
python -m mace.cli summarize --runs runs/m4_20261030_091725
python -m mace.cli trace --fixture overwrite_channel.json \
    --args '{"xs": [2, 3], "keep": true}'
```
