import customtkinter as ctk
import json
import os
from PIL import Image

class SettingsTab(ctk.CTkFrame):
    """
    Tab 'Dashboard' (Settings):
    1. Material Database (O<num>) -> PRIMA RIGA
    2. DUST Clock | Channel Read Mode | Averaging Window -> SECONDA RIGA
    3. DSP Filter Settings (T, W, D, E) -> TERZA RIGA
    4. Channel Masking -> QUARTA RIGA
    5. Display Settings (Refresh, Appearance) -> QUINTA RIGA
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

        # Frame contenitore principale SCROLLABILE
        content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        content.grid(row=0, column=0, sticky="nsew", padx=5, pady=5) 
        content.grid_columnconfigure(0, weight=1)
        
        # Layout righe AGGIORNATO:
        content.grid_rowconfigure(0, weight=0) # Materiali
        content.grid_rowconfigure(1, weight=0) # Hardware
        content.grid_rowconfigure(2, weight=0) # DSP Settings
        content.grid_rowconfigure(3, weight=0) # Channel Masking
        content.grid_rowconfigure(4, weight=0) # Display & System
        content.grid_rowconfigure(5, weight=1) # filler elastico

        # ==================================================================
        # 1) RIGA MATERIALI (50/50 Layout)
        # ==================================================================
        mat_card = self._create_card(content)
        mat_card.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        
        # Dividiamo esattamente a metà (weight=1 per entrambi e uniform per forzare il 50%)
        mat_card.grid_columnconfigure(0, weight=1, uniform="half")
        mat_card.grid_columnconfigure(1, weight=1, uniform="half") 

        # --- SINISTRA: Controlli, Dati Tecnici e Descrizione ---
        self.left_mat = ctk.CTkFrame(mat_card, fg_color="transparent")
        self.left_mat.grid(row=0, column=0, sticky="nsew", padx=20, pady=15)
        
        ctk.CTkLabel(self.left_mat, text="🧪 Material Configuration", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(0, 10))
        
        self.mat_combo = ctk.CTkComboBox(self.left_mat, width=400, values=["Loading..."], command=self._on_material_selected)
        self.mat_combo.pack(anchor="w", pady=(0, 10))
        
        self.lbl_mat_value = ctk.CTkLabel(self.left_mat, text="Digital Threshold: ---", font=ctk.CTkFont(weight="bold"))
        self.lbl_mat_value.pack(anchor="w", pady=(0, 10))

        # Dati Tecnici (Spostati a sinistra, più grandi e in grassetto)
        stats_font = ctk.CTkFont(size=24, weight="bold")
        self.lbl_mat_range = ctk.CTkLabel(self.left_mat, text="Size Range: ---", font=stats_font)
        self.lbl_mat_range.pack(anchor="w", pady=(0, 5))
        
        self.lbl_mat_median = ctk.CTkLabel(self.left_mat, text="Median Size: ---", font=stats_font)
        self.lbl_mat_median.pack(anchor="w", pady=(0, 15))

        # Descrizione (Spostata a sinistra)
        self.lbl_mat_desc = ctk.CTkLabel(self.left_mat, text="...", text_color="gray", justify="left")
        self.lbl_mat_desc.pack(anchor="w", pady=(0, 30))
        
        reload_btn = ctk.CTkButton(self.left_mat, text="Reload DB", width=100, fg_color="transparent", border_width=1, command=self._load_materials_db)
        reload_btn.pack(anchor="w", pady=(0, 20)) # Margine inferiore per separare i blocchi

        # Bind sulla colonna di sinistra per calcolare quando andare a capo
        self.left_mat.bind("<Configure>", self._update_text_wrap)

        # --- DESTRA: Titolo e Immagine (Centrati) ---
        self.right_mat = ctk.CTkFrame(mat_card, fg_color="transparent")
        self.right_mat.grid(row=0, column=1, sticky="nsew", padx=20, pady=15)
        
        # Titolo Materiale (Centrato in alto)
        self.lbl_mat_name = ctk.CTkLabel(self.right_mat, text="Select a material", font=ctk.CTkFont(size=22, weight="bold"))
        self.lbl_mat_name.pack(anchor="center", pady=(0, 15))
        
        # IMMAGINE (Centrata)
        self.lbl_mat_img = ctk.CTkLabel(self.right_mat, text="No Image", text_color="gray")
        self.lbl_mat_img.pack(anchor="center", pady=5) 

        # ==================================================================
        # 2) RIGA HARDWARE: Clock / Read Mode / Averaging
        # ==================================================================
        hw_frame = ctk.CTkFrame(content, fg_color="transparent")
        hw_frame.grid(row=1, column=0, sticky="ew", pady=(0, 15))
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
        self._update_manual_ch_ui()

        # --- Card PWM Frequency ---
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
        self.v_value = ctk.IntVar(value=10)
        self.v_entry = ctk.CTkEntry(avg_inner, width=50, textvariable=self.v_value, justify="center")
        self.v_entry.pack(side="left", padx=5)
        self.v_entry.bind("<Return>", self._on_v_entry_commit)
        
        btn_frame = ctk.CTkFrame(avg_inner, fg_color="transparent")
        btn_frame.pack(side="left")
        ctk.CTkButton(btn_frame, text="▲", width=25, height=20, command=self._on_v_inc).pack(pady=1)
        ctk.CTkButton(btn_frame, text="▼", width=25, height=20, command=self._on_v_dec).pack(pady=1)
        ctk.CTkLabel(avg_card, text="Moving avg samples.", font=self._desc_font, text_color="gray").pack(pady=(5, 10), padx=15)


        # ==================================================================
        # 3) RIGA DSP FILTER SETTINGS 
        # ==================================================================
        dsp_card = self._create_card(content)
        dsp_card.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        dsp_card.grid_columnconfigure(1, weight=1) 

        ctk.CTkLabel(dsp_card, text="🎛️ DSP Filter Settings", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, padx=20, pady=(15, 5), sticky="w")

        params_container = ctk.CTkFrame(dsp_card, fg_color="transparent")
        params_container.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="w")

        # 1. Thresh
        ctk.CTkLabel(params_container, text="Threshold:").grid(row=0, column=0, padx=5, pady=3, sticky="e")
        self.dsp_thresh_var = ctk.StringVar(value="170")
        ctk.CTkEntry(params_container, width=60, textvariable=self.dsp_thresh_var).grid(row=0, column=1, padx=5, pady=3)
        ctk.CTkLabel(params_container, text="Minimum amplitude step (bits) to trigger.", font=self._desc_font, text_color="gray").grid(row=0, column=2, padx=10, sticky="w")

        # 2. Window
        ctk.CTkLabel(params_container, text="Window:").grid(row=1, column=0, padx=5, pady=3, sticky="e")
        self.dsp_window_var = ctk.StringVar(value="50")
        ctk.CTkEntry(params_container, width=60, textvariable=self.dsp_window_var).grid(row=1, column=1, padx=5, pady=3)
        ctk.CTkLabel(params_container, text="Settling time (Auto-doubled x2 for FW).", font=self._desc_font, text_color="gray").grid(row=1, column=2, padx=10, sticky="w")

        # 3. Trig Step
        ctk.CTkLabel(params_container, text="Trig. Step:").grid(row=2, column=0, padx=5, pady=3, sticky="e")
        self.dsp_trig_var = ctk.StringVar(value="3")
        ctk.CTkEntry(params_container, width=60, textvariable=self.dsp_trig_var).grid(row=2, column=1, padx=5, pady=3)
        ctk.CTkLabel(params_container, text="Rise time span (Auto-doubled x2 for FW).", font=self._desc_font, text_color="gray").grid(row=2, column=2, padx=10, sticky="w")

        # 4. Rec Ratio
        ctk.CTkLabel(params_container, text="Rec. Ratio:").grid(row=3, column=0, padx=5, pady=3, sticky="e")
        self.dsp_rec_var = ctk.StringVar(value="0.18")
        ctk.CTkEntry(params_container, width=60, textvariable=self.dsp_rec_var).grid(row=3, column=1, padx=5, pady=3)
        ctk.CTkLabel(params_container, text="Max baseline return allowed (0.18 = 18%).", font=self._desc_font, text_color="gray").grid(row=3, column=2, padx=10, sticky="w")

        self.btn_send_dsp = ctk.CTkButton(
            dsp_card, 
            text="Send DSP to Device", 
            fg_color="#1f6aa5", 
            command=self._send_dsp_params
        )
        self.btn_send_dsp.grid(row=1, column=1, padx=20, pady=15, sticky="se")


        # ==================================================================
        # 4) RIGA CHANNEL MASKING 
        # ==================================================================
        mask_card = self._create_card(content)
        mask_card.grid(row=3, column=0, sticky="ew", pady=(0, 15))
        
        ctk.CTkLabel(mask_card, text="🔌 Channel Masking (Exclude from Global Sum)", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5), padx=15, anchor="w")

        mask_grid = ctk.CTkFrame(mask_card, fg_color="transparent")
        mask_grid.pack(pady=(0, 10), padx=15, fill="x")
        
        for i in range(8):
            mask_grid.grid_columnconfigure(i, weight=1)

        self.ch_vars = []
        for i in range(32):
            var = ctk.BooleanVar(value=True) 
            self.ch_vars.append(var)
            
            cb = ctk.CTkCheckBox(
                mask_grid, text=f"CH {i+1}", variable=var, width=50,
                command=lambda ch=i: self._on_mask_changed(ch)
            )
            cb.grid(row=i // 8, column=i % 8, padx=2, pady=5, sticky="w")

        # ==================================================================
        # 5) RIGA DISPLAY & SYSTEM
        # ==================================================================
        sys_frame = self._create_card(content)
        sys_frame.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        
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
        color = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#ffffff"
        return ctk.CTkFrame(parent, fg_color=color, corner_radius=6)

    # ====================================================================== #
    # LOGICA MATERIALI
    # ====================================================================== #
    
    def _load_materials_db(self):
        if not os.path.exists(self.db_path):
            self.materials_data = {}
            self.mat_combo.configure(values=["DB Not Found"])
            self.lbl_mat_desc.configure(text=f"Error: {self.db_path} not found.") 
            return

        try:
            with open(self.db_path, "r") as f:
                self.materials_data = json.load(f)
            
            names = list(self.materials_data.keys())
            if names:
                self.mat_combo.configure(values=names)
                self.mat_combo.set("Select Material...")
                self.lbl_mat_desc.configure(text="Database loaded successfully.") 
            else:
                self.mat_combo.configure(values=["Empty DB"])
        except Exception as e:
            self.lbl_mat_desc.configure(text=f"JSON Error: {str(e)}") 

    def _update_text_wrap(self, event=None):
        """Aggiorna la larghezza del testo della descrizione in base alla finestra."""
        # Usa la colonna di sinistra (left_mat) come riferimento per la larghezza del wrap
        if hasattr(self, "lbl_mat_desc"):
            new_width = self.left_mat.winfo_width() - 40
            if new_width > 100:
                self.lbl_mat_desc.configure(wraplength=new_width)

    def _on_material_selected(self, selection):
        if selection not in self.materials_data:
            return

        mat_info = self.materials_data[selection]
        
        offset_val = mat_info.get("dust_thresh_offset", 0)
        desc = mat_info.get("text", mat_info.get("description", ""))
        size_range = mat_info.get("particle_size_range", "N/A")
        median = mat_info.get("median_particle_size", "N/A")
        pic_filename = mat_info.get("picture", "")

        # Aggiornamento Testi
        self.lbl_mat_name.configure(text=selection)
        self.lbl_mat_range.configure(text=f"Size Range: {size_range}")
        self.lbl_mat_median.configure(text=f"Median Size: {median}")
        self.lbl_mat_desc.configure(text=desc)
        self.lbl_mat_value.configure(text=f"Digital Threshold: {offset_val}")
        self._update_text_wrap() 

        # Gestione Immagine 
        if pic_filename:
            img_path = os.path.join(os.path.dirname(__file__), "img", pic_filename)
            if os.path.exists(img_path):
                try:
                    pil_img = Image.open(img_path)
                    
                    target_width = 350
                    w_percent = (target_width / float(pil_img.size[0]))
                    target_height = int((float(pil_img.size[1]) * float(w_percent)))
                    
                    self.current_ctk_image = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(target_width, target_height))
                    
                    self.lbl_mat_img.configure(image=self.current_ctk_image, text="")
                except Exception as e:
                    self.current_ctk_image = None
                    self.lbl_mat_img.configure(image=None, text="Error loading image")
            else:
                self.current_ctk_image = None
                self.lbl_mat_img.configure(image=None, text="Image not found")
        else:
            self.current_ctk_image = None
            self.lbl_mat_img.configure(image=None, text="No image available")

        # Invio comandi esistenti...
        if hasattr(self.controller, "set_material_calibration"):
            calib_a = mat_info.get("calib_a", 0.264)
            calib_b = mat_info.get("calib_b", 0.553)
            self.controller.set_material_calibration(calib_a, calib_b)

        self._send_bt(f"O{offset_val}".encode("ascii"))
        
        print(f"[Dashboard] Material selected: {selection}, Sent: O{offset_val}")

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
            self.manual_ch_value.set(1)
            self._send_manual_ch_command()
            
        self._update_manual_ch_ui()

    def _update_manual_ch_ui(self):
        state = "disabled" if self.read_auto_var.get() else "normal"
        self.manual_ch_entry.configure(state=state)

    # ====================================================================== #
    # LOGICA CANALE MANUALE (1 - 32)
    # ====================================================================== #
    
    def _on_manual_ch_inc(self):
        if not self.read_auto_var.get():
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
        return max(1, min(500, value))

    def _send_pwm_command(self):
        self._send_bt(f"F{self.pwm_value.get()}".encode("ascii"))

    # ====================================================================== #
    # LOGICA INVIO DSP FILTER SETTINGS 
    # ====================================================================== #
    def _send_dsp_params(self):
        try:
            th = int(self.dsp_thresh_var.get())
            win = int(self.dsp_window_var.get())
            trig = int(self.dsp_trig_var.get())
            rec = float(self.dsp_rec_var.get())

            win_hw = win * 2           
            trig_hw = trig * 2
            rec_hw = int(rec * 100)    

            commands_to_send = [
                f"T{th}".encode("ascii"),
                f"W{win_hw}".encode("ascii"),
                f"D{trig_hw}".encode("ascii"),
                f"E{rec_hw}".encode("ascii")
            ]

            def send_next():
                if commands_to_send:
                    cmd = commands_to_send.pop(0)
                    self._send_bt(cmd)
                    self.after(20, send_next)
                else:
                    print(f"[Settings] Sent DSP config: Thresh={th}, Window={win_hw}, TrigStep={trig_hw}, RecRatio={rec_hw}%")

            send_next()

        except ValueError:
            print("[Settings Error] Please enter valid numbers in the DSP fields.")

    # ====================================================================== #
    # SYSTEM & MASKING
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
        self._refresh_ui_colors()
        if self.controller is not None and hasattr(self.controller, "on_theme_changed"):
            try: self.controller.on_theme_changed()
            except Exception: pass

    def _refresh_ui_colors(self):
        color = "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#ffffff"
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                for sub in child.winfo_children():
                    if isinstance(sub, ctk.CTkFrame) and sub.cget("corner_radius") == 6:
                         sub.configure(fg_color=color)

    def _on_mask_changed(self, ch_idx):
        is_active = self.ch_vars[ch_idx].get()
        if hasattr(self.controller, "set_channel_active"):
            self.controller.set_channel_active(ch_idx, is_active)