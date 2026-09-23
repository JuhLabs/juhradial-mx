import QtQuick
import QtQuick.Shapes

// One button callout over a mouse photo: a pin on the physical button, a thin
// elbow leader line, and a chip showing the button name + its current action.
// Fills the image box; positions are normalized (0..1) to that box so they
// track any resize. Click the pin or chip to remap. selected highlights it.
Item {
    id: c
    anchors.fill: parent

    property real nx: 0.5      // pin position on the image (normalized)
    property real ny: 0.5
    property real cx: 0.5      // chip position (normalized, in a gutter)
    property real cy: 0.5
    property string label: ""
    property string action: ""
    property bool selected: false
    property bool changed: false        // differs from the default: a dot on the chip
    property string note: ""            // a third line (a macro on the same button)
    property bool editable: false       // drag the pin to reposition it
    signal clicked
    signal moved(real nx, real ny)
    // Keyboard: Tab reaches each callout, Return/Space opens its action.
    activeFocusOnTab: !editable
    Keys.onReturnPressed: c.clicked()
    Keys.onEnterPressed: c.clicked()
    Keys.onSpacePressed: c.clicked()
    Accessible.role: Accessible.Button
    Accessible.name: label + ": " + action + (note !== "" ? ", " + note : "")
    Accessible.onPressAction: c.clicked()

    readonly property real px: nx * width
    readonly property real py: ny * height
    readonly property real chx: cx * width
    readonly property real chy: cy * height
    readonly property bool hot: selected || pinMa.containsMouse || chipMa.containsMouse

    // leader line: pin -> horizontal -> chip
    Shape {
        anchors.fill: parent; antialiasing: true; z: 1
        ShapePath {
            strokeColor: c.hot ? Theme.accent : Theme.borderStrong
            strokeWidth: c.hot ? 2 : 1.4
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            startX: c.px; startY: c.py
            PathLine { x: c.chx < c.px ? c.chx + chip.width / 2 : c.chx - chip.width / 2; y: c.py }
            PathLine { x: c.chx < c.px ? c.chx + chip.width / 2 : c.chx - chip.width / 2; y: c.chy }
        }
    }

    // pin on the button
    Rectangle {
        z: 2
        x: c.px - width / 2; y: c.py - height / 2
        width: c.hot ? 18 : 14; height: width; radius: width / 2
        color: c.hot ? Theme.accent : "#E8EAED"
        border.color: c.hot ? "#FFFFFF" : Theme.accent; border.width: 2
        Behavior on width { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
        // static faint halo (no pulse: an idle pin is not state)
        Rectangle {
            anchors.centerIn: parent
            width: parent.width + 12; height: width; radius: width / 2
            color: "transparent"; border.color: Theme.accentGlow; border.width: 2
            opacity: c.hot ? 0.0 : 0.35
            Behavior on opacity { NumberAnimation { duration: Theme.dShort } }
        }
        MouseArea {
            id: pinMa; anchors.fill: parent; anchors.margins: -8
            hoverEnabled: true
            cursorShape: c.editable ? Qt.SizeAllCursor : Qt.PointingHandCursor
            onClicked: if (!c.editable) c.clicked()
            onPositionChanged: (m) => {
                if (c.editable && pressed) {
                    var pt = mapToItem(c, m.x, m.y)
                    c.nx = Math.max(0.02, Math.min(0.98, pt.x / c.width))
                    c.ny = Math.max(0.02, Math.min(0.98, pt.y / c.height))
                }
            }
            onReleased: if (c.editable) c.moved(c.nx, c.ny)
        }
    }

    // chip: button name + current action
    Rectangle {
        id: chip
        z: 3
        x: c.chx - width / 2; y: c.chy - height / 2
        width: chipCol.implicitWidth + 24; height: chipCol.implicitHeight + 14
        radius: 10
        color: c.hot ? Theme.accentSubtle : Theme.surfaceGlassHi
        border.color: c.hot ? Theme.accent : Theme.border; border.width: 1
        Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
        Column {
            id: chipCol
            anchors.centerIn: parent; spacing: 1
            Row {
                spacing: 5
                Text {
                    text: c.label; color: Theme.textMuted
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro; font.weight: Font.Medium
                }
                Rectangle {
                    visible: c.changed
                    anchors.verticalCenter: parent.verticalCenter
                    width: 6; height: 6; radius: 3; color: Theme.accent
                }
            }
            Text {
                text: c.action; color: c.hot ? Theme.accent : Theme.textBody
                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
            }
            Text {
                visible: c.note !== ""
                text: c.note; color: Theme.danger
                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro; font.weight: Font.Medium
            }
        }
        MouseArea { id: chipMa; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor; onClicked: c.clicked() }
        FocusHalo { active: c.activeFocus; radius: parent.radius; margin: 2 }
    }
}
