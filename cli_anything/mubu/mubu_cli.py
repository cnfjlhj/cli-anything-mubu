from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_canonical_module():
    canonical_path = Path(__file__).resolve().parents[2] / "agent-harness" / "cli_anything" / "mubu" / "mubu_cli.py"
    spec = importlib.util.spec_from_file_location("cli_anything_mubu_canonical_cli", canonical_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load canonical cli_anything.mubu.mubu_cli module from {canonical_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CANONICAL_MODULE = _load_canonical_module()
_PUBLIC_NAMES = getattr(_CANONICAL_MODULE, "__all__", None)
if _PUBLIC_NAMES is None:
    _PUBLIC_NAMES = [name for name in vars(_CANONICAL_MODULE) if not name.startswith("_")]

globals().update({name: getattr(_CANONICAL_MODULE, name) for name in _PUBLIC_NAMES})

__all__ = list(_PUBLIC_NAMES)
