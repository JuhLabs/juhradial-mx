import QtQuick
import QtQuick.Layouts
import "../components"

Item {
    id: page
    anchors.fill: parent
    readonly property var pages: Backend.keypadPages
    readonly property var status: Backend.keypadStatus
    readonly property int currentPage: Math.max(0, Math.min(status.active_page, pages.length - 1))
    property int selectedKey: 1
    property int litKey: 0
    property int bump: 0

    function step(delta) {
        if (pages.length) Backend.setKeypadPage((currentPage + delta + pages.length) % pages.length)
    }
    function editKey(key) { selectedKey = key; editor.load() }

    Connections {
        target: Backend
        function onConfigChanged() { editor.load() }
        function onKeypadChanged() { page.bump++ }
        function onKeypadKeyPressed(p, key) {
            if (p === page.currentPage) { page.litKey = key; flash.restart() }
        }
    }
    Timer { id: flash; interval: 300; onTriggered: page.litKey = 0 }
    Component.onCompleted: Backend.refreshKeypadStatus()
    component Divider: Rectangle { width: parent.width; height: 1; color: Theme.border }

    Flickable {
        anchors.fill: parent
        clip: true; contentHeight: column.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        ColumnLayout {
            id: column
            width: parent.width; spacing: Theme.gap

            GlassCard {
                Layout.fillWidth: true; Layout.preferredHeight: 190
                RowLayout {
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapL
                    Column {
                        Layout.fillWidth: true; spacing: Theme.gapS
                        Text {
                            text: qsTr("MX Keypad")
                            color: Theme.textPrimary; font.family: Theme.fontUI
                            font.pixelSize: Theme.fsH1; font.weight: Font.Bold
                        }
                        Text {
                            width: parent.width; wrapMode: Text.WordWrap
                            text: qsTr("Nine keys, your everyday actions")
                            color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                        }
                        Row {
                            spacing: Theme.gapS
                            Badge {
                                text: page.status.connected ? qsTr("Connected") : qsTr("Not connected")
                                dot: true; accent: page.status.connected
                            }
                            Badge {
                                text: page.pages.length ? qsTr("Page %1 of %2").arg(page.currentPage + 1).arg(page.pages.length) : qsTr("No pages yet")
                            }
                        }
                    }
                    Image {
                        Layout.preferredWidth: 240; Layout.fillHeight: true
                        source: assetsDir + "/devices/mx_keypad.png"
                        fillMode: Image.PreserveAspectFit; smooth: true
                        Accessible.role: Accessible.Graphic
                        Accessible.name: qsTr("MX Keypad with nine display keys and two page buttons")
                    }
                }
            }

            EmptyState {
                visible: !page.status.connected
                Layout.fillWidth: true; Layout.preferredHeight: 145
                title: qsTr("Connect your MX Keypad to use these keys.")
            }

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: gridColumn.implicitHeight + Theme.padCard * 2
                Column {
                    id: gridColumn
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: qsTr("Key plates")
                        subtitle: page.pages.length ? page.pages[page.currentPage].name : qsTr("Add a page or choose a template to get started")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/keypad"
                    }
                    Divider {}
                    RowLayout {
                        width: parent.width; spacing: Theme.gapL
                        Rectangle {
                            id: body
                            Layout.preferredWidth: Math.min(420, gridColumn.width * 0.53)
                            Layout.preferredHeight: width * 1.13
                            radius: 26; color: "#181b20"
                            border.width: 1; border.color: Theme.borderStrong
                            Item {
                                id: lcd
                                anchors.top: parent.top; anchors.topMargin: 18
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: parent.width - 30; height: width
                                readonly property real unit: width / 480
                                Repeater {
                                    model: 9
                                    Rectangle {
                                        id: keyTile
                                        required property int index
                                        readonly property int keyNumber: index + 1
                                        readonly property var binding: (page.bump, Backend.keypadKey(page.currentPage, keyNumber))
                                        x: (23 + index % 3 * 158) * lcd.unit
                                        y: (6 + Math.floor(index / 3) * 158) * lcd.unit
                                        width: 118 * lcd.unit; height: width
                                        radius: 8; color: "#070b14"
                                        border.width: 2
                                        border.color: page.litKey === keyNumber ? "#efe6cf" : (page.selectedKey === keyNumber ? Theme.accent : Theme.border)
                                        activeFocusOnTab: true
                                        Accessible.role: Accessible.Button
                                        Accessible.name: qsTr("Key %1: %2").arg(keyNumber).arg(binding.label || qsTr("Unassigned"))
                                        Accessible.onPressAction: page.editKey(keyNumber)
                                        Keys.onSpacePressed: page.editKey(keyNumber)
                                        Keys.onReturnPressed: page.editKey(keyNumber)
                                        FocusHalo { active: keyTile.activeFocus; radius: 8 }
                                        Image {
                                            anchors.fill: parent; anchors.margins: 3
                                            source: (Backend.keypadRevision, page.bump, Backend.keypadPlate(page.currentPage, keyTile.keyNumber))
                                            cache: false; smooth: true
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            visible: !keyTile.binding.label && !keyTile.binding.icon
                                            text: String(keyTile.keyNumber)
                                            color: Theme.textMuted; font.family: Theme.fontMono; font.pixelSize: Theme.fsH3
                                        }
                                        Rectangle {
                                            anchors.fill: parent; radius: 8
                                            color: Theme.accent; opacity: page.litKey === keyTile.keyNumber ? 0.35 : 0
                                        }
                                        MouseArea {
                                            anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                            onClicked: page.editKey(keyTile.keyNumber)
                                        }
                                    }
                                }
                            }
                            Row {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom; anchors.bottomMargin: 15
                                spacing: 16
                                IconButton {
                                    diameter: 38; icon: "go-previous-symbolic"; tint: Theme.textBody
                                    tip: qsTr("Previous keypad page"); enabled: page.pages.length > 1
                                    onClicked: page.step(-1)
                                }
                                IconButton {
                                    diameter: 38; icon: "go-next-symbolic"; tint: Theme.textBody
                                    tip: qsTr("Next keypad page"); enabled: page.pages.length > 1
                                    onClicked: page.step(1)
                                }
                            }
                        }
                        KeypadKeyEditor {
                            id: editor
                            Layout.fillWidth: true; Layout.alignment: Qt.AlignTop
                            enabled: page.pages.length > 0
                            pageIndex: page.currentPage; keyNumber: page.selectedKey
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: pageColumn.implicitHeight + Theme.padCard * 2
                Column {
                    id: pageColumn
                    anchors.fill: parent; anchors.margins: Theme.padCard; spacing: Theme.gapS
                    CardHeader {
                        width: parent.width; title: qsTr("Pages")
                        subtitle: qsTr("Page buttons wrap from the last page to the first")
                        PrimaryButton {
                            text: qsTr("Add page"); ghost: true; enabled: page.pages.length < 255
                            onClicked: Backend.addKeypadPage(qsTr("New page"))
                        }
                    }
                    Divider {}
                    Repeater {
                        model: page.pages
                        RowLayout {
                            required property int index
                            required property var modelData
                            width: pageColumn.width; spacing: Theme.gapS
                            InputField {
                                Layout.fillWidth: true
                                accessibleName: qsTr("Page %1 name").arg(index + 1)
                                text: modelData.name
                                onEditingFinished: Backend.renameKeypadPage(index, text)
                            }
                            PrimaryButton {
                                text: index === page.currentPage ? qsTr("Active") : qsTr("Show")
                                ghost: index !== page.currentPage
                                onClicked: Backend.setKeypadPage(index)
                            }
                            IconButton {
                                icon: "go-previous-symbolic"; rotation: 90
                                tip: qsTr("Move page up"); enabled: index > 0
                                onClicked: Backend.moveKeypadPage(index, index - 1)
                            }
                            IconButton {
                                icon: "go-next-symbolic"; rotation: 90
                                tip: qsTr("Move page down"); enabled: index + 1 < page.pages.length
                                onClicked: Backend.moveKeypadPage(index, index + 1)
                            }
                            IconButton {
                                icon: "edit-delete-symbolic"; tip: qsTr("Delete page")
                                onClicked: {
                                    var snapshot = Backend.deleteKeypadPage(index)
                                    if (snapshot) page.Window.window.undoToast(qsTr("Page deleted"), function() { Backend.restoreKeypadPages(snapshot) })
                                }
                            }
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: templateColumn.implicitHeight + Theme.padCard * 2
                Column {
                    id: templateColumn
                    anchors.fill: parent; anchors.margins: Theme.padCard; spacing: Theme.gapS
                    CardHeader {
                        width: parent.width; title: qsTr("Templates")
                        subtitle: qsTr("Add a ready page. Missing apps leave keys for you to assign.")
                    }
                    Divider {}
                    Repeater {
                        model: Backend.keypadTemplates()
                        SettingRow {
                            required property var modelData
                            label: modelData.name; desc: modelData.description
                            PrimaryButton {
                                text: qsTr("Add template"); ghost: true; enabled: page.pages.length < 255
                                onClicked: { Backend.applyKeypadTemplate(modelData.id); editor.load() }
                            }
                        }
                    }
                }
            }
            Item { Layout.preferredHeight: Theme.gap; Layout.fillWidth: true }
        }
    }
}
