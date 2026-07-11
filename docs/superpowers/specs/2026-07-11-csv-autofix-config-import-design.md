# CSV 宽容补齐与 config.cpp 导入 Design

## Goal

两处增强 DayZ Translate Tool：

1. **打开 CSV 时自动补齐/宽容修复**，尽量把不完整或略乱的 stringtable 读成标准 DayZ 列结构后进入编辑表。
2. **从 `config.cpp` 批量提取 `$` / `#` 字符串表键**，去重后以新行追加到**当前已打开**的 stringtable。

## Scope

### In scope

- 修改 `load_dayz_csv` 的加载规则（打开时修复）。
- 新增 `config_cpp.py`：解析、扫目录、与现有行按 Language 键合并。
- 主窗口 File 菜单增加导入入口；中英文 UI 文案。
- 单元测试覆盖解析、补齐、去重、导入合并。

### Out of scope

- 导入前预览/确认对话框。
- 键已存在时合并或覆盖翻译列。
- 修改 wordbook 行为。
- 解析引号外的 `$` / `#`。
- 自动新建空白 stringtable（无当前表时只提示先打开 CSV）。
- 保存路径上的二次“修复逻辑”（保存继续用现有标准写出即可）。

## Assumptions

- 标准列仍是现有 `DAYZ_HEADERS`（含尾部空列约定）。
- DayZ 本地化键通常形如 `STR_...`，但导入不强制 `STR_` 前缀：只要引号内出现 `$token` / `#token` 即提取 `token`。
- 同一引号字符串内可有多个 `$` / `#` 片段。
- 去重键 = 当前表 `Language` 列（第 0 列）的完整字符串，大小写敏感、去首尾空白后比较。
- 用户已明确：CSV 修复在**打开时**；导入**只追加当前表**；新行**只填 Language 键**。

## Feature 1 — CSV 打开时宽容补齐

### 行为

| 情况 | 行为 |
|------|------|
| 文件为空 | 仍 `ValueError` |
| 表头含合法 DayZ 列名（`Language` / `original` / 各语言列 / 尾空列） | 按列名映射到完整 `DAYZ_HEADERS` |
| 缺少部分标准语言列 | 补空列 |
| 数据行短于标准列数 | 行末补空 |
| 未知列名 | **跳过该列**，不抛错；记入 warnings |
| 首列不是 `Language`，但至少识别到一个合法 DayZ 列 | 仍输出完整标准表头；`Language` 列从映射得到（若原文件无该列则为空）；数据按列名填入 |
| 表头无法识别任何合法 DayZ 列 | `ValueError`（无法修复） |
| 合法列名大小写 | 与现有一致：列名按 `DAYZ_HEADERS` 精确匹配（当前实现大小写敏感）；不在本需求扩大模糊匹配，除非实现时发现必要 |

### API 变化

`load_dayz_csv(path)` 返回值扩展为：

```python
(headers, rows, warnings)
```

- `headers`: 始终 `list(DAYZ_HEADERS)`
- `rows`: 已扩到标准宽度的数据行
- `warnings`: `list[str]`，例如跳过的未知列名；无问题时为空列表

调用方（`DayzTranslateTool.load_file`）更新为解包三元组；若有 warnings，状态栏或一次非阻断信息提示（优先状态栏汇总，避免每次打开弹模态框打扰）。

### 与现有行为的差异

- 旧：未知列 / 首列非 `Language` → 直接失败（见 `test_load_rejects_wrong_dayz_header`）。
- 新：能识别则修复；仅在“完全无法识别”时失败。
- 相关测试必须改写：
  - 原“错误首列必失败”改为“含合法列则修复，或无合法列才失败”。
  - 增加：未知列跳过、缺列补齐、warnings 内容。

### 保存

不改 `write_dayz_csv`：打开修复后的表保存时自然写出完整标准 DayZ CSV。

## Feature 2 — 从 config.cpp 导入

### UI

在主窗口 **File** 菜单、`Save As` 之后增加分隔线与两项：

1. **Import from config.cpp…**  
   - `QFileDialog.getOpenFileNames`  
   - 过滤器优先 `config.cpp` / `*.cpp`  
   - 支持多选

2. **Import config.cpp from folder…**  
   - `QFileDialog.getExistingDirectory`  
   - 递归收集路径名为 `config.cpp` 的文件（大小写：Windows 上按不区分、实现用 `name.lower() == "config.cpp"`）

前置条件：

- `self.headers` 已加载为 DayZ 表（非空且为标准结构）。  
- 否则 `QMessageBox.warning`：请先打开 stringtable.csv，中止导入。

### 解析规则（`config_cpp.py`）

1. 读文件文本：优先 `utf-8-sig`，失败再试 `utf-8` / `cp1252` / `latin-1`（最后 latin-1 不失败以保证尽量可读）。
2. 扫描源文本中的**引号字符串**：
   - 双引号 `"..."` 与单引号 `'...'`
   - 支持 `\"` / `\'` 转义的朴素扫描即可（config.cpp 常见写法）
   - 不处理原始字符串等 C++11 复杂形式（YAGNI）
3. 在每个引号字符串内容内，用正则找全部：

   ```text
   [$#]([A-Za-z_][A-Za-z0-9_]*)
   ```

   捕获组为键（已去掉 `$` / `#`）。
4. 键 `strip` 后非空才保留。
5. **单文件内**保持首次出现顺序；**多文件**按文件路径排序后依次扫描，全局键顺序 = 首次出现顺序。
6. 示例：

   ```cpp
   displayName="$STR_My_CODM_Weapons_LMG_Chopper_RulesOfTheGame0";
   ```

   → `STR_My_CODM_Weapons_LMG_Chopper_RulesOfTheGame0`

   ```cpp
   text = "Hello $STR_A and #STR_B end";
   ```

   → `STR_A`, `STR_B`

### 合并规则

纯函数建议：

```python
def merge_language_keys(existing_rows, keys) -> tuple[list[list[str]], int, int]:
    """
    返回 (全部应展示的行, added_count, skipped_duplicate_count)
    已存在 Language 键（strip 后）跳过；新键追加一行：
    [key] + [""] * (len(DAYZ_HEADERS) - 1)
    """
```

- 比较时对现有行第 0 列与候选键做 `strip`；不改写已有行内容。
- 空 Language 行不参与“已存在”集合（或参与但不阻塞导入——实现选：空键不加入 existing set）。

### GUI 应用步骤

1. 收集文件列表（多选或文件夹递归）。
2. 无文件 → 提示后返回。
3. 对每个文件提取键；汇总去重（保序）。
4. `existing = table_rows()`；`merged, added, skipped = merge_language_keys(existing, keys)`。
5. 若 `added == 0`：信息提示无新键（可含 skipped / 扫描文件数）。
6. 若有新增：`set` 表格为 merged（或只 append 新行）、`set_dirty(True)`。
7. 状态栏或信息框：`新增 N，跳过重复 M，扫描文件 K`（单文件失败可读时计入 warnings，不中断其余文件）。

单文件读失败：记入 warnings，继续其它文件；全部失败且无键 → 错误提示。

### 不做

- 不写回 config.cpp  
- 不自动填 original/english  
- 不打开导入专用对话框预览  

## Architecture

```text
dayz_csv.py          load 宽容修复 + (headers, rows, warnings)
config_cpp.py        新建：读文件、提键、扫目录、merge_language_keys
main.py              菜单、对话框、调解析、刷新表格、UI 文案
tests/
  test_dayz_csv.py   更新/新增 load 用例
  test_config_cpp.py 新建解析与 merge 用例
  test_main_gui.py   可选：菜单/导入路径冒烟（保持与现有 GUI 测风格一致）
```

原则：解析与合并无 Qt 依赖，便于单测；GUI 只做 I/O 选择与表格更新。

## Data flow

### Open CSV

```text
用户 Open
  → load_dayz_csv(path)
  → 宽容映射/补列/跳过未知列
  → (DAYZ_HEADERS, rows, warnings)
  → 填表；状态栏 loaded + 可选 warnings
```

### Import config.cpp

```text
用户选文件/文件夹
  → 需已有 headers
  → collect paths
  → extract keys (quoted $/#)
  → merge_language_keys(table_rows(), keys)
  → 刷新表 + dirty
  → 结果摘要
```

## Error handling

| 场景 | 处理 |
|------|------|
| CSV 空 / 无法识别任何合法列 | 阻断，critical/open_failed |
| CSV 有未知列但可识别 | 加载成功 + warnings |
| 未打开 stringtable 就导入 | warning，中止 |
| 未选文件/空文件夹 | 信息提示，中止 |
| 单文件无法读取 | warning 列表，继续 |
| 无新键可加 | information，不改表 |

## Testing

### `dayz_csv`

- 完整标准头：行为与今相同（返回值多 warnings=`[]`）。
- 部分语言列：扩到完整 `DAYZ_HEADERS`，值按列名就位。
- 含未知列：跳过，warnings 含列名，合法列保留。
- 首列非 `Language` 但含 `english` 等：成功加载，Language 列为空（若原无）。
- 无任何合法列：ValueError。
- 写路径回归：quote / 尾逗号不变。

### `config_cpp`

- 单引号/双引号内 `$STR_x`、`#STR_y`。
- 同一字符串多个键。
- 引号外 `$STR_z` 不提取。
- 多文件保序去重。
- `merge_language_keys`：已存在跳过、新键只填 Language、其它列空。
- 文件夹递归只收 `config.cpp`。

### GUI（按需、轻量）

- 无表导入被拒。
- 有表导入后行数增加、dirty（若现有测试基建方便）。

## UI strings

在 `UI_TEXT` 的 `en` / `zh`（及项目已有语言）增加例如：

- `import_config_cpp` / `import_config_cpp_folder`
- `import_config_cpp_title` / `import_config_folder_title`
- `config_cpp_files` 过滤器文案
- `import_requires_csv`
- `import_result`（`added` / `skipped` / `files`）
- `import_no_new_keys`
- `csv_load_warnings`（可选）

具体中文与现有 `tr()` 风格一致即可。

## Implementation notes (lazy defaults)

- 引号扫描用手写状态机或一个清晰正则循环；不引新依赖。
- `load_dayz_csv` 签名改为三元组是破坏性小改，全仓调用点很少（main + tests）。
- 文件夹递归：`Path(dir).rglob("config.cpp")`，再按 `path.name.lower() == "config.cpp"` 过滤以兼容大小写。
- ponytail：不做导入预览、不做智能填翻译、不做 config 语法级 parser。

## Verification

- `python -m unittest tests.test_dayz_csv tests.test_config_cpp`（及必要的 GUI 测）通过。
- 手工：打开缺列/含杂列 CSV 能进表；对含 `$STR_...` 的 config.cpp 导入后新行出现且重复跳过。

## Decision log

| 项 | 选择 |
|----|------|
| CSV 修复策略 | 尽量宽容：未知列跳过，缺列补齐 |
| 修复时机 | 仅打开时 |
| config 提取 | 仅引号内 `$`/`#`，允许多个 |
| 去重 | 按 Language 键 |
| 导入目标 | 仅当前已打开表 |
| 新行内容 | 仅 Language 键 |
| 结构 | `config_cpp.py` + `dayz_csv` 改 load + main 薄封装 |
