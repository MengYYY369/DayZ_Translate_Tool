import importlib
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class TkinterCheckResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class BuildCheckResult:
    ok: bool
    messages: list[str]


def check_tkinter_available() -> TkinterCheckResult:
    try:
        tkinter = importlib.import_module("tkinter")
    except ModuleNotFoundError as exc:
        return TkinterCheckResult(False, f"Current Python is missing tkinter: {exc}")
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
    except Exception as exc:
        return TkinterCheckResult(False, f"Current Python Tcl/Tk runtime is not usable: {exc}")
    return TkinterCheckResult(True, "tkinter/Tcl/Tk available")


def check_build_environment() -> BuildCheckResult:
    messages: list[str] = []
    tkinter_result = check_tkinter_available()
    if not tkinter_result.ok:
        messages.append(tkinter_result.message)
    for module_name in ["ttkbootstrap", "PyInstaller"]:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            messages.append(f"Current Python is missing {module_name}: {exc}")
    if messages:
        return BuildCheckResult(False, messages)
    return BuildCheckResult(True, [tkinter_result.message])


def main() -> int:
    result = check_build_environment()
    for message in result.messages:
        print(message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
