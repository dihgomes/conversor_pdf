"""Ordenacao automatica de paginas digitalizadas por perfil de dossie.

Cada pagina e identificada pelo texto nativo (paginas digitais) ou por
OCR (paginas escaneadas), usando fragmentos de palavras-chave por tipo
de documento. O perfil ORTOPEDIA segue a sequencia padrao da conta
hospitalar/OPME do SUS.
"""
import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pymupdf

_ocr_engine = None

# Cache de OCR por (arquivo, mtime, tamanho, pagina): reutiliza o
# resultado se o mesmo PDF for analisado de novo. A assinatura do
# arquivo (mtime+size) esta na chave — um PDF substituido por um
# rescan com o mesmo nome nao recebe OCR velho.
_OCR_CACHE: dict[tuple[str, int, int, int], tuple[str, float, bool]] = {}


def _file_sig(doc: pymupdf.Document, fallback: str) -> tuple:
    """Assinatura do arquivo do Document para o cache: (nome, mtime,
    tamanho). Documentos sem arquivo (memoria) usam o fallback."""
    if doc.name:
        try:
            st = os.stat(doc.name)
            return (doc.name, st.st_mtime_ns, st.st_size)
        except OSError:
            pass
    return (fallback, 0, 0)


def _ocr():
    """RapidOCR em singleton — o modelo demora para carregar na 1a vez."""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _normalize(text: str) -> str:
    """Maiusculo, sem acento e sem espacos/pontuacao — robusto ao OCR
    (que frequentemente junta as palavras, ex.: 'TERMODECONSENTIMENTO')."""
    text = unicodedata.normalize("NFD", text)
    return "".join(
        c for c in text.upper()
        if unicodedata.category(c) != "Mn" and c.isalnum()
    )


# Padroes de documento de identidade/CPF escaneado. Fragmentos curtos
# toleram erros comuns do OCR (ex.: "CARTEIRADEDENTIDADE" com D).
_DOC_ID = [
    "REPUBLICAFEDERATIVA", "CARTEIRADE", "CARTAONACIONAL",
    "VALIDAEMTODO", "REGISTROGERAL", "NAOALFABETIZADO",
]
_CPF_RE = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")

# Ordem final do dossie. doc_paciente/doc_responsavel e raiox sao
# resolvidos por heuristicas proprias (nome do paciente / pixels escuros),
# nao por palavras-chave.
ORTOPEDIA = [
    ("guia",                 ["GUIADEAUTORIZACAODEINTERN", "CREDENCIAMENTODECIRURGIAS", "SENHADEAUTORIZACAO"]),
    ("laudo",                ["LAUDOPARASOLICITACAO", "SOLICITACAODEAUTORIZACAO", "JUSTIFICATIVADAINTERNACAO"]),
    ("doc_paciente",         []),
    ("doc_responsavel",      []),
    ("relatorio_social",     ["RELATORIOSOCIAL", "ASSISTENTESOCIAL", "CRESS"]),
    ("ficha",                ["ATENDENTE", "DATADAEMISSAO"]),
    ("faturamento",          ["FATURAMENTOINDIVIDUAL", "TERMADEADESAO", "TERMOCOMPROMISSO"]),
    ("termo_cirurgia",       ["TERMODECONSENTIMENTO", "CIRURGIADE"]),
    ("termo_anestesia",      ["AVALIACAOPREANESTESICA", "PREANESTESICA", "PROCEDIMENTOSANESTESICOS"]),
    ("descricao_anestesica", ["DESCRICAOANESTESICA"]),
    ("descricao_cirurgica",  ["DESCRICAOCIRURGICA", "ATOCIRURGICO"]),
    ("raiox",                []),
    ("nfe",                  ["DANFE", "NOTAFISCALELETRONICA", "CHAVEDEACESSO"]),
    ("relatorio_alta",       ["RELATORIODEALTA", "RECEBEUALTA", "ALTAHOSPITALAR"]),
    ("espelho_aih",          ["ESPELHODAAIH"]),
]


# Palavras que marcam documento anulado/cancelado/rasurado.
_CANCEL_WORDS = ("ANULADO", "CANCELADO", "RASURADO", "SEMVALIDADE")


def _has_big_x(arr: np.ndarray) -> bool:
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
            crosses_center(p, n) for p in ps for n in ns
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


def _has_color_mark(arr: np.ndarray) -> bool:
    """Detecta marcacao de anulacao com caneta colorida que NAO e X:
    ovais, circulos e elipses desenhados sobre campos ou a pagina.

    Tres propriedades de uma marcacao a caneta separam isso de ruido:
    tinta saturada (a mesma mascara do caminho 1 de _has_big_x),
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


def _has_box_mark(arr: np.ndarray) -> bool:
    """Detecta marcacao de anulacao em forma de CAIXA/RETANGULO a
    caneta — contorno quebrado demais para _has_color_mark, que exige
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


def _ocr_page(page: pymupdf.Page) -> tuple[str, float, bool]:
    """Renderiza a pagina, mede a fracao escura, detecta anulacao (X)
    e roda OCR. Retorna (texto_ocr, dark_ratio, anulada).

    Paginas escuras (raio-x) pulam o OCR — nao ha texto util nelas e a
    escuridao ja as classifica — mas ainda passam pela deteccao de X,
    pois raio-x anulado e justamente marcado a caneta sobre o filme.
    Se o texto sair quase vazio, tenta com a pagina a 90 graus
    (scans de RG frequentemente ficam deitados).
    """
    def render(rotation: int) -> np.ndarray:
        matrix = pymupdf.Matrix(1.5, 1.5).prerotate(rotation)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )

    arr = render(0)
    dark = float((arr.mean(axis=2) < 100).mean())
    cancelled = (
        _has_big_x(arr) or _has_color_mark(arr) or _has_box_mark(arr)
    )
    if dark >= 0.5:
        return "", dark, cancelled

    result, _ = _ocr()(arr)
    text = " ".join(r[1] for r in result) if result else ""
    if len(text) < 25:
        result, _ = _ocr()(render(90))
        text2 = " ".join(r[1] for r in result) if result else ""
        if len(text2) > len(text):
            text = text2
    return text, dark, cancelled


def _patient_name(raw_texts: list[str]) -> str | None:
    """Extrai o nome do paciente de qualquer pagina ('Paciente: NOME').

    Usa a mesma extracao da auditoria — rotulo + run em caixa alta —
    com trim em rotulo de campo e rejeicao de prosa ("paciente sob
    anestesia"). Retorna o run cru com espacos para tokenizacao.
    """
    for raw in raw_texts:
        for m in _NAME_RAW_RE.finditer(raw):
            tokens = m.group(1).split()
            if len(tokens) < 2:
                continue
            norm = _normalize(m.group(1))
            trimmed = _trim_name(norm)
            if not (8 <= len(trimmed) <= 45) or any(
                r in norm for r in _NAME_REJECT
            ):
                continue
            # mantem so os tokens originais que cobrem o nome aparado
            keep, acc = [], ""
            for t in tokens:
                keep.append(t)
                acc += _normalize(t)
                if len(acc) >= len(trimmed):
                    break
            return " ".join(keep)
    return None


def _name_match_score(text_norm: str, name: str) -> float:
    """Fracao de palavras >=4 letras do nome presentes no texto."""
    tokens = [t for t in _normalize(name).split() if len(t) >= 4]
    # _normalize remove espacos; refaz os tokens a partir do nome cru
    tokens = [
        _normalize(t) for t in name.split()
        if len(_normalize(t)) >= 4
    ]
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in text_norm)
    return hits / len(tokens)


def _exam_date(text_norm: str) -> int:
    """Maior data ddmmyyyy encontrada (data do exame > data de nascimento)."""
    best = 0
    for m in re.finditer(r"(\d{2})(\d{2})(\d{4})", text_norm):
        dd, mm, yyyy = map(int, m.groups())
        if 1 <= dd <= 31 and 1 <= mm <= 12 and 1990 <= yyyy <= 2100:
            best = max(best, yyyy * 10000 + mm * 100 + dd)
    return best


def _scan(
    docs: list[pymupdf.Document],
) -> tuple[
    dict[tuple[int, int], str],
    dict[tuple[int, int], float],
    dict[tuple[int, int], bool],
]:
    """Extrai texto (nativo ou OCR), fracao escura e flag de anulacao
    (X) de cada pagina.

    Resultados ficam em cache por arquivo — analises repetidas do
    mesmo PDF sao instantaneas.
    """
    raw_texts: dict[tuple[int, int], str] = {}
    darks: dict[tuple[int, int], float] = {}
    annulled: dict[tuple[int, int], bool] = {}
    todo: list[tuple[tuple[int, int], tuple, pymupdf.Page, str]] = []

    for d, doc in enumerate(docs):
        sig = _file_sig(doc, f"__memdoc_{d}")
        for i in range(doc.page_count):
            key = (d, i)
            try:
                page = doc[i]
                text = page.get_text()
            except Exception:  # noqa: BLE001 - pagina danificada nao
                page, text = None, ""  # deve derrubar a varredura toda
            if page is None:
                raw_texts[key] = ""
                darks[key] = 0.0
                annulled[key] = False
                continue
            if len(text.strip()) >= 200:
                raw_texts[key] = text
                # pagina com camada de texto pula o OCR, mas a marca
                # de anulacao e VISUAL (desenho sobre o scan) — ainda
                # precisa renderizar e passar pelos detectores
                try:
                    pix = page.get_pixmap(
                        matrix=pymupdf.Matrix(1.5, 1.5), alpha=False
                    )
                    arr = np.frombuffer(
                        pix.samples, dtype=np.uint8
                    ).reshape(pix.height, pix.width, pix.n)
                    darks[key] = float((arr.mean(axis=2) < 100).mean())
                    annulled[key] = (
                        _has_big_x(arr)
                        or _has_color_mark(arr)
                        or _has_box_mark(arr)
                    )
                except Exception:  # noqa: BLE001
                    darks[key] = 0.0
                    annulled[key] = False
                continue
            cache_key = sig + (i,)
            cached = _OCR_CACHE.get(cache_key)
            if cached is not None:
                ocr_text, dark, cancelled = cached
                raw_texts[key] = f"{text} {ocr_text}"
                darks[key] = dark
                annulled[key] = cancelled
            else:
                todo.append((key, cache_key, page, text))

    # OCR em serie: o onnxruntime ja usa todos os nucleos internamente,
    # e rodar sessoes em paralelo medido ficou mais lento (contencao).
    if todo:
        _ocr()  # falha do MOTOR propaga — nao e erro por pagina
    for key, cache_key, page, text in todo:
        try:
            ocr_text, dark, cancelled = _ocr_page(page)
        except Exception:  # noqa: BLE001 - uma pagina ruim nao derruba
            ocr_text, dark, cancelled = "", 0.0, False  # a pasta toda
        _OCR_CACHE[cache_key] = (ocr_text, dark, cancelled)
        raw_texts[key] = f"{text} {ocr_text}"
        darks[key] = dark
        annulled[key] = cancelled

    return raw_texts, darks, annulled


def _classify(
    raws: dict[tuple[int, int], str],
    norms: dict[tuple[int, int], str],
    darks: dict[tuple[int, int], float],
    annulled: dict[tuple[int, int], bool],
    patient_name: str | None,
) -> dict[tuple[int, int], str]:
    """Prioridade: anulado > palavras-chave > raio-x > doc de identidade."""
    classes: dict[tuple[int, int], str] = {}
    for key, text_norm in norms.items():
        # pagina anulada nao entra no dossie, mesmo com conteudo valido
        # por baixo do X — vem primeiro que as palavras-chave
        if annulled.get(key) or any(w in text_norm for w in _CANCEL_WORDS):
            classes[key] = "anulado"
            continue
        # melhor score de palavras-chave
        best_class, best_score = "", 0
        for class_name, patterns in ORTOPEDIA:
            score = sum(1 for p in patterns if p in text_norm)
            if score > best_score:
                best_class, best_score = class_name, score
        if best_score:
            classes[key] = best_class
            continue
        # raio-x: pagina escura com pouco texto
        if darks[key] >= 0.4 and len(text_norm) < 150:
            classes[key] = "raiox"
            continue
        # documento de identidade: paciente x responsavel pelo nome
        if any(p in text_norm for p in _DOC_ID) or _CPF_RE.search(raws[key]):
            if patient_name and _name_match_score(text_norm, patient_name) >= 0.5:
                classes[key] = "doc_paciente"
            else:
                classes[key] = "doc_responsavel"
            continue
        classes[key] = "desconhecido"
    return classes


def classify_documents(
    docs: list[pymupdf.Document],
) -> dict[tuple[int, int], str]:
    """Identifica a classe de cada pagina de todos os documentos."""
    raw_texts, darks, annulled = _scan(docs)
    norms = {k: _normalize(v) for k, v in raw_texts.items()}
    name = _patient_name(list(raw_texts.values()))
    return _classify(raw_texts, norms, darks, annulled, name)


def suggest_order(docs: list[pymupdf.Document]) -> list[tuple[int, int]]:
    """Retorna todas as (doc, pagina) na sequencia do perfil ORTOPEDIA.

    Paginas anuladas (X/rasura) sao EXCLUIDAS — nao entram no dossie.
    Paginas nao identificadas vao para o fim, na ordem original.
    Raios-X sao ordenados pela data do exame (pre antes de pos).
    """
    raw_texts, darks, annulled = _scan(docs)
    norms = {k: _normalize(v) for k, v in raw_texts.items()}
    name = _patient_name(list(raw_texts.values()))
    classes = _classify(raw_texts, norms, darks, annulled, name)

    order: list[tuple[int, int]] = []
    for class_name, _ in ORTOPEDIA:
        group = [k for k in classes if classes[k] == class_name]
        if class_name == "raiox":
            group.sort(key=lambda k: _exam_date(norms[k]))
        order.extend(group)
    order.extend(k for k in classes if classes[k] == "desconhecido")
    return order


# --------------------------------------------------- auditoria de paciente

# Extracao de nome no texto BRUTO do OCR (que preserva fronteiras de
# palavra). O rotulo exige \b para nao casar dentro de palavras
# ("CNE-S-REGULAGAO" → SR falso) e o nome precisa comecar em maiuscula —
# assim prosa como "o paciente recebeu..." nao gera candidato.
_NAME_RAW_RE = re.compile(
    r"\b(?i:paciente|benefici[aá]rio|cliente|sra?|sr\W*a?)"
    r"[^A-Za-zÀ-ÿ0-9]{0,10}"
    r"([A-ZÀ-Ý][A-ZÀ-Ý'\-]*(?:\s+[A-ZÀ-Ý][A-ZÀ-Ý'\-]*){0,6})"
)
# Candidatos que contem estas palavras sao prosa/rotulo de assinatura,
# nao nome de paciente ("PACIENTE OU RESPONSAVEL", "paciente atendido").
_NAME_REJECT = (
    "RESPONSAVEL", "MEDICO", "TESTEMUNHA", "ASSINATURA", "DECLAR",
    "ATENDIDO", "ATRAVES", "RECEBEU", "ADMITIDO", "ENCAMINHADO",
    "PROFISSIONAL", "CIENTE", "APRESENTANDO", "REALIZOU",
    # prosa medica capturada junto ("paciente em dd/h sob anestesia...")
    "ANESTESIA", "VISUALIZADO", "DEFORMIDADE", "REALIZADO", "REDUCAO",
    "FIXACAO", "CIRURGIA", "TRATAMENTO", "EQUIPAMENTO", "RECURSOS",
    "FRATURA", "MEMBRO", "ANTEBRACO", "ANESTESICO",
)
# Rotulos de campo que costumam vir colados logo apos o nome no texto
# normalizado — cortam o run capturado (ex.: NOME + "DATANASC...").
_NAME_CUTS = (
    "IDADE", "SEXO", "DATANASC", "NASCIMENTO", "PRONTUARIO", "MEDICO",
    "FILIACAO", "ENDERECO", "NATURALIDADE", "MUNICIPIO", "TELEFONE",
    "ADMISSAO", "SOLICITANTE", "PROCEDIMENTO", "HOSPITAL", "CONVENIO",
    "INTERNACAO", "SERVICO",
)
# Classes em que o nome do paciente e obrigatorio no documento.
_NAME_STRICT = {
    "guia", "laudo", "ficha", "faturamento",
    "relatorio_alta", "espelho_aih", "doc_paciente",
}
# Classes sem nome de paciente por natureza (nfe = hospital;
# doc_responsavel = nome do responsavel, diferente por definicao).
_NAME_SKIP = {"raiox", "nfe", "doc_responsavel", "desconhecido", "anulado"}
# Palavras de anotacao em nomes de pasta que nao fazem parte do nome
# do paciente (ex.: "ANDRE SANTOS falta danfe").
_FOLDER_NOISE = {
    "FALTA", "FALTANDO", "DANFE", "PLACA", "SEM", "USO", "MATERIAL",
    "RX", "PRE", "POS", "NAO", "TEM", "PENDENTE", "PENDENTES",
}


def _trim_name(run: str) -> str:
    """Corta o run de letras no primeiro rotulo de campo colado."""
    cut = len(run)
    for label in _NAME_CUTS:
        pos = run.find(label)
        if 0 < pos < cut:
            cut = pos
    return run[:cut]


def _divergent_names(raw: str, ref_norm: str | None) -> list[str]:
    """Nomes ligados a rotulos de paciente ("PACIENTE X", "Sr(a), X")
    que NAO sao a referencia — candidatos a pagina de outro paciente."""
    found: list[str] = []
    for m in _NAME_RAW_RE.finditer(raw):
        cand = _trim_name(_normalize(m.group(1)))
        if (8 <= len(cand) <= 45 and cand not in found
                and not any(r in cand for r in _NAME_REJECT)
                and not _same_person(cand, ref_norm)):
            found.append(cand)
    return found


def _reocr_page(page: pymupdf.Page, zoom: float = 2.0) -> str:
    """Re-OCR em zoom alternado: o detector do RapidOCR as vezes
    dropa a linha italica/sublinhada do nome em certos zooms
    (guia SESAB, termos de consentimento)."""
    try:
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom), alpha=False
        )
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        result, _ = _ocr()(arr)
        return " ".join(r[1] for r in result) if result else ""
    except Exception:  # noqa: BLE001 - falha no retry nao e erro
        return ""


def _same_person(a: str, b: str) -> bool:
    """Dois nomes normalizados sao a mesma pessoa? Tolera sufixos de
    campo colados e pequenos erros de OCR."""
    if not a or not b:
        return False
    if len(a) >= 8 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.72


def ref_from_folder(folder_name: str) -> str | None:
    """Nome de referencia a partir do nome da pasta do paciente,
    removendo anotacoes entre parenteses e palavras de observacao."""
    name = re.sub(r"\(.*?\)", " ", folder_name)
    tokens = [
        t for t in re.split(r"[^A-Za-zÀ-ÿ]+", name)
        if len(_normalize(t)) >= 4 and _normalize(t) not in _FOLDER_NOISE
    ]
    return " ".join(tokens) if len(tokens) >= 2 else None


def audit_patient(
    docs: list[pymupdf.Document],
    reference: str | None = None,
) -> dict:
    """Verifica se todas as paginas pertencem ao mesmo paciente.

    reference: nome esperado (ex.: nome da pasta). Sem ele, usa o nome
    mais comum encontrado nos documentos. Retorna {"reference",
    "checks", "suspects"} — suspects lista as paginas divergentes.
    """
    raw_texts, darks, annulled = _scan(docs)
    norms = {k: _normalize(v) for k, v in raw_texts.items()}
    name = reference or _patient_name(list(raw_texts.values()))
    name_norm = _normalize(name) if name else None
    classes = _classify(raw_texts, norms, darks, annulled, name)

    checks: list[dict] = []
    suspects: list[dict] = []
    for key, cls in sorted(classes.items()):
        entry = {"key": key, "cls": cls}
        if cls in _NAME_SKIP:
            entry["status"] = "skip"
        elif not name:
            entry["status"] = "noverify"
        else:
            score = _name_match_score(norms[key], name)
            # Nomes ligados a rotulos de paciente (ex.: "PACIENTE X",
            # "Sr(a), X"). Suspeita so quando um nome divergente e
            # efetivamente encontrado — ausencia de nome (variantes de
            # formulario sem campo) vira "nao verificavel", nao alarme.
            found = _divergent_names(raw_texts[key], name_norm)
            if score < 0.5:
                # Re-OCR em zooms alternados antes de julgar: cada
                # scan responde a um zoom diferente (o detector do
                # RapidOCR dropa a linha italica/sublinhada do nome).
                # So paginas nao verificadas pagam esse custo, e para
                # assim que a referencia aparece.
                d, i = key
                for zoom in (2.0, 2.5, 1.2):
                    retry = _reocr_page(docs[d][i], zoom)
                    if retry:
                        raw_texts[key] = f"{raw_texts[key]} {retry}"
                        norms[key] = _normalize(raw_texts[key])
                        score = _name_match_score(norms[key], name)
                        found = _divergent_names(
                            raw_texts[key], name_norm
                        )
                    if score >= 0.5:
                        break
            if found and score < 0.5:
                # nome de paciente divergente E referencia ausente —
                # so assim a pagina pode ser de outro paciente; com o
                # nome correto presente, "divergencias" sao so prosa
                # capturada (medico, mae, texto corrido).
                entry.update(status="suspeita", found=found[:1],
                             score=score)
                suspects.append(entry)
            elif score >= 0.5:
                entry.update(status="ok", score=score)
            else:
                entry.update(status="noverify", score=score)
        checks.append(entry)
    return {"reference": name, "checks": checks, "suspects": suspects}


# ------------------------------------------------------- modo em lote


def list_patient_folders(root: str | Path) -> list[tuple[Path, list[Path]]]:
    """Lista (pasta_do_paciente, pdfs) dentro da pasta raiz.

    PDFs soltos na raiz viram uma pseudo-pasta "(raiz)" — sem isso
    eles seriam silenciosamente ignorados quando ha subpastas.
    """
    def pdfs_of(folder: Path) -> list[Path]:
        # insumo real: exclui a saida <pasta>.pdf e restos .tmp.pdf —
        # contavam como "arquivo" na UI e na estatistica do lote
        return sorted(
            p for p in folder.iterdir()
            if p.suffix.lower() == ".pdf"
            and not p.name.endswith(".tmp.pdf")
            and p.name != f"{folder.name}.pdf"
        )

    root = Path(root)
    subs = sorted(p for p in root.iterdir() if p.is_dir())
    loose = pdfs_of(root)
    folders = [(f, pdfs_of(f)) for f in subs]
    if loose:
        folders.insert(0, (root, loose))
    return folders


def _is_valid_output(path: Path) -> bool:
    """Saida existente so conta se for um PDF abrivel com paginas.

    Um save interrompido (crash/queda de energia) deixaria um arquivo
    truncado — trata-lo como 'ja organizado' esconderia o problema.
    """
    try:
        with pymupdf.open(path) as doc:
            return doc.page_count > 0
    except Exception:  # noqa: BLE001 - qualquer falha = invalido
        return False


def process_folder(
    folder: Path, pdfs: list[Path]
) -> tuple[Path, int, list, list, list]:
    """Junta todos os PDFs da pasta, ordena pelo perfil, audita o nome
    do paciente e salva o dossie como <pasta>/<nome_da_pasta>.pdf.

    O save e atomico (arquivo .tmp.pdf + rename): se o app morrer no
    meio da escrita, sobra um .tmp.pdf descartavel em vez de um PDF
    truncado contado como pronto.

    PDFs que nao abrem sao pulados e reportados — um arquivo corrompido
    nao pode derrubar a pasta inteira.

    Retorna (saida, num_paginas, suspects, excluidas, ilegiveis) —
    suspects com "pos" = a pagina no PDF final; excluidas = paginas
    anuladas ({file, page}) fora do dossie; ilegiveis = nomes dos
    arquivos que nao abriram.
    """
    output = folder / f"{folder.name}.pdf"
    tmp = folder / f"{folder.name}.tmp.pdf"
    docs: list[pymupdf.Document] = []
    src_paths: list[Path] = []
    suspects: list[dict] = []
    excluded: list[dict] = []
    skipped: list[str] = []
    try:
        for path in pdfs:
            if path in (output, tmp):
                continue  # nunca inclui saida/resto de execucao anterior
            try:
                docs.append(pymupdf.open(path))
            except Exception:  # noqa: BLE001 - pula e reporta ao fim
                skipped.append(path.name)
                continue
            src_paths.append(path)
        if not docs:
            raise ValueError("nenhum PDF legivel para processar")
        order = suggest_order(docs)
        for (d, i), cls in classify_documents(docs).items():
            if cls == "anulado":
                excluded.append({"file": src_paths[d].name, "page": i + 1})
        if not order:
            # todas as paginas sairam da ordem (anuladas) — salvar um
            # PDF vazio seria invalido e faria a pasta reprocessar toda
            # rodada sem nunca ficar "pronta"
            raise ValueError(
                f"todas as {len(excluded)} pagina(s) estao anuladas"
            )
        audit = audit_patient(docs, ref_from_folder(folder.name))
        for s in audit["suspects"]:
            s = dict(s)
            s["pos"] = order.index(s["key"]) + 1  # pagina no PDF final
            suspects.append(s)
        with pymupdf.open() as out:
            for d, i in order:
                out.insert_pdf(docs[d], from_page=i, to_page=i)
            tmp.unlink(missing_ok=True)
            out.save(tmp, garbage=4, deflate=True)
        os.replace(tmp, output)
    finally:
        for doc in docs:
            doc.close()
    return output, len(order), suspects, excluded, skipped


def organize_batch(
    root: str | Path,
    progress=None,
    cancel=None,
) -> list[dict]:
    """Processa todas as pastas de pacientes sob `root`, uma por vez.

    progress.emit(dict) e chamado com {"folder", "index", "total",
    "status": start|ok|skip|error, ...} a cada evento. cancel() entre
    pastas interrompe o lote. Pastas cujo arquivo de saida ja existe
    sao puladas.
    """
    folders = list_patient_folders(root)
    results: list[dict] = []
    total = len(folders)

    # Preflight: se alguma pasta precisa de fato processar, garante que
    # o motor de OCR sobe — senao cada pasta falharia com o mesmo erro
    # (ex.: "no module named cv2" quando a extracao do exe ficou
    # incompleta apos encerramento abrupto).
    if any(
        pdfs and not _is_valid_output(f / f"{f.name}.pdf")
        for f, pdfs in folders
    ):
        try:
            _ocr()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Motor de OCR indisponivel "
                f"({exc}). Se o app foi encerrado de forma abrupta, "
                "feche-o, reinicie o aplicativo e tente novamente."
            ) from exc

    for index, (folder, pdfs) in enumerate(folders, 1):
        if cancel and cancel():
            break
        entry = {"folder": folder.name, "index": index, "total": total,
                 "files": len(pdfs)}
        if progress:
            progress({**entry, "status": "start"})
        output = folder / f"{folder.name}.pdf"
        # resto de um save interrompido — descarta antes de processar
        (folder / f"{folder.name}.tmp.pdf").unlink(missing_ok=True)
        if _is_valid_output(output):
            entry.update(status="skip", detail="ja organizado",
                         output=output.name)
        elif not pdfs:
            entry.update(status="skip", detail="sem arquivos PDF")
        else:
            try:
                out, pages, suspects, excluded, skipped = process_folder(
                    folder, pdfs
                )
                entry.update(status="ok", pages=pages, output=out.name,
                             suspects=suspects, excluded=excluded,
                             skipped=skipped)
            except Exception as exc:  # noqa: BLE001 - segue para a proxima pasta
                entry.update(status="error", detail=str(exc))
        results.append(entry)
        if progress:
            progress(entry)
    return results
