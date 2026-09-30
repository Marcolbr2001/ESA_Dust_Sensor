# widgets.py
import math
import tkinter as tk
import tkinter.font as tkfont
from collections import deque

import customtkinter as ctk

from . import theme


def _nice_step(raw, integer=False):
    """Passo 'tondo' (1, 2, 2.5, 5 x 10^k) maggiore o uguale a raw."""
    if raw <= 0:
        return 1.0
    base = 10 ** math.floor(math.log10(raw))
    for m in ((1, 2, 5, 10) if integer else (1, 2, 2.5, 5, 10)):
        if m * base >= raw - 1e-9:
            step = m * base
            return max(1.0, step) if integer else step
    return 10 * base


# -------------------------------------------------------------------------
#                        GENERIC TIME-SERIES GRAPH
# -------------------------------------------------------------------------

class TimeSeriesGraph(tk.Canvas):
    """
    Grafico a linea su Canvas nativo, pensato per essere aggiornato molte volte al secondo:
    - push() accoda i campioni senza disegnare; render() disegna solo se ci sono novità
      e solo se il grafico è visibile (tab nascoste = nessun costo)
    - griglia, etichette e linee vengono create una volta sola e poi solo spostate
    - i colori si applicano solo al cambio tema (apply_theme), non a ogni frame
    """

    MAX_ADC = 32768
    N_TICKS = 3          # etichette asse Y (min, metà, max)
    GRID_X = 4           # linee verticali
    INTEGER_TICKS = False

    def __init__(self, master, max_points=50, y_labels=True, font_size=8, **kwargs):
        colors = theme.plot_colors()
        kwargs.setdefault("bg", colors["bg"])
        kwargs.setdefault("width", 100)
        kwargs.setdefault("height", 60)
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(master, **kwargs)

        self.max_points = max_points
        self.values = deque(maxlen=max_points)
        self.adc_pos_values = deque(maxlen=max_points)
        self.adc_neg_values = deque(maxlen=max_points)
        self.display_mode = "bit"
        self.is_active = True
        self.show_adcs = False
        self.y_labels = y_labels

        self._colors = colors
        self._font = theme.canvas_font(font_size)
        self._label_w = None           # larghezza etichette asse Y (misurata una volta)
        self._dirty = True
        self._geom_dirty = True
        self._range = None             # (lo, hi) attuale dell'asse Y
        self._tick_key = None          # ultimo contenuto delle etichette
        self._layout = None            # (left, top, pw, ph, labels_visibili)

        self._grid_v = [self.create_line(0, 0, 0, 0, state="hidden") for _ in range(self.GRID_X)]
        self._grid_h = [self.create_line(0, 0, 0, 0, state="hidden") for _ in range(self.N_TICKS)]
        self._ticks = [self.create_text(0, 0, anchor="e", font=self._font, state="hidden")
                       for _ in range(self.N_TICKS)]
        self._adc_pos = self.create_line(0, 0, 0, 0, width=1, state="hidden")
        self._adc_neg = self.create_line(0, 0, 0, 0, width=1, dash=(3, 2), state="hidden")
        self._adc_pos_txt = self.create_text(0, 0, anchor="ne", font=self._font, state="hidden")
        self._adc_neg_txt = self.create_text(0, 0, anchor="ne", font=self._font, state="hidden")
        self._line = self.create_line(0, 0, 0, 0, width=1.5, state="hidden")
        self._apply_item_colors()

        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------------ dati

    def push(self, value, adc_pos=None, adc_neg=None):
        """Accoda un campione (nessun disegno: lo fa render())."""
        self.values.append(value)
        self.adc_pos_values.append(adc_pos if adc_pos is not None else 0)
        self.adc_neg_values.append(adc_neg if adc_neg is not None else 0)
        self._dirty = True

    def add_value(self, value, adc_pos=None, adc_neg=None):
        self.push(value, adc_pos, adc_neg)

    def clear(self):
        self.values.clear()
        self.adc_pos_values.clear()
        self.adc_neg_values.clear()
        self._range = None
        self._dirty = True

    # ------------------------------------------------------------------ stato

    def set_active_state(self, is_active: bool):
        self.is_active = is_active
        self._apply_item_colors()
        self._dirty = True

    def set_show_adcs(self, state: bool):
        self.show_adcs = state
        self._dirty = True

    def set_display_mode(self, mode: str):
        if mode not in ("bit", "voltage"):
            return
        self.display_mode = mode
        self._label_w = None
        self._tick_key = None
        self._geom_dirty = True
        self._dirty = True

    def apply_theme(self):
        self._colors = theme.plot_colors()
        self.configure(bg=self._colors["bg"])
        self._apply_item_colors()
        self._dirty = True

    def redraw(self, force=False):
        self.render(force=True)

    def _apply_item_colors(self):
        c = self._colors
        line = c["line"] if self.is_active else c["dim"]
        text = c["text"] if self.is_active else c["dim"]
        for item in self._grid_v + self._grid_h:
            self.itemconfigure(item, fill=c["grid"])
        for item in self._ticks:
            self.itemconfigure(item, fill=text)
        self.itemconfigure(self._line, fill=line)
        self.itemconfigure(self._adc_pos, fill=c["adc_pos"] if self.is_active else c["dim"])
        self.itemconfigure(self._adc_neg, fill=c["adc_neg"] if self.is_active else c["dim"])
        self.itemconfigure(self._adc_pos_txt, fill=c["adc_pos"])
        self.itemconfigure(self._adc_neg_txt, fill=c["adc_neg"])

    def _on_resize(self, event):
        self._geom_dirty = True
        self._dirty = True

    # ------------------------------------------------------------------ scala

    def _format_tick(self, val):
        if self.display_mode == "voltage":
            return f"{val * 3.3 / self.MAX_ADC:.2f}V"
        return f"{int(round(val))}"

    def _label_width(self):
        if self._label_w is None:
            f = tkfont.Font(font=self._font)
            self._label_w = max(f.measure(self._format_tick(v)) for v in (self.MAX_ADC, 88888 if self.display_mode == "bit" else 0))
        return self._label_w

    def _scale(self, data):
        """Asse Y con passi 'tondi' e isteresi: resta fermo finché i dati ci stanno bene."""
        mn, mx = min(data), max(data)
        if self._range is not None:
            lo, hi = self._range
            if lo <= mn and mx <= hi and (mx - mn) >= 0.25 * (hi - lo):
                return self._range
        n = self.N_TICKS - 1
        step = _nice_step(max(mx - mn, 8) * 1.1 / n)
        while True:
            lo = math.floor(mn / step) * step
            hi = lo + n * step
            if hi >= mx:
                break
            step = _nice_step(step * 1.01)
        self._range = (lo, hi)
        return self._range

    # ------------------------------------------------------------------ disegno

    def _compute_layout(self, w, h):
        s = theme.widget_scaling(self)
        labels = self.y_labels and w >= 90 * s   # anteprime molto strette: solo la traccia
        left = self._label_width() + 8 * s if labels else 3 * s
        top = 6 * s
        return left, top, max(1.0, w - left - 3 * s), max(1.0, h - top - 6 * s), labels

    def _place_grid(self, w, h):
        left, top, pw, ph, labels = self._layout
        for i, item in enumerate(self._grid_v):
            x = left + pw * (i + 1) / (self.GRID_X + 1)
            self.coords(item, x, top, x, top + ph)
            self.itemconfigure(item, state="normal")
        for i, item in enumerate(self._grid_h):
            y = top + ph * i / (self.N_TICKS - 1)
            self.coords(item, left, y, left + pw, y)
            self.itemconfigure(item, state="normal")
        for i, item in enumerate(self._ticks):
            y = top + ph * i / (self.N_TICKS - 1)
            self.coords(item, left - 5, y)
            self.itemconfigure(item, state="normal" if labels else "hidden")
        s = theme.widget_scaling(self)
        self.coords(self._adc_pos_txt, left + pw - 2 * s, top + 1 * s)
        self.coords(self._adc_neg_txt, left + pw - 2 * s, top + 13 * s)

    def _x_positions(self, n, left, pw):
        """Campioni allineati a destra: i nuovi entrano da destra e scorrono verso sinistra."""
        denom = max(1, self.max_points - 1)
        offset = self.max_points - n
        return [left + pw * (i + offset) / denom for i in range(n)]

    def _line_points(self, data, lo, hi, left, top, pw, ph):
        span = (hi - lo) or 1
        xs = self._x_positions(len(data), left, pw)
        pts = []
        for x, v in zip(xs, data):
            v = lo if v < lo else hi if v > hi else v
            pts.append(x)
            pts.append(top + ph * (1.0 - (v - lo) / span))
        return pts

    def render(self, force=False):
        if not (self._dirty or force):
            return
        if not self.winfo_ismapped():
            return  # tab nascosta o finestra ridotta a icona: resta 'dirty' e si disegna quando torna visibile
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        self._dirty = False

        if self._geom_dirty or self._layout is None:
            self._layout = self._compute_layout(w, h)
            self._place_grid(w, h)
            self._geom_dirty = False
            self._tick_key = None
        left, top, pw, ph, labels = self._layout

        data = self.values
        if len(data) < 2:
            for item in (self._line, self._adc_pos, self._adc_neg, self._adc_pos_txt, self._adc_neg_txt):
                self.itemconfigure(item, state="hidden")
            return

        lo, hi = self._scale(data)
        key = (lo, hi, self.display_mode)
        if labels and key != self._tick_key:
            for i, item in enumerate(self._ticks):
                val = hi - (hi - lo) * i / (self.N_TICKS - 1)
                self.itemconfigure(item, text=self._format_tick(val))
            self._tick_key = key

        self.coords(self._line, *self._line_points(data, lo, hi, left, top, pw, ph))
        self.itemconfigure(self._line, state="normal")

        if self.show_adcs:
            self.coords(self._adc_pos, *self._line_points(self.adc_pos_values, 0, 255, left, top, pw, ph))
            self.coords(self._adc_neg, *self._line_points(self.adc_neg_values, 0, 255, left, top, pw, ph))
            self.itemconfigure(self._adc_pos_txt, text=f"+{self.adc_pos_values[-1]}")
            self.itemconfigure(self._adc_neg_txt, text=f"−{self.adc_neg_values[-1]}")
            for item in (self._adc_pos, self._adc_neg, self._adc_pos_txt, self._adc_neg_txt):
                self.itemconfigure(item, state="normal")
            self.tag_raise(self._line)
        else:
            for item in (self._adc_pos, self._adc_neg, self._adc_pos_txt, self._adc_neg_txt):
                self.itemconfigure(item, state="hidden")


# -------------------------------------------------------------------------
#                        GLOBAL GRAPH (Custom)
# -------------------------------------------------------------------------

class GlobalGraph(TimeSeriesGraph):
    """Conteggio cumulativo: asse Y da 0 con passi interi e linea a gradini (niente smussature)."""

    N_TICKS = 5
    GRID_X = 5

    def __init__(self, master, max_points=300, **kwargs):
        kwargs.setdefault("font_size", 9)
        super().__init__(master, max_points=max_points, **kwargs)
        self.itemconfigure(self._line, width=2)

    def _format_tick(self, val):
        return f"{int(round(val))}"

    def _label_width(self):
        if self._label_w is None:
            self._label_w = tkfont.Font(font=self._font).measure("88888")
        return self._label_w

    def _scale(self, data):
        mx = max(data)
        if self._range is not None:
            lo, hi = self._range
            if mx <= hi and (mx >= 0.3 * hi or hi <= 4 * (self.N_TICKS - 1)):
                return self._range
        step = _nice_step(max(mx, 4) * 1.15 / (self.N_TICKS - 1), integer=True)
        self._range = (0, step * (self.N_TICKS - 1))
        return self._range

    def _line_points(self, data, lo, hi, left, top, pw, ph):
        span = (hi - lo) or 1
        xs = self._x_positions(len(data), left, pw)
        pts = []
        prev_y = None
        for x, v in zip(xs, data):
            y = top + ph * (1.0 - (min(max(v, lo), hi) - lo) / span)
            if prev_y is not None and y != prev_y:
                pts.extend((x, prev_y))   # gradino: prima in orizzontale, poi in verticale
            pts.extend((x, y))
            prev_y = y
        return pts


# -------------------------------------------------------------------------
#                            CHANNEL PREVIEW
# -------------------------------------------------------------------------

class ChannelPreview(ctk.CTkFrame):
    def __init__(self, master, channel_id: int, *args, click_callback=None, **kwargs):
        kwargs.setdefault("fg_color", theme.CARD)
        kwargs.setdefault("corner_radius", 8)
        super().__init__(master, *args, **kwargs)
        self.channel_id = channel_id
        self._click_callback = click_callback
        self.show_adcs_flag = False
        self.is_active = True
        self._particles = 0
        self._particles_shown = None

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=(9, 8), pady=(4, 0))
        header.grid_columnconfigure(0, weight=1)

        self.ch_label = ctk.CTkLabel(header, text=f"CH {channel_id}", font=theme.font(12, "bold"),
                                     text_color=theme.TEXT, anchor="w", height=18)
        self.ch_label.grid(row=0, column=0, sticky="w")

        self.particles_label = ctk.CTkLabel(header, text="Pt: 0", font=theme.font(11),
                                            text_color=theme.TEXT_MUTED, anchor="e", height=18)
        self.particles_label.grid(row=0, column=1, sticky="e")

        self.graph = TimeSeriesGraph(self, max_points=50, height=30, font_size=8)
        self.graph.grid(row=1, column=0, sticky="nsew", padx=6, pady=(1, 6))

        if self._click_callback:
            self._make_clickable(self)
            self._set_hand_cursor(self)

    def _make_clickable(self, widget):
        widget.bind("<Button-1>", self._on_click, add="+")
        for child in widget.winfo_children():
            self._make_clickable(child)

    def _set_hand_cursor(self, widget):
        try:
            widget.configure(cursor="hand2")
        except (tk.TclError, ValueError):
            pass
        for child in widget.winfo_children():
            self._set_hand_cursor(child)

    def _on_click(self, event):
        if self._click_callback:
            self._click_callback(self.channel_id)

    # --- dati (nessun disegno) ---
    def push(self, value, adc_pos=None, adc_neg=None):
        self.graph.push(value, adc_pos, adc_neg)

    def update_from_value(self, value: int, adc_pos=None, adc_neg=None):
        self.push(value, adc_pos, adc_neg)

    def add_value(self, value: int):
        self.push(value)

    def set_particles(self, particles: int):
        self._particles = particles

    def clear(self):
        self.graph.clear()
        self._particles = 0

    # --- disegno (chiamato dal ciclo di render dell'App) ---
    def render(self):
        self.graph.render()
        if self._particles != self._particles_shown:
            self.particles_label.configure(text=f"Pt: {self._particles}")
            self._particles_shown = self._particles

    # --- stato ---
    def set_display_mode(self, mode: str):
        self.graph.set_display_mode(mode)

    def set_active_state(self, is_active: bool):
        self.is_active = is_active
        self.ch_label.configure(text_color=theme.TEXT if is_active else theme.TEXT_DIM)
        self.particles_label.configure(text_color=theme.TEXT_MUTED if is_active else theme.TEXT_DIM)
        self.graph.set_active_state(is_active)

    def set_show_adcs(self, state: bool):
        self.show_adcs_flag = state
        self.graph.set_show_adcs(state)

    def apply_theme(self):
        self.graph.apply_theme()


# -------------------------------------------------------------------------
#                            CHANNEL WINDOW
# -------------------------------------------------------------------------

class ChannelWindow(ctk.CTkToplevel):
    def __init__(self, master, channel_id: int, history=None, initial_particles=None,
                 display_mode="bit", show_adcs=False):
        super().__init__(master)
        self.title(f"Channel {channel_id}")
        self.geometry("760x440")
        self.minsize(520, 320)
        self.configure(fg_color=theme.PAGE)
        self.channel_id = channel_id
        self._particles = initial_particles or 0
        self._particles_shown = None
        self._rate = None
        self._rate_shown = None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # --- pannello informazioni (larghezza fissa) ---
        info = theme.card(self, width=200)
        info.grid(row=0, column=0, sticky="nsew", padx=(theme.PAD, theme.GAP), pady=theme.PAD)
        info.grid_propagate(False)
        info.grid_columnconfigure(0, weight=1)

        theme.section_title(info, f"Channel {channel_id}", size=18).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 0))
        theme.caption(info, "Particles").grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 0))
        self.value_label = ctk.CTkLabel(info, text=str(self._particles), font=theme.font(44, "bold"), anchor="w")
        self.value_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=16)

        self.param_labels = {}
        for r, name in enumerate(["Particle Count", "Events / s", "Noise level"], start=3):
            theme.caption(info, name).grid(row=r, column=0, sticky="w", padx=(16, 4), pady=2)
            val = ctk.CTkLabel(info, text="---", font=theme.font(13, "bold"), anchor="e")
            val.grid(row=r, column=1, sticky="e", padx=(4, 16), pady=2)
            self.param_labels[name] = val
        info.grid_rowconfigure(3, pad=theme.GAP)

        # --- grafico ---
        plot_card = theme.card(self)
        plot_card.grid(row=0, column=1, sticky="nsew", padx=(0, theme.PAD), pady=theme.PAD)
        plot_card.grid_rowconfigure(0, weight=1)
        plot_card.grid_columnconfigure(0, weight=1)

        self.graph = TimeSeriesGraph(plot_card, max_points=200, font_size=9)
        self.graph.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.graph.set_display_mode(display_mode)
        self.graph.set_show_adcs(show_adcs)

        if history:
            for v in history:
                self.graph.push(v)

    # --- dati ---
    def push(self, adc_value, particles=None, adc_pos=None, adc_neg=None):
        self.graph.push(adc_value, adc_pos, adc_neg)
        if particles is not None:
            self._particles = particles

    def update_from_value(self, adc_value: int, particles=None, adc_pos=None, adc_neg=None):
        self.push(adc_value, particles, adc_pos, adc_neg)

    # --- disegno ---
    def render(self, rate=None):
        self.graph.render()
        if self._particles != self._particles_shown:
            self.value_label.configure(text=str(self._particles))
            self.param_labels["Particle Count"].configure(text=str(self._particles))
            self._particles_shown = self._particles
        if rate is not None:
            text = f"{rate:.2f}"
            if text != self._rate_shown:
                self.param_labels["Events / s"].configure(text=text)
                self._rate_shown = text

    # --- stato ---
    def set_show_adcs(self, state: bool):
        self.graph.set_show_adcs(state)

    def set_display_mode(self, mode: str):
        self.graph.set_display_mode(mode)

    def apply_theme(self):
        self.graph.apply_theme()
