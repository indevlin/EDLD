"""Settings window: Commanders, Sharing, Integrations, About. Changes save at once."""
import time
import webbrowser

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import NAME, VERSION
from ..config import DELAY_LABELS, DELAYS, SHAREABLE, SPEC
from ..proto import ProtoError
from ..uplink import Engine

LABELS = {
    'location': 'Location and where ships are kept', 'ranks': 'Ranks and reputation',
    'statistics': 'Lifetime statistics (leaderboards)', 'fleet': 'Fleet and fittings',
    'engineering': 'Engineers', 'powerplay': 'Powerplay', 'squadron': 'Squadron and rank',
    'portrait': 'Codex portrait', 'presence': 'Show when I am in game',
}
LATER: dict[str, str] = {}
UNDELAYED = set(SPEC['undelayed'])
POWERS = SPEC['powers']
RECRUITING = {'': '—', 'open': 'Open', 'invite': 'By invitation', 'closed': 'Closed'}


def note(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName('note')
    lb.setWordWrap(True)
    return lb


class SettingsWindow(QWidget):
    def __init__(self, engine: Engine, host: str | None = None):
        super().__init__()
        self.engine = engine
        self.host = host
        self._loading = True
        self.setWindowTitle(f'ED Commanders · {host}' if host else 'EDCMDR')
        self.resize(760, 560)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._commanders_tab(), 'Commanders')
        self.tabs.addTab(self._sharing_tab(), 'Sharing')
        self.sq_widget = None
        self.sq_widget = self._squadron_tab()
        if host is None:
            self.tabs.addTab(self._integrations_tab(), 'Integrations')
            self.tabs.addTab(self._about_tab(), 'About')
        lay = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setObjectName('head')
        lay.addWidget(self.status)
        lay.addWidget(self.tabs)
        self.refresh()

    # ── Commanders ──────────────────────────────────────────────────────────
    def _commanders_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        g = QGroupBox('Journal folders')
        gl = QVBoxLayout(g)
        self.dirs = QListWidget()
        self.dirs.setMaximumHeight(110)
        row = QHBoxLayout()
        add, rem = QPushButton('Add folder…'), QPushButton('Remove')
        add.clicked.connect(self._add_dir)
        rem.clicked.connect(self._remove_dir)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        gl.addWidget(self.dirs)
        gl.addLayout(row)
        gl.addWidget(note('Every journal in these folders is read. Each file belongs to the commander named in its '
                          'first lines, so several commanders can share a folder.'))
        lay.addWidget(g)

        g2 = QGroupBox('Commanders found')
        g2l = QVBoxLayout(g2)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Commander', 'On EDCMDR', 'Last push'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        row2 = QHBoxLayout()
        self.open_btn, self.forget_btn = QPushButton('Open page'), QPushButton('Forget on EDCMDR…')
        self.verify_btn = QPushButton('Verify with Frontier…')
        self.portrait_btn = QPushButton('Portrait…')
        self.portrait_btn.setToolTip('Send a screenshot of the Codex hub with your commander tile highlighted.')
        self.portrait_btn.clicked.connect(self._portrait)
        self.open_btn.clicked.connect(self._open_page)
        self.forget_btn.clicked.connect(self._forget)
        self.verify_btn.clicked.connect(self._verify)
        row2.addWidget(self.open_btn)
        row2.addWidget(self.verify_btn)
        row2.addWidget(self.portrait_btn)
        row2.addStretch()
        row2.addWidget(self.forget_btn)
        g2l.addWidget(self.table)
        g2l.addLayout(row2)
        lay.addWidget(g2)
        return w

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, 'Journal folder')
        if d:
            self.engine.set_dirs([*map(str, self.engine.settings.journal_dirs), d])
            self.refresh()

    def _remove_dir(self):
        it = self.dirs.currentItem()
        if it:
            self.engine.set_dirs([p for p in map(str, self.engine.settings.journal_dirs) if p != it.text()])
            self.refresh()

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        cm = self.engine.snapshot()['commanders']
        return cm[r] if 0 <= r < len(cm) else None

    def _open_page(self):
        c = self._selected()
        if c and c['pub_id']:
            webbrowser.open(f"{self.engine.client.base}/cmdr/{c['pub_id']}")

    def _verify(self):
        c = self._selected()
        if not c:
            return
        try:
            v = self.engine.verify_start(c['fid'])
        except ProtoError as e:
            QMessageBox.warning(self, 'Verify with Frontier', str(e))
            return
        QMessageBox.information(self, 'Verify with Frontier',
                                f"Your browser will open EDCMDR's verification page.\n\n"
                                f"Code: {v['code']}\n\n"
                                'Continue only if the page shows this same code. You sign in on Frontier\'s own site, '
                                'then this app finishes the verification; EDCMDR keeps no password or token. This '
                                f"installation then becomes the only one that can publish as CMDR {c['name']}.")
        webbrowser.open(v['url'])

    @staticmethod
    def jpeg(path: str, max_w: int = 1920) -> bytes:
        """Load a screenshot and re-encode it as JPEG (quality 85, at most max_w wide, no metadata)."""
        img = QImage(path)
        if img.isNull():
            raise ValueError('That file is not a picture.')
        if img.width() > max_w:
            img = img.scaledToWidth(max_w, Qt.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.convertToFormat(QImage.Format_RGB888).save(buf, 'JPEG', 85)
        return bytes(ba)

    def _portrait(self):
        c = self._selected()
        if not c:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Codex screenshot', '', 'Screenshots (*.png *.jpg *.jpeg *.bmp)')
        if not path:
            return
        p = self.engine.settings.prefs(c['fid'])
        if not p['share'].get('portrait'):
            if QMessageBox.question(self, 'Portrait', f"Share a portrait for CMDR {c['name']}?\n\n"
                                    'It is shown on your EDCMDR page and squadron roster, and deleted if you '
                                    'switch portrait sharing off.') != QMessageBox.Yes:
                return
            p['share']['portrait'] = True
            self.engine.set_prefs(c['fid'], p)
        try:
            url = self.engine.push_portrait(c['fid'], self.jpeg(path))
        except (ProtoError, ValueError) as e:
            QMessageBox.warning(self, 'Portrait', str(e))
            return
        QMessageBox.information(self, 'Portrait', 'Portrait published.')
        self._load_prefs()

    # ── Squadron (leaders only) ─────────────────────────────────────────────
    def _squadron_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(note('Shown for commanders verified with Frontier as their squadron\'s leader. Each edits only '
                           'the squadron that commander leads; these details appear on its EDCMDR page.'))
        form = QFormLayout()
        self.sq_name = QLabel('')
        self.sq_leads: dict = {}
        self.sq_name.setObjectName('head')
        self.sq_who = QComboBox()
        self.sq_who.currentIndexChanged.connect(self._load_squadron)
        self.sq_home = QLineEdit()
        self.sq_home.setMaxLength(64)
        self.sq_power = QComboBox()
        self.sq_power.addItem('—', None)
        for pw in POWERS:
            self.sq_power.addItem(pw, pw)
        self.sq_factions = QLineEdit()
        self.sq_factions.setPlaceholderText('Up to five, separated by commas')
        self.sq_recruit = QComboBox()
        for k, v in RECRUITING.items():
            self.sq_recruit.addItem(v, k or None)
        self.sq_tagline = QLineEdit()
        self.sq_tagline.setMaxLength(SPEC['limits']['tagline_len'])
        for label, field in (('Commander', self.sq_who), ('Squadron', self.sq_name), ('Home system', self.sq_home), ('Power', self.sq_power),
                             ('Supported factions', self.sq_factions), ('Recruiting', self.sq_recruit),
                             ('Tagline', self.sq_tagline)):
            form.addRow(label, field)
        lay.addLayout(form)
        save = QPushButton('Save to EDCMDR')
        save.clicked.connect(self._save_squadron)
        lay.addWidget(save, alignment=Qt.AlignLeft)
        lay.addStretch()
        return w

    def _sync_squadron_tab(self, cm: list[dict]):
        leaders = [c for c in cm if c.get('leader_of')]
        idx = self.tabs.indexOf(self.sq_widget) if self.sq_widget else -1
        if leaders and idx < 0:
            self.tabs.insertTab(2, self.sq_widget, 'Squadron')
        elif not leaders and idx >= 0:
            self.tabs.removeTab(idx)
        self.sq_leads = {c['fid']: (c['leader_of'], c.get('leader_squadron') or {}) for c in leaders}
        items = [(c['fid'], f"CMDR {c['name']} · {self._sq_label(c['leader_of'], c.get('leader_squadron'))}") for c in leaders]
        if [(self.sq_who.itemData(i), self.sq_who.itemText(i)) for i in range(self.sq_who.count())] != items:
            cur = self.sq_who.currentData()
            self.sq_who.blockSignals(True)
            self.sq_who.clear()
            for fid, text in items:
                self.sq_who.addItem(text, fid)
            if cur in self.sq_leads:
                self.sq_who.setCurrentIndex([f for f, _ in items].index(cur))
            self.sq_who.blockSignals(False)
            self._load_squadron()

    @staticmethod
    def _sq_label(sid, sq) -> str:
        sq = sq or {}
        name = sq.get('name') or f'squadron {sid}'
        return f"{name} [{sq['tag']}]" if sq.get('tag') else name

    def _load_squadron(self):
        fid = self.sq_who.currentData()
        sid, sq = getattr(self, 'sq_leads', {}).get(fid, (None, {}))
        self.sq_name.setText(self._sq_label(sid, sq) if fid else '')
        d = self.engine.settings.commander(fid).get('squadron_details') or {} if fid else {}
        if d.get('squadron_id') != sid:
            d = {}  # details saved for another squadron are not this one's
        self.sq_home.setText(d.get('home_system') or '')
        self.sq_power.setCurrentIndex(max(0, self.sq_power.findData(d.get('power'))))
        self.sq_factions.setText(', '.join(d.get('factions') or []))
        self.sq_recruit.setCurrentIndex(max(0, self.sq_recruit.findData(d.get('recruiting'))))
        self.sq_tagline.setText(d.get('tagline') or '')

    def _save_squadron(self):
        fid = self.sq_who.currentData()
        if not fid:
            return
        factions = [f.strip() for f in self.sq_factions.text().split(',') if f.strip()][:SPEC['limits']['factions']]
        details = {'home_system': self.sq_home.text().strip() or None, 'power': self.sq_power.currentData(),
                   'factions': factions, 'recruiting': self.sq_recruit.currentData(),
                   'tagline': self.sq_tagline.text().strip() or None}
        sid, sq = self.sq_leads.get(fid, (None, {}))
        if sid is None:
            return
        try:
            self.engine.save_squadron(fid, details, sid)
        except ProtoError as e:
            QMessageBox.warning(self, 'Squadron', str(e))
            self.refresh()
            return
        QMessageBox.information(self, 'Squadron', f'Saved for {self._sq_label(sid, sq)}. Its page shows it now.')

    def _forget(self):
        c = self._selected()
        if not c:
            return
        if QMessageBox.question(self, 'Forget on EDCMDR',
                                f"Delete everything EDCMDR holds for CMDR {c['name']}?\n\n"
                                'This cannot be undone. Sharing is switched off on this computer too.') != QMessageBox.Yes:
            return
        p = self.engine.settings.prefs(c['fid'])
        for k in p['share']:
            p['share'][k] = False
        p['presence'] = False
        err = self.engine.forget(c['fid'])
        self.engine.settings.set_prefs(c['fid'], p)
        if err:
            QMessageBox.warning(self, 'Forget on EDCMDR', f'The server could not be reached: {err}')
        self.refresh()

    # ── Sharing ─────────────────────────────────────────────────────────────
    def _sharing_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        top.addWidget(QLabel('Commander'))
        self.who = QComboBox()
        self.who.currentIndexChanged.connect(self._load_prefs)
        top.addWidget(self.who, 1)
        lay.addLayout(top)
        lay.addWidget(note('Nothing is published until you switch it on. Switching a section off deletes it from '
                           'EDCMDR. Delays are enforced by EDCMDR, not just this computer.'))
        grid = QGridLayout()
        for col, h in enumerate(['', 'EDCMDR', 'Delay']):
            lb = QLabel(h)
            lb.setObjectName('head')
            grid.addWidget(lb, 0, col, alignment=Qt.AlignCenter if col else Qt.AlignLeft)
        self.share: dict[str, QCheckBox] = {}
        self.delay: dict[str, QComboBox] = {}
        rows = [c for c in SHAREABLE if c != 'presence'] + ['presence']
        for r, cat in enumerate(rows, 1):
            grid.addWidget(QLabel(LABELS.get(cat, cat)), r, 0)
            cb = QCheckBox()
            cb.toggled.connect(self._save_prefs)
            dl = QComboBox()
            for d in DELAYS:
                dl.addItem(DELAY_LABELS[d], d)
            dl.currentIndexChanged.connect(self._save_prefs)
            if cat in LATER:
                cb.setEnabled(False)
                dl.setEnabled(False)
                cb.setToolTip(LATER[cat])
            if cat in UNDELAYED:
                dl.setEnabled(False)
                dl.setToolTip('Portraits are published at once; switching sharing off deletes them.')
            self.share[cat], self.delay[cat] = cb, dl
            grid.addWidget(cb, r, 1, alignment=Qt.AlignCenter)
            grid.addWidget(dl, r, 2)
        lay.addLayout(grid)
        self.wealth = QCheckBox('Include net worth (credits plus ships, modules and carriers) with lifetime statistics')
        self.names = QCheckBox('Let my earlier commander names find this page')
        for x in (self.wealth, self.names):
            x.toggled.connect(self._save_prefs)
            lay.addWidget(x)
        lay.addStretch()
        self._loading = False
        return w

    def _load_prefs(self):
        fid = self.who.currentData()
        if not fid:
            return
        self._loading = True
        p = self.engine.settings.prefs(fid)
        for cat, cb in self.share.items():
            cb.setChecked(p['presence'] if cat == 'presence' else p['share'].get(cat, False))
            self.delay[cat].setCurrentIndex(DELAYS.index(p['delay'].get(cat, 0)))
        self.wealth.setChecked(p['wealth'])
        self.names.setChecked(p['name_history'])
        self.wealth.setEnabled(self.share['statistics'].isChecked())
        self._loading = False

    def _save_prefs(self):
        fid = self.who.currentData()
        if self._loading or not fid:
            return
        p = self.engine.settings.prefs(fid)
        for cat, cb in self.share.items():
            if cat == 'presence':
                p['presence'] = cb.isChecked()
                p['share']['presence'] = cb.isChecked()
            else:
                p['share'][cat] = cb.isChecked()
            p['delay'][cat] = self.delay[cat].currentData()
        p['wealth'] = self.wealth.isChecked() and p['share'].get('statistics', False)
        p['name_history'] = self.names.isChecked()
        self.wealth.setEnabled(self.share['statistics'].isChecked())
        self.engine.set_prefs(fid, p)

    # ── Integrations, About ─────────────────────────────────────────────────
    def _integrations_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(note('Optional uploads to community services, sent from this computer straight to each '
                           'service. Each is off until you switch it on for a commander. Only what you play while '
                           'the client runs is sent, never your history; Pause stops these uploads too.'))
        top = QHBoxLayout()
        top.addWidget(QLabel('Commander'))
        self.iwho = QComboBox()
        self.iwho.currentIndexChanged.connect(self._load_integrations)
        top.addWidget(self.iwho, 1)
        lay.addLayout(top)
        net = QGroupBox('EDDN, Elite Dangerous Data Network')
        n = QFormLayout(net)
        self.eddn_on = QCheckBox('Share markets, outfitting, shipyards and exploration with EDDN')
        n.addRow(self.eddn_on)
        n.addRow(note('EDDN passes these on to the community tools (Inara, Spansh, EDSM and others). '
                      'Messages carry your commander name, as EDDN requires.'))
        lay.addWidget(net)
        edsm = QGroupBox('EDSM, Elite Dangerous Star Map')
        f = QFormLayout(edsm)
        self.edsm_on = QCheckBox('Send my journal to EDSM, under my EDSM account')
        self.edsm_key = QLineEdit()
        self.edsm_key.setEchoMode(QLineEdit.Password)
        self.edsm_key.setPlaceholderText('From www.edsm.net → Settings → API key')
        f.addRow(self.edsm_on)
        f.addRow('API key', self.edsm_key)
        f.addRow(note('EDSM receives the events it accepts, with your commander name from the journal.'))
        lay.addWidget(edsm)
        ina = QGroupBox('Inara')
        i = QFormLayout(ina)
        self.inara_on = QCheckBox('Send my commander to Inara, under my Inara account')
        self.inara_key = QLineEdit()
        self.inara_key.setEchoMode(QLineEdit.Password)
        self.inara_key.setPlaceholderText('From inara.cz → Settings → Inara API key')
        i.addRow(self.inara_on)
        i.addRow('API key', self.inara_key)
        i.addRow(note('Ranks, credits, ships and their fittings, travel, missions, engineers and materials.'))
        lay.addWidget(ina)
        cap = QGroupBox('Frontier CAPI')
        k = QFormLayout(cap)
        self.capi_on = QCheckBox('Keep my Frontier sign-in on this computer for CAPI')
        self.capi_state = QLabel('')
        self.capi_state.setWordWrap(True)
        k.addRow(self.capi_on)
        k.addRow(self.capi_state)
        k.addRow(note('With EDDN on, your fleet carrier bartender orders are shared from CAPI when you dock there. '
                      'The sign-in is kept only here, never on edcmdr.com. After switching this on, press Verify '
                      'with Frontier once to sign in.'))
        lay.addWidget(cap)
        astro = QGroupBox('EDAstro')
        g = QFormLayout(astro)
        self.astro_on = QCheckBox('Send exploration and travel events to EDAstro (no account)')
        self.astro_carrier = QCheckBox("Include my fleet carrier's jumps and status")
        g.addRow(self.astro_on)
        g.addRow(self.astro_carrier)
        lay.addWidget(astro)
        for x in (self.eddn_on, self.edsm_on, self.inara_on, self.capi_on, self.astro_on, self.astro_carrier):
            x.toggled.connect(self._save_integrations)
        self.edsm_key.editingFinished.connect(self._save_integrations)
        self.inara_key.editingFinished.connect(self._save_integrations)
        self.int_status = QLabel('')
        self.int_status.setWordWrap(True)
        lay.addWidget(self.int_status)
        lay.addStretch()
        return w

    def _load_integrations(self):
        fid = self.iwho.currentData() if hasattr(self, 'iwho') else None
        if not fid:
            return
        from ..integrations import Hub
        self._int_loading = True
        self.eddn_on.setChecked(Hub.config(self.engine.settings, fid, 'eddn')['enabled'])
        e = Hub.config(self.engine.settings, fid, 'edsm')
        self.capi_on.setChecked(Hub.config(self.engine.settings, fid, 'capi')['enabled'])
        self._capi_state(fid)
        n = Hub.config(self.engine.settings, fid, 'inara')
        self.inara_on.setChecked(n['enabled'])
        self.inara_key.setText(n['api_key'])
        a = Hub.config(self.engine.settings, fid, 'edastro')
        self.edsm_on.setChecked(e['enabled'])
        self.edsm_key.setText(e['api_key'])
        self.astro_on.setChecked(a['enabled'])
        self.astro_carrier.setChecked(a['carrier'])
        self._int_loading = False

    def _capi_state(self, fid):
        from ..capi import Store
        if not self.capi_on.isChecked():
            self.capi_state.setText('')
        elif Store(fid).signed_in():
            self.capi_state.setText('Signed in with Frontier on this computer.')
        else:
            self.capi_state.setText('Not signed in yet: press Verify with Frontier on the Commanders tab.')

    def _save_integrations(self):
        fid = self.iwho.currentData()
        if not fid or getattr(self, '_int_loading', False):
            return
        self.engine.settings.set_integration(fid, 'eddn', {'enabled': self.eddn_on.isChecked()})
        self.engine.settings.set_integration(fid, 'edsm', {'enabled': self.edsm_on.isChecked(),
                                                           'api_key': self.edsm_key.text().strip()})
        self.engine.settings.set_integration(fid, 'capi', {'enabled': self.capi_on.isChecked()})
        if not self.capi_on.isChecked():
            from ..capi import Store
            Store(fid).forget()
        self._capi_state(fid)
        self.engine.settings.set_integration(fid, 'inara', {'enabled': self.inara_on.isChecked(),
                                                            'api_key': self.inara_key.text().strip()})
        self.engine.settings.set_integration(fid, 'edastro', {'enabled': self.astro_on.isChecked(),
                                                              'carrier': self.astro_carrier.isChecked()})

    def _about_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        snap = self.engine.snapshot()
        lay.addWidget(QLabel(f'{NAME} {VERSION}'))
        lay.addWidget(note('Official build.' if snap['official'] else
                           'Unofficial build: it reads journals but EDCMDR will not accept its pushes.'))
        lay.addWidget(note(f"Server: {snap['server']}"))
        b = QPushButton('Privacy policy')
        b.clicked.connect(lambda: webbrowser.open(f'{self.engine.client.base}/privacy'))
        lay.addWidget(b, alignment=Qt.AlignLeft)
        lay.addWidget(note('Published by Indevlin, LLC. MIT licence. Elite Dangerous is a trademark of Frontier '
                           'Developments plc; this client is not affiliated with Frontier.'))
        lay.addStretch()
        return w

    # ── refresh ─────────────────────────────────────────────────────────────
    def refresh(self):
        snap = self.engine.snapshot()
        upd = f" · Update {snap['update']} available at edcmdr.com/client" if snap['update'] else ''
        self.status.setText(f"{snap['status']}{upd}")
        dirs = [str(p) for p in self.engine.settings.journal_dirs]
        if [self.dirs.item(i).text() for i in range(self.dirs.count())] != dirs:
            self.dirs.clear()
            self.dirs.addItems(dirs)
        cm = snap['commanders']
        sel = self.table.currentRow()
        self.table.setRowCount(len(cm))
        for i, c in enumerate(cm):
            if c['verify']:
                st = c['verify']
            elif c['blocked']:
                st = c['blocked']
            elif c['error']:
                st = 'Problem: ' + c['error']
            elif c['enrolled']:
                st = 'Verified' if c['verified'] else 'Publishing (unverified)'
            else:
                st = 'Not shared'
            ago = '—' if not c['last_push'] else f"{int((time.time() - c['last_push']) // 60)} min ago"
            for col, v in enumerate([f"CMDR {c['name']}", st, ago]):
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                self.table.setItem(i, col, item)
        if 0 <= sel < len(cm):
            self.table.selectRow(sel)
        fids = [c['fid'] for c in cm]
        if [self.who.itemData(i) for i in range(self.who.count())] != fids:
            cur = self.who.currentData()
            self.who.blockSignals(True)
            self.who.clear()
            for c in cm:
                self.who.addItem(f"CMDR {c['name']}", c['fid'])
            if cur in fids:
                self.who.setCurrentIndex(fids.index(cur))
            self.who.blockSignals(False)
            self._load_prefs()
        if hasattr(self, 'iwho') and [self.iwho.itemData(i) for i in range(self.iwho.count())] != fids:
            cur = self.iwho.currentData()
            self.iwho.blockSignals(True)
            self.iwho.clear()
            for c in cm:
                self.iwho.addItem(f"CMDR {c['name']}", c['fid'])
            if cur in fids:
                self.iwho.setCurrentIndex(fids.index(cur))
            self.iwho.blockSignals(False)
            self._load_integrations()
        if hasattr(self, 'int_status') and self.engine.hub is not None:
            st = self.engine.hub.status()
            label = {'eddn': 'EDDN', 'edsm': 'EDSM', 'edastro': 'EDAstro', 'inara': 'Inara'}
            self.int_status.setText('  ·  '.join(f'{label[k]}: {v}' for k, v in sorted(st.items())))
        has = bool(cm)
        for x in (self.open_btn, self.forget_btn, self.verify_btn, self.portrait_btn):
            x.setEnabled(has)
        self._sync_squadron_tab(cm)
