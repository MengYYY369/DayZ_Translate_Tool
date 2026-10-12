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
