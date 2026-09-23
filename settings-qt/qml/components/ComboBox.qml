import QtQuick
import QtQuick.Controls.Basic as B

// Dark, accent-aware dropdown. Model is a list of {id, name} objects.
// Set currentId to preselect; activated(id) fires on pick.
B.ComboBox {
    id: control
    property string currentId: ""
    signal activated2(string id)

    textRole: "name"
    valueRole: "id"
    implicitWidth: 188
    implicitHeight: 38

    onModelChanged: _sync()
    onCurrentIdChanged: _sync()
    Component.onCompleted: _sync()
    function _sync() {
        if (!model) return
        for (var i = 0; i < count; i++) {
            if (valueAt(i) === currentId) { if (currentIndex !== i) currentIndex = i; return }
        }
    }
    onActivated: (i) => { currentId = valueAt(i); activated2(currentId) }

    contentItem: Text {
        leftPadding: 14; rightPadding: 34
        text: control.displayText
        color: Theme.textBody
        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Canvas {
        x: control.width - width - 13; y: control.height / 2 - 3
        width: 11; height: 7
        onPaint: {
            var c = getContext("2d"); c.reset()
            c.strokeStyle = Theme.textMuted; c.lineWidth = 1.6; c.lineCap = "round"
            c.beginPath(); c.moveTo(1, 1); c.lineTo(width / 2, height - 1); c.lineTo(width - 1, 1); c.stroke()
        }
    }
    background: Rectangle {
        radius: Theme.radiusCtl
        color: control.pressed ? "#26FFFFFF" : (control.hovered ? "#1CFFFFFF" : "#14FFFFFF")
        border.width: 1
        border.color: control.activeFocus || control.popup.visible ? Theme.accent : Theme.border
        Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
    }
    popup: B.Popup {
        y: control.height + 6
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 12, 300)
        padding: 6
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: Theme.dShort }
            NumberAnimation { property: "scale"; from: 0.94; to: 1.0; duration: Theme.dShort; easing.type: Easing.OutCubic }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: Theme.dShort }
        }
        background: Rectangle {
            radius: 12; color: Theme.surfaceGlassHi
            border.color: Theme.borderStrong; border.width: 1
        }
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            B.ScrollIndicator.vertical: B.ScrollIndicator {}
        }
    }
    delegate: B.ItemDelegate {
        required property var model
        required property int index
        width: control.width - 12
        height: 34
        contentItem: Text {
            text: model.name
            color: highlighted ? Theme.accent : Theme.textBody
            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
            font.weight: index === control.currentIndex ? Font.DemiBold : Font.Normal
            verticalAlignment: Text.AlignVCenter; leftPadding: 8; elide: Text.ElideRight
        }
        highlighted: control.highlightedIndex === index
        background: Rectangle {
            radius: 8; color: highlighted ? Theme.accentSubtle : "transparent"
        }
    }
}
