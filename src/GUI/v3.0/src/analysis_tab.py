import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import FuncFormatter, MaxNLocator
import random
import datetime
import os
import numpy as np
from tkinter import filedialog, messagebox

# --- COSTANTI ---
Y_MIN_PAD = -100
Y_MAX_PAD_BIT = 32768
Y_MAX_PAD_VOLT = 3.3

# -------------------------------------------------------------------------
#                       FUNZIONI HELPER (Parsing)
# -------------------------------------------------------------------------

def generate_dummy_file(filename="datalog_samples.txt", total_lines=3000):
    start_time = datetime.datetime.now()
    with open(filename, "w") as f:
        samples_per_second = 10 
        for i in range(total_lines):
            line_parts = ["22"] 
            is_spike = (i % 200) < 5 and (i > 50) 
            for _ in range(32):
                if is_spike:
                    val = 0 if (i % 2 == 0) else 32000 
                else:
                    noise = random.randint(-50, 50)
                    val = 15000 + noise
                    val = max(0, min(32768, val))
                msb = (val >> 8) & 0xFF
                lsb = val & 0xFF
                line_parts.append(f"{msb:02X}")
                line_parts.append(f"{lsb:02X}")
            line_parts.append("0A") 
            time_offset = i // samples_per_second
            current_time = start_time + datetime.timedelta(seconds=time_offset)
            for fmt in ["%y", "%m", "%d", "%H", "%M", "%S"]:
                line_parts.append(current_time.strftime(fmt))
            f.write(", ".join(line_parts) + "\n")

# --- PARSER BINARIO (.bin) ---
def _parse_bin_file(filename):
    FRAME_SIZE = 68
    NUM_CHANNELS = 32
    try:
        raw_bytes = np.fromfile(filename, dtype=np.uint8)
    except Exception as e:
        print(f"Errore file: {e}")
        return None

    start_offset = -1
    for i in range(min(len(raw_bytes), 500)): 
        if raw_bytes[i] == 0xAA and (i+1 < len(raw_bytes)) and raw_bytes[i+1] == 0x55:
            start_offset = i
            break     
    if start_offset == -1: return None
        
    aligned_bytes = raw_bytes[start_offset:]
    n_frames = len(aligned_bytes) // FRAME_SIZE
    aligned_bytes = aligned_bytes[:n_frames * FRAME_SIZE]
    frames = aligned_bytes.reshape(n_frames, FRAME_SIZE)
    payload = frames[:, 2:66] 
    
    # QUI LA LOGICA È GIÀ CORRETTA GRAZIE A NUMPY:
    # >i2 = Big-Endian 16-bit Signed Integer
    raw_values = payload.view(dtype='>i2').reshape(n_frames, NUM_CHANNELS)
    # abs() converte i negativi in positivi (es. -32768 -> 32768)
    abs_values = np.abs(raw_values)
    
    data = {}
    for i in range(NUM_CHANNELS):
        ch_id = i + 1
        data[ch_id] = {
            'times': np.arange(n_frames),
            'values': abs_values[:, i]
        }
    return data

# --- PARSER HEX TEXT (.txt) ---
def _parse_hex_txt_log(filename):
    """
    Legge file TXT. Cerca 'AA 55'.
    Converte MSB+LSB in Signed 16-bit e poi in Absolute Value.
    """
    data = {i: {'times': [], 'values': []} for i in range(1, 33)}
    sample_index = 0
    
    try:
        with open(filename, "r") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                
                hex_tokens = line.split()
                # Minimo sindacale: AA 55 + 96 byte dati
                if len(hex_tokens) < 98: 
                    continue
                
                # Cerca sync AA 55
                indices = [i for i, x in enumerate(hex_tokens) if x.upper() == 'AA']
                
                for i in indices:
                    if i + 1 < len(hex_tokens) and hex_tokens[i+1].upper() == '55':
                        start_payload = i + 2
                        if start_payload + 96 <= len(hex_tokens):
                            payload = hex_tokens[start_payload : start_payload + 96]
                            
                            temp_values = []
                            valid_packet = True
                            
                            for ch in range(32):
                                base = ch * 3
                                try:
                                    msb = int(payload[base+1], 16)
                                    lsb = int(payload[base+2], 16)
                                    
                                    # 1. Combina i byte (0 - 65535)
                                    raw_unsigned = (msb << 8) | lsb
                                    
                                    # 2. Converti in Signed 16-bit (Complemento a due)
                                    # Se il bit più significativo (0x8000) è 1, è negativo
                                    if raw_unsigned & 0x8000:
                                        signed_val = raw_unsigned - 0x10000
                                    else:
                                        signed_val = raw_unsigned
                                    
                                    # 3. Valore Assoluto (0 - 32768)
                                    final_val = abs(signed_val)
                                    
                                    temp_values.append(final_val)
                                except ValueError:
                                    valid_packet = False
                                    break
                            
                            if valid_packet:
                                for ch_idx, val in enumerate(temp_values):
                                    ch_id = ch_idx + 1
                                    data[ch_id]['values'].append(val)
                                    data[ch_id]['times'].append(sample_index)
                                sample_index += 1
                                break 

        return data
    except Exception as e:
        print(f"Errore TXT Hex: {e}")
        return None

# -------------------------------------------------------------------------
#                       UTILS GRAFICA
# -------------------------------------------------------------------------

def get_plot_style():
    """Ritorna i colori (bg, fg, line) in base al tema corrente di CTk."""
    mode = ctk.get_appearance_mode().lower()
    
    if mode == "light":
        return {
            "fig_bg": "#f5f5f7",     # Grigio chiarissimo
            "axes_bg": "#ffffff",    # Bianco
            "text": "#222222",       # Scuro
            "line": "#1f6aa5",       # Blu classico
            "grid": "#d0d0d0"        # Grigio chiaro per griglia
        }
    else:  # Dark
        return {
            "fig_bg": "#2b2b2b",     # Grigio scuro (sfondo frame)
            "axes_bg": "#1c1c1c",    # Nero/Grigio (area grafico)
            "text": "#cccccc",       # Grigio chiaro
            "line": "#33b5ff",       # Azzurro Ciano (Theme color)
            "grid": "#333333"        # Grigio scuro per griglia
        }

# -------------------------------------------------------------------------
#                       FINESTRA DI DETTAGLIO
# -------------------------------------------------------------------------

class DetailWindow(ctk.CTkToplevel):
    def __init__(self, parent, channel_id, times, values, display_mode="bit"):
        super().__init__(parent)
        self.title(f"Channel {channel_id} Detail - {display_mode.upper()}")
        self.geometry("900x600")
        
        # Gestione Layout a Griglia
        # Riga 0: Grafico (si espande)
        # Riga 1: Controlli (altezza fissa in basso)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)
        
        self.after(100, self.lift)
        self.after(100, self.focus_force)
        
        self.times = list(times)
        
        if display_mode == "voltage":
            # Conversione 0-32768 -> 0-3.3V
            self.values = [v * 3.3 / 32768.0 for v in values]
            y_label = "Voltage (V)"
            y_max_limit = Y_MAX_PAD_VOLT
        else:
            self.values = list(values)
            y_label = "ADC Value (Bit)"
            y_max_limit = Y_MAX_PAD_BIT

        self.display_mode = display_mode
        self.num_points = len(self.values)
        self.x_indices = range(self.num_points)
        
        style = get_plot_style()
        
        # --- 1. FRAME GRAFICO (Riga 0) ---
        self.plot_frame = ctk.CTkFrame(self)
        self.plot_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        
        self.fig, self.ax = plt.subplots(figsize=(8, 5), dpi=100)
        
        # Applicazione Colori
        self.fig.patch.set_facecolor(style["fig_bg"])
        self.ax.set_facecolor(style["axes_bg"])
        self.ax.tick_params(colors=style["text"], which='both')
        self.ax.xaxis.label.set_color(style["text"])
        self.ax.yaxis.label.set_color(style["text"])
        self.ax.title.set_color(style["text"])
        for spine in self.ax.spines.values():
            spine.set_edgecolor(style["text"])

        self.line, = self.ax.plot(self.x_indices, self.values, color=style["line"], linewidth=1.5)
        
        self.ax.set_title(f"Channel {channel_id}", fontsize=12)
        self.ax.set_ylabel(y_label)
        self.ax.set_xlabel("Sample Index")
        
        self.ax.grid(True, linestyle='-', alpha=0.3, color=style["grid"])
        
        def format_date(x, pos=None):
            idx = int(x)
            if 0 <= idx < self.num_points:
                val = self.times[idx]
                if isinstance(val, (int, np.integer, float, np.floating)):
                    return str(val) 
                return val.strftime('%H:%M:%S')
            return ""

        self.ax.xaxis.set_major_formatter(FuncFormatter(format_date))
        self.ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.draw()
        # Nota: dentro il frame usiamo ancora pack per il canvas che deve riempirlo tutto
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
        # --- 2. FRAME CONTROLLI (Riga 1) ---
        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        
        ctk.CTkLabel(self.controls_frame, text="Zoom / Pan:").pack(side="left", padx=10)
        
        self.window_size = max(20, int(self.num_points * 0.1)) 
        
        if self.num_points > 20:
            self.slider = ctk.CTkSlider(
                self.controls_frame, 
                from_=0, 
                to=max(0, self.num_points - self.window_size), 
                number_of_steps=1000,
                command=self.update_plot_view
            )
            self.slider.set(0)
            self.slider.pack(fill="x", expand=True, padx=10, pady=10)
            self.update_plot_view(0)

    def update_plot_view(self, value):
        start_idx = int(value)
        end_idx = start_idx + self.window_size
        if end_idx >= self.num_points: end_idx = self.num_points - 1
        
        self.ax.set_xlim(start_idx, end_idx)
        
        chunk = self.values[start_idx : end_idx]
        if chunk:
            y_min = min(chunk)
            y_max = max(chunk)
            margin = (y_max - y_min) * 0.1 if y_max != y_min else (100 if self.display_mode == "bit" else 0.1)
            
            global_min = -100 if self.display_mode == "bit" else -0.1
            global_max = 33000 if self.display_mode == "bit" else 3.4
            
            final_min = max(global_min, y_min - margin)
            final_max = min(global_max, y_max + margin)
            
            self.ax.set_ylim(final_min, final_max)
        
        self.canvas.draw_idle()

    def update_plot_view(self, value):
        start_idx = int(value)
        end_idx = start_idx + self.window_size
        if end_idx >= self.num_points: end_idx = self.num_points - 1
        
        self.ax.set_xlim(start_idx, end_idx)
        
        chunk = self.values[start_idx : end_idx]
        if chunk:
            y_min = min(chunk)
            y_max = max(chunk)
            margin = (y_max - y_min) * 0.1 if y_max != y_min else (100 if self.display_mode == "bit" else 0.1)
            
            global_min = -100 if self.display_mode == "bit" else -0.1
            global_max = 33000 if self.display_mode == "bit" else 3.4
            
            final_min = max(global_min, y_min - margin)
            final_max = min(global_max, y_max + margin)
            
            self.ax.set_ylim(final_min, final_max)
        
        self.canvas.draw_idle()


# -------------------------------------------------------------------------
#                       TAB ANALISI (Main Class)
# -------------------------------------------------------------------------

class AnalysisTab(ctk.CTkFrame):
    def __init__(self, master, controller=None):
        super().__init__(master)
        self.controller = controller
        self.data = None
        self.display_mode = "bit" 

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0) 
        self.grid_columnconfigure(1, weight=1) 

        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(10, weight=1) 

        lbl_title = ctk.CTkLabel(self.sidebar, text="File Analysis", font=ctk.CTkFont(size=20, weight="bold"))
        lbl_title.grid(row=0, column=0, padx=20, pady=(20, 10))

        # 1. Binary Button
        self.btn_load_bin = ctk.CTkButton(
            self.sidebar, 
            text="Load SD file", 
            command=self.load_bin_dialog
        )
        self.btn_load_bin.grid(row=1, column=0, padx=20, pady=(10, 5))

        # 2. Hex Text Button
        self.btn_load_txt = ctk.CTkButton(
            self.sidebar, 
            text="Load from PC", 
            command=self.load_txt_dialog,
            fg_color="#555555",
            hover_color="#333333"
        )
        self.btn_load_txt.grid(row=2, column=0, padx=20, pady=(5, 10))
        
        self.lbl_filename = ctk.CTkLabel(self.sidebar, text="No file loaded", font=ctk.CTkFont(size=12), text_color="gray")
        self.lbl_filename.grid(row=3, column=0, padx=20, pady=(0, 20))

        ctk.CTkFrame(self.sidebar, height=2, fg_color="gray").grid(row=4, column=0, sticky="ew", padx=20, pady=5)

        lbl_view = ctk.CTkLabel(self.sidebar, text="View Mode:", font=ctk.CTkFont(weight="bold"))
        lbl_view.grid(row=5, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.switch_mode = ctk.CTkSwitch(
            self.sidebar, 
            text="Voltage (V)", 
            command=self._on_mode_switch
        )
        self.switch_mode.grid(row=6, column=0, padx=20, pady=10, sticky="w")

        ctk.CTkFrame(self.sidebar, height=2, fg_color="gray").grid(row=7, column=0, sticky="ew", padx=20, pady=15)

        lbl_analysis = ctk.CTkLabel(self.sidebar, text="Particle Count:", font=ctk.CTkFont(weight="bold"))
        lbl_analysis.grid(row=8, column=0, padx=20, pady=(0, 5), sticky="w")

        params_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        params_frame.grid(row=9, column=0, padx=10, pady=5)
        
        ctk.CTkLabel(params_frame, text="Thresh:").grid(row=0, column=0, padx=5)
        self.thresh_var = ctk.StringVar(value="20")
        self.thresh_entry = ctk.CTkEntry(params_frame, width=60, textvariable=self.thresh_var)
        self.thresh_entry.grid(row=0, column=1, padx=5)

        ctk.CTkLabel(params_frame, text="Step:").grid(row=1, column=0, padx=5, pady=5)
        self.step_var = ctk.StringVar(value="2")
        self.step_entry = ctk.CTkEntry(params_frame, width=60, textvariable=self.step_var)
        self.step_entry.grid(row=1, column=1, padx=5, pady=5)

        self.btn_count = ctk.CTkButton(
            self.sidebar, 
            text="CALCULATE", 
            fg_color="#1f6aa5", 
            command=self.run_particle_count
        )
        self.btn_count.grid(row=10, column=0, padx=20, pady=10)

        self.lbl_result = ctk.CTkLabel(self.sidebar, text="Particles: ---", font=ctk.CTkFont(size=18, weight="bold"))
        self.lbl_result.grid(row=11, column=0, padx=20, pady=10, sticky="n")

        self.btn_gen = ctk.CTkButton(
            self.sidebar, 
            text="Gen. Dummy", 
            fg_color="transparent", 
            border_width=1,
            text_color=("gray10", "gray90"),
            command=self.create_dummy,
            height=20
        )
        self.btn_gen.grid(row=12, column=0, padx=20, pady=20, sticky="s")

        self.right_area = ctk.CTkFrame(self, fg_color="transparent")
        self.right_area.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        self.scroll_frame = ctk.CTkScrollableFrame(self.right_area, label_text="Channels Preview")
        self.scroll_frame.pack(fill="both", expand=True)
        
        self.grid_container = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        self.grid_container.pack(fill="both", expand=True)

        for c in range(4):
            self.grid_container.columnconfigure(c, weight=1)

    def create_dummy(self):
        generate_dummy_file("datalog_samples.txt", total_lines=3000)
        messagebox.showinfo("Info", "Generated: datalog_samples.txt")

    def load_bin_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Select Binary Log File", 
            filetypes=(("Binary Files", "*.bin"), ("All Files", "*.*"))
        )
        self._load_file(file_path, is_bin=True)

    def load_txt_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Select Hex Log File", 
            filetypes=(("Text Files", "*.txt"), ("All Files", "*.*"))
        )
        self._load_file(file_path, is_bin=False)

    def _load_file(self, file_path, is_bin=True):
        if file_path:
            self.lbl_filename.configure(text=f"...{os.path.basename(file_path)[-20:]}")
            self.update() 
            
            if is_bin:
                self.data = _parse_bin_file(file_path)
            else:
                self.data = _parse_hex_txt_log(file_path)
            
            if self.data:
                self.create_thumbnails()
                self.lbl_result.configure(text="Particles: -")
            else:
                messagebox.showerror("Error", "Could not parse file.")
                self.lbl_filename.configure(text="Error loading file")

    def _on_mode_switch(self):
        if self.switch_mode.get() == 1:
            self.display_mode = "voltage"
        else:
            self.display_mode = "bit"
        if self.data:
            self.create_thumbnails()

    def update_theme(self):
        if self.data:
            self.create_thumbnails()

    def run_particle_count(self):
        if not self.data: return
        try:
            threshold_raw = float(self.thresh_var.get())
            step = int(self.step_var.get()) 
            if step < 1: step = 1
        except ValueError:
            messagebox.showerror("Error", "Invalid Threshold or Step")
            return

        total_particles = 0
        for ch_id in range(1, 33):
            if ch_id not in self.data: continue
            raw_values = np.array(self.data[ch_id]['values'], dtype=float)
            if len(raw_values) <= step + 1: continue
            diffs = raw_values[step:] - raw_values[:-step]
            abs_diffs = np.abs(diffs)
            mask1 = abs_diffs[:-1] > threshold_raw
            mask2 = abs_diffs[1:] > threshold_raw
            consecutive_jumps = mask1 & mask2
            count = np.sum(consecutive_jumps)
            total_particles += count
        self.lbl_result.configure(text=f"Particles: {total_particles}")

    def create_thumbnails(self):
        for widget in self.grid_container.winfo_children():
            widget.destroy()
        
        style = get_plot_style()
        plt.rcParams.update({'figure.facecolor': style["axes_bg"], 'axes.facecolor': style["axes_bg"]})

        for i in range(1, 33):
            row = (i - 1) // 4
            col = (i - 1) % 4
            
            times = self.data[i]['times']
            raw_values = self.data[i]['values']
            
            # Setup valori e ticks
            if self.display_mode == "voltage":
                plot_values = raw_values * 3.3 / 32768.0
                y_max_limit = Y_MAX_PAD_VOLT
                y_min_limit = -0.1
                yticks = [0, 0.825, 1.65, 2.475, 3.3]
            else:
                plot_values = raw_values
                y_max_limit = Y_MAX_PAD_BIT
                y_min_limit = Y_MIN_PAD
                yticks = [0, 8192, 16384, 24576, 32768]
            
            num_points = len(plot_values)

            card_color = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#ffffff"
            frame = ctk.CTkFrame(self.grid_container, fg_color=card_color, corner_radius=6)
            frame.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            
            header_text = f"CH {i} [{self.display_mode}]"
            header = ctk.CTkLabel(frame, text=header_text, font=("Segoe UI", 11, "bold"))
            header.pack(side="top", fill="x", pady=(2,0))
            
            if num_points == 0:
                ctk.CTkLabel(frame, text="No Data", text_color="gray").pack(expand=True)
                continue

            fig = plt.Figure(figsize=(2.5, 1.8), dpi=70)
            
            # Margini (Left 0.32 per font size 8)
            fig.subplots_adjust(left=0.32, right=0.95, top=0.95, bottom=0.05)
            
            fig.patch.set_facecolor(style["fig_bg"])
            if ctk.get_appearance_mode() == "Dark":
                 fig.patch.set_facecolor(card_color)

            ax = fig.add_subplot(111)
            ax.set_facecolor(style["axes_bg"])
            
            ax.plot(np.arange(num_points), plot_values, color=style["line"], linewidth=1.2)
            
            ax.set_ylim(y_min_limit, y_max_limit)
            
            # Tick Config
            ax.set_yticks(yticks)
            ax.tick_params(axis='y', which='major', labelsize=12, length=2, pad=1, 
                           colors=style["text"], left=True, labelleft=True)
            ax.tick_params(axis='x', which='both', bottom=False, labelbottom=False)
            
            ax.grid(True, linestyle=':', linewidth=0.5, color=style["grid"], alpha=0.5)
            
            for spine in ax.spines.values():
                spine.set_visible(False)
            
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill="both", expand=True, padx=2, pady=2)
            
            canvas_widget.bind("<Button-1>", lambda event, ch=i: self.open_detail(ch))
            header.bind("<Button-1>", lambda event, ch=i: self.open_detail(ch))
            
            plt.close(fig)

    def open_detail(self, channel_id):
        if not self.data: return
        times = self.data[channel_id]['times']
        values = self.data[channel_id]['values']
        if len(times) > 0:
            DetailWindow(self, channel_id, times, values, display_mode=self.display_mode)