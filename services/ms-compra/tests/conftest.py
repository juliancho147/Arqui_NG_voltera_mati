"""Config de pruebas de ms_compra: hace importables `main`/`config`/`health`.

Los modulos del servicio viven en `services/ms-compra/` (no es un paquete instalado), asi
que se anade esa carpeta al `sys.path` para poder importarlos directamente en los tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))
