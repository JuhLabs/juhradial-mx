import QtQuick

// Numeric stepper: [-]  value suffix  [+]. Emits committed(int) on every change
// (suitable for D-Bus/hardware writes; values are discrete). Mono readout.
Item {
    id: st
    property int from: 0
    property int to: 100
    property int step: 1
    property int value: 0
    property string suffix: ""
    property int pageStep: 0                  // 0 = step * 10
    property string accessibleName: ""
    property string accessibleDescription: ""
    signal committed(int v)
    implicitWidth: 138; implicitHeight: 36

    activeFocusOnTab: true
    Keys.onLeftPressed: _set(value - step)
    Keys.onDownPressed: _set(value - step)
    Keys.onRightPressed: _set(value + step)
    Keys.onUpPressed: _set(value + step)
    Keys.onPressed: (e) => {
        const page = pageStep > 0 ? pageStep : step * 10
        if (e.key === Qt.Key_PageUp) { _set(value + page); e.accepted = true }
        else if (e.key === Qt.Key_PageDown) { _set(value - page); e.accepted = true }
        else if (e.key === Qt.Key_Home) { _set(from); e.accepted = true }
        else if (e.key === Qt.Key_End) { _set(to); e.accepted = true }
    }

    Accessible.role: Accessible.SpinBox
    Accessible.name: accessibleName
    Accessible.description: (value + suffix) + (accessibleDescription ? ". " + accessibleDescription : "")
    Accessible.onIncreaseAction: _set(value + step)
    Accessible.onDecreaseAction: _set(value - step)

    function _set(v) {
        var nv = Math.max(from, Math.min(to, v))
        if (nv !== value) { value = nv; committed(nv) }
    }

    Rectangle {
        anchors.fill: parent; radius: Theme.radiusCtl
        color: "#12FFFFFF"; border.width: 1; border.color: Theme.border
    }
    FocusHalo { active: st.activeFocus; radius: Theme.radiusCtl }
    Row {
        anchors.fill: parent
        Item {
            width: 34; height: parent.height
            Rectangle {
                anchors.centerIn: parent; width: 28; height: 28; radius: 14
                color: minusMa.pressed ? "#28FFFFFF"
                       : (minusMa.containsMouse ? "#18FFFFFF" : "transparent")
                Behavior on color { ColorAnimation { duration: Theme.dShort } }
            }
            Text { anchors.centerIn: parent; text: "\u2212"; color: Theme.textBody  // i18n-ignore
                   opacity: st.value === st.from ? 0.3 : 1.0
                   font.pixelSize: 18; font.family: Theme.fontUI }
            MouseArea { id: minusMa; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: st._set(st.value - st.step) }
        }
        Item {
            width: parent.width - 68; height: parent.height
            Text {
                anchors.centerIn: parent
                text: st.value + st.suffix; color: Theme.textPrimary
                font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
            }
        }
        Item {
            width: 34; height: parent.height
            Rectangle {
                anchors.centerIn: parent; width: 28; height: 28; radius: 14
                color: plusMa.pressed ? "#28FFFFFF"
                       : (plusMa.containsMouse ? "#18FFFFFF" : "transparent")
                Behavior on color { ColorAnimation { duration: Theme.dShort } }
            }
            Text { anchors.centerIn: parent; text: "+"; color: Theme.textBody
                   opacity: st.value === st.to ? 0.3 : 1.0
                   font.pixelSize: 17; font.family: Theme.fontUI }
            MouseArea { id: plusMa; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: st._set(st.value + st.step) }
        }
    }
}
