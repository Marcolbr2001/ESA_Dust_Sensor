import tkinter as tk

import customtkinter as ctk

from . import theme
from .widgets import ChannelPreview, ChannelWindow


class AdvancedTab(ctk.CTkFrame):
    """Tab 'Channels': griglia 8x4 di anteprime canali + comandi acquisizione, salvataggio e visualizzazione."""

    def __init__(self, master, controller, num_channels: int = 32):
        super().__init__(master, fg_color="transparent")
        self.controller = controller
        self.num_channels = num_channels
        pad, gap = theme.PAD, theme.GAP

        # riga 0: comandi, riga 1: griglia
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ==========================================
        # BARRA COMANDI: due gruppi, il secondo va a capo se la finestra è stretta
        # ==========================================
        self.toolbar = theme.card(self)
        self.toolbar.grid(row=0, column=0, sticky="ew", padx=pad, pady=(theme.TOP, gap))
        self.toolbar.grid_columnconfigure(1, weight=1)
        self._acq_group = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        self._view_group = ctk.CTkFrame(self.toolbar, fg_color="transparent")

        # --- Gruppo acquisizione ---
        g = self._acq_group
        theme.section_title(g, "Acquisition", size=14).pack(side="left", padx=(6, 12))
        theme.start_button(g, command=self._on_start_pressed).pack(side="left", padx=(0, gap))
        theme.stop_button(g, command=self._on_stop_pressed).pack(side="left", padx=(0, gap))
        self.reset_btn = theme.secondary_button(g, "Reset", self._on_reset_pressed, width=70)
        self.reset_btn.pack(side="left", padx=(0, 14))
        theme.separator(g).pack(side="left", padx=(0, 14))
        self.log_switch = ctk.CTkSwitch(g, text="Save to file", width=40, command=self._on_log_switch_toggle)
        self.log_switch.pack(side="left", padx=(0, 10))
        self.sd_switch = ctk.CTkSwitch(g, text="Save to SD", width=40, command=self._on_sd_switch_toggle)
        self.sd_switch.pack(side="left")

        # --- Gruppo visualizzazione ---
        g = self._view_group
        self.show_adc_var = ctk.BooleanVar(value=False)
        self.adc_switch = ctk.CTkSwitch(g, text="Show ADCs", variable=self.show_adc_var, width=40,
                                        command=self._on_adc_switch_toggle)
        self.adc_switch.pack(side="left")
        # Legenda colori delle tracce ADC (visibile solo con lo switch attivo)
        self._legend = ctk.CTkFrame(g, fg_color="transparent")
        self._legend_pos = ctk.CTkLabel(self._legend, text="━ OUT_P", font=theme.font(11, "bold"))
        self._legend_pos.pack(side="left", padx=(8, 6))
        self._legend_neg = ctk.CTkLabel(self._legend, text="┅ OUT_N", font=theme.font(11, "bold"))
        self._legend_neg.pack(side="left")
        self._apply_legend_colors()
        self._sep_mode = theme.separator(g)
        self._sep_mode.pack(side="left", padx=12)

        ctk.CTkLabel(g, text="Manual").pack(side="left", padx=(0, 6))
        self.read_auto_var = ctk.BooleanVar(value=True)  # Default su Auto
        self.mode_switch = ctk.CTkSwitch(g, text="Auto", variable=self.read_auto_var, width=40,
                                         command=self._on_read_mode_changed)
        self.mode_switch.pack(side="left", padx=(0, 10))

        # --- Selettore Canale Manuale ---
        self.manual_ch_frame = ctk.CTkFrame(g, fg_color="transparent")
        self.manual_ch_frame.pack(side="left")
        ctk.CTkLabel(self.manual_ch_frame, text="CH").pack(side="left", padx=(0, 4))
        self.manual_ch_value = ctk.IntVar(value=1)
        self.manual_ch_entry = ctk.CTkEntry(self.manual_ch_frame, width=44, textvariable=self.manual_ch_value, justify="center")
        self.manual_ch_entry.pack(side="left")
        self.manual_ch_entry.bind("<Return>", self._on_manual_ch_commit)
        arrows = ctk.CTkFrame(self.manual_ch_frame, fg_color="transparent")
        arrows.pack(side="left", padx=(3, 0))
        ctk.CTkButton(arrows, text="▲", width=24, height=14, font=theme.font(9), command=self._on_manual_ch_inc).pack(pady=(0, 1))
        ctk.CTkButton(arrows, text="▼", width=24, height=14, font=theme.font(9), command=self._on_manual_ch_dec).pack()

        theme.separator(g).pack(side="left", padx=12)

        # --- Unità di misura dei grafici (bit / volt) ---
        self.display_mode = ctk.StringVar(value="bit")
        self.units_switch = ctk.CTkSegmentedButton(g, values=["Bit", "Volt"], width=110, command=self._on_units_changed)
        self.units_switch.set("Bit")
        self.units_switch.pack(side="left", padx=(0, 4))

        self._update_manual_ch_ui()
        self._toolbar_wrapped = None
        self._layout_toolbar(False)
        self.toolbar.bind("<Configure>", self._on_toolbar_resize)
        self.read_auto_var.trace_add("write", lambda *_: self._update_manual_ch_ui())

        # ==========================================
        # GRIGLIA CANALI 8x4: colonne e righe uguali che seguono la finestra
        # ==========================================
        grid_frame = ctk.CTkFrame(self, fg_color="transparent")
        grid_frame.grid(row=1, column=0, sticky="nsew", padx=pad - 4, pady=(0, pad - 4))
        for col in range(8):
            grid_frame.grid_columnconfigure(col, weight=1, uniform="ch_col")
        for row in range(4):
            grid_frame.grid_rowconfigure(row, weight=1, uniform="ch_row")

        self.channel_previews = []
        for ch in range(num_channels):
            preview = ChannelPreview(grid_frame, channel_id=ch + 1, click_callback=self._open_channel_window)
            preview.grid(row=ch // 8, column=ch % 8, padx=4, pady=4, sticky="nsew")
            self.channel_previews.append(preview)

        self.channel_windows = {}

    # ====================================================================== #
    # LAYOUT RESPONSIVE DELLA BARRA COMANDI
    # ====================================================================== #
    def _layout_toolbar(self, wrapped):
        self._acq_group.grid(row=0, column=0, sticky="w", padx=10, pady=8)
        if wrapped:
            self._view_group.grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 8))
        else:
            self._view_group.grid(row=0, column=1, sticky="e", padx=10, pady=8)
        self._toolbar_wrapped = wrapped

    def _on_toolbar_resize(self, event=None):
        width = event.width if event is not None else self.toolbar.winfo_width()
        needed = (self._acq_group.winfo_reqwidth() + self._view_group.winfo_reqwidth()
                  + int(40 * theme.widget_scaling(self)))
        wrapped = width < needed
        if wrapped != self._toolbar_wrapped:
            self._layout_toolbar(wrapped)

    def _apply_legend_colors(self):
        c = theme.plot_colors()
        self._legend_pos.configure(text_color=c["adc_pos"])
        self._legend_neg.configure(text_color=c["adc_neg"])

    # ====================================================================== #
    # DATI (nessun disegno) E DISEGNO (dal ciclo di render dell'App)
    # ====================================================================== #
    def push_sample(self, ch_index: int, value: int, particles: int | None = None,
                    adc_pos: int | None = None, adc_neg: int | None = None):
        if 0 <= ch_index < len(self.channel_previews):
            preview = self.channel_previews[ch_index]
            preview.push(value, adc_pos, adc_neg)
            if particles is not None:
                preview.set_particles(particles)
        win = self.channel_windows.get(ch_index + 1)
        if win is not None:
            win.push(value, particles, adc_pos, adc_neg)

    def update_channel(self, ch_index: int, value: int, particles: int | None = None,
                       adc_pos: int | None = None, adc_neg: int | None = None):
        self.push_sample(ch_index, value, particles, adc_pos, adc_neg)

    def render(self):
        for preview in self.channel_previews:
            preview.render()

    def render_windows(self, rates=None):
        for channel_id, win in list(self.channel_windows.items()):
            try:
                if not win.winfo_exists():
                    del self.channel_windows[channel_id]
                    continue
                win.render(rates[channel_id - 1] if rates else None)
            except tk.TclError:
                self.channel_windows.pop(channel_id, None)

    def apply_theme(self):
        self._apply_legend_colors()
        for preview in self.channel_previews:
            preview.apply_theme()
        for win in list(self.channel_windows.values()):
            try:
                win.apply_theme()
            except tk.TclError:
                pass

    def _open_channel_window(self, channel_id: int):
        if channel_id in self.channel_windows:
            try:
                win = self.channel_windows[channel_id]
                if win.winfo_exists():
                    win.deiconify()
                    win.lift()
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

        win = ChannelWindow(self, channel_id, history=history, initial_particles=initial_particles,
                            display_mode=self.display_mode.get(), show_adcs=self.show_adc_var.get())
        self.channel_windows[channel_id] = win

    # ====================================================================== #
    # LOGICA PULSANTI ACQUISIZIONE E SALVATAGGIO
    # ====================================================================== #
    def _on_start_pressed(self):
        self.controller._on_start_acquisition()

    def _on_stop_pressed(self):
        self.controller._on_stop_acquisition()

    def _on_reset_pressed(self):
        # Azzera i contatori del firmware e anche quelli della GUI (conteggi, istogramma, grafico)
        if hasattr(self.controller, "reset_device"):
            self.controller.reset_device()
        else:
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

    def _on_adc_switch_toggle(self):
        show_adcs = self.show_adc_var.get()
        if show_adcs:
            self._legend.pack(side="left", after=self.adc_switch)
        else:
            self._legend.pack_forget()
        for preview in self.channel_previews:
            preview.set_show_adcs(show_adcs)
        for win in self.channel_windows.values():
            try:
                win.set_show_adcs(show_adcs)
            except tk.TclError:
                pass
        self.after_idle(self._on_toolbar_resize)  # la legenda cambia la larghezza richiesta

    def _on_units_changed(self, value):
        mode = "voltage" if value == "Volt" else "bit"
        self.display_mode.set(mode)
        for preview in self.channel_previews:
            preview.set_display_mode(mode)
        for win in self.channel_windows.values():
            try:
                win.set_display_mode(mode)
            except tk.TclError:
                pass

    # ====================================================================== #
    # LOGICA AUTO/MANUAL MODE (condivisa con la Dashboard, stesse variabili)
    # ====================================================================== #
    def _send_bt(self, payload: bytes):
        if hasattr(self.controller, "_bt_send_command"):
            try:
                self.controller._bt_send_command(payload)
            except Exception:
                pass

    def _update_manual_ch_ui(self):
        self.manual_ch_entry.configure(state="disabled" if self.read_auto_var.get() else "normal")

    def _on_read_mode_changed(self):
        is_auto = self.read_auto_var.get()
        if is_auto:
            self._send_bt(b"MA")
        else:
            self._send_bt(b"MM")

            # Imposta la GUI sul canale 1
            self.manual_ch_value.set(1)

            # Usa un piccolo ritardo (150ms) per evitare collisioni BLE col pacchetto "MM"
            self.after(150, self._send_manual_ch_command)

            self._clear_other_graphs()
        self._update_manual_ch_ui()

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
                if hasattr(self.controller, "clear_channel"):
                    self.controller.clear_channel(ch)  # storia, conteggio e particelle nell'istogramma

                if 0 <= ch < len(self.channel_previews):
                    self.channel_previews[ch].clear()

    def set_channel_active(self, ch_index: int, is_active: bool):
        """Trova la preview corretta e le dice di sbiadirsi o accendersi."""
        if 0 <= ch_index < len(self.channel_previews):
            self.channel_previews[ch_index].set_active_state(is_active)
