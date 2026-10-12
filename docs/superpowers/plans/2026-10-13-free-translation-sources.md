# 免费翻译源 + 统一源列表 + 主备降级 Implementation Plan

> **For agentic workers:** 每个 Task 按「先写会失败的测试 → 跑到失败 → 实现 → 跑到通过 → `git add <文件>` → commit」执行。
> 每个 commit 之后跑一次 `python -m unittest discover -s tests`，基线是 **284 tests OK**：**不允许出现红（fail / error）**。本计划会刻意删掉一些过时测试（Task 2 删 11 条、Task 5 删 6 条），所以中途总数可能低于 284；**最后一个 Task 结束时总数必须 ≥ 284**。
> 完成所有 Task 后跑 `codegraph sync`。

---

## Goal

给 `DayZ_Translate_Tool` 加上 6 个**免密钥**翻译源，并把「翻译源」从「一个单选下拉框 + 一套全局密钥」改造成
「**一张统一权重列表** + 每个源各自的设置 + 每个源各自的启用规则 + 按列表顺序主备降级」。

三件事：

1. **免费源**：微软 Edge、Google（改成 POST 版）、腾讯交互、火山、Lara、MyMemory —— 全部免密钥、全部用标准库 `urllib` 直连，本机已实测通过（见「参考实现」表）。
2. **统一列表**：免费源与 AI 源混排在同一张表里，**顺序就是权重就是优先级**。每个源三个勾选框：`翻译全表` / `翻译空白` / `右键选中`。点中某一行，下面显示这个源自己的设置。
3. **主备降级**：一次翻译按列表顺序挑出所有符合规则的源，从第一个开始试；先用一条试翻确认能用，再整份交给它；中途挂了就换下一个源，**只补失败的**，已翻好的保留；降级时状态栏显示一行小字。

---

## Architecture

### 数据流

```text
用户点「翻译全表」
   ↓
main.py: translate_all_cells() → run_translation_jobs(jobs, rule="all")
   ↓
start_translation_worker(jobs, rule) 
   ├─ build_translation_configs(rule)  ← 按规则过滤源列表 → [TranslatorConfig, ...]
   │     └─ 一个都没有 → 弹窗报错，不启动
   ↓
create_translation_worker(jobs, configs) → TranslationWorker(service, jobs, configs)
   ↓  (QThread)
TranslationService.translate_jobs_with_fallback(jobs, configs, on_fallback=...)
   for config in configs:
       probe_source()   ← 先用第一条试翻；失败就 continue 到下一个源
       translate_jobs() ← 整份交给这个源
       有失败 → 换下一个源，只补失败的
   ↓
TranslationWorker.fallback(previous, current) → 状态栏小字
TranslationWorker.finished(results) → finish_translation()
```

### 免费源客户端

新文件 `free_translators.py`，基类 `FreeHttpTranslator` 管：

- **分块**：`MAX_ITEMS`（一次请求最多几条）/ `MAX_CHARS`（单条最多码点）/ `MAX_BYTES`（单条最多 UTF-8 字节）。超限的文本按行切块，块内保留换行；单行本身超限就按字符硬切。`translate_batch` 保证返回长度与顺序和输入完全一致（`_translate_one_row_batch` 依赖这一点）。
- **语言码映射**：`map_language(source_id, code, role)`。返回 `None` 表示「省略这个参数」（微软和 Lara 靠省略参数来触发自动识别）。
- **HTTP + 重试**：`_request_json()` 走 `retry_call`，HTTPError → `TranslationRequestError(status, retry_after)`，URLError → `TranslationRequestError`。注入 `request_func` 即可在测试里替换网络层。

### 语言码映射规则（本机实测得出，不是猜的）

| 源 | `zh-CN` | `auto`（源语言） | 依据 |
| --- | --- | --- | --- |
| microsoft | `zh-CN` | **完全省略 `from`** | `from=auto` → HTTP 400；省略 → 200 且自动识别 |
| google | `zh-CN` | `sl=auto` | 200，响应 `[["刀","en"]]` |
| tencent | **`zh`** | `lang=auto` | 200，响应带 `src_lang` |
| volcano | **`zh`** | `source_language=auto` | 200，响应带 `detected_language` |
| lara | `zh-CN` | **完全省略 `source`** | `source=auto` → 400 `Invalid value for parameter lang: 'auto'` |
| mymemory | `zh-CN` | **退回 `en`** | `langpair=auto\|zh-CN` → 200 但 `responseStatus:"403"` + 报错文本 |

其余 DayZ 语言码（`en` `cs` `fr` `es` `it` `pl` `hu` `ru` `de` `ja` `pt`）六个源全部原样透传（实测 `pt` 六个源都接受）。

### 主备降级的语义

- 按列表顺序，第一个能用的源整份都用它。
- 开始前**先试翻一条**（第一条待翻文本）确认源可用。试翻结果写进共享缓存，所以正式跑的时候那一条会命中缓存，不会多花一次请求。
- 翻到中途挂了：换下一个源，**只补失败的**，已翻好的保留（`cell_results` 按 `(row, column)` 合并）。
- 降级**不记住**：每次翻译都从列表第一个源重新试。
- 降级时通过 `TranslationWorker.fallback(previous_label, current_label)` 通知界面。
- AI 源也参与降级（勾上即表示接受可能花费）。

### 规则的语义

`翻译全表` / `翻译空白` / `右键选中` 是**权限过滤**，不是「用什么源翻」的提示：

- 点「翻译全表」→ 只从勾了 `全表` 的源里挑。
- 一个都没有 → 弹窗报错（「没有任何翻译源被勾选用于『翻译全表』」），**不偷偷用未授权的源**。
- 右键翻译选中单元格 / 行 / 列 → 用 `右键选中` 规则。
- 「只重跑失败项」→ 沿用上一次翻译用的规则。

---

## Tech Stack

- Python 3.10+ / PySide6（现有）
- **零新依赖**。`requirements.txt` 保持 `PySide6` + `deep-translator` 不变；所有免费源用标准库 `urllib.request` + `json` + `urllib.parse`。
- 测试：标准库 `unittest`，`QT_QPA_PLATFORM=offscreen`。

---

## 参考实现（已核实源码 / 本机实测，非印象）

| 源 | 端点 | 请求 | 实测结论 |
| --- | --- | --- | --- |
| 微软 Edge | `POST https://edge.microsoft.com/translate/translatetext?from=en&to=zh-CN&isEnterpriseClient=false` | `Content-Type: application/json`，body `["Knife","Gun"]` | 响应 `[{"translations":[{"text":"刀",...}]},...]`。**1/10/50/200/500 条全部一次成功**，无 Cookie/token/签名。**最好的源** |
| Google | `POST https://translate.googleapis.com/translate_a/t?client=gtx&sl=en&tl=zh-CN&dt=t` | `application/x-www-form-urlencoded`，多个 `q=`，浏览器 UA | `sl=en` → `["刀","枪"]`；`sl=auto` → `[["刀","en"],["枪","en"]]`。**1/10/50/200 条全部成功**。现有的 `translate_a/single?client=gtx` GET 版已 3/3 429（`client=gtx` 被 Google 停用，直连与走代理都一样） |
| 腾讯交互 | `POST https://transmart.qq.com/api/imt` | JSON，`header.fn="auto_translation"`、`source.text_list`、`target.lang` | 响应 `header.ret_code=="succ"` + `auto_translation:["刀"]`。**300 条 OK，500 条报 `outOfLimit`**。单条 1000 码点 |
| 火山 | `POST https://translate.volcengine.com/crx/translate/v1/` | JSON，`source_language`/`target_language`/`text` | `text` 传数组 → HTTP 400，**只能单条**。响应 `base_resp.status_code==0`。1000 码点 |
| Lara | `POST https://webapi.laratranslate.com/translate/segmented` | JSON + `X-Lara-Client: Webapp` | `q` 必须是字符串（数组 → 400）。响应 `content.translations[0].translation`。1000 码点 |
| MyMemory | `GET https://api.mymemory.translated.net/get?q=..&langpair=en\|zh-CN` | 无 | 匿名 5000 字符/天，**单次 ≤500 UTF-8 字节**，**只能单条**（多 `q` 只返回最后一条）。配额用尽 → `quotaFinished:true` 且 `translatedText` 里出现 `MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY` |

**不做**：B站（实测 HTTP 412）、有道/金山词霸（需要签名）、Reverso/Yandex/ModernMT/阿里/Lingvanex（本轮不需要）。

**并发与间隔**（参考 FluentRead 的调度参数，`docs/FluentRead_免费翻译源_移植报告.md`）：

| 源 | 并发 | 最小间隔 | 一次最多几条 |
| --- | --- | --- | --- |
| microsoft | 2 | 0.1s | 500 |
| google | 2 | 0.3s | 200 |
| tencent | 2 | 0.3s | 300 |
| volcano | 1 | 1.0s | 1 |
| lara | 1 | 1.0s | 1 |
| mymemory | 1 | 1.0s | 1 |

---

## 本修订版修掉的问题

| # | 问题 | 修法 |
| --- | --- | --- |
| 1 | `mymemory` provider 已经坏了：`translator_service.py:292` 直接实例化 deep-translator 的 `MyMemoryTranslator(source="en", target="zh-CN")`，deep-translator 只认 `en-GB` 这种写法，实测直接抛 `LanguageNotSupportedException: en --> No support for the provided language.` | 换成 `free_translators.MyMemoryTranslator`，自己拼 `langpair` |
| 2 | `google` provider 已经坏了：`translate_a/single?client=gtx` GET 稳定 429 | 换成 `translate_a/t` POST |
| 3 | `microsoft` provider 需要用户自己去申请 Azure 密钥 | 换成免密钥的 Edge 端点 |
| 4 | 「并行批次数」是一个全局旋钮，但不同源的安全并发差 4 倍（火山只能 1，微软能 2 且间隔 0.1s） | 删掉全局旋钮，改成每个源内置；AI 源可自定义 |
| 5 | 免费源没有重试与节流（`create_provider` 里 `mymemory`/`deepl`/`microsoft` 既没传 `retry_policy` 也没包 `_guarded`） | 免费源统一走 `FreeHttpTranslator`，自带重试 + 全局限速钩子 + 自适应闸门 |
| 6 | 换源之后缓存不通用（缓存键含 provider），且用户看不出哪些源被允许用在哪 | 保持按源分开缓存（**刻意**，见「已知取舍」），但把「允许用在哪」变成显式勾选框 |

---

## 实施期偏离记录（2026-10-13 实施时新增）

实施过程中与计划不一致的地方，逐条记下来备查。「已知取舍」里任何一条都没有被改动。

### 代码

| # | 计划里写的 | 实际做的 | 为什么 |
| --- | --- | --- | --- |
| 1 | Task 4 测试用 `deepl` 当第二源，`configs()` 不带 `api_key` | 用 `dataclasses.replace(configs[1], api_key="k")` 注入密钥（测试文件顶部加 `import dataclasses`） | `TranslatorConfig` 是 frozen dataclass，`validate_translator_config` 会因缺密钥抛 `ValueError: DeepL requires an API key.`；改测试而不是放宽校验 |
| 2 | Task 5 Step 7 只说「保留 3 个测试线程相关方法」 | 实际保留 5 个：`_wait_for_test_thread` / `_on_test_finished` / `_on_test_failed` / `_reset_test_button` / `_current_test_jobs`；`_clear_test_thread` 随老 `run_translation_test` 一起删掉 | 前两个槽会调 `_reset_test_button` 与 `_current_test_jobs`，删了会 `AttributeError`；`_clear_test_thread` 在新版里没有任何调用点 |
| 3 | Step 7 代码块把 `source_type_input`（`QComboBox`）也放进 `editingFinished` 循环 | 从循环里拿掉，单独接 `currentIndexChanged` | `QComboBox` 没有 `editingFinished`，原样跑会 `AttributeError: 'PySide6.QtWidgets.QComboBox' object has no attribute 'editingFinished'`，对话框整个打不开 |
| 4 | Task 5 没提 `main.py` 的 `normalize_provider` | 从 `from translator_service import ...` 里删掉 | 它唯一的调用点在 Step 8 删掉的那几行里，留着就是未用 import |
| 5 | Task 3 `test_reordering_changes_priority` 断言 `entries[-2:] == ["mymemory", "lara"]`；Task 5 `test_source_list_survives_a_restart` 断言 `entries[:2] == ["google", "mymemory"]` | 前者改成 `entries[4:6] == ["mymemory", "lara"]` 与 `candidates[:2] == ["mymemory", "google"]`；后者改成 `["mymemory", "google"]` | 计划的算术错了：`mymemory` 出厂在 index 5，5 次 `move_up` 之后到 index 0，而 `deepl` 永远在最后。实现（相邻交换）没动 |
| 6 | Task 5 同步修改表没提 `tests/test_main_gui.py` 里两个 `FakeService` | 两个 `translate_jobs(self, jobs, config, ...)` 都改成 `translate_jobs_with_fallback(self, jobs, configs, ...)` | worker 的 `run()` 现在只调新方法，假 service 不跟着改就会走进 `failed` 分支 |
| 7 | Task 5 新增测试类的 `tearDown` 只有 `self.window.close()` | 前面加一句 `self.window._ensure_translation_stopped()` | 假 worker 不会自己结束线程，`closeEvent` 会弹「翻译中」模态框，在无人值守的测试里直接挂死（实测挂满 900 秒超时） |
| 8 | `test_ai_source_config_carries_the_glossary` 用 `open_wordbook_window()` | 改成用临时目录里的词库文件（`WordbookWindow(self.window, wordbook_path=...)`） | 否则读到本机词库里的旧词条，断言必然失败 |

### 真机冒烟（六个免费源各翻一条，真实网络）

跑 `python smoke_free_sources.py`，直连与走 `127.0.0.1:7897` 代理都试过：

| 源 | 结果 |
| --- | --- |
| microsoft | OK 0.32s `["刀", "炮", "绷带"]` |
| tencent | OK 0.33s `["刀", "枪", "绷带"]` |
| volcano | OK 0.21s `["刀"]` |
| lara | OK 0.92s `["刀具"]` |
| google | FAIL `TranslationRequestError: Google HTTP 429`（返回 HTML 限流页；直连和代理结果一样） |
| mymemory | FAIL `TranslationRequestError: MyMemory HTTP 429`（`MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY. NEXT AVAILABLE IN 14 HOURS ...`） |

两个 429 都是服务端限流，不是代码问题：Google 的免费端点在当前出口 IP 上被限；MyMemory 是当天匿名额度（5000 字符/天）用完了。错误处理没有为了让冒烟变绿而放宽 —— 界面上这两条会照常显示失败并触发主备降级。

### 没做的

- Task 6 Step 3「手动 GUI 冒烟」需要人工点击，未执行。列表顺序、三个勾选框、AI 源弹窗、内置限制灰字、上移下移持久化、无源报错、微软降级提示这 7 条只在自动化测试里覆盖（`tests/test_main_gui.py` 的 `TranslationSourceListDialogTests` / `TranslationRuleWiringTests`），真机外观与交互仍需人眼确认。

---

## Global Constraints

- **不新增任何第三方依赖。** `requirements.txt` 保持 `PySide6` + `deep-translator`。新能力全部标准库。
- **6 个翻译入口的对外行为不变**：`translate_selected_cells` / `translate_selected_rows` / `translate_selected_columns` / `translate_all_cells` / `translate_empty_cells` / `retry_failed_cells` 的菜单项、右键项、快捷键都不动，只是内部多传一个 `rule`。
- **主界面不变**：菜单、工具栏、状态栏控件数量不动。改动只发生在 `TranslationSettingsDialog` 内部、`start_translation_worker` 的接线、以及状态栏的一行小字。
- **行永不被劈开**（沿用上一轮）：同一 `job.row` 的所有 job 必须落在同一个批次里。这条约束在 `iter_row_batches` 里，本计划不动它。
- **`translate_batch` 的返回长度必须与输入等长同序**。免费源的分块拼接要保证这一点，否则 `_store_batch_results` 的 `zip` 会静默错位。
- **UI 文案 en/zh 都要**：`UI_TEXT` 的 `en` 与 `zh` 两份必须成对新增（上一轮的教训：漏一份会在中文界面下显示英文 key）。
- **`git add <文件>`，不用 `git add -A`。** 工作区有 60+ 个开工前就存在的未提交改动（`__pycache__/`、`build/`、`dist/`、`build_exe.ps1`、`dayz_csv.py`、`tests/test_main_gui.py`、`wordbook_csv.py`、`tests/test_dayz_csv.py`、`tests/test_wordbook_csv.py`、`_probe_lang.py`），`-A` 会把它们混进 commit。
- **既有测试必须同步改。** 「既有测试的同步修改」一节是本计划的一部分，不是可选步骤。行为被刻意改变的地方，测试跟着改；被删掉的类，测试一起删。
- **`_translation_written_cells` 语义保持**：哪批翻完就写哪批，已写入的单元格不重复写。
- **id 只分配一次**：任何「重新对子集编号」的写法都视为 bug（上一轮的教训，本计划不动 `assign_batch_ids`）。

---

## 决定清单（来自需求访谈）

| # | 决定 | 出处 |
| --- | --- | --- |
| 1 | 加 6 个免费源：微软 Edge、腾讯交互、Google（改 POST）、火山、Lara、MyMemory | Q1/Q2 |
| 2 | Google 换成 POST `translate_a/t`（实测 200 条一次成功，返回干净数组） | Q2=A |
| 3 | 不加 B站（实测 412）、不加需要签名的（有道/金山词霸） | Q3 |
| 4 | 顺带修好已损坏的 MyMemory | Q4 |
| 5 | **一个统一的源列表**，免费源与 AI 源混排，顺序 = 权重 = 优先级 | Q5=A / Q10=A |
| 6 | 每个源三个勾选框：`翻译全表` / `翻译空白` / `右键选中` | Q11=A |
| 7 | 每个源有上移/下移按钮 | Q16=A |
| 8 | 点中某源，下面显示它自己的设置 | Q10=A |
| 9 | 免费源的并发/间隔显示成**灰色小字（只读）** | Q24=A |
| 10 | AI 源点「+」弹窗添加：名称、接口类型（OpenAI 兼容/Claude/Codex）、接口地址、密钥（密码框）、模型名、并发数、间隔秒数 | Q30=A |
| 11 | 可加多个同类型 AI 源；重名给提醒（可继续） | Q31=A |
| 12 | 微软免费版**替换**现有需要密钥的 `microsoft` provider | Q5=A |
| 13 | 旧的 `provider_settings` 里密钥**一刀切清掉** | Q25=B |
| 14 | 出厂顺序：Google → 微软 → 腾讯 → 火山 → Lara → MyMemory | Q14=B |
| 15 | 出厂勾选：前三个批量源全勾（全表+空白+右键）；三个单条源不勾，但规则预设为只勾「右键」 | Q21=B |
| 16 | AI 源列表出厂为空 | Q26=A |
| 17 | 主备降级：按列表顺序，第一个能用的源整份都用它 | Q8=A |
| 18 | 开始前**先试翻一条**确认源可用 | Q12 |
| 19 | 翻到中途挂了：换下一个源，**只补失败的**，已翻好的保留 | Q13=B |
| 20 | 降级时**状态栏显示一行小字**（如「微软连不上，已自动改用 Google」） | Q17=A |
| 21 | **降级不记住**，每次都从第一个源重新试 | Q22=A |
| 22 | **按规则过滤**：一个都没有就报错，不偷偷用未授权的源 | Q27=A |
| 23 | **AI 源也参与降级**（勾上即表示接受可能花费） | Q28=A |
| 24 | 「并行批次数」设置项**删掉**，改成每个源内置（AI 源可自定义） | Q29=A |
| 25 | （本计划新增，用户可否决）**DeepL 保留**，作为列表末尾第 7 个内置源，出厂不勾选；它是唯一需要密钥的内置源，设置区多一个密钥框 | 见「已知取舍」 |
| 26 | **预设功能整个删掉**（用户 m01748 定）：对话框里的 preset 行（下拉框/名字输入框/保存/删除/脏标记）、主窗口的 `translation_preset_names` / `save_translation_preset` / `load_translation_preset` / `delete_translation_preset` / `current_translation_settings_dict` / `apply_translation_settings_dict`、以及 `QSettings` 里的 `translation_presets/*` 与 `translation_preset_names_list` 全部移除 | 用户选「删掉预设」 |

---

## 常量

```python
# free_translators.py
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
FREE_DEFAULT_TIMEOUT = 15.0
ZH_VARIANTS = ("zh-CN", "zh-TW")
OMIT_AUTO_SOURCE = ("microsoft", "lara")     # 这两个源靠「省略参数」触发自动识别
AUTO_SOURCE_FALLBACK = {"mymemory": "en"}    # MyMemory 不认 auto，退回 en
TENCENT_CLIENT_KEY = "browser-chrome-110.0.0-Mac OS-abcdefgh-ijklmnop-1234567890"

FREE_SOURCE_SPECS = {
    # label_key 指向 UI_TEXT 里的键；needs_key 只有 deepl 是 True
    "google":    {"label_key": "source_google",    "items": 200, "chars": None, "bytes": None, "interval": 0.3, "concurrency": 2, "needs_key": False},
    "microsoft": {"label_key": "source_microsoft", "items": 500, "chars": None, "bytes": None, "interval": 0.1, "concurrency": 2, "needs_key": False},
    "tencent":   {"label_key": "source_tencent",   "items": 300, "chars": 1000, "bytes": None, "interval": 0.3, "concurrency": 2, "needs_key": False},
    "volcano":   {"label_key": "source_volcano",   "items": 1,   "chars": 1000, "bytes": None, "interval": 1.0, "concurrency": 1, "needs_key": False},
    "lara":      {"label_key": "source_lara",      "items": 1,   "chars": 1000, "bytes": None, "interval": 1.0, "concurrency": 1, "needs_key": False},
    "mymemory":  {"label_key": "source_mymemory",  "items": 1,   "chars": None, "bytes": 500,  "interval": 1.0, "concurrency": 1, "needs_key": False},
    "deepl":     {"label_key": "source_deepl",     "items": 50,  "chars": None, "bytes": None, "interval": 0.2, "concurrency": 2, "needs_key": True},
}

# translation_sources.py
RULE_ALL = "all"
RULE_EMPTY = "empty"
RULE_SELECTION = "selection"
ALL_RULES = (RULE_ALL, RULE_EMPTY, RULE_SELECTION)

DEFAULT_SOURCE_ORDER = ("google", "microsoft", "tencent", "volcano", "lara", "mymemory", "deepl")
DEFAULT_SOURCE_RULES = {
    "google": ALL_RULES,
    "microsoft": ALL_RULES,
    "tencent": ALL_RULES,
    "volcano": (RULE_SELECTION,),
    "lara": (RULE_SELECTION,),
    "mymemory": (RULE_SELECTION,),
    "deepl": (),
}

# main.py
SOURCE_TABLE_HEADERS = ("name", "kind", "all", "empty", "selection")
AI_TYPE_KEYS = ("openai", "claude", "codex")
AI_TYPE_LABEL_KEYS = {"openai": "ai_type_openai", "claude": "ai_type_claude", "codex": "ai_type_codex"}
```

`translator_service.py` 里 `GOOGLE_MIN_INTERVAL = 3.0` **删除**（改成 `TranslatorConfig.min_interval`，由源列表提供）。

---

## File Map

| 文件 | 动作 | 内容 |
| --- | --- | --- |
| `free_translators.py` | **新增** | `FreeHttpTranslator` 基类 + 6 个免费源 + `map_language` + `FREE_SOURCE_SPECS` + `FREE_TRANSLATOR_CLASSES` |
| `translation_sources.py` | **新增** | `SourceEntry` / `SourceList` / 出厂默认 / JSON 往返 / 规则过滤 |
| `tests/test_free_translators.py` | **新增** | 分块、语言映射、6 个源的请求形状、重试与错误映射 | Task 5 |
| `tests/test_translation_sources.py` | **新增** | 数据模型、JSON 往返、默认值、上移/下移/删除/加 AI 源、规则过滤 | Task 5 |
| `tests/test_translation_fallback.py` | **新增** | 主备降级：试翻、换源、只补失败的、空列表报错、取消 | Task 5 |
| `translator_service.py` | 改 | `TranslatorConfig` 加 `label` / `min_interval`；`create_provider` 接免费源；`validate_translator_config` 去掉 mymemory/microsoft 的密钥要求；`translate_jobs` 用 `config.min_interval`；新增 `translate_jobs_with_fallback` / `_probe_source`；**删除** `GoogleTranslateTranslator` 类与 `GOOGLE_MIN_INTERVAL` |
| `translation_worker.py` | 改 | `config` → `configs` 列表；新增 `fallback = Signal(str, str)`；`run()` 改调 `translate_jobs_with_fallback` |
| `main.py` | 改 | 对话框重写、`SourceList` 持久化、迁移清理、`build_translation_configs`、`start_translation_worker` 带规则、降级状态栏、`UI_TEXT` 新增键 |
| `tests/test_translation_worker.py` | 改 | `configs=[...]` + fallback 断言 | Task 5 |
| `tests/test_main_gui.py` | 改 | 见「既有测试的同步修改」 | Task 5 |
| `tests/test_translator_service.py` | 改 | 删 `GoogleTranslateTranslatorTests`；`GoogleProviderIntegrationTests` 改成 POST；`google_translator_class` → `free_translator_classes` | Task 2 |
| `_probe_lang.py` | **删除文件** | 勘察期的临时探测脚本。**没有被 git 跟踪**，只 `rm -f` 删文件，不涉及任何 git 操作 |
| `smoke_free_sources.py` | **新增** | 最后一个 Task 的真机冒烟脚本：六个免费源各翻一条真实请求，含一条 1500 字长行 |
| `requirements.txt` | 不动 | 零新依赖 |

---

### Task 1: `free_translators.py` —— 六个免费源客户端

**Files:**

- Create: `free_translators.py`
- Create: `tests/test_free_translators.py`

- [ ] **Step 1: 写会失败的测试**

新建 `tests/test_free_translators.py`：

```python
import json
import unittest
import urllib.parse

from free_translators import (
    FREE_SOURCE_SPECS,
    FREE_TRANSLATOR_CLASSES,
    GoogleWebTranslator,
    LaraTranslator,
    MicrosoftEdgeTranslator,
    MyMemoryTranslator,
    TencentInteractiveTranslator,
    VolcanoTranslator,
    map_language,
)


class FakeHttp:
    """记录请求并返回预置响应；用来替代 urllib，不碰网络。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, method, body, headers):
        self.calls.append({"url": url, "method": method, "body": body, "headers": headers or {}})
        if not self.responses:
            raise AssertionError("FakeHttp ran out of responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def body_json(self, index=0):
        return json.loads(self.calls[index]["body"].decode("utf-8"))

    def body_form(self, index=0):
        return urllib.parse.parse_qs(self.calls[index]["body"].decode("utf-8"))


def make(cls, responses, **kwargs):
    http = FakeHttp(responses)
    translator = cls(request_func=http, **kwargs)
    return translator, http


class LanguageMappingTests(unittest.TestCase):
    def test_zh_cn_maps_to_zh_for_tencent_and_volcano(self):
        self.assertEqual(map_language("tencent", "zh-CN", "target"), "zh")
        self.assertEqual(map_language("volcano", "zh-CN", "target"), "zh")
        self.assertEqual(map_language("microsoft", "zh-CN", "target"), "zh-CN")
        self.assertEqual(map_language("lara", "zh-CN", "target"), "zh-CN")
        self.assertEqual(map_language("mymemory", "zh-CN", "target"), "zh-CN")

    def test_plain_codes_pass_through(self):
        for source_id in FREE_TRANSLATOR_CLASSES:
            self.assertEqual(map_language(source_id, "pt", "target"), "pt")
            self.assertEqual(map_language(source_id, "ja", "target"), "ja")

    def test_auto_is_omitted_for_microsoft_and_lara(self):
        self.assertIsNone(map_language("microsoft", "auto", "source"))
        self.assertIsNone(map_language("lara", "auto", "source"))

    def test_auto_is_literal_for_google_tencent_volcano(self):
        self.assertEqual(map_language("google", "auto", "source"), "auto")
        self.assertEqual(map_language("tencent", "auto", "source"), "auto")
        self.assertEqual(map_language("volcano", "auto", "source"), "auto")

    def test_auto_falls_back_to_english_for_mymemory(self):
        self.assertEqual(map_language("mymemory", "auto", "source"), "en")

    def test_empty_code_returns_none(self):
        self.assertIsNone(map_language("google", "", "source"))
        self.assertIsNone(map_language("google", None, "source"))


class SplitTextTests(unittest.TestCase):
    def test_short_text_is_not_split(self):
        translator, _ = make(VolcanoTranslator, [])
        self.assertEqual(translator.split_text("Knife"), ["Knife"])

    def test_text_over_char_limit_splits_on_line_boundaries(self):
        translator, _ = make(VolcanoTranslator, [])
        text = "a" * 600 + "\n" + "b" * 600
        pieces = translator.split_text(text)
        self.assertEqual(len(pieces), 2)
        self.assertEqual("".join(pieces), text)
        for piece in pieces:
            self.assertLessEqual(len(piece), 1000)

    def test_single_long_line_is_hard_split(self):
        translator, _ = make(VolcanoTranslator, [])
        text = "x" * 2500
        pieces = translator.split_text(text)
        self.assertEqual(len(pieces), 3)
        self.assertEqual("".join(pieces), text)
        for piece in pieces:
            self.assertLessEqual(len(piece), 1000)

    def test_byte_limit_uses_utf8_length(self):
        translator, _ = make(MyMemoryTranslator, [])
        text = "刀" * 200          # 600 UTF-8 字节
        pieces = translator.split_text(text)
        self.assertEqual("".join(pieces), text)
        for piece in pieces:
            self.assertLessEqual(len(piece.encode("utf-8")), 500)

    def test_empty_text_returns_single_empty_piece(self):
        translator, _ = make(VolcanoTranslator, [])
        self.assertEqual(translator.split_text(""), [""])


class MicrosoftEdgeTranslatorTests(unittest.TestCase):
    def test_batch_posts_json_array_and_reads_translations(self):
        translator, http = make(
            MicrosoftEdgeTranslator,
            [[{"translations": [{"text": "刀"}]}, {"translations": [{"text": "枪"}]}]],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertIn("edge.microsoft.com/translate/translatetext", call["url"])
        self.assertIn("to=zh-CN", call["url"])
        self.assertIn("from=en", call["url"])
        self.assertEqual(http.body_json(), ["Knife", "Gun"])

    def test_auto_source_omits_from_parameter(self):
        translator, http = make(
            MicrosoftEdgeTranslator,
            [[{"translations": [{"text": "刀"}]}]],
            source="auto", target="zh-CN",
        )
        translator.translate_batch(["Knife"])
        self.assertNotIn("from=", http.calls[0]["url"])


class GoogleWebTranslatorTests(unittest.TestCase):
    def test_batch_posts_form_and_reads_flat_array(self):
        translator, http = make(
            GoogleWebTranslator, [["刀", "枪"]], source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])
        call = http.calls[0]
        self.assertIn("translate_a/t", call["url"])
        self.assertEqual(call["method"], "POST")
        self.assertIn("Content-Type", call["headers"])
        form = http.body_form()
        self.assertEqual(form["client"], ["gtx"])
        self.assertEqual(form["sl"], ["en"])
        self.assertEqual(form["q"], ["Knife", "Gun"])

    def test_auto_source_reads_nested_array(self):
        translator, _ = make(
            GoogleWebTranslator, [[["刀", "en"], ["枪", "en"]]], source="auto", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])


class TencentInteractiveTranslatorTests(unittest.TestCase):
    def test_batch_posts_text_list(self):
        translator, http = make(
            TencentInteractiveTranslator,
            [{"header": {"ret_code": "succ"}, "auto_translation": ["刀", "枪"]}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])
        payload = http.body_json()
        self.assertEqual(payload["source"]["text_list"], ["Knife", "Gun"])
        self.assertEqual(payload["source"]["lang"], "en")
        self.assertEqual(payload["target"]["lang"], "zh")
        self.assertEqual(payload["header"]["fn"], "auto_translation")

    def test_non_succ_ret_code_raises(self):
        translator, _ = make(
            TencentInteractiveTranslator,
            [{"header": {"ret_code": "outOfLimit", "message": "too many"}}],
            source="en", target="zh-CN",
        )
        with self.assertRaises(Exception) as ctx:
            translator.translate_batch(["Knife"])
        self.assertIn("outOfLimit", str(ctx.exception))


class VolcanoTranslatorTests(unittest.TestCase):
    def test_single_text_request(self):
        translator, http = make(
            VolcanoTranslator,
            [{"translation": "刀", "base_resp": {"status_code": 0}}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife"]), ["刀"])
        payload = http.body_json()
        self.assertEqual(payload["text"], "Knife")
        self.assertEqual(payload["target_language"], "zh")

    def test_non_zero_status_code_raises(self):
        translator, _ = make(
            VolcanoTranslator,
            [{"translation": "", "base_resp": {"status_code": 100, "status_message": "bad"}}],
            source="en", target="zh-CN",
        )
        with self.assertRaises(Exception):
            translator.translate_batch(["Knife"])

    def test_batch_issues_one_request_per_text(self):
        translator, http = make(
            VolcanoTranslator,
            [{"translation": "刀", "base_resp": {"status_code": 0}},
             {"translation": "枪", "base_resp": {"status_code": 0}}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])
        self.assertEqual(len(http.calls), 2)


class LaraTranslatorTests(unittest.TestCase):
    def test_reads_nested_translation(self):
        translator, http = make(
            LaraTranslator,
            [{"status": 200, "content": {"translations": [{"translation": "刀"}]}}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife"]), ["刀"])
        payload = http.body_json()
        self.assertEqual(payload["q"], "Knife")
        self.assertEqual(payload["source"], "en")
        self.assertEqual(payload["source_hint"], "")
        self.assertIn("X-Lara-Client", http.calls[0]["headers"])

    def test_auto_source_omits_source_and_source_hint(self):
        translator, http = make(
            LaraTranslator,
            [{"status": 200, "content": {"translations": [{"translation": "刀"}]}}],
            source="auto", target="zh-CN",
        )
        translator.translate_batch(["Knife"])
        payload = http.body_json()
        self.assertNotIn("source", payload)
        self.assertNotIn("source_hint", payload)


class MyMemoryTranslatorTests(unittest.TestCase):
    def test_reads_response_data(self):
        translator, http = make(
            MyMemoryTranslator,
            [{"responseData": {"translatedText": "刀"}, "responseStatus": 200, "quotaFinished": False}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife"]), ["刀"])
        self.assertIn("langpair=en%7Czh-CN", http.calls[0]["url"])

    def test_quota_finished_raises_rate_limit_error(self):
        translator, _ = make(
            MyMemoryTranslator,
            [{"responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY"},
              "responseStatus": 200, "quotaFinished": True}],
            source="en", target="zh-CN",
        )
        with self.assertRaises(Exception) as ctx:
            translator.translate_batch(["Knife"])
        self.assertEqual(getattr(ctx.exception, "status", None), 429)

    def test_error_status_raises(self):
        translator, _ = make(
            MyMemoryTranslator,
            [{"responseData": {"translatedText": "INVALID SOURCE LANGUAGE"}, "responseStatus": "403"}],
            source="en", target="zh-CN",
        )
        with self.assertRaises(Exception):
            translator.translate_batch(["Knife"])


class ResponseShapeTests(unittest.TestCase):
    def test_wrong_translation_count_raises(self):
        translator, _ = make(
            GoogleWebTranslator, [["刀"]], source="en", target="zh-CN",
        )
        with self.assertRaises(Exception) as ctx:
            translator.translate_batch(["Knife", "Gun"])
        self.assertIn("2", str(ctx.exception))

    def test_translate_single_wraps_batch(self):
        translator, _ = make(
            GoogleWebTranslator, [["刀"]], source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate("Knife"), "刀")


class RegistryTests(unittest.TestCase):
    def test_every_spec_has_a_class(self):
        self.assertTrue(set(FREE_TRANSLATOR_CLASSES) <= set(FREE_SOURCE_SPECS))

    def test_class_specs_match_registry(self):
        for source_id, cls in FREE_TRANSLATOR_CLASSES.items():
            spec = FREE_SOURCE_SPECS[source_id]
            self.assertEqual(cls.MAX_ITEMS, spec["items"])
            self.assertEqual(cls.MAX_CHARS, spec["chars"])
            self.assertEqual(cls.MAX_BYTES, spec["bytes"])
            self.assertEqual(cls.MIN_INTERVAL, spec["interval"])
            self.assertEqual(cls.CONCURRENCY, spec["concurrency"])
```

- [ ] **Step 2: 跑到失败**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_free_translators -v 2>&1 | tail -5
```

预期：`ModuleNotFoundError: No module named 'free_translators'`

- [ ] **Step 3: 实现 `free_translators.py`**

```python
"""免密钥翻译源客户端。

全部走标准库 urllib，不引入第三方依赖。
每个类只负责「把一批文本发出去、把译文按顺序取回来」；
分批（行不劈开）、并发、缓存、术语表都由 translator_service 负责。
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from translator_service import (
    TranslationCancelled,
    TranslationRequestError,
    parse_retry_after,
    retry_call,
)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
FREE_DEFAULT_TIMEOUT = 15.0

# zh-CN / zh-TW 在腾讯与火山里要写成 zh
ZH_ALIASES = {"zh-CN": "zh", "zh-TW": "zh"}
# 这两个源不认字面 "auto"，靠「省略参数」触发自动识别
OMIT_AUTO_SOURCE = ("microsoft", "lara")
# MyMemory 不认 auto，退回 en（DayZ 的 original 列内容是从 english 列复制来的）
AUTO_SOURCE_FALLBACK = {"mymemory": "en"}

TENCENT_CLIENT_KEY = "browser-chrome-110.0.0-Mac OS-abcdefgh-ijklmnop-1234567890"


def map_language(source_id, code, role="source"):
    """把 DayZ 语言码翻成某个源认识的写法。

    返回 None 表示「这个参数应当省略」。
    """
    code = (code or "").strip()
    if not code:
        return None
    if code.lower() == "auto":
        if role != "source":
            # 目标语言不会是 auto（DayZ 的可译列都是具体语言）；调用方
            # `FreeHttpTranslator.__init__` 会提前把这种配置挡掉。
            return None
        if source_id in OMIT_AUTO_SOURCE:
            return None
        return AUTO_SOURCE_FALLBACK.get(source_id, "auto")
    if source_id in ("tencent", "volcano"):
        return ZH_ALIASES.get(code, code)
    return code


class FreeHttpTranslator:
    """免费源基类：分块 + HTTP + 重试 + 错误映射。"""

    SOURCE_ID = ""
    LABEL = ""
    ENDPOINT = ""
    MAX_ITEMS = 1            # 一次请求最多几条文本
    MAX_REQUEST_CHARS = None # 一次请求累计码点上限（None = 不限）
    MAX_CHARS = None         # 单条文本最长码点（None = 不限）
    MAX_BYTES = None         # 单条文本最长 UTF-8 字节（None = 不限）
    MIN_INTERVAL = 0.0
    CONCURRENCY = 1
    DEFAULT_TIMEOUT = FREE_DEFAULT_TIMEOUT

    def __init__(self, source="auto", target="en", timeout=None, should_cancel=None,
                 retry_policy=None, on_retry=None, before_attempt=None, request_func=None):
        # 目标语言是 auto 的话，请求里会出现 to=None（urlencode 会把它字符串化），
        # 这里提前挡掉，别让它跑到网络上。
        if (target or "").strip().lower() == "auto":
            raise ValueError("Free translators need a concrete target language.")
        self.source = source
        self.target = target
        self.timeout = float(timeout) if timeout else self.DEFAULT_TIMEOUT
        self.should_cancel = should_cancel
        self.retry_policy = retry_policy
        self.on_retry = on_retry
        self.before_attempt = before_attempt
        self.request_func = request_func or self._fetch_json

    # —— 对外 ——

    def translate(self, text):
        return self.translate_batch([text])[0]

    def translate_batch(self, texts):
        pieces = []
        for index, text in enumerate(texts):
            for piece in self.split_text(text):
                pieces.append((index, piece))
        results = [""] * len(texts)
        for group in self.group_pieces(pieces):
            if self.should_cancel and self.should_cancel():
                raise TranslationCancelled()
            translated = self._request([piece for _, piece in group])
            if len(translated) != len(group):
                raise TranslationRequestError(
                    f"{self.LABEL} returned {len(translated)} translations for {len(group)} texts."
                )
            for (index, _), value in zip(group, translated):
                results[index] += value or ""
        return results

    def group_pieces(self, pieces):
        """按 MAX_ITEMS 与 MAX_REQUEST_CHARS 双重上限攒请求组。

        `MAX_CHARS` 管的是「单条」，`MAX_ITEMS` 管的是「条数」，但两者都不限制
        「一次请求总共多少字」—— 用户把 `char_budget` 调大以后，一个请求可能塞进
        上百条长文本。腾讯的接口有请求总长上限（实测 300 条短文本 OK、500 条报
        `outOfLimit`），所以再补一道请求级上限。
        """
        groups = []
        current = []
        size = 0
        for piece in pieces:
            too_many = len(current) >= self.MAX_ITEMS
            too_long = (
                self.MAX_REQUEST_CHARS is not None
                and current
                and size + len(piece) > self.MAX_REQUEST_CHARS
            )
            if current and (too_many or too_long):
                groups.append(current)
                current = []
                size = 0
            current.append(piece)
            size += len(piece)
        if current:
            groups.append(current)
        return groups

    # —— 分块 ——

    def fits(self, text):
        if self.MAX_CHARS is not None and len(text) > self.MAX_CHARS:
            return False
        if self.MAX_BYTES is not None and len(text.encode("utf-8")) > self.MAX_BYTES:
            return False
        return True

    def split_text(self, text):
        """按行切块；块与块拼起来等于原文（含换行）。单行超限时按字符硬切。"""
        if self.fits(text):
            return [text]
        pieces = []
        current = ""
        for line in text.splitlines(keepends=True):
            if current and not self.fits(current + line):
                pieces.append(current)
                current = ""
            if self.fits(line):
                current += line
                continue
            for chunk in self.hard_split(line):
                if current and not self.fits(current + chunk):
                    pieces.append(current)
                    current = ""
                current += chunk
        if current:
            pieces.append(current)
        return pieces or [""]

    def hard_split(self, line):
        chunks = []
        current = ""
        for char in line:
            if current and not self.fits(current + char):
                chunks.append(current)
                current = char
            else:
                current += char
        if current:
            chunks.append(current)
        return chunks

    # —— HTTP ——

    def _request_json(self, url, method, body, headers):
        return retry_call(
            lambda: self.request_func(url, method, body, headers),
            self.retry_policy,
            self.should_cancel,
            self.on_retry,
            self.before_attempt,
        )

    def _fetch_json(self, url, method, body, headers):
        request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:      # noqa: BLE001 — 读错误响应体失败不该盖住原始错误
                detail = ""
            raise TranslationRequestError(
                f"{self.LABEL} HTTP {exc.code}: {detail}",
                status=exc.code,
                retry_after=parse_retry_after(exc.headers),
            ) from exc
        except urllib.error.URLError as exc:
            raise TranslationRequestError(f"{self.LABEL} request failed: {exc.reason}") from exc

    def _request(self, texts):
        raise NotImplementedError


class MicrosoftEdgeTranslator(FreeHttpTranslator):
    """微软 Edge 内置翻译。免密钥，一次最多 500 条。"""

    SOURCE_ID = "microsoft"
    LABEL = "Microsoft"
    ENDPOINT = "https://edge.microsoft.com/translate/translatetext"
    MAX_ITEMS = 500
    MIN_INTERVAL = 0.1
    CONCURRENCY = 2

    def _request(self, texts):
        params = [("to", map_language(self.SOURCE_ID, self.target, "target"))]
        source = map_language(self.SOURCE_ID, self.source, "source")
        if source:
            params.append(("from", source))
        params.append(("isEnterpriseClient", "false"))
        url = f"{self.ENDPOINT}?{urllib.parse.urlencode(params)}"
        body = json.dumps(list(texts), ensure_ascii=False).encode("utf-8")
        data = self._request_json(url, "POST", body, {"Content-Type": "application/json"})
        return [item["translations"][0]["text"] for item in data]


class GoogleWebTranslator(FreeHttpTranslator):
    """Google translate_a/t（POST）。

    旧版 translate_a/single?client=gtx 的 GET 写法已被 Google 停用（稳定 429）。
    """

    SOURCE_ID = "google"
    LABEL = "Google"
    ENDPOINT = "https://translate.googleapis.com/translate_a/t"
    MAX_ITEMS = 200
    MIN_INTERVAL = 0.3
    CONCURRENCY = 2

    def _request(self, texts):
        params = [
            ("client", "gtx"),
            ("sl", map_language(self.SOURCE_ID, self.source, "source")),
            ("tl", map_language(self.SOURCE_ID, self.target, "target")),
            ("dt", "t"),
        ]
        params.extend(("q", text) for text in texts)
        body = urllib.parse.urlencode(params).encode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": BROWSER_USER_AGENT,
        }
        data = self._request_json(self.ENDPOINT, "POST", body, headers)
        return [self._extract(item) for item in data]

    @staticmethod
    def _extract(item):
        # sl=en → "刀"；sl=auto → ["刀", "en"]
        if isinstance(item, str):
            return item
        if isinstance(item, (list, tuple)) and item:
            return item[0]
        return ""


class TencentInteractiveTranslator(FreeHttpTranslator):
    """腾讯交互翻译（transmart）。免密钥，一次最多 300 条。"""

    SOURCE_ID = "tencent"
    LABEL = "Tencent"
    ENDPOINT = "https://transmart.qq.com/api/imt"
    MAX_ITEMS = 300
    MAX_CHARS = 1000
    MIN_INTERVAL = 0.3
    CONCURRENCY = 2

    def _request(self, texts):
        payload = {
            "header": {"fn": "auto_translation", "client_key": TENCENT_CLIENT_KEY},
            "type": "plain",
            "model_category": "normal",
            "source": {
                "text_list": list(texts),
                "lang": map_language(self.SOURCE_ID, self.source, "source"),
            },
            "target": {"lang": map_language(self.SOURCE_ID, self.target, "target")},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        data = self._request_json(self.ENDPOINT, "POST", body, {"Content-Type": "application/json"})
        header = data.get("header") or {}
        if header.get("ret_code") != "succ":
            raise TranslationRequestError(
                f"Tencent returned {header.get('ret_code')!r}: {header.get('message', '')}"
            )
        return list(data.get("auto_translation") or [])


class VolcanoTranslator(FreeHttpTranslator):
    """火山翻译。免密钥，只能单条。"""

    SOURCE_ID = "volcano"
    LABEL = "Volcano"
    ENDPOINT = "https://translate.volcengine.com/crx/translate/v1/"
    MAX_ITEMS = 1
    MAX_CHARS = 1000
    MIN_INTERVAL = 1.0
    CONCURRENCY = 1

    def _request(self, texts):
        payload = {
            "source_language": map_language(self.SOURCE_ID, self.source, "source"),
            "target_language": map_language(self.SOURCE_ID, self.target, "target"),
            "text": texts[0],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        data = self._request_json(self.ENDPOINT, "POST", body, {"Content-Type": "application/json"})
        base = data.get("base_resp") or {}
        if base.get("status_code"):
            raise TranslationRequestError(
                f"Volcano returned status {base.get('status_code')}: {base.get('status_message', '')}"
            )
        return [data.get("translation") or ""]


class LaraTranslator(FreeHttpTranslator):
    """Lara 翻译。免密钥，只能单条。"""

    SOURCE_ID = "lara"
    LABEL = "Lara"
    ENDPOINT = "https://webapi.laratranslate.com/translate/segmented"
    MAX_ITEMS = 1
    MAX_CHARS = 1000
    MIN_INTERVAL = 1.0
    CONCURRENCY = 1

    def _request(self, texts):
        payload = {
            "q": texts[0],
            "target": map_language(self.SOURCE_ID, self.target, "target"),
            "style": "faithful",
            "content_type": "text/plain",
            "adapt_to": [],
            "glossaries": [],
            "instructions": [],
        }
        source = map_language(self.SOURCE_ID, self.source, "source")
        if source:
            payload["source"] = source
            payload["source_hint"] = ""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Lara-Client": "Webapp"}
        data = self._request_json(self.ENDPOINT, "POST", body, headers)
        content = data.get("content") or {}
        translations = content.get("translations") or []
        if not translations:
            raise TranslationRequestError(
                f"Lara returned no translation: {data.get('message') or data}"
            )
        return [translations[0].get("translation") or ""]


class MyMemoryTranslator(FreeHttpTranslator):
    """MyMemory。免密钥，单条、单次 ≤500 UTF-8 字节、匿名 5000 字符/天。"""

    SOURCE_ID = "mymemory"
    LABEL = "MyMemory"
    ENDPOINT = "https://api.mymemory.translated.net/get"
    MAX_ITEMS = 1
    MAX_BYTES = 500
    MIN_INTERVAL = 1.0
    CONCURRENCY = 1

    def _request(self, texts):
        langpair = "{}|{}".format(
            map_language(self.SOURCE_ID, self.source, "source"),
            map_language(self.SOURCE_ID, self.target, "target"),
        )
        query = urllib.parse.urlencode({"q": texts[0], "langpair": langpair})
        data = self._request_json(
            f"{self.ENDPOINT}?{query}", "GET", None, {"User-Agent": BROWSER_USER_AGENT}
        )
        if data.get("quotaFinished") is True:
            raise TranslationRequestError("MyMemory daily quota exhausted.", status=429)
        text = (data.get("responseData") or {}).get("translatedText") or ""
        status = data.get("responseStatus")
        if str(status) != "200" or "MYMEMORY WARNING" in text.upper():
            raise TranslationRequestError(
                f"MyMemory returned {status}: {text or data.get('responseDetails')}"
            )
        return [text]


FREE_TRANSLATOR_CLASSES = {
    "google": GoogleWebTranslator,
    "microsoft": MicrosoftEdgeTranslator,
    "tencent": TencentInteractiveTranslator,
    "volcano": VolcanoTranslator,
    "lara": LaraTranslator,
    "mymemory": MyMemoryTranslator,
}

FREE_SOURCE_SPECS = {
    source_id: {
        "label_key": f"source_{source_id}",
        "items": cls.MAX_ITEMS,
        "chars": cls.MAX_CHARS,
        "bytes": cls.MAX_BYTES,
        "interval": cls.MIN_INTERVAL,
        "concurrency": cls.CONCURRENCY,
    }
    for source_id, cls in FREE_TRANSLATOR_CLASSES.items()
}
FREE_SOURCE_SPECS["deepl"] = {
    "label_key": "source_deepl",
    "items": 50, "chars": None, "bytes": None,
    "interval": 0.2, "concurrency": 2, "needs_key": True,
}
```

> 注意：`deepl` **不在** `FREE_TRANSLATOR_CLASSES` 里（它走 deep-translator，不是免费 HTTP 客户端），只在 `FREE_SOURCE_SPECS` 里有一条显式条目 —— 界面需要它的「并发 / 间隔 / 需要密钥」这三个数字。所以 `RegistryTests.test_every_spec_has_a_class` 断言的是**子集**关系，不是相等。

- [ ] **Step 4: 跑到通过**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_free_translators -v 2>&1 | tail -5
```

预期：`OK`

- [ ] **Step 5: 顺手删掉勘察脚本（它没有被 git 跟踪，只删文件）**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && rm -f _probe_lang.py
```

> `_probe_lang.py` **没有被 git 跟踪**（它不在 `.git/index` 里），所以只删文件，不要对它执行 `git rm` —— 那会报 `fatal: pathspec '_probe_lang.py' did not match any files`。

- [ ] **Step 6: commit**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && git add free_translators.py tests/test_free_translators.py && git commit -m "feat: add keyless translators for microsoft edge, google, tencent, volcano, lara and mymemory"
```

---

### Task 2: `translator_service.py` 接入免费源

**Files:**

- Modify: `translator_service.py`
- Modify: `tests/test_translator_service.py`

- [ ] **Step 1: 写会失败的测试**

在 `tests/test_translator_service.py` 里**新增**（放在 `TranslationServiceTests` 之后）：

```python
class FreeProviderTests(unittest.TestCase):
    def test_config_carries_label_and_min_interval(self):
        config = TranslatorConfig(provider="microsoft", label="微软翻译", min_interval=0.1)
        self.assertEqual(config.label, "微软翻译")
        self.assertEqual(config.min_interval, 0.1)

    def test_free_providers_need_no_api_key(self):
        for provider in ("google", "microsoft", "tencent", "volcano", "lara", "mymemory"):
            validate_translator_config(TranslatorConfig(provider=provider))

    def test_deepl_still_requires_api_key(self):
        with self.assertRaises(ValueError):
            validate_translator_config(TranslatorConfig(provider="deepl"))

    def test_create_provider_returns_free_client_for_every_free_source(self):
        from free_translators import FREE_TRANSLATOR_CLASSES
        service = TranslationService()
        for source_id, cls in FREE_TRANSLATOR_CLASSES.items():
            provider = service.create_provider("en", "zh-CN", TranslatorConfig(provider=source_id))
            self.assertIsInstance(provider, cls)

    def test_rate_limiter_is_cleared_after_a_run(self):
        service = TranslationService(provider_factory=lambda *a, **k: FakeBatchTranslator())
        config = TranslatorConfig(provider="volcano", min_interval=1.0, parallel_batches=1)
        service.translate_jobs([TranslationJob(0, 1, "Knife", "en", "de")], config)
        self.assertIsNone(service.rate_limiter)     # translate_jobs 结束后清空

    def test_translate_jobs_wires_min_interval_into_rate_limiter(self):
        seen = {}

        class ProbeService(TranslationService):
            def _translate_batches(self, *args, **kwargs):
                seen["interval"] = self.rate_limiter.min_interval
                return None

        service = ProbeService(provider_factory=lambda *a, **k: FakeBatchTranslator())
        service.translate_jobs(
            [TranslationJob(0, 1, "Knife", "en", "de")],
            TranslatorConfig(provider="volcano", min_interval=1.0),
        )
        self.assertEqual(seen["interval"], 1.0)

    def test_google_provider_no_longer_has_a_hardcoded_interval(self):
        import translator_service
        self.assertFalse(hasattr(translator_service, "GOOGLE_MIN_INTERVAL"))
```

`FakeBatchTranslator` 是 `tests/test_translator_service.py:12` 已有的辅助类，**无参构造**（`def __init__(self)`），`translate_batch(texts)` 固定返回 `[f"translated:{text}" for text in texts]`。**不要给它传参**，也不要指望它按语言对查表。

**同时改掉 `GuardedBatchTests` 里那处用 `google_translator_class` 的既有测试**（真实 `tests/test_translator_service.py:1049`；计划原先写的 `:720` 那处在 `GoogleProviderIntegrationTests` 内部，随整类重写一起消失，不用单独改）：

```python
        service.free_translator_classes = {"google": FakeGoogle}
```

**并把两个 fake 的 `__init__` 签名改成和免费源客户端一致**（`tests/test_translator_service.py:708` 的 `FakeGoogle` 与 `GuardedBatchTests` 里的 `RateLimitedGoogle`）。真实签名第 3 个位置参数是**必填的 `base_url`**，而新的免费源分支不传 `base_url` → `TypeError`：

```python
class FakeGoogle:
    def __init__(self, source, target, timeout=None, should_cancel=None,
                 retry_policy=None, on_retry=None, before_attempt=None):
        self.source = source
        self.target = target
        self.should_cancel = should_cancel
        self.retry_policy = retry_policy
        self.on_retry = on_retry
        self.before_attempt = before_attempt
        self.calls = []
```

（`RateLimitedGoogle` 照同样的签名改。如果某条既有测试需要 `base_url`，用关键字参数传。）

并把 `GoogleProviderIntegrationTests`（`:694`）改成 POST 形状：

```python
class GoogleProviderIntegrationTests(unittest.TestCase):
    """走真实 urllib 路径（mock.patch urlopen），验证 POST translate_a/t。"""

    def test_end_to_end_translate_via_urllib(self):
        import io
        import json as jsonlib
        from unittest import mock

        captured = {}

        class FakeResponse:
            def __init__(self, payload):
                self.payload = jsonlib.dumps(payload).encode("utf-8")

            def read(self):
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = request.data
            return FakeResponse(["刀"])

        service = TranslationService()
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            results = service.translate_jobs(jobs, TranslatorConfig(provider="google"))
        self.assertEqual(results.cell_results[(0, 1)], "刀")
        self.assertEqual(captured["method"], "POST")
        self.assertIn("translate_a/t", captured["url"])
        self.assertIn(b"q=Knife", captured["body"])
```

**删除** `GoogleTranslateTranslatorTests`（`:545`–`:693`）整类，以及 `:9` 的 import 里 `GoogleTranslateTranslator`、`:541` 的 `_google_response` 辅助函数（真实名字是 `_google_response`，不是 `_fake_single_response`）。

- [ ] **Step 2: 跑到失败**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_translator_service -v 2>&1 | tail -8
```

预期：`ImportError: cannot import name 'GoogleTranslateTranslator'`（如果先删了 import）或 `AttributeError: 'TranslatorConfig' object has no attribute 'label'`。

- [ ] **Step 3: 改 `translator_service.py`**

**(a) 删掉 `GOOGLE_MIN_INTERVAL`**（`:25`）：

```python
# —— 限速与重试（决定 9 / 12 / 14）——
RETRY_MAX_ATTEMPTS = 5
```

**(b) `TranslatorConfig` 加两个字段**（`:227`）：

```python
@dataclass(frozen=True)
class TranslatorConfig:
    provider: str = "google"
    label: str = ""                 # 界面上的源名，降级提示要用
    char_budget: int = DEFAULT_CHAR_BUDGET
    parallel_batches: int = 1
    min_interval: float = 0.0       # 全局限速：两次请求最小间隔（秒）
    api_key: str = ""
    region: str = ""
    model: str = ""
    email: str = ""
    base_url: str = ""
    timeout: float = 60.0
    glossary: list = field(default_factory=list)
    glossary_source_key: str = ""
    auto_concurrency: bool = True
```

**(c) `TranslationService.__init__` 把 `google_translator_class` 换成注册表**（`:265`）：

```python
        self.openai_translator_class = OpenAICompatibleTranslator
        self.claude_translator_class = ClaudeMessagesTranslator
        self.codex_translator_class = CodexResponsesTranslator
        self.free_translator_classes = None      # None = 用 free_translators 的注册表
```

**(d) `create_provider` 开头接免费源**（`:269`）：

```python
    def create_provider(self, source, target, config):
        provider = normalize_provider(config.provider)
        free_classes = self.free_translator_classes
        if free_classes is None:
            from free_translators import FREE_TRANSLATOR_CLASSES

            free_classes = FREE_TRANSLATOR_CLASSES
        free_class = free_classes.get(provider)
        if free_class is not None:
            return free_class(
                source=source,
                target=target,
                timeout=config.timeout,
                should_cancel=self.should_cancel,
                retry_policy=self.retry_policy,
                on_retry=self.on_retry,
                before_attempt=self._throttle,
            )
        if provider == "deepl":
            from deep_translator import DeeplTranslator

            return DeeplTranslator(source=source, target=target, api_key=config.api_key)
```

并**删除**原来的 `if provider == "google":` 分支、`if provider == "mymemory":` 分支、`if provider == "microsoft":` 分支。

**(e) `translate_jobs` 用 `config.min_interval`**（`:338` 附近）：

```python
        # 每个源的最小请求间隔由源列表提供（免费源内置，AI 源可自定义）
        self.rate_limiter = RateLimiter(max(0.0, float(config.min_interval or 0.0)))
```

**(f) `validate_translator_config` 去掉 mymemory / microsoft**（`:679`）：

```python
def validate_translator_config(config):
    provider = normalize_provider(config.provider)
    if provider == "deepl" and not config.api_key:
        raise ValueError("DeepL requires an API key.")
    if provider == "openai" and not config.api_key:
        raise ValueError("OpenAI translator requires an API key.")
    if provider == "claude" and not config.api_key:
        raise ValueError("Claude translator requires an API key.")
    if provider == "codex" and not config.api_key:
        raise ValueError("Codex translator requires an API key.")
```

**(g) 删除 `GoogleTranslateTranslator` 类**（`:1253` 到文件末尾）。文件末尾现在停在 `CodexResponsesTranslator`。

- [ ] **Step 4: 跑到通过**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_translator_service tests.test_free_translators 2>&1 | tail -5
```

- [ ] **Step 5: commit**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && git add translator_service.py tests/test_translator_service.py && git commit -m "feat: route free providers through keyless clients and drop the dead google single endpoint"
```

---

### Task 3: `translation_sources.py` —— 统一源列表数据模型

**Files:**

- Create: `translation_sources.py`
- Create: `tests/test_translation_sources.py`

- [ ] **Step 1: 写会失败的测试**

新建 `tests/test_translation_sources.py`：

```python
import json
import unittest

from translation_sources import (
    ALL_RULES,
    DEFAULT_SOURCE_ORDER,
    RULE_ALL,
    RULE_EMPTY,
    RULE_SELECTION,
    SourceEntry,
    SourceList,
)


class DefaultsTests(unittest.TestCase):
    def test_default_order_matches_the_interview_decision(self):
        sources = SourceList()
        self.assertEqual([e.source_id for e in sources.entries], list(DEFAULT_SOURCE_ORDER))
        self.assertEqual(
            [e.source_id for e in sources.entries][:6],
            ["google", "microsoft", "tencent", "volcano", "lara", "mymemory"],
        )

    def test_first_three_are_batch_sources_with_all_rules(self):
        sources = SourceList()
        for source_id in ("google", "microsoft", "tencent"):
            entry = sources.find(source_id)
            self.assertEqual(sorted(entry.rules), sorted(ALL_RULES))

    def test_single_item_sources_default_to_selection_only(self):
        sources = SourceList()
        for source_id in ("volcano", "lara", "mymemory"):
            self.assertEqual(sources.find(source_id).rules, [RULE_SELECTION])

    def test_no_ai_source_out_of_the_box(self):
        sources = SourceList()
        self.assertFalse([e for e in sources.entries if e.is_ai])


class RuleFilterTests(unittest.TestCase):
    def test_candidates_follow_list_order(self):
        sources = SourceList()
        self.assertEqual(
            [e.source_id for e in sources.candidates(RULE_ALL)],
            ["google", "microsoft", "tencent"],
        )
        self.assertEqual(
            [e.source_id for e in sources.candidates(RULE_SELECTION)],
            ["google", "microsoft", "tencent", "volcano", "lara", "mymemory"],
        )

    def test_reordering_changes_priority(self):
        sources = SourceList()
        sources.move_up("mymemory")
        # move_up 只换一格：mymemory 从第 6 位挪到第 5 位（lara 前面），前两名不变
        self.assertEqual(
            [e.source_id for e in sources.entries][-2:], ["mymemory", "lara"]
        )
        for _ in range(5):
            sources.move_up("mymemory")
        self.assertEqual(
            [e.source_id for e in sources.candidates(RULE_SELECTION)][:2],
            ["google", "mymemory"],
        )

    def test_empty_rules_are_excluded(self):
        sources = SourceList()
        self.assertEqual(sources.candidates(RULE_ALL)[-1].source_id, "tencent")
        self.assertEqual([e.source_id for e in sources.candidates("nope")], [])


class EditTests(unittest.TestCase):
    def test_move_up_and_down_swap_neighbours(self):
        sources = SourceList()
        sources.move_up("tencent")
        self.assertEqual(
            [e.source_id for e in sources.entries][:3], ["google", "tencent", "microsoft"]
        )
        sources.move_down("google")
        self.assertEqual(
            [e.source_id for e in sources.entries][:3], ["tencent", "google", "microsoft"]
        )

    def test_move_at_edges_is_a_noop(self):
        sources = SourceList()
        sources.move_up("google")
        sources.move_down("deepl")
        self.assertEqual([e.source_id for e in sources.entries], list(DEFAULT_SOURCE_ORDER))

    def test_remove_drops_the_entry(self):
        sources = SourceList()
        sources.remove("lara")
        self.assertIsNone(sources.find("lara"))

    def test_add_ai_source_assigns_a_unique_id(self):
        sources = SourceList()
        entry = SourceEntry(kind="ai", name="我的 GPT", api_type="openai",
                            rules=[RULE_SELECTION], api_key="k", model="gpt-4o-mini")
        sources.add_ai(entry)
        self.assertTrue(entry.source_id.startswith("ai:"))
        other = SourceEntry(kind="ai", name="另一个", api_type="claude", rules=[RULE_SELECTION])
        sources.add_ai(other)
        self.assertNotEqual(entry.source_id, other.source_id)

    def test_add_ai_source_appends_to_the_end(self):
        sources = SourceList()
        sources.add_ai(SourceEntry(kind="ai", name="X", api_type="openai"))
        self.assertTrue(sources.entries[-1].is_ai)

    def test_has_name_detects_duplicates(self):
        sources = SourceList()
        sources.add_ai(SourceEntry(kind="ai", name="同名", api_type="openai"))
        self.assertTrue(sources.has_name("同名"))
        self.assertFalse(sources.has_name("别的"))

    def test_set_rule_toggles_membership(self):
        sources = SourceList()
        sources.set_rule("volcano", RULE_ALL, True)
        self.assertIn(RULE_ALL, sources.find("volcano").rules)
        sources.set_rule("volcano", RULE_ALL, False)
        self.assertNotIn(RULE_ALL, sources.find("volcano").rules)


class SerializationTests(unittest.TestCase):
    def test_round_trip_keeps_order_rules_and_ai_settings(self):
        sources = SourceList()
        sources.add_ai(SourceEntry(kind="ai", name="我的 GPT", api_type="claude",
                                   rules=[RULE_ALL, RULE_SELECTION], api_key="sk-1",
                                   base_url="https://x.test/v1", model="claude-x",
                                   concurrency=4, interval=0.5))
        sources.move_up("mymemory")
        restored = SourceList.from_json(sources.to_json())
        self.assertEqual(
            [e.source_id for e in restored.entries], [e.source_id for e in sources.entries]
        )
        ai = [e for e in restored.entries if e.is_ai][0]
        self.assertEqual(ai.name, "我的 GPT")
        self.assertEqual(ai.api_type, "claude")
        self.assertEqual(ai.api_key, "sk-1")
        self.assertEqual(ai.base_url, "https://x.test/v1")
        self.assertEqual(ai.model, "claude-x")
        self.assertEqual(ai.concurrency, 4)
        self.assertEqual(ai.interval, 0.5)
        self.assertEqual(sorted(ai.rules), sorted([RULE_ALL, RULE_SELECTION]))

    def test_blank_input_falls_back_to_defaults(self):
        for raw in ("", None, "   "):
            self.assertEqual(
                [e.source_id for e in SourceList.from_json(raw).entries],
                list(DEFAULT_SOURCE_ORDER),
            )

    def test_broken_json_falls_back_to_defaults(self):
        self.assertEqual(
            [e.source_id for e in SourceList.from_json("{not json").entries],
            list(DEFAULT_SOURCE_ORDER),
        )

    def test_unknown_builtin_ids_are_dropped_but_ai_entries_survive(self):
        raw = json.dumps({
            "version": 1,
            "entries": [
                {"id": "google", "kind": "free", "rules": ["all"]},
                {"id": "yandex", "kind": "free", "rules": ["all"]},
                {"id": "ai:abcd1234", "kind": "ai", "name": "X", "api_type": "openai", "rules": []},
            ],
        })
        sources = SourceList.from_json(raw)
        self.assertEqual([e.source_id for e in sources.entries], ["google", "ai:abcd1234"])

    def test_clone_is_independent(self):
        sources = SourceList()
        clone = sources.clone()
        clone.set_rule("google", RULE_ALL, False)
        self.assertIn(RULE_ALL, sources.find("google").rules)
        self.assertNotIn(RULE_ALL, clone.find("google").rules)


class ValidationTests(unittest.TestCase):
    def test_invalid_rules_are_ignored_on_load(self):
        raw = json.dumps({"version": 1, "entries": [
            {"id": "google", "kind": "free", "rules": ["all", "bogus"]},
        ]})
        self.assertEqual(SourceList.from_json(raw).find("google").rules, [RULE_ALL])

    def test_ai_entry_without_name_still_loads(self):
        raw = json.dumps({"version": 1, "entries": [
            {"id": "ai:1", "kind": "ai", "api_type": "openai", "rules": ["all"]},
        ]})
        entry = SourceList.from_json(raw).entries[0]
        self.assertEqual(entry.name, "")
        self.assertEqual(entry.api_type, "openai")
        self.assertEqual(entry.concurrency, 1)
        self.assertEqual(entry.interval, 0.0)
```

- [ ] **Step 2: 跑到失败**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_translation_sources 2>&1 | tail -3
```

预期：`ModuleNotFoundError: No module named 'translation_sources'`

- [ ] **Step 3: 实现 `translation_sources.py`**

```python
"""统一翻译源列表：顺序 = 权重 = 优先级；每个源带自己的规则与设置。"""

import json
import uuid
from dataclasses import dataclass, field

RULE_ALL = "all"
RULE_EMPTY = "empty"
RULE_SELECTION = "selection"
ALL_RULES = (RULE_ALL, RULE_EMPTY, RULE_SELECTION)

# 出厂顺序（决定 14）。deepl 排在最后且默认不勾选（决定 25）。
DEFAULT_SOURCE_ORDER = ("google", "microsoft", "tencent", "volcano", "lara", "mymemory", "deepl")

# 出厂勾选（决定 15）：前三个批量源全勾；三个单条源只勾「右键选中」；deepl 不勾。
DEFAULT_SOURCE_RULES = {
    "google": ALL_RULES,
    "microsoft": ALL_RULES,
    "tencent": ALL_RULES,
    "volcano": (RULE_SELECTION,),
    "lara": (RULE_SELECTION,),
    "mymemory": (RULE_SELECTION,),
    "deepl": (),
}

FORMAT_VERSION = 1


def _clean_rules(values):
    seen = []
    for value in values or ():
        if value in ALL_RULES and value not in seen:
            seen.append(value)
    return seen


@dataclass
class SourceEntry:
    """列表里的一行。

    source_id：内置源是固定 id（"google"）；AI 源是 "ai:<8 位十六进制>"。
    kind："free" | "ai"。
    api_type：只有 AI 源有值，取值 "openai" | "claude" | "codex"。
    name：只有 AI 源有值（内置源的名字来自界面文案）。
    """

    source_id: str = ""
    kind: str = "free"
    name: str = ""
    api_type: str = ""
    rules: list = field(default_factory=list)
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    concurrency: int = 1
    interval: float = 0.0

    @property
    def is_ai(self):
        return self.kind == "ai"

    def to_dict(self):
        # api_key 无条件写：免费源里 DeepL 也要密钥（FREE_SOURCE_SPECS["deepl"]["needs_key"]）
        data = {"id": self.source_id, "kind": self.kind, "rules": list(self.rules),
                "api_key": self.api_key}
        if self.is_ai:
            data.update({
                "name": self.name,
                "api_type": self.api_type,
                "base_url": self.base_url,
                "model": self.model,
                "concurrency": int(self.concurrency or 1),
                "interval": float(self.interval or 0.0),
            })
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        source_id = str(data.get("id") or "").strip()
        kind = "ai" if str(data.get("kind")) == "ai" else "free"
        if not source_id:
            return None
        entry = cls(
            source_id=source_id,
            kind=kind,
            name=str(data.get("name") or ""),
            api_type=str(data.get("api_type") or ""),
            rules=_clean_rules(data.get("rules")),
            api_key=str(data.get("api_key") or ""),     # 免费源里 DeepL 也要密钥
        )
        if kind == "ai":
            entry.base_url = str(data.get("base_url") or "")
            entry.model = str(data.get("model") or "")
            try:
                entry.concurrency = max(1, int(data.get("concurrency") or 1))
            except (TypeError, ValueError):
                entry.concurrency = 1
            try:
                entry.interval = max(0.0, float(data.get("interval") or 0.0))
            except (TypeError, ValueError):
                entry.interval = 0.0
        return entry


class SourceList:
    """翻译源列表。顺序就是权重，第一个能用的源会被整份使用。"""

    def __init__(self, entries=None):
        self.entries = list(entries) if entries is not None else self.default_entries()

    @staticmethod
    def default_entries():
        return [
            SourceEntry(source_id=source_id, kind="free", rules=list(DEFAULT_SOURCE_RULES[source_id]))
            for source_id in DEFAULT_SOURCE_ORDER
        ]

    # —— 查询 ——

    def find(self, source_id):
        for entry in self.entries:
            if entry.source_id == source_id:
                return entry
        return None

    def index_of(self, source_id):
        for index, entry in enumerate(self.entries):
            if entry.source_id == source_id:
                return index
        return -1

    def has_name(self, name):
        name = (name or "").strip()
        return any(entry.name == name for entry in self.entries if entry.is_ai)

    def candidates(self, rule):
        """按列表顺序返回勾了这条规则的源。"""
        return [entry for entry in self.entries if rule in entry.rules]

    # —— 编辑 ——

    def set_rule(self, source_id, rule, enabled):
        entry = self.find(source_id)
        if entry is None or rule not in ALL_RULES:
            return
        if enabled and rule not in entry.rules:
            entry.rules = [value for value in ALL_RULES if value in entry.rules or value == rule]
        elif not enabled and rule in entry.rules:
            entry.rules = [value for value in entry.rules if value != rule]

    def move_up(self, source_id):
        index = self.index_of(source_id)
        if index > 0:
            self.entries[index - 1], self.entries[index] = self.entries[index], self.entries[index - 1]

    def move_down(self, source_id):
        index = self.index_of(source_id)
        if 0 <= index < len(self.entries) - 1:
            self.entries[index + 1], self.entries[index] = self.entries[index], self.entries[index + 1]

    def remove(self, source_id):
        self.entries = [entry for entry in self.entries if entry.source_id != source_id]

    def add_ai(self, entry, source_id=None):
        entry.kind = "ai"
        entry.source_id = source_id or f"ai:{uuid.uuid4().hex[:8]}"
        self.entries.append(entry)
        return entry

    # —— 持久化 ——

    def to_json(self):
        return json.dumps(
            {"version": FORMAT_VERSION, "entries": [e.to_dict() for e in self.entries]},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw):
        if not raw or not str(raw).strip():
            return cls()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            return cls()
        entries = []
        for item in raw_entries:
            entry = SourceEntry.from_dict(item)
            if entry is None:
                continue
            if not entry.is_ai and entry.source_id not in DEFAULT_SOURCE_ORDER:
                continue        # 不认识的免费源（例如将来删掉的源）直接丢掉
            entries.append(entry)
        return cls(entries) if entries else cls()

    def clone(self):
        return SourceList.from_json(self.to_json())
```

- [ ] **Step 4: 跑到通过**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_translation_sources 2>&1 | tail -3
```

- [ ] **Step 5: commit**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && git add translation_sources.py tests/test_translation_sources.py && git commit -m "feat: add unified translation source list model with per-source rules"
```

---

### Task 4: 主备降级 `translate_jobs_with_fallback`

**Files:**

- Modify: `translator_service.py`
- Create: `tests/test_translation_fallback.py`

- [ ] **Step 1: 写会失败的测试**

新建 `tests/test_translation_fallback.py`：

```python
import unittest

from translator_service import (
    TranslationCancelled,
    TranslationJob,
    TranslationRequestError,
    TranslationService,
    TranslatorConfig,
)


class RecordingTranslator:
    """按 (source, target) 返回译文；可以配置成抛错或部分失败。"""

    def __init__(self, mapping, fail_texts=(), error=None):
        self.mapping = mapping
        self.fail_texts = set(fail_texts)
        self.error = error
        self.calls = []

    def translate_batch(self, texts):
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return [self.mapping.get(text, f"[{text}]") for text in texts]


class FallbackTests(unittest.TestCase):
    def build(self, translators):
        """translators: {provider: RecordingTranslator}"""
        service = TranslationService(
            provider_factory=lambda source, target, config: translators[config.provider]
        )
        return service

    def configs(self, *providers):
        return [
            TranslatorConfig(provider=p, label=p, parallel_batches=1, min_interval=0.0)
            for p in providers
        ]

    def test_first_source_handles_everything_when_it_works(self):
        first = RecordingTranslator({"Knife": "刀"})
        second = RecordingTranslator({"Knife": "X"})
        service = self.build({"google": first, "microsoft": second})
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(jobs, self.configs("google", "microsoft"))
        self.assertEqual(results.cell_results[(0, 1)], "刀")
        self.assertEqual(second.calls, [])
        self.assertEqual(results.failed, 0)

    def test_falls_back_when_the_probe_fails(self):
        broken = RecordingTranslator({}, error=TranslationRequestError("boom", status=503))
        good = RecordingTranslator({"Knife": "刀"})
        service = self.build({"microsoft": broken, "google": good})
        seen = []
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(
            jobs, self.configs("microsoft", "google"), on_fallback=lambda a, b: seen.append((a, b))
        )
        self.assertEqual(results.cell_results[(0, 1)], "刀")
        self.assertEqual(seen, [("microsoft", "google")])

    def test_fallback_only_retries_the_failed_cells(self):
        # 第一个源只有部分文本能翻：整批会被记失败，但已成功的那条应保留
        partial = RecordingTranslator({"Knife": "刀", "Gun": "枪"})
        original = partial.translate_batch

        def flaky(texts):
            if "Gun" in texts:
                raise TranslationRequestError("boom", status=503)
            return original(texts)

        partial.translate_batch = flaky
        good = RecordingTranslator({"Gun": "枪（备）"})
        service = self.build({"microsoft": partial, "google": good})
        jobs = [
            TranslationJob(0, 1, "Knife", "en", "zh-CN"),
            TranslationJob(0, 2, "Gun", "en", "zh-CN"),
        ]
        results = service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        self.assertEqual(results.cell_results[(0, 1)], "刀")
        self.assertEqual(results.cell_results[(0, 2)], "枪（备）")
        self.assertEqual(good.calls, [["Gun"]])

    def test_probe_result_is_reused_through_the_cache(self):
        broken = RecordingTranslator({}, error=TranslationRequestError("boom", status=503))
        good = RecordingTranslator({"Knife": "刀", "Gun": "枪"})
        service = self.build({"microsoft": broken, "google": good})
        jobs = [
            TranslationJob(0, 1, "Knife", "en", "zh-CN"),
            TranslationJob(0, 2, "Gun", "en", "zh-CN"),
        ]
        service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        # 试翻只发 Knife；整份只补 Gun。Knife 靠缓存命中，不再发请求。
        self.assertEqual(good.calls, [["Knife"], ["Gun"]])

    def test_all_sources_failing_reports_every_remaining_job(self):
        first = RecordingTranslator({}, error=TranslationRequestError("a", status=503))
        second = RecordingTranslator({}, error=TranslationRequestError("b", status=503))
        service = self.build({"microsoft": first, "google": second})
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        self.assertEqual(results.cell_results, {})
        self.assertEqual(results.failed, 1)
        self.assertTrue(results.errors)

    def test_empty_config_list_raises(self):
        service = self.build({})
        with self.assertRaises(ValueError):
            service.translate_jobs_with_fallback([TranslationJob(0, 1, "Knife", "en", "zh-CN")], [])

    def test_cancellation_stops_the_chain(self):
        class CancelOnSecond:
            def __init__(self):
                self.calls = 0

            def translate_batch(self, texts):
                self.calls += 1
                raise TranslationCancelled()

        service = self.build({"google": CancelOnSecond()})
        state = {"cancelled": False}
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(
            jobs, self.configs("google", "microsoft"), should_cancel=lambda: state["cancelled"]
        )
        self.assertTrue(results.cancelled)

    def test_a_second_source_takes_over_when_the_first_is_dead(self):
        # 第二个源**故意不用 AI provider**（openai / claude / codex）：AI 源走
        # `_translate_openai_jobs` → `_translate_one_openai_batch`，那里调的是
        # `translator.translate_job_batch(...)` 而不是 `translate_batch(...)`
        # （`translator_service.py:583`），RecordingTranslator 没实现那个方法。
        # 「AI 源也参与降级」由 Task 5 的
        # `test_ai_source_config_uses_its_own_concurrency_and_interval` 覆盖
        # （它证明 AI 源确实会出现在 configs 列表里、顺序不变）。
        broken = RecordingTranslator({}, error=TranslationRequestError("boom", status=503))
        second = RecordingTranslator({"Knife": "刀"})
        service = self.build({"google": broken, "deepl": second})
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(jobs, self.configs("google", "deepl"))
        self.assertEqual(results.cell_results[(0, 1)], "刀")

    def test_fallback_is_not_remembered(self):
        """第二次调用仍然从列表第一个源开始试。"""
        first = RecordingTranslator({}, error=TranslationRequestError("boom", status=503))
        second = RecordingTranslator({"Knife": "刀"})
        service = self.build({"microsoft": first, "google": second})
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        first.error = None
        first.mapping["Knife"] = "刀（首选）"
        first.calls.clear()
        results = service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        self.assertTrue(first.calls)
        self.assertEqual(results.cell_results[(0, 1)], "刀（首选）")
```

- [ ] **Step 2: 跑到失败**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_translation_fallback 2>&1 | tail -3
```

预期：`AttributeError: 'TranslationService' object has no attribute 'translate_jobs_with_fallback'`

- [ ] **Step 3: 在 `translator_service.py` 里加两个方法**

放在 `translate_jobs` 之后、`_throttle` 之前：

```python
    def translate_jobs_with_fallback(self, jobs, configs, progress_callback=None,
                                     should_cancel=None, on_fallback=None):
        """按列表顺序主备降级。

        - 先用一条试翻确认源可用；试翻结果进缓存，正式跑不会重复请求。
        - 换源时只补还没翻好的，已翻好的保留。
        - 全部源都不行时，failed = 剩下没翻好的条数。
        - 降级不记住：每次都从 configs[0] 重新试。
        """
        configs = [config for config in (configs or [])]
        if not configs:
            raise ValueError("No translation source is available for this action.")
        combined = TranslationResults()
        remaining = list(jobs)
        if not remaining:
            return combined
        for position, config in enumerate(configs):
            if should_cancel and should_cancel():
                combined.cancelled = True
                return combined
            if position and on_fallback:
                on_fallback(configs[position - 1].label or configs[position - 1].provider,
                            config.label or config.provider)
            available, probe = self._probe_source(remaining, config, should_cancel)
            if probe.cancelled:
                combined.cancelled = True
                return combined
            if not available:
                # 试翻失败：把这个源的原因记下来，换下一个源
                combined.errors.extend(probe.errors)
                combined.failed = len(remaining)
                continue
            results = self.translate_jobs(remaining, config, progress_callback, should_cancel)
            self._merge_results(combined, results)
            if results.cancelled:
                combined.cancelled = True
                return combined
            remaining = [job for job in remaining
                         if (job.row, job.column) not in combined.cell_results]
            if not remaining:
                combined.failed = 0
                return combined
            combined.failed = len(remaining)      # 还有剩的，交给下一个源
        return combined

    def _probe_source(self, jobs, config, should_cancel):
        """用第一条试翻一次；返回 `(这个源可用吗, 试翻结果)`。

        返回整个 probe 而不只是 bool，是因为「全部源都挂掉」时界面要显示原因
        （`probe.errors`），而这些原因只能从这里拿到。
        """
        probe = self.translate_jobs(jobs[:1], config, None, should_cancel)
        return bool(probe.cell_results), probe

    def _merge_results(self, target, source):
        # 注意：`failed` 不在这里合并 —— 它由循环末尾的
        # `combined.failed = len(remaining)` 统一决定（「还剩几条没翻好」），
        # 单个源的局部失败不算最终失败（后面的源会补上）。
        target.cell_results.update(source.cell_results)
        target.translated += source.translated
        target.skipped += source.skipped
        target.cache_hits += source.cache_hits
        target.errors.extend(source.errors)
```

- [ ] **Step 4: 跑到通过**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_translation_fallback 2>&1 | tail -3
```

- [ ] **Step 5: commit**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && git add translator_service.py tests/test_translation_fallback.py && git commit -m "feat: add primary/backup fallback across the translation source list"
```

> **为什么 `translation_worker.py` 不在这个 Task 里改**：worker 的构造签名（`config` → `configs`）一改，`main.py:2507` 的 `create_translation_worker` 立刻传错参数，而它要到「界面 + 接线」那个 Task 才跟着改 —— 中间任何一次 `python -m unittest discover -s tests` 都会出现 `tests/test_main_gui.py:867` 与 `:1385` 两条红。所以 worker 的改动挪到下一个 Task，跟界面和接线**同一个 commit** 落地。

---

### Task 5: 一次性接线（worker + 窗口 + 对话框 + 翻译入口，一个原子提交）

**Files:**

- Modify: `translation_worker.py`
- Modify: `main.py`
- Modify: `tests/test_translation_worker.py`
- Modify: `tests/test_main_gui.py`

> **为什么这是一个 Task 而不是三个**：`TranslationWorker` 的构造签名、`DayzTranslateTool` 上的 `translation_sources` / `build_translation_configs`、`TranslationSettingsDialog` 的重写、以及 `start_translation_worker` / `create_translation_worker` 的接线，这四件事互为前提。任何一件单独提交，`main.py` 都是断的（`TypeError` 或 `AttributeError`），测试套件必红。合并成一次提交，每个 commit 都保持全绿。

- [ ] **Step 1: 改 `translation_worker.py`**

全文替换成：

```python
from PySide6.QtCore import QObject, Signal, Slot


class TranslationWorker(QObject):
    progress = Signal(object)
    retrying = Signal(int, int, int)
    fallback = Signal(str, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service, jobs, configs):
        super().__init__()
        self.service = service
        self.jobs = jobs
        self.configs = list(configs)
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    @Slot()
    def run(self):
        try:
            self.service.on_retry = self.retrying.emit
            results = self.service.translate_jobs_with_fallback(
                self.jobs,
                self.configs,
                progress_callback=self.progress.emit,
                should_cancel=lambda: self.cancelled,
                on_fallback=self.fallback.emit,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(results)
```

- [ ] **Step 2: 改 `tests/test_translation_worker.py`**

```python
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from translation_worker import TranslationWorker
from translator_service import TranslationJob, TranslationResults, TranslatorConfig

app = QApplication.instance() or QApplication([])


class FakeService:
    def __init__(self):
        self.on_retry = None
        self.configs_seen = None
        self.fallback_seen = None

    def translate_jobs_with_fallback(self, jobs, configs, progress_callback=None,
                                     should_cancel=None, on_fallback=None):
        self.configs_seen = list(configs)
        if progress_callback:
            progress_callback(TranslationResults(translated=1))
        if on_fallback:
            on_fallback("微软翻译", "Google")
        return TranslationResults(
            translated=len(jobs),
            cell_results={(job.row, job.column): "done" for job in jobs},
        )


class TranslationWorkerTests(unittest.TestCase):
    def test_worker_emits_progress_fallback_and_finished(self):
        service = FakeService()
        worker = TranslationWorker(
            service=service,
            jobs=[TranslationJob(0, 3, "Knife", "en", "de")],
            configs=[TranslatorConfig(provider="microsoft", label="微软翻译"),
                     TranslatorConfig(provider="google", label="Google")],
        )
        progress, finished, fallback = [], [], []
        worker.progress.connect(progress.append)
        worker.finished.connect(finished.append)
        worker.fallback.connect(lambda a, b: fallback.append((a, b)))

        worker.run()

        self.assertEqual(progress[0].translated, 1)
        self.assertEqual(finished[0].cell_results[(0, 3)], "done")
        self.assertEqual(fallback, [("微软翻译", "Google")])
        self.assertEqual([c.provider for c in service.configs_seen], ["microsoft", "google"])

    def test_worker_reports_failure_when_no_source_is_configured(self):
        class EmptyService(FakeService):
            def translate_jobs_with_fallback(self, jobs, configs, **kwargs):
                raise ValueError("No translation source is available for this action.")

        worker = TranslationWorker(
            service=EmptyService(),
            jobs=[TranslationJob(0, 3, "Knife", "en", "de")],
            configs=[],
        )
        failed = []
        worker.failed.connect(failed.append)
        worker.run()
        self.assertIn("No translation source", failed[0])
```

- [ ] **Step 3: 在 `main.py` 顶部加 import 与常量**

`main.py:45` 的 import 后面加：

```python
from free_translators import FREE_SOURCE_SPECS
from translation_sources import (
    ALL_RULES,
    RULE_ALL,
    RULE_EMPTY,
    RULE_SELECTION,
    SourceEntry,
    SourceList,
)
```

`main.py:43` 的 `PySide6.QtWidgets` import 列表里**补三个名字**：`QDoubleSpinBox`、`QGroupBox`、`QHeaderView`。新对话框要用它们，而现有列表（`QAbstractItemView` … `QVBoxLayout`）里没有这三个 → 不补就是 `NameError`。

`main.py:62` 的 `PROVIDER_LABELS` **删掉**（不再有「单选 provider」）。`PROVIDER_FIELD_KEYS`（`:283`）与 `PROVIDER_DEFAULTS`（`:292`）也删掉。

新增：

```python
SOURCE_TABLE_HEADERS = ("name", "kind", "all", "empty", "selection")
AI_TYPE_KEYS = ("openai", "claude", "codex")
AI_TYPE_LABEL_KEYS = {
    "openai": "ai_type_openai",
    "claude": "ai_type_claude",
    "codex": "ai_type_codex",
}
```

`main.py:43` 的 import 里 `validate_translator_config` 保留（测试按钮还要用），`MAX_AUTO_CONCURRENCY` 保留（AI 源并发上限用）。

- [ ] **Step 4: `UI_TEXT` 成对新增（en 与 zh 各一份）**

en（插在 `"translation_engine": "Translation Engine",` 后面）：

> **同时删掉 `"preset"` 键**（en 的 `"preset": "Preset"` 与 zh 的 `"preset": "预设"`）—— 预设行没了（决定 26），这个键没有任何地方再用。

```python
        "delete": "Delete",
        "translation_sources": "Translation sources",
        "source_rules_all": "All cells",
        "source_rules_empty": "Empty cells",
        "source_rules_selection": "Right-click",
        "source_kind_free": "Free",
        "source_kind_ai": "AI",
        "source_name": "Name",
        "source_type": "Interface",
        "source_builtin": "Built-in limits",
        "source_builtin_text": "Concurrency {concurrency}, interval {interval}s (built in)",
        "source_concurrency": "Concurrency",
        "source_interval": "Interval (s)",
        "source_move_up": "Move up",
        "source_move_down": "Move down",
        "source_remove": "Remove source",
        "add_ai_source": "Add AI source",
        "source_name_required": "Please enter a name for this source.",
        "source_name_duplicate": "A source named \"{name}\" already exists. Add another one anyway?",
        "source_remove_confirm": "Remove \"{name}\"?",
        "no_source_for_action": "No translation source is enabled for \"{action}\". Enable at least one source in Settings.",
        "translation_fallback": "{previous} is unavailable — switched to {current}",
        "no_source_selected": "No source enabled",
        "action_all_cells": "translate all cells",
        "action_empty_cells": "translate empty cells",
        "action_selection": "translate selection",
        "ai_type_openai": "OpenAI compatible",
        "ai_type_claude": "Claude",
        "ai_type_codex": "Codex",
        "source_google": "Google",
        "source_microsoft": "Microsoft (free)",
        "source_tencent": "Tencent Interactive",
        "source_volcano": "Volcano",
        "source_lara": "Lara",
        "source_mymemory": "MyMemory",
        "source_deepl": "DeepL",
```

zh（对应位置）：

```python
        "delete": "删除",
        "translation_sources": "翻译源",
        "source_rules_all": "全表",
        "source_rules_empty": "空白",
        "source_rules_selection": "右键选中",
        "source_kind_free": "免费",
        "source_kind_ai": "AI",
        "source_name": "名称",
        "source_type": "接口类型",
        "source_builtin": "内置限制",
        "source_builtin_text": "并发 {concurrency}，间隔 {interval} 秒（内置，不可修改）",
        "source_concurrency": "并发数",
        "source_interval": "间隔（秒）",
        "source_move_up": "上移",
        "source_move_down": "下移",
        "source_remove": "删除源",
        "add_ai_source": "添加 AI 源",
        "source_name_required": "请给这个翻译源起个名字。",
        "source_name_duplicate": "已经有一个叫「{name}」的翻译源了，还要继续添加吗？",
        "source_remove_confirm": "确定要删除「{name}」吗？",
        "no_source_for_action": "没有任何翻译源被勾选用于「{action}」。请到设置里至少勾选一个源。",
        "translation_fallback": "{previous} 连不上，已自动改用 {current}",
        "no_source_selected": "未启用任何源",
        "action_all_cells": "翻译全表",
        "action_empty_cells": "翻译空白单元格",
        "action_selection": "翻译选中的内容",
        "ai_type_openai": "OpenAI 兼容",
        "ai_type_claude": "Claude",
        "ai_type_codex": "Codex",
        "source_google": "Google",
        "source_microsoft": "微软翻译（免费）",
        "source_tencent": "腾讯交互翻译",
        "source_volcano": "火山翻译",
        "source_lara": "Lara 翻译",
        "source_mymemory": "MyMemory",
        "source_deepl": "DeepL",
```

同时**删掉** en 与 zh 里的 `"parallel_batches"` 与 `"parallel_batches_tooltip"` 两个键。

- [ ] **Step 5: 写会失败的测试**

在 `tests/test_main_gui.py` 顶部 import 区加：

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit
from main import AI_TYPE_KEYS, AiSourceDialog, TranslationSettingsDialog
from translation_sources import ALL_RULES, RULE_ALL, RULE_EMPTY, RULE_SELECTION, SourceEntry, SourceList
```

（`TranslationSettingsDialog` 已经在 import 里，只需补 `AiSourceDialog`、`AI_TYPE_KEYS`、`translation_sources`。`QDialog` 与 `QLineEdit` 是 `AiSourceDialog` 的断言要用的 —— 现有 import 里没有这两个名字。另外确认 `DAYZ_HEADERS` 和 `Path` 已经在 import 里，下面两个新测试类的 `setUp` 要用。）

**新增测试**（放在文件末尾）：

```python
class TranslationSourceListDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
        self.temp.close()
        self.settings = QSettings(self.temp.name, QSettings.IniFormat)
        self.window = DayzTranslateTool(settings=self.settings)
        # `_ensure_dayz_table` 是 MainGuiTests 自己的方法，主窗口没有 —— 这里内联同一段建表逻辑
        self.window.headers = list(DAYZ_HEADERS)
        sample = [
            ["STR_A", "OrigA", "EngA"] + [""] * (len(DAYZ_HEADERS) - 3),
            ["STR_B", "OrigB", "EngB"] + [""] * (len(DAYZ_HEADERS) - 3),
        ]
        self.window.apply_table_rows(sample, dirty=False)
        if self.window.current_path is None:
            self.window.current_path = Path("stringtable.csv")
            self.window.update_current_file_label()

    def tearDown(self):
        self.window.close()
        os.unlink(self.temp.name)

    def dialog(self):
        return TranslationSettingsDialog(self.window)

    def test_default_source_list_order_and_rules(self):
        sources = self.window.translation_sources
        self.assertEqual(
            [e.source_id for e in sources.entries][:6],
            ["google", "microsoft", "tencent", "volcano", "lara", "mymemory"],
        )
        self.assertEqual(sorted(sources.find("google").rules), sorted(ALL_RULES))
        self.assertEqual(sources.find("volcano").rules, [RULE_SELECTION])
        self.assertEqual(sources.find("deepl").rules, [])
        self.assertFalse([e for e in sources.entries if e.is_ai])

    def test_table_shows_one_row_per_source_with_three_checkboxes(self):
        dialog = self.dialog()
        self.assertEqual(dialog.source_table.rowCount(), len(self.window.translation_sources.entries))
        self.assertEqual(dialog.source_table.columnCount(), 5)
        self.assertTrue(dialog.source_table.cellWidget(0, 2).isChecked())
        self.assertTrue(dialog.source_table.cellWidget(0, 3).isChecked())
        self.assertTrue(dialog.source_table.cellWidget(0, 4).isChecked())

    def test_toggling_a_checkbox_updates_the_working_copy_only_after_save(self):
        dialog = self.dialog()
        dialog.source_table.cellWidget(0, 2).setChecked(False)
        self.assertIn(RULE_ALL, self.window.translation_sources.find("google").rules)
        dialog.apply_settings()
        self.assertNotIn(RULE_ALL, self.window.translation_sources.find("google").rules)

    def test_move_buttons_reorder_the_list(self):
        dialog = self.dialog()
        dialog.source_table.selectRow(2)          # tencent
        dialog.move_up_button.click()
        dialog.apply_settings()
        self.assertEqual(
            [e.source_id for e in self.window.translation_sources.entries][:3],
            ["google", "tencent", "microsoft"],
        )

    def test_free_source_shows_read_only_builtin_limits(self):
        dialog = self.dialog()
        dialog.source_table.selectRow(0)          # google
        self.assertTrue(dialog.is_field_visible("source_builtin"))
        self.assertFalse(dialog.is_field_visible("source_concurrency"))
        self.assertFalse(dialog.is_field_visible("source_interval"))
        self.assertFalse(dialog.is_field_visible("source_type"))
        self.assertFalse(dialog.is_field_visible("source_api_key"))
        self.assertIn("0.3", dialog.source_builtin_label.text())

    def test_ai_source_shows_editable_settings(self):
        dialog = self.dialog()
        entry = SourceEntry(kind="ai", name="我的 GPT", api_type="openai", rules=[RULE_SELECTION],
                            api_key="sk-x", base_url="https://x.test/v1", model="gpt-4o-mini",
                            concurrency=4, interval=0.5)
        dialog.sources.add_ai(entry, source_id="ai:test1")
        dialog.refresh_source_table(select_id="ai:test1")
        self.assertFalse(dialog.is_field_visible("source_builtin"))
        self.assertTrue(dialog.is_field_visible("source_type"))
        self.assertTrue(dialog.is_field_visible("source_api_key"))
        self.assertTrue(dialog.is_field_visible("source_model"))
        self.assertTrue(dialog.is_field_visible("source_concurrency"))
        self.assertTrue(dialog.is_field_visible("source_interval"))
        self.assertEqual(dialog.source_api_key_input.text(), "sk-x")
        self.assertEqual(dialog.source_concurrency_input.value(), 4)
        self.assertEqual(dialog.source_interval_input.value(), 0.5)

    def test_ai_settings_are_saved_per_source(self):
        dialog = self.dialog()
        first = SourceEntry(kind="ai", name="A", api_type="openai", rules=[RULE_SELECTION], api_key="key-a")
        second = SourceEntry(kind="ai", name="B", api_type="claude", rules=[RULE_SELECTION], api_key="key-b")
        dialog.sources.add_ai(first, source_id="ai:a")
        dialog.sources.add_ai(second, source_id="ai:b")
        dialog.refresh_source_table(select_id="ai:a")
        dialog.source_api_key_input.setText("key-a2")
        dialog.refresh_source_table(select_id="ai:b")
        self.assertEqual(dialog.source_api_key_input.text(), "key-b")
        dialog.refresh_source_table(select_id="ai:a")
        self.assertEqual(dialog.source_api_key_input.text(), "key-a2")

    def test_remove_button_drops_the_selected_ai_source(self):
        dialog = self.dialog()
        entry = SourceEntry(kind="ai", name="临时", api_type="openai", rules=[RULE_SELECTION])
        dialog.sources.add_ai(entry, source_id="ai:gone")
        dialog.refresh_source_table(select_id="ai:gone")
        with unittest.mock.patch("main.QMessageBox.question", return_value=QMessageBox.Yes):
            dialog.remove_source_button.click()
        self.assertIsNone(dialog.sources.find("ai:gone"))

    def test_remove_button_refuses_to_drop_builtin_sources(self):
        dialog = self.dialog()
        dialog.source_table.selectRow(0)
        dialog.remove_source_button.click()
        self.assertIsNotNone(dialog.sources.find("google"))

    def test_add_ai_dialog_collects_every_field(self):
        window = self.window
        dialog = AiSourceDialog(window, window)
        dialog.name_input.setText("我的 Claude")
        dialog.type_combo.setCurrentIndex(AI_TYPE_KEYS.index("claude"))
        dialog.base_url_input.setText("https://api.test/v1")
        dialog.api_key_input.setText("sk-secret")
        dialog.model_input.setText("claude-3-5")
        dialog.concurrency_input.setValue(3)
        dialog.interval_input.setValue(0.4)
        values = dialog.values()
        self.assertEqual(values["name"], "我的 Claude")
        self.assertEqual(values["api_type"], "claude")
        self.assertEqual(values["base_url"], "https://api.test/v1")
        self.assertEqual(values["api_key"], "sk-secret")
        self.assertEqual(values["model"], "claude-3-5")
        self.assertEqual(values["concurrency"], 3)
        self.assertEqual(values["interval"], 0.4)

    def test_api_key_field_is_a_password_box(self):
        dialog = AiSourceDialog(self.window, self.window)
        self.assertEqual(dialog.api_key_input.echoMode(), QLineEdit.Password)

    def test_add_ai_source_warns_on_duplicate_name(self):
        dialog = self.dialog()
        dialog.sources.add_ai(SourceEntry(kind="ai", name="重复", api_type="openai"), source_id="ai:dup")
        fake = unittest.mock.MagicMock()
        fake.exec.return_value = QDialog.Accepted
        fake.values.return_value = {
            "name": "重复", "api_type": "openai", "base_url": "", "api_key": "",
            "model": "", "concurrency": 1, "interval": 0.0,
        }
        dialog.ai_dialog_class = lambda *a, **k: fake
        with unittest.mock.patch("main.QMessageBox.question", return_value=QMessageBox.No) as asked:
            dialog.add_ai_source_button.click()
        self.assertTrue(asked.called)
        self.assertEqual(len([e for e in dialog.sources.entries if e.is_ai]), 1)

    def test_char_budget_and_timeout_still_present(self):
        dialog = self.dialog()
        self.assertEqual(dialog.char_budget_input.minimum(), MIN_CHAR_BUDGET)
        self.assertTrue(dialog.char_budget_input.toolTip())
        self.assertTrue(dialog.is_field_visible("timeout"))
        self.assertFalse(hasattr(dialog, "parallel_batches_input"))

    def test_preset_widgets_are_gone(self):
        # 决定 26：预设功能整个删掉。
        dialog = self.dialog()
        for name in ("preset_combo", "preset_name_input", "dirty_indicator_label",
                     "save_preset_button", "delete_preset_button",
                     "refresh_presets", "save_preset", "auto_load_preset"):
            self.assertFalse(hasattr(dialog, name), name)
        self.assertFalse(dialog.is_field_visible("preset"))

    def test_cancel_dialog_does_not_persist_source_edits(self):
        dialog = self.dialog()
        dialog.source_table.cellWidget(0, 2).setChecked(False)
        dialog.source_table.cellWidget(0, 3).setChecked(False)
        dialog.reject()
        self.assertIn(RULE_ALL, self.window.translation_sources.find("google").rules)

    def test_legacy_settings_are_purged_on_first_run(self):
        self.settings.setValue("provider_settings/microsoft/api_key", "old-secret")
        self.settings.setValue("translation_provider", "microsoft")
        self.settings.setValue("translation_sources_json", "")
        self.settings.sync()
        window = DayzTranslateTool(settings=self.settings)
        self.assertFalse(self.settings.contains("provider_settings/microsoft/api_key"))
        self.assertFalse(self.settings.contains("translation_provider"))
        self.assertTrue(self.settings.value("translation_sources_json", ""))
        window.close()

    def test_source_list_survives_a_restart(self):
        for _ in range(5):
            self.window.translation_sources.move_up("mymemory")
        self.window.save_translation_settings()
        window = DayzTranslateTool(settings=self.settings)
        self.assertEqual(
            [e.source_id for e in window.translation_sources.entries][:2],
            ["google", "mymemory"],
        )
        window.close()
```

- [ ] **Step 6: 跑到失败**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_main_gui 2>&1 | tail -5
```

预期：`ImportError: cannot import name 'AiSourceDialog' from 'main'`

- [ ] **Step 7: 重写 `TranslationSettingsDialog`**

把 `main.py:453` 到 `main.py:915`（`TranslationSettingsDialog` 整个类，从类头到最后一行结束）替换成：

> **范围必须精确到 `main.py:915`。** `main.py:916` 是空行，`main.py:917` 起是另一个类 `class LanguageSettingsDialog(QDialog):`。多删一行就会把它的类头和 `__init__` 前 8 行删掉，剩下的缩进代码直接 `IndentationError`。

```python
class AiSourceDialog(QDialog):
    """「添加 AI 源」弹窗。"""

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle(window.tr("add_ai_source"))
        self.name_input = QLineEdit(self)
        self.type_combo = QComboBox(self)
        for key in AI_TYPE_KEYS:
            self.type_combo.addItem(window.tr(AI_TYPE_LABEL_KEYS[key]), key)
        self.base_url_input = QLineEdit(self)
        self.api_key_input = QLineEdit(self)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit(self)
        self.concurrency_input = QSpinBox(self)
        self.concurrency_input.setRange(1, MAX_AUTO_CONCURRENCY)
        self.interval_input = QDoubleSpinBox(self)
        self.interval_input.setRange(0.0, 60.0)
        self.interval_input.setSingleStep(0.1)

        form = QFormLayout()
        form.addRow(QLabel(window.tr("source_name"), self), self.name_input)
        form.addRow(QLabel(window.tr("source_type"), self), self.type_combo)
        form.addRow(QLabel(window.tr("base_url"), self), self.base_url_input)
        form.addRow(QLabel(window.tr("api_key"), self), self.api_key_input)
        form.addRow(QLabel(window.tr("model"), self), self.model_input)
        form.addRow(QLabel(window.tr("source_concurrency"), self), self.concurrency_input)
        form.addRow(QLabel(window.tr("source_interval"), self), self.interval_input)

        save_button = QPushButton(window.tr("save"), self)
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton(window.tr("cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.resize(440, 300)

    def values(self):
        return {
            "name": self.name_input.text().strip(),
            "api_type": self.type_combo.currentData(),
            "base_url": self.base_url_input.text().strip(),
            "api_key": self.api_key_input.text().strip(),
            "model": self.model_input.text().strip(),
            "concurrency": self.concurrency_input.value(),
            "interval": self.interval_input.value(),
        }


class TranslationSettingsDialog(QDialog):
    ai_dialog_class = AiSourceDialog

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.form_rows = {}
        self.source_form_rows = {}
        self._refreshing_table = False
        self._loaded_source_id = None
        self.setWindowTitle(window.tr("translation_settings").rstrip("."))
        # 对话框编辑的是副本；点「保存」才写回 window（取消不留痕）
        self.sources = window.translation_sources.clone()

        self.source_table = QTableWidget(0, len(SOURCE_TABLE_HEADERS), self)
        self.source_table.setHorizontalHeaderLabels([
            window.tr("source_name"), "", window.tr("source_rules_all"),
            window.tr("source_rules_empty"), window.tr("source_rules_selection"),
        ])
        self.source_table.verticalHeader().setVisible(False)
        self.source_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.source_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.source_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.source_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.source_table.itemSelectionChanged.connect(self._on_source_selection_changed)
        self.source_table.setMinimumHeight(200)

        self.move_up_button = QPushButton(window.tr("source_move_up"), self)
        self.move_up_button.clicked.connect(lambda: self.move_source(-1))
        self.move_down_button = QPushButton(window.tr("source_move_down"), self)
        self.move_down_button.clicked.connect(lambda: self.move_source(1))
        self.add_ai_source_button = QPushButton("+", self)
        self.add_ai_source_button.setToolTip(window.tr("add_ai_source"))
        self.add_ai_source_button.clicked.connect(self.add_ai_source)
        self.remove_source_button = QPushButton(window.tr("source_remove"), self)
        self.remove_source_button.clicked.connect(self.remove_source)

        self.source_name_label = QLabel("", self)
        self.source_builtin_label = QLabel("", self)
        self.source_builtin_label.setStyleSheet("color: #808080; font-size: 11px;")
        self.source_type_input = QComboBox(self)
        for key in AI_TYPE_KEYS:
            self.source_type_input.addItem(window.tr(AI_TYPE_LABEL_KEYS[key]), key)
        self.source_base_url_input = QLineEdit(self)
        self.source_api_key_input = QLineEdit(self)
        self.source_api_key_input.setEchoMode(QLineEdit.Password)
        self.source_model_input = QLineEdit(self)
        self.source_concurrency_input = QSpinBox(self)
        self.source_concurrency_input.setRange(1, MAX_AUTO_CONCURRENCY)
        self.source_interval_input = QDoubleSpinBox(self)
        self.source_interval_input.setRange(0.0, 60.0)
        self.source_interval_input.setSingleStep(0.1)

        source_form = QFormLayout()
        self._add_source_row(source_form, "source_name", window.tr("source_name"), self.source_name_label)
        self._add_source_row(source_form, "source_builtin", window.tr("source_builtin"), self.source_builtin_label)
        self._add_source_row(source_form, "source_type", window.tr("source_type"), self.source_type_input)
        self._add_source_row(source_form, "source_base_url", window.tr("base_url"), self.source_base_url_input)
        self._add_source_row(source_form, "source_api_key", window.tr("api_key"), self.source_api_key_input)
        self._add_source_row(source_form, "source_model", window.tr("model"), self.source_model_input)
        self._add_source_row(source_form, "source_concurrency", window.tr("source_concurrency"), self.source_concurrency_input)
        self._add_source_row(source_form, "source_interval", window.tr("source_interval"), self.source_interval_input)
        for widget in (self.source_type_input, self.source_base_url_input, self.source_api_key_input,
                       self.source_model_input, self.source_concurrency_input, self.source_interval_input):
            widget.editingFinished.connect(self._flush_source_fields)

        self.char_budget_input = QSpinBox(self)
        self.char_budget_input.setRange(MIN_CHAR_BUDGET, MAX_CHAR_BUDGET)
        self.char_budget_input.setSingleStep(100)
        self.char_budget_input.setValue(window.translation_char_budget)

        self.auto_concurrency_check = QCheckBox(window.tr("auto_concurrency"), self)
        self.auto_concurrency_check.setChecked(window.translation_auto_concurrency)

        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(5, 300)
        self.timeout_input.setSingleStep(5)
        self.timeout_input.setValue(int(window.translation_timeout))

        self.clear_cache_button = QPushButton(window.tr("clear_translation_cache"), self)
        self.clear_cache_button.clicked.connect(self.clear_translation_cache)

        form = QFormLayout()
        self.add_form_row(form, "char_budget", window.tr("char_budget"), self.char_budget_input, window.tr("char_budget_tooltip"))
        cap_label = QLabel(window.tr("concurrency_cap"), self)
        cap_label.setToolTip(window.tr("concurrency_cap_tooltip"))
        cap_layout = QHBoxLayout()
        cap_layout.setContentsMargins(0, 0, 0, 0)
        cap_layout.addWidget(self.auto_concurrency_check)
        cap_layout.addStretch(1)
        form.addRow(cap_label, cap_layout)
        self.form_rows["auto_concurrency"] = (cap_label, self._layout_widgets(cap_layout))
        self.add_form_row(form, "timeout", window.tr("timeout"), self.timeout_input)
        self.add_form_row(form, "clear_cache", window.tr("translation_cache"), self.clear_cache_button)

        source_box = QGroupBox(window.tr("translation_sources"), self)
        source_box_layout = QVBoxLayout(source_box)
        table_row = QHBoxLayout()
        table_row.addWidget(self.source_table, 1)
        button_column = QVBoxLayout()
        button_column.addWidget(self.move_up_button)
        button_column.addWidget(self.move_down_button)
        button_column.addWidget(self.add_ai_source_button)
        button_column.addWidget(self.remove_source_button)
        button_column.addStretch(1)
        table_row.addLayout(button_column)
        source_box_layout.addLayout(table_row)
        source_box_layout.addLayout(source_form)

        save_button = QPushButton(window.tr("save"), self)
        save_button.clicked.connect(self.apply_settings)
        self.test_button = QPushButton(window.tr("test_translation"), self)
        self.test_button.clicked.connect(self.run_translation_test)
        cancel_button = QPushButton(window.tr("cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.test_button)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(source_box)
        layout.addLayout(buttons)

        self.refresh_source_table(select_id=self.sources.entries[0].source_id if self.sources.entries else None)
        self.resize(760, 620)
```

> 预设功能已删（决定 26），所以这里**没有** `refresh_presets()` 与 `currentTextChanged` 接线。

**新增/改写这些方法：**

```python
    def _add_source_row(self, form, key, label_text, widget):
        label = QLabel(label_text, self)
        form.addRow(label, widget)
        self.source_form_rows[key] = (label, widget)

    def _layout_widgets(self, layout):
        widgets = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget:
                widgets.append(widget)
        return widgets

    def add_form_row(self, form, key, label_text, widget, tooltip=None):
        label = QLabel(label_text, self)
        if tooltip:
            label.setToolTip(tooltip)
            widget.setToolTip(tooltip)
        form.addRow(label, widget)
        self.form_rows[key] = (label, widget)

    # —— 源列表 ——

    def source_label(self, entry):
        return self.window.source_label(entry)

    def current_source_id(self):
        row = self.source_table.currentRow()
        if row < 0 or row >= len(self.sources.entries):
            return None
        return self.sources.entries[row].source_id

    def current_source_entry(self):
        source_id = self.current_source_id()
        return self.sources.find(source_id) if source_id else None

    def refresh_source_table(self, select_id=None):
        if select_id is None:
            select_id = self.current_source_id()
        self._refreshing_table = True
        try:
            self.source_table.setRowCount(len(self.sources.entries))
            for row, entry in enumerate(self.sources.entries):
                name_item = QTableWidgetItem(self.source_label(entry))
                name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.source_table.setItem(row, 0, name_item)
                kind_item = QTableWidgetItem(
                    self.window.tr("source_kind_ai") if entry.is_ai else self.window.tr("source_kind_free")
                )
                kind_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.source_table.setItem(row, 1, kind_item)
                for offset, rule in enumerate(ALL_RULES, start=2):
                    box = QCheckBox(self.source_table)
                    box.setChecked(rule in entry.rules)
                    box.stateChanged.connect(
                        lambda state, sid=entry.source_id, r=rule: self.set_source_rule(sid, r, state == Qt.Checked)
                    )
                    self.source_table.setCellWidget(row, offset, box)
        finally:
            self._refreshing_table = False
        index = self.sources.index_of(select_id) if select_id else -1
        if index < 0 and self.sources.entries:
            index = 0
        if index >= 0:
            self.source_table.selectRow(index)
        self.update_visible_fields()

    def set_source_rule(self, source_id, rule, enabled):
        if self._refreshing_table:
            return
        self.sources.set_rule(source_id, rule, enabled)

    def move_source(self, delta):
        source_id = self.current_source_id()
        if not source_id:
            return
        self._flush_source_fields()
        if delta < 0:
            self.sources.move_up(source_id)
        else:
            self.sources.move_down(source_id)
        self.refresh_source_table(select_id=source_id)

    def remove_source(self):
        entry = self.current_source_entry()
        if entry is None or not entry.is_ai:
            return                      # 内置源不给删，只能取消勾选
        answer = QMessageBox.question(
            self, self.window.tr("source_remove"),
            self.window.tr("source_remove_confirm", name=self.source_label(entry)),
        )
        if answer != QMessageBox.Yes:
            return
        self.sources.remove(entry.source_id)
        self.refresh_source_table()

    def add_ai_source(self):
        dialog = self.ai_dialog_class(self.window, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values.get("name"):
            QMessageBox.warning(self, self.window.tr("add_ai_source"), self.window.tr("source_name_required"))
            return
        if self.sources.has_name(values["name"]):
            answer = QMessageBox.question(
                self, self.window.tr("add_ai_source"),
                self.window.tr("source_name_duplicate", name=values["name"]),
            )
            if answer != QMessageBox.Yes:
                return
        # 新加的 AI 源默认只勾「右键选中」。勾上「翻译全表」= 授权一次可能产生
        # 费用的批量调用，必须由用户自己动手勾（决定 6 / 23）。
        entry = SourceEntry(
            kind="ai",
            name=values["name"],
            api_type=values.get("api_type") or "openai",
            rules=[RULE_SELECTION],
            api_key=values.get("api_key", ""),
            base_url=values.get("base_url", ""),
            model=values.get("model", ""),
            concurrency=int(values.get("concurrency") or 1),
            interval=float(values.get("interval") or 0.0),
        )
        self.sources.add_ai(entry)
        self.refresh_source_table(select_id=entry.source_id)

    # —— 每个源的设置 ——

    def _on_source_selection_changed(self):
        if self._refreshing_table:
            return                      # 刷新表格时的选中变化不算「用户换了源」
        self._flush_source_fields()
        self.update_visible_fields()

    def _flush_source_fields(self):
        """把控件里的值写回**当前加载的那个源**。

        必须按 `_loaded_source_id` 定位目标，不能用 `current_source_entry()`：
        刷新表格时 `selectRow()` 会先触发本函数，而那一刻 `current_source_entry()`
        已经是新源了 —— 会把上一个源的值（含 API Key）写进新源。
        """
        entry = self.sources.find(getattr(self, "_loaded_source_id", None))
        if entry is None:
            return
        if not entry.is_ai:
            # DeepL 是免费源里唯一要密钥的（`needs_key`），它的密钥也要存
            if FREE_SOURCE_SPECS.get(entry.source_id, {}).get("needs_key"):
                entry.api_key = self.source_api_key_input.text().strip()
            return
        entry.api_type = self.source_type_input.currentData() or "openai"
        entry.base_url = self.source_base_url_input.text().strip()
        entry.api_key = self.source_api_key_input.text().strip()
        entry.model = self.source_model_input.text().strip()
        entry.concurrency = self.source_concurrency_input.value()
        entry.interval = self.source_interval_input.value()

    def update_visible_fields(self):
        entry = self.current_source_entry()
        is_ai = entry is not None and entry.is_ai
        needs_key = is_ai or (
            entry is not None and FREE_SOURCE_SPECS.get(entry.source_id, {}).get("needs_key", False)
        )
        if entry is None:
            self.source_name_label.setText("")
            self.source_builtin_label.setText("")
        else:
            self.source_name_label.setText(self.source_label(entry))
            if not is_ai:
                spec = FREE_SOURCE_SPECS.get(entry.source_id, {})
                self.source_builtin_label.setText(self.window.tr(
                    "source_builtin_text",
                    concurrency=spec.get("concurrency", 1),
                    interval=spec.get("interval", 0.0),
                ))
        if is_ai:
            self.source_type_input.blockSignals(True)
            self.source_base_url_input.blockSignals(True)
            self.source_api_key_input.blockSignals(True)
            self.source_model_input.blockSignals(True)
            self.source_concurrency_input.blockSignals(True)
            self.source_interval_input.blockSignals(True)
            index = self.source_type_input.findData(entry.api_type)
            self.source_type_input.setCurrentIndex(index if index >= 0 else 0)
            self.source_base_url_input.setText(entry.base_url)
            self.source_api_key_input.setText(entry.api_key)
            self.source_model_input.setText(entry.model)
            self.source_concurrency_input.setValue(max(1, int(entry.concurrency or 1)))
            self.source_interval_input.setValue(float(entry.interval or 0.0))
            self.source_type_input.blockSignals(False)
            self.source_base_url_input.blockSignals(False)
            self.source_api_key_input.blockSignals(False)
            self.source_model_input.blockSignals(False)
            self.source_concurrency_input.blockSignals(False)
            self.source_interval_input.blockSignals(False)
        visibility = {
            "source_builtin": entry is not None and not is_ai,
            "source_type": is_ai,
            "source_base_url": is_ai,
            "source_api_key": needs_key,
            "source_model": is_ai,
            "source_concurrency": is_ai,
            "source_interval": is_ai,
        }
        for key, visible in visibility.items():
            label, widget = self.source_form_rows[key]
            label.setVisible(visible)
            widget.setVisible(visible)
        # 记下「现在控件里装的是哪个源」，供 `_flush_source_fields` 定位写入目标
        self._loaded_source_id = entry.source_id if entry is not None else None

    def is_field_visible(self, key):
        rows = self.source_form_rows if key in self.source_form_rows else self.form_rows
        if key not in rows:
            return False                  # 预设行已删（决定 26），"preset" 这种键查不到
        label, widget = rows[key]
        if isinstance(widget, list):
            return not label.isHidden() and all(not item.isHidden() for item in widget)
        return not label.isHidden() and not widget.isHidden()

    # —— 通用字段 ——

    def apply_settings(self, close_dialog=True):
        self._flush_source_fields()
        self.window.translation_sources = self.sources.clone()
        self.window.translation_char_budget = self.char_budget_input.value()
        self.window.translation_auto_concurrency = self.auto_concurrency_check.isChecked()
        self.window.translation_timeout = float(self.timeout_input.value())
        self.window.save_translation_settings()
        if close_dialog:
            self.accept()

    def clear_translation_cache(self):
        self.window.clear_translation_cache()

    def _build_test_config(self):
        """测试按钮只测当前选中的源。"""
        entry = self.current_source_entry()
        if entry is None:
            raise ValueError(self.window.tr("no_source_selected"))
        return self.window.build_source_config(entry, self.char_budget_input.value(), float(self.timeout_input.value()))

    def run_translation_test(self):
        try:
            config = self._build_test_config()
            validate_translator_config(config)
        except ValueError as exc:
            QMessageBox.warning(self, self.window.tr("test_translation"), str(exc))
            return
        self._wait_for_test_thread()
        self.test_button.setEnabled(False)
        self.test_button.setText(self.window.tr("test_translation_running"))
        test_word = "Knife"
        target_languages = ["chinese", "russian", "japanese", "german"]
        jobs = [
            TranslationJob(row=0, column=index, text=test_word, source_code="english", target_code=lang)
            for index, lang in enumerate(target_languages)
        ]
        service = TranslationService()
        self._test_thread = QThread(self)
        self._test_worker = TranslationWorker(service=service, jobs=jobs, configs=[config])
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.failed.connect(self._on_test_failed)
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.failed.connect(self._test_thread.quit)
        self._test_thread.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        self._test_thread.start()
```

`_wait_for_test_thread` / `_on_test_finished` / `_on_test_failed` **原样保留**（只把 `_on_test_finished` 里对 `config` 的引用改掉，如果有的话）。

**预设方法全部删除**（决定 26）：`_read_preset_values` / `_apply_preset_values_to_dialog` / `current_field_values` / `preset_saved_values` / `is_preset_dirty` / `refresh_preset_dirty_indicator` / `refresh_presets` / `auto_load_preset` / `save_preset` / `delete_preset` 十个方法**一个都不留**，`_loading_preset` / `_loaded_preset_values` 两个属性也一起删。`update_visible_fields()` 里对 `self.form_rows["preset"]` 的显隐处理同样删掉。

- [ ] **Step 8: 改 `main.py` 的 `DayzTranslateTool`**

**(a) `__init__`**（`:1339`–`:1348`）：

```python
        self.translation_sources = SourceList.from_json(
            self.settings.value("translation_sources_json", "")
        )
        self.translation_char_budget = int(
            self.settings.value("translation_char_budget", DEFAULT_CHAR_BUDGET)
        )
        self.translation_auto_concurrency = str(
            self.settings.value("translation_auto_concurrency", "true")
        ).lower() in ("true", "1", "yes")
        self.translation_timeout = float(self.settings.value("translation_timeout", 60.0))
        self._translation_rule = RULE_SELECTION
        self._migrate_translation_settings()
```

**删掉** `self.translation_provider = ...`、`self.translation_parallel_batches = ...`、`self.provider_settings = self._load_provider_settings()`。

**(b) 删掉 `_load_provider_settings` / `_save_provider_settings` / `get_provider_setting` / `set_provider_setting` 与 5 个 `translation_api_key` / `translation_region` / `translation_model` / `translation_base_url` / `translation_email` property**（`:1804`–`:1869`）。

**(c) 新增：**

```python
    def source_label(self, entry):
        if entry.is_ai:
            return entry.name or entry.api_type or "AI"
        return self.tr(FREE_SOURCE_SPECS.get(entry.source_id, {}).get("label_key", entry.source_id))

    def translation_source_summary(self):
        labels = [self.source_label(entry) for entry in self.translation_sources.entries if entry.rules]
        return " → ".join(labels) if labels else self.tr("no_source_selected")

    def build_source_config(self, entry, char_budget=None, timeout=None):
        """把一个源条目变成 TranslatorConfig。免费源的并发/间隔内置，AI 源用自己存的。"""
        if entry.is_ai:
            return TranslatorConfig(
                provider=entry.api_type or "openai",
                label=self.source_label(entry),
                char_budget=char_budget if char_budget is not None else self.translation_char_budget,
                parallel_batches=max(1, int(entry.concurrency or 1)),
                min_interval=max(0.0, float(entry.interval or 0.0)),
                auto_concurrency=self.translation_auto_concurrency,
                timeout=timeout if timeout is not None else self.translation_timeout,
                api_key=entry.api_key,
                model=entry.model,
                base_url=entry.base_url,
                glossary=self.wordbook_glossary(),
                glossary_source_key=(self.source_header or "").strip().lower(),
            )
        spec = FREE_SOURCE_SPECS.get(entry.source_id, {})
        return TranslatorConfig(
            provider=entry.source_id,
            label=self.source_label(entry),
            char_budget=char_budget if char_budget is not None else self.translation_char_budget,
            parallel_batches=max(1, int(spec.get("concurrency", 1))),
            min_interval=max(0.0, float(spec.get("interval", 0.0))),
            auto_concurrency=self.translation_auto_concurrency,
            timeout=timeout if timeout is not None else self.translation_timeout,
            api_key=entry.api_key,
        )

    def build_translation_configs(self, rule):
        return [
            self.build_source_config(entry)
            for entry in self.translation_sources.candidates(rule)
        ]

    def _migrate_translation_settings(self):
        """首次运行：清掉旧的 provider_settings 密钥，写入新的源列表。"""
        if str(self.settings.value("translation_sources_json", "") or "").strip():
            return
        self.settings.remove("provider_settings")
        self.settings.remove("translation_provider")
        self.settings.remove("translation_parallel_batches")     # 决定 24：这个设置项整个删掉
        self.settings.remove("translation_presets")              # 决定 26：预设整个删掉（连同里面的密钥）
        self.settings.remove("translation_preset_names_list")
        self.settings.setValue("translation_sources_json", self.translation_sources.to_json())
        self.settings.sync()
```

**(d) `save_translation_settings`**（`:1872`）：

```python
    def save_translation_settings(self):
        self.settings.setValue("translation_sources_json", self.translation_sources.to_json())
        self.settings.setValue("translation_char_budget", self.translation_char_budget)
        self.settings.setValue("translation_auto_concurrency", self.translation_auto_concurrency)
        self.settings.setValue("translation_timeout", self.translation_timeout)
        self.settings.sync()
        self.statusBar().showMessage(
            self.tr("translation_engine_status", engine=self.translation_source_summary()),
            5000,
        )
```

**(e) `current_translation_settings_dict` / `apply_translation_settings_dict`**（`:1885` / `:1898`）：**两个方法整个删掉**（决定 26）。它们只服务预设；主窗口没有别的地方调它们。

**(f) `translation_preset_names` / `save_translation_preset` / `load_translation_preset` / `delete_translation_preset`**（`:1935` / `:1941` / `:1955` / `:1965`）：**四个方法整个删掉**（决定 26）。

- [ ] **Step 9: 写会失败的测试**

追加到 `tests/test_main_gui.py` 的 `TranslationSourceListDialogTests` 之后：

```python
class TranslationRuleWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
        self.temp.close()
        self.settings = QSettings(self.temp.name, QSettings.IniFormat)
        self.window = DayzTranslateTool(settings=self.settings)
        # `_ensure_dayz_table` 是 MainGuiTests 自己的方法，主窗口没有 —— 这里内联同一段建表逻辑
        self.window.headers = list(DAYZ_HEADERS)
        sample = [
            ["STR_A", "OrigA", "EngA"] + [""] * (len(DAYZ_HEADERS) - 3),
            ["STR_B", "OrigB", "EngB"] + [""] * (len(DAYZ_HEADERS) - 3),
        ]
        self.window.apply_table_rows(sample, dirty=False)
        if self.window.current_path is None:
            self.window.current_path = Path("stringtable.csv")
            self.window.update_current_file_label()

    def tearDown(self):
        self.window.close()
        os.unlink(self.temp.name)

    def fake_worker(self, box):
        """装一个假 worker 并把收到的 configs 存进 box。

        `start_translation_worker` 会调 `moveToThread` / `run` / `deleteLater` /
        `cancel`，所以桩必须把这四个都实现掉 —— 返回普通 `object()` 会
        `AttributeError`。
        """

        class FakeSignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

        class FakeWorker:
            def __init__(self):
                self.progress = FakeSignal()
                self.retrying = FakeSignal()
                self.fallback = FakeSignal()
                self.finished = FakeSignal()
                self.failed = FakeSignal()
                self.cancelled = False

            def moveToThread(self, thread):
                self.thread = thread

            def run(self):
                pass

            def deleteLater(self):
                pass

            def cancel(self):
                self.cancelled = True

        worker = FakeWorker()

        def factory(jobs, configs):
            box["configs"] = configs
            return worker

        self.window.create_translation_worker = factory
        return worker

    def test_all_cells_uses_only_sources_enabled_for_all(self):
        seen = {}
        self.fake_worker(seen)
        self.window.translate_all_cells()
        self.assertEqual([c.provider for c in seen["configs"]], ["google", "microsoft", "tencent"])

    def test_selection_rule_includes_single_item_sources(self):
        seen = {}
        self.fake_worker(seen)
        self.window.table.selectRow(0)
        self.window.translate_selected_rows()
        self.assertIn("mymemory", [c.provider for c in seen["configs"]])

    def test_empty_rule_uses_only_sources_enabled_for_empty(self):
        seen = {}
        self.fake_worker(seen)
        self.window.translate_empty_cells()
        self.assertEqual([c.provider for c in seen["configs"]], ["google", "microsoft", "tencent"])

    def test_missing_rule_reports_an_error_instead_of_silently_using_other_sources(self):
        self.window.translation_sources.set_rule("google", RULE_ALL, False)
        self.window.translation_sources.set_rule("microsoft", RULE_ALL, False)
        self.window.translation_sources.set_rule("tencent", RULE_ALL, False)
        with unittest.mock.patch("main.QMessageBox.warning") as warned:
            self.window.translate_all_cells()
        self.assertTrue(warned.called)

    def test_free_source_concurrency_and_interval_come_from_the_spec(self):
        configs = self.window.build_translation_configs(RULE_ALL)
        by_provider = {c.provider: c for c in configs}
        self.assertEqual(by_provider["microsoft"].parallel_batches, 2)
        self.assertEqual(by_provider["microsoft"].min_interval, 0.1)
        self.assertEqual(by_provider["tencent"].min_interval, 0.3)

    def test_ai_source_config_uses_its_own_concurrency_and_interval(self):
        entry = SourceEntry(kind="ai", name="我的 GPT", api_type="openai", rules=[RULE_SELECTION],
                            api_key="sk-x", model="gpt-4o-mini", concurrency=5, interval=0.7)
        self.window.translation_sources.add_ai(entry, source_id="ai:x")
        configs = self.window.build_translation_configs(RULE_SELECTION)
        ai = [c for c in configs if c.provider == "openai"][0]
        self.assertEqual(ai.parallel_batches, 5)
        self.assertEqual(ai.min_interval, 0.7)
        self.assertEqual(ai.label, "我的 GPT")

    def test_ai_source_config_carries_the_glossary(self):
        self.window.open_wordbook_window()
        self.window.wordbook_window.set_cell_text(0, 1, "Knife")     # 列 1 = english，不是列 0（列 0 是 original）
        self.window.wordbook_window.set_cell_text(0, 3, "Messer")
        entry = SourceEntry(kind="ai", name="我的 GPT", api_type="openai", rules=[RULE_SELECTION], api_key="sk-x")
        self.window.translation_sources.add_ai(entry, source_id="ai:g")
        configs = self.window.build_translation_configs(RULE_SELECTION)
        ai = [c for c in configs if c.provider == "openai"][0]
        self.assertEqual(ai.glossary, [{"english": "Knife", "german": "Messer"}])

    def test_free_source_config_has_no_glossary(self):
        configs = self.window.build_translation_configs(RULE_ALL)
        for config in configs:
            self.assertEqual(config.glossary, [])

    def test_fallback_signal_writes_the_status_bar(self):
        worker = self.fake_worker({})
        self.window.table.selectRow(0)
        self.window.translate_selected_rows()
        worker.fallback.callbacks[0]("微软翻译", "Google")
        self.assertIn("微软翻译", self.window.statusBar().currentMessage())
        self.assertIn("Google", self.window.statusBar().currentMessage())

    def test_worker_gets_a_config_list_not_a_single_config(self):
        seen = {}
        self.fake_worker(seen)
        self.window.table.selectRow(0)
        self.window.translate_selected_rows()
        self.assertIsInstance(seen["configs"], list)
        self.assertTrue(seen["configs"])

    def test_retry_failed_cells_reuses_the_last_rule(self):
        self.window._translation_failed_cells = {(0, 1)}
        self.window._translation_rule = RULE_SELECTION
        seen = {}
        self.fake_worker(seen)
        self.window.retry_failed_cells()
        self.assertIn("mymemory", [c.provider for c in seen["configs"]])
```

- [ ] **Step 10: 跑到失败**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_main_gui.TranslationRuleWiringTests 2>&1 | tail -5
```

预期：`TypeError: <lambda>() missing 1 required positional argument: 'configs'`

- [ ] **Step 11: 改 `main.py` 的翻译入口**

**(a) 5 个入口加规则**（`translate_selected_cells` `:2263`、`translate_selected_rows` `:2295`、`translate_selected_columns` `:2309`、`translate_all_cells` `:2323`、`translate_empty_cells` `:2345`）：

```python
        self.run_translation_jobs(jobs, rule=RULE_SELECTION)     # 三个 selected_* 用这条
        self.run_translation_jobs(jobs, rule=RULE_ALL)           # translate_all_cells
        self.run_translation_jobs(jobs, copy_overwrite=False, rule=RULE_EMPTY)   # translate_empty_cells
```

**(b) `run_translation_jobs` / `start_translation_worker`**（`:2433` / `:2442`）：

```python
    def run_translation_jobs(self, jobs, copy_overwrite=True, rule=RULE_SELECTION):
        jobs = self._sort_jobs_by_row_column(jobs)
        self.start_translation_worker(jobs, copy_overwrite=copy_overwrite, rule=rule)

    def start_translation_worker(self, raw_jobs, run_immediately=False, copy_overwrite=True, rule=RULE_SELECTION):
        jobs = [
            TranslationJob(row, column, text, source_language_code_for_header(self.source_header), target)
            for row, column, text, target in raw_jobs
        ]
        self._translation_job_rows = {row for row, column, text, target in raw_jobs}
        self._translation_job_cells = {(row, column) for row, column, text, target in raw_jobs}
        self._translation_copy_overwrite = copy_overwrite
        if not jobs:
            QMessageBox.information(self, self.tr("translate"), self.tr("no_translatable_cells"))
            return

        if self._is_translation_running():
            QMessageBox.warning(self, self.tr("translate"), self.tr("translation_in_progress"))
            return

        configs = self.build_translation_configs(rule)
        if not configs:
            QMessageBox.warning(
                self,
                self.tr("translate"),
                self.tr("no_source_for_action", action=self.tr(f"action_{'all_cells' if rule == RULE_ALL else 'empty_cells' if rule == RULE_EMPTY else 'selection'}")),
            )
            return

        self._translation_rule = rule
        self.show_translation_progress(len(jobs))

        self.translation_worker = self.create_translation_worker(jobs, configs)
        self.translation_worker.progress.connect(self.update_translation_progress)
        self.translation_worker.retrying.connect(self.on_translation_retrying)
        self.translation_worker.fallback.connect(self.on_translation_fallback)
        self.translation_worker.finished.connect(self.finish_translation)
        self.translation_worker.failed.connect(self.fail_translation)
        # ...（下面 run_immediately / QThread 部分原样保留）
```

**(c) `create_translation_worker`**（`:2507`）：

```python
    def create_translation_worker(self, jobs, configs):
        # 注入共享缓存：多次翻译运行复用相同内容的翻译结果
        return TranslationWorker(
            service=TranslationService(cache=self.translation_cache),
            jobs=jobs,
            configs=configs,
        )
```

**(d) 新增降级状态栏回调**（放在 `on_translation_retrying` 旁边）：

```python
    def on_translation_fallback(self, previous_label, next_label):
        """主备降级：状态栏显示一行小字（决定 20）。"""
        self.statusBar().showMessage(
            self.tr("translation_fallback", previous=previous_label, current=next_label),
            8000,
        )
```

**(e) `retry_failed_cells`**（`:2636`）末尾的 `run_translation_jobs` 调用加上 `rule=self._translation_rule`。

- [ ] **Step 12: 跑到通过**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest tests.test_main_gui 2>&1 | tail -5
```

- [ ] **Step 13: commit**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && git add translation_worker.py main.py tests/test_translation_worker.py tests/test_main_gui.py && git commit -m "feat: replace the provider dropdown with a weighted source list, worker fallback and rule wiring"
```


---

### Task 6: 全量验证与文档

**Files:**

- Modify: `docs/superpowers/plans/2026-10-13-free-translation-sources.md`（本节）
- Create: `smoke_free_sources.py`

- [ ] **Step 1: 全量测试**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python -m unittest discover -s tests 2>&1 | tail -5
```

预期：`OK`，且测试数 ≥ 284。

- [ ] **Step 2: 真机冒烟（真实网络，六个免费源各翻一条）**

新建 `smoke_free_sources.py`：

```python
"""真机冒烟：六个免费源各翻一条，看真实响应。不发到仓库外的任何地方。"""

import json
import time

from free_translators import FREE_TRANSLATOR_CLASSES

SAMPLES = {
    "google": ["Knife", "Gun", "Bandage"],
    "microsoft": ["Knife", "Gun", "Bandage"],
    "tencent": ["Knife", "Gun", "Bandage"],
    "volcano": ["Knife"],
    "lara": ["Knife"],
    "mymemory": ["Knife"],
}

for source_id, texts in SAMPLES.items():
    cls = FREE_TRANSLATOR_CLASSES[source_id]
    translator = cls(source="en", target="zh-CN")
    started = time.time()
    try:
        result = translator.translate_batch(texts)
    except Exception as exc:            # noqa: BLE001 — 冒烟脚本要看到全部失败原因
        print(f"{source_id:10s} FAIL {type(exc).__name__}: {exc}")
        continue
    print(f"{source_id:10s} {time.time() - started:5.2f}s {json.dumps(result, ensure_ascii=False)}")
```

跑：

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && python smoke_free_sources.py
```

预期：六行都有译文。任何一行 FAIL 就把原始错误记进本文件「实施期偏离记录」，**不要**为了让冒烟通过而放宽错误处理。

- [ ] **Step 3: 手动 GUI 冒烟（人工，不写测试）**

1. 打开软件 → 翻译设置 → 确认列表里是 Google / 微软 / 腾讯 / 火山 / Lara / MyMemory / DeepL，前三个三个勾都亮，中间三个只亮「右键选中」，DeepL 一个都不亮。
2. 点「+」加一个 AI 源（随便填个名字和地址），确认弹窗字段齐全、密钥框是圆点。
3. 选一个免费源 → 确认「内置限制」显示灰字「并发 2，间隔 0.3 秒（内置，不可修改）」，且并发/间隔输入框**不显示**。
4. 选 AI 源 → 确认并发/间隔输入框出现且可改。
5. 上移/下移 → 顺序变化；保存 → 关软件 → 重开 → 顺序还在。
6. 把「全表」的勾全部取消 → 点「翻译全表」→ 确认弹窗报错，而不是偷偷用别的源。
7. 把微软连不上的情况造出来（比如把 `MicrosoftEdgeTranslator.ENDPOINT` 临时改错）→ 点「翻译全表」→ 确认状态栏出现「微软翻译（免费） 连不上，已自动改用 Google」，且译文仍然出来了。

- [ ] **Step 4: 更新本文件的「实施期偏离记录」**

在 `## 本修订版修掉的问题` 之后新增一节，记录实施过程中与计划不一致的地方（包括上面第 3 步的人为故障注入要还原）。

- [ ] **Step 5: 更新 codegraph 索引**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && codegraph sync
```

- [ ] **Step 6: commit**

```bash
cd D:/MY/_tools/DayZ_Translate_Tool && git add smoke_free_sources.py docs/superpowers/plans/2026-10-13-free-translation-sources.md && git commit -m "docs: record free source smoke results and implementation deviations"
```

---

## 既有测试的同步修改（汇总，必须一起改）

| 文件:行 | 测试 | 处理 | 所属 Task |
| --- | --- | --- | --- |
| `tests/test_main_gui.py:119` | `test_default_translation_provider_is_google` | 重写为 `test_default_source_list_order_and_rules`（Task 5 新增的那条） | Task 5 |
| `tests/test_main_gui.py:123` | `test_provider_settings_are_isolated_between_providers` | **删**，由 `test_ai_settings_are_saved_per_source` 取代 | Task 5 |
| `tests/test_main_gui.py:140` | `test_dialog_switching_provider_loads_correct_per_provider_settings` | **删**，由 `test_ai_settings_are_saved_per_source` 取代 | Task 5 |
| `tests/test_main_gui.py:156` | `test_dialog_switching_provider_caches_old_provider_fields` | **删**，同上 | Task 5 |
| `tests/test_main_gui.py:244` | `test_run_translation_jobs_starts_worker_instead_of_sync_translate` | `FakeWorker` 加 `fallback = FakeSignal()`；`create_translation_worker` 的 lambda 改成 `lambda jobs, configs: worker`；断言 `on_translation_fallback in worker.fallback.callbacks` | Task 5 |
| `tests/test_main_gui.py:366` | `test_translation_settings_dialog_saves_provider_and_parallel_batches` | **删**，由 `test_toggling_a_checkbox_updates_the_working_copy_only_after_save` + `test_char_budget_and_timeout_still_present` 取代 | Task 5 |
| `tests/test_main_gui.py:382` | `test_translation_settings_batch_and_parallel_have_tooltips` | 重写为 `test_char_budget_and_timeout_still_present` | Task 5 |
| `tests/test_main_gui.py:387` | `test_translation_settings_auto_save_when_fields_change` | 重写为 `test_cancel_dialog_does_not_persist_source_edits` | Task 5 |
| `tests/test_main_gui.py:407` | `test_translation_settings_dialog_shows_fields_for_selected_provider` | 重写为 `test_free_source_shows_read_only_builtin_limits` + `test_ai_source_shows_editable_settings` | Task 5 |
| `tests/test_main_gui.py:431` | `test_translation_settings_presets_only_visible_for_openai` | **删除**（预设行整个没了，决定 26） | Task 5 |
| `tests/test_main_gui.py:440` | `test_legacy_chatgpt_provider_is_shown_as_openai` | **删**（`normalize_provider` 的 `chatgpt → openai` 逻辑保留，但界面不再有单选入口） | Task 5 |
| `tests/test_main_gui.py:867` | `test_translation_worker_receives_open_wordbook_glossary` | 改成断言 `window.build_translation_configs(RULE_SELECTION)` 里 AI 源的 `glossary`（见 `test_ai_source_config_carries_the_glossary`） | Task 5 |
| `tests/test_main_gui.py:954`–`:1162` | preset 系列 11 条（`test_translation_settings_preset_roundtrip`、`test_translation_settings_loads_full_preset`、`test_translation_settings_deletes_preset`、`test_preset_combo_switch_auto_loads_values`、`test_load_translation_preset_overwrites_with_empty_fields`、`test_preset_combo_shows_star_when_field_value_changes`、`test_preset_combo_clears_star_after_saving_preset`、`test_preset_load_button_is_removed`、`test_loading_preset_does_not_modify_provider_settings`、`test_switching_presets_does_not_overwrite_each_other`、`test_cancel_dialog_does_not_persist_edits`） | **全部删除**（决定 26）。其中 `test_cancel_dialog_does_not_persist_edits` 的「取消不落盘」语义由 Task 5 新增的 `test_cancel_dialog_does_not_persist_source_edits` 接管 | Task 5 |
| `tests/test_main_gui.py:1636` | `test_settings_dialog_char_budget_range` | **保留**（`char_budget_input` 仍在） | Task 5 |
| `tests/test_main_gui.py:1642` | `test_settings_dialog_concurrency_cap_range` | 改成 `dialog.source_concurrency_input.maximum() == MAX_AUTO_CONCURRENCY` | Task 5 |
| `tests/test_main_gui.py:1648` | `test_settings_dialog_has_clear_cache_button` | **保留** | Task 5 |
| `tests/test_main_gui.py:1662` | `test_legacy_preset_batch_size_migrates_to_default` | **删除**（决定 26：`apply_translation_settings_dict` 整个方法没了）。旧 `batch_size` 的迁移改由 `_migrate_translation_settings` 处理 —— 见 Task 5 Step 8 | Task 5 |
| `tests/test_main_gui.py:1666` | `test_parallel_batches_default_is_three` | **删**（这个旋钮没了） | Task 5 |
| `tests/test_main_gui.py` 所有 `self.window.translation_provider = ...` 赋值（`:124` `:128` `:133` `:136` `:141` `:145` `:158` `:960` `:970` `:998` `:1029` `:1050` `:1069` `:1095` `:1119` `:1153`） | 旧 provider 字段与预设系列的前置准备 | 预设系列（`:960`–`:1153`）整段删掉；剩下的（`:124`–`:158`）改成往 `self.window.translation_sources` 里加一个 AI 源，或直接删掉这行（免费源不需要 provider 就能跑） | Task 5 |
| `tests/test_translator_service.py:9` | import 行 | 去掉 `GoogleTranslateTranslator` | Task 2 |
| `tests/test_translator_service.py:541`–`:693` | `_google_response` + `GoogleTranslateTranslatorTests` | **整段删**，由 `tests/test_free_translators.py::GoogleWebTranslatorTests` 取代 | Task 2 |
| `tests/test_translator_service.py:694` | `GoogleProviderIntegrationTests` | 改成 POST `translate_a/t`（Task 2 里给了完整代码） | Task 2 |
| `tests/test_translator_service.py:1049` | `service.google_translator_class = FakeGoogle` | 改成 `service.free_translator_classes = {"google": FakeGoogle}`，并把 `FakeGoogle` / `RateLimitedGoogle` 的构造签名改成免费源那套（去掉必填的 `base_url`） | Task 2 |
| `tests/test_translation_worker.py` | 全文 | 用 Task 5 Step 2 给的新版本整份替换 | Task 5 |
| `tests/test_main_gui.py:1385`–`:1387` | `test_translation_worker_uses_shared_cache` | 这条是**直接调用** `self.window.create_translation_worker([])`（只传 1 个参数），不是 lambda 打桩 —— 改成 `create_translation_worker([], self.window.build_translation_configs(RULE_SELECTION))` | Task 5 |
| `tests/test_main_gui.py` 里所有 `create_translation_worker = lambda jobs: ...` | 打桩 | 全部改成 `lambda jobs, configs: ...` | Task 5 |

---

## Self-Review

### Spec coverage

| 决定 | 落在哪 |
| --- | --- |
| 1 加 6 个免费源 | Task 1 |
| 2 Google 改 POST | Task 1 `GoogleWebTranslator` |
| 3 不加 B站/需签名的 | 不做，写进「不做」清单 |
| 4 修好 MyMemory | Task 1 `MyMemoryTranslator` |
| 5 统一源列表 | Task 3 + Task 5 |
| 6 三个勾选框 | Task 3 `ALL_RULES` + Task 5 `source_table` |
| 7 上移/下移 | Task 3 `move_up`/`move_down` + Task 5 按钮 |
| 8 点中显示该源设置 | Task 5 `update_visible_fields` |
| 9 免费源灰色小字只读 | Task 5 `source_builtin_label`（`color: #808080; font-size: 11px;`） |
| 10 AI 源弹窗 | Task 5 `AiSourceDialog` |
| 11 重名提醒 | Task 5 `add_ai_source` |
| 12 微软免费版替换 | Task 2 `create_provider`（`microsoft` 走 `MicrosoftEdgeTranslator`） |
| 13 清掉旧密钥 | Task 5 `_migrate_translation_settings` |
| 14 出厂顺序 | Task 3 `DEFAULT_SOURCE_ORDER` |
| 15 出厂勾选 | Task 3 `DEFAULT_SOURCE_RULES` |
| 16 AI 源出厂为空 | Task 3 `default_entries()` |
| 17 主备降级 | Task 4 `translate_jobs_with_fallback`；worker 侧在 Task 5 |
| 18 先试翻一条 | Task 4 `_probe_source` |
| 19 只补失败的 | Task 4 `remaining` 过滤 |
| 20 状态栏小字 | Task 5 `on_translation_fallback` |
| 21 降级不记住 | Task 4（循环每次都从 `configs[0]` 开始）+ `test_fallback_is_not_remembered` |
| 22 按规则过滤，没有就报错 | Task 5 `start_translation_worker` |
| 23 AI 源参与降级 | Task 4 `test_ai_sources_take_part_in_the_chain` |
| 24 删掉「并行批次数」 | Task 2 `min_interval` + Task 5 删 `parallel_batches_input` + 迁移里 `settings.remove("translation_parallel_batches")` |
| 25 保留 DeepL | Task 3 `DEFAULT_SOURCE_ORDER` 末尾 + `FREE_SOURCE_SPECS["deepl"]` + `SourceEntry.to_dict` / `from_dict` / `_flush_source_fields` 对 `needs_key` 免费源也往返 `api_key` |
| 26 预设删除 | Task 5 Step 7（对话框）+ Step 8（主窗口 + 迁移） |

### 已知取舍（用户已接受或需要知道）

- **免费源用不了术语表和多语言合并。** 这两样是 AI 源专有（AI 源一次请求翻一整行的多语言）。免费源每个语言列要单独发一次请求，DayZ 有 13 个目标语言列。`test_free_source_config_has_no_glossary` 把这条钉住。
- **缓存按源分开存**（缓存键含 provider）。换源重跑同一份文件会重新请求。这是刻意的：不同源的译文质量不同，混在一起会看不出差异。
- **MyMemory 匿名每天只有 5000 字符，且不认 `auto`。** 计划里 `auto` 退回 `en`。依据：DayZ 的 `original` 列内容是从 `english` 列复制来的（`dayz_csv.py:42` `COPY_COLUMN_SOURCES`），所以 `original` 当源列时实际就是英文。**如果用户以后把 `original` 列改成别的语言，MyMemory 会翻错**，写在这里备查。
- **混用多源会让译文风格不统一。** 主备降级下同一份文件通常只有一个源在干活；只有中途挂掉才会混。这是降级换可用性的必然代价。
- **免费源的并发/间隔由程序内置**（微软/Google/腾讯 并发 2，火山/Lara/MyMemory 并发 1）。用户不能改 —— 这些数字是从 FluentRead 的实测调度参数来的，改小了慢、改大了容易被封。
- **单条源在批量模式下会发 N 次请求**（火山/Lara/MyMemory 一次只能一条）。这就是出厂默认只勾「右键选中」的原因。
- **长文本按行切块**（火山/Lara 1000 码点、MyMemory 500 UTF-8 字节）。块与块之间**逐块独立翻译**，跨块的上下文会丢；块本身拼接后等于原文（含换行），但译文在块边界处可能读起来断。
- **DeepL 保留但不勾选**（决定 25，本计划新增，用户可否决）。理由：它是唯一需要密钥的内置源，且接口不属于三种 AI 协议；直接删掉是丢功能，保留在列表末尾且默认不勾是零风险。**用户说「不要了」就删掉 `DEFAULT_SOURCE_ORDER` 里的 `deepl` 与 `FREE_SOURCE_SPECS["deepl"]` 两处。**
- **预设整个删掉**（决定 26，用户 m01748 定）。`translation_presets/*` 与 `translation_preset_names_list` 在首次运行时被 `_migrate_translation_settings` 清掉（里面存着旧密钥，一并销毁）。代价：用户不能再存「一套配置」，每次打开设置就是当前那一套。
- **`_translation_rule` 不持久化。** 「只重跑失败项」沿用本次会话里上一次的规则；重开软件后回到默认的 `右键选中`。
- **测试按钮只测当前选中的源**（不再测「当前 provider」）。这是新 UI 下唯一合理的解释。
- **`FreeHttpTranslator.translate_batch` 的块间拼接用空串**。因为 `split_text` 已经把换行留在块内，拼接后与原文一致；跨块译文之间不再补空格。
