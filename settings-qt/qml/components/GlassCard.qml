import QtQuick

// Elevated dark-glass surface: all controls live on these, never on raw wallpaper.
Item {
    id: root
    default property alias content: holder.data
    property real radius: Theme.radiusCard

    // Pre-baked 9-patch drop shadow (tools/gen_card_shadow.py): no per-card
    // offscreen layer, so animated children never re-blur the whole card.
    BorderImage {
        anchors.fill: parent
        anchors.margins: -32
        source: assetsDir + "/fx/card_shadow.png"
        border { left: 32; top: 32; right: 32; bottom: 32 }
        smooth: true
    }

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: root.radius
        color: Theme.surfaceGlass
        border.width: 1
        border.color: Theme.border
        antialiasing: true
    }
    // 6px inner top highlight ("light catches glass")
    Rectangle {
        anchors { left: bg.left; right: bg.right; top: bg.top }
        anchors.margins: 1
        height: 8
        radius: root.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#1AFFFFFF" }
            GradientStop { position: 1.0; color: "#00FFFFFF" }
        }
    }
    Item { id: holder; anchors.fill: parent; anchors.margins: 1 }
}
