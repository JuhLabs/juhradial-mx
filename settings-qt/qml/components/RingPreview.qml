import QtQuick

// Live miniature of the user's own radial menu: their skin (or the classic
// ring), their eight slices in the current icon style, the centre zone, and
// the size settings. Sizes are drawn relative to the largest ring Settings
// allows, so growing or shrinking the ring is visible here.
//   outer, inner   ring and centre radii in reference px (radial.outer_radius / inner_radius)
//   iconScale      Settings > Icon size multiplier
//   outerMax       the slider maximum (the box edge)
Item {
    id: rp
    property real outer: 150
    property real inner: 45
    property real iconScale: 1.0
    property real outerMax: 250
    implicitWidth: 220; implicitHeight: 220

    // "" and "none" both mean the built-in classic ring (overlay fallback).
    readonly property string wheelKey: {
        Backend.configChanged   // re-read after a skin change elsewhere
        const k = Backend.get("radial.wheel", "")
        return (k === "" || k === "none") ? "none" : k
    }
    readonly property bool mono: Theme.iconStyle === "mono"
    readonly property real boxR: Math.min(width, height) / 2 - 4
    readonly property real ringR: boxR * Math.min(1, outer / outerMax)
    readonly property real iconR: ringR * 100 / 150
    readonly property real iconPx: Math.max(10, ringR * 32 / 150 * iconScale)

    Accessible.role: Accessible.Graphic
    Accessible.name: qsTr("Preview of the radial menu")

    Image {
        anchors.centerIn: parent
        width: rp.ringR * 2 * 310 / 300; height: width
        visible: rp.wheelKey !== "none"
        source: rp.wheelKey !== "none" ? Theme.wheelImage(rp.wheelKey) : ""
        sourceSize.width: 512; sourceSize.height: 512
        fillMode: Image.PreserveAspectFit; smooth: true
    }
    ClassicWheel {
        anchors.centerIn: parent
        visible: rp.wheelKey === "none"
        size: rp.ringR * 2
        onSizeChanged: requestPaint()
    }
    // Centre zone: where nothing is selected.
    Rectangle {
        anchors.centerIn: parent
        width: rp.ringR * 2 * Math.min(1, rp.inner / Math.max(1, rp.outer)); height: width
        radius: width / 2
        color: "transparent"
        border.width: 1; border.color: Theme.accentFaint
        Behavior on width { NumberAnimation { duration: Theme.dShort } }
    }
    Repeater {
        model: Slices
        Item {
            required property int index
            required property string icon
            required property string hex
            required property string actionId
            readonly property string btnImg: (rp.mono || icon.startsWith("/")) ? "" : (Theme.iconStyle, Theme.sliceButton(actionId))
            width: rp.iconPx * 1.12; height: width
            x: rp.width / 2 + rp.iconR * Math.cos((index * 45 - 90) * Math.PI / 180) - width / 2
            y: rp.height / 2 + rp.iconR * Math.sin((index * 45 - 90) * Math.PI / 180) - height / 2
            Image {
                anchors.fill: parent; visible: btnImg !== ""
                source: btnImg; sourceSize.width: 128; sourceSize.height: 128
                smooth: true; fillMode: Image.PreserveAspectFit
            }
            Rectangle {
                anchors.fill: parent; radius: width / 2
                visible: btnImg === ""
                color: "#1B1F28"; border.width: 1.5
                border.color: rp.mono ? Theme.borderStrong : hex
            }
            ActionIcon {
                anchors.centerIn: parent; visible: btnImg === ""
                iconName: icon; tint: rp.mono ? Theme.textBody : hex
                px: Math.max(8, Math.round(parent.width * 0.5))
            }
        }
    }
}
