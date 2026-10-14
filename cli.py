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
from dayz_csv import header_index, language_code_for_header, load_dayz_csv, write_dayz_csv
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
            print(json.dumps(payload, ensure_ascii=False, indent=2))
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


def apply_changes(args, reporter, path, headers, rows, data):
    """统一出口：`--write` 就备份后写回，否则只写预览文件。"""
    if getattr(args, "write", False):
        backup = Path(f"{path}.bak")
        shutil.copy2(path, backup)
        write_dayz_csv(path, headers, rows)
        reporter.info(f"wrote {path} (backup: {backup})")
        data.update({"written": True, "backup": str(backup), "preview": None})
    else:
        preview = Path(args.preview) if getattr(args, "preview", None) else default_preview_path(path)
        if Path(preview).resolve() == Path(path).resolve():
            # 不加 --write 就承诺原文件一字不动；预览路径指回原文件会静默覆盖且不留备份
            raise CliError("--preview must not point at the source file; pass --write to overwrite it")
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


# —— 命令行装配 ——

def build_parser():
    parser = argparse.ArgumentParser(prog="cli.py", description="DayZ Translate Tool command line")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="show what is inside a stringtable csv")
    inspect_parser.add_argument("file")
    _add_json(inspect_parser)
    inspect_parser.set_defaults(handler=cmd_inspect)
    return parser


def _add_json(parser):
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--quiet", action="store_true", help="do not print progress logs")


def main(argv=None):
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
