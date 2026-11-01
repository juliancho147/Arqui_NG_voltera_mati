// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {EnergyToken} from "../src/EnergyToken.sol";
import {MarketEscrow} from "../src/MarketEscrow.sol";

/// Pruebas de los dos contratos. Cada prueba cuenta un caso en una frase.
contract MercadoTest is Test {
    EnergyToken token;
    MarketEscrow mercado;

    address plataforma = makeAddr("plataforma"); // la cuenta que firma todo (modelo custodial)
    address A = makeAddr("participanteA"); // vendedor
    address B = makeAddr("participanteB"); // comprador
    address C = makeAddr("participanteC"); // otro comprador
    address intruso = makeAddr("intruso");

    uint256 id; // solar + octubre 2026
    uint256 constant PRECIO = 600; // pesos por kWh
    bytes32 constant LECTURA = keccak256("lectura-1");

    function setUp() public {
        token = new EnergyToken(plataforma);
        mercado = new MarketEscrow(token, plataforma);
        vm.prank(plataforma);
        token.configurarMercado(address(mercado));
        id = token.calcularId("solar", 202610);
    }

    // ── Ayudas ──
    function _emitirA(uint256 kwh) internal {
        vm.prank(plataforma);
        token.emitir(A, id, kwh, PRECIO, LECTURA);
    }

    function _publicar(uint256 kwh) internal returns (uint256 ofertaId) {
        vm.prank(plataforma);
        ofertaId = mercado.publicar(A, id, kwh);
    }

    // ───────────────── EnergyToken ─────────────────

    function test_emitir_da_los_kwh_al_participante_y_fija_el_precio() public {
        _emitirA(10);
        assertEq(token.balanceOf(A, id), 10);
        assertEq(token.precioPorKwh(id), PRECIO);
    }

    function test_emitir_registra_la_lectura_de_origen_en_el_evento() public {
        vm.expectEmit(true, true, false, true);
        emit EnergyToken.Emitido(id, A, 10, PRECIO, LECTURA);
        _emitirA(10);
    }

    function test_solo_la_plataforma_puede_emitir() public {
        vm.prank(intruso);
        vm.expectRevert(EnergyToken.SoloPlataforma.selector);
        token.emitir(A, id, 10, PRECIO, LECTURA);
        assertEq(token.balanceOf(A, id), 0); // E1: sin autorización, no hay tokens
    }

    function test_el_precio_de_un_id_no_puede_cambiar() public {
        _emitirA(10);
        vm.prank(plataforma);
        vm.expectRevert(abi.encodeWithSelector(EnergyToken.PrecioDistinto.selector, PRECIO, 700));
        token.emitir(A, id, 5, 700, LECTURA);
    }

    function test_una_segunda_emision_del_mismo_id_reutiliza_el_precio() public {
        _emitirA(10);
        _emitirA(5);
        assertEq(token.balanceOf(A, id), 15);
    }

    function test_no_se_emite_cantidad_ni_precio_en_cero() public {
        vm.startPrank(plataforma);
        vm.expectRevert(EnergyToken.CantidadInvalida.selector);
        token.emitir(A, id, 0, PRECIO, LECTURA);
        vm.expectRevert(EnergyToken.PrecioInvalido.selector);
        token.emitir(A, id, 10, 0, LECTURA);
        vm.stopPrank();
    }

    // ───────────────── MarketEscrow ─────────────────

    function test_publicar_bloquea_los_tokens_en_el_mercado() public {
        _emitirA(10);
        uint256 ofertaId = _publicar(10);
        assertEq(ofertaId, 1);
        assertEq(token.balanceOf(A, id), 0); // salieron de A
        assertEq(token.balanceOf(address(mercado), id), 10); // quedaron bloqueados
    }

    function test_comprar_mueve_los_tokens_de_A_a_B_y_registra_la_transaccion() public {
        _emitirA(10);
        uint256 ofertaId = _publicar(10);

        vm.expectEmit(true, true, true, true);
        emit MarketEscrow.Compra(ofertaId, A, B, id, 10, 10 * PRECIO);
        vm.prank(plataforma);
        mercado.comprar(ofertaId, B);

        assertEq(token.balanceOf(A, id), 0);
        assertEq(token.balanceOf(B, id), 10);
        assertEq(token.balanceOf(address(mercado), id), 0);
    }

    /// E3: dos compradores intentan la misma oferta. Solo uno se queda con los kWh.
    function test_doble_venta_la_segunda_compra_se_revierte() public {
        _emitirA(10);
        uint256 ofertaId = _publicar(10);

        vm.prank(plataforma);
        mercado.comprar(ofertaId, B); // la primera se confirma

        vm.prank(plataforma);
        vm.expectRevert(abi.encodeWithSelector(MarketEscrow.OfertaNoDisponible.selector, ofertaId));
        mercado.comprar(ofertaId, C); // la segunda se revierte

        // Conservación de kWh: los 10 emitidos están todos en B.
        assertEq(token.balanceOf(B, id), 10);
        assertEq(token.balanceOf(C, id), 0);
        assertEq(token.balanceOf(A, id) + token.balanceOf(B, id) + token.balanceOf(C, id), 10);
    }

    function test_el_vendedor_no_puede_comprarse_a_si_mismo() public {
        _emitirA(10);
        uint256 ofertaId = _publicar(10);
        vm.prank(plataforma);
        vm.expectRevert(MarketEscrow.VendedorYCompradorIguales.selector);
        mercado.comprar(ofertaId, A);
    }

    function test_no_se_publica_un_token_sin_precio() public {
        uint256 otro = token.calcularId("eolica", 202610); // nunca emitido
        vm.prank(plataforma);
        vm.expectRevert(abi.encodeWithSelector(MarketEscrow.TokenSinPrecio.selector, otro));
        mercado.publicar(A, otro, 1);
    }

    function test_cancelar_devuelve_los_tokens_y_cierra_la_oferta() public {
        _emitirA(10);
        uint256 ofertaId = _publicar(10);
        vm.prank(plataforma);
        mercado.cancelar(ofertaId);
        assertEq(token.balanceOf(A, id), 10);

        vm.prank(plataforma);
        vm.expectRevert(abi.encodeWithSelector(MarketEscrow.OfertaNoDisponible.selector, ofertaId));
        mercado.comprar(ofertaId, B);
    }

    function test_solo_la_plataforma_opera_el_mercado() public {
        _emitirA(10);
        vm.prank(intruso);
        vm.expectRevert(MarketEscrow.SoloPlataforma.selector);
        mercado.publicar(A, id, 10);
    }

    // ───────────────── Certificado (E2) ─────────────────

    function test_anclar_guarda_el_cid_de_una_compra_realizada() public {
        _emitirA(10);
        uint256 ofertaId = _publicar(10);
        vm.prank(plataforma);
        mercado.comprar(ofertaId, B);

        vm.prank(plataforma);
        mercado.anclar(ofertaId, "QmCertificadoDeLaCompra1");
        assertEq(mercado.certificado(ofertaId), "QmCertificadoDeLaCompra1");
    }

    function test_no_se_ancla_un_certificado_de_una_compra_que_no_existe() public {
        _emitirA(10);
        uint256 ofertaId = _publicar(10); // publicada pero NO comprada
        vm.prank(plataforma);
        vm.expectRevert(abi.encodeWithSelector(MarketEscrow.CompraNoRealizada.selector, ofertaId));
        mercado.anclar(ofertaId, "QmX");
    }

    function test_el_cid_anclado_no_se_puede_reemplazar() public {
        _emitirA(10);
        uint256 ofertaId = _publicar(10);
        vm.startPrank(plataforma);
        mercado.comprar(ofertaId, B);
        mercado.anclar(ofertaId, "QmOriginal");
        vm.expectRevert(abi.encodeWithSelector(MarketEscrow.CertificadoYaAnclado.selector, ofertaId));
        mercado.anclar(ofertaId, "QmAlterado");
        vm.stopPrank();
        assertEq(mercado.certificado(ofertaId), "QmOriginal");
    }
}
