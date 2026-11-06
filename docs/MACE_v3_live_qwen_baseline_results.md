# MACE Benchmark v3 真实 Qwen 公平基线运行结果

- `experiment_id`：`mace_v3_live_qwen_baseline_2026-11-03`
- 日期：2026-11-03（Asia/Shanghai）
- Benchmark release：`v3.0-dev-pilot-2026-11-02`
- 分支：`baseline/mace-v3-pilot`
- 代码提交：`86e1b543f5ee6193e76994c7bfd757f4b9ece02d`
- 运行配置 SHA-256：`cda565fda3e8de22d85dd4c7800a9636d3e36a7ee08f2ee1f2c2f080b7133d62`
- 运行目录：`runs/v3_live_qwen/`
- 运行标签：`LIVE_MODEL_RUN`（A/B）/ `NO_MODEL_DETERMINISTIC_RUN`（C）

本轮把冻结的 `qwen2.5-coder:32b` 真实部署在 AutoDL RTX 4090 D 上，
通过 SSH 端口转发在冻结端点 `http://127.0.0.1:11434` 完成 5 次真实
模型调用。A（Direct Qwen）在 5 道冻结题上共提交 15 条 claim，得到
**2 条 credited relation**；B（同一 proposal 的纯验证）**没有新增模型
调用**，把 A 的 2 条 FALSE 和 3 条 INVALID 全部剔除，但也没有增加
credited relation；C 在完全相同的冻结题上复算得到 **23 条 credited
relation**，与冻结记录一致。

五道题仍是 `DEV-TUNED` 开发题，本文件的所有数字都不得当作 held-out
泛化准确率。

---

## 1. 实验身份与冻结一致性

| 项 | 值 |
|---|---|
| `experiment_id` | `mace_v3_live_qwen_baseline_2026-11-03` |
| 代码提交 | `86e1b543f5ee6193e76994c7bfd757f4b9ece02d` |
| 分支 | `baseline/mace-v3-pilot` |
| 本轮 `config.json` SHA-256 | `cda565fda3e8de22d85dd4c7800a9636d3e36a7ee08f2ee1f2c2f080b7133d62` |
| 冻结 C 的 `config_sha256` | `7cd4df5c0478ec7b84f01b557cc0e498767e5a786505459c39663e11d76b591b` |
| 两者差异 | **仅** `git_commit`（`a51faab` → `86e1b54`）；`model`、`budget`、`task_hashes` 逐字段相等 |
| Benchmark release | `v3.0-dev-pilot-2026-11-02` |
| 题目状态 | 5 题全部 `DEV_TUNED` |
| HIDDEN 数据 | 基线包不读取；评分由冻结 scorer 子进程完成 |
| 冻结清单复核 | `python scripts/v3_freeze_manifest.py --verify runs/v3_baseline_freeze` → `FREEZE VERIFY OK` |

### 1.1 首次真实调用前的一处传输层修正

`QwenClient` 原先在 `mace/qwen.py` 中把 `num_predict` 硬编码为 `2048`，
而冻结配置声明的是 `4096`。在任何真实模型调用发生之前，已提交
`86e1b54` 把它改为读取 `self.num_predict`（默认 4096），使实际请求与
冻结配置一致。该文件不在冻结清单 `CODE_FILES` 内；C 的代码、配置、
提交与全部冻结产物未改动，`--verify` 仍为 `FREEZE VERIFY OK`。

冻结模型、规模、量化方式均未更换：

| 参数 | 值 |
|---|---|
| provider | `ollama` |
| model | `qwen2.5-coder:32b` |
| 参数量 | 32.8B |
| 量化 | `Q4_K_M`（未改动） |
| temperature | `0.0` |
| seed | `42` |
| `num_ctx` | `32768` |
| `num_predict` | `4096` |
| `json_mode` | `true` |
| timeout | `900 s` |
| retries | `1` |
| 端点 | `http://127.0.0.1:11434` |

预算未改动：每题最多 3 次模型调用、全实验 15 次、每次 4096 completion
tokens、每题 6000 probes、最多 6 个候选操作、8 个输入、40 条 claim。
本轮 A 实际只用了 **5 次**调用（每题 1 次），B 新增 **0 次**。

---

## 2. GPU、服务与模型身份

AutoDL 容器内检查结果：

| 项 | 值 |
|---|---|
| 主机名 | `autodl-container-54ed41a6ad-438061c3` |
| GPU | `NVIDIA GeForce RTX 4090 D`，24564 MiB |
| 驱动 / CUDA | `580.76.05` / CUDA 13.0 |
| 主机内存 | 1007 GB |
| 系统盘 | 30 GB（运行前 26 GB 可用） |
| ollama | `0.40.13` |
| 服务监听 | `127.0.0.1:11434` |
| 模型目录 | `OLLAMA_MODELS=/root/autodl-tmp/ollama_models` |
| ollama manifest digest | `b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41` |
| 权重 blob SHA-256 | `ac3d1ba8aa77755dab3806d9024e9c385ea0d5b412d6bdf9157f8a4a7e9fc0d9`（19,851,336,384 B，`sha256sum` 实测） |
| `context_length` | `32768` |
| 加载后 `size` | 25,522,937,527 B |
| 加载后 `size_vram` | 23,535,435,120 B（21.9 GiB，约 1.85 GiB 在 CPU） |
| 加载时 `nvidia-smi` | 22,861 MiB used |

端点路径：本机 `http://127.0.0.1:11434` → SSH 转发 →
AutoDL `127.0.0.1:11434`。这样客户端使用的端点字符串与冻结配置完全
一致，没有改用远程 IP 或其它端口。

服务启动日志中的关键行：

```text
inference compute id=0 library=CUDA compute=8.9
  name=CUDA0 description="NVIDIA GeForce RTX 4090 D"
  driver=13.0 total="23.5 GiB" available="23.2 GiB"
vram-based default context total_vram="23.5 GiB" default_num_ctx=32768
Listening on 127.0.0.1:11434 (version 0.40.13)
```

---

## 3. 冒烟测试：证明请求真实到达模型

冒烟调用使用与正式实验相同的客户端与参数；请求、原始响应、统计和
`/api/ps` 已保存到 `runs/v3_live_qwen/smoke/smoke.json`。

请求：

```json
{"messages": [
  {"role": "system", "content": "Return only JSON."},
  {"role": "user", "content": "Reply with exactly {\"ok\": true}."}],
 "stream": false, "format": "json",
 "options": {"temperature": 0.0, "seed": 42,
             "num_ctx": 32768, "num_predict": 4096}}
```

原始响应：

```json
{"ok": true}
```

| 指标 | 值 |
|---|---|
| 响应模型名 | `qwen2.5-coder:32b` |
| `prompt_tokens` | 25 |
| `completion_tokens` | 6 |
| `done_reason` | `stop` |
| 加载耗时 | 31.39 s |
| 端到端耗时 | 35.07 s |
| `/api/ps` `context_length` | 32768 |
| `/api/ps` `size_vram` | 23,535,435,120 B |
| 运行标签 | `LIVE_MODEL_RUN` |

响应内容与请求语义一致，且 `/api/ps` 显示的就是 32B 模型本体；这不是
历史响应重放，也不是 1.5B 模型冒充。

---

## 4. 逐题结果

### 4.1 汇总表

记 `W/F/INV/U` 分别为 `WITNESS_VERIFIED / FALSE / INVALID / UNVERIFIED`。
B 的 `V/R/U` 是验证器本地判定 `VERIFIED / REFUTED / UNKNOWN`。

| 题 | A claims | A 状态 | A credited | A tokens (p/c) | A wall | B V/R/U | B credited | C credited |
|---|---|---:|---|---:|---:|---:|---:|---:|
| `jinja2_bytecode_cache_read` | 3 | W0 F1 INV0 U2 | 0 | 6244 / 198 | 135.069 s | 1/2/0 | 0 | 4 |
| `werkzeug_bind_server_name_lower` | 3 | W1 F0 INV0 U2 | 1 | 9272 / 234 | 182.323 s | 1/2/0 | 1 | 4 |
| `werkzeug_filestorage_stream_name` | 3 | W1 F0 INV0 U2 | 1 | 23660 / 256 | 404.319 s | 1/2/0 | 1 | 4 |
| `werkzeug_get_host_default_empty` | 3 | W0 F0 INV3 U0 | 0 | 4690 / 251 | 140.582 s | 0/3/0 | 0 | 7 |
| `werkzeug_secure_filename_ascii_filter` | 3 | W0 F1 INV0 U2 | 0 | 7106 / 256 | 162.795 s | 1/2/0 | 0 | 4 |
| **合计** | **15** | **W2 F2 INV3 U8** | **2** | **50972 / 1195** | **1025.088 s** | **4/11/0** | **2** | **23** |

所有 5 次 A 调用 `attempt=0`、`done_reason=stop`，没有重试，也没有
因超时被截断。B 在本地执行 16 次 probe、耗时 12.303 s，没有发起任何
新的模型调用。

### 4.2 逐题说明

**`jinja2_bytecode_cache_read`（NO_LOCAL_EFFECT）**

A 提交 1 条 EXPOSING、1 条 MSMS、1 条 MMBS，全部基于
`loaders.py:132 code = bucket.code`。EXPOSING 被判 `FALSE`（P+ 与 P−
观测相等）；MSMS/MMBS 的操作为 `outside the declared candidate universe`，
计 `UNVERIFIED`。B 本地验证器复算后：EXPOSING `REFUTED`、MMBS
`REFUTED`，MSMS 在“只含该 1 个操作的 universe”里 `VERIFIED`；但该
操作仍不在评分器的隐藏候选域内，最终计 `UNVERIFIED`。**A/B 均 0
credited。**

**`werkzeug_bind_server_name_lower`（NO_LOCAL_EFFECT）**

A 的 EXPOSING 输入 `{"host":"Example.com","server_name":"Example.com",
"subdomain":null}` 被 `WITNESS_VERIFIED`，这是本轮 A 的第 1 条
credited relation。A 同时把 `map.py:307 server_name = server_name.lower()`
作为单元素 MSMS/MMBS 提交；两者都因超出隐藏候选域计 `UNVERIFIED`。
B 保留该 witness、剔除两条不可评分 claim，最终 1 credited、0 FALSE。

**`werkzeug_filestorage_stream_name`（ASSERTION_GAP_STORY）**

A 的 EXPOSING witness（`stream=named, name=testfile.txt`）被
`WITNESS_VERIFIED`，是第 2 条 credited relation；MSMS/MMBS 依赖
`datastructures.py:2918 filename = getattr(stream, "name", None)`，
超出隐藏候选域，均 `UNVERIFIED`。B 保留 witness，1 credited、0 FALSE。

**`werkzeug_get_host_default_empty`（FULL_MASKING_STORY）**

A 的三条 claim 都使用了公开 input contract 中不存在的字段
`trusted_hosts`，评分器直接判 3 条 `INVALID`（0 credit）。B 的验证器
在运行 probe 之前就拒绝非法输入，3 条全部 `REFUTED`，probe 执行数为 0。
这是 B 真正发挥作用的一题：**把 A 的无效输入拦在评分之前**。

**`werkzeug_secure_filename_ascii_filter`（FULL_MASKING_STORY）**

A 的 EXPOSING（`filename="i contain cool ümläuts.txt"`）被判 `FALSE`
（P+/P− 观测相等）；MSMS/MMBS 依赖
`utils.py:222 filename = filename.encode("ascii", "ignore").decode("ascii")`，
超出隐藏候选域，`UNVERIFIED`。B 本地把该单元素 MSMS 判 `VERIFIED`，
但评分仍为 `UNVERIFIED`；另两条被 `REFUTED`。0 credited。

### 4.3 逐题产物与哈希

每题 A 的 request、原始响应、解析后的 submission 均已落盘：

| 题 | request SHA-256 | raw_response SHA-256 | submission SHA-256 |
|---|---|---|---|
| `jinja2_bytecode_cache_read` | `1d0926afdc6199958b54f71c05f38f95dc5a7963774d511a396d814857af147b` | `5364eca0f6770cc480c0cbfadf2ec7a0f17c85334e778448535cbfdeb467c172` | `2e48b8a1fa1c673516bc5494993f2d69d0c9e0889542b543fe899bfab65ff36a` |
| `werkzeug_bind_server_name_lower` | `ae2a4be9c2c6b1d4c1d92fb296f88934e96171f42ffd559e0c7ec54905483324` | `fe9ffff10c917ba60dfdc5ffed33f58376865eda65cf9edcc558685612dc68b9` | `7fdcf4a5034c4db4e7225665c0a2f1faccf435a70e32faff55051819b2c61375` |
| `werkzeug_filestorage_stream_name` | `53793bce0da8f18a82335cc21f3ab335d2f53007c645a26442ef927c29b6ddfc` | `52b51e04d6792b7af512e2151230eb38d04fc0514112cde02ded5e0aefd0166e` | `93bb1245779c4287e404dc304518314df22f1b864b89477593420d765a5fe255` |
| `werkzeug_get_host_default_empty` | `ecc663e03c7e00e2b70dd261dd657e30ae7f3fe3daa6d07f9dab19eda5c30599` | `baf75d21c763fd87f448d3dfb77b341d7eb7536533b04a99df586a26531fd4b7` | `ec1d33213b2ca1065cca9b8072689e05a1cc9e2e8544c09015bc67f2cf4850d7` |
| `werkzeug_secure_filename_ascii_filter` | `1f38868faba5647adc52efb3eee9d50c66d4466d57ac16824a16866f8eb8e2db` | `f9fc97efe51b73a52bf4807e55897792ad2291ac50afec7440888c5d79e0fa8d` | `ce1531b3f2cef20750026b727c8b59e7d3f4b8f4a71c2d10bd8bb9b35044f586` |

每题目录：

```text
runs/v3_live_qwen/tasks/<task_id>/
  baseline_a/request.json          # 完整 messages（system + task JSON + 源文件）
  baseline_a/raw_response.txt      # 模型原始输出，逐字保存
  baseline_a/run.json              # messages、raw_response、stats、wall
  baseline_a/submission.json       # 机械解析结果，未修复
  baseline_b/verifier.json         # 本地 VERIFIED/REFUTED/UNKNOWN 明细
  baseline_b/verified_submission.json
  baseline_c/…                     # C 的确定性复算
  scores/{A,B,C}.json              # 冻结 scorer 输出
  summary.json                     # 本题 A/B/C 汇总
```

完整原始响应（均为模型逐字输出）保存在上述 `raw_response.txt`；这里不
重复展开 5 份 JSON，以免与文件内容产生漂移。全部 5 份响应的 sha256
已在上表列出。

---

## 5. 与冻结 C 的对比

| 指标 | A Direct Qwen | B Qwen + Verifier | C AST + Intervention |
|---|---:|---:|---:|
| 新增模型调用 | **5**（每题 1 次） | **0** | **0** |
| 提交 claim 数 | 15 | 4（验证后保留） | 23 |
| credited relation | **2** | **2** | **23** |
| WITNESS_VERIFIED | 2 | 2 | 12 |
| FINITE_DOMAIN_EXACT | 0 | 0 | 11 |
| FALSE | 2 | **0** | **0** |
| INVALID | 3 | **0** | **0** |
| UNVERIFIED | 8 | 2 | 0 |
| probe 执行 | 0 | 16 | 696 |
| variant 构建 | 0 | 0 | 112 |
| 本地/总耗时 | 1025.1 s | 12.3 s | 237.4 s（冻结记录 231.94 s） |

C 的复算结果：

- submission 与冻结版本逐字节相同（5/5）。
- 评分器中所有计分字段相同；`filestorage` 仅有一处
  `observations.plus.filename` 字符串包含操作系统临时目录路径，
  两次运行路径不同，该字段不参与计分。
- 23 条 credited relation = 18 条参考关系 + 5 条额外真实 prerequisite；
  0 FALSE / 0 INVALID / 0 UNVERIFIED；696 probes、112 variants。
- 本轮 C 耗时 237.378 s，冻结记录 231.94 s，差异是机器负载波动。

**C 没有被重新调参，也没有使用本轮 A/B 的任何结果。** 这些数字仍只
代表 5 道 `DEV-TUNED` 题，不能据此宣称 C 在未见项目上的泛化准确率。

---

## 6. 能力边界观察（仅基于本轮证据）

1. **A 没有产生任何多操作集合。** 15 条 claim 中，每条 MSMS/MMBS 都是
   单元素集合，且与它自己命名的操作相同；没有出现“两个操作共同遮蔽”
   或备用路径的组合。A 也没有提交 prerequisite、条件正确性等类型。
2. **A 能偶尔找到真实 witness，但不能把 witness 转成关系。** 2 条
   credited relation 都是 `EXPOSING`；MSMS/MMBS 全部因操作不在隐藏
   候选域而 `UNVERIFIED`。A 的 claim 数与真实关系数之间没有稳定对应。
3. **A 会发明公开契约之外的输入字段。** `get_host` 的 3 条 claim 全部
   使用 `trusted_hosts`，直接 `INVALID`。这说明“知道 API 语义”不等于
   “遵守冻结输入契约”。
4. **B 的收益是精确率，不是召回率。** B 剔除了 A 的 2 条 FALSE 和 3 条
   INVALID，使保留 claim 中 0 FALSE / 0 INVALID；但它没有发现 A 未
   命名的操作，也没有把 2 条“本地可验证、隐藏域外”的 MSMS 变成
   credited relation。
5. **B 的验证是相对于 proposal 自己命名的 universe。** 每题 B 的
   universe 只有 1 个操作（A 只命名了 1 个），因此“单元素 MSMS 最小”
   在该 universe 内几乎自动成立；这种 VERIFIED 不能外推为隐藏域内的
   真实关系。评分器的 `outside the declared candidate universe` 正是
   这一限制的体现。
6. **B 确实阻止了无效执行。** `get_host` 上 B 在 0 次 probe 的情况下
   拒绝了 3 条非法输入；这是本轮最明确的“验证器前置拦截”证据。

本轮没有证据支持以下说法：A 能处理协作遮蔽、多级 fallback、
跨函数状态、循环/有状态执行、复杂布尔条件；B 能补出 A 未提到的操作。
这些能力仍未被执行层验证。

---

## 7. 状态台账

| 运行项 | 状态 |
|---|---|
| A Direct Qwen × 5 题 | `LIVE_MODEL_RUN`（5 次真实调用） |
| B pure verification × 5 题 | `LIVE_MODEL_RUN`（0 次新增调用，验证 A 的同一份 proposal） |
| C AST + Intervention × 5 题 | `NO_MODEL_DETERMINISTIC_RUN` |
| feedback regeneration | `NOT_RUN`（未执行；需要单独条件与单独成本） |
| legacy Full MACE | `UNSUPPORTED_INTERFACE`（不是 0 分） |
| `FAILED` | 无 |
| `NOT_RUN`（A/B） | 无 |
| `FIXED_PROPOSAL_REPLAY` | 无；本轮全部是实时模型输出 |

---

## 8. 复现与环境记录

运行命令：

```bash
python -m benchmark_v3_baselines.run_pilot --out runs/v3_live_qwen
```

关键文件：

```text
runs/v3_live_qwen/
  config.json / config.sha256     # 本轮冻结配置与哈希
  environment.json                # 模型 digest、/api/ps、GPU、服务日志
  smoke/smoke.json                # 冒烟请求、原始响应、token、显存
  availability.json               # 端点可达、模型存在
  summary.json                    # 五题 A/B/C 总汇总
  driver.log                      # 运行日志
  tasks/<task_id>/…               # 逐题全部原始产物
```

`environment.json` 中记录：模型 manifest digest、权重 blob sha256、
`/api/ps` 的 `size/size_vram`、`nvidia-smi` 输出、ollama 版本与服务
启动日志。`config.sha256` 与 `experiment_config()` 的 canonical JSON
一致。

---

## 9. 合规与安全

- 没有 fake Qwen、没有历史响应重放、没有模拟成绩；A/B 的
  `raw_response.txt` 均来自本轮真实 HTTP 响应。
- 没有使用本机 1.5B checkpoint；实际响应模型名为
  `qwen2.5-coder:32b`，`/api/ps` 显示 32.8B / Q4_K_M / 32768 context。
- 没有更换冻结模型、规模或量化方式；没有把不同配置的结果混入同一实验。
- SSH 密码只存在于临时进程环境变量，没有写入 `runs/`、`docs/`、
  配置快照或 Git；对 `runs/` 与 `docs/` 的扫描命中数为 0。
- 没有修改 Benchmark 题目、公开 task.json、评分器或 HIDDEN 数据；
  C 的算法与冻结产物未改。
- 没有新增 Agent、Prompt 阶段、EXP-1、子图模块或新算法架构。
- 全量测试：262 passed。
