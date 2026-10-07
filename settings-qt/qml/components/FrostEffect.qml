import QtQuick.Effects

// GlassCard's frost layer: clipped to the card's rounded mask and darkened a
// touch (the contrast floor over bright wallpapers). MultiEffect needs
// Qt 6.5; +noeffects/FrostEffect.qml stands in below that.
MultiEffect { maskEnabled: true; brightness: -0.12 }
