import QtQuick

// FrostEffect.qml without QtQuick.Effects (Qt 6.4, or the module is not
// installed). Never shown: Theme.reduceTransparency is on then, so GlassCard
// keeps its frost layer off and draws the solid surface.
Item {
    property Item source
    property Item maskSource
}
