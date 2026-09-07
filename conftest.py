"""Make the App Lab ``python/`` package tree importable from the test suite."""

import sys
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))
