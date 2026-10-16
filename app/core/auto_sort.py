"""Ordenacao automatica de paginas digitalizadas por perfil de dossie.

Cada pagina e identificada pelo texto nativo (paginas digitais) ou por
OCR (paginas escaneadas), usando fragmentos de palavras-chave por tipo
de documento. O perfil do processo (ortopedia, retirada...) — ordem
das classes e documentos obrigatorios — mora em dossier_profiles; os
detectores visuais de anulacao, em annul_detect.
"""
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pymupdf

from app.core import annul_detect
from app.core import xray_detect
from app.core.dossier_profiles import (
    CLASS_PATTERNS,
    DEFAULT_PROFILE,
    DossierProfile,
    detect,
)
from app.core.dossier_profiles import norm as _normalize

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


# Padroes de documento de identidade/CPF escaneado. Fragmentos curtos
# toleram erros comuns do OCR (ex.: "CARTEIRADEDENTIDADE" com D).
_DOC_ID = [
    "REPUBLICAFEDERATIVA", "CARTEIRADE", "CARTAONACIONAL",
    "VALIDAEMTODO", "REGISTROGERAL", "NAOALFABETIZADO",
]
_CPF_RE = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")


# Palavras que marcam documento anulado/cancelado/rasurado.
_CANCEL_WORDS = ("ANULADO", "CANCELADO", "RASURADO", "SEMVALIDADE")


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
    cancelled = annul_detect.is_annulled(arr)
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


def _has_implant(page: pymupdf.Page) -> bool:
    """Renderiza a pagina de raio-x e detecta implante metalico.
    Falha na renderizacao nao derruba a ordenacao — trata como
    sem implante (vai para depois no perfil de retirada)."""
    try:
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(1.5, 1.5), alpha=False
        )
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        return xray_detect.has_implant(arr)
    except Exception:  # noqa: BLE001 - pagina ruim nao impede o lote
        return False


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
        # documento sem arquivo (memoria) usa o id do objeto —
        # pelo indice dois Document distintos de chamadas
        # diferentes colidiriam no cache de OCR
        sig = _file_sig(doc, f"__memdoc_{id(doc)}")
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
                    annulled[key] = annul_detect.is_annulled(arr)
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
        for class_name, patterns in CLASS_PATTERNS.items():
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


def suggest_order(
    docs: list[pymupdf.Document],
    profile: DossierProfile | None = None,
) -> list[tuple[int, int]]:
    """Retorna todas as (doc, pagina) na sequencia do perfil.

    Paginas anuladas (X/rasura) sao EXCLUIDAS — nao entram no dossie.
    Paginas nao identificadas vao para o fim, na ordem original.
    Raios-X sao ordenados pela data do exame (pre antes de pos).
    """
    profile = profile or DEFAULT_PROFILE
    raw_texts, darks, annulled = _scan(docs)
    norms = {k: _normalize(v) for k, v in raw_texts.items()}
    name = _patient_name(list(raw_texts.values()))
    classes = _classify(raw_texts, norms, darks, annulled, name)

    order: list[tuple[int, int]] = []
    for class_name in profile.order:
        group = [k for k in classes if classes[k] == class_name]
        if class_name == "raiox":
            if profile.xray_opme_first:
                # retirada: filme COM implante (fio/placa/parafuso)
                # antes do pos-retirada; a data desempata cada grupo
                opme = {k: _has_implant(docs[k[0]][k[1]]) for k in group}
                group.sort(
                    key=lambda k: (
                        not opme.get(k, False), _exam_date(norms[k])
                    )
                )
            else:
                group.sort(key=lambda k: _exam_date(norms[k]))
        order.extend(group)
    # desconhecidos e classes fora do perfil (ex.: uma "consulta" que
    # aparece num lote de ortopedia) vao para o fim — nunca sao
    # descartadas silenciosamente
    known = set(profile.order)
    order.extend(
        k for k in classes
        if classes[k] not in known and classes[k] != "anulado"
    )
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
    "FATURAMENTO", "ESPELHO",
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


def detect_process_kind(
    folder: Path, docs: list[pymupdf.Document]
) -> DossierProfile:
    """Perfil do processo da pasta: ortopedia, retirada, etc.

    O conteudo OCR das paginas decide primeiro; sem pista no texto,
    o nome da pasta do paciente e da pasta-mae servem de reserva
    (raiz do lote "RETIRADAS", por exemplo).
    """
    raw_texts, _, _ = _scan(docs)
    norms = [_normalize(t) for t in raw_texts.values()]
    return detect(norms, folder.name, folder.parent.name)


def _strip_falta(name: str) -> str:
    """Nome limpo da pasta/dossie: remove anotacoes de pendencia
    anteriores — "(falta AIH)" geradas pelo app e rabiscos manuais
    tipo "NOME falta danfe" — para nao duplicar na reexecucao."""
    name = re.sub(r"\s*\(falta[^)]*\)", " ", name, flags=re.IGNORECASE)
    name = re.sub(
        r"\s+falta(?:ndo)?\b.*$", "", name, flags=re.IGNORECASE
    )
    return name.strip()


def list_patient_folders(root: str | Path) -> list[tuple[Path, list[Path]]]:
    """Lista (pasta_do_paciente, pdfs) dentro da pasta raiz.

    PDFs soltos na raiz viram uma pseudo-pasta "(raiz)" — sem isso
    eles seriam silenciosamente ignorados quando ha subpastas.
    """
    def pdfs_of(folder: Path) -> list[Path]:
        # insumo real: exclui a saida <pasta>.pdf (com ou sem
        # anotacao " (falta ...)") e restos .tmp.pdf — contavam como
        # "arquivo" na UI e na estatistica do lote
        base = _strip_falta(folder.name)

        def is_output(p: Path) -> bool:
            # cobre "NOME.pdf", "NOME (falta X).pdf" e a anotacao
            # legada "NOME falta X.pdf" — todas sao dossies gerados
            return _strip_falta(p.stem) == base

        return sorted(
            p for p in folder.iterdir()
            if p.suffix.lower() == ".pdf"
            and not p.name.endswith(".tmp.pdf")
            and not is_output(p)
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
    folder: Path, pdfs: list[Path], rename_folder: bool = True
) -> dict:
    """Junta todos os PDFs da pasta, ordena pelo perfil do processo
    (ortopedia/retirada), audita o nome do paciente e salva o dossie
    como <pasta>/<nome_da_pasta>.pdf.

    Documentos obrigatorios ausentes (profile.required) viram anotacao
    no nome do dossie E da pasta: "NOME (falta AIH, GAI)". Na proxima
    execucao a anotacao e recalculada — documento adicionado some da
    lista, e a pasta volta ao nome limpo quando nada falta.

    O save e atomico (arquivo .tmp.pdf + rename): se o app morrer no
    meio da escrita, sobra um .tmp.pdf descartavel em vez de um PDF
    truncado contado como pronto.

    PDFs que nao abrem sao pulados e reportados — um arquivo corrompido
    nao pode derrubar a pasta inteira.

    Retorna {"output", "pages", "suspects", "excluded", "skipped",
    "missing", "profile"} — suspects com "pos" = a pagina no PDF final;
    excluded = paginas anuladas ({file, page}) fora do dossie; skipped =
    nomes dos arquivos que nao abriram; missing = rotulos dos docs
    obrigatorios ausentes; profile = DossierProfile detectado.
    """
    base = _strip_falta(folder.name)
    docs: list[pymupdf.Document] = []
    src_paths: list[Path] = []
    suspects: list[dict] = []
    excluded: list[dict] = []
    skipped: list[str] = []
    try:
        for path in pdfs:
            # nunca inclui resto .tmp nem um dossie gerado antes —
            # mesmo com anotacao " (falta ...)" de rodada anterior
            if path.name.endswith(".tmp.pdf") or _strip_falta(
                path.stem
            ) == base:
                continue
            try:
                docs.append(pymupdf.open(path))
            except Exception:  # noqa: BLE001 - pula e reporta ao fim
                skipped.append(path.name)
                continue
            src_paths.append(path)
        if not docs:
            raise ValueError("nenhum PDF legivel para processar")
        raw_texts, _, _ = _scan(docs)
        norms_map = {k: _normalize(t) for k, t in raw_texts.items()}
        norms_list = list(norms_map.values())
        profile = detect(norms_list, folder.name, folder.parent.name)
        # procedimentos citados por pagina (retirada: fio x placa) —
        # dois tipos no mesmo dossie = documentos divergentes
        proc_pages: dict[str, list[str]] = {}
        for (d, i), t in norms_map.items():
            for label, proc_hints in profile.procedures:
                if any(h in t for h in proc_hints):
                    ref = f"{src_paths[d].name} p.{i + 1}"
                    proc_pages.setdefault(label, []).append(ref)
        order = suggest_order(docs, profile)
        classes = classify_documents(docs)
        for (d, i), cls in classes.items():
            if cls == "anulado":
                excluded.append({"file": src_paths[d].name, "page": i + 1})
        if not order:
            # todas as paginas sairam da ordem (anuladas) — salvar um
            # PDF vazio seria invalido e faria a pasta reprocessar toda
            # rodada sem nunca ficar "pronta"
            raise ValueError(
                f"todas as {len(excluded)} pagina(s) estao anuladas"
            )
        present = {c for c in classes.values() if c != "anulado"}
        missing = [
            label for cls, label in profile.required
            if cls not in present
        ]
        # obrigatorios condicionais do perfil (ex.: termo de anestesia
        # so e exigido na retirada de placa/parafusos, nao na de fio)
        for cls, label, cond_hints in profile.conditional:
            if cls in present:
                continue
            if any(h in t for t in norms_list for h in cond_hints):
                missing.append(label)
        audit = audit_patient(docs, ref_from_folder(folder.name))
        for s in audit["suspects"]:
            s = dict(s)
            s["pos"] = order.index(s["key"]) + 1  # pagina no PDF final
            suspects.append(s)
        with pymupdf.open() as out:
            for d, i in order:
                out.insert_pdf(docs[d], from_page=i, to_page=i)
            # fecha os insumos ANTES de mexer no disco — no Windows um
            # handle aberto impede rename/delete do dossie antigo
            for doc in docs:
                doc.close()
            docs.clear()

            desired = (
                f"{base} (falta {', '.join(missing)})"
                if missing else base
            )
            output = folder / f"{desired}.pdf"
            tmp = folder / f"{desired}.tmp.pdf"
            tmp.unlink(missing_ok=True)
            out.save(tmp, garbage=4, deflate=True)
            os.replace(tmp, output)
            # dossie com anotacao velha (falta diferente) nao pode
            # sobrar — seria lido como insumo na proxima rodada
            for p in folder.iterdir():
                if (
                    p.is_file()
                    and p != output
                    and p.suffix.lower() == ".pdf"
                    and not p.name.endswith(".tmp.pdf")
                    and _strip_falta(p.stem) == base
                ):
                    p.unlink(missing_ok=True)
            if rename_folder and desired != folder.name:
                try:
                    new_folder = folder.with_name(desired)
                    folder.rename(new_folder)
                    folder, output = new_folder, new_folder / output.name
                except OSError:
                    # pasta bloqueada (Explorer aberto etc.) — o
                    # dossie anotado ja sinaliza a pendencia
                    pass
    finally:
        for doc in docs:
            doc.close()
    return {
        "output": output,
        "pages": len(order),
        "suspects": suspects,
        "excluded": excluded,
        "skipped": skipped,
        "missing": missing,
        "profile": profile,
        # {tipo: [refs das paginas]} — so presente quando dois tipos
        # de procedimento aparecem no mesmo dossie
        "proc_divergence": (
            proc_pages if len(proc_pages) > 1 else None
        ),
    }


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
        # restos de saves interrompidos — descarta antes de processar
        for t in folder.glob("*.tmp.pdf"):
            t.unlink(missing_ok=True)
        if _is_valid_output(output):
            entry.update(status="skip", detail="ja organizado",
                         output=output.name)
        elif not pdfs:
            entry.update(status="skip", detail="sem arquivos PDF")
        else:
            try:
                res = process_folder(
                    folder, pdfs, rename_folder=(folder != Path(root))
                )
                out = res["output"]
                profile = res["profile"]
                entry.update(status="ok", pages=res["pages"],
                             output=out.name,
                             folder_path=str(out.parent),
                             suspects=res["suspects"],
                             excluded=res["excluded"],
                             skipped=res["skipped"],
                             missing=res["missing"],
                             kind=profile.key, kind_label=profile.label,
                             proc_divergence=res["proc_divergence"])
            except Exception as exc:  # noqa: BLE001 - segue para a proxima pasta
                entry.update(status="error", detail=str(exc))
        results.append(entry)
        if progress:
            progress(entry)
    return results
