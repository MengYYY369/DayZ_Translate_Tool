# Delete Selected Cells Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multi-select-only context menu action that clears every selected cell, while keeping single-cell Delete Cell unchanged.

**Architecture:** Detect multi-cell selection via `selectedRanges()` area/count. Show `delete_selected_cells` only when multi-selected. Clear by iterating ranges and calling existing `set_cell_text`.

**Tech Stack:** Python 3, PySide6 `QTableWidget` / `QTableWidgetSelectionRange`, pytest.

## Global Constraints

- Keep existing `delete_cell` / `delete_cell_text` single-cell behavior.
- New action only appears for multi-cell selection on cell context menu.
- Clear via `selectedRanges()` + `set_cell_text` (not only `selectedItems()`).
- UI strings in both `en` and `zh`.
- No keyboard shortcut, no Wordbook changes, no cut/copy/paste changes.

## File Map

| File | Responsibility |
|------|----------------|
| `main.py` | UI strings, multi-select helper, menu wiring, `delete_selected_cells` |
| `tests/test_main_gui.py` | Menu visibility + clear behavior tests |

---

### Task 1: Multi-select delete action

**Files:**
- Modify: `main.py` — `UI_TEXT`, `has_multi_cell_selection`, `delete_selected_cells`, `context_action_names`, `show_context_menu` action_map
- Test: `tests/test_main_gui.py`

**Interfaces:**
- Produces: `DayzTranslateTool.has_multi_cell_selection() -> bool`
- Produces: `DayzTranslateTool.delete_selected_cells() -> None`
- Consumes: `DayzTranslateTool.set_cell_text(row_index, column_index, text)`
- Consumes: `self.table.selectedRanges()`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main_gui.py` (near existing delete tests):

```python
    def test_context_menu_includes_delete_selected_cells_when_multi_selected(self):
        table = self.window.table
        table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 4), True)

        actions = self.window.context_action_names(context="cell", row=0, column=2)

        self.assertIn("delete_cell", actions)
        self.assertIn("delete_selected_cells", actions)

    def test_context_menu_omits_delete_selected_cells_for_single_cell(self):
        table = self.window.table
        table.clearSelection()
        table.setCurrentCell(0, 2)
        item = table.item(0, 2)
        if item is not None:
            item.setSelected(True)

        actions = self.window.context_action_names(context="cell", row=0, column=2)

        self.assertIn("delete_cell", actions)
        self.assertNotIn("delete_selected_cells", actions)

    def test_delete_selected_cells_clears_all_selected_cells(self):
        table = self.window.table
        self.window.set_cell_text(0, 2, "A")
        self.window.set_cell_text(0, 3, "B")
        self.window.set_cell_text(1, 2, "C")
        self.window.set_cell_text(1, 3, "D")
        self.window.set_cell_text(0, 5, "Keep")
        table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 3), True)
        self.window.set_dirty(False)

        self.window.delete_selected_cells()

        self.assertEqual(table.item(0, 2).text(), "")
        self.assertEqual(table.item(0, 3).text(), "")
        self.assertEqual(table.item(1, 2).text(), "")
        self.assertEqual(table.item(1, 3).text(), "")
        self.assertEqual(table.item(0, 5).text(), "Keep")
        self.assertTrue(self.window.is_dirty)

    def test_delete_selected_cells_clears_empty_items_in_range(self):
        table = self.window.table
        self.window.set_cell_text(0, 2, "A")
        # leave (1, 2) without forcing content beyond empty selection coverage
        table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 2), True)
        self.window.set_dirty(False)

        self.window.delete_selected_cells()

        self.assertEqual(self.window.table.item(0, 2).text(), "")
        self.assertEqual(self.window.table.item(1, 2).text(), "")
        self.assertTrue(self.window.is_dirty)

    def test_delete_selected_cells_chinese_label(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        self.window.table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 3), True)

        labels = self.window.context_action_labels(context="cell", row=0, column=2)

        self.assertIn("删除选中单元格", labels)
```

Ensure imports already include `QTableWidgetSelectionRange` (already used in this file).

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_main_gui.py -k "delete_selected_cells or context_menu_includes_delete_selected or context_menu_omits_delete_selected" -v
```

Expected: FAIL with missing method/attribute/`delete_selected_cells` not in actions / missing UI key.

- [ ] **Step 3: Add UI strings**

In `main.py` `UI_TEXT["en"]`, after `"delete_cell"`:

```python
        "delete_selected_cells": "Delete Selected Cells",
```

In `UI_TEXT["zh"]`, after `"delete_cell"`:

```python
        "delete_selected_cells": "删除选中单元格",
```

- [ ] **Step 4: Implement helper + delete method**

Add near `is_cell_in_selection` / `delete_cell_text` in `DayzTranslateTool`:

```python
    def has_multi_cell_selection(self):
        ranges = self.table.selectedRanges()
        if len(ranges) > 1:
            return True
        for selected_range in ranges:
            rows = selected_range.bottomRow() - selected_range.topRow() + 1
            columns = selected_range.rightColumn() - selected_range.leftColumn() + 1
            if rows * columns > 1:
                return True
        return False

    def delete_selected_cells(self):
        ranges = self.table.selectedRanges()
        if not ranges:
            return
        for selected_range in ranges:
            for row_index in range(selected_range.topRow(), selected_range.bottomRow() + 1):
                for column_index in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                    self.set_cell_text(row_index, column_index, "")
```

- [ ] **Step 5: Wire context menu**

In `show_context_menu` `action_map`, after `delete_cell`:

```python
            "delete_selected_cells": self.delete_selected_cells,
```

In `context_action_names`, change the cell branch to:

```python
        elif context == "cell" and row >= 0 and column >= 0:
            actions.append("delete_cell")
            if self.has_multi_cell_selection():
                actions.append("delete_selected_cells")
```

Do not change `delete_cell_text`.

- [ ] **Step 6: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_main_gui.py -k "delete_selected_cells or context_menu_includes_delete_selected or context_menu_omits_delete_selected or delete_cell_clears" -v
```

Expected: all selected tests PASS.

Also run full GUI suite if time allows:

```bash
python -m pytest tests/test_main_gui.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main_gui.py docs/superpowers/plans/2026-07-21-delete-selected-cells.md
git commit -m "feat: add delete selected cells context menu action"
```

---

## Spec Coverage Self-Review

| Spec requirement | Task |
|------------------|------|
| Keep single-cell Delete Cell | Task 1 (unchanged `delete_cell_text`, always append `delete_cell`) |
| New action only when multi-selected | Task 1 (`has_multi_cell_selection` + menu append) |
| Clear all selected via ranges | Task 1 (`delete_selected_cells`) |
| Empty items in range cleared | Task 1 test + `set_cell_text` |
| en/zh labels | Task 1 UI_TEXT |
| No row/column header / Wordbook / shortcut changes | Out of task scope, not modified |

## Placeholder Scan

No TBD/TODO placeholders. Concrete code and commands included.

## Type Consistency

- `has_multi_cell_selection()` → bool
- `delete_selected_cells()` → None
- Action key: `delete_selected_cells` (menu + UI_TEXT + action_map)
