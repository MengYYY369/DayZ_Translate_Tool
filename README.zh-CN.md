# DayZ 翻译工具

[![release](https://img.shields.io/github/v/release/MengYYY369/DayZ_Translate_Tool?label=release&color=4c1)](https://github.com/MengYYY369/DayZ_Translate_Tool/releases)
![许可证](https://img.shields.io/badge/license-GPL--3.0-blue)
![平台](https://img.shields.io/badge/platform-Windows-0078d4)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![界面](https://img.shields.io/badge/UI-Qt%206%20%C2%B7%20PySide6-41cd52)
![测试](https://img.shields.io/badge/tests-570%20passing-4c1)

[English](README.md) · **简体中文**

给 DayZ 模组本地化用的桌面翻译工具。打开模组里的 `stringtable.csv`，让不用密钥的免费源或者你自己的 AI 接口把选中的列翻掉，再存回去 —— 不用再一行行复制到网页翻译里。

![主界面](docs/images/main-window.zh-CN.png)

## 功能

### 翻译源随便搭

- **六个不用密钥的免费源** —— 谷歌、微软翻译、腾讯交互翻译、火山翻译、Lara 翻译、MyMemory。不用注册、不用填密钥，装好就能用。
- **DeepL** —— 可选，用你自己的密钥。
- **AI 翻译源** —— 任何走 OpenAI 对话格式的接口，另外 Claude、Codex 也能加。想加几个加几个，每个源单独填密钥、模型、并发数和请求间隔。
- **优先级 + 自动接力** —— 源列表是有顺序的：排在上面的先用。翻到一半挂了，剩下的自动交给下一个源，状态栏会提示换了哪个源。
- **每个源单独的适用范围** —— 每个源自己带勾选框：*全表*、*只翻空白格*、*只翻选中部分*。顺序加上勾选规则，一起决定这次翻译到底用哪些源。
- **每个源都有测试按钮** —— 点一下就发一条 4 种语言的测试，成功直接看结果，失败直接看真实报错。
- **重试与限速** —— 失败会按指数退避重试，也尊重服务端给的 `Retry-After`。并发数和间隔按源单独设，不容易被限流限死。翻完一轮还能只重试失败的那些格子。

### 翻译跟着表格走

- **想翻哪儿就翻哪儿** —— 全表翻译、只翻空白格，或者只翻你选中的部分（右键 → 选中的格 / 行 / 列）。
- **翻译缓存** —— 翻过的内容按源、原文、语言缓存下来，关掉软件再开也还在。
- **术语表 / 单词本** —— 你自己维护的 `wordbook.csv`，命中的词条会作为术语交给 AI 源，让专有名词前后一致。
- **长文本会按换行切开** 来适配单个源的长度限制，同一格被切开的部分之间不共享上下文。

### 自带质量检查

- **27 条本地规则**把翻完的译文扫一遍，把可疑的格子标出来：占位符丢了、数字对不上、标点用了全角、直接抄了原文、术语表里的词没用上……
- **只标不改** —— 不修改内容，也不联网。可以只看被标出来的格子，然后只重翻这几个。

### 表格本身也能编辑

- **读写 DayZ 的 `stringtable.csv`** —— 游戏标准的 15 列格式，带不带 BOM 的 UTF-8 都能读。打开时会自动修坏行：按表头名字对齐列、少列的补齐、多出来的截掉。
- **撤销/重做和各种表格操作** —— 插入或删除行列、清空格子、用一格填满整行、重置列顺序，还有支持全词匹配和区分大小写的查找。
- **从 `config.cpp` 导入键名** —— 可以选一个文件、几个文件，也可以直接选文件夹，把表里还缺的键名批量找出来。
- **自动分词** —— 源语言列里粘成一坨的英文（`AsaraShotGun`、`VirusHealerAngelBP`），选中后右键 → `自动分词`，就拆成 `Asara Shot Gun`、`Virus Healer Angel BP`。只有整格都是粘连词的才拆，`AK74`、`M4A1` 这种带数字的枪名原样不动。
- **界面语言** —— 中文和英文。

## 界面截图

翻译源设置 —— 有序的源列表、每个源的适用范围和测试按钮：

![翻译源设置](docs/images/translation-sources.zh-CN.png)

添加 AI 翻译源（这里填的是一个免费的公共接口）：

![添加 AI 源](docs/images/add-ai-source.zh-CN.png)

<details>
<summary>English screenshots</summary>

![Main window](docs/images/main-window.png)
![Translation sources](docs/images/translation-sources.png)

</details>

## 快速开始

需要：**Windows**、**Python 3.10 以上**（界面用的是 Qt 6，通过 PySide6）。

```bash
pip install -r requirements.txt
python main.py
```

也可以直接到[发布页](../../releases)下载打包好的 `DayZ_Translate_Tool`，双击 exe 就能用。

## 怎么用

1. **打开文件** —— `文件 → 打开`（`Ctrl+O`），选模组里的 `stringtable.csv`，一般在这个位置：`<模组>\addons\<某个文件夹>\stringtable.csv`。
2. **告诉它你已经有哪一列** —— `设置 → 源语言`，选你手上已经有译文的那一列（通常是 `english`）。这一列永远不会被覆盖。
3. **挑翻译源** —— `设置 → 翻译源设置…`。勾上每个源的勾选框，决定它能不能参与「全表 / 空白格 / 右键选中」；用 ▲▼ 调顺序（上面的优先），用 ▶ 单独测一个源。
4. **开始翻译** —— `文件 → 翻译全表` / `翻译空白格`，或者选中若干格后右键 → `翻译选中的格`。状态栏会显示进度和「成功 / 失败 / 命中缓存」的数量，随时可以取消。
5. **保存** —— `Ctrl+S`。`original` 列会自动复制 `english` 列、`chinese` 列会自动复制 `chinesesimp` 列，跟游戏要求的一致。

### 添加一个免费的 AI 源

有些公共接口用的就是 OpenAI 的对话格式，而且完全不用密钥。

`设置 → 翻译源设置… → + 添加 AI 源`

| 字段 | 例子 |
|---|---|
| 名称 | `Index-Translate` |
| 接口类型 | `OpenAI 兼容` |
| 接口地址 | `https://index-translate.bilibili.com/v1` |
| 密钥 | 随便填点非空内容（比如 `index`），留空不让保存 |
| 模型 | `Index-Translate-35B-A3B` |

这个接口来自 [Index-Translate](https://github.com/bilibili/Index-Translate) 项目。能不能用、有没有额度限制都是那边说了算，当成额外的福利源就好，别当成稳定的服务。

## 命令行

<details>
<summary>不打开窗口也能用整套功能</summary>

整工具也能不开窗口跑，写脚本或者让 AI 自己动手改表都很方便。命令行走的是和界面完全一样的那套代码、同一份设置，所以你在 `设置 → 翻译源设置…` 里配好的翻译源，命令行用的就是它。

```bash
python cli.py <命令> [参数]
```

| 命令 | 干什么 |
|---|---|
| `inspect <csv>` | 列出有几列、每个语言列有多少格有内容、哪些行没有原文 |
| `translate <csv>` | 翻译表格；`--mode empty`（默认）/ `all` / `columns` / `rows`，还能用 `--columns a,b`、`--rows 3,5-9`、`--only-empty`、`--source 源ID`、`--from-column english`、`--wordbook 路径` 再收窄 |
| `edit set-cell <csv> --row N --column 列名 --text "..."` | 改一个格子 |
| `edit replace <csv> --column 列名 --find 旧 --replace 新 [--regex] [--ignore-case] [--whole-word]` | 在一列里批量查找替换 |
| `edit add-row <csv> --key 键名 [--after N]` | 加一行 |
| `edit delete-row <csv> --row N` / `--key 键名` | 删一行 |
| `keys <csv> --from <config.cpp 或文件夹>` | 把模组 `config.cpp` 里缺的键导进来 |
| `wordbook list` / `set --original X --language chinesesimp --text 刀` / `remove --original X` / `import <csv>` / `export <csv>` | 读改术语表 |
| `sources list` / `test [--source 源ID]` / `add-ai ...` / `remove 源ID` / `move 源ID --up` / `--down` / `set-rule 源ID --rules all,empty` / `set-key 源ID --key ...` | 读改翻译源列表 |
| `cache stats` / `clear` | 看缓存或者清空缓存 |

所有命令都支持 `--json`（结果以 JSON 打到屏幕、进度打到错误输出）和 `--quiet`。

**不主动说写就不写。** `translate`、`edit` 和 `keys` 只读原文件，结果写进预览文件（默认是 `stringtable.preview.csv`，可以用 `--preview` 指定）。要真改原文件就加 `--write`，这时会先存一份 `.bak` 备份。只动设置的命令（`sources`、`wordbook`、`cache`）立即生效 —— 界面开着的话重开一下才看得到。

退出码：`0` 全部成功、`1` 跑完了但有失败（有格子没翻成，或者 `sources test` 没测通）、`2` 命令根本没跑起来。

几个常用例子：

```bash
python cli.py inspect stringtable.csv
python cli.py translate stringtable.csv --mode empty --json
python cli.py translate stringtable.csv --write
python cli.py sources test
```

</details>

## 注意事项和已知限制

<details>
<summary>翻整张表之前先看一眼</summary>

- **免费源都是非官方接口。** 它们就是浏览器在用的那些公共地址，随时可能被限流或者改掉。实际使用中，谷歌翻几十条就开始返回 `HTTP 429`，MyMemory 每天大概只给你 5000 个字符。软件会把这些报错如实显示出来，不会假装成功，同时自动接力把剩下的交给下一个源。
- **免费源只能翻文本。** 术语表（单词本）只对 AI 源生效，因为那些免费接口没法把术语传进去。
- **一次只吃一条的源**（火山、Lara、MyMemory）每次请求只接受一条文本，所以翻大表会发很多次请求；记得给它们设个合理的间隔，并且把更快的源排在它们上面。
- **长文本会按换行切开** 以适配单个源的长度限制，同一格被切开的部分之间不共享上下文。
- **DeepL 需要密钥**，所以出厂是关着的。其它源装好就能用。
- 界面会跟随 Windows 的浅色/深色主题。

</details>

## 软件会写哪些文件

| 文件 | 位置 | 用途 |
|---|---|---|
| `stringtable.csv` | 你保存的地方（默认是 exe 旁边） | 模组的翻译文本 |
| `wordbook.csv` | `%LOCALAPPDATA%\DayZTranslateTool\...`（需要时自动创建） | 你的术语表 |
| `translation_cache.json` | exe 旁边；如果那个目录不能写，就退到 `%LOCALAPPDATA%\DayZ_Translate_Tool\` | 翻译缓存 |
| 软件设置 | Windows 注册表 `HKCU\Software\DayZTranslateTool` | 翻译源、勾选规则、窗口状态、界面语言 |

## 打包成单独的 exe

<details>
<summary>PyInstaller 打包</summary>

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
# 也可以指定用哪个 Python：
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -PythonPath "C:\Python313\python.exe"
```

脚本会自动安装并使用 PyInstaller，产物在 `dist\DayZ_Translate_Tool\`。因为打包过程会清空输出目录，脚本会先把 exe 旁边的 `stringtable.csv` / `wordbook.csv` 备份出来，打完再还原。

</details>

## 开发

<details>
<summary>代码结构和测试</summary>

```bash
python -m unittest discover -s tests     # 570 个测试，不需要联网
```

| 文件 | 负责什么 |
|---|---|
| `main.py` | 界面窗口、表格、各种对话框、菜单、设置读写 |
| `dayz_csv.py` | stringtable.csv 的读写、修行、生成翻译任务 |
| `wordbook_csv.py` | 术语表的文件格式 |
| `config_cpp.py` | 从 `config.cpp` 里提取键名 |
| `translation_sources.py` | 有顺序的翻译源列表（规则、AI 源、JSON 存取） |
| `translator_service.py` | 任务规划、分批、重试、缓存、主备接力 |
| `free_translators.py` | 六个免费翻译源 |
| `translation_worker.py` | 在后台线程里跑翻译 |
| `translation_flow.py` | 界面和命令行共用的一套翻译流程 |
| `cli.py` | 命令行入口 |
| `table_history.py` | 撤销/重做的快照 |
| `translation_cache.py` | 缓存写盘 |
| `quality_check.py` | 本地质量规则，把可疑的译文找出来 |
| `quality_check_worker.py` | 在后台线程里跑质量检查 |
| `word_split.py` | 把粘在一起的英文拆开 |

`smoke_free_sources.py` 是个小脚本，可以在命令行里把六个免费源各戳一下，用来判断一个 `429` 到底是你的网络问题还是对方限流。

</details>

## 许可证

[GNU 通用公共许可证 第三版](LICENSE)。

用到的第三方组件：[PySide6 / Qt 6](https://www.qt.io/)（LGPL-3.0 / GPL-3.0）和 [deep-translator](https://github.com/nidhaloff/deep-translator)（Apache-2.0）。

## 免责声明

这是玩家自己做的非官方工具，跟 Bohemia Interactive 没有关系，也没有得到他们的认可。DayZ 是 Bohemia Interactive 的商标。那些免费翻译接口都是没有公开文档的公共服务，请悠着点用，并遵守它们的服务条款。