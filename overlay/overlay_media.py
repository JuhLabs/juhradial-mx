"""Asynchronous media playback-state queries for the overlay."""

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal


def actions_use_media_state(actions):
    """Return whether an action tree renders the dynamic play/pause icon."""
    for action in actions:
        if len(action) > 4 and action[4] == "play_pause":
            return True
        submenu = action[5] if len(action) > 5 else None
        if submenu and actions_use_media_state(submenu):
            return True
    return False


class MediaStateQuery(QObject):
    """Run at most one non-blocking ``playerctl status`` query at a time."""

    state_changed = pyqtSignal(bool)

    def __init__(self, parent=None, *, program="playerctl", timeout_ms=200):
        super().__init__(parent)
        self.program = program
        self.timeout_ms = timeout_ms
        self._process = None
        self._retiring = False
        self._pending_start = False

    def start(self):
        """Start or coalesce a query without overlapping child processes."""
        if self._process is not None:
            # A healthy in-flight status query is fresh enough for every caller.
            # If it is already being retired, remember one replacement request.
            if self._retiring:
                self._pending_start = True
            return
        self._start_process()

    def _start_process(self):
        process = QProcess(self)
        self._process = process
        self._retiring = False
        process.setProgram(self.program)
        process.setArguments(["status"])
        process.finished.connect(
            lambda _exit_code, _exit_status, active=process: self._on_finished(active)
        )
        process.errorOccurred.connect(
            lambda error, active=process: self._on_error(active, error)
        )
        QTimer.singleShot(
            self.timeout_ms,
            lambda active=process: self._on_timeout(active),
        )
        process.start()

    def _on_finished(self, process):
        if process is not self._process:
            return
        if self._retiring:
            self._release(process)
            return
        output = bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self.state_changed.emit(output.strip() == "Playing")
        self._release(process)

    def _on_error(self, process, error):
        if process is not self._process:
            return
        if not self._retiring:
            self._retiring = True
            self.state_changed.emit(False)

        if error == QProcess.ProcessError.FailedToStart:
            # Qt does not emit finished() when the executable cannot be started.
            self._release(process)
            return

        # Crashed is followed by finished(); keep the QProcess alive until that
        # required terminal signal. Other live error paths are explicitly killed
        # and likewise released only by finished().
        if (
            error != QProcess.ProcessError.Crashed
            and process.state() != QProcess.ProcessState.NotRunning
        ):
            process.kill()

    def _on_timeout(self, process):
        if process is not self._process or self._retiring:
            return
        self._retiring = True
        self.state_changed.emit(False)
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()

    def _release(self, process):
        """Release a terminal process, then service one deferred request."""
        if process is not self._process:
            return
        self._process = None
        self._retiring = False
        process.deleteLater()
        if self._pending_start:
            self._pending_start = False
            self._start_process()
