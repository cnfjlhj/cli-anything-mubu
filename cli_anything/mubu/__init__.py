from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_canonical_module():
    canonical_path = Path(__file__).resolve().parents[2] / "agent-harness" / "cli_anything" / "mubu" / "__init__.py"
    spec = importlib.util.spec_from_file_location("cli_anything_mubu_canonical_init", canonical_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load canonical cli_anything.mubu module from {canonical_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CANONICAL_MODULE = _load_canonical_module()

__all__ = getattr(_CANONICAL_MODULE, "__all__", ["__version__"])
__version__ = _CANONICAL_MODULE.__version__
