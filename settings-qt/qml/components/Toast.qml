import QtQuick
import QtQuick.Effects

// Bottom-centre status toast with an optional action (Undo). One at a time;
// a new message replaces the current one. show(text, kind, actionLabel, cb).
Item {
    id: toast
    anchors.fill: parent
    z: 1000
    property string text: ""
    property string kind: "info"          // info | success | warning | danger
    property string actionLabel: ""
    property var actionCallback: null
    readonly property bool shown: text !== ""

    function show(msg, k, label, cb) {
        text = msg
        kind = k || "info"
        actionLabel = label || ""
        actionCallback = cb || null
        hideTimer.restart()
    }
    function hide() { text = ""; hideTimer.stop() }
    Timer { id: hideTimer; interval: 4200; onTriggered: toast.hide() }

    readonly property color _tint: kind === "success" ? "#2FBF71"
                                 : kind === "warning" ? "#F5B22A"
                                 : kind === "danger" ? Theme.danger : Theme.accent

    Item {
        id: card
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: toast.shown ? 22 : 4
        width: row.implicitWidth + 32
        height: 44
        opacity: toast.shown ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
        Behavior on anchors.bottomMargin { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
        RectangularShadow {
            anchors.fill: parent; radius: 12; blur: 24; offset.y: 8; color: "#80000000"
        }
        Rectangle {
            anchors.fill: parent; radius: 12
            color: Theme.surfaceGlassHi
            border.width: 1; border.color: Theme.borderStrong
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                anchors.leftMargin: 12; anchors.rightMargin: 12; anchors.topMargin: 1
                height: 1; color: Theme.borderLit
            }
        }
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 12
            Rectangle {
                width: 8; height: 8; radius: 4; color: toast._tint
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: toast.text; color: Theme.textBody
                anchors.verticalCenter: parent.verticalCenter
                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
            }
            Text {
                visible: toast.actionLabel !== ""
                text: toast.actionLabel; color: Theme.accent
                anchors.verticalCenter: parent.verticalCenter
                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                MouseArea {
                    anchors.fill: parent; anchors.margins: -8
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { if (toast.actionCallback) toast.actionCallback(); toast.hide() }
                }
            }
        }
    }
}
