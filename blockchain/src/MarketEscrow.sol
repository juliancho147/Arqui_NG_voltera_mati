// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC1155Holder} from "@openzeppelin/contracts/token/ERC1155/utils/ERC1155Holder.sol";
import {EnergyToken} from "./EnergyToken.sol";

/// @title MarketEscrow
/// @notice Mercado P2P de energía de Voltera.
///
/// Flujo de una venta:
///   1. publicar():  el vendedor ofrece sus kWh. Los tokens quedan BLOQUEADOS en este contrato.
///   2. comprar():   el comprador adquiere la oferta. Los tokens pasan al comprador y la oferta queda
///                   VENDIDA, todo en una sola transacción (o ocurre todo o no ocurre nada).
///   3. anclar():    se guarda la huella (CID de IPFS) del certificado PDF de la compra.
///
/// El pago en dinero es simulado y ocurre fuera de la cadena (lo gestiona ms_compra).
/// El precio no se manda en la oferta: se lee del EnergyToken, que es donde lo fijó la plataforma.
///
/// Modelo custodial: solo la plataforma puede llamar a las funciones de escritura. El vendedor y el
/// comprador se reciben como parámetros (direcciones seudónimas distintas), no como "quien llama".
contract MarketEscrow is ERC1155Holder {
    // ───────────────────────── Tipos ───────────────────────────
    enum Estado {
        Inexistente, // la oferta no existe
        Activa, // publicada y disponible
        Vendida, // ya fue comprada
        Cancelada // el vendedor la retiró
    }

    struct Oferta {
        address vendedor;
        address comprador; // address(0) mientras no se venda
        uint256 id; // fuente + época del token
        uint256 kwh;
        Estado estado;
    }

    // ───────────────────────── Errores ─────────────────────────
    error SoloPlataforma();
    error CantidadInvalida();
    error TokenSinPrecio(uint256 id);
    error OfertaNoDisponible(uint256 ofertaId);
    error VendedorYCompradorIguales();
    error CompraNoRealizada(uint256 ofertaId);
    error CertificadoYaAnclado(uint256 ofertaId);
    error CidVacio();

    // ───────────────────────── Estado ──────────────────────────
    EnergyToken public immutable token;
    address public immutable plataforma;

    /// @notice Cantidad de ofertas creadas. El id de la oferta N es N (empieza en 1).
    uint256 public totalOfertas;
    mapping(uint256 ofertaId => Oferta) public ofertas;

    /// @notice CID del certificado PDF de cada compra (el id de la compra es el de su oferta).
    mapping(uint256 ofertaId => string cid) public certificado;

    // ───────────────────────── Eventos ─────────────────────────
    event OfertaPublicada(uint256 indexed ofertaId, address indexed vendedor, uint256 indexed id, uint256 kwh);
    /// @notice Registro de la transacción "de quién a quién": es lo que escucha el Chain Event Listener.
    event Compra(
        uint256 indexed ofertaId,
        address indexed vendedor,
        address indexed comprador,
        uint256 id,
        uint256 kwh,
        uint256 total
    );
    event OfertaCancelada(uint256 indexed ofertaId);
    event Anclado(uint256 indexed ofertaId, string cid);

    modifier soloPlataforma() {
        if (msg.sender != plataforma) revert SoloPlataforma();
        _;
    }

    constructor(EnergyToken token_, address plataforma_) {
        token = token_;
        plataforma = plataforma_;
    }

    // ───────────────────────── Funciones ───────────────────────

    /// @notice Publica una oferta y bloquea los tokens del vendedor en este contrato.
    function publicar(address vendedor, uint256 id, uint256 kwh) external soloPlataforma returns (uint256 ofertaId) {
        if (kwh == 0) revert CantidadInvalida();
        if (token.precioPorKwh(id) == 0) revert TokenSinPrecio(id);

        ofertaId = ++totalOfertas;
        ofertas[ofertaId] =
            Oferta({vendedor: vendedor, comprador: address(0), id: id, kwh: kwh, estado: Estado.Activa});

        // Bloqueo: los tokens salen de la cuenta del vendedor y quedan en este contrato.
        token.safeTransferFrom(vendedor, address(this), id, kwh, "");
        emit OfertaPublicada(ofertaId, vendedor, id, kwh);
    }

    /// @notice Ejecuta la compra de una oferta. Si dos compras llegan a la vez, la cadena las ordena:
    /// la primera se confirma y la segunda se revierte porque la oferta ya no está Activa.
    function comprar(uint256 ofertaId, address comprador) external soloPlataforma {
        Oferta storage o = ofertas[ofertaId];
        if (o.estado != Estado.Activa) revert OfertaNoDisponible(ofertaId);
        if (comprador == o.vendedor) revert VendedorYCompradorIguales();

        // Primero se actualiza el estado y después se mueven los tokens (evita reentradas).
        o.estado = Estado.Vendida;
        o.comprador = comprador;

        token.safeTransferFrom(address(this), comprador, o.id, o.kwh, "");

        uint256 total = o.kwh * token.precioPorKwh(o.id);
        emit Compra(ofertaId, o.vendedor, comprador, o.id, o.kwh, total);
    }

    /// @notice Retira una oferta activa y devuelve los tokens al vendedor.
    function cancelar(uint256 ofertaId) external soloPlataforma {
        Oferta storage o = ofertas[ofertaId];
        if (o.estado != Estado.Activa) revert OfertaNoDisponible(ofertaId);

        o.estado = Estado.Cancelada;
        token.safeTransferFrom(address(this), o.vendedor, o.id, o.kwh, "");
        emit OfertaCancelada(ofertaId);
    }

    /// @notice Guarda el CID (huella en IPFS) del certificado PDF de una compra ya realizada.
    /// Más adelante, ms_certificado compara el hash del PDF con este CID para detectar alteraciones.
    function anclar(uint256 ofertaId, string calldata cid) external soloPlataforma {
        if (ofertas[ofertaId].estado != Estado.Vendida) revert CompraNoRealizada(ofertaId);
        if (bytes(cid).length == 0) revert CidVacio();
        if (bytes(certificado[ofertaId]).length != 0) revert CertificadoYaAnclado(ofertaId);

        certificado[ofertaId] = cid;
        emit Anclado(ofertaId, cid);
    }
}
