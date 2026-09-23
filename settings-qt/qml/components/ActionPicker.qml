import QtQuick
import QtQuick.Controls.Basic as B

// Reusable action chooser popup. Call open() after setting `actions` (a list of
// {id, name, icon?, hex?}) and `title`. Emits picked(id). Used by the physical
// button map and the radial-slice editor so both share one polished picker.
B.Popup {
    id: pop
    property var actions: []
    property string title: "Choose an action"
    property string currentId: ""
    signal picked(string id)

    modal: true
    dim: true
    focus: true
    width: 460
    height: Math.min(560, parent ? parent.height - 80 : 560)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside

    property string _q: ""

    onAboutToShow: { _q = ""; search.text = "" }

    background: Rectangle {
        radius: Theme.radiusCard; color: Theme.surfaceGlassHi
        border.color: Theme.borderStrong; border.width: 1
    }
    B.Overlay.modal: Rectangle { color: "#99000000" }

    contentItem: Column {
        spacing: 12
        Text {
            text: pop.title; color: Theme.textPrimary
            font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
        }
        Rectangle {
            width: parent.width; height: 38; radius: Theme.radiusCtl
            color: "#14FFFFFF"; border.color: search.activeFocus ? Theme.accent : Theme.border; border.width: 1
            Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
            B.TextField {
                id: search
                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                placeholderText: "Search actions…"
                placeholderTextColor: Theme.textMuted
                color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                verticalAlignment: Text.AlignVCenter
                background: Item {}
                onTextChanged: pop._q = text
            }
        }
        B.ScrollView {
            width: parent.width
            height: pop.height - 130
            clip: true
            B.ScrollBar.horizontal.policy: B.ScrollBar.AlwaysOff
            Grid {
                width: pop.width - 36
                columns: 2; spacing: 8
                Repeater {
                    // Bound to the full list once: filtering hides delegates
                    // instead of rebuilding them all on every keystroke.
                    model: pop.actions
                    Rectangle {
                        required property var modelData
                        readonly property bool _match: pop._q === ""
                            || (modelData.name || "").toLowerCase().indexOf(pop._q.toLowerCase()) >= 0
                        visible: _match
                        width: _match ? (pop.width - 44) / 2 : 0
                        height: _match ? 46 : 0
                        radius: 11
                        color: pop.currentId === modelData.id ? Theme.accentSubtle
                               : (rowMa.containsMouse ? "#16FFFFFF" : "#0CFFFFFF")
                        border.width: 1
                        border.color: pop.currentId === modelData.id ? Theme.accent : Theme.border
                        Behavior on color { ColorAnimation { duration: Theme.dShort } }
                        Row {
                            anchors.fill: parent; anchors.leftMargin: 12; spacing: 11
            Item {
                                width: 30; height: 30
                                anchors.verticalCenter: parent.verticalCenter
                                property string btn: (Theme.iconStyle, Theme.sliceButton(modelData.id || ""))
                                Image {
                                    anchors.fill: parent; visible: parent.btn !== ""
                                    source: parent.btn; sourceSize.width: 96; sourceSize.height: 96
                                    smooth: true; fillMode: Image.PreserveAspectFit
                                }
                                Rectangle {
                                    anchors.fill: parent; radius: 8; visible: parent.btn === ""
                                    color: modelData.hex ? Qt.rgba(0, 0, 0, 0.25) : "transparent"
                                    ActionIcon {
                                        anchors.centerIn: parent
                                        iconName: modelData.icon || ""
                                        tint: modelData.hex ? modelData.hex : Theme.accent
                                        px: 18
                                    }
                                }
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 60
                                text: modelData.name; color: Theme.textBody; elide: Text.ElideRight
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.Medium
                            }
                        }
                        MouseArea {
                            id: rowMa; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: { pop.picked(modelData.id); pop.close() }
                        }
                    }
                }
            }
        }
    }
}
