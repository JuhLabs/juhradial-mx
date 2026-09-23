import QtQuick

Item {
    id: row
    property string label
    property string desc: ""
    default property alias control: slot.data
    width: parent ? parent.width : 400
    height: Math.max(56, col.implicitHeight + 24)

    // Global-search highlight: when Backend flags this row's label as the search
    // target, scroll it into view and flash an accent wash. Both completion and
    // the change signal are handled so it fires whether the page already existed
    // or was lazily built by the result jump.
    function _flickToView() {
        var p = row.parent
        while (p) {
            if (p.contentY !== undefined && p.contentHeight !== undefined
                    && p.contentItem !== undefined)
                break
            p = p.parent
        }
        if (!p) return
        var pos = row.mapToItem(p.contentItem, 0, 0)
        var maxY = Math.max(0, p.contentHeight - p.height)
        p.contentY = Math.max(0, Math.min(pos.y - 50, maxY))
    }
    function _maybeTarget() {
        if (Backend.searchTarget !== "" && Backend.searchTarget === row.label) {
            _flickToView()
            flash.restart()
        }
    }
    Component.onCompleted: Qt.callLater(_maybeTarget)
    Connections { target: Backend; function onSearchTargetChanged() { row._maybeTarget() } }

    // Quiet hover wash so the eye finds the row it is pointing at.
    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: -8; anchors.rightMargin: -8
        anchors.topMargin: 2; anchors.bottomMargin: 2
        radius: Theme.radiusCtl
        color: hoverMa.containsMouse ? "#0AFFFFFF" : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
    }
    MouseArea { id: hoverMa; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }

    Rectangle {
        id: hi
        anchors.fill: parent
        anchors.leftMargin: -8; anchors.rightMargin: -8
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

    Column {
        id: col
        anchors.left: parent.left
        anchors.right: slot.left
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 3
        Text {
            text: row.label; color: Theme.textBody
            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
        }
        Text {
            visible: row.desc !== ""
            text: row.desc; color: Theme.textMuted
            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            width: col.width; wrapMode: Text.WordWrap
        }
    }
    Item {
        id: slot
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: childrenRect.width; height: childrenRect.height
    }
}
