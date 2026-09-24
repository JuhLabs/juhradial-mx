import QtCore
import QtQuick
import QtQuick.Dialogs
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
    // A profile's or app's icon: its own art or app icon, else an accent glyph.
    component RowIcon: Rectangle {
        property string icon: ""
        property string kind: "glyph"
        width: 36; height: 36; radius: 9
        color: kind === "glyph" ? Theme.accentFaint : "#0CFFFFFF"
        border.width: 1; border.color: Theme.border
        Image {
            anchors.fill: parent; anchors.margins: parent.kind === "app" ? 5 : 2
            visible: parent.kind !== "glyph"
            source: parent.kind === "file" ? "file://" + parent.icon
                  : (parent.kind === "app" ? "image://icon/raw/" + parent.icon : "")
            sourceSize.width: 72; sourceSize.height: 72
            fillMode: Image.PreserveAspectFit; smooth: true; asynchronous: true
        }
        ActionIcon {
            anchors.centerIn: parent
            visible: parent.kind === "glyph"
            iconName: parent.kind === "glyph" ? parent.icon : ""
            tint: Theme.accent; px: 20
        }
    }

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
                                        // An animated picture plays here as it does on the key.
                                        AnimatedImage {
                                            readonly property string pic: keyTile.binding.plate || ""
                                            anchors.fill: parent; anchors.margins: 3
                                            visible: /\.(gif|webp)$/i.test(pic)
                                            source: visible ? "file://" + pic : ""
                                            fillMode: Image.PreserveAspectCrop; smooth: true
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
                        subtitle: qsTr("Grouped by the apps that bring them up. Page buttons cycle within the group in front.")
                        Row {
                            spacing: Theme.gapS
                            PrimaryButton {
                                text: qsTr("New app profile"); ghost: true; enabled: page.pages.length < 255
                                onClicked: profileAppPicker.open()
                            }
                            PrimaryButton {
                                text: qsTr("Add page"); ghost: true; enabled: page.pages.length < 255
                                onClicked: Backend.addKeypadPage(qsTr("New page"))
                            }
                        }
                    }
                    SettingRow {
                        width: parent.width
                        label: qsTr("Key brightness")
                        desc: qsTr("The keypad keeps it after it wakes")
                        Slider {
                            width: 190; showValue: true; suffix: " %"; stepSize: 5
                            from: 5; to: 100
                            value: Backend.get("keypad.brightness", 100) || 100
                            onCommitted: (v) => Backend.set("keypad.brightness", Math.round(v))
                        }
                    }
                    Repeater {
                        model: (Backend.keypadRevision, page.bump, Backend.keypadGroups())
                        Column {
                            id: group
                            required property var modelData
                            width: pageColumn.width; spacing: Theme.gapS
                            Divider {}
                            RowLayout {
                                width: parent.width; spacing: Theme.gap
                                RowIcon { icon: group.modelData.icon; kind: group.modelData.iconKind }
                                Column {
                                    Layout.fillWidth: true; spacing: 2
                                    Text {
                                        width: parent.width; elide: Text.ElideRight
                                        text: group.modelData.name; color: Theme.textPrimary
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                                    }
                                    Text {
                                        width: parent.width; elide: Text.ElideRight
                                        text: group.modelData.desc; color: Theme.textMuted
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                    }
                                }
                                PrimaryButton {
                                    text: qsTr("Add page"); ghost: true; enabled: page.pages.length < 255
                                    onClicked: Backend.addKeypadGroupPage(qsTr("New page"), group.modelData.apps, group.modelData.profile)
                                }
                                IconButton {
                                    icon: "document-export"; tip: qsTr("Save these pages as a pack to share")
                                    onClicked: {
                                        exportDialog.indexes = group.modelData.pages
                                        exportDialog.selectedFile = exportDialog.currentFolder + "/"
                                            + (group.modelData.name.replace(/[^A-Za-z0-9 _-]/g, "").trim() || "keypad") + ".zip"
                                        exportDialog.open()
                                    }
                                }
                            }
                            Repeater {
                                model: group.modelData.pages
                                RowLayout {
                                    id: pageRow
                                    required property int modelData
                                    readonly property int index: modelData
                                    readonly property var pg: page.pages[modelData] || ({ name: "", apps: [] })
                                    // Moves stay inside the group: swap with the neighbour page it lists.
                                    readonly property var siblings: group.modelData.pages
                                    readonly property int pos: siblings.indexOf(modelData)
                                    width: pageColumn.width; spacing: Theme.gapS
                                    InputField {
                                        Layout.fillWidth: true; Layout.leftMargin: 48
                                        accessibleName: qsTr("Page %1 name").arg(pageRow.index + 1)
                                        text: pageRow.pg.name
                                        onEditingFinished: Backend.renameKeypadPage(pageRow.index, text)
                                    }
                                    PrimaryButton {
                                        text: pageRow.index === page.currentPage ? qsTr("Active") : qsTr("Show")
                                        ghost: pageRow.index !== page.currentPage
                                        onClicked: Backend.setKeypadPage(pageRow.index)
                                    }
                                    // Which apps bring this page up (none = the general pages).
                                    PrimaryButton {
                                        ghost: true
                                        readonly property var apps: pageRow.pg.apps || []
                                        text: apps.length ? qsTr("For %1").arg(apps.length > 1 ? apps[0] + " +" + (apps.length - 1) : apps[0]) : qsTr("All apps")
                                        onClicked: { pageAppPicker.pageIndex = pageRow.index; pageAppPicker.open() }
                                    }
                                    IconButton {
                                        visible: (pageRow.pg.apps || []).length > 0
                                        icon: "edit-clear-symbolic"; tip: qsTr("Show this page for all apps")
                                        onClicked: Backend.setKeypadPageApps(pageRow.index, [])
                                    }
                                    IconButton {
                                        icon: "go-previous-symbolic"; rotation: 90
                                        tip: qsTr("Move page up"); enabled: pageRow.pos > 0
                                        onClicked: Backend.moveKeypadPage(pageRow.index, pageRow.siblings[pageRow.pos - 1])
                                    }
                                    IconButton {
                                        icon: "go-next-symbolic"; rotation: 90
                                        tip: qsTr("Move page down"); enabled: pageRow.pos + 1 < pageRow.siblings.length
                                        onClicked: Backend.moveKeypadPage(pageRow.index, pageRow.siblings[pageRow.pos + 1])
                                    }
                                    IconButton {
                                        icon: "edit-delete-symbolic"; tip: qsTr("Delete page")
                                        onClicked: {
                                            var snapshot = Backend.deleteKeypadPage(pageRow.index)
                                            if (snapshot) page.Window.window.undoToast(qsTr("Page deleted"), function() { Backend.restoreKeypadPages(snapshot) })
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            GlassCard {
                id: profileCard
                Layout.fillWidth: true
                Layout.preferredHeight: profileColumn.implicitHeight + Theme.padCard * 2
                property bool showAll: false
                // Re-read after every keypad save (added marks) and on open.
                readonly property var profiles: (Backend.keypadRevision, Backend.keypadProfiles())
                Column {
                    id: profileColumn
                    anchors.fill: parent; anchors.margins: Theme.padCard; spacing: Theme.gapS
                    CardHeader {
                        width: parent.width; title: qsTr("App profiles")
                        subtitle: qsTr("Pages that come up by themselves while an app is in front. Your most used apps first.")
                    }
                    Divider {}
                    Repeater {
                        model: profileCard.profiles.filter(function (p) { return profileCard.showAll || p.installed })
                        Row {
                            id: profileRow
                            required property var modelData
                            width: profileColumn.width; spacing: Theme.gap
                            RowIcon {
                                anchors.verticalCenter: parent.verticalCenter
                                icon: profileRow.modelData.icon; kind: profileRow.modelData.iconKind
                            }
                            SettingRow {
                                width: parent.width - 36 - Theme.gap
                                label: profileRow.modelData.name
                                desc: profileRow.modelData.description
                                      + (profileRow.modelData.minutes > 0 ? "  " + qsTr("Used %1 min").arg(profileRow.modelData.minutes) : "")
                                      + (profileRow.modelData.requires.length ? "  " + qsTr("Needs %1").arg(profileRow.modelData.requires.join(", ")) : "")
                                PrimaryButton {
                                    text: profileRow.modelData.added ? qsTr("Added") : qsTr("Add profile")
                                    ghost: true
                                    enabled: !profileRow.modelData.added && page.pages.length < 254
                                    onClicked: { Backend.applyKeypadProfile(profileRow.modelData.id); editor.load() }
                                }
                            }
                        }
                    }
                    PrimaryButton {
                        visible: profileCard.profiles.some(function (p) { return !p.installed })
                        text: profileCard.showAll ? qsTr("Only apps on this computer") : qsTr("Show all profiles")
                        ghost: true
                        onClicked: profileCard.showAll = !profileCard.showAll
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
                        PrimaryButton {
                            text: qsTr("Import pack"); ghost: true; enabled: page.pages.length < 255
                            onClicked: packDialog.open()
                        }
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

    AppPicker {
        id: pageAppPicker
        property int pageIndex: -1
        onPicked: (app) => {
            var apps = ((page.pages[pageIndex] || {}).apps || []).slice()
            var cls = Backend.appClassFor(app.id)
            if (cls && apps.indexOf(cls) < 0) apps.push(cls)
            Backend.setKeypadPageApps(pageIndex, apps)
        }
    }
    AppPicker {
        id: profileAppPicker
        title: qsTr("Which app is this profile for?")
        onPicked: (app) => { if (Backend.addKeypadAppProfile(app.id)) editor.load() }
    }
    FileDialog {
        id: exportDialog
        property var indexes: []
        title: qsTr("Save pages as a keypad pack")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "zip"
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        nameFilters: [qsTr("Keypad pack (*.zip)")]
        onAccepted: Backend.exportKeypadPack(selectedFile.toString(), indexes)
    }
    FileDialog {
        id: packDialog
        title: qsTr("Import a keypad pack")
        nameFilters: [qsTr("Keypad pack (*.zip portable.json)")]
        onAccepted: { if (Backend.importKeypadPack(selectedFile.toString())) editor.load() }
    }
}
