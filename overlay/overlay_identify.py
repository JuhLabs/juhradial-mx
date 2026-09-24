"""Settings > Flow > Identify screens: a card on every monitor with its
number, connector name and size, and which one is the Flow screen. Shown by
the overlay because it runs on X11/XWayland, where a window can be placed on
any monitor on every desktop."""
from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PyQt6.QtWidgets import QWidget

SHOW_MS = 3500
_cards = []


class _Card(QWidget):
    def __init__(self, number, screen, flow_screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.number, self.flow = number, flow_screen
        g = screen.geometry()
        self.detail = f"{screen.name()}  {g.width()} x {g.height()}"
        self.resize(440, 250)
        self.move(g.x() + (g.width() - 440) // 2, g.y() + (g.height() - 250) // 2)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(255, 255, 255, 40))
        p.setBrush(QColor(10, 14, 22, 225))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 28, 28)
        p.setPen(QColor("#ffffff"))
        font = QFont()
        font.setPixelSize(110)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(QRectF(0, 12, self.width(), 140), Qt.AlignmentFlag.AlignCenter, str(self.number))
        font.setPixelSize(22)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor("#c9d4e5"))
        p.drawText(QRectF(0, 150, self.width(), 34), Qt.AlignmentFlag.AlignCenter, self.detail)
        if self.flow:
            p.setPen(QColor("#4c9aff"))
            p.drawText(QRectF(0, 188, self.width(), 34), Qt.AlignmentFlag.AlignCenter, self.flow)


def identify_screens(flow_monitor="", flow_label=""):
    """Show the cards for SHOW_MS. `flow_monitor` is the connector name Flow
    watches ("" = any); its card carries `flow_label`."""
    for card in _cards:
        card.close()
    _cards.clear()
    for number, screen in enumerate(QGuiApplication.screens(), 1):
        is_flow = bool(flow_label) and (not flow_monitor or screen.name() == flow_monitor)
        card = _Card(number, screen, flow_label if is_flow else "")
        card.show()
        _cards.append(card)
    QTimer.singleShot(SHOW_MS, lambda: [c.close() for c in _cards])
