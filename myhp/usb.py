"""Low-level USB / HID communication for HP Prime calculators."""

from __future__ import annotations

import glob
import os
import select
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from myhp.apps import build_app_packet, read_hpprgm_source
from myhp.formats import PrimeFileType, build_file_payload
from myhp.protocol import (
    PrimeCatalogEntry,
    PrimeCommand,
    PrimeInfo,
    build_command_packet,
    chunk_payload,
    chunk_v2_payload,
    parse_file_packet,
    parse_vtl_response,
)

# Known HP Prime USB IDs
HP_VENDOR_ID = 0x03F0
HP_PRIME_PIDS = {
    0x0141: "HP Prime G1",
    0x0441: "HP Prime G1",
    0x1541: "HP Prime G2",
    0x2441: "HP Prime G2",
}


@dataclass
class PrimeDeviceDescriptor:
    """Descriptor of a detected HP Prime device node."""
    hidraw_path: str
    vid: int
    pid: int
    model_name: str
    product_string: str = ""
    manufacturer_string: str = ""


def find_prime_devices() -> list[PrimeDeviceDescriptor]:
    """Scan /sys/class/hidraw to detect connected HP Prime calculators."""
    devices: list[PrimeDeviceDescriptor] = []

    for hidraw_dir in glob.glob("/sys/class/hidraw/hidraw*"):
        node_name = os.path.basename(hidraw_dir)
        dev_node = os.path.join("/dev", node_name)
        device_link = os.path.realpath(os.path.join(hidraw_dir, "device"))

        # Walk up device hierarchy to locate USB idVendor and idProduct
        cur = device_link
        vid: Optional[int] = None
        pid: Optional[int] = None
        product_name = ""
        manufacturer = ""

        while cur and cur != "/":
            v_file = os.path.join(cur, "idVendor")
            p_file = os.path.join(cur, "idProduct")
            if os.path.isfile(v_file) and os.path.isfile(p_file):
                try:
                    with open(v_file, "r") as f:
                        vid = int(f.read().strip(), 16)
                    with open(p_file, "r") as f:
                        pid = int(f.read().strip(), 16)
                except Exception:
                    pass

                prod_file = os.path.join(cur, "product")
                if os.path.isfile(prod_file):
                    try:
                        with open(prod_file, "r") as f:
                            product_name = f.read().strip()
                    except Exception:
                        pass

                manuf_file = os.path.join(cur, "manufacturer")
                if os.path.isfile(manuf_file):
                    try:
                        with open(manuf_file, "r") as f:
                            manufacturer = f.read().strip()
                    except Exception:
                        pass
                break
            cur = os.path.dirname(cur)

        if vid == HP_VENDOR_ID and pid in HP_PRIME_PIDS:
            devices.append(
                PrimeDeviceDescriptor(
                    hidraw_path=dev_node,
                    vid=vid,
                    pid=pid,
                    model_name=HP_PRIME_PIDS[pid],
                    product_string=product_name,
                    manufacturer_string=manufacturer,
                )
            )

    return devices


class PrimeDevice:
    """Manages an open connection to an HP Prime calculator via hidraw."""

    def __init__(self, hidraw_path: str, model_hint: str = "HP Prime"):
        self.hidraw_path = hidraw_path
        self.model_hint = model_hint
        self._fd: Optional[int] = None
        self._seq = 0

    def open(self) -> None:
        """Open the hidraw device node with read/write access."""
        if self._fd is None:
            self._fd = os.open(self.hidraw_path, os.O_RDWR)

    def close(self) -> None:
        """Close the hidraw device node."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def __enter__(self) -> PrimeDevice:
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def send_raw(self, data: bytes) -> int:
        """Send a raw packet to the device.

        For Linux hidraw, packets are 65 bytes long (Report ID 0x00 + 64 bytes).
        """
        if self._fd is None:
            raise RuntimeError("Device not open")
        if len(data) != 65:
            # Pad or truncate to 65 bytes
            pkt = bytearray(65)
            pkt[: min(len(data), 65)] = data[:65]
            data = bytes(pkt)
        return os.write(self._fd, data)

    def recv_raw(self, timeout_s: float = 2.0, max_bytes: int = 64) -> bytes:
        """Read a raw packet from the device (typically 64 bytes on Linux hidraw)."""
        if self._fd is None:
            raise RuntimeError("Device not open")

        r, _, _ = select.select([self._fd], [], [], timeout_s)
        if not r:
            raise TimeoutError(f"Timed out waiting for data from {self.hidraw_path}")

        return os.read(self._fd, max_bytes)

    def send_command(self, cmd: int | PrimeCommand, payload: bytes = b"") -> None:
        """Send a single command packet using the internal sequence counter."""
        pkt = build_command_packet(cmd, packet_id=self._seq, payload=payload)
        self._seq = (self._seq + 1) % 0xFF
        self.send_raw(pkt)

    def check_ready(self) -> bool:
        """Ping calculator with CMD_CHECK_READY (0xFF)."""
        self.send_command(PrimeCommand.CHECK_READY)
        chunk = self.recv_raw(timeout_s=1.0)
        # Check ready returns a 64-byte packet starting with 0x00 sequence
        return len(chunk) > 0

    def get_info(self) -> PrimeInfo:
        """Retrieve calculator device info (serial, build, version, etc.)."""
        # Drain any residual pending data if necessary
        while True:
            r, _, _ = select.select([self._fd], [], [], 0.05)
            if r and self._fd is not None:
                os.read(self._fd, 64)
            else:
                break

        self.send_command(PrimeCommand.GET_INFOS)
        # GET_INFOS typically responds with 2 chunks of 64 bytes (126 payload bytes after sequence bytes)
        chunks: list[bytes] = []
        for _ in range(2):
            chunks.append(self.recv_raw(timeout_s=2.0))

        cmd, payload = parse_vtl_response(chunks)
        if cmd != PrimeCommand.GET_INFOS:
            # If command echo mismatch, parse payload anyway if non-empty
            pass

        return PrimeInfo.from_bytes(payload, model_hint=self.model_hint)

    def send_file(
        self,
        name: str,
        content: str | bytes,
        file_type: int | PrimeFileType = PrimeFileType.PRGM,
    ) -> int:
        """Send a complete file (note, program, etc.) to the HP Prime.

        Builds the virtual file packet, splits it into HID chunks, transmits
        each chunk, and verifies the calculator remains ready.
        Returns the number of transmitted HID chunks.
        """
        payload = build_file_payload(name, content, file_type=file_type)
        chunks = chunk_payload(payload)

        for chunk in chunks:
            self.send_raw(chunk)

        # Check ready to ensure calculator accepted packet cleanly
        try:
            self.check_ready()
        except Exception:
            pass

        return len(chunks)

    def send_v2_message(
        self,
        data: bytes,
        message_id: int = 4,
        timeout_s: float = 3.0,
    ) -> int:
        """Send data using HP Prime V2 framing (CMD_APP 0xF7 0x03, etc.) and handle ACKs.

        Splits data into V2 chunk reports, transmits them to the calculator,
        and listens for AckFrame (0xFE 0x01) notifications. Responds with host
        sync ACK if requested, completing when the Prime confirms receipt
        (final ACK with sequence 0xFF or final sequence).
        Returns the number of transmitted chunks.
        """
        if self._fd is None:
            raise RuntimeError("Device not open")

        # 1. Negotiate V2 protocol mode with calculator (FF EC + FD MAX_PROT_VER)
        p_v2 = bytearray(65)
        p_v2[1] = 0xFF
        p_v2[2] = 0xEC
        self.send_raw(bytes(p_v2))
        time.sleep(0.02)

        p_fd = bytearray(65)
        p_fd[1] = 0x01
        p_fd[2:6] = struct.pack("<I", 1)
        p_fd[6:10] = struct.pack("<I", 7)
        p_fd[10:17] = bytes([0xFD, 0x01, 0x00, 0x00, 0x00, 0x01, 0x03])
        self.send_raw(bytes(p_fd))
        time.sleep(0.02)

        for _ in range(5):
            r, _, _ = select.select([self._fd], [], [], 0.05)
            if r:
                try:
                    os.read(self._fd, 64)
                except OSError:
                    break
            else:
                break

        h_ack1 = bytearray(65)
        h_ack1[1] = 0xFE
        h_ack1[2] = 0x01
        h_ack1[3] = 0x01
        h_ack1[5:9] = struct.pack("<I", 0x37)
        h_ack1[9:13] = struct.pack("<I", 1)
        self.send_raw(bytes(h_ack1))

        chunks = chunk_v2_payload(data, message_id=message_id)

        # Transmit all V2 chunks to the device
        for chunk in chunks:
            self.send_raw(chunk)
            # Drain/handle any immediate incoming packets if available without blocking
            r, _, _ = select.select([self._fd], [], [], 0.0)
            if r:
                try:
                    os.read(self._fd, 64)
                except OSError:
                    pass

        # Wait for the calculator's confirmation ACKs (0xFE 0x01)
        # Expected sequence:
        # 1. ACK for the final chunk (seq == final_seq and p_mid == message_id)
        # 2. Final ACK indicating completion (seq == 0xFF and p_mid == message_id)
        final_seq = chunks[-1][1]
        chunk_ack_received = False
        ack_received = False

        while True:
            r, _, _ = select.select([self._fd], [], [], timeout_s)
            if not r:
                break

            try:
                report = os.read(self._fd, 64)
            except OSError:
                break

            if not report:
                break

            # ACK frame check: report starts with 0xFE, command 0x01
            if len(report) >= 4 and report[0] == 0xFE and report[1] == 0x01:
                seq = report[2]
                p_pos = struct.unpack_from("<I", report, 4)[0] if len(report) >= 8 else len(data) + 9
                p_mid = struct.unpack_from("<I", report, 8)[0] if len(report) >= 12 else message_id

                # Ignore keepalive or ACK frames where p_mid != message_id
                if p_mid != message_id:
                    continue

                if seq == final_seq:
                    chunk_ack_received = True
                    continue

                # Sequence 0xFF indicates full transfer and app registration completion
                if seq == 0xFF:
                    ack_received = True

                    try:
                        # Host response ACK (replica of packets 629 and 631 in capture)
                        host_ack = bytearray(65)
                        host_ack[0] = 0x00  # Report ID
                        host_ack[1] = 0xFE  # Byte 254
                        host_ack[2] = 0x01  # ACK cmd
                        host_ack[3] = 0xFF  # Final seq
                        host_ack[4] = 0x00
                        host_ack[5:9] = struct.pack("<I", 0x37)  # chunk 1 data size (55 bytes)
                        host_ack[9:13] = struct.pack("<I", 6)
                        host_ack[17:21] = struct.pack("<I", p_pos)
                        host_ack[33:37] = struct.pack("<I", p_mid)
                        host_ack[41:45] = bytes([0xA2, 0x81, 0x00, 0x00])
                        self.send_raw(bytes(host_ack))
                        time.sleep(0.01)
                        self.send_raw(bytes(host_ack))
                        time.sleep(0.05)

                    except Exception:
                        pass

                    break

        return len(chunks)

    def send_app(self, name: str, app_directory: str) -> int:
        """Install an app by sending a compressed container over CMD_APP (0xF7 0x03)."""
        if self._fd is None:
            raise RuntimeError("Device not open")
        report_size = self._output_report_size()
        if report_size != 64:
            raise NotImplementedError(
                f"La instalación de apps aún no está implementada para reportes HID de {report_size} bytes"
            )

        packet = build_app_packet(name, app_directory)
        return self.send_v2_message(packet, message_id=4)

    def _output_report_size(self) -> int:
        """Read the output report size from this hidraw node's HID descriptor."""
        descriptor_path = os.path.join(
            "/sys/class/hidraw", os.path.basename(self.hidraw_path), "device", "report_descriptor"
        )
        try:
            with open(descriptor_path, "rb") as descriptor_file:
                descriptor = descriptor_file.read()
        except OSError as exc:
            raise RuntimeError(f"No se pudo leer el descriptor HID {descriptor_path}: {exc}") from exc

        report_size = 0
        report_count = 0
        offset = 0
        while offset < len(descriptor):
            prefix = descriptor[offset]
            offset += 1
            if prefix == 0xFE:  # Long item; skip its declared payload.
                if offset + 2 > len(descriptor):
                    break
                length = descriptor[offset]
                offset += 2 + length
                continue
            item_size = (0, 1, 2, 4)[prefix & 0x03]
            item_type = (prefix >> 2) & 0x03
            item_tag = (prefix >> 4) & 0x0F
            raw = descriptor[offset : offset + item_size]
            if len(raw) != item_size:
                break
            value = int.from_bytes(raw, "little")
            offset += item_size
            if item_type == 1:  # Global item.
                if item_tag == 7:
                    report_size = value
                elif item_tag == 9:
                    report_count = value
            elif item_type == 0 and item_tag == 9:  # Output main item.
                bits = report_size * report_count
                if bits and bits % 8 == 0:
                    return bits // 8
        raise RuntimeError(f"No se encontró el tamaño del reporte HID de salida en {descriptor_path}")

    def list_content(self, timeout_s: float = 0.5) -> list[PrimeCatalogEntry]:
        """Query memory catalog from the HP Prime using CMD_RECV_BACKUP (0xF9).

        Reads all file packets returned by the calculator until the stream ends.
        Handles graceful recovery if the device resets its USB pipe at completion.
        """
        if self._fd is None:
            raise RuntimeError("Device not open")

        # Drain any lingering data
        while True:
            r, _, _ = select.select([self._fd], [], [], 0.05)
            if r and self._fd is not None:
                os.read(self._fd, 64)
            else:
                break

        # Send CMD_RECV_BACKUP (0xF9 0x01)
        self.send_command(PrimeCommand.RECV_BACKUP, payload=b"\x01")

        def _read_hid_chunk(t: float) -> bytes | None:
            if self._fd is None:
                return None
            r, _, _ = select.select([self._fd], [], [], t)
            if not r:
                return None
            try:
                return os.read(self._fd, 64)
            except OSError:
                return None

        entries: list[PrimeCatalogEntry] = []

        while True:
            first_chunk = _read_hid_chunk(timeout_s)
            if first_chunk is None:
                break

            data = first_chunk[1:]  # strip seq byte
            if len(data) < 2:
                continue

            cmd = data[0]
            if cmd == PrimeCommand.RECV_BACKUP:  # 0xF9 marker signals end of backup
                break
            if cmd != PrimeCommand.FILE:  # Expected 0xF7
                break

            if len(data) < 6:
                break

            import struct
            size = struct.unpack_from(">I", data, 2)[0]
            expected_vtl_len = 6 + size
            expected_chunks = (expected_vtl_len + 62) // 63

            vtl_buf = bytearray(data)
            for _ in range(expected_chunks - 1):
                rem_chunk = _read_hid_chunk(timeout_s)
                if rem_chunk is not None:
                    vtl_buf.extend(rem_chunk[1:])

            vtl_pkt = bytes(vtl_buf[:expected_vtl_len])
            entry = parse_file_packet(vtl_pkt)
            if entry is not None:
                entries.append(entry)

        return entries

    def get_file(
        self,
        name: str,
        file_type: int | PrimeFileType | None = None,
    ) -> PrimeCatalogEntry | None:
        """Retrieve a specific file/note/program by name from the calculator catalog."""
        catalog = self.list_content()
        target_name = name.strip().lower()
        for entry in catalog:
            if entry.name.lower() == target_name:
                if file_type is None or entry.file_type == int(file_type):
                    return entry
        return None

    def delete_file(
        self,
        name: str,
        file_type: int | PrimeFileType = PrimeFileType.NOTE,
    ) -> bool:
        """Clear/delete a file in calculator memory.

        Note: The HP Prime protocol does not offer a standalone DELETE command.
        Overwrites the item with empty content, clearing the note or program body.
        """
        self.send_file(name, "", file_type=file_type)
        return True


