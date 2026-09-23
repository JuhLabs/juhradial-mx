import QtQuick

// Numeric stepper: [-]  value suffix  [+]. Emits committed(int) on every change
// (suitable for D-Bus/hardware writes; values are discrete).
Item {
    id: st
    property int from: 0
    property int to: 100
    property int step: 1
    property int value: 0
    property string suffix: ""
    signal committed(int v)
    implicitWidth: 132; implicitHeight: 36

    activeFocusOnTab: true
    Keys.onLeftPressed: _set(value - step)
    Keys.onRightPressed: _set(value + step)

    function _set(v) {
        var nv = Math.max(from, Math.min(to, v))
        if (nv !== value) { value = nv; committed(nv) }
    }

    Rectangle {
        anchors.fill: parent; radius: Theme.radiusCtl
        color: "#14FFFFFF"; border.width: 1
        border.color: st.activeFocus ? Theme.accent : Theme.border
    }
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
            Text { anchors.centerIn: parent; text: "−"; color: Theme.textBody
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
                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
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
