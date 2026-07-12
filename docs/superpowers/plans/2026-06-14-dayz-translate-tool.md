# DayZ Translate Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a focused DayZ `stringtable.csv` editor with context-menu translation powered by `deep-translator`.

**Architecture:** Keep CSV parsing, CSV writing, and translation target selection in a testable core module. Keep the PySide6 GUI thin: it loads core data into a table, collects selections, and calls translation helpers.

**Tech Stack:** Python 3.10, PySide6, deep-translator, unittest.

---

### Task 1: Core CSV Helpers

**Files:**
- Create: `dayz_csv.py`
- Create: `tests/test_dayz_csv.py`

- [ ] Write tests for loading a DayZ CSV where the first row becomes headers.
- [ ] Write tests for saving all cells with double quotes.
- [ ] Implement `load_dayz_csv(path)` and `write_dayz_csv(path, headers, rows)`.
- [ ] Run `py -3 -m unittest discover -s tests`.

### Task 2: Translation Selection Helpers

**Files:**
- Modify: `dayz_csv.py`
- Modify: `tests/test_dayz_csv.py`

- [ ] Write tests for mapping DayZ column names to translator language codes.
- [ ] Write tests for selected-row and selected-column target planning.
- [ ] Implement `language_code_for_header`, `build_row_translation_jobs`, and `build_column_translation_jobs`.
- [ ] Run `py -3 -m unittest discover -s tests`.

### Task 3: GUI

**Files:**
- Create: `main.py`
- Create: `requirements.txt`

- [ ] Build a larger `QMainWindow` with menu actions for Open, Save, Save As, and Settings.
- [ ] Use a single `QTableWidget` with headers from `stringtable.csv`.
- [ ] Add a table context menu for copy, paste, cut, translate selected cells, translate selected rows, and translate selected columns.
- [ ] Use `deep_translator.GoogleTranslator` lazily inside translation actions.
- [ ] Run `py -3 -m py_compile dayz_csv.py main.py`.

### Task 4: Final Verification

**Files:**
- Verify only.

- [ ] Run `py -3 -m unittest discover -s tests`.
- [ ] Run `py -3 -m py_compile dayz_csv.py main.py`.
- [ ] Confirm `requirements.txt` contains `PySide6` and `deep-translator`.
