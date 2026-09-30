import math
import tkinter as tk
import tkinter.font as tkfont
from collections import Counter

import customtkinter as ctk

from . import theme
from .widgets import GlobalGraph, _nice_step

# --- COSTANTI PER CALCOLO PPM ---
SENSOR_AREA_MM2 = 12.0          # Area totale sensore in mm^2
PARTICLE_SIZE_UM = 10.0         # Dimensione lato particella in micron
# Calcolo Area singola particella in mm^2
PARTICLE_AREA_MM2 = (PARTICLE_SIZE_UM / 1000.0) ** 2
# Fattore: Quanti PPM vale una singola particella?
PPM_FACTOR = (PARTICLE_AREA_MM2 / SENSOR_AREA_MM2) * 1_000_000

# Fattore di conversione: 10 LSB = 1 µm -> 1 LSB = 0.1 µm
LSB_TO_UM = 0.1


# --- CLASSE ISTOGRAMMA ---
class ParticleHistogram(tk.Canvas):
    """
    Istogramma delle ampiezze delle particelle (pulse height distribution).
    Riceve l'ampiezza in LSB di ogni particella e la raggruppa in classi solo al momento del
    disegno, così cambiare unità o calibrazione del materiale ricalcola tutto:
    - µm: classi di larghezza costante in µm (d = a * LSB^b, equazione 5.5 della tesi)
    - LSB: classi di larghezza costante in LSB
    Gli oggetti del canvas vengono riutilizzati; al passaggio del mouse un tooltip mostra
    intervallo e conteggio della classe.
    """
    TARGET_BINS = 45
    MAX_Y_TICKS = 6
    MAX_X_TICKS = 9

    def __init__(self, master, max_val=3000, **kwargs):
        colors = theme.plot_colors()
        kwargs.setdefault("bg", colors["bg"])
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("height", 120)
        super().__init__(master, **kwargs)
        self.max_val = max_val        # fondo scala in LSB: le ampiezze oltre finiscono nell'ultima classe
        self.num_bins = 0             # calcolato al disegno (dipende da unità e calibrazione)
        self.calib_a = 0.264
        self.calib_b = 0.553
        self.display_unit = "um"
        self.on_stats = None          # callback(testo): riepilogo N / mediana / media per l'intestazione

        self._events = {}             # {ampiezza in LSB: quante particelle}
        self._unsized = 0             # particelle contate di cui non si è potuta misurare l'ampiezza
        self._colors = colors
        self._font = theme.canvas_font(9)
        self._title_font = theme.canvas_font(9, "bold")
        self._dirty = True
        self._layout = None           # (left, top, plot_w, plot_h, bin_w, counts, overflow)
        self._hover = None
        self._bars = []

        self._y_grid = [self.create_line(0, 0, 0, 0, dash=(2, 4), state="hidden") for _ in range(self.MAX_Y_TICKS)]
        self._y_ticks = [self.create_text(0, 0, anchor="e", font=self._font, state="hidden") for _ in range(self.MAX_Y_TICKS)]
        self._x_marks = [self.create_line(0, 0, 0, 0, state="hidden") for _ in range(self.MAX_X_TICKS)]
        self._x_ticks = [self.create_text(0, 0, anchor="n", font=self._font, state="hidden") for _ in range(self.MAX_X_TICKS)]
        self._baseline = self.create_line(0, 0, 0, 0, state="hidden")
        self._x_title = self.create_text(0, 0, anchor="s", font=self._title_font, state="hidden")
        self._y_title = self.create_text(0, 0, anchor="n", angle=90, font=self._title_font,
                                         text="Particles", state="hidden")
        self._empty_txt = self.create_text(0, 0, text="No particles detected yet",
                                           font=theme.canvas_font(10), state="hidden")
        self._tip_box = self.create_rectangle(0, 0, 0, 0, state="hidden")
        self._tip_txt = self.create_text(0, 0, anchor="nw", font=self._font, state="hidden")
        self._apply_item_colors()

        self.bind("<Configure>", lambda e: self._mark_dirty())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))

    # --- API usata da App / VisualTab ---
    def set_calibration_params(self, a: float, b: float):
        self.calib_a = a
        self.calib_b = b
        self._mark_dirty()

    def set_display_unit(self, unit: str):
        self.display_unit = unit
        self._mark_dirty()

    def update_data(self, amplitudes, unsized: int = 0):
        """
        Ampiezze (LSB) delle particelle da mostrare, come {ampiezza: quante} oppure come lista,
        più il numero di particelle contate ma senza misura.
        """
        if hasattr(amplitudes, "items"):
            self._events = dict(amplitudes)
        else:
            self._events = dict(Counter(amplitudes))
        self._unsized = unsized
        self._mark_dirty()

    def redraw(self):
        self.render(force=True)

    def apply_theme(self):
        self._colors = theme.plot_colors()
        self.configure(bg=self._colors["bg"])
        self._apply_item_colors()
        self._mark_dirty()

    # --- interni ---
    def _mark_dirty(self):
        self._dirty = True

    def _apply_item_colors(self):
        c = self._colors
        for item in self._y_grid + self._x_marks + [self._baseline]:
            self.itemconfigure(item, fill=c["grid"])
        for item in self._y_ticks + self._x_ticks + [self._x_title, self._y_title, self._empty_txt]:
            self.itemconfigure(item, fill=c["text"])
        for bar in self._bars:
            self.itemconfigure(bar, fill=c["bar"])
        self.itemconfigure(self._tip_box, fill=c["tip_bg"], outline=c["tip_border"])
        self.itemconfigure(self._tip_txt, fill=c["tip_text"])

    def _to_unit(self, lsb):
        if self.display_unit == "um":
            return 0.0 if lsb <= 0 else self.calib_a * (lsb ** self.calib_b)
        return float(lsb)

    def _unit(self):
        return "µm" if self.display_unit == "um" else "LSB"

    def _fmt(self, v):
        if self.display_unit == "um":
            return f"{v:.1f}" if abs(v) < 100 else f"{v:.0f}"
        return f"{v:.0f}"

    @staticmethod
    def _nth(sorted_values, k):
        """k-esimo valore (da 0) di una lista ordinata di (valore, quante)."""
        for v, c in sorted_values:
            if k < c:
                return v
            k -= c
        return sorted_values[-1][0]

    def _publish_stats(self, values):
        """values: lista di (valore nell'unità scelta, quante particelle)."""
        if self.on_stats is None:
            return
        n = sum(c for _, c in values)
        # Così N torna sempre con il conteggio globale anche se qualche gradino non è misurabile
        extra = f"  ·  {self._unsized} not sized" if self._unsized else ""
        if n == 0:
            self.on_stats("N 0" + extra)
            return
        sv = sorted(values)
        median = (self._nth(sv, (n - 1) // 2) + self._nth(sv, n // 2)) / 2
        mean = sum(v * c for v, c in values) / n
        u = self._unit()
        self.on_stats(f"N {n}  ·  median {self._fmt(median)} {u}  ·  mean {self._fmt(mean)} {u}{extra}")

    def render(self, force=False):
        if not (self._dirty or force):
            return
        if not self.winfo_ismapped():
            return
        w, h = self.winfo_width(), self.winfo_height()
        if w < 40 or h < 40:
            return
        self._dirty = False

        # --- Classi (nell'unità scelta) ---
        x_max = self._to_unit(self.max_val)
        bin_w = _nice_step(x_max / self.TARGET_BINS)
        n_bins = max(1, math.ceil(x_max / bin_w - 1e-9))
        counts = [0] * n_bins
        overflow = 0
        values = []
        for a, c in self._events.items():
            v = self._to_unit(a)
            values.append((v, c))
            if a > self.max_val:
                overflow += c
            counts[min(n_bins - 1, int(min(v, x_max) / bin_w))] += c
        self.num_bins = n_bins
        self._publish_stats(values)

        # --- Geometria ---
        s = theme.widget_scaling(self)
        f = tkfont.Font(font=self._font)
        lh = f.metrics("linespace")
        # Finestra bassa: senza titoli degli assi (unità già in didascalia e nello switch) le barre
        # hanno quasi il doppio dello spazio
        compact = h < 130 * s
        top_count = max(counts)
        # Il fondo scala Y dipende dal passo, che dipende dall'altezza: per il margine sinistro
        # si misura l'etichetta del caso più largo (un solo intervallo)
        widest = int(_nice_step(max(top_count, 1), integer=True))
        left = (4 * s if compact else lh + 8 * s) + f.measure(str(widest)) + 8 * s
        right, top = 10 * s, (6 if compact else 10) * s
        bottom = lh + 8 * s if compact else 2 * lh + 10 * s
        plot_w, plot_h = max(10, w - left - right), max(10, h - top - bottom)
        base_y = top + plot_h

        # --- Asse Y: passi interi 'tondi', al massimo 4 intervalli e solo quanti ne stanno ---
        intervals = max(1, min(4, int(plot_h / (lh * 1.3))))
        y_step = int(_nice_step(max(top_count, 1) / intervals, integer=True))
        y_top = y_step * max(1, math.ceil(top_count / y_step))
        y_vals = list(range(0, y_top + 1, y_step))
        for i, item in enumerate(self._y_ticks):
            if i < len(y_vals):
                y = base_y - y_vals[i] / y_top * plot_h
                self.coords(item, left - 6 * s, y)
                self.itemconfigure(item, text=str(y_vals[i]), state="normal")
                self.coords(self._y_grid[i], left, y, left + plot_w, y)
                self.itemconfigure(self._y_grid[i], state="normal" if y_vals[i] > 0 else "hidden")
            else:
                self.itemconfigure(item, state="hidden")
                self.itemconfigure(self._y_grid[i], state="hidden")
        self.coords(self._baseline, left, base_y, left + plot_w, base_y)
        self.itemconfigure(self._baseline, state="normal")

        # --- Asse X: tacche su valori 'tondi' dell'unità scelta ---
        span = n_bins * bin_w
        x_step = _nice_step(span / 5)
        x_vals = []
        v = 0.0
        while v <= span + 1e-9 and len(x_vals) < self.MAX_X_TICKS:
            x_vals.append(v)
            v += x_step
        for i, item in enumerate(self._x_ticks):
            if i < len(x_vals):
                x = left + x_vals[i] / span * plot_w
                self.coords(item, x, base_y + 4 * s)
                self.itemconfigure(item, text=self._fmt(x_vals[i]), state="normal")
                self.coords(self._x_marks[i], x, base_y, x, base_y + 3 * s)
                self.itemconfigure(self._x_marks[i], state="normal")
            else:
                self.itemconfigure(item, state="hidden")
                self.itemconfigure(self._x_marks[i], state="hidden")
        title = "Particle size (µm)" if self.display_unit == "um" else "Pulse amplitude (LSB)"
        self.coords(self._x_title, left + plot_w / 2, h - 2 * s)
        self.itemconfigure(self._x_title, text=title, state="hidden" if compact else "normal")
        # Il titolo verticale solo se ci sta per intero
        y_title_len = tkfont.Font(font=self._title_font).measure("Particles")
        show_y_title = not compact and plot_h >= y_title_len + 4 * s
        self.coords(self._y_title, 4 * s, top + plot_h / 2)
        self.itemconfigure(self._y_title, state="normal" if show_y_title else "hidden")

        # --- Barre ---
        while len(self._bars) < n_bins:
            self._bars.append(self.create_rectangle(0, 0, 0, 0, fill=self._colors["bar"], outline="", state="hidden"))
        bar_px = plot_w / n_bins
        gap = 1 if bar_px > 4 else 0
        for i, bar in enumerate(self._bars):
            if i < n_bins and counts[i] > 0:
                x0 = left + i * bar_px
                self.coords(bar, x0 + gap, base_y - counts[i] / y_top * plot_h, x0 + bar_px - gap, base_y)
                self.itemconfigure(bar, state="normal", fill=self._colors["bar"])
            else:
                self.itemconfigure(bar, state="hidden")

        self.coords(self._empty_txt, left + plot_w / 2, top + plot_h / 2)
        self.itemconfigure(self._empty_txt, state="normal" if not self._events else "hidden")

        self._layout = (left, top, plot_w, plot_h, bin_w, counts, overflow)
        self._hover = None
        self._set_hover(None)

    def _on_motion(self, event):
        if self._layout is None:
            return
        left, top, plot_w, plot_h, bin_w, counts, overflow = self._layout
        if left <= event.x <= left + plot_w and top <= event.y <= top + plot_h:
            i = min(len(counts) - 1, max(0, int((event.x - left) / plot_w * len(counts))))
            if i != self._hover:
                self._set_hover(i, event.x, event.y)
            else:
                self._place_tip(event.x, event.y)
        else:
            self._set_hover(None)

    def _set_hover(self, i, x=0, y=0):
        """Evidenzia la classe sotto il mouse e mostra intervallo e conteggio."""
        if self._hover is not None and self._hover < len(self._bars):
            self.itemconfigure(self._bars[self._hover], fill=self._colors["bar"])
        self._hover = i
        if i is None or self._layout is None:
            self.itemconfigure(self._tip_box, state="hidden")
            self.itemconfigure(self._tip_txt, state="hidden")
            return
        left, top, plot_w, plot_h, bin_w, counts, overflow = self._layout
        if i < len(self._bars):
            self.itemconfigure(self._bars[i], fill=self._colors["bar_hover"])
        lo, hi = i * bin_w, (i + 1) * bin_w
        u = self._unit()
        if i == len(counts) - 1 and overflow:
            rng = f"≥ {self._fmt(lo)} {u}"
        else:
            rng = f"{self._fmt(lo)} – {self._fmt(hi)} {u}"
        n = counts[i]
        label = "particle" if n == 1 else "particles"
        self.itemconfigure(self._tip_txt, text=f"{rng}\n{n} {label}", state="normal")
        self.itemconfigure(self._tip_box, state="normal")
        self._place_tip(x, y)

    def _place_tip(self, x, y):
        s = theme.widget_scaling(self)
        self.coords(self._tip_txt, 0, 0)
        x1, y1, x2, y2 = self.bbox(self._tip_txt)
        tw, th = x2 - x1, y2 - y1
        tx = x + 14 * s
        if tx + tw + 8 * s > self.winfo_width():
            tx = x - tw - 14 * s
        ty = max(4 * s, y - th - 10 * s)
        self.coords(self._tip_txt, tx, ty)
        self.coords(self._tip_box, tx - 6 * s, ty - 4 * s, tx + tw + 6 * s, ty + th + 4 * s)
        self.tag_raise(self._tip_box)
        self.tag_raise(self._tip_txt)


class VisualTab(ctk.CTkFrame):
    """Tab 'Global': comandi, conteggio globale, andamento nel tempo e istogramma."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller
        pad, gap = theme.PAD, theme.GAP

        self._count = 0
        self._count_shown = None
        self._rate = None
        self._rate_shown = None
        self._count_font_size = None
        self._fit_job = None

        s = theme.widget_scaling(self)  # minsize è in pixel fisici: va scalato col DPI
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)                          # barra comandi (sempre visibile)
        self.grid_rowconfigure(1, weight=2, minsize=int(150 * s))    # riepilogo + grafico
        self.grid_rowconfigure(2, weight=1, minsize=int(90 * s))     # istogramma

        # === BARRA COMANDI ===
        bar = theme.card(self)
        bar.grid(row=0, column=0, sticky="ew", padx=pad, pady=(theme.TOP, gap))
        theme.section_title(bar, "Acquisition", size=14).pack(side="left", padx=(16, 12), pady=10)
        theme.start_button(bar, command=self._on_start_pressed).pack(side="left", padx=(0, gap), pady=8)
        theme.stop_button(bar, command=self._on_stop_pressed).pack(side="left", pady=8)

        # === RIEPILOGO + GRAFICO ===
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.grid(row=1, column=0, sticky="nsew", padx=pad, pady=(0, gap))
        mid.grid_rowconfigure(0, weight=1)
        mid.grid_columnconfigure(1, weight=1)

        # Larghezza fissa: il grafico non si sposta quando il numero cambia di cifre
        self.summary = theme.card(mid, width=250)
        self.summary.grid(row=0, column=0, sticky="nsew", padx=(0, gap))
        self.summary.grid_propagate(False)
        self.summary.grid_columnconfigure(0, weight=1)
        self.summary.grid_rowconfigure(1, weight=1)

        theme.caption(self.summary, "GLOBAL PARTICLE COUNT", font=theme.font(12, "bold"), height=20).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(14, 0))

        self._count_font = theme.font(72, "bold")
        self.global_count_label = ctk.CTkLabel(self.summary, text="0", font=self._count_font, anchor="w")
        self.global_count_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=16)

        theme.separator(self.summary, vertical=False).grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 8))

        self.param_labels = {}
        for r, name in enumerate(["Particle Density", "Events / s", "Noise level"], start=3):
            theme.caption(self.summary, name, height=24).grid(row=r, column=0, sticky="w", padx=(18, 4), pady=1)
            val = ctk.CTkLabel(self.summary, text="---", font=theme.font(13, "bold"), anchor="e", height=24)
            val.grid(row=r, column=1, sticky="e", padx=(4, 18), pady=1)
            self.param_labels[name] = val
        ctk.CTkFrame(self.summary, height=10, fg_color="transparent").grid(row=6, column=0)
        self.summary.bind("<Configure>", self._fit_count_font)

        graph_card = theme.card(mid)
        graph_card.grid(row=0, column=1, sticky="nsew")
        graph_card.grid_rowconfigure(1, weight=1)
        graph_card.grid_columnconfigure(0, weight=1)
        theme.section_title(graph_card, "Particle count over time", size=14).grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        theme.caption(graph_card, "last ~15 s").grid(row=0, column=1, sticky="e", padx=16, pady=(12, 0))
        self.global_graph = GlobalGraph(graph_card, max_points=300)
        self.global_graph.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(4, 10))

        # === ISTOGRAMMA ===
        hist_card = theme.card(self)
        hist_card.grid(row=2, column=0, sticky="nsew", padx=pad, pady=(0, pad))
        hist_card.grid_rowconfigure(1, weight=1)
        hist_card.grid_columnconfigure(1, weight=1)
        theme.section_title(hist_card, "Pulse height distribution", size=14).grid(
            row=0, column=0, sticky="w", padx=(16, 10), pady=(12, 0))

        # Riepilogo della distribuzione: numero di particelle, mediana e media della dimensione
        self.hist_stats = theme.caption(hist_card, "N 0")
        self.hist_stats.grid(row=0, column=1, sticky="w", pady=(12, 0))
        self._hist_stats_shown = "N 0"

        self.unit_switch = ctk.CTkSwitch(hist_card, text="Show in µm", command=self._on_unit_switch)
        self.unit_switch.select()  # Lo accendiamo di default
        self.unit_switch.grid(row=0, column=2, sticky="e", padx=16, pady=(12, 0))

        self.histogram = ParticleHistogram(hist_card, max_val=32768)
        self.histogram.on_stats = self._set_hist_stats
        self.histogram.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=10, pady=(4, 10))

    # ------------------------------------------------------------------ dati

    def update_global(self, particle_count: int, particle_sizes: list = None, unsized: int = 0):
        """Aggiorna i dati del riepilogo (il disegno avviene in render())."""
        self._count = particle_count
        if particle_sizes is not None:
            self.histogram.update_data(particle_sizes, unsized)

    def set_event_rate(self, rate: float):
        self._rate = rate

    def push_global(self, particle_count: int):
        self.global_graph.push(particle_count)

    def clear_history(self):
        self.global_graph.clear()

    # ------------------------------------------------------------------ disegno

    def render(self):
        if self._count != self._count_shown:
            self.global_count_label.configure(text=str(self._count))
            self.param_labels["Particle Density"].configure(text=f"{self._count * PPM_FACTOR:.2f} PPM")
            self._count_shown = self._count
        if self._rate is not None:
            text = f"{self._rate:.2f}"
            if text != self._rate_shown:
                self.param_labels["Events / s"].configure(text=text)
                self._rate_shown = text
        self.global_graph.render()
        self.histogram.render()

    def _set_hist_stats(self, text):
        if text != self._hist_stats_shown:
            self.hist_stats.configure(text=text)
            self._hist_stats_shown = text

    def apply_theme(self):
        self.global_graph.apply_theme()
        self.histogram.apply_theme()

    def _fit_count_font(self, event=None):
        # Si calcola a layout completato (dopo il ridimensionamento della card)
        if self._fit_job is None:
            self._fit_job = self.after_idle(self._do_fit_count_font)

    def _do_fit_count_font(self):
        """Il numero grande usa lo spazio che resta nel pannello: grande a finestra alta, più piccolo se è bassa."""
        self._fit_job = None
        # La riga del numero ha weight=1: la sua cella è esattamente lo spazio lasciato libero dalle altre righe
        bbox = self.summary.grid_bbox(0, 1, 1, 1)
        if not bbox:
            return
        s = theme.widget_scaling(self)
        cell_h = bbox[3] / s
        w = self.summary.winfo_width() / s
        size = int(max(20, min(96, w * 0.30, cell_h / 1.25)) // 2 * 2)
        if size != self._count_font_size:
            self._count_font.configure(size=size)
            self._count_font_size = size

    # ------------------------------------------------------------------ comandi

    def _on_start_pressed(self):
        self.controller._on_start_acquisition()

    def _on_stop_pressed(self):
        self.controller._on_stop_acquisition()

    def _on_unit_switch(self):
        """Alterna la visualizzazione tra micrometri e LSB."""
        if self.unit_switch.get() == 1:
            self.histogram.set_display_unit("um")
        else:
            self.histogram.set_display_unit("lsb")
