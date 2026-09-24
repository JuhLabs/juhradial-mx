import QtQuick
import QtQuick.Controls.Basic as B

// Pick a haptic pattern by name and feel: each row shows the pattern's
// rhythm, its name and a one-line description, and resting on a row (mouse
// or keys) plays it on the mouse. Set currentId; picked(id) fires on choice.
B.ComboBox {
    id: control
    property string currentId: ""
    property string accessibleName: ""
    signal picked(string id)
    // Light the rhythm once (after a Play that played).
    function flash() { shownGlyph.play() }
    readonly property var entry: {
        for (var i = 0; i < count; i++) if (valueAt(i) === currentId) return model[i]
        return null
    }

    model: Backend.hapticPatterns()
    textRole: "name"
    valueRole: "id"
    implicitWidth: 196
    implicitHeight: 38
    Accessible.name: accessibleName
    Accessible.description: entry ? entry.desc : ""

    onModelChanged: _sync()
    onCurrentIdChanged: _sync()
    Component.onCompleted: _sync()
    function _sync() {
        for (var i = 0; i < count; i++)
            if (valueAt(i) === currentId) { if (currentIndex !== i) currentIndex = i; return }
    }
    onActivated: (i) => { currentId = valueAt(i); picked(currentId) }

    // Preview what the highlight rests on (hover or arrow keys).
    Timer {
        id: preview
        interval: 260
        onTriggered: if (control.popup.visible && control.highlightedIndex >= 0)
                         Backend.previewHaptic(control.valueAt(control.highlightedIndex))
    }
    onHighlightedIndexChanged: if (popup.visible) preview.restart()

    contentItem: Row {
        leftPadding: 12; spacing: 10
        RhythmGlyph {
            id: shownGlyph
            anchors.verticalCenter: parent.verticalCenter
            beats: control.entry ? control.entry.beats : []
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: control.width - 12 - 34 - 10 - 34
            text: control.displayText
            color: Theme.textBody
            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
            elide: Text.ElideRight
        }
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
    background: Item {
        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusCtl
            color: control.pressed ? "#26FFFFFF" : (control.hovered ? "#1AFFFFFF" : "#12FFFFFF")
            border.width: 1
            border.color: control.popup.visible ? Theme.accent : (control.hovered ? Theme.borderStrong : Theme.border)
            Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
        }
        FocusHalo { active: control.visualFocus && !control.popup.visible; radius: Theme.radiusCtl }
    }
    popup: B.Popup {
        y: control.height + 6
        width: Math.max(control.width, 300)
        implicitHeight: Math.min(contentItem.implicitHeight + 12, 420)
        padding: 6
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: Theme.dShort }
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
        id: row
        required property var model
        required property int index
        width: Math.max(control.width, 300) - 12
        height: 46
        highlighted: control.highlightedIndex === index
        Accessible.name: model.name + ". " + model.desc
        contentItem: Row {
            spacing: 12; leftPadding: 6
            RhythmGlyph {
                anchors.verticalCenter: parent.verticalCenter
                beats: row.model.beats
                color: row.highlighted ? Theme.accent : Theme.textMuted
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1
                Text {
                    text: row.model.name
                    color: row.highlighted ? Theme.accent : Theme.textBody
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                    font.weight: row.index === control.currentIndex ? Font.DemiBold : Font.Normal
                }
                Text {
                    text: row.model.desc
                    color: Theme.textMuted
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                }
            }
        }
        background: Rectangle { radius: 8; color: row.highlighted ? Theme.accentSubtle : "transparent" }
    }
}
