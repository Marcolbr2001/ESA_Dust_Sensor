# app.py
import sys
import os
import re
from PIL import Image
import customtkinter as ctk
import time
import serial
from serial.tools import list_ports
import asyncio
import threading
import queue
from bleak import BleakScanner, BleakClient
from .connection_tab import ConnectionTab
from .visual_tab import VisualTab
from .advanced_tab import AdvancedTab
from .settings_tab import SettingsTab
from .analysis_tab import AnalysisTab
from collections import Counter, deque
import datetime

from . import paths, theme

# --------- UUID BLE ---------
BT_SERVICE_UUID       = "00000000-0001-11e1-9ab4-0002a5d5c51b"
BT_CHAR_MYDATA_UUID   = "00c00000-0001-11e1-ac36-0002a5d5c51b"  # notify
BT_CHAR_RECVDATA_UUID = "00c10000-0001-11e1-ac36-0002a5d5c51b"  # write

# --------- Costanti protocollo DUST ---------
DUST_CHANNELS = 32
FRAME_SYNC1 = 0xAA
FRAME_SYNC2 = 0x55
FRAME_LEN = 2 + (DUST_CHANNELS * 5) + 2  # Totale 164 bytes
FRAME_RATE = 20.8  # frame/s dal firmware: un frame ogni 2 giri dei 32 canali (64 x 0.75 ms)

# --------- Nome del dispositivo (comando 'L', salvato nel flash del sensore) ---------
DEVICE_NAME_RE = re.compile(r"DUST_[A-Za-z0-9_-]{1,5}")  # max 10 caratteri: limite dell'advertising
RENAME_ERRORS = {
    "BUSY": "a previous rename is still being written",
    "NAME": "invalid name (DUST_ + 1-5 letters, digits, '_' or '-')",
    "SPACE": "the firmware image reaches the name page, the name cannot be stored",
    "FLASH": "flash write error",
    "VERIFY": "flash verify error",
}
AMP_SETTLE_SAMPLES = 2  # campioni da attendere dopo il conteggio prima di misurare il gradino


class EventRate:
    """Eventi al secondo mediati su una finestra mobile (default 10 s)."""

    def __init__(self, window_s=10.0):
        self.window_s = window_s
        self._events = deque()  # (istante, numero di eventi)
        self._total = 0

    def add(self, t, n):
        self._events.append((t, n))
        self._total += n

    def rate(self, now):
        cutoff = now - self.window_s
        while self._events and self._events[0][0] < cutoff:
            self._total -= self._events.popleft()[1]
        return self._total / self.window_s

    def reset(self):
        self._events.clear()
        self._total = 0


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # === EVENTI PARTICELLA, ISTOGRAMMA E MASCHERE CANALI ===
        self.HISTO_MAX_VAL = 3000      # fondo scala delle ampiezze nell'istogramma (LSB)
        self.MIN_HISTO_DELTA = 20      # sotto questa ampiezza la stima non è affidabile: niente istogramma

        # Ampiezze (LSB) delle particelle, per canale, come {ampiezza: quante}: l'istogramma si
        # calcola da qui al disegno e il suo costo non cresce con la durata dell'acquisizione
        self.channel_events = [Counter() for _ in range(DUST_CHANNELS)]
        # Somma dei canali attivi, aggiornata a ogni particella: si ricostruisce solo quando
        # cambiano le maschere o si svuota un canale (_global_events_stale)
        self._global_events = Counter()
        self._global_events_stale = False
        # Particelle contate ma non ancora misurate, per canale: [quante, campioni che mancano]
        self._pending_amp = [None] * DUST_CHANNELS

        # Array di maschera (True = Attivo, False = Ignorato)
        self.channel_mask = [True] * DUST_CHANNELS

        # Contatori a 8 bit del firmware: servono solo a ricavare i NUOVI eventi di ogni frame.
        # I conteggi mostrati sono quelli della GUI (channel_particles): partono da 0 a Start/Reset
        # e non ripartono da zero dopo 255 particelle
        self.last_total_particles = [0] * DUST_CHANNELS
        self._resync_until = 0.0       # fino a questo istante i contatori si riallineano senza contare
        self._resync_next = True       # il primo frame (avvio, connessione) si allinea senza contare
        # ==================================================

        self.current_threshold = 10.0

        self.channel_values = [0 for _ in range(DUST_CHANNELS)]
        self.channel_particles = [0 for _ in range(DUST_CHANNELS)]
        self.global_count = 0
        # ~19 s per canale: serve anche a ritrovare il gradino di ogni particella (vedi _estimate_amplitude)
        self.channel_history = [deque(maxlen=400) for _ in range(DUST_CHANNELS)]

        # Eventi al secondo (globale e per canale)
        self.global_rate = EventRate()
        self.channel_rates = [EventRate() for _ in range(DUST_CHANNELS)]

        # Rendering: i frame aggiornano solo i dati, il disegno avviene a frequenza fissa
        # (Refresh rate della Dashboard) e solo per la tab visibile
        self._min_draw_interval = 0.05
        self._render_interval_ms = 50
        self._global_dirty = True
        self._rx_frames = 0
        self._status_t = time.perf_counter()
        self._status_frames = 0
        self._status_texts = (None, None, None)
        self._mtu = None
        self._bt_name = ""
        self._bt_disconnecting = False
        self._rename_pending = None
        self._rename_timeout_job = None

        # --- GESTIONE LOG SU FILE ---
        self.is_logging = False
        self.log_file = None
        # ---------------------------- #

        paths.ensure_data_dirs()  # saved_data/logs, sd_card, dummy

        self.title("DUST Monitor")
        self.geometry("1000x750")
        self.minsize(800, 500)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # ----- Barra superiore: loghi e titolo si ridimensionano con la finestra -----
        self._logos = []
        self._header_scale = None
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(side="top", fill="x", padx=14, pady=(8, 0))
        # Colonne laterali uguali (uniform): il titolo resta davvero centrato
        header.grid_columnconfigure(0, weight=1, uniform="side")
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=1, uniform="side")

        left_logo = self._make_logo(header, "polimiD.png", "polimiW.png", (190, 60))
        if left_logo is not None:
            left_logo.grid(row=0, column=0, sticky="w")

        self._title_font = ctk.CTkFont(size=30, weight="bold")
        title_label = ctk.CTkLabel(header, text="DUST Tracker Monitor", font=self._title_font)
        title_label.grid(row=0, column=1, padx=16, pady=4)

        right_frame = ctk.CTkFrame(header, fg_color="transparent")
        right_frame.grid(row=0, column=2, sticky="e")
        esa_logo = self._make_logo(right_frame, "ESA_White.png", "ESA_White.png", (60, 60))
        if esa_logo is not None:
            esa_logo.pack(side="left", padx=(0, 24))
        i3n_logo = self._make_logo(right_frame, "i3n.png", "i3nW.png", (200, 48))
        if i3n_logo is not None:
            i3n_logo.pack(side="left")

        # ----- Barra di stato (in basso, sempre visibile) -----
        self.status_bar = ctk.CTkFrame(self, height=28, corner_radius=0, fg_color=theme.STATUS_BAR)
        self.status_bar.pack(side="bottom", fill="x")
        self._status_conn = ctk.CTkLabel(self.status_bar, text="● Disconnected", height=24,
                                         font=theme.font(12, "bold"), text_color=theme.OFFLINE)
        self._status_conn.pack(side="left", padx=(14, 18))
        self._status_stream = ctk.CTkLabel(self.status_bar, text="No data", height=24, font=theme.font(12),
                                           text_color=theme.TEXT_MUTED)
        self._status_stream.pack(side="left")
        self._status_right = ctk.CTkLabel(self.status_bar, text="", height=24, font=theme.font(12),
                                          text_color=theme.TEXT_MUTED)
        self._status_right.pack(side="right", padx=14)

        # --- Serial e BLE ---
        self.serial = None
        self.ble_client = None
        self._bt_scan_results = {}

        # Le callback di bleak girano nel thread asyncio e Tkinter non è thread-safe:
        # dal thread BLE si passa alla UI solo attraverso questa coda (vedi _post_to_ui)
        self._ui_queue = queue.SimpleQueue()
        self._ui_queue_job = self.after(20, self._drain_ui_queue)

        self.ble_loop = asyncio.new_event_loop()
        self.ble_thread = threading.Thread(target=self._ble_loop_runner, daemon=True)
        self.ble_thread.start()

        self._dust_rx_buffer = bytearray()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # TAB VIEW
        self.tabview = ctk.CTkTabview(self, fg_color=theme.PAGE, corner_radius=theme.RADIUS,
                                      command=self._on_tab_changed)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(2, 8))
        try:
            self.tabview._segmented_button.configure(font=theme.font(14, "bold"), height=32)
        except Exception:
            pass

        self.tab_connection_page = self.tabview.add("Connection")
        self.tab_visual_page = self.tabview.add("Global")
        self.tab_advanced_page = self.tabview.add("Channels")
        self.tab_settings_page = self.tabview.add("Dashboard")
        self.tab_analysis_page = self.tabview.add("File Analysis")

        self.connection_tab = ConnectionTab(self.tab_connection_page, controller=self)
        self.connection_tab.pack(fill="both", expand=True)

        self.visual_tab = VisualTab(self.tab_visual_page, controller=self)
        self.visual_tab.pack(fill="both", expand=True)
        self.visual_tab.histogram.max_val = self.HISTO_MAX_VAL

        self.advanced_tab = AdvancedTab(self.tab_advanced_page, controller=self, num_channels=DUST_CHANNELS)
        self.advanced_tab.pack(fill="both", expand=True)

        self.settings_tab = SettingsTab(self.tab_settings_page, controller=self)
        self.settings_tab.pack(fill="both", expand=True)

        self.analysis_tab = AnalysisTab(self.tab_analysis_page, controller=self)
        self.analysis_tab.pack(fill="both", expand=True)

        # Ridimensionamento finestra (larghezza e altezza): add="+" per non sostituire il binding interno di CTk
        self.bind("<Configure>", lambda e: self._on_header_resize() if e.widget is self else None, add="+")
        self._refresh_serial_ports()
        self._render_job = self.after(self._render_interval_ms, self._render_tick)

    # ---------- HEADER RESPONSIVE ----------
    def _make_logo(self, parent, light_name, dark_name, base_size):
        try:
            light = Image.open(paths.image(light_name))
            dark = Image.open(paths.image(dark_name))
        except Exception as e:
            print("Errore nel caricamento dei loghi:", e)
            return None
        label = ctk.CTkLabel(parent, text="", image=ctk.CTkImage(light_image=light, dark_image=dark, size=base_size))
        self._logos.append((label, light, dark, base_size))
        return label

    def _on_header_resize(self, event=None):
        """Loghi e titolo si riducono a gradini quando la finestra è stretta o bassa."""
        s = theme.widget_scaling(self)
        w = self.winfo_width() / s
        h = self.winfo_height() / s
        k = 1.0 if w >= 1250 else 0.85 if w >= 1050 else 0.7 if w >= 900 else 0.6
        if h < 640:
            k = min(k, 0.7)
        if k == self._header_scale:
            return
        self._header_scale = k
        for label, light, dark, (bw, bh) in self._logos:
            label.configure(image=ctk.CTkImage(light_image=light, dark_image=dark, size=(int(bw * k), int(bh * k))))
        self._title_font.configure(size=int(30 * k))

    # ---------- GESTIONE MASCHERA CANALI ----------
    def set_channel_active(self, ch_idx: int, is_active: bool):
        """Disabilita o abilita logicamente e visivamente un canale."""
        # 1. Aggiorna lo stato in memoria
        self.channel_mask[ch_idx] = is_active
        self._global_events_stale = True

        # 2. Aggiorna la vista sbiadita nella Advanced Tab
        if hasattr(self, "advanced_tab"):
            self.advanced_tab.set_channel_active(ch_idx, is_active)

        # 3. Ricalcolo globale immediato per la Visual Tab
        self._force_ui_update()

        # 4. Aggiorna i grafici nell'Analysis Tab (se c'è un file caricato)
        if hasattr(self, "analysis_tab") and self.analysis_tab.data is not None:
            self.analysis_tab.create_thumbnails()

    def _force_ui_update(self):
        """Ricalcola la somma e l'istogramma globali tenendo conto delle maschere."""
        if self._global_events_stale:
            self._global_events = Counter()
            for ch in range(DUST_CHANNELS):
                if self.channel_mask[ch]:
                    self._global_events.update(self.channel_events[ch])
            self._global_events_stale = False
        total = 0
        pending = 0
        for ch in range(DUST_CHANNELS):
            if self.channel_mask[ch]:
                total += self.channel_particles[ch]
                if self._pending_amp[ch] is not None:
                    pending += self._pending_amp[ch][0]
        self.global_count = total
        # Contate ma senza ampiezza (gradino non ritrovato): lo dice la didascalia dell'istogramma
        unsized = max(0, total - sum(self._global_events.values()) - pending)
        self.visual_tab.update_global(total, self._global_events, unsized)
        self._global_dirty = False

    def reset_counters(self, resync_s=0.5):
        """Azzera conteggi, istogramma, eventi/s e grafico globale (Start e Reset)."""
        for ch in range(DUST_CHANNELS):
            self.channel_events[ch].clear()
            self._pending_amp[ch] = None
            self.channel_particles[ch] = 0
            self.channel_rates[ch].reset()
            self.advanced_tab.channel_previews[ch].set_particles(0)
        self._global_events.clear()
        self.global_rate.reset()
        self.global_count = 0
        self.visual_tab.update_global(0, Counter())
        self.visual_tab.clear_history()
        # I contatori del firmware si riallineano senza contare per un attimo: dopo un Reset
        # ('R') il frame con i vecchi valori può essere ancora in viaggio
        self._resync_until = time.perf_counter() + resync_s
        self._resync_next = True
        self._global_dirty = True

    def clear_channel(self, ch):
        """Svuota storia, conteggio e particelle di un canale (canali non selezionati in Manual)."""
        self.channel_history[ch].clear()
        self.channel_particles[ch] = 0
        self.channel_events[ch].clear()
        self._pending_amp[ch] = None
        self._global_events_stale = True
        self._global_dirty = True
    # -----------------------------------------------------

    def set_logging_state(self, active: bool):
        if active:
            if not self.is_logging:
                try:
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
                    date_str = now.strftime("%Y-%m-%d %H:%M:%S") # Per l'header interno
                    # I log vanno in saved_data/logs, non nella cartella del programma
                    filename = os.path.join(paths.ensure_dir(paths.LOGS_DIR), f"dust_log_{timestamp}.txt")
                    self.log_file = open(filename, "w")
                    self.is_logging = True

                    # --- SCRITTURA METADATI NELL'HEADER ---
                    try:
                        # Leggiamo i parametri dalla Settings Tab
                        th = self.settings_tab.dsp_thresh_var.get()
                        win = self.settings_tab.dsp_window_var.get()
                        trig = self.settings_tab.dsp_trig_var.get()
                        rec = self.settings_tab.dsp_rec_var.get()

                        # Creiamo la stringa con il cancelletto '#' per indicare che è un commento
                        header = f"# METADATA | Date: {date_str} | Thresh: {th} | Window: {win} | Trig: {trig} | RecRatio: {rec}\n"
                        self.log_file.write(header)
                        self.log_file.flush()
                    except Exception as e:
                        print(f"Impossibile scrivere i metadati: {e}")
                    # ---------------------------------------------

                    self._log(f"[LOG] File logging started: {filename}")
                except Exception as e:
                    self._log(f"[LOG] Error creating file: {e}")
                    self.is_logging = False
        else:
            if self.is_logging and self.log_file:
                try:
                    self.log_file.close()
                    self._log("[LOG] File logging stopped and saved.")
                except Exception as e:
                    self._log(f"[LOG] Error closing file: {e}")
                finally:
                    self.log_file = None
                    self.is_logging = False

    def _ble_loop_runner(self):
        asyncio.set_event_loop(self.ble_loop)
        self.ble_loop.run_forever()

    def _post_to_ui(self, fn):
        """Esegue fn() nel thread di Tk: da usare per tutto ciò che arriva dal thread BLE."""
        self._ui_queue.put(fn)

    def _drain_ui_queue(self):
        # Al massimo 200 callback per giro, così la UI resta reattiva anche con la coda piena
        for _ in range(200):
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                self.report_callback_exception(*sys.exc_info())
        self._ui_queue_job = self.after(20, self._drain_ui_queue)

    def _log(self, text: str):
        self.connection_tab.log(text)

    def _get_serial_ports(self):
        ports = list_ports.comports()
        return [p.device for p in ports] or ["No ports found"]

    def _refresh_serial_ports(self):
        ports = self._get_serial_ports()
        self.connection_tab.set_serial_ports(ports)
        self._log("[INFO] Serial ports refreshed")

    def _on_serial_connect(self):
        # Il pulsante "Serial Connect" esiste nella Connection tab, ma lo streaming seriale
        # non è mai stato implementato nella GUI: meglio dirlo che sollevare AttributeError
        self._log("[SERIAL] Serial connection is not implemented in this GUI version, please use Bluetooth")

    # ---------- STATO CONNESSIONE ----------
    def _set_connection_state(self, connected: bool, name: str = ""):
        self._bt_name = name if connected else ""
        if not connected:
            self._mtu = None
        self.connection_tab.set_connection_state(connected, name)
        if connected:
            self._status_conn.configure(text=f"● Connected · {name}" if name else "● Connected", text_color=theme.ONLINE)
        else:
            self._status_conn.configure(text="● Disconnected", text_color=theme.OFFLINE)

    def _on_ble_lost(self):
        """Chiamata (via coda) quando bleak segnala la disconnessione del dispositivo."""
        if self.ble_client is not None and not self._bt_disconnecting:
            self._log("[BT] Connection lost")
        self.ble_client = None
        self._bt_disconnecting = False
        self._set_connection_state(False)

    def _on_bt_scan(self):
        self._log("[BT] Scanning for BLE devices...")
        async def do_scan():
            devices = await BleakScanner.discover(timeout=3.0)
            dust_devices = [d for d in devices if d.name and d.name.startswith("DUST_")]
            # Nomi uguali (es. più DUST_X non ancora rinominati): si aggiunge la fine dell'indirizzo,
            # altrimenti nella lista ne resterebbe uno solo
            counts = Counter(d.name for d in dust_devices)
            addr_map = {}
            for d in dust_devices:
                label = d.name if counts[d.name] == 1 else f"{d.name} ({d.address[-5:]})"
                addr_map[label] = d.address
            names = sorted(addr_map.keys())
            return names, addr_map

        future = asyncio.run_coroutine_threadsafe(do_scan(), self.ble_loop)

        def done_cb(fut):
            try:
                names, addr_map = fut.result()
            except Exception as err:
                # 'err' viene cancellata a fine except: il messaggio va costruito subito
                msg = f"[BT] Scan error: {err}"
                self._post_to_ui(lambda: self._log(msg))
                return
            def update_ui():
                self._bt_scan_results = addr_map
                self.connection_tab.set_bt_devices(names)
                if names: self._log(f"[BT] Found: {', '.join(names)}")
                else: self._log("[BT] No DUST_ devices found")
            self._post_to_ui(update_ui)

        future.add_done_callback(done_cb)

    def _on_bt_connect(self):
        if self.ble_client is not None:
            self._log("[BT] Disconnecting...")
            self._bt_disconnecting = True
            future = asyncio.run_coroutine_threadsafe(self._bt_disconnect_async(), self.ble_loop)
            def done_cb(fut):
                try: fut.result()
                except Exception as err:
                    msg = f"[BT] Disconnect error: {err}"
                    self._post_to_ui(lambda: self._log(msg))
                else: self._post_to_ui(lambda: self._log("[BT] Disconnected"))
                finally:
                    self.ble_client = None
                    self._post_to_ui(lambda: self._set_connection_state(False))
            future.add_done_callback(done_cb)
            return

        name = self.connection_tab.get_bt_selection()
        if not name or name.startswith("Press") or name.startswith("No DUST"):
            self._log("[BT] Please scan and select a valid device")
            return

        address = self._bt_scan_results.get(name)
        if not address:
            self._log(f"[BT] No address for device '{name}' (scan again)")
            return

        self._log(f"[BT] Connecting to {name} ({address})...")
        future = asyncio.run_coroutine_threadsafe(self._bt_connect_async(address), self.ble_loop)
        def done_cb(fut):
            try: ok = fut.result()
            except Exception as err:
                msg = f"[BT] Connect error: {err}"
                self._post_to_ui(lambda: self._log(msg))
                return
            if ok:
                self._post_to_ui(lambda: self._log("[BT] Connected successfully"))
                self._post_to_ui(lambda: self._set_connection_state(True, name))
            else: self._post_to_ui(lambda: self._log("[BT] Connection failed"))
        future.add_done_callback(done_cb)

    async def _bt_connect_async(self, address: str) -> bool:
        try:
            client = BleakClient(address, disconnected_callback=lambda c: self._post_to_ui(self._on_ble_lost))
            await client.connect()
            await asyncio.sleep(0.4)
            if not client.is_connected: return False
            self.ble_client = client
            self._bt_disconnecting = False
            self._resync_next = True  # prima delle notifiche: i contatori del dispositivo possono essere qualsiasi
            try: await client.start_notify(BT_CHAR_MYDATA_UUID, self._bt_notification_handler)
            except Exception as err:
                await asyncio.sleep(0.5)
                try: await client.start_notify(BT_CHAR_MYDATA_UUID, self._bt_notification_handler)
                except Exception as err2:
                    msg = f"[BT] start_notify error: {err2}"
                    self._post_to_ui(lambda: self._log(msg))
                    return False
            # Risposte ai comandi (es. rinomina) come notifiche sulla caratteristica dei comandi
            try: await client.start_notify(BT_CHAR_RECVDATA_UUID, self._bt_reply_handler)
            except Exception: pass  # senza notifiche il rinomina funziona lo stesso, solo senza conferma
            self._log_mtu(client)
            return True
        except Exception as e:
            msg = f"[BT] Connect exception: {e}"
            self._post_to_ui(lambda: self._log(msg))
            return False

    def _log_mtu(self, client):
        # Una notifica porta al massimo MTU-3 byte: un frame più lungo viene troncato dallo
        # stack BLE e il parser non trova mai il terminatore 0D 0A (nessun dato nei grafici)
        try:
            mtu = client.mtu_size
        except Exception:
            return
        needed = FRAME_LEN + 3
        if mtu < needed:
            msg = f"[BT] WARNING: ATT MTU {mtu} < {needed}, DUST frames ({FRAME_LEN} bytes) will be truncated"
        else:
            msg = f"[BT] ATT MTU {mtu} (DUST frame: {FRAME_LEN} bytes)"
        def update_ui():
            self._mtu = mtu
            self._log(msg)
        self._post_to_ui(update_ui)

    async def _bt_disconnect_async(self):
        if self.ble_client is not None:
            try:
                try: await self.ble_client.stop_notify(BT_CHAR_MYDATA_UUID)
                except Exception: pass
                try: await self.ble_client.stop_notify(BT_CHAR_RECVDATA_UUID)
                except Exception: pass
                await self.ble_client.disconnect()
            except Exception: pass
            self.ble_client = None

    def _bt_send_command(self, cmd_byte: bytes):
        if self.ble_client is None or not self.ble_client.is_connected:
            self._log("[BT] Not connected, cannot send command")
            return
        self._log(f"[BT] Sending command {cmd_byte!r}")
        async def do_write():
            await self.ble_client.write_gatt_char(BT_CHAR_RECVDATA_UUID, cmd_byte, response=True)
        future = asyncio.run_coroutine_threadsafe(do_write(), self.ble_loop)
        def done_cb(fut):
            try: fut.result()
            except Exception as err:
                msg = f"[BT] Write error: {err}"
                self._post_to_ui(lambda: self._log(msg))
            else: self._post_to_ui(lambda: self._log("[BT] Command sent OK"))
        future.add_done_callback(done_cb)

    def _on_send_text(self, text: str):
        if not text: return
        self._bt_send_command(text.encode("ascii", errors="ignore"))

    # ---------- NOME DEL DISPOSITIVO ----------
    def rename_device(self, name: str):
        """
        Salva il nome nel flash del sensore (comando 'L'): resta anche dopo il caricamento di un
        nuovo firmware. Il dispositivo lo usa nell'advertising dalla prossima disconnessione.
        """
        if not DEVICE_NAME_RE.fullmatch(name):
            self._log(f"[BT] Invalid name '{name}': use DUST_ followed by 1-5 letters, digits, '_' or '-'")
            return
        if self.ble_client is None:
            self._log("[BT] Not connected, cannot rename the device")
            return
        self._rename_pending = name
        self._log(f"[BT] Saving device name '{name}'...")
        # Lo zero finale delimita il nome anche se il firmware riceve più byte di quelli scritti
        self._bt_send_command(b"L" + name.encode("ascii") + b"\0")
        if self._rename_timeout_job is not None:
            self.after_cancel(self._rename_timeout_job)
        self._rename_timeout_job = self.after(4000, self._on_rename_timeout)

    def _on_rename_timeout(self):
        self._rename_timeout_job = None
        if self._rename_pending:
            self._log("[BT] No answer from the device: its firmware may not support renaming yet. "
                      "Disconnect and scan again to check the name.")
            self._rename_pending = None

    def _bt_reply_handler(self, sender, data: bytes):
        # Thread BLE: la risposta ha lunghezza fissa (20 byte) completata con zeri
        text = bytes(data).split(b"\0", 1)[0].decode("ascii", errors="replace")
        self._post_to_ui(lambda: self._handle_device_reply(text))

    def _handle_device_reply(self, text: str):
        if not text.startswith("L") or len(text) < 2:
            return
        if self._rename_timeout_job is not None:
            self.after_cancel(self._rename_timeout_job)
            self._rename_timeout_job = None
        self._rename_pending = None
        if text[1] == "+":
            self._log(f"[BT] Device name saved: {text[2:]}. It is kept after firmware updates; "
                      "the device advertises it after you disconnect (then Scan again).")
        else:
            code = text[2:]
            self._log(f"[BT] Rename failed: {RENAME_ERRORS.get(code, code)}")

    def _on_start_acquisition(self):
        # Nuova acquisizione: conteggi, istogramma e grafico globale ripartono da zero
        self.reset_counters()
        self._bt_send_command(b'Cb')

    def reset_device(self):
        """Pulsante Reset: azzera i contatori del firmware ('R') e quelli della GUI."""
        self.reset_counters(resync_s=1.0)
        self._bt_send_command(b'R')

    def _on_stop_acquisition(self):
        self._bt_send_command(b'0')

    def _bt_notification_handler(self, sender, data: bytes):
        hex_str = " ".join(f"{b:02X}" for b in data)
        data_copy = bytes(data)
        self._post_to_ui(lambda: self._handle_bt_message(hex_str, data_copy))

    def _handle_bt_message(self, hex_text: str, raw: bytes):
        # Il monitor mostra i frame grezzi solo se richiesto: ~20 righe/s costano molta CPU alla UI
        if self.connection_tab.log_rx_enabled():
            self._log(f"[BT RX] {hex_text}")
        if self.is_logging and self.log_file:
            try:
                self.log_file.write(hex_text + "\n")
                self.log_file.flush()
            except Exception: pass
        self._append_dust_bytes(raw)

    def _append_dust_bytes(self, data: bytes):
        buf = self._dust_rx_buffer
        buf.extend(data)
        while True:
            if len(buf) < 2: return
            start = -1
            for i in range(len(buf) - 1):
                if buf[i] == FRAME_SYNC1 and buf[i + 1] == FRAME_SYNC2:
                    start = i
                    break
            if start < 0:
                buf.clear()
                return
            if start > 0:
                del buf[:start]
            if len(buf) < FRAME_LEN:
                return
            candidate = buf[:FRAME_LEN]
            if not (candidate[-2] == 0x0D and candidate[-1] == 0x0A):
                del buf[0]
                continue

            adc_values = [0] * DUST_CHANNELS
            particles_values = [0] * DUST_CHANNELS
            adc_pos_values = [0] * DUST_CHANNELS
            adc_neg_values = [0] * DUST_CHANNELS

            for k in range(DUST_CHANNELS):
                off = 2 + (k * 5)
                particles = candidate[off]
                raw = (candidate[off + 1] << 8) | candidate[off + 2]
                if raw & 0x8000: raw -= 0x10000
                adc = abs(raw)
                adc_pos = candidate[off + 3]
                adc_neg = candidate[off + 4]

                if 0 <= k < DUST_CHANNELS:
                    adc_values[k] = adc
                    particles_values[k] = particles
                    adc_pos_values[k] = adc_pos
                    adc_neg_values[k] = adc_neg

            self._handle_dust_frame(adc_values, particles_values, adc_pos_values, adc_neg_values)
            del buf[:FRAME_LEN]

    def _handle_dust_frame(self, adc_values, particles_values, adc_pos_values, adc_neg_values):
        """Aggiorna solo i dati (costo minimo a ogni frame): il disegno lo fa _render_tick."""
        now = time.perf_counter()
        self._rx_frames += 1
        n_ch = min(DUST_CHANNELS, len(adc_values))

        # Nuovi eventi dai contatori a 8 bit del firmware (differenza modulo 256, quindi anche
        # l'overflow 255 -> 0 è gestito). Un calo del contatore dà un valore > 128: non è un
        # overflow ma un Reset del firmware, si riallinea senza contare nulla.
        resync = self._resync_next or now < self._resync_until
        self._resync_next = False
        new_events = [0] * n_ch
        for ch in range(n_ch):
            delta = (particles_values[ch] - self.last_total_particles[ch]) & 0xFF
            if not resync and delta <= 128:
                new_events[ch] = delta
            self.last_total_particles[ch] = particles_values[ch]

        if self.advanced_tab.read_auto_var.get():
            channels = range(n_ch)
        else:
            # === MODALITÀ MANUALE: arriva un solo canale valido ===
            active_ch_idx = self.advanced_tab.manual_ch_value.get() - 1
            channels = [active_ch_idx] if 0 <= active_ch_idx < n_ch else []

        for ch in channels:
            current_adc = adc_values[ch]
            self.channel_values[ch] = current_adc
            self.channel_history[ch].append(current_adc)

            pending = self._pending_amp[ch]
            if pending is not None:
                pending[1] -= 1
                if pending[1] <= 0:
                    self._resolve_amplitude(ch)

            n_new = new_events[ch]
            if n_new > 0:
                self.channel_particles[ch] += n_new
                self.channel_rates[ch].add(now, n_new)
                if self.channel_mask[ch]:
                    self.global_rate.add(now, n_new)
                if self._pending_amp[ch] is not None:  # la particella precedente si misura subito
                    self._resolve_amplitude(ch)
                self._pending_amp[ch] = [n_new, AMP_SETTLE_SAMPLES]
                self._global_dirty = True

            self.advanced_tab.push_sample(ch, current_adc, self.channel_particles[ch],
                                          adc_pos_values[ch], adc_neg_values[ch])

        total = sum(p for p, active in zip(self.channel_particles, self.channel_mask) if active)
        if total != self.global_count:
            self.global_count = total
            self._global_dirty = True
        self.visual_tab.push_global(total)

    def _resolve_amplitude(self, ch):
        """Misura le particelle in attesa del canale e le aggiunge all'istogramma."""
        n, _ = self._pending_amp[ch]
        self._pending_amp[ch] = None
        amplitude = self._estimate_amplitude(ch)
        if amplitude is not None:
            self.channel_events[ch][amplitude] += n
            if self.channel_mask[ch]:
                self._global_events[amplitude] += n
            self._global_dirty = True

    def _estimate_amplitude(self, ch):
        """
        Ampiezza (LSB) del gradino che ha prodotto la particella appena contata.
        Il firmware conferma una particella solo a fine finestra DSP, cioè 'Window' campioni del
        canale dopo il gradino (in Auto ~2.4 s con i valori di default): il gradino va cercato
        indietro nel tempo. Con finestre corte conteggio e gradino possono cadere nello stesso
        frame, per questo la misura si fa AMP_SETTLE_SAMPLES campioni dopo il conteggio.
        L'ampiezza è la massima distanza tra il livello attuale e i livelli della finestra di
        ricerca (mediana su 3 campioni contro i picchi di rumore).
        """
        lookback = self._event_lookback_frames() + AMP_SETTLE_SAMPLES
        vals = list(self.channel_history[ch])[-(lookback + 1):]
        if len(vals) < 8:
            return None
        level_now = sorted(vals[-3:])[1]
        past = [sorted(vals[i - 1:i + 2])[1] for i in range(1, len(vals) - 3)]
        amplitude = max(abs(level_now - v) for v in past) if past else 0
        return amplitude if amplitude >= self._min_amplitude() else None

    def _min_amplitude(self):
        """
        Il firmware conta solo gradini oltre la soglia DSP (Threshold della Dashboard): se la
        misura resta sotto metà soglia il gradino non è stato trovato e la particella non va
        nell'istogramma (la didascalia la segnala come 'not sized').
        """
        try:
            thresh = int(self.settings_tab.dsp_thresh_var.get())
        except (ValueError, AttributeError):
            thresh = 0
        return max(self.MIN_HISTO_DELTA, thresh // 2)

    def _event_lookback_frames(self):
        """Frame da guardare indietro: ritardo di conferma del firmware (Window) + margine."""
        try:
            window_fw = int(self.settings_tab.dsp_window_var.get()) * 2  # la Dashboard invia Window x2
        except (ValueError, AttributeError):
            window_fw = 100
        # Un campione per canale ogni 32 periodi LPTIM (0.75 ms) in Auto, ogni periodo in Manual
        sample_s = 32 * 0.00075 if self.advanced_tab.read_auto_var.get() else 0.00075
        return int((window_fw * sample_s + 0.8) * FRAME_RATE)

    # ---------- CICLO DI RENDER ----------
    def _render_tick(self):
        try:
            self._render_now()
        except Exception:
            self.report_callback_exception(*sys.exc_info())
        self._render_job = self.after(self._render_interval_ms, self._render_tick)

    def _render_now(self):
        now = time.perf_counter()
        tab = self.tabview.get()
        if tab == "Global":
            if self._global_dirty:
                self._force_ui_update()
            self.visual_tab.set_event_rate(self.global_rate.rate(now))
            self.visual_tab.render()
        elif tab == "Channels":
            self.advanced_tab.render()
        if self.advanced_tab.channel_windows:
            self.advanced_tab.render_windows([r.rate(now) for r in self.channel_rates])
        self._update_status_bar(now)

    def _on_tab_changed(self):
        # Disegna subito la tab appena aperta, senza aspettare il prossimo tick
        try:
            self._render_now()
        except Exception:
            self.report_callback_exception(*sys.exc_info())

    def _update_status_bar(self, now):
        dt = now - self._status_t
        if dt < 0.5:
            return
        fps = (self._rx_frames - self._status_frames) / dt
        self._status_t, self._status_frames = now, self._rx_frames
        if fps > 0.5:
            stream = f"Streaming · {fps:.1f} frames/s"
        else:
            stream = "Connected · no data" if self.ble_client is not None else "No data"
        hz = round(1000 / self._render_interval_ms)
        right = f"MTU {self._mtu}  ·  Refresh {hz} Hz" if self._mtu else f"Refresh {hz} Hz"
        texts = (stream, right)
        if texts != self._status_texts[:2]:
            self._status_stream.configure(text=stream)
            self._status_right.configure(text=right)
            self._status_texts = (stream, right, None)

    def set_refresh_interval(self, interval_seconds: float):
        try:
            value = float(interval_seconds)
            if value > 0:
                self._min_draw_interval = value
                self._render_interval_ms = max(10, int(round(value * 1000)))
        except Exception: pass

    def on_theme_changed(self):
        try: self.visual_tab.apply_theme()
        except Exception: pass
        try: self.advanced_tab.apply_theme()
        except Exception: pass
        try: self.analysis_tab.update_theme()
        except Exception: pass
        self._on_tab_changed()

    def set_material_calibration(self, a: float, b: float):
        try:
            self.visual_tab.histogram.set_calibration_params(a, b)
        except Exception as e:
            pass

    def on_close(self):
        for job in (self._ui_queue_job, self._render_job, self._rename_timeout_job):
            if job is None: continue
            try: self.after_cancel(job)
            except Exception: pass
        if self.is_logging and self.log_file: self.log_file.close()
        if self.serial and self.serial.is_open:
            try: self.serial.close()
            except Exception: pass
        if self.ble_client is not None:
            self._bt_disconnecting = True
            fut = asyncio.run_coroutine_threadsafe(self._bt_disconnect_async(), self.ble_loop)
            try: fut.result(timeout=1.0)
            except Exception: pass
        if self.ble_loop.is_running():
            self.ble_loop.call_soon_threadsafe(self.ble_loop.stop)
        self.destroy()

