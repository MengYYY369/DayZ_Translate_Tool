# DayZ Translate Tool

DayZ `stringtable.csv` 翻译编辑工具，使用 `ttkbootstrap` 构建桌面界面。

## 功能

- 打开、编辑、保存固定格式的 DayZ `stringtable.csv`。
- 选择主语言/源列和目标语言列。
- 双击表格单元格手动修改。
- 双击每行最后的“翻译”操作列翻译单行。
- 支持翻译选中行、翻译全部可翻译行。
- 从文件或文件夹扫描 `$STR_xxx` / `#STR_xxx` 引用，自动加入缺失的 `Language` 键。
- 支持 OpenAI 兼容 API 和 Opencode CLI 两种 AI 后端。
- 批量翻译时默认每 5 行自动保存一次。

## 开发运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m dayz_translate_tool
```

当前 Codex bundled Python 的 Tcl/Tk 运行时不完整，可能无法直接启动 Tk 窗口。请用本机完整安装的 Python 3.12 或其它带 Tcl/Tk 的 Python 运行和打包。

## 打包

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

脚本优先使用 `.venv\Scripts\python.exe`，没有虚拟环境时回退到 PATH 里的 `python`。打包产物输出到 `release\DayZTranslateTool.exe`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
