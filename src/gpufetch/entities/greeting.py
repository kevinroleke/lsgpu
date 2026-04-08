from ..ansi import MAGENTA
from .base import EntitySpec
import os

def get_user_name():
    if os.name == 'nt':
        import ctypes
        GetUserNameExW = ctypes.windll.secur32.GetUserNameExW
        name_display = 3

        size = ctypes.pointer(ctypes.c_ulong(0))
        GetUserNameExW(name_display, None, size)

        name_buffer = ctypes.create_unicode_buffer(size.contents.value)
        GetUserNameExW(name_display, name_buffer, size)
        return name_buffer.value
    else:
        import pwd
        # Note that for some reason pwd.getpwuid(os.geteuid())[4] did not work for me
        display_name = next(entry[4] for entry in pwd.getpwall() if entry[2] == os.geteuid())
        return display_name

name = get_user_name()
SPEC = EntitySpec("greeting", color=MAGENTA, frames=[
    [
        "-"*(8+len(name)),
        "| Hi, " + name + " |",
        "-"*(8+len(name))
    ]
])
