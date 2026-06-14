# Wordbook Design

## Goal

Add a separate wordbook feature for user-defined terminology. The wordbook is edited in a table like the main DayZ CSV editor, saved as its own CSV file, and used only by the OpenAI translation engine as glossary context.

## Scope

- Add a Wordbook menu entry that opens an independent wordbook window.
- Use fixed DayZ language columns without the `Language` column and without the trailing empty CSV column.
- Start with one empty row.
- Automatically append a new empty row when the current last row receives any content.
- Save and load the wordbook as an independent CSV file.
- Include loaded wordbook entries in OpenAI translation prompts.
- Do not apply the wordbook to Google, DeepL, Microsoft, or MyMemory engines.

## Wordbook Columns

The fixed wordbook headers are:

```text
original, english, czech, german, russian, polish, hungarian, italian, spanish, french, chinese, japanese, portuguese, chinesesimp
```

The wordbook intentionally omits:

- `Language`
- the trailing empty column used by DayZ `stringtable.csv`

## CSV Behavior

The wordbook CSV will be handled by a dedicated `wordbook_csv.py` module.

Rules:

- Save with the fixed wordbook header order.
- Quote every cell with double quotes, matching the existing DayZ CSV style.
- Escape inner double quotes by doubling them.
- On load, accept files with the fixed wordbook headers.
- If a supported language column is missing, fill it with empty values by header name.
- Reject unsupported columns so mistakes are visible.
- Do not use the `stringtable.csv` trailing comma rule.

## UI Behavior

The main window gets a `Wordbook` menu or action. Activating it opens a separate modeless wordbook window.

The wordbook window contains:

- a `QTableWidget`
- open/save/save-as actions
- the fixed wordbook headers
- one initial empty row when no file is loaded

Auto-row behavior:

- When the user edits the last row and any cell in that row becomes non-empty, append exactly one new empty row.
- Do not append multiple blank rows while the last row is already blank.
- Save ignores the final trailing blank row.

## Translation Behavior

Only the OpenAI engine uses the wordbook.

When translation starts:

- The main window reads non-empty wordbook rows from the open wordbook window.
- A wordbook row is useful only when it has at least one source-side term and at least one target-side term.
- The wordbook entries are passed into `TranslatorConfig` or another explicit translation context object.

For OpenAI requests:

- The prompt includes a `glossary` JSON array.
- Each glossary item contains the available language values from one wordbook row.
- During translation, the model is instructed to use glossary terms when a matching source term and target language value exist.
- If the target language cell is empty for a glossary row, that glossary row is skipped for that target language.

Non-OpenAI engines:

- Ignore the wordbook.
- Do not attempt post-translation string replacement.

## Testing

Add focused tests for:

- wordbook CSV save/load with fixed headers and quoted cells
- missing supported columns are filled by header name
- unsupported columns are rejected
- wordbook table starts with one empty row
- editing the last row appends one empty row
- save ignores the final empty row
- main menu can open the wordbook window
- OpenAI prompt payload includes glossary data
- non-OpenAI translation remains unchanged

## Non-Goals

- No automatic machine translation inside the wordbook itself.
- No merging wordbook data into `stringtable.csv`.
- No glossary support for non-OpenAI engines in this change.
- No new database or settings format.
