# MACE Source-derived v2.1：最终报告

- 日期：2026-11-05（UTC）
- 范围：`SOURCE_DERIVED_CONTROLLED` 正式 50 题（DEV 25 / HELDOUT 25）
- 基线：`source_derived/`（v2，只读冻结）
- 产物：`source_derived_v2_1/`（全部修改在独立目录）
- 状态：数据集侧修复完成，50/50 通过 v2.1 独立验收；**等待独立复核，未进入算法窗口**

## 一、这次到底改了什么

| 类别 | 修复前 | 修复后 |
|---|---|---|
| 正式题数 | 50 | 50（未增删、未替换、未改判） |
| MMBS | 35 题中存在错误，根因是直接复制 MSMS | 从禁用集观测表独立重算；50/50 与独立核验一致 |
| 空集极小集 | 38 个输入把 `[]` 当成极小集 | 非空极小集；空集只抑制、不输出 |
| 非空 MSMS | — | **没有算错**；38 个变化全是删除空集 artifact |
| 函数名 | 3 处嵌套 helper 误记为函数名 | 改为最内层 AST 函数，并补 `related_functions` |
| API 元数据 | 25 道 HELDOUT 题为占位符 `see probe` | 记录具体调用点；10 道旧 DEV 题原文保留 |
| 交付哈希 | CRLF 交付字节与 LF 枚举哈希不一致 | 统一 LF；50/50 题交付/枚举/来源哈希一致 |
| 验收 | v2 验收不含上述检查 | v2.1 每题 15 项检查，50/50 通过；旧验收保留在 `legacy_v2` |
| HELDOUT seal | 只有 v2 seal | 新建 v2.1 seal；v2 seal 未修改 |

正式 50 题的 case 规格、probe、A 行、U 块、DEV/HELDOUT 划分与机制指派都没有改。reference 的变化是**关系更正**，不是改题。

## 二、七个必答问题

### （1）50 道题是否仍然全部有效？

**是，作为“声明输入 + 声明候选全集”的有限域题，50/50 有效。**

- 50/50 通过 v2.1 独立验收（`results/source_derived_v2_1_acceptance_summary.json`）。
- 独立核验器重新解压 sdist、重跑全部 probe、自行枚举全部子集；v2.1 reference 与独立结果 50/50 一致。
- 每题都有完整的 MSMS/MMBS/全子集观测/极小性证据。

但“有效”不等于“适合所有主张”：

- 25 道 HELDOUT 中只有 19 道项目隔离、16 道模板隔离，**14 道同时满足两者**。
- 每题材只有 1–3 个候选，不适合评估大规模候选筛选。

### （2）是否存在真正的标准答案错误？

**是。旧版有两类真错，v2.1 已修复。**

1. **MMBS 错**：实现把 `mmbs = minimal_masking_sets`，共影响 58 个输入 / 35 题。其中：
   - 20 个输入 / 19 题的非空 MMBS 确实算错。例如 coverage 旧值 `[[U1,U2]]`，正确值是 `[[U1],[U2]]`；docutils ellipsis 旧值 `[[U1,U2,U3]]`，正确值是三个单元素集。
   - 38 个输入只是空集 artifact，去掉 `[]` 后与正确值相同。
2. **空集被当成极小集**：38 个输入 / 34 题把 `[]` 写进 MSMS/MMBS。按冻结定义，极小集必须非空；空保留集若已复现 PLUS，只抑制非空 MSMS。

**没有发现的错误**：非空 MSMS 一个也没有算错。函数名错误 3 处、API 占位符 25 处属于元数据缺陷，不是关系答案错误。

### （3）MMBS 是否独立、正确地计算了？

**是。**

- 独立实现不调用构造脚本：重新解压 sdist、自己生成变体文本、`runpy` 跑 probe、按位掩码枚举、自己做极小性判定。
- MMBS 只在该输入 `P_MINUS == PLUS` 时定义；否则标记 `NOT_SEPARABLE`，不伪造空集或占位值。
- 正式 50 题共 155 个输入：97 个 `MASKED`、58 个 `EXPOSING`（= `NOT_SEPARABLE`）；59 个输入有非空 MSMS，59 个有非空 MMBS，38 个因空集抑制两者皆空。
- v2.1 reference 与独立结果在 50/50 题上逐输入一致；`AC_v2_1_mmbs_only_when_masked`、`AC_v2_1_not_separable_marking`、`AC_v2_1_minimal_sets_nonempty` 全部通过。

### （4）HELDOUT 是否存在项目泄漏？

**是，存在。**

- DEV 10 个项目，HELDOUT 17 个，交集 4 个：attrs、isort、jsonschema、toml。
- 6/25 道 HELDOUT 与 DEV 同项目，且版本相同。
- 更严重的是 2 个题目与 DEV **同文件同 A 行**：`jsonschema/validators.py:1145`、`toml/encoder.py:97`。
- 项目隔离子集：19 题 / 13 个项目；机制分布 M2=3、M3=3、M6=3、M10=2、M5=2、M8=2、M9=2、M4=1、M7=1。

**没有做**：没有构建 6 道替换题来恢复 25 题项目隔离可用集。任务书把替换列为可选；本次选择不新建、不用替换题冒充原题，只交付诚实的 19 题子集和 6 题缺口清单（M10×3、M4×2、M5×1）。

### （5）HELDOUT 是否存在模板泄漏？

**是，存在模板级泄漏，但没有“机制 + 模板”双重新颖的题。**

- 25 道 HELDOUT 中，9 道使用 DEV 已出现的构造模板：
  - 1 道模板与机制都相同（`sd_jedi_param_hyphen_m2`，M2）；
  - 8 道模板相同但机制不同。
- 16 道模板未在 DEV 出现，但它们的机制都在 DEV 出现。
- **0 道同时具备机制新 + 模板新。**
- 模板隔离子集 16 题；与项目隔离子集交集 14 题。

**结论**：可以说“16 题模板隔离”，不能说“HELDOUT 是未见机制/未见模板的挑战集”，更不能说“双新”。

### （6）哈希与函数元数据是否正确？

**修复后正确。**

- 50/50 题：source 哈希三方一致（sdist 源文件 / evidence original / 旧 acceptance），交付 patched 哈希 = 实际字节 = enumeration 哈希，`patch.diff` 为 LF。
- 50/50 题：`function` 等于最内层 AST 函数，`related_functions` 覆盖 A 函数与所有 U 锚点函数；3 处旧错误已改正。
- 50/50 题：v2.1 acceptance 15 项检查全部通过；旧 v2 结论与哈希未删除，保存在 `legacy_v2`。
- 旧版 CRLF 缺陷已消除：v2.1 全部交付文本为 LF，且同时给出 delivered 与 logical 两个哈希，避免再次出现“哈希与字节对不上”。
- 历史哈希没有被覆盖：`results/source_derived_v2_1_diff.json` 保存每个变化文件的 v2/v2.1 双哈希。

### （7）是否已经可以公开发布？

**条件性可以；不建议无条件发布。**

可以发布的部分：

- 数据集侧质量缺陷已修复，50/50 独立验收通过；
- 原始 v2 完整保留，v2.1 差异可逐文件审计；
- 许可证与来源清单完整；
- 阴性对照、项目/模板子集、扩展挑战集、时间戳审计齐全。

发布前必须披露或处理的事项：

1. **项目泄漏**：6/25 道 HELDOUT 与 DEV 同项目。若论文主张“跨项目泛化”，必须改用 19 题项目隔离子集，或先补 6 道替换题。
2. **模板泄漏**：9/25 道 HELDOUT 共享 DEV 模板，0 道双新。不能使用“unseen mechanism/template”措辞。
3. **候选规模**：正式题只有 1–3 个候选。需要候选筛选能力的主张应使用扩展挑战集，且要注明它是辅助集。
4. **阴性对照语义**：M10 只证明“该候选补丁在这些输入上不构成掩盖关系”，不能写成“A 没有掩盖关系”。
5. **docutils 复合许可证**：若打包上游源码，必须整体携带 `COPYING.txt` 与 `licenses/`；更稳妥的是只发补丁 + 固定版本下载脚本。
6. **一个遗留目录**：`sd_docutils_optionxform_m2` 是无 case/无 task 的 v2 evidence 目录，不属于正式 50；为不破坏证据而保留，发布时应排除或注明。

**建议发布口径**：

> v2.1 修复了 MMBS、空集极小集、函数元数据、API 占位符与 CRLF 哈希五类缺陷；正式 50 题全部通过独立验收。项目泛化结论请使用 19 题项目隔离子集；模板泛化结论请使用 16 题模板隔离子集；两者交集 14 题。数据集不声称 HELDOUT 具备“未见机制 + 未见模板”的双重新颖性。

## 三、独立复核入口

| 复核对象 | 文件 |
|---|---|
| 逐题字段 | `results/source_derived_v2_1_inventory.csv` |
| 统计口径 | `results/source_derived_v2_1_statistics.json` |
| 哈希 | `results/source_derived_v2_1_hash_manifest.json` |
| 独立重算 | `results/source_derived_v2_1_msms_mmbs.json` |
| 验收 | `results/source_derived_v2_1_acceptance_summary.json` 与每题 `acceptance.json` |
| 项目隔离 | `results/source_derived_v2_1_project_split.json`、`..._project_disjoint_subset.json` |
| 模板隔离 | `results/source_derived_v2_1_template_audit.json`、`..._template_disjoint_subset.json` |
| 差异 | `results/source_derived_v2_1_diff.json`、`..._diff_summary.md` |
| NC | `results/source_derived_v2_1_m10_review.json`、`..._dev_nc_ext_verified.json` |
| 扩展挑战集 | `results/source_derived_v2_1_challenge_ext_manifest.json`、`..._verified.json` |
| 许可证 | `results/source_derived_v2_1_license_manifest.csv` |
| 封存 | `source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json` |

## 四、停止声明

本次工作只修改数据集侧 `source_derived_v2_1/`、`docs/` 与 `results/`。未修改 MACE 算法、Graph、Qwen Prompt、AST 搜索器或 Verifier；未调用 GPU；未覆盖 v2；未删除原始 acceptance/evidence；未修改 v2 seal；未把 HELDOUT 答案写入算法窗口。

**到此停止，等待独立复核。**
