import sys
from pathlib import Path

# The Worker imports these as top-level modules (pywrangler flattens src/ into
# the bundle), so tests resolve them the same way.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
