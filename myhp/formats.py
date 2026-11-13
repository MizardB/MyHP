"""Payload and format handlers for HP Prime files (notes, programs, python)."""

from __future__ import annotations

import os
import re
from enum import IntEnum
from typing import Union


class PrimeFileType(IntEnum):
    """HP Prime file type identifiers."""
    SETTINGS = 0x00
    APP = 0x02
    LIST = 0x03
    MATRIX = 0x04
    NOTE = 0x05
    PRGM = 0x06
    APPNOTE = 0x07
    APPPRGM = 0x08
    COMPLEX = 0x09
    REAL = 0x0A
    TESTMODECONFIG = 0x0B
    UNKNOWN = 0xFF


# CCITT CRC16 lookup table (standard for HP Prime protocol)
CCITT_CRC16_TABLE = (
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7,
    0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52b5, 0x4294, 0x72f7, 0x62d6,
    0x9339, 0x8318, 0xb37b, 0xa35a, 0xd3bd, 0xc39c, 0xf3ff, 0xe3de,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64e6, 0x74c7, 0x44a4, 0x5485,
    0xa56a, 0xb54b, 0x8528, 0x9509, 0xe5ee, 0xf5cf, 0xc5ac, 0xd58d,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76d7, 0x66f6, 0x5695, 0x46b4,
    0xb75b, 0xa77a, 0x9719, 0x8738, 0xf7df, 0xe7fe, 0xd79d, 0xc7bc,
    0x48c4, 0x58e5, 0x6886, 0x78a7, 0x0840, 0x1861, 0x2802, 0x3823,
    0xc9cc, 0xd9ed, 0xe98e, 0xf9af, 0x8948, 0x9969, 0xa90a, 0xb92b,
    0x5af5, 0x4ad4, 0x7ab7, 0x6a96, 0x1a71, 0x0a50, 0x3a33, 0x2a12,
    0xdbfd, 0xcbdc, 0xfbbf, 0xeb9e, 0x9b79, 0x8b58, 0xbb3b, 0xab1a,
    0x6ca6, 0x7c87, 0x4ce4, 0x5cc5, 0x2c22, 0x3c03, 0x0c60, 0x1c41,
    0xedae, 0xfd8f, 0xcdec, 0xddcd, 0xad2a, 0xbd0b, 0x8d68, 0x9d49,
    0x7e97, 0x6eb6, 0x5ed5, 0x4ef4, 0x3e13, 0x2e32, 0x1e51, 0x0e70,
    0xff9f, 0xefbe, 0xdfdd, 0xcffc, 0xbf1b, 0xaf3a, 0x9f59, 0x8f78,
    0x9188, 0x81a9, 0xb1ca, 0xa1eb, 0xd10c, 0xc12d, 0xf14e, 0xe16f,
    0x1080, 0x00a1, 0x30c2, 0x20e3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83b9, 0x9398, 0xa3fb, 0xb3da, 0xc33d, 0xd31c, 0xe37f, 0xf35e,
    0x02b1, 0x1290, 0x22f3, 0x32d2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xb5ea, 0xa5cb, 0x95a8, 0x8589, 0xf56e, 0xe54f, 0xd52c, 0xc50d,
    0x34e2, 0x24c3, 0x14a0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xa7db, 0xb7fa, 0x8799, 0x97b8, 0xe75f, 0xf77e, 0xc71d, 0xd73c,
    0x26d3, 0x36f2, 0x0691, 0x16b0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xd94c, 0xc96d, 0xf90e, 0xe92f, 0x99c8, 0x89e9, 0xb98a, 0xa9ab,
    0x5844, 0x4865, 0x7806, 0x6827, 0x18c0, 0x08e1, 0x3882, 0x28a3,
    0xcb7d, 0xdb5c, 0xeb3f, 0xfb1e, 0x8bf9, 0x9bd8, 0xabbb, 0xbb9a,
    0x4a75, 0x5a54, 0x6a37, 0x7a16, 0x0af1, 0x1ad0, 0x2ab3, 0x3a92,
    0xfd2e, 0xed0f, 0xdd6c, 0xcd4d, 0xbdaa, 0xad8b, 0x9de8, 0x8dc9,
    0x7c26, 0x6c07, 0x5c64, 0x4c45, 0x3ca2, 0x2c83, 0x1ce0, 0x0cc1,
    0xef1f, 0xff3e, 0xcf5d, 0xdf7c, 0xaf9b, 0xbfba, 0x8fd9, 0x9ff8,
    0x6e17, 0x7e36, 0x4e55, 0x5e74, 0x2e93, 0x3eb2, 0x0ed1, 0x1ef0,
)


def calc_crc16(buffer: bytes | bytearray, length: int | None = None) -> int:
    """Calculate the 16-bit CCITT CRC used by HP Prime."""
    if length is None:
        length = len(buffer)
    crc = 0
    for i in range(min(length, len(buffer))):
        crc = (CCITT_CRC16_TABLE[(crc >> 8) ^ buffer[i]] ^ (crc << 8)) & 0xFFFF
    return crc


def sanitize_program_name(name: str) -> str:
    """Sanitize program identifier for HP Prime.
    
    HP Prime program names must:
    - Start with a letter if possible (letters, digits, underscores).
    - If starting with a digit, prefix with 'P'.
    - Replace spaces and invalid characters with underscores.
    - Max 64 characters.
    """
    cleaned = re.sub(r"[^\w]", "_", name.strip())
    if not cleaned:
        cleaned = "PROG"
    if cleaned[0].isdigit():
        cleaned = "P" + cleaned
    return cleaned[:64]


def sanitize_note_name(name: str) -> str:
    """Sanitize note identifier for HP Prime.
    
    Notes allow alphanumeric characters and underscores, max 64 characters.
    """
    cleaned = re.sub(r"[^\w\s-]", "_", name.strip())
    cleaned = cleaned.replace(" ", "_")
    if not cleaned:
        cleaned = "NOTE"
    return cleaned[:64]


def prepare_file_content(content: Union[str, bytes]) -> bytes:
    """Encode string or raw bytes to UTF-16LE without BOM for HP Prime."""
    if isinstance(content, str):
        # Convert newlines to standard \n or \r\n (HP Prime accepts standard LF or CRLF)
        return content.encode("utf-16le")

    raw = content
    # If starting with UTF-16LE BOM (0xFF, 0xFE), strip it
    if len(raw) >= 2 and raw[0] == 0xFF and raw[1] == 0xFE:
        return raw[2:]

    # Check if raw is already valid UTF-16LE or ASCII/UTF-8
    # Try decoding as utf-8 / text first to normalize if it wasn't utf-16
    try:
        text = raw.decode("utf-8")
        return text.encode("utf-16le")
    except UnicodeDecodeError:
        # Might already be raw utf-16le bytes
        return raw


def build_file_payload(
    name: str,
    content: Union[str, bytes],
    file_type: int | PrimeFileType = PrimeFileType.PRGM,
    *,
    raw_content: bool = False,
) -> bytes:
    """Build a complete HP Prime virtual packet for CMD_FILE (0xF7).
    
    Structure:
    - Bytes 0..1: [0xF7, 0x01]
    - Bytes 2..5: Size (uint32 big-endian) = namelen + content_len + 4
    - Byte 6: File Type (0x05 = Note, 0x06 = Program)
    - Byte 7: Name length in bytes (uint8)
    - Bytes 8..9: CRC16 (little-endian uint16) over the first `size` bytes of pkt
    - Bytes 10..10+namelen: Name encoded in UTF-16LE
    - Bytes 10+namelen..end: Body encoded in UTF-16LE
    """
    encoded_body = bytes(content) if raw_content and isinstance(content, bytes) else prepare_file_content(content)
    encoded_name = name.encode("utf-16le")

    if len(encoded_name) > 255:
        encoded_name = encoded_name[:254]
        if len(encoded_name) % 2 != 0:
            encoded_name = encoded_name[:-1]

    namelen = len(encoded_name)
    data_size = 4 + namelen + len(encoded_body)

    pkt = bytearray()
    pkt.extend([0xF7, 0x01])
    pkt.extend(data_size.to_bytes(4, "big"))
    pkt.append(int(file_type) & 0xFF)
    pkt.append(namelen & 0xFF)
    pkt.extend([0x00, 0x00])  # Placeholder for CRC
    pkt.extend(encoded_name)
    pkt.extend(encoded_body)

    # Compute CRC16 over the packet up to `data_size` bytes
    crc = calc_crc16(pkt, data_size)
    pkt[8] = crc & 0xFF
    pkt[9] = (crc >> 8) & 0xFF

    return bytes(pkt)


def decode_note_text(raw_content: bytes) -> str:
    """Extract human-readable plain text from HP Prime note payload.
    
    HP Prime notes contain UTF-16LE text followed optionally by an internal
    formatting/style block prefixed by the marker 'CSWD' (encoded in UTF-16LE).
    """
    if not raw_content:
        return ""

    # Look for UTF-16LE 'CSWD' separator
    cswd_marker = "CSWD".encode("utf-16le")
    idx = raw_content.find(cswd_marker)
    text_bytes = raw_content[:idx] if idx != -1 else raw_content

    # Strip trailing null characters if present
    text = text_bytes.decode("utf-16le", errors="replace")
    return text.rstrip("\x00")

