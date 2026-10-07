import QtQuick

// Stands in for a page whose QML could not be loaded: what failed and, where
// a QML module is missing (Debian-family systems package each one on its
// own), the command that installs it. An empty pane told nobody anything
// (issue #172). Uses nothing beyond QtQuick and the card itself, so it loads
// whatever the page was missing.
Item {
    id: pe
    property url source
    // Compiling the page again is the only way to its error text; it runs
    // once, when the panel becomes visible.
    readonly property string detail: visible ? _errors() : ""
    readonly property string fix: detail !== "" ? Backend.qmlErrorHint(detail) : ""
    function _errors() {
        const component = Qt.createComponent(source)
        const text = component.errorString().trim()
        component.destroy()
        return text
    }

    GlassCard {
        width: Math.min(parent.width, 720)
        height: col.implicitHeight + 2 * Theme.pad
        Column {
            id: col
            x: Theme.pad; y: Theme.pad
            width: parent.width - 2 * Theme.pad
            spacing: Theme.gapL
            Row {
                spacing: Theme.gapS
                ActionIcon { iconName: "dialog-warning-symbolic"; tint: Theme.danger; px: 20; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    text: qsTr("This page could not be loaded")
                    color: Theme.textPrimary
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                }
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                visible: pe.fix !== ""
                text: qsTr("A part of Qt that this page needs is not installed. Run this in a terminal, then open Settings again:")
                color: Theme.textBody
                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
            }
            Text {
                width: parent.width; wrapMode: Text.WrapAnywhere
                visible: pe.fix !== ""
                text: pe.fix  // i18n-ignore (a shell command)
                color: Theme.textPrimary
                font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
            }
            Text {
                width: parent.width; wrapMode: Text.WrapAnywhere
                text: pe.detail  // i18n-ignore (Qt's own error text)
                color: Theme.textMuted
                font.family: Theme.fontMono; font.pixelSize: Theme.fsMicro
            }
            Row {
                spacing: Theme.gapS
                PrimaryButton {
                    visible: pe.fix !== ""
                    text: qsTr("Copy command")
                    onClicked: Backend.copyText(pe.fix, qsTr("Command"))
                }
                PrimaryButton {
                    text: qsTr("Copy details"); ghost: true
                    onClicked: Backend.copyText(pe.detail, qsTr("Details"))
                }
            }
        }
    }
}
