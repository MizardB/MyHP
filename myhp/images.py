"""PNG-to-PPL conversion for simple HP Prime image programs."""

from __future__ import annotations

import struct
import zlib


def _png_pixels(data: bytes) -> tuple[int, int, list[tuple[int, int, int]]]:
    """Decode non-interlaced 8-bit PNGs without external dependencies."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Formato no compatible: se requiere una imagen PNG")
    pos = 8
    width = height = color_type = bit_depth = interlace = 0
    palette: list[tuple[int, int, int]] = []
    compressed = bytearray()
    while pos + 12 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4 : pos + 8]
        block = data[pos + 8 : pos + 8 + length]
        if len(block) != length:
            raise ValueError("PNG incompleto")
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", block)
        elif kind == b"PLTE":
            palette = [tuple(block[i : i + 3]) for i in range(0, len(block), 3)]
        elif kind == b"IDAT":
            compressed.extend(block)
        elif kind == b"IEND":
            break
        pos += 12 + length

    channels_by_type = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    channels = channels_by_type.get(color_type)
    if not width or not height or bit_depth != 8 or channels is None or interlace:
        raise ValueError("PNG no compatible: admite 8 bits por canal, sin entrelazado")
    stride = width * channels
    raw = zlib.decompress(compressed)
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError("Datos PNG con tamaño inesperado")

    rows: list[bytearray] = []
    offset = 0
    previous = bytearray(stride)
    for _ in range(height):
        filt = raw[offset]
        scan = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += stride + 1
        for i in range(stride):
            a = scan[i - channels] if i >= channels else 0
            b = previous[i]
            c = previous[i - channels] if i >= channels else 0
            if filt == 1:
                scan[i] = (scan[i] + a) & 255
            elif filt == 2:
                scan[i] = (scan[i] + b) & 255
            elif filt == 3:
                scan[i] = (scan[i] + ((a + b) // 2)) & 255
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                scan[i] = (scan[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif filt != 0:
                raise ValueError(f"Filtro PNG no compatible: {filt}")
        rows.append(scan)
        previous = scan

    pixels: list[tuple[int, int, int]] = []
    for row in rows:
        for x in range(width):
            i = x * channels
            if color_type == 0:
                rgb = (row[i],) * 3
            elif color_type == 2:
                rgb = tuple(row[i : i + 3])
            elif color_type == 3:
                if row[i] >= len(palette):
                    raise ValueError("Índice de paleta PNG fuera de rango")
                rgb = palette[row[i]]
            elif color_type == 4:
                rgb = (row[i],) * 3
            else:
                rgb = tuple(row[i : i + 3])
            pixels.append(rgb)
    return width, height, pixels


def _resize(
    width: int,
    height: int,
    pixels: list[tuple[int, int, int]],
    max_width: int,
    max_height: int,
) -> tuple[int, int, list[tuple[int, int, int]]]:
    scale = min(1.0, max_width / width, max_height / height)
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    resized = [
        pixels[min(height - 1, int(y * height / new_height)) * width + min(width - 1, int(x * width / new_width))]
        for y in range(new_height)
        for x in range(new_width)
    ]
    return new_width, new_height, resized


def _a1r5g5b5(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return 0x8000 | (r >> 3) << 10 | (g >> 3) << 5 | (b >> 3)


def png_to_ppl(
    data: bytes,
    program_name: str,
    max_width: int = 160,
    max_height: int = 120,
    entrypoint: str | None = None,
) -> str:
    """Create a PPL program that draws a PNG into G1, then displays it."""
    if not 1 <= max_width <= 320 or not 1 <= max_height <= 240:
        raise ValueError("El tamaño máximo debe estar entre 1×1 y 320×240")
    width, height, pixels = _png_pixels(data)
    width, height, pixels = _resize(width, height, pixels, max_width, max_height)

    # Pack each run as A1R5G5B5 color, count. Runs bound the source size while
    # preserving the full 16-bit image palette.
    runs: list[str] = []
    current = _a1r5g5b5(pixels[0])
    count = 0
    for rgb in pixels:
        color = _a1r5g5b5(rgb)
        if color == current and count < 65535:
            count += 1
        else:
            runs.extend((str(current), str(count)))
            current, count = color, 1
    runs.extend((str(current), str(count)))
    x = (320 - width) // 2
    y = (240 - height) // 2
    name = (entrypoint or program_name).upper()
    source = (
        f"EXPORT {name}()\nBEGIN\n"
        "  LOCAL C,I,X,Y,J,N;\n"
        f"  C:={{{','.join(runs)}}};\n"
        "  I:=1;X:=0;Y:=0;\n"
        f"  DIMGROB_P(G1,{width},{height},0);\n"
        "  WHILE I<=SIZE(C) DO\n"
        "    N:=C(I+1);\n"
        "    FOR J FROM 1 TO N DO\n"
        "      PIXON_P(G1,X,Y,C(I));\n"
        "      X:=X+1;\n"
        f"      IF X=={width} THEN X:=0;Y:=Y+1;END;\n"
        "    END;\n"
        "    I:=I+2;\n"
        "  END;\n"
        f"  BLIT_P(G0,{{{x},{y}}},{{{x + width - 1},{y + height - 1}}},G1);\n"
        "  WAIT(0);\n"
        "END;\n"
    )
    if len(source.encode("utf-16le")) > 60_000:
        raise ValueError("El visor supera el límite seguro de tamaño PPL; reduce --width o --height")
    return source


def png_icon(data: bytes) -> bytes:
    """Resize a PNG to the HP Prime custom-app icon dimensions (73×74)."""
    width, height, pixels = _png_pixels(data)
    width, height, pixels = _resize(width, height, pixels, 73, 74)
    x_offset = (73 - width) // 2
    y_offset = (74 - height) // 2
    rows = []
    for y in range(74):
        row = bytearray([0])
        for x in range(73):
            source_x = x - x_offset
            source_y = y - y_offset
            if 0 <= source_x < width and 0 <= source_y < height:
                r, g, b = pixels[source_y * width + source_x]
                row.extend((r, g, b, 255))
            else:
                row.extend((0, 0, 0, 0))
        rows.append(bytes(row))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", 73, 74, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
    png += chunk(b"IEND", b"")
    return png
