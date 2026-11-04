"""Validacion real y determinista de lecturas de medidor (R2.2, R2.3, R2.4, R5.1).

`ms_oraculo` decide aceptar o rechazar cada lectura con logica propia (no delegada a un
stub). Las tres categorias de invalidez son:

- `valor_alterado`: el valor reportado no es consistente con la referencia esperada que
  aportan los stubs de medidor/clima (fuera de la tolerancia relativa configurada).
- `medidor_desconocido`: el `medidorId` no esta en el padron conocido.
- `lectura_duplicada`: el `lecturaId` ya se vio, o la tupla (medidor, epoca) ya se registro
  en la corrida.

La validacion PURA (`evaluar`) es una funcion deterministica de la lectura, los stubs y el
conjunto de claves ya vistas: la misma entrada produce siempre el mismo veredicto (R2.2).
El estado de duplicados (lo que convierte una lectura repetida en invalida) se mantiene en
`RegistroDuplicados`, separado de la logica pura para que esta sea trivialmente reproducible.

Orden de evaluacion (determinista): medidor_desconocido -> valor_alterado -> lectura_duplicada.
Se evalua primero lo estructural (padron, consistencia de valor) y, por ultimo, la unicidad
dentro de la corrida, de modo que una lectura intrinsecamente invalida se rechace por su
causa intrinseca aunque ademas estuviese duplicada.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from stubs import ClimaStub, MedidorStub, referencia_esperada

# Categorias de invalidez (coinciden con el glosario de requisitos y el modelo de datos del diseno).
VALOR_ALTERADO = "valor_alterado"
MEDIDOR_DESCONOCIDO = "medidor_desconocido"
LECTURA_DUPLICADA = "lectura_duplicada"


class LecturaInvalidaError(ValueError):
    """La lectura no cumple el contrato minimo (campos ausentes o de tipo incorrecto)."""


@dataclass(frozen=True)
class Lectura:
    """Lectura de medidor normalizada (ver Data Models del diseno).

    `epoca` es `AAAAMM` (p. ej. 202610). `kwh` es el valor reportado a validar.
    """

    lectura_id: str
    medidor_id: str
    epoca: int
    fuente: str
    kwh: int
    precio: int
    participante: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Lectura":
        """Construye una Lectura desde el JSON del request, validando campos y tipos.

        Lanza `LecturaInvalidaError` ante un contrato invalido (campo ausente o no convertible),
        que el handler traduce a HTTP 400. Esto es un error de *contrato*, distinto del rechazo
        de *negocio* (lectura bien formada pero invalida), que responde 200 con `aceptada:false`.
        """
        if not isinstance(payload, dict):
            raise LecturaInvalidaError("el cuerpo debe ser un objeto JSON")

        def _str(campo: str) -> str:
            valor = payload.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                raise LecturaInvalidaError(f"campo '{campo}' ausente o vacio")
            return valor.strip()

        def _int(campo: str) -> int:
            valor = payload.get(campo)
            if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
                raise LecturaInvalidaError(f"campo '{campo}' ausente o no numerico")
            try:
                return int(valor)
            except (TypeError, ValueError) as exc:
                raise LecturaInvalidaError(f"campo '{campo}' no es un entero: {valor!r}") from exc

        return cls(
            lectura_id=_str("lecturaId"),
            medidor_id=_str("medidorId"),
            epoca=_int("epoca"),
            fuente=_str("fuente"),
            kwh=_int("kwh"),
            precio=_int("precio"),
            participante=_str("participante"),
        )

    @property
    def clave_epoca(self) -> tuple[str, int]:
        """Clave (medidor, epoca) usada para detectar duplicados por tupla."""
        return (self.medidor_id, self.epoca)


@dataclass(frozen=True)
class Veredicto:
    """Resultado de validar una lectura (ver `VeredictoLectura` del diseno)."""

    lectura_id: str
    aceptada: bool
    categoria: str | None = None
    motivo: str | None = None

    def to_response(self) -> dict[str, Any]:
        """Cuerpo JSON de la respuesta de `POST /lecturas`.

        Aceptada: `{aceptada:true}`. Rechazada: `{aceptada:false, motivo, categoria}` (R2.3).
        Se incluye `lecturaId` en ambos casos para correlacion/registro en el reporte.
        """
        if self.aceptada:
            return {"aceptada": True, "lecturaId": self.lectura_id}
        return {
            "aceptada": False,
            "lecturaId": self.lectura_id,
            "motivo": self.motivo,
            "categoria": self.categoria,
        }


def evaluar(
    lectura: Lectura,
    medidor: MedidorStub,
    clima: ClimaStub,
    *,
    tolerancia_relativa: float,
    vistas_lectura: Iterable[str] = (),
    vistas_epoca: Iterable[tuple[str, int]] = (),
) -> Veredicto:
    """Evalua una lectura y devuelve su veredicto de forma pura y determinista (R2.2).

    No muta estado: los duplicados se deciden contra los conjuntos `vistas_*` recibidos, de modo
    que la misma entrada (lectura + stubs + vistas) siempre produce el mismo veredicto. El
    registro de nuevas claves vistas lo hace el llamador (`RegistroDuplicados`) solo tras aceptar.
    """
    vistas_lectura = set(vistas_lectura)
    vistas_epoca = set(vistas_epoca)

    # 1) Medidor desconocido: el padron del stub no incluye el medidor.
    if not medidor.es_conocido(lectura.medidor_id):
        return Veredicto(
            lectura.lectura_id, False, MEDIDOR_DESCONOCIDO,
            f"medidor '{lectura.medidor_id}' fuera del padron",
        )

    # 2) Valor alterado: el valor reportado no es consistente con la referencia esperada.
    referencia = referencia_esperada(medidor, clima, lectura.medidor_id, lectura.fuente, lectura.epoca)
    if referencia is None:
        # El medidor existe pero no reporta esa fuente: tampoco hay base consistente -> valor alterado.
        return Veredicto(
            lectura.lectura_id, False, VALOR_ALTERADO,
            f"fuente '{lectura.fuente}' no esperada para el medidor '{lectura.medidor_id}'",
        )
    if lectura.kwh < 0:
        return Veredicto(lectura.lectura_id, False, VALOR_ALTERADO, "kwh negativo")
    if not _dentro_de_tolerancia(lectura.kwh, referencia, tolerancia_relativa):
        return Veredicto(
            lectura.lectura_id, False, VALOR_ALTERADO,
            f"kwh={lectura.kwh} fuera de tolerancia respecto a la referencia {referencia}",
        )

    # 3) Lectura duplicada: por lecturaId o por tupla (medidor, epoca) ya registrada en la corrida.
    if lectura.lectura_id in vistas_lectura:
        return Veredicto(
            lectura.lectura_id, False, LECTURA_DUPLICADA,
            f"lecturaId '{lectura.lectura_id}' ya registrado",
        )
    if lectura.clave_epoca in vistas_epoca:
        return Veredicto(
            lectura.lectura_id, False, LECTURA_DUPLICADA,
            f"lectura para medidor '{lectura.medidor_id}' y epoca {lectura.epoca} ya registrada",
        )

    return Veredicto(lectura.lectura_id, True)


def _dentro_de_tolerancia(valor: int, referencia: int, tolerancia_relativa: float) -> bool:
    """True si `valor` esta dentro de +/- tolerancia_relativa de `referencia` (determinista)."""
    if referencia == 0:
        return valor == 0
    margen = abs(referencia) * tolerancia_relativa
    return abs(valor - referencia) <= margen


class RegistroDuplicados:
    """Estado de duplicados de la corrida: lecturaId y tuplas (medidor, epoca) ya aceptadas.

    Se separa de la logica pura (`evaluar`) para que la decision sea reproducible: `evaluar`
    consulta los conjuntos y el registro solo se actualiza tras una aceptacion.
    """

    def __init__(self) -> None:
        self._lecturas: set[str] = set()
        self._epocas: set[tuple[str, int]] = set()

    @property
    def lecturas(self) -> set[str]:
        return self._lecturas

    @property
    def epocas(self) -> set[tuple[str, int]]:
        return self._epocas

    def registrar(self, lectura: Lectura) -> None:
        """Marca la lectura como vista (tras aceptarla) para detectar futuros duplicados."""
        self._lecturas.add(lectura.lectura_id)
        self._epocas.add(lectura.clave_epoca)
