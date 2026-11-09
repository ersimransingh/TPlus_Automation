import sys
import ctypes
from contextlib import contextmanager


@contextmanager
def detached_dll_search():
    """
    In a PyInstaller onefile build the bootloader calls SetDllDirectory(_MEIPASS),
    which child processes inherit. Apps launched from here (TradePlus, CDSL) then
    load the bundled VC++/MFC DLLs from %TEMP%\\_MEIxxxx, keep them locked after
    activity.exe exits, and the bootloader shows "Failed to remove temporary
    directory". Reset the DLL directory while spawning the child, then restore it.
    """
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        yield
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.SetDllDirectoryW(None)
    try:
        yield
    finally:
        kernel32.SetDllDirectoryW(sys._MEIPASS)
