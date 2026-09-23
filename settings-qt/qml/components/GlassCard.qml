import QtQuick
import QtQuick.Window
import QtQuick.Effects

// The one surface material: frosted wallpaper sample + graphite tint + hairline
// + lit top edge + ambient shadow. Every control lives on one of these, never
// on raw wallpaper. `solid` (or Theme.reduceTransparency) swaps the frost for
// the opaque fallback; `rail` is the denser sidebar variant.
Item {
    id: root
    default property alias content: holder.data
    property real radius: Theme.radiusCard
    property bool solid: false
    property bool rail: false
    property bool shadow: true
    readonly property bool frosted: !solid && !Theme.reduceTransparency && Theme.wallpaper !== ""

    // Window-space origin of the card so the frost sample lines up with the
    // wallpaper behind it. Re-synced on layout, scroll and window resize.
    property real _wx: 0
    property real _wy: 0
    property Item _flick: null
    function _sync() {
        if (!root.frosted) return
        var p = root.mapToItem(null, 0, 0)
        root._wx = p.x; root._wy = p.y
    }
    onXChanged: _sync()
    onYChanged: _sync()
    onWidthChanged: _sync()
    onHeightChanged: _sync()
    onFrostedChanged: _sync()
    Component.onCompleted: {
        var p = root.parent
        while (p) {
            if (p.contentY !== undefined && p.contentItem !== undefined) { root._flick = p; break }
            p = p.parent
        }
        Qt.callLater(root._sync)
    }
    Connections {
        target: root._flick
        function onContentYChanged() { root._sync() }
        function onContentXChanged() { root._sync() }
    }
    Connections {
        target: root.Window.window
        function onWidthChanged() { Qt.callLater(root._sync) }
        function onHeightChanged() { Qt.callLater(root._sync) }
    }

    RectangularShadow {
        visible: root.shadow
        anchors.fill: parent
        radius: root.radius
        blur: 28; spread: 0
        offset.y: 10
        color: "#70000000"
    }

    // Frost: the wallpaper decoded at 48 px wide and magnified by the GPU is a
    // wide, smooth blur for free (no Pillow, no cache, one shared texture).
    Item {
        id: frost
        anchors.fill: parent
        visible: root.frosted
        layer.enabled: root.frosted
        layer.effect: MultiEffect { maskEnabled: true; maskSource: frostMask; brightness: -0.12 }
        Image {
            x: -root._wx; y: -root._wy
            width: root.Window.width; height: root.Window.height
            source: Theme.wallpaper
            sourceSize.width: 48; sourceSize.height: 30
            fillMode: Image.PreserveAspectCrop
            smooth: true; cache: true
        }
        // the same dim scrim the window lays over the wallpaper, so the frost
        // never reads brighter than what surrounds the card (legibility floor:
        // muted text >= 4.5:1 on the brightest block of every wallpaper)
        Rectangle { anchors.fill: parent; color: "#000000"; opacity: 0.42 }
    }
    Rectangle {
        id: frostMask
        anchors.fill: parent; radius: root.radius
        visible: false; layer.enabled: root.frosted
    }

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        antialiasing: true
        color: root.frosted ? (root.rail ? Theme.glassTintRail : Theme.glassTint)
                            : (root.rail ? Theme.surfaceRail : Theme.surfaceGlass)
        border.width: 1
        border.color: Theme.border
    }
    Rectangle {   // lit top edge: the light source is above the glass
        anchors { left: parent.left; right: parent.right; top: parent.top }
        anchors.leftMargin: root.radius; anchors.rightMargin: root.radius; anchors.topMargin: 1
        height: 1; color: Theme.borderLit
    }
    Rectangle {   // top sheen
        anchors { left: parent.left; right: parent.right; top: parent.top }
        anchors.margins: 1
        height: 10; radius: root.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#12FFFFFF" }
            GradientStop { position: 1.0; color: "#00FFFFFF" }
        }
    }
    Item { id: holder; anchors.fill: parent; anchors.margins: 1 }
}
