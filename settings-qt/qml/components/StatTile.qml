import QtQuick

// Compact stat block for dashboards: big value over a muted label, optional
// leading freedesktop icon. Drop inside a GlassCard.
Item {
    id: t
    property string value: ""
    property string label: ""
    property string icon: ""
    property color valueColor: Theme.textPrimary

    Column {
        anchors.centerIn: parent
        spacing: 6
        ActionIcon {
            visible: t.icon !== ""
            iconName: t.icon; tint: Theme.accent; px: 22
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Text {
            text: t.value; color: t.valueColor
            font.family: Theme.fontUI; font.pixelSize: Theme.fsH2; font.weight: Font.DemiBold
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Text {
            text: t.label; color: Theme.textMuted
            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }
}
