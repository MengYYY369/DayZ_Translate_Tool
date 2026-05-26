import json
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationRequest:
    key: str
    source_language: str
    source_text: str
    target_language: str
    current_target_text: str = ""


@dataclass(frozen=True)
class BatchTranslationResult:
    translated: int
    skipped: int
    failed: list[tuple[int, str]]


class AITranslator:
    def translate(self, request: TranslationRequest) -> str:
        raise NotImplementedError


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


def clean_ai_text(text: str) -> str:
    result = text.strip()
    if result.startswith("```") and result.endswith("```"):
        lines = result.splitlines()
        result = "\n".join(lines[1:-1]).strip()
    if len(result) >= 2 and result[0] == result[-1] and result[0] in {'"', "'"}:
        result = result[1:-1].strip()
    return result


def clean_process_error(text: str) -> str:
    result = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
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

    def _completion_url(self) -> str:
        url = self.base_url.rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        if url.endswith("/v1"):
            return f"{url}/chat/completions"
        return f"{url}/v1/chat/completions"


class OpencodeCliTranslator(AITranslator):
    def __init__(self, executable_path: str, extra_args: str = "", timeout_seconds: int = 120, port: int = 0, model: str = ""):
        self.executable_path = executable_path.strip()
        self.extra_args = extra_args.strip()
        self.timeout_seconds = timeout_seconds
        self.port = max(0, int(port))
        self.model = model.strip()
        self._lock = threading.Lock()

    def translate(self, request: TranslationRequest) -> str:
        if not self.executable_path:
            raise ValueError("缺少 Opencode 可执行文件路径")
        command = [self.executable_path, "run"]
        if self.port:
            command.extend(["--port", str(self.port)])
        if self.model:
            command.extend(["--model", self.model])
        if self.extra_args:
            command.extend(shlex.split(self.extra_args, posix=False))
        prompt = build_translation_prompt(request)
        command.append(prompt)
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
        if completed.returncode != 0:
            stderr = clean_process_error(completed.stderr)
            raise RuntimeError(f"Opencode 退出码 {completed.returncode}: {stderr}")
        output = clean_ai_text(completed.stdout)
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
