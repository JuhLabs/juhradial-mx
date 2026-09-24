import QtQuick
import QtQuick.Shapes

// Empty state that teaches: spot illustration, one sentence, one action.
// Dashed hairline says "nothing here yet" without shouting.
Item {
    id: es
    property string spot: ""
    property string title: ""
    property string body: ""
    // The one action (a PrimaryButton child) goes in the default slot.
    default property alias action: actionSlot.data
    Accessible.role: Accessible.Grouping
    Accessible.name: title
    Accessible.description: body
    implicitHeight: col.implicitHeight + 56

    Shape {
        anchors.fill: parent
        antialiasing: true
        ShapePath {
            strokeColor: Theme.borderStrong
            strokeWidth: 1
            strokeStyle: ShapePath.DashLine
            dashPattern: [6, 5]
            fillColor: "transparent"
            startX: 1; startY: Theme.radiusCard
            PathArc { x: Theme.radiusCard; y: 1; radiusX: Theme.radiusCard - 1; radiusY: Theme.radiusCard - 1 }
            PathLine { x: es.width - Theme.radiusCard; y: 1 }
            PathArc { x: es.width - 1; y: Theme.radiusCard; radiusX: Theme.radiusCard - 1; radiusY: Theme.radiusCard - 1 }
            PathLine { x: es.width - 1; y: es.height - Theme.radiusCard }
            PathArc { x: es.width - Theme.radiusCard; y: es.height - 1; radiusX: Theme.radiusCard - 1; radiusY: Theme.radiusCard - 1 }
            PathLine { x: Theme.radiusCard; y: es.height - 1 }
            PathArc { x: 1; y: es.height - Theme.radiusCard; radiusX: Theme.radiusCard - 1; radiusY: Theme.radiusCard - 1 }
            PathLine { x: 1; y: Theme.radiusCard }
        }
    }
    Column {
        id: col
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 420)
        spacing: Theme.gapS
        SpotImage {
            visible: es.spot !== ""
            name: es.spot; size: 116
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Item { width: 1; height: 2 }
        Text {
            width: parent.width
            text: es.title; color: Theme.textPrimary
            horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
            font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
        }
        Text {
            visible: es.body !== ""
            width: parent.width
            text: es.body; color: Theme.textMuted
            horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
        }
        Item { width: 1; height: 4 }
        Item {
            id: actionSlot
            anchors.horizontalCenter: parent.horizontalCenter
            width: childrenRect.width; height: childrenRect.height
        }
    }
}
