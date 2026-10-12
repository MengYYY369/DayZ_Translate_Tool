import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import mktime_tz, parsedate_tz

# —— 限速与重试（决定 9 / 12 / 14）——
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 2.0
RETRY_MAX_DELAY = 60.0
RETRYABLE_STATUS = frozenset({408, 409, 413, 429, 500, 502, 503, 504})
FATAL_STATUS = frozenset({400, 401, 403, 404, 422})


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
    batch_size: int = 30
    parallel_batches: int = 1
    api_key: str = ""
    region: str = ""
    model: str = ""
    email: str = ""
    base_url: str = ""
    timeout: float = 60.0
    glossary: list = field(default_factory=list)


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
    def __init__(self, provider_factory=None, batch_size=30, should_cancel=None, cache=None):
        self.provider_factory = provider_factory or self.create_provider
        self.batch_size = batch_size
        # cache 允许外部注入：多次翻译运行共享同一个字典即可复用相同内容的翻译结果
        self.cache = cache if cache is not None else {}
        self.cache_namespace = ""
        self.should_cancel = should_cancel
        self.retry_policy = RetryPolicy()
        self.on_retry = None
        self.openai_translator_class = OpenAICompatibleTranslator
        self.google_translator_class = GoogleTranslateTranslator
        self.claude_translator_class = ClaudeMessagesTranslator
        self.codex_translator_class = CodexResponsesTranslator

    def create_provider(self, source, target, config):
        provider = normalize_provider(config.provider)
        if provider == "google":
            return self.google_translator_class(
                source=source,
                target=target,
                base_url=config.base_url,
                timeout=config.timeout,
                should_cancel=self.should_cancel,
                retry_policy=self.retry_policy,
                on_retry=self.on_retry,
            )
        if provider == "mymemory":
            from deep_translator import MyMemoryTranslator

            kwargs = {"source": source, "target": target}
            if config.email:
                kwargs["email"] = config.email
            return MyMemoryTranslator(**kwargs)
        if provider == "deepl":
            from deep_translator import DeeplTranslator

            return DeeplTranslator(source=source, target=target, api_key=config.api_key)
        if provider == "microsoft":
            from deep_translator import MicrosoftTranslator

            return MicrosoftTranslator(source=source, target=target, api_key=config.api_key, region=config.region)
        if provider == "openai":
            return self.openai_translator_class(
                source=source,
                target=target,
                api_key=config.api_key,
                model=config.model or "gpt-3.5-turbo",
                base_url=config.base_url,
                glossary=config.glossary,
                timeout=config.timeout,
                should_cancel=self.should_cancel,
                retry_policy=self.retry_policy,
                on_retry=self.on_retry,
            )
        if provider == "claude":
            return self.claude_translator_class(
                source=source,
                target=target,
                api_key=config.api_key,
                model=config.model or self.claude_translator_class.DEFAULT_MODEL,
                base_url=config.base_url,
                glossary=config.glossary,
                timeout=config.timeout,
                should_cancel=self.should_cancel,
                retry_policy=self.retry_policy,
                on_retry=self.on_retry,
            )
        if provider == "codex":
            return self.codex_translator_class(
                source=source,
                target=target,
                api_key=config.api_key,
                model=config.model or self.codex_translator_class.DEFAULT_MODEL,
                base_url=config.base_url,
                glossary=config.glossary,
                timeout=config.timeout,
                should_cancel=self.should_cancel,
                retry_policy=self.retry_policy,
                on_retry=self.on_retry,
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

    def _translate_openai_jobs(self, jobs, config, results, progress_callback=None, should_cancel=None):
        provider = normalize_provider(config.provider)
        jobs = self._openai_uncached_jobs(jobs, results, provider)
        if not jobs:
            return results
        translator = self._create_provider("auto", "multi", config)
        batches = list(self._row_chunks(jobs))
        if not batches:
            return results
        max_workers = max(1, int(config.parallel_batches or 1))
        try:
            if max_workers == 1 or len(batches) == 1:
                for batch in batches:
                    if should_cancel and should_cancel():
                        break
                    self._translate_one_openai_batch(translator, batch, results, provider)
                    if progress_callback:
                        progress_callback(results)
            else:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(self._translate_one_openai_batch, translator, batch, results, provider): batch for batch in batches}
                    for future in as_completed(futures):
                        batch = futures[future]
                        try:
                            future.result()
                        except TranslationCancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            raise
                        if progress_callback:
                            progress_callback(results)
                        if should_cancel and should_cancel():
                            executor.shutdown(wait=False, cancel_futures=True)
                            return
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

    def _row_chunks(self, jobs):
        """按 job.row 分批，每批包含 batch_size 个不同行的 job。"""
        if not jobs:
            return
        unique_rows = sorted(set(job.row for job in jobs))
        size = max(1, self.batch_size)
        for index in range(0, len(unique_rows), size):
            batch_rows = set(unique_rows[index:index + size])
            yield [job for job in jobs if job.row in batch_rows]

    def _create_provider(self, source, target, config):
        try:
            return self.provider_factory(source, target, config)
        except TypeError:
            return self.provider_factory(source, target)

    def _translate_batches(self, translator, group_jobs, config, provider, source, target, results, progress_callback=None, should_cancel=None):
        batches = list(self._row_chunks(group_jobs))
        if not batches:
            return
        max_workers = max(1, int(config.parallel_batches or 1))
        if max_workers == 1 or len(batches) == 1:
            for batch_jobs in batches:
                self._translate_one_row_batch(translator, batch_jobs, provider, source, target, results)
                if progress_callback:
                    progress_callback(results)
                if should_cancel and should_cancel():
                    return
            return

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._translate_one_row_batch, translator, batch_jobs, provider, source, target, results): batch_jobs for batch_jobs in batches}
            for future in as_completed(futures):
                batch_jobs = futures[future]
                try:
                    future.result()
                except TranslationCancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
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
            except Exception as exc:
                self._record_failed_batch(texts, batch_jobs, results, exc)
                return
            self._store_batch_results(texts, translated_texts, provider, source, target)
        self._apply_cached_results(provider, source, target, batch_jobs, results)

    def _translate_one_openai_batch(self, translator, batch, results, provider):
        try:
            translated_texts = translator.translate_job_batch(batch)
        except TranslationCancelled:
            raise
        except Exception as exc:
            self._record_failed_jobs(batch, results, exc)
            return
        self._store_job_results(batch, translated_texts, results, provider)

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

    def _store_job_results(self, jobs, translated_texts, results, provider="openai"):
        if len(translated_texts) != len(jobs):
            raise RuntimeError(f"OpenAI returned {len(translated_texts)} translations for {len(jobs)} jobs.")
        for job, translated_text in zip(jobs, translated_texts):
            self.cache[self._openai_cache_key(job, provider)] = translated_text
            results.cell_results[(job.row, job.column)] = translated_text
            results.translated += 1

    def _openai_cache_key(self, job, provider="openai"):
        return self._cache_key(provider, job.source_code, job.target_code, job.text)


def validate_translator_config(config):
    provider = normalize_provider(config.provider)
    if provider == "deepl" and not config.api_key:
        raise ValueError("DeepL requires an API key.")
    if provider == "microsoft" and (not config.api_key or not config.region):
        raise ValueError("Microsoft Translator requires an API key and region.")
    if provider == "openai" and not config.api_key:
        raise ValueError("OpenAI translator requires an API key.")
    if provider == "claude" and not config.api_key:
        raise ValueError("Claude translator requires an API key.")
    if provider == "codex" and not config.api_key:
        raise ValueError("Codex translator requires an API key.")


def normalize_provider(provider):
    provider = (provider or "google").lower()
    return "openai" if provider == "chatgpt" else provider


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
        }
        response = self.post_json(self._chat_completions_url(), headers, payload)
        content = self._extract_content(response)
        translated = self._parse_translations(content)
        if len(translated) != len(texts):
            raise RuntimeError(f"OpenAI returned {len(translated)} translations for {len(texts)} source texts.")
        return translated

    def translate_job_batch(self, jobs):
        if not jobs:
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
                    "content": self._build_job_batch_prompt(jobs),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.post_json(self._chat_completions_url(), headers, payload)
        content = self._extract_content(response)
        translated = self._parse_translations(content)
        if len(translated) != len(jobs):
            raise RuntimeError(f"OpenAI returned {len(translated)} translations for {len(jobs)} jobs.")
        return translated

    def translate(self, text):
        return self.translate_batch([text])[0]

    def _build_batch_prompt(self, texts):
        return (
            f"Translate each string from {self.source} into {self.target}.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Source JSON array:\n{json.dumps(texts, ensure_ascii=False)}"
        )

    def _build_job_batch_prompt(self, jobs):
        items = [
            {
                "source_language": job.source_code,
                "target_language": job.target_code,
                "text": job.text,
            }
            for job in jobs
        ]
        return (
            "Translate each item.text from item.source_language into item.target_language.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Use glossary entries when a matching source term and target language value exist.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Glossary JSON object:\n{json.dumps({'glossary': self.glossary}, ensure_ascii=False)}\n"
            f"Items JSON array:\n{json.dumps(items, ensure_ascii=False)}"
        )

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
            "max_tokens": 4096,
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

    def translate_job_batch(self, jobs):
        if not jobs:
            return []
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": "You are a translation engine. Return only a JSON array of translated strings.",
            "messages": [
                {"role": "user", "content": self._build_job_batch_prompt(jobs)}
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
        if len(translated) != len(jobs):
            raise RuntimeError(f"Claude returned {len(translated)} translations for {len(jobs)} jobs.")
        return translated

    def translate(self, text):
        return self.translate_batch([text])[0]

    def _build_batch_prompt(self, texts):
        return (
            f"Translate each string from {self.source} into {self.target}.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Source JSON array:\n{json.dumps(texts, ensure_ascii=False)}"
        )

    def _build_job_batch_prompt(self, jobs):
        items = [
            {"source_language": job.source_code, "target_language": job.target_code, "text": job.text}
            for job in jobs
        ]
        return (
            "Translate each item.text from item.source_language into item.target_language.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Use glossary entries when a matching source term and target language value exist.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Glossary JSON object:\n{json.dumps({'glossary': self.glossary}, ensure_ascii=False)}\n"
            f"Items JSON array:\n{json.dumps(items, ensure_ascii=False)}"
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

    def translate_job_batch(self, jobs):
        if not jobs:
            return []
        payload = {
            "model": self.model,
            "instructions": "You are a translation engine. Return only a JSON array of translated strings.",
            "input": self._build_job_batch_prompt(jobs),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.post_json(self._responses_url(), headers, payload)
        content = self._extract_content(response)
        translated = OpenAICompatibleTranslator._parse_translations_static(content)
        if len(translated) != len(jobs):
            raise RuntimeError(f"Codex returned {len(translated)} translations for {len(jobs)} jobs.")
        return translated

    def translate(self, text):
        return self.translate_batch([text])[0]

    def _build_batch_prompt(self, texts):
        return (
            f"Translate each string from {self.source} into {self.target}.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Source JSON array:\n{json.dumps(texts, ensure_ascii=False)}"
        )

    def _build_job_batch_prompt(self, jobs):
        items = [
            {"source_language": job.source_code, "target_language": job.target_code, "text": job.text}
            for job in jobs
        ]
        return (
            "Translate each item.text from item.source_language into item.target_language.\n"
            "Keep the same order and preserve placeholders, tags, punctuation, and line breaks.\n"
            "Use glossary entries when a matching source term and target language value exist.\n"
            "Return only valid JSON in this exact shape: [\"translation 1\", \"translation 2\"].\n"
            f"Glossary JSON object:\n{json.dumps({'glossary': self.glossary}, ensure_ascii=False)}\n"
            f"Items JSON array:\n{json.dumps(items, ensure_ascii=False)}"
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


class GoogleTranslateTranslator:
    """Google Translate via the googleapis.com JSON endpoint.

    Uses ``translate.googleapis.com/translate_a/single`` instead of the
    HTML-scraping ``translate.google.com/m`` endpoint used by
    ``deep_translator.GoogleTranslator``.  The JSON endpoint is more
    reliable and supports a configurable timeout so the UI does not hang
    indefinitely when the network is unreachable.
    """

    DEFAULT_BASE_URL = "https://translate.googleapis.com/translate_a/single"
    DEFAULT_TIMEOUT = 15.0

    def __init__(self, source="auto", target="en", base_url="", timeout=None,
                 request_func=None, should_cancel=None,
                 retry_policy=None, on_retry=None, before_attempt=None):
        self.source = source
        self.target = target
        self.base_url = self._normalize_base_url(base_url or self.DEFAULT_BASE_URL)
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.request_func = request_func or self._default_request
        self.should_cancel = should_cancel
        self.retry_policy = retry_policy or RetryPolicy()
        self.on_retry = on_retry
        self.before_attempt = before_attempt

    @staticmethod
    def _normalize_base_url(url):
        url = url.strip().rstrip("/")
        if not url.endswith("/translate_a/single"):
            url = f"{url}/translate_a/single"
        return url

    def translate(self, text):
        return self.translate_batch([text])[0]

    def translate_batch(self, texts):
        if not texts:
            return []
        params = [("client", "gtx"), ("sl", self.source),
                  ("tl", self.target), ("dt", "t")]
        params.extend(("q", text) for text in texts)
        query_string = urllib.parse.urlencode(params)
        url = f"{self.base_url}?{query_string}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        # 重试包在 request_func 外面：测试注入的假 request_func 也走同一套重试，
        # 同时不改它「返回已解析数据」的契约。
        data = retry_call(
            lambda: self.request_func(url, headers),
            self.retry_policy, self.should_cancel, self.on_retry, self.before_attempt,
        )
        translated = self._extract_translations(data)
        if len(translated) != len(texts):
            raise RuntimeError(
                f"Google returned {len(translated)} translations "
                f"for {len(texts)} texts."
            )
        return translated

    @staticmethod
    def _extract_translations(data):
        if not isinstance(data, list) or not data or not isinstance(data[0], list):
            raise RuntimeError(f"Unexpected Google Translate response: {data}")
        translations = []
        for item in data[0]:
            if isinstance(item, list) and item:
                translations.append(item[0])
            else:
                raise RuntimeError(f"Unexpected Google Translate response item: {item}")
        return translations

    def _default_request(self, url, headers):
        if self.should_cancel and self.should_cancel():
            raise TranslationCancelled()
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TranslationRequestError(
                f"Google Translate HTTP {exc.code}: {detail}",
                status=exc.code,
                retry_after=parse_retry_after(exc.headers),
            ) from exc
        except urllib.error.URLError as exc:
            raise TranslationRequestError(f"Google Translate request failed: {exc.reason}") from exc
        return json.loads(body)
