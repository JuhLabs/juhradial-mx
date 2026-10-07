import QtQuick

// GlowEffect.qml without QtQuick.Effects (Qt 6.4, or the module is not
// installed). Never shown: callers switch their layer on Theme.effects.
Item {
    property Item source
    property color shadowColor
}
