"""Exporta el TinyCNN a ONNX y guarda un input de ejemplo.

Usa el exporter legacy (dynamo=False) con opset 13: el grafo del exporter
dynamo no lo lee bien tract, el parser de EZKL; el legacy sí (ver CLAUDE.md).

Genera:
  - model.onnx: el modelo exportado.
  - input.json: un input de ejemplo en el formato {"input_data": [[...]]},
    que es el que después consumirá EZKL (lo adelantamos acá por compatibilidad;
    en este plan NO se toca nada de EZKL).

Nota para el plan EZKL siguiente (acá no se configura): la visibilidad del
circuito será input private, output public, param fixed.
"""

import json

import torch

from model import INPUT_SHAPE, SEED, build_model

ONNX_PATH = "model.onnx"
INPUT_PATH = "input.json"


def main() -> None:
    model = build_model()

    # Input de ejemplo reproducible (misma semilla -> mismo tensor siempre).
    torch.manual_seed(SEED)
    dummy = torch.randn(*INPUT_SHAPE)

    # Export legacy: opset 13 + dynamo=False (compatibilidad con tract/EZKL).
    torch.onnx.export(
        model,
        dummy,
        ONNX_PATH,
        opset_version=13,
        dynamo=False,
        input_names=["input"],
        output_names=["output"],
    )
    print(f"ONNX exportado a {ONNX_PATH}")

    # input.json: tensor aplanado en el formato que espera EZKL.
    data = dummy.detach().numpy().reshape(-1).tolist()
    with open(INPUT_PATH, "w") as f:
        json.dump({"input_data": [data]}, f)
    print(f"Input de ejemplo guardado en {INPUT_PATH}")


if __name__ == "__main__":
    main()
