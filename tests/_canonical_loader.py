from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


CANONICAL_TEST_ROOT = Path(__file__).resolve().parents[1] / "agent-harness" / "cli_anything" / "mubu" / "tests"


def load_canonical_test_module(filename: str, namespace: dict[str, object]) -> None:
    path = CANONICAL_TEST_ROOT / filename
    spec = spec_from_file_location(f"canonical_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load canonical test module: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, value in vars(module).items():
        if name.startswith("__") and name not in {"__doc__"}:
            continue
        namespace[name] = value
