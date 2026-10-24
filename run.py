"""Entrada compatível com desenvolvimento e PyInstaller."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if (ROOT / 'vendor').is_dir():
    sys.path.insert(0, str(ROOT / 'vendor'))

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
        from studio.validation import smoke_test
        raise SystemExit(smoke_test(Path(sys.argv[2])))
    if len(sys.argv) == 3 and sys.argv[1] == '--ui-smoke-test':
        from studio.validation import ui_smoke_test
        raise SystemExit(ui_smoke_test(Path(sys.argv[2])))
    from studio.app import main
    main()
