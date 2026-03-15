import tkinter as tk
import customtkinter as ctk
from widgets import ChannelPreview, ChannelWindow


class AdvancedTab(ctk.CTkFrame):
    """Tab 'Advanced': griglia 4x8 di anteprime canali + controlli Start/Stop + SD + Auto/Manual."""

    def __init__(self, master, controller, num_channels: int = 32):
        super().__init__(master)
        self.controller = controller
        self.num_channels = num_channels

        # riga 0: controlli, riga 1: griglia
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ==========================================
        # BARRA CONTROLLI SUPERIORE
        # ==========================================
        control_frame = ctk.CTkFrame(self)
        control_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 0))
        
        # DEFINIZIONE COLONNE:
        # 0: Label | 1: Start | 2: Stop | 3: Save PC | 4: Save SD | 5: Reset
        # 6: Spazio vuoto elastico
        # 7: Switch Auto/Manual | 8: CH Selector | 9: Switch voltage
        control_frame.grid_columnconfigure(0, weight=0)
        control_frame.grid_columnconfigure(1, weight=0)
        control_frame.grid_columnconfigure(2, weight=0)
        control_frame.grid_columnconfigure(3, weight=0)
        control_frame.grid_columnconfigure(4, weight=0)
        control_frame.grid_columnconfigure(5, weight=0) # Reset Button
        control_frame.grid_columnconfigure(6, weight=1) # Spazio elastico per separare
        control_frame.grid_columnconfigure(7, weight=0) # Auto/Manual
        control_frame.grid_columnconfigure(8, weight=0) # Selector
        control_frame.grid_columnconfigure(9, weight=0) # Voltage Switch

        label = ctk.CTkLabel(
            control_frame,
            text="Acquisition:",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        label.grid(row=0, column=0, padx=(0, 8), pady=5, sticky="w")

        start_btn = ctk.CTkButton(
            control_frame, text="▶", font=ctk.CTkFont(size=18, weight="bold"),
            width=60, command=self._on_start_pressed,
        )
        start_btn.grid(row=0, column=1, padx=(0, 6), pady=5, sticky="w")

        stop_btn = ctk.CTkButton(
            control_frame, text="■", font=ctk.CTkFont(size=18, weight="bold"),
            width=60, command=self._on_stop_pressed,
        )
        stop_btn.grid(row=0, column=2, padx=(0, 15), pady=5, sticky="w")
        
        # --- Switch per LOGGING SU PC ---
        self.log_switch = ctk.CTkSwitch(control_frame, text="Save to file", command=self._on_log_switch_toggle)
        self.log_switch.grid(row=0, column=3, padx=5, pady=5, sticky="w")

        # --- SWITCH PER LOGGING SU SD ---
        self.sd_switch = ctk.CTkSwitch(control_frame, text="Save to SD", command=self._on_sd_switch_toggle)
        self.sd_switch.grid(row=0, column=4, padx=5, pady=5, sticky="w")

        # --- NUOVO: Bottone RESET ---
        self.reset_btn = ctk.CTkButton(
            control_frame, text="Reset", font=ctk.CTkFont(size=14, weight="bold"),
            width=60, command=self._on_reset_pressed,
        )
        self.reset_btn.grid(row=0, column=5, padx=5, pady=5, sticky="w")


        # --- NUOVO: Auto/Manual Switch ---
        self.read_auto_var = ctk.BooleanVar(value=True) # Default su Auto

        mode_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        mode_frame.grid(row=0, column=7, padx=(10, 5), pady=5, sticky="e")
        ctk.CTkLabel(mode_frame, text="Manual").pack(side="left", padx=5)
        self.mode_switch = ctk.CTkSwitch(
            mode_frame, text="Auto", variable=self.read_auto_var, 
            command=self._on_read_mode_changed, width=40
        )
        self.mode_switch.pack(side="left", padx=5)

        # --- NUOVO: Selettore Canale Manuale ---
        self.manual_ch_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        self.manual_ch_frame.grid(row=0, column=8, padx=(5, 15), pady=5, sticky="e")

        ctk.CTkLabel(self.manual_ch_frame, text="CH:").pack(side="left", padx=(0, 2))
        self.manual_ch_value = ctk.IntVar(value=1)
        self.manual_ch_entry = ctk.CTkEntry(self.manual_ch_frame, width=40, textvariable=self.manual_ch_value, justify="center")
        self.manual_ch_entry.pack(side="left", padx=2)
        self.manual_ch_entry.bind("<Return>", self._on_manual_ch_commit)

        ch_btn_frame = ctk.CTkFrame(self.manual_ch_frame, fg_color="transparent")
        ch_btn_frame.pack(side="left")
        ctk.CTkButton(ch_btn_frame, text="▲", width=20, height=12, command=self._on_manual_ch_inc).pack(pady=1)
        ctk.CTkButton(ch_btn_frame, text="▼", width=20, height=12, command=self._on_manual_ch_dec).pack(pady=1)

        # Disabilitato di base finché non si passa in Manual
        self.manual_ch_entry.configure(state="disabled")

        # --- Pulsante Switch bit/voltage ---
        self.display_mode = ctk.StringVar(value="bit")
        self.btn_switch_mode = ctk.CTkButton(
            control_frame, text="Switch to voltage", width=150, command=self._toggle_display_mode,
        )
        self.btn_switch_mode.grid(row=0, column=9, padx=(0, 15), pady=10, sticky="e")


        # ==========================================
        # GRIGLIA CANALI (FISSA 4x8)
        # ==========================================
        grid_frame = ctk.CTkFrame(self)
        grid_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=15)

        for col in range(8):
            grid_frame.grid_columnconfigure(col, weight=1, minsize=150)
        for row in range(4):
            grid_frame.grid_rowconfigure(row, weight=1, minsize=60)

        self.channel_previews = []

        for ch in range(num_channels):
            row = ch // 8
            col = ch % 8
            preview = ChannelPreview(
                grid_frame,
                channel_id=ch + 1,
                click_callback=self._open_channel_window,
            )
            preview.grid(row=row, column=col, padx=8, pady=4, sticky="nsew")
            self.channel_previews.append(preview)

        self.channel_windows = {}

    # ====================================================================== #
    # LOGICA DI AGGIORNAMENTO DATI
    # ====================================================================== #
    def update_channel(self, ch_index: int, value: int, particles: int | None = None):
        if 0 <= ch_index < len(self.channel_previews):
            preview = self.channel_previews[ch_index]
            preview.update_from_value(value)
            if particles is not None:
                preview.set_particles(particles)

        channel_id = ch_index + 1
        win = self.channel_windows.get(channel_id)

        if win is not None:
            try:
                if win.winfo_exists():
                    win.update_from_value(value, particles=particles)
                else:
                    del self.channel_windows[channel_id]
            except tk.TclError:
                if channel_id in self.channel_windows:
                    del self.channel_windows[channel_id]

    def _open_channel_window(self, channel_id: int):
        if channel_id in self.channel_windows:
            try:
                win = self.channel_windows[channel_id]
                win.focus()
                return
            except Exception:
                pass

        history = None
        if hasattr(self.controller, "channel_history"):
            history = list(self.controller.channel_history[channel_id - 1])

        initial_particles = None
        if hasattr(self.controller, "channel_particles"):
            try:
                initial_particles = self.controller.channel_particles[channel_id - 1]
            except Exception:
                initial_particles = None

        win = ChannelWindow(
            self,
            channel_id,
            history=history,
            initial_particles=initial_particles
        )
        self.channel_windows[channel_id] = win

    # ====================================================================== #
    # LOGICA PULSANTI ACQUISIZIONE E SALVATAGGIO
    # ====================================================================== #
    def _on_start_pressed(self):
        self.controller._on_start_acquisition()

    def _on_stop_pressed(self):
        self.controller._on_stop_acquisition()
        
    def _on_reset_pressed(self):
        self._send_bt(b"R")
        
    def _on_log_switch_toggle(self):
        is_active = bool(self.log_switch.get())
        if self.controller:
            self.controller.set_logging_state(is_active)

    def _on_sd_switch_toggle(self):
        is_active = bool(self.sd_switch.get())
        if hasattr(self.controller, "_bt_send_command"):
            if is_active:
                self.controller._bt_send_command(b'S')
            else:
                self.controller._bt_send_command(b'S0')

    def _toggle_display_mode(self):
        if self.display_mode.get() == "bit":
            self.display_mode.set("voltage")
            self.btn_switch_mode.configure(text="Switch to bit")
        else:
            self.display_mode.set("bit")
            self.btn_switch_mode.configure(text="Switch to voltage")

        for preview in self.channel_previews:
            preview.set_display_mode(self.display_mode.get())

    # ====================================================================== #
    # LOGICA AUTO/MANUAL MODE
    # ====================================================================== #
    def _send_bt(self, payload: bytes):
        if hasattr(self.controller, "_bt_send_command"):
            try:
                self.controller._bt_send_command(payload)
            except Exception:
                pass

    def _on_read_mode_changed(self):
        is_auto = self.read_auto_var.get()
        if is_auto:
            self._send_bt(b"MA")
            self.manual_ch_entry.configure(state="disabled")
        else:
            self._send_bt(b"MM")
            self.manual_ch_entry.configure(state="normal")
            
            # Imposta la GUI sul canale 1
            self.manual_ch_value.set(1)
            
            # Usa un piccolo ritardo (150ms) per evitare collisioni BLE col pacchetto "MM"
            self.after(150, self._send_manual_ch_command)
            
            self._clear_other_graphs()

    def _on_manual_ch_inc(self):
        if not self.read_auto_var.get():
            self.manual_ch_value.set(self._clamp_ch(self.manual_ch_value.get() + 1))
            self._send_manual_ch_command()
            self._clear_other_graphs()

    def _on_manual_ch_dec(self):
        if not self.read_auto_var.get():
            self.manual_ch_value.set(self._clamp_ch(self.manual_ch_value.get() - 1))
            self._send_manual_ch_command()
            self._clear_other_graphs()

    def _on_manual_ch_commit(self, event=None):
        if not self.read_auto_var.get():
            try:
                val = int(self.manual_ch_entry.get())
                self.manual_ch_value.set(self._clamp_ch(val))
                self._send_manual_ch_command()
                self._clear_other_graphs()
            except ValueError:
                pass

    def _clamp_ch(self, value):
        return max(1, min(self.num_channels, value))

    def _send_manual_ch_command(self):
        # Aggiunge lo zero iniziale (es. "N01" invece di "N1") per normalizzare il payload a 3 byte
        cmd = f"N{self.manual_ch_value.get():02d}".encode("ascii")
        self._send_bt(cmd)

    def _clear_other_graphs(self):
            """Svuota la cronologia e resetta il testo a 0 dei grafici non selezionati."""
            active_ch_idx = self.manual_ch_value.get() - 1

            for ch in range(self.num_channels):
                if ch != active_ch_idx:
                    # 1. Svuota lo storico nel controller principale (rimuove i vecchi dati dalla memoria)
                    if hasattr(self.controller, "channel_history"):
                        self.controller.channel_history[ch].clear()
                    
                    # 2. Resetta il numero particelle globale a 0
                    if hasattr(self.controller, "channel_particles"):
                        self.controller.channel_particles[ch] = 0

                    # 3. Aggiorna solo visivamente il TESTO delle particelle a 0 
                    # (senza chiamare update_channel che scriverebbe falsi punti sul grafico)
                    if 0 <= ch < len(self.channel_previews):
                        preview = self.channel_previews[ch]
                        if hasattr(preview, "set_particles"):
                            preview.set_particles(0)
                            
                        # 4. Se la tua widget supporta una pulizia esplicita della linea grafica, usala
                        if hasattr(preview, "clear"):
                            try:
                                preview.clear()
                            except Exception:
                                pass