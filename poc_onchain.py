"""Verificación on-chain de la prueba EZKL (Plan 3).

Genera el contrato verificador Solidity con create_evm_verifier, lo despliega en
un nodo EVM local (Hardhat en 127.0.0.1:8545) con deploy_evm y verifica la prueba
on-chain con verify_evm. Registra el gas (verificación y despliegue) en metrics.log.

No incluye nada fuera del alcance de CLAUDE.md (sin UI/IPFS/DB).

Uso:
    # con el venv activo (para que EZKL encuentre solc):
    python poc_onchain.py
El script levanta el nodo Hardhat por su cuenta si el 8545 está caído y lo apaga
al terminar. Alternativa manual: `npx hardhat node` en otra terminal.
"""

import inspect
import os
import re
import subprocess
import sys
import time
from datetime import datetime

# Aseguramos que el bin del venv (donde solc-select dejó el shim `solc`) esté en
# el PATH del proceso, así EZKL lo encuentra aunque el venv no esté "activado".
_VENV_BIN = os.path.dirname(sys.executable)
os.environ["PATH"] = _VENV_BIN + os.pathsep + os.environ.get("PATH", "")

import ezkl  # noqa: E402  (después de tocar el PATH)

# Artefactos de entrada (Plan 2).
VK = "vk.key"
SETTINGS = "settings.json"
SRS = "kzg.srs"
PROOF = "proof.json"

# Artefactos generados (gitignored).
SOL = "Verifier.sol"
ABI = "abi.json"
ADDR_FILE = "verifier_addr.txt"
CALLDATA = "calldata.bytes"

METRICS_PATH = "metrics.log"

RPC = "http://127.0.0.1:8545"
# Cuenta #0 de Hardhat (key de test PÚBLICA, solo válida en el nodo local).
# Verificada: deriva a 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266.
# deploy_evm la exige SIN prefijo 0x (64 chars hex).
DEPLOYER_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
DEPLOYER_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
SOLC_REQUIRED = "0.8.20"


def _call(fn, *a, **k):
    """Ejecuta fn dentro de un event loop y la awaitea si hace falta.

    CLAUDE.md avisa que create_evm_verifier corre sobre runtime async: estas
    funciones pyo3 capturan el loop EN EL MOMENTO de la llamada (si no hay loop
    corriendo, fallan con "no running event loop"). Por eso invocamos fn dentro
    de asyncio.run. Si la función resultara síncrona, igual funciona.
    """
    import asyncio

    async def _run():
        r = fn(*a, **k)
        return await r if inspect.isawaitable(r) else r

    return asyncio.run(_run())


def validar_solc() -> None:
    """Aborta si solc no está en el PATH o no es la versión requerida."""
    import shutil

    if shutil.which("solc") is None:
        sys.exit("ERROR: solc no está en el PATH. Ver setup (solc-select use 0.8.20).")
    out = subprocess.run(["solc", "--version"], capture_output=True, text=True).stdout
    if SOLC_REQUIRED not in out:
        sys.exit(f"ERROR: se requiere solc {SOLC_REQUIRED}; encontrado:\n{out}")
    print(f"solc {SOLC_REQUIRED} OK")


def rpc_responde(w3) -> bool:
    try:
        w3.eth.block_number
        return True
    except Exception:
        return False


def levantar_nodo_si_hace_falta(w3):
    """Si el 8545 no responde, levanta `npx hardhat node` y devuelve el proceso."""
    if rpc_responde(w3):
        print("Nodo EVM ya disponible en 8545")
        return None
    print("Levantando nodo Hardhat...")
    proc = subprocess.Popen(
        ["npx", "hardhat", "node"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        if rpc_responde(w3):
            print("Nodo Hardhat listo")
            return proc
        time.sleep(0.5)
    proc.terminate()
    sys.exit("ERROR: el nodo Hardhat no respondió a tiempo")


def leer_address() -> str:
    """Extrae la address 0x... del archivo que escribe deploy_evm."""
    with open(ADDR_FILE) as f:
        contenido = f.read()
    m = re.search(r"0x[0-9a-fA-F]{40}", contenido)
    if not m:
        raise RuntimeError(f"No se encontró una address en {ADDR_FILE}: {contenido!r}")
    return m.group(0)


def gas_de_despliegue(w3, addr: str, desde_bloque: int):
    """Busca el gasUsed de la tx de creación del contrato en addr."""
    from web3 import Web3

    objetivo = Web3.to_checksum_address(addr)
    for n in range(desde_bloque, w3.eth.block_number + 1):
        bloque = w3.eth.get_block(n, full_transactions=True)
        for tx in bloque.transactions:
            if tx.to is None:  # creación de contrato
                receipt = w3.eth.get_transaction_receipt(tx.hash)
                if receipt.contractAddress and \
                        Web3.to_checksum_address(receipt.contractAddress) == objetivo:
                    return int(receipt.gasUsed)
    return None


def main() -> int:
    from web3 import Web3

    validar_solc()

    w3 = Web3(Web3.HTTPProvider(RPC))
    nodo = levantar_nodo_si_hace_falta(w3)
    try:
        # 1. Generar el verifier Solidity (autocontenido, sin contrato VK aparte).
        _call(
            ezkl.create_evm_verifier,
            VK,
            SETTINGS,
            SOL,
            ABI,
            srs_path=SRS,
            reusable=False,
        )
        assert os.path.exists(SOL), "create_evm_verifier no generó Verifier.sol"
        print("[1/4] create_evm_verifier OK")

        # 2. Desplegar con la cuenta #0 de Hardhat.
        bloque_pre = w3.eth.block_number
        _call(
            ezkl.deploy_evm,
            ADDR_FILE,
            RPC,
            sol_code_path=SOL,
            private_key=DEPLOYER_KEY,
        )
        addr = leer_address()
        print(f"[2/4] deploy_evm OK -> {addr}")

        # 3. Verificar la prueba on-chain.
        ok = bool(_call(ezkl.verify_evm, addr, RPC, proof_path=PROOF))
        print(f"[3/4] verify_evm -> {ok}")

        # 4. Gas: verificación (calldata + estimate_gas) y despliegue (receipt).
        calldata = _call(ezkl.encode_evm_calldata, PROOF, CALLDATA)
        data_hex = "0x" + bytes(calldata).hex()
        verify_gas = int(
            w3.eth.estimate_gas(
                {
                    "from": Web3.to_checksum_address(DEPLOYER_ADDR),
                    "to": Web3.to_checksum_address(addr),
                    "data": data_hex,
                }
            )
        )
        deploy_gas = gas_de_despliegue(w3, addr, bloque_pre + 1)
        print(f"[4/4] gas verify={verify_gas} deploy={deploy_gas}")

        linea = (
            f"{datetime.now().isoformat()} plan3 onchain "
            f"verify_evm={ok} verify_gas={verify_gas} deploy_gas={deploy_gas} "
            f"addr={addr}"
        )
        with open(METRICS_PATH, "a") as f:
            f.write(linea + "\n")
        print(linea)
        print(f"verify_evm={ok}")
        return 0 if ok else 1
    finally:
        if nodo is not None:
            nodo.terminate()
            print("Nodo Hardhat apagado")


if __name__ == "__main__":
    sys.exit(main())
