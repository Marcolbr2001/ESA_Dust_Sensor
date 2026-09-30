import json
import os

import customtkinter as ctk
from PIL import Image

from . import paths, theme


class SettingsTab(ctk.CTkFrame):
    """
    Tab 'Dashboard' (Settings):
    1. Material Database (O<num>)
    2. DUST Clock | Channel Read Mode | PWM Freq | Averaging Window
    3. DSP Filter Settings (T, W, D, E)
    4. Channel Masking
    5. Display Settings (Refresh, Appearance)
    Le card si dispongono su 4 o 2 colonne in base alla larghezza della finestra.
    """

    def __init__(self, master, controller=None):
        super().__init__(master, fg_color="transparent")

        # controller (App) usato per chiamare _bt_send_command(...)
        self.controller = controller
        pad, gap = theme.PAD, theme.GAP

        # Percorso del file database materiali
        self.db_path = paths.database_file("materials.json")
        self.materials_data = {}
        self._mat_pil = None
        self._mat_img_job = None
        self.current_ctk_image = None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Frame contenitore principale SCROLLABILE
        # Colore esplicito (chiaro, scuro) e non "transparent": dentro un CTkScrollableFrame il cambio
        # tema non arriva ai figli trasparenti, che resterebbero scuri passando al tema chiaro
        content = ctk.CTkScrollableFrame(self, fg_color=theme.PAGE)
        content.grid(row=0, column=0, sticky="nsew", padx=pad - 6, pady=(0, 4))
        content.grid_columnconfigure(0, weight=1)

        # ==================================================================
        # 1) MATERIALI
        # ==================================================================
        mat_card = theme.card(content)
        mat_card.grid(row=0, column=0, sticky="ew", pady=(0, gap), padx=4)
        mat_card.grid_columnconfigure(0, weight=1, uniform="half")
        mat_card.grid_columnconfigure(1, weight=1, uniform="half")

        # --- SINISTRA: Controlli, Dati Tecnici e Descrizione ---
        self.left_mat = ctk.CTkFrame(mat_card, fg_color="transparent")
        self.left_mat.grid(row=0, column=0, sticky="nsew", padx=(20, 10), pady=16)
        self.left_mat.grid_columnconfigure(0, weight=1)

        theme.section_title(self.left_mat, "Material Configuration").grid(row=0, column=0, sticky="w")
        mat_caption = theme.caption(self.left_mat, "Sets the digital threshold and the size calibration of the histogram.")
        mat_caption.grid(row=1, column=0, sticky="w", pady=(0, 10))
        theme.autowrap(mat_caption, self.left_mat, margin=4)

        self.mat_combo = ctk.CTkComboBox(self.left_mat, values=["Loading..."], command=self._on_material_selected)
        self.mat_combo.grid(row=2, column=0, sticky="ew", pady=(0, 12))

        self.lbl_mat_value = ctk.CTkLabel(self.left_mat, text="Digital Threshold: ---", font=theme.font(13, "bold"), anchor="w")
        self.lbl_mat_value.grid(row=3, column=0, sticky="w", pady=(0, 6))

        stats_font = theme.font(20, "bold")
        self.lbl_mat_range = ctk.CTkLabel(self.left_mat, text="Size Range: ---", font=stats_font, anchor="w")
        self.lbl_mat_range.grid(row=4, column=0, sticky="w")
        self.lbl_mat_median = ctk.CTkLabel(self.left_mat, text="Median Size: ---", font=stats_font, anchor="w")
        self.lbl_mat_median.grid(row=5, column=0, sticky="w", pady=(0, 10))

        self.lbl_mat_desc = theme.caption(self.left_mat, "...")
        self.lbl_mat_desc.grid(row=6, column=0, sticky="w", pady=(0, 14))

        reload_btn = ctk.CTkButton(self.left_mat, text="Reload DB", width=100, fg_color="transparent", border_width=1,
                                   text_color=theme.TEXT, command=self._load_materials_db)
        reload_btn.grid(row=7, column=0, sticky="w")

        # La descrizione va a capo in base alla larghezza della colonna
        self.left_mat.bind("<Configure>", self._update_text_wrap)

        # --- DESTRA: Titolo e Immagine (Centrati, immagine scalata sulla colonna) ---
        self.right_mat = ctk.CTkFrame(mat_card, fg_color="transparent")
        self.right_mat.grid(row=0, column=1, sticky="nsew", padx=(10, 20), pady=16)

        self.lbl_mat_name = ctk.CTkLabel(self.right_mat, text="Select a material", font=theme.font(20, "bold"))
        self.lbl_mat_name.pack(anchor="center", pady=(0, 10))

        self.lbl_mat_img = ctk.CTkLabel(self.right_mat, text="No Image", text_color=theme.TEXT_MUTED)
        self.lbl_mat_img.pack(anchor="center", pady=5)
        self.right_mat.bind("<Configure>", self._schedule_image_rescale)

        # ==================================================================
        # 2) HARDWARE: Clock / Read Mode / PWM / Averaging
        # ==================================================================
        hw_frame = ctk.CTkFrame(content, fg_color="transparent")
        hw_frame.grid(row=1, column=0, sticky="ew", pady=(0, gap))

        # --- Card Dust Clock ---
        clock_card = self._small_card(hw_frame, "DUST Clock", "Sensor clock frequency.")
        self.clock_var = ctk.StringVar(value="200")
        for val in ["50", "200", "400"]:
            ctk.CTkRadioButton(clock_card.body, text=f"{val} kHz", value=val, variable=self.clock_var,
                               command=self._on_clock_changed).pack(anchor="w", pady=2)

        # --- Card Channel Mode (stesse variabili della tab Channels: restano sempre allineate) ---
        read_card = self._small_card(hw_frame, "Read Mode", "Automatic scan or single channel.")
        adv = getattr(controller, "advanced_tab", None)
        self._adv = adv
        self.read_auto_var = adv.read_auto_var if adv is not None else ctk.BooleanVar(value=True)
        self.manual_ch_value = adv.manual_ch_value if adv is not None else ctk.IntVar(value=1)

        mode_inner = ctk.CTkFrame(read_card.body, fg_color="transparent")
        mode_inner.pack(anchor="w", pady=2)
        ctk.CTkLabel(mode_inner, text="Manual").pack(side="left", padx=(0, 6))
        ctk.CTkSwitch(mode_inner, text="Auto", variable=self.read_auto_var, width=40,
                      command=self._on_read_mode_changed).pack(side="left")

        self.manual_ch_frame = ctk.CTkFrame(read_card.body, fg_color="transparent")
        self.manual_ch_frame.pack(anchor="w", pady=(8, 2))
        ctk.CTkLabel(self.manual_ch_frame, text="CH").pack(side="left", padx=(0, 4))
        self.manual_ch_entry = ctk.CTkEntry(self.manual_ch_frame, width=44, textvariable=self.manual_ch_value, justify="center")
        self.manual_ch_entry.pack(side="left")
        self.manual_ch_entry.bind("<Return>", self._on_manual_ch_commit)
        self._arrow_buttons(self.manual_ch_frame, self._on_manual_ch_inc, self._on_manual_ch_dec)
        self.read_auto_var.trace_add("write", lambda *_: self._update_manual_ch_ui())
        self._update_manual_ch_ui()

        # --- Card PWM Frequency ---
        pwm_card = self._small_card(hw_frame, "PWM Freq", "Auto mode toggle rate.")
        pwm_inner = ctk.CTkFrame(pwm_card.body, fg_color="transparent")
        pwm_inner.pack(anchor="w", pady=2)
        self.pwm_value = ctk.IntVar(value=4)
        self.pwm_entry = ctk.CTkEntry(pwm_inner, width=56, textvariable=self.pwm_value, justify="center")
        self.pwm_entry.pack(side="left")
        self.pwm_entry.bind("<Return>", self._on_pwm_entry_commit)
        ctk.CTkLabel(pwm_inner, text="kHz", text_color=theme.TEXT_MUTED).pack(side="left", padx=(6, 0))
        self._arrow_buttons(pwm_inner, self._on_pwm_inc, self._on_pwm_dec)

        # --- Card Averaging ---
        avg_card = self._small_card(hw_frame, "Avg Window", "Moving average samples.")
        avg_inner = ctk.CTkFrame(avg_card.body, fg_color="transparent")
        avg_inner.pack(anchor="w", pady=2)
        self.v_value = ctk.IntVar(value=10)
        self.v_entry = ctk.CTkEntry(avg_inner, width=56, textvariable=self.v_value, justify="center")
        self.v_entry.pack(side="left")
        self.v_entry.bind("<Return>", self._on_v_entry_commit)
        self._arrow_buttons(avg_inner, self._on_v_inc, self._on_v_dec)

        self._make_responsive(hw_frame, [clock_card, read_card, pwm_card, avg_card], min_item_width=200)

        # ==================================================================
        # 3) DSP FILTER SETTINGS
        # ==================================================================
        dsp_card = theme.card(content)
        dsp_card.grid(row=2, column=0, sticky="ew", pady=(0, gap), padx=4)
        dsp_card.grid_columnconfigure(0, weight=1)
        theme.section_title(dsp_card, "DSP Filter Settings").grid(row=0, column=0, sticky="w", padx=20, pady=(16, 0))
        dsp_caption = theme.caption(dsp_card, "Particle detection parameters used by the firmware.")
        dsp_caption.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))
        theme.autowrap(dsp_caption, dsp_card, margin=40)

        fields = ctk.CTkFrame(dsp_card, fg_color="transparent")
        fields.grid(row=2, column=0, sticky="ew", padx=16)
        self.dsp_thresh_var = ctk.StringVar(value="170")
        self.dsp_window_var = ctk.StringVar(value="50")
        self.dsp_trig_var = ctk.StringVar(value="3")
        self.dsp_rec_var = ctk.StringVar(value="0.18")
        self._dsp_desc_labels = []
        dsp_fields = [
            self._dsp_field(fields, "Threshold", self.dsp_thresh_var, "Minimum amplitude step (bits) to trigger."),
            self._dsp_field(fields, "Window", self.dsp_window_var, "Settling time (auto-doubled x2 for FW)."),
            self._dsp_field(fields, "Trig. Step", self.dsp_trig_var, "Rise time span (auto-doubled x2 for FW)."),
            self._dsp_field(fields, "Rec. Ratio", self.dsp_rec_var, "Max baseline return allowed (0.18 = 18%)."),
        ]
        self._make_responsive(fields, dsp_fields, min_item_width=190, on_layout=self._wrap_dsp_descriptions)

        self.btn_send_dsp = ctk.CTkButton(dsp_card, text="Send DSP to Device", command=self._send_dsp_params)
        self.btn_send_dsp.grid(row=3, column=0, sticky="e", padx=20, pady=(4, 16))

        # ==================================================================
        # 4) CHANNEL MASKING
        # ==================================================================
        mask_card = theme.card(content)
        mask_card.grid(row=3, column=0, sticky="ew", pady=(0, gap), padx=4)
        theme.section_title(mask_card, "Channel Masking").pack(anchor="w", padx=20, pady=(16, 0))
        mask_caption = theme.caption(mask_card, "Unchecked channels are excluded from the global sum and dimmed in the plots.")
        mask_caption.pack(anchor="w", padx=20, pady=(0, 8))
        theme.autowrap(mask_caption, mask_card, margin=40)

        mask_grid = ctk.CTkFrame(mask_card, fg_color="transparent")
        mask_grid.pack(pady=(0, 14), padx=20, fill="x")
        for i in range(8):
            mask_grid.grid_columnconfigure(i, weight=1, uniform="mask")

        self.ch_vars = []
        for i in range(32):
            var = ctk.BooleanVar(value=True)
            self.ch_vars.append(var)
            cb = ctk.CTkCheckBox(mask_grid, text=f"CH {i+1}", variable=var, width=50,
                                 command=lambda ch=i: self._on_mask_changed(ch))
            cb.grid(row=i // 8, column=i % 8, padx=2, pady=5, sticky="w")

        # ==================================================================
        # 5) DISPLAY & SYSTEM
        # ==================================================================
        sys_card = theme.card(content)
        sys_card.grid(row=4, column=0, sticky="ew", pady=(0, gap), padx=4)
        theme.section_title(sys_card, "Display").grid(row=0, column=0, columnspan=4, sticky="w", padx=20, pady=(16, 8))

        ctk.CTkLabel(sys_card, text="Refresh rate").grid(row=1, column=0, sticky="w", padx=(20, 8), pady=(0, 4))
        self.refresh_option = ctk.CTkOptionMenu(
            sys_card, values=["10 Hz", "20 Hz", "30 Hz", "40 Hz", "50 Hz", "60 Hz"], width=100, command=self._on_refresh_changed
        )
        self.refresh_option.grid(row=1, column=1, sticky="w", padx=(0, 30), pady=(0, 4))
        self.refresh_option.set("20 Hz")
        self._on_refresh_changed("20 Hz")

        ctk.CTkLabel(sys_card, text="Theme").grid(row=1, column=2, sticky="w", padx=(0, 8), pady=(0, 4))
        self.appearance_option = ctk.CTkOptionMenu(
            sys_card, values=["Dark", "Light", "System"], width=100, command=self._on_appearance_changed
        )
        self.appearance_option.grid(row=1, column=3, sticky="w", pady=(0, 4))
        self.appearance_option.set(ctk.get_appearance_mode())
        sys_caption = theme.caption(sys_card, "How often the plots are redrawn. Data is always processed at the full rate "
                                              "of the sensor (~21 frames/s), so higher values only cost CPU.")
        sys_caption.grid(row=2, column=0, columnspan=4, sticky="w", padx=20, pady=(2, 16))
        theme.autowrap(sys_caption, sys_card, margin=40)

        # --- CARICA DB DOPO AVER CREATO LA UI ---
        self._load_materials_db()

    # ====================================================================== #
    # HELPER DI LAYOUT
    # ====================================================================== #

    def _small_card(self, parent, title, description):
        card = theme.card(parent)
        theme.section_title(card, title, size=14).pack(anchor="w", padx=16, pady=(14, 0))
        desc = theme.caption(card, description)
        desc.pack(anchor="w", padx=16, pady=(0, 8))
        theme.autowrap(desc, card, margin=32)
        card.body = ctk.CTkFrame(card, fg_color="transparent")
        card.body.pack(anchor="w", fill="x", padx=16, pady=(0, 14))
        return card

    def _arrow_buttons(self, parent, on_up, on_down):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(side="left", padx=(6, 0))
        ctk.CTkButton(box, text="▲", width=26, height=15, font=theme.font(9), command=on_up).pack(pady=(0, 1))
        ctk.CTkButton(box, text="▼", width=26, height=15, font=theme.font(9), command=on_down).pack()

    def _dsp_field(self, parent, title, var, description):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(box, text=title, font=theme.font(13, "bold"), anchor="w").pack(anchor="w", padx=4)
        ctk.CTkEntry(box, width=90, textvariable=var).pack(anchor="w", padx=4, pady=(2, 2))
        desc = theme.caption(box, description)
        desc.pack(anchor="w", fill="x", padx=4, pady=(0, 6))
        self._dsp_desc_labels.append(desc)
        return box

    def _make_responsive(self, container, items, min_item_width, on_layout=None):
        """Mette gli elementi su 4 colonne se c'è spazio, altrimenti 2x2 (o 1 sotto l'altro)."""
        state = {"cols": None}
        n = len(items)

        def relayout(event=None):
            s = theme.widget_scaling(container)
            width = (event.width if event is not None else container.winfo_width()) / s
            cols = max(1, min(n, int(width // min_item_width)))
            if n == 4 and cols == 3:
                cols = 2  # 3 + 1 è sbilanciato, meglio 2 x 2
            if cols == state["cols"]:
                return
            state["cols"] = cols
            for c in range(n):
                container.grid_columnconfigure(c, weight=1 if c < cols else 0, uniform="rg" if c < cols else "")
            for i, w in enumerate(items):
                w.grid(row=i // cols, column=i % cols, sticky="nsew", padx=4, pady=(0, theme.GAP))
            if on_layout is not None:
                container.after_idle(on_layout)

        container.bind("<Configure>", relayout, add="+")
        relayout()

    def _wrap_dsp_descriptions(self):
        for lbl in self._dsp_desc_labels:
            w = lbl.master.winfo_width() / theme.widget_scaling(lbl)
            if w > 40:
                lbl.configure(wraplength=int(w - 8))

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
        if hasattr(self, "lbl_mat_desc"):
            # wraplength in px logici: CTkLabel lo moltiplica già per il fattore DPI
            new_width = self.left_mat.winfo_width() / theme.widget_scaling(self) - 4
            if new_width > 60:
                self.lbl_mat_desc.configure(wraplength=int(new_width))

    def _schedule_image_rescale(self, event=None):
        if self._mat_img_job is not None:
            self.after_cancel(self._mat_img_job)
        self._mat_img_job = self.after(150, self._rescale_material_image)

    def _rescale_material_image(self):
        self._mat_img_job = None
        if self._mat_pil is None:
            return
        s = theme.widget_scaling(self)
        avail = self.right_mat.winfo_width() / s - 10
        target_w = int(max(140, min(380, avail)))
        img_w, img_h = self._mat_pil.size
        target_h = int(img_h * target_w / img_w)
        if target_h > 300:  # immagini molto alte: limitiamo l'altezza
            target_w, target_h = int(target_w * 300 / target_h), 300
        size = (target_w, target_h)
        if self.current_ctk_image is None or self.current_ctk_image.cget("size") != size:
            self.current_ctk_image = ctk.CTkImage(light_image=self._mat_pil, dark_image=self._mat_pil, size=size)
            self.lbl_mat_img.configure(image=self.current_ctk_image, text="")

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

        # Gestione Immagine (scalata sulla colonna da _rescale_material_image)
        self._mat_pil = None
        self.current_ctk_image = None
        message = "No image available"
        if pic_filename:
            img_path = paths.image(pic_filename)
            if os.path.exists(img_path):
                try:
                    self._mat_pil = Image.open(img_path)
                except Exception:
                    message = "Error loading image"
            else:
                message = "Image not found"
        if self._mat_pil is not None:
            self._rescale_material_image()
        else:
            self.lbl_mat_img.configure(image=None, text=message)

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
        # Stessa logica della tab Channels (MA/MM, reset canale, pulizia grafici)
        if self._adv is not None:
            self._adv._on_read_mode_changed()
            return
        if self.read_auto_var.get():
            self._send_bt(b"MA")
        else:
            self._send_bt(b"MM")
            self.manual_ch_value.set(1)
            self._send_manual_ch_command()

    def _update_manual_ch_ui(self):
        state = "disabled" if self.read_auto_var.get() else "normal"
        self.manual_ch_entry.configure(state=state)

    # ====================================================================== #
    # LOGICA CANALE MANUALE (1 - 32)
    # ====================================================================== #

    def _on_manual_ch_inc(self):
        if self._adv is not None:
            return self._adv._on_manual_ch_inc()
        if not self.read_auto_var.get():
            self.manual_ch_value.set(self._clamp_ch(self.manual_ch_value.get() + 1))
            self._send_manual_ch_command()

    def _on_manual_ch_dec(self):
        if self._adv is not None:
            return self._adv._on_manual_ch_dec()
        if not self.read_auto_var.get():
            self.manual_ch_value.set(self._clamp_ch(self.manual_ch_value.get() - 1))
            self._send_manual_ch_command()

    def _on_manual_ch_commit(self, event=None):
        if self._adv is not None:
            return self._adv._on_manual_ch_commit()
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
        # Le card usano colori (chiaro, scuro): CustomTkinter le aggiorna da solo,
        # i canvas dei grafici li aggiorna l'App in on_theme_changed()
        ctk.set_appearance_mode(mode)
        if self.controller is not None and hasattr(self.controller, "on_theme_changed"):
            try: self.controller.on_theme_changed()
            except Exception: pass

    def _on_mask_changed(self, ch_idx):
        is_active = self.ch_vars[ch_idx].get()
        if hasattr(self.controller, "set_channel_active"):
            self.controller.set_channel_active(ch_idx, is_active)
