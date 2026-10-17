"""Import the Home-Assistant-free modules under test without Home Assistant.

``custom_components.energiebe.__init__`` imports ``homeassistant``, which is not
installed in a plain checkout, and ``coordinator`` uses syntax newer than the
Python this may run on. So register a stand-in parent package whose ``__path__``
points at the real directory and load single modules into it: relative imports
between them resolve, and the package body never runs.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from typing import Any

PACKAGE = "energiebe_under_test"
ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "energiebe"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _parent() -> types.ModuleType:
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT)]
        sys.modules[PACKAGE] = package
    return sys.modules[PACKAGE]


def load(name: str) -> Any:
    """Return the integration module ``name``, loaded from its file."""
    _parent()
    full = f"{PACKAGE}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, ROOT / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {ROOT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


def fixture(name: str) -> bytes:
    """Return the bytes of a committed fixture."""
    return (FIXTURES / name).read_bytes()
