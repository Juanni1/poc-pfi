"""Verifica que la inferencia del ONNX coincide con la de PyTorch.

Es el comando de cierre del Plan 1 (Definition of Done): corre el mismo input
por PyTorch y por onnxruntime, compara los logits y la clase predicha, imprime
OK/True, escribe la métrica en metrics.log y sale con código 0 (ok) o 1 (falla).

Uso:
    python verify_model.py
"""

import json
import sys
from datetime import datetime

import numpy as np
import onnxruntime as ort
import torch

from model import INPUT_SHAPE, build_model

ONNX_PATH = "model.onnx"
INPUT_PATH = "input.json"
METRICS_PATH = "metrics.log"
ATOL = 1e-5


def cargar_input() -> np.ndarray:
    """Lee input.json y reconstruye el tensor con la forma del modelo."""
    with open(INPUT_PATH) as f:
        data = json.load(f)
    arr = np.array(data["input_data"][0], dtype=np.float32)
    return arr.reshape(INPUT_SHAPE)


def main() -> int:
    x = cargar_input()

    # Inferencia PyTorch.
    model = build_model()
    with torch.no_grad():
        out_torch = model(torch.from_numpy(x)).numpy()

    # Inferencia ONNX (onnxruntime).
    sess = ort.InferenceSession(ONNX_PATH)
    input_name = sess.get_inputs()[0].name
    out_onnx = sess.run(None, {input_name: x})[0]

    # Comparación: logits cercanos y misma clase predicha.
    max_diff = float(np.max(np.abs(out_torch - out_onnx)))
    pred_torch = int(np.argmax(out_torch))
    pred_onnx = int(np.argmax(out_onnx))
    allclose = bool(np.allclose(out_torch, out_onnx, atol=ATOL))
    ok = allclose and pred_torch == pred_onnx

    # Métrica persistida.
    linea = (
        f"{datetime.now().isoformat()} plan1 verify_model "
        f"max_abs_diff={max_diff:.3e} pred_torch={pred_torch} "
        f"pred_onnx={pred_onnx} allclose={allclose} resultado={'OK' if ok else 'FAIL'}"
    )
    with open(METRICS_PATH, "a") as f:
        f.write(linea + "\n")

    print(linea)
    if ok:
        print("OK — la inferencia ONNX coincide con PyTorch (True)")
        return 0
    print("FAIL — la inferencia ONNX NO coincide con PyTorch")
    return 1


if __name__ == "__main__":
    sys.exit(main())
