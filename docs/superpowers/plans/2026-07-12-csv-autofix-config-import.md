# CSV 宽容补齐与 config.cpp 导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打开 CSV 时宽容补齐为完整 DayZ stringtable 列结构；从 config.cpp（多选/文件夹）提取引号内 `$`/`#` 键，按 Language 去重后只填键追加到当前表。

**Architecture:** 解析层无 Qt：`dayz_csv.load_dayz_csv` 改为返回 `(headers, rows, warnings)` 并跳过未知列；新建 `config_cpp.py` 负责读文件、提键、扫目录、`merge_language_keys`。`main.py` 只做菜单、文件对话框、刷新表格与 UI 文案。

**Tech Stack:** Python 3、stdlib `csv`/`re`/`pathlib`、现有 PySide6 GUI、`unittest`（与仓库现有测试一致，不用 pytest）。

**Spec:** `docs/superpowers/specs/2026-07-11-csv-autofix-config-import-design.md`

## Global Constraints

- 不新增第三方依赖。
- 保存路径不改：`write_dayz_csv` 行为保持。
- 导入只追加当前已打开表；无表则 warning 中止。
- 新行仅 `Language` 列有值，其余空。
- 仅解析引号内 `$token` / `#token`；不解析引号外。
- 去重：`Language` 列 `strip` 后比较，大小写敏感。
- 测试命令用 `python -m unittest ...`，不用 pytest。
- 每次 task 完成后 commit；中英文 `UI_TEXT` 同步加键。

## File Structure

| File | Responsibility |
|------|----------------|
| `dayz_csv.py` | 宽容 `_build_header_map` + `load_dayz_csv` 三元组返回 |
| `config_cpp.py` | **新建**：读文本、提键、收集 config.cpp、merge |
| `main.py` | 菜单、load 解包 warnings、导入动作、UI 文案、表格刷新 |
| `tests/test_dayz_csv.py` | 更新 load 用例 + 新宽容用例 |
| `tests/test_config_cpp.py` | **新建**：解析/merge/扫目录 |
| `tests/test_main_gui.py` | 轻量：无表导入拒绝；有表导入增行 dirty |

---

### Task 1: CSV 打开时宽容补齐（`load_dayz_csv`）

**Files:**
- Modify: `dayz_csv.py`（`load_dayz_csv`、`_build_header_map`）
- Modify: `tests/test_dayz_csv.py`
- Modify: `main.py`（仅 `load_file` 解包三元组 + 状态栏 warnings；菜单等留给 Task 3）

**Interfaces:**
- Consumes: 现有 `DAYZ_HEADERS`、`_expand_row`
- Produces:
  - `load_dayz_csv(path) -> tuple[list[str], list[list[str]], list[str]]`
  - `_build_header_map(headers) -> tuple[list[tuple[int, int]], list[str]]`  
    返回 `(column_map, warnings)`；若没有任何合法列则 `ValueError`

- [ ] **Step 1: 改写/新增失败用例（TDD）**

在 `tests/test_dayz_csv.py` 中：

1. 所有 `load_dayz_csv` 调用改为解包三元组：`headers, rows, warnings = load_dayz_csv(path)`。
2. 替换 `test_load_rejects_wrong_dayz_header` 为两个用例（删除旧名）：

```python
def test_load_skips_unknown_columns_with_warning(self):
    path = self.write_sample(
        '"Language","original","english","unknown","chinesesimp",\n'
        '"STR_A","Knife","Knife","x","刀",\n'
    )
    headers, rows, warnings = load_dayz_csv(path)
    self.assertEqual(headers, DAYZ_HEADERS)
    self.assertEqual(rows[0][0], "STR_A")
    self.assertEqual(rows[0][1], "Knife")
    self.assertEqual(rows[0][2], "Knife")
    self.assertEqual(rows[0][14], "刀")
    self.assertTrue(any("unknown" in w for w in warnings))

def test_load_rejects_header_with_no_known_dayz_columns(self):
    path = self.write_sample('"id","foo","bar",\n"1","a","b",\n')
    with self.assertRaises(ValueError):
        load_dayz_csv(path)

def test_load_without_language_column_still_maps_known_languages(self):
    path = self.write_sample(
        '"original","english","chinesesimp",\n'
        '"Knife","Knife","刀",\n'
    )
    headers, rows, warnings = load_dayz_csv(path)
    self.assertEqual(headers, DAYZ_HEADERS)
    self.assertEqual(rows[0][0], "")  # no Language column in source
    self.assertEqual(rows[0][1], "Knife")
    self.assertEqual(rows[0][2], "Knife")
    self.assertEqual(rows[0][14], "刀")

def test_load_full_header_returns_empty_warnings(self):
    path = self.write_sample(
        '"Language","original","english","czech","german","russian","polish","hungarian","italian","spanish","french","chinese","japanese","portuguese","chinesesimp",\n'
        '"STR_A","Knife","Knife","","","","","","","","","","","","",\n'
    )
    headers, rows, warnings = load_dayz_csv(path)
    self.assertEqual(headers, DAYZ_HEADERS)
    self.assertEqual(warnings, [])
    self.assertEqual(rows[0][0], "STR_A")
```

同步改现有 `test_load_uses_fixed_dayz_headers` / `test_load_expands_partial_dayz_header` 为三元组解包（可 assert `warnings == []` 或忽略 warnings）。

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
python -m unittest tests.test_dayz_csv -v
```

Expected: 新用例 FAIL（仍两元组或仍拒绝未知列/非 Language 首列）。

- [ ] **Step 3: 实现宽容 `load`**

改 `dayz_csv.py` 中 `_build_header_map` 与 `load_dayz_csv` 为：

```python
def load_dayz_csv(path):
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        raise ValueError("CSV file is empty.")

    column_map, warnings = _build_header_map(rows[0])
    return list(DAYZ_HEADERS), [_expand_row(row, column_map) for row in rows[1:]], warnings


def _build_header_map(headers):
    fixed_indexes = {header: index for index, header in enumerate(DAYZ_HEADERS)}
    column_map = []
    warnings = []
    known_count = 0

    for source_index, header in enumerate(headers):
        if header == "" and source_index == len(headers) - 1:
            column_map.append((source_index, len(DAYZ_HEADERS) - 1))
            known_count += 1
            continue
        if header in fixed_indexes:
            column_map.append((source_index, fixed_indexes[header]))
            known_count += 1
            continue
        warnings.append(f'Skipped unsupported DayZ language column "{header}".')

    if known_count == 0:
        raise ValueError("No supported DayZ stringtable columns were found.")

    return column_map, warnings
```

要点：

- **删除**「首列必须是 `Language`」硬门槛。
- 未知列只进 `warnings`，不进 `column_map`。
- 至少识别 1 个合法列（含尾空列映射）才成功。

- [ ] **Step 4: 更新 `main.load_file` 解包**

`main.py` 的 `load_file`：

```python
def load_file(self, path):
    try:
        headers, rows, warnings = load_dayz_csv(path)
    except Exception as exc:
        QMessageBox.critical(self, self.tr("open_failed"), str(exc))
        return

    self.headers = headers
    self.current_path = Path(path)
    # ... 现有填表逻辑不变 ...
    self.set_dirty(False)
    message = self.tr("loaded", path=self.current_path)
    if warnings:
        message = f"{message} | " + "; ".join(warnings)
    self.statusBar().showMessage(message, 8000)
```

本 task **不**加 import 菜单。

- [ ] **Step 5: 跑测试通过**

```bash
python -m unittest tests.test_dayz_csv -v
```

Expected: PASS。

若 `tests.test_main_gui` 因默认打开 `stringtable.csv` 仍工作，可顺带：

```bash
python -m unittest tests.test_main_gui -v
```

Expected: 若 load 三元组未更新会 FAIL；Step 4 后应 PASS。

- [ ] **Step 6: Commit**

```bash
git add dayz_csv.py tests/test_dayz_csv.py main.py
git commit -m "feat: tolerant DayZ CSV load with column autofill and skip-unknown"
```

---

### Task 2: `config_cpp.py` 解析与 merge

**Files:**
- Create: `config_cpp.py`
- Create: `tests/test_config_cpp.py`

**Interfaces:**
- Consumes: `DAYZ_HEADERS` from `dayz_csv`
- Produces:
  - `read_text(path: Path | str) -> str`
  - `extract_stringtable_keys_from_text(text: str) -> list[str]`  # 保序去重
  - `extract_stringtable_keys_from_file(path) -> list[str]`
  - `collect_config_cpp_files(folder) -> list[Path]`  # 递归，name.lower()==config.cpp，排序
  - `extract_keys_from_paths(paths) -> tuple[list[str], list[str]]`  # (keys, file_warnings)
  - `merge_language_keys(existing_rows, keys) -> tuple[list[list[str]], int, int]`  # merged, added, skipped

- [ ] **Step 1: 写失败测试**

创建 `tests/test_config_cpp.py`：

```python
import tempfile
import unittest
from pathlib import Path

from dayz_csv import DAYZ_HEADERS
from config_cpp import (
    collect_config_cpp_files,
    extract_keys_from_paths,
    extract_stringtable_keys_from_text,
    merge_language_keys,
)


class ConfigCppTests(unittest.TestCase):
    def test_extract_dollar_and_hash_inside_quotes(self):
        text = 'displayName="$STR_My_CODM_Weapons_LMG_Chopper_RulesOfTheGame0";'
        self.assertEqual(
            extract_stringtable_keys_from_text(text),
            ["STR_My_CODM_Weapons_LMG_Chopper_RulesOfTheGame0"],
        )

    def test_extract_multiple_keys_in_one_string(self):
        text = 'text = "Hello $STR_A and #STR_B end";'
        self.assertEqual(extract_stringtable_keys_from_text(text), ["STR_A", "STR_B"])

    def test_ignores_keys_outside_quotes(self):
        text = 'displayName=$STR_OUT; value="#STR_IN";'
        self.assertEqual(extract_stringtable_keys_from_text(text), ["STR_IN"])

    def test_single_quoted_string(self):
        text = "name = '#STR_SINGLE';"
        self.assertEqual(extract_stringtable_keys_from_text(text), ["STR_SINGLE"])

    def test_dedupe_preserves_first_order(self):
        text = '"$STR_A"; "$STR_B"; "$STR_A";'
        self.assertEqual(extract_stringtable_keys_from_text(text), ["STR_A", "STR_B"])

    def test_merge_skips_existing_language_keys(self):
        existing = [["STR_A", "x"] + [""] * (len(DAYZ_HEADERS) - 2)]
        merged, added, skipped = merge_language_keys(existing, ["STR_A", "STR_B"])
        self.assertEqual(added, 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(merged[0][0], "STR_A")
        self.assertEqual(merged[0][1], "x")
        self.assertEqual(merged[1][0], "STR_B")
        self.assertEqual(merged[1][1:], [""] * (len(DAYZ_HEADERS) - 1))
        self.assertEqual(len(merged[1]), len(DAYZ_HEADERS))

    def test_merge_ignores_blank_existing_language_for_set(self):
        existing = [["", ""] + [""] * (len(DAYZ_HEADERS) - 2)]
        merged, added, skipped = merge_language_keys(existing, ["STR_NEW"])
        self.assertEqual(added, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(merged), 2)

    def test_collect_config_cpp_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "config.cpp").write_text('"$STR_A";', encoding="utf-8")
            (root / "b.cpp").write_text('"$STR_X";', encoding="utf-8")
            (root / "Config.CPP").write_text('"$STR_B";', encoding="utf-8")
            files = collect_config_cpp_files(root)
            names = {p.name.lower() for p in files}
            self.assertEqual(names, {"config.cpp"})
            keys, warnings = extract_keys_from_paths(files)
            self.assertEqual(set(keys), {"STR_A", "STR_B"})
            self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m unittest tests.test_config_cpp -v
```

Expected: FAIL import error / missing module.

- [ ] **Step 3: 实现 `config_cpp.py`**

```python
import re
from pathlib import Path

from dayz_csv import DAYZ_HEADERS

_KEY_IN_STRING = re.compile(r"[$#]([A-Za-z_][A-Za-z0-9_]*)")


def read_text(path):
    path = Path(path)
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _quoted_string_contents(text):
    contents = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                buf.append(c)
                i += 1
            contents.append("".join(buf))
            continue
        i += 1
    return contents


def extract_stringtable_keys_from_text(text):
    seen = set()
    ordered = []
    for content in _quoted_string_contents(text or ""):
        for match in _KEY_IN_STRING.finditer(content):
            key = match.group(1).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return ordered


def extract_stringtable_keys_from_file(path):
    return extract_stringtable_keys_from_text(read_text(path))


def collect_config_cpp_files(folder):
    root = Path(folder)
    files = [p for p in root.rglob("*") if p.is_file() and p.name.lower() == "config.cpp"]
    return sorted(files, key=lambda p: str(p).lower())


def extract_keys_from_paths(paths):
    seen = set()
    ordered = []
    warnings = []
    for path in sorted((Path(p) for p in paths), key=lambda p: str(p).lower()):
        try:
            keys = extract_stringtable_keys_from_file(path)
        except OSError as exc:
            warnings.append(f"{path}: {exc}")
            continue
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return ordered, warnings


def merge_language_keys(existing_rows, keys):
    width = len(DAYZ_HEADERS)
    merged = [list(row[:width]) + [""] * max(0, width - len(row)) for row in existing_rows]
    existing_keys = set()
    for row in merged:
        key = (row[0] if row else "").strip()
        if key:
            existing_keys.add(key)

    added = 0
    skipped = 0
    for key in keys:
        key = (key or "").strip()
        if not key:
            continue
        if key in existing_keys:
            skipped += 1
            continue
        new_row = [key] + [""] * (width - 1)
        merged.append(new_row)
        existing_keys.add(key)
        added += 1
    return merged, added, skipped
```

- [ ] **Step 4: 跑测试通过**

```bash
python -m unittest tests.test_config_cpp -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add config_cpp.py tests/test_config_cpp.py
git commit -m "feat: extract stringtable keys from config.cpp and merge by Language"
```

---

### Task 3: GUI 导入入口与文案

**Files:**
- Modify: `main.py`（imports、`UI_TEXT`、`create_menus`、`apply_ui_language`、导入方法、可选 `set_table_rows` 辅助）
- Modify: `tests/test_main_gui.py`

**Interfaces:**
- Consumes: Task 1 的 `load_dayz_csv` 三元组；Task 2 的 `collect_config_cpp_files`、`extract_keys_from_paths`、`merge_language_keys`
- Produces:
  - `DayzTranslateTool.import_from_config_cpp_files()`
  - `DayzTranslateTool.import_config_cpp_from_folder()`
  - `DayzTranslateTool._import_config_cpp_paths(paths)`
  - `DayzTranslateTool.apply_rows(rows, dirty=True)`（或等价：填表辅助，避免复制 load_file 填表代码）

- [ ] **Step 1: 写 GUI 失败/行为测试**

在 `tests/test_main_gui.py` 增加：

```python
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox

# inside MainGuiTests:

def test_import_config_requires_loaded_csv(self):
    self.window.headers = []
    self.window.table.setRowCount(0)
    with patch.object(QMessageBox, "warning") as warning:
        self.window.import_from_config_cpp_files()
        warning.assert_called()

def test_import_config_paths_appends_new_keys_and_sets_dirty(self):
    # ensure a loaded dayz table
    self.assertTrue(self.window.headers)
    before = self.window.table.rowCount()
    # seed one existing key if table empty of STR_TEST_EXIST
    if before == 0:
        self.window.table.setRowCount(1)
        self.window.set_cell_text(0, 0, "STR_EXIST")
        before = 1
    else:
        self.window.set_cell_text(0, 0, "STR_EXIST")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.cpp"
        path.write_text(
            'displayName="$STR_EXIST";\ndescription="$STR_NEW_FROM_CPP";\n',
            encoding="utf-8",
        )
        self.window._import_config_cpp_paths([path])

    self.assertEqual(self.window.table.rowCount(), before + 1)
    last = self.window.table.item(self.window.table.rowCount() - 1, 0).text()
    self.assertEqual(last, "STR_NEW_FROM_CPP")
    self.assertTrue(self.window.is_dirty)
```

说明：若默认 `stringtable.csv` 不存在导致 headers 空，setUp 里用最小标准表：

```python
from dayz_csv import DAYZ_HEADERS

def _ensure_dayz_table(self):
    if self.window.headers:
        return
    self.window.headers = list(DAYZ_HEADERS)
    self.window.table.setColumnCount(len(self.window.visible_headers()))
    self.window.table.setHorizontalHeaderLabels(self.window.visible_headers())
    self.window.table.setRowCount(0)
```

在需要表的 import 测试开头调用。

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m unittest tests.MainGuiTests.test_import_config_requires_loaded_csv tests.MainGuiTests.test_import_config_paths_appends_new_keys_and_sets_dirty -v
```

若类路径写法因模块而异，用：

```bash
python -m unittest tests.test_main_gui.MainGuiTests.test_import_config_requires_loaded_csv tests.test_main_gui.MainGuiTests.test_import_config_paths_appends_new_keys_and_sets_dirty -v
```

Expected: FAIL（方法不存在）。

- [ ] **Step 3: 实现 main 导入与文案**

1. `main.py` 顶部：

```python
from config_cpp import collect_config_cpp_files, extract_keys_from_paths, merge_language_keys
```

2. `UI_TEXT["en"]` 增加：

```python
"import_config_cpp": "Import from config.cpp...",
"import_config_cpp_folder": "Import config.cpp from Folder...",
"import_config_cpp_title": "Select config.cpp files",
"import_config_folder_title": "Select folder containing config.cpp",
"config_cpp_files": "config.cpp (config.cpp);;C++ files (*.cpp);;All files (*.*)",
"import_requires_csv": "Open a DayZ stringtable.csv before importing config.cpp keys.",
"import_no_files": "No config.cpp files were selected.",
"import_no_new_keys": "No new keys to import. Skipped duplicates: {skipped}. Files: {files}.",
"import_result": "Imported {added} keys, skipped {skipped} duplicates, files: {files}.",
"import_failed": "Import failed",
```

3. `UI_TEXT["zh"]` 增加：

```python
"import_config_cpp": "从 config.cpp 导入...",
"import_config_cpp_folder": "从文件夹批量导入 config.cpp...",
"import_config_cpp_title": "选择 config.cpp 文件",
"import_config_folder_title": "选择包含 config.cpp 的文件夹",
"config_cpp_files": "config.cpp (config.cpp);;C++ 文件 (*.cpp);;所有文件 (*.*)",
"import_requires_csv": "请先打开 DayZ stringtable.csv，再导入 config.cpp 键。",
"import_no_files": "没有选择 config.cpp 文件。",
"import_no_new_keys": "没有可导入的新键。跳过重复 {skipped}，文件数 {files}。",
"import_result": "新增 {added} 个键，跳过重复 {skipped}，文件数 {files}。",
"import_failed": "导入失败",
```

4. `create_menus` 在 `Save As` 后：

```python
self.menu_file.addSeparator()
self.action_import_config_cpp = QAction("Import from config.cpp...", self)
self.action_import_config_cpp.triggered.connect(self.import_from_config_cpp_files)
self.menu_file.addAction(self.action_import_config_cpp)
self.action_import_config_folder = QAction("Import config.cpp from Folder...", self)
self.action_import_config_folder.triggered.connect(self.import_config_cpp_from_folder)
self.menu_file.addAction(self.action_import_config_folder)
```

5. `apply_ui_language` 设置上述两个 action 的文本。

6. 方法：

```python
def apply_table_rows(self, rows, dirty=True):
    self.loading = True
    self.table.blockSignals(True)
    visible_headers = self.visible_headers()
    self.table.setColumnCount(len(visible_headers))
    self.table.setHorizontalHeaderLabels(visible_headers)
    self.table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index in range(len(visible_headers)):
            value = row[column_index] if column_index < len(row) else ""
            self.table.setItem(row_index, column_index, QTableWidgetItem(value))
    self.table.blockSignals(False)
    self.loading = False
    self.apply_column_widths()
    if dirty:
        self.set_dirty(True)


def import_from_config_cpp_files(self):
    if not self.headers:
        QMessageBox.warning(self, self.tr("import_failed"), self.tr("import_requires_csv"))
        return
    paths, _ = QFileDialog.getOpenFileNames(
        self,
        self.tr("import_config_cpp_title"),
        "",
        self.tr("config_cpp_files"),
    )
    if not paths:
        return
    self._import_config_cpp_paths(paths)


def import_config_cpp_from_folder(self):
    if not self.headers:
        QMessageBox.warning(self, self.tr("import_failed"), self.tr("import_requires_csv"))
        return
    folder = QFileDialog.getExistingDirectory(self, self.tr("import_config_folder_title"), "")
    if not folder:
        return
    paths = collect_config_cpp_files(folder)
    if not paths:
        QMessageBox.information(self, self.tr("import_failed"), self.tr("import_no_files"))
        return
    self._import_config_cpp_paths(paths)


def _import_config_cpp_paths(self, paths):
    if not self.headers:
        QMessageBox.warning(self, self.tr("import_failed"), self.tr("import_requires_csv"))
        return
    try:
        keys, file_warnings = extract_keys_from_paths(paths)
        existing = self.table_rows()
        merged, added, skipped = merge_language_keys(existing, keys)
    except Exception as exc:
        QMessageBox.critical(self, self.tr("import_failed"), str(exc))
        return

    files_count = len(list(paths))
    if added == 0:
        msg = self.tr("import_no_new_keys", skipped=skipped, files=files_count)
        if file_warnings:
            msg = msg + "\n" + "\n".join(file_warnings)
        QMessageBox.information(self, self.tr("import_config_cpp"), msg)
        return

    self.apply_table_rows(merged, dirty=True)
    msg = self.tr("import_result", added=added, skipped=skipped, files=files_count)
    if file_warnings:
        msg = f"{msg} | " + "; ".join(file_warnings)
    self.statusBar().showMessage(msg, 8000)
```

可选重构：`load_file` 填表可改为 `self.headers = headers` 后 `self.apply_table_rows(rows, dirty=False)`，减少重复（保持行为一致即可）。

- [ ] **Step 4: 跑相关测试**

```bash
python -m unittest tests.test_dayz_csv tests.test_config_cpp tests.test_main_gui -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main_gui.py
git commit -m "feat: GUI import of stringtable keys from config.cpp"
```

---

### Task 4: 回归与手工验收清单

**Files:** 无新代码（除非修测试失败）

- [ ] **Step 1: 全量单测**

```bash
python -m unittest discover -s tests -v
```

Expected: 全部 PASS。

- [ ] **Step 2: 手工清单（实现者勾选）**

1. 打开仅含 `Language,english,chinesesimp` 的 CSV → 表为完整列，缺列空。
2. 打开含 `unknown` 列的 CSV → 成功打开，状态栏有 skipped 提示。
3. 打开 `"id","foo"` 类 CSV → 失败提示。
4. 已打开表后 File → Import from config.cpp，选含  
   `displayName="$STR_My_CODM_Weapons_LMG_Chopper_RulesOfTheGame0";`  
   → 新行 Language 为该键，其它空，dirty。
5. 再导入同一文件 → 无新行，提示 skipped。
6. 文件夹导入递归找到子目录 `config.cpp`。
7. 未打开 CSV 时点导入 → warning。
8. Save 后文件仍是标准 DayZ 引号 CSV。

- [ ] **Step 3: 若有修复则 commit**

```bash
git add -u
git commit -m "fix: polish csv autofix / config import edge cases"
```

（无改动则跳过 commit。）

---

## Spec coverage checklist

| Spec 要求 | Task |
|-----------|------|
| 打开时宽容补齐 / 未知列跳过 / warnings | Task 1 |
| `load_dayz_csv` 三元组 | Task 1 |
| 无合法列 ValueError | Task 1 |
| 保存仍标准写出 | 不改 write（Task 1 说明） |
| 引号内 `$`/`#` 多键 | Task 2 |
| 引号外忽略 | Task 2 |
| 文件夹递归 config.cpp | Task 2 |
| merge 按 Language 去重，新行仅键 | Task 2 |
| File 菜单两项 + 需已打开表 | Task 3 |
| 中英文 UI | Task 3 |
| 结果摘要 / 单文件失败继续 | Task 2+3 |
| 测试 | Task 1–4 |

## Self-review notes

- 无 TBD/占位步骤。
- `merge_language_keys` / `extract_keys_from_paths` 签名在 Task 2/3 一致。
- GUI 测试依赖 offscreen Qt，与现有 `test_main_gui.py` 一致。
- Windows 上 `Config.CPP` 由 `name.lower() == "config.cpp"` 覆盖。
