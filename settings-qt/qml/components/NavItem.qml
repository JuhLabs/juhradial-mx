import QtQuick
import QtQuick.Effects

// Sidebar nav row. "Light is state": only the active row carries accent (the
// filament and its bloom); inactive rows are graphite and white. Hover is a
// quiet wash, never a glow.
Item {
    id: it
    property string label
    property string icon: ""        // nav icon name (assets/icons/nav/<name>.svg)
    property bool active: false
    signal clicked
    height: 44
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined

    activeFocusOnTab: true
    Keys.onSpacePressed: it.clicked()
    Keys.onReturnPressed: it.clicked()
    Keys.onEnterPressed: it.clicked()
    Accessible.role: Accessible.PageTab
    Accessible.name: label
    Accessible.selected: active
    Accessible.onPressAction: it.clicked()

    Rectangle {
        id: pill
        anchors.fill: parent
        anchors.leftMargin: 8; anchors.rightMargin: 8
        anchors.topMargin: 2; anchors.bottomMargin: 2
        radius: Theme.radiusCtl
        color: it.active ? Theme.accentSubtle : (ma.containsMouse ? "#0FFFFFFF" : "transparent")
        border.width: it.active ? 1 : 0
        border.color: Theme.accentFaint
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
        FocusHalo { active: it.activeFocus; radius: Theme.radiusCtl; margin: 2 }
    }

    // accent filament: crisp bar + bloom, the row's power LED
    Item {
        x: 10; width: 3
        height: parent.height - 20
        anchors.verticalCenter: parent.verticalCenter
        opacity: it.active ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
        RectangularShadow {
            anchors.fill: parent
            radius: 1.5; blur: 10; spread: 1
            color: Theme.accentGlow
        }
        Rectangle { anchors.fill: parent; radius: 1.5; color: Theme.accent }
    }

    Image {
        id: ico
        x: 26; width: 20; height: 20
        anchors.verticalCenter: parent.verticalCenter
        visible: it.icon !== ""
        source: it.icon !== ""
                ? "image://icon/" + (it.active ? "FFFFFF" : (ma.containsMouse ? "E8EAED" : "9AA3B2")) + "/" + Theme.iconStyle + "/" + it.icon
                : ""
        sourceSize.width: 40; sourceSize.height: 40
        smooth: true
    }

    Text {
        anchors.verticalCenter: parent.verticalCenter
        x: it.icon !== "" ? 58 : 28
        text: it.label
        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
        font.weight: it.active ? Font.DemiBold : Font.Medium
        color: it.active ? Theme.textPrimary : (ma.containsMouse ? Theme.textBody : Theme.textMuted)
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
    }

    MouseArea {
        id: ma; anchors.fill: parent; hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: it.clicked()
    }
}
