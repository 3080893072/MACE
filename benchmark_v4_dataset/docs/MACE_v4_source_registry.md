# MACE V4 数据源登记表（Broad Discovery 轮）

- 生成时间：2026-11-04
- 元数据来源：`https://pypi.org/pypi/<name>/<version>/json`（经 `curl --ssl-no-revoke` 获取）
- 下载完整性：70/70 sdist 的 SHA-256 与 PyPI 官方摘要逐位一致（`broad_manifest.py verify`）
- HELDOUT_BROAD 封存哈希：`2d961e2e58f4116b8c4d0c820c28e8866fa74c0d0b602cb24879578f49dd08e3`；封存时间早于任何源码读取；未解封。

## 1. DEV 扫描池（58 个项目，已解包并做 AST 扫描）

| 项目 | 版本 | License | requires-python | 测试文件数 | 原始测试 | sdist SHA-256（前16） |
|---|---|---|---|---:|---|---|
| attrs | 23.2.0 | MIT License | >=3.7 | 25 | yes | `935dc3b529c262f6` |
| cattrs | 23.2.3 | MIT | >=3.8 | 37 | yes | `a934090d95abaa9e` |
| cerberus | 1.3.5 | ISC License  Copyright (c) 2012-2016 Nic |  | 0 | no | `81011e10266ef71b` |
| cloudpickle | 3.0.0 | BSD-3-Clause | >=3.8 | 0 | no | `996d9a482c6fb4f3` |
| coverage | 7.4.0 | Apache-2.0 | >=3.8 | 39 | yes | `707c0f58cb1712b8` |
| decorator | 5.1.1 | new BSD License | >=3.5 | 0 | no | `637996211036b638` |
| diskcache | 5.6.3 | Apache 2.0 | >=3 | 7 | yes | `2c3a3fa2743d8535` |
| docutils | 0.20.1 | public domain, Python, 2-Clause BSD, GPL | >=3.7 | 138 | yes | `f08a4e276c3a1583` |
| ecdsa | 0.18.0 | MIT | >=2.6, !=3.0.*, !=3.1.*, !=3.2.* | 13 | yes | `190348041559e21b` |
| exceptiongroup | 1.2.0 | MIT License | >=3.7 | 7 | yes | `91f5c769735f051a` |
| execnet | 2.0.2 | MIT License | >=3.7 | 11 | yes | `cc59bc4423742fd7` |
| filetype | 1.2.0 | MIT |  | 6 | yes | `66b56cd6474bf41d` |
| flake8 | 7.0.0 | MIT | >=3.8.1 | 0 | no | `33f96621059e65ee` |
| h11 | 0.14.0 | MIT | >=3.7 | 9 | yes | `8f19fbbe99e72420` |
| httpcore | 1.0.2 | BSD License | >=3.8 | 17 | yes | `9fc092e4799b2617` |
| humanize | 4.9.0 | MIT | >=3.8 | 4 | yes | `582a265c931c683a` |
| importlib_resources | 6.1.1 | Apache Software License | >=3.8 | 9 | yes | `3893a00122eafde6` |
| iniconfig | 2.0.0 | MIT License | >=3.7 | 0 | no | `2d91e135bf72d31a` |
| isort | 5.13.2 | MIT | >=3.8.0 | 41 | yes | `48fdfcb9face5d58` |
| jedi | 0.19.1 | MIT | >=3.6 | 55 | yes | `cf0496f3651bc65d` |
| jsonschema | 4.20.0 | MIT | >=3.8 | 8 | yes | `4f614fd46d8d6125` |
| lark | 1.1.9 | MIT | >=3.6 | 13 | yes | `15fa5236490824c2` |
| Markdown | 3.5.1 | Copyright 2007, 2008 The Python Markdown | >=3.8 | 30 | yes | `b65d7beb248dc22f` |
| mccabe | 0.7.0 | Expat license | >=3.6 | 1 | yes | `348e0240c33b60bb` |
| more-itertools | 10.1.0 | MIT License | >=3.8 | 2 | yes | `626c369fa0eb37ba` |
| msgpack | 1.0.7 | Apache 2.0 | >=3.8 | 17 | yes | `572efc93db7a4d27` |
| multidict | 6.0.4 | Apache 2 | >=3.7 | 12 | yes | `3666906492efb764` |
| networkx | 3.2.1 | BSD License | >=3.9 | 256 | yes | `9f1bb5cf3409bf32` |
| parsimonious | 0.10.0 | MIT |  | 4 | yes | `8281600da180ec8a` |
| parso | 0.8.3 | MIT | >=3.6 | 21 | yes | `8c07be290bb59f03` |
| passlib | 1.7.4 | BSD |  | 26 | yes | `defd50f72b65c540` |
| pluggy | 1.3.0 | MIT | >=3.8 | 8 | yes | `cf61ae8f126ac6f7` |
| py | 1.11.0 | MIT license | >=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.* | 26 | yes | `51c75c4126074b47` |
| pycodestyle | 2.11.1 | MIT | >=3.8 | 11 | yes | `41ba0e7afc9752df` |
| pyflakes | 3.1.0 | MIT | >=3.8 | 11 | yes | `a0aae034c444db00` |
| Pygments | 2.17.2 | BSD-2-Clause | >=3.7 | 34 | yes | `da46cec9fd2de5be` |
| PyJWT | 2.8.0 | MIT | >=3.7 | 10 | yes | `57e28d156e3d5c10` |
| Pympler | 1.0.1 | Apache License, Version 2.0 | >=3.6 | 11 | yes | `993f1a3599ca3f4f` |
| pyrsistent | 0.20.0 | MIT | >=3.8 | 18 | yes | `4c48f78f62ab596c` |
| pytest | 7.4.4 | MIT | >=3.7 | 116 | yes | `2cf0005922c6ace4` |
| python-dateutil | 2.8.2 | Dual License | !=3.0.*,!=3.1.*,!=3.2.*,>=2.7 | 14 | yes | `0123cacc1627ae19` |
| pytz | 2023.3.post1 | MIT |  | 3 | yes | `7b4fddbeb94a1eba` |
| PyYAML | 6.0.1 | MIT | >=3.6 | 22 | yes | `bfdf460b1736c775` |
| requests | 2.31.0 | Apache 2.0 | >=3.7 | 9 | yes | `942c5a758f98d790` |
| rfc3986 | 2.0.0 | Apache 2.0 | >=3.7 | 10 | yes | `97aacf9dbd4bfd82` |
| rsa | 4.9 | Apache-2.0 | >=3.6,<4 | 0 | no | `e38464a49c6c85d7` |
| schema | 0.7.5 | MIT |  | 1 | yes | `f06717112c61895c` |
| simplejson | 3.19.2 | MIT License | >=2.5, !=3.0.*, !=3.1.*, !=3.2.* | 30 | yes | `9eb442a2442ce417` |
| sqlparse | 0.4.4 | BSD License | >=3.5 | 10 | yes | `d446183e84b8349f` |
| tabulate | 0.9.0 | MIT | >=3.7 | 7 | yes | `0095b12bf5966de5` |
| tenacity | 8.2.3 | Apache 2.0 | >=3.7 | 4 | yes | `5398ef0d78e63f40` |
| toml | 0.10.2 | MIT | >=2.6, !=3.0.*, !=3.1.*, !=3.2.* | 2 | yes | `b3bda1d108d5dd99` |
| toolz | 0.12.0 | BSD | >=3.5 | 12 | yes | `88c570861c440ee3` |
| urllib3 | 2.1.0 | MIT License | >=3.8 | 29 | yes | `df7aa8afb0148fa7` |
| voluptuous | 0.14.2 | BSD-3-Clause | >=3.8 | 0 | no | `533e36175967a310` |
| wheel | 0.42.0 | MIT License | >=3.7 | 11 | yes | `c45be39f7882c9d3` |
| wrapt | 1.16.0 | BSD | >=3.6 | 31 | yes | `5f370f952971e7d1` |
| zipp | 3.17.0 | MIT License | >=3.8 | 3 | yes | `84e64a1c28cf7e91` |

## 2. HELDOUT_BROAD 封存池（12 个项目，未解包、未读源码、未扫描）

| 项目 | 版本 | License | requires-python | sdist SHA-256（前16） |
|---|---|---|---|---|
| aiofiles | 23.2.1 | Apache-2.0 | >=3.7 | `84ec2218d8419404` |
| bitstring | 4.1.2 | MIT License | >=3.7 | `c22283d60fd3e1a8` |
| blinker | 1.7.0 | MIT License | >=3.8 | `e6820ff6fa4e4d1d` |
| boltons | 23.1.1 | BSD |  | `d2cb2fa83cf2ebe7` |
| cachetools | 5.3.2 | MIT | >=3.7 | `086ee420196f7b2a` |
| cssselect | 1.2.0 | BSD | >=3.7 | `666b19839cfaddb9` |
| docopt | 0.6.2 | MIT |  | `49b3a825280bd66b` |
| feedparser | 6.0.11 | BSD-2-Clause | >=3.6 | `c9d0407b64c6f2a0` |
| jsonpointer | 2.4 | Modified BSD License | >=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, !=3.5.*, !=3.6.* | `585cee82b70211fa` |
| pathspec | 0.12.1 | Mozilla Public License 2.0 (MPL 2.0) | >=3.8 | `a482d51503a1ab33` |
| tqdm | 4.66.1 | MPL-2.0 AND MIT | >=3.7 | `d88e651f9db8d855` |
| xmltodict | 0.13.0 | MIT | >=3.4 | `341595a488e3e01a` |

## 3. 与既有 V3 / Phase-1 HELDOUT 的关系

- 既有 8 个 HELDOUT（chardet、filelock、idna、MarkupSafe、platformdirs、sortedcontainers、tomli、wcwidth）保持封存，未进入本轮任何流程。
- V3 的 Jinja2/Werkzeug 只作回归参考，不计入本轮统计。
- 本轮新增 70 个项目中，58 个进入 DEV 扫描池，12 个进入 HELDOUT_BROAD 封存池。

## 4. 出处、版本与校验口径

| 字段 | 口径 |
|---|---|
| 项目名 / 版本 | PyPI 发布版本（`name==version`），不是 clone 的 HEAD |
| release / commit SHA | **sdist 不携带 git commit**。出处以 `name==version` + sdist SHA-256 固定；表中 SHA-256 为完整摘要的前 16 位，完整值见 `discovery/manifest/source_registry.json`。未对任何项目断言 commit SHA |
| License | 取 PyPI JSON `info.license`（原样），不做 SPDX 归一化 |
| Python 版本 | 项目在 `discovery/sources/<slug>/` 下的独立 venv（`<local-path>`），版本记录在 `discovery/stage2_3/<slug>.env.json` |
| 原始测试入口 | `discovery/stage0/projects.json` 的 `test_roots` / `test_file_count`；实际 pytest 入口记录在每个项目的 `plus.summary.json.command` |
| 依赖/环境 | 每个项目的 `env.json` 记录 bootstrap 与 install 步骤、返回码和超时；构建失败的项目原样记录，不替换 |
| 校验和 | sdist SHA-256 逐位与 PyPI 官方摘要一致（`tools/broad_manifest.py verify`），70/70 通过 |

复现：`python -I benchmark_v4_dataset/tools/broad_manifest.py verify` 重新比对全部
sdist；`docs/MACE_v4_broad_dataset_mining.md` §2 给出封存哈希与顺序。
