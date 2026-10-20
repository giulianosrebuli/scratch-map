"""Gera static/textures/foil.png: papel metálico amassado, para a película dos
quadros (/quadros). Ladrilho sem emenda (tudo periódico: ruído por FFT e
derivadas com np.roll), em tons de cinza; o quadro aplica por cima do dourado
com mix-blend-mode: overlay (cinza médio = neutro).

  facetas  células de Voronoi em duas escalas, cada uma inclinada para um lado
           e sombreada pela luz do alto à esquerda; vincos claros entre elas
  grão     ruído fino por cima

Uso: python scripts/foil_texture.py [--seed N] [--size 512]
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "static" / "textures" / "foil.png"


def periodic_noise(rng, n, beta):
    """Ruído com espectro 1/f^beta, periódico (FFT), normalizado em [-1, 1]."""
    f = np.fft.fftfreq(n)
    k = np.sqrt(f[:, None] ** 2 + f[None, :] ** 2)
    k[0, 0] = 1
    spec = (rng.normal(size=(n, n)) + 1j * rng.normal(size=(n, n))) / k ** beta
    spec[0, 0] = 0
    x = np.real(np.fft.ifft2(spec))
    return x / np.abs(x).max()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--size", type=int, default=512)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    n = args.size

    # Papel amassado = facetas planas, cada uma inclinada para um lado, com
    # vincos entre elas. Células de Voronoi (distância no toro: repete sem
    # emenda) em duas escalas; cada célula recebe uma inclinação e é sombreada
    # pela luz do alto à esquerda. No vinco (perto da fronteira), um fio claro.
    yy, xx = np.mgrid[0:n, 0:n] / n
    light = np.array([-0.55, -0.6, 0.58])
    light /= np.linalg.norm(light)
    shade = np.zeros((n, n))
    for cells, weight, tilt in ((70, 1.0, 0.45), (420, 0.55, 0.35)):
        pts = rng.random((cells, 2))
        normals = rng.normal(size=(cells, 2)) * tilt
        cell_shade = (normals[:, 0] * light[0] + normals[:, 1] * light[1] + light[2]) / np.sqrt(
            (normals ** 2).sum(1) + 1)
        near = np.zeros((n, n), dtype=int)
        d1 = np.full((n, n), 9.0)
        d2 = np.full((n, n), 9.0)
        for i, (px, py) in enumerate(pts):  # nearest e segundo nearest, célula a célula
            dx = np.abs(xx - px)
            dy = np.abs(yy - py)
            d = np.hypot(np.minimum(dx, 1 - dx), np.minimum(dy, 1 - dy))
            closer = d < d1
            d2 = np.where(closer, d1, np.minimum(d2, d))
            near = np.where(closer, i, near)
            d1 = np.where(closer, d, d1)
        edge = np.exp(-((d2 - d1) * n / 2.2) ** 2)  # 1 no vinco
        layer = cell_shade[near]
        shade += weight * ((layer - layer.mean()) / layer.std() + 0.9 * edge)
    shade += 0.6 * periodic_noise(rng, n, 2.6) * 3  # ondulação suave dentro das facetas

    # grão fino, um pouco mais marcado (como pediu: mais granular)
    grain = rng.normal(size=(n, n))
    z = (shade - shade.mean()) / shade.std()
    img = 0.5 + 0.12 * np.tanh(z * 0.9) + 0.05 * grain  # tanh: sem manchas escuras grandes
    img = np.clip(img, 0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((img * 255).astype(np.uint8), "L").save(OUT, optimize=True)
    print(OUT, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
