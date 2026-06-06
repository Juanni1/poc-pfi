"""Verificación on-chain de la prueba EZKL (Planes 3 y 4).

Genera el contrato verificador Solidity con create_evm_verifier, lo despliega y
verifica la prueba on-chain con verify_evm, registrando gas y latencia en
metrics.log.

Dos modos (se elige por entorno):
  - LOCAL (default): si NO está seteada L2_RPC_URL, usa un nodo Hardhat en
    127.0.0.1:8545 con la cuenta #0 de test y lo autolevanta. (Plan 3)
  - TESTNET: si L2_RPC_URL está seteada, despliega contra esa red usando
    L2_PRIVATE_KEY del entorno. NO levanta nodo. (Plan 4 — Base Sepolia)

Los secretos (RPC y clave) se leen del entorno o de un archivo .env gitignored.
La clave NUNCA se hardcodea, ni se loguea, ni se commitea.

No incluye nada fuera del alcance de CLAUDE.md (sin UI/IPFS/DB).

Uso:
    # local (con el venv activo para que EZKL encuentre solc):
    python poc_onchain.py
    # testnet: poblar .env con L2_RPC_URL y L2_PRIVATE_KEY, luego:
    python poc_onchain.py
"""

import inspect
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from eth_account import Account
from web3 import Web3
import asyncio
import shutil


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

LOCAL_RPC = "http://127.0.0.1:8545"
# Cuenta #0 de Hardhat (key de test PÚBLICA, solo válida en el nodo local).
# Verificada: deriva a 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266.
# deploy_evm la exige SIN prefijo 0x (64 chars hex).
LOCAL_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SOLC_REQUIRED = "0.8.20"

# chainId -> nombre legible para las métricas.
NET_NAMES = {
    84532: "base-sepolia",
    11155420: "op-sepolia",
    421614: "arb-sepolia",
    31337: "local",
}


def cargar_dotenv(path: str = ".env") -> None:
    """Carga claves de un .env al entorno (sin pisar las ya definidas)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _call(fn, *a, **k):
    """Ejecuta fn dentro de un event loop y la awaitea si hace falta.

    CLAUDE.md avisa que create_evm_verifier corre sobre runtime async: estas
    funciones pyo3 capturan el loop EN EL MOMENTO de la llamada (si no hay loop
    corriendo, fallan con "no running event loop"). Por eso invocamos fn dentro
    de asyncio.run. Si la función resultara síncrona, igual funciona.
    """

    async def _run():
        r = fn(*a, **k)
        return await r if inspect.isawaitable(r) else r

    return asyncio.run(_run())


def normalizar_key(key: str) -> str:
    """deploy_evm exige la key sin prefijo 0x."""
    return key[2:] if key.startswith("0x") else key


def resolver_config():
    """Devuelve (rpc, key_sin_0x, spawn_node) según el entorno."""
    rpc = os.environ.get("L2_RPC_URL")
    if rpc:
        key = os.environ.get("L2_PRIVATE_KEY")
        if not key:
            sys.exit(
                "ERROR: L2_RPC_URL está seteada pero falta L2_PRIVATE_KEY "
                "(ponela en .env o el entorno; nunca en el repo)."
            )
        return rpc, normalizar_key(key), False
    return LOCAL_RPC, LOCAL_KEY, True


def validar_solc() -> None:
    """Aborta si solc no está en el PATH o no es la versión requerida."""

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


def receipt_de_despliegue(w3, addr: str, desde_bloque: int):
    """Devuelve el receipt de la tx de creación del contrato en addr (o None)."""

    objetivo = Web3.to_checksum_address(addr)
    for n in range(desde_bloque, w3.eth.block_number + 1):
        bloque = w3.eth.get_block(n, full_transactions=True)
        for tx in bloque.transactions:
            if tx.to is None:  # creación de contrato
                receipt = w3.eth.get_transaction_receipt(tx.hash)
                if (
                    receipt.contractAddress
                    and Web3.to_checksum_address(receipt.contractAddress) == objetivo
                ):
                    return receipt
    return None


def _as_int(v):
    """Convierte un valor de receipt (int o hex str) a int, o None."""
    if v is None:
        return None
    return int(v, 16) if isinstance(v, str) else int(v)


def main() -> int:

    cargar_dotenv()
    validar_solc()

    rpc, key, spawn = resolver_config()
    deployer = Account.from_key("0x" + key).address

    w3 = Web3(Web3.HTTPProvider(rpc))
    nodo = levantar_nodo_si_hace_falta(w3) if spawn else None
    try:
        if not rpc_responde(w3):
            sys.exit("ERROR: la RPC no responde. Revisá L2_RPC_URL.")
        net = NET_NAMES.get(w3.eth.chain_id, f"chain-{w3.eth.chain_id}")
        print(f"Red: {net} (chainId {w3.eth.chain_id}), deployer {deployer}")

        # En testnet exigimos fondos: sin balance el deploy falla.
        if not spawn and w3.eth.get_balance(deployer) == 0:
            sys.exit(
                f"ERROR: la cuenta {deployer} no tiene fondos en {net}. "
                "Pedí ETH de prueba a un faucet de Base Sepolia."
            )

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

        # 2. Desplegar (latencia wall-clock).
        bloque_pre = w3.eth.block_number
        t0 = time.perf_counter()
        _call(ezkl.deploy_evm, ADDR_FILE, rpc, sol_code_path=SOL, private_key=key)
        deploy_latency = time.perf_counter() - t0
        addr = leer_address()
        print(f"[2/4] deploy_evm OK -> {addr} ({deploy_latency:.2f}s)")

        # 3. Verificar la prueba on-chain (latencia wall-clock).
        t0 = time.perf_counter()
        ok = bool(_call(ezkl.verify_evm, addr, rpc, proof_path=PROOF))
        verify_latency = time.perf_counter() - t0
        print(f"[3/4] verify_evm -> {ok} ({verify_latency:.2f}s)")

        # 4. Gas: verificación (calldata + estimate_gas) y despliegue (receipt).
        calldata = _call(ezkl.encode_evm_calldata, PROOF, CALLDATA)
        data_hex = "0x" + bytes(calldata).hex()
        verify_gas = int(
            w3.eth.estimate_gas(
                {
                    "from": Web3.to_checksum_address(deployer),
                    "to": Web3.to_checksum_address(addr),
                    "data": data_hex,
                }
            )
        )
        receipt = receipt_de_despliegue(w3, addr, bloque_pre + 1)
        deploy_gas = _as_int(receipt.gasUsed) if receipt else None
        l1_fee = _as_int(receipt.get("l1Fee")) if receipt else None  # OP-stack
        print(f"[4/4] gas verify={verify_gas} deploy={deploy_gas} l1_fee={l1_fee}")

        linea = (
            f"{datetime.now().isoformat()} plan4 onchain net={net} "
            f"verify_evm={ok} verify_gas={verify_gas} deploy_gas={deploy_gas} "
            f"deploy_latency_s={deploy_latency:.2f} "
            f"verify_latency_s={verify_latency:.2f} addr={addr}"
        )
        if l1_fee is not None:
            linea += f" l1_fee={l1_fee}"
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
