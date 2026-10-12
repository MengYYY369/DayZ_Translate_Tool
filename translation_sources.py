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
