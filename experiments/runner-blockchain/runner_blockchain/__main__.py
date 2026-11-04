"""Permite `python -m runner_blockchain e1|e2|e3|all [opciones]` (R7.6)."""
import sys

from .cli import main

sys.exit(main())
