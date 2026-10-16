"""Deteccao visual de paginas anuladas/marcadas em dossiês digitalizados.

Tres detectores cobrem os tipos de marcacao encontrados nos lotes:
- X grande cruzando a pagina (caneta escura ou colorida)
- oval/circulo colorido sobre campos
- caixa/retangulo a caneta em torno de campos

Todos recebem a pagina renderizada como array RGB (np.ndarray) e
devolvem bool. O wrapper is_annulled() e o que o pipeline usa.
"""
import numpy as np


def has_big_x(arr: np.ndarray) -> bool:
    """Detecta o 'X' de anulacao sobre a pagina.

    Dois caminhos, porque a marcacao pode ser feita com caneta escura
    sobre papel claro ou com caneta colorida sobre filme/raio-x:

    1. mascara de tinta colorida (saturacao alta) — tracos diagonais
       SOLIDOS (re-detectados ou de grande cobertura) nas duas
       direcoes cruzando na regiao central
    2. bordas em cinza — diagonais de 0,3w x 0,3h nas duas direcoes
       cujo cruzamento cai no interior de ambos os segmentos e na
       regiao central; o teste de interioridade rejeita bordas de
       documento digitalizado torto (se tocam so nos cantos)
    """
    import cv2

    h, w = arr.shape[:2]
    m = min(h, w)

    def collect(
        mask: np.ndarray, min_len: float, th: int, gap: int
    ) -> tuple[list, list]:
        lines = cv2.HoughLinesP(
            mask, 1, np.pi / 180, threshold=th,
            minLineLength=int(min_len * m), maxLineGap=gap,
        )
        pos, neg = [], []
        if lines is not None:
            for x1, y1, x2, y2 in lines[:, 0]:
                dx, dy = x2 - x1, y2 - y1
                if dx == 0:
                    continue
                slope = dy / dx
                if 0.4 <= abs(slope) <= 2.5:
                    (pos if slope > 0 else neg).append((x1, y1, x2, y2))
        return pos, neg

    def crosses_center(a, b) -> bool:
        """Cruzamento dentro da regiao central E na porcao interior de
        ambos os tracos — num X de anulacao cada risco continua alem do
        ponto de encontro; as bordas de um documento girado se tocam
        apenas nas pontas (cantos do cartao)."""
        ax, ay, bx, by = a
        cx, cy, dx_, dy_ = b
        den = (bx - ax) * (dy_ - cy) - (by - ay) * (dx_ - cx)
        if den == 0:
            return False
        t = ((cx - ax) * (dy_ - cy) - (cy - ay) * (dx_ - cx)) / den
        ix, iy = ax + t * (bx - ax), ay + t * (by - ay)
        blen2 = (dx_ - cx) ** 2 + (dy_ - cy) ** 2
        tb = ((ix - cx) * (dx_ - cx) + (iy - cy) * (dy_ - cy)) / blen2
        straddle = 0.12 <= t <= 0.88 and 0.12 <= tb <= 0.88
        return straddle and (0.15 * w <= ix <= 0.85 * w) and (
            0.15 * h <= iy <= 0.85 * h
        )

    def stroke_darkness(s, band: int = 4) -> float:
        """Fracao de pixels escuros (<120) na banda ao longo do traco.
        Risco de caneta e uma faixa escura continua (~0,4+); borda de
        cartao/documento girado e um degrau fino entre areas claras
        (~0,15-0,2) — e o que separa um X de anulacao de bordas de
        RG/CNH digitalizados de lado."""
        g = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        gh, gw = g.shape
        x1, y1, x2, y2 = [int(round(v)) for v in s]
        n = int(max(abs(x2 - x1), abs(y2 - y1))) + 1
        xs = np.linspace(x1, x2, n).astype(int)
        ys = np.linspace(y1, y2, n).astype(int)
        ln = np.hypot(x2 - x1, y2 - y1) or 1
        px_, py_ = -(y2 - y1) / ln, (x2 - x1) / ln
        dark, total = 0, 0
        for off in range(-band, band + 1):
            xx = np.clip(xs + int(round(px_ * off)), 0, gw - 1)
            yy = np.clip(ys + int(round(py_ * off)), 0, gh - 1)
            dark += int((g[yy, xx] < 120).sum())
            total += n
        return dark / total

    def solid_strokes(grp) -> list:
        """Agrupa segmentos colineares (rho proximo) no mesmo traco e
        devolve um representante dos tracos SOLIDOS — re-detectados 3+
        vezes ou cobrindo 0,6x o lado menor.

        Um risco de caneta grosso e visto varias vezes pelo Hough;
        bordas de implante/arte do raio-x aparecem 1-2 vezes — e isso
        que separa o X de anulacao de estrutura da propria imagem.
        """
        # mesmo traco = mesma inclinacao (bucket 0,125) E mesmo rho;
        # sem isso, segmentos de angulos distintos com rho parecido
        # (artefatos do raio-x) formariam um "traco" falso
        buckets: dict[float, list] = {}
        for x1, y1, x2, y2 in grp:
            slope = (y2 - y1) / (x2 - x1)
            buckets.setdefault(round(slope * 8) / 8, []).append(
                (x1, y1, x2, y2)
            )
        solids = []
        for segs_in in buckets.values():
            items = sorted(
                (
                    (x1 * (y2 - y1) - y1 * (x2 - x1))
                    / np.hypot(x2 - x1, y2 - y1),
                    (x1, y1, x2, y2),
                )
                for x1, y1, x2, y2 in segs_in
            )
            clusters: list[list] = []
            for rho, seg in items:
                if clusters and rho - clusters[-1][1] <= 0.05 * m:
                    clusters[-1][0].append(seg)
                    clusters[-1][1] = rho
                else:
                    clusters.append([[seg], rho])
            for segs, _ in clusters:
                x1, y1, x2, y2 = segs[0]
                L = np.hypot(x2 - x1, y2 - y1)
                ux, uy = (x2 - x1) / L, (y2 - y1) / L
                ts = [
                    x * ux + y * uy
                    for s in segs
                    for x, y in ((s[0], s[1]), (s[2], s[3]))
                ]
                if len(segs) < 3 and (max(ts) - min(ts)) < 0.6 * m:
                    continue
                # reconstrói a extensao total do traco na linha de
                # suporte (rho medio) — necessario para o teste de
                # atravessamento do X
                rho = np.mean(
                    [
                        (s[0] * (s[3] - s[1]) - s[1] * (s[2] - s[0]))
                        / np.hypot(s[2] - s[0], s[3] - s[1])
                        for s in segs
                    ]
                )
                px, py = rho * uy, -rho * ux
                solids.append(
                    (
                        px + min(ts) * ux,
                        py + min(ts) * uy,
                        px + max(ts) * ux,
                        py + max(ts) * uy,
                    )
                )
        return solids

    # 1) tinta colorida (caneta azul/vermelha sobre papel ou filme).
    # Teto de cobertura: risco de caneta e esparso (~3%); documento
    # colorido inteiro (CNH, carimbo grande) gera "tracos" nas bordas.
    # Saturacao >60 (nao 30): o tom azulado de filme de raio-x fica
    # em S~35 — logo acima do limiar baixo, as bordas diagonais do
    # filme girado viravam um "X" falso. Caneta de verdade tem S~60+.
    def pair_spans_page(p, n) -> bool:
        """O par cruzado precisa ocupar boa parte da pagina: um X de
        anulacao atravessa o documento (>=0,45m na largura e >=0,30m
        na altura nos casos reais); curvas de assinatura/rabisco que
        simulam um X ficam confinadas num canto (<=0,43m)."""
        x0 = min(p[0], p[2], n[0], n[2])
        x1 = max(p[0], p[2], n[0], n[2])
        y0 = min(p[1], p[3], n[1], n[3])
        y1 = max(p[1], p[3], n[1], n[3])
        return (x1 - x0) >= 0.45 * m and (y1 - y0) >= 0.30 * m

    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    ink = ((hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 40)).astype(
        np.uint8
    ) * 255
    # Teto 1,2%: pagina de X a caneta tem ~0,5-0,7% de tinta;
    # documento colorido inteiro (CNH com guilloche ~2%) produz
    # tracos diagonais falsos ate com os filtros geometricos.
    if (ink > 0).mean() <= 0.012:
        ink = cv2.morphologyEx(
            ink, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)),
        )
        pos, neg = collect(ink, 0.15, 15, 60)
        ps, ns = solid_strokes(pos), solid_strokes(neg)
        if ps and ns and any(
            crosses_center(p, n) and pair_spans_page(p, n)
            for p in ps for n in ns
        ):
            return True

    # 2) traco escuro sobre papel claro (caneta preta, carimbo).
    # O Hough quebra uma diagonal longa em segmentos ~0,3-0,5x a
    # pagina — solid_strokes reagrupa os pedacos colineares e
    # reconstrói a extensao total do traco; aqui exigimos traco
    # reconstruido >= 0,85x o lado menor (um X a caneta atravessa a
    # pagina inteira — guilloche de certidao e bordas de cartao ficam
    # bem abaixo) e o teste de interioridade barra encontros de canto.
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    pos, neg = collect(edges, 0.3, 60, 20)
    # muitos segmentos diagonais = textura (guilloche de certidao,
    # diagramacao), nao um X — um risco de anulacao sao poucos tracos
    if len(pos) + len(neg) > 35:
        return False
    ps = [
        s for s in solid_strokes(pos)
        if np.hypot(s[2] - s[0], s[3] - s[1]) >= 0.85 * m
    ]
    ns = [
        s for s in solid_strokes(neg)
        if np.hypot(s[2] - s[0], s[3] - s[1]) >= 0.85 * m
    ]
    return bool(ps) and bool(ns) and any(
        crosses_center(p, n)
        and stroke_darkness(p) >= 0.25
        and stroke_darkness(n) >= 0.25
        for p in ps
        for n in ns
    )


def has_color_mark(arr: np.ndarray) -> bool:
    """Detecta marcacao de anulacao com caneta colorida que NAO e X:
    ovais, circulos e elipses desenhados sobre campos ou a pagina.

    Tres propriedades de uma marcacao a caneta separam isso de ruido:
    tinta saturada (a mesma mascara do caminho 1 de has_big_x),
    formato FECHADO grande (perimetro e area minimos) e anel FINO
    (interior quase vazio). Isso deixa de fora carimbos (interior
    denso de texto), sublinhados (razao de aspecto de linha) e
    documentos coloridos inteiros (teto de cobertura de 15%).
    """
    import cv2

    h, w = arr.shape[:2]
    m = min(h, w)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    ink = ((hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 40)).astype(
        np.uint8
    ) * 255
    if (ink > 0).mean() > 0.15:
        return False  # documento colorido inteiro (CNH etc.)

    ink = cv2.morphologyEx(
        ink,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)),
    )
    contours, _ = cv2.findContours(
        ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        extent = (cw * ch) / (w * h)
        if extent < 0.02:
            continue  # marca pequena (check, rubrica)
        if extent > 0.20:
            continue  # estrutura do documento (tabela, moldura)
        if min(cw, ch) / max(cw, ch) < 0.15:
            continue  # linha/sublinhado — aberto, nao fechado
        if cv2.arcLength(c, True) < 1.6 * m:
            # lacada de assinatura forma anel pequeno (1,2-1,35m); a
            # marcacao de anulacao circula conteudo (2,4m+)
            continue
        inner = (ink[y : y + ch, x : x + cw] > 0).mean()
        if inner > 0.18:
            continue  # interior cheio: carimbo/realce, nao anel
        # Solidez (area do contorno / hull convexo): um oval fechado
        # cobre quase todo o hull (~0,5+); assinatura e rabisco sao
        # esparsos dentro do proprio contorno (~0,2).
        hull = cv2.convexHull(c)
        if cv2.contourArea(c) / max(cv2.contourArea(hull), 1) < 0.40:
            continue
        return True
    return False


def has_box_mark(arr: np.ndarray) -> bool:
    """Detecta marcacao de anulacao em forma de CAIXA/RETANGULO a
    caneta — contorno quebrado demais para has_color_mark, que exige
    anel fechado. Aqui o sinal e geometrico: um par de segmentos quase
    horizontais sobrepostos em X e separados em Y (topo e base da
    caixa), com um segmento quase vertical ligando-os numa ponta.

    Discriminadores contra tabelas/molduras do proprio documento:
    - largura da caixa <= 0,6 da pagina (moldura de tabela ~0,84)
    - altura <= 0,2 e densidade de tinta no interior baixa (caixa a
      caneta envolve texto/impressao, nao mais linhas de grade)
    Saturacao >60: reduz o cast azulado de scan que pinta linhas de
    tabela impressas de "tinta colorida".
    """
    import cv2

    h, w = arr.shape[:2]
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    ink = ((hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 40)).astype(
        np.uint8
    )
    dark = (cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) < 120).astype(
        np.uint8
    )
    if ink.mean() > 0.006:
        # formulario com grade impressa colorida, cartao (RG/CNH/SUS)
        # ou documento colorido — marcacao a caneta e ~0,2% da pagina
        return False

    lines = cv2.HoughLinesP(
        ink,
        1,
        np.pi / 180,
        threshold=20,
        minLineLength=30,
        maxLineGap=15,
    )
    if lines is None:
        return False

    hs, vs = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = x2 - x1, y2 - y1
        length = np.hypot(dx, dy)
        if length < 40:
            continue
        slope = abs(dy / dx) if dx else 99
        if slope < 0.15:
            hs.append((min(x1, x2), (y1 + y2) / 2, max(x1, x2)))
        elif slope > 6:
            vs.append((min(y1, y2), (x1 + x2) / 2, max(y1, y2)))

    if len(hs) + len(vs) > 25:
        # a grade da propria tabela e impressa em cor saturada — as
        # "caixas" sao celulas do formulario, nao marcacao. Uma caixa
        # a caneta gera poucas linhas isoladas (~10-16 no total).
        return False

    boxes: list[tuple[int, int, int, int]] = []
    for a in range(len(hs)):
        for b in range(a + 1, len(hs)):
            x0a, ya, x1a = hs[a]
            x0b, yb, x1b = hs[b]
            gap_y = abs(ya - yb)
            if not 20 <= gap_y <= 0.2 * h:
                continue
            bx0, bx1 = min(x0a, x0b), max(x1a, x1b)
            if bx1 - bx0 > 0.6 * w:
                continue  # moldura de tabela/pagina inteira
            if min(x1a, x1b) - max(x0a, x0b) < 50:
                continue  # horizontais nao se sobrepoem
            for y0v, xv, y1v in vs:
                if y1v - y0v < 0.5 * gap_y:
                    continue
                near_edge = min(
                    abs(xv - x0a), abs(xv - x1a),
                    abs(xv - x0b), abs(xv - x1b),
                ) < 25
                spans = (y0v - 15 <= min(ya, yb)
                         and y1v + 15 >= max(ya, yb))
                if not (near_edge and spans):
                    continue
                # densidade no interior ENCOLHIDO — sem isso os
                # proprios tracos da caixa contaminam a medida (numa
                # caixa pequena as 4 bordas sao ~12% da area)
                y0, y1 = int(min(ya, yb)), int(max(ya, yb))
                mx = max(8, int(0.08 * (bx1 - bx0)))
                my = max(8, int(0.15 * gap_y))
                roi = ink[y0 + my : y1 - my, int(bx0) + mx : int(bx1) - mx]
                if roi.size == 0:
                    continue  # caixa pequena demais p/ interior encolhido
                inner = roi.mean()
                if inner >= 0.04:
                    continue  # interior com tinta: carimbo preenchido
                # a caixa precisa cercar CONTEUDO (texto do campo) —
                # sublinhado/tira de assinatura forma caixa vazia
                dk = dark[y0 + my : y1 - my,
                          int(bx0) + mx : int(bx1) - mx].mean()
                if dk < 0.02:
                    continue
                box = (int(bx0), y0, int(bx1), y1)
                # a mesma caixa fisica e detectada varias vezes
                # (Hough emite linhas duplicadas) — conta uma so
                dup = any(
                    abs(box[0] - q[0]) < 20 and abs(box[1] - q[1]) < 20
                    and abs(box[2] - q[2]) < 20 and abs(box[3] - q[3]) < 20
                    for q in boxes
                )
                if not dup:
                    boxes.append(box)
                    if len(boxes) > 8:
                        # tabela/grade gera dezenas de caixas
                        # distintas; marcacao a caneta e 1-3
                        return False
                break  # proxima linha vertical so conta uma vez
    return len(boxes) > 0


def is_annulled(arr: np.ndarray) -> bool:
    """True se a pagina renderizada tem marcacao de anulacao
    (X grande, oval colorido ou caixa a caneta)."""
    return (
        has_big_x(arr)
        or has_color_mark(arr)
        or has_box_mark(arr)
    )
