"""Tray icon and menu: Pause, Resume, Stop, Push now, Settings, Exit."""
import signal
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..config import Settings
from ..uplink import Engine
from . import style
from .settings import SettingsWindow


class Bridge(QObject):
    changed = Signal()


class Tray:
    def __init__(self, app: QApplication, engine: Engine):
        self.app = app
        self.engine = engine
        self.window: SettingsWindow | None = None
        self.bridge = Bridge()
        self.bridge.changed.connect(self.refresh)
        engine.on_change(self.bridge.changed.emit)

        self.menu = QMenu()
        self.head = QAction('EDCMDR')
        self.head.setEnabled(False)
        self.a_pause = QAction('Pause', triggered=engine.pause)
        self.a_resume = QAction('Resume', triggered=engine.resume)
        self.a_stop = QAction('Stop', triggered=engine.halt)
        self.a_push = QAction('Push now', triggered=engine.push_now)
        self.a_settings = QAction('Settings…', triggered=self.show_settings)
        self.a_exit = QAction('Exit', triggered=self.exit)
        self.menu.addAction(self.head)
        self.menu.addSeparator()
        for a in (self.a_pause, self.a_resume, self.a_stop, self.a_push):
            self.menu.addAction(a)
        self.menu.addSeparator()
        self.menu.addAction(self.a_settings)
        self.menu.addAction(self.a_exit)

        self.tray = QSystemTrayIcon(style.icon('running'))
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.has_tray = QSystemTrayIcon.isSystemTrayAvailable()
        if self.has_tray:
            self.tray.show()
        else:
            self.show_settings()
        self.timer = QTimer(interval=30_000, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_settings()

    def show_settings(self):
        if self.window is None:
            self.window = SettingsWindow(self.engine)
            if not self.has_tray:
                self.window.setWindowTitle('EDCMDR — no system tray found; closing this window exits')
                self.window.destroyed.connect(self.exit)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def refresh(self):
        s = self.engine.snapshot()
        state = s['state']
        err = state == 'running' and s['status'] not in ('Connected', 'Starting')
        self.tray.setIcon(style.icon('error' if err else state))
        last = max([c['last_push'] for c in s['commanders']] or [0])
        when = f" · last push {int((time.time() - last) // 60)} min ago" if last else ''
        upd = f" · update {s['update']} available" if s['update'] else ''
        text = f"EDCMDR — {s['status']}{when}{upd}"
        self.tray.setToolTip(text)
        self.head.setText(text if len(text) < 60 else text[:57] + '…')
        self.a_pause.setEnabled(state == 'running')
        self.a_resume.setEnabled(state != 'running')
        self.a_stop.setEnabled(state != 'stopped')
        self.a_push.setEnabled(state == 'running')
        if self.window and self.window.isVisible():
            self.window.refresh()

    def exit(self):
        self.engine.shutdown()
        self.tray.hide()
        self.app.quit()


def run(settings: Settings, show_settings: bool = False) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName('EDCMDR')
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(style.QSS)
    engine = Engine(settings)
    tray = Tray(app, engine)
    if not tray.has_tray:
        app.setQuitOnLastWindowClosed(True)
    engine.start()
    # Ctrl-C and SIGTERM exit cleanly: the timer lets Python run its signal handlers inside Qt's loop.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: tray.exit())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(250)
    if show_settings or not tray.has_tray:
        tray.show_settings()
    code = app.exec()
    tick.stop()
    return code
