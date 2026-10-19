"""Non-mutating packaging preflight; does not build or contact Kalshi."""
import importlib.util
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
requirements = [
    'desktop/launcher.py',
    'src/jobs/demo_safe_submit.py',
    'src/jobs/demo_order_lifecycle.py',
    'src/jobs/execute.py',
    'build_windows.py',
]
missing = [x for x in requirements if not (root / x).is_file()]
for x in requirements:
    print(('OK     ' if x not in missing else 'MISSING') + '  ' + x)
for module in ('PyInstaller', 'PySide6', 'streamlit'):
    print(('OK     ' if importlib.util.find_spec(module) else 'MISSING') + '  Python package: ' + module)
    if importlib.util.find_spec(module) is None:
        missing.append(module)
if sys.platform != 'win32':
    print('WARNING: run actual Windows build on Windows, not this OS')
if missing:
    print('\nPreflight incomplete; no build attempted.')
    sys.exit(1)
print('\nPreflight OK. Next: python build_windows.py')
