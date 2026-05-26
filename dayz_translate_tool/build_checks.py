import importlib
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class TkinterCheckResult:
    ok: bool
    message: str


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


def main() -> int:
    result = check_tkinter_available()
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
