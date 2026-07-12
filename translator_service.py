import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed


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
    timeout: float = 15.0
    glossary: list = field(default_factory=list)


@dataclass
class TranslationResults:
    translated: int = 0
    skipped: int = 0
    failed: int = 0
    cache_hits: int = 0
    cell_results: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


class TranslationService:
    def __init__(self, provider_factory=None, batch_size=30):
        self.provider_factory = provider_factory or self.create_provider
        self.batch_size = batch_size
        self.cache = {}
        self.openai_translator_class = OpenAICompatibleTranslator
        self.google_translator_class = GoogleTranslateTranslator

    def create_provider(self, source, target, config):
        provider = normalize_provider(config.provider)
        if provider == "google":
            return self.google_translator_class(
                source=source,
                target=target,
                base_url=config.base_url,
                timeout=config.timeout,
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
            )
        raise ValueError(f'Unsupported translation provider "{config.provider}".')

    def translate_jobs(self, jobs, config, progress_callback=None, should_cancel=None):
        validate_translator_config(config)
        results = TranslationResults()
        provider = normalize_provider(config.provider)
        if provider == "openai":
            return self._translate_openai_jobs(jobs, config, results, progress_callback, should_cancel)
        grouped = self._group_jobs(jobs, results)

        for (source, target), group_jobs in grouped.items():
            if should_cancel and should_cancel():
                break
            translator = self._create_provider(source, target, config)
            unique_texts = self._unique_uncached_texts(provider, source, target, group_jobs, results)
            if self._apply_cached_results(provider, source, target, group_jobs, results) and progress_callback:
                progress_callback(results)
            self._translate_batches(translator, unique_texts, config, provider, source, target, group_jobs, results, progress_callback)

        return results

    def _translate_openai_jobs(self, jobs, config, results, progress_callback=None, should_cancel=None):
        jobs = self._openai_uncached_jobs(jobs, results)
        if not jobs:
            return results
        translator = self._create_provider("auto", "multi", config)
        for batch in self._chunks(jobs):
            if should_cancel and should_cancel():
                break
            try:
                translated_texts = translator.translate_job_batch(batch)
            except Exception as exc:
                self._record_failed_jobs(batch, results, exc)
                if progress_callback:
                    progress_callback(results)
                continue
            self._store_job_results(batch, translated_texts, results)
            if progress_callback:
                progress_callback(results)
        return results

    def _group_jobs(self, jobs, results):
        grouped = {}
        for job in jobs:
            if not job.text:
                results.skipped += 1
                continue
            grouped.setdefault((job.source_code, job.target_code), []).append(job)
        return grouped

    def _unique_uncached_texts(self, provider, source, target, jobs, results):
        seen = set()
        texts = []
        for job in jobs:
            key = (provider, source, target, job.text)
            if key in self.cache:
                results.cache_hits += 1
                continue
            if job.text not in seen:
                seen.add(job.text)
                texts.append(job.text)
        return texts

    def _chunks(self, values):
        size = max(1, self.batch_size)
        for index in range(0, len(values), size):
            yield values[index:index + size]

    def _create_provider(self, source, target, config):
        try:
            return self.provider_factory(source, target, config)
        except TypeError:
            return self.provider_factory(source, target)

    def _translate_batches(self, translator, unique_texts, config, provider, source, target, group_jobs, results, progress_callback=None):
        batches = list(self._chunks(unique_texts))
        if not batches:
            return
        max_workers = max(1, int(config.parallel_batches or 1))
        if max_workers == 1 or len(batches) == 1:
            for batch in batches:
                self._translate_one_batch(translator, batch, provider, source, target, group_jobs, results)
                if progress_callback:
                    progress_callback(results)
            return

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(translator.translate_batch, batch): batch for batch in batches}
            for future in as_completed(futures):
                batch = futures[future]
                try:
                    translated_texts = future.result()
                except Exception as exc:
                    self._record_failed_batch(batch, group_jobs, results, exc)
                    if progress_callback:
                        progress_callback(results)
                    continue
                self._store_batch_results(batch, translated_texts, provider, source, target)
                self._apply_cached_results(provider, source, target, group_jobs, results, set(batch))
                if progress_callback:
                    progress_callback(results)

    def _translate_one_batch(self, translator, batch, provider, source, target, group_jobs, results):
        try:
            translated_texts = translator.translate_batch(batch)
        except Exception as exc:
            self._record_failed_batch(batch, group_jobs, results, exc)
            return
        self._store_batch_results(batch, translated_texts, provider, source, target)
        self._apply_cached_results(provider, source, target, group_jobs, results, set(batch))

    def _record_failed_batch(self, batch, group_jobs, results, exc):
        failed_texts = set(batch)
        results.failed += sum(1 for job in group_jobs if job.text in failed_texts)
        results.errors.append(str(exc))

    def _record_failed_jobs(self, jobs, results, exc):
        results.failed += len(jobs)
        results.errors.append(str(exc))

    def _store_batch_results(self, batch, translated_texts, provider, source, target):
        for source_text, translated_text in zip(batch, translated_texts):
            self.cache[(provider, source, target, source_text)] = translated_text

    def _apply_cached_results(self, provider, source, target, group_jobs, results, source_texts=None):
        applied = 0
        for job in group_jobs:
            if source_texts is not None and job.text not in source_texts:
                continue
            cell_key = (job.row, job.column)
            cache_key = (provider, source, target, job.text)
            if cell_key in results.cell_results or cache_key not in self.cache:
                continue
            results.cell_results[cell_key] = self.cache[cache_key]
            results.translated += 1
            applied += 1
        return applied

    def _openai_uncached_jobs(self, jobs, results):
        uncached = []
        for job in jobs:
            if not job.text:
                results.skipped += 1
                continue
            cache_key = self._openai_cache_key(job)
            if cache_key in self.cache:
                results.cache_hits += 1
                results.cell_results[(job.row, job.column)] = self.cache[cache_key]
                results.translated += 1
                continue
            uncached.append(job)
        return uncached

    def _store_job_results(self, jobs, translated_texts, results):
        if len(translated_texts) != len(jobs):
            raise RuntimeError(f"OpenAI returned {len(translated_texts)} translations for {len(jobs)} jobs.")
        for job, translated_text in zip(jobs, translated_texts):
            self.cache[self._openai_cache_key(job)] = translated_text
            results.cell_results[(job.row, job.column)] = translated_text
            results.translated += 1

    def _openai_cache_key(self, job):
        return ("openai", job.source_code, job.target_code, job.text)


def validate_translator_config(config):
    provider = normalize_provider(config.provider)
    if provider == "deepl" and not config.api_key:
        raise ValueError("DeepL requires an API key.")
    if provider == "microsoft" and (not config.api_key or not config.region):
        raise ValueError("Microsoft Translator requires an API key and region.")
    if provider == "openai" and not config.api_key:
        raise ValueError("OpenAI translator requires an API key.")


def normalize_provider(provider):
    provider = (provider or "google").lower()
    return "openai" if provider == "chatgpt" else provider


class OpenAICompatibleTranslator:
    def __init__(self, source, target, api_key, model, base_url="", glossary=None, post_json=None):
        self.source = source
        self.target = target
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"
        self.glossary = glossary or []
        self.post_json = post_json or self._post_json

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
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc.reason}") from exc
        return json.loads(body)

    def _extract_content(self, response):
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"OpenAI response missing choices[0].message.content: {response}") from exc

    def _parse_translations(self, content):
        content = content.strip()
        if content.startswith("```"):
            content = self._strip_code_fence(content)
        try:
            values = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI response was not a JSON array: {content}") from exc
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise RuntimeError(f"OpenAI response must be a JSON array of strings: {content}")
        return values

    def _strip_code_fence(self, content):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()


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
                 request_func=None):
        self.source = source
        self.target = target
        self.base_url = self._normalize_base_url(base_url or self.DEFAULT_BASE_URL)
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.request_func = request_func or self._default_request

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
        data = self.request_func(url, headers)
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
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Translate HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Google Translate request failed: {exc.reason}") from exc
        return json.loads(body)
