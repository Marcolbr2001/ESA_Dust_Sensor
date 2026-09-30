import customtkinter as ctk

from . import theme

NAME_PREFIX = "DUST_"  # la scansione mostra solo i dispositivi con questo prefisso


class ConnectionTab(ctk.CTkFrame):
    """
    Tab 'Connection': gestione UI per Bluetooth, Serial e log,
    la logica viene gestita dal controller (App).
    """

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller
        pad, gap = theme.PAD, theme.GAP

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure((0, 1), weight=1, uniform="conn")

        # --- Bluetooth ---
        bt_card = theme.card(self)
        bt_card.grid(row=0, column=0, sticky="nsew", padx=(pad, gap // 2), pady=(theme.TOP, gap))
        bt_card.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(bt_card, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 8))
        head.grid_columnconfigure(0, weight=1)
        theme.section_title(head, "Bluetooth (BLE)").grid(row=0, column=0, sticky="w")
        self.bt_state_label = ctk.CTkLabel(head, text="● Disconnected", font=theme.font(12, "bold"),
                                           text_color=theme.OFFLINE)
        self.bt_state_label.grid(row=0, column=1, sticky="e")

        self.bt_combo = ctk.CTkComboBox(bt_card, values=["Press Scan"])
        self.bt_combo.set("Press Scan")
        self.bt_combo.grid(row=1, column=0, padx=(16, gap), pady=(0, gap), sticky="ew")

        bt_scan_button = ctk.CTkButton(bt_card, text="Scan BT", width=110, command=self._on_bt_scan_pressed)
        bt_scan_button.grid(row=1, column=1, padx=(0, 16), pady=(0, gap), sticky="ew")

        self.bt_button = ctk.CTkButton(bt_card, text="BT Connect", command=self._on_bt_connect_pressed)
        self.bt_button.grid(row=2, column=0, padx=(16, gap), pady=(0, 16), sticky="ew")

        # Nome del dispositivo (salvato nel flash del sensore): operazione rara, quindi in una
        # finestrella invece che in una riga fissa che ruberebbe spazio al monitor
        self._current_name = ""
        self.rename_dialog = None
        self.rename_button = theme.secondary_button(bt_card, "Rename…", self._on_rename_pressed, width=110,
                                                    height=28)
        self.rename_button.grid(row=2, column=1, padx=(0, 16), pady=(0, 16), sticky="ew")
        self._set_rename_enabled(False)

        # --- Serial ---
        ser_card = theme.card(self)
        ser_card.grid(row=0, column=1, sticky="nsew", padx=(gap // 2, pad), pady=(theme.TOP, gap))
        ser_card.grid_columnconfigure(0, weight=1)
        theme.section_title(ser_card, "Serial port").grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 8))

        self.serial_combo = ctk.CTkComboBox(ser_card, values=["No ports found"])
        self.serial_combo.set("No ports found")
        self.serial_combo.grid(row=1, column=0, padx=(16, gap), pady=(0, gap), sticky="ew")

        refresh_button = ctk.CTkButton(ser_card, text="Refresh", width=110, command=self._on_serial_refresh_pressed)
        refresh_button.grid(row=1, column=1, padx=(0, 16), pady=(0, gap), sticky="ew")

        serial_button = ctk.CTkButton(ser_card, text="Serial Connect", command=self._on_serial_connect_pressed)
        serial_button.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 16), sticky="ew")

        # --- riga centrale: text-box + pulsante Send ---
        cmd_card = theme.card(self)
        cmd_card.grid(row=1, column=0, columnspan=2, sticky="ew", padx=pad, pady=(0, gap))
        cmd_card.grid_columnconfigure(0, weight=1)

        self.command_entry = ctk.CTkEntry(cmd_card, placeholder_text="Type command to send…")
        self.command_entry.grid(row=0, column=0, padx=(16, gap), pady=12, sticky="ew")
        self.command_entry.bind("<Return>", lambda e: self._on_send_pressed())

        send_button = ctk.CTkButton(cmd_card, text="Send", width=100, command=self._on_send_pressed)
        send_button.grid(row=0, column=1, padx=(0, 16), pady=12, sticky="e")

        # --- riga inferiore (log + controlli) ---
        log_card = theme.card(self)
        log_card.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=pad, pady=(0, pad))
        log_card.grid_rowconfigure(1, weight=1)
        log_card.grid_columnconfigure(0, weight=1)
        theme.section_title(log_card, "Monitor").grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))

        # Textbox del monitor
        self.terminal = ctk.CTkTextbox(log_card, font=ctk.CTkFont(family="Consolas", size=12))
        self.terminal.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))

        options = ctk.CTkFrame(log_card, fg_color="transparent")
        options.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        options.grid_columnconfigure(2, weight=1)

        # Autoscroll checkbox (in basso a sinistra)
        self.autoscroll_var = ctk.BooleanVar(value=True)
        self.autoscroll_check = ctk.CTkCheckBox(options, text="Autoscroll", variable=self.autoscroll_var)
        self.autoscroll_check.grid(row=0, column=0, sticky="w", padx=(4, 16))

        # Frame grezzi ricevuti: ~20 righe/s illeggibili e costose da disegnare, quindi spenti di default
        self.log_rx_var = ctk.BooleanVar(value=False)
        self.log_rx_check = ctk.CTkCheckBox(options, text="Log raw RX frames", variable=self.log_rx_var)
        self.log_rx_check.grid(row=0, column=1, sticky="w")

        # Clear Monitor (in basso a destra)
        self.clear_button = ctk.CTkButton(options, text="Clear Monitor", width=120, command=self.clear_log,
                                          fg_color=theme.NEUTRAL, hover_color=theme.NEUTRAL_HOVER)
        self.clear_button.grid(row=0, column=3, sticky="e")

    # --------- metodi helper usati dal controller ---------

    # Con lo stream attivo e 'Log raw RX frames' acceso arriva una riga di ~500 caratteri ogni ~50 ms:
    # senza limite il Text di Tk cresce di decine di MB/ora e la UI rallenta fino a bloccarsi
    MAX_LOG_LINES = 1000

    def log(self, text: str):
        self.terminal.insert("end", text + "\n")
        # "end-1c" è sulla riga vuota finale, quindi le righe di testo sono line_count - 1
        line_count = int(self.terminal.index("end-1c").split(".")[0])
        if line_count > self.MAX_LOG_LINES + 1:
            self.terminal.delete("1.0", f"{line_count - self.MAX_LOG_LINES}.0")
        # autoscroll solo se la checkbox è attiva
        if self.autoscroll_var.get():
            self.terminal.see("end")

    def log_rx_enabled(self) -> bool:
        return bool(self.log_rx_var.get())

    def set_connection_state(self, connected: bool, name: str = ""):
        if connected:
            self.bt_state_label.configure(text=f"● Connected{' · ' + name if name else ''}", text_color=theme.ONLINE)
            self.bt_button.configure(text="BT Disconnect", fg_color=theme.STOP, hover_color=theme.STOP_HOVER)
            # Nome attuale senza l'indirizzo aggiunto in caso di nomi uguali (es. "DUST_X (00:01)")
            self._current_name = name.split(" (")[0]
            self._set_rename_enabled(True)
        else:
            btn_theme = ctk.ThemeManager.theme["CTkButton"]
            self.bt_state_label.configure(text="● Disconnected", text_color=theme.OFFLINE)
            self.bt_button.configure(text="BT Connect", fg_color=btn_theme["fg_color"], hover_color=btn_theme["hover_color"])
            self._set_rename_enabled(False)

    def _set_rename_enabled(self, enabled: bool):
        self.rename_button.configure(state="normal" if enabled else "disabled")
        if not enabled and self.rename_dialog is not None:
            self.rename_dialog.close()

    def get_bt_selection(self) -> str:
        return self.bt_combo.get()

    def set_bt_devices(self, names):
        if not names:
            self.bt_combo.configure(values=["No DUST_ devices found"])
            self.bt_combo.set("No DUST_ devices found")
        else:
            self.bt_combo.configure(values=names)
            self.bt_combo.set(names[0])

    def set_bt_selection(self, name: str):
        self.bt_combo.set(name)

    def get_serial_selection(self) -> str:
        return self.serial_combo.get()

    def set_serial_ports(self, ports):
        if not ports:
            self.serial_combo.configure(values=["No ports found"])
            self.serial_combo.set("No ports found")
        else:
            self.serial_combo.configure(values=ports)
            self.serial_combo.set(ports[0])

    # --------- callback dei pulsanti (chiamano il controller) ---------

    def _on_bt_scan_pressed(self):
        self.controller._on_bt_scan()

    def _on_bt_connect_pressed(self):
        self.controller._on_bt_connect()

    def _on_serial_refresh_pressed(self):
        self.controller._refresh_serial_ports()

    def _on_serial_connect_pressed(self):
        self.controller._on_serial_connect()

    def _on_rename_pressed(self):
        if str(self.rename_button.cget("state")) == "disabled":
            return
        if self.rename_dialog is not None:
            self.rename_dialog.lift()
            return
        suffix = self._current_name[len(NAME_PREFIX):] if self._current_name.startswith(NAME_PREFIX) else ""
        self.rename_dialog = RenameDialog(self, suffix, on_confirm=self._on_rename_confirmed)

    def _on_rename_confirmed(self, suffix: str):
        self.controller.rename_device(NAME_PREFIX + suffix)

    def _on_rename_dialog_closed(self):
        self.rename_dialog = None

    def _on_send_pressed(self):
        """Legge il testo e chiede al controller di inviarlo via BLE."""
        text = self.command_entry.get().strip()
        self.controller._on_send_text(text)

    def clear_log(self):
        """Cancella il contenuto del monitor/log."""
        self.terminal.delete("1.0", "end")


class RenameDialog(ctk.CTkToplevel):
    """Finestrella per il nome del dispositivo: DUST_ + suffisso, salvato nel flash del sensore."""

    def __init__(self, tab, suffix, on_confirm):
        super().__init__(tab)
        self._tab = tab
        self._on_confirm = on_confirm
        self._closed = False
        self.title("Rename device")
        self.resizable(False, False)
        self.configure(fg_color=theme.PAGE)
        self.transient(tab.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)

        body = theme.card(self)
        body.pack(fill="both", expand=True, padx=theme.PAD, pady=theme.PAD)
        body.grid_columnconfigure(1, weight=1)
        theme.section_title(body, "Device name").grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        theme.caption(body, "Saved in the sensor's flash memory, so it is kept when you load a new firmware. "
                            "The sensor advertises the new name after you disconnect.",
                      wraplength=330).grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 12))

        ctk.CTkLabel(body, text=NAME_PREFIX, font=theme.font(14, "bold")).grid(row=2, column=0, sticky="e", padx=(16, 2))
        self.entry = ctk.CTkEntry(body, width=100, placeholder_text="6")
        self.entry.grid(row=2, column=1, sticky="w", padx=(0, 16))
        if suffix:
            self.entry.insert(0, suffix)
        theme.caption(body, "1-5 letters, digits, _ or -").grid(row=3, column=1, sticky="w", pady=(2, 12))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", padx=16, pady=(0, 14))
        theme.secondary_button(buttons, "Cancel", self.close, width=90).pack(side="left", padx=(0, theme.GAP))
        ctk.CTkButton(buttons, text="Save name", width=110, height=34, font=theme.font(13, "bold"),
                      command=self.confirm).pack(side="left")

        self.entry.bind("<Return>", lambda e: self.confirm())
        self.bind("<Escape>", lambda e: self.close())
        self.after(20, self._show)

    def _show(self):
        # Centrata sulla finestra principale (le coordinate +x+y non sono scalate dal DPI)
        self.update_idletasks()
        top = self._tab.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_width()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.lift()
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        try:
            self.grab_set()
        except Exception:
            pass

    def confirm(self):
        suffix = self.entry.get().strip()
        self.close()
        self._on_confirm(suffix)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        self._tab._on_rename_dialog_closed()
        # CTkToplevel imposta l'icona 200 ms dopo la creazione: si nasconde subito e si distrugge dopo
        self.withdraw()
        self.after(300, self.destroy)
