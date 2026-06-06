"""CNN de juguete para la PoC zkML.

Arquitectura mínima para clasificación binaria (2 clases) sobre una imagen
chica de 3x16x16. Solo usa capas baratas de aritmetizar de cara a EZKL:
conv + ReLU + AvgPool + lineal (preferimos AvgPool sobre MaxPool por ser
lineal, ver CLAUDE.md). La salida son logits sin softmax: la predicción
pública se obtiene después con argmax y el grafo final queda lineal.
"""

import torch
from torch import nn

# Semilla fija: pesos reproducibles entre corridas (mismo modelo siempre).
SEED = 0

# Forma del input esperado por el modelo: (batch, canales, alto, ancho).
INPUT_SHAPE = (1, 3, 16, 16)


class TinyCNN(nn.Module):
    """CNN liviana: 3x16x16 -> 2 clases."""

    def __init__(self) -> None:
        super().__init__()
        # Conv con padding=1 mantiene el tamaño espacial: 16x16 -> 16x16.
        self.conv = nn.Conv2d(in_channels=3, out_channels=4, kernel_size=3, padding=1)
        self.relu = nn.ReLU()
        # AvgPool 2x2 reduce a la mitad: 4x16x16 -> 4x8x8.
        self.pool = nn.AvgPool2d(kernel_size=2)
        self.flatten = nn.Flatten()
        # 4 canales * 8 * 8 = 256 features -> 2 logits.
        self.fc = nn.Linear(4 * 8 * 8, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv(x)
        x = self.relu(x)
        x = self.pool(x)
        x = self.flatten(x)
        x = self.fc(x)
        return x


def build_model() -> TinyCNN:
    """Construye el modelo con pesos reproducibles y en modo eval.

    Fijar la semilla antes de instanciar garantiza que tanto el export a ONNX
    como la verificación posterior usen exactamente los mismos pesos.
    """
    torch.manual_seed(SEED)
    model = TinyCNN()
    model.eval()
    return model
