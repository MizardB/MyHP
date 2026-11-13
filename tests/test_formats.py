"""Unit tests for myhp formats and payload construction."""

import struct
import unittest

from myhp.formats import (
    PrimeFileType,
    calc_crc16,
    sanitize_note_name,
    sanitize_program_name,
    prepare_file_content,
    build_file_payload,
)
from myhp.protocol import chunk_payload


class TestPrimeFormats(unittest.TestCase):
    def test_crc16(self):
        # Known CCITT CRC16 vector with initial value 0x0000
        data = b"123456789"
        crc = calc_crc16(data)
        self.assertEqual(crc, 0x31C3)

    def test_sanitize_program_name(self):
        self.assertEqual(sanitize_program_name("my_prog"), "my_prog")
        self.assertEqual(sanitize_program_name("123test"), "P123test")
        self.assertEqual(sanitize_program_name("hello world!"), "hello_world_")
        self.assertEqual(sanitize_program_name(""), "PROG")

    def test_sanitize_note_name(self):
        self.assertEqual(sanitize_note_name("note 1"), "note_1")
        self.assertEqual(sanitize_note_name("valid-name_01"), "valid-name_01")
        self.assertEqual(sanitize_note_name(""), "NOTE")

    def test_prepare_file_content(self):
        # String input
        text = "Hello Prime"
        res = prepare_file_content(text)
        self.assertEqual(res, text.encode("utf-16le"))

        # Raw bytes with BOM
        bom_bytes = b"\xff\xfe" + text.encode("utf-16le")
        res_bom = prepare_file_content(bom_bytes)
        self.assertEqual(res_bom, text.encode("utf-16le"))

    def test_build_file_payload_note(self):
        name = "QuickNote"
        content = "Sample note content"
        pkt = build_file_payload(name, content, file_type=PrimeFileType.NOTE)

        self.assertEqual(pkt[0], 0xF7)
        self.assertEqual(pkt[1], 0x01)
        size = struct.unpack_from(">I", pkt, 2)[0]
        file_type = pkt[6]
        namelen = pkt[7]
        crc = struct.unpack_from("<H", pkt, 8)[0]

        self.assertEqual(file_type, 0x05)
        name_bytes = pkt[10 : 10 + namelen]
        self.assertEqual(name_bytes.decode("utf-16le"), name)

        body_bytes = pkt[10 + namelen :]
        self.assertEqual(body_bytes.decode("utf-16le"), content)

        # Re-check CRC
        pkt_copy = bytearray(pkt)
        pkt_copy[8] = 0x00
        pkt_copy[9] = 0x00
        calc_crc = calc_crc16(pkt_copy, size)
        self.assertEqual(crc, calc_crc)

    def test_decode_note_text(self):
        from myhp.formats import decode_note_text
        text = "Hello world!"
        # Simple UTF-16LE text
        raw = text.encode("utf-16le")
        self.assertEqual(decode_note_text(raw), text)

        # Note with CSWD metadata attached
        raw_with_cswd = text.encode("utf-16le") + "CSWD110".encode("utf-16le") + b"\x00\x01\x02\x03"
        self.assertEqual(decode_note_text(raw_with_cswd), text)


    def test_build_file_payload_program(self):
        name = "MyScript"
        code = "EXPORT MyScript()\nBEGIN\nEND;\n"
        pkt = build_file_payload(name, code, file_type=PrimeFileType.PRGM)

        self.assertEqual(pkt[0], 0xF7)
        self.assertEqual(pkt[1], 0x01)
        file_type = pkt[6]
        self.assertEqual(file_type, 0x06)

        namelen = pkt[7]
        self.assertEqual(pkt[10 : 10 + namelen].decode("utf-16le"), name)

    def test_chunk_payload(self):
        # 130 bytes payload -> should split into 3 chunks:
        # chunk 0: 63 bytes data (len 65)
        # chunk 1: 63 bytes data (len 65)
        # chunk 2: 4 bytes data + 59 zeros (len 65)
        payload = bytes(range(130))
        chunks = chunk_payload(payload, chunk_size=64)

        self.assertEqual(len(chunks), 3)
        for i, c in enumerate(chunks):
            self.assertEqual(len(c), 65)
            self.assertEqual(c[0], 0x00)  # Report ID
            self.assertEqual(c[1], i)     # Packet ID

        reassembled = bytearray()
        for i, c in enumerate(chunks):
            if i < 2:
                reassembled.extend(c[2:])
            else:
                reassembled.extend(c[2:2 + (130 - 126)])

        self.assertEqual(bytes(reassembled), payload)


if __name__ == "__main__":
    unittest.main()
