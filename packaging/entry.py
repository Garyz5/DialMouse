"""PyInstaller entry point for the packaged DialMouse binary.

PyInstaller analyses a script, not a ``-m`` module, so this thin wrapper just
calls into the real CLI. Keeping it tiny means the frozen binary behaves exactly
like ``python -m dialmouse``.
"""

import sys

from dialmouse.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
