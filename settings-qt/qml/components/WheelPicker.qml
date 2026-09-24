import QtQuick
import QtQuick.Layouts
import QtQuick.Effects

// Horizontal gallery of radial-wheel skins (independent of the colour theme).
// Reads Theme.wheelList(); current = config radial.wheel. selected(key) fires.
Flickable {
    id: wp
    property string current: "azure"
    signal selected(string key)
    implicitHeight: 124
    contentWidth: row.width
    flickableDirection: Flickable.HorizontalFlick
    boundsBehavior: Flickable.StopAtBounds
    clip: true

    // edge fades: the strip scrolls horizontally
    Rectangle {
        parent: wp; z: 2
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        width: 40
        visible: wp.contentWidth > wp.width && wp.contentX < wp.contentWidth - wp.width - 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#00000000" }
            GradientStop { position: 1.0; color: "#8C000000" }
        }
    }
    Rectangle {
        parent: wp; z: 2
        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        width: 40
        visible: wp.contentX > 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#8C000000" }
            GradientStop { position: 1.0; color: "#00000000" }
        }
    }

    Row {
        id: row
        spacing: 14
        Repeater {
            model: Theme.wheelList()
            Item {
                id: cell
                required property var modelData
                width: 100; height: 116
                readonly property bool sel: wp.current === modelData.key
                Rectangle {
                    anchors.fill: parent; radius: 14
                    color: cell.sel ? Theme.accentSubtle : "#10FFFFFF"
                    border.width: cell.sel ? 2 : 1
                    border.color: cell.sel ? Theme.accent : (hov.hovered ? Theme.borderStrong : Theme.border)
                    Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                    RectangularShadow {
                        anchors.fill: parent; radius: 14; blur: 14
                        color: Theme.accentGlow; z: -1
                        opacity: cell.sel ? 0.55 : 0
                        Behavior on opacity { NumberAnimation { duration: Theme.dMed } }
                    }
                }
                Column {
                    anchors.centerIn: parent; spacing: 6
                    Item {
                        width: 72; height: 72
                        anchors.horizontalCenter: parent.horizontalCenter
                        ClassicWheel {
                            anchors.fill: parent; size: 72
                            material: modelData.image
                            fill: modelData.light ? "#FFFFFF" : "#1B1F28"
                            hi: modelData.light ? "#EEF1F4" : "#2A303C"
                            stroke: modelData.light ? "#D8DEE4" : "#38FFFFFF"
                        }
                    }
                    Text {
                        text: modelData.name
                        color: cell.sel ? Theme.textPrimary : Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        font.weight: cell.sel ? Font.DemiBold : Font.Normal
                        anchors.horizontalCenter: parent.horizontalCenter
                    }
                }
                HoverHandler { id: hov }
                TapHandler { onTapped: { wp.current = modelData.key; wp.selected(modelData.key) } }
            }
        }
    }
}
