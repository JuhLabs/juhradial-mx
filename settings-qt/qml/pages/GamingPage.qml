import QtQuick
import QtQuick.Layouts
import "../components"

// Gaming: the switch shows what the daemon does (a button, the tray or
// automatic mode can flip it too); automatic mode for Feral GameMode or
// chosen apps; 1 to 5 DPI presets with the active one applied at once; and
// what the ring button, the radial menu and the wheel do in games.
Item {
    id: page
    anchors.fill: parent

    property int bump: 0
    Connections {
        target: Backend
        function onConfigChanged() { page.bump++ }
    }

    function cfg(path, def) { page.bump; return Backend.get(path, def) }
    readonly property var presets: (page.bump, Backend.gamingPresets())
    readonly property int active: Math.min(cfg("gaming.active_dpi_profile", 1), presets.length - 1)
    readonly property var st: Backend.gamingStatus
    readonly property bool ringShown: !cfg("gaming.suppress_overlay", true)
    readonly property string status: {
        if (!Backend.gamingMode) return qsTr("Off")
        var p = page.presets[page.active]
        var parts = [page.st.auto ? qsTr("On automatically") : qsTr("On"),
                     qsTr("%1 DPI").arg(Backend.dpi)]
        if (p) parts.push(qsTr("Preset %1").arg(p.name))
        parts.push(page.ringShown ? qsTr("Ring shown") : qsTr("Ring hidden"))
        return parts.join("  ·  ")
    }

    component Divider: Rectangle { width: parent ? parent.width : 400; height: 1; color: Theme.border }
    component AppChips: Flow {
        id: chips
        property var apps: []
        signal removed(string app)
        width: parent ? parent.width : 400
        spacing: 6
        Repeater {
            model: chips.apps
            Rectangle {
                id: chip
                required property string modelData
                width: chipTxt.implicitWidth + 44; height: 30; radius: 8
                color: "#12FFFFFF"; border.color: Theme.border; border.width: 1
                Text {
                    id: chipTxt
                    anchors.left: parent.left; anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: chip.modelData
                    color: Theme.textBody
                    font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                }
                IconButton {
                    anchors.right: parent.right; anchors.rightMargin: 2
                    anchors.verticalCenter: parent.verticalCenter
                    diameter: 26
                    icon: "window-close-symbolic"
                    tip: qsTr("Remove %1").arg(chip.modelData)
                    onClicked: chips.removed(chip.modelData)
                }
            }
        }
    }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            // ---- Gaming mode ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: masterCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: masterCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Gaming mode")
                        subtitle: page.status
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/gaming"
                        Toggle {
                            checked: Backend.gamingMode
                            accessibleName: qsTr("Gaming mode")
                            onToggled: (v) => Backend.setGamingMode(v)
                        }
                    }
                    Divider { visible: !Backend.gamingMode }
                    RowLayout {
                        width: parent.width
                        visible: !Backend.gamingMode
                        spacing: Theme.pad
                        SpotImage { name: "spot_gaming"; size: 84; Layout.alignment: Qt.AlignVCenter }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 4
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("A DPI preset for your game, the radial menu out of the way, and a gaming job for the ring button.")
                                color: Theme.textBody
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("Turn it on here, from the tray menu, with a button set to Gaming mode, or automatically below.")
                                color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }

            // ---- Automatic ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: autoCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: autoCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Turn on automatically")
                        subtitle: qsTr("On while a game runs, off again when it ends. A switch you flipped yourself stays as you left it")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/media-playback-start-symbolic"
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("When Feral GameMode runs a game")
                        desc: page.st.gamemodeInstalled
                              ? qsTr("Games started with gamemoderun, or with GameMode switched on in Steam, Lutris or Heroic")
                              : qsTr("Feral GameMode is not installed")
                        Toggle {
                            enabled: page.st.gamemodeInstalled || page.cfg("gaming.auto_gamemode", false)
                            checked: page.cfg("gaming.auto_gamemode", false)
                            onToggled: (v) => Backend.set("gaming.auto_gamemode", v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("When these apps are in front")
                        desc: qsTr("For games GameMode does not see, and apps that want the gaming presets")
                        PrimaryButton {
                            text: qsTr("Add app"); ghost: true
                            onClicked: autoPicker.open()
                        }
                    }
                    AppChips {
                        apps: (page.bump, Backend.gamingAutoApps())
                        onRemoved: (app) => Backend.removeGamingAutoApp(app)
                    }
                }
            }

            // ---- DPI presets ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: dpiCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: dpiCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("DPI presets")
                        subtitle: qsTr("The active preset applies while gaming mode is on. A button set to DPI cycle steps through them")
                        mousePart: "sensor"
                        PrimaryButton {
                            text: qsTr("Add preset"); ghost: true
                            enabled: page.presets.length < 5
                            onClicked: Backend.addGamingPreset()
                        }
                    }
                    Divider {}
                    Repeater {
                        model: page.presets
                        Rectangle {
                            id: row
                            required property var modelData
                            required property int index
                            readonly property bool sel: page.active === index
                            width: dpiCol.width
                            height: 60
                            radius: Theme.radiusCtl
                            color: sel ? Theme.accentSubtle : (rowHov.hovered ? "#0CFFFFFF" : "transparent")
                            border.width: 1
                            border.color: sel ? Theme.accentFaint : "transparent"
                            Behavior on color { ColorAnimation { duration: Theme.dShort } }
                            activeFocusOnTab: true
                            Accessible.role: Accessible.RadioButton
                            Accessible.name: qsTr("%1, %2 DPI").arg(modelData.name).arg(modelData.dpi)
                            Accessible.checkable: true
                            Accessible.checked: sel
                            Accessible.onPressAction: Backend.setActiveGamingPreset(index)
                            Keys.onSpacePressed: Backend.setActiveGamingPreset(index)
                            Keys.onReturnPressed: Backend.setActiveGamingPreset(index)
                            FocusHalo { active: row.activeFocus; radius: Theme.radiusCtl }
                            HoverHandler { id: rowHov }
                            // Under the controls: a click on the row itself picks it,
                            // dragging its slider or typing its name does not.
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: Backend.setActiveGamingPreset(row.index)
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12; anchors.rightMargin: 6
                                spacing: Theme.gapS
                                // radio
                                Rectangle {
                                    Layout.preferredWidth: 18; Layout.preferredHeight: 18
                                    radius: 9; color: "transparent"
                                    border.width: 2; border.color: row.sel ? Theme.accent : Theme.borderStrong
                                    Rectangle {
                                        anchors.centerIn: parent; width: 8; height: 8; radius: 4
                                        visible: row.sel; color: Theme.accent
                                    }
                                }
                                // colour: click for the next one
                                Rectangle {
                                    Layout.preferredWidth: 16; Layout.preferredHeight: 16
                                    radius: 8; color: row.modelData.hex
                                    border.width: 1; border.color: Theme.border
                                    TapHandler {
                                        onTapped: {
                                            var cs = ["blue", "green", "red", "yellow", "mauve", "peach", "teal", "pink"]
                                            var i = cs.indexOf(row.modelData.color)
                                            Backend.setGamingPreset(row.index, "color", cs[(i + 1) % cs.length])
                                        }
                                    }
                                }
                                InputField {
                                    Layout.preferredWidth: 150
                                    text: row.modelData.name
                                    accessibleName: qsTr("Preset name")
                                    field.maximumLength: 12
                                    error: text.trim() === "" ? qsTr("Give it a name") : ""
                                    onEditingFinished: if (text.trim() !== "") Backend.setGamingPreset(row.index, "name", text)
                                }
                                DpiControl {
                                    Layout.fillWidth: true
                                    Layout.alignment: Qt.AlignVCenter
                                    value: row.modelData.dpi
                                    accessibleName: qsTr("%1 DPI").arg(row.modelData.name)
                                    onCommitted: (v) => Backend.setGamingPreset(row.index, "dpi", v)
                                }
                                IconButton {
                                    icon: "go-next-symbolic"; diameter: 30; rotation: -90
                                    enabled: row.index > 0
                                    tip: qsTr("Move up")
                                    onClicked: Backend.moveGamingPreset(row.index, -1)
                                }
                                IconButton {
                                    icon: "go-next-symbolic"; diameter: 30; rotation: 90
                                    enabled: row.index < page.presets.length - 1
                                    tip: qsTr("Move down")
                                    onClicked: Backend.moveGamingPreset(row.index, 1)
                                }
                                IconButton {
                                    icon: "user-trash-symbolic"; diameter: 30
                                    enabled: page.presets.length > 1
                                    tip: qsTr("Remove %1").arg(row.modelData.name)
                                    onClicked: Backend.removeGamingPreset(row.index)
                                }
                            }
                        }
                    }
                }
            }

            // ---- In games ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: gameCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: gameCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("In games")
                        subtitle: qsTr("These apply while gaming mode is on")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-grid-symbolic"
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Show the radial menu")
                        desc: page.ringShown ? qsTr("The ring still opens in games") : qsTr("The ring stays hidden so a stray press never covers the game")
                        Toggle {
                            checked: page.ringShown
                            onToggled: (v) => Backend.set("gaming.suppress_overlay", !v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Ring button")
                        desc: {
                            var r = page.cfg("gaming.ring_button", "none")
                            if (r === "dpi_shift") return qsTr("Hold for the precision DPI, let go to go back")
                            if (r === "dpi_cycle") return qsTr("Each press steps to the next DPI preset")
                            return page.ringShown ? qsTr("Opens the radial menu as usual") : qsTr("Does nothing while the ring is hidden")
                        }
                        SegmentedControl {
                            width: 340
                            accessibleName: qsTr("Ring button")
                            model: [{ id: "none", name: qsTr("Usual") }, { id: "dpi_shift", name: qsTr("Precision DPI") },
                                    { id: "dpi_cycle", name: qsTr("Next preset") }]
                            currentId: page.cfg("gaming.ring_button", "none")
                            onActivated: (id) => Backend.set("gaming.ring_button", id)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Scroll wheel")
                        desc: qsTr("Hold the wheel in one mode while playing; your usual mode comes back after")
                        SegmentedControl {
                            width: 300
                            accessibleName: qsTr("Scroll wheel in games")
                            model: [{ id: "keep", name: qsTr("As is") }, { id: "ratchet", name: qsTr("Ratchet") },
                                    { id: "freespin", name: qsTr("Free-spin") }]
                            currentId: page.cfg("gaming.wheel", "keep")
                            onActivated: (id) => Backend.set("gaming.wheel", id)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Pulse on preset change")
                        desc: qsTr("One pulse for the first preset, two for the second, and so on")
                        Toggle {
                            enabled: !Backend.primed || Backend.hapticsSupported
                            checked: page.cfg("gaming.dpi_pulse", true)
                            onToggled: (v) => Backend.set("gaming.dpi_pulse", v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Game macros")
                        desc: qsTr("Bind macros to buttons on the Macros tab; they work in games too")
                        PrimaryButton { text: qsTr("Macros"); ghost: true; onClicked: Backend.goTo("macros") }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    AppPicker {
        id: autoPicker
        title: qsTr("Gaming mode while this app is in front")
        onPicked: (app) => Backend.addGamingAutoApp(Backend.appClassFor(app.id))
    }
}
