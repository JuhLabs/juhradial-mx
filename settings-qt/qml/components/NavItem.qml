import QtQuick
import QtQuick.Effects

// Sidebar nav row. Brand rule "light is state": the active row lights up (a
// bloomed accent filament + a soft glow behind its icon), inactive rows stay
// quiet. Machined depth on the active pill via a hairline top sheen.
Item {
    id: it
    property string label
    property string icon: ""
    property bool active: false
    signal clicked
    height: 48
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined

    activeFocusOnTab: true
    Keys.onSpacePressed: it.clicked()
    Keys.onReturnPressed: it.clicked()

    // ---- pill background ----
    Rectangle {
        id: pill
        anchors.fill: parent
        anchors.leftMargin: 8; anchors.rightMargin: 8
        anchors.topMargin: 3; anchors.bottomMargin: 3
        radius: Theme.radiusCtl
        color: it.active ? Theme.accentSubtle : (ma.containsMouse ? "#12FFFFFF" : "transparent")
        border.width: (it.active || it.activeFocus) ? 1 : 0
        border.color: it.activeFocus ? Theme.accent
                      : (it.active ? Theme.accentFaint : "transparent")
        Behavior on color { ColorAnimation { duration: 130 } }

        // machined top-edge sheen, only on the lit row
        Rectangle {
            anchors.top: parent.top; anchors.topMargin: 1
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 20; height: 1; radius: 1
            color: "#18FFFFFF"
            opacity: it.active ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 160 } }
        }
    }

    // ---- accent filament (the "power LED"): crisp bar + soft bloom ----
    Item {
        x: 10; width: 3
        height: parent.height - 24
        anchors.verticalCenter: parent.verticalCenter
        opacity: it.active ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Rectangle {   // bloom
            anchors.centerIn: parent
            width: 9; height: parent.height + 10; radius: 5
            color: Theme.accent; opacity: 0.30
        }
        Rectangle {   // crisp core
            anchors.fill: parent; radius: 2; color: Theme.accent
        }
    }

    // ---- icon (+ glow when active) ----
    Item {
        id: iconWrap
        width: 22; height: 22; x: 26
        anchors.verticalCenter: parent.verticalCenter

        MultiEffect {   // blurred copy behind = soft accent glow, active only
            anchors.fill: ico
            source: ico
            visible: it.active
            blurEnabled: true; blur: 1.0; blurMax: 22
            opacity: 0.85
        }
        Image {
            id: ico
            source: it.icon
            visible: it.icon !== ""
            sourceSize.width: 44; sourceSize.height: 44
            anchors.fill: parent; smooth: true
            opacity: it.active ? 1.0 : (ma.containsMouse ? 0.9 : 0.5)
            Behavior on opacity { NumberAnimation { duration: 130 } }
        }
    }

    Text {
        anchors.verticalCenter: parent.verticalCenter
        x: it.icon !== "" ? 60 : 28
        text: it.label
        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
        font.weight: it.active ? Font.DemiBold : Font.Medium
        color: it.active ? Theme.textPrimary : Theme.textMuted
        Behavior on color { ColorAnimation { duration: 130 } }
    }

    MouseArea {
        id: ma; anchors.fill: parent; hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: it.clicked()
    }
}
