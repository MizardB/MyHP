"""Protocol definitions and message parsing for HP Prime calculators."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum


class PrimeCommand(IntEnum):
    """HP Prime protocol command IDs."""
    CHECK_READY = 0xFF       # 255: Ping / check ready status
    GET_INFOS = 0xFA         # 250: Device info (model, firmware, serial)
    RECV_BACKUP = 0xF9       # 249: Backup request
    REQ_FILE = 0xF8          # 248: Request file
    FILE = 0xF7              # 247: File transfer (RECV_FILE / SEND_FILE)
    SCREEN = 0xFC            # 252: Screenshot capture
    SEND_CHAT = 0xF2         # 242: Send chat
    RECV_CHAT = 0xF2         # 242: Receive chat
    SEND_KEY = 0xEC          # 236: Send key event
    SET_DATE_TIME = 0xE7     # 231: Set calculator date & time


@dataclass
class PrimeInfo:
    """Parsed calculator identification and version information."""
    model: str
    serial: str
    firmware: str
    build: int
    raw_header: str
    raw_payload: bytes

    @classmethod
    def from_bytes(cls, payload: bytes, model_hint: str = "") -> PrimeInfo:
        """Parse the payload returned by CMD_GET_INFOS (0xFA).
        
        The typical 108-byte payload structure:
        - Bytes 0..63: UTF-16LE or ASCII identification string (starts with 'STAR')
        - Bytes 72..74: Build number (uint16 little-endian)
        - Bytes 76..86: Firmware version string (e.g. 'V0.050.640')
        - Bytes 92..103: Serial number string (e.g. '4CY41001642')
        """
        # Header string (usually 'STAR')
        raw_header = ""
        try:
            # First 16 bytes often UTF-16LE 'STAR'
            decoded_utf16 = payload[:16].decode("utf-16le", errors="ignore").split("\x00")[0]
            if decoded_utf16:
                raw_header = decoded_utf16
            else:
                raw_header = payload[:16].decode("ascii", errors="ignore").split("\x00")[0]
        except Exception:
            raw_header = ""

        # Build number
        build = 0
        if len(payload) >= 74:
            build = struct.unpack_from("<H", payload, 72)[0]

        # Version string: located at index len - 32 or offset 76..88
        firmware = ""
        if len(payload) >= 88:
            ver_bytes = payload[76:88].split(b"\x00")[0]
            firmware = ver_bytes.decode("ascii", errors="replace").strip()
        elif len(payload) >= 32:
            idx_v = len(payload) - 32
            ver_bytes = payload[idx_v:idx_v + 12].split(b"\x00")[0]
            firmware = ver_bytes.decode("ascii", errors="replace").strip()

        # Serial number: located at index len - 16 or offset 92..108
        serial = ""
        if len(payload) >= 104:
            ser_bytes = payload[92:104].split(b"\x00")[0]
            serial = ser_bytes.decode("ascii", errors="replace").strip()
        elif len(payload) >= 16:
            idx_s = len(payload) - 16
            ser_bytes = payload[idx_s:].split(b"\x00")[0]
            serial = ser_bytes.decode("ascii", errors="replace").strip()

        # Model resolution
        model = model_hint or "HP Prime"

        return cls(
            model=model,
            serial=serial,
            firmware=firmware,
            build=build,
            raw_header=raw_header,
            raw_payload=payload,
        )


def build_command_packet(cmd: int | PrimeCommand, packet_id: int = 0, payload: bytes = b"") -> bytes:
    """Build a 65-byte HID packet for transmission to the HP Prime.
    
    Structure:
    - Byte 0: Report ID (0x00)
    - Byte 1: Packet ID / sequence (0..254)
    - Byte 2: Command code
    - Bytes 3..64: Optional parameter / padding zeroes
    """
    cmd_val = int(cmd)
    raw = bytearray(65)
    raw[0] = 0x00
    raw[1] = packet_id & 0xFF
    raw[2] = cmd_val & 0xFF
    if payload:
        copy_len = min(len(payload), 62)
        raw[3:3 + copy_len] = payload[:copy_len]
    return bytes(raw)


def parse_vtl_response(chunks: list[bytes]) -> tuple[int, bytes]:
    """Parse reassembled response chunks from the calculator into (cmd, payload).
    
    Each 64-byte received HID packet format:
    - Byte 0: Sequence number (0x00, 0x01, ...)
    - Bytes 1..63: Data stream
    
    In the data stream:
    - Stream Byte 0: Command echo (e.g. 0xFA for INFOS)
    - Stream Byte 1: Flag (e.g. 0x01)
    - Stream Bytes 2..5: Size of subsequent payload (uint32 big-endian)
    - Stream Bytes 6..6+size: Payload
    """
    stream = bytearray()
    for chunk in chunks:
        if len(chunk) > 1:
            stream.extend(chunk[1:])  # Strip HID sequence byte

    if len(stream) < 6:
        return 0, bytes(stream)

    cmd = stream[0]
    flag = stream[1]
    if flag == 0x01 and len(stream) >= 6:
        size = struct.unpack_from(">I", stream, 2)[0]
        payload = bytes(stream[6:6 + size])
        return cmd, payload

    return cmd, bytes(stream[1:])


def chunk_payload(data: bytes, chunk_size: int = 64) -> list[bytes]:
    """Fragment virtual packet data into 65-byte HID packets for transmission.
    
    Structure of each HID output packet:
    - Byte 0: Report ID (0x00)
    - Byte 1: Sequence / packet ID (0, 1, 2, ... wrapping at 254)
    - Bytes 2..64: Data payload (up to 63 bytes)
    """
    payload_per_chunk = chunk_size - 1  # 63 bytes
    chunks: list[bytes] = []
    pkt_id = 0
    offset = 0

    while offset < len(data):
        slice_end = min(offset + payload_per_chunk, len(data))
        chunk_slice = data[offset:slice_end]

        pkt = bytearray(chunk_size + 1)  # 65 bytes
        pkt[0] = 0x00
        pkt[1] = pkt_id & 0xFF
        pkt[2 : 2 + len(chunk_slice)] = chunk_slice
        chunks.append(bytes(pkt))

        offset = slice_end
        pkt_id = (pkt_id + 1) % 0xFF

    return chunks


@dataclass
class PrimeCatalogEntry:
    """An individual entry retrieved from the HP Prime memory catalog."""
    file_type: int
    name: str
    size: int
    raw_content: bytes

    @property
    def type_name(self) -> str:
        """Friendly type name for listing."""
        from myhp.formats import PrimeFileType
        try:
            return PrimeFileType(self.file_type).name
        except ValueError:
            return f"TYPE_{self.file_type:02X}"

    def get_text_content(self) -> str:
        """Decode content as text according to entry type."""
        from myhp.formats import PrimeFileType, decode_note_text
        if self.file_type == PrimeFileType.NOTE:
            return decode_note_text(self.raw_content)
        # Try decoding programs or other text objects as UTF-16LE or UTF-8
        try:
            return self.raw_content.decode("utf-16le").rstrip("\x00")
        except UnicodeDecodeError:
            try:
                return self.raw_content.decode("utf-8").rstrip("\x00")
            except UnicodeDecodeError:
                return self.raw_content.decode("latin-1", errors="replace")


def parse_file_packet(vtl_pkt: bytes) -> PrimeCatalogEntry | None:
    """Parse a single reassembled virtual file packet (CMD_FILE 0xF7).
    
    Structure:
    - Byte 0: 0xF7
    - Byte 1: Flag (usually 0x01)
    - Bytes 2..5: Size (uint32 big-endian) = namelen + content_len + 4
    - Byte 6: File Type
    - Byte 7: Namelen (uint8)
    - Bytes 8..9: CRC16
    - Bytes 10..10+namelen: Name (UTF-16LE)
    - Bytes 10+namelen..6+size: Content
    """
    if len(vtl_pkt) < 10 or vtl_pkt[0] != 0xF7:
        return None

    size = struct.unpack_from(">I", vtl_pkt, 2)[0]
    file_type = vtl_pkt[6]
    namelen = vtl_pkt[7]
    if len(vtl_pkt) < 10 + namelen:
        return None

    name = vtl_pkt[10 : 10 + namelen].decode("utf-16le", errors="replace").rstrip("\x00")
    content_end = min(6 + size, len(vtl_pkt))
    raw_content = vtl_pkt[10 + namelen : content_end]

    return PrimeCatalogEntry(
        file_type=file_type,
        name=name,
        size=len(raw_content),
        raw_content=raw_content,
    )


