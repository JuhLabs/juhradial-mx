import QtQuick.Effects

// A glow in the item's own shape (BatteryRing's arc). MultiEffect needs
// Qt 6.5; +noeffects/GlowEffect.qml stands in below that.
MultiEffect {
    shadowEnabled: true
    shadowBlur: 1.0; shadowOpacity: 0.85
    shadowHorizontalOffset: 0; shadowVerticalOffset: 0
}
