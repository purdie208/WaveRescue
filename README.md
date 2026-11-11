# WaveRescue

A Windows desktop app for recovering audio from WAV recordings interrupted by a restart, crash, or power loss. Built for QA agents: pick or drag a WAV, choose where to save, click **Repair recording**.

## Make the Windows EXE (one-time IT task)

On a Windows 10/11 machine with Python 3.10 or later installed, extract this project and double-click **build_windows.bat**. The build downloads PySide6 and PyInstaller. The finished distributable is **dist\WaveRescue.exe**; copy this single executable to QA computers. They do **not** need Python, ffmpeg, or administrative rights for normal use.

A code-signing certificate is recommended for enterprise distribution. Unsigned executables may trigger SmartScreen or endpoint security, so have IT approve and distribute it through your standard software deployment method. Build on the same Windows architecture/version family you support, and test on a nonproduction machine.

## How it works

1. Select/drag the source file.
2. Automatic mode locates the WAV format and audio data, ignoring or correcting broken header sizes, then writes a fresh PCM or IEEE float WAV container without transcoding the samples.
3. Pick a new destination and click Repair. Existing output files are **never overwritten**. The original remains untouched.
4. Play the result to check that the recording is intelligible and complete.

If a selected file has no recognizable WAV header, WaveRescue selects the **X-Lite preset** automatically for review. That preset interprets **100% of the file as signed 16-bit little-endian PCM, mono, 16,000 Hz, offset 0**; the repaired file still requires playback verification. If an actual broken 44-byte WAV header is present, use **Raw PCM recovery (advanced)** and set the offset to 44 instead. Do not skip 44 bytes if the file begins directly with audio. For other recording formats, verify the settings before using raw mode. For this X-Lite installation, the user confirmed that **16,000 Hz** produces correct playback in Audacity for the sample recording. Raw PCM recovery now defaults to **16,000 Hz, mono, 16-bit PCM, 0 skipped bytes**. Confirm playback for each recording; these parameters are not universally guaranteed.

## Important limits

- Can restore a broken/missing RIFF length or audio-data size when uncompressed audio bytes remain, and can rewrap raw PCM bytes.
- Cannot restore audio that was never saved, fix randomly damaged samples, or decode A-law, mu-law, MP3, ADPCM, or other compressed WAV codecs.
- Only writes standard RIFF WAV up to 4 GiB; huge recordings need RF64 support or splitting.
- If a crashed file has trailing metadata and an invalid data length, automatic mode may include those bytes as a short burst of unwanted audio at the end. Check the recording before treating it as evidence.
- WAV data lengths that are incorrect but still *plausible* may result in a partial recovery. In such cases raw mode may help, with a suitable skip offset.
- Raw mode is an interpretation, not signal processing; wrong audio settings produce incorrect speed or noise.
- For evidentiary recordings, retain the original, document the recovery, and verify output before relying on it.

## Privacy

Local file processing only; does not upload any audio, does not use the internet, and does not write diagnostic logs. The build step (only) downloads Python packages from pip.

## Appearance

Use the **Appearance** selector in the upper-right corner to switch between **Dark** and **Light**. The selection persists on that Windows user profile. The design uses a neutral slate background, accessible light/dark text, blue primary actions, and teal progress rather than purple branding.

## Observed X-Lite damaged example (November 10, 2026)

A real interrupted recording was inspected. It is 16,863,232 bytes and begins with sample-like little-endian data, with no RIFF/WAVE header. As a result, **automatic WAV header repair cannot restore it**; WaveRescue selects its **X-Lite preset** when this file is opened. Its bytes are consistent with signed 16-bit PCM, but file contents alone do not prove the original sampling rate or number of channels. The user confirmed that Audacity recovery at **16,000 Hz**, instead of 8,000 Hz, gives the correct playback speed. WaveRescue now defaults to **16,000 Hz, mono, 16-bit PCM, zero skipped bytes** for raw recovery. The sample-rate choice is supported by listening results, not by metadata in this damaged file; verify channel count and recovered output as well.

## Confirmed X-Lite Audacity import parameters

Signed 16-bit PCM, little-endian, 1 channel (mono), 16,000 Hz, start offset 0 bytes (or 44 bytes ONLY for a file that retains a damaged 44-byte WAV header), import 100%. The preset uses offset 0; advanced mode allows 44. This is a raw audio rewrap, not restoration of audio never written to disk.
