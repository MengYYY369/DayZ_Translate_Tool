import json
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationRequest:
    key: str
    source_language: str
    source_text: str
    target_language: str
    current_target_text: str = ""


@dataclass(frozen=True)
class MultiTranslationRequest:
    key: str
    source_language: str
    source_text: str
    targets: list[TranslationRequest]


@dataclass(frozen=True)
class BatchTranslationResult:
    translated: int
    skipped: int
    failed: list[tuple[int, str]]
    canceled: bool = False


class AITranslator:
    def translate(self, request: TranslationRequest) -> str:
        raise NotImplementedError

    def translate_many(self, request: MultiTranslationRequest) -> dict[str, str]:
        results: dict[str, str] = {}
        for target in request.targets:
            results[target.target_language] = self.translate(target)
        return results


LANGUAGE_CODES = {
    "original": "auto",
    "english": "en",
    "czech": "cs",
    "german": "de",
    "russian": "ru",
    "polish": "pl",
    "hungarian": "hu",
    "italian": "it",
    "spanish": "es",
    "french": "fr",
    "chinese": "zh-CN",
    "chinesesimp": "zh-CN",
    "japanese": "ja",
    "portuguese": "pt",
}

MICROSOFT_LANGUAGE_CODES = {
    **LANGUAGE_CODES,
    "chinese": "zh-Hans",
    "chinesesimp": "zh-Hans",
}

YANDEX_LANGUAGE_CODES = {
    **LANGUAGE_CODES,
    "chinese": "zh",
    "chinesesimp": "zh",
}

class RateLimiter:
    def __init__(self, interval_seconds: float = 0.0, monotonic=time.monotonic, sleep=time.sleep):
        self.interval_seconds = max(0.0, float(interval_seconds))
        self.monotonic = monotonic
        self.sleep = sleep
        self._lock = threading.Lock()
        self._next_at: float | None = None

    def wait(self) -> None:
        if self.interval_seconds <= 0:
            return
        with self._lock:
            now = self.monotonic()
            if self._next_at is not None and now < self._next_at:
                delay = self._next_at - now
                self.sleep(delay)
                now = self._next_at
            self._next_at = now + self.interval_seconds


def build_translation_prompt(request: TranslationRequest) -> str:
    mode = "优化当前翻译" if request.current_target_text else "翻译"
    current = request.current_target_text or "(空)"
    return (
        "你是 DayZ 模组 stringtable.csv 翻译助手。\n"
        "只返回目标语言文本本身，不要解释，不要 Markdown，不要加引号。\n"
        "保留物品名、品牌名、代码名、口径、型号和专有名词的可读性。\n"
        f"任务: {mode}\n"
        f"Key: {request.key}\n"
        f"源语言列: {request.source_language}\n"
        f"目标语言列: {request.target_language}\n"
        f"源文本: {request.source_text}\n"
        f"当前目标文本: {current}\n"
    )


def build_multi_translation_prompt(request: MultiTranslationRequest) -> str:
    target_languages = [target.target_language for target in request.targets]
    current_values = []
    for target in request.targets:
        if target.current_target_text:
            current_values.append(f"{target.target_language}={target.current_target_text}")
    current = ", ".join(current_values) if current_values else "(空)"
    example = "{" + ", ".join([f'"{language}":"..."' for language in target_languages]) + "}"
    return (
        "你是 DayZ 模组 stringtable.csv 翻译助手。\n"
        "一次把源文本翻译到所有目标语言列。\n"
        "只返回 JSON 对象，不要解释，不要 Markdown，不要额外字段。\n"
        "JSON key 必须完全等于目标语言列名，value 是目标语言文本。\n"
        "保留物品名、品牌名、代码名、口径、型号和专有名词的可读性。\n"
        f"返回格式示例: {example}\n"
        f"Key: {request.key}\n"
        f"源语言列: {request.source_language}\n"
        f"目标语言列: {', '.join(target_languages)}\n"
        f"源文本: {request.source_text}\n"
        f"当前目标文本: {current}\n"
    )


def clean_ai_text(text: str) -> str:
    result = text.strip()
    if result.startswith("```") and result.endswith("```"):
        lines = result.splitlines()
        result = "\n".join(lines[1:-1]).strip()
    if len(result) >= 2 and result[0] == result[-1] and result[0] in {'"', "'"}:
        result = result[1:-1].strip()
    return result


def parse_multi_translation_response(text: str, target_languages: list[str]) -> dict[str, str]:
    result = clean_ai_text(text)
    try:
        payload = json.loads(result)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 返回的多语言 JSON 无法解析: {result}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"AI 返回的多语言结果不是 JSON 对象: {payload}")
    translations: dict[str, str] = {}
    for language in target_languages:
        value = payload.get(language)
        if value is not None:
            translations[language] = clean_ai_text(str(value))
    return translations


def _process_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def clean_process_error(text: str) -> str:
    result = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    if "FreeUsageLimitError" in result or "Rate limit exceeded" in result:
        retry_match = re.search(r'"retry-after"\s*:\s*"?(\d+)"?', result, re.IGNORECASE)
        retry_text = ""
        if retry_match:
            retry_seconds = int(retry_match.group(1))
            retry_hours = retry_seconds / 3600
            retry_text = f"，建议约 {retry_hours:.1f} 小时后再试"
        return f"Opencode free 模型额度已触发限流（Rate limit exceeded{retry_text}）。请换成已配置 API key 的模型，或等待额度恢复。"
    start = result.find("{")
    end = result.rfind("}")
    if start != -1 and end > start:
        try:
            payload = json.loads(result[start : end + 1])
            message = payload.get("data", {}).get("message") or payload.get("message")
            if message:
                result = str(message)
        except json.JSONDecodeError:
            pass
    if "model not found" in result.lower():
        result = f"{result}。请检查 Opencode 的 Run 参数或本机配置，改成当前账号可用的模型。"
    return result


def hidden_subprocess_kwargs() -> dict:
    options = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        if hasattr(subprocess, "STARTF_USESHOWWINDOW"):
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        if hasattr(subprocess, "SW_HIDE"):
            startupinfo.wShowWindow = subprocess.SW_HIDE
        options["startupinfo"] = startupinfo
    return options


def parse_opencode_models_output(output: str) -> list[str]:
    models = set()
    pattern = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+")
    for token in output.split():
        candidate = token.strip("`'\" ,;()[]{}")
        if candidate.startswith(("http://", "https://")):
            continue
        if pattern.fullmatch(candidate):
            models.add(candidate)
    return sorted(models)


def list_opencode_models(executable_path: str, refresh: bool = False, timeout_seconds: int = 60) -> list[str]:
    executable = executable_path.strip()
    if not executable:
        raise ValueError("缺少 Opencode 可执行文件路径")
    command = [executable, "models"]
    if refresh:
        command.append("--refresh")
    completed = subprocess.run(
        command,
        input="",
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
        **hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        stderr = clean_process_error(completed.stderr)
        raise RuntimeError(f"获取 Opencode 模型失败: {stderr}")
    models = parse_opencode_models_output(completed.stdout)
    if not models:
        raise RuntimeError("没有从 Opencode 输出中识别到模型")
    return models


class OpenAICompatibleTranslator(AITranslator):
    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: int = 60):
        self.base_url = base_url.strip()
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds

    def translate(self, request: TranslationRequest) -> str:
        if not self.base_url:
            raise ValueError("缺少 API base_url")
        if not self.model:
            raise ValueError("缺少 API model")
        url = self._completion_url()
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You translate DayZ stringtable entries."},
                    {"role": "user", "content": build_translation_prompt(request)},
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API 请求失败: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"API 请求失败: {exc}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"API 返回格式无法识别: {payload}") from exc
        return clean_ai_text(str(content))

    def translate_many(self, request: MultiTranslationRequest) -> dict[str, str]:
        if len(request.targets) == 1:
            target = request.targets[0]
            return {target.target_language: self.translate(target)}
        if not self.base_url:
            raise ValueError("缺少 API base_url")
        if not self.model:
            raise ValueError("缺少 API model")
        url = self._completion_url()
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You translate DayZ stringtable entries and return JSON only."},
                    {"role": "user", "content": build_multi_translation_prompt(request)},
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API 请求失败: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"API 请求失败: {exc}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"API 返回格式无法识别: {payload}") from exc
        return parse_multi_translation_response(str(content), [target.target_language for target in request.targets])

    def _completion_url(self) -> str:
        url = self.base_url.rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        if url.endswith("/v1"):
            return f"{url}/chat/completions"
        return f"{url}/v1/chat/completions"


class AzureTranslator(AITranslator):
    def __init__(
        self,
        key: str,
        endpoint: str = "https://api.cognitive.microsofttranslator.com",
        region: str = "",
        timeout_seconds: int = 60,
    ):
        self.key = key.strip()
        self.endpoint = endpoint.strip() or "https://api.cognitive.microsofttranslator.com"
        self.region = region.strip()
        self.timeout_seconds = timeout_seconds

    def translate(self, request: TranslationRequest) -> str:
        if not self.key:
            raise ValueError("缺少 Azure Translator key")
        url = self._translate_url(request)
        body = json.dumps([{"Text": request.source_text}]).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": self.key,
        }
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region
        http_request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Azure 翻译请求失败: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Azure 翻译请求失败: {exc}") from exc
        try:
            content = payload[0]["translations"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Azure 翻译返回格式无法识别: {payload}") from exc
        return clean_ai_text(str(content))

    def _translate_url(self, request: TranslationRequest) -> str:
        source_code = MICROSOFT_LANGUAGE_CODES.get(request.source_language, request.source_language)
        target_code = MICROSOFT_LANGUAGE_CODES.get(request.target_language, request.target_language)
        query = {"api-version": "3.0", "to": target_code}
        if source_code != "auto":
            query["from"] = source_code
        endpoint = self.endpoint.rstrip("/")
        if endpoint.endswith("/translator/text/v3.0"):
            base = f"{endpoint}/translate"
        elif endpoint.endswith("/translate"):
            base = endpoint
        elif endpoint.endswith(".cognitiveservices.azure.com"):
            base = f"{endpoint}/translator/text/v3.0/translate"
        else:
            base = f"{endpoint}/translate"
        return f"{base}?{urllib.parse.urlencode(query)}"


class BingFreeTranslator(AITranslator):
    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    def translate(self, request: TranslationRequest) -> str:
        source_code = MICROSOFT_LANGUAGE_CODES.get(request.source_language, "auto")
        target_code = MICROSOFT_LANGUAGE_CODES.get(request.target_language, request.target_language)
        query = {"api-version": "3.0", "to": target_code}
        if source_code != "auto":
            query["from"] = source_code
        token = self._fetch_auth_token()
        url = f"https://api.cognitive.microsofttranslator.com/translate?{urllib.parse.urlencode(query)}"
        body = json.dumps([{"Text": request.source_text}]).encode("utf-8")
        http_request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari Edg",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Bing 免费翻译请求失败: HTTP {exc.code} {detail}。非官方免费源可能失效或被限流。") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Bing 免费翻译请求失败: {exc}。非官方免费源可能失效或被限流。") from exc
        try:
            content = payload[0]["translations"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Bing 免费翻译返回格式无法识别: {payload}。非官方免费源可能失效或被限流。") from exc
        return clean_ai_text(str(content))

    def _fetch_auth_token(self) -> str:
        http_request = urllib.request.Request(
            "https://edge.microsoft.com/translate/auth",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari Edg"},
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                token = response.read().decode("utf-8").strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Bing 免费翻译授权失败: HTTP {exc.code} {detail}。非官方免费源可能失效或被限流。") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Bing 免费翻译授权失败: {exc}。非官方免费源可能失效或被限流。") from exc
        if not token:
            raise RuntimeError("Bing 免费翻译授权失败: 返回空 token。非官方免费源可能失效或被限流。")
        return token


class YandexFreeTranslator(AITranslator):
    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    def translate(self, request: TranslationRequest) -> str:
        source_code = YANDEX_LANGUAGE_CODES.get(request.source_language, request.source_language)
        target_code = YANDEX_LANGUAGE_CODES.get(request.target_language, request.target_language)
        lang = target_code if source_code == "auto" else f"{source_code}-{target_code}"
        sid = f"{uuid.uuid4().hex}-0-0"
        query = urllib.parse.urlencode({"sid": sid, "srv": "android", "format": "text"})
        body = urllib.parse.urlencode({"text": request.source_text, "lang": lang}).encode("utf-8")
        url = f"http://translate.yandex.net/api/v1/tr.json/translate?{query}"
        http_request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "ru.yandex.translate/22.11.8.22364114 (samsung SM-A505GM; Android 12)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Yandex 免费翻译请求失败: HTTP {exc.code} {detail}。非官方免费源可能失效或被限流。") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Yandex 免费翻译请求失败: {exc}。非官方免费源可能失效或被限流。") from exc
        if payload.get("code") not in (None, 200):
            message = payload.get("message") or payload
            raise RuntimeError(f"Yandex 免费翻译请求失败: {message}。非官方免费源可能失效或被限流。")
        try:
            content = payload["text"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Yandex 免费翻译返回格式无法识别: {payload}。非官方免费源可能失效或被限流。") from exc
        return clean_ai_text(str(content))


class OpencodeCliTranslator(AITranslator):
    def __init__(self, executable_path: str, extra_args: str = "", timeout_seconds: int = 120, port: int = 0, model: str = ""):
        self.executable_path = executable_path.strip()
        self.extra_args = extra_args.strip()
        self.timeout_seconds = timeout_seconds
        self.port = max(0, int(port))
        self.model = model.strip()
        self._lock = threading.Lock()

    def translate(self, request: TranslationRequest) -> str:
        return self._run_prompt(build_translation_prompt(request))

    def translate_many(self, request: MultiTranslationRequest) -> dict[str, str]:
        if len(request.targets) == 1:
            target = request.targets[0]
            return {target.target_language: self.translate(target)}
        results: dict[str, str] = {}
        for target in request.targets:
            results[target.target_language] = self.translate(target)
        return results

    def _run_prompt(self, prompt: str) -> str:
        if not self.executable_path:
            raise ValueError("缺少 Opencode 可执行文件路径")
        command = [self.executable_path, "run"]
        if self.port:
            command.extend(["--port", str(self.port)])
        if self.model:
            command.extend(["--model", self.model])
        if self.extra_args:
            command.extend(shlex.split(self.extra_args, posix=False))
        if "--print-logs" not in command:
            command.append("--print-logs")
        if "--pure" not in command:
            command.append("--pure")
        command.append(prompt)
        try:
            with self._lock:
                completed = subprocess.run(
                    command,
                    input="",
                    text=True,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                    check=False,
                    **hidden_subprocess_kwargs(),
                )
        except subprocess.TimeoutExpired as exc:
            detail = clean_process_error(f"{_process_text(exc.stderr)}\n{_process_text(exc.output)}")
            if not detail:
                detail = "未收到可用错误输出"
            raise RuntimeError(f"Opencode 在 {self.timeout_seconds} 秒内没有返回: {detail}") from exc
        if completed.returncode != 0:
            stderr = clean_process_error(completed.stderr or completed.stdout)
            raise RuntimeError(f"Opencode 退出码 {completed.returncode}: {stderr}")
        output = clean_ai_text(completed.stdout)
        if re.search(r"(^|\n)Error:", output) or '"type":"error"' in output:
            raise RuntimeError(f"Opencode 请求失败: {clean_process_error(output)}")
        if not output:
            raise RuntimeError("Opencode 返回了空翻译")
        return output


class GoogleTranslateTranslator(AITranslator):
    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    def translate(self, request: TranslationRequest) -> str:
        source_code = LANGUAGE_CODES.get(request.source_language, "auto")
        target_code = LANGUAGE_CODES.get(request.target_language, request.target_language)
        query = urllib.parse.urlencode(
            {
                "client": "gtx",
                "sl": source_code,
                "tl": target_code,
                "dt": "t",
                "q": request.source_text,
            }
        )
        url = f"https://translate.googleapis.com/translate_a/single?{query}"
        http_request = urllib.request.Request(url, headers={"User-Agent": "DayZTranslateTool/0.1"})
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google 翻译请求失败: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Google 翻译请求失败: {exc}") from exc
        try:
            pieces = [part[0] for part in payload[0] if part and part[0]]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Google 翻译返回格式无法识别: {payload}") from exc
        return clean_ai_text("".join(pieces))
