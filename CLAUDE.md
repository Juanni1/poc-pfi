# PoC PFI — zkML + verificación on-chain

## Qué es esto
PoC mínima para validar UN flujo de punta a punta: clasificador CNN liviano →
ONNX → prueba zkML con EZKL → verificación local → verificación on-chain.
NO es el MVP. El objetivo es probar factibilidad técnica, no construir producto.

## Alcance (no cruzar sin que yo lo pida)
DENTRO: un modelo chico, un caso de inferencia, generación y verificación de
una prueba real, contrato verificador desplegado en nodo EVM local.
FUERA: interfaz de usuario, IPFS, base de datos, taxonomía de daños, múltiples
estados operativos, flujo de revisión humana. No agregar nada de esto.

## Toolchain validado (usar estas versiones, ya probadas)
- Python 3.12; ezkl 23.0.5; torch; onnx; onnxscript
- Export ONNX: opset 13 con dynamo=False (el exporter dynamo genera un grafo
  que tract, el parser de EZKL, no lee bien; el legacy sí)
- solc 0.8.20 en el PATH para generar el verifier EVM (instalar con solc-select:
  pip install solc-select && solc-select install 0.8.20 && solc-select use 0.8.20)
- Nodo EVM local: Hardhat 2.x (fijar "hardhat@^2.22"; Hardhat 3.x NO sirve, es
  ESM-first con config y flujo de `node` distintos). Levanta en 127.0.0.1:8545
  con `npx hardhat node`. Anvil también vale
- Visibilidad del circuito: input private, output public, param fixed
  (la foto queda privada en el witness; la predicción es pública)

## Hechos conocidos (no redescubrir, ya costaron tiempo)
- prove, setup, verify, compile son síncronos en 23.x
- create_evm_verifier (y deploy_evm/verify_evm/encode_evm_calldata) son async de
  verdad: capturan el event loop EN EL MOMENTO de la llamada; si se las invoca
  sin un loop corriendo fallan con "no running event loop". Hay que LLAMARLAS
  dentro de asyncio.run, no solo envolver el resultado. Patrón que funciona:
  async def _run(): r = fn(...); return await r if isawaitable(r) else r
  luego asyncio.run(_run()). gen_srs y setup devuelven None en éxito (no True):
  validar por existencia del archivo, no por truthiness.
- deploy_evm exige la private key SIN prefijo 0x (64 chars hex).
- Cuenta #0 de Hardhat/Anvil (test, pública, solo local): address
  0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266, key
  ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80. OJO: NO es
  la "...944bafb478..." que suele citarse de memoria; verificar derivando la
  address o leyendo el log del nodo.
- Firma actual: prove(witness, model, pk_path, proof_path, srs_path) — sin arg proof_type
- get_srs descarga el SRS de la ceremonia de PSE (necesita red). Para testing
  local usar gen_srs(srs_path, logrows) y pasar ese srs a setup/prove/verify
- Preferir AvgPool sobre MaxPool (lineal, más barato de aritmetizar)
- Métricas de referencia (CPU, modelo de juguete): logrows 16–17, PK 277–554 MB,
  proof ~17,5 KB, proving ~17 s. On-chain: gas verify ~540 k, gas deploy ~2,95 M.
  Sirven de orden de magnitud, no de objetivo.

## Definition of done (filosofía, aplica a cada plan)
Un plan termina cuando existe UN comando reproducible que devuelve un OK/True
verificable. Si no hay forma automática de comprobar que funcionó, el plan no
está terminado. Cada plan deja sus métricas escritas en metrics.log.

## Convenciones
- Comentarios de código en español.
- Un commit por plan, mensaje descriptivo.
- Artefactos pesados (pk.key, srs) van a .gitignore.
- Referencia de implementación ya validada: poc_pipeline.py y poc_onchain.py.
