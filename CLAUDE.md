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
- solc 0.8.20 en el PATH para generar el verifier EVM
- Hardhat o Anvil para el nodo EVM local
- Visibilidad del circuito: input private, output public, param fixed
  (la foto queda privada en el witness; la predicción es pública)

## Hechos conocidos (no redescubrir, ya costaron tiempo)
- prove, setup, verify, compile son síncronos en 23.x
- create_evm_verifier corre sobre runtime async → envolver en asyncio.run
- Firma actual: prove(witness, model, pk_path, proof_path, srs_path) — sin arg proof_type
- get_srs descarga el SRS de la ceremonia de PSE (necesita red). Para testing
  local usar gen_srs(srs_path, logrows) y pasar ese srs a setup/prove/verify
- Preferir AvgPool sobre MaxPool (lineal, más barato de aritmetizar)
- Métricas de referencia (CPU, modelo de juguete): logrows 16–17, PK 277–554 MB,
  proof ~17,5 KB, proving ~17 s. Sirven de orden de magnitud, no de objetivo.

## Definition of done (filosofía, aplica a cada plan)
Un plan termina cuando existe UN comando reproducible que devuelve un OK/True
verificable. Si no hay forma automática de comprobar que funcionó, el plan no
está terminado. Cada plan deja sus métricas escritas en metrics.log.

## Convenciones
- Comentarios de código en español.
- Un commit por plan, mensaje descriptivo.
- Artefactos pesados (pk.key, srs) van a .gitignore.
- Referencia de implementación ya validada: poc_pipeline.py y poc_onchain.py.
