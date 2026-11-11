import struct
import tempfile
import unittest
import wave
from pathlib import Path
from wav_repair import repair, inspect_wav, AudioFormat, RepairError

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / 'input.wav'
        self.dest = self.root / 'fixed.wav'
        self.audio = struct.pack('<' + 'h' * 800, *range(800))
        with wave.open(str(self.src), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(self.audio)

    def tearDown(self):
        self.tmp.cleanup()

    def test_repair_zero_sizes(self):
        b = bytearray(self.src.read_bytes())
        b[4:8] = b'\0'*4
        b[40:44] = b'\0'*4
        self.src.write_bytes(b)
        result = repair(self.src, self.dest)
        self.assertAlmostEqual(result.duration_seconds, .1)
        with wave.open(str(self.dest), 'rb') as wf:
            self.assertEqual(wf.readframes(800), self.audio)

    def test_truncated_frame(self):
        b = bytearray(self.src.read_bytes())
        b[40:44] = b'\xff'*4
        b += b'X'
        self.src.write_bytes(b)
        repair(self.src, self.dest)
        with wave.open(str(self.dest), 'rb') as wf:
            self.assertEqual(wf.readframes(800), self.audio)

    def test_raw(self):
        self.src.write_bytes(b'garbage' + self.audio)
        repair(self.src, self.dest, raw_format=AudioFormat(1,1,8000,16), raw_offset=7)
        with wave.open(str(self.dest), 'rb') as wf:
            self.assertEqual(wf.readframes(800), self.audio)

    def test_original_preserved_and_no_overwrite(self):
        original = self.src.read_bytes()
        repair(self.src, self.dest)
        with self.assertRaises(RepairError):
            repair(self.src, self.dest)
        self.assertEqual(self.src.read_bytes(), original)

    def test_unsupported_codec(self):
        b = bytearray(self.src.read_bytes())
        b[20:22] = struct.pack('<H', 6)
        self.src.write_bytes(b)
        with self.assertRaises(RepairError):
            repair(self.src, self.dest)

if __name__ == '__main__':
    unittest.main()
