"""DayZ Translate Tool 的命令行入口：给 AI（和人）用的无界面操作方式。

用法：python cli.py <命令> [参数]，完整清单见 README 的「命令行」一节。
退出码：0 = 成功；1 = 部分失败（有没翻好的行）；2 = 彻底失败（参数错、文件读不了、没有可用源）。
提示文案与 JSON 字段一律用英文，避免 Windows 终端中文乱码。
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import translation_flow as flow
from dayz_csv import (
    header_index,
    is_copy_only_column,
    language_code_for_header,
    load_dayz_csv,
    write_dayz_csv,
)
from translation_sources import ALL_RULES, SourceEntry, SourceList

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_FAIL = 2

# 界面启动时只读一次配置，命令行改完得重开界面才看得到
RESTART_HINT = " (restart the app window to see the change)"


def _restart_required(data):
    """改配置的命令用：JSON 模式下 RESTART_HINT 只拼在文本里，根本看不到，

    所以额外塞一个机器能读的标记，让 AI 记得提醒用户重开界面。
    """
    data["restart_required"] = True
    return data


class CliError(Exception):
    """参数或环境问题：打印一句话就退出，退出码 2。"""


class Reporter:
    """结果走 stdout，进度日志走 stderr。"""

    def __init__(self, json_mode=False, quiet=False):
        self.json_mode = json_mode
        self.quiet = quiet

    def info(self, message):
        if not self.quiet:
            print(message, file=sys.stderr, flush=True)

    def emit(self, payload, text):
        if self.json_mode:
            # ensure_ascii=True：结果必须是纯 ASCII。Windows 控制台默认 GBK，
            # 直接把非 ASCII 写进 stdout 会按 GBK 编码，AI 按 UTF-8 读就废了。
            print(json.dumps(payload, ensure_ascii=True, indent=2))
        else:
            print(text)


def envelope(command, path=None, data=None, warnings=None, errors=None):
    return {
        "ok": not errors,
        "command": command,
        "file": str(path) if path else None,
        "data": data or {},
        "warnings": list(warnings or []),
        "errors": list(errors or []),
    }


# —— 参数小工具 ——

def parse_rows(text):
    """`'3,5-9'` → `[3, 5, 6, 7, 8, 9]`（数据行号，从 1 开始；去重升序）。"""
    rows = set()
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, _sep, end_text = part.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                raise CliError(f"bad row range: {part}")
            if start < 1 or end < start:
                raise CliError(f"bad row range: {part}")
            rows.update(range(start, end + 1))
        else:
            try:
                value = int(part)
            except ValueError:
                raise CliError(f"bad row number: {part}")
            if value < 1:
                raise CliError(f"bad row number: {part}")
            rows.add(value)
    if not rows:
        raise CliError("no rows given")
    return sorted(rows)


def resolve_columns(headers, text):
    """`'chinesesimp,zh-CN'` → 列下标列表。既认表头名，也认语言代码，**都不区分大小写**。

    语言代码有歧义时（`chinese` 和 `chinesesimp` 都映射 `zh-CN`）直接报错并列出候选列名，
    不替用户瞎猜。
    """
    indexes = []
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            indexes.append(header_index(headers, part))
            continue
        except ValueError:
            pass
        wanted = part.lower()
        matches = [index for index, header in enumerate(headers)
                   if (language_code_for_header(header) or "").lower() == wanted]
        if not matches:
            raise CliError(f"unknown column: {part}")
        if len(matches) > 1:
            names = ", ".join(headers[index] for index in matches)
            raise CliError(f"column {part} is ambiguous, it matches: {names}")
        indexes.append(matches[0])
    if not indexes:
        raise CliError("no columns given")
    return sorted(set(indexes))


def _single_column(headers, text):
    """`edit` 的命令一次只改一列。

    `--column english,chinesesimp` 会被 `resolve_columns` 排成 `[2, 14]`，再取 `[0]`
    就变成「静默只改 english」—— 直接报错比让 AI 以为两列都改了安全。
    """
    indexes = resolve_columns(headers, text)
    if len(indexes) > 1:
        names = ", ".join(headers[index] for index in indexes)
        raise CliError(f"this command takes one column, got: {names}")
    return indexes[0]


def parse_rules(text):
    """`'all,empty'` → `['all', 'empty']`；不写就默认 `['selection']`。"""
    if text is None:
        return ["selection"]
    rules = [part.strip() for part in str(text).split(",") if part.strip()]
    for rule in rules:
        if rule not in ALL_RULES:
            raise CliError(f"unknown rule: {rule} (choose from {', '.join(ALL_RULES)})")
    return rules


def load_table(path):
    if not Path(path).exists():
        raise CliError(f"file not found: {path}")
    headers, rows, warnings = load_dayz_csv(path)
    if not headers:
        raise CliError(f"not a DayZ stringtable csv: {path}")
    return headers, rows, warnings


def default_preview_path(path):
    path = Path(path)
    return path.with_name(f"{path.stem}.preview{path.suffix}")


def _check_preview_target(args, path):
    """不加 `--write` 时原文件必须一字不动，预览路径指回原文件就是无备份覆盖。

    翻译命令要在联网之前先调一次：不然会先翻完、写完缓存，最后才报错，白跑一趟。
    """
    if getattr(args, "write", False) or not getattr(args, "preview", None):
        return
    if Path(args.preview).resolve() == Path(path).resolve():
        raise CliError("--preview must not point at the source file; pass --write to overwrite it")


def apply_changes(args, reporter, path, headers, rows, data):
    """统一出口：`--write` 就备份后写回，否则只写预览文件。"""
    _check_preview_target(args, path)
    if getattr(args, "write", False):
        backup = Path(f"{path}.bak")
        shutil.copy2(path, backup)
        write_dayz_csv(path, headers, rows)
        reporter.info(f"wrote {path} (backup: {backup})")
        data.update({"written": True, "backup": str(backup), "preview": None})
    else:
        preview = Path(args.preview) if getattr(args, "preview", None) else default_preview_path(path)
        write_dayz_csv(preview, headers, rows)
        reporter.info(f"preview: {preview} (original file untouched; pass --write to save)")
        data.update({"written": False, "backup": None, "preview": str(preview)})
    return data


# —— inspect ——

def cmd_inspect(args, reporter):
    path = Path(args.file)
    headers, rows, warnings = load_table(path)
    settings = flow.load_app_settings()
    columns = []
    for index, header in enumerate(headers):
        if index == 0 or not header.strip():
            continue
        code = language_code_for_header(header)
        if not code:
            continue
        translated = sum(1 for row in rows if _cell(row, index))
        columns.append({
            "index": index,
            "header": header,
            "language": code,
            "translated": translated,
            "empty": len(rows) - translated,
        })
    try:
        source_index = header_index(headers, settings.source_header)
    except ValueError:
        source_index = None
    missing_source = [index + 1 for index, row in enumerate(rows)
                      if source_index is None or not _cell(row, source_index)]
    empty_rows = [index + 1 for index, row in enumerate(rows) if not any(_cell(row, i) for i in range(len(headers)))]
    data = {
        "headers": list(headers),
        "rows": len(rows),
        "source_header": settings.source_header,
        "columns": columns,
        "rows_missing_source": missing_source,
        "empty_rows": empty_rows,
    }
    lines = [f"file: {path}", f"rows: {len(rows)}", f"source column: {settings.source_header}"]
    for item in columns:
        lines.append(f"  {item['header']:<14} {item['language']:<8} "
                     f"translated {item['translated']} / empty {item['empty']}")
    lines.append(f"rows missing source text: {_join(missing_source)}")
    lines.append(f"empty rows: {_join(empty_rows)}")
    reporter.emit(envelope("inspect", path, data, warnings), "\n".join(lines))
    return EXIT_OK


def _cell(row, index):
    if index < 0 or index >= len(row):
        return ""
    return (row[index] or "").strip()


def _join(values):
    return ", ".join(str(value) for value in values) if values else "(none)"


# —— translate ——

def make_cache_store():
    """单测会把 cli.make_cache_store 换掉，避免碰到用户本机的真缓存。"""
    from translation_cache import TranslationCacheStore
    return TranslationCacheStore()


def cmd_translate(args, reporter):
    path = Path(args.file)
    _check_preview_target(args, path)
    headers, rows, warnings = load_table(path)
    settings = flow.load_app_settings()
    source_header = args.from_column or settings.source_header
    try:
        header_index(headers, source_header)
    except ValueError:
        raise CliError(f"source column not found in file: {source_header}")
    # 复制列（original←english、chinese←chinesesimp）先填再挑任务 —— 跟界面那四个入口
    # 不一样（界面是拿填之前的快照挑任务）。这样 `--from-column original` 时 original
    # 原本空着也能翻；界面在同样情况下会挑出 0 条。这是有意为之，别「对齐」成快照。
    rows, _changed = flow.fill_copy_columns(
        headers, rows, overwrite=args.mode == flow.MODE_ALL)
    columns = resolve_columns(headers, args.columns) if args.columns else None
    if columns:
        for index in columns:
            if is_copy_only_column(headers[index]):
                # 点名一个自动复制列（original / chinese）会挑出 0 条任务，说清楚免得当成功
                warnings.append(f"column {headers[index]} is filled automatically, "
                                "it is never translated")
    row_indexes = None
    if args.rows:
        row_indexes = []
        for value in parse_rows(args.rows):
            if value > len(rows):
                raise CliError(f"row out of range: {value} (file has {len(rows)} data rows)")
            row_indexes.append(value - 1)
    jobs = flow.collect_jobs(headers, rows, source_header, mode=args.mode,
                             columns=columns, row_indexes=row_indexes, only_empty=args.only_empty)
    reporter.info(f"jobs: {len(jobs)}")
    glossary = flow.build_glossary(_load_wordbook_rows(args.wordbook))
    try:
        configs = flow.build_translation_configs(
            settings.sources, flow.rule_for_mode(args.mode),
            char_budget=settings.char_budget, timeout=settings.timeout,
            glossary=glossary, glossary_source_key=source_header, source_id=args.source)
    except ValueError as exc:
        raise CliError(str(exc))
    if not configs:
        if args.source:
            raise CliError(f"source {args.source} is not enabled for mode {args.mode} "
                           "(check its rules with: sources list)")
        raise CliError("no translation source is enabled for this mode "
                       "(check the rules in Settings, or pass --source)")
    data = {"rows": len(rows), "jobs": len(jobs)}
    if not jobs:
        # 没有任务时原文件不可能变，所以不写预览文件；字段和正常分支保持同一套
        data.update({"translated": 0, "failed": 0, "cache_hits": 0, "failed_cells": [],
                     "errors": [], "written": False, "backup": None, "preview": None})
        reporter.emit(envelope("translate", path, data, warnings), "nothing to translate")
        return EXIT_OK

    cache_store = make_cache_store()
    cache = cache_store.load()
    results = flow.run_translation(
        jobs, configs, source_header, cache=cache,
        progress_callback=lambda results: reporter.info(
            f"translated {results.translated}, failed {results.failed}, cache hits {results.cache_hits}"),
        on_fallback=lambda previous, current: reporter.info(f"fallback: {previous} -> {current}"),
    )
    cache_store.save(cache)
    rows = flow.apply_results(headers, rows, results)
    failed = flow.failed_cells(jobs, results)
    failed_set = set(failed)
    data.update({
        "translated": results.translated,
        "failed": len(failed),
        "cache_hits": results.cache_hits,
        "failed_cells": [
            {"row": row + 1, "column": column, "header": headers[column] if column < len(headers) else "",
             "text": text}
            for row, column, text, _target in jobs if (row, column) in failed_set
        ],
        "errors": results.errors[:5],
    })
    apply_changes(args, reporter, path, headers, rows, data)
    if data["written"]:
        where = f"wrote {path} (backup: {data['backup']})"
    else:
        where = f"preview {data['preview']}"
    text = f"translated {results.translated}, failed {len(failed)}, {where}"
    # 有翻不出来的格子就算部分失败，信封里也要能看出来（只看 ok 的 AI 不会误判成功）
    errors = [f"{len(failed)} cell(s) failed"] if failed else []
    reporter.emit(envelope("translate", path, data, warnings, errors=errors), text)
    return EXIT_PARTIAL if failed else EXIT_OK


def _load_wordbook_rows(path=None):
    """词表存在就拿来当术语表；不存在就是空的，不算错误。"""
    from wordbook_csv import load_wordbook_csv

    wordbook = Path(path) if path else flow.config_dir() / "wordbook.csv"
    if not wordbook.exists():
        return []
    _headers, rows = load_wordbook_csv(wordbook)
    return rows


# —— edit ——

def cmd_edit_set_cell(args, reporter):
    path = Path(args.file)
    headers, rows, warnings = load_table(path)
    if args.row < 1 or args.row > len(rows):
        raise CliError(f"row out of range: {args.row} (file has {len(rows)} data rows)")
    column = _single_column(headers, args.column)
    row_index = args.row - 1
    before = _cell(rows[row_index], column)
    _set_cell(rows[row_index], column, args.text)
    data = {"changes": [{"row": args.row, "column": column, "header": headers[column],
                         "before": before, "after": args.text}]}
    apply_changes(args, reporter, path, headers, rows, data)
    reporter.emit(envelope("edit set-cell", path, data, warnings),
                  f"row {args.row} {headers[column]}: {before!r} -> {args.text!r}")
    return EXIT_OK


def cmd_edit_replace(args, reporter):
    path = Path(args.file)
    headers, rows, warnings = load_table(path)
    column = _single_column(headers, args.column)
    flags = re.IGNORECASE if args.ignore_case else 0
    pattern = args.find if args.regex else re.escape(args.find)
    if args.whole_word:
        pattern = rf"\b{pattern}\b"
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise CliError(f"bad pattern: {exc}")
    changes = []
    for row_index, row in enumerate(rows):
        before = _cell(row, column)
        if not before:
            continue
        after = regex.sub(args.replace, before)
        if after == before:
            continue
        _set_cell(row, column, after)
        changes.append({"row": row_index + 1, "column": column, "header": headers[column],
                        "before": before, "after": after})
    data = {"changes": changes, "count": len(changes)}
    apply_changes(args, reporter, path, headers, rows, data)
    reporter.emit(envelope("edit replace", path, data, warnings), f"replaced {len(changes)} cell(s)")
    return EXIT_OK


def cmd_edit_add_row(args, reporter):
    path = Path(args.file)
    headers, rows, warnings = load_table(path)
    if not args.key:
        # 整行全空的行保存时会被 dayz_rows_for_save 丢掉，不给键名就加不出东西来 ——
        # 与其报一个盘上不存在的 added_row，不如直接报错。
        raise CliError("edit add-row needs --key")
    new_row = [""] * len(headers)
    _set_cell(new_row, 0, args.key)
    if args.after is None:
        rows.append(new_row)
        position = len(rows)
    else:
        if args.after < 0 or args.after > len(rows):
            raise CliError(f"--after out of range: {args.after}")
        rows.insert(args.after, new_row)
        position = args.after + 1
    data = {"added_row": position, "key": args.key or ""}
    apply_changes(args, reporter, path, headers, rows, data)
    reporter.emit(envelope("edit add-row", path, data, warnings), f"added row {position}")
    return EXIT_OK


def cmd_edit_delete_row(args, reporter):
    path = Path(args.file)
    headers, rows, warnings = load_table(path)
    if args.row is not None and args.key is not None:
        raise CliError("edit delete-row takes --row or --key, not both")
    if args.row is not None:
        if args.row < 1 or args.row > len(rows):
            raise CliError(f"row out of range: {args.row} (file has {len(rows)} data rows)")
        indexes = [args.row - 1]
    elif args.key is not None:
        indexes = [index for index, row in enumerate(rows) if _cell(row, 0) == args.key]
        if not indexes:
            raise CliError(f"no row with key: {args.key}")
    else:
        raise CliError("edit delete-row needs --row or --key")
    deleted = [{"row": index + 1, "key": _cell(rows[index], 0)} for index in indexes]
    for index in sorted(indexes, reverse=True):
        del rows[index]
    data = {"deleted": [item["key"] for item in deleted], "rows": deleted}
    apply_changes(args, reporter, path, headers, rows, data)
    reporter.emit(envelope("edit delete-row", path, data, warnings),
                  f"deleted {len(deleted)} row(s)")
    return EXIT_OK


def _set_cell(row, column, text):
    while len(row) <= column:
        row.append("")
    row[column] = text


# —— keys ——

def cmd_keys(args, reporter):
    from config_cpp import collect_config_cpp_files, extract_keys_from_paths, merge_language_keys

    path = Path(args.file)
    headers, rows, warnings = load_table(path)
    # --from 可以给 config.cpp，也可以给文件夹（文件夹要自己展开，extract_keys_from_paths 不展开）
    sources = []
    for value in args.from_paths:
        source = Path(value)
        if not source.exists():
            raise CliError(f"path not found: {source}")
        if source.is_dir():
            found = collect_config_cpp_files(source)
            if not found:
                raise CliError(f"no config.cpp found under: {source}")
            sources.extend(found)
        else:
            sources.append(source)
    keys, file_warnings = extract_keys_from_paths(sources)
    merged, added, skipped = merge_language_keys(rows, keys)
    data = {"keys_found": len(keys), "added": added, "skipped": skipped}
    apply_changes(args, reporter, path, headers, merged, data)
    reporter.emit(envelope("keys", path, data, warnings + file_warnings),
                  f"added {added} key(s), skipped {skipped}")
    return EXIT_OK


# —— wordbook ——

def _wordbook_path(args):
    value = getattr(args, "wordbook", None)
    return Path(value) if value else flow.config_dir() / "wordbook.csv"


def cmd_wordbook_list(args, reporter):
    from wordbook_csv import load_wordbook_csv

    path = _wordbook_path(args)
    if path.exists():
        headers, rows = load_wordbook_csv(path)
    else:
        headers, rows = [], []
    data = {"wordbook": str(path), "headers": list(headers), "count": len(rows), "rows": rows}
    lines = [f"wordbook: {path}", f"entries: {len(rows)}"]
    for row in rows:
        lines.append("  " + " | ".join(row))
    reporter.emit(envelope("wordbook list", path, data), "\n".join(lines))
    return EXIT_OK


def cmd_wordbook_set(args, reporter):
    from wordbook_csv import WORDBOOK_HEADERS, load_wordbook_csv, write_wordbook_csv

    path = _wordbook_path(args)
    if args.language not in WORDBOOK_HEADERS:
        raise CliError(f"unknown language column: {args.language}")
    column = WORDBOOK_HEADERS.index(args.language)
    _headers, rows = load_wordbook_csv(path) if path.exists() else (list(WORDBOOK_HEADERS), [])
    created = True
    for row in rows:
        if (row[0] or "").strip() == args.original:
            created = False
            _set_cell(row, column, args.text)
            break
    if created:
        new_row = [""] * len(WORDBOOK_HEADERS)
        new_row[0] = args.original
        new_row[column] = args.text
        rows.append(new_row)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_wordbook_csv(path, rows)
    data = {"wordbook": str(path), "created": created, "original": args.original,
            "language": args.language, "text": args.text, "count": len(rows)}
    reporter.emit(envelope("wordbook set", path, data),
                  f"{'added' if created else 'updated'} {args.original} -> {args.text}")
    return EXIT_OK


def cmd_wordbook_remove(args, reporter):
    from wordbook_csv import load_wordbook_csv, write_wordbook_csv

    path = _wordbook_path(args)
    if not path.exists():
        raise CliError(f"wordbook not found: {path}")
    _headers, rows = load_wordbook_csv(path)
    kept = [row for row in rows if (row[0] or "").strip() != args.original]
    removed = len(rows) - len(kept)
    if not removed:
        raise CliError(f"no wordbook entry for: {args.original}")
    write_wordbook_csv(path, kept)
    data = {"wordbook": str(path), "removed": removed, "count": len(kept)}
    reporter.emit(envelope("wordbook remove", path, data), f"removed {removed} entry")
    return EXIT_OK


def cmd_wordbook_import(args, reporter):
    from wordbook_csv import WORDBOOK_HEADERS, load_wordbook_csv, write_wordbook_csv

    path = _wordbook_path(args)
    source = Path(args.file)
    if not source.exists():
        raise CliError(f"file not found: {source}")
    _headers, incoming = load_wordbook_csv(source)
    _headers, rows = load_wordbook_csv(path) if path.exists() else (list(WORDBOOK_HEADERS), [])
    known = {(row[0] or "").strip(): row for row in rows}
    imported = 0
    for row in incoming:
        original = (row[0] or "").strip()
        if not original:
            continue
        target = known.get(original)
        if target is None:
            target = [""] * len(WORDBOOK_HEADERS)
            target[0] = original
            rows.append(target)
            known[original] = target
        for column in range(1, min(len(row), len(WORDBOOK_HEADERS))):
            value = (row[column] or "").strip()
            if value:
                _set_cell(target, column, value)
        imported += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    write_wordbook_csv(path, rows)
    data = {"wordbook": str(path), "imported": imported, "count": len(rows)}
    reporter.emit(envelope("wordbook import", path, data), f"imported {imported} entr(ies)")
    return EXIT_OK


def cmd_wordbook_export(args, reporter):
    from wordbook_csv import load_wordbook_csv, write_wordbook_csv

    path = _wordbook_path(args)
    if not path.exists():
        raise CliError(f"wordbook not found: {path}")
    _headers, rows = load_wordbook_csv(path)
    target = Path(args.file)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_wordbook_csv(target, rows)
    data = {"wordbook": str(path), "exported": len(rows), "target": str(target)}
    reporter.emit(envelope("wordbook export", target, data), f"exported {len(rows)} entr(ies) to {target}")
    return EXIT_OK


# —— sources ——

def _source_entries(sources):
    items = []
    for position, entry in enumerate(sources.entries, start=1):
        spec = flow.FREE_SOURCE_SPECS.get(entry.source_id, {}) if not entry.is_ai else {}
        items.append({
            "order": position,
            "id": entry.source_id,
            "kind": entry.kind,
            "name": entry.name or entry.source_id,
            "api_type": entry.api_type,
            "rules": list(entry.rules),
            "has_key": bool(entry.api_key),
            "needs_key": bool(spec.get("needs_key")),
            "concurrency": entry.concurrency,
            "interval": entry.interval,
        })
    return items


def cmd_sources_list(args, reporter):
    settings = flow.load_app_settings()
    items = _source_entries(settings.sources)
    data = {"count": len(items), "sources": items}
    lines = ["id            kind  rules                 name"]
    for item in items:
        lines.append(f"{item['id']:<13} {item['kind']:<5} {','.join(item['rules']):<21} {item['name']}")
    reporter.emit(envelope("sources list", None, data), "\n".join(lines))
    return EXIT_OK


def cmd_sources_test(args, reporter):
    settings = flow.load_app_settings()
    entries = settings.sources.entries
    if args.source:
        entry = settings.sources.find(args.source)
        if entry is None:
            raise CliError(f"unknown source id: {args.source}")
        entries = [entry]
    if not entries:
        raise CliError("no translation source configured")
    source_header = settings.source_header
    jobs = flow.build_test_jobs(source_header)
    glossary = flow.build_glossary(_load_wordbook_rows(args.wordbook))
    results = []
    for entry in entries:
        config = flow.build_source_config(entry, char_budget=settings.char_budget,
                                          timeout=settings.timeout, label=entry.name or entry.source_id,
                                          glossary=glossary, glossary_source_key=source_header)
        reporter.info(f"testing {entry.source_id} ...")
        outcome = flow.run_translation(jobs, [config], source_header, retry_policy=flow.TEST_RETRY_POLICY)
        translated = len(outcome.cell_results)
        results.append({
            "id": entry.source_id,
            "name": entry.name or entry.source_id,
            "translated": translated,
            "total": len(jobs),
            "ok": translated > 0,
            "errors": outcome.errors[:3],
        })
    data = {"source_header": source_header, "results": results}
    lines = [f"{item['id']}: {item['translated']}/{item['total']} "
             f"{'ok' if item['ok'] else 'FAILED'}" for item in results]
    for item in results:
        for message in item["errors"]:
            lines.append(f"  {item['id']}: {message}")
    reporter.emit(envelope("sources test", None, data), "\n".join(lines))
    return EXIT_OK if all(item["ok"] for item in results) else EXIT_PARTIAL


def cmd_sources_add_ai(args, reporter):
    if args.type not in flow.AI_TYPE_KEYS:
        raise CliError(f"unknown api type: {args.type} (choose from {', '.join(flow.AI_TYPE_KEYS)})")
    if not args.name.strip():
        raise CliError("--name is required")
    rules = parse_rules(args.rules)
    settings = flow.load_app_settings()
    entry = SourceEntry(kind="ai", name=args.name.strip(), api_type=args.type, rules=rules,
                        api_key=args.key or "", base_url=args.base_url or "",
                        model=args.model or "", concurrency=max(1, args.concurrency),
                        interval=max(0.0, args.interval))
    settings.sources.add_ai(entry)
    flow.save_sources(settings.sources)
    data = _restart_required({"id": entry.source_id, "name": entry.name, "rules": rules})
    reporter.emit(envelope("sources add-ai", None, data),
                  f"added {entry.source_id} ({entry.name})" + RESTART_HINT)
    return EXIT_OK


def cmd_sources_remove(args, reporter):
    settings = flow.load_app_settings()
    entry = settings.sources.find(args.id)
    if entry is None:
        raise CliError(f"unknown source id: {args.id}")
    settings.sources.remove(args.id)
    flow.save_sources(settings.sources)
    data = _restart_required({"id": args.id, "count": len(settings.sources.entries)})
    reporter.emit(envelope("sources remove", None, data), f"removed {args.id}" + RESTART_HINT)
    return EXIT_OK


def cmd_sources_move(args, reporter):
    if args.up == args.down:
        raise CliError("pass exactly one of --up / --down")
    settings = flow.load_app_settings()
    if settings.sources.find(args.id) is None:
        raise CliError(f"unknown source id: {args.id}")
    if args.up:
        settings.sources.move_up(args.id)
    else:
        settings.sources.move_down(args.id)
    flow.save_sources(settings.sources)
    order = [entry.source_id for entry in settings.sources.entries]
    data = _restart_required({"id": args.id, "order": order})
    reporter.emit(envelope("sources move", None, data),
                  "order: " + ", ".join(order) + RESTART_HINT)
    return EXIT_OK


def cmd_sources_set_rule(args, reporter):
    rules = parse_rules(args.rules)
    settings = flow.load_app_settings()
    if settings.sources.find(args.id) is None:
        raise CliError(f"unknown source id: {args.id}")
    for rule in ALL_RULES:
        settings.sources.set_rule(args.id, rule, rule in rules)
    flow.save_sources(settings.sources)
    entry = settings.sources.find(args.id)
    data = _restart_required({"id": args.id, "rules": list(entry.rules)})
    reporter.emit(envelope("sources set-rule", None, data),
                  f"{args.id}: {', '.join(entry.rules) or '(none)'}" + RESTART_HINT)
    return EXIT_OK


def cmd_sources_set_key(args, reporter):
    settings = flow.load_app_settings()
    entry = settings.sources.find(args.id)
    if entry is None:
        raise CliError(f"unknown source id: {args.id}")
    entry.api_key = args.key or ""
    flow.save_sources(settings.sources)
    data = _restart_required({"id": args.id, "has_key": bool(entry.api_key)})
    reporter.emit(envelope("sources set-key", None, data),
                  f"{args.id}: key {'set' if entry.api_key else 'cleared'}" + RESTART_HINT)
    return EXIT_OK


# —— cache ——

def cmd_cache_stats(args, reporter):
    store = make_cache_store()
    cache = store.load()
    data = {"path": str(store.path), "entries": len(cache), "writable": store.is_writable()}
    reporter.emit(envelope("cache stats", None, data),
                  f"cache: {store.path}\nentries: {len(cache)}")
    return EXIT_OK


def cmd_cache_clear(args, reporter):
    store = make_cache_store()
    before = len(store.load())
    store.clear()
    # TranslationCacheStore.clear() 删不掉时也会静默返回，所以看文件还在不在，别谎报成功
    if store.path.exists():
        raise CliError(f"could not delete the cache file: {store.path}")
    data = {"path": str(store.path), "removed": before, "cleared": True}
    reporter.emit(envelope("cache clear", None, data), f"cleared {before} cached translation(s)")
    return EXIT_OK


# —— 命令行装配 ——

def build_parser():
    parser = argparse.ArgumentParser(prog="cli.py", description="DayZ Translate Tool command line")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="show what is inside a stringtable csv")
    inspect_parser.add_argument("file")
    _add_json(inspect_parser)
    inspect_parser.set_defaults(handler=cmd_inspect)

    translate_parser = subparsers.add_parser("translate", help="translate a stringtable csv")
    translate_parser.add_argument("file")
    translate_parser.add_argument("--mode", choices=list(flow.ALL_MODES), default=flow.MODE_EMPTY)
    translate_parser.add_argument("--columns", help="comma separated column names or language codes")
    translate_parser.add_argument("--rows", help="comma separated row numbers, ranges allowed (1 based)")
    translate_parser.add_argument("--only-empty", action="store_true", help="only fill empty target cells")
    translate_parser.add_argument("--source", help="use only this source id for this run")
    translate_parser.add_argument("--from-column", help="override the source column for this run")
    translate_parser.add_argument("--wordbook", help="path to a wordbook csv (default: the app data one)")
    translate_parser.add_argument("--preview", help="where to write the preview file")
    translate_parser.add_argument("--write", action="store_true", help="save back to the original file")
    _add_json(translate_parser)
    translate_parser.set_defaults(handler=cmd_translate)

    edit_parser = subparsers.add_parser("edit", help="change cells, rows and text in a csv")
    edit_sub = edit_parser.add_subparsers(dest="edit_command", required=True)

    set_cell = edit_sub.add_parser("set-cell")
    set_cell.add_argument("file")
    set_cell.add_argument("--row", type=int, required=True)
    set_cell.add_argument("--column", required=True)
    set_cell.add_argument("--text", required=True)
    _add_write_flags(set_cell)
    set_cell.set_defaults(handler=cmd_edit_set_cell)

    replace = edit_sub.add_parser("replace")
    replace.add_argument("file")
    replace.add_argument("--column", required=True)
    replace.add_argument("--find", required=True)
    replace.add_argument("--replace", required=True)
    replace.add_argument("--regex", action="store_true")
    replace.add_argument("--ignore-case", action="store_true")
    replace.add_argument("--whole-word", action="store_true")
    _add_write_flags(replace)
    replace.set_defaults(handler=cmd_edit_replace)

    add_row = edit_sub.add_parser("add-row")
    add_row.add_argument("file")
    add_row.add_argument("--key")
    add_row.add_argument("--after", type=int)
    _add_write_flags(add_row)
    add_row.set_defaults(handler=cmd_edit_add_row)

    delete_row = edit_sub.add_parser("delete-row")
    delete_row.add_argument("file")
    delete_row.add_argument("--row", type=int)
    delete_row.add_argument("--key")
    _add_write_flags(delete_row)
    delete_row.set_defaults(handler=cmd_edit_delete_row)

    keys_parser = subparsers.add_parser("keys", help="import missing keys from config.cpp")
    keys_parser.add_argument("file")
    keys_parser.add_argument("--from", dest="from_paths", action="append", required=True,
                             help="a config.cpp file or a folder (repeatable)")
    _add_write_flags(keys_parser)
    keys_parser.set_defaults(handler=cmd_keys)

    wordbook_parser = subparsers.add_parser("wordbook", help="read and write the glossary wordbook")
    wordbook_sub = wordbook_parser.add_subparsers(dest="wordbook_command", required=True)

    wb_list = wordbook_sub.add_parser("list")
    wb_list.add_argument("--wordbook")
    _add_json(wb_list)
    wb_list.set_defaults(handler=cmd_wordbook_list)

    wb_set = wordbook_sub.add_parser("set")
    wb_set.add_argument("--original", required=True)
    wb_set.add_argument("--language", required=True)
    wb_set.add_argument("--text", required=True)
    wb_set.add_argument("--wordbook")
    _add_json(wb_set)
    wb_set.set_defaults(handler=cmd_wordbook_set)

    wb_remove = wordbook_sub.add_parser("remove")
    wb_remove.add_argument("--original", required=True)
    wb_remove.add_argument("--wordbook")
    _add_json(wb_remove)
    wb_remove.set_defaults(handler=cmd_wordbook_remove)

    wb_import = wordbook_sub.add_parser("import")
    wb_import.add_argument("file")
    wb_import.add_argument("--wordbook")
    _add_json(wb_import)
    wb_import.set_defaults(handler=cmd_wordbook_import)

    wb_export = wordbook_sub.add_parser("export")
    wb_export.add_argument("file")
    wb_export.add_argument("--wordbook")
    _add_json(wb_export)
    wb_export.set_defaults(handler=cmd_wordbook_export)

    sources_parser = subparsers.add_parser("sources", help="read and edit the translation source list")
    sources_sub = sources_parser.add_subparsers(dest="sources_command", required=True)

    src_list = sources_sub.add_parser("list")
    _add_json(src_list)
    src_list.set_defaults(handler=cmd_sources_list)

    src_test = sources_sub.add_parser("test")
    src_test.add_argument("--source")
    src_test.add_argument("--wordbook")
    _add_json(src_test)
    src_test.set_defaults(handler=cmd_sources_test)

    src_add = sources_sub.add_parser("add-ai")
    src_add.add_argument("--name", required=True)
    src_add.add_argument("--type", required=True)
    src_add.add_argument("--base-url")
    src_add.add_argument("--model")
    src_add.add_argument("--key")
    src_add.add_argument("--concurrency", type=int, default=1)
    src_add.add_argument("--interval", type=float, default=0.0)
    src_add.add_argument("--rules")
    _add_json(src_add)
    src_add.set_defaults(handler=cmd_sources_add_ai)

    src_remove = sources_sub.add_parser("remove")
    src_remove.add_argument("id")
    _add_json(src_remove)
    src_remove.set_defaults(handler=cmd_sources_remove)

    src_move = sources_sub.add_parser("move")
    src_move.add_argument("id")
    src_move.add_argument("--up", action="store_true")
    src_move.add_argument("--down", action="store_true")
    _add_json(src_move)
    src_move.set_defaults(handler=cmd_sources_move)

    src_rule = sources_sub.add_parser("set-rule")
    src_rule.add_argument("id")
    src_rule.add_argument("--rules", required=True)
    _add_json(src_rule)
    src_rule.set_defaults(handler=cmd_sources_set_rule)

    src_key = sources_sub.add_parser("set-key")
    src_key.add_argument("id")
    src_key.add_argument("--key", required=True)
    _add_json(src_key)
    src_key.set_defaults(handler=cmd_sources_set_key)

    cache_parser = subparsers.add_parser("cache", help="inspect or clear the translation cache")
    cache_sub = cache_parser.add_subparsers(dest="cache_command", required=True)

    cache_stats = cache_sub.add_parser("stats")
    _add_json(cache_stats)
    cache_stats.set_defaults(handler=cmd_cache_stats)

    cache_clear = cache_sub.add_parser("clear")
    _add_json(cache_clear)
    cache_clear.set_defaults(handler=cmd_cache_clear)
    return parser


def _add_write_flags(parser):
    parser.add_argument("--preview", help="where to write the preview file")
    parser.add_argument("--write", action="store_true", help="save back to the original file")
    _add_json(parser)


def _add_json(parser):
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--quiet", action="store_true", help="do not print progress logs")


def _make_streams_safe():
    """Windows 控制台默认 GBK，碰到 emoji 之类的字符会抛 UnicodeEncodeError 把命令搞崩。

    只把装不下的字符换成 `?`，结果照样拿得到。（单测里 stdout 被换成 StringIO，
    没有 reconfigure，忽略即可。）
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _make_streams_safe()
    parser = build_parser()
    args = parser.parse_args(argv)
    reporter = Reporter(json_mode=getattr(args, "json", False), quiet=getattr(args, "quiet", False))
    try:
        return args.handler(args, reporter)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
