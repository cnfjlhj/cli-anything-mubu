import unittest
from tests._canonical_loader import load_canonical_test_module


load_canonical_test_module("test_full_e2e.py", globals())


if __name__ == "__main__":
    unittest.main()
