# DayZ Translate Tool

[![release](https://img.shields.io/github/v/release/MengYYY369/DayZ_Translate_Tool?label=release&color=4c1)](https://github.com/MengYYY369/DayZ_Translate_Tool/releases)
![license](https://img.shields.io/badge/license-GPL--3.0-blue)
![platform](https://img.shields.io/badge/platform-Windows-0078d4)
![python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![Qt](https://img.shields.io/badge/UI-Qt%206%20%C2%B7%20PySide6-41cd52)
![tests](https://img.shields.io/badge/tests-570%20passing-4c1)

**English** · [简体中文](README.zh-CN.md)

A desktop tool for translating DayZ mod localization. Open a mod's `stringtable.csv`, let keyless free sources or your own AI endpoint translate the columns you pick, and save the file back — no more copy-pasting rows into a web translator.

![Main window](docs/images/main-window.png)

## Features

### Sources you can mix freely

- **Six keyless free sources** — Google, Microsoft Edge, Tencent Interactive, Volcano, Lara and MyMemory. No account, no API key, works right after install.
- **DeepL** — optional, uses your own API key.
- **AI sources** — anything speaking the OpenAI chat protocol, plus Claude and Codex. Add as many as you like; each keeps its own key, model, concurrency and request interval.
- **Priority with automatic failover** — the list is ordered. If the top source dies mid-run, the remaining rows continue on the next one, and the status bar tells you it happened.
- **Per-source rules** — every source has its own checkboxes: *all cells*, *empty cells only* or *selections only*. Order plus rules decide what actually runs.
- **Test button per source** — fires a 4-language smoke test and shows you the result, or the real error, straight away.
- **Retry and rate limits** — failed requests are retried with exponential backoff that honours `Retry-After`. Concurrency and interval are per source, so you don't get throttled into oblivion. Afterwards you can retry just the cells that failed.

### Translation that adapts to the table

- **Exactly the scope you ask for** — translate the whole table, only the empty cells, or just the selection (right-click → cells / rows / columns).
- **Translation cache** — results are cached by source, text and language, and survive restarts.
- **Glossary / wordbook** — a `wordbook.csv` you maintain yourself. Matching entries are handed to the AI sources as terminology, so names stay consistent.
- **Long cells are split** at line breaks to fit a source's per-request limit; the pieces do not share context.

### Built-in quality check

- **27 local rules** scan the finished translations and flag the suspicious cells: a lost placeholder, a number that no longer matches, full-width punctuation, a cell that simply copied its source, a glossary term that never made it in...
- **It only flags** — it never edits and never goes online. Filter the table down to the flagged cells and retranslate just those.

### Editing the table itself

- **DayZ `stringtable.csv` handling** — reads and writes the game's 15-column format, UTF-8 with or without BOM. Malformed rows are repaired on load: columns are matched by header name, short rows padded, stray ones trimmed.
- **Undo/redo and the usual edits** — insert or delete rows and columns, delete cells, fill a whole row from one cell, reset the column order, search with whole-word and case matching.
- **Import keys from `config.cpp`** — point it at one file, several, or a whole folder, and it pulls out the string keys your CSV is still missing.
- **Split stuck words** — English glued into one token (`AsaraShotGun`, `VirusHealerAngelBP`) can be split via right-click → `Split Stuck Words` into `Asara Shot Gun`, `Virus Healer Angel BP`. Only fully glued cells are touched; names with digits like `AK74` or `M4A1` are left alone.
- **Interface language** — English and 简体中文.

## Screenshots

Translation settings — the ordered source list, with per-source rules and test buttons:

![Translation sources](docs/images/translation-sources.png)

Adding an AI source (here: a free public OpenAI-compatible endpoint):

![Add AI source](docs/images/add-ai-source.png)

<details>
<summary>中文界面截图</summary>

![主界面](docs/images/main-window.zh-CN.png)
![翻译源设置](docs/images/translation-sources.zh-CN.png)

</details>

## Quick start

Requirements: **Windows** and **Python 3.10+** (the interface is Qt 6, through PySide6).

```bash
pip install -r requirements.txt
python main.py
```

Or download the prebuilt `DayZ_Translate_Tool` from the [releases page](../../releases) and double-click the exe.

## How to use

1. **Open your file** — `File → Open` (`Ctrl+O`), then pick the mod's `stringtable.csv`. It usually sits at `<mod>\addons\<something>\stringtable.csv`.
2. **Tell it what you already have** — `Settings → Source Language`, and choose the column holding the text you want to translate *from* (usually `english`). That column is never overwritten.
3. **Enable sources** — `Settings → Translation Settings...`. Tick the boxes next to each source to decide whether it may translate all cells, only empty cells, or right-click selections. Drag with ▲▼ to set priority and use ▶ to test one.
4. **Translate** — `File → Translate All Cells` / `Translate Empty Cells`, or select cells and right-click → `Translate Selected Cells`. Progress and the running tally (`translated / failed / cache hits`) show up in the status bar, and the run can be cancelled at any time.
5. **Save** — `Ctrl+S`. The `original` column is copied from `english` and `chinese` from `chinesesimp` automatically, exactly like the game expects.

### Adding a free AI source

Some public endpoints speak the OpenAI chat-completions protocol and need no key at all.

`Settings → Translation Settings... → + Add AI source`

| Field | Example |
|---|---|
| Name | `Index-Translate` |
| Interface | `OpenAI compatible` |
| Base URL | `https://index-translate.bilibili.com/v1` |
| API Key | any non-empty text (e.g. `index`) — the field cannot be left blank |
| Model | `Index-Translate-35B-A3B` |

That endpoint comes from the [Index-Translate](https://github.com/bilibili/Index-Translate) project. Its availability and quota are entirely up to them, so treat it as a bonus source rather than a promise.

## Command line

<details>
<summary>Everything the window does, without the window</summary>

The whole tool also runs headless, which makes it convenient for scripts — and for letting an AI agent work on a table on its own. It goes through exactly the same code and the same settings as the window, so the source list you configured in `Settings → Translation Settings...` is the one the command line uses.

```bash
python cli.py <command> [options]
```

| Command | What it does |
|---|---|
| `inspect <csv>` | List the columns, how many cells each language column holds, and which rows have no source text |
| `translate <csv>` | Translate the table; `--mode empty` (default) / `all` / `columns` / `rows`, narrowed further with `--columns a,b`, `--rows 3,5-9`, `--only-empty`, `--source ID`, `--from-column english`, `--wordbook PATH` |
| `edit set-cell <csv> --row N --column COL --text "..."` | Write a single cell |
| `edit replace <csv> --column COL --find OLD --replace NEW [--regex] [--ignore-case] [--whole-word]` | Find and replace inside one column |
| `edit add-row <csv> --key NAME [--after N]` | Insert a row |
| `edit delete-row <csv> --row N` / `--key NAME` | Delete a row |
| `keys <csv> --from <config.cpp or a folder>` | Import the keys that are missing from a mod's `config.cpp` |
| `wordbook list` / `set --original X --language chinesesimp --text 刀` / `remove --original X` / `import <csv>` / `export <csv>` | Read and edit the glossary |
| `sources list` / `test [--source ID]` / `add-ai ...` / `remove ID` / `move ID --up` / `--down` / `set-rule ID --rules all,empty` / `set-key ID --key ...` | Read and edit the source list |
| `cache stats` / `clear` | Inspect or empty the translation cache |

Every command accepts `--json` (the result as JSON on stdout, progress on stderr) and `--quiet`.

**Nothing is written unless you ask for it.** `translate`, `edit` and `keys` only read the file and put the result in a preview file (`stringtable.preview.csv`, or whatever `--preview` points at). Add `--write` to actually replace the table; a `.bak` copy is saved first. Commands that only change settings (`sources`, `wordbook`, `cache`) take effect right away — if the window is open, reopen it to see them.

Exit codes: `0` all good, `1` the command ran but something failed (cells that could not be translated, or a source that did not pass `sources test`), `2` the command could not run at all.

A few typical runs:

```bash
python cli.py inspect stringtable.csv
python cli.py translate stringtable.csv --mode empty --json
python cli.py translate stringtable.csv --write
python cli.py sources test
```

</details>

## Notes and limitations

<details>
<summary>Read this before translating a whole mod</summary>

- **Free sources are unofficial.** They are the same public endpoints a browser talks to, so they can be rate-limited or changed without notice. In practice Google starts answering `HTTP 429` after a few dozen requests, and MyMemory caps you at roughly 5000 characters per day. The tool reports these errors instead of hiding them, and failover moves the remaining rows to the next source.
- **Free sources translate text only.** The glossary/wordbook is used by AI sources, because the free endpoints have no way to receive terminology.
- **One-at-a-time sources** (Volcano, Lara, MyMemory) accept a single text per request, so a big table means a lot of requests. Give them a sensible interval and keep a faster source above them.
- **Long cells are split** at line breaks to fit a source's per-request limit; context is not shared across the pieces of one cell.
- **DeepL needs a key**, so it ships disabled. Everything else works out of the box.
- The interface follows your Windows theme (light or dark).

</details>

## Files the tool writes

| File | Location | Purpose |
|---|---|---|
| `stringtable.csv` | wherever you saved it (default: next to the exe) | the mod's translations |
| `wordbook.csv` | `%LOCALAPPDATA%\DayZTranslateTool\...` (created on demand) | your glossary |
| `translation_cache.json` | next to the exe; falls back to `%LOCALAPPDATA%\DayZ_Translate_Tool\` if that folder is read-only | cached translations |
| application settings | Windows registry, `HKCU\Software\DayZTranslateTool` | sources, rules, window state, interface language |

## Building a standalone exe

<details>
<summary>PyInstaller build</summary>

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
# or point it at a specific interpreter:
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -PythonPath "C:\Python313\python.exe"
```

The script installs and uses PyInstaller, then builds into `dist\DayZ_Translate_Tool\`. Because PyInstaller wipes the output folder, the script backs up and restores the `stringtable.csv` / `wordbook.csv` sitting next to the exe.

</details>

## Development

<details>
<summary>Project layout and tests</summary>

```bash
python -m unittest discover -s tests     # 570 tests, no network access needed
```

| Module | Responsibility |
|---|---|
| `main.py` | Qt window, table, dialogs, menus, settings persistence |
| `dayz_csv.py` | stringtable.csv reading/writing, repair, translation job building |
| `wordbook_csv.py` | glossary file format |
| `config_cpp.py` | pulling keys out of `config.cpp` |
| `translation_sources.py` | the ordered source list model (rules, AI entries, JSON persistence) |
| `translator_service.py` | job planning, batching, retries, caching, fallback |
| `free_translators.py` | the six keyless translators |
| `translation_worker.py` | runs a translation in a background thread |
| `translation_flow.py` | the headless translation flow shared by the window and the command line |
| `cli.py` | the command-line entry point |
| `table_history.py` | undo/redo snapshots |
| `translation_cache.py` | on-disk cache |
| `quality_check.py` | the local quality rules that flag suspicious translations |
| `quality_check_worker.py` | runs a quality check in a background thread |
| `word_split.py` | splitting glued-together English |

`smoke_free_sources.py` pings every free source once from the command line — handy to check whether a `429` is your network or the provider.

</details>

## License

[GNU General Public License v3.0](LICENSE).

Third-party components: [PySide6 / Qt 6](https://www.qt.io/) (LGPL-3.0 / GPL-3.0) and [deep-translator](https://github.com/nidhaloff/deep-translator) (Apache-2.0).

## Disclaimer

Unofficial community tool, not affiliated with or endorsed by Bohemia Interactive. DayZ is a trademark of Bohemia Interactive. The free translation endpoints are undocumented public services — use them at a sane pace and respect their terms of service.