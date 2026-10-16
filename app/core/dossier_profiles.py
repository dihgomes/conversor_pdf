"""Perfis de dossie por tipo de processo hospitalar.

O que muda entre os processos nao e o conteudo dos documentos (as
classes e as palavras-chave sao compartilhadas — CLASS_PATTERNS), mas:

- order:    a sequencia das classes no dossie final
- required: documentos cuja ausencia vira anotacao "(falta ...)"
            no nome do PDF e da pasta
- hints / name_hints: como o processo e identificado — palavras
            normalizadas no texto das paginas (ex.: "Retirada de
            Materiais de Sintese" no credenciamento) ou no nome da
            pasta/pasta-mae (ex.: raiz do lote "RETIRADAS")

Para adicionar o perfil de REVISOES no futuro basta criar outro
DossierProfile e registra-lo em PROFILES — a deteccao e a UI ja
reagem automaticamente.
"""
import unicodedata
from dataclasses import dataclass


def norm(text: str) -> str:
    """Maiusculo, sem acento e sem espacos/pontuacao — robusto ao OCR
    (que frequentemente junta as palavras, ex.: 'TERMODECONSENTIMENTO')."""
    text = unicodedata.normalize("NFD", text)
    return "".join(
        c for c in text.upper()
        if unicodedata.category(c) != "Mn" and c.isalnum()
    )


# Palavras-chave normalizadas por classe de documento. Fragmentos
# curtos toleram erros comuns do OCR. doc_paciente/doc_responsavel e
# raiox nao usam palavras-chave — sao resolvidos por heuristicas
# proprias (nome do paciente / pixels escuros).
CLASS_PATTERNS: dict[str, list[str]] = {
    "guia":                 ["GUIADEAUTORIZACAODEINTERN", "CREDENCIAMENTODECIRURGIAS", "SENHADEAUTORIZACAO"],
    "laudo":                ["LAUDOPARASOLICITACAO", "SOLICITACAODEAUTORIZACAO", "JUSTIFICATIVADAINTERNACAO"],
    "doc_paciente":         [],
    "doc_responsavel":      [],
    "relatorio_social":     ["RELATORIOSOCIAL", "ASSISTENTESOCIAL", "CRESS"],
    "ficha":                ["ATENDENTE", "DATADAEMISSAO"],
    "faturamento":          ["FATURAMENTOINDIVIDUAL", "TERMADEADESAO", "TERMOCOMPROMISSO"],
    "termo_cirurgia":       ["TERMODECONSENTIMENTO", "CIRURGIADE"],
    "termo_anestesia":      ["AVALIACAOPREANESTESICA", "PREANESTESICA", "PROCEDIMENTOSANESTESICOS"],
    "descricao_anestesica": ["DESCRICAOANESTESICA"],
    "descricao_cirurgica":  ["DESCRICAOCIRURGICA", "ATOCIRURGICO"],
    "raiox":                [],
    "nfe":                  ["DANFE", "NOTAFISCALELETRONICA", "CHAVEDEACESSO"],
    "relatorio_alta":       ["RELATORIODEALTA", "RECEBEUALTA", "ALTAHOSPITALAR"],
    "espelho_aih":          ["ESPELHODAAIH"],
    # processos ambulatoriais de revisao: guia de atendimento da
    # consulta e a solicitacao de exame/controle de revisoes
    "consulta":             ["GUIAATENDIMENTO", "CONSULTADEREVISAO", "ATENDIMENTOENFERMAGEM"],
    "solicitacao":          ["SOLICITACAODEEXAME", "CONTROLEDEREVISOES"],
}


@dataclass(frozen=True)
class DossierProfile:
    """Configuracao de um tipo de processo: rotulo para exibicao,
    ordem das classes no dossie, documentos obrigatorios
    ((classe, rotulo) na ordem de exibicao) e pistas de deteccao.

    conditional: (classe, rotulo, pistas) — a classe so e obrigatoria
    quando alguma pista aparece no texto do lote (ex.: termo de
    anestesia so e exigido na retirada de PLACA/PARAFUSOS — retirada
    de fio usa anestesia local e dispensa o termo).

    xray_opme_first: ordena os raios-x com implante (fio/placa/parafuso
    visivel) antes dos sem — regra do dossie de retirada.
    """
    key: str
    label: str
    order: tuple[str, ...]
    required: tuple[tuple[str, str], ...]
    hints: tuple[str, ...] = ()
    name_hints: tuple[str, ...] = ()
    conditional: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    xray_opme_first: bool = False
    # tipos de procedimento reconheciveis no texto — quando dois
    # tipos distintos aparecem em paginas diferentes do mesmo dossie,
    # os documentos divergem (ex.: um diz "retirada de fio", outro
    # "retirada de placa") e o lote alerta o usuario
    procedures: tuple[tuple[str, tuple[str, ...]], ...] = ()


# Ordem padrao da conta hospitalar/OPME do SUS — compartilhada pelos
# perfis atuais; um perfil pode reordenar quando a sequencia dele
# diferir.
_ORDER_CONTA = (
    "guia", "laudo", "doc_paciente", "doc_responsavel",
    "relatorio_social", "ficha", "faturamento", "termo_cirurgia",
    "termo_anestesia", "descricao_anestesica", "descricao_cirurgica",
    "raiox", "nfe", "relatorio_alta", "espelho_aih",
)

ORTOPEDIA = DossierProfile(
    key="ortopedia",
    label="Ortopedia",
    order=_ORDER_CONTA,
    required=(
        ("guia", "GAI"),
        ("laudo", "AIH"),
        ("faturamento", "FATURAMENTO"),
        ("nfe", "DANFE"),
        ("espelho_aih", "ESPELHO AIH"),
    ),
)

# Retirada de OPME/materiais de sintese: o paciente retorna so para a
# cirurgia de retirada — nao ha compra de OPME, logo o DANFE nao e
# documento obrigatorio desse processo. O termo de anestesia so e
# exigido quando o procedimento e "retirada de placa e/ou parafusos"
# (anestesia geral/raqui); retirada de fio/pino e local e dispensa.
RETIRADA = DossierProfile(
    key="retirada",
    label="Retirada",
    order=_ORDER_CONTA,
    required=(
        ("guia", "GAI"),
        ("laudo", "AIH"),
        ("faturamento", "FATURAMENTO"),
        ("espelho_aih", "ESPELHO AIH"),
    ),
    conditional=(
        ("termo_anestesia", "TERMO ANESTESIA",
         ("RETIRADADEPLACA", "RETIRADADEIMPLANTE")),
        ("descricao_anestesica", "DESCRICAO ANESTESICA",
         ("RETIRADADEPLACA", "RETIRADADEIMPLANTE")),
    ),
    xray_opme_first=True,
    procedures=(
        ("placa/parafusos",
         ("RETIRADADEPLACA", "RETIRADADEIMPLANTE")),
        ("fio/pino",
         ("RETIRADADEFIO", "RETIRADADEPINO")),
    ),
    hints=(
        # "Retirada de Materiais de Sintese" (credenciamento),
        # "retirada de OPME", "retirada de implante" — ja normalizadas
        "RETIRADADEMATERIAIS", "RETIRADADEMATERIAL",
        "RETIRADADEOPME", "RETIRADADESINTESE", "RETIRADADEIMPLANTE",
    ),
    name_hints=("RETIRADA",),
)

# Revisao ambulatorial: retorno pos-cirurgico — consulta e
# solicitacao de exames, sem internamento nem faturamento. A ordem
# segue a dos dossies observados; obrigatorios em rascunho ate a
# confirmacao do fluxo.
REVISAO = DossierProfile(
    key="revisao",
    label="Revisão",
    order=(
        "guia", "consulta", "relatorio_alta", "laudo", "doc_paciente",
        "doc_responsavel", "relatorio_social", "ficha", "raiox",
        "solicitacao", "espelho_aih",
    ),
    required=(
        ("guia", "GAI"),
        ("consulta", "CONSULTA"),
    ),
    hints=(
        "CONSULTADEREVISAO", "CONTROLEDEREVISOES",
        "CONTROLDEREVISAO", "CONTROLEDEREVISAO",
    ),
    name_hints=("REVISO",),
)

PROFILES: dict[str, DossierProfile] = {
    p.key: p for p in (ORTOPEDIA, RETIRADA, REVISAO)
}
DEFAULT_PROFILE = ORTOPEDIA


def detect(norms: list[str], *folder_names: str) -> DossierProfile:
    """Escolhe o perfil do processo.

    1. Conteudo: qualquer pagina cujo texto normalizado contenha uma
       pista do perfil (ex.: "RETIRADADEMATERIAISDESINTESE" no
       credenciamento) — decide mesmo se a pasta tem nome neutro.
    2. Nome: a pasta do paciente ou a raiz do lote (ex.: "RETIRADAS")
       — cobre o caso em que o OCR nao leu a pista.
    3. Sem evidencia: perfil padrao (ortopedia).
    """
    for profile in PROFILES.values():
        if profile.hints and any(
            hint in text for text in norms for hint in profile.hints
        ):
            return profile
    for name in folder_names:
        n = norm(name)
        for profile in PROFILES.values():
            if any(h in n for h in profile.name_hints):
                return profile
    return DEFAULT_PROFILE
