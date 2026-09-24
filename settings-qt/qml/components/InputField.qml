import QtQuick
import QtQuick.Controls.Basic as B

// One text field for the whole app: inset surface, hairline, accent focus halo,
// inline error line. `mono` for identifiers (window classes, URLs).
Item {
    id: f
    property alias text: field.text
    property alias placeholder: field.placeholderText
    property alias field: field
    property bool mono: false
    property string error: ""
    signal accepted
    signal editingFinished
    signal textEdited
    property string accessibleName: ""
    property string accessibleDescription: ""
    implicitWidth: 220
    implicitHeight: 38 + (error !== "" ? errTxt.implicitHeight + 4 : 0)

    Rectangle {
        id: box
        width: parent.width; height: 38
        radius: Theme.radiusCtl
        color: field.activeFocus ? "#18FFFFFF" : (hov.hovered ? "#16FFFFFF" : "#12FFFFFF")
        border.width: 1
        border.color: f.error !== "" ? Theme.danger : (hov.hovered ? Theme.borderStrong : Theme.border)
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
        Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
        HoverHandler { id: hov }
        FocusHalo { active: field.activeFocus; radius: Theme.radiusCtl }
        B.TextField {
            id: field
            Accessible.name: f.accessibleName !== "" ? f.accessibleName : placeholderText
            Accessible.description: f.error !== "" ? f.error : f.accessibleDescription
            anchors.fill: parent
            anchors.leftMargin: 12; anchors.rightMargin: 10
            placeholderTextColor: Theme.textMuted
            color: Theme.textBody
            font.family: f.mono ? Theme.fontMono : Theme.fontUI
            font.pixelSize: f.mono ? Theme.fsSmall : Theme.fsBody
            verticalAlignment: Text.AlignVCenter
            selectByMouse: true
            background: Item {}
            onAccepted: f.accepted()
            onEditingFinished: f.editingFinished()
            onTextEdited: f.textEdited()
        }
    }
    Text {
        id: errTxt
        visible: f.error !== ""
        anchors.top: box.bottom; anchors.topMargin: 4
        anchors.left: parent.left; anchors.leftMargin: 4
        width: parent.width - 8
        text: f.error; color: Theme.danger; wrapMode: Text.WordWrap
        font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
    }
}
