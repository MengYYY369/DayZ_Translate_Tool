import json
import shlex
import subprocess
import urllib.error
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
    def __init__(self, executable_path: str, extra_args: str = "", timeout_seconds: int = 120):
        self.executable_path = executable_path.strip()
        self.extra_args = extra_args.strip()
        self.timeout_seconds = timeout_seconds

    def translate(self, request: TranslationRequest) -> str:
        if not self.executable_path:
            raise ValueError("缺少 Opencode 可执行文件路径")
        command = [self.executable_path]
        if self.extra_args:
            command.extend(shlex.split(self.extra_args, posix=False))
        prompt = build_translation_prompt(request)
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise RuntimeError(f"Opencode 退出码 {completed.returncode}: {stderr}")
        output = clean_ai_text(completed.stdout)
        if not output:
            raise RuntimeError("Opencode 返回了空翻译")
        return output
