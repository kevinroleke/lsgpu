"""
Theme registry — auto-discovers every themes/*.py that exposes a THEME instance.

Adding a new theme requires no changes here; just drop a new file in this
directory with a module-level  THEME = YourTheme()  and it will be picked up.
"""

import importlib
import pkgutil
from pathlib import Path

from .base import Theme

THEME_REGISTRY: dict[str, Theme] = {
    "default": Theme(),
}

for _info in pkgutil.iter_modules([str(Path(__file__).parent)]):
    if _info.name == "base":
        continue
    _mod = importlib.import_module(f".{_info.name}", package=__name__)
    if hasattr(_mod, "THEME"):
        _t = _mod.THEME
        THEME_REGISTRY[_t.name] = _t
