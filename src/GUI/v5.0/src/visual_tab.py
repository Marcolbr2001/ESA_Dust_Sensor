import tkinter as tk
import customtkinter as ctk
from widgets import GlobalGraph

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
class ParticleHistogram(ctk.CTkFrame):
    """
    Widget Istogramma OTTIMIZZATO con assi convertiti.
    X-Axis: Micrometri (10 LSB = 1 um).
    Y-Axis: Quantità particelle (Auto-scaling).
    """
    def __init__(self, master, num_bins=64, max_val=32768, height=150, **kwargs):
        super().__init__(master, height=height, **kwargs)
        self.num_bins = num_bins
        self.max_val = max_val
        
        self.calib_a = 0.264       
        self.calib_b = 0.553       
        self.display_unit = "um"

        self.canvas = tk.Canvas(
            self, 
            bg="#2b2b2b", 
            highlightthickness=0, 
            height=height
        )
        self.canvas.pack(fill="both", expand=True, padx=5, pady=5)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        
        # Ora current_data sarà una lista di contatori, es: [0, 5, 120, 4, ...]
        self.current_bins = [0] * num_bins 
        self.bar_color = "#3B8ED0"
        self.text_color = "#aaaaaa"
        self.grid_color = "#444444"

    # --- NUOVI METODI ---
    def set_calibration_params(self, a: float, b: float):
        self.calib_a = a
        self.calib_b = b
        self.redraw()

    def set_display_unit(self, unit: str):
        self.display_unit = unit
        self.redraw()

    def update_data(self, bins_counts: list):
        """Riceve la lista dei conteggi per colonna."""
        # Se la lunghezza è diversa, adattiamo (sicurezza)
        if len(bins_counts) != self.num_bins:
            return 
        self.current_bins = bins_counts
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        
        if w < 10 or h < 10: return

        # --- MARGINI ---
        margin_bottom = 20  # Spazio per etichette asse X
        margin_left = 40    # Spazio per etichette asse Y
        margin_top = 20     # <--- NUOVO: Spazio sopra per non tagliare l'ultimo numero
        
        # L'area utile per il disegno (grafico vero e proprio)
        graph_w = w - margin_left
        graph_h = h - margin_bottom - margin_top 

        # Coordinata Y della linea di base (asse X)
        base_y = h - margin_bottom

        # 1. Scala Y
        max_count = max(self.current_bins) if self.current_bins else 1
        if max_count == 0: max_count = 1

        # --- DISEGNO ASSE Y (Quantità) ---
        y_steps = [0, max_count // 2, max_count]
        
        for val in y_steps:
            # Calcolo posizione Y
            ratio = val / max_count
            # y_pos parte dal basso (base_y) e sale di (ratio * graph_h)
            y_pos = base_y - (ratio * graph_h)
            
            # Testo
            self.canvas.create_text(
                margin_left - 5, y_pos, 
                text=str(val), 
                fill=self.text_color, 
                font=("Arial", 9), 
                anchor="e" # Allinea a destra verso l'asse
            )
            
            # Linea griglia
            if val > 0:
                self.canvas.create_line(
                    margin_left, y_pos, w, y_pos, 
                    fill=self.grid_color, dash=(2, 4)
                )

        # --- BARRE ---
        bar_width = graph_w / self.num_bins
        
        for i, count in enumerate(self.current_bins):
            if count > 0:
                # Altezza della barra
                bar_height = (count / max_count) * graph_h
                
                x0 = margin_left + (i * bar_width)
                # Il top della barra è la base meno l'altezza
                y0 = base_y - bar_height 
                x1 = margin_left + ((i + 1) * bar_width) - 1 
                y1 = base_y # La base della barra è fissa
                
                self.canvas.create_rectangle(
                    x0, y0, x1, y1, 
                    fill=self.bar_color, 
                    outline=""
                )

        # --- DISEGNO ASSE X (Micrometri o LSB) ---
        num_ticks = 5 
        labels_adc = [int(self.max_val * i / (num_ticks - 1)) for i in range(num_ticks)]
        
        for val_adc in labels_adc:
            x_pos = margin_left + ((val_adc / self.max_val) * graph_w)
            
            # --- LOGICA DELLO SWITCH E POWER LAW ---
            if self.display_unit == "um":
                if val_adc == 0:
                    val_display = 0.0
                else:
                    # Equazione 5.5 della tesi: d = a * LSB^b
                    val_display = self.calib_a * (val_adc ** self.calib_b)
                
                text_str = f"{val_display:.1f}µm"
            else:
                text_str = f"{val_adc} LSB"
            
            anchor = "center"
            if val_adc == 0: 
                x_pos = margin_left + 2; anchor = "w"
            elif val_adc == self.max_val:
                x_pos = w - 2; anchor = "e"
            
            self.canvas.create_text(
                x_pos, h - 8, 
                text=text_str,
                fill=self.text_color, 
                font=("Arial", 9), 
                anchor=anchor
            )
            # Tick
            self.canvas.create_line(
                x_pos, base_y, x_pos, base_y + 3,
                fill=self.grid_color
            )

class VisualTab(ctk.CTkFrame):
    """Tab 'Visual': numero globale, grafico tempo e istogramma."""

    def __init__(self, master, controller):
        super().__init__(master)
        self.controller = controller

        # Layout: Riga 0 (Top) peso 3, Riga 1 (Bottom) peso 1
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # === PARTE SUPERIORE (Row 0) ===
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        top_frame.grid_rowconfigure(0, weight=1)
        top_frame.grid_columnconfigure(0, weight=0)   # info sinistra
        top_frame.grid_columnconfigure(1, weight=1)   # grafico destra

        # --- colonna sinistra ---
        left_frame = ctk.CTkFrame(top_frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(15, 5), pady=15)
        left_frame.grid_columnconfigure(0, weight=1)
        
        left_frame.grid_rowconfigure(0, weight=0)
        left_frame.grid_rowconfigure(1, weight=0)
        left_frame.grid_rowconfigure(2, weight=0) 
        left_frame.grid_rowconfigure(3, weight=1)
        left_frame.grid_rowconfigure(4, weight=0) 

        section_font = ctk.CTkFont(size=20, weight="bold")

        title = ctk.CTkLabel(
            left_frame,
            text="Global Particle Count",
            font=section_font,
        )
        title.grid(row=0, column=0, padx=(10, 10), pady=(10, 10), sticky="w")

        self.global_count_label = ctk.CTkLabel(
            left_frame,
            text="0",
            font=ctk.CTkFont(size=90, weight="bold"),
        )
        self.global_count_label.grid(row=1, column=0, pady=(30, 10), sticky="n")

        # --- parametri sotto il numero ---
        params_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        params_frame.grid(row=2, column=0, sticky="nw", padx=(10, 10), pady=(60, 0))
        params_frame.grid_columnconfigure(0, weight=0) 
        params_frame.grid_columnconfigure(1, weight=1) 

        small_font = ctk.CTkFont(size=13)
        self.param_labels = {}

        row_idx = 0
        for name in ["Particle Density", "Events / s", "Noise level"]:
            lab_name = ctk.CTkLabel(
                params_frame,
                text=f"{name}:",
                font=small_font,
            )
            lab_name.grid(row=row_idx, column=0, sticky="w", pady=(0, 2), padx=(0, 4))

            lab_val = ctk.CTkLabel(
                params_frame,
                text="---",
                font=small_font,
            )
            lab_val.grid(row=row_idx, column=1, sticky="e", pady=(0, 2))
            self.param_labels[name] = lab_val
            row_idx += 1

        # --- controlli Start/Stop ---
        control_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        control_frame.grid(row=4, column=0, pady=(10, 0), sticky="swe")
        control_frame.grid_columnconfigure(0, weight=1)

        ctrl_label = ctk.CTkLabel(
            control_frame,
            text="Acquisition:",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        ctrl_label.grid(row=0, column=0, pady=(0, 5), sticky="n")

        buttons_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        buttons_frame.grid(row=1, column=0, pady=(0, 5), sticky="n")
        buttons_frame.grid_columnconfigure((0, 1), weight=0)

        start_btn = ctk.CTkButton(
            buttons_frame,
            text="▶",
            font=ctk.CTkFont(size=18, weight="bold"),
            width=60,
            command=self._on_start_pressed,
        )
        start_btn.grid(row=0, column=0, padx=6, pady=5)

        stop_btn = ctk.CTkButton(
            buttons_frame,
            text="■",
            font=ctk.CTkFont(size=18, weight="bold"),
            width=60,
            command=self._on_stop_pressed,
        )
        stop_btn.grid(row=0, column=1, padx=6, pady=5)

        # --- colonna destra: grafico temporale ---
        right_frame = ctk.CTkFrame(top_frame)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 10), pady=10)
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        self.global_graph = GlobalGraph(
            right_frame,
            max_points=100,
            highlightthickness=0,
        )
        self.global_graph.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # === PARTE INFERIORE (Row 1 - Istogramma) ===
        bottom_frame = ctk.CTkFrame(self)
        bottom_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        bottom_frame.grid_rowconfigure(0, weight=0) # Header (Title + Switch)
        bottom_frame.grid_rowconfigure(1, weight=1) # Graph
        bottom_frame.grid_columnconfigure(0, weight=1)
        
        # --- HEADER ISTOGRAMMA (Riga invisibile per allineare titolo e tasto) ---
        bottom_header = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        bottom_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(5,0))
        bottom_header.grid_columnconfigure(0, weight=1) # Spinge lo switch tutto a destra
        
        histo_title = ctk.CTkLabel(bottom_header, text="Pulse Height Distribution (Size)", font=ctk.CTkFont(size=12, weight="bold"))
        histo_title.grid(row=0, column=0, sticky="w") # "w" = allineato a sinistra

        # --- TASTO SWITCH ---
        self.unit_switch = ctk.CTkSwitch(
            bottom_header,
            text="Show in µm",
            command=self._on_unit_switch
        )
        self.unit_switch.select() # Lo accendiamo di default
        self.unit_switch.grid(row=0, column=1, sticky="e") # "e" = allineato a destra

        # --- Istogramma ---
        self.histogram = ParticleHistogram(
            bottom_frame, 
            num_bins=64, 
            max_val=32768, # Fondo scala ADC
            height=150
        )
        self.histogram.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))

    def update_global(self, particle_count: int, particle_sizes: list = None):
        """
        Aggiorna GUI.
        """
        # Label Numero
        self.global_count_label.configure(text=str(particle_count))

        # PPM
        ppm_val = particle_count * PPM_FACTOR
        if "Particle Density" in self.param_labels:
            self.param_labels["Particle Density"].configure(text=f"{ppm_val:.2f} PPM")

        # Grafico Linea (Temporale)
        self.global_graph.add_value(particle_count)
        
        # Istogramma (Storico)
        if particle_sizes is not None:
            self.histogram.update_data(particle_sizes)

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