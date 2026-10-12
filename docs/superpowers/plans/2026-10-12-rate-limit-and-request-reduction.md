# 限速处理与请求削减 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让翻译在被限速时自动等待重试而不是丢数据，并把请求数与输入 token 降到合理水平。

**Architecture:** 在 `TranslationService` 与各 translator 之间插入一层薄的标准库能力：可中断的退避重试（`RetryPolicy`）、全局最小间隔节流（`RateLimiter`）、自适应并发闸门（`AdaptiveGate`）。分批从「按行数」改为「按行累积、按字数预算封批」，并把同一行的多目标语言合并成一次请求（源文只出现一次），返回格式从位置数组改为带编号对象以便只补发缺失项。翻译缓存从内存字典升级为软件目录旁的 JSON 文件。UI 只在「翻译设置」对话框内原地替换两个旋钮并新增一个清空缓存按钮，翻译入口与主界面不动。

**Tech Stack:** Python 3.13, 标准库（`threading` / `json` / `time` / `urllib` / `email.utils` / `os`）, PySide6, unittest（现有 `tests/` 用 `unittest.TestCase`）。

## 参考实现（已核实源码，非印象）

| 采用的做法 | 出处 |
|---|---|
| 按 token 预算累积封批；超长条目单独成批 | bilingual_book_maker `book_maker/loader/epub_loader.py:3143-3160` |
| 退避上限 300s，只对「永远好不了」的错误放弃 | bilingual_book_maker `book_maker/loader/helper.py:27,77,482-500` |
| 每次重试打一行日志，理由：「长时间沉默看起来就和卡死一样」 | 同上 `_say_retrying` |
| 429 重试、退避有上限、每次打日志 | pdf2zh `pdf2zh/translator.py:465-473` |
| 退避 `min(0.5·2ⁿ, 8)` + 抖动 `×(1−0.25·random())`；读 `Retry-After`/`retry-after-ms`；重试 408/409/429/5xx | openai 2.45.0 `_base_client.py:771-826`（本机已装） |
| 可重试状态码含 413 | urllib3 `util/retry.py` `RETRY_AFTER_STATUS_CODES` |
| Anthropic 提示词缓存需显式 `cache_control: ephemeral` | anthropic 0.116.0（本机已装） |
| 反面教材：429 只抛错不重试；`batch_translate` 是 N 条 = N 次请求 | deep-translator `google.py` / `base.py` |

**不采用**：`tenacity` / `backoff` / `aiolimiter` / `asyncio` / `tiktoken` / `httpx`。全部标准库手写；token 预算用字符数近似。

## 本修订版修掉的问题（相对上一版）

上一版经两轮独立审查 + 逐条复核后确认**不可直接实施**，本版已修：

| # | 上一版的问题 | 本版的处理 |
|---|---|---|
| 1 | **P0** 缺失补发时重新编号 id，导致补发的第 1 行覆盖原第 1 行的译文，静默写错单元格并污染磁盘缓存 | `assign_batch_ids()` 只调用一次；补发直接复用同一映射的子集（Task 5） |
| 2 | **P1** 429 被 `_translate_one_openai_batch` 的 `except Exception` 吞掉，永远到不了闸门 → 降速功能是死的 | 该处改为记失败后 `raise TranslationRequestError`；调用方吞掉异常但闸门已收到信号（Task 3） |
| 3 | **P1** `retry_call` 在 `_post_json` 内、限速器在批次外 → 5 次重试不过节流，撞限速后反而连发 | 节流移到 `retry_call` 的 `before_attempt`，每次尝试（含重试）都过一次（Task 2/3） |
| 4 | **P1** `self.retry_policy` 从未定义 → 每次请求 `AttributeError` 被吞成「批次失败」 | `TranslationService.__init__` 定义；provider 构造参数带默认值，Task 2 自洽（Task 2/3） |
| 5 | **P1** `main.py` 未 import 新常量 → `NameError` | Task 7 Step 1 明确列出 import 行 |
| 6 | **P2** `iter_row_batches` 里 `max(MIN_CHAR_BUDGET, char_budget)` 与 `max(budget, cap)` 钳制，使两个测试在自己的实现下不可能通过 | 去掉两处钳制，只做 `max(1, ...)` 防零（Task 4） |
| 7 | **P2** `parse_numbered_translations` 被缩进成嵌套函数且在 `return` 之后 → 死代码 | 提升为模块级函数（Task 5） |
| 8 | **P2** `_assign_batch_ids` / `_missing_jobs` / `_store_parsed_results` 只有散文、无实现 | 改为给出完整实现（Task 5） |
| 9 | **P2** `self.stats = None` 死代码（决定 13 明确不做统计面板） | 删除 |
| 10 | **P2** `AdaptiveGate` 的 `maximum` 三处不一致（`5` / `8` / 「默认 5」） | 统一为常量；上限 = 用户设的并发数（默认 3） |
| 11 | **P2b** 计划声称「既有测试全绿」，实际 8 处会挂 | 新增专节逐条列出改法 |
| 12 | **P3** Task 2 在文件顶部插约 130 行导致后续行号全部失效 | 改为按符号名定位；行号仅作参考 |
| 13 | **P3** Task 2 用了 Task 3 才定义的 `self.on_retry` → 单独提交即 `AttributeError` | provider 构造参数带默认值；`TranslationService` 的字段在 Task 2 就补上 |
| 14 | **设计错误** 术语表硬编码匹配 `original` 列，而 `original` 的语言码是 `auto`，真实单词本常只有 `english`/`german` 列 → 术语表永远落空 | 改为匹配**本批源语言对应的列**（`self.source_header`，与 `WORDBOOK_HEADERS` 同名，无需映射表）（Task 6） |
| 15 | **D** 「既有测试里断言 `RuntimeError` 的用例需改成 `TranslationRequestError`」是错的 | 那 3 处都不经过 `_post_json`，一处都不用改 |
| 16 | **D** `add_form_row` 无 tooltip 守卫、`main.py:2402`/`1780` 行号错 | 已更正 |
| 17 | **P1** `GoogleTranslateTranslator` 根本没有 `_post_json`（它用可注入的 `request_func`，构造器也没有 `api_key`/`model`/`glossary`）→ 上一版给 Google 写的重试代码全部落空，Google 线路没有重试 | 拆成两组分别处理，重试包在 `request_func` 外层；`_default_request` 的 `RuntimeError` 换成 `TranslationRequestError`（Task 2 Step 4） |
| 18 | **P1** Google 的 429 会被 `_translate_one_row_batch` 的 `except Exception` 吞掉，与问题 2 同源 → Google 线路的自适应降速也是死的 | 该处同样改为「记失败后 `raise`」（Task 3 Step 4） |
| 19 | **P1** 决定 22 把 `translation_parallel_batches` 默认值从 1 改成 3，会让既有测试 `test_default_translation_provider_is_google`（`test_main_gui.py:121`）直接挂，而上一版未列入同步修改表 | 已列入同步表 |
| 20 | **P2** 上一版给 `main.py` 写了「旧值 < `MIN_CHAR_BUDGET` 就迁移成默认值」的钳制，与 `test_translation_settings_loads_full_preset`（存 12 断言 12）直接矛盾 | 去掉读取端钳制，`MIN_CHAR_BUDGET` 改作 UI 下限；迁移只认旧键 `batch_size` |
| 21 | **P2** 上一版只列了「同步四处」，漏了对话框侧的 `_read_preset_values` / `_apply_preset_values_to_dialog` / `current_field_values` 三处 —— 只改一半会出现「对话框存 `char_budget`、主窗口读 `batch_size`」的静默不生效 | 改为列出完整八处，并给出统一的旧值迁移规则（Task 7 Step 5） |
| 22 | **P2** Task 3 的 `AdaptiveGate.acquire` 在拿到名额后多查了一次 `should_cancel()`，使 `test_cancel_stops_before_processing_later_groups`（靠调用次数计数的脆弱断言）从「译了 1 批」变成「一批都没译」而挂 —— 与同步修改表「该测试不用改」矛盾 | 删掉那次多余的检查：调用方在提交每个批次前已经查过，闸门只需在「真的被挡住」时响应取消。既有测试因此不用改 |
| 23 | **P2** Task 3 的闸门代码读 `config.auto_concurrency`，而该字段是 Task 4 才加进 `TranslatorConfig` 的 —— 单独实施 Task 3 会 `AttributeError` | `auto_concurrency: bool = True` 提前到 Task 3 加；Task 4 只补 `char_budget` 与 `glossary_source_key` |

**行号基准**：本文所有行号是修订当日（2026-10-12）的现状。Task 2 起会在 `translator_service.py` 顶部插入约 130 行，此后行号会漂移 —— **实现时请按符号名定位，行号仅作快速跳转参考**。

## 实施期偏离记录

计划实施过程中发现的、与原计划不一致的地方。每条都记「发现于哪个 Task」+「实际怎么做的」+「为什么」。

| # | 发现于 | 原计划 | 实际做法与原因 |
|---|---|---|---|
| I1 | Task 3 | Task 3 只需给 `TranslatorConfig` 加 `auto_concurrency` | 同时把 `RateLimiter` / `AdaptiveGate` 的类定义、`_throttle` / `_guarded` 辅助方法与 `_run_guarded_batch` 一并落地；`_translate_batches` 的 `except TranslationRequestError` 分支保留 `raise`（问题 18）。既有测试 `test_cancel_stops_before_processing_later_groups` 未改，符合问题 22 的结论 |
| I2 | Task 4 | Task 4 只改 `main.py` 的 `create_translation_worker` / `run_translation_test` 两处 | 实际把「`batch_size` → `char_budget`」的**全部八处重命名**（含设置持久化、预设两条链路、旧值迁移）都放进 Task 4。原因：Task 4 的 `create_translation_worker` 片段引用 `self.translation_char_budget`，若只改那两处会直接 `AttributeError`；Task 7 只保留「对话框勾选框 + 重试信号 + 倒计时 + 只重跑失败项 + 清空缓存」 |
| I3 | Task 4 | `test_translation_settings_dialog_saves_provider_and_parallel_batches` 把 `setValue(40)` 后的断言改成 `== 40` | 改为 `setValue(2400)` 断言 `== 2400`。原因：对话框走 `QSpinBox`，下限是 `MIN_CHAR_BUDGET=200`，`setValue(40)` 会被控件夹成 200，原计划写的 `== 40` 在自己的实现下不可能通过（与问题 20 同源，但方向相反）。主窗口链路的 `test_translation_settings_loads_full_preset` 存 12 断言 12 不受影响（该路径不夹） |
| I4 | Task 4 | `TranslationService.__init__` 去掉 `batch_size` 后，既有测试只需机械删除该参数 | 机械 `sed` 后仍有 6 个测试挂：它们靠 `batch_size` 制造「多批」场景，删掉参数后默认 `char_budget=1500` 让所有短文本并成一批。逐个补上合适的 `char_budget`（`test_batches_by_language_direction_and_dedupes_texts` 用 10、`test_char_budget_groups_jobs_by_row_count` 用 2、其余三个用 5），断言不变。两个按行数命名的测试改名为 `test_char_budget_groups_jobs_by_row_count` / `test_char_budget_rows_groups_multi_target_per_row` |
| I5 | Task 5 | 计划只规定「缺译时带原 `assigned` 的子集补发」 | 补发**只做一次**：补发后仍缺的单元格直接记失败，不再二次补发。原因：这是「减少请求次数」的硬边界，循环补发会让最坏情况下的请求数失控；单次补发已能覆盖「模型漏译一两行」这个真实场景 |
| I6 | Task 5 | 计划把 `build_merged_prompt` 列为 `OpenAICompatibleTranslator` 的方法 | 实现为 `@staticmethod`，`ClaudeMessagesTranslator` / `CodexResponsesTranslator` 直接调 `OpenAICompatibleTranslator.build_merged_prompt(assigned, self.glossary)`。原因：沿用文件里既有的静态复用风格（这两个类本来就不是 OpenAI 的子类，靠 `_parse_translations_static` 复用），不必为了多一个方法去改继承关系 |
| I7 | Task 6 | 计划只加 `matching_glossary_entries` 与 `TranslatorConfig.glossary_source_key` | `create_provider` 的三个 AI 分支（`translator_service.py:305` / `:320` / `:335`）补传 `glossary_source_key=config.glossary_source_key`，三个 translator 构造器各加该参数并在 `translate_job_batch` 里传给 `build_merged_prompt`（`translator_service.py:871` / `:1056` / `:1183`）。Google 分支不传：Google 线路不走提示词，没有术语表注入点 |
| I8 | Task 7 | 计划把「`batch_size` → `char_budget`」的对话框与持久化改名放在 Task 7 Step 5 | 已在 Task 4 一并做完（见 I2）。Task 7 实际只落地：`TranslationWorker.retrying` 信号、设置对话框的勾选框与「清空缓存」按钮、倒计时文案、只重跑失败项、清空缓存方法 |
| I9 | Task 7 | 计划的 Task 7 测试清单不含「429 → 重试 → 成功」的端到端闸门 | 新增 `RetryWiringTests.test_rate_limit_is_retried_and_on_retry_is_called`（`tests/test_translator_service.py`，用 `mock.patch("urllib.request.urlopen")` 走**真实** `_post_json` 路径，先抛 429 带 `Retry-After: 0.01` 再成功）。原因：注入 `post_json` 会绕过 `_post_json`，既有假 provider 全都走不到重试层；没有这条测试，倒计时 UI 接到空信号也照样全绿 |
| I10 | Task 7 | 计划未列出决定 22（默认并发 1 → 3）会打破的既有断言 | `tests/test_main_gui.py:121` 的 `test_default_translation_provider_is_google` 断言 `translation_parallel_batches == 1` 改为 `== 3`；同文件 `FakeWorker` 补 `self.retrying = FakeSignal()`（`TranslationWorker` 多了一个信号），并在 `test_run_translation_jobs_starts_worker_instead_of_sync_translate` 末尾加一行 `assertIn(self.window.on_translation_retrying, worker.retrying.callbacks)` 验证信号真的接上了 |
| I11 | Task 8 | 计划假设「注入假 provider 就能验证重试」 | **发现：`post_json` 注入点绕过了整个重试层。** `OpenAICompatibleTranslator` 里是 `self.post_json = post_json or self._post_json`（`translator_service.py:824` / `:1018` / `:1149`），调用点是 `self.post_json(...)`（`:852` / `:891` / `:1041` / `:1081` / `:1168` / `:1194`）—— 一旦注入，`_post_json` 里的 `retry_call` 与 `HTTPError → TranslationRequestError` 转换全部不会执行，异常以原始 `HTTPError` 冒出，`_guarded` 也看不到 `status=429`。生产代码从不注入 `post_json`（只有测试用），所以不影响线上行为；但**所有既有假 provider 测试都走不到重试层**，端到端验证必须 mock `urllib.request.urlopen`（见 I9） |
| I12 | Task 8 | Task 8 Step 3 预期 Google 免费线路冒烟能跑通 | 本机 Google 返回 429「your computer or network may be sending automated queries」，冒烟失败。**但这恰好是整条链路的真实端到端验证**：`on_retry` 收到 `(1, 2, 0.42)`、`AdaptiveGate` 从 2 降到 1（`limits == [(1, True)]`）、`GOOGLE_MIN_INTERVAL=3.0` 把两次请求隔开（3 行、`parallel_batches=3` 只花了 3.71s，说明后两行没发出并发请求）。结论：限速防护本身工作正常，但**这台机器当前用不了 Google 免费线路**，需换网络或改用付费 API |
| I13 | Task 8 | 计划「既有测试的同步修改」表里同时写着 `test_translation_settings_dialog_saves_provider_and_parallel_batches` 断言 `== 40` 与 `test_translation_settings_loads_full_preset` 存 12 断言 12 | 两者不能同时成立（前者走 `QSpinBox` 会被夹到下限 200，后者直接写属性不夹）。实际：对话框测试用 `setValue(2400)` 断言 `== 2400`；主窗口测试保持存 12 断言 12。这条与 I3 同源，是计划的内部矛盾 |
| I14 | Task 8 | Step 6「若 README 或 docs/ 里描述了旧语义就更新」 | 无需执行：仓库根目录没有 `README.md`，`docs/` 下只有 `docs/superpowers/`（计划本身）。`.trae/specs/improve-translation-cancel-timeout-batching/spec.md` 里的「按行批次」是历史 spec 快照，不回改 |

### 仓库卫生：两个 commit 混入了开工前就存在的未提交改动

开工时工作区已有 58 个未提交改动（`__pycache__/`、`build/`、`dist/`、`build_exe.ps1`、`dayz_csv.py`、`tests/test_main_gui.py` 的 801 行新增、`.trae/specs/`、`TODO.txt`）。Task 1 与 Task 4 的提交用了 `git add -A`，把这些 WIP 一并带进了：

- `947763a`（Task 1）里 `main.py` 显示 980 行变更，而 Task 1 本身只改了 5 行（3 处 `TranslationCacheStore` 接线）
- `4b39498`（Task 4）带进了 `tests/test_main_gui.py` 的 891 行新增

**未重写历史**（WIP 没有丢失，全部 284 个测试仍绿）。但这两个 commit 的 `--stat` 不能当作本次改动的真实规模：Task 1–Task 8 自己改动的是 `translator_service.py` +800、`tests/test_translator_service.py` +881、`main.py` +206、`translation_worker.py` +2，以及新建 `translation_cache.py` 与 `tests/test_translation_cache.py`。后续提交一律用显式 `git add <文件>`。

## Global Constraints

- **不新增任何第三方依赖。** `requirements.txt` 保持 `PySide6` + `deep-translator`。所有新能力用标准库实现。
- **翻译入口不变。** `translate_selected_cells` / `translate_selected_rows` / `translate_selected_columns` / `translate_all_cells` / `translate_empty_cells` 的行为与调用方式不动。
- **主界面不变。** 菜单、工具栏、翻译按钮、状态栏控件数量不动。改动只发生在 `TranslationSettingsDialog` 内部与状态栏进度标签的文案。
- **行永不被劈开。** 同一 `job.row` 的所有 job 必须落在同一个批次里。
- **只翻本次实际请求的单元格。** 不要求 AI 返回整行（含已有内容单元格）的翻译 —— 沿用 `.trae/specs/improve-translation-cancel-timeout-batching/spec.md` 的既有约束。
- **不做批次拆分重试。** 一批失败就按退避重试同一批，最多 5 次；不做二分拆小。
- **不加统计面板。** 翻译结束后不显示请求数/token 数统计。
- **UI 文案 en/zh 都要**（`UI_TEXT` 的 `en` 与 `zh` 两份）。
- **`_translation_written_cells` 语义保持**：哪批翻完就写哪批，已写入的单元格不重复写。
- **id 只分配一次。** 任何「重新对子集编号」的写法都视为 bug（见本修订版问题 1）。
- 现有 6 个测试文件必须全绿。**行为被刻意改变的地方，测试要跟着改** —— 见「既有测试的同步修改」一节，那是本计划的一部分，不是可选步骤。

## 决定清单（来自需求访谈）

| # | 决定 |
|---|---|
| 1 | 谷歌免费翻译与 AI 翻译两条线都要支持，限速策略分开 |
| 2 | 失败自动等待重试 |
| 3 | 缓存存硬盘，跨次运行复用 |
| 4 | 并发默认自动模式，但提供上限旋钮 |
| 5 | 分批按内容长度自动切 |
| 6 | 换模型作废缓存；改单词本不作废；提供「清空翻译缓存」按钮 |
| 7 | 术语表只带本批文本里命中的条目 |
| 8 | 重试不拆批 |
| 9 | 限速等待时显示倒计时，且停止按钮立即生效 |
| 10 | 提供「只重跑失败项」按钮 |
| 11 | 同一行多目标语言合并成一次请求，源文只出现一次 |
| 12 | 谷歌单独限速 |
| 13 | 不显示统计面板 |
| 14 | 重试总共最多 5 次，单次最多等 60 秒 |
| 15 | 缓存放软件目录旁，不限制大小 |
| 16 | 撞限速降速后慢慢试探回升 |
| 17 | 交付物 = 本实施计划 + 自动化测试 |
| 18 | 返回带编号对象，只补发缺失项 |
| 19 | 调高回复上限 + 内部按产出量封批 |
| 20 | 「每批最多字数」上限 100000，默认 1500 |
| 21 | 术语表按**本批源语言对应的列**匹配源词（不硬编码 `original`） |
| 22 | 自动并发上限的默认值从 1 提到 3（否则自动模式在默认配置下完全不生效） |

## 常量

```python
# translator_service.py

# —— 分批（决定 5 / 19 / 20）——
DEFAULT_CHAR_BUDGET = 1500          # 每批源文字数预算默认值
MAX_CHAR_BUDGET = 100000            # 「每批最多字数」旋钮上限
MIN_CHAR_BUDGET = 200               # 仅用于「旧值迁移」判定，不参与分批钳制
DEFAULT_OUTPUT_CHAR_CAP = 16000     # 单批预估产出字符上限（≈ 8000 token）

# —— 自适应并发（决定 4 / 16 / 22）——
DEFAULT_AUTO_CONCURRENCY = 2        # 自动模式起始并发
MIN_AUTO_CONCURRENCY = 1
MAX_AUTO_CONCURRENCY = 8            # 自动模式上限旋钮的取值上限
RECOVER_AFTER_SUCCESSES = 8         # 连续成功多少次后并发 +1

# —— 限速与重试（决定 9 / 12 / 14）——
GOOGLE_MIN_INTERVAL = 3.0           # 谷歌免费接口：两次请求最小间隔（约 20 请求/分钟）
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 2.0
RETRY_MAX_DELAY = 60.0
RETRYABLE_STATUS = frozenset({408, 409, 413, 429, 500, 502, 503, 504})
FATAL_STATUS = frozenset({400, 401, 403, 404, 422})
RATE_LIMIT_STATUS = frozenset({429, 503})   # 命中即让自适应闸门减半

# —— 术语表（决定 7 / 21）——
GLOSSARY_MAX_ENTRIES = 200
```

> **`MIN_CHAR_BUDGET` 只用于迁移判定。** 上一版把它当成分批的下限钳制（`max(MIN_CHAR_BUDGET, char_budget)`），导致「传 10 就得到 200」，与自己的测试矛盾。分批只做 `max(1, ...)` 防零。

## File Map

| File | Responsibility |
|------|----------------|
| `translation_cache.py`（新建） | 磁盘缓存读写：原子写、可写目录探测与回退、损坏文件容错 |
| `translator_service.py` | `RetryPolicy` / `RateLimiter` / `AdaptiveGate` / `interruptible_sleep`；按字数预算分批；多语言合并提示词；带编号解析与缺失补发；术语表命中过滤；缓存键 |
| `translation_worker.py` | 新增 `retrying` 信号，把重试倒计时透传到 UI |
| `main.py` | 缓存落盘接线；设置对话框两个旋钮原地替换 + 清空缓存按钮；倒计时显示；「只重跑失败项」按钮；UI 文案 |
| `tests/test_translation_cache.py`（新建） | 缓存读写/原子性/回退/损坏容错 |
| `tests/test_translator_service.py` | 重试、退避、节流、分批、解析、缺失补发的单元测试 |
| `tests/test_main_gui.py` | 设置对话框控件、倒计时标签、只重跑失败项 |

---

### Task 1: 缓存落盘

**Files:**
- Create: `translation_cache.py`
- Modify: `translator_service.py` — `_cache_namespace` / `_cache_key`
- Modify: `main.py` — `__init__`、`finish_translation`、`fail_translation`、`cancel_translation`
- Test: `tests/test_translation_cache.py`

**Interfaces:**
- Produces: `TranslationCacheStore(base_dir=None, fallback_dir=None)`
- Produces: `TranslationCacheStore.path -> Path`
- Produces: `TranslationCacheStore.load() -> dict`
- Produces: `TranslationCacheStore.save(cache: dict) -> None`
- Produces: `TranslationCacheStore.clear() -> None`
- Produces: `TranslationCacheStore.is_writable() -> bool`
- Consumes: `TranslationService._cache_key` 返回的 5 元组

- [x] **Step 1: 写失败测试**

`tests/test_translation_cache.py`：
- `test_save_then_load_roundtrip`：存 `{("openai","english","chinese","gpt-4o","Knife"): "刀"}`，新实例 `load()` 得到等值字典（键还原成元组）。
- `test_load_missing_file_returns_empty`：目录为空时 `load() == {}`，不抛异常。
- `test_load_corrupt_file_returns_empty`：文件内容为 `"{not json"` 时 `load() == {}`。
- `test_save_is_atomic`：`save()` 后目录里不存在 `*.tmp` 残留。
- `test_falls_back_when_base_dir_unwritable`：`base_dir` 指向一个不可写路径（用一个同名**文件**占位，使 `mkdir` 失败），`path` 落在 `fallback_dir`。
- `test_clear_removes_file`：`clear()` 后文件不存在且 `load() == {}`。

- [x] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_translation_cache -v
```
预期：`ModuleNotFoundError: No module named 'translation_cache'`。

- [x] **Step 3: 实现 `translation_cache.py`**

```python
"""翻译缓存的磁盘持久化：软件目录旁一个 JSON 文件，写不进去就回退到用户数据目录。"""
import json
import os
import sys
from pathlib import Path

FILENAME = "translation_cache.json"
FORMAT_VERSION = 1


class TranslationCacheStore:
    def __init__(self, base_dir=None, fallback_dir=None):
        self.base_dir = Path(base_dir) if base_dir else self._default_base_dir()
        self.fallback_dir = Path(fallback_dir) if fallback_dir else self._default_fallback_dir()
        self.path = self._resolve_path()

    @staticmethod
    def _default_base_dir():
        # 打包后 sys.executable 是 exe；开发时 __file__ 是仓库根
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        return Path(__file__).resolve().parent

    @staticmethod
    def _default_fallback_dir():
        if sys.platform == "win32":
            root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            if root:
                return Path(root) / "DayZ_Translate_Tool"
        return Path.home() / ".local" / "share" / "DayZ_Translate_Tool"

    def _resolve_path(self):
        for directory in (self.base_dir, self.fallback_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                probe = directory / f".{FILENAME}.probe"
                probe.write_text("", encoding="utf-8")
                probe.unlink()
                return directory / FILENAME
            except OSError:
                continue
        return self.fallback_dir / FILENAME

    def is_writable(self):
        return self.path.parent.exists() and os.access(self.path.parent, os.W_OK)

    def load(self):
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(payload, dict) or payload.get("version") != FORMAT_VERSION:
            return {}
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return {}
        cache = {}
        for row in entries:
            if not isinstance(row, list) or len(row) != 6:
                continue
            key = tuple(str(part) for part in row[:5])
            value = row[5]
            if isinstance(value, str):
                cache[key] = value
        return cache

    def save(self, cache):
        entries = [list(key) + [value] for key, value in cache.items()]
        payload = {"version": FORMAT_VERSION, "entries": entries}
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass

    def clear(self):
        try:
            self.path.unlink()
        except OSError:
            pass
```

- [x] **Step 4: 缓存键去掉术语表（决定 6）**

`translator_service.py` 的 `_cache_namespace` 改为只含模型名：

```python
    def _cache_namespace(self, config):
        # 术语表不进缓存键：改单词本不作废已有译文（决定 6）。
        # 模型进缓存键：换模型自然作废。
        return config.model or ""
```

同时改 `translate_jobs` 里那行已经过时的注释（原文写「model 与单词本会影响 AI 翻译结果，纳入缓存命名空间避免命中过期翻译」，与新行为相反）：

```python
        # model 进缓存命名空间：换模型自然作废。
        # 单词本不进：改单词本不作废已有译文（决定 6，靠「清空缓存」手动纠正）。
        self.cache_namespace = self._cache_namespace(config)
```

> `json` 仍被提示词构造使用，import 保留。

**既有测试要同步改**：`tests/test_translator_service.py` 的 `test_cache_miss_when_glossary_changes` 断言的是**旧行为**。改名并反转断言：

```python
    def test_cache_hit_when_glossary_changes(self):
        """决定 6：改单词本不作废已有译文，缓存照常命中。"""
        fake = FakeBatchTranslator()
        shared_cache = {}
        jobs = [TranslationJob(0, 3, "Knife", "en", "de")]

        first_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        first_service.translate_jobs(jobs, TranslatorConfig(provider="google"))
        second_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        second = second_service.translate_jobs(
            jobs,
            TranslatorConfig(provider="google", glossary=[{"english": "Knife", "german": "Messer"}]),
        )

        self.assertEqual(second.cache_hits, 1)
```

（`batch_size=` 参数已在本版删除，见 Task 4 Step 4 的扫描步骤。）

- [x] **Step 5: main.py 接线**

`DayzTranslateTool.__init__`（`main.py:1325` 附近）把

```python
        self.translation_cache = {}
```
改为

```python
        self.translation_cache_store = TranslationCacheStore()
        self.translation_cache = self.translation_cache_store.load()
```
并在文件顶部 import：`from translation_cache import TranslationCacheStore`。

在 `finish_translation`、`fail_translation` 的收尾处、以及 `_clear_translation_thread` 之前，加入 `self.translation_cache_store.save(self.translation_cache)`（取消也要存：已翻好的部分不该白花）。

- [x] **Step 6: 运行测试**

```bash
python -m unittest tests.test_translation_cache tests.test_translator_service -v
```
预期：全绿。

- [x] **Step 7: Commit**

```bash
git add translation_cache.py tests/test_translation_cache.py translator_service.py main.py tests/test_translator_service.py
git commit -m "feat: persist translation cache to disk beside the app"
```

---

### Task 2: 可中断的退避重试

**Files:**
- Modify: `translator_service.py` — 新增 `TranslationRequestError`、`parse_retry_after`、`RetryPolicy`、`interruptible_sleep`、`retry_call`；改造四处请求点
- Test: `tests/test_translator_service.py`

**Interfaces:**
- Produces: `TranslationRequestError(Exception)`，属性 `status: int | None`、`retry_after: float | None`
- Produces: `parse_retry_after(headers) -> float | None`
- Produces: `interruptible_sleep(seconds, should_cancel=None, slice_seconds=0.2) -> None`（取消时抛 `TranslationCancelled`）
- Produces: `RetryPolicy(max_attempts, base_delay, max_delay, sleep)`，方法 `delay_for(attempt, retry_after=None) -> float`、`is_retryable(exc) -> bool`
- Produces: `retry_call(func, policy=None, should_cancel=None, on_retry=None, before_attempt=None) -> Any`
- Consumes: 现有 `TranslationCancelled`

> **本 Task 必须自洽。** `before_attempt` 是节流的挂载点（Task 3 接上），`TranslationService` 侧的重试策略字段也在这里补 —— 上一版把 `self.on_retry` / `self.retry_policy` 留到 Task 3 才定义，导致 Task 2 单独提交就 `AttributeError`。

- [x] **Step 1: 写失败测试**

在 `tests/test_translator_service.py` 新增 `RetryPolicyTests(unittest.TestCase)` 与 `RetryCallTests(unittest.TestCase)`：

`RetryPolicyTests`：
- `test_fatal_status_not_retryable`：`TranslationRequestError("bad", status=401)` → `is_retryable` 为 False。400/403/404/422 同理。
- `test_retryable_status`：408/409/413/429/500/502/503/504 → True。
- `test_url_error_retryable`：`TranslationRequestError("timeout")`（无 status）→ True。
- `test_delay_grows_and_caps`：`RetryPolicy(base_delay=2.0, max_delay=60.0)` 下 `delay_for(1)` ∈ (1.5, 2.0]、`delay_for(3)` ∈ (6.0, 8.0]、`delay_for(10)` ≤ 60.0。
- `test_retry_after_header_wins`：`delay_for(1, retry_after=7.0) == 7.0`；`retry_after=0` 与 `retry_after=999` 被忽略（回落到指数退避）。
- `test_parse_retry_after_milliseconds`：`{"retry-after-ms": "1500"}` → 1.5。
- `test_parse_retry_after_seconds`：`{"Retry-After": "12"}` → 12.0。
- `test_parse_retry_after_http_date`：`{"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}` → 相对秒数 > 0（用 `unittest.mock.patch` 固定当前时间）。
- `test_parse_retry_after_handles_missing`：`None` / `{}` → `None`。

`RetryCallTests`：
- `test_retry_call_retries_then_succeeds`：函数前两次抛 429，第三次返回 `"ok"`；`retry_call` 返回 `"ok"`，调用次数 3，`on_retry` 收到 2 次回调且第 1 次参数为 `(1, 5, wait)`。
- `test_retry_call_gives_up_after_max_attempts`：一直抛 429 → 抛 `TranslationRequestError`，调用次数 5。
- `test_retry_call_does_not_retry_fatal`：抛 401 → 立即抛出，调用次数 1。
- `test_retry_call_cancel_interrupts_wait`：`should_cancel` 在第 1 次失败后返回 True → 抛 `TranslationCancelled`，且总耗时 < 1 秒（用 `base_delay=60.0` 证明没有真的等）。
- `test_before_attempt_runs_on_every_attempt`：计数器版 `before_attempt`，在「前两次 429、第三次成功」的用例里**恰好被调用 3 次**。这是防止「重试绕过节流」的回归闸门。

测试里用 `RetryPolicy(..., sleep=...)` 注入假的 sleep 以避免真等待。

- [x] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_translator_service.RetryPolicyTests -v
```
预期：`AttributeError` / `ImportError`。

- [x] **Step 3: 实现重试层**

在 `translator_service.py` 顶部补 import：`import random`、`import time`、`from email.utils import parsedate_tz, mktime_tz`。

```python
class TranslationRequestError(Exception):
    """一次 HTTP 请求的失败。带状态码与 Retry-After，供重试层判定。"""

    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def parse_retry_after(headers):
    """读 Retry-After / retry-after-ms。无法解析或超出范围时返回 None。"""
    if not headers:
        return None
    get = getattr(headers, "get", None)
    if get is None:
        return None
    milliseconds = get("retry-after-ms")
    if milliseconds:
        try:
            return max(0.0, float(milliseconds) / 1000.0)
        except (TypeError, ValueError):
            pass
    raw = get("Retry-After") or get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    parsed = parsedate_tz(str(raw))
    if parsed is None:
        return None
    try:
        return max(0.0, float(mktime_tz(parsed) - time.time()))
    except (OverflowError, ValueError):
        return None


def interruptible_sleep(seconds, should_cancel=None, slice_seconds=0.2):
    """分片 sleep，每片查一次取消标志 —— 限速等待期间「停止」必须立刻生效（决定 9）。"""
    remaining = float(seconds)
    while remaining > 0:
        if should_cancel and should_cancel():
            raise TranslationCancelled()
        step = min(slice_seconds, remaining)
        time.sleep(step)
        remaining -= step
    if should_cancel and should_cancel():
        raise TranslationCancelled()


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = RETRY_MAX_ATTEMPTS
    base_delay: float = RETRY_BASE_DELAY
    max_delay: float = RETRY_MAX_DELAY
    sleep: object = interruptible_sleep

    def is_retryable(self, exc):
        if isinstance(exc, TranslationCancelled):
            return False
        if isinstance(exc, TranslationRequestError):
            if exc.status is None:
                return True          # 超时 / 连接断 / URLError
            if exc.status in FATAL_STATUS:
                return False
            return exc.status in RETRYABLE_STATUS or exc.status >= 500
        return isinstance(exc, (TimeoutError, ConnectionError, OSError))

    def delay_for(self, attempt, retry_after=None):
        # 复刻 openai SDK 的取整与抖动：min(base·2ⁿ⁻¹, max) × (1 − 0.25·random())
        if retry_after is not None and 0 < retry_after <= self.max_delay:
            return float(retry_after)
        raw = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        return raw * (1 - 0.25 * random.random())


def retry_call(func, policy=None, should_cancel=None, on_retry=None, before_attempt=None):
    """按 policy 重试 func。

    before_attempt 在**每次尝试之前**调用（含第一次与每次重试）—— 全局节流就挂在这里，
    这样「重试」也受同一个最小间隔约束，不会出现「撞了限速反而连发」（本修订版问题 3）。
    on_retry(attempt, max_attempts, wait_seconds) 在每次等待之前调用一次。
    """
    policy = policy or RetryPolicy()
    last_error = None
    for attempt in range(1, policy.max_attempts + 1):
        if should_cancel and should_cancel():
            raise TranslationCancelled()
        if before_attempt is not None:
            before_attempt()
        try:
            return func()
        except TranslationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — 是否重试由 policy 判定
            if not policy.is_retryable(exc):
                raise
            last_error = exc
            if attempt >= policy.max_attempts:
                break
            wait = policy.delay_for(attempt, getattr(exc, "retry_after", None))
            if on_retry:
                on_retry(attempt, policy.max_attempts, wait)
            policy.sleep(wait, should_cancel)
    raise last_error
```

- [x] **Step 4: 给四个 provider 接上重试**

**分两组改，Google 与另外三个的请求路径不同，不能套同一段代码。**

**(a) 三个 AI provider** —— `OpenAICompatibleTranslator` / `ClaudeMessagesTranslator` / `CodexResponsesTranslator` 的构造器各加三个参数并保存（**全部带默认值，保证 Task 2 不依赖 Task 3**）：

```python
    def __init__(self, source, target, api_key, model, base_url="", glossary=None,
                 glossary_source_key="", post_json=None, timeout=60.0, should_cancel=None,
                 retry_policy=None, on_retry=None, before_attempt=None):
        ...
        self.glossary_source_key = glossary_source_key
        self.retry_policy = retry_policy or RetryPolicy()
        self.on_retry = on_retry
        self.before_attempt = before_attempt
```

（`glossary_source_key` 由 Task 6 使用，此处先占位。）它们的 `_post_json` 改成「把网络调用抽成闭包 → 交给 `retry_call`」：

```python
    def _post_json(self, url, headers, payload):
        if self.should_cancel and self.should_cancel():
            raise TranslationCancelled()
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def attempt():
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise TranslationRequestError(
                    f"OpenAI HTTP {exc.code}: {detail}",
                    status=exc.code,
                    retry_after=parse_retry_after(exc.headers),
                ) from exc
            except urllib.error.URLError as exc:
                raise TranslationRequestError(f"OpenAI request failed: {exc.reason}") from exc

        return retry_call(attempt, self.retry_policy, self.should_cancel,
                          self.on_retry, self.before_attempt)
```

（`<Provider>` 文案按各自原有：`OpenAI` / `Claude` / `Codex`。）

**(b) `GoogleTranslateTranslator` 走的是完全不同的路径 —— 它没有 `_post_json`。**

现状（`translator_service.py:755-762`）：构造器是 `__init__(self, source="auto", target="en", base_url="", timeout=None, request_func=None, should_cancel=None)` —— **没有 `api_key` / `model` / `glossary`**，且带一个可注入的 `request_func`（测试全靠它）。请求发生点是一个方法调用，不是一个 JSON POST：

```python
    def __init__(self, source="auto", target="en", base_url="", timeout=None,
                 request_func=None, should_cancel=None,
                 retry_policy=None, on_retry=None, before_attempt=None):
        ...
        self.retry_policy = retry_policy or RetryPolicy()
        self.on_retry = on_retry
        self.before_attempt = before_attempt
```

`translate_batch` 里那一行 `data = self.request_func(url, headers)`（`:789`）改成：

```python
        # 重试包在 request_func **外面**：这样测试注入的假 request_func 也走同一套重试，
        # 同时不改它「返回已解析数据」的契约。
        data = retry_call(
            lambda: self.request_func(url, headers),
            self.retry_policy, self.should_cancel, self.on_retry, self.before_attempt,
        )
```

并把 `_default_request`（`:805-819`）里的两处 `RuntimeError` 改成 `TranslationRequestError`，带上状态码与 `Retry-After`：

```python
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TranslationRequestError(
                f"Google Translate HTTP {exc.code}: {detail}",
                status=exc.code,
                retry_after=parse_retry_after(exc.headers),
            ) from exc
        except urllib.error.URLError as exc:
            raise TranslationRequestError(f"Google Translate request failed: {exc.reason}") from exc
```

> Google 一次 `translate_batch(texts)` 就是**一个** HTTP 请求（`q` 参数重复出现，`:774-789`），本来就已批量。所以「按字数分批」对它只影响「一次带多少条」，不影响请求数口径。

`TranslationService.__init__` 补上重试策略字段（Task 3 只做接线，不新增字段）：

```python
        self.retry_policy = RetryPolicy()
        self.on_retry = None
```

`create_provider`（`:60`）里给 **4 个分支**各补 `retry_policy=self.retry_policy, on_retry=self.on_retry`：

- `google`（`:62-69`）→ 传给 `google_translator_class`（该分支**不加** `glossary`，Google 没有这个参数）
- `openai`（`:85-95`）/ `claude`（`:96-106`）/ `codex`（`:107-117`）→ 各传给对应 class

`before_attempt` 在 Task 3 接。**`mymemory` / `deepl` / `microsoft` 三个分支不动** —— 它们直接用 deep-translator 的类，本计划不改造它们（它们也拿不到 `retry_policy`，属于已知的未覆盖面）。

- [x] **Step 5: 修正既有测试的假 provider**

`FakeOpenAITranslator` 在测试里出现 **3 次**（`:70`、`:317`、`:446`），当前签名都是：

```python
            def __init__(self, source, target, api_key, model, base_url, glossary, timeout=60.0, should_cancel=None):
```

`create_provider` 一旦多传 `retry_policy`/`on_retry`，这三处都 `TypeError`（`_create_provider` 的 TypeError 回退会再试一次 `(source, target)`，同样失败）。三处统一改为：

```python
            def __init__(self, source, target, api_key, model, base_url, glossary,
                         glossary_source_key="", timeout=60.0, should_cancel=None,
                         retry_policy=None, on_retry=None, before_attempt=None):
```

（`CancellingTranslator` 在 `:503` 用的是 `*args, **kwargs`，不受影响。）

同样地，`_default_request` 的异常类型从 `RuntimeError` 换成 `TranslationRequestError` 后，这两处**不用改**且必须继续通过：

- `test_request_error_raises_runtime_error`（`:637`）注入的假 `request_func` 直接抛 `RuntimeError("connection timed out")` —— `RetryPolicy.is_retryable(RuntimeError)` 为 False，原样向上抛，断言仍然成立。
- `test_unexpected_response_raises_runtime_error`（`:649`）的 `RuntimeError` 来自 `_extract_translations`（在重试**之外**），不受影响。

- [x] **Step 6: 运行测试**

```bash
python -m unittest tests.test_translator_service -v
```
预期：新增测试与既有测试全绿。

> **不要去改这 3 处 `assertRaises(RuntimeError)`**（`tests/test_translator_service.py:572` / `:645` / `:655`），但要清楚它们各自为什么不受影响：
>
> - `:572` `test_translate_batch_count_mismatch_raises` —— 数量不符是 `translate_batch` **解析后**的检查，在重试之外。
> - `:645` `test_request_error_raises_runtime_error` —— 它注入的假 `request_func` 直接抛 `RuntimeError("connection timed out")`。`RetryPolicy.is_retryable` 对 `RuntimeError` 返回 False，所以原样向上抛。**这一处确实经过请求路径**，它之所以仍然通过，靠的是「`RuntimeError` 不可重试且不被转换」，不是「不经过 `_post_json`」。真正会被转成 `TranslationRequestError` 的是 `_default_request` 里的 `HTTPError`/`URLError`。
> - `:655` `test_unexpected_response_raises_runtime_error` —— 解析阶段的 `RuntimeError`，在重试之外。

- [x] **Step 7: Commit**

```bash
git add translator_service.py tests/test_translator_service.py
git commit -m "feat: add interruptible exponential-backoff retry with Retry-After support"
```

---

### Task 3: 全局节流与自适应并发

**Files:**
- Modify: `translator_service.py` — 新增 `RateLimiter`、`AdaptiveGate`、`TranslationService._throttle` / `_guarded`；改造 `translate_jobs` / `_translate_openai_jobs` / `_translate_batches` / `_translate_one_openai_batch` / `_translate_one_row_batch`
- Test: `tests/test_translator_service.py`

**Interfaces:**
- Produces: `RateLimiter(min_interval=0.0)`，方法 `acquire(should_cancel=None)`、`set_interval(seconds)`、属性 `min_interval`
- Produces: `AdaptiveGate(initial=DEFAULT_AUTO_CONCURRENCY, minimum=MIN_AUTO_CONCURRENCY, maximum=MAX_AUTO_CONCURRENCY, recover_after=RECOVER_AFTER_SUCCESSES)`，方法 `acquire(should_cancel=None)`、`release(rate_limited=False)`、属性 `limit`、`active`
- Produces: `TranslationService._throttle() -> None`
- Produces: `TranslationService._guarded(func, *args, **kwargs) -> Any`
- Consumes: `interruptible_sleep`、`TranslationRequestError`、`TranslationCancelled`

- [x] **Step 1: 写失败测试**

`RateLimiterTests`：
- `test_first_acquire_does_not_wait`：新建后 `acquire()` 立即返回（`time.monotonic` 前后差 < 0.05）。
- `test_second_acquire_waits_min_interval`：`RateLimiter(min_interval=0.3)` 连续两次 `acquire`，总耗时 ≥ 0.25。
- `test_acquire_honors_cancel`：`min_interval=5.0`，先 `acquire()` 一次，第二次传 `should_cancel=lambda: True` → 抛 `TranslationCancelled` 且耗时 < 1 秒。

`AdaptiveGateTests`（用极小的 recover 阈值避免真等待）：
- `test_limit_halves_on_rate_limit`：`AdaptiveGate(initial=4, minimum=1, maximum=8)` → `release(rate_limited=True)` 后 `limit == 2`；再来一次 → `1`；再来一次仍为 `1`。
- `test_limit_recovers_after_successes`：`initial=2, maximum=4, recover_after=3` → 连续 3 次 `release()` 后 `limit == 3`；再 3 次 → `4`；再 3 次仍为 `4`。
- `test_rate_limit_resets_success_streak`：连续 2 次成功（`recover_after=3`）后 `release(rate_limited=True)` → 再成功 2 次 `limit` 不回升。
- `test_initial_is_clamped_into_range`：`AdaptiveGate(initial=99, minimum=1, maximum=4)` → `limit == 4`；`AdaptiveGate(initial=0, minimum=1, maximum=4)` → `limit == 1`。
- `test_acquire_blocks_beyond_limit`：`initial=1` 时，一个线程 `acquire()` 占住，主线程再 `acquire()` 在 `should_cancel` 为 True 时抛 `TranslationCancelled`。

`GuardedBatchTests`：
- `test_rate_limited_error_halves_gate`：把 `_guarded` 包在一个抛 `TranslationRequestError(status=429)` 的函数外，`gate.limit` 减半，且异常**继续向外抛**（不能被 `_guarded` 吞掉）。
- `test_non_rate_limit_error_does_not_halve_gate`：抛 `TranslationRequestError(status=401)` → `limit` 不变。
- `test_batch_failure_still_counts_jobs_as_failed`：注入一个 `translate_job_batch` 抛 429 的假 translator，跑 `translate_jobs` → `results.failed == len(jobs)` 且 `results.cancelled is False`（限速不该让整次运行看起来像被取消）。

- [x] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_translator_service.RateLimiterTests tests.test_translator_service.AdaptiveGateTests tests.test_translator_service.GuardedBatchTests -v
```
预期：`AttributeError`。

- [x] **Step 3: 实现节流与闸门**

```python
class RateLimiter:
    """全局最小请求间隔。线程安全，纯标准库（替代 aiolimiter）。"""

    def __init__(self, min_interval=0.0):
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self.min_interval = float(min_interval)

    def set_interval(self, seconds):
        with self._lock:
            self.min_interval = max(0.0, float(seconds))

    def acquire(self, should_cancel=None):
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self.min_interval
        if wait > 0:
            interruptible_sleep(wait, should_cancel)


class AdaptiveGate:
    """动态并发闸门：撞到限速立刻减半，连续平稳若干次后 +1（决定 16）。"""

    def __init__(self, initial=DEFAULT_AUTO_CONCURRENCY, minimum=MIN_AUTO_CONCURRENCY,
                 maximum=MAX_AUTO_CONCURRENCY, recover_after=RECOVER_AFTER_SUCCESSES):
        self._cond = threading.Condition()
        self._minimum = max(1, int(minimum))
        self._maximum = max(self._minimum, int(maximum))
        self._limit = min(max(int(initial), self._minimum), self._maximum)
        self._active = 0
        self._streak = 0
        self._recover_after = max(1, int(recover_after))

    @property
    def limit(self):
        with self._cond:
            return self._limit

    @property
    def active(self):
        with self._cond:
            return self._active

    def acquire(self, should_cancel=None):
        with self._cond:
            while self._active >= self._limit:
                if should_cancel and should_cancel():
                    raise TranslationCancelled()
                self._cond.wait(0.2)
            if should_cancel and should_cancel():
                raise TranslationCancelled()
            self._active += 1

    def release(self, rate_limited=False):
        with self._cond:
            self._active = max(0, self._active - 1)
            if rate_limited:
                self._limit = max(self._minimum, self._limit // 2)
                self._streak = 0
            else:
                self._streak += 1
                if self._streak >= self._recover_after and self._limit < self._maximum:
                    self._limit += 1
                    self._streak = 0
            self._cond.notify_all()
```

`translator_service.py` 顶部补 `import threading`。

- [x] **Step 4: 接进翻译流程**

`TranslationService` 新增两个方法：

```python
    def _throttle(self):
        """每次 HTTP 尝试（含重试）之前调用：全局限速（决定 12）。"""
        if self.rate_limiter is not None:
            self.rate_limiter.acquire(self.should_cancel)

    def _guarded(self, func, *args, **kwargs):
        """把一个批次的执行包在自适应闸门里，并把限速信号回传给闸门。

        func 抛 TranslationRequestError 时必须继续向外抛（调用方负责吞），
        否则闸门永远收不到「被限速了」这个信号 —— 降速功能就是死的。
        """
        if self.gate is not None:
            self.gate.acquire(self.should_cancel)
        rate_limited = False
        try:
            return func(*args, **kwargs)
        except TranslationRequestError as exc:
            rate_limited = exc.status in RATE_LIMIT_STATUS
            raise
        finally:
            if self.gate is not None:
                self.gate.release(rate_limited=rate_limited)
```

`translate_jobs` 在 AI 分支之前装配两条线：

```python
        # 谷歌免费接口按 IP 限「短时间发太密」，与 AI 的 token 配额是两套规则（决定 1 / 12）
        self.rate_limiter = RateLimiter(GOOGLE_MIN_INTERVAL if provider == "google" else 0.0)
        # 自动模式的并发上限 = 用户设的并发数（决定 22：默认 3）。
        # 关掉自动时闸门为 None，并发完全由线程池大小决定。
        ceiling = max(MIN_AUTO_CONCURRENCY, int(config.parallel_batches or MIN_AUTO_CONCURRENCY))
        if config.auto_concurrency:
            self.gate = AdaptiveGate(
                initial=min(DEFAULT_AUTO_CONCURRENCY, ceiling),
                minimum=MIN_AUTO_CONCURRENCY,
                maximum=ceiling,
            )
        else:
            self.gate = None
```

`finally` 里清理：`self.rate_limiter = None`、`self.gate = None`。

`create_provider` 的四个 urllib provider 分支补 `before_attempt=self._throttle`。

`_translate_openai_jobs` 的串行与并行两条路径都改为经 `_guarded`，并吞掉 `TranslationRequestError`：

```python
    def _translate_openai_jobs(self, jobs, config, results, progress_callback=None, should_cancel=None):
        provider = normalize_provider(config.provider)
        jobs = self._openai_uncached_jobs(jobs, results, provider)
        if not jobs:
            return results
        translator = self._create_provider("auto", "multi", config)
        batches = list(self.iter_row_batches(jobs, config.char_budget, DEFAULT_OUTPUT_CHAR_CAP))
        if not batches:
            return results
        max_workers = max(1, int(config.parallel_batches or 1))
        try:
            if max_workers == 1 or len(batches) == 1:
                for batch in batches:
                    if should_cancel and should_cancel():
                        break
                    try:
                        self._guarded(self._translate_one_openai_batch, translator, batch, results, provider)
                    except TranslationRequestError:
                        pass          # 批内已记失败，闸门已收到限速信号
                    if progress_callback:
                        progress_callback(results)
            else:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(self._guarded, self._translate_one_openai_batch,
                                        translator, batch, results, provider): batch
                        for batch in batches
                    }
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except TranslationCancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            raise
                        except TranslationRequestError:
                            pass
                        if progress_callback:
                            progress_callback(results)
                        if should_cancel and should_cancel():
                            executor.shutdown(wait=False, cancel_futures=True)
                            return
        except TranslationCancelled:
            results.cancelled = True
        return results
```

`_translate_batches` 的串行与并行路径同样经 `_guarded`。**`_translate_one_row_batch` 是 Google 线路的限速信号进入闸门的唯一路径**，它的 `except Exception` 必须同样改为「记失败后 `raise`（若是 `TranslationRequestError`），其余照旧 `return`」—— 不改的话，Google 的 429 会在这里被吞掉，自适应闸门永远收不到降速信号（与 `_translate_one_openai_batch` 是同一个 bug）：

```python
    def _translate_one_openai_batch(self, translator, batch, results, provider):
        try:
            translated_texts = translator.translate_job_batch(batch)
        except TranslationCancelled:
            raise
        except TranslationRequestError as exc:
            self._record_failed_jobs(batch, results, exc)
            raise                    # 让闸门看到限速信号（本修订版问题 2）
        except Exception as exc:
            self._record_failed_jobs(batch, results, exc)
            return                   # 非限速类错误：本批记失败，不打断其它批次
        self._store_job_results(batch, translated_texts, results, provider)
```

（Task 5 会替换这个方法的成功路径，**但必须保留这里的异常契约**。）

- [x] **Step 5: 运行测试**

```bash
python -m unittest tests.test_translator_service -v
```
预期：全绿。

- [x] **Step 6: Commit**

```bash
git add translator_service.py tests/test_translator_service.py
git commit -m "feat: add global request throttle and adaptive concurrency gate"
```

---

### Task 4: 按字数预算分批（行边界封批）

**Files:**
- Modify: `translator_service.py` — `TranslatorConfig` 字段改名；`_row_chunks` 替换为 `iter_row_batches`；`TranslationService.__init__` 去掉 `batch_size`
- Modify: `main.py` — `create_translation_worker` / `run_translation_test`
- Test: `tests/test_translator_service.py`（含机械扫描）

**Interfaces:**
- Produces: `TranslatorConfig.char_budget: int = DEFAULT_CHAR_BUDGET`、`TranslatorConfig.auto_concurrency: bool = True`、`TranslatorConfig.glossary_source_key: str = ""`
- Produces: `TranslationService.iter_row_batches(jobs, char_budget, output_char_cap) -> Iterator[list[TranslationJob]]`
- 移除：`TranslatorConfig.batch_size`、`TranslationService.__init__(batch_size=...)`、`TranslationService.batch_size`、`TranslationService._row_chunks`
- 改名：Task 标题与正文统一用 `iter_row_batches`（上一版标题误写 `_row_batches`）

- [x] **Step 1: 写失败测试**

`RowBatchingTests`：
- `test_short_rows_share_a_batch`：20 个行、每行 5 字、`char_budget=100` → 单个批次。
- `test_budget_cuts_at_row_boundary`：`char_budget=10`，每行 6 字 → 每批 1 行（6+6=12 ≥ 10 时封批）。
- `test_row_is_never_split`：一行有 3 个列（同 row 的 3 个 job），`char_budget=1` → 这 3 个 job 在同一个批次里。
- `test_oversized_row_gets_own_batch`：行 A 5 字、行 B 500 字、行 C 5 字，`char_budget=100` → 三个批次，B 单独一批且 C 不被并进 B。
- `test_output_cap_cuts_batch`：单行 10 字、8 个目标语言、`output_char_cap=100` → 每批 1 行（10×8=80，再加一行 160 ≥ 100）。
- `test_budget_is_not_clamped_upward`：`char_budget=10` 时实际封批阈值就是 10，不是 `MIN_CHAR_BUDGET`（上一版把下限钳制到 200，这条测试是那个 bug 的回归闸门）。
- `test_all_jobs_preserved`：任意参数下 `sum(len(b) for b in batches) == len(jobs)` 且每个 job 恰好出现一次。

- [x] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_translator_service.RowBatchingTests -v
```
预期：`AttributeError: 'TranslationService' object has no attribute 'iter_row_batches'`。

- [x] **Step 3: 实现分批**

```python
    def iter_row_batches(self, jobs, char_budget=DEFAULT_CHAR_BUDGET,
                         output_char_cap=DEFAULT_OUTPUT_CHAR_CAP):
        """按行累积、按字数预算封批。行永不被劈开。

        形状参照 bilingual_book_maker 的 _assign_batch_indexes
        （book_maker/loader/epub_loader.py:3143-3160）：累到预算就封批，
        超长条目单独成批，不拖累下一条。
        """
        if not jobs:
            return
        # 只防零，不做下限钳制 —— 下限钳制会让「传 10」变成 200，测试与实现互相矛盾。
        budget = max(1, int(char_budget or DEFAULT_CHAR_BUDGET))
        cap = max(1, int(output_char_cap or DEFAULT_OUTPUT_CHAR_CAP))

        by_row = {}
        for job in jobs:
            by_row.setdefault(job.row, []).append(job)

        batch = []
        batch_chars = 0
        batch_cost = 0
        for row in sorted(by_row):
            row_jobs = by_row[row]
            # 同一行共享同一句原文，源文字数按最长的那条算
            row_chars = max(len(job.text) for job in row_jobs)
            # 预估产出量：源文字数 × 目标语言数（同一目标语言只算一次）
            targets = {(job.source_code, job.target_code) for job in row_jobs}
            row_cost = row_chars * max(1, len(targets))

            if batch and (batch_chars + row_chars > budget or batch_cost + row_cost > cap):
                yield batch
                batch, batch_chars, batch_cost = [], 0, 0

            batch.extend(row_jobs)
            batch_chars += row_chars
            batch_cost += row_cost

            if row_chars > budget or row_cost > cap:
                yield batch
                batch, batch_chars, batch_cost = [], 0, 0

        if batch:
            yield batch
```

`_translate_openai_jobs` 与 `_translate_batches` 里的 `list(self._row_chunks(...))` 改为：

```python
        batches = list(self.iter_row_batches(jobs, config.char_budget, DEFAULT_OUTPUT_CHAR_CAP))
```
（`_translate_batches` 里第一参数是 `group_jobs`。两个方法**已经**接收 `config`，不需要改签名。）

`TranslatorConfig` 的 `batch_size: int = 30` 改为 `char_budget: int = DEFAULT_CHAR_BUDGET`，并加 `auto_concurrency: bool = True`、`glossary_source_key: str = ""`。`TranslationService.__init__` 去掉 `batch_size` 参数与 `self.batch_size`。删除 `_row_chunks`。

- [x] **Step 4: 机械扫描既有测试**

测试里 `batch_size=` 现在只是噪音参数（分批改由 `config.char_budget` 决定），删掉：

```bash
sed -i -E 's/, batch_size=[0-9]+//g; s/batch_size=[0-9]+, //g; s/\(batch_size=[0-9]+\)/()/g' tests/test_translator_service.py
grep -n "batch_size" tests/test_translator_service.py   # 应无输出
```

`main.py` 两处：

```python
            service=TranslationService(cache=self.translation_cache),          # 原 batch_size=...
```
```python
                char_budget=self.translation_char_budget,                        # 原 batch_size=...
```
以及测试连接那条路径：`TranslationService(batch_size=len(jobs))`（`main.py:687`）→ `TranslationService()`；构造 `TranslatorConfig` 的地方不是内联的，而是 `_build_test_config`（`main.py:655`）里的 `batch_size=self.batch_size_input.value()`（`:660`）→ `char_budget=MAX_CHAR_BUDGET`（测试连接固定用一个大预算，不分批）。

**同时重写两个按行数分批的测试**（它们测的是被刻意替换掉的旧行为）：

- `test_batch_size_groups_jobs_by_row_count`（`tests/test_translator_service.py:47`）→ 改为 `test_char_budget_groups_jobs_by_budget`，用 `TranslatorConfig(provider="google", char_budget=N)` 表达同样的「每批 N 行」场景。
- `test_batch_size_rows_groups_multi_target_per_row`（`:66`）→ 同样改用 `char_budget`。

- [x] **Step 5: 运行测试**

```bash
python -m unittest tests.test_translator_service -v
```
预期：全绿。

- [x] **Step 6: Commit**

```bash
git add translator_service.py main.py tests/test_translator_service.py
git commit -m "feat: batch by character budget on row boundaries instead of fixed row count"
```

---

### Task 5: 多语言合并 + 带编号返回 + 缺失补发

**Files:**
- Modify: `translator_service.py` — 三个 AI translator 的提示词与解析；`_translate_one_openai_batch` / `_store_job_results`
- Test: `tests/test_translator_service.py`

**Interfaces:**
- Produces: `assign_batch_ids(jobs) -> dict[int, list[TranslationJob]]`（模块级，**唯一的 id 分配点**）
- Produces: `salvage_truncated_object(text) -> str`（模块级）
- Produces: `parse_numbered_translations(content) -> dict[int, dict[str, str]]`（模块级）
- Produces: `OpenAICompatibleTranslator.build_merged_prompt(assigned, glossary_entries=None) -> str`
- Produces: `translate_job_batch(jobs, assigned=None) -> dict[int, dict[str, str]]`（**保留方法名**：既有 6 处测试调用它）
- Produces: `TranslationService._missing_assigned(assigned, parsed) -> dict[int, list[TranslationJob]]`
- Produces: `TranslationService._store_parsed_results(assigned, parsed, results, provider) -> None`
- 移除：`TranslationService._store_job_results` 的「数量不符就抛」逻辑（已被缺失补发取代）

> **本 Task 的核心约束（决定 18 + 本修订版问题 1）**：id 只在 `assign_batch_ids` 分配一次。补发时传入的是**同一份映射的子集**，因此 id 天然稳定。任何「对补发子集重新编号」的写法都会让补发的第 1 行冒充原第 1 行，静默写错单元格并污染磁盘缓存。

- [x] **Step 1: 写失败测试**

`IdAssignmentTests`：
- `test_ids_follow_row_order`：3 行 → `{1: [行0 的 jobs], 2: [...], 3: [...]}`。
- `test_same_row_shares_one_id`：一行 8 个目标语言 → 只有一个 id，其值是 8 个 job。
- `test_subset_keeps_original_ids`：`assign_batch_ids(3 行)` 得到 `{1,2,3}`；取 `{k: v for k, v in assigned.items() if k in (1, 3)}` 再喂给 `build_merged_prompt` → 提示词里的 id 仍是 **1 和 3**，不是 1 和 2。（本修订版问题 1 的回归闸门。）

`MergedPromptTests`：
- `test_source_text_appears_once_per_row`：一行 8 个目标语言 → 提示词里该源文只出现 1 次。
- `test_targets_listed_per_item`：提示词含 `"targets": ["chinese", "russian", ...]`。
- `test_only_requested_cells_included`：一行 8 列但只有 3 个 job → `targets` 恰好 3 个。
- `test_prompt_is_deterministic`：同一输入两次调用输出完全相同（前缀缓存的前提）。

`NumberedParsingTests`：
- `test_parses_clean_object`：`{"1": {"chinese": "刀"}, "2": {"chinese": "盾"}}` → 对应字典。
- `test_strips_code_fence`：被 ``` ```json ``` 包裹时同样解析成功。
- `test_salvages_truncated_object`：内容为 `{"1": {"chinese": "刀"}, "2": {"chinese": "盾"` （末尾被腰斩）→ 至少救回 id 1，不抛异常。
- `test_rejects_non_object`：`["刀"]` → 抛 `TranslationRequestError`。
- `test_drops_non_string_values`：`{"1": {"chinese": 42}}` → id 1 被丢弃。

`MissingRecoveryTests`：
- `test_missing_assigned_detected`：3 个 id，返回只有 id 1 和 3 → `_missing_assigned` 返回 `{2: [该行缺译文的 job]}`。
- `test_second_request_covers_only_missing`：注入一个假 translator，第 1 次返回缺 id 2 的对象，第 2 次只收到含 **id 2** 的请求，最终 3 个单元格全部填上。
- `test_recovery_ids_are_not_renumbered`：同上，但断言第 2 次请求的提示词里 id 是 **2**（而非重新编号后的 1）—— 本修订版问题 1 的端到端回归闸门。
- `test_still_missing_after_recovery_counts_failed`：两次都缺 id 2 → `results.failed == 1`，`results.cell_results` 有 id 1、3。

- [x] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_translator_service.IdAssignmentTests tests.test_translator_service.NumberedParsingTests -v
```
预期：`AttributeError` / `ImportError`。

- [x] **Step 3: 实现 id 分配与合并提示词**

```python
def assign_batch_ids(jobs):
    """给一批 job 分配稳定 id：同一行的所有 job 共享一个 id。

    **id 只在这里分配一次。** 补发时直接复用同一份映射的子集，绝不重新编号 ——
    重新编号会让补发的第 1 行冒充原来的第 1 行，把结果写到错误的单元格并污染磁盘缓存。
    """
    by_row = {}
    for job in jobs:
        by_row.setdefault(job.row, []).append(job)
    return {index: by_row[row] for index, row in enumerate(sorted(by_row), start=1)}
```

```python
    def build_merged_prompt(self, assigned, glossary_entries=None):
        """assigned: {id: [该行的 job]}（由 assign_batch_ids 产出，id 稳定）。"""
        items = []
        for item_id in sorted(assigned):
            row_jobs = assigned[item_id]
            targets = []
            for job in row_jobs:
                if job.target_code not in targets:
                    targets.append(job.target_code)
            items.append({
                "id": item_id,
                "source_language": row_jobs[0].source_code,
                "targets": targets,
                "text": row_jobs[0].text,
            })
        parts = [
            "Translate each item.text from its source_language into every language in its targets.",
            "Preserve placeholders, tags, punctuation and line breaks exactly.",
            "Reply with only a JSON object mapping each id to an object of target_language -> translation.",
            'Shape: {"1": {"chinese": "\\u5200", "russian": "\\u041d\\u043e\\u0436"}}',
        ]
        if glossary_entries:
            parts.append("Glossary (use these for matching terms):")
            parts.append(json.dumps({"glossary": glossary_entries}, ensure_ascii=False))
        parts.append("Items:")
        parts.append(json.dumps(items, ensure_ascii=False))
        return "\n".join(parts)
```

`_build_job_batch_prompt(jobs, assigned=None)` 直接委托：`self.build_merged_prompt(assigned or assign_batch_ids(jobs))`。`translate_job_batch` 改为：

```python
    def translate_job_batch(self, jobs, assigned=None):
        """返回 {id: {target_language: translation}}。

        jobs 与 assigned 二选一：只给 jobs 时在这里分配 id；服务层会传入已分配的
        assigned，以保证补发时 id 不变。
        """
        if not jobs and not assigned:
            return {}
        assigned = assigned or assign_batch_ids(jobs)
        payload = { ... "messages": [{"role": "user", "content": self.build_merged_prompt(assigned, glossary_entries)}] ... }
        response = self.post_json(url, headers, payload)
        return parse_numbered_translations(self._extract_content(response))
```

（三个 translator 共用同一实现，`ClaudeMessagesTranslator` / `CodexResponsesTranslator` 不再各写一份 `_build_job_batch_prompt`。）

- [x] **Step 4: 实现带编号解析与截断抢救**

```python
def salvage_truncated_object(text):
    """从被腰斩的 JSON 对象里救出最后一个完整的键值对。"""
    text = text.strip()
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escaped = False
    last_complete = -1
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 1:
                last_complete = index
            elif depth == 0:
                return text[start:index + 1]
    if last_complete < 0:
        return text
    return text[start:last_complete + 1] + "}"


def parse_numbered_translations(content):
    """解析 {"1": {"chinese": "刀"}} 形状的回复。被腰斩时尽力抢救。"""
    content = content.strip()
    if content.startswith("```"):
        content = OpenAICompatibleTranslator._strip_code_fence_static(content)
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        salvaged = salvage_truncated_object(content)
        if salvaged == content:
            raise TranslationRequestError(f"AI response was not JSON: {content}")
        try:
            payload = json.loads(salvaged)
        except json.JSONDecodeError as exc:
            raise TranslationRequestError(f"AI response was not JSON: {content}") from exc
    if not isinstance(payload, dict):
        raise TranslationRequestError(f"AI response must be a JSON object: {content}")
    parsed = {}
    for raw_id, value in payload.items():
        try:
            item_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        cleaned = {str(lang): text for lang, text in value.items() if isinstance(text, str)}
        if cleaned:
            parsed[item_id] = cleaned
    return parsed
```

> `parse_numbered_translations` 必须是**模块级函数**。上一版把它缩进成了 `salvage_truncated_object` 的嵌套函数、还放在 `return` 之后 —— 那段代码永不执行，`OpenAICompatibleTranslator.parse_numbered_translations` 根本不存在。

- [x] **Step 5: 实现缺失补发**

```python
    def _missing_assigned(self, assigned, parsed):
        """返回 id → 该行仍缺译文的那部分 job。id 沿用 assigned，不重新编号。"""
        missing = {}
        for item_id, row_jobs in assigned.items():
            got = parsed.get(item_id) or {}
            lack = [job for job in row_jobs if job.target_code not in got]
            if lack:
                missing[item_id] = lack
        return missing

    def _store_parsed_results(self, assigned, parsed, results, provider):
        for item_id in sorted(assigned):
            row_jobs = assigned[item_id]
            got = parsed.get(item_id) or {}
            for job in row_jobs:
                value = got.get(job.target_code)
                if not isinstance(value, str) or not value:
                    results.failed += 1
                    results.errors.append(
                        f"row {job.row} column {job.column}: missing {job.target_code} translation"
                    )
                    continue
                results.translated += 1
                results.cell_results[(job.row, job.column)] = value
                self.cache[self._openai_cache_key(job, provider)] = value

    def _translate_one_openai_batch(self, translator, batch, results, provider):
        assigned = assign_batch_ids(batch)          # 唯一一次编号
        try:
            parsed = translator.translate_job_batch(batch, assigned=assigned)
            missing = self._missing_assigned(assigned, parsed)
            if missing:
                # 只补发缺的，不拆批（决定 8 / 18）。
                # 注意：missing 的 key 就是 assigned 的 key，绝不重新编号。
                retry_parsed = translator.translate_job_batch(
                    [job for jobs in missing.values() for job in jobs],
                    assigned=missing,
                )
                for item_id, langs in retry_parsed.items():
                    parsed.setdefault(item_id, {}).update(langs)
        except TranslationCancelled:
            raise
        except TranslationRequestError as exc:
            self._record_failed_jobs(batch, results, exc)
            raise                    # 保留 Task 3 的异常契约：让闸门看到限速信号
        except Exception as exc:
            self._record_failed_jobs(batch, results, exc)
            return
        self._store_parsed_results(assigned, parsed, results, provider)
```

删除 `_store_job_results`（其「数量不符就抛 `RuntimeError`」已由缺失补发取代）。

- [x] **Step 6: 提高回复上限（决定 19）**

`ClaudeMessagesTranslator` 的两处 `"max_tokens": 4096`（`translate_batch` 与 `translate_job_batch`）改为 `8192`。

`OpenAICompatibleTranslator` 与 `CodexResponsesTranslator` 的 payload **不加** `max_tokens` —— 它们本来就没有这个字段，OpenAI 的 Chat Completions 与 Responses API 都允许省略（省略即用模型默认）。上一版要求「先试 8192，失败再去掉重发一次」，那是一个无法测试的脆弱分支，已删除。

- [x] **Step 7: 修正既有测试的假 translator 与断言**

- `test_openai_translator_includes_glossary_in_job_batch_prompt`（`:419`）与 `test_openai_translator_job_batch_prompt_contains_target_language`（`:408` 附近）：
  - 断言从 `result == ["Messer", "Нож"]` 改为 `result == {1: {"de": "Messer", "ru": "Нож"}}`（同一行两个目标语言现在共用一个 id）。
  - 提示词断言从 `'"target_language": "de"'` 改为 `'"targets": ["de", "ru"]'`。
  - 假 `post_json` 的返回值从 `json.dumps(["Messer"])` 改为 `json.dumps({"1": {"de": "Messer", "ru": "Нож"}})`。
- `test_translate_jobs_marks_cancelled_on_translation_cancelled`（`:502`）里的 `CancellingTranslator` 必须实现新签名，否则改名/改签名后 `AttributeError` 会被 `except Exception` 吞掉，`results.cancelled` 变 False：
  ```python
            def translate_job_batch(self, jobs, assigned=None):
                raise TranslationCancelled()
  ```
- 其余实现 `translate_job_batch` 的假 translator（`:74` / `:134` / `:450`）同样补 `assigned=None` 参数，并把返回值改成 `{id: {lang: text}}` 形状。

- [x] **Step 8: 运行测试**

```bash
python -m unittest tests.test_translator_service -v
```
预期：全绿。

- [x] **Step 9: Commit**

```bash
git add translator_service.py tests/test_translator_service.py
git commit -m "feat: merge a row's target languages into one request with stable id-keyed replies"
```

---

### Task 6: 术语表只带命中的条目

**Files:**
- Modify: `translator_service.py` — 新增 `matching_glossary_entries`；`build_merged_prompt` 调用它；三个 translator 使用 `self.glossary_source_key`
- Modify: `main.py` — `create_translation_worker` 传 `glossary_source_key`
- Test: `tests/test_translator_service.py`

**Interfaces:**
- Produces: `matching_glossary_entries(glossary, texts, source_key="", max_entries=GLOSSARY_MAX_ENTRIES) -> list[dict]`
- Consumes: `TranslatorConfig.glossary_source_key`
- 移除：`GLOSSARY_SOURCE_KEY` 常量（硬编码 `original` 是错的）

> **为什么源词键不是硬编码的 `original`（决定 21）**：`dayz_csv.LANGUAGE_CODES["original"] == "auto"` —— `original` 列不是一种语言，是「自动检测」。而单词本（`wordbook_csv.WORDBOOK_HEADERS`）用的列名与 stringtable **完全相同**（`original` / `english` / `czech` / …），且 `main.py` 里 `self.source_header`（默认 `"english"`）本来就是那个列名。所以正确做法是直接用**当前源列名**去取源词，不需要任何映射表：源列是 `english` 就查 `entry["english"]`，源列是 `original` 就查 `entry["original"]`。

- [x] **Step 1: 写失败测试**

`GlossaryFilterTests`：
- `test_only_matching_entries_included`：术语表 3 条，本批文本只含其中 1 条的源词 → 只返回那 1 条。
- `test_match_is_case_insensitive`：文本 `"KNIFE"` 命中源词 `"knife"`。
- `test_no_match_returns_empty`：无命中 → 空列表（提示词里不出现 Glossary 段）。
- `test_uses_the_given_source_column`：术语表 `{"english": "Knife", "german": "Messer"}`，`source_key="english"` → 命中；`source_key="german"` 而文本是 `"Knife"` → **不**命中。（这是硬编码 `original` 那个 bug 的回归闸门。）
- `test_source_key_missing_from_entry_is_skipped`：条目里没有 `source_key` 那一列 → 跳过。
- `test_empty_source_key_matches_any_column`：`source_key=""` 时退化为「任一词条列命中即可」（直接构造 translator 的测试用得到）。
- `test_respects_max_entries`：命中 300 条、`max_entries=200` → 返回 200 条。

`GlossaryPromptIntegrationTests`：
- `test_translator_uses_config_source_key`：`TranslatorConfig(provider="openai", glossary_source_key="english", glossary=[...])` 经 `create_provider` 造出的 translator，`glossary_source_key == "english"`。

- [x] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_translator_service.GlossaryFilterTests -v
```

- [x] **Step 3: 实现**

```python
def matching_glossary_entries(glossary, texts, source_key="", max_entries=GLOSSARY_MAX_ENTRIES):
    """只挑本批文本里真的出现了源词的术语条目（决定 7）。

    每次请求都带完整单词本时，几百条术语会在每条请求里白花一遍 token。

    source_key 是**当前源列名**（`main.py` 的 `self.source_header`，如 "english"），
    与 `wordbook_csv.WORDBOOK_HEADERS` 同名，因此可以直接取源词。
    传空则退化为「任一词条列命中即可」。
    """
    if not glossary or not texts:
        return []
    haystack = "\n".join(texts).lower()
    key = (source_key or "").strip().lower()
    matched = []
    for entry in glossary:
        if not isinstance(entry, dict):
            continue
        if key:
            candidates = [entry.get(key)]
        else:
            candidates = list(entry.values())
        hit = False
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value and value.lower() in haystack:
                hit = True
                break
        if hit:
            matched.append(entry)
            if len(matched) >= max_entries:
                break
    return matched
```

`translate_job_batch` 里：

```python
        glossary_entries = matching_glossary_entries(
            self.glossary,
            [row_jobs[0].text for row_jobs in assigned.values()],
            self.glossary_source_key,
        )
```

术语表放在 **Items 之前**（变动区），系统提示保持稳定在最前 —— 这样 OpenAI 的自动前缀缓存至少能命中系统提示，Anthropic 在 system 块上加 `cache_control`：

```python
        payload["system"] = [
            {
                "type": "text",
                "text": "You are a translation engine. Reply with only a JSON object, no prose.",
                "cache_control": {"type": "ephemeral"},
            }
        ]
```

（仅 `ClaudeMessagesTranslator`。`OpenAICompatibleTranslator` 与 `CodexResponsesTranslator` 保持纯字符串 system，靠 OpenAI 的自动前缀缓存。）

`main.py` 的 `create_translation_worker` 里 `TranslatorConfig(...)` 补：

```python
                glossary=self.wordbook_glossary(),
                glossary_source_key=(self.source_header or "").strip().lower(),
```

- [x] **Step 4: 修正既有测试**

`test_openai_translator_includes_glossary_in_job_batch_prompt`（`:419`）现在**不需要改数据**（它直接构造 translator，`glossary_source_key` 默认 `""` → 走「任一列」回退，`{"english": "Knife", ...}` 照样命中），但提示词形状断言要跟着 Task 5 一起改。若想让它更贴近真实路径，可显式传 `glossary_source_key="english"`。

- [x] **Step 5: 运行测试**

```bash
python -m unittest tests.test_translator_service -v
```
预期：全绿。

- [x] **Step 6: Commit**

```bash
git add translator_service.py main.py tests/test_translator_service.py
git commit -m "feat: send only glossary entries that match the batch text"
```

---

### Task 7: UI 接线

**Files:**
- Modify: `translation_worker.py` — 新增 `retrying` 信号
- Modify: `main.py` — import、设置对话框、缓存接线、倒计时、只重跑失败项、UI 文案、默认并发值
- Test: `tests/test_main_gui.py`

**Interfaces:**
- Produces: `TranslationWorker.retrying = Signal(int, int, int)`（attempt, max_attempts, wait_seconds）
- Produces: `DayzTranslateTool.on_translation_retrying(attempt, max_attempts, wait_seconds) -> None`
- Produces: `DayzTranslateTool.retry_failed_cells() -> None`
- Produces: `DayzTranslateTool.clear_translation_cache() -> None`
- Produces: `DayzTranslateTool.translation_char_budget: int`（默认 `DEFAULT_CHAR_BUDGET`）
- Produces: `DayzTranslateTool.translation_auto_concurrency: bool`（默认 True）
- 移除：`DayzTranslateTool.translation_batch_size`（语义已由 `translation_char_budget` 取代）
- Consumes: `TranslationCacheStore.clear()`

- [x] **Step 0: 补 import（本修订版问题 5）**

`main.py` 顶部的 `from translator_service import ...`（现为 `TranslationJob, TranslationService, TranslatorConfig, normalize_provider, validate_translator_config`）补上新常量：

```python
from translator_service import (
    DEFAULT_CHAR_BUDGET,
    MAX_AUTO_CONCURRENCY,
    MAX_CHAR_BUDGET,
    MIN_CHAR_BUDGET,
    TranslationJob,
    TranslationService,
    TranslatorConfig,
    normalize_provider,
    validate_translator_config,
)
```

> 上一版计划让 `main.py` 直接用 `DEFAULT_CHAR_BUDGET` / `MAX_CHAR_BUDGET` / `MAX_AUTO_CONCURRENCY` / `MIN_CHAR_BUDGET` 却从未 import，运行期必 `NameError`。

- [x] **Step 1: 写失败测试**

`tests/test_main_gui.py` 新增：
- `test_settings_dialog_char_budget_range`：`batch_size_input` 的 `minimum() == MIN_CHAR_BUDGET`、`maximum() == MAX_CHAR_BUDGET`、默认值 `DEFAULT_CHAR_BUDGET`。
- `test_settings_dialog_concurrency_cap_range`：`parallel_batches_input.maximum() == MAX_AUTO_CONCURRENCY`，且存在 `auto_concurrency_check`（默认勾选）。
- `test_settings_dialog_has_clear_cache_button`：存在 `clear_cache_button`。
- `test_clear_cache_empties_memory_and_disk`：写入一条缓存 → 点按钮 → `window.translation_cache == {}` 且 `store.load() == {}`。
- `test_legacy_preset_batch_size_migrates_to_default`：`apply_translation_settings_dict({"batch_size": 30})` → `translation_char_budget == DEFAULT_CHAR_BUDGET`（30 是旧版「行数」，必须当成旧值）。
- `test_parallel_batches_default_is_three`：全新 settings 下 `window.translation_parallel_batches == 3`（决定 22）。
- `test_retry_countdown_shown_and_cleared`：调用 `on_translation_retrying(1, 5, 12)` → 进度标签文本含 `12` 与 `1/5`；再调用 `update_translation_progress` 后文本恢复为 `已完成/总数`。
- `test_retry_failed_cells_rebuilds_only_failed_jobs`：构造 `results.cell_results` 与失败集合，调用 `retry_failed_cells()` → 传给 worker 的 jobs 恰好是失败的那些单元格。

- [x] **Step 2: 运行测试确认失败**

```bash
python -m unittest tests.test_main_gui -v
```
预期：`AttributeError`。

- [x] **Step 3: worker 增加重试信号**

```python
class TranslationWorker(QObject):
    progress = Signal(object)
    retrying = Signal(int, int, int)
    finished = Signal(object)
    failed = Signal(str)
```

`run()` 里把 `on_retry` 接上：`self.service.on_retry = self.retrying.emit`，再调用 `translate_jobs`。

- [x] **Step 4: 设置对话框原地替换**

`TranslationSettingsDialog.__init__`：

```python
        self.batch_size_input = QSpinBox(self)
        self.batch_size_input.setRange(MIN_CHAR_BUDGET, MAX_CHAR_BUDGET)   # 200..100000（决定 20）
        self.batch_size_input.setSingleStep(500)
        self.batch_size_input.setValue(window.translation_char_budget)

        self.auto_concurrency_check = QCheckBox(window.tr("auto_concurrency"), self)
        self.auto_concurrency_check.setChecked(window.translation_auto_concurrency)

        self.parallel_batches_input = QSpinBox(self)
        self.parallel_batches_input.setRange(1, MAX_AUTO_CONCURRENCY)   # 1..8
        self.parallel_batches_input.setToolTip(window.tr("concurrency_cap_tooltip"))
        self.parallel_batches_input.setValue(window.translation_parallel_batches)
```

> `parallel_batches_input.setToolTip(...)` 这行**必须留**：既有测试 `test_translation_settings_batch_and_parallel_have_tooltips`（`tests/test_main_gui.py:379`）断言的是 `parallel_batches_input.toolTip()`，不是标签的 tooltip。

`form_rows` 的键名保持 `batch_size` / `parallel_batches`（预设兼容），但标签文案换成新键 `char_budget` / `concurrency_cap`。同时把 `UI_TEXT` 里已经没人用的 `"batch_size"` / `"batch_size_tooltip"` 两条（`main.py:94,96` 与 `:188,190`）删掉，避免留一份说「Rows Per Batch」的旧文案误导后续维护。`"parallel_batches"` / `"parallel_batches_tooltip"` 保留（控件 tooltip 仍然用它们，见 `:504`）。

`parallel_batches` 那一行要放两个控件，**不能走 `add_form_row`** —— 它的实现是 `widget.setToolTip(tooltip)` + `form_rows[key] = (label, widget)`（`main.py:541-547`），传 list 会在 `setToolTip` 上崩（`add_form_row` 对 tooltip 有 `if tooltip:` 守卫，所以只有真传了 tooltip 才会崩）。照 `preset` 那一行的既有写法手动建行（`main.py:496-501`）：

```python
        cap_label = QLabel(window.tr("concurrency_cap"), self)
        cap_label.setToolTip(window.tr("concurrency_cap_tooltip"))
        cap_layout = QHBoxLayout()
        cap_layout.setContentsMargins(0, 0, 0, 0)
        cap_layout.addWidget(self.auto_concurrency_check)
        cap_layout.addWidget(self.parallel_batches_input)
        cap_layout.addStretch(1)
        form.addRow(cap_label, cap_layout)
        self.form_rows["parallel_batches"] = (cap_label, self._layout_widgets(cap_layout))
```

（`_layout_widgets` 在 `main.py:533`。`is_field_visible` 已经能处理 list 形式的 widget；`parallel_batches` 不在任何 `PROVIDER_FIELD_KEYS` 集合里，所以 `update_visible_fields` 不会碰它，始终可见。）

`clear_cache_button` 那一行走普通 `add_form_row` 即可（单个 widget）：

```python
        self.clear_cache_button = QPushButton(window.tr("clear_translation_cache"), self)
        self.clear_cache_button.clicked.connect(self.clear_translation_cache)
        self.add_form_row(form, "clear_cache", window.tr("translation_cache"), self.clear_cache_button)
```

**不要动 `_get_field_value` / `_set_field_value`** —— 它们只映射 provider 凭据字段（`api_key`/`region`/`model`/`base_url`/`email`，`main.py:599-620`），`batch_size` 与 `parallel_batches` 从来不走它们。真正的读写路径是：

- **读**：对话框 `__init__` 直接 `setValue(window.translation_*)`（`main.py:464-470`）
- **写**：对话框 `apply_settings` 直接赋值（`main.py:641-644`）

所以在 `apply_settings` 里：

```python
        self.window.translation_provider = provider
        self.window.translation_char_budget = self.batch_size_input.value()
        self.window.translation_parallel_batches = self.parallel_batches_input.value()
        self.window.translation_auto_concurrency = self.auto_concurrency_check.isChecked()
        self.window.translation_timeout = float(self.timeout_input.value())
```

（即把原来的 `translation_batch_size` 一行**换成** `translation_char_budget`，并新增 `translation_auto_concurrency`。`translation_parallel_batches` 那一行原样保留，不要删。）

- [x] **Step 5: 设置持久化、默认值与旧值迁移**

这些是**普通属性**（不是 property），在 `DayzTranslateTool.__init__` 里从 settings 读（`main.py:1288-1291`）：

```python
        self.translation_provider = normalize_provider(self.settings.value("translation_provider", "google"))
        self.translation_parallel_batches = int(self.settings.value("translation_parallel_batches", 3))   # 决定 22：1 → 3
        self.translation_timeout = float(self.settings.value("translation_timeout", 60.0))
```

删掉 `translation_batch_size` 那行，改为：

```python
        # 旧版本的 translation_batch_size 存的是「行数」（默认 30），语义已变成「字数」。
        # 这里只认新键；旧键由 apply_translation_settings_dict 的迁移分支接住。
        # 刻意不做下限钳制：预设里可能存着低于 UI 下限的历史值，钳制会造成
        # 「存 12 读回 1500」这种静默改写（test_translation_settings_loads_full_preset 靠这一点）。
        self.translation_char_budget = int(
            self.settings.value("translation_char_budget", DEFAULT_CHAR_BUDGET)
        )
        self.translation_auto_concurrency = str(
            self.settings.value("translation_auto_concurrency", "true")
        ).lower() in ("true", "1", "yes")
```

**同步八处，不是一个「四处」。** `batch_size` 这个名字散落在对话框与主窗口两条独立的预设链路上，只改一半就会出现「对话框存 `char_budget`、主窗口读 `batch_size`」的静默不生效：

**对话框侧（`TranslationSettingsDialog`）**

1. `_read_preset_values`（`main.py:801`）的 `preset_keys` 列表：把 `"batch_size"` 换成 `"char_budget"`，并在末尾**追加** `"batch_size"`（为了读旧预设），再追加 `"auto_concurrency"`
2. `_apply_preset_values_to_dialog`（`main.py:809-811`）的读取分支：按下面的迁移规则改
3. `current_field_values`（`main.py:832`）的返回字典：`"batch_size"` 换成 `"char_budget"`（值改成 `self.batch_size_input.value()`），加 `"auto_concurrency"`

**主窗口侧（`DayzTranslateTool`）**

4. `save_translation_settings`（`main.py:1780` 附近）把 `setValue("translation_batch_size", ...)` 换成 `setValue("translation_char_budget", self.translation_char_budget)`，并加 `setValue("translation_auto_concurrency", self.translation_auto_concurrency)`
5. `current_translation_settings_dict`（`main.py:1789-1800`）：`"batch_size"` 换成 `"char_budget"`（值 `self.translation_char_budget`），加 `"auto_concurrency"`
6. `apply_translation_settings_dict`（`main.py:1802-1813`）：`batch_size` 分支换成 `char_budget` 分支，**并保留**对旧键 `batch_size` 的读取（迁移规则见下）
7. `load_translation_preset` 的 `preset_keys`（`main.py:1854`）：同 1（换成 `char_budget` + 追加旧键 `batch_size` + 加 `auto_concurrency`）
8. `__init__` 的默认值读取（`main.py:1289` 附近）：见上面已给的那段代码

**统一的旧值迁移规则**（写在两个 apply 函数里，两处必须一致）：

```python
        # 旧键 batch_size 存的是「行数」（默认 30），新键 char_budget 是「字数」。
        # 旧值 30 落在新区间里，直接拿来用就会被当成「每批 30 个字」—— 一律换成默认值。
        char_budget = values.get("char_budget")
        if char_budget is None or char_budget == "":
            legacy = values.get("batch_size")
            if legacy is not None and legacy != "":
                char_budget = DEFAULT_CHAR_BUDGET
        if char_budget is not None and char_budget != "":
            self.translation_char_budget = int(char_budget)
```

（`_apply_preset_values_to_dialog` 里最后一句改为 `self.batch_size_input.setValue(int(char_budget))`。）

> **两条链路对下限的严格程度不同，这是有意的**：对话框链路经 `QSpinBox`，低于 `MIN_CHAR_BUDGET` 的值会被控件夹到 200；主窗口链路直接写属性，不夹。旧预设里的 `batch_size` 会被迁移规则换成 1500，所以正常使用下走不到这个差异。

（预设是 `translation_presets/<name>/<key>` 逐键存的，所以「读旧键」就是多读一个 `settings.value`，不需要写回迁移。）

`create_translation_worker`（`main.py:2398` 附近）改为：

```python
    def create_translation_worker(self, jobs):
        return TranslationWorker(
            # 注入共享缓存：多次翻译运行复用相同内容的翻译结果
            service=TranslationService(cache=self.translation_cache),
            jobs=jobs,
            config=TranslatorConfig(
                provider=self.translation_provider,
                char_budget=self.translation_char_budget,
                auto_concurrency=self.translation_auto_concurrency,
                parallel_batches=self.translation_parallel_batches,
                timeout=self.translation_timeout,
                api_key=self.translation_api_key,
                region=self.translation_region,
                model=self.translation_model,
                base_url=self.translation_base_url,
                email=self.translation_email,
                glossary=self.wordbook_glossary(),
                glossary_source_key=(self.source_header or "").strip().lower(),
            ),
        )
```

- [x] **Step 6: 倒计时显示（决定 9）**

```python
    def create_translation_status_widgets(self):
        ...
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(1000)
        self._retry_timer.timeout.connect(self._tick_retry_countdown)
        self._retry_seconds_left = 0
        self._retry_attempt = 0
        self._retry_max_attempts = 0
```

```python
    def on_translation_retrying(self, attempt, max_attempts, wait_seconds):
        self._retry_seconds_left = max(0, int(round(wait_seconds)))
        self._retry_attempt = attempt
        self._retry_max_attempts = max_attempts
        self._render_retry_label()
        self._retry_timer.start()

    def _tick_retry_countdown(self):
        self._retry_seconds_left -= 1
        if self._retry_seconds_left <= 0:
            self._retry_timer.stop()
            self._retry_seconds_left = 0
        self._render_retry_label()

    def _render_retry_label(self):
        self.translation_progress_label.setText(
            self.tr("retry_countdown",
                    seconds=self._retry_seconds_left,
                    attempt=self._retry_attempt,
                    max_attempts=self._retry_max_attempts)
        )

    def _stop_retry_countdown(self):
        self._retry_timer.stop()
        self._retry_seconds_left = 0
```

在 `update_translation_progress`、`finish_translation`、`fail_translation`、`hide_translation_progress` 开头调用 `self._stop_retry_countdown()`（让批次一恢复就把标签还原成 `已完成/总数`）。

`start_translation_worker` 里连接：`self.translation_worker.retrying.connect(self.on_translation_retrying)`。

UI 文案（`UI_TEXT` 的 en / zh 两份）：

```python
"retry_countdown": "Rate limited — retrying in {seconds}s (attempt {attempt}/{max_attempts})",
"char_budget": "Max chars per batch",
"char_budget_tooltip": "Source characters a single request may carry. Rows are never split across requests. Larger = fewer requests but a bigger loss if one fails.",
"concurrency_cap": "Concurrency cap",
"auto_concurrency": "Auto",
"concurrency_cap_tooltip": "Auto mode starts low, halves on rate limits and climbs back slowly. This is the ceiling it may climb to.",
"translation_cache": "Translation cache",
"clear_translation_cache": "Clear cache",
```

zh：

```python
"retry_countdown": "被限速，{seconds} 秒后重试（第 {attempt}/{max_attempts} 次）",
"char_budget": "每批最多字数",
"char_budget_tooltip": "单次请求最多携带的源文字数。行不会被拆到两个请求里。越大请求越少，但单次失败的代价也越大。",
"concurrency_cap": "并发上限",
"auto_concurrency": "自动",
"concurrency_cap_tooltip": "自动模式起步保守，撞到限速立刻减半，之后慢慢回升。这里是最多能升到几个。",
"translation_cache": "翻译缓存",
"clear_translation_cache": "清空缓存",
```

（`tr()` 用 `text.format(**kwargs)`，见 `main.py:1337`。）

- [x] **Step 7: 只重跑失败项（决定 10）**

`start_translation_worker` 里新增 `self._translation_job_cells = {(row, column) for row, column, _, _ in raw_jobs}`。

`finish_translation` 里记录失败单元格：

```python
        self._translation_failed_cells = {
            key for key in self._translation_job_cells if key not in results.cell_results
        }
```

收尾时，若 `not results.cancelled and self._translation_failed_cells`，弹一个带自定义按钮的提示：

```python
        box = QMessageBox(self)
        box.setWindowTitle(self.tr("translate"))
        box.setText(self.tr("failed_cells_count", count=len(self._translation_failed_cells)))
        retry_button = box.addButton(self.tr("retry_failed_only"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(self.tr("close"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is retry_button:
            self.retry_failed_cells()
```

```python
    def retry_failed_cells(self):
        cells = sorted(self._translation_failed_cells)
        if not cells:
            return
        rows = self.table_rows()
        source_column = self.headers.index(self.source_header)
        jobs = []
        for row_index, column_index in cells:
            row = rows[row_index]
            source_text = row[source_column].strip() if source_column < len(row) else ""
            if not source_text:
                continue
            target_code = language_code_for_header(self.headers[column_index])
            if not target_code:
                continue
            jobs.append((row_index, column_index, source_text, target_code))
        self.run_translation_jobs(jobs, copy_overwrite=False)
```

UI 文案：`"retry_failed_only": "Retry failed only"` / `"只重跑失败项"`，`"failed_cells_count": "{count} cells failed."` / `"有 {count} 个单元格翻译失败。"`。

- [x] **Step 8: 修正既有 GUI 测试**

- `test_translation_settings_dialog_saves_provider_and_parallel_batches`（`tests/test_main_gui.py:362`）：`assertEqual(self.window.translation_batch_size, 40)` → `assertEqual(self.window.translation_char_budget, 40)`。
- `test_translation_settings_loads_full_preset`（`:956`）：`self.window.translation_batch_size = 12` / `= 30` → `self.window.translation_char_budget = 1500` / `= DEFAULT_CHAR_BUDGET`；断言 `translation_batch_size == 12` → `translation_char_budget == 1500`。
  > 注意：`12 < MIN_CHAR_BUDGET`，所以它会被迁移成默认值 —— 这正是 `test_legacy_preset_batch_size_migrates_to_default` 要断言的行为，两个测试必须一致。
- `test_translation_settings_batch_and_parallel_have_tooltips`（`:379`）：**不用改**，但 Task 7 Step 4 必须给 `parallel_batches_input` 设 tooltip 才能过。

- [x] **Step 9: 运行测试**

```bash
python -m unittest tests.test_main_gui tests.test_translation_worker -v
```
预期：全绿。

- [x] **Step 10: Commit**

```bash
git add main.py translation_worker.py tests/test_main_gui.py
git commit -m "feat: expose char budget, auto concurrency, cache clearing and retry countdown in settings"
```

---

### Task 8: 全量验证

- [x] **Step 1: 跑全部测试**

```bash
python -m unittest discover -s tests -v
```
预期：全绿。

- [x] **Step 2: 静态检查**

```bash
python -m py_compile main.py translator_service.py translation_worker.py translation_cache.py
```

- [x] **Step 3: 手工冒烟（Google 免费线路）**

1. 启动 `python main.py`，打开一个 `stringtable.csv`。
2. 「翻译设置」里确认：每批最多字数 1500、自动勾选、并发上限 3、清空缓存按钮存在。
3. 对 20 行跑一次「翻译选中行」，确认进度正常、结果写入。
4. 关闭软件再打开，对同样 20 行再跑一次 —— 状态栏应显示大量「缓存命中」，且**不应产生新的网络请求**（可用抓包或临时在 `_post_json` 打点确认）。
5. 点「清空缓存」，再跑一次，确认重新发起请求。

- [x] **Step 4: 手工冒烟（限速路径）**

1. 把「每批最多字数」临时设为 100000、并发上限设为 8，对整表跑一次，制造并发压力。
2. 观察进度标签是否出现「被限速，N 秒后重试（第 x/5 次）」倒计时。
3. **确认并发真的降下来了**：在 `AdaptiveGate.release` 里临时打一行 `print(self._limit, rate_limited)`，撞限速后应看到 `limit` 减半（这是本修订版问题 2 的端到端验证 —— 上一版这里永远是 `1` 个线程，看不出降速）。
4. 倒计时期间点「取消」—— 应在 1 秒内停止，且不弹异常。
5. 若有格子最终失败，确认弹出「只重跑失败项」按钮；点击后只重跑失败的那些格子。

- [x] **Step 5: 术语表端到端验证（本修订版问题 14）**

1. 打开单词本，填一行 `english=Knife` / `german=Messer`。
2. 源列选 `english`，对含 `Knife` 的行跑一次翻译。
3. 在 `build_merged_prompt` 里临时打点，确认提示词里**出现了** Glossary 段且含 `Knife`。
4. 换成不含任何术语的行再跑，确认 Glossary 段**不出现**。

- [x] **Step 6: 更新 README / 说明（可选）**

若 `README` 或 `docs/` 里描述了「每批次行数」的旧语义，同步更新为「每批最多字数」。

---

## 既有测试的同步修改（汇总，必须一起改）

本计划刻意改变了几处行为，对应测试必须跟着改 —— 否则套件不绿，而计划声称全绿就是错的。

| 测试 | 文件:行 | 为什么挂 | 怎么改 |
|---|---|---|---|
| `test_cache_miss_when_glossary_changes` | `test_translator_service.py:156` | 决定 6：术语表不再进缓存键，`cache_hits` 从 0 变 1 | 改名 `test_cache_hit_when_glossary_changes`，断言 `== 1` |
| `test_batch_size_groups_jobs_by_row_count` | `test_translator_service.py:47` | Task 4 改按字数分批 | 改用 `TranslatorConfig(char_budget=...)` 表达同一场景 |
| `test_batch_size_rows_groups_multi_target_per_row` | `test_translator_service.py:66` | 同上 | 同上 |
| `test_openai_provider_uses_base_url` 的 `FakeOpenAITranslator` | `test_translator_service.py:71,318,447` | `create_provider` 多传 `retry_policy`/`on_retry` → `TypeError` | 三处假构造器都补 `glossary_source_key=""` / `retry_policy=None` / `on_retry=None` / `before_attempt=None` |
| `test_openai_translator_job_batch_prompt_contains_target_language` | `test_translator_service.py:408` | 返回值从位置数组改成 id 字典；提示词从 `target_language` 改成 `targets` | 断言 `{1: {"de": ..., "ru": ...}}` 与 `'"targets": ["de", "ru"]'` |
| `test_openai_translator_includes_glossary_in_job_batch_prompt` | `test_translator_service.py:419` | 同上（数据本身仍命中，靠「任一列」回退） | 同上 |
| 三处 `translate_job_batch` 假实现 | `test_translator_service.py:73,134,449` | 新签名多一个 `assigned=None`；返回值从 `list[str]` 改成 `{id: {lang: text}}` | 补参数、改返回形状 |
| `test_translate_jobs_marks_cancelled_on_translation_cancelled` 的 `CancellingTranslator` | `test_translator_service.py:507` | `AttributeError` 会被 `except Exception` 吞掉，`cancelled` 变 False | `def translate_job_batch(self, jobs, assigned=None)` |
| `test_default_translation_provider_is_google` | `test_main_gui.py:121` | 断言 `translation_parallel_batches == 1`，而决定 22 把默认值改成 3 | 断言改为 `== 3` |
| `test_translation_settings_dialog_saves_provider_and_parallel_batches` | `test_main_gui.py:363` | `translation_batch_size` 已删除 | `:374` 断言改为 `translation_char_budget == 40`（`:373` 的 `parallel_batches == 3` 保持不变） |
| `test_translation_settings_loads_full_preset` | `test_main_gui.py:956` | `translation_batch_size` 已删除（`:958`/`:968`/`:979`） | 改用 `translation_char_budget`；`:958` 存 12、`:979` 断言 `== 12`（不钳制，所以 12 原样读回） |
| 20 余处 `TranslationService(batch_size=...)` | `test_translator_service.py` | Task 4 删除该参数 | Task 4 Step 4 的 sed 扫描 |

`test_translation_settings_batch_and_parallel_have_tooltips`（`test_main_gui.py:379`）**不用改**，但它要求 Task 7 Step 4 给 `parallel_batches_input` 本身设 tooltip。

## Self-Review

**Spec coverage** — 22 条决定逐条落位：

| 决定 | 落在哪 |
|---|---|
| 1 谷歌与 AI 两条线 | Task 3 Step 4（`provider == "google"` 用 `GOOGLE_MIN_INTERVAL`，AI 用 0） |
| 2 自动等待重试 | Task 2 |
| 3 缓存存硬盘 | Task 1 |
| 4 自动并发 + 上限旋钮 | Task 3 `AdaptiveGate` + Task 7 Step 4 |
| 5 按内容长度分批 | Task 4 |
| 6 换模型作废 / 改单词本不作废 / 清空按钮 | Task 1 Step 4 + Task 7 Step 4 |
| 7 术语表只带命中 | Task 6 |
| 8 重试不拆批 | Task 5 Step 5（补发只发缺失项，不二分） |
| 9 倒计时 + 立即停止 | Task 2 `interruptible_sleep` + Task 7 Step 6 |
| 10 只重跑失败项 | Task 7 Step 7 |
| 11 多语言合并、源文只出现一次 | Task 5 Step 3 |
| 12 谷歌单独限速 | Task 3 Step 4 |
| 13 不显示统计面板 | 无对应实现（刻意不做；`self.stats` 已删除） |
| 14 最多 5 次、单次最多 60s | 常量 `RETRY_MAX_ATTEMPTS` / `RETRY_MAX_DELAY` |
| 15 缓存放软件目录旁、不限大小 | Task 1 Step 3 `_resolve_path` |
| 16 降速后慢慢回升 | Task 3 `AdaptiveGate.release` |
| 17 交付物 = 计划 + 测试 | 本文件 + 各 Task 的测试 |
| 18 带编号返回、只补发缺失 | Task 5 Step 3/4/5 |
| 19 调高回复上限 + 按产出量封批 | Task 5 Step 6 + `DEFAULT_OUTPUT_CHAR_CAP` |
| 20 上限 100000、默认 1500 | Task 7 Step 4 + `MAX_CHAR_BUDGET` / `DEFAULT_CHAR_BUDGET` |
| 21 术语表按源语言列匹配 | Task 6 |
| 22 自动并发默认值 1 → 3 | Task 7 Step 5 |

**已知取舍（需在实现时如实处理，不得掩盖）**

- 缓存键去掉术语表后，改单词本不会让已有译文失效 —— 个别句子可能仍用旧术语。用户已接受，靠「清空缓存」按钮手动纠正。
- 「只带命中的术语」让术语表内容随批次变化，削弱了提示词前缀缓存的收益；可缓存的只剩系统提示。这是用户在 Q7 明确选择的取舍。
- 字符数不是 token 数，中英混排下预算会有偏差；不引入 `tiktoken` 是刻意选择（零新依赖）。
- 自动模式的并发上限是**用户设的 `parallel_batches`**（决定 22 后默认 3），不是 `MAX_AUTO_CONCURRENCY`（8）；8 只是旋钮的取值上限。自动模式起步 `DEFAULT_AUTO_CONCURRENCY`（2），因此默认配置下的实际区间是 2..3 —— 升幅有限，是「默认 3」这个决定的直接后果。
- 限速等待期间批次仍占着闸门的一个名额，所以「闸门减半」与「批次卡在退避里」会叠加降速。方向上符合决定 16（更保守），但实际吞吐会比 `limit` 数字看起来更低。
- 术语表匹配用 `entry.get(source_key)` 精确取列；若单词本里同一语言的列名与源列名不同（例如源列 `chinesesimp` 而单词本只填了 `chinese`），该条目不会被命中。这是「按源列匹配」的必然结果，不做模糊回退。
- **`mymemory` / `deepl` / `microsoft` 三个 provider 没有重试与节流。** 它们直接实例化 deep-translator 的类（`create_provider` `:70-84`），本计划不改造它们 —— 既没给它们传 `retry_policy`，也没给它们包 `_guarded`。它们的失败仍按旧行为计入 `results.failed`。若要覆盖，需要在 `create_provider` 里把它们包一层，属于后续工作。
- **Google 线路的 `translate_batch` 是「一个请求带 N 条 `q`」**，所以对 Google 而言「减少请求数」靠的是别拆太多批，而不是合并语言 —— 合并多语言（Task 5）只对 AI 线路生效。
