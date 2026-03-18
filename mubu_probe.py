from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_canonical_module():
    canonical_path = Path(__file__).resolve().parent / "agent-harness" / "mubu_probe.py"
    spec = importlib.util.spec_from_file_location("mubu_probe_canonical", canonical_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load canonical mubu_probe module from {canonical_path}")
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
__doc__ = _CANONICAL_MODULE.__doc__


if __name__ == "__main__":
    raise SystemExit(main())
