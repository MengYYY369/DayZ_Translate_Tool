# DayZ Translate Tool Design

## Goal

Build a small PySide6 desktop editor for DayZ `stringtable.csv` files. It imports the local DayZ CSV format, edits cells in a table, and translates selected cells, rows, or columns through `deep-translator`.

## Assumptions

- The supported CSV shape is DayZ `stringtable.csv`: the first row contains fixed column names such as `Language`, `original`, `english`, and `chinesesimp`.
- The first row is shown as the table header, not as editable data.
- CSV output must quote every cell with double quotes.
- Translation source language is configured in Settings.
- If the configured source-language cell for a row is empty, row translation skips that row.

## UI

- The main window is larger than the original CSVeditor window.
- The table is the primary surface.
- Removed features: font style toolbar, font size controls, color controls, multi-table creation, and replace controls.
- Right-clicking the table opens a context menu with Copy, Paste, Cut, Translate Selected Cells, Translate Selected Rows, and Translate Selected Columns.
- Multi-selection is supported. Row and column translation deduplicate all selected rows or columns.

## Data Flow

- Load CSV with Python's `csv` module.
- Validate that the first header cell is `Language`.
- Set horizontal table headers from the first CSV row.
- Populate table rows from remaining CSV rows.
- Save by combining the fixed header with table rows and writing through `csv.writer(..., quoting=csv.QUOTE_ALL)`.

## Translation

- Use `deep_translator.GoogleTranslator`.
- Settings stores the source language column name, defaulting to `english`.
- Target language is inferred from the target column name when possible.
- Translate Selected Cells overwrites each selected cell with its translated value.
- Translate Selected Rows translates from the configured source column into selected target columns in the same row; if no target columns are selected, all language columns except `Language` and the source column are targets.
- Translate Selected Columns translates each selected column using the configured source column in the same row.

## Verification

- Unit tests cover CSV parsing, quoted CSV writing, source-empty row skipping, row target selection, and DayZ language-code mapping.
- Syntax verification runs on the created Python files.
