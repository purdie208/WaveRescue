"""WaveRescue — drag-and-drop Windows GUI for interrupted WAV recordings."""
import sys
import traceback
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSettings
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from wav_repair import AudioFormat, RepairError, inspect_wav, repair


class DropZone(QFrame):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('drop')
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        title = QLabel('↓  Drop a damaged WAV recording here')
        title.setObjectName('dropTitle')
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel('Or select a file from your computer')
        sub.setObjectName('muted')
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(sub)
        self.setMinimumHeight(126)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        local = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if local:
            self.file_dropped.emit(local[0])
            event.acceptProposedAction()


class Worker(QThread):
    progress_changed = Signal(int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, src, dest, fmt, offset):
        super().__init__()
        self.src, self.dest, self.fmt, self.offset = src, dest, fmt, offset

    def run(self):
        try:
            result = repair(self.src, self.dest, raw_format=self.fmt,
                            raw_offset=self.offset, progress=self.progress_changed.emit)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WaveRescue — WAV Recording Recovery')
        self.resize(760, 720)
        self.setMinimumSize(650, 650)
        self.worker = None
        self.settings = QSettings('WaveRescue', 'WaveRescue')
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(34, 26, 34, 26)
        main.setSpacing(16)

        brand = QLabel('◉  WaveRescue')
        brand.setObjectName('brand')
        subtitle = QLabel('Recover playable audio from interrupted or damaged WAV recordings.')
        subtitle.setObjectName('muted')
        top = QHBoxLayout()
        top.addWidget(brand, 1)
        top.addWidget(QLabel('Appearance'))
        self.theme = QComboBox()
        self.theme.setAccessibleName('Application appearance')
        self.theme.addItems(['Dark', 'Light'])
        self.theme.setFixedWidth(120)
        self.theme.setCurrentText(self.settings.value('theme', 'Dark'))
        self.theme.currentTextChanged.connect(self.set_theme)
        top.addWidget(self.theme)
        main.addLayout(top)
        main.addWidget(subtitle)

        self.drop = DropZone()
        self.drop.file_dropped.connect(self.set_source)
        main.addWidget(self.drop)

        browse_row = QHBoxLayout()
        self.src_input = QLineEdit()
        self.src_input.setPlaceholderText('Choose a corrupted .wav file')
        self.src_input.setReadOnly(True)
        browse = QPushButton('Browse…')
        browse.clicked.connect(self.browse_source)
        browse_row.addWidget(self.src_input, 1)
        browse_row.addWidget(browse)
        main.addLayout(browse_row)

        self.info = QLabel('Your original recording is never changed.')
        self.info.setWordWrap(True)
        self.info.setObjectName('muted')
        main.addWidget(self.info)

        mode_row = QHBoxLayout()
        mode_label = QLabel('Recovery mode')
        mode_label.setObjectName('section')
        self.mode = QComboBox()
        self.mode.addItems(['Automatic WAV header repair', 'X-Lite preset — 16 kHz mono PCM', 'Raw PCM recovery (advanced)'])
        self.mode.currentIndexChanged.connect(self.toggle_raw)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.mode, 1)
        main.addLayout(mode_row)

        self.raw_frame = QFrame()
        self.raw_frame.setObjectName('panel')
        raw_lay = QFormLayout(self.raw_frame)
        self.rate = QComboBox()
        self.rate.addItems(['8000', '16000', '22050', '32000', '44100', '48000'])
        self.rate.setCurrentText('16000')
        self.channels = QComboBox()
        self.channels.addItems(['1', '2'])
        self.depth = QComboBox()
        self.depth.addItems(['8', '16', '24', '32'])
        self.depth.setCurrentText('16')
        self.skip = QSpinBox()
        self.skip.setRange(0, 4 * 1024 * 1024)
        self.skip.setValue(0)
        self.skip.setSuffix(' bytes')
        raw_lay.addRow('Sample rate (Hz)', self.rate)
        raw_lay.addRow('Channels', self.channels)
        raw_lay.addRow('PCM bit depth', self.depth)
        raw_lay.addRow('Skip bytes from start', self.skip)
        hint = QLabel('X-Lite recovery starting point: 16,000 Hz, mono, 16-bit PCM, skip 0 bytes (confirmed by Audacity playback for one damaged recording). Other files may differ. Verify recovered audio.')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        raw_lay.addRow(hint)
        self.raw_frame.hide()
        main.addWidget(self.raw_frame)

        out_title = QLabel('Save repaired recording as')
        out_title.setObjectName('section')
        main.addWidget(out_title)
        dest_row = QHBoxLayout()
        self.dest_input = QLineEdit()
        self.dest_input.setPlaceholderText('Choose output location…')
        out_browse = QPushButton('Save as…')
        out_browse.clicked.connect(self.browse_destination)
        dest_row.addWidget(self.dest_input, 1)
        dest_row.addWidget(out_browse)
        main.addLayout(dest_row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        main.addWidget(self.progress)
        self.status = QLabel('Ready. Select a recording to begin.')
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        main.addWidget(self.status)
        main.addStretch(1)
        self.run_button = QPushButton('Repair recording')
        self.run_button.setObjectName('primary')
        self.run_button.setMinimumHeight(48)
        self.run_button.clicked.connect(self.start)
        main.addWidget(self.run_button)
        footer = QLabel('Processes locally  •  Original preserved  •  PCM / IEEE float')
        footer.setAlignment(Qt.AlignCenter)
        footer.setObjectName('muted')
        main.addWidget(footer)
        self.set_theme(self.theme.currentText())

    def set_theme(self, theme):
        self.settings.setValue('theme', theme)
        QApplication.instance().setStyleSheet(make_stylesheet(theme == 'Dark'))

    def toggle_raw(self):
        self.raw_frame.setVisible(self.mode.currentIndex() == 2)
        if self.mode.currentIndex() == 1:
            self.info.setText('X-Lite preset: signed 16-bit PCM, little-endian, mono, 16,000 Hz, offset 0. Uses all complete samples. Confirm correct playback after recovery.')
        elif self.mode.currentIndex() == 2:
            self.info.setText('Advanced raw PCM: choose the correct parameters. Use 44-byte skip only when a damaged 44-byte header actually exists.')
        else:
            self.inspect()

    def browse_source(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Open recording', '', 'WAV files (*.wav *.wave);;All files (*)')
        if filename:
            self.set_source(filename)

    def set_source(self, path):
        src = Path(path)
        if not src.is_file():
            QMessageBox.warning(self, 'File not found', 'Select an existing recording file.')
            return
        self.src_input.setText(str(src))
        self.dest_input.setText(str(src.with_name(src.stem + '_repaired.wav')))
        self.progress.setValue(0)
        self.status.setText('File selected. Ready to repair.')
        self.mode.setCurrentIndex(0)
        self.inspect()

    def inspect(self):
        if self.mode.currentIndex() or not self.src_input.text():
            return
        try:
            fmt, off, nbytes, detail = inspect_wav(Path(self.src_input.text()))
            self.info.setText(f'Detected: {fmt.sample_rate:,} Hz · {fmt.channels} channel(s) · {fmt.bits}-bit '
                              f'{"PCM" if fmt.tag == 1 else "float"} · {nbytes / fmt.byte_rate:,.1f} seconds.\n{detail}')
        except (RepairError, OSError) as exc:
            # Only suggest raw interpretation automatically when the WAV container signature is absent.
            # A recognizable WAV with an unsupported codec needs investigation, not blind PCM decoding.
            try:
                with Path(self.src_input.text()).open('rb') as handle:
                    start = handle.read(12)
            except OSError:
                start = b''
            missing_header = not (start[:4] in (b'RIFF', b'RF64', b'BW64') and start[8:12] == b'WAVE')
            if missing_header:
                self.mode.setCurrentIndex(1)
                self.info.setText('No recognizable WAV header detected. Selected the X-Lite recovery preset (16,000 Hz, signed 16-bit little-endian mono, offset 0). This is based on your Audacity settings, not automatic identification of the audio encoding. Listen to the result to verify.')
            else:
                self.info.setText(f'Automatic inspection: {exc}\nThis file has a WAV signature but could not be safely interpreted. Consult IT before selecting raw PCM recovery.')

    def browse_destination(self):
        initial = self.dest_input.text() or 'repaired.wav'
        filename, _ = QFileDialog.getSaveFileName(self, 'Save recovered WAV', initial, 'WAV files (*.wav)')
        if filename:
            self.dest_input.setText(filename)

    def start(self):
        src, dst = self.src_input.text().strip(), self.dest_input.text().strip()
        if not src or not dst:
            QMessageBox.warning(self, 'Missing file', 'Choose an input file and output destination.')
            return
        if not dst.lower().endswith('.wav'):
            dst += '.wav'
            self.dest_input.setText(dst)
        if Path(dst).exists():
            QMessageBox.warning(self, 'Output exists', 'Please choose a new output filename. WaveRescue never overwrites files.')
            return
        fmt = None
        offset = 0
        if self.mode.currentIndex() == 1:
            fmt = AudioFormat(1, 1, 16000, 16)
            offset = 0
        elif self.mode.currentIndex() == 2:
            fmt = AudioFormat(1, int(self.channels.currentText()), int(self.rate.currentText()), int(self.depth.currentText()))
            offset = self.skip.value()
        self.run_button.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText('Repairing…')
        self.worker = Worker(src, dst, fmt, offset)
        self.worker.progress_changed.connect(self.progress.setValue)
        self.worker.succeeded.connect(self.done)
        self.worker.failed.connect(self.failed)
        self.worker.start()

    def done(self, result):
        self.run_button.setEnabled(True)
        self.progress.setValue(100)
        self.status.setText(f'✓ Recovered {result.duration_seconds:,.1f} seconds of audio. Saved to {result.destination}\n{result.details}')
        QMessageBox.information(self, 'Recovery complete', f'Saved recovered recording to:\n{result.destination}\n\nThe original file was not modified.\n\nListen to the output to verify the recovered audio.')

    def failed(self, reason):
        self.run_button.setEnabled(True)
        self.status.setText(f'Unable to repair: {reason}')
        QMessageBox.warning(self, 'Recovery unsuccessful', reason)



def make_stylesheet(dark):
    # WCAG-minded contrasting palette; blue is the action color, teal signals success.
    c = ({'bg':'#101820','surface':'#192530','field':'#223241','line':'#42586b',
          'text':'#f3f7fa','muted':'#bacbd8','accent':'#55b4e5','button':'#263b4c',
          'hover':'#34526a','primary':'#1674ae','primary_hover':'#0b6398',
          'primary_text':'#ffffff','disabled':'#3b4a55','dim':'#b4c2cc',
          'drop':'#1b303e','bar':'#2a4050','success':'#36c7ac'} if dark else
         {'bg':'#f3f7fa','surface':'#ffffff','field':'#ffffff','line':'#8399a9',
          'text':'#172d3e','muted':'#425c6f','accent':'#075d90','button':'#e4edf3',
          'hover':'#d3e5f0','primary':'#075d90','primary_hover':'#064b75',
          'primary_text':'#ffffff','disabled':'#cbd5dc','dim':'#506676',
          'drop':'#e8f3f9','bar':'#d7e4eb','success':'#087a65'})
    return """
    QWidget {{ background:{bg}; color:{text}; font-size:13px; }}
    QMainWindow {{ background:{bg}; }}
    QLabel#brand {{ color:{accent}; font-size:28px; font-weight:750; }}
    QLabel#muted {{ color:{muted}; font-size:12px; }}
    QLabel#section {{ font-size:14px; font-weight:700; }}
    QFrame#drop {{ background:{drop}; border:2px dashed {accent}; border-radius:14px; }}
    QLabel#dropTitle {{ color:{text}; font-size:16px; font-weight:700; background:transparent; }}
    QFrame#drop QLabel {{ background:transparent; }}
    QFrame#panel {{ background:{surface}; border:1px solid {line}; border-radius:10px; padding:8px; }}
    QFrame#panel QLabel {{ background:transparent; }}
    QLineEdit, QComboBox, QSpinBox {{ background:{field}; color:{text}; border:1px solid {line}; border-radius:8px; padding:9px; selection-background-color:{primary}; }}
    QComboBox::drop-down {{ border:0; width:25px; }}
    QComboBox QAbstractItemView {{ background:{surface}; color:{text}; selection-background-color:{primary}; selection-color:white; }}
    QPushButton {{ background:{button}; border:1px solid {line}; border-radius:8px; padding:9px 15px; font-weight:650; }}
    QPushButton:hover {{ background:{hover}; }}
    QPushButton#primary {{ background:{primary}; color:{primary_text}; border:0; font-size:15px; }}
    QPushButton#primary:hover {{ background:{primary_hover}; }}
    QPushButton:disabled {{ background:{disabled}; color:{dim}; }}
    QProgressBar {{ background:{bar}; border:0; border-radius:6px; min-height:12px; text-align:center; }}
    QProgressBar::chunk {{ background:{success}; border-radius:6px; }}
    QMessageBox {{ background:{bg}; }}
    """.format(**c)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setFont(QFont('Segoe UI', 10))
    win = Window()
    win.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
