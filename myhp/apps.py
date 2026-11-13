"""Build a PPL image viewer as an HP Prime application package."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from myhp.formats import calc_crc16

DATA_DIR = Path(__file__).parent / "data" / "app_templates"


def _source_record(template: bytes) -> tuple[list[int], int, int]:
    """Find the UTF-16LE PPL source record and all containers holding it."""
    if template[:4] != b"\x7c\x61\x8a\xb2":
        raise ValueError("La plantilla PPL no tiene la cabecera HP Prime esperada")
    candidates: list[tuple[int, int]] = []
    for offset in range(12, len(template) - 12):
        if offset + 9 >= len(template) or template[offset + 9] != 0:
            continue
        first = template[offset + 8]
        if not (first == 10 or 0x20 <= first < 0x7F or first >= 0xA0):
            continue
        end = offset + 4 + struct.unpack_from("<I", template, offset)[0]
        if end > len(template) or end - (offset + 8) < 8:
            continue
        raw = template[offset + 8 : end]
        if len(raw) % 2 or raw[-2:] != b"\0\0":
            continue
        try:
            source = raw[:-2].decode("utf-16le")
        except UnicodeDecodeError:
            continue
        if source and sum(c.isprintable() or c in "\n\t" for c in source[:2000]) >= 0.9 * min(len(source), 2000):
            candidates.append((offset, end))
    if not candidates:
        raise ValueError("La plantilla PPL no contiene una fuente editable")
    end = max(candidates, key=lambda item: item[1] - item[0])[1]
    source_offset = max(offset for offset, candidate_end in candidates if candidate_end == end)
    length_offsets = [
        offset
        for offset in range(12, source_offset + 1)
        if offset + 4 + struct.unpack_from("<I", template, offset)[0] == end
    ]
    return length_offsets, source_offset + 8, end


def _write_hpprgm(source: str) -> bytes:
    template = (DATA_DIR / "code.hpprgm").read_bytes()
    length_offsets, start, end = _source_record(template)
    normalized = source.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    replacement = (normalized + "\0").encode("utf-16le")
    delta = len(replacement) - (end - start)
    output = bytearray(template[:start] + replacement + template[end:])
    for offset in length_offsets:
        struct.pack_into("<I", output, offset, struct.unpack_from("<I", output, offset)[0] + delta)
    return bytes(output)


def read_hpprgm_source(program: bytes) -> str:
    """Extract the UTF-16LE source block from an HP Prime program container."""
    _, start, end = _source_record(program)
    return program[start : end - 2].decode("utf-16le")


def build_app_directory(
    name: str,
    source: str,
    icon: bytes,
    output_dir: str | Path = ".",
) -> Path:
    """Create a portable .hpappdir folder using the bundled G2 wrappers."""
    if not name or len(name.encode("utf-16le")) > 255:
        raise ValueError("El nombre de la aplicación no es válido")
    folder = Path(output_dir) / f"{name}.hpappdir"
    folder.mkdir(parents=True, exist_ok=True)
    for template_name, target_name in (
        ("blank.hpapp", f"{name}.hpapp"),
        ("note.hpappnote", f"{name}.hpappnote"),
    ):
        (folder / target_name).write_bytes((DATA_DIR / template_name).read_bytes())
    (folder / f"{name}.hpappprgm").write_bytes(_write_hpprgm(source))
    (folder / "icon.png").write_bytes(icon)
    return folder


def build_app_packet(name: str, folder: str | Path) -> bytes:
    """Build the compressed CMD_FILE app packet used by the Prime link."""
    folder = Path(folder)
    name_data = name.encode("utf-16le")
    if len(name_data) > 255:
        raise ValueError("El nombre de la aplicación supera el límite del protocolo")

    app_data = bytearray(b"\0\0\0\0")
    app_data.extend((0x02, len(name_data)))
    app_data.extend(name_data)

    descriptor = (folder / f"{name}.hpapp").read_bytes()
    app_data.extend(struct.pack(">I", len(descriptor)))
    app_data.extend(descriptor)
    note = (folder / f"{name}.hpappnote").read_bytes()
    app_data.extend(struct.pack(">I", len(note)))
    app_data.extend(note)

    # The app-file section begins with a two-byte separator record.
    app_data.extend(b"\0\0\0\x02\0\0")
    for path in sorted(folder.iterdir()):
        if path.name in (f"{name}.hpapp", f"{name}.hpappnote", f"{name}.hpappprgm"):
            continue
        file_name = path.name.encode("utf-16le")
        content = path.read_bytes()
        app_data.extend(struct.pack(">I", len(file_name) + 2 + len(content)))
        app_data.extend(file_name)
        app_data.extend(b"\0\0")
        app_data.extend(content)

    program = (folder / f"{name}.hpappprgm").read_bytes()
    file_name = f"{name}.hpappprgm".encode("utf-16le")
    app_data.extend(struct.pack(">I", len(file_name) + 2 + len(program)))
    app_data.extend(file_name)
    app_data.extend(b"\0\0")
    app_data.extend(program)
    struct.pack_into(">I", app_data, 0, len(app_data) - 4)

    compressed = zlib.compress(bytes(app_data))
    packet = bytearray(b"\xF7\x03" + struct.pack(">I", len(compressed) + 4) + b"\0\0\0\0" + compressed)
    crc = calc_crc16(packet, len(compressed) + 4)
    packet[6:8] = struct.pack("<H", crc)
    return bytes(packet)
