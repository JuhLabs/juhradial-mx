import QtQuick
import QtQuick.Layouts

// Title + optional subtitle row for the top of a GlassCard. Right-side slot for
// a control (toggle, button) via the default `trailing` property.
Item {
    id: h
    property string title: ""
    property string subtitle: ""
    property string icon: ""          // image://icon/<hex>/<name> or asset url
    property string mousePart: ""     // a MouseGlyph part instead of the icon
    default property alias trailing: slot.data
    implicitHeight: Math.max(40, row.implicitHeight)

    // Global search can land on a card title too (SettingRow does the same
    // for rows): scroll the card into view and flash the header.
    function _maybeTarget() {
        if (Backend.searchTarget === "" || Backend.searchTarget !== h.title) return
        var p = h.parent
        while (p && !(p.contentY !== undefined && p.contentItem !== undefined)) p = p.parent
        if (p) {
            var pos = h.mapToItem(p.contentItem, 0, 0)
            p.contentY = Math.max(0, Math.min(pos.y - 50, Math.max(0, p.contentHeight - p.height)))
        }
        flash.restart()
    }
    Component.onCompleted: Qt.callLater(_maybeTarget)
    Connections { target: Backend; function onSearchTargetChanged() { h._maybeTarget() } }
    Rectangle {
        id: hi
        anchors.fill: parent
        anchors.margins: -6
        radius: Theme.radiusCtl
        color: Theme.accentSubtle
        border.color: Theme.accent; border.width: 1
        opacity: 0
        visible: opacity > 0.01
        SequentialAnimation {
            id: flash
            NumberAnimation { target: hi; property: "opacity"; from: 0.0; to: 1.0; duration: 180; easing.type: Easing.OutCubic }
            NumberAnimation { target: hi; property: "opacity"; to: 0.4; duration: 460 }
            NumberAnimation { target: hi; property: "opacity"; to: 1.0; duration: 420 }
            NumberAnimation { target: hi; property: "opacity"; to: 0.0; duration: 760; easing.type: Easing.InCubic }
        }
    }

    RowLayout {
        id: row
        anchors.left: parent.left; anchors.right: slot.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 12
        // icon chip: the accent glyph sits in a quiet inset tile
        Rectangle {
            visible: h.icon !== "" || h.mousePart !== ""
            Layout.preferredWidth: 34; Layout.preferredHeight: 34
            Layout.alignment: Qt.AlignVCenter
            radius: 10
            color: Theme.accentFaint
            border.width: 1; border.color: Theme.accentFaint
            MouseGlyph {
                anchors.centerIn: parent
                visible: h.mousePart !== ""
                part: h.mousePart
            }
            Image {
                anchors.centerIn: parent
                visible: h.mousePart === ""
                source: h.mousePart === "" ? h.icon : ""
                sourceSize.width: 40; sourceSize.height: 40
                width: 19; height: 19; smooth: true
            }
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
