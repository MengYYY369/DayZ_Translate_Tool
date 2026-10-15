import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import mktime_tz, parsedate_tz

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

# 部分第三方网关会拦掉 Python 默认的 User-Agent（实测 B 站 Index-Translate 返回 412），
# AI 源统一带上自己的名字。
AI_USER_AGENT = "DayZ-Translate-Tool/1.0"

# —— 限速与重试（决定 9 / 12 / 14）——
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 2.0
RETRY_MAX_DELAY = 60.0
RETRYABLE_STATUS = frozenset({408, 409, 413, 429, 500, 502, 503, 504})
FATAL_STATUS = frozenset({400, 401, 403, 404, 422})
RATE_LIMIT_STATUS = frozenset({429, 503})   # 命中即让自适应闸门减半

# —— 术语表（决定 7 / 21）——
GLOSSARY_MAX_ENTRIES = 200


class TranslationCancelled(Exception):
    """Raised when a translation run is cancelled via should_cancel."""


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
                return True  # 超时 / 连接断 / URLError
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
    这样「重试」也受同一个最小间隔约束，不会出现「撞了限速反而连发」。
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


class RateLimiter:
    """全局最小请求间隔。线程安全，纯标准库（决定 12）。"""

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
            # 只在「真的被挡住」时查取消：调用方在提交每个批次之前已经查过一次，
            # 这里再查一遍纯属多余，且会把「取消检查次数」这种脆弱断言弄乱。
            while self._active >= self._limit:
                if should_cancel and should_cancel():
                    raise TranslationCancelled()
                self._cond.wait(0.2)
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


@dataclass(frozen=True)
class TranslationJob:
    row: int
    column: int
    text: str
    source_code: str
    target_code: str


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


@dataclass
class TranslationResults:
    translated: int = 0
    skipped: int = 0
    failed: int = 0
    cache_hits: int = 0
    cell_results: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    cancelled: bool = False


class TranslationService:
    def __init__(self, provider_factory=None, should_cancel=None, cache=None):
        self.provider_factory = provider_factory or self.create_provider
        # cache 允许外部注入：多次翻译运行共享同一个字典即可复用相同内容的翻译结果
        self.cache = cache if cache is not None else {}
        self.cache_namespace = ""
        self.should_cancel = should_cancel
        self.retry_policy = RetryPolicy()
        self.on_retry = None
        self.rate_limiter = None
        self.gate = None
        self.openai_translator_class = OpenAICompatibleTranslator
        self.free_translator_classes = None      # None = 用 free_translators 的注册表
        self.claude_translator_class = ClaudeMessagesTranslator
        self.codex_translator_class = CodexResponsesTranslator

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
        if provider == "openai":
            return self.openai_translator_class(
                source=source,
                target=target,
                api_key=config.api_key,
                model=config.model or "gpt-3.5-turbo",
                base_url=config.base_url,
                glossary=config.glossary,
                glossary_source_key=config.glossary_source_key,
                timeout=config.timeout,
                should_cancel=self.should_cancel,
                retry_policy=self.retry_policy,
                on_retry=self.on_retry,
                before_attempt=self._throttle,
            )
        if provider == "claude":
            return self.claude_translator_class(
                source=source,
                target=target,
                api_key=config.api_key,
                model=config.model or self.claude_translator_class.DEFAULT_MODEL,
                base_url=config.base_url,
                glossary=config.glossary,
                glossary_source_key=config.glossary_source_key,
                timeout=config.timeout,
                should_cancel=self.should_cancel,
                retry_policy=self.retry_policy,
                on_retry=self.on_retry,
                before_attempt=self._throttle,
            )
        if provider == "codex":
            return self.codex_translator_class(
                source=source,
                target=target,
                api_key=config.api_key,
                model=config.model or self.codex_translator_class.DEFAULT_MODEL,
                base_url=config.base_url,
                glossary=config.glossary,
                glossary_source_key=config.glossary_source_key,
                timeout=config.timeout,
                should_cancel=self.should_cancel,
                retry_policy=self.retry_policy,
                on_retry=self.on_retry,
                before_attempt=self._throttle,
            )
        raise ValueError(f'Unsupported translation provider "{config.provider}".')

    def translate_jobs(self, jobs, config, progress_callback=None, should_cancel=None):
        validate_translator_config(config)
        results = TranslationResults()
        provider = normalize_provider(config.provider)
        # model 进缓存命名空间：换模型自然作废。
        # 单词本不进：改单词本不作废已有译文（决定 6，靠「清空缓存」手动纠正）。
        self.cache_namespace = self._cache_namespace(config)
        previous_cancel = self.should_cancel
        self.should_cancel = should_cancel
        # 每个源的最小请求间隔由源列表提供（免费源内置，AI 源可自定义）
        self.rate_limiter = RateLimiter(max(0.0, float(config.min_interval or 0.0)))
        # 自动模式的并发上限 = 用户设的并发数（决定 22）。
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
        try:
            if provider in ("openai", "claude", "codex"):
                return self._translate_openai_jobs(jobs, config, results, progress_callback, should_cancel)
            grouped = self._group_jobs(jobs, results)

            for (source, target), group_jobs in grouped.items():
                if should_cancel and should_cancel():
                    break
                translator = self._create_provider(source, target, config)
                if self._apply_cached_results(provider, source, target, group_jobs, results, count_cache_hits=True) and progress_callback:
                    progress_callback(results)
                self._translate_batches(translator, group_jobs, config, provider, source, target, results, progress_callback, should_cancel)

            return results
        except TranslationCancelled:
            results.cancelled = True
            return results
        finally:
            self.should_cancel = previous_cancel
            self.rate_limiter = None
            self.gate = None

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

    def _translate_openai_jobs(self, jobs, config, results, progress_callback=None, should_cancel=None):
        provider = normalize_provider(config.provider)
        jobs = self._openai_uncached_jobs(jobs, results, provider)
        if not jobs:
            return results
        translator = self._create_provider("auto", "multi", config)
        batches = list(self.iter_row_batches(jobs, config.char_budget, DEFAULT_OUTPUT_CHAR_CAP,
                                             request_char_cap=config.char_budget))
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
                            results.cancelled = True
                            return results
        except TranslationCancelled:
            results.cancelled = True
        return results

    def _cache_namespace(self, config):
        # 术语表不进缓存键：改单词本不作废已有译文（决定 6）。
        # 模型进缓存键：换模型自然作废。
        return config.model or ""

    def _cache_key(self, provider, source, target, text):
        return (provider, source, target, text, self.cache_namespace)

    def _group_jobs(self, jobs, results):
        grouped = {}
        for job in jobs:
            if not job.text:
                results.skipped += 1
                continue
            grouped.setdefault((job.source_code, job.target_code), []).append(job)
        return grouped

    def iter_row_batches(self, jobs, char_budget=DEFAULT_CHAR_BUDGET,
                         output_char_cap=DEFAULT_OUTPUT_CHAR_CAP, request_char_cap=None):
        """按行累积、按字数预算封批。行永不被劈开。

        形状参照 bilingual_book_maker 的 _assign_batch_indexes
        （book_maker/loader/epub_loader.py:3143-3160）：累到预算就封批，
        超长条目单独成批，不拖累下一条。

        char_budget 管源文，output_char_cap 管预估产出，都只跟内容有关；
        request_char_cap 管整个请求的预估体积，只有 AI 源才传 —— 它把一行的多个
        目标语言合并进一条 JSON，每行都带一遍骨架，只按内容封批会发出远超预算的请求。
        """
        if not jobs:
            return
        # 只防零，不做下限钳制 —— 下限钳制会让「传 10」变成 200，测试与实现互相矛盾。
        budget = max(1, int(char_budget or DEFAULT_CHAR_BUDGET))
        cap = max(1, int(output_char_cap or DEFAULT_OUTPUT_CHAR_CAP))
        request_cap = None if request_char_cap is None else max(1, int(request_char_cap))

        by_row = {}
        for job in jobs:
            by_row.setdefault(job.row, []).append(job)

        batch = []
        batch_chars = 0
        batch_cost = 0
        batch_prompt = 0
        for row in sorted(by_row):
            row_jobs = by_row[row]
            # 同一行共享同一句原文，源文字数按最长的那条算
            row_chars = max(len(job.text) for job in row_jobs)
            # 预估产出量：源文字数 × 目标语言数（同一目标语言只算一次）
            targets = {(job.source_code, job.target_code) for job in row_jobs}
            row_cost = row_chars * max(1, len(targets))
            row_prompt = estimate_row_prompt_chars(row_jobs) if request_cap else 0

            if batch and (batch_chars + row_chars > budget or batch_cost + row_cost > cap
                          or (request_cap is not None and batch_prompt + row_prompt > request_cap)):
                yield batch
                batch, batch_chars, batch_cost, batch_prompt = [], 0, 0, 0

            batch.extend(row_jobs)
            batch_chars += row_chars
            batch_cost += row_cost
            batch_prompt += row_prompt

            if row_chars > budget or row_cost > cap or (request_cap is not None and row_prompt > request_cap):
                yield batch
                batch, batch_chars, batch_cost, batch_prompt = [], 0, 0, 0

        if batch:
            yield batch

    def _create_provider(self, source, target, config):
        try:
            return self.provider_factory(source, target, config)
        except TypeError:
            return self.provider_factory(source, target)

    def _translate_batches(self, translator, group_jobs, config, provider, source, target, results, progress_callback=None, should_cancel=None):
        batches = list(self.iter_row_batches(group_jobs, config.char_budget, DEFAULT_OUTPUT_CHAR_CAP))
        if not batches:
            return
        max_workers = max(1, int(config.parallel_batches or 1))
        if max_workers == 1 or len(batches) == 1:
            for batch_jobs in batches:
                try:
                    self._guarded(self._translate_one_row_batch, translator, batch_jobs, provider, source, target, results)
                except TranslationRequestError:
                    pass          # 批内已记失败，闸门已收到限速信号
                if progress_callback:
                    progress_callback(results)
                if should_cancel and should_cancel():
                    return
            return

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._guarded, self._translate_one_row_batch, translator, batch_jobs, provider, source, target, results): batch_jobs for batch_jobs in batches}
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

    def _translate_one_row_batch(self, translator, batch_jobs, provider, source, target, results):
        """翻译一个行批次：批内去重未缓存文本，调用 translate_batch，应用结果。"""
        seen = set()
        texts = []
        for job in batch_jobs:
            cache_key = self._cache_key(provider, source, target, job.text)
            if cache_key in self.cache:
                continue
            if job.text not in seen:
                seen.add(job.text)
                texts.append(job.text)
        if texts:
            try:
                translated_texts = translator.translate_batch(texts)
            except TranslationCancelled:
                raise
            except TranslationRequestError as exc:
                self._record_failed_batch(texts, batch_jobs, results, exc)
                raise                    # 让闸门看到限速信号
            except Exception as exc:
                self._record_failed_batch(texts, batch_jobs, results, exc)
                return                   # 非限速类错误：本批记失败，不打断其它批次
            self._store_batch_results(texts, translated_texts, provider, source, target)
        self._apply_cached_results(provider, source, target, batch_jobs, results)

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
            halves = split_batch_at_row(batch) if is_request_too_large(exc) else None
            if halves is None:
                self._record_failed_jobs(batch, results, exc)
                raise                # 保留 Task 3 的异常契约：让闸门看到限速信号
            # 网关嫌请求太大：按行劈成两半重发，父批不算失败 ——
            # 一整批几百上千个格子不该因为一次「请求太大」全军覆没。
            pending = None
            for half in halves:
                try:
                    self._translate_one_openai_batch(translator, half, results, provider)
                except TranslationCancelled:
                    raise
                except TranslationRequestError as half_exc:
                    pending = half_exc      # 子批已自己记失败，记下信号最后再回传
            if pending is not None:
                raise pending
            return
        except Exception as exc:
            self._record_failed_jobs(batch, results, exc)
            return                   # 非限速类错误：本批记失败，不打断其它批次
        self._store_parsed_results(assigned, parsed, results, provider)

    def _record_failed_batch(self, batch, group_jobs, results, exc):
        failed_texts = set(batch)
        results.failed += sum(1 for job in group_jobs if job.text in failed_texts)
        results.errors.append(str(exc))

    def _record_failed_jobs(self, jobs, results, exc):
        results.failed += len(jobs)
        results.errors.append(str(exc))

    def _store_batch_results(self, batch, translated_texts, provider, source, target):
        for source_text, translated_text in zip(batch, translated_texts):
            self.cache[self._cache_key(provider, source, target, source_text)] = translated_text

    def _apply_cached_results(self, provider, source, target, group_jobs, results, source_texts=None, count_cache_hits=False):
        applied = 0
        for job in group_jobs:
            if source_texts is not None and job.text not in source_texts:
                continue
            cell_key = (job.row, job.column)
            cache_key = self._cache_key(provider, source, target, job.text)
            if cell_key in results.cell_results or cache_key not in self.cache:
                continue
            results.cell_results[cell_key] = self.cache[cache_key]
            results.translated += 1
            if count_cache_hits:
                results.cache_hits += 1
            applied += 1
        return applied

    def _openai_uncached_jobs(self, jobs, results, provider="openai"):
        uncached = []
        for job in jobs:
            if not job.text:
                results.skipped += 1
                continue
            cache_key = self._openai_cache_key(job, provider)
            if cache_key in self.cache:
                results.cache_hits += 1
                results.cell_results[(job.row, job.column)] = self.cache[cache_key]
                results.translated += 1
                continue
            uncached.append(job)
        return uncached

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

    def _openai_cache_key(self, job, provider="openai"):
        return self._cache_key(provider, job.source_code, job.target_code, job.text)


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


def normalize_provider(provider):
    provider = (provider or "google").lower()
    return "openai" if provider == "chatgpt" else provider


# --- 批次编号与带编号回复解析（决定 18） -------------------------------------


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


# 一行在合并提示词里的固定骨架：{"id": 1, "source_language": "en", "targets": [], "text": ""},
AI_ROW_PROMPT_OVERHEAD = 60
# 每个目标语言在 "targets" 里的开销："zh-CN",
AI_TARGET_PROMPT_CHARS = 8


def estimate_row_prompt_chars(row_jobs):
    """估一行在 AI 合并提示词里占多少字符（形状见 build_merged_prompt 的 items）。

    源文往往只有几个字符，而每行都要带一遍键名、语言码与引号，骨架比原文大得多：
    只按源文字数封批会发出远超预算的请求（实测 3000 字预算发出 24000 字，网关直接拒绝）。
    这里只做粗估，不要求精确，真实提示词还会多出系统提示与术语表。
    """
    targets = {job.target_code for job in row_jobs}
    text_chars = max((len(job.text) for job in row_jobs), default=0)
    return text_chars + AI_TARGET_PROMPT_CHARS * len(targets) + AI_ROW_PROMPT_OVERHEAD


def assign_batch_ids(jobs):
    """给一批 job 分配稳定 id：同一行的所有 job 共享一个 id。

    **id 只在这里分配一次。** 补发时直接复用同一份映射的子集，绝不重新编号 ——
    重新编号会让补发的第 1 行冒充原来的第 1 行，把结果写到错误的单元格并污染磁盘缓存。
    """
    by_row = {}
    for job in jobs:
        by_row.setdefault(job.row, []).append(job)
    return {index: by_row[row] for index, row in enumerate(sorted(by_row), start=1)}


# 网关/模型嫌请求太大时的报错特征：413，或 400 正文里的英文短语、
# 或中文网关的「Token + 上限词」（实测 Index-Translate 两条文案都命中）。
TOO_LARGE_HINTS = (
    "too many tokens", "maximum context", "context length", "context_length_exceeded",
    "token limit", "tokens limit", "too large", "payload too large", "prompt is too long",
)
TOO_LARGE_LIMIT_WORDS = ("超出", "超过", "上限", "最大限制", "上下文")


def is_request_too_large(exc):
    """这个失败是不是「请求体积超出网关/模型上限」？命中就值得劈开重发。"""
    if not isinstance(exc, TranslationRequestError):
        return False
    if exc.status == 413:
        return True
    if exc.status != 400:
        return False
    text = str(exc).lower()
    if any(hint in text for hint in TOO_LARGE_HINTS):
        return True
    return "token" in text and any(word in text for word in TOO_LARGE_LIMIT_WORDS)


def split_batch_at_row(batch):
    """把一批按行对半劈开，行永不被拆散。只有一行时返回 None（没得劈）。"""
    by_row = {}
    for job in batch:
        by_row.setdefault(job.row, []).append(job)
    rows = sorted(by_row)
    if len(rows) < 2:
        return None
    middle = len(rows) // 2
    return (
        [job for row in rows[:middle] for job in by_row[row]],
        [job for row in rows[middle:] for job in by_row[row]],
    )


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
    content = (content or "").strip()
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


class OpenAICompatibleTranslator:
    def __init__(self, source, target, api_key, model, base_url="", glossary=None,
                 glossary_source_key="", post_json=None, timeout=60.0, should_cancel=None,
                 retry_policy=None, on_retry=None, before_attempt=None):
        self.source = source
        self.target = target
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"
        self.glossary = glossary or []
        self.glossary_source_key = glossary_source_key
        self.post_json = post_json or self._post_json
        self.timeout = timeout
        self.should_cancel = should_cancel
        self.retry_policy = retry_policy or RetryPolicy()
        self.on_retry = on_retry
        self.before_attempt = before_attempt

    def translate_batch(self, texts):
        if not texts:
            return []
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a translation engine. Return only a JSON array of translated strings.",
                },
                {
                    "role": "user",
                    "content": self._build_batch_prompt(texts),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": AI_USER_AGENT,
        }
        response = self.post_json(self._chat_completions_url(), headers, payload)
        content = self._extract_content(response)
        translated = self._parse_translations(content)
        if len(translated) != len(texts):
            raise RuntimeError(f"OpenAI returned {len(translated)} translations for {len(texts)} source texts.")
        return translated

    def translate_job_batch(self, jobs, assigned=None):
        """返回 {id: {target_language: translation}}。

        jobs 与 assigned 二选一：只给 jobs 时在这里分配 id；服务层会传入已分配的
        assigned，以保证补发时 id 不变（决定 18）。
        """
        if not jobs and not assigned:
            return {}
        assigned = assigned or assign_batch_ids(jobs)
        glossary_entries = matching_glossary_entries(
            self.glossary,
            [row_jobs[0].text for row_jobs in assigned.values()],
            self.glossary_source_key,
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a translation engine. Return only a JSON object keyed by item id.",
                },
                {
                    "role": "user",
                    "content": self.build_merged_prompt(assigned, glossary_entries),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": AI_USER_AGENT,
        }
        response = self.post_json(self._chat_completions_url(), headers, payload)
        content = self._extract_content(response)
        return parse_numbered_translations(content)

    def translate(self, text):
        return self.translate_batch([text])[0]

    def _build_batch_prompt(self, texts):
        return (
            f"Translate each string from {self.source} into {self.target}.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Source JSON array:\n{json.dumps(texts, ensure_ascii=False)}"
        )

    @staticmethod
    def build_merged_prompt(assigned, glossary_entries=None):
        """assigned: {id: [该行的 job]}（由 assign_batch_ids 产出，id 稳定）。

        同一行的多个目标语言合并成一条 item：源文只出现一次，减少请求体积。
        """
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

    def _chat_completions_url(self):
        url = self.base_url.strip().rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        return f"{url}/chat/completions"

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

        return retry_call(attempt, self.retry_policy, self.should_cancel, self.on_retry, self.before_attempt)

    def _extract_content(self, response):
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"OpenAI response missing choices[0].message.content: {response}") from exc

    def _parse_translations(self, content):
        return self._parse_translations_static(content)

    @staticmethod
    def _parse_translations_static(content):
        content = content.strip()
        if content.startswith("```"):
            content = OpenAICompatibleTranslator._strip_code_fence_static(content)
        try:
            values = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI response was not a JSON array: {content}") from exc
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise RuntimeError(f"OpenAI response must be a JSON array of strings: {content}")
        return values

    def _strip_code_fence(self, content):
        return self._strip_code_fence_static(content)

    @staticmethod
    def _strip_code_fence_static(content):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()


class ClaudeMessagesTranslator:
    """Anthropic Claude Messages API translator (POST /v1/messages)."""

    DEFAULT_BASE_URL = "https://api.anthropic.com"
    DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, source, target, api_key, model, base_url="", glossary=None,
                 glossary_source_key="", post_json=None, timeout=60.0, should_cancel=None,
                 retry_policy=None, on_retry=None, before_attempt=None):
        self.source = source
        self.target = target
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.glossary = glossary or []
        self.glossary_source_key = glossary_source_key
        self.post_json = post_json or self._post_json
        self.timeout = timeout
        self.should_cancel = should_cancel
        self.retry_policy = retry_policy or RetryPolicy()
        self.on_retry = on_retry
        self.before_attempt = before_attempt

    def translate_batch(self, texts):
        if not texts:
            return []
        payload = {
            "model": self.model,
            "max_tokens": 8192,
            "system": "You are a translation engine. Return only a JSON array of translated strings.",
            "messages": [
                {"role": "user", "content": self._build_batch_prompt(texts)}
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        response = self.post_json(self._messages_url(), headers, payload)
        content = self._extract_content(response)
        translated = OpenAICompatibleTranslator._parse_translations_static(content)
        if len(translated) != len(texts):
            raise RuntimeError(f"Claude returned {len(translated)} translations for {len(texts)} source texts.")
        return translated

    def translate_job_batch(self, jobs, assigned=None):
        """返回 {id: {target_language: translation}}（见 OpenAICompatibleTranslator）。"""
        if not jobs and not assigned:
            return {}
        assigned = assigned or assign_batch_ids(jobs)
        glossary_entries = matching_glossary_entries(
            self.glossary,
            [row_jobs[0].text for row_jobs in assigned.values()],
            self.glossary_source_key,
        )
        payload = {
            "model": self.model,
            "max_tokens": 8192,
            # system 用数组形状才能在稳定前缀上加 cache_control（决定 7）。
            "system": [
                {
                    "type": "text",
                    "text": "You are a translation engine. Reply with only a JSON object, no prose.",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": OpenAICompatibleTranslator.build_merged_prompt(assigned, glossary_entries),
                }
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        response = self.post_json(self._messages_url(), headers, payload)
        content = self._extract_content(response)
        return parse_numbered_translations(content)

    def translate(self, text):
        return self.translate_batch([text])[0]

    def _build_batch_prompt(self, texts):
        return (
            f"Translate each string from {self.source} into {self.target}.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Source JSON array:\n{json.dumps(texts, ensure_ascii=False)}"
        )

    def _messages_url(self):
        url = self.base_url.strip().rstrip("/")
        if url.endswith("/v1/messages"):
            return url
        if url.endswith("/v1"):
            return f"{url}/messages"
        return f"{url}/v1/messages"

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
                    f"Claude HTTP {exc.code}: {detail}",
                    status=exc.code,
                    retry_after=parse_retry_after(exc.headers),
                ) from exc
            except urllib.error.URLError as exc:
                raise TranslationRequestError(f"Claude request failed: {exc.reason}") from exc

        return retry_call(attempt, self.retry_policy, self.should_cancel, self.on_retry, self.before_attempt)

    def _extract_content(self, response):
        try:
            return response["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Claude response missing content[0].text: {response}") from exc


class CodexResponsesTranslator:
    """OpenAI Responses API translator (POST /v1/responses)."""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, source, target, api_key, model, base_url="", glossary=None,
                 glossary_source_key="", post_json=None, timeout=60.0, should_cancel=None,
                 retry_policy=None, on_retry=None, before_attempt=None):
        self.source = source
        self.target = target
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.glossary = glossary or []
        self.glossary_source_key = glossary_source_key
        self.post_json = post_json or self._post_json
        self.timeout = timeout
        self.should_cancel = should_cancel
        self.retry_policy = retry_policy or RetryPolicy()
        self.on_retry = on_retry
        self.before_attempt = before_attempt

    def translate_batch(self, texts):
        if not texts:
            return []
        payload = {
            "model": self.model,
            "instructions": "You are a translation engine. Return only a JSON array of translated strings.",
            "input": self._build_batch_prompt(texts),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.post_json(self._responses_url(), headers, payload)
        content = self._extract_content(response)
        translated = OpenAICompatibleTranslator._parse_translations_static(content)
        if len(translated) != len(texts):
            raise RuntimeError(f"Codex returned {len(translated)} translations for {len(texts)} source texts.")
        return translated

    def translate_job_batch(self, jobs, assigned=None):
        """返回 {id: {target_language: translation}}（见 OpenAICompatibleTranslator）。"""
        if not jobs and not assigned:
            return {}
        assigned = assigned or assign_batch_ids(jobs)
        glossary_entries = matching_glossary_entries(
            self.glossary,
            [row_jobs[0].text for row_jobs in assigned.values()],
            self.glossary_source_key,
        )
        payload = {
            "model": self.model,
            "instructions": "You are a translation engine. Return only a JSON object keyed by item id.",
            "input": OpenAICompatibleTranslator.build_merged_prompt(assigned, glossary_entries),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.post_json(self._responses_url(), headers, payload)
        content = self._extract_content(response)
        return parse_numbered_translations(content)

    def translate(self, text):
        return self.translate_batch([text])[0]

    def _build_batch_prompt(self, texts):
        return (
            f"Translate each string from {self.source} into {self.target}.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Source JSON array:\n{json.dumps(texts, ensure_ascii=False)}"
        )

    def _responses_url(self):
        url = self.base_url.strip().rstrip("/")
        if url.endswith("/responses"):
            return url
        if url.endswith("/v1"):
            return f"{url}/responses"
        return f"{url}/v1/responses"

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
                    f"Codex HTTP {exc.code}: {detail}",
                    status=exc.code,
                    retry_after=parse_retry_after(exc.headers),
                ) from exc
            except urllib.error.URLError as exc:
                raise TranslationRequestError(f"Codex request failed: {exc.reason}") from exc

        return retry_call(attempt, self.retry_policy, self.should_cancel, self.on_retry, self.before_attempt)

    def _extract_content(self, response):
        if "output_text" in response and response["output_text"]:
            return response["output_text"]
        try:
            for item in response["output"]:
                if item.get("type") == "message":
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            return part.get("text", "")
        except (KeyError, IndexError, TypeError):
            pass
        raise RuntimeError(f"Codex response missing output_text: {response}")

