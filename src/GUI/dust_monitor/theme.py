# theme.py
"""
Stile condiviso della GUI: colori, font e spaziature in un solo posto.
I colori sono tuple (tema chiaro, tema scuro): CustomTkinter li aggiorna da solo quando
cambia il tema. I canvas tk nativi invece non capiscono le tuple, per quelli c'è plot_colors().
"""
import customtkinter as ctk

# --- Superfici --------------------------------------------------------------------------
PAGE = ("#e9e9ee", "#1b1b1e")          # sfondo delle tab
CARD = ("#ffffff", "#26262a")          # card / pannelli / riquadri canale
CARD_HOVER = ("#f1f4f9", "#2d2d33")
STATUS_BAR = ("#dcdce2", "#141416")
SEPARATOR = ("#d9d9e0", "#3a3a41")

# --- Testo ------------------------------------------------------------------------------
TEXT = ("gray10", "#DCE4EE")           # come il default di CustomTkinter
TEXT_MUTED = ("#6e6e78", "#9b9ba5")
TEXT_DIM = ("#b4b4bc", "#55555c")      # canali esclusi dalla somma

# --- Pulsanti e stati -------------------------------------------------------------------
START = ("#2e9d5b", "#2a8a52")
START_HOVER = ("#27854d", "#237446")
STOP = ("#d64545", "#b83b3b")
STOP_HOVER = ("#b93a3a", "#9c3232")
NEUTRAL = ("#8a8a94", "#46464e")
NEUTRAL_HOVER = ("#76767f", "#55555e")
ONLINE = ("#2e9d5b", "#3fb86b")
OFFLINE = ("#a0a0a8", "#6e6e78")

# --- Geometria (px logici, CustomTkinter li scala con il DPI) ---------------------------
RADIUS = 10
PAD = 12        # margine esterno delle card
GAP = 8         # spazio tra elementi vicini
TOP = 4         # margine sopra la prima card di una tab (il CTkTabview ha già il suo)

# --- Canvas (grafici) -------------------------------------------------------------------
_PLOT = {
    "light": {"bg": "#ffffff", "grid": "#e6e6eb", "text": "#6e6e78", "line": "#1f6aa5",
              "adc_pos": "#d97706", "adc_neg": "#7c3aed", "bar": "#3b82c4", "dim": "#c9c9d1",
              "bar_hover": "#1f5f9e", "tip_bg": "#ffffff", "tip_border": "#c9c9d1", "tip_text": "#222226"},
    "dark":  {"bg": "#26262a", "grid": "#35353b", "text": "#9b9ba5", "line": "#4cc2ff",
              "adc_pos": "#f5a524", "adc_neg": "#c084fc", "bar": "#3b8ed0", "dim": "#4a4a52",
              "bar_hover": "#7cc2ff", "tip_bg": "#111114", "tip_border": "#4a4a52", "tip_text": "#e6e6ea"},
}

# Roboto è il font di CustomTkinter (lo registra all'avvio), così canvas e widget coincidono
CANVAS_FONT = "Roboto"


def is_dark():
    return (ctk.get_appearance_mode() or "Dark").lower() != "light"


def plot_colors():
    """Colori per i canvas tk nativi, in base al tema attivo."""
    return dict(_PLOT["dark" if is_dark() else "light"])


def font(size=13, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def canvas_font(size, weight="normal"):
    return (CANVAS_FONT, size, weight) if weight != "normal" else (CANVAS_FONT, size)


def widget_scaling(widget):
    """Fattore DPI di CustomTkinter (es. 1.5 con lo schermo al 150%)."""
    try:
        return ctk.ScalingTracker.get_widget_scaling(widget)
    except Exception:
        return 1.0


def card(parent, **kwargs):
    opts = dict(fg_color=CARD, corner_radius=RADIUS)
    opts.update(kwargs)
    return ctk.CTkFrame(parent, **opts)


def section_title(parent, text, size=15, **kwargs):
    kwargs.setdefault("font", font(size, "bold"))
    kwargs.setdefault("anchor", "w")
    return ctk.CTkLabel(parent, text=text, **kwargs)


def caption(parent, text, **kwargs):
    kwargs.setdefault("text_color", TEXT_MUTED)
    kwargs.setdefault("font", font(12))
    kwargs.setdefault("anchor", "w")
    kwargs.setdefault("justify", "left")
    return ctk.CTkLabel(parent, text=text, **kwargs)


def autowrap(label, container, margin=0):
    """
    Manda a capo il testo di label sulla larghezza di container.
    CTkLabel moltiplica wraplength per il fattore DPI, quindi il valore va in px logici.
    """
    def on_configure(event):
        width = event.width / widget_scaling(container) - margin
        if width > 40:
            label.configure(wraplength=int(width))
    container.bind("<Configure>", on_configure, add="+")


def separator(parent, vertical=True):
    if vertical:
        return ctk.CTkFrame(parent, width=1, height=26, fg_color=SEPARATOR, corner_radius=0)
    return ctk.CTkFrame(parent, height=1, fg_color=SEPARATOR, corner_radius=0)


def start_button(parent, command, **kwargs):
    opts = dict(text="▶  Start", width=96, height=34, font=font(14, "bold"),
                fg_color=START, hover_color=START_HOVER, command=command)
    opts.update(kwargs)
    return ctk.CTkButton(parent, **opts)


def stop_button(parent, command, **kwargs):
    opts = dict(text="■  Stop", width=96, height=34, font=font(14, "bold"),
                fg_color=STOP, hover_color=STOP_HOVER, command=command)
    opts.update(kwargs)
    return ctk.CTkButton(parent, **opts)


def secondary_button(parent, text, command, **kwargs):
    opts = dict(text=text, height=34, font=font(13), fg_color=NEUTRAL,
                hover_color=NEUTRAL_HOVER, command=command)
    opts.update(kwargs)
    return ctk.CTkButton(parent, **opts)
