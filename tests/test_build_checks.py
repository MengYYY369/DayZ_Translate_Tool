import unittest
from unittest.mock import MagicMock, patch

from dayz_translate_tool.build_checks import TkinterCheckResult, check_tkinter_available


class BuildCheckTests(unittest.TestCase):
    def test_tkinter_check_reports_missing_module(self):
        with patch("dayz_translate_tool.build_checks.importlib.import_module", side_effect=ModuleNotFoundError("No module named 'tkinter'")):
            result = check_tkinter_available()

        self.assertFalse(result.ok)
        self.assertIn("tkinter", result.message)

    def test_tkinter_check_reports_broken_tcl_runtime(self):
        tkinter_module = MagicMock()
        tkinter_module.Tk.side_effect = RuntimeError("Can't find a usable init.tcl")
        with patch("dayz_translate_tool.build_checks.importlib.import_module", return_value=tkinter_module):
            result = check_tkinter_available()

        self.assertFalse(result.ok)
        self.assertIn("Tcl/Tk", result.message)

    def test_tkinter_check_accepts_usable_runtime(self):
        root = MagicMock()
        tkinter_module = MagicMock()
        tkinter_module.Tk.return_value = root
        with patch("dayz_translate_tool.build_checks.importlib.import_module", return_value=tkinter_module):
            result = check_tkinter_available()

        self.assertEqual(TkinterCheckResult(True, "tkinter/Tcl/Tk available"), result)
        root.withdraw.assert_called_once()
        root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
