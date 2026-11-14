"""Unit tests for myhp formats and payload construction."""

import struct
import unittest
import zlib
from pathlib import Path

from myhp.apps import build_app_packet, build_gallery_app_directory, read_hpprgm_source
from myhp.formats import (
    PrimeFileType,
    calc_crc16,
    sanitize_note_name,
    sanitize_program_name,
    prepare_file_content,
    build_file_payload,
)
from myhp.protocol import chunk_payload, chunk_v2_payload


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

    def test_chunk_v2_payload(self):
        # Test short payload (< 55 bytes) -> single chunk
        short_data = b"Hello HP Prime V2!"
        chunks = chunk_v2_payload(short_data, message_id=1, chunk_size=64)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 65)
        self.assertEqual(chunks[0][0], 0x00)  # Report ID
        self.assertEqual(chunks[0][1], 0x01)  # Sequence 1
        msg_id = struct.unpack_from("<I", chunks[0], 2)[0]
        total_len = struct.unpack_from("<I", chunks[0], 6)[0]
        self.assertEqual(msg_id, 1)
        self.assertEqual(total_len, len(short_data))
        self.assertEqual(chunks[0][10 : 10 + len(short_data)], short_data)

        # Test multi-chunk payload: 55 bytes in chunk 1, 63 bytes in chunk 2, 10 bytes in chunk 3 (total 128 bytes)
        payload = bytes(range(128))
        chunks = chunk_v2_payload(payload, message_id=4, chunk_size=64)
        self.assertEqual(len(chunks), 3)

        # Chunk 1
        self.assertEqual(len(chunks[0]), 65)
        self.assertEqual(chunks[0][0], 0x00)
        self.assertEqual(chunks[0][1], 0x01)
        self.assertEqual(struct.unpack_from("<I", chunks[0], 2)[0], 4)
        self.assertEqual(struct.unpack_from("<I", chunks[0], 6)[0], 128)
        self.assertEqual(chunks[0][10:65], payload[:55])

        # Chunk 2
        self.assertEqual(len(chunks[1]), 65)
        self.assertEqual(chunks[1][0], 0x00)
        self.assertEqual(chunks[1][1], 0x02)
        self.assertEqual(chunks[1][2:65], payload[55:118])

        # Chunk 3
        self.assertEqual(len(chunks[2]), 65)
        self.assertEqual(chunks[2][0], 0x00)
        self.assertEqual(chunks[2][1], 0x03)
        self.assertEqual(chunks[2][2:12], payload[118:128])
        self.assertEqual(chunks[2][12:], bytes(53))  # Padding zeroes

        # Reassemble payload from V2 chunks
        reassembled = bytearray(chunks[0][10:65])
        reassembled.extend(chunks[1][2:65])
        reassembled.extend(chunks[2][2:12])
        self.assertEqual(bytes(reassembled), payload)

        # Test sequence wrap at 0xFD
        huge_data = bytes(55 + 252 * 63 + 10)  # > 253 chunks
        huge_chunks = chunk_v2_payload(huge_data, message_id=1, chunk_size=64)
        self.assertEqual(huge_chunks[0][1], 1)
        self.assertEqual(huge_chunks[1][1], 2)
        self.assertEqual(huge_chunks[0xFD - 1][1], 0xFD)
        self.assertEqual(huge_chunks[0xFD][1], 2)  # Wrapped to 2

    def test_build_app_packet(self):
        import tempfile
        from myhp.apps import build_app_directory

        with tempfile.TemporaryDirectory() as tmpdir:
            folder = build_app_directory(
                "IMAGEN",
                "EXPORT START()\nBEGIN\nEND;\n",
                b"\x89PNG\r\n\x1a\n",
                output_dir=tmpdir,
            )
            pkt = build_app_packet("IMAGEN", folder)
            desc_expected = (folder / "IMAGEN.hpapp").read_bytes()
            note_expected = (folder / "IMAGEN.hpappnote").read_bytes()
            prgm_expected = (read_hpprgm_source((folder / "IMAGEN.hpappprgm").read_bytes()) + "\0").encode("utf-16le")
            icon_expected = "icon.png".encode("utf-16le") + b"\0\0" + (folder / "icon.png").read_bytes()

        self.assertEqual(pkt[:2], b"\xF7\x03")

        comp_len_plus_4 = struct.unpack_from(">I", pkt, 2)[0]
        uncomp_len = struct.unpack_from("<I", pkt, 6)[0]
        compressed = pkt[10:]
        self.assertEqual(len(compressed) + 4, comp_len_plus_4)

        decomp = zlib.decompress(compressed)
        self.assertEqual(len(decomp), uncomp_len)
        self.assertEqual(decomp[0], 0x02)  # Tipo APP
        name_len = decomp[1]
        self.assertEqual(name_len, len("IMAGEN".encode("utf-16le")))

        crc = struct.unpack_from("<H", decomp, 2)[0]
        fake_pkt = bytearray(b"\xF7\x03" + struct.pack(">I", len(decomp)) + decomp)
        fake_pkt[8:10] = b"\0\0"
        self.assertEqual(calc_crc16(fake_pkt, len(fake_pkt)), crc)

        name = decomp[4 : 4 + name_len].decode("utf-16le")
        self.assertEqual(name, "IMAGEN")

        curr = 4 + name_len
        desc_len = struct.unpack_from(">I", decomp, curr)[0]
        curr += 4
        desc = decomp[curr : curr + desc_len]
        curr += desc_len
        self.assertEqual(desc, desc_expected)

        note_len = struct.unpack_from(">I", decomp, curr)[0]
        curr += 4
        note = decomp[curr : curr + note_len]
        curr += note_len
        self.assertEqual(note, note_expected)

        prgm_len = struct.unpack_from(">I", decomp, curr)[0]
        curr += 4
        prgm_bytes = decomp[curr : curr + prgm_len]
        curr += prgm_len
        self.assertEqual(prgm_bytes, prgm_expected)

        # Additional files (icon.png)
        self.assertLess(curr, len(decomp))
        icon_item_len = struct.unpack_from(">I", decomp, curr)[0]
        curr += 4
        icon_item = decomp[curr : curr + icon_item_len]
        self.assertEqual(icon_item, icon_expected)
        curr += icon_item_len
        self.assertEqual(curr, len(decomp))

    def test_png_to_ppl_interactive_viewer_and_color_24bit(self):
        from myhp.images import png_to_ppl, _rgb24

        # 24-bit RGB calculation
        self.assertEqual(_rgb24((255, 0, 0)), 16711680)
        self.assertEqual(_rgb24((0, 255, 0)), 65280)
        self.assertEqual(_rgb24((0, 0, 255)), 255)
        self.assertEqual(_rgb24((255, 255, 255)), 16777215)
        self.assertEqual(_rgb24((0, 0, 0)), 0)

        # Generate a minimal 2x2 test PNG with red, green, blue, white
        w, h = 2, 2
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
        rows = [bytearray([0]) + bytearray(colors[0] + colors[1]), bytearray([0]) + bytearray(colors[2] + colors[3])]
        raw = b"".join(bytes(r) for r in rows)
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)

        def make_chunk(tag: bytes, body: bytes) -> bytes:
            return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

        png_data = b"\x89PNG\r\n\x1a\n" + make_chunk(b"IHDR", ihdr) + make_chunk(b"IDAT", zlib.compress(raw)) + make_chunk(b"IEND", b"")

        ppl = png_to_ppl(png_data, "PHOTO_VIEW")

        # 1. Verify 24-bit RGB color encoding in PPL
        self.assertIn("16711680", ppl)  # Red (0xFF0000)
        self.assertIn("65280", ppl)     # Green (0x00FF00)
        self.assertIn("255", ppl)       # Blue (0x0000FF)
        self.assertIn("16777215", ppl)  # White (0xFFFFFF)

        # 2. Verify interactive viewer loop and features
        self.assertIn("WHILE is_run==1 DO", ppl)
        self.assertIn("GETKEY", ppl)
        self.assertIn("MOUSE", ppl)
        self.assertIn("BLIT_P", ppl)
        self.assertIn("RECT_P(0,0,319,239,0,0)", ppl)

        # Keyboard controls
        self.assertIn("key_c==4 OR key_c==15 THEN is_run:=0", ppl)       # Esc / Clear exit
        self.assertIn("key_c==2 THEN oy:=oy+20", ppl)              # Up arrow
        self.assertIn("key_c==12 THEN oy:=oy-20", ppl)            # Down arrow
        self.assertIn("key_c==7 THEN ox:=ox+20", ppl)              # Left arrow
        self.assertIn("key_c==8 THEN ox:=ox-20", ppl)              # Right arrow
        self.assertIn("key_c==50 OR key_c==45", ppl)                   # '+' and '-' zoom keys
        self.assertIn("key_c==46 OR key_c==30", ppl)                   # '0' and Enter reset

        # Touch controls
        self.assertIn("ox:=ox+m_x-last_x", ppl)                     # Touch pan/drag
        self.assertIn("oy:=oy+m_y-last_y", ppl)
        self.assertIn("m_t==4", ppl)                             # Double tap zoom

    def test_build_gallery_app_directory(self):
        import tempfile
        import shutil
        from myhp.cli import main

        def make_dummy_png(w=2, h=2, color=(255, 0, 0)) -> bytes:
            def chunk(tag: bytes, body: bytes) -> bytes:
                return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
            ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
            stride = w * 3
            rows = []
            for _ in range(h):
                row = bytearray([0])
                for _ in range(w):
                    row.extend(color)
                rows.append(bytes(row))
            raw = b"".join(rows)
            return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

        with tempfile.TemporaryDirectory() as tmpdir:
            test_img = Path(tmpdir) / "sample.png"
            test_img.write_bytes(make_dummy_png())

            # 1. Single image file test with auto-generated icon
            app_dir = build_gallery_app_directory("mygallery", test_img, output_dir=tmpdir)
            self.assertTrue(app_dir.is_dir())
            self.assertEqual(app_dir.name, "MYGALLERY.hpappdir")

            self.assertTrue((app_dir / "MYGALLERY.hpapp").is_file())
            self.assertTrue((app_dir / "MYGALLERY.hpappnote").is_file())
            self.assertTrue((app_dir / "MYGALLERY.hpappprgm").is_file())
            self.assertTrue((app_dir / "icon.png").is_file())
            self.assertTrue((app_dir / "sample.png").is_file())

            # Icon should be 73x74 PNG generated from first image
            icon_data = (app_dir / "icon.png").read_bytes()
            self.assertTrue(icon_data.startswith(b"\x89PNG\r\n\x1a\n"))

            # Verify program export name and lifecycle views
            src = read_hpprgm_source((app_dir / "MYGALLERY.hpappprgm").read_bytes())
            self.assertIn("EXPORT MYGALLERY()", src)
            self.assertIn('VIEW "Help",START()', src)
            self.assertIn("AFiles()", src)

            # Test build_app_packet on Gallery app directory
            pkt = build_app_packet("MYGALLERY", app_dir)
            self.assertEqual(pkt[:2], b"\xF7\x03")
            uncomp_len = struct.unpack_from("<I", pkt, 6)[0]
            decomp = zlib.decompress(pkt[10:])
            self.assertEqual(len(decomp), uncomp_len)
            self.assertIn("sample.png".encode("utf-16le"), decomp)
            self.assertIn("icon.png".encode("utf-16le"), decomp)

        # 2. Multi-image test (directory input, explicit icon, fallback, sorting)
        with tempfile.TemporaryDirectory() as tmpdir:
            img_dir = Path(tmpdir) / "photos"
            img_dir.mkdir()
            (img_dir / "b_photo.jpg").write_bytes(b"JPEG_MOCK_DATA")
            (img_dir / "a_photo.png").write_bytes(make_dummy_png(color=(0, 255, 0)))
            (img_dir / "c_photo.bmp").write_bytes(b"BM_MOCK_DATA")
            (img_dir / "ignored.txt").write_bytes(b"NOT_AN_IMAGE")

            out_dir = Path(tmpdir) / "build"
            out_dir.mkdir()

            app_dir2 = build_gallery_app_directory("MultiPics", img_dir, output_dir=out_dir)
            self.assertEqual(app_dir2.name, "MULTIPICS.hpappdir")
            self.assertTrue((app_dir2 / "a_photo.png").is_file())
            self.assertTrue((app_dir2 / "b_photo.jpg").is_file())
            self.assertTrue((app_dir2 / "c_photo.bmp").is_file())
            self.assertFalse((app_dir2 / "ignored.txt").exists())

            # Check that build_app_packet contains all images
            pkt2 = build_app_packet("MULTIPICS", app_dir2)
            self.assertEqual(pkt2[:2], b"\xF7\x03")
            decomp2 = zlib.decompress(pkt2[10:])
            self.assertIn("a_photo.png".encode("utf-16le"), decomp2)
            self.assertIn("b_photo.jpg".encode("utf-16le"), decomp2)
            self.assertIn("c_photo.bmp".encode("utf-16le"), decomp2)
            self.assertNotIn("ignored.txt".encode("utf-16le"), decomp2)

            # Test list of paths with custom icon
            custom_icon = b"CUSTOM_PNG_ICON"
            app_dir3 = build_gallery_app_directory(
                "CustomList",
                [img_dir / "b_photo.jpg", img_dir / "a_photo.png"],
                icon=custom_icon,
                output_dir=out_dir,
            )
            self.assertEqual((app_dir3 / "icon.png").read_bytes(), custom_icon)

        # 3. CLI test: myhp send gallery <name> <images...> --output <out_dir>
        # Mock find_prime_devices to return [] to test offline local build path without USB communication
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmpdir:
            test_img1 = Path(tmpdir) / "cli1.png"
            test_img1.write_bytes(make_dummy_png())
            test_img2 = Path(tmpdir) / "cli2.png"
            test_img2.write_bytes(make_dummy_png())
            cli_out = Path(tmpdir) / "out"

            with patch("myhp.cli.find_prime_devices", return_value=[]):
                ret = main(["send", "gallery", "vacations", str(test_img1), str(test_img2), "--output", str(cli_out)])
            self.assertEqual(ret, 0)
            created = cli_out / "VACATIONS.hpappdir"
            self.assertTrue(created.is_dir())
            self.assertTrue((created / "cli1.png").is_file())
            self.assertTrue((created / "cli2.png").is_file())
            self.assertTrue((created / "VACATIONS.hpapp").is_file())
            self.assertTrue((created / "VACATIONS.hpappprgm").is_file())

        # 4. CLI test: mock device sending
        with tempfile.TemporaryDirectory() as tmpdir:
            test_img = Path(tmpdir) / "pic.png"
            test_img.write_bytes(make_dummy_png())
            cli_out = Path(tmpdir) / "out"

            from unittest.mock import MagicMock
            mock_dev = MagicMock()
            mock_dev.hidraw_path = "/dev/hidraw_dummy"
            mock_dev.model_name = "HP Prime G2"

            mock_app_item = MagicMock()
            mock_app_item.file_type = PrimeFileType.APP
            mock_app_item.name = "MYAPP"

            mock_prime = MagicMock()
            mock_prime.hidraw_path = "/dev/hidraw_dummy"
            mock_prime.__enter__.return_value = mock_prime
            mock_prime.send_app.return_value = 10
            mock_prime.list_content.return_value = [mock_app_item]

            with patch("myhp.cli.find_prime_devices", return_value=[mock_dev]), \
                 patch("myhp.cli.PrimeDevice", return_value=mock_prime), \
                 patch("time.sleep", return_value=None):
                ret = main(["send", "gallery", "myapp", str(test_img), "--output", str(cli_out)])
            self.assertEqual(ret, 0)
            mock_prime.send_app.assert_called_once()

        # 5. CLI test: send gallery without --output cleans up and does not pollute current working dir
        with tempfile.TemporaryDirectory() as tmpdir:
            test_img = Path(tmpdir) / "pic.png"
            test_img.write_bytes(make_dummy_png())

            from unittest.mock import MagicMock
            mock_dev = MagicMock()
            mock_dev.hidraw_path = "/dev/hidraw_dummy"
            mock_dev.model_name = "HP Prime G2"

            mock_app_item = MagicMock()
            mock_app_item.file_type = PrimeFileType.APP
            mock_app_item.name = "MYTEMPAPP"

            mock_prime = MagicMock()
            mock_prime.hidraw_path = "/dev/hidraw_dummy"
            mock_prime.__enter__.return_value = mock_prime
            mock_prime.send_app.return_value = 10
            mock_prime.list_content.return_value = [mock_app_item]

            cwd_before = set(Path(".").iterdir())
            with patch("myhp.cli.find_prime_devices", return_value=[mock_dev]), \
                 patch("myhp.cli.PrimeDevice", return_value=mock_prime), \
                 patch("time.sleep", return_value=None):
                ret = main(["send", "gallery", "mytempapp", str(test_img)])
            self.assertEqual(ret, 0)
            cwd_after = set(Path(".").iterdir())
            self.assertEqual(cwd_before, cwd_after)
            self.assertFalse(Path("MYTEMPAPP.hpappdir").exists())



if __name__ == "__main__":
    unittest.main()
