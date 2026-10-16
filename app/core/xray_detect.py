"""Deteccao de implante (OPME) em pagina de raio-x.

Usado para ordenar os raios-x do dossie de retirada: o filme com o
material (fios, pinos, placas, parafusos) vem antes do filme pos-
retirada.

O implante metalico e a estrutura mais branca e FINA do filme. O
sinal usado: transformada white top-hat isola estruturas claras
menores que o kernel (o osso, regiao ampla, desaparece; o fio,
fina faixa saturada, permanece); depois procuram-se linhas longas —
sozinhas ou em PAR PARALELO (as bordas de um fio/pino/placa sao
duas linhas paralelas a poucos px, coisa que borda de osso, sempre
curva, nao produz). A faixa de 10% nas bordas e excluida para a
moldura do filme nao virar "implante".
"""
import numpy as np


def has_implant(arr: np.ndarray) -> bool:
    """True se a pagina renderizada parece raio-x COM implante."""
    import cv2

    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    m = min(h, w)

    # top-hat branco: sobra so o que e claro e menor que ~35px
    # (fio, parafuso, borda fina de placa — nao o osso)
    tophat = cv2.morphologyEx(
        gray,
        cv2.MORPH_TOPHAT,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (35, 35)),
    )
    mask = (tophat > 60).astype(np.uint8) * 255

    # fora a moldura do filme — a borda da chapa vira linha fina
    # longa no top-hat e dominaria a medida
    bx, by = int(0.10 * w), int(0.10 * h)
    inner = np.zeros_like(mask)
    inner[by : h - by, bx : w - bx] = mask[by : h - by, bx : w - bx]

    lines = cv2.HoughLinesP(
        inner,
        1,
        np.pi / 180,
        threshold=35,
        minLineLength=int(0.10 * m),
        maxLineGap=12,
    )
    if lines is None:
        return False

    longs = []
    for x1, y1, x2, y2 in lines[:, 0]:
        length = float(np.hypot(x2 - x1, y2 - y1))
        if length < 0.2 * m:
            continue
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        rho = (x1 * (y2 - y1) - y1 * (x2 - x1)) / length
        longs.append((ang, rho, length))

    # um fio/pino unico pode ter so uma borda detectada — uma linha
    # interior muito longa ja basta
    if any(length >= 0.38 * m for _, _, length in longs):
        return True

    # bordas paralelas de objeto manufaturado (fio, pino, placa):
    # mesmo angulo (<4 graus) e rho separado por poucos pixels.
    # Calibrado nos casos reais: filme COM fios → 0,43m; filme
    # pos-retirada → melhor par 0,22m (bordas de osso).
    for i in range(len(longs)):
        a1, r1, l1 = longs[i]
        for j in range(i + 1, len(longs)):
            a2, r2, l2 = longs[j]
            da = abs(a1 - a2)
            da = min(da, 180 - da)
            if (
                da < 4
                and 2 < abs(r1 - r2) < 0.06 * m
                and min(l1, l2) >= 0.28 * m
            ):
                return True
    return False
