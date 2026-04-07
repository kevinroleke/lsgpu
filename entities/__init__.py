"""
Entity registry — auto-discovers every entities/*.py that exposes a SPEC instance.

Adding a new entity requires no changes here; just drop a new file in this
directory with a module-level  SPEC = EntitySpec(...)  and it will be picked up.
"""

import importlib
import pkgutil
from pathlib import Path

from .base import EntitySpec, Entity, spawn, overlay

ENTITY_REGISTRY: dict[str, EntitySpec] = {}

for _info in pkgutil.iter_modules([str(Path(__file__).parent)]):
    if _info.name == "base":
        continue
    _mod = importlib.import_module(f".{_info.name}", package=__name__)
    if hasattr(_mod, "SPEC"):
        _s = _mod.SPEC
        ENTITY_REGISTRY[_s.name] = _s
