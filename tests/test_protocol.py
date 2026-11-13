"""Unit tests for myhp protocol parsing and packet building."""

import unittest
from myhp.protocol import PrimeCommand, PrimeInfo, build_command_packet, parse_vtl_response


class TestPrimeProtocol(unittest.TestCase):
    def test_build_command_packet(self):
        pkt = build_command_packet(PrimeCommand.CHECK_READY, packet_id=1)
        self.assertEqual(len(pkt), 65)
        self.assertEqual(pkt[0], 0x00)
        self.assertEqual(pkt[1], 0x01)
        self.assertEqual(pkt[2], 0xFF)
        self.assertEqual(pkt[3:], bytes(62))

    def test_parse_vtl_response(self):
        # Construct synthetic response with 2 chunks
        # Chunk 1: seq 0x00 + [0xFA, 0x01, 0x00, 0x00, 0x00, 0x04, ord('A'), ord('B'), ord('C'), ord('D')] + 53 zeroes
        chunk1 = bytes([0x00, 0xFA, 0x01, 0x00, 0x00, 0x00, 0x04, 65, 66, 67, 68]) + bytes(53)
        self.assertEqual(len(chunk1), 64)
        cmd, payload = parse_vtl_response([chunk1])
        self.assertEqual(cmd, 0xFA)
        self.assertEqual(payload, b"ABCD")

    def test_parse_prime_info(self):
        # Build synthetic 108-byte payload matching real Prime G2 reply
        payload = bytearray(108)
        # STAR header in utf-16le: 'S\0T\0A\0R\0'
        payload[0:8] = "STAR".encode("utf-16le")
        # Build number 15751 (0x3D87) at index 72
        payload[72:74] = (15751).to_bytes(2, "little")
        # Version V0.050.640 at index 76
        ver = b"V0.050.640"
        payload[76:76+len(ver)] = ver
        # Serial 4CY41001642 at index 92
        ser = b"4CY41001642"
        payload[92:92+len(ser)] = ser

        info = PrimeInfo.from_bytes(bytes(payload), model_hint="HP Prime G2")
        self.assertEqual(info.model, "HP Prime G2")
        self.assertEqual(info.raw_header, "STAR")
        self.assertEqual(info.build, 15751)
        self.assertEqual(info.firmware, "V0.050.640")
        self.assertEqual(info.serial, "4CY41001642")

    def test_parse_file_packet(self):
        from myhp.formats import build_file_payload, PrimeFileType
        from myhp.protocol import parse_file_packet

        pkt = build_file_payload("TestNote", "My content", file_type=PrimeFileType.NOTE)
        entry = parse_file_packet(pkt)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.name, "TestNote")
        self.assertEqual(entry.file_type, 0x05)
        self.assertEqual(entry.type_name, "NOTE")
        self.assertEqual(entry.get_text_content(), "My content")



if __name__ == "__main__":
    unittest.main()
