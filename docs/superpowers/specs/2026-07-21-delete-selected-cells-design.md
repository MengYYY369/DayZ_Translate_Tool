# Delete Selected Cells Design

## Goal

When multiple table cells are selected, the context menu should offer a new action that clears every selected cell. The existing single-cell delete action stays unchanged.

## Background

Multi-select right-click already preserves the selection (`is_cell_in_selection` + `open_context_menu`). However, **Delete Cell** (`delete_cell_text`) only clears `currentRow` / `currentColumn` — the cell under the right-click. Users who multi-select and choose delete expect either a dedicated multi-delete action.

`cut_selection` already clears all `selectedItems()`, but it also writes the clipboard. That is not a substitute for delete-selected.

## Desired Behavior

| Scenario | Context menu | Behavior |
|----------|--------------|----------|
| Single cell selected (or only current cell) | `Delete Cell` only | Clear current cell (existing) |
| Multiple cells selected | `Delete Cell` **and** `Delete Selected Cells` | Former clears only current/right-clicked cell; latter clears all selected cells |
| Row / column header menus | Unchanged | Existing delete row / delete column |

### Multi-selection definition

Treat the table as multi-selected when either:

1. more than one `selectedRanges()` entry exists, or
2. any single range has area `(bottomRow - topRow + 1) * (rightColumn - leftColumn + 1) > 1`.

Otherwise show only the single-cell delete action.

## Design

### 1. `delete_selected_cells()`

- Iterate `self.table.selectedRanges()`.
- For every `(row, column)` inside each range, call `self.set_cell_text(row, column, "")`.
- Prefer ranges over `selectedItems()` so empty / null items in the selection are still cleared.
- No-op when there are no selected ranges.
- Dirty flag is set via existing `set_cell_text` behavior (same as other edits).

### 2. Context menu wiring

- Add UI keys:
  - en: `delete_selected_cells` → `"Delete Selected Cells"`
  - zh: `delete_selected_cells` → `"删除选中单元格"`
- In `context_action_names`, for `context == "cell"` after appending `delete_cell`: if multi-selected, also append `delete_selected_cells`.
- Register the action in `show_context_menu`'s `action_map` → `self.delete_selected_cells`.

Optional small helper: `has_multi_cell_selection()` implementing the multi-selection definition above, used by `context_action_names` (and tests). Keep it local to the main window; no new module.

### 3. Unchanged

- `delete_cell_text` — still single current cell only.
- `cut_selection` / `copy_selection` / paste / translate actions.
- Row-header and column-header menus.
- Keyboard Delete shortcut (out of scope; none added).
- Wordbook window (no cell context-menu system).

## Testing

1. Multi-select ≥ 2 cells → `context_action_names("cell", ...)` includes `delete_selected_cells`.
2. Single-cell selection → action list does **not** include `delete_selected_cells`.
3. `delete_selected_cells()` clears every cell in the selected range(s); cells outside the selection keep their text; `is_dirty` becomes true.
4. Range that includes empty/null items still ends empty after delete (via `set_cell_text`).

## Out of Scope

- Changing Delete key / keyboard shortcuts
- Renaming or removing existing **Delete Cell**
- Merging multi-delete into `delete_cell_text`
- Wordbook table context menus
