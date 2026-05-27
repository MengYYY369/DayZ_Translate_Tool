from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, DISABLED, END, LEFT, NORMAL, RIGHT, X, Y

from .ai import AzureTranslator, BingFreeTranslator, GoogleTranslateTranslator, OpenAICompatibleTranslator, OpencodeCliTranslator, YandexFreeTranslator, list_opencode_models
from .config import DEFAULT_LANGUAGE_COLUMNS, AppConfig, load_config, save_config
from .scanner import scan_translation_keys
from .stringtable import StringTable


CHECKED_TEXT = "☑"
UNCHECKED_TEXT = "☐"
SELECT_COLUMN_ID = "__selected__"
SHELL_PAGES = (
    ("translate", "译", "Translate"),
    ("settings", "设", "Settings"),
    ("glossary", "词", "Glossary"),
)


def shell_page_keys() -> tuple[str, ...]:
    return tuple(page[0] for page in SHELL_PAGES)


def shell_page_title(page_key: str) -> str:
    for key, _nav_text, title in SHELL_PAGES:
        if key == page_key:
            return title
    return page_key


def format_translation_task_summary(row_count: int, target_columns: list[str]) -> str:
    safe_rows = max(0, int(row_count))
    target_count = len(target_columns)
    return f"选中 {safe_rows} 行 · 目标 {target_count} 列 · 预计 {safe_rows * target_count} 项"


def format_select_all_heading(visible_row_indices: list[int], selected_row_indices: set[int]) -> str:
    if not visible_row_indices:
        return UNCHECKED_TEXT
    return CHECKED_TEXT if set(visible_row_indices).issubset(selected_row_indices) else UNCHECKED_TEXT


class DayZTranslateApp(ttk.Window):
    def __init__(self):
        super().__init__(themename="cosmo")
        self.title("DayZ Translate Tool")
        self.geometry("1800x980")
        self.minsize(1240, 720)
        self.config_data = load_config()
        self.table: StringTable | None = None
        self.current_path: Path | None = None
        self.dirty = False
        self.column_ids: list[str] = []
        self.visible_column_indices: list[int] = []
        self.selected_row_indices: set[int] = set()
        self.target_vars: dict[str, tk.BooleanVar] = {}
        self.cancel_event = threading.Event()
        self.edit_entry: tk.Entry | None = None
        self._configure_styles()
        self._build_ui()
        self._load_default_csv()
        self._maximize_window()

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            self.geometry("1800x980")

    def _configure_styles(self) -> None:
        self.style.configure(".", font=("Segoe UI", 9))
        self.style.configure("App.TFrame", background="#edf5fb")
        self.style.configure("Nav.TFrame", background="#f7fbff")
        self.style.configure("Page.TFrame", background="#edf5fb")
        self.style.configure("Card.TFrame", background="#ffffff", borderwidth=1, relief="solid")
        self.style.configure("Panel.TFrame", background="#ffffff", borderwidth=1, relief="solid")
        self.style.configure("PageTitle.TLabel", background="#edf5fb", foreground="#111827", font=("Segoe UI", 18, "bold"))
        self.style.configure("SectionTitle.TLabel", background="#ffffff", foreground="#111827", font=("Segoe UI", 11, "bold"))
        self.style.configure("Muted.TLabel", background="#ffffff", foreground="#52616f", font=("Segoe UI", 9))
        self.style.configure("NavMuted.TLabel", background="#f7fbff", foreground="#52616f", font=("Segoe UI", 9))
        self.style.configure("TaskSummary.TLabel", background="#ffffff", font=("Segoe UI", 9), foreground="#52616f")
        self.style.configure("Nav.TButton", background="#f7fbff", foreground="#1f2933", borderwidth=0, relief="flat", padding=(10, 9), font=("Segoe UI", 10))
        self.style.configure("NavSelected.TButton", background="#e5f3ff", foreground="#003e73", borderwidth=0, relief="flat", padding=(10, 9), font=("Segoe UI", 10, "bold"))
        self.style.map("Nav.TButton", background=[("active", "#eef7ff")], foreground=[("active", "#003e73")])
        self.style.map("NavSelected.TButton", background=[("active", "#d5ecff")], foreground=[("active", "#003e73")])
        self.style.configure("TLabelframe", background="#ffffff", borderwidth=1, relief="solid")
        self.style.configure("TLabelframe.Label", background="#ffffff", font=("Segoe UI", 9, "bold"), foreground="#24364b")
        self.style.configure(
            "Grid.Treeview",
            rowheight=27,
            borderwidth=0,
            relief="flat",
            fieldbackground="#ffffff",
            background="#ffffff",
            foreground="#1f2933",
            font=("Segoe UI", 9),
        )
        self.style.configure(
            "Grid.Treeview.Heading",
            borderwidth=0,
            relief="flat",
            padding=(8, 6),
            background="#eef3f8",
            foreground="#24364b",
            font=("Segoe UI", 9, "bold"),
        )
        self.style.map("Grid.Treeview", background=[("selected", "#d7e9fb")], foreground=[("selected", "#102a43")])

    def _build_ui(self) -> None:
        self.path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="准备就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.task_summary_var = tk.StringVar(value=format_translation_task_summary(0, []))
        self.configure(background="#edf5fb")
        self.shell = ttk.Frame(self, style="App.TFrame")
        self.shell.pack(fill=BOTH, expand=True)
        self.pages: dict[str, ttk.Frame] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}
        self._build_nav(self.shell)
        self.content_root = ttk.Frame(self.shell, style="Page.TFrame", padding=(18, 14, 18, 18))
        self.content_root.pack(side=LEFT, fill=BOTH, expand=True)
        self.workbench_tab = ttk.Frame(self.content_root, style="Page.TFrame")
        self.settings_tab = ttk.Frame(self.content_root, style="Page.TFrame")
        self.glossary_tab = ttk.Frame(self.content_root, style="Page.TFrame")
        self.pages["translate"] = self.workbench_tab
        self.pages["settings"] = self.settings_tab
        self.pages["glossary"] = self.glossary_tab
        self._build_workbench_tab()
        self._build_settings_tab()
        self._build_glossary_tab()
        self._show_page("translate")

    def _build_nav(self, parent) -> None:
        nav = ttk.Frame(parent, style="Nav.TFrame", padding=(10, 10))
        nav.pack(side=LEFT, fill=Y)
        ttk.Label(nav, text="DayZ", style="NavMuted.TLabel", anchor="center").pack(fill=X, pady=(0, 12))
        for key, nav_text, _title in SHELL_PAGES:
            button = ttk.Button(nav, text=nav_text, command=lambda page_key=key: self._show_page(page_key), style="Nav.TButton", width=4)
            button.pack(fill=X, pady=3)
            self.nav_buttons[key] = button

    def _show_page(self, page_key: str) -> None:
        for key, page in self.pages.items():
            page.pack_forget()
            if key in self.nav_buttons:
                self.nav_buttons[key].configure(style="Nav.TButton")
        page = self.pages.get(page_key)
        if not page:
            return
        page.pack(fill=BOTH, expand=True)
        if page_key in self.nav_buttons:
            self.nav_buttons[page_key].configure(style="NavSelected.TButton")

    def _build_workbench_tab(self) -> None:
        ttk.Label(self.workbench_tab, text=shell_page_title("translate"), style="PageTitle.TLabel").pack(anchor="w", pady=(0, 12))
        body = ttk.Frame(self.workbench_tab, style="Page.TFrame")
        body.pack(fill=BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=310)
        body.rowconfigure(1, weight=1)
        self._build_actions(body)
        table_host = ttk.Frame(body, style="Page.TFrame")
        table_host.grid(row=1, column=0, sticky="nsew")
        self._build_table(table_host)
        self._build_translation_panel(body)

    def _build_settings_tab(self) -> None:
        ttk.Label(self.settings_tab, text=shell_page_title("settings"), style="PageTitle.TLabel").pack(anchor="w", pady=(0, 12))
        frame = ttk.Labelframe(self.settings_tab, text="翻译引擎", padding=(12, 10))
        frame.pack(fill=X, pady=(0, 10))
        self.backend_var = tk.StringVar(value=self.config_data.ai_backend)
        self.base_url_var = tk.StringVar(value=self.config_data.base_url)
        self.api_key_var = tk.StringVar(value=self.config_data.api_key)
        self.model_var = tk.StringVar(value=self.config_data.model)
        self.azure_key_var = tk.StringVar(value=self.config_data.azure_key)
        self.azure_endpoint_var = tk.StringVar(value=self.config_data.azure_endpoint)
        self.azure_region_var = tk.StringVar(value=self.config_data.azure_region)
        self.opencode_path_var = tk.StringVar(value=self.config_data.opencode_path)
        self.opencode_args_var = tk.StringVar(value=self.config_data.opencode_args)
        self.opencode_port_var = tk.IntVar(value=self.config_data.opencode_port)
        self.opencode_model_var = tk.StringVar(value=self.config_data.opencode_model)
        self.autosave_var = tk.IntVar(value=self.config_data.autosave_every)
        self.max_workers_var = tk.IntVar(value=self.config_data.max_workers)
        self.rate_limit_var = tk.DoubleVar(value=self.config_data.rate_limit_seconds)
        self.timeout_var = tk.IntVar(value=max(240, int(self.config_data.timeout_seconds)))
        ttk.Label(frame, text="后端", width=13).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(frame, textvariable=self.backend_var, values=["google", "api", "opencode", "azure", "bing_free", "yandex_free"], width=18, state="readonly").grid(row=0, column=1, sticky="ew", padx=(6, 18), pady=3)
        ttk.Label(frame, text="并发线程", width=13).grid(row=0, column=2, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=1, to=16, textvariable=self.max_workers_var, width=10).grid(row=0, column=3, sticky="w", padx=(6, 18), pady=3)
        ttk.Label(frame, text="请求间隔(秒)", width=13).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=0, to=60, increment=0.25, textvariable=self.rate_limit_var, width=10).grid(row=1, column=1, sticky="w", padx=(6, 18), pady=3)
        ttk.Label(frame, text="自动保存行数", width=13).grid(row=1, column=2, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=1, to=100, textvariable=self.autosave_var, width=10).grid(row=1, column=3, sticky="w", padx=(6, 18), pady=3)
        ttk.Label(frame, text="请求超时(秒)", width=13).grid(row=2, column=0, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=30, to=900, increment=30, textvariable=self.timeout_var, width=10).grid(row=2, column=1, sticky="w", padx=(6, 18), pady=3)
        frame.columnconfigure(1, weight=1)

        api = ttk.Labelframe(self.settings_tab, text="OpenAI 兼容 API", padding=(12, 10))
        api.pack(fill=X, pady=(0, 10))
        ttk.Label(api, text="base_url", width=13).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(api, textvariable=self.base_url_var).grid(row=0, column=1, sticky="ew", padx=(6, 18), pady=3)
        ttk.Label(api, text="api_key", width=13).grid(row=0, column=2, sticky="w", pady=3)
        ttk.Entry(api, textvariable=self.api_key_var, show="*").grid(row=0, column=3, sticky="ew", padx=(6, 18), pady=3)
        ttk.Label(api, text="model", width=13).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(api, textvariable=self.model_var, width=28).grid(row=1, column=1, sticky="ew", padx=(6, 18), pady=3)
        for column in [1, 3]:
            api.columnconfigure(column, weight=1)

        azure = ttk.Labelframe(self.settings_tab, text="Azure Translator", padding=(12, 10))
        azure.pack(fill=X, pady=(0, 10))
        ttk.Label(azure, text="key", width=13).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(azure, textvariable=self.azure_key_var, show="*").grid(row=0, column=1, sticky="ew", padx=(6, 18), pady=3)
        ttk.Label(azure, text="endpoint", width=13).grid(row=0, column=2, sticky="w", pady=3)
        ttk.Entry(azure, textvariable=self.azure_endpoint_var).grid(row=0, column=3, sticky="ew", padx=(6, 18), pady=3)
        ttk.Label(azure, text="region", width=13).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(azure, textvariable=self.azure_region_var, width=20).grid(row=1, column=1, sticky="ew", padx=(6, 18), pady=3)
        for column in [1, 3]:
            azure.columnconfigure(column, weight=1)

        opencode = ttk.Labelframe(self.settings_tab, text="Opencode CLI", padding=(12, 10))
        opencode.pack(fill=X)
        ttk.Label(opencode, text="程序", width=13).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(opencode, textvariable=self.opencode_path_var).grid(row=0, column=1, sticky="ew", padx=(6, 8), pady=3)
        ttk.Button(opencode, text="选择程序", command=self.choose_opencode_program, bootstyle="secondary").grid(row=0, column=2, padx=(0, 18), pady=3)
        ttk.Label(opencode, text="本地端口", width=13).grid(row=0, column=3, sticky="w", pady=3)
        ttk.Spinbox(opencode, from_=1, to=65535, textvariable=self.opencode_port_var, width=10).grid(row=0, column=4, sticky="w", padx=(6, 18), pady=3)
        ttk.Label(opencode, text="模型", width=13).grid(row=1, column=0, sticky="w", pady=3)
        self.opencode_model_combo = ttk.Combobox(opencode, textvariable=self.opencode_model_var, values=self.config_data.opencode_models, state="normal")
        self.opencode_model_combo.grid(row=1, column=1, sticky="ew", padx=(6, 8), pady=3)
        ttk.Button(opencode, text="刷新模型", command=self.refresh_opencode_models, bootstyle="secondary").grid(row=1, column=2, padx=(0, 18), pady=3)
        ttk.Label(opencode, text="Run 参数", width=13).grid(row=1, column=3, sticky="w", pady=3)
        ttk.Entry(opencode, textvariable=self.opencode_args_var).grid(row=1, column=4, sticky="ew", padx=(6, 18), pady=3)
        opencode.columnconfigure(1, weight=1)
        opencode.columnconfigure(4, weight=1)

    def _build_glossary_tab(self) -> None:
        ttk.Label(self.glossary_tab, text=shell_page_title("glossary"), style="PageTitle.TLabel").pack(anchor="w", pady=(0, 12))
        editor = ttk.Labelframe(self.glossary_tab, text="词条编辑", padding=(10, 8))
        editor.pack(fill=X, pady=(0, 8))
        self.glossary_term_var = tk.StringVar()
        self.glossary_language_var = tk.StringVar(value="english")
        self.glossary_text_var = tk.StringVar()
        self.glossary_note_var = tk.StringVar()
        ttk.Label(editor, text="词条名", width=10).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(editor, textvariable=self.glossary_term_var).grid(row=0, column=1, sticky="ew", padx=(5, 14), pady=3)
        ttk.Label(editor, text="语言", width=8).grid(row=0, column=2, sticky="w", pady=3)
        self.glossary_language_combo = ttk.Combobox(editor, textvariable=self.glossary_language_var, values=DEFAULT_LANGUAGE_COLUMNS, width=16, state="readonly")
        self.glossary_language_combo.grid(row=0, column=3, sticky="ew", padx=(5, 14), pady=3)
        ttk.Label(editor, text="文本", width=10).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(editor, textvariable=self.glossary_text_var).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(5, 14), pady=3)
        ttk.Label(editor, text="备注", width=8).grid(row=1, column=4, sticky="w", pady=3)
        ttk.Entry(editor, textvariable=self.glossary_note_var).grid(row=1, column=5, sticky="ew", padx=(5, 14), pady=3)
        ttk.Button(editor, text="添加/更新", command=self.add_glossary_entry, bootstyle="primary").grid(row=0, column=6, sticky="ew", padx=(0, 6), pady=3)
        ttk.Button(editor, text="删除选中", command=self.delete_glossary_entries, bootstyle="secondary").grid(row=1, column=6, sticky="ew", padx=(0, 6), pady=3)
        for column in [1, 3, 5]:
            editor.columnconfigure(column, weight=1)

        frame = ttk.Frame(self.glossary_tab, borderwidth=1, relief="solid")
        frame.pack(fill=BOTH, expand=True)
        self.glossary_columns = ["term"] + DEFAULT_LANGUAGE_COLUMNS + ["note"]
        self.glossary_tree = ttk.Treeview(frame, columns=self.glossary_columns, show="headings", selectmode="extended", style="Grid.Treeview")
        self.glossary_tree.heading("term", text="词条名")
        self.glossary_tree.column("term", width=150, minwidth=100, stretch=True)
        for column in DEFAULT_LANGUAGE_COLUMNS:
            self.glossary_tree.heading(column, text=column)
            self.glossary_tree.column(column, width=120, minwidth=78, stretch=True)
        self.glossary_tree.heading("note", text="备注")
        self.glossary_tree.column("note", width=220, minwidth=120, stretch=True)
        self.glossary_tree.tag_configure("odd", background="#f8fbff")
        self.glossary_tree.tag_configure("even", background="#ffffff")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.glossary_tree.yview)
        self.glossary_tree.configure(yscrollcommand=yscroll.set)
        self.glossary_tree.pack(side=LEFT, fill=BOTH, expand=True)
        yscroll.pack(side=RIGHT, fill=Y)
        self._reload_glossary_tree()

    def _build_actions(self, parent) -> None:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=(8, 7))
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame.columnconfigure(6, weight=1)
        self.scan_key_prefixes_var = tk.StringVar(value=self.config_data.scan_key_prefixes)
        ttk.Button(frame, text="打开", command=self.open_csv, bootstyle="primary", width=9).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Button(frame, text="保存", command=self.save_csv, bootstyle="primary", width=9).grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Button(frame, text="另存为", command=self.save_csv_as, bootstyle="secondary", width=9).grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Button(frame, text="扫描文件", command=self.scan_file, bootstyle="secondary", width=11).grid(row=0, column=3, sticky="w", padx=(0, 8))
        ttk.Button(frame, text="扫描文件夹", command=self.scan_folder, bootstyle="secondary", width=12).grid(row=0, column=4, sticky="w", padx=(0, 14))
        ttk.Label(frame, text="Key 前缀", style="Muted.TLabel").grid(row=0, column=5, sticky="w", padx=(0, 6))
        ttk.Entry(frame, textvariable=self.scan_key_prefixes_var, width=28).grid(row=0, column=6, sticky="ew")

    def _build_translation_panel(self, parent) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 12))
        panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(12, 0))
        panel.columnconfigure(0, weight=1)
        self.source_var = tk.StringVar()

        ttk.Label(panel, text="Translation Controls", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        ttk.Label(panel, text="源列", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self.source_combo = ttk.Combobox(panel, textvariable=self.source_var, state="readonly")
        self.source_combo.grid(row=2, column=0, sticky="ew", pady=(4, 10))

        ttk.Label(panel, text="目标列", style="Muted.TLabel").grid(row=3, column=0, sticky="w")
        target_panel = ttk.Frame(panel, style="Card.TFrame", padding=(8, 6))
        target_panel.grid(row=4, column=0, sticky="ew", pady=(4, 10))
        target_panel.columnconfigure(0, weight=1)
        self.target_checks_frame = ttk.Frame(target_panel, style="Card.TFrame")
        self.target_checks_frame.grid(row=0, column=0, sticky="ew")

        ttk.Button(panel, text="全选目标", command=self.select_all_targets, bootstyle="secondary").grid(row=5, column=0, sticky="ew", pady=(0, 8))
        self.translate_selected_button = ttk.Button(panel, text="翻译选中行", command=self.translate_selected_rows, bootstyle="primary")
        self.translate_selected_button.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        self.translate_all_button = ttk.Button(panel, text="翻译全部可翻译行", command=self.translate_all_rows, bootstyle="primary")
        self.translate_all_button.grid(row=7, column=0, sticky="ew", pady=(0, 8))
        self.cancel_translation_button = ttk.Button(panel, text="取消当前工作", command=self.cancel_current_work, bootstyle="danger", state=DISABLED)
        self.cancel_translation_button.grid(row=8, column=0, sticky="ew", pady=(0, 12))

        ttk.Label(panel, textvariable=self.task_summary_var, anchor="w", style="TaskSummary.TLabel", wraplength=260).grid(row=9, column=0, sticky="ew", pady=(0, 10))
        self.progress = ttk.Progressbar(panel, variable=self.progress_var, maximum=1, mode="determinate", bootstyle="primary")
        self.progress.grid(row=10, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(panel, textvariable=self.status_var, anchor="nw", style="Muted.TLabel", wraplength=260).grid(row=11, column=0, sticky="nsew")
        panel.rowconfigure(11, weight=1)

    def choose_opencode_program(self) -> None:
        path = filedialog.askopenfilename(title="选择 Opencode 程序", filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path:
            self.opencode_path_var.set(path)

    def refresh_opencode_models(self) -> None:
        self._save_config_from_ui()
        self._set_status("正在获取 Opencode 模型列表")
        thread = threading.Thread(target=self._refresh_opencode_models_worker, daemon=True)
        thread.start()

    def _refresh_opencode_models_worker(self) -> None:
        try:
            models = list_opencode_models(
                self.opencode_path_var.get(),
                refresh=True,
                timeout_seconds=int(self.config_data.timeout_seconds),
            )
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("获取模型失败", str(exc)))
            self.after(0, lambda: self._set_status("获取 Opencode 模型失败"))
            return
        self.after(0, lambda: self._apply_opencode_models(models))

    def _apply_opencode_models(self, models: list[str]) -> None:
        self.config_data.opencode_models = models
        if self.opencode_model_var.get() not in models:
            self.opencode_model_var.set(models[0] if models else "")
        self.opencode_model_combo.configure(values=models)
        self._save_config_from_ui()
        self._set_status(f"已获取 {len(models)} 个 Opencode 模型")

    def add_glossary_entry(self) -> None:
        term = self.glossary_term_var.get().strip()
        language = self.glossary_language_var.get().strip()
        text = self.glossary_text_var.get().strip()
        note = self.glossary_note_var.get().strip()
        if not term or not language or not text:
            messagebox.showwarning("词条不完整", "请填写词条名、语言和文本")
            return
        entries = list(self.config_data.glossary_entries)
        entry = next((item for item in entries if item.get("term") == term), None)
        if entry is None:
            entry = {"term": term}
            entries.append(entry)
        entry[language] = text
        entry["note"] = note
        self.config_data.glossary_entries = entries
        save_config(self.config_data)
        self.glossary_text_var.set("")
        self._reload_glossary_tree()
        self._set_status("已保存自定义词条")

    def delete_glossary_entries(self) -> None:
        selected_terms = {self.glossary_tree.item(iid, "values")[0] for iid in self.glossary_tree.selection()}
        if not selected_terms:
            return
        self.config_data.glossary_entries = [entry for entry in self.config_data.glossary_entries if entry.get("term") not in selected_terms]
        save_config(self.config_data)
        self._reload_glossary_tree()
        self._set_status("已删除选中词条")

    def _reload_glossary_tree(self) -> None:
        for item in self.glossary_tree.get_children():
            self.glossary_tree.delete(item)
        for index, entry in enumerate(self.config_data.glossary_entries):
            tag = "odd" if index % 2 else "even"
            values = [entry.get("term", "")] + [entry.get(column, "") for column in DEFAULT_LANGUAGE_COLUMNS] + [entry.get("note", "")]
            self.glossary_tree.insert("", END, values=values, tags=(tag,))

    def _build_table(self, parent) -> None:
        frame = ttk.Frame(parent, borderwidth=1, relief="solid")
        frame.pack(fill=BOTH, expand=True)
        self.tree = ttk.Treeview(frame, show="headings", selectmode="extended", style="Grid.Treeview")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.tag_configure("odd", background="#f8fbff")
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        yscroll.pack(side=RIGHT, fill=Y)
        xscroll.pack(side="bottom", fill=X)
        self.tree.bind("<Button-1>", self._on_table_click)
        self.tree.bind("<Double-1>", self._on_table_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._update_task_summary())

    def _load_default_csv(self) -> None:
        candidates = []
        if self.config_data.last_csv_path:
            candidates.append(Path(self.config_data.last_csv_path))
        candidates.append(Path.cwd() / "stringtable.csv")
        for candidate in candidates:
            if candidate.exists():
                self.load_csv(candidate)
                return

    def open_csv(self) -> None:
        path = filedialog.askopenfilename(title="打开 stringtable.csv", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.load_csv(Path(path))

    def load_csv(self, path: Path) -> None:
        try:
            self.table = StringTable.load(path)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))
            return
        self.current_path = path
        self.path_var.set(str(path))
        self.config_data.last_csv_path = str(path)
        self._save_config_from_ui()
        self.dirty = False
        self.selected_row_indices = set()
        self._reload_tree()
        self._set_status(f"已打开 {path}")

    def save_csv(self) -> None:
        if not self.table:
            return
        path = self.current_path or Path(self.path_var.get())
        try:
            self.table.save(path)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self.current_path = path
        self.path_var.set(str(path))
        self.dirty = False
        self._save_config_from_ui()
        self._set_status(f"已保存 {path}")

    def save_csv_as(self) -> None:
        if not self.table:
            return
        path = filedialog.asksaveasfilename(title="另存为", defaultextension=".csv", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.current_path = Path(path)
            self.save_csv()

    def scan_file(self) -> None:
        path = filedialog.askopenfilename(title="扫描文件", filetypes=[("DayZ script/layout", "*.cpp *.c *.layout"), ("All files", "*.*")])
        if path:
            self._scan_path(Path(path))

    def scan_folder(self) -> None:
        path = filedialog.askdirectory(title="扫描文件夹")
        if path:
            self._scan_path(Path(path))

    def _scan_path(self, path: Path) -> None:
        if not self.table:
            messagebox.showwarning("没有表格", "请先打开 stringtable.csv")
            return
        self._save_config_from_ui()
        keys = scan_translation_keys(path, key_prefixes=self.scan_key_prefixes_var.get())
        added = self.table.add_keys(keys)
        if added:
            self.dirty = True
            self._reload_tree()
        self._set_status(f"扫描到 {len(keys)} 个 key，新增 {added} 行")

    def translate_selected_rows(self) -> None:
        indices = self._checked_or_tree_selected_indices()
        self._update_task_summary(len(indices))
        self._start_translation(indices)

    def translate_all_rows(self) -> None:
        if self.table:
            self._update_task_summary(len(self.table.rows))
            self._start_translation(range(len(self.table.rows)))

    def translate_single_row(self, row_index: int) -> None:
        self._start_translation([row_index])

    def select_all_targets(self) -> None:
        for column, variable in self.target_vars.items():
            variable.set(column != self.source_var.get())
        self._update_task_summary()

    def cancel_current_work(self) -> None:
        self.cancel_event.set()
        if hasattr(self, "cancel_translation_button"):
            self.cancel_translation_button.configure(state=DISABLED)
        self._set_status("正在取消当前翻译，等待已开始的请求返回")

    def _selected_target_columns(self) -> list[str]:
        return [column for column, variable in self.target_vars.items() if variable.get()]

    def _start_translation(self, indices) -> None:
        if not self.table:
            return
        row_indices = list(indices)
        if not row_indices:
            messagebox.showinfo("没有选中行", "请先选中要翻译的行")
            return
        source_column = self.source_var.get()
        target_columns = self._selected_target_columns()
        if not source_column or not target_columns:
            messagebox.showwarning("缺少语言列", "请选择主语言/源列和至少一个目标列")
            return
        if source_column in target_columns:
            messagebox.showwarning("语言列重复", "目标列不能包含源列")
            return
        try:
            translator = self._create_translator()
        except Exception as exc:
            messagebox.showerror("AI 设置错误", str(exc))
            return
        autosave_every = max(1, int(self.autosave_var.get()))
        max_workers = max(1, int(self.max_workers_var.get()))
        rate_limit_seconds = max(0.0, float(self.rate_limit_var.get()))
        self._save_config_from_ui()
        self.cancel_event.clear()
        self._set_translation_buttons(DISABLED)
        self._set_progress(0, len(row_indices))
        self.task_summary_var.set(format_translation_task_summary(len(row_indices), target_columns))
        self._set_status(f"开始翻译：{self.task_summary_var.get()}")
        thread = threading.Thread(
            target=self._translation_worker,
            args=(row_indices, source_column, target_columns, translator, autosave_every, max_workers, rate_limit_seconds),
            daemon=True,
        )
        thread.start()

    def _translation_worker(self, row_indices, source_column: str, target_columns: list[str], translator, autosave_every: int, max_workers: int, rate_limit_seconds: float) -> None:
        def autosave(table: StringTable) -> None:
            if self.current_path:
                table.save(self.current_path)

        def progress(done: int, total: int) -> None:
            self.after(0, lambda: self._set_progress(done, total))
            self.after(0, lambda: self._set_status(f"AI 翻译进度 {done}/{total}"))

        result = self.table.translate_rows_multi(
            row_indices=row_indices,
            source_column=source_column,
            target_columns=target_columns,
            translator=translator,
            autosave_every=autosave_every,
            save_callback=autosave,
            progress_callback=progress,
            max_workers=max_workers,
            rate_limit_seconds=rate_limit_seconds,
            cancel_callback=self.cancel_event.is_set,
        )
        self.after(0, lambda: self._finish_translation(result))

    def _finish_translation(self, result) -> None:
        self.dirty = self.current_path is None and result.translated > 0
        self._reload_tree()
        self._set_translation_buttons(NORMAL)
        self._set_progress(1, 1)
        failed = f"，失败 {len(result.failed)} 行" if result.failed else ""
        if result.canceled:
            self._set_status(f"翻译已取消：成功 {result.translated} 行，跳过 {result.skipped} 行{failed}")
        else:
            self._set_status(f"翻译完成：成功 {result.translated} 行，跳过 {result.skipped} 行{failed}")
        if result.failed:
            detail = "\n".join([f"第 {row + 1} 行: {error}" for row, error in result.failed[:10]])
            messagebox.showwarning("部分翻译失败", detail)

    def _create_translator(self):
        backend = self.backend_var.get()
        timeout_seconds = max(30, int(self.timeout_var.get()))
        if backend == "google":
            return GoogleTranslateTranslator(timeout_seconds=timeout_seconds)
        if backend == "azure":
            return AzureTranslator(
                key=self.azure_key_var.get(),
                endpoint=self.azure_endpoint_var.get(),
                region=self.azure_region_var.get(),
                timeout_seconds=timeout_seconds,
            )
        if backend == "bing_free":
            return BingFreeTranslator(timeout_seconds=timeout_seconds)
        if backend == "yandex_free":
            return YandexFreeTranslator(timeout_seconds=timeout_seconds)
        if backend == "opencode":
            return OpencodeCliTranslator(
                executable_path=self.opencode_path_var.get(),
                extra_args=self.opencode_args_var.get(),
                timeout_seconds=timeout_seconds,
                port=max(1, int(self.opencode_port_var.get())),
                model=self.opencode_model_var.get(),
            )
        return OpenAICompatibleTranslator(
            base_url=self.base_url_var.get(),
            api_key=self.api_key_var.get(),
            model=self.model_var.get(),
            timeout_seconds=timeout_seconds,
        )

    def _reload_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.table:
            return
        self.visible_column_indices = [index for index, column in enumerate(self.table.header) if column]
        self.selected_row_indices = {index for index in self.selected_row_indices if index < len(self.table.rows)}
        self.column_ids = [SELECT_COLUMN_ID] + [f"c{index}" for index in self.visible_column_indices]
        self.tree.configure(columns=self.column_ids)
        self.tree.heading(SELECT_COLUMN_ID, text=format_select_all_heading(list(range(len(self.table.rows))), self.selected_row_indices), anchor="center")
        self.tree.column(SELECT_COLUMN_ID, width=44, minwidth=44, stretch=False, anchor="center")
        for column_pos, column_id in enumerate(self.column_ids[1:]):
            header_index = self.visible_column_indices[column_pos]
            heading = self.table.header[header_index]
            self.tree.heading(column_id, text=heading)
            self.tree.column(column_id, width=112 if header_index else 155, minwidth=62, stretch=True)
        for row_index, row in enumerate(self.table.rows):
            tag = "odd" if row_index % 2 else "even"
            self.tree.insert("", END, iid=str(row_index), values=self._visible_row_values(row_index, row), tags=(tag,))
        columns = self.table.language_columns()
        self.source_combo.configure(values=columns)
        self.glossary_language_combo.configure(values=columns or DEFAULT_LANGUAGE_COLUMNS)
        if not self.source_var.get() and "english" in columns:
            self.source_var.set("english")
        self._reload_target_checks(columns)
        self._update_task_summary()

    def _visible_row_values(self, row_index: int, row: list[str]) -> list[str]:
        marker = CHECKED_TEXT if row_index in self.selected_row_indices else UNCHECKED_TEXT
        return [marker] + [row[index] for index in self.visible_column_indices]

    def _reload_target_checks(self, columns: list[str]) -> None:
        previous_selection = set(self._selected_target_columns())
        configured_targets = set(self.config_data.target_columns or ["chinesesimp"])
        selected = previous_selection or configured_targets
        for child in self.target_checks_frame.winfo_children():
            child.destroy()
        self.target_vars = {}
        for index, column in enumerate(columns):
            variable = tk.BooleanVar(value=column in selected)
            self.target_vars[column] = variable
            check = ttk.Checkbutton(self.target_checks_frame, text=column or "(空列)", variable=variable, command=self._update_task_summary, bootstyle="primary")
            check.grid(row=index // 2, column=index % 2, sticky="w", padx=4, pady=2)

    def _update_task_summary(self, row_count: int | None = None) -> None:
        if not hasattr(self, "task_summary_var"):
            return
        if row_count is None:
            row_count = len(self._checked_or_tree_selected_indices()) if hasattr(self, "tree") else 0
        self.task_summary_var.set(format_translation_task_summary(row_count, self._selected_target_columns()))

    def _checked_or_tree_selected_indices(self) -> list[int]:
        if self.selected_row_indices:
            return sorted(self.selected_row_indices)
        return [int(iid) for iid in self.tree.selection()]

    def _refresh_select_heading(self) -> None:
        if not self.table:
            return
        self.tree.heading(SELECT_COLUMN_ID, text=format_select_all_heading(list(range(len(self.table.rows))), self.selected_row_indices), anchor="center")

    def _refresh_row_marker(self, row_index: int) -> None:
        if not self.table:
            return
        iid = str(row_index)
        if self.tree.exists(iid):
            self.tree.item(iid, values=self._visible_row_values(row_index, self.table.rows[row_index]))

    def _toggle_row_checked(self, row_index: int) -> None:
        if row_index in self.selected_row_indices:
            self.selected_row_indices.remove(row_index)
        else:
            self.selected_row_indices.add(row_index)
        self._refresh_row_marker(row_index)
        self._refresh_select_heading()
        self._update_task_summary()

    def _toggle_all_rows(self) -> None:
        if not self.table:
            return
        row_indices = list(range(len(self.table.rows)))
        if row_indices and set(row_indices).issubset(self.selected_row_indices):
            self.selected_row_indices.clear()
        else:
            self.selected_row_indices = set(row_indices)
        self._reload_tree()

    def _on_table_click(self, event):
        if not self.table:
            return None
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x)
        if column != "#1":
            return None
        if region == "heading":
            self._toggle_all_rows()
            return "break"
        if region == "cell":
            iid = self.tree.identify_row(event.y)
            if iid:
                self._toggle_row_checked(int(iid))
                return "break"
        return None

    def _on_table_double_click(self, event) -> None:
        if not self.table:
            return
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not iid or not column:
            return
        column_pos = int(column.replace("#", "")) - 2
        if column_pos < 0 or column_pos >= len(self.visible_column_indices):
            return
        self._edit_cell(iid, column_pos)

    def _edit_cell(self, iid: str, column_pos: int) -> None:
        if self.edit_entry:
            self.edit_entry.destroy()
        column_id = self.column_ids[column_pos + 1]
        bbox = self.tree.bbox(iid, column_id)
        if not bbox:
            return
        x, y, width, height = bbox
        header_index = self.visible_column_indices[column_pos]
        value = self.table.rows[int(iid)][header_index]
        self.edit_entry = tk.Entry(self.tree, relief="solid", borderwidth=1)
        self.edit_entry.insert(0, value)
        self.edit_entry.select_range(0, END)
        self.edit_entry.place(x=x, y=y, width=width, height=height)
        self.edit_entry.focus_set()
        self.edit_entry.bind("<Return>", lambda event: self._commit_edit(iid, column_pos))
        self.edit_entry.bind("<Escape>", lambda event: self._cancel_edit())
        self.edit_entry.bind("<FocusOut>", lambda event: self._commit_edit(iid, column_pos))

    def _commit_edit(self, iid: str, column_pos: int) -> None:
        if not self.edit_entry or not self.table:
            return
        header_index = self.visible_column_indices[column_pos]
        self.table.rows[int(iid)][header_index] = self.edit_entry.get()
        self.tree.item(iid, values=self._visible_row_values(int(iid), self.table.rows[int(iid)]))
        self.edit_entry.destroy()
        self.edit_entry = None
        self.dirty = True
        self._set_status("有未保存修改")

    def _cancel_edit(self) -> None:
        if self.edit_entry:
            self.edit_entry.destroy()
            self.edit_entry = None

    def _save_config_from_ui(self) -> None:
        self.config_data.ai_backend = self.backend_var.get()
        self.config_data.base_url = self.base_url_var.get()
        self.config_data.api_key = self.api_key_var.get()
        self.config_data.model = self.model_var.get()
        self.config_data.azure_key = self.azure_key_var.get()
        self.config_data.azure_endpoint = self.azure_endpoint_var.get()
        self.config_data.azure_region = self.azure_region_var.get()
        self.config_data.opencode_path = self.opencode_path_var.get()
        self.config_data.opencode_args = self.opencode_args_var.get()
        self.config_data.opencode_port = max(1, int(self.opencode_port_var.get()))
        self.config_data.opencode_model = self.opencode_model_var.get()
        self.config_data.autosave_every = max(1, int(self.autosave_var.get()))
        self.config_data.max_workers = max(1, int(self.max_workers_var.get()))
        self.config_data.rate_limit_seconds = max(0.0, float(self.rate_limit_var.get()))
        self.config_data.timeout_seconds = max(30, int(self.timeout_var.get()))
        self.config_data.target_columns = self._selected_target_columns()
        self.config_data.scan_key_prefixes = self.scan_key_prefixes_var.get()
        if self.current_path:
            self.config_data.last_csv_path = str(self.current_path)
        save_config(self.config_data)

    def _set_translation_buttons(self, state: str) -> None:
        self.translate_selected_button.configure(state=state)
        self.translate_all_button.configure(state=state)
        if hasattr(self, "cancel_translation_button"):
            cancel_state = NORMAL if state == DISABLED else DISABLED
            self.cancel_translation_button.configure(state=cancel_state)

    def _set_progress(self, done: int, total: int) -> None:
        maximum = max(1, int(total))
        value = max(0, min(int(done), maximum))
        self.progress.configure(maximum=maximum)
        self.progress_var.set(value)

    def _set_status(self, message: str) -> None:
        marker = " *" if self.dirty else ""
        self.status_var.set(f"{message}{marker}")


def main() -> None:
    app = DayZTranslateApp()
    app.mainloop()


if __name__ == "__main__":
    main()
