# PoC PFI — zkML + verificación on-chain

Prueba de concepto mínima que valida **un flujo de punta a punta**: un
clasificador CNN liviano se exporta a ONNX, se genera una **prueba zkML** real
con [EZKL](https://github.com/zkonduit/ezkl), se verifica localmente y, por
último, se verifica **on-chain** mediante un contrato verificador desplegado en
un nodo EVM.

> Esto **no** es el MVP ni un producto. El objetivo es probar factibilidad
> técnica del flujo completo. El alcance está deliberadamente acotado (ver
> [CLAUDE.md](CLAUDE.md)).

## ¿De qué se trata?

zkML (zero-knowledge machine learning) permite demostrar criptográficamente que
**una inferencia se ejecutó correctamente sobre un modelo dado**, sin revelar el
input. En esta PoC:

- El **modelo** es un `TinyCNN` de juguete (clasificación binaria sobre una
  imagen 3×16×16): `Conv → ReLU → AvgPool → Linear`.
- La **foto (input) queda privada**: vive solo en el *witness*, nunca se publica.
- La **predicción (output) es pública**: cualquiera puede verificar qué predijo
  el modelo sin ver la entrada.
- Los **parámetros (pesos) son fijos** (`fixed`): forman parte del circuito.

Visibilidad del circuito: `input private`, `output public`, `param fixed`.

El resultado tangible es: una prueba (`proof.json`) que un contrato Solidity
desplegado puede aceptar o rechazar on-chain.

## Flujo del proceso, paso a paso

El flujo está partido en cuatro planes, cada uno con un comando reproducible que
devuelve un OK/True verificable y escribe sus métricas en `metrics.log`.

### Plan 1 — Modelo y export a ONNX

```
python export_onnx.py      # exporta model.onnx + input.json de ejemplo
python verify_model.py     # comando de cierre: OK/True
```

1. [`model.py`](model.py) define el `TinyCNN` con semilla fija (pesos
   reproducibles).
2. [`export_onnx.py`](export_onnx.py) lo exporta a `model.onnx` con el **exporter
   legacy** (`opset 13`, `dynamo=False` — el grafo del exporter `dynamo` no lo
   lee bien *tract*, el parser de EZKL) y guarda un `input.json` de ejemplo.
3. [`verify_model.py`](verify_model.py) corre el mismo input por PyTorch y por
   onnxruntime y compara logits y clase predicha. **Cierra cuando coinciden**
   (`allclose=True`, misma predicción).

### Plan 2 — Pipeline EZKL (prueba zkML)

```
python poc_pipeline.py     # gen_settings → ... → prove → verify; verify=True
```

[`poc_pipeline.py`](poc_pipeline.py) corre el pipeline completo de EZKL:

1. `gen_settings` — configura visibilidad (input privado).
2. `calibrate_settings` (`target=resources`) — minimiza logrows/PK.
3. `compile_circuit` — compila el circuito (`network.compiled`).
4. `gen_srs` **local** (sin red) con el logrows calibrado (`kzg.srs`).
5. `setup` — genera proving key (`pk.key`) y verifying key (`vk.key`).
6. `gen_witness` — genera el *witness* (incluye el input privado).
7. `prove` — genera la prueba (`proof.json`), cronometrada.
8. `verify` — verifica la prueba localmente. **Cierra con `verify=True`.**

### Planes 3 y 4 — Verificación on-chain

```
python poc_onchain.py      # create_evm_verifier → deploy → verify_evm; verify_evm=True
```

[`poc_onchain.py`](poc_onchain.py) lleva la verificación a la cadena:

1. `create_evm_verifier` — genera el contrato `Verifier.sol` (+ `abi.json`).
2. `deploy_evm` — lo despliega y guarda la address en `verifier_addr.txt`.
3. `verify_evm` — verifica la prueba on-chain. **Cierra con `verify_evm=True`.**
4. Mide gas de verificación y de despliegue, y latencias wall-clock.

Dos modos, elegidos por entorno:

- **Local (default, Plan 3):** si `L2_RPC_URL` no está seteada, autolevanta un
  nodo **Hardhat** en `127.0.0.1:8545` con la cuenta de test #0.
- **Testnet (Plan 4):** si `L2_RPC_URL` está seteada, despliega contra esa red
  (p. ej. Base Sepolia) usando `L2_PRIVATE_KEY`. Requiere una cuenta de prueba
  con fondos de faucet. No levanta nodo.

## Diagrama

```
  model.py ──► export_onnx.py ──► model.onnx + input.json
                                        │
                             verify_model.py   (Plan 1: ONNX ≈ PyTorch)
                                        │
                                  poc_pipeline.py
            gen_settings→calibrate→compile→gen_srs→setup→
            gen_witness→prove→verify    (Plan 2: proof.json, verify=True)
                                        │
                                  poc_onchain.py
            create_evm_verifier→deploy_evm→verify_evm
                          (Planes 3/4: verificación on-chain, verify_evm=True)
```

## Requisitos y setup

Toolchain validado (ver [CLAUDE.md](CLAUDE.md) para el detalle y los porqués):

- **Python 3.12**, `ezkl==23.0.5`, `torch`, `onnx`, `onnxscript`, `onnxruntime`,
  `numpy`, `web3`, `solc-select`.
- **solc 0.8.20** en el `PATH` (para generar el verifier EVM).
- **Node.js** + **Hardhat 2.x** (Hardhat 3.x **no** sirve) para el nodo EVM local.

```bash
# 1. Dependencias Python (en un venv 3.12)
pip install -r requirements.txt      # o: uv sync

# 2. Compilador Solidity 0.8.20
pip install solc-select
solc-select install 0.8.20
solc-select use 0.8.20

# 3. Nodo EVM local (Hardhat 2.x)
npm install

# 4. (Opcional, solo testnet) configurar secretos
cp .env.example .env                 # completar L2_RPC_URL y L2_PRIVATE_KEY
```

## Cómo correr todo

```bash
python export_onnx.py     # Plan 1: genera model.onnx + input.json
python verify_model.py    # Plan 1: ONNX coincide con PyTorch (OK)
python poc_pipeline.py    # Plan 2: genera y verifica la prueba (verify=True)
python poc_onchain.py     # Planes 3/4: verificación on-chain (verify_evm=True)
```

Cada script imprime su resultado, sale con código `0` (ok) o `1` (falla) y
agrega una línea a `metrics.log`.

## Artefactos

| Archivo | Qué es | Versionado |
|---|---|---|
| `model.onnx`, `input.json` | Modelo exportado e input de referencia | Sí |
| `settings.json`, `network.compiled` | Config y circuito compilado de EZKL | No |
| `kzg.srs` | SRS local (KZG) | No |
| `pk.key`, `vk.key` | Proving / verifying keys | No |
| `witness.json`, `proof.json` | Witness y prueba zkML | No |
| `Verifier.sol`, `abi.json`, `verifier_addr.txt`, `calldata.bytes` | Verifier EVM y artefactos de despliegue | No |
| `metrics.log` | Métricas de cada corrida | No |

Los artefactos pesados y regenerables están en [.gitignore](.gitignore). Solo
`model.onnx` e `input.json` se versionan, como referencia reproducible.

## Métricas de referencia

Órdenes de magnitud (CPU, modelo de juguete) — no son objetivos:

- logrows 16–17, PK ~277–554 MB, proof ~17,5 KB, proving ~4–17 s.
- On-chain (local): gas verify ~543 k, gas deploy ~2,95 M.

Ver `metrics.log` para los valores de cada corrida.

## Seguridad

- La cuenta y clave usadas en modo local son las de test **públicas** de
  Hardhat/Anvil: válidas **solo** en el nodo local, nunca en una red real.
- Para testnet, usar siempre una cuenta de prueba **descartable** con fondos de
  faucet. Los secretos van en `.env` (gitignored); nunca se hardcodean,
  loguean ni commitean.
