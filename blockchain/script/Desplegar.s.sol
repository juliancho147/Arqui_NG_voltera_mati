// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {EnergyToken} from "../src/EnergyToken.sol";
import {MarketEscrow} from "../src/MarketEscrow.sol";

/// Despliega los dos contratos y deja a la plataforma como firmante.
/// Uso (la llave de la plataforma sale de la variable PRIVATE_KEY):
///   forge script script/Desplegar.s.sol --rpc-url $RPC_URL --private-key $PRIVATE_KEY --broadcast
contract Desplegar is Script {
    function run() external {
        vm.startBroadcast();
        address plataforma = msg.sender; // la cuenta que firma este despliegue

        EnergyToken token = new EnergyToken(plataforma);
        MarketEscrow mercado = new MarketEscrow(token, plataforma);
        token.configurarMercado(address(mercado));
        vm.stopBroadcast();

        console.log("plataforma   :", plataforma);
        console.log("EnergyToken  :", address(token));
        console.log("MarketEscrow :", address(mercado));
    }
}
