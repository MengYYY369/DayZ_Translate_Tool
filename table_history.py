"""表格编辑历史栈，支持撤销/重做。

每个快照保存整个表格的文本内容（二维列表）和当前单元格位置。
历史栈由外部表格调用 record() 记录，撤销/重做时调用 restore() 还原。
"""

from PySide6.QtWidgets import QTableWidgetItem


class TableHistory:
    """管理一个表格的撤销/重做历史。

    语义：undo_stack 保存历史快照序列（含初始状态）。
    每次用户编辑后调用 record() 推入新快照并清空 redo_stack。
    undo() 把栈顶快照移到 redo_stack 并返回栈顶前一个快照（要还原的状态）。
    redo() 把 redo_stack 栈顶移回 undo_stack 并返回该快照（要还原的状态）。
    """

    def __init__(self, max_size=100):
        self._undo_stack = []
        self._redo_stack = []
        self._max_size = max_size
        self._suppressed = False

    def record(self, snapshot):
        """记录一个新快照（用户编辑后的状态）。"""
        if self._suppressed:
            return
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self._max_size:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def can_undo(self):
        return len(self._undo_stack) > 1

    def can_redo(self):
        return len(self._redo_stack) > 0

    def undo(self):
        """撤销：弹出当前快照到 redo 栈，返回要还原的前一个快照或 None。"""
        if len(self._undo_stack) <= 1:
            return None
        current = self._undo_stack.pop()
        self._redo_stack.append(current)
        return self._undo_stack[-1]

    def redo(self):
        """重做：从 redo 栈弹出一个快照到 undo 栈，返回要还原的快照或 None。"""
        if not self._redo_stack:
            return None
        snapshot = self._redo_stack.pop()
        self._undo_stack.append(snapshot)
        return snapshot

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()

    def suppress(self, suppressed):
        """暂停记录（加载文件、撤销/重做还原期间使用）。"""
        self._suppressed = suppressed


def snapshot_table(table):
    """捕获 QTableWidget 的当前状态作为快照。"""
    rows = []
    for row_index in range(table.rowCount()):
        row = []
        for column_index in range(table.columnCount()):
            item = table.item(row_index, column_index)
            row.append(item.text() if item else "")
        rows.append(row)
    return (rows, table.currentRow(), table.currentColumn())


def restore_table(table, snapshot, block_signal_widget=None):
    """从快照还原 QTableWidget 的状态。返回 (current_row, current_column)。"""
    rows, current_row, current_column = snapshot
    if block_signal_widget is not None:
        block_signal_widget.blockSignals(True)
    table.clearContents()
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            if column_index >= table.columnCount():
                continue
            table.setItem(row_index, column_index, QTableWidgetItem(value))
    if block_signal_widget is not None:
        block_signal_widget.blockSignals(False)
    target_row = max(0, min(current_row, table.rowCount() - 1)) if table.rowCount() > 0 else -1
    target_col = max(0, min(current_column, table.columnCount() - 1)) if table.columnCount() > 0 else -1
    if target_row >= 0 and target_col >= 0:
        table.setCurrentCell(target_row, target_col)
    return target_row, target_col
