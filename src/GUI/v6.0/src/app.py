# app.py
import sys
import os
from PIL import Image
import customtkinter as ctk
import time
import serial
from serial.tools import list_ports
import asyncio
import threading
from bleak import BleakScanner, BleakClient
from connection_tab import ConnectionTab
from visual_tab import VisualTab
from advanced_tab import AdvancedTab
from settings_tab import SettingsTab
from analysis_tab import AnalysisTab 
from collections import deque
import datetime 

# --------- UUID BLE ---------
BT_SERVICE_UUID       = "00000000-0001-11e1-9ab4-0002a5d5c51b"
BT_CHAR_MYDATA_UUID   = "00c00000-0001-11e1-ac36-0002a5d5c51b"  # notify
BT_CHAR_RECVDATA_UUID = "00c10000-0001-11e1-ac36-0002a5d5c51b"  # write

# --------- Costanti protocollo DUST ---------
DUST_CHANNELS = 32
FRAME_SYNC1 = 0xAA
FRAME_SYNC2 = 0x55
FRAME_LEN = 2 + (DUST_CHANNELS * 5) + 2  # Totale 164 bytes


def resource_path(relative_path):
    """ 
    Ottiene il percorso assoluto alle risorse.
    Funziona sia in modalità sviluppo che dopo essere stato compilato con PyInstaller via sys._MEIPASS 
    """
    try:
        # PyInstaller crea una cartella temporanea in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Profiling semplice delle prestazioni
        self._profile_last_log = time.perf_counter()
        self._profile_frame_count = 0
        self._profile_last_frame_ms = 0.0
        self._profile_total_frame_ms = 0.0

        # === ISTOGRAMMI E MASCHERE CANALI ===
        self.HISTO_BINS_COUNT = 64
        self.HISTO_MAX_VAL = 3000
        
        # NUOVO: Salviamo la storia dell'istogramma PER SINGOLO CANALE
        self.channel_histograms = [[0] * self.HISTO_BINS_COUNT for _ in range(DUST_CHANNELS)]
        
        # NUOVO: Array di maschera (True = Attivo, False = Ignorato)
        self.channel_mask = [True] * DUST_CHANNELS
        
        # Buffer finestra mobile per calcolo salto (5 campioni)
        self.JUMP_WINDOW_SIZE = 5
        self.channel_buffers = [deque(maxlen=self.JUMP_WINDOW_SIZE) for _ in range(DUST_CHANNELS)]
        
        # MEMORIA PER RILEVARE L'INCREMENTO DEL CONTATORE
        self.last_total_particles = [0] * DUST_CHANNELS
        
        # Filtro minimo per il salto
        self.MIN_HISTO_DELTA = 20 
        # ==================================================

        self.current_threshold = 10.0     
        
        self.channel_values = [0 for _ in range(DUST_CHANNELS)]
        self.channel_particles = [0 for _ in range(DUST_CHANNELS)]
        self.global_count = 0 
        self.channel_history = [deque(maxlen=200) for _ in range(DUST_CHANNELS)]

        # Throttling del disegno grafici
        self._last_draw_time = 0.0
        self._min_draw_interval = 0.1  # 10 FPS
        
        # --- GESTIONE LOG SU FILE ---
        self.is_logging = False
        self.log_file = None
        # ---------------------------- #

        self.title("DUST Monitor")
        self.geometry("1000x750")
        self.minsize(800, 500)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # ----- Barra superiore con loghi dipendenti dal tema -----
        try:
            left_light = Image.open(resource_path(os.path.join("img", "polimiD.png")))
            left_dark = Image.open(resource_path(os.path.join("img", "polimiW.png")))
            self.logo_l = ctk.CTkImage(light_image=left_light, dark_image=left_dark, size=(190, 60))

            center_light = Image.open(resource_path(os.path.join("img", "ESA_White.png")))
            center_dark = Image.open(resource_path(os.path.join("img", "ESA_White.png")))
            self.logo_c = ctk.CTkImage(light_image=center_light, dark_image=center_dark, size=(60, 60))

            right_light = Image.open(resource_path(os.path.join("img", "i3n.png")))
            right_dark = Image.open(resource_path(os.path.join("img", "i3nW.png")))
            self.logo_r = ctk.CTkImage(light_image=right_light, dark_image=right_dark, size=(200, 48))
        except Exception as e:
            print("Errore nel caricamento dei loghi:", e)
            self.logo_l = None
            self.logo_c = None
            self.logo_r = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(side="top", fill="x", padx=10, pady=(5, 0))
        header.grid_rowconfigure(0, weight=1)
        header.grid_columnconfigure(0, weight=0)
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(2, weight=0)

        if self.logo_l is not None:
            ctk.CTkLabel(header, text="", image=self.logo_l).grid(row=0, column=0, sticky="w")

        title_label = ctk.CTkLabel(
            header,
            text="DUST Tracker Monitor",
            font=ctk.CTkFont(family="Segoe UI", size=32, weight="bold"),
            anchor="center",
        )
        title_label.grid(row=0, column=1, pady=(10, 10), padx=(120, 0))

        if self.logo_c is not None or self.logo_r is not None:
            right_frame = ctk.CTkFrame(header, fg_color="transparent")
            right_frame.grid(row=0, column=2, sticky="e", padx=(0, 10))
            if self.logo_c is not None:
                ctk.CTkLabel(right_frame, text="", image=self.logo_c).pack(side="left", padx=(0, 30))
            if self.logo_r is not None:
                ctk.CTkLabel(right_frame, text="", image=self.logo_r).pack(side="left")

        # --- Serial e BLE ---
        self.serial = None
        self.ble_client = None
        self._bt_scan_results = {}

        self.ble_loop = asyncio.new_event_loop()
        self.ble_thread = threading.Thread(target=self._ble_loop_runner, daemon=True)
        self.ble_thread.start()

        self._dust_rx_buffer = bytearray()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # TAB VIEW
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_connection_page = self.tabview.add("Connection")
        self.tab_visual_page = self.tabview.add("Global")
        self.tab_advanced_page = self.tabview.add("Channels")
        self.tab_settings_page = self.tabview.add("Dashboard")
        self.tab_analysis_page = self.tabview.add("File Analysis")

        self.connection_tab = ConnectionTab(self.tab_connection_page, controller=self)
        self.connection_tab.pack(fill="both", expand=True)
        
        self.visual_tab = VisualTab(self.tab_visual_page, controller=self)
        self.visual_tab.pack(fill="both", expand=True)
        self.visual_tab.histogram.num_bins = self.HISTO_BINS_COUNT
        self.visual_tab.histogram.max_val = self.HISTO_MAX_VAL
        
        self.advanced_tab = AdvancedTab(self.tab_advanced_page, controller=self, num_channels=DUST_CHANNELS)
        self.advanced_tab.pack(fill="both", expand=True)
        
        self.settings_tab = SettingsTab(self.tab_settings_page, controller=self)
        self.settings_tab.pack(fill="both", expand=True)
        
        self.analysis_tab = AnalysisTab(self.tab_analysis_page, controller=self)
        self.analysis_tab.pack(fill="both", expand=True)
        
        self._refresh_serial_ports()


    # ---------- NUOVO: GESTIONE MASCHERA CANALI ----------
    def set_channel_active(self, ch_idx: int, is_active: bool):
        """Disabilita o abilita logicamente e visivamente un canale."""
        # 1. Aggiorna lo stato in memoria
        self.channel_mask[ch_idx] = is_active
        
        # 2. Aggiorna la vista sbiadita nella Advanced Tab
        if hasattr(self, "advanced_tab"):
            self.advanced_tab.set_channel_active(ch_idx, is_active)
            
        # 3. Forza un ricalcolo globale immediato per la Visual Tab
        self._force_ui_update()

        # 4. NUOVO: Aggiorna i grafici nell'Analysis Tab (se c'è un file caricato)
        if hasattr(self, "analysis_tab") and self.analysis_tab.data is not None:
            self.analysis_tab.create_thumbnails()

    def _force_ui_update(self):
        """Ricalcola il sum e l'istogramma tenendo conto delle maschere."""
        current_global_sum = 0
        current_global_hist = [0] * self.HISTO_BINS_COUNT
        
        for ch in range(DUST_CHANNELS):
            if self.channel_mask[ch]:
                current_global_sum += self.channel_particles[ch]
                for b in range(self.HISTO_BINS_COUNT):
                    current_global_hist[b] += self.channel_histograms[ch][b]
                    
        self.global_count = current_global_sum
        self.visual_tab.update_global(self.global_count, current_global_hist)
    # -----------------------------------------------------

    def set_logging_state(self, active: bool):
        if active:
            if not self.is_logging:
                try:
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
                    date_str = now.strftime("%Y-%m-%d %H:%M:%S") # Per l'header interno
                    filename = f"dust_log_{timestamp}.txt"
                    self.log_file = open(filename, "w")
                    self.is_logging = True
                    
                    # --- NUOVO: SCRITTURA METADATI NELL'HEADER ---
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

    def _log(self, text: str):
        self.connection_tab.log(text)

    def _get_serial_ports(self):
        ports = list_ports.comports()
        return [p.device for p in ports] or ["No ports found"]

    def _refresh_serial_ports(self):
        ports = self._get_serial_ports()
        self.connection_tab.set_serial_ports(ports)
        self._log("[INFO] Serial ports refreshed")

    def _on_bt_scan(self):
        self._log("[BT] Scanning for BLE devices...")
        async def do_scan():
            devices = await BleakScanner.discover(timeout=3.0)
            dust_devices = [d for d in devices if d.name and d.name.startswith("DUST_")]
            addr_map = {d.name: d.address for d in dust_devices}
            names = list(addr_map.keys())
            return names, addr_map

        future = asyncio.run_coroutine_threadsafe(do_scan(), self.ble_loop)

        def done_cb(fut):
            try:
                names, addr_map = fut.result()
            except Exception as err:
                self.after(0, lambda e: self._log(f"[BT] Scan error: {err}"))
                return
            def update_ui():
                self._bt_scan_results = addr_map
                self.connection_tab.set_bt_devices(names)
                if names: self._log(f"[BT] Found: {', '.join(names)}")
                else: self._log("[BT] No DUST_ devices found")
            self.after(0, update_ui)

        future.add_done_callback(done_cb)

    def _on_bt_connect(self):
        if self.ble_client is not None:
            self._log("[BT] Disconnecting...")
            future = asyncio.run_coroutine_threadsafe(self._bt_disconnect_async(), self.ble_loop)
            def done_cb(fut):
                try: fut.result()
                except Exception as err: self.after(0, lambda: self._log(f"[BT] Disconnect error: {err}"))
                else: self.after(0, lambda: self._log("[BT] Disconnected"))
                finally: self.ble_client = None
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
                self.after(0, lambda: self._log(f"[BT] Connect error: {err}"))
                return
            if ok: self.after(0, lambda: self._log("[BT] Connected successfully"))
            else: self.after(0, lambda: self._log("[BT] Connection failed"))
        future.add_done_callback(done_cb)

    async def _bt_connect_async(self, address: str) -> bool:
        try:
            client = BleakClient(address)
            await client.connect()
            await asyncio.sleep(0.4)
            if not client.is_connected: return False
            self.ble_client = client
            try: await client.start_notify(BT_CHAR_MYDATA_UUID, self._bt_notification_handler)
            except Exception as err:
                await asyncio.sleep(0.5)
                try: await client.start_notify(BT_CHAR_MYDATA_UUID, self._bt_notification_handler)
                except Exception as err2:
                    self.after(0, lambda: self._log(f"[BT] start_notify error: {err2}"))
                    return False
            return True
        except Exception as e:
            self.after(0, lambda: self._log(f"[BT] Connect exception: {e}"))
            return False

    async def _bt_disconnect_async(self):
        if self.ble_client is not None:
            try:
                try: await self.ble_client.stop_notify(BT_CHAR_MYDATA_UUID)
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
            except Exception as err: self.after(0, lambda: self._log(f"[BT] Write error: {err}"))
            else: self.after(0, lambda: self._log("[BT] Command sent OK"))
        future.add_done_callback(done_cb)

    def _on_send_text(self, text: str):
        if not text: return
        self._bt_send_command(text.encode("ascii", errors="ignore"))

    def _on_start_acquisition(self):
        # RESET ISTOGRAMMA E BUFFER ALL'AVVIO
        self.channel_histograms = [[0] * self.HISTO_BINS_COUNT for _ in range(DUST_CHANNELS)]
        self.visual_tab.update_global(0, [0] * self.HISTO_BINS_COUNT)
        
        for buf in self.channel_buffers:
            buf.clear()
        
        self.last_total_particles = [0] * DUST_CHANNELS
        self._bt_send_command(b'Cb')

    def _on_stop_acquisition(self):
        self._bt_send_command(b'0')

    def _bt_notification_handler(self, sender, data: bytes):
        hex_str = " ".join(f"{b:02X}" for b in data)
        data_copy = bytes(data)
        self.after(0, lambda: self._handle_bt_message(hex_str, data_copy))

    def _handle_bt_message(self, hex_text: str, raw: bytes):
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
        now = time.perf_counter()
        
        is_auto_mode = self.advanced_tab.read_auto_var.get()
        
        if not is_auto_mode:
            # === MODALITÀ MANUALE ===
            active_ch_idx = self.advanced_tab.manual_ch_value.get() - 1
            
            if 0 <= active_ch_idx < min(DUST_CHANNELS, len(adc_values)):
                current_adc = adc_values[active_ch_idx]
                current_total_acc = particles_values[active_ch_idx]
                
                self.channel_buffers[active_ch_idx].append(current_adc)
                
                prev_total = self.last_total_particles[active_ch_idx]
                new_events = current_total_acc - prev_total
                if new_events < 0: 
                    new_events += 256
                self.last_total_particles[active_ch_idx] = current_total_acc
                
                self.channel_values[active_ch_idx] = current_adc
                self.channel_particles[active_ch_idx] = current_total_acc
                
                if new_events > 0:
                    buf = self.channel_buffers[active_ch_idx]
                    if len(buf) > 0:
                        window_delta = max(buf) - min(buf)
                        if window_delta >= self.MIN_HISTO_DELTA:
                            bin_idx = int((window_delta / self.HISTO_MAX_VAL) * self.HISTO_BINS_COUNT)
                            bin_idx = max(0, min(self.HISTO_BINS_COUNT - 1, bin_idx))
                            self.channel_histograms[active_ch_idx][bin_idx] += new_events
                            
                self.channel_history[active_ch_idx].append(current_adc)
                
            # Forza l'aggiornamento UI usando la logica delle maschere
            if now - self._last_draw_time >= self._min_draw_interval:
                self._last_draw_time = now
                self._force_ui_update()
                
                if 0 <= active_ch_idx < len(self.channel_values):
                    self.advanced_tab.update_channel(
                        active_ch_idx, 
                        self.channel_values[active_ch_idx], 
                        self.channel_particles[active_ch_idx],
                        adc_pos=adc_pos_values[active_ch_idx],
                        adc_neg=adc_neg_values[active_ch_idx]
                    )
            return

        
        # === MODALITÀ AUTOMATICA ===
        for ch in range(min(DUST_CHANNELS, len(adc_values))):
            current_adc = adc_values[ch]
            current_total_acc = particles_values[ch]

            self.channel_buffers[ch].append(current_adc)
            prev_total = self.last_total_particles[ch]
            new_events = current_total_acc - prev_total
            if new_events < 0: 
                new_events += 256
            self.last_total_particles[ch] = current_total_acc
            
            self.channel_values[ch] = current_adc
            self.channel_particles[ch] = current_total_acc

            if new_events > 0:
                buf = self.channel_buffers[ch]
                if len(buf) > 0:
                    window_delta = max(buf) - min(buf)
                    if window_delta >= self.MIN_HISTO_DELTA:
                        bin_idx = int((window_delta / self.HISTO_MAX_VAL) * self.HISTO_BINS_COUNT)
                        bin_idx = max(0, min(self.HISTO_BINS_COUNT - 1, bin_idx))
                        self.channel_histograms[ch][bin_idx] += new_events

        if now - self._last_draw_time < self._min_draw_interval:
            return
        self._last_draw_time = now

        # Aggiorna Visual Tab con le maschere attive
        self._force_ui_update()

        # Aggiorna la Advanced Tab
        for ch in range(min(DUST_CHANNELS, len(adc_values))):
            self.channel_history[ch].append(self.channel_values[ch])
            self.advanced_tab.update_channel(
                ch, 
                self.channel_values[ch], 
                self.channel_particles[ch],
                adc_pos=adc_pos_values[ch],
                adc_neg=adc_neg_values[ch]
            )

    def set_refresh_interval(self, interval_seconds: float):
        try:
            value = float(interval_seconds)
            if value > 0: self._min_draw_interval = value
        except Exception: pass

    def on_theme_changed(self):
        try: self.visual_tab.global_graph.redraw()
        except Exception: pass
        try: self.visual_tab.histogram.redraw()
        except Exception: pass
        try:
            for preview in self.advanced_tab.channel_previews:
                preview.graph.redraw()
        except Exception: pass
        try: self.analysis_tab.update_theme()
        except Exception: pass

    def set_material_calibration(self, a: float, b: float):
        try:
            self.visual_tab.histogram.set_calibration_params(a, b)
        except Exception as e:
            pass

    def on_close(self):
        if self.is_logging and self.log_file: self.log_file.close()
        if self.serial and self.serial.is_open:
            try: self.serial.close()
            except Exception: pass
        if self.ble_client is not None:
            fut = asyncio.run_coroutine_threadsafe(self._bt_disconnect_async(), self.ble_loop)
            try: fut.result(timeout=1.0)
            except Exception: pass
        if self.ble_loop.is_running():
            self.ble_loop.call_soon_threadsafe(self.ble_loop.stop)
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()