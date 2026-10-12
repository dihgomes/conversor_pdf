"""Paleta de cores do aplicativo (tons de verde — identidade da empresa).

Centralizar aqui evita cores soltas pelo codigo e facilita rebrand.
Dois modos: claro e escuro — set_mode troca os valores no modulo, e as
folhas de estilo remontadas depois ja pegam o tema novo.
"""

# Cores fixas, iguais nos dois temas (a sidebar ja e escura por padrao).
PRIMARY = "#16a34a"          # verde principal (botoes, selecao)
PRIMARY_HOVER = "#15803d"    # verde mais escuro no hover

SIDEBAR_BG = "#17251d"       # fundo da sidebar (verde bem escuro)
SIDEBAR_HOVER = "#26402f"    # hover dos itens da sidebar
SIDEBAR_TEXT = "#e8ece9"     # texto dos itens da sidebar
SIDEBAR_SECTION = "#8fb8a1"  # rotulos de categoria na sidebar
SIDEBAR_SCROLL = "#3d6b52"   # alca do scrollbar na sidebar
SIDEBAR_SCROLL_HOVER = "#4a8a66"  # alca do scrollbar no hover

_LIGHT = {
    "PRIMARY_DISABLED": "#9ccfb0",  # verde claro quando desabilitado
    "APP_BG": "#f7f8f7",            # fundo geral do app
    "SURFACE": "#ffffff",           # cards, listas, inputs
    "BORDER": "#e0e4e1",            # bordas suaves
    "TEXT": "#232a25",              # texto principal
    "TEXT_MUTED": "#6b7280",        # texto secundario
    "TEXT_FAINT": "#9aa39d",        # texto terciario/placeholder
    "STATUS_OK": "#15803d",         # mensagens de sucesso
    "THUMB_BORDER": "#c9cfcb",      # contorno das miniaturas
    "SELECTION_BG": "#dcfce7",      # fundo do item selecionado na grade
    "SELECTION_HOVER": "#bbf7d0",   # borda do item sob o mouse
}

_DARK = {
    "PRIMARY_DISABLED": "#2f5b41",
    "APP_BG": "#131a15",
    "SURFACE": "#1e2822",
    "BORDER": "#33453b",
    "TEXT": "#e8ece9",
    "TEXT_MUTED": "#9aa8a0",
    "TEXT_FAINT": "#6b7a71",
    "STATUS_OK": "#4ade80",
    "THUMB_BORDER": "#3d5248",
    "SELECTION_BG": "#14301f",
    "SELECTION_HOVER": "#1d3f2d",
}

# Valores ativos — comecam no tema claro.
globals().update(_LIGHT)


def set_mode(mode: str) -> None:
    """Troca o tema ativo ('light' ou 'dark'). So atualiza as constantes;
    quem monta stylesheet precisa reaplica-la depois da troca."""
    globals().update(_DARK if mode == "dark" else _LIGHT)
