# MACE Source-derived v2.1：数据集质量审计

- 审计日期：2026-11-05（UTC）
- 审计范围：`benchmark_v4_dataset/source_derived/`（冻结的 v2）与新建的 `benchmark_v4_dataset/source_derived_v2_1/`
- 审计对象：50 道正式 `SOURCE_DERIVED_CONTROLLED` 题（DEV 25 / HELDOUT 25），23 个上游项目
- 冻结约束：不修改 MACE 算法窗口的任何代码、Prompt、Graph、AST、搜索器或 Verifier；不调用 GPU；不覆盖 v2；不删除原始 acceptance/evidence；不修改 HELDOUT 原始 seal；不把 HELDOUT 答案写入算法窗口；不通过降低验收标准增加通过数。
- 性质：数据集侧审计与修复。正式 50 题**没有增删、替换或改判**。

## 0. 结论摘要

| # | 审计项 | 结论 |
|---|---|---|
| 1 | 项目隔离 | **不完全隔离**。DEV 10 个项目、HELDOUT 17 个项目，交集 4 个；6/25 道 HELDOUT 与 DEV 同项目，且同版本；jsonschema 与 toml 还共用同一 A 行。项目隔离子集为 19 题 / 13 个项目。 |
| 2 | 模板泄漏 | **存在模板级泄漏**。HELDOUT 的 17 个构造模板中有 4 个在 DEV 出现，涉及 9 题；其中 1 题模板与机制都相同，8 题模板相同但机制不同；没有任何 HELDOUT 题同时做到机制新 + 模板新。模板隔离子集 16 题。 |
| 3 | 元数据/哈希 | 旧版有 3 处函数名错误、25 处 `api` 占位符、50 题交付文件 CRLF 与枚举哈希不一致；v2.1 已全部修复并逐题复核。50/50 题哈希校验通过。 |
| 4 | MSMS/MMBS 独立核验 | 旧版 35 道可比题中 23 道不一致，根因是 MMBS 直接复制 MSMS，以及把空集 `[]` 当作极小集；非空 MSMS 本身没有算错。v2.1 用独立实现重算，50/50 与 reference 一致；58 个输入按定义标记 `NOT_SEPARABLE`。 |
| 5 | M10 阴性对照 | 5 题均满足严格阴性条件；结论仅是“该候选补丁在这些输入上不构成掩盖关系”，不是“A 在任何候选下都没有掩盖关系”。另新增 3 道 DEV 阴性对照。 |
| 6 | 复杂度 | 候选全集 U 仅 1–3 个（31 / 13 / 6 题）；每题材 4/6/10 个探针；5 题跨函数。已构建 5 题扩展挑战集（U=4–5，各加 3 个干扰候选）。 |
| 7 | 许可证 | 23 个项目全部允许再分发源码，但均附带许可证/NOTICE 条件；推荐发行方式仍是“补丁 + 固定版本下载脚本”。docutils 为复合许可证，需整体携带 `COPYING.txt` 与 `licenses/`。 |
| 8 | 时间戳 | 23 个机器可读时间戳全部为 ISO 8601 UTC（`Z` 结尾），0 个非法；历史 v2 seal 与日志未改写，仅记录 mtime。 |
| 9 | 交付物 | 见第 9 节；两篇文档、7 个 `results/source_derived_v2_1_*` 主产物、子集/NC/验收/差异记录均已落盘。 |

## 1. 项目隔离审计

### 1.1 方法

从 50 个 `task.json` 的 `project`、`version`、`target_operation.file/line` 重新统计，不沿用旧报告的分组：

- DEV 项目集合与 HELDOUT 项目集合分别求并；
- 交集项目逐题列出，并核对版本与源文件是否相同；
- 同一 `(project, file, line)` 的 A 行重复单独列出；
- 项目隔离子集定义为“HELDOUT 中项目不出现在任何 DEV 题中的题”。

### 1.2 结果

| 项 | 数量 |
|---|---:|
| DEV 项目 | 10 |
| HELDOUT 项目 | 17 |
| 交集项目 | 4（attrs、isort、jsonschema、toml） |
| 与 DEV 同项目的 HELDOUT 题 | 6 / 25 |
| 项目隔离子集 | 19 题 / 13 个项目 |

6 道重叠题：

| 题号 | 项目 | 版本 | 与 DEV 的关系 |
|---|---|---|---|
| `sd_attrs_tobool_nc` | attrs | 23.2.0 | 与 `sd_attrs_asdict_loop_m7` 同项目同版本，不同文件 |
| `sd_isort_module_key_m5` | isort | 5.13.2 | 与 `sd_isort_format_strip_m4` 同项目同版本，不同文件 |
| `sd_jsonschema_pointer_m4` | jsonschema | 4.20.0 | 与 DEV 题**同一文件同一行**（`validators.py:1145`） |
| `sd_jsonschema_pointer_nc` | jsonschema | 4.20.0 | 同上 |
| `sd_toml_quote_escape_m4` | toml | 0.10.2 | 与 DEV 题**同一文件同一行**（`encoder.py:97`） |
| `sd_toml_quote_nc` | toml | 0.10.2 | 同上 |

重复 A 行共 3 组：

| 项目 / 文件:行 | 题数 | 构成 |
|---|---:|---|
| `jsonschema/validators.py:1145` | 3 | 1 DEV + 2 HELDOUT |
| `multidict/_multidict_py.py:47` | 2 | 2 HELDOUT（同项目内部） |
| `toml/encoder.py:97` | 2 | 1 DEV + 1 HELDOUT |

**判定**：HELDOUT 在“项目”维度不是干净的留出集。最严重的是 jsonschema/toml 的同一 A 行同时出现在 DEV 与 HELDOUT，即使机制标签不同，也不能排除模型记住该行的修复形态。`sd_jsonschema_pointer_nc` 还是 DEV M1 题的同锚点阴性对照。

### 1.3 处置

- 已生成 `results/source_derived_v2_1_project_disjoint_subset.json` / `.csv`：19 题、13 个项目、机制分布 M2=3、M3=3、M6=3、M10=2、M5=2、M8=2、M9=2、M4=1、M7=1。
- 恢复 25 题的替换计划已记录（需补 M10×3、M4×2、M5×1），`built: false`。按任务书，替换是可选动作；本次没有新建替换题，也没有用替换题冒充原题。
- 正式 50 题保持不变；对外声明若涉及项目泛化，应使用 19 题项目隔离子集，或明确披露 6 题重叠。

## 2. 模板泄漏审计

### 2.1 方法

对每题 A 语句做归一化 AST 比较（`Name→v`、`Attribute→a`、`Constant→c`、`FunctionDef.name→f`），模板定义为“A 语句类型 + 外层控制祖先 + U 块形状（guarded/unguarded、before/at/after 锚点）”，另用归一化 AST token 的 Jaccard 相似度找最近 DEV 题。该方法是结构指纹，不是“换个变量名就算新模板”。

### 2.2 结果

| 类别 | 题数 | 含义 |
|---|---:|---|
| `B_same_template` | 1 | 模板与机制都与某道 DEV 题相同 |
| `B_same_template_other_mechanism` | 8 | 模板相同，机制不同 |
| `A_same_mechanism_diff_template` | 16 | 机制相同，模板不同 |
| `C_diff_mechanism_diff_template` | 0 | 机制与模板都新 |

- DEV 模板目录 17 个，HELDOUT 模板 17 个；HELDOUT 的 17 个模板中只有 4 个在 DEV 出现（对应 9 题），13 个未出现（对应 16 题）。
- 唯一“模板 + 机制都相同”的题是 `sd_jedi_param_hyphen_m2`（M2），最近 DEV 题为 `sd_docutils_make_id_lower`。
- 8 道“同模板异机制”题：`sd_attrs_tobool_nc`、`sd_isort_module_key_m5`、`sd_jsonschema_pointer_nc`、`sd_multidict_version_nc`、`sd_pycodestyle_paths_nc`、`sd_requests_casedict_m8`、`sd_requests_contenttype_m7`、`sd_toml_quote_nc`。

**判定**：不能把 HELDOUT 描述为“未见机制”或“未见模板”的挑战集。准确说法是：16 题模板未在 DEV 出现，但机制都在 DEV 出现；0 题同时具备机制新与模板新。

### 2.3 处置

- `results/source_derived_v2_1_template_disjoint_subset.json` / `.csv`：16 题模板隔离。
- 与 19 题项目隔离子集取交集，得到 **14 题同时满足项目隔离与模板隔离**。
- 文档中明确要求：模板隔离子集不得被表述为“unseen mechanism”；若论文需要“双新”主张，当前数据集不支持。

## 3. 元数据与哈希审计

### 3.1 函数元数据

用 `ast` 取包含 A 的**最内层** `FunctionDef/AsyncFunctionDef`，并与 `task.json`、`provenance.metadata.function` 三方比对。发现 3 处旧值错误，均是把“嵌套 helper 的名字”记成了函数名：

| 题号 | 旧值 | 新值 | 原因 |
|---|---|---|---|
| `sd_networkx_gexf448_slices` | `edge_key_data` | `add_edges` | 旧值是嵌套 helper，不包含 A |
| `sd_pygments_latex297_italic` | `rgbcolor` | `_create_stylesheet` | 同上 |
| `sd_pygments_style95_cache` | `colorformat` | `__new__` | 同上 |

同时新增 `related_functions`：A 所在函数 + 每个 U 锚点所在函数。5 道跨函数题：

| 题号 | 涉及函数 |
|---|---|
| `sd_pygments_latex297_italic` | `_create_stylesheet; get_style_defs` |
| `sd_pygments_style95_cache` | `__new__; style_for_token` |
| `sd_multidict_version_m6` | `incr_version; getversion` |
| `sd_simplejson_decoder_m6` | `_toggle_speedups; loads` |
| `sd_urllib3_headerdict_m6` | `__init__; add` |

另外，25 道 HELDOUT 题的 `legal_input_contract.api` 在 v2 中是占位符 `see probe`；v2.1 记录具体调用点（例如 `jsonschema.validators.RefResolver(...).resolve_fragment(...)`）。10 道旧 DEV 题的具体 API 文本逐字节保留。

验收检查：`AC_v2_1_function_metadata`、`AC_v2_1_related_functions`、`AC_v2_1_legal_input_contract_api` 全部 50/50 通过。

### 3.2 哈希语义

| 哈希 | 语义 |
|---|---|
| `source_file_sha256` | sdist 内目标源文件字节 |
| `patched_file_sha256` | 交付的 patched 文件字节（v2.1 为 LF） |
| `patched_file_sha256_logical` | 把 CRLF 归一为 LF 后的逻辑文本哈希 |
| `patch_diff_sha256` | 交付的 `patch.diff` 字节 |
| `enumeration_sha256` | 生成 reference 所用的枚举文件字节 |
| `acceptance_sha256` / `task_bundle_sha256` | 验收报告 / 单题交付目录的目录摘要 |

### 3.3 旧版缺陷与修复

- **CRLF 缺陷**：v2 交付的 patched 文件与 `patch.diff` 是 CRLF，而枚举按 LF 文本计算哈希，导致交付字节与 `patched_sha256` 对不上。v2.1 把交付文本统一为 LF，并同时保留 delivered/logical 两个哈希；50/50 题 `patched_file_sha256 == 实际交付字节 == enumeration.patched_sha256`。
- **哈希来源**：v2.1 的 source 哈希与旧 acceptance 的 `hashes.sdist`、evidence 原始文件三方一致（50/50）。
- **历史保留**：旧 v2 哈希与旧验收结论没有删除，逐题保存在 acceptance 的 `legacy_v2` 块；原始 `source_derived/` 一个字节也没有改。
- **manifest**：`results/source_derived_v2_1_hash_manifest.json` 记录每题 `v2_legacy` 与 `v2_1` 两套哈希及 `hash_checks`；50/50 全部为 true。`results/source_derived_v2_1_workspace_manifest.json` 记录 722 个文件的 sha256。

## 4. MSMS/MMBS 独立核验

### 4.1 冻结定义

- `PLUS`：A + 全部 U；`P_MINUS`：删除 A + 全部 U；`KEEP_S`：删除 A + 保留子集 S，未保留的 U 置为不生效。
- **MSMS**：使 `obs(S) == obs(PLUS)` 的**非空**极小保留集 S。
- **MMBS**：仅当 `obs(P_MINUS) == obs(PLUS)` 时定义；使 `obs(U\D) != obs(PLUS)` 的**非空**极小禁用集 D。
- 空保留集若已经复现 PLUS，则不报告非空 MSMS（空集抑制），也不定义 MMBS。
- `P_MINUS != PLUS` 的输入标记 `NOT_SEPARABLE`：没有掩盖基线，MMBS 不可定义。

### 4.2 独立实现

`D:/tmp/sdgen/v21_verify.py` 不调用构造脚本的枚举逻辑，独立完成：重新解压 sdist → 自己生成 P+/P−/KEEP 文本 → 用 `runpy` 在对应 venv 跑 probe → 逐输入按位掩码枚举全部子集 → 自己算极小性。每个 probe 前删除 `__pycache__`，Python 以 `-B -I` 启动。

> 发现的实现坑：`-I` 隐含 `-E`，会忽略 `PYTHONDONTWRITEBYTECODE`；复制树里残留的 `__pycache__` 曾使 msgpack 的两次相同输入产生不同结果。修复后重跑，msgpack 状态为 OK。第一次受污染的日志保留为 `source_derived_v2_1_msms_mmbs_run1_contaminated.json`，不冒充正式结果。

### 4.3 与旧 reference 的比对

| 状态 | 题数 | 含义 |
|---|---:|---|
| `OK` | 12 | 旧 reference 与独立重算一致 |
| `MISMATCH` | 23 | 旧 reference 有错，均可由下述两类缺陷解释 |
| `UNKNOWN` | 15 | 旧 v2 没有这些 DEV 题的 reference，无法比对；独立重算仍完整执行 |
| `INVALID` / `INCOMPLETE` | 0 | — |

**重要**：`UNKNOWN` 只表示“没有旧 reference 可比”，不表示“未核验”。v2.1 reference 与独立重算在全部 50 题上一致（`AC_v2_1_independent_relation_agreement` 50/50）。

### 4.4 更正内容

| 缺陷 | 影响 | 更正 |
|---|---:|---|
| MMBS 被直接赋值为 MSMS | 58 个输入 / 35 题 | 从禁用集观测表独立重算 MMBS |
| 其中“非空 MMBS 真的算错” | 20 个输入 / 19 题 | 例如 coverage 的 `[[U1,U2]]` 应为 `[[U1],[U2]]`；docutils ellipsis 的 `[[U1,U2,U3]]` 应为三个单元素集 |
| 其中“只是空集 artifact” | 38 个输入 | 旧值含 `[]`，去掉空集后与正确值相同 |
| 空集 `[]` 被当作极小集 | 38 个输入 / 34 题 | 非空极小集；空集只用于抑制，不输出 |
| 非空 MSMS 本身算错 | **0** | 38 个 MSMS 变化全部是删除空集 artifact，非空集合一个也没变 |

形式化 50 题共 155 个输入：97 个 `MASKED`、58 个 `EXPOSING`；59 个输入有非空 MSMS，59 个有非空 MMBS，38 个因空集抑制而两者皆空，58 个 `NOT_SEPARABLE`。

### 4.5 交付

- 逐题 `evidence/<cid>/enumeration.json`：`per_input` 含 `plus`、`p_minus`、`masking_sets`、`minimal_masking_sets`、`mmbs`、`empty_kept_masks`、`u_necessary`、`by_variant`（全部 KEEP 子集观测）、`relation`、`msms_status`、`mmbs_status`；旧文件保留为 `enumeration_v2_legacy.json`。
- `reference.json`：每题每个输入的 `msms`/`mmbs` 与 `mmbs_status`，并保留 `p_plus`/`p_minus`。
- `results/source_derived_v2_1_msms_mmbs.json`：独立重算的逐题逐输入结果。
- v2.1 acceptance：15 项检查/题，50/50 通过；旧 v2 验收保留在 `legacy_v2`。

## 5. M10 阴性对照复核

5 道 HELDOUT M10：`sd_attrs_tobool_nc`、`sd_jsonschema_pointer_nc`、`sd_multidict_version_nc`、`sd_pycodestyle_paths_nc`、`sd_toml_quote_nc`。

逐题核对结果（`results/source_derived_v2_1_m10_review.json`）：

| 条件 | 结果 |
|---|---|
| 所有声明输入 `P_MINUS != P_PLUS` | 5/5 是 |
| 空保留集复现 PLUS | 5/5 否 |
| 存在任何保留子集复现 PLUS | 5/5 否 |
| 存在非空极小掩盖集 | 5/5 否 |
| 存在合法极小掩盖集（含空集以外的定义） | 5/5 否 |

**措辞边界**：这只证明“该候选补丁在这些声明输入上不构成掩盖关系”，不能写成“操作 A 不存在任何掩盖关系”。同一 A 换一个候选补丁完全可以是正题——本次新增的 3 道 DEV NC 就是反过来构造的对照。

新增 DEV 阴性对照 3 题（不属于正式 50）：

| 题号 | 项目 | 错误候选 | 验收 |
|---|---|---|---|
| `sd_docutils_backticks_nc` | docutils | 用普通单引号替换 “``” | PASS |
| `sd_tabulate_1052_strip_nc` | tabulate | 只 `lstrip(" ")`，不处理尾随空格/Tab | PASS |
| `sd_pygments_bbcode64_nc` | Pygments | 关闭标签写成 `[/bgcolor]` | PASS |

3 题都满足：所有输入暴露、空集不复现 PLUS、无任何掩盖集。日志：`results/source_derived_v2_1_dev_nc_ext_verified.json`。

## 6. 复杂度审计

| 指标 | 结果 |
|---|---|
| 候选全集 U 大小 | 1→31 题；2→13 题；3→6 题；**50/50 题都只有 1–3 个候选** |
| 严格子集数 | 2→31；4→13；8→6 |
| 声明输入数 | 2→6 题；3→36 题；4→8 题 |
| 探针数 | 4→31；6→13；10→6 |
| 最大完整源文件 LOC | 2716（`sd_tabulate_2557_curlen`） |
| 最大 A 所在函数 LOC | 116（`sd_sqlparse_indentwidth_m9`） |
| 控制上下文层数 | 0→23；1→14；2→10；3→2；5→1 |
| 调用深度 | 1→15；2→18；3→7；4→9；6→1 |
| 跨函数题 | 5 |
| 无关候选 | 正式 50 题中 5 个，且全部在 M10 阴性对照里（U1 对结果无影响） |

**判定**：正式 50 题的候选搜索空间很小，绝大多数是 1–3 选 1 的判定；这适合做“关系是否成立”的精确题，但不适合评估大规模候选筛选能力。

扩展挑战集（不属于正式 50）：5 题，U=4/5/4/5/5，每题在真实 A 与原 U 不变的前提下加入 3 个干扰候选；干扰项都挂在声明输入中不存在的字符/条件上（NUL、CR、`&nbsp;`、`%`、反斜杠、`bgcolor`）。harness 与独立关系核验均 5/5 通过，变体总数 18/34。

## 7. 许可证与来源审计

`results/source_derived_v2_1_license_manifest.csv` / `.json` 覆盖 23 个项目。每行包含：项目、版本、slug、仓库 URL（及来源，如 PKG-INFO Project-URL）、sdist SHA-256、字节数、SPDX、声明的许可证、许可证文件、独立 NOTICE 文件、是否要求版权声明、声明摘录、是否允许再分发源码、再分发条件、推荐发行方式、审计时间。

| SPDX | 项目数 |
|---|---:|
| MIT | 13 |
| Apache-2.0 | 4（coverage、msgpack、multidict、requests） |
| BSD-3-Clause | 4（passlib、networkx、sqlparse、Markdown） |
| BSD-2-Clause | 1（Pygments） |
| `LicenseRef-docutils-compound` | 1（docutils） |

- 23/23 `redistribute_source_allowed = yes`，但都附带条件；22 个项目要求版权声明，docutils 要求“逐组件”携带声明。
- coverage 与 requests 带独立 NOTICE；docutils 是复合许可证（public domain + PSF-2.1.1 + BSD-2-Clause + GPL-3.0 等），必须整体携带 `COPYING.txt` 与 `licenses/`。
- **推荐**：对外只发行“补丁 + 固定版本下载脚本（含 sdist SHA-256）”，不打包上游源码；这不影响可复现性，也避免逐项目收集 NOTICE。若确需打包 sdist，按 manifest 的条件执行。

来源标识使用“版本 + sdist SHA-256”，不是 git commit SHA：本项目按 sdist 构建与复现，sdist 哈希是实际读取字节的标识；manifest 同时给出仓库 URL 便于追溯。

## 8. 时间戳与文件时间审计

- 扫描 `results/source_derived_v2_1_*.json` 与 v2.1 seal 中的时间字段：23 个，全部匹配 `YYYY-MM-DDTHH:MM:SSZ`，0 个非法（`results/source_derived_v2_1_timestamp_audit.json`）。
- v2.1 的结果文件统一使用 `2026-11-05T00:00:00Z` 作为本次发布的 as-of 时间；seal 使用实际封存时刻。文件 mtime 只作为文件系统元数据记录，不参与任何哈希或结论。
- 历史 v2 日志、v2 seal 与原始 acceptance 未改写；审计只读取并记录其 mtime。v2 seal 的 sha256 为 `52d10ce6741a157e922f459dbd31b8a20314e6a8766529dc14a170e0b05ab82b`，v2.1 的 diff 记录中再次引用该值。
- **不覆盖历史哈希**：v2.1 的差异记录保存每个变化文件的 v2/v2.1 双哈希；旧值不能通过“重算覆盖”消失。

## 9. 交付物索引

文档：

- `docs/MACE_source_derived_v2_1_quality_audit.md`（本文）
- `docs/MACE_source_derived_v2_1_final.md`

主结果：

- `results/source_derived_v2_1_inventory.csv`（50 行逐题字段）
- `results/source_derived_v2_1_statistics.json`
- `results/source_derived_v2_1_hash_manifest.json`
- `results/source_derived_v2_1_project_split.json`
- `results/source_derived_v2_1_license_manifest.csv` / `.json`

子集与辅助集：

- `results/source_derived_v2_1_project_disjoint_subset.json` / `.csv`（19 题）
- `results/source_derived_v2_1_template_disjoint_subset.json` / `.csv`（16 题）
- `results/source_derived_v2_1_template_audit.json`
- `results/source_derived_v2_1_m10_review.json`
- `results/source_derived_v2_1_complexity.json`
- `results/source_derived_v2_1_challenge_ext_manifest.json` / `..._verified.json`（5 题扩展挑战集）
- `results/source_derived_v2_1_dev_nc_ext_verified.json`（3 题 DEV NC）

独立验收与差异：

- `results/source_derived_v2_1_msms_mmbs.json`（独立重算；受污染首跑另存 `..._run1_contaminated.json`）
- `results/source_derived_v2_1_acceptance_summary.json`（50/50）
- `results/source_derived_v2_1_relation_correction.json`
- `results/source_derived_v2_1_function_corrections.json`
- `results/source_derived_v2_1_diff.json` / `..._diff_summary.md`
- `results/source_derived_v2_1_lf_normalization.json`
- `results/source_derived_v2_1_timestamp_audit.json`
- `results/source_derived_v2_1_workspace_manifest.json`

封存：

- `source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json` / `.md`（新建）
- `source_derived/heldout/seal/heldout_v2_seal.*`（原始，未修改）

## 10. 已知限制

1. 正式 50 题没有增删；HELDOUT 仍为 25 题，但只有 19 题项目隔离。6 道替换题未构建（任务书列为可选）。
2. 没有任何 HELDOUT 题同时具备“机制新 + 模板新”；不能对外宣称双重新颖。
3. 每题材只有 1–3 个候选；扩展挑战集是辅助集，不改变正式 50 题的统计。
4. M10 阴性对照是“候选补丁特定”的，不是“操作 A 全称”的。
5. `sd_docutils_optionxform_m2` 是 v2 遗留的无 case/无 task 的 evidence 目录；为不破坏证据而保留在 v2.1，但不属于正式 50，也不计入任何统计。
6. 本次审计在数据集侧完成，未运行或修改 MACE 算法，也未读取算法窗口代码。

**审计到此停止，等待独立复核。**
