"""Generacion del PDF del certificado de compra (R3.2).

Genera un PDF minimo y **determinista** (solo biblioteca estandar, sin dependencias de
terceros) a partir de los datos de la compra. El determinismo importa porque el CID se
calcula por contenido (Property 5): los mismos `datosCompra` para la misma `ofertaId`
deben producir exactamente los mismos bytes y, por tanto, el mismo CID.

Para evitar que metadatos variables (p. ej. fechas de creacion) rompan el determinismo, el
PDF no incluye marcas temporales generadas en tiempo de ejecucion: todo su contenido deriva
unicamente de los datos de entrada.
"""
from __future__ import annotations

import json
from typing import Any


def _escapar_texto_pdf(texto: str) -> str:
    """Escapa los caracteres especiales de una cadena de texto en un PDF."""
    return texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _lineas_contenido(oferta_id: Any, datos_compra: dict[str, Any]) -> list[str]:
    """Deriva las lineas visibles del certificado de forma determinista por contenido."""
    lineas = ["Certificado de compra de energia - Voltera", f"Oferta: {oferta_id}"]
    # Orden estable de las claves para que el contenido no dependa del orden de insercion.
    for clave in sorted(datos_compra):
        lineas.append(f"{clave}: {datos_compra[clave]}")
    return lineas


def generar_pdf(oferta_id: Any, datos_compra: dict[str, Any]) -> bytes:
    """Construye un PDF valido y determinista para `(oferta_id, datos_compra)`.

    El PDF es de una sola pagina con las lineas del certificado. Al no depender de relojes
    ni de identificadores aleatorios, el mismo par de entradas produce siempre los mismos
    bytes (requisito para que el CID quede determinado por el contenido).
    """
    lineas = _lineas_contenido(oferta_id, datos_compra)

    # Flujo de texto del contenido de pagina: una linea por `Tj`, descendiendo con `TD`.
    partes = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    for i, linea in enumerate(lineas):
        if i == 0:
            partes.append(f"({_escapar_texto_pdf(linea)}) Tj")
        else:
            partes.append(f"T* ({_escapar_texto_pdf(linea)}) Tj")
    partes.append("ET")
    stream = "\n".join(partes).encode("latin-1", "replace")

    objetos: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    salida = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"

    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode("ascii")
    salida += b"0000000000 65535 f \n"
    for off in offsets:
        salida += f"{off:010d} 00000 n \n".encode("ascii")
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
        f"startxref\n{inicio_xref}\n%%EOF\n"
    ).encode("ascii")
    return bytes(salida)
