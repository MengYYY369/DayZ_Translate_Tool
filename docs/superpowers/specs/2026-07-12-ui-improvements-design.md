# UI Improvements Design

## Goal

Four targeted improvements to the DayZ Translate Tool: smarter AI preset handling, persistent file dialog paths, multi-select right-click preservation, and new full-table translation buttons.

## Feature 1: AI Preset Auto-Load on Switch

### Current Behavior

User selects a preset name from the combo box, then clicks a separate "Open" button to load the preset values into the input fields.

### Desired Behavior

- Switching the preset combo box automatically loads the preset values into all input fields — no button click required.
- The "Open" button is removed.
- When the current input field values differ from the saved preset values, the preset name in the combo box is suffixed with `*` to indicate unsaved changes.
- When values match the saved preset, the `*` is removed.

### Design

- Connect `preset_combo.currentTextChanged` to a new `auto_load_preset` method that calls `load_translation_preset(name)` and refreshes all input fields.
- Maintain a method `current_field_values()` that returns a dict of all field values from the dialog.
- Maintain a method `preset_dirty()` that compares `current_field_values()` against the saved preset values (loaded from QSettings).
- Call `refresh_preset_dirty_indicator()` after every field change (via the existing auto-save signal connections) and after `auto_load_preset`.
- `refresh_preset_dirty_indicator()` updates the combo box item text: if dirty, append `*` to the preset name; if clean, remove the `*`.

### Edge Cases

- If no preset is selected (empty combo), no indicator is shown.
- Saving a preset clears the `*` for that preset.
- Deleting a preset refreshes the combo.

## Feature 2: Remember Last File Dialog Path

### Current Behavior

All `QFileDialog` calls use a fixed default path (`DEFAULT_CSV_PATH` or empty string), so the dialog always opens at the same location regardless of where the user last navigated.

### Desired Behavior

Every file dialog (open, save, import) opens at the directory of the last file the user opened or saved. This applies to:
- Main window: Open CSV, Save As CSV, Import config.cpp files, Import config.cpp folder
- Wordbook window: Open, Save As

### Design

- Add `last_file_dir` attribute to `DayzTranslateTool`, initialized from `QSettings` value `last_file_dir` (default: `str(DEFAULT_CSV_PATH.parent)`).
- Add a helper `update_last_file_dir(path)` that saves the parent directory of `path` to both the instance attribute and `QSettings`.
- Call `update_last_file_dir` after every successful file open, save, or import.
- All `QFileDialog.getOpenFileName`, `getSaveFileName`, `getOpenFileNames`, and `getExistingDirectory` calls use `self.last_file_dir` as the starting directory.
- For the Wordbook window, the main window shares `last_file_dir` so both windows use the same remembered path.

### Edge Cases

- If `last_file_dir` doesn't exist (e.g., external drive removed), QFileDialog falls back to its default. No explicit handling needed.
- Wordbook window accesses `self.parent_window.last_file_dir` and calls `self.parent_window.update_last_file_dir(path)`.

## Feature 3: Multi-Select Right-Click Preservation

### Current Behavior

When multiple cells are selected and the user right-clicks on a cell, the selection is cleared and only the right-clicked cell is selected. This happens because the code checks `item.isSelected()`, but if the right-clicked cell has no `QTableWidgetItem` (it's empty/null), a new item is created and is not in the selected state.

### Desired Behavior

Right-clicking on a cell that is within the current multi-selection preserves the selection. Right-clicking on a cell outside the selection clears the selection and selects only that cell.

### Design

- In `open_context_menu`, replace the `item.isSelected()` check with a `selectedRanges()` check that tests whether `(row, column)` falls within any selected range.
- Add a helper method `is_cell_in_selection(row, column)` that iterates `self.table.selectedRanges()` and returns `True` if the cell is within any range's row/column span.
- If the cell is in selection: do nothing to selection, just set `setCurrentCell(row, column)` (which doesn't clear selection).
- If the cell is not in selection: clear selection and select only that cell (existing behavior).
- Ensure the item exists (create if null) before setting current cell, but only clear/select if the cell is outside the selection — the item creation itself doesn't affect selection state.

### Edge Cases

- Right-clicking on empty space (no row/column): no action, just show context menu with minimal options (existing behavior).
- Right-clicking on a header: uses `selectRow`/`selectColumn` which is separate from cell context menu (no change needed).

## Feature 4: Translate Full Table & Translate Empty Cells

### Current Behavior

Translation is only available via right-click context menu for selected cells, rows, or columns. There's no way to translate the entire table at once.

### Desired Behavior

Two new actions in the "File" menu:
- **Translate Full Table**: Translates all translatable cells in the table (all rows, all language columns except source column and `Language` column). Overwrites existing translations.
- **Translate Empty Cells**: Translates only cells that are currently empty, across the same column scope. Does not overwrite existing translations.

### Design

- Add two `QAction`s in `create_menus`, placed in the File menu after Save As and before the config.cpp import separator.
- Add UI text entries for both actions in `UI_TEXT` for `en` and `zh`.
- `translate_full_table()`: builds jobs for all rows × all translatable columns using the source column. Reuses `build_column_translation_jobs` with all translatable column indices.
- `translate_empty_cells()`: same scope, but filters to only include cells where the current cell text is empty/whitespace. Builds jobs manually by iterating rows and translatable columns, checking cell text.
- Both methods show a confirmation dialog before starting (since they can be expensive).
- Both reuse `run_translation_jobs` for execution.
- A "translatable column" is defined by `is_translatable_column(column)` (existing method: column > 0, has a language code, within visible headers).
- Source column (from `self.source_header`) is excluded from translation targets.

### Edge Cases

- No CSV loaded: show a warning message (same as import).
- No source column configured or source column not found: show warning (same as existing translate actions).
- Table is empty (0 rows): show information dialog that there's nothing to translate.
- All cells already translated (for "Translate Empty Cells"): show information dialog that no empty cells were found.

## Testing

- **Feature 1**: Test that switching preset combo loads values automatically. Test that `*` appears when field values change. Test that `*` disappears after saving. Test that "Open" button is gone.
- **Feature 2**: Test that `last_file_dir` is updated after open/save. Test that `QFileDialog` receives `last_file_dir` as starting path (mock `QFileDialog`).
- **Feature 3**: Test that right-clicking within a multi-selection preserves selection. Test that right-clicking outside selection clears and selects only that cell. Test with empty cells (no item).
- **Feature 4**: Test that `translate_full_table` builds jobs for all translatable cells. Test that `translate_empty_cells` only builds jobs for empty cells. Test confirmation dialog. Test edge cases (no CSV, no source column, empty table).
