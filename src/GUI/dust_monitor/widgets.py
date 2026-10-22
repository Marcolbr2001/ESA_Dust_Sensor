# widgets.py
import math
import tkinter as tk
import tkinter.font as tkfont
from collections import deque

import customtkinter as ctk
from PIL import Image, ImageDraw

from . import theme

# Zoom nel tempo dei grafici dei canali (lenti +/-): finestre in secondi, dalla più stretta alla più
# larga. Un canale riceve un campione a ogni frame (~62.5/s): 0.8 s sono i 50 punti di sempre
ZOOM_SECONDS = (0.8, 2, 5, 10, 20, 30)


def zoom_points(seconds, frame_rate):
    """Campioni (frame) in una finestra di 'seconds' secondi."""
    return max(2, round(seconds * frame_rate))


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
    LINE_WIDTH = 1.5     # traccia principale; decimata (zoom out) è da 1 px: le linee spesse costano molto a Tk
    # OUT_P/OUT_N: codici a 12 bit dell'ADC4 (riferimento VDDA), con un loro asse in volt a destra
    ADC4_VREF = 3.3
    ADC4_CODES = 4096
    ADC4_MIN_SPAN = 8    # codici: l'asse destro non zooma oltre (1 codice = 0.8 mV)

    def __init__(self, master, max_points=50, y_labels=True, font_size=8, capacity=None, **kwargs):
        colors = theme.plot_colors()
        kwargs.setdefault("bg", colors["bg"])
        kwargs.setdefault("width", 100)
        kwargs.setdefault("height", 60)
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(master, **kwargs)

        self.max_points = max_points   # campioni mostrati: la finestra, cambia con lo zoom (set_window)
        # Campioni tenuti: con capacity > max_points lo zoom out mostra subito la storia già ricevuta
        keep = max(capacity or max_points, max_points)
        self.values = deque(maxlen=keep)
        self.adc_pos_values = deque(maxlen=keep)
        self.adc_neg_values = deque(maxlen=keep)
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
        self._rrange = None            # (lo, hi) in volt dell'asse destro (OUT_P/OUT_N)
        self._tick_key = None          # ultimo contenuto delle etichette
        self._rtick_key = None
        self._rlabel_w = None
        self._layout = None            # (left, top, pw, ph, labels_visibili)

        self._grid_v = [self.create_line(0, 0, 0, 0, state="hidden") for _ in range(self.GRID_X)]
        self._grid_h = [self.create_line(0, 0, 0, 0, state="hidden") for _ in range(self.N_TICKS)]
        self._ticks = [self.create_text(0, 0, anchor="e", font=self._font, state="hidden")
                       for _ in range(self.N_TICKS)]
        self._rticks = [self.create_text(0, 0, anchor="w", font=self._font, state="hidden")
                        for _ in range(self.N_TICKS)]
        self._adc_pos = self.create_line(0, 0, 0, 0, width=1, state="hidden")
        self._adc_neg = self.create_line(0, 0, 0, 0, width=1, dash=(3, 2), state="hidden")
        self._adc_pos_txt = self.create_text(0, 0, anchor="ne", font=self._font, state="hidden")
        self._adc_neg_txt = self.create_text(0, 0, anchor="ne", font=self._font, state="hidden")
        self._line = self.create_line(0, 0, 0, 0, width=self.LINE_WIDTH, state="hidden")
        self._line_width = self.LINE_WIDTH
        self._apply_item_colors()

        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------------ dati

    def push(self, value, adc_pos=None, adc_neg=None):
        """Accoda un campione (nessun disegno: lo fa render()). OUT_P/OUT_N mancanti restano None,
        così non portano l'asse destro a 0 V (es. storia del canale, che non ha i valori dell'ADC4)."""
        self.values.append(value)
        self.adc_pos_values.append(adc_pos)
        self.adc_neg_values.append(adc_neg)
        self._dirty = True

    def add_value(self, value, adc_pos=None, adc_neg=None):
        self.push(value, adc_pos, adc_neg)

    def set_values(self, values):
        """Sostituisce i dati con gli ultimi max_points valori di 'values', senza OUT_P/OUT_N
        (viste che rileggono una storia già raccolta altrove, es. la tab Global)."""
        self.values.clear()
        self.values.extend(self._tail(values))
        self.adc_pos_values.clear()
        self.adc_neg_values.clear()
        self._dirty = True

    def set_window(self, points):
        """Zoom nel tempo: mostra gli ultimi 'points' campioni (al massimo quelli tenuti)."""
        points = max(2, min(int(points), self.values.maxlen))
        if points != self.max_points:
            self.max_points = points
            self._dirty = True

    def _tail(self, samples):
        """Gli ultimi max_points campioni (la finestra mostrata), come lista."""
        samples = list(samples)
        return samples[-self.max_points:] if len(samples) > self.max_points else samples

    def clear(self):
        self.values.clear()
        self.adc_pos_values.clear()
        self.adc_neg_values.clear()
        self._range = None
        self._rrange = None
        self._dirty = True

    # ------------------------------------------------------------------ stato

    def set_active_state(self, is_active: bool):
        self.is_active = is_active
        self._apply_item_colors()
        self._dirty = True

    def set_show_adcs(self, state: bool):
        self.show_adcs = state
        self._rrange = None
        self._rtick_key = None
        self._geom_dirty = True        # l'asse destro toglie spazio all'area del grafico
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
        for item in self._ticks + self._rticks:
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

    def _rlabel_width(self):
        if self._rlabel_w is None:
            self._rlabel_w = tkfont.Font(font=self._font).measure("3.300V")
        return self._rlabel_w

    @staticmethod
    def _format_volts(val, step):
        return f"{val:.{3 if step < 0.01 else 2}f}V"

    def _scale_adc(self, volts):
        """Asse destro in volt, unico per OUT_P e OUT_N (si vede anche la loro distanza):
        passi 'tondi' e isteresi come l'asse sinistro, ma mai più stretto di ADC4_MIN_SPAN codici."""
        mn, mx = min(volts), max(volts)
        if self._rrange is not None:
            lo, hi = self._rrange
            if lo <= mn and mx <= hi and (mx - mn) >= 0.25 * (hi - lo):
                return self._rrange
        n = self.N_TICKS - 1
        min_span = self.ADC4_MIN_SPAN * self.ADC4_VREF / self.ADC4_CODES
        step = _nice_step(max(mx - mn, min_span) * 1.1 / n)
        while True:
            lo = math.floor(mn / step) * step
            hi = lo + n * step
            if hi >= mx:
                break
            step = _nice_step(step * 1.01)
        self._rrange = (lo, hi)
        return self._rrange

    # ------------------------------------------------------------------ disegno

    def _compute_layout(self, w, h):
        s = theme.widget_scaling(self)
        labels = self.y_labels and w >= 90 * s   # anteprime molto strette: solo la traccia
        left = self._label_width() + 8 * s if labels else 3 * s
        right = self._rlabel_width() + 8 * s if (labels and self.show_adcs) else 3 * s
        top = 6 * s
        return left, top, max(1.0, w - left - right), max(1.0, h - top - 6 * s), labels

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
        for i, item in enumerate(self._rticks):  # visibilità decisa in render(): servono i dati dell'ADC4
            self.coords(item, left + pw + 5 * s, top + ph * i / (self.N_TICKS - 1))
        self.coords(self._adc_pos_txt, left + pw - 2 * s, top + 1 * s)
        self.coords(self._adc_neg_txt, left + pw - 2 * s, top + 13 * s)

    @staticmethod
    def _columns(pw):
        """Colonne del disegno decimato: una ogni 2 pixel."""
        return max(1, int(pw / 2))

    def _samples(self, data, left, pw, has_none=False):
        """(x, valore) da disegnare, campioni allineati a destra: i nuovi entrano da destra e scorrono
        verso sinistra. Con più campioni che pixel ogni colonna porta solo il minimo e il massimo dei
        suoi (min/max in C sulle fette): gradini e picchi restano visibili, il rumore diventa una banda
        piena e una finestra lunga (zoom out) costa come un punto per pixel. has_none: in data ci sono
        None (OUT_P/OUT_N mancanti)."""
        n = len(data)
        offset = self.max_points - n
        cols = self._columns(pw)
        if n <= 2 * cols:
            denom = max(1, self.max_points - 1)
            return [(left + pw * (i + offset) / denom, v) for i, v in enumerate(data)]
        per_col = self.max_points / cols
        out = []
        for c in range(int(offset / per_col), cols):
            seg = data[max(0, math.ceil(c * per_col) - offset):max(0, math.ceil((c + 1) * per_col) - offset)]
            if has_none:
                seg = [v for v in seg if v is not None]
            if seg:
                x = left + pw * (c + 0.5) / cols
                out.append((x, min(seg)))
                out.append((x, max(seg)))
        return out

    def _line_points(self, data, lo, hi, left, top, pw, ph):
        span = (hi - lo) or 1
        pts = []
        for x, v in self._samples(data, left, pw):
            v = lo if v < lo else hi if v > hi else v
            pts.append(x)
            pts.append(top + ph * (1.0 - (v - lo) / span))
        return pts

    def _adc_points(self, codes, lo, hi, left, top, pw, ph, has_none=True):
        """Codici dell'ADC4 come linea a gradini sull'asse destro (lo, hi in volt): sono quantizzati,
        una linea obliqua tra due codici mostrerebbe valori mai misurati. I campioni None si saltano."""
        span = (hi - lo) or 1
        k = self.ADC4_VREF / self.ADC4_CODES
        pts = []
        prev_y = None
        for x, code in self._samples(codes, left, pw, has_none):
            if code is None:
                continue
            v = min(max(code * k, lo), hi)
            y = top + ph * (1.0 - (v - lo) / span)
            if prev_y is not None and y != prev_y:
                pts.extend((x, prev_y))
            pts.extend((x, y))
            prev_y = y
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

        data = self._tail(self.values)
        if len(data) < 2:
            for item in (self._line, self._adc_pos, self._adc_neg, self._adc_pos_txt, self._adc_neg_txt, *self._rticks):
                self.itemconfigure(item, state="hidden")
            return

        lo, hi = self._scale(data)
        key = (lo, hi, self.display_mode)
        if labels and key != self._tick_key:
            for i, item in enumerate(self._ticks):
                val = hi - (hi - lo) * i / (self.N_TICKS - 1)
                self.itemconfigure(item, text=self._format_tick(val))
            self._tick_key = key

        # Finestra con più campioni che pixel (zoom out): traccia decimata, da 1 px
        width = 1 if self.max_points > 2 * self._columns(pw) else self.LINE_WIDTH
        if width != self._line_width:
            self.itemconfigure(self._line, width=width)
            self._line_width = width
        self.coords(self._line, *self._line_points(data, lo, hi, left, top, pw, ph))
        self.itemconfigure(self._line, state="normal")

        self._render_adcs(labels, left, top, pw, ph)

    def _render_adcs(self, labels, left, top, pw, ph):
        """OUT_P (continua) e OUT_N (tratteggiata) sul loro asse in volt a destra: la scala della
        traccia blu (ADS8867, 16 bit, ~0.1 mV) non vale per loro (ADC4, 12 bit, 0.8 mV)."""
        k = self.ADC4_VREF / self.ADC4_CODES
        traces = []
        volts = []
        if self.show_adcs:
            for line, txt, name, samples in ((self._adc_pos, self._adc_pos_txt, "P", self.adc_pos_values),
                                             (self._adc_neg, self._adc_neg_txt, "N", self.adc_neg_values)):
                codes = self._tail(samples)
                has_none = None in codes
                valid = [c for c in codes if c is not None] if has_none else codes
                if valid:
                    volts += (min(valid) * k, max(valid) * k)
                traces.append((line, txt, name, codes, has_none, valid[-1] if valid else None))
        if not volts:
            for item in (self._adc_pos, self._adc_neg, self._adc_pos_txt, self._adc_neg_txt, *self._rticks):
                self.itemconfigure(item, state="hidden")
            return

        lo, hi = self._scale_adc(volts)
        step = (hi - lo) / (self.N_TICKS - 1)
        if labels and (lo, hi) != self._rtick_key:
            for i, item in enumerate(self._rticks):
                self.itemconfigure(item, text=self._format_volts(hi - step * i, step))
            self._rtick_key = (lo, hi)
        for item in self._rticks:
            self.itemconfigure(item, state="normal" if labels else "hidden")

        for line, txt, name, codes, has_none, last in traces:
            pts = self._adc_points(codes, lo, hi, left, top, pw, ph, has_none)
            if len(pts) >= 4:
                self.coords(line, *pts)
                self.itemconfigure(line, state="normal")
            else:
                self.itemconfigure(line, state="hidden")
            if last is None:
                self.itemconfigure(txt, state="hidden")
            else:
                self.itemconfigure(txt, text=f"{name} {last * k:.3f}V", state="normal")
        self.tag_raise(self._line)


# -------------------------------------------------------------------------
#                        GLOBAL GRAPH (Custom)
# -------------------------------------------------------------------------

class GlobalGraph(TimeSeriesGraph):
    """Conteggio cumulativo: asse Y da 0 con passi interi e linea a gradini (niente smussature)."""

    N_TICKS = 5
    GRID_X = 5
    LINE_WIDTH = 2

    def __init__(self, master, max_points=300, **kwargs):
        kwargs.setdefault("font_size", 9)
        super().__init__(master, max_points=max_points, **kwargs)

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
        pts = []
        prev_y = None
        for x, v in self._samples(data, left, pw):
            y = top + ph * (1.0 - (min(max(v, lo), hi) - lo) / span)
            if prev_y is not None and y != prev_y:
                pts.extend((x, prev_y))   # gradino: prima in orizzontale, poi in verticale
            pts.extend((x, y))
            prev_y = y
        return pts


# -------------------------------------------------------------------------
#                       ZOOM NEL TEMPO (lenti + e -)
# -------------------------------------------------------------------------

def _lens_image(sign, color, size):
    """Lente d'ingrandimento con '+' o '-' dentro. Disegnata a 4x e ridotta per avere bordi lisci;
    l'immagine finale è 2x 'size', così CTkImage resta nitida anche con lo schermo al 150-200%."""
    n = size * 2 * 4
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = round(n * 0.09)                       # spessore del tratto
    r = n * 0.29                              # raggio della lente
    c = n * 0.42                              # centro della lente
    d.ellipse((c - r, c - r, c + r, c + r), outline=color, width=w)
    a = (r + w * 0.3) / math.sqrt(2)
    d.line((c + a, c + a, n * 0.9, n * 0.9), fill=color, width=round(w * 1.5))  # manico
    h = r * 0.5
    d.line((c - h, c, c + h, c), fill=color, width=w)
    if sign == "+":
        d.line((c, c - h, c, c + h), fill=color, width=w)
    return img.resize((size * 2, size * 2), Image.LANCZOS)


class ZoomButtons(ctk.CTkFrame):
    """Due lenti per lo zoom nel tempo di tutti i grafici di una tab: '+' accorcia la finestra
    (zoom in), '-' la allunga (zoom out). command riceve -1 (zoom in) o +1 (zoom out)."""

    ICON = 18

    def __init__(self, master, command, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        # Per ogni lente: (attiva, spenta al limite della finestra), nei colori di tema chiaro e scuro
        self._icons = {sign: tuple(ctk.CTkImage(light_image=_lens_image(sign, light, self.ICON),
                                                dark_image=_lens_image(sign, dark, self.ICON),
                                                size=(self.ICON, self.ICON))
                                   for light, dark in (theme.TEXT_MUTED, theme.TEXT_DIM))
                       for sign in "+-"}
        self._buttons = {}
        for sign, step in (("+", -1), ("-", 1)):
            btn = ctk.CTkButton(self, text="", image=self._icons[sign][0], width=28, height=28,
                                fg_color="transparent", hover_color=theme.CARD_HOVER,
                                command=lambda s=step: command(s))
            btn.pack(side="left")
            self._buttons[sign] = btn

    def set_limits(self, can_zoom_in: bool, can_zoom_out: bool):
        """Lente spenta quando la finestra è già al limite."""
        for sign, enabled in (("+", can_zoom_in), ("-", can_zoom_out)):
            self._buttons[sign].configure(image=self._icons[sign][0 if enabled else 1],
                                          state="normal" if enabled else "disabled")


# -------------------------------------------------------------------------
#                            CHANNEL PREVIEW
# -------------------------------------------------------------------------

class ChannelPreview(ctk.CTkFrame):
    def __init__(self, master, channel_id: int, *args, click_callback=None, compact=False, capacity=None,
                 **kwargs):
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

        # compact: anteprime più piccole (tab Global), font e margini ridotti perché "CH 32" e
        # "Pt: 12" stiano ancora sulla stessa riga
        title_size, count_size, header_pad = (11, 10, (6, 5)) if compact else (12, 11, (9, 8))
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=header_pad, pady=(4, 0))
        header.grid_columnconfigure(0, weight=1)

        self.ch_label = ctk.CTkLabel(header, text=f"CH {channel_id}", font=theme.font(title_size, "bold"),
                                     text_color=theme.TEXT, anchor="w", height=18)
        self.ch_label.grid(row=0, column=0, sticky="w")

        self.particles_label = ctk.CTkLabel(header, text="Pt: 0", font=theme.font(count_size),
                                            text_color=theme.TEXT_MUTED, anchor="e", height=18)
        self.particles_label.grid(row=0, column=1, sticky="e")

        self.graph = TimeSeriesGraph(self, max_points=50, height=30, font_size=8, capacity=capacity)
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

    def set_window(self, points: int):
        self.graph.set_window(points)

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
