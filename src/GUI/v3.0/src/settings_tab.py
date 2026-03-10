import customtkinter as ctk
import json
import os

class SettingsTab(ctk.CTkFrame):
    """
    Tab 'Dashboard' (Settings):
    1. Material Database (O<num>) -> PRIMA RIGA
    2. DUST Clock (K5/K20/K40) | Channel Read Mode (MM/MA) | Averaging Window (V<num>) -> SECONDA RIGA
    3. Display Settings (Refresh, Appearance) -> TERZA RIGA
    """

    def __init__(self, master, controller=None):
        super().__init__(master)

        # controller (App) usato per chiamare _bt_send_command(...)
        self.controller = controller

        # Font per le descrizioni
        self._desc_font = ctk.CTkFont(size=11, slant="italic")
        
        # Percorso del file database materiali
        self.db_path = os.path.join(os.path.dirname(__file__), "materials.json")
        self.materials_data = {}

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Frame contenitore principale
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        content.grid_columnconfigure(0, weight=1)
        
        # Layout righe AGGIORNATO:
        # 0: Material Database (Spostato qui)
        # 1: Settings Hardware (Clock, Read Mode, Average)
        # 2: Display Settings (Refresh, Appearance)
        content.grid_rowconfigure(0, weight=0)
        content.grid_rowconfigure(1, weight=0)
        content.grid_rowconfigure(2, weight=0)
        content.grid_rowconfigure(3, weight=1) # filler

        # ==================================================================
        # 1) RIGA MATERIALI (Database) - ORA IN CIMA
        # ==================================================================
        mat_frame = self._create_card(content)
        mat_frame.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        mat_frame.grid_columnconfigure(1, weight=1)

        # Titolo e Icona (simulata con testo)
        ctk.CTkLabel(mat_frame, text="🧪 Material Configuration", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=20, pady=15, sticky="w")

        # Selezione Materiale (ComboBox agisce da ricerca)
        self.mat_combo = ctk.CTkComboBox(
            mat_frame,
            width=250,
            values=["Loading..."],
            command=self._on_material_selected
        )
        self.mat_combo.grid(row=0, column=1, padx=10, pady=15, sticky="ew")

        # Label Descrittiva / Valore Corrente
        self.lbl_mat_info = ctk.CTkLabel(mat_frame, text="Select a material to configure threshold.", text_color="gray")
        self.lbl_mat_info.grid(row=1, column=0, columnspan=2, padx=20, pady=(0, 5), sticky="w")
        
        # Valore attivo
        self.lbl_mat_value = ctk.CTkLabel(mat_frame, text="Offset: ---", font=ctk.CTkFont(weight="bold"))
        self.lbl_mat_value.grid(row=1, column=2, padx=20, pady=(0, 5), sticky="e")

        # Bottone Reload DB
        reload_btn = ctk.CTkButton(
            mat_frame, 
            text="Reload DB", 
            width=80, 
            fg_color="transparent", 
            border_width=1, 
            text_color=("gray10", "gray90"),
            command=self._load_materials_db
        )
        reload_btn.grid(row=0, column=2, padx=20, pady=15, sticky="e")
        

        # ==================================================================
        # 2) RIGA HARDWARE: Clock / Read Mode / Averaging - ORA SOTTO
        # ==================================================================
        hw_frame = ctk.CTkFrame(content, fg_color="transparent")
        hw_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        hw_frame.grid_columnconfigure(0, weight=1)
        hw_frame.grid_columnconfigure(1, weight=1)
        hw_frame.grid_columnconfigure(2, weight=1)
        hw_frame.grid_columnconfigure(3, weight=1)

        # --- Card Dust Clock ---
        clock_card = self._create_card(hw_frame)
        clock_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        ctk.CTkLabel(clock_card, text="DUST Clock", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5), padx=15, anchor="w")
        
        self.clock_var = ctk.StringVar(value="200")
        for val in ["50", "200", "400"]:
            ctk.CTkRadioButton(clock_card, text=f"{val} kHz", value=val, variable=self.clock_var, command=self._on_clock_changed).pack(anchor="w", padx=20, pady=2)
        
        ctk.CTkLabel(clock_card, text="Sensor clock frequency.", font=self._desc_font, text_color="gray").pack(pady=(5, 10), padx=15, anchor="w")

        # --- Card Channel Mode ---
        read_card = self._create_card(hw_frame)
        read_card.grid(row=0, column=1, sticky="nsew", padx=5)
        
        ctk.CTkLabel(read_card, text="Read Mode", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5), padx=15, anchor="center")
        
        mode_inner = ctk.CTkFrame(read_card, fg_color="transparent")
        mode_inner.pack(pady=2)
        ctk.CTkLabel(mode_inner, text="Manual").pack(side="left", padx=5)
        self.read_auto_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(mode_inner, text="Auto", variable=self.read_auto_var, command=self._on_read_mode_changed).pack(side="left", padx=5)
        
        # --- NUOVO: Selettore canale manuale (mostrato sotto lo switch) ---
        self.manual_ch_frame = ctk.CTkFrame(read_card, fg_color="transparent")
        self.manual_ch_frame.pack(pady=(2, 5))

        ctk.CTkLabel(self.manual_ch_frame, text="CH:", font=self._desc_font).pack(side="left", padx=(0, 2))
        self.manual_ch_value = ctk.IntVar(value=1)
        self.manual_ch_entry = ctk.CTkEntry(self.manual_ch_frame, width=40, textvariable=self.manual_ch_value, justify="center")
        self.manual_ch_entry.pack(side="left", padx=2)
        self.manual_ch_entry.bind("<Return>", self._on_manual_ch_commit)

        ch_btn_frame = ctk.CTkFrame(self.manual_ch_frame, fg_color="transparent")
        ch_btn_frame.pack(side="left")
        ctk.CTkButton(ch_btn_frame, text="▲", width=25, height=20, command=self._on_manual_ch_inc).pack(pady=1)
        ctk.CTkButton(ch_btn_frame, text="▼", width=25, height=20, command=self._on_manual_ch_dec).pack(pady=1)
        
        # Inizializza lo stato dell'UI (abilitato/disabilitato)
        self._update_manual_ch_ui()

        # --- NUOVA CARD: PWM Frequency ---
        pwm_card = self._create_card(hw_frame)
        pwm_card.grid(row=0, column=2, sticky="nsew", padx=5)
        
        ctk.CTkLabel(pwm_card, text="PWM Freq", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5), padx=15)
        
        pwm_inner = ctk.CTkFrame(pwm_card, fg_color="transparent")
        pwm_inner.pack(pady=5)
        
        self.pwm_value = ctk.IntVar(value=4)
        self.pwm_entry = ctk.CTkEntry(pwm_inner, width=50, textvariable=self.pwm_value, justify="center")
        self.pwm_entry.pack(side="left", padx=5)
        self.pwm_entry.bind("<Return>", self._on_pwm_entry_commit)
        
        ctk.CTkLabel(pwm_inner, text="kHz", font=self._desc_font).pack(side="left", padx=2)
        
        pwm_btn_frame = ctk.CTkFrame(pwm_inner, fg_color="transparent")
        pwm_btn_frame.pack(side="left")
        ctk.CTkButton(pwm_btn_frame, text="▲", width=25, height=20, command=self._on_pwm_inc).pack(pady=1)
        ctk.CTkButton(pwm_btn_frame, text="▼", width=25, height=20, command=self._on_pwm_dec).pack(pady=1)
        
        ctk.CTkLabel(pwm_card, text="Auto mode toggle rate.", font=self._desc_font, text_color="gray").pack(pady=(5, 10), padx=15)

        # --- Card Averaging ---
        avg_card = self._create_card(hw_frame)
        avg_card.grid(row=0, column=3, sticky="nsew", padx=(5, 0))
        
        ctk.CTkLabel(avg_card, text="Avg Window", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5), padx=15)
        
        avg_inner = ctk.CTkFrame(avg_card, fg_color="transparent")
        avg_inner.pack(pady=5)
        
        self.v_value = ctk.IntVar(value=4)
        self.v_entry = ctk.CTkEntry(avg_inner, width=50, textvariable=self.v_value, justify="center")
        self.v_entry.pack(side="left", padx=5)
        self.v_entry.bind("<Return>", self._on_v_entry_commit)
        
        btn_frame = ctk.CTkFrame(avg_inner, fg_color="transparent")
        btn_frame.pack(side="left")
        ctk.CTkButton(btn_frame, text="▲", width=25, height=20, command=self._on_v_inc).pack(pady=1)
        ctk.CTkButton(btn_frame, text="▼", width=25, height=20, command=self._on_v_dec).pack(pady=1)
        
        ctk.CTkLabel(avg_card, text="Moving average samples.", font=self._desc_font, text_color="gray").pack(pady=(5, 10), padx=15)


        # ==================================================================
        # 3) RIGA DISPLAY & SYSTEM
        # ==================================================================
        sys_frame = self._create_card(content)
        sys_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        
        sys_frame.grid_columnconfigure(0, weight=1)
        sys_frame.grid_columnconfigure(1, weight=1)
        sys_frame.grid_columnconfigure(2, weight=1)

        # Refresh Rate
        rf_frame = ctk.CTkFrame(sys_frame, fg_color="transparent")
        rf_frame.grid(row=0, column=0, padx=20, pady=15)
        ctk.CTkLabel(rf_frame, text="Refresh Rate:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        self.refresh_option = ctk.CTkOptionMenu(
            rf_frame, values=["10 Hz", "20 Hz", "30 Hz", "40 Hz", "50 Hz", "60 Hz"], width=90, command=self._on_refresh_changed
        )
        self.refresh_option.pack(side="left", padx=5)
        self.refresh_option.set("20 Hz") 
        self._on_refresh_changed("20 Hz")
        
        # Appearance
        app_frame = ctk.CTkFrame(sys_frame, fg_color="transparent")
        app_frame.grid(row=0, column=2, padx=20, pady=15)
        ctk.CTkLabel(app_frame, text="Theme:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        self.appearance_option = ctk.CTkOptionMenu(
            app_frame, values=["Dark", "Light", "System"], width=90, command=self._on_appearance_changed
        )
        self.appearance_option.pack(side="left", padx=5)
        self.appearance_option.set(ctk.get_appearance_mode())
        
        # --- CARICA DB DOPO AVER CREATO LA UI ---
        self._load_materials_db()


    def _create_card(self, parent):
        """Helper per creare frame con stile 'Card' coerente."""
        # Colore adattivo
        color = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#ffffff"
        return ctk.CTkFrame(parent, fg_color=color, corner_radius=6)

    # ====================================================================== #
    # LOGICA MATERIALI
    # ====================================================================== #
    
    def _load_materials_db(self):
        """Carica il file JSON e popola la ComboBox."""
        if not os.path.exists(self.db_path):
            self.materials_data = {}
            self.mat_combo.configure(values=["DB Not Found"])
            self.lbl_mat_info.configure(text=f"Error: {self.db_path} not found.")
            return

        try:
            with open(self.db_path, "r") as f:
                self.materials_data = json.load(f)
            
            names = list(self.materials_data.keys())
            if names:
                self.mat_combo.configure(values=names)
                self.mat_combo.set("Select Material...")
                self.lbl_mat_info.configure(text="Database loaded successfully.")
            else:
                self.mat_combo.configure(values=["Empty DB"])
        except Exception as e:
            self.lbl_mat_info.configure(text=f"JSON Error: {str(e)}")

    def _on_material_selected(self, selection):
        if selection not in self.materials_data:
            return

        mat_info = self.materials_data[selection]
        
        # Recupera dati
        offset_val = mat_info.get("dust_thresh_offset", 0)
        desc = mat_info.get("description", "")
        
        # NUOVO: Lettura parametri Power Law (default ai valori della tua tesi se non presenti)
        calib_a = mat_info.get("calib_a", 0.264)
        calib_b = mat_info.get("calib_b", 0.553)

        # Aggiorna UI
        self.lbl_mat_info.configure(text=desc)
        self.lbl_mat_value.configure(text=f"Offset: {offset_val}")

        # Invia i parametri all'istogramma
        if hasattr(self.controller, "set_material_calibration"):
            self.controller.set_material_calibration(calib_a, calib_b)

        # Invia comando al micro
        cmd_str = f"O{offset_val}"
        self._send_bt(cmd_str.encode("ascii"))
        
        print(f"[Dashboard] Material selected: {selection}, Sent: {cmd_str}")


    # ====================================================================== #
    # LOGICA HARDWARE (Legacy)
    # ====================================================================== #
    
    def _send_bt(self, payload: bytes):
        if self.controller is not None and hasattr(self.controller, "_bt_send_command"):
            try:
                self.controller._bt_send_command(payload)
            except Exception:
                pass

    def _on_clock_changed(self):
        val = self.clock_var.get()
        if val == "50": self._send_bt(b"K5")
        elif val == "200": self._send_bt(b"K20")
        elif val == "400": self._send_bt(b"K40")

    def _on_read_mode_changed(self):
        if self.read_auto_var.get(): 
            self._send_bt(b"MA")
        else: 
            self._send_bt(b"MM")
            self._send_manual_ch_command() # Invia il canale non appena entri in manuale
            
        self._update_manual_ch_ui()

    def _update_manual_ch_ui(self):
        # Disabilita il campo testo se siamo in "Auto" (read_auto_var == True nel tuo caso)
        state = "disabled" if self.read_auto_var.get() else "normal"
        self.manual_ch_entry.configure(state=state)

    # ====================================================================== #
    # LOGICA CANALE MANUALE (1 - 32)
    # ====================================================================== #
    
    def _on_manual_ch_inc(self):
        if not self.read_auto_var.get(): # Permesso solo in Manual
            self.manual_ch_value.set(self._clamp_ch(self.manual_ch_value.get() + 1))
            self._send_manual_ch_command()

    def _on_manual_ch_dec(self):
        if not self.read_auto_var.get():
            self.manual_ch_value.set(self._clamp_ch(self.manual_ch_value.get() - 1))
            self._send_manual_ch_command()

    def _on_manual_ch_commit(self, event=None):
        if not self.read_auto_var.get():
            try:
                val = int(self.manual_ch_entry.get())
                self.manual_ch_value.set(self._clamp_ch(val))
                self._send_manual_ch_command()
            except ValueError:
                pass

    def _clamp_ch(self, value):
        return max(1, min(32, value))

    def _send_manual_ch_command(self):
        # Invia il comando 'N' + numero canale (es: N5)
        self._send_bt(f"N{self.manual_ch_value.get()}".encode("ascii"))

    def _on_v_inc(self):
        self.v_value.set(self._clamp_v(self.v_value.get() + 1))
        self._send_v_command()

    def _on_v_dec(self):
        self.v_value.set(self._clamp_v(self.v_value.get() - 1))
        self._send_v_command()

    def _on_v_entry_commit(self, event=None):
        try:
            val = int(self.v_entry.get())
            self.v_value.set(self._clamp_v(val))
            self._send_v_command()
        except ValueError:
            pass

    def _clamp_v(self, value):
        return max(1, min(99, value))

    def _send_v_command(self):
        self._send_bt(f"V{self.v_value.get()}".encode("ascii"))

# ====================================================================== #
    # LOGICA PWM FREQUENCY
    # ====================================================================== #
    
    def _on_pwm_inc(self):
        self.pwm_value.set(self._clamp_pwm(self.pwm_value.get() + 1))
        self._send_pwm_command()

    def _on_pwm_dec(self):
        self.pwm_value.set(self._clamp_pwm(self.pwm_value.get() - 1))
        self._send_pwm_command()

    def _on_pwm_entry_commit(self, event=None):
        try:
            val = int(self.pwm_entry.get())
            self.pwm_value.set(self._clamp_pwm(val))
            self._send_pwm_command()
        except ValueError:
            pass

    def _clamp_pwm(self, value):
        return max(1, min(500, value)) # Clamp tra 1 kHz e 500 kHz

    def _send_pwm_command(self):
        # Invia la stringa "F<valore>"
        self._send_bt(f"F{self.pwm_value.get()}".encode("ascii"))

    # ====================================================================== #
    # SYSTEM
    # ====================================================================== #

    def _on_refresh_changed(self, selection: str):
        if self.controller is None: return
        try:
            hz = float(selection.replace("Hz", "").strip())
            if hz > 0:
                interval = 1.0 / hz
                if hasattr(self.controller, "set_refresh_interval"):
                    self.controller.set_refresh_interval(interval)
        except Exception: pass

    def _on_appearance_changed(self, mode: str):
        ctk.set_appearance_mode(mode)
        # Refresh cards color
        self._refresh_ui_colors()
        if self.controller is not None and hasattr(self.controller, "on_theme_changed"):
            try: self.controller.on_theme_changed()
            except Exception: pass

    def _refresh_ui_colors(self):
        color = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#ffffff"
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                # Aggiorna ricorsivamente le card che abbiamo creato
                for sub in child.winfo_children():
                    if isinstance(sub, ctk.CTkFrame) and sub.cget("corner_radius") == 6:
                         sub.configure(fg_color=color)