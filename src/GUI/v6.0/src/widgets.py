# widgets.py
import tkinter as tk
import customtkinter as ctk
from collections import deque
import math
import time

# -------------------------------------------------------------------------
#                      PALETTE COLORI
# -------------------------------------------------------------------------

def _get_graph_colors():
    """Ritorna i colori in base al tema."""
    try:
        mode = ctk.get_appearance_mode()
    except Exception:
        mode = "Dark"

    mode = (mode or "Dark").lower()

    if mode == "light":
        return {
            "bg":   "#f5f5f7",
            "grid": "#d0d0d0",
            "line": "#1f6aa5",
            "text": "#222222",
            "adc_pos": "#a0a0a0", # Grigio ADC Positivo
            "adc_neg": "#808080", # Grigio scuro ADC Negativo
        }
    else:  # "dark"
        return {
            "bg":   "#1c1c1c",
            "grid": "#333333",
            "line": "#33b5ff",
            "text": "#cccccc",
            "adc_pos": "#b0b0b0", # Grigio chiaro ADC Pos
            "adc_neg": "#707070", # Grigio medio ADC Neg
        }


# -------------------------------------------------------------------------
#                        GENERIC TIME-SERIES GRAPH
# -------------------------------------------------------------------------

class TimeSeriesGraph(tk.Canvas):
    """
    Canvas nativo ottimizzato per Windows.
    - Usa self.coords(...) per muovere la linea (no delete/create continuo).
    - Usa 'debounce' sul resize per velocizzare l'avvio dell'app.
    """

    MAX_ADC = 32768

    def __init__(self, master, max_points=50, **kwargs):
        if "bg" not in kwargs:
            kwargs["bg"] = "#1c1c1c"

        kwargs.setdefault("width", 100)
        kwargs.setdefault("height", 60)
        kwargs.setdefault("highlightthickness", 0)

        super().__init__(master, **kwargs)

        self.max_points = max_points
        self.values = deque(maxlen=max_points)
        
        # Buffer per gli ADC
        self.adc_pos_values = deque(maxlen=max_points)
        self.adc_neg_values = deque(maxlen=max_points)
        
        self.display_mode = "bit"
        self.is_active = True 
        self.show_adcs = False

        # Throttle FPS (0.033 = ~30 FPS).
        self._min_draw_interval = 0.033
        self._last_draw_time = 0.0

        # Memoria per evitare ridisegni inutili della griglia
        self._prev_min = -999
        self._prev_max = -999
        self._prev_w = 0
        self._prev_h = 0

        # ID degli oggetti grafici persistenti
        self.line_id = None
        self.adc_pos_line_id = None
        self.adc_neg_line_id = None
        
        # Debounce job per il resize
        self._resize_job = None

        self.bind("<Configure>", self._on_resize)

    def set_active_state(self, is_active: bool):
        self.is_active = is_active
        self.redraw(force=True)

    def set_show_adcs(self, state: bool):
        self.show_adcs = state
        if not state:
            if self.adc_pos_line_id: self.itemconfigure(self.adc_pos_line_id, state="hidden")
            if self.adc_neg_line_id: self.itemconfigure(self.adc_neg_line_id, state="hidden")
        else:
            if self.adc_pos_line_id: self.itemconfigure(self.adc_pos_line_id, state="normal")
            if self.adc_neg_line_id: self.itemconfigure(self.adc_neg_line_id, state="normal")
        self.redraw(force=True)

    def set_display_mode(self, mode: str):
        if mode not in ("bit", "voltage"): return
        self.display_mode = mode
        self._prev_min = -999
        self.redraw(force=True)

    def _on_resize(self, event):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(100, lambda: self.redraw(force=False))

    def add_value(self, value: float, adc_pos: int = None, adc_neg: int = None):
        self.values.append(value)
        self.adc_pos_values.append(adc_pos if adc_pos is not None else 0)
        self.adc_neg_values.append(adc_neg if adc_neg is not None else 0)
        self.redraw()

    # ------------------------------------------------------------------ utils

    def _y_to_px(self, v, vmin, vmax, top, plot_h):
        if vmax <= vmin: return top + plot_h / 2.0
        if v < vmin: v = vmin
        elif v > vmax: v = vmax
        return top + plot_h * (1.0 - (v - vmin) / (vmax - vmin))

    # ------------------------------------------------------------------ draw

    def redraw(self, force=False):
        now = time.perf_counter()
        if (not force) and (now - self._last_draw_time) < self._min_draw_interval:
            return
        self._last_draw_time = now

        try:
            w = self.winfo_width()
            h = self.winfo_height()
        except tk.TclError:
            return

        if w < 2 or h < 2: return
        
        data = list(self.values)
        if not data: return 

        raw_min = min(data)
        raw_max = max(data)
        curr_min = raw_min - 1
        curr_max = raw_max + 1
        
        if (curr_max - curr_min) % 2 != 0: curr_max += 1
        if curr_min < 0: curr_min = 0
        if curr_max > self.MAX_ADC: curr_max = self.MAX_ADC
        if curr_max <= curr_min: curr_max = curr_min + 2

        colors = _get_graph_colors()

        if not self.is_active:
            colors["line"] = "#444444" 
            colors["text"] = "#555555" 
            colors["grid"] = "#222222" 
            colors["adc_pos"] = "#333333"
            colors["adc_neg"] = "#333333"

        self.configure(bg=colors["bg"])

        left, right, top, bottom = 50, 5, 5, 10
        plot_w = w - left - right
        plot_h = h - top - bottom

        grid_changed = (curr_min != self._prev_min or 
                        curr_max != self._prev_max or 
                        w != self._prev_w or 
                        h != self._prev_h)

        if grid_changed:
            self.delete("grid_tag") 
            
            grid_col = colors["grid"]
            for i in range(1, 5):
                x = left + plot_w * i / 5
                self.create_line(x, top, x, top + plot_h, fill=grid_col, tags="grid_tag")

            ticks = [curr_max, (curr_max + curr_min) / 2.0, curr_min]
            for val in ticks:
                y_raw = self._y_to_px(val, curr_min, curr_max, top, plot_h)
                self.create_line(left, y_raw, left + plot_w, y_raw, fill=grid_col, tags="grid_tag")

                if self.display_mode == "voltage":
                    txt = f"{val * 3.3 / self.MAX_ADC:.2f}V"
                else:
                    txt = f"{int(round(val))}"
                
                self.create_text(
                    left - 4, y_raw,
                    text=txt, anchor="e", fill=colors["text"],
                    font=("Segoe UI", 9), tags="grid_tag"
                )
            
            self._prev_min = curr_min
            self._prev_max = curr_max
            self._prev_w = w
            self._prev_h = h

        # --- DISEGNO LINEA PRINCIPALE ---
        points = []
        n_vals = len(data)
        denom = max(1, n_vals - 1)
        
        for i, v in enumerate(data):
            points.append(left + plot_w * (i / denom))
            if v < curr_min: v = curr_min
            elif v > curr_max: v = curr_max
            frac = (v - curr_min) / (curr_max - curr_min)
            points.append(top + plot_h * (1.0 - frac))

        if self.line_id:
            self.coords(self.line_id, *points)
            self.itemconfigure(self.line_id, fill=colors["line"]) 
        else:
            self.line_id = self.create_line(points, fill=colors["line"], width=1.5, tags="line_tag")

        # --- DISEGNO LINEE ADC ---
        if self.show_adcs and len(self.adc_pos_values) > 0:
            pos_data = list(self.adc_pos_values)
            neg_data = list(self.adc_neg_values)
            
            pos_points = []
            neg_points = []
            
            for i in range(len(pos_data)):
                x = left + plot_w * (i / denom)
                vp = max(0, min(255, pos_data[i]))
                vn = max(0, min(255, neg_data[i]))
                pos_points.extend([x, top + plot_h * (1.0 - (vp / 255.0))])
                neg_points.extend([x, top + plot_h * (1.0 - (vn / 255.0))])

            if len(pos_points) >= 4:
                if self.adc_pos_line_id:
                    self.coords(self.adc_pos_line_id, *pos_points)
                    self.itemconfigure(self.adc_pos_line_id, fill=colors.get("adc_pos"), state="normal")
                else:
                    self.adc_pos_line_id = self.create_line(pos_points, fill=colors.get("adc_pos"), width=1.5, tags="adc_line")

            if len(neg_points) >= 4:
                if self.adc_neg_line_id:
                    self.coords(self.adc_neg_line_id, *neg_points)
                    self.itemconfigure(self.adc_neg_line_id, fill=colors.get("adc_neg"), state="normal")
                else:
                    self.adc_neg_line_id = self.create_line(neg_points, fill=colors.get("adc_neg"), width=1.5, dash=(2, 2), tags="adc_line")
        else:
            if self.adc_pos_line_id: self.itemconfigure(self.adc_pos_line_id, state="hidden")
            if self.adc_neg_line_id: self.itemconfigure(self.adc_neg_line_id, state="hidden")

        # La linea blu deve stare sempre sopra
        if self.line_id:
            self.tag_raise(self.line_id)


# -------------------------------------------------------------------------
#                        GLOBAL GRAPH (Custom)
# -------------------------------------------------------------------------

class GlobalGraph(TimeSeriesGraph):
    """Come TimeSeriesGraph ma con autoscale diverso."""
    
    def redraw(self, force=False):
        now = time.perf_counter()
        if (not force) and (now - self._last_draw_time) < self._min_draw_interval: return
        self._last_draw_time = now

        try: w, h = self.winfo_width(), self.winfo_height()
        except tk.TclError: return
        if w < 2 or h < 2: return

        data = list(self.values)
        if not data: return

        raw_max = max(data)
        curr_min = 0
        curr_max = 10 if raw_max <= 0 else raw_max + (raw_max * 0.1)
        if curr_max <= curr_min: curr_max = curr_min + 1

        colors = _get_graph_colors()
        self.configure(bg=colors["bg"])
        
        left, right, top, bottom = 55, 10, 10, 10
        plot_w = w - left - right
        plot_h = h - top - bottom

        grid_changed = (curr_max != self._prev_max or w != self._prev_w or h != self._prev_h)
        
        if grid_changed:
            self.delete("grid_tag")
            grid_col = colors["grid"]
            
            span = curr_max - curr_min
            step = max(1, math.ceil(span / 5))
            val = int(math.floor(curr_min))
            safe = 0
            while val <= curr_max and safe < 50:
                y_raw = self._y_to_px(val, curr_min, curr_max, top, plot_h)
                self.create_line(left, y_raw, left + plot_w, y_raw, fill=grid_col, tags="grid_tag")
                
                self.create_text(
                    left-5, y_raw, 
                    text=str(int(val)), anchor="e", fill=colors["text"], 
                    font=("Arial", 10), tags="grid_tag"
                )
                val += step
                safe += 1

            for i in range(1, 6):
                x = left + plot_w * (i / 6)
                self.create_line(x, top, x, top + plot_h, fill=grid_col, tags="grid_tag")

            self._prev_max = curr_max
            self._prev_w = w
            self._prev_h = h

        points = []
        denom = max(1, len(data) - 1)
        for i, v in enumerate(data):
            points.append(left + plot_w * (i / denom))
            if v < curr_min: v = curr_min
            elif v > curr_max: v = curr_max
            frac = (v - curr_min) / (curr_max - curr_min)
            points.append(top + plot_h * (1.0 - frac))

        if len(points) < 4: return

        if self.line_id:
            self.coords(self.line_id, *points)
            self.itemconfigure(self.line_id, fill=colors["line"])
        else:
            self.line_id = self.create_line(points, fill=colors["line"], width=2, smooth=True, tags="line_tag")

        # --- DISEGNO LINEE ADC ANCHE SUL GLOBALE ---
        if self.show_adcs and len(self.adc_pos_values) > 0:
            pos_data = list(self.adc_pos_values)
            neg_data = list(self.adc_neg_values)
            
            pos_points = []
            neg_points = []
            
            for i in range(len(pos_data)):
                x = left + plot_w * (i / denom)
                vp = max(0, min(255, pos_data[i]))
                vn = max(0, min(255, neg_data[i]))
                pos_points.extend([x, top + plot_h * (1.0 - (vp / 255.0))])
                neg_points.extend([x, top + plot_h * (1.0 - (vn / 255.0))])

            if len(pos_points) >= 4:
                if self.adc_pos_line_id:
                    self.coords(self.adc_pos_line_id, *pos_points)
                    self.itemconfigure(self.adc_pos_line_id, fill=colors.get("adc_pos"), state="normal")
                else:
                    self.adc_pos_line_id = self.create_line(pos_points, fill=colors.get("adc_pos"), width=1.5, tags="adc_line")

            if len(neg_points) >= 4:
                if self.adc_neg_line_id:
                    self.coords(self.adc_neg_line_id, *neg_points)
                    self.itemconfigure(self.adc_neg_line_id, fill=colors.get("adc_neg"), state="normal")
                else:
                    self.adc_neg_line_id = self.create_line(neg_points, fill=colors.get("adc_neg"), width=1.5, dash=(2,2), tags="adc_line")
        else:
            if self.adc_pos_line_id: self.itemconfigure(self.adc_pos_line_id, state="hidden")
            if self.adc_neg_line_id: self.itemconfigure(self.adc_neg_line_id, state="hidden")

        if self.line_id:
            self.tag_raise(self.line_id)


# -------------------------------------------------------------------------
#                            CHANNEL PREVIEW
# -------------------------------------------------------------------------

class ChannelPreview(ctk.CTkFrame):
    def __init__(self, master, channel_id: int, *args, click_callback=None, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.channel_id = channel_id
        self._click_callback = click_callback
        self.show_adcs_flag = False

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        # Colonna 0 per il grafico, Colonna 1 per le label ADC a destra
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0) 

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="we", padx=6, pady=(2, 1))
        
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        self.ch_label = ctk.CTkLabel(header, text=f"CH {channel_id}", font=ctk.CTkFont(size=12, weight="bold"), anchor="w")
        self.ch_label.grid(row=0, column=0, sticky="w")

        self.particles_label = ctk.CTkLabel(header, text="Pt: 0", font=ctk.CTkFont(size=10), anchor="e")
        self.particles_label.grid(row=0, column=1, sticky="e", padx=(4, 0))

        # Il grafico principale
        self.graph = TimeSeriesGraph(self, max_points=50, highlightthickness=0, height=30)
        self.graph.grid(row=1, column=0, sticky="nsew", padx=(6, 2), pady=(0, 2))

        # Frame dedicato ai valori numerici dell'ADC, posto a DESTRA del grafico
        self.adc_frame = ctk.CTkFrame(self, fg_color="transparent", width=25)
        self.adc_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 6), pady=(0, 2))
        self.adc_frame.grid_rowconfigure(0, weight=1)
        self.adc_frame.grid_rowconfigure(1, weight=1)
        self.adc_frame.grid_columnconfigure(0, weight=1)

        # Label ADC Positivo (in alto, grigio chiaro)
        self.adc_pos_lbl = ctk.CTkLabel(self.adc_frame, text="", font=ctk.CTkFont(size=9, weight="bold"), text_color=("#a0a0a0", "#b0b0b0"))
        self.adc_pos_lbl.grid(row=0, column=0, sticky="s", pady=(0, 1))

        # Label ADC Negativo (in basso, grigio scuro)
        self.adc_neg_lbl = ctk.CTkLabel(self.adc_frame, text="", font=ctk.CTkFont(size=9, weight="bold"), text_color=("#808080", "#707070"))
        self.adc_neg_lbl.grid(row=1, column=0, sticky="n", pady=(1, 0))

        if self._click_callback:
            self._make_clickable(self)
            self._set_hand_cursor(self)

    def _make_clickable(self, widget):
        widget.bind("<Button-1>", self._on_click, add="+")
        for child in widget.winfo_children():
            self._make_clickable(child)

    def _set_hand_cursor(self, widget):
        try: widget.configure(cursor="hand2")
        except tk.TclError: pass
        for child in widget.winfo_children():
            self._set_hand_cursor(child)

    def _on_click(self, event):
        if self._click_callback: self._click_callback(self.channel_id)

    def update_from_value(self, value: int, adc_pos=None, adc_neg=None):
        self.graph.add_value(value, adc_pos=adc_pos, adc_neg=adc_neg)
        
        # Scrive i numeri a destra del grafico solo se lo switch è attivo
        if self.show_adcs_flag:
            p = adc_pos if adc_pos is not None else 0
            n = adc_neg if adc_neg is not None else 0
            self.adc_pos_lbl.configure(text=f"{p}")
            self.adc_neg_lbl.configure(text=f"{n}")

    def add_value(self, value: int):
        self.update_from_value(value)

    def set_display_mode(self, mode: str):
        if hasattr(self, "graph"): self.graph.set_display_mode(mode)

    def set_particles(self, particles: int):
        self.particles_label.configure(text=f"Pt: {particles}")

    def set_active_state(self, is_active: bool):
        if is_active:
            text_col = "#cccccc" if ctk.get_appearance_mode() == "Dark" else "black"
            self.ch_label.configure(text_color=text_col)
            self.particles_label.configure(text_color=text_col)
        else:
            self.ch_label.configure(text_color="#444444")
            self.particles_label.configure(text_color="#444444")
            
        if hasattr(self, "graph"):
            self.graph.set_active_state(is_active)
            
    def set_show_adcs(self, state: bool):
        self.show_adcs_flag = state
        if hasattr(self, "graph"):
            self.graph.set_show_adcs(state)
            
        if state:
            self.adc_pos_lbl.configure(text="-")
            self.adc_neg_lbl.configure(text="-")
        else:
            self.adc_pos_lbl.configure(text="")
            self.adc_neg_lbl.configure(text="")


# -------------------------------------------------------------------------
#                            CHANNEL WINDOW
# -------------------------------------------------------------------------

class ChannelWindow(ctk.CTkToplevel):
    def __init__(self, master, channel_id: int, history=None, initial_particles=None):
        super().__init__(master)
        self.title(f"Channel {channel_id}")
        self.geometry("650x400")
        self.minsize(500, 320)
        self.channel_id = channel_id

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=0)
        main_frame.grid_columnconfigure(1, weight=1)

        left = ctk.CTkFrame(main_frame)
        left.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)
        
        ctk.CTkLabel(left, text=f"Channel {channel_id}", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(0, 10))
        
        self.value_label = ctk.CTkLabel(left, text="0" if initial_particles is None else str(initial_particles), font=ctk.CTkFont(size=40, weight="bold"))
        self.value_label.pack(anchor="w", pady=(0, 15))

        self.param_labels = {}
        for name in ["Particle Count", "Events / s", "Noise level"]:
            l = ctk.CTkLabel(left, text=f"{name}: ---", font=ctk.CTkFont(size=13))
            l.pack(anchor="w", pady=2)
            self.param_labels[name] = l

        if initial_particles is not None:
            self.param_labels["Particle Count"].configure(text=f"Particle Count: {initial_particles}")

        right = ctk.CTkFrame(main_frame)
        right.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.graph = TimeSeriesGraph(right, max_points=50, highlightthickness=0)
        self.graph.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        if history:
            self.graph.values.extend(history)
            self.graph.adc_pos_values.extend([0] * len(history))
            self.graph.adc_neg_values.extend([0] * len(history))
            self.graph.redraw(force=True)

    def update_from_value(self, adc_value: int, particles=None, adc_pos=None, adc_neg=None):
        self.graph.add_value(adc_value, adc_pos=adc_pos, adc_neg=adc_neg)
        if particles is not None:
            self.value_label.configure(text=str(particles))
            self.param_labels["Particle Count"].configure(text=f"Particle Count: {particles}")

    def set_show_adcs(self, state: bool):
        if hasattr(self, "graph"):
            self.graph.set_show_adcs(state)