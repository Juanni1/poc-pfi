"""Pipeline EZKL completo sobre model.onnx (Plan 2).

Corre de punta a punta: gen_settings -> calibrate_settings -> compile_circuit ->
gen_srs (local) -> setup -> gen_witness -> prove -> verify. Imprime el resultado
de verify y registra logrows, tamaño de PK, tamaño de proof y proving time en
metrics.log.

Visibilidad del circuito (CLAUDE.md): input private, output public, param fixed.
La foto queda privada en el witness; la predicción es pública.

No incluye create_evm_verifier ni nada on-chain (eso es el Plan 3).

Uso:
    python poc_pipeline.py
"""

import json
import os
import sys
import time
from datetime import datetime

import ezkl

# Rutas de entrada (generadas en el Plan 1).
MODEL = "model.onnx"
DATA = "input.json"

# Artefactos generados por este pipeline (todos en .gitignore).
SETTINGS = "settings.json"
COMPILED = "network.compiled"
SRS = "kzg.srs"
PK = "pk.key"
VK = "vk.key"
WITNESS = "witness.json"
PROOF = "proof.json"

METRICS_PATH = "metrics.log"


def leer_logrows() -> int:
    """Lee el logrows calibrado de settings.json.

    En EZKL 23.x vive en run_args.logrows; dejamos un fallback que busca la
    clave 'logrows' en cualquier nivel por robustez ante cambios de formato.
    """
    with open(SETTINGS) as f:
        settings = json.load(f)
    run_args = settings.get("run_args", {})
    if "logrows" in run_args:
        return int(run_args["logrows"])

    # Fallback: búsqueda recursiva de la primera clave 'logrows'.
    def buscar(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "logrows":
                    return v
                r = buscar(v)
                if r is not None:
                    return r
        return None

    encontrado = buscar(settings)
    if encontrado is None:
        raise RuntimeError("No se encontró 'logrows' en settings.json")
    return int(encontrado)


def main() -> int:
    # 1. Settings: input privado, output público, param fixed (defaults menos input).
    run_args = ezkl.PyRunArgs()
    run_args.input_visibility = "private"
    assert ezkl.gen_settings(MODEL, SETTINGS, run_args), "gen_settings falló"
    print("[1/8] gen_settings OK")

    # 2. Calibración orientada a recursos (menos logrows/PK posibles).
    assert ezkl.calibrate_settings(DATA, MODEL, SETTINGS, target="resources"), \
        "calibrate_settings falló"
    print("[2/8] calibrate_settings (target=resources) OK")

    # 3. Compilar el circuito.
    assert ezkl.compile_circuit(MODEL, COMPILED, SETTINGS), "compile_circuit falló"
    print("[3/8] compile_circuit OK")

    # 4. Logrows calibrado.
    logrows = leer_logrows()
    print(f"[4/8] logrows calibrado = {logrows}")

    # 5. SRS local (sin red): gen_srs en vez de get_srs (CLAUDE.md).
    # Nota: gen_srs devuelve None en éxito; validamos por el archivo generado.
    ezkl.gen_srs(SRS, logrows)
    assert os.path.exists(SRS), "gen_srs no generó el SRS"
    print("[5/8] gen_srs local OK")

    # 6. Setup: genera proving key (PK) y verifying key (VK).
    ezkl.setup(COMPILED, VK, PK, srs_path=SRS)
    assert os.path.exists(PK) and os.path.exists(VK), "setup no generó PK/VK"
    print("[6/8] setup OK")

    # 7. Witness (incluye el input privado).
    ezkl.gen_witness(DATA, COMPILED, WITNESS, srs_path=SRS)
    print("[7/8] gen_witness OK")

    # 8. Prove (cronometrado) + verify.
    t0 = time.perf_counter()
    ezkl.prove(WITNESS, COMPILED, PK, PROOF, srs_path=SRS)
    proving_time = time.perf_counter() - t0
    print(f"[8/8] prove OK ({proving_time:.2f}s)")

    ok = bool(ezkl.verify(PROOF, SETTINGS, VK, srs_path=SRS))

    # Métricas.
    pk_bytes = os.path.getsize(PK)
    proof_bytes = os.path.getsize(PROOF)
    linea = (
        f"{datetime.now().isoformat()} plan2 ezkl_pipeline "
        f"logrows={logrows} pk_bytes={pk_bytes} proof_bytes={proof_bytes} "
        f"proving_time_s={proving_time:.2f} verify={ok}"
    )
    with open(METRICS_PATH, "a") as f:
        f.write(linea + "\n")

    print(linea)
    print(f"verify={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
