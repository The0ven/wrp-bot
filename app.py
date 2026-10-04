"""
Compatibility entrypoint.

The daemon uses `main.py` (cogs architecture) as the single source of truth.
Keeping this tiny wrapper prevents dual command declarations.
"""

from main import main


if __name__ == "__main__":
    main()
