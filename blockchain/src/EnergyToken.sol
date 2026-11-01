// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC1155} from "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";

/// @title EnergyToken
/// @notice Token de energía de Voltera (estándar ERC-1155).
///
/// Cada "id" representa una fuente de energía en una época (por ejemplo: solar, octubre 2026).
/// La cantidad de tokens de un id es la cantidad de kWh. Los tokens del mismo id son intercambiables
/// entre sí (semi-fungibles), pero un id de otra fuente o época es un token distinto.
///
/// Qué hace este contrato:
///   1. Emitir kWh a un participante (solo la plataforma).
///   2. Guardar el precio por kWh de cada id (lo calcula ms_energia fuera de la cadena).
///   3. Dejar que la plataforma y el mercado muevan tokens en nombre de los participantes
///      (modelo custodial: los participantes no firman con su propia billetera).
contract EnergyToken is ERC1155 {
    // ───────────────────────── Errores ─────────────────────────
    error SoloPlataforma();
    error CantidadInvalida();
    error PrecioInvalido();
    error PrecioDistinto(uint256 precioActual, uint256 precioRecibido);

    // ───────────────────────── Estado ──────────────────────────
    /// @notice Dirección de la plataforma (la cuenta que firma las transacciones).
    address public immutable plataforma;

    /// @notice Dirección del contrato MarketEscrow. Puede mover tokens para bloquearlos en una oferta.
    address public mercado;

    /// @notice Precio por kWh de cada id, como número entero (por ejemplo, pesos).
    /// La primera emisión de un id fija su precio; las siguientes deben usar el mismo.
    /// Si el precio cambia (por ejemplo por temporada), corresponde a otra época y por tanto a otro id.
    mapping(uint256 id => uint256 precio) public precioPorKwh;

    // ───────────────────────── Eventos ─────────────────────────
    /// @notice Se emitió energía. `lecturaId` es el identificador de la lectura del medidor que la originó
    /// (queda registrado en el evento para la trazabilidad, sin guardarlo en el estado del contrato).
    event Emitido(uint256 indexed id, address indexed a, uint256 kwh, uint256 precio, bytes32 lecturaId);
    event MercadoConfigurado(address indexed mercado);

    modifier soloPlataforma() {
        if (msg.sender != plataforma) revert SoloPlataforma();
        _;
    }

    constructor(address plataforma_) ERC1155("") {
        plataforma = plataforma_;
    }

    // ───────────────────────── Funciones ───────────────────────

    /// @notice Calcula el id de una fuente en una época. Es una función auxiliar (no guarda nada).
    /// @param fuente Nombre de la fuente convertido a bytes32 (por ejemplo "solar").
    /// @param epoca Época como número (por ejemplo 202610 para octubre de 2026).
    function calcularId(bytes32 fuente, uint64 epoca) public pure returns (uint256) {
        return uint256(keccak256(abi.encode(fuente, epoca)));
    }

    /// @notice Registra la dirección del contrato MarketEscrow. Se llama una vez después del despliegue.
    function configurarMercado(address mercado_) external soloPlataforma {
        mercado = mercado_;
        emit MercadoConfigurado(mercado_);
    }

    /// @notice Emite kWh a un participante. Solo la plataforma (ms_energia) puede llamarla.
    /// @param a Dirección seudónima del participante que recibe la energía.
    /// @param id Fuente + época (ver calcularId).
    /// @param kwh Cantidad de kWh a emitir.
    /// @param precio Precio por kWh calculado por la plataforma. Si el id ya tiene precio, debe ser el mismo.
    /// @param lecturaId Identificador de la lectura validada que origina esta emisión.
    function emitir(address a, uint256 id, uint256 kwh, uint256 precio, bytes32 lecturaId)
        external
        soloPlataforma
    {
        if (kwh == 0) revert CantidadInvalida();
        if (precio == 0) revert PrecioInvalido();

        uint256 actual = precioPorKwh[id];
        if (actual == 0) {
            precioPorKwh[id] = precio; // primera emisión de este id: fija el precio
        } else if (actual != precio) {
            revert PrecioDistinto(actual, precio);
        }

        _mint(a, id, kwh, "");
        emit Emitido(id, a, kwh, precio, lecturaId);
    }

    /// @notice Modelo custodial: la plataforma y el contrato de mercado se consideran autorizados
    /// para mover los tokens de cualquier participante, sin que cada uno tenga que firmar.
    /// Para el resto de direcciones se aplica la regla normal del estándar.
    function isApprovedForAll(address cuenta, address operador) public view override returns (bool) {
        return operador == plataforma || operador == mercado || super.isApprovedForAll(cuenta, operador);
    }
}
