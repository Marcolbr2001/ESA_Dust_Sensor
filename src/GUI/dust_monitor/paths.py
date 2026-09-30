# paths.py
"""
Tutti i percorsi della GUI in un solo posto.

Struttura della cartella (GUI/v6.0):
    main.py            avvio della GUI
    dust_monitor/      script (questo pacchetto)
    resources/img/     immagini: loghi e foto dei materiali
    database/          database materiali (materials.json)
    saved_data/        dati salvati dalla GUI
        logs/          "Save to file": dust_log_<data>_<ora>.txt
        sd_card/       copia qui i DATA.BIN presi dalla SD ("Load SD file" parte da questa cartella)
        dummy/         file di prova creati con "Gen. Dummy"

Da eseguibile PyInstaller le risorse sono dentro l'eseguibile (sys._MEIPASS), mentre
saved_data/ viene creata accanto al .exe, dove si può scrivere.
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    BUNDLE_DIR = APP_DIR

IMG_DIR = os.path.join(BUNDLE_DIR, "resources", "img")

DATA_DIR = os.path.join(APP_DIR, "saved_data")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
SD_DIR = os.path.join(DATA_DIR, "sd_card")
DUMMY_DIR = os.path.join(DATA_DIR, "dummy")


def image(name):
    return os.path.join(IMG_DIR, name)


def database_file(name):
    """Prima il database accanto all'eseguibile (modificabile), poi quello impacchettato."""
    local = os.path.join(APP_DIR, "database", name)
    if os.path.exists(local):
        return local
    return os.path.join(BUNDLE_DIR, "database", name)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def ensure_data_dirs():
    for path in (LOGS_DIR, SD_DIR, DUMMY_DIR):
        ensure_dir(path)
