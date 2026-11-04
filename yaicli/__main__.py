"""Allow ``python -m yaicli`` to behave exactly like the ``ai`` console script.

Routed through :mod:`yaicli._faststart` so the ``--version`` fast path (no
config/role import, no writes) is shared by both entry points.
"""

from ._faststart import main

if __name__ == "__main__":
    main()
