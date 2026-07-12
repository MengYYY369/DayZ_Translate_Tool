# UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement four UI improvements: AI preset auto-load with dirty indicator, persistent file dialog paths, multi-select right-click preservation, and full-table/empty-cell translation buttons.

**Architecture:** All changes are in `main.py` and `tests/test_main_gui.py`. Each feature is independent and can be implemented and tested in isolation. The existing TDD pattern (write test → verify fail → implement → verify pass → commit) applies throughout.

**Tech Stack:** Python 3.13, PySide6, pytest/unittest, QSettings for persistence

## Global Constraints

- All UI text must be added to both `en` and `zh` in the `UI_TEXT` dict
- All new methods on `DayzTranslateTool` must be covered by tests in `tests/test_main_gui.py`
- Tests run with `QT_QPA_PLATFORM=offscreen`
- Existing tests must continue to pass

---

### Task 1: AI Preset Auto-Load with Dirty Indicator

**Files:**
- Modify: `main.py` — `TranslationSettingsDialog` class (lines ~307-469)
- Test: `tests/test_main_gui.py`

**Interfaces:**
- Consumes: `DayzTranslateTool.translation_preset_names()`, `DayzTranslateTool.load_translation_preset(name)`, `DayzTranslateTool.save_translation_preset(name)`, `DayzTranslateTool.delete_translation_preset(name)`, `DayzTranslateTool.current_translation_settings_dict()`
- Produces: `TranslationSettingsDialog.auto_load_preset(name)`, `TranslationSettingsDialog.current_field_values()`, `TranslationSettingsDialog.is_preset_dirty()`, `TranslationSettingsDialog.refresh_preset_dirty_indicator()`

- [ ] **Step 1: Write failing tests for preset auto-load and dirty indicator**

Add to `tests/test_main_gui.py`:

```python
    def test_preset_combo_switch_auto_loads_values(self):
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "key-a"
        self.window.translation_model = "model-a"
        self.window.translation_base_url = "https://a.test/v1"
        self.window.save_translation_preset("PresetA")

        self.window.translation_api_key = "key-b"
        self.window.translation_model = "model-b"
        self.window.translation_base_url = "https://b.test/v1"
        self.window.save_translation_preset("PresetB")

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")

        dialog.preset_combo.setCurrentText("PresetA")
        self.assertEqual(dialog.api_key_input.text(), "key-a")
        self.assertEqual(dialog.model_input.text(), "model-a")
        self.assertEqual(dialog.base_url_input.text(), "https://a.test/v1")

        dialog.preset_combo.setCurrentText("PresetB")
        self.assertEqual(dialog.api_key_input.text(), "key-b")
        self.assertEqual(dialog.model_input.text(), "model-b")
        self.assertEqual(dialog.base_url_input.text(), "https://b.test/v1")

    def test_preset_combo_shows_star_when_field_value_changes(self):
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "original-key"
        self.window.translation_model = "original-model"
        self.window.translation_base_url = "https://original.test/v1"
        self.window.save_translation_preset("StarPreset")

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")
        dialog.preset_combo.setCurrentText("StarPreset")

        self.assertNotIn("*", dialog.preset_combo.currentText())

        dialog.api_key_input.setText("changed-key")

        self.assertIn("*", dialog.preset_combo.currentText())

    def test_preset_combo_clears_star_after_saving_preset(self):
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "save-key"
        self.window.translation_model = "save-model"
        self.window.translation_base_url = "https://save.test/v1"
        self.window.save_translation_preset("SavePreset")

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")
        dialog.preset_combo.setCurrentText("SavePreset")

        dialog.api_key_input.setText("changed-key")
        self.assertIn("*", dialog.preset_combo.currentText())

        dialog.preset_name_input.setText("SavePreset")
        dialog.save_preset()

        self.assertNotIn("*", dialog.preset_combo.currentText())

    def test_preset_load_button_is_removed(self):
        dialog = TranslationSettingsDialog(self.window)
        self.assertFalse(hasattr(dialog, "load_preset_button"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main_gui.py -k "preset_combo_switch or preset_combo_shows_star or preset_combo_clears_star or preset_load_button" -v`
Expected: FAIL

- [ ] **Step 3: Implement preset auto-load and dirty indicator**

In `main.py`, modify the `TranslationSettingsDialog` class:

1. In `__init__`, remove the `load_preset_button` creation and its connection. Replace the `preset_combo.currentTextChanged` connection with auto-load. After `self.update_visible_fields()`, connect `preset_combo.currentTextChanged` to `auto_load_preset`.

Replace this block in `__init__` (around lines 318-326):
```python
        self.preset_combo = QComboBox(self)
        self.refresh_presets()
        self.preset_name_input = QLineEdit(self)
        self.save_preset_button = QPushButton(window.tr("save"), self)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.load_preset_button = QPushButton(window.tr("open"), self)
        self.load_preset_button.clicked.connect(self.load_preset)
        self.delete_preset_button = QPushButton("Delete", self)
        self.delete_preset_button.clicked.connect(self.delete_preset)
```
with:
```python
        self.preset_combo = QComboBox(self)
        self.refresh_presets()
        self.preset_name_input = QLineEdit(self)
        self.save_preset_button = QPushButton(window.tr("save"), self)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.delete_preset_button = QPushButton("Delete", self)
        self.delete_preset_button.clicked.connect(self.delete_preset)
```

2. In the `preset_layout` section, remove the `preset_layout.addWidget(self.load_preset_button)` line:
```python
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addWidget(self.preset_name_input)
        preset_layout.addWidget(self.save_preset_button)
        preset_layout.addWidget(self.delete_preset_button)
```

3. After `self.update_visible_fields()` (around line 371), add the auto-load connection:
```python
        self.update_visible_fields()
        self.preset_combo.currentTextChanged.connect(self.auto_load_preset)
```

4. Replace the `connect_auto_save_signals` method with one that also refreshes the dirty indicator:
```python
    def connect_auto_save_signals(self):
        self.provider_combo.currentTextChanged.connect(lambda value: self.apply_settings(close_dialog=False))
        self.batch_size_input.valueChanged.connect(lambda value: self.apply_settings(close_dialog=False))
        self.parallel_batches_input.valueChanged.connect(lambda value: self.apply_settings(close_dialog=False))
        self.api_key_input.textChanged.connect(lambda value: (self.apply_settings(close_dialog=False), self.refresh_preset_dirty_indicator()))
        self.region_input.textChanged.connect(lambda value: (self.apply_settings(close_dialog=False), self.refresh_preset_dirty_indicator()))
        self.model_input.textChanged.connect(lambda value: (self.apply_settings(close_dialog=False), self.refresh_preset_dirty_indicator()))
        self.base_url_input.textChanged.connect(lambda value: (self.apply_settings(close_dialog=False), self.refresh_preset_dirty_indicator()))
        self.email_input.textChanged.connect(lambda value: (self.apply_settings(close_dialog=False), self.refresh_preset_dirty_indicator()))
```

5. Update `refresh_presets` to block signals during repopulation (prevents `currentTextChanged` from triggering `auto_load_preset` when the combo is cleared/repopulated):
```python
    def refresh_presets(self):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(self.window.translation_preset_names())
        self.preset_combo.blockSignals(False)
```

7. Add the new methods (replacing the old `load_preset` method):
```python
    def auto_load_preset(self, name):
        name = (name or "").rstrip("*").strip()
        if not name:
            return
        self.window.load_translation_preset(name)
        self.provider_combo.setCurrentText(PROVIDER_LABELS.get(self.window.translation_provider, "Google"))
        self.batch_size_input.setValue(self.window.translation_batch_size)
        self.parallel_batches_input.setValue(self.window.translation_parallel_batches)
        self.api_key_input.setText(self.window.translation_api_key)
        self.region_input.setText(self.window.translation_region)
        self.model_input.setText(self.window.translation_model)
        self.base_url_input.setText(self.window.translation_base_url)
        self.email_input.setText(self.window.translation_email)
        self.refresh_preset_dirty_indicator()

    def current_field_values(self):
        return {
            "provider": self.window.translation_provider,
            "batch_size": self.batch_size_input.value(),
            "parallel_batches": self.parallel_batches_input.value(),
            "api_key": self.api_key_input.text().strip(),
            "region": self.region_input.text().strip(),
            "model": self.model_input.text().strip(),
            "base_url": self.base_url_input.text().strip(),
            "email": self.email_input.text().strip(),
        }

    def preset_saved_values(self):
        name = (self.preset_combo.currentText() or "").rstrip("*").strip()
        if not name:
            return None
        self.window.settings.beginGroup(f"translation_presets/{name}")
        values = {key: self.window.settings.value(key) for key in self.window.settings.childKeys()}
        self.window.settings.endGroup()
        return values

    def is_preset_dirty(self):
        saved = self.preset_saved_values()
        if saved is None:
            return False
        current = self.current_field_values()
        for key, value in current.items():
            saved_value = saved.get(key, "")
            if str(value) != str(saved_value):
                return True
        return False

    def refresh_preset_dirty_indicator(self):
        name = (self.preset_combo.currentText() or "").rstrip("*").strip()
        if not name:
            return
        if self.is_preset_dirty():
            new_label = f"{name}*"
        else:
            new_label = name
        if self.preset_combo.currentText() != new_label:
            self.preset_combo.blockSignals(True)
            index = self.preset_combo.currentIndex()
            self.preset_combo.setItemText(index, new_label)
            self.preset_combo.blockSignals(False)
```

8. In `save_preset`, add `refresh_preset_dirty_indicator()` call after `refresh_presets()`:
```python
    def save_preset(self):
        self.apply_settings(close_dialog=False)
        self.window.save_translation_preset(self.preset_name_input.text())
        self.refresh_presets()
        self.refresh_preset_dirty_indicator()
```

9. In `delete_preset`, add `refresh_preset_dirty_indicator()` after `refresh_presets()`:
```python
    def delete_preset(self):
        self.window.delete_translation_preset(self.preset_combo.currentText().rstrip("*").strip())
        self.refresh_presets()
        self.refresh_preset_dirty_indicator()
```

10. The old `load_preset` method is replaced by `auto_load_preset` (added above). Remove the old `load_preset` method entirely.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main_gui.py -k "preset_combo_switch or preset_combo_shows_star or preset_combo_clears_star or preset_load_button" -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python -m pytest tests/test_main_gui.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_gui.py
git commit -m "feat: AI preset auto-load on combo switch with dirty star indicator"
```

---

### Task 2: Remember Last File Dialog Path

**Files:**
- Modify: `main.py` — `DayzTranslateTool.__init__`, `DayzTranslateTool.open_file`, `DayzTranslateTool.save_file_as`, `DayzTranslateTool.import_from_config_cpp_files`, `DayzTranslateTool.import_config_cpp_from_folder`, `WordbookWindow.open_file`, `WordbookWindow.save_file_as`
- Test: `tests/test_main_gui.py`

**Interfaces:**
- Consumes: `QSettings`
- Produces: `DayzTranslateTool.last_file_dir` (str), `DayzTranslateTool.update_last_file_dir(path)`

- [ ] **Step 1: Write failing tests for file path memory**

Add to `tests/test_main_gui.py`:

```python
    def test_last_file_dir_persisted_after_load(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "stringtable.csv"
            csv_path.write_text("Language,original,english\n,Test,Test\n", encoding="utf-8")

            self.window.load_file(csv_path)

            self.assertEqual(self.window.last_file_dir, str(Path(tmp_dir)))
            self.assertEqual(self.settings.value("last_file_dir"), str(Path(tmp_dir)))

    def test_update_last_file_dir_stores_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "sub" / "stringtable.csv"
            csv_path.parent.mkdir()
            csv_path.write_text("Language,original,english\n,Test,Test\n", encoding="utf-8")

            self.window.update_last_file_dir(csv_path)

            self.assertEqual(self.window.last_file_dir, str(csv_path.parent))

    def test_open_file_uses_last_file_dir_as_starting_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.window.last_file_dir = str(Path(tmp_dir))
            with patch("main.QFileDialog.getOpenFileName", return_value=("", "")) as mock_dialog:
                self.window.open_file()
                args = mock_dialog.call_args.args
                self.assertEqual(args[2], str(Path(tmp_dir)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main_gui.py -k "last_file_dir or open_file_uses_last" -v`
Expected: FAIL

- [ ] **Step 3: Implement file path memory**

In `main.py`, modify `DayzTranslateTool.__init__` — after the line `self.translation_email = self.settings.value("translation_email", "")` (around line 702), add:
```python
        self.last_file_dir = self.settings.value("last_file_dir", str(DEFAULT_CSV_PATH.parent))
```

Add a new method after `save_ui_language`:
```python
    def update_last_file_dir(self, path):
        if path:
            directory = str(Path(path).parent)
            self.last_file_dir = directory
            self.settings.setValue("last_file_dir", directory)
```

Modify `open_file`:
```python
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("open_dayz_csv"), self.last_file_dir, self.tr("csv_files"))
        if path:
            self.load_file(Path(path))
```

Modify `load_file` — after the line `self.current_path = Path(path)` (around line 838), add:
```python
        self.update_last_file_dir(path)
```

Modify `save_file_as`:
```python
    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(self, self.tr("save_dayz_csv"), self.last_file_dir, self.tr("csv_files"))
        if path:
            return self.write_current_file(Path(path))
        return False
```

Modify `write_current_file` — after the line `self.current_path = Path(path)` (around line 948), add:
```python
        self.update_last_file_dir(path)
```

Modify `import_from_config_cpp_files`:
```python
    def import_from_config_cpp_files(self):
        if not self.headers:
            QMessageBox.warning(self, self.tr("import_failed"), self.tr("import_requires_csv"))
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("import_config_cpp_title"),
            self.last_file_dir,
            self.tr("config_cpp_files"),
        )
        if not paths:
            return
        self.update_last_file_dir(paths[0])
        self._import_config_cpp_paths(paths)
```

Modify `import_config_cpp_from_folder`:
```python
    def import_config_cpp_from_folder(self):
        if not self.headers:
            QMessageBox.warning(self, self.tr("import_failed"), self.tr("import_requires_csv"))
            return
        folder = QFileDialog.getExistingDirectory(self, self.tr("import_config_folder_title"), self.last_file_dir)
        if not folder:
            return
        self.update_last_file_dir(folder)
        paths = collect_config_cpp_files(folder)
        if not paths:
            QMessageBox.information(self, self.tr("import_failed"), self.tr("import_no_files"))
            return
        self._import_config_cpp_paths(paths)
```

Modify `WordbookWindow.open_file`:
```python
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.parent_window.tr("open_wordbook_csv"), self.parent_window.last_file_dir, self.parent_window.tr("wordbook_files"))
        if path:
            self.load_file(Path(path))
```

Modify `WordbookWindow.load_file` — after the line `self.current_path = Path(path)` (around line 556), add:
```python
        self.parent_window.update_last_file_dir(path)
```

Modify `WordbookWindow.save_file_as`:
```python
    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(self, self.parent_window.tr("save_wordbook_csv"), self.parent_window.last_file_dir, self.parent_window.tr("wordbook_files"))
        if path:
            return self.write_current_file(Path(path))
        return False
```

Modify `WordbookWindow.write_current_file` — after the line `self.current_path = Path(path)` (around line 578), add:
```python
        self.parent_window.update_last_file_dir(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main_gui.py -k "last_file_dir or open_file_uses_last" -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python -m pytest tests/test_main_gui.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_gui.py
git commit -m "feat: remember last file dialog path across open/save operations"
```

---

### Task 3: Multi-Select Right-Click Preservation

**Files:**
- Modify: `main.py` — `DayzTranslateTool.open_context_menu` (lines ~1077-1090)
- Test: `tests/test_main_gui.py`

**Interfaces:**
- Produces: `DayzTranslateTool.is_cell_in_selection(row, column)` → bool

- [ ] **Step 1: Write failing tests for multi-select preservation**

Add to `tests/test_main_gui.py`:

```python
    def test_right_click_within_multiselection_preserves_selection(self):
        self.window.table.clearSelection()
        self.window.set_cell_text(0, 2, "A")
        self.window.set_cell_text(0, 4, "B")
        self.window.set_cell_text(1, 2, "C")
        self.window.set_cell_text(1, 4, "D")
        self.window.table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 4), True)

        item_rect = self.window.table.visualItemRect(self.window.table.item(0, 4))
        center = item_rect.center()

        with patch.object(self.window, "show_context_menu") as show_menu:
            self.window.open_context_menu(center)

        selected_rows = set()
        selected_cols = set()
        for item in self.window.table.selectedItems():
            selected_rows.add(item.row())
            selected_cols.add(item.column())
        self.assertIn(0, selected_rows)
        self.assertIn(1, selected_rows)
        self.assertIn(2, selected_cols)
        self.assertIn(4, selected_cols)

    def test_right_click_outside_multiselection_clears_and_selects_one(self):
        self.window.table.clearSelection()
        self.window.set_cell_text(0, 2, "A")
        self.window.set_cell_text(0, 4, "B")
        self.window.set_cell_text(1, 6, "C")
        self.window.table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 0, 4), True)

        item_rect = self.window.table.visualItemRect(self.window.table.item(1, 6))
        center = item_rect.center()

        with patch.object(self.window, "show_context_menu") as show_menu:
            self.window.open_context_menu(center)

        selected = [(item.row(), item.column()) for item in self.window.table.selectedItems()]
        self.assertEqual(selected, [(1, 6)])

    def test_right_click_on_empty_cell_within_selection_preserves_selection(self):
        self.window.table.clearSelection()
        self.window.set_cell_text(0, 2, "A")
        self.window.set_cell_text(1, 2, "B")
        self.window.table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 6), True)

        item_rect = self.window.table.visualItemRect(self.window.table.item(0, 2))
        center = item_rect.center()

        with patch.object(self.window, "show_context_menu") as show_menu:
            self.window.open_context_menu(center)

        selected_rows = set()
        for item in self.window.table.selectedItems():
            selected_rows.add(item.row())
        self.assertIn(0, selected_rows)
        self.assertIn(1, selected_rows)
```

Add this import at the top of the test file if not present:
```python
from PySide6.QtWidgets import QTableWidgetSelectionRange
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main_gui.py -k "right_click_within_multiselection or right_click_outside_multiselection or right_click_on_empty_cell_within" -v`
Expected: FAIL

- [ ] **Step 3: Implement multi-select preservation**

In `main.py`, add the import for `QTableWidgetSelectionRange` — it's already available via `PySide6.QtWidgets`. Add it to the import list at the top:

```python
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTableWidgetSelectionRange,
    QVBoxLayout,
)
```

Replace `open_context_menu`:
```python
    def open_context_menu(self, position):
        row = self.table.rowAt(position.y())
        column = self.table.columnAt(position.x())
        if row >= 0 and column >= 0:
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem("")
                self.table.setItem(row, column, item)
            if not self.is_cell_in_selection(row, column):
                self.table.clearSelection()
                item.setSelected(True)
            self.table.setCurrentCell(row, column)
        self.show_context_menu("cell", row, column, self.table.viewport().mapToGlobal(position))

    def is_cell_in_selection(self, row, column):
        for selected_range in self.table.selectedRanges():
            if selected_range.topRow() <= row <= selected_range.bottomRow() and \
               selected_range.leftColumn() <= column <= selected_range.rightColumn():
                return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main_gui.py -k "right_click_within_multiselection or right_click_outside_multiselection or right_click_on_empty_cell_within" -v`
Expected: PASS

- [ ] **Step 5: Run the existing right-click test to ensure no regression**

Run: `python -m pytest tests/test_main_gui.py -k "right_click_context_menu_selects" -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/test_main_gui.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main_gui.py
git commit -m "feat: preserve multi-selection when right-clicking within selected range"
```

---

### Task 4: Translate Full Table & Translate Empty Cells

**Files:**
- Modify: `main.py` — `UI_TEXT` dict, `DayzTranslateTool.create_menus`, `DayzTranslateTool.apply_ui_language`, new methods `translate_full_table`, `translate_empty_cells`, `translatable_column_indices`
- Test: `tests/test_main_gui.py`

**Interfaces:**
- Consumes: `DayzTranslateTool.run_translation_jobs`, `dayz_csv.build_column_translation_jobs`, `DayzTranslateTool.is_translatable_column`
- Produces: `DayzTranslateTool.translatable_column_indices()` → list[int], `DayzTranslateTool.translate_full_table()`, `DayzTranslateTool.translate_empty_cells()`

- [ ] **Step 1: Write failing tests for translate full table and empty cells**

Add to `tests/test_main_gui.py`:

```python
    def test_translatable_column_indices_excludes_language_original_and_source(self):
        self.window.source_header = "english"
        indices = self.window.translatable_column_indices()
        self.assertNotIn(0, indices)  # Language column
        self.assertNotIn(1, indices)  # original column
        self.assertNotIn(2, indices)  # english (source) column
        self.assertIn(3, indices)     # czech
        self.assertIn(14, indices)    # chinesesimp

    def test_translate_full_table_builds_jobs_for_all_translatable_cells(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(1, 2, "Rifle")
        self.window.run_translation_jobs = lambda jobs: captured_jobs.extend(jobs)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.translate_full_table()

        target_columns = set(col for _, col, _, _ in captured_jobs)
        self.assertIn(3, target_columns)
        self.assertIn(14, target_columns)
        self.assertNotIn(0, target_columns)
        self.assertNotIn(2, target_columns)
        self.assertEqual(len(captured_jobs), 2 * len(target_columns))

    def test_translate_empty_cells_only_builds_jobs_for_empty_cells(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 3, "Messer")
        self.window.set_cell_text(0, 14, "")
        self.window.set_cell_text(1, 2, "Rifle")
        self.window.set_cell_text(1, 3, "")
        self.window.set_cell_text(1, 14, "")
        self.window.run_translation_jobs = lambda jobs: captured_jobs.extend(jobs)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.translate_empty_cells()

        cell_keys = set((row, col) for row, col, _, _ in captured_jobs)
        self.assertNotIn((0, 3), cell_keys)  # already filled
        self.assertIn((0, 14), cell_keys)    # empty
        self.assertIn((1, 3), cell_keys)     # empty
        self.assertIn((1, 14), cell_keys)    # empty

    def test_translate_full_table_aborts_when_user_declines(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.run_translation_jobs = lambda jobs: captured_jobs.extend(jobs)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.window.translate_full_table()

        self.assertEqual(captured_jobs, [])

    def test_translate_full_table_warns_when_no_csv_loaded(self):
        self.window.headers = []
        self.window.table.setRowCount(0)
        with patch.object(QMessageBox, "warning") as warning:
            self.window.translate_full_table()
            warning.assert_called()

    def test_translate_empty_cells_warns_when_no_csv_loaded(self):
        self.window.headers = []
        self.window.table.setRowCount(0)
        with patch.object(QMessageBox, "warning") as warning:
            self.window.translate_empty_cells()
            warning.assert_called()

    def test_translate_empty_cells_informs_when_all_cells_filled(self):
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        for col in self.window.translatable_column_indices():
            self.window.set_cell_text(0, col, "translated")
        self.window.table.setRowCount(1)

        with patch.object(QMessageBox, "information") as info:
            self.window.translate_empty_cells()
            info.assert_called()

    def test_translate_menu_actions_exist_in_file_menu(self):
        action_texts = [action.text() for action in self.window.menu_file.actions()]
        self.assertIn("Translate Full Table", action_texts)
        self.assertIn("Translate Empty Cells", action_texts)

    def test_translate_menu_actions_chinese_labels(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        action_texts = [action.text() for action in self.window.menu_file.actions()]
        self.assertIn("翻译全表", action_texts)
        self.assertIn("翻译空白单元格", action_texts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main_gui.py -k "translatable_column_indices or translate_full_table or translate_empty_cells or translate_menu_actions" -v`
Expected: FAIL

- [ ] **Step 3: Add UI text entries**

In `main.py`, in the `UI_TEXT` dict, add to the `"en"` section (after `"import_failed": "Import failed",`):
```python
        "translate_full_table": "Translate Full Table",
        "translate_empty_cells": "Translate Empty Cells",
        "translate_full_table_confirm": "This will translate all translatable cells and overwrite existing translations. Continue?",
        "translate_empty_cells_confirm": "This will translate all empty translatable cells. Continue?",
        "no_empty_cells": "No empty translatable cells were found.",
        "translate_full_table_title": "Translate Full Table",
        "translate_empty_cells_title": "Translate Empty Cells",
```

Add to the `"zh"` section (after `"import_failed": "导入失败",`):
```python
        "translate_full_table": "翻译全表",
        "translate_empty_cells": "翻译空白单元格",
        "translate_full_table_confirm": "这将翻译所有可翻译单元格并覆盖已有翻译。是否继续？",
        "translate_empty_cells_confirm": "这将翻译所有空白的可翻译单元格。是否继续？",
        "no_empty_cells": "没有找到空白的可翻译单元格。",
        "translate_full_table_title": "翻译全表",
        "translate_empty_cells_title": "翻译空白单元格",
```

- [ ] **Step 4: Add menu actions**

In `main.py`, in `create_menus`, after the `action_save_as` block and before the separator (around line 752), add:
```python
        self.menu_file.addSeparator()

        self.action_translate_full_table = QAction("Translate Full Table", self)
        self.action_translate_full_table.triggered.connect(self.translate_full_table)
        self.menu_file.addAction(self.action_translate_full_table)

        self.action_translate_empty_cells = QAction("Translate Empty Cells", self)
        self.action_translate_empty_cells.triggered.connect(self.translate_empty_cells)
        self.menu_file.addAction(self.action_translate_empty_cells)
```

In `apply_ui_language`, after `self.action_import_config_folder.setText(texts["import_config_cpp_folder"])` (around line 789), add:
```python
        self.action_translate_full_table.setText(texts["translate_full_table"])
        self.action_translate_empty_cells.setText(texts["translate_empty_cells"])
```

- [ ] **Step 5: Implement translation methods**

In `main.py`, add the following methods to `DayzTranslateTool` (after `translate_selected_columns`):

```python
    def translatable_column_indices(self):
        source_index = -1
        try:
            source_index = self.headers.index(self.source_header)
        except ValueError:
            pass
        indices = []
        for column in range(len(self.visible_headers())):
            if column == 0:
                continue
            if column == source_index:
                continue
            if (self.headers[column] or "").strip().lower() == "original":
                continue
            if self.is_translatable_column(column):
                indices.append(column)
        return indices

    def translate_full_table(self):
        if not self.headers:
            QMessageBox.warning(self, self.tr("translate_full_table_title"), self.tr("no_dayz_csv_loaded"))
            return
        if self.table.rowCount() == 0:
            QMessageBox.information(self, self.tr("translate_full_table_title"), self.tr("no_translatable_cells"))
            return
        result = QMessageBox.question(
            self,
            self.tr("translate_full_table_title"),
            self.tr("translate_full_table_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        columns = set(self.translatable_column_indices())
        if not columns:
            QMessageBox.information(self, self.tr("translate_full_table_title"), self.tr("no_translatable_cells"))
            return
        try:
            jobs = build_column_translation_jobs(self.headers, self.table_rows(), self.source_header, columns)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("translate_full_table_title"), str(exc))
            return
        self.run_translation_jobs(jobs)

    def translate_empty_cells(self):
        if not self.headers:
            QMessageBox.warning(self, self.tr("translate_empty_cells_title"), self.tr("no_dayz_csv_loaded"))
            return
        if self.table.rowCount() == 0:
            QMessageBox.information(self, self.tr("translate_empty_cells_title"), self.tr("no_empty_cells"))
            return
        result = QMessageBox.question(
            self,
            self.tr("translate_empty_cells_title"),
            self.tr("translate_empty_cells_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        columns = self.translatable_column_indices()
        if not columns:
            QMessageBox.information(self, self.tr("translate_empty_cells_title"), self.tr("no_empty_cells"))
            return
        try:
            source_column = self.headers.index(self.source_header)
        except ValueError:
            QMessageBox.warning(self, self.tr("translate_empty_cells_title"), self.tr("source_column_missing", header=self.source_header))
            return
        rows = self.table_rows()
        jobs = []
        for row_index in range(len(rows)):
            source_text = rows[row_index][source_column].strip()
            if not source_text:
                continue
            for column_index in columns:
                item = self.table.item(row_index, column_index)
                cell_text = item.text().strip() if item else ""
                if cell_text:
                    continue
                target_code = language_code_for_header(self.headers[column_index])
                if target_code:
                    jobs.append((row_index, column_index, source_text, target_code))
        if not jobs:
            QMessageBox.information(self, self.tr("translate_empty_cells_title"), self.tr("no_empty_cells"))
            return
        self.run_translation_jobs(jobs)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_main_gui.py -k "translatable_column_indices or translate_full_table or translate_empty_cells or translate_menu_actions" -v`
Expected: PASS

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/test_main_gui.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add main.py tests/test_main_gui.py
git commit -m "feat: add translate full table and translate empty cells menu actions"
```

---

### Task 5: Final Regression Test

**Files:**
- Test: `tests/test_main_gui.py`, `tests/test_dayz_csv.py`, `tests/test_translation_worker.py`, `tests/test_translator_service.py`, `tests/test_wordbook_csv.py`, `tests/test_config_cpp.py`

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Fix any failures**

If any pre-existing tests fail due to the changes (especially the `test_right_click_context_menu_selects_target_cell` test which expects single-cell selection on right-click), adjust the test to account for the new selection-preserving behavior. The existing test right-clicks on a cell with no prior selection, so it should still work — the cell is not in any selection, so the old behavior applies.

- [ ] **Step 3: Commit any fixes**

```bash
git add tests/test_main_gui.py
git commit -m "test: fix regressions from UI improvements"
```
