"""Qt (PySide6) graphical interface."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QTextEdit, QPushButton, QRadioButton, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .engine import SUPPORTED_EXTS, clean_file, detect_kind, iter_files
from .report import Options, Report
from .text import LINE_SEPARATORS, SPACES, char_name, classify, clean_text

OPTION_LABELS = [
    ("invisible", "Invisible characters", "Zero-width spaces/joiners, BOMs, bidi controls, hidden Unicode "
                                          "tag text, variation selectors, control characters"),
    ("spaces", "Exotic spaces", "Non-breaking, thin, narrow, ideographic... spaces become normal spaces"),
    ("typography", "AI typography", "Em/en dashes, curly quotes and ellipsis become plain ASCII"),
    ("citations", "Chatbot artifacts", "ChatGPT/Grok citation markers, oaicite references, "
                                       "utm_source=chatgpt.com links, chat-UI HTML attributes"),
    ("metadata", "Metadata && provenance", "EXIF/XMP/IPTC, C2PA content credentials, AI prompt fields, "
                                          "document properties, generator fingerprints, PDF info"),
    ("symbols", "Decorative emoji/icons", "Strip chatbot-style emoji and icons (✅ 🚀 ⓘ ✨). "
                                          "Form checkboxes ☐ are kept"),
    ("preserve_legit", "Keep script-required joiners", "Keep ZWJ/ZWNJ/variation selectors where emoji, "
                                                       "Arabic/Persian or Indic text needs them"),
    ("keep_icc", "Keep image colour profile", "ICC profiles affect colours only, not provenance"),
]

STATUS_COLORS = {"FIXED": "#2e9d5b", "CLEAN": "#6b7a8f", "FOUND": "#d08a1d", "FAIL": "#d0453b",
                 "…": "#6b7a8f"}


class Worker(QObject):
    progress = Signal(int, object)   # row, Result
    finished = Signal()

    def __init__(self, jobs, out_dir, opts, suffix, in_place, dry_run):
        super().__init__()
        self.jobs, self.out_dir, self.opts = jobs, out_dir, opts
        self.suffix, self.in_place, self.dry_run = suffix, in_place, dry_run
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for row, path in self.jobs:
            if self._stop:
                break
            res = clean_file(path, self.out_dir, self.opts, self.suffix, self.in_place, self.dry_run)
            self.progress.emit(row, res)
        self.finished.emit()


class DropArea(QFrame):
    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("drop")
        self.setMinimumHeight(110)
        lay = QVBoxLayout(self)
        title = QLabel("Drop files or folders here")
        title.setAlignment(Qt.AlignCenter)
        f = title.font()
        f.setPointSize(f.pointSize() + 4)
        f.setBold(True)
        title.setFont(f)
        sub = QLabel("Text, Markdown, HTML, code · DOCX / XLSX / PPTX / ODT / EPUB · PDF · "
                     "JPG / PNG / WEBP / GIF / TIFF · audio & video (ffmpeg)")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setObjectName("muted")
        lay.addStretch()
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addStretch()
        self._set_hover(False)

    def _set_hover(self, on: bool):
        self.setProperty("hover", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, e):
        self._set_hover(False)

    def dropEvent(self, e):
        self._set_hover(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"AI Cleanup {__version__}")
        self.resize(1100, 760)
        self.setAcceptDrops(True)
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.results: dict[int, object] = {}

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 10)
        self.setCentralWidget(central)

        # ---- options (shared)
        box = QGroupBox("What to remove")
        grid = QGridLayout(box)
        self.checks: dict[str, QCheckBox] = {}
        defaults = Options()
        for i, (key, label, tip) in enumerate(OPTION_LABELS):
            cb = QCheckBox(label)
            cb.setToolTip(tip)
            cb.setChecked(getattr(defaults, key))
            cb.toggled.connect(self._options_changed)
            self.checks[key] = cb
            grid.addWidget(cb, i // 4, i % 4)
        root.addWidget(box)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._files_tab(), "Files")
        self.tabs.addTab(self._text_tab(), "Paste text")
        root.addWidget(self.tabs, 1)

        self.statusBar().showMessage("Ready - add files or switch to 'Paste text'")

    # ------------------------------------------------------------------ files tab
    def _files_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.drop = DropArea()
        self.drop.dropped.connect(self.add_paths)
        lay.addWidget(self.drop)

        btns = QHBoxLayout()
        add_f = QPushButton("Add files…")
        add_f.clicked.connect(self._pick_files)
        add_d = QPushButton("Add folder…")
        add_d.clicked.connect(self._pick_folder)
        clr = QPushButton("Clear list")
        clr.clicked.connect(self._clear)
        btns.addWidget(add_f)
        btns.addWidget(add_d)
        btns.addWidget(clr)
        btns.addStretch()
        lay.addLayout(btns)

        split = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Type", "Status", "Removed"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 70)
        self.tree.itemSelectionChanged.connect(self._show_details)
        self.tree.itemDoubleClicked.connect(self._open_item)
        split.addWidget(self.tree)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a file to see exactly what was found and removed.")
        split.addWidget(self.details)
        split.setSizes([380, 140])
        lay.addWidget(split, 1)

        # output options
        out = QHBoxLayout()
        self.out_group = QButtonGroup(self)
        self.rb_next = QRadioButton("Next to original")
        self.rb_dir = QRadioButton("Into folder:")
        self.rb_inplace = QRadioButton("Overwrite originals")
        for i, rb in enumerate((self.rb_next, self.rb_dir, self.rb_inplace)):
            self.out_group.addButton(rb, i)
        self.rb_next.setChecked(True)
        self.suffix = QLineEdit(".cleaned")
        self.suffix.setMaximumWidth(90)
        self.suffix.setToolTip("Suffix added to output file names")
        self.out_dir = QLineEdit(str(Path.home() / "AI-Cleanup-output"))
        browse = QPushButton("…")
        browse.setMaximumWidth(34)
        browse.clicked.connect(self._pick_out)
        out.addWidget(QLabel("Save:"))
        out.addWidget(self.rb_next)
        out.addWidget(QLabel("suffix"))
        out.addWidget(self.suffix)
        out.addSpacing(12)
        out.addWidget(self.rb_dir)
        out.addWidget(self.out_dir, 1)
        out.addWidget(browse)
        out.addSpacing(12)
        out.addWidget(self.rb_inplace)
        lay.addLayout(out)

        act = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.btn_scan = QPushButton("Scan only")
        self.btn_scan.setToolTip("Report what would be removed without writing anything")
        self.btn_scan.clicked.connect(lambda: self._start(dry_run=True))
        self.btn_clean = QPushButton("Clean files")
        self.btn_clean.setObjectName("primary")
        self.btn_clean.clicked.connect(lambda: self._start(dry_run=False))
        self.btn_open = QPushButton("Open output folder")
        self.btn_open.clicked.connect(self._open_output)
        act.addWidget(self.progress, 1)
        act.addWidget(self.btn_open)
        act.addWidget(self.btn_scan)
        act.addWidget(self.btn_clean)
        lay.addLayout(act)
        return w

    # ------------------------------------------------------------------ text tab
    def _text_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        paste = QPushButton("Paste from clipboard")
        paste.clicked.connect(lambda: self.inp.setPlainText(QGuiApplication.clipboard().text()))
        self.copy_btn = QPushButton("Copy cleaned text")
        self.copy_btn.setObjectName("primary")
        self.copy_btn.clicked.connect(self._copy_clean)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.inp.clear())
        self.text_stats = QLabel("")
        self.text_stats.setObjectName("muted")
        self.text_stats.setWordWrap(True)
        bar.addWidget(paste)
        bar.addWidget(clear)
        bar.addWidget(self.text_stats, 1)
        bar.addWidget(self.copy_btn)
        lay.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        mono = QFont("Consolas" if sys.platform == "win32" else "Monospace")
        mono.setStyleHint(QFont.Monospace)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Original - hidden characters are highlighted"))
        self.inp = QPlainTextEdit()
        self.inp.setPlaceholderText("Paste AI-generated text here…")
        self.inp.setFont(mono)
        ll.addWidget(self.inp)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Cleaned"))
        self.outp = QPlainTextEdit()
        self.outp.setReadOnly(True)
        self.outp.setFont(mono)
        rl.addWidget(self.outp)
        split.addWidget(left)
        split.addWidget(right)
        lay.addWidget(split, 1)

        self.hidden_list = QPlainTextEdit()
        self.hidden_list.setReadOnly(True)
        self.hidden_list.setMaximumHeight(110)
        self.hidden_list.setPlaceholderText("Hidden characters found will be listed here with their positions.")
        lay.addWidget(self.hidden_list)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._refresh_text)
        self.inp.textChanged.connect(self._debounce.start)
        return w

    # ------------------------------------------------------------------ helpers
    def options(self) -> Options:
        return Options(**{k: cb.isChecked() for k, cb in self.checks.items()})

    def _options_changed(self):
        if self.inp.toPlainText():
            self._refresh_text()

    def _refresh_text(self):
        text = self.inp.toPlainText()
        cleaned, rep = clean_text(text, self.options())
        self.outp.setPlainText(cleaned)
        self.text_stats.setText(f"Removed/changed: {rep.summary()}" if rep.total else
                                ("No AI traces found." if text else ""))
        # highlight hidden chars in the input and list them
        sels, lines = [], []
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#ff5a5f"))
        fmt.setForeground(QColor("white"))
        doc = self.inp.document()
        for i, ch in enumerate(text):
            cp = ord(ch)
            if classify(ch) or cp in SPACES or cp in LINE_SEPARATORS:
                if len(lines) < 500:
                    lines.append(f"pos {i:>6}: U+{cp:04X}  {char_name(ch)}")
                if len(sels) < 5000:
                    sel = QTextEdit.ExtraSelection()
                    cur = QTextCursor(doc)
                    cur.setPosition(i)
                    cur.setPosition(i + 1, QTextCursor.KeepAnchor)
                    sel.cursor = cur
                    sel.format = fmt
                    sels.append(sel)
        self.inp.setExtraSelections(sels)
        self.hidden_list.setPlainText("\n".join(lines) if lines else "")

    def _copy_clean(self):
        QGuiApplication.clipboard().setText(self.outp.toPlainText())
        self.statusBar().showMessage("Cleaned text copied to clipboard", 3000)

    def _pick_files(self):
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files", "",
                                                f"Supported files ({exts});;All files (*)")
        self.add_paths(files)

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose folder")
        if d:
            self.add_paths([d])

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.out_dir.text())
        if d:
            self.out_dir.setText(d)
            self.rb_dir.setChecked(True)

    def _clear(self):
        if self.thread:
            return
        self.tree.clear()
        self.results.clear()
        self.details.clear()
        self.progress.setValue(0)

    def add_paths(self, paths):
        existing = {self.tree.topLevelItem(i).data(0, Qt.UserRole)
                    for i in range(self.tree.topLevelItemCount())}
        added = 0
        for f in iter_files(paths, suffix=self.suffix.text() or ".cleaned"):
            key = str(f.resolve())
            if key in existing:
                continue
            existing.add(key)
            it = QTreeWidgetItem([str(f), detect_kind(f), "", ""])
            it.setData(0, Qt.UserRole, key)
            it.setToolTip(0, str(f))
            self.tree.addTopLevelItem(it)
            added += 1
        self.statusBar().showMessage(f"Added {added} file(s)", 3000)
        self.tabs.setCurrentIndex(0)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if self.tabs.currentIndex() == 1 and len(paths) == 1 and Path(paths[0]).is_file() \
                and detect_kind(Path(paths[0])) in ("text", "code"):
            self.inp.setPlainText(Path(paths[0]).read_text(encoding="utf-8", errors="replace"))
        else:
            self.add_paths(paths)

    def _out_dir(self) -> Path | None:
        return Path(self.out_dir.text()).expanduser() if self.rb_dir.isChecked() else None

    def _start(self, dry_run: bool):
        n = self.tree.topLevelItemCount()
        if not n or self.thread:
            return
        if self.rb_inplace.isChecked() and not dry_run:
            if QMessageBox.question(self, "Overwrite originals?",
                                    f"This will overwrite {n} original file(s). Continue?") \
                    != QMessageBox.Yes:
                return
        jobs = []
        for i in range(n):
            it = self.tree.topLevelItem(i)
            it.setText(2, "…")
            it.setText(3, "")
            jobs.append((i, Path(it.data(0, Qt.UserRole))))
        self.results.clear()
        self.progress.setMaximum(n)
        self.progress.setValue(0)
        self._set_busy(True)
        self.thread = QThread()
        self.worker = Worker(jobs, self._out_dir(), self.options(), self.suffix.text() or ".cleaned",
                             self.rb_inplace.isChecked(), dry_run)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_result)
        self.worker.finished.connect(self._on_done)
        self.worker.finished.connect(self.thread.quit)
        self._dry = dry_run
        self.thread.start()

    def _set_busy(self, busy: bool):
        for b in (self.btn_scan, self.btn_clean):
            b.setEnabled(not busy)

    def _on_result(self, row: int, res):
        self.results[row] = res
        it = self.tree.topLevelItem(row)
        if res.error:
            status, text = "FAIL", res.error
        elif res.report.total:
            status, text = ("FOUND" if self._dry else "FIXED"), res.report.summary()
        else:
            status, text = "CLEAN", "nothing found"
        it.setText(2, status)
        it.setForeground(2, QColor(STATUS_COLORS[status]))
        it.setText(3, text)
        it.setToolTip(3, text)
        self.progress.setValue(self.progress.value() + 1)
        if self.tree.currentItem() is it:
            self._show_details()

    def _on_done(self):
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        self._set_busy(False)
        vals = list(self.results.values())
        dirty = sum(1 for r in vals if r.ok and r.report.total)
        failed = sum(1 for r in vals if not r.ok)
        verb = "contain" if self._dry else "were cleaned of"
        self.statusBar().showMessage(f"Done: {len(vals)} file(s), {dirty} {verb} AI traces, {failed} failed")

    def _show_details(self):
        it = self.tree.currentItem()
        if not it:
            return
        res = self.results.get(self.tree.indexOfTopLevelItem(it))
        if not res:
            self.details.setPlainText(it.text(0))
            return
        lines = [f"File:   {res.src}", f"Type:   {res.kind}"]
        if res.dst:
            lines.append(f"Output: {res.dst}")
        if res.error:
            lines.append(f"Error:  {res.error}")
        for k, v in res.report.changes.most_common():
            lines.append(f"  • {k}: {v}")
        for n in res.report.notes:
            lines.append(f"  note: {n}")
        self.details.setPlainText("\n".join(lines))

    def _open_item(self, it, _col):
        res = self.results.get(self.tree.indexOfTopLevelItem(it))
        target = res.dst if res and res.dst else Path(it.data(0, Qt.UserRole))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_output(self):
        if self.rb_dir.isChecked():
            folder = self._out_dir()
        else:
            it = self.tree.currentItem() or self.tree.topLevelItem(0)
            folder = Path(it.data(0, Qt.UserRole)).parent if it else None
        if folder and folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, e):
        if self.worker:
            self.worker.stop()
        if self.thread:
            self.thread.quit()
            self.thread.wait(3000)
        super().closeEvent(e)


STYLE = """
QWidget { font-size: 10pt; }
#drop { border: 2px dashed palette(mid); border-radius: 12px; background: palette(base); }
#drop[hover="true"] { border-color: #3b82f6; background: rgba(59,130,246,0.08); }
#muted { color: palette(placeholder-text); }
QPushButton { padding: 6px 14px; }
QPushButton#primary { background: #2563eb; color: white; border: none; border-radius: 6px;
                      padding: 7px 18px; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #93a4c3; }
QGroupBox { font-weight: 600; }
"""


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AI Cleanup")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    paths = [a for a in sys.argv[1:] if not a.startswith("-") and Path(a).exists()]
    if paths:
        win.add_paths(paths)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
