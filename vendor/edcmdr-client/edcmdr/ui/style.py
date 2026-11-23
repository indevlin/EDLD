"""HUD palette, stylesheet and the tray icon, drawn at runtime."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF

ACCENT = '#ff7a1a'
STATE_COLOURS = {'running': ACCENT, 'paused': '#f8c45c', 'stopped': '#7a6a52', 'error': '#e05c5c'}

QSS = f"""
QWidget {{ background: #120e09; color: #e8ddd0; font-size: 13px; }}
QTabWidget::pane {{ border: 1px solid #3d2e18; top: -1px; }}
QTabBar::tab {{ background: #1c150d; color: #8a7a62; padding: 7px 16px; border: 1px solid #3d2e18; border-bottom: 0; }}
QTabBar::tab:selected {{ background: {ACCENT}; color: #140b02; }}
QGroupBox {{ border: 1px solid #3d2e18; margin-top: 14px; padding: 10px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {ACCENT}; text-transform: uppercase; }}
QPushButton {{ background: #221a10; border: 1px solid #3d2e18; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: #5a4d3a; }}
QListWidget, QTableWidget, QComboBox {{ background: #0b0906; border: 1px solid #3d2e18; selection-background-color: #3a2410; }}
QHeaderView::section {{ background: #221a10; color: {ACCENT}; border: 0; border-bottom: 1px solid #3d2e18; padding: 4px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid #8a7a62; background: #0b0906; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ border-color: #3d2e18; background: #17120b; }}
QLabel#note {{ color: #8a7a62; }}
QLabel#head {{ color: {ACCENT}; text-transform: uppercase; }}
"""


def icon(state: str) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(STATE_COLOURS.get(state, ACCENT)))
    p.drawPolygon(QPolygonF([QPointF(4, 8), QPointF(60, 8), QPointF(60, 42), QPointF(46, 56), QPointF(4, 56)]))
    p.setPen(QColor('#140b02'))
    f = p.font()
    f.setBold(True)
    f.setPixelSize(26)
    p.setFont(f)
    p.drawText(pm.rect().adjusted(0, -2, -4, 0), Qt.AlignCenter, 'ED')
    p.end()
    return QIcon(pm)
