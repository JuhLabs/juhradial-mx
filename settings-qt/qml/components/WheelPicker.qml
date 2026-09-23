import QtQuick
import QtQuick.Layouts

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
                    border.color: cell.sel ? Theme.accent : Theme.border
                    Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                    scale: hov.hovered ? 1.04 : 1.0
                    Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }
                }
                Column {
                    anchors.centerIn: parent; spacing: 6
                    Image {
                        source: modelData.image
                        sourceSize.width: 144; sourceSize.height: 144
                        width: 72; height: 72; smooth: true
                        anchors.horizontalCenter: parent.horizontalCenter
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
