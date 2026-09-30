"""
Crea il file .hex con il nome di un sensore DUST, da programmare con STM32CubeProgrammer.

Il nome va nella pagina 125 del flash (0x080FA000), che un normale caricamento del firmware
(CubeIDE, CubeProgrammer senza "Full chip erase") non cancella. Il firmware lo legge all'avvio
(Core/Src/device_config.c) e lo usa nell'advertising BLE al posto di DUST_X.
Lo stesso nome si può impostare anche senza programmatore, dalla GUI (tab Connection).

Uso:
    python make_device_name.py DUST_6                 -> DUST_6_name.hex
    python make_device_name.py DUST_6 -o nome.hex

Programmazione (dopo o insieme al firmware):
    STM32_Programmer_CLI -c port=SWD -w DUST_6_name.hex -v
oppure CubeProgrammer: Erasing & Programming -> file .hex -> Start Programming
("Full chip erase" NON selezionato, altrimenti si cancella anche il firmware).
"""
import argparse
import re
import struct
import sys
import zlib

# Deve corrispondere a device_config.c
DEVCFG_ADDR = 0x080FA000          # FLASH_BASE + pagina 125 (CFG_SNVMA_START_SECTOR_ID - 1) * 8 KB
DEVCFG_MAGIC = 0x47464344         # "DCFG"
DEVCFG_VERSION = 1
NAME_MAX_LEN = 10                 # advertising legacy: 31 - flag (3) - dati costruttore (16) - intestazione (2)
NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,%d}" % NAME_MAX_LEN)


def build_record(name: str) -> bytes:
    """Record di 48 byte: magic, versione, lunghezza, nome[32], riservato, CRC-32 (come zlib.crc32)."""
    raw = name.encode("ascii")
    body = struct.pack("<IHH32sI", DEVCFG_MAGIC, DEVCFG_VERSION, len(raw), raw.ljust(32, b"\0"), 0xFFFFFFFF)
    return body + struct.pack("<I", zlib.crc32(body))


def to_intel_hex(address: int, data: bytes) -> str:
    def record(rtype, offset, payload):
        b = bytes([len(payload), (offset >> 8) & 0xFF, offset & 0xFF, rtype]) + payload
        return ":" + (b + bytes([(-sum(b)) & 0xFF])).hex().upper()

    lines = [record(0x04, 0, struct.pack(">H", address >> 16))]      # indirizzo lineare esteso
    for i in range(0, len(data), 16):
        lines.append(record(0x00, (address + i) & 0xFFFF, data[i:i + 16]))
    lines.append(record(0x01, 0, b""))                                 # fine file
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create the .hex file that stores a DUST sensor name in flash.")
    parser.add_argument("name", help="device name, e.g. DUST_6 (max 10 characters: letters, digits, '_' or '-')")
    parser.add_argument("-o", "--output", help="output .hex file (default: <name>_name.hex)")
    args = parser.parse_args(argv)

    if not NAME_RE.fullmatch(args.name):
        parser.error(f"invalid name '{args.name}': 1-{NAME_MAX_LEN} letters, digits, '_' or '-'")
    if not args.name.startswith("DUST_"):
        print("warning: the GUI lists only devices whose name starts with DUST_", file=sys.stderr)

    output = args.output or f"{args.name}_name.hex"
    with open(output, "w", newline="\n") as f:
        f.write(to_intel_hex(DEVCFG_ADDR, build_record(args.name)))
    print(f"{output}: name '{args.name}' at 0x{DEVCFG_ADDR:08X}")
    print(f"program it with:  STM32_Programmer_CLI -c port=SWD -w {output} -v")


if __name__ == "__main__":
    main()
