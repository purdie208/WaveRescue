"""Lossless WAV header reconstruction for interrupted PCM/float recordings.

Never alters input. Does not fabricate samples or decode encoded formats.
"""
from __future__ import annotations

import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

Progress = Optional[Callable[[int], None]]


class RepairError(Exception):
    pass


@dataclass
class AudioFormat:
    tag: int
    channels: int
    sample_rate: int
    bits: int
    valid_bits: int | None = None

    @property
    def block_align(self) -> int:
        return self.channels * ((self.bits + 7) // 8)

    @property
    def byte_rate(self) -> int:
        return self.sample_rate * self.block_align

    def validate(self) -> None:
        if self.tag not in (1, 3):
            raise RepairError('This tool only supports uncompressed PCM or IEEE float WAV audio.')
        if not 1 <= self.channels <= 32:
            raise RepairError('Invalid channel count.')
        if not 1000 <= self.sample_rate <= 384000:
            raise RepairError('Invalid sample rate.')
        if self.tag == 1 and self.bits not in (8, 16, 24, 32):
            raise RepairError('Unsupported PCM bit depth (expected 8, 16, 24, or 32).')
        if self.tag == 3 and self.bits not in (32, 64):
            raise RepairError('Unsupported float bit depth (expected 32 or 64).')
        if self.block_align == 0 or self.byte_rate > 0xFFFFFFFF:
            raise RepairError('Invalid audio format.')


@dataclass
class Result:
    destination: Path
    recovered_bytes: int
    duration_seconds: float
    details: str


def _fmt_from_bytes(blob: bytes) -> AudioFormat:
    if len(blob) < 16:
        raise RepairError('Incomplete WAV format information.')
    tag, channels, rate, byte_rate, align, bits = struct.unpack_from('<HHIIHH', blob)
    valid_bits = None
    if tag == 0xFFFE:  # WAVE_FORMAT_EXTENSIBLE
        if len(blob) < 40:
            raise RepairError('Incomplete WAVE_FORMAT_EXTENSIBLE header.')
        valid_bits = struct.unpack_from('<H', blob, 18)[0]
        guid = blob[24:40]
        guid_tail = bytes.fromhex('00001000800000aa00389b71')
        if guid[4:] != guid_tail:
            raise RepairError('Unsupported extended WAV codec; PCM/float only.')
        sub_tag = struct.unpack_from('<I', guid)[0]
        if sub_tag not in (1, 3):
            raise RepairError('Unsupported extended WAV codec; PCM/float only.')
        tag = sub_tag
    fmt = AudioFormat(tag, channels, rate, bits, valid_bits)
    fmt.validate()
    # Some crashed applications leave byte_rate/block_align inaccurate. The
    # actual PCM layout comes from channel count and container bit depth.
    return fmt


def inspect_wav(path: Path) -> tuple[AudioFormat, int, int, str]:
    """Locate a valid fmt chunk and audio data chunk, even with broken sizes.

    Scan only within first 4 MiB. Trust an aligned data size only if it is
    credible; otherwise take remaining bytes. The latter may include trailing
    metadata if the recorder appended it (reported in details).
    """
    total = path.stat().st_size
    if total < 32:
        raise RepairError('The source is too small to contain a WAV recording.')
    with path.open('rb') as f:
        lead = f.read(min(total, 4 * 1024 * 1024))
    if lead[:4] not in (b'RIFF', b'RF64', b'BW64') or lead[8:12] != b'WAVE':
        raise RepairError('Not a recognizable WAV container. Try Raw PCM mode only if you know the recording format.')

    # First try normal chunk walking. A broken size can prevent reaching data,
    # so a constrained signature scan is the backup.
    possible_fmt: list[int] = []
    possible_data: list[int] = []
    p = 12
    while p + 8 <= len(lead):
        name = lead[p:p+4]
        size = struct.unpack_from('<I', lead, p+4)[0]
        if name == b'fmt ':
            possible_fmt.append(p)
        if name == b'data':
            possible_data.append(p)
        nxt = p + 8 + size + (size & 1)
        if nxt <= p or nxt > len(lead):
            break
        p = nxt
    # Search on two-byte boundaries; chunks are word-aligned, and this avoids
    # interpreting ordinary arbitrary PCM as a header in most cases.
    for needle, dest in ((b'fmt ', possible_fmt), (b'data', possible_data)):
        start = 12
        while True:
            i = lead.find(needle, start)
            if i < 0:
                break
            if i % 2 == 0 and i not in dest:
                dest.append(i)
            start = i + 1

    candidates = []
    for fp in sorted(possible_fmt):
        if fp + 24 > len(lead):
            continue
        n = struct.unpack_from('<I', lead, fp+4)[0]
        if not 16 <= n <= 4096 or fp + 8 + n > len(lead):
            continue
        try:
            fmt = _fmt_from_bytes(lead[fp+8:fp+8+n])
        except RepairError:
            continue
        for dp in sorted(possible_data):
            if dp < fp + 8 + n or dp + 8 >= total:
                continue
            declared = struct.unpack_from('<I', lead, dp+4)[0]
            available = total - (dp + 8)
            if available <= 0:
                continue
            # The header may claim a stale length (typical after crash). If
            # believable, use it; otherwise consume all complete sample frames.
            if declared not in (0, 0xFFFFFFFF) and declared <= available and declared % fmt.block_align == 0:
                data_len = declared
                reason = 'Recovered audio using the WAV data chunk length.'
                if available - declared > 0:
                    reason += ' Additional bytes after that chunk were excluded.'
            else:
                data_len = available
                reason = 'Data length was missing or invalid; recovered complete sample frames through end of file.'
            data_len -= data_len % fmt.block_align
            if data_len <= 0:
                continue
            # Prefer first fmt then first data with reasonable proximity.
            candidates.append((fp, dp, fmt, data_len, reason))
    if not candidates:
        raise RepairError('Could not find a complete PCM/float format header and audio data. Raw PCM mode may help if the audio encoding is known.')
    fp, dp, fmt, data_len, reason = min(candidates, key=lambda x: (x[0], x[1]))
    return fmt, dp + 8, data_len, reason


def _wav_header(fmt: AudioFormat, length: int) -> bytes:
    # Canonical RIFF PCM or IEEE float; float gets a fact chunk. Keep source
    # bit/container depth (not a lossy conversion).
    fmt_chunk = struct.pack('<4sIHHIIHH', b'fmt ', 16, fmt.tag, fmt.channels,
                            fmt.sample_rate, fmt.byte_rate, fmt.block_align, fmt.bits)
    fact = b''
    if fmt.tag == 3:
        frames = length // fmt.block_align
        fact = struct.pack('<4sII', b'fact', 4, frames)
    riff_size = 4 + len(fmt_chunk) + len(fact) + 8 + length
    if riff_size > 0xFFFFFFFF or length > 0xFFFFFFFF:
        raise RepairError('This recording is too large for a standard WAV file (>4 GiB).')
    return b'RIFF' + struct.pack('<I', riff_size) + b'WAVE' + fmt_chunk + fact + b'data' + struct.pack('<I', length)


def repair(source: str | Path, dest: str | Path, *, raw_format: AudioFormat | None = None,
           raw_offset: int = 0, progress: Progress = None) -> Result:
    source = Path(source)
    dest = Path(dest)
    if not source.is_file():
        raise RepairError('Source file does not exist.')
    if source.resolve() == dest.resolve():
        raise RepairError('Choose a different output path. The original is never overwritten.')
    if raw_format is None:
        fmt, offset, length, details = inspect_wav(source)
    else:
        raw_format.validate()
        fmt = raw_format
        total = source.stat().st_size
        if not 0 <= raw_offset < total:
            raise RepairError('Raw PCM skip offset must be smaller than file size.')
        offset = raw_offset
        length = total - offset
        length -= length % fmt.block_align
        details = 'Raw PCM interpretation; correct playback depends on the parameters supplied.'
    if not length:
        raise RepairError('No complete audio frames to recover.')
    header = _wav_header(fmt, length)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write a temp file in the output directory, then atomically move it into
    # place only after all bytes have been copied successfully.
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.waverescue-', suffix='.tmp', dir=dest.parent, delete=False) as out:
            temp_name = out.name
            out.write(header)
            with source.open('rb') as src:
                src.seek(offset)
                remaining = length
                copied = 0
                while remaining:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise RepairError('The source ended before the expected audio data.')
                    out.write(chunk)
                    remaining -= len(chunk)
                    copied += len(chunk)
                    if progress:
                        progress(int(100 * copied / length))
            out.flush()
            os.fsync(out.fileno())
        # Refuse accidental replacement, including races with an existing file.
        # Windows rename refuses to replace an existing target, and works on
        # network shares that do not allow hard links. On other systems, link
        # explicitly fails if the destination exists.
        if dest.exists():
            raise RepairError('Output file already exists. Choose another filename.')
        if os.name == 'nt':
            os.rename(temp_name, dest)
        else:
            os.link(temp_name, dest)
            os.unlink(temp_name)
        temp_name = None
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return Result(dest, length, length / fmt.byte_rate, details)
