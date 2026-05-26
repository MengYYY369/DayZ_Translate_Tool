from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, DISABLED, END, LEFT, NORMAL, RIGHT, X, Y

from .ai import OpenAICompatibleTranslator, OpencodeCliTranslator
from .config import AppConfig, load_config, save_config
from .scanner import scan_translation_keys
from .stringtable import StringTable


class DayZTranslateApp(ttk.Window):
    def __init__(self):
        super().__init__(themename="flatly")
        self.title("DayZ Translate Tool")
        self.geometry("1280x760")
        self.minsize(1024, 620)
        self.config_data = load_config()
        self.table: StringTable | None = None
        self.current_path: Path | None = None
        self.dirty = False
        self.column_ids: list[str] = []
        self.edit_entry: tk.Entry | None = None
        self._build_ui()
        self._load_default_csv()

    def _build_ui(self) -> None:
        self._build_file_bar()
        self._build_ai_bar()
        self._build_actions()
        self._build_table()
        self.status_var = tk.StringVar(value="准备就绪")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill=X, padx=8, pady=(0, 6))

    def _build_file_bar(self) -> None:
        frame = ttk.Frame(self, padding=8)
        frame.pack(fill=X)
        ttk.Label(frame, text="CSV").pack(side=LEFT)
        self.path_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.path_var).pack(side=LEFT, fill=X, expand=True, padx=6)
        ttk.Button(frame, text="打开", command=self.open_csv, bootstyle="secondary").pack(side=LEFT, padx=2)
        ttk.Button(frame, text="保存", command=self.save_csv, bootstyle="success").pack(side=LEFT, padx=2)
        ttk.Button(frame, text="另存为", command=self.save_csv_as, bootstyle="secondary").pack(side=LEFT, padx=2)

    def _build_ai_bar(self) -> None:
        frame = ttk.Labelframe(self, text="AI 设置", padding=8)
        frame.pack(fill=X, padx=8, pady=(0, 6))
        self.backend_var = tk.StringVar(value=self.config_data.ai_backend)
        self.base_url_var = tk.StringVar(value=self.config_data.base_url)
        self.api_key_var = tk.StringVar(value=self.config_data.api_key)
        self.model_var = tk.StringVar(value=self.config_data.model)
        self.opencode_path_var = tk.StringVar(value=self.config_data.opencode_path)
        self.opencode_args_var = tk.StringVar(value=self.config_data.opencode_args)
        self.autosave_var = tk.IntVar(value=self.config_data.autosave_every)
        ttk.Label(frame, text="后端").grid(row=0, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=self.backend_var, values=["api", "opencode"], width=12, state="readonly").grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(frame, text="base_url").grid(row=0, column=2, sticky="w")
        ttk.Entry(frame, textvariable=self.base_url_var).grid(row=0, column=3, sticky="ew", padx=4)
        ttk.Label(frame, text="api_key").grid(row=0, column=4, sticky="w")
        ttk.Entry(frame, textvariable=self.api_key_var, show="*").grid(row=0, column=5, sticky="ew", padx=4)
        ttk.Label(frame, text="model").grid(row=0, column=6, sticky="w")
        ttk.Entry(frame, textvariable=self.model_var, width=20).grid(row=0, column=7, sticky="ew", padx=4)
        ttk.Label(frame, text="Opencode").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(frame, textvariable=self.opencode_path_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=4, pady=(6, 0))
        ttk.Label(frame, text="参数").grid(row=1, column=3, sticky="w", pady=(6, 0))
        ttk.Entry(frame, textvariable=self.opencode_args_var).grid(row=1, column=4, columnspan=2, sticky="ew", padx=4, pady=(6, 0))
        ttk.Label(frame, text="自动保存行数").grid(row=1, column=6, sticky="w", pady=(6, 0))
        ttk.Spinbox(frame, from_=1, to=100, textvariable=self.autosave_var, width=8).grid(row=1, column=7, sticky="w", padx=4, pady=(6, 0))
        for column in range(8):
            frame.columnconfigure(column, weight=1 if column in {3, 5, 7} else 0)

    def _build_actions(self) -> None:
        frame = ttk.Frame(self, padding=(8, 0, 8, 6))
        frame.pack(fill=X)
        self.source_var = tk.StringVar()
        self.target_var = tk.StringVar()
        ttk.Label(frame, text="主语言/源列").pack(side=LEFT)
        self.source_combo = ttk.Combobox(frame, textvariable=self.source_var, width=18, state="readonly")
        self.source_combo.pack(side=LEFT, padx=4)
        ttk.Label(frame, text="目标列").pack(side=LEFT, padx=(10, 0))
        self.target_combo = ttk.Combobox(frame, textvariable=self.target_var, width=18, state="readonly")
        self.target_combo.pack(side=LEFT, padx=4)
        self.translate_selected_button = ttk.Button(frame, text="翻译选中行", command=self.translate_selected_rows, bootstyle="primary")
        self.translate_selected_button.pack(side=LEFT, padx=4)
        self.translate_all_button = ttk.Button(frame, text="翻译全部可翻译行", command=self.translate_all_rows, bootstyle="primary")
        self.translate_all_button.pack(side=LEFT, padx=4)
        ttk.Button(frame, text="扫描文件", command=self.scan_file, bootstyle="secondary").pack(side=RIGHT, padx=2)
        ttk.Button(frame, text="扫描文件夹", command=self.scan_folder, bootstyle="secondary").pack(side=RIGHT, padx=2)

    def _build_table(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))
        self.tree = ttk.Treeview(frame, show="headings", selectmode="extended")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        yscroll.pack(side=RIGHT, fill=Y)
        xscroll.pack(side="bottom", fill=X)
        self.tree.bind("<Double-1>", self._on_table_double_click)

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
        path = filedialog.askopenfilename(title="扫描文件", filetypes=[("DayZ/Text files", "*.c *.cpp *.h *.hpp *.json *.xml *.txt *.layout *.cfg *.csv"), ("All files", "*.*")])
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
        keys = scan_translation_keys(path)
        added = self.table.add_keys(keys)
        if added:
            self.dirty = True
            self._reload_tree()
        self._set_status(f"扫描到 {len(keys)} 个 key，新增 {added} 行")

    def translate_selected_rows(self) -> None:
        indices = [int(iid) for iid in self.tree.selection()]
        self._start_translation(indices)

    def translate_all_rows(self) -> None:
        if self.table:
            self._start_translation(range(len(self.table.rows)))

    def translate_single_row(self, row_index: int) -> None:
        self._start_translation([row_index])

    def _start_translation(self, indices) -> None:
        if not self.table:
            return
        row_indices = list(indices)
        if not row_indices:
            messagebox.showinfo("没有选中行", "请先选中要翻译的行")
            return
        source_column = self.source_var.get()
        target_column = self.target_var.get()
        if not source_column or not target_column:
            messagebox.showwarning("缺少语言列", "请选择主语言/源列和目标列")
            return
        if source_column == target_column:
            messagebox.showwarning("语言列重复", "源列和目标列不能相同")
            return
        try:
            translator = self._create_translator()
        except Exception as exc:
            messagebox.showerror("AI 设置错误", str(exc))
            return
        autosave_every = max(1, int(self.autosave_var.get()))
        self._save_config_from_ui()
        self._set_translation_buttons(DISABLED)
        self._set_status(f"开始翻译 {len(row_indices)} 行")
        thread = threading.Thread(target=self._translation_worker, args=(row_indices, source_column, target_column, translator, autosave_every), daemon=True)
        thread.start()

    def _translation_worker(self, row_indices, source_column: str, target_column: str, translator, autosave_every: int) -> None:
        def autosave(table: StringTable) -> None:
            if self.current_path:
                table.save(self.current_path)

        def progress(done: int, total: int) -> None:
            self.after(0, lambda: self._set_status(f"AI 翻译进度 {done}/{total}"))

        result = self.table.translate_rows(
            row_indices=row_indices,
            source_column=source_column,
            target_column=target_column,
            translator=translator,
            autosave_every=autosave_every,
            save_callback=autosave,
            progress_callback=progress,
        )
        self.after(0, lambda: self._finish_translation(result))

    def _finish_translation(self, result) -> None:
        self.dirty = self.current_path is None and result.translated > 0
        self._reload_tree()
        self._set_translation_buttons(NORMAL)
        failed = f"，失败 {len(result.failed)} 行" if result.failed else ""
        self._set_status(f"翻译完成：成功 {result.translated} 行，跳过 {result.skipped} 行{failed}")
        if result.failed:
            detail = "\n".join([f"第 {row + 1} 行: {error}" for row, error in result.failed[:10]])
            messagebox.showwarning("部分翻译失败", detail)

    def _create_translator(self):
        if self.backend_var.get() == "opencode":
            return OpencodeCliTranslator(
                executable_path=self.opencode_path_var.get(),
                extra_args=self.opencode_args_var.get(),
                timeout_seconds=int(self.config_data.timeout_seconds),
            )
        return OpenAICompatibleTranslator(
            base_url=self.base_url_var.get(),
            api_key=self.api_key_var.get(),
            model=self.model_var.get(),
            timeout_seconds=int(self.config_data.timeout_seconds),
        )

    def _reload_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.table:
            return
        self.column_ids = [f"c{index}" for index in range(len(self.table.header))] + ["action"]
        self.tree.configure(columns=self.column_ids)
        for index, column_id in enumerate(self.column_ids):
            if column_id == "action":
                self.tree.heading(column_id, text="操作")
                self.tree.column(column_id, width=80, minwidth=70, stretch=False, anchor="center")
            else:
                heading = self.table.header[index] or "(空列)"
                self.tree.heading(column_id, text=heading)
                self.tree.column(column_id, width=150 if index else 190, minwidth=80, stretch=True)
        for row_index, row in enumerate(self.table.rows):
            self.tree.insert("", END, iid=str(row_index), values=row + ["翻译"])
        columns = self.table.language_columns()
        self.source_combo.configure(values=columns)
        self.target_combo.configure(values=columns)
        if not self.source_var.get() and "english" in columns:
            self.source_var.set("english")
        if not self.target_var.get() and "chinesesimp" in columns:
            self.target_var.set("chinesesimp")

    def _on_table_double_click(self, event) -> None:
        if not self.table:
            return
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not iid or not column:
            return
        column_pos = int(column.replace("#", "")) - 1
        if column_pos == len(self.table.header):
            self.translate_single_row(int(iid))
            return
        if column_pos < 0 or column_pos >= len(self.table.header):
            return
        self._edit_cell(iid, column_pos)

    def _edit_cell(self, iid: str, column_pos: int) -> None:
        if self.edit_entry:
            self.edit_entry.destroy()
        column_id = self.column_ids[column_pos]
        bbox = self.tree.bbox(iid, column_id)
        if not bbox:
            return
        x, y, width, height = bbox
        value = self.table.rows[int(iid)][column_pos]
        self.edit_entry = tk.Entry(self.tree)
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
        self.table.rows[int(iid)][column_pos] = self.edit_entry.get()
        self.tree.item(iid, values=self.table.rows[int(iid)] + ["翻译"])
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
        self.config_data.opencode_path = self.opencode_path_var.get()
        self.config_data.opencode_args = self.opencode_args_var.get()
        self.config_data.autosave_every = max(1, int(self.autosave_var.get()))
        if self.current_path:
            self.config_data.last_csv_path = str(self.current_path)
        save_config(self.config_data)

    def _set_translation_buttons(self, state: str) -> None:
        self.translate_selected_button.configure(state=state)
        self.translate_all_button.configure(state=state)

    def _set_status(self, message: str) -> None:
        marker = " *" if self.dirty else ""
        self.status_var.set(f"{message}{marker}")


def main() -> None:
    app = DayZTranslateApp()
    app.mainloop()


if __name__ == "__main__":
    main()
