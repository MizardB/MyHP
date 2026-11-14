"""Build a PPL image viewer as an HP Prime application package."""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

from myhp.formats import calc_crc16
from myhp.images import png_icon

DATA_DIR = Path(__file__).parent / "data" / "app_templates"
GALLERY_DATA_DIR = Path(__file__).parent / "data" / "gallery_templates"


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


def gallery_ppl_source(name: str) -> str:
    """Generate the Gallery PPL image viewer source configured to open the first image on start."""
    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", name.upper())
    if not safe_name or safe_name[0].isdigit():
        safe_name = f"APP_{safe_name}"
    template_src = (GALLERY_DATA_DIR / "Gallery.hpp").read_text(encoding="utf-8")
    source = template_src.replace("EXPORT Gallery()", f"EXPORT {safe_name}()", 1)
    source = source.replace(
        """    STARTVIEW(6,1);
  END;
END;""",
        """    STARTVIEW(6,1);
    IF length(FILE_LIST)>0
    THEN
      WAIT(0.1);
      CURRENT_FILE:=1;
      Open_File();
    END;
  END;
END;""",
        1,
    )
    source = source.replace(
        """    CHOOSE(CURRENT_FILE, "Select File to Open", FILE_LIST);
    Open_File();""",
        """    IF CHOOSE(CURRENT_FILE, "Select File to Open", FILE_LIST)<>0
    THEN
      Open_File();
    ELSE
      STARTVIEW(6,1);
    END;""",
        1,
    )
    source = source.replace(
        """  UNTIL STOP_GALLERY==1;
  Open_File_Dialog();
  START();
  RETURN;""",
        """  UNTIL STOP_GALLERY==1;
  Open_File_Dialog();
  RETURN;""",
        1,
    )
    return source


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


def build_gallery_app_directory(
    name: str,
    images: str | Path | list[str | Path],
    icon: bytes | None = None,
    output_dir: str | Path = ".",
) -> Path:
    """Create a native Gallery app directory containing the original PNG/JPG/BMP images."""
    if not name or len(name.encode("utf-16le")) > 255:
        raise ValueError("El nombre de la aplicación no es válido")

    valid_extensions = {".png", ".jpg", ".jpeg", ".bmp"}
    collected_files: list[Path] = []

    def _collect_from_path(p: Path) -> list[Path]:
        if p.is_file():
            return [p]
        elif p.is_dir():
            files = [
                f for f in p.rglob("*")
                if f.is_file() and f.suffix.lower() in valid_extensions
            ]
            return sorted(files, key=lambda f: f.name.lower())
        else:
            raise FileNotFoundError(f"No se encontró el archivo o directorio de imagen: {p}")

    if isinstance(images, (str, Path)):
        collected_files = _collect_from_path(Path(images))
    elif isinstance(images, (list, tuple)):
        for item in images:
            collected_files.extend(_collect_from_path(Path(item)))
    else:
        raise TypeError(f"Tipo no admitido para images: {type(images)}")

    if not collected_files:
        raise ValueError("No se encontraron imágenes válidas para la galería")

    # Remove duplicates preserving order
    seen = set()
    unique_files: list[Path] = []
    for f in collected_files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)

    safe_name = name.upper()
    folder = Path(output_dir) / f"{safe_name}.hpappdir"
    folder.mkdir(parents=True, exist_ok=True)

    # 1. Base app descriptor from Gallery template
    (folder / f"{safe_name}.hpapp").write_bytes((GALLERY_DATA_DIR / "Gallery.hpapp").read_bytes())

    # 2. Base note from Gallery template
    (folder / f"{safe_name}.hpappnote").write_bytes((GALLERY_DATA_DIR / "Gallery.hpappnote").read_bytes())

    # 3. Base program source with EXPORT <SAFE_NAME>() injected into Gallery.hpappprgm container
    src = gallery_ppl_source(safe_name)
    prgm_template = (GALLERY_DATA_DIR / "Gallery.hpappprgm").read_bytes()
    (folder / f"{safe_name}.hpappprgm").write_bytes(_write_gallery_hpprgm(src, prgm_template))

    # 4. Copy all images into app directory
    for img_path in unique_files:
        (folder / img_path.name).write_bytes(img_path.read_bytes())

    # 5. Icon handling
    if icon is not None:
        (folder / "icon.png").write_bytes(icon)
    else:
        # Check first image
        first_img = unique_files[0]
        icon_bytes = None
        try:
            icon_bytes = png_icon(first_img.read_bytes())
        except Exception:
            icon_bytes = None

        if icon_bytes is not None:
            (folder / "icon.png").write_bytes(icon_bytes)
        else:
            (folder / "icon.png").write_bytes((GALLERY_DATA_DIR / "icon.png").read_bytes())

    return folder


def _write_gallery_hpprgm(source: str, template: bytes) -> bytes:
    length_offsets, start, end = _source_record(template)
    normalized = source.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    replacement = (normalized + "\0").encode("utf-16le")
    delta = len(replacement) - (end - start)
    output = bytearray(template[:start] + replacement + template[end:])
    for offset in length_offsets:
        struct.pack_into("<I", output, offset, struct.unpack_from("<I", output, offset)[0] + delta)
    return bytes(output)


def build_app_packet(name: str, folder: str | Path) -> bytes:
    """Build the compressed CMD_APP (0xF7 0x03) packet used by HP Prime link."""
    folder = Path(folder)
    name_data = name.encode("utf-16le")
    if len(name_data) > 255:
        raise ValueError("El nombre de la aplicación supera el límite del protocolo")

    # Uncompressed container structure:
    # Byte 0: 0x02 (APP type)
    # Byte 1: name_len in bytes (uint8)
    # Bytes 2..3: CRC16 (little-endian uint16, computed over synthetic virtual packet)
    # Bytes 4..4+name_len: name in UTF-16LE
    # 4 bytes: desc_len (uint32 big-endian)
    # desc_len bytes: .hpapp content
    # 4 bytes: note_len (uint32 big-endian)
    # note_len bytes: .hpappnote content
    # 4 bytes: prgm_len (uint32 big-endian)
    # prgm_len bytes: PPL source in UTF-16LE (with trailing null char)
    # For each additional file (e.g. icon.png):
    #   4 bytes: total item length (len(utf16_name) + 2 + len(file_bytes))
    #   utf16_name bytes
    #   2 bytes: \0\0
    #   file binary bytes
    app_data = bytearray()
    app_data.append(0x02)
    app_data.append(len(name_data))
    app_data.extend(b"\0\0")  # placeholder for CRC16
    app_data.extend(name_data)

    descriptor = (folder / f"{name}.hpapp").read_bytes()
    app_data.extend(struct.pack(">I", len(descriptor)))
    app_data.extend(descriptor)

    note = (folder / f"{name}.hpappnote").read_bytes()
    app_data.extend(struct.pack(">I", len(note)))
    app_data.extend(note)

    program_file = (folder / f"{name}.hpappprgm").read_bytes()
    source = read_hpprgm_source(program_file)
    source_bytes = (source + "\0").encode("utf-16le")
    app_data.extend(struct.pack(">I", len(source_bytes)))
    app_data.extend(source_bytes)

    for path in sorted(folder.iterdir()):
        if path.name in (f"{name}.hpapp", f"{name}.hpappnote", f"{name}.hpappprgm"):
            continue
        file_name = path.name.encode("utf-16le")
        content = path.read_bytes()
        app_data.extend(struct.pack(">I", len(file_name) + 2 + len(content)))
        app_data.extend(file_name)
        app_data.extend(b"\0\0")
        app_data.extend(content)

    # Compute CRC16 over synthetic virtual packet [0xF7, 0x03, len(app_data)[BE], app_data with CRC=0]
    fake_pkt = bytearray(b"\xF7\x03" + struct.pack(">I", len(app_data)) + app_data)
    fake_pkt[8:10] = b"\0\0"
    crc = calc_crc16(fake_pkt, len(fake_pkt))
    app_data[2:4] = struct.pack("<H", crc)

    compressed = zlib.compress(bytes(app_data), level=1)

    # Virtual packet 0xF7 0x03:
    # Bytes 0..1: 0xF7, 0x03
    # Bytes 2..5: compressed length + 4 (uint32 big-endian)
    # Bytes 6..9: uncompressed length (uint32 little-endian)
    # Bytes 10..end: compressed zlib stream
    packet = (
        b"\xF7\x03"
        + struct.pack(">I", len(compressed) + 4)
        + struct.pack("<I", len(app_data))
        + compressed
    )
    return packet
