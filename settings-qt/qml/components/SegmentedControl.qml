import QtQuick

// Pill segmented control. model = [{id,name}, ...]. currentId selects; the
// accent highlight slides between segments. activated(id) fires on click.
Item {
    id: seg
    property var model: []
    property string currentId: ""
    property string accessibleName: ""
    property string accessibleDescription: ""
    signal activated(string id)
    Accessible.role: Accessible.Grouping
    Accessible.name: accessibleName
    Accessible.description: accessibleDescription
    implicitWidth: 280; implicitHeight: 36

    readonly property int _count: model ? model.length : 0
    readonly property real _segW: _count > 0 ? width / _count : width
    function _indexOf(id) {
        for (var i = 0; i < _count; i++) if (model[i].id === id) return i
        return 0
    }

    activeFocusOnTab: true
    Keys.onSpacePressed: _next()
    Keys.onReturnPressed: _next()
    Keys.onRightPressed: _next()
    Keys.onLeftPressed: _prev()
    Keys.onDownPressed: _next()
    Keys.onUpPressed: _prev()
    Keys.onPressed: (e) => {
        if (_count === 0) return
        const i = e.key === Qt.Key_Home ? 0 : e.key === Qt.Key_End ? _count - 1 : -1
        if (i < 0) return
        currentId = model[i].id; activated(currentId); e.accepted = true
    }
    function _next() {
        if (_count === 0) return
        var i = (_indexOf(currentId) + 1) % _count
        currentId = model[i].id
        activated(currentId)
    }
    function _prev() {
        if (_count === 0) return
        var i = (_indexOf(currentId) + _count - 1) % _count
        currentId = model[i].id
        activated(currentId)
    }

    Rectangle {
        anchors.fill: parent; radius: height / 2
        color: Theme.surfaceInset; border.width: 1; border.color: Theme.border
    }
    FocusHalo { active: seg.activeFocus; radius: seg.height / 2 }
    Rectangle {
        id: pill
        width: seg._segW - 4; height: parent.height - 6
        radius: height / 2; y: 3
        x: 2 + seg._indexOf(seg.currentId) * seg._segW
        color: Theme.accent
        Behavior on x { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            anchors.margins: 1; height: 1; radius: 1; color: "#33FFFFFF"
        }
    }
    Row {
        anchors.fill: parent
        Repeater {
            model: seg.model
            Item {
                width: seg._segW; height: seg.height
                required property var modelData
                required property int index
                Rectangle {
                    anchors.fill: parent; anchors.margins: 3
                    radius: height / 2; color: "#12FFFFFF"
                    visible: segMa.containsMouse && seg.currentId !== modelData.id
                }
                Text {
                    anchors.centerIn: parent
                    text: modelData.name
                    color: seg.currentId === modelData.id ? Theme.bgBase : Theme.textBody
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    font.weight: seg.currentId === modelData.id ? Font.DemiBold : Font.Medium
                    Behavior on color { ColorAnimation { duration: Theme.dShort } }
                }
                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData.name
                Accessible.checkable: true
                Accessible.checked: seg.currentId === modelData.id
                Accessible.onPressAction: { seg.currentId = modelData.id; seg.activated(modelData.id) }
                MouseArea {
                    id: segMa
                    anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: { seg.currentId = modelData.id; seg.activated(modelData.id) }
                }
            }
        }
    }
}
