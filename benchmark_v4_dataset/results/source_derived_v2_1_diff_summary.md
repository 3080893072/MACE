# MACE Source-derived v2 → v2.1 差异记录

基线 `source_derived/`（v2）保持只读；所有改动在 `source_derived_v2_1/` 完成。

## 文件层面

- v2 文件：533；v2.1 文件：722；共同文件：531
- 完全相同：82；仅换行符不同：208；内容改变：241
- 仅 v2 有：2（冻结的 v2 seal，未复制进 v2.1）；仅 v2.1 有：191

内容改变（按类别）：

| 类别 | 文件数 |
|---|---:|
| acceptance | 85 |
| enumeration | 51 |
| provenance | 35 |
| reference | 35 |
| task | 35 |

## 关系更正

- 受影响题目：**35/50**
- MSMS 发生变化的输入：**38**
- MMBS 发生变化的输入：**58**

| 题号 | MSMS 变化输入 | MMBS 变化输入 |
|---|---:|---:|
| sd_coverage_glob_backslash_m2 | 1 | 2 |
| sd_docutils_backticks_m1 | 1 | 1 |
| sd_docutils_educate_dashes_m2 | 1 | 2 |
| sd_docutils_ellipsis_m3 | 1 | 2 |
| sd_docutils_language_tag_m3 | 1 | 2 |
| sd_docutils_make_id_nonid_m2 | 1 | 2 |
| sd_docutils_smartquotes_strip_m1 | 1 | 1 |
| sd_docutils_stupefy_emdash_m2 | 1 | 2 |
| sd_docutils_stupefy_endash_m1 | 1 | 1 |
| sd_humanize_filesize_gnu_m5 | 1 | 1 |
| sd_isort_format_strip_m4 | 1 | 2 |
| sd_jsonschema_1145_pointer | 1 | 1 |
| sd_networkx_gexf448_slices | 2 | 2 |
| sd_pygments_bbcode64_color | 1 | 2 |
| sd_pygments_bbcode70_italic | 1 | 3 |
| sd_pygments_groff73_italic | 1 | 2 |
| sd_pygments_latex297_italic | 1 | 1 |
| sd_tabulate_1052_strip_right | 2 | 2 |
| sd_tabulate_1056_strip_center | 2 | 2 |
| sd_tabulate_2557_curlen | 2 | 2 |
| sd_toml_strict_num_strip_m1 | 1 | 1 |
| sd_h11_comma_header_m5 | 1 | 1 |
| sd_jedi_param_hyphen_m2 | 1 | 2 |
| sd_jsonschema_pointer_m4 | 1 | 2 |
| sd_markdown_attrib_m3 | 1 | 2 |
| sd_markdown_cdata_m2 | 1 | 2 |
| sd_multidict_version_m6 | 1 | 1 |
| sd_passlib_hashname_m2 | 0 | 1 |
| sd_passlib_name_norm_m3 | 1 | 2 |
| sd_pyyaml_int_underscore_m3 | 1 | 2 |
| sd_requests_contenttype_m7 | 1 | 1 |
| sd_simplejson_decoder_m6 | 1 | 1 |
| sd_simplejson_htmlamp_m4 | 1 | 2 |
| sd_sqlparse_indentwidth_m9 | 1 | 1 |
| sd_toml_quote_escape_m4 | 1 | 2 |

## 函数元数据更正

| 题号 | 旧值 | 新值 | 依据 |
|---|---|---|---|
| sd_networkx_gexf448_slices | `edge_key_data` | `add_edges` | recorded name is a nested helper defined inside the enclosing function but does not contain A |
| sd_pygments_latex297_italic | `rgbcolor` | `_create_stylesheet` | recorded name is a nested helper defined inside the enclosing function but does not contain A |
| sd_pygments_style95_cache | `colorformat` | `__new__` | recorded name is a nested helper defined inside the enclosing function but does not contain A |

## 保留与新增

- 50 道题、题号、DEV/HELDOUT 划分、机制指派、case 规格与 probe 均未改。
- v2 seal 未修改（sha256 `52d10ce6741a157e922f459dbd31b8a20314e6a8766529dc14a170e0b05ab82b`）。
- 新增：项目隔离子集、模板隔离子集、5 题扩展挑战集、3 题 DEV NC、v2.1 seal、v2.1 acceptance 与独立 MSMS/MMBS 核验日志。

完整逐文件哈希见 `results/source_derived_v2_1_diff.json`。
