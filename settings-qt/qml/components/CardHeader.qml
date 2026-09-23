import QtQuick
import QtQuick.Layouts

// Title + optional subtitle row for the top of a GlassCard. Right-side slot for
// a control (toggle, button) via the default `trailing` property.
Item {
    id: h
    property string title: ""
    property string subtitle: ""
    property string icon: ""          // image://icon/<hex>/<name> or asset url
    default property alias trailing: slot.data
    implicitHeight: Math.max(40, row.implicitHeight)

    RowLayout {
        id: row
        anchors.left: parent.left; anchors.right: slot.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 12
        Image {
            visible: h.icon !== ""
            source: h.icon
            sourceSize.width: 40; sourceSize.height: 40
            Layout.preferredWidth: 20; Layout.preferredHeight: 20
            Layout.alignment: Qt.AlignVCenter
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 2
            Text {
                text: h.title; color: Theme.textPrimary
                font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                Layout.fillWidth: true; elide: Text.ElideRight
            }
            Text {
                visible: h.subtitle !== ""
                text: h.subtitle; color: Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                Layout.fillWidth: true; wrapMode: Text.WordWrap
            }
        }
    }
    Item {
        id: slot
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: childrenRect.width; height: childrenRect.height
    }
}
