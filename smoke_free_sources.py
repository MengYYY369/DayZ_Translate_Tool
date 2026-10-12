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
