import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as QQC
import QtQuick.Dialogs
import "../components"

// App-wide preferences: appearance, language/desktop, startup, about and reset.
Item {
    id: page
    // Actions Ring geometry (radial.outer_radius / inner_radius, null = theme default)
    property var geo: Backend.ringGeometry()
    function reloadGeo() { geo = Backend.ringGeometry() }
    anchors.fill: parent

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            // ---- Appearance ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: appearCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: appearCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Appearance"; subtitle: "Theme and menu styling"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/preferences-desktop-theme-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Theme"
                        desc: "Currently " + Theme.name
                        Column {
                            spacing: Theme.gapS
                            Row {
                                id: swatchRow
                                spacing: 6
                                Repeater {
                                    model: Theme.themeList()
                                    Rectangle {
                                        required property var modelData
                                        required property int index
                                        width: 18; height: 18; radius: 9
                                        color: modelData.accent
                                        border.width: Theme.index === index ? 2 : 1
                                        border.color: Theme.index === index ? Theme.textPrimary
                                                      : (swMa.containsMouse ? "#AAFFFFFF" : Theme.border)
                                        Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                                        MouseArea {
                                            id: swMa; anchors.fill: parent; hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: Theme.setIndex(index)
                                        }
                                    }
                                }
                            }
                            Text {
                                anchors.right: swatchRow.right
                                text: "More in the Themes tab"
                                color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Menu background blur"
                        desc: "Frost the wallpaper behind the radial menu"
                        Toggle {
                            checked: Backend.get("blur_enabled", true)
                            onToggled: (v) => Backend.set("blur_enabled", v)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Ring size"
                        desc: "Outer radius of the Actions Ring. Icons, submenus and the centre label scale with it"
                        Row {
                            spacing: Theme.gapS
                            Slider {
                                id: ringOuter
                                anchors.verticalCenter: parent.verticalCenter
                                width: 200; showValue: true; suffix: " px"
                                from: page.geo.outerMin; to: page.geo.outerMax
                                value: page.geo.outer
                                onCommitted: (v) => { Backend.setRingOuter(Math.round(v)); page.reloadGeo() }
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Center zone"
                        desc: "Dead zone in the middle where nothing is selected"
                        Row {
                            spacing: Theme.gapS
                            Slider {
                                id: ringInner
                                anchors.verticalCenter: parent.verticalCenter
                                width: 200; showValue: true; suffix: " px"
                                from: page.geo.innerMin; to: page.geo.outer - page.geo.margin
                                value: page.geo.inner
                                onCommitted: (v) => { Backend.setRingInner(Math.round(v)); page.reloadGeo() }
                            }
                            PrimaryButton {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "Default size"; ghost: true
                                enabled: page.geo.custom
                                onClicked: { Backend.resetRingGeometry(); page.reloadGeo() }
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Icon style"
                        desc: "Line: the 0.4.5 family. Classic: the glossy 0.4.4 buttons. Mono: flat single-colour glyphs"
                        SegmentedControl {
                            width: 270
                            model: [{ id: "line", name: "Line" }, { id: "classic", name: "Classic" }, { id: "mono", name: "Mono" }]
                            currentId: Theme.iconStyle
                            onActivated: (id) => {
                                Theme.setIconStyle(id)
                                // The overlay reads radial.icon_style on every open;
                                // monochrome_icons stays in step for older readers.
                                Backend.setLocal("radial.icon_style", id)
                                Backend.setLocal("radial.monochrome_icons", id === "mono")
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Reduce transparency"
                        desc: "Solid cards instead of frosted glass. Easier to read, lighter on the GPU."
                        Toggle {
                            checked: Theme.reduceTransparency
                            onToggled: (v) => Theme.setReduceTransparency(v)
                        }
                    }
                }
            }

            // ---- Radial menu ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: radCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: radCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Radial menu"; subtitle: "How the on-screen wheel looks"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-grid-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Simplified wheel"
                        desc: "Hide the ring and show only the action icons"
                        Toggle {
                            checked: Backend.get("radial.minimal_mode", false)
                            onToggled: (v) => Backend.setLocal("radial.minimal_mode", v)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Click outside to close"
                        desc: "Dismiss the open menu by clicking anywhere outside the ring"
                        Toggle {
                            checked: Backend.get("radial.click_outside_closes", true)
                            onToggled: (v) => Backend.setLocal("radial.click_outside_closes", v)
                        }
                    }
                }
            }

            // ---- Language & desktop ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: langCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: langCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Language & desktop"; subtitle: "Interface language and desktop integration"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/preferences-desktop-locale-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Language"
                        ComboBox {
                            width: 200
                            model: Backend.languages()
                            currentId: Backend.get("language", "en")
                            onActivated2: (id) => Backend.setLocal("language", id)
                        }
                    }
                    Row {
                        leftPadding: 2; spacing: Theme.gapS
                        Badge { text: "Restart to apply"; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "A new language is picked up on the next start."
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Desktop environment"
                        desc: "Used to pick sensible default actions"
                        ComboBox {
                            width: 200
                            model: Backend.desktopEnvs()
                            currentId: Backend.get("desktop_environment", "auto")
                            onActivated2: (id) => Backend.setLocal("desktop_environment", id)
                        }
                    }
                    Item {
                        width: parent.width
                        height: applyBtn.implicitHeight + Theme.gapS
                        PrimaryButton {
                            id: applyBtn
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            text: "Apply desktop defaults"
                            ghost: true
                            onClicked: Backend.applyDeDefaults(Backend.get("desktop_environment", "auto"))
                        }
                    }
                }
            }

            // ---- Startup ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: startCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: startCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Startup"; subtitle: "Launch behaviour and tray presence"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/system-run-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Start at login"
                        desc: "Run JuhRadial MX automatically when you log in"
                        Toggle {
                            checked: Backend.get("app.start_at_login", false)
                            onToggled: (v) => Backend.setStartAtLogin(v)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Show tray icon"
                        Toggle {
                            checked: Backend.get("app.show_tray_icon", true)
                            onToggled: (v) => Backend.setLocal("app.show_tray_icon", v)
                        }
                    }
                }
            }

            // ---- Backup ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: backupCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: backupCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Backup"; subtitle: "Keep a copy of your setup or move it to another machine"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/document-save-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Export settings"
                        desc: "One zip file with your configuration, profiles, macros, slice icons and themes. Flow pairing keys stay on this machine"
                        PrimaryButton {
                            text: "Export…"; ghost: true
                            onClicked: { exportDialog.selectedFile = Backend.suggestedBackupUrl(); exportDialog.open() }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Import settings"
                        desc: "Restore a backup made here or on another machine. The current config.json and profiles.json are kept as .bak"
                        PrimaryButton {
                            text: "Import…"; ghost: true
                            onClicked: importDialog.open()
                        }
                    }
                }
            }

            // ---- About & reset ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: aboutCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: aboutCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "About"; subtitle: "Version and reset"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/help-about-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Flow {
                        width: parent.width
                        spacing: Theme.gapL
                        Repeater {
                            model: [
                                { l: "App", v: Backend.appVersion },
                                { l: "Daemon", v: Backend.daemonVersion },
                                { l: "Device mode", v: Backend.deviceMode }
                            ]
                            Row {
                                required property var modelData
                                spacing: 6
                                Text {
                                    text: modelData.l; color: Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: modelData.v; color: Theme.textBody
                                    font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }
                    }
                    Row {
                        spacing: 6
                        Text {
                            text: "JuhRadial MX by JuhLabs."
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: "Free and open source. If it earns its keep, you can support it."
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Item {
                        width: parent.width
                        height: resetBtn.implicitHeight + Theme.gapS
                        PrimaryButton {
                            anchors.left: parent.left
                            anchors.bottom: parent.bottom
                            text: "Close window"
                            ghost: true
                            onClicked: Backend.quitApp()
                        }
                        PrimaryButton {
                            id: resetBtn
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            text: "Restore defaults"
                            danger: true
                            onClicked: confirmPopup.open()
                        }
                    }
                }
            }
            Item { Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    // ---- Backup file dialogs (native where the platform offers one) ----
    FileDialog {
        id: exportDialog
        title: "Export JuhRadial MX settings"
        fileMode: FileDialog.SaveFile
        nameFilters: ["Zip archive (*.zip)"]
        defaultSuffix: "zip"
        onAccepted: Backend.exportBackup(selectedFile.toString())
    }
    FileDialog {
        id: importDialog
        title: "Import JuhRadial MX settings"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Zip archive (*.zip)", "All files (*)"]
        onAccepted: Backend.importBackup(selectedFile.toString())
    }

    // ---- Restore-defaults confirmation (dark glass) ----
    QQC.Popup {
        id: confirmPopup
        width: 360
        padding: Theme.pad
        modal: true
        dim: true
        anchors.centerIn: parent
        closePolicy: QQC.Popup.CloseOnEscape | QQC.Popup.CloseOnPressOutside

        background: Rectangle {
            color: Theme.surfaceGlassHi
            radius: Theme.radiusCard
            border.width: 1
            border.color: Theme.borderStrong
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                anchors.leftMargin: Theme.radiusCard; anchors.rightMargin: Theme.radiusCard; anchors.topMargin: 1
                height: 1; color: Theme.borderLit
            }
        }

        contentItem: Column {
            spacing: Theme.gapL
            Text {
                width: parent.width
                text: "Restore defaults?"
                color: Theme.textPrimary
                font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "Restore all settings to defaults? This cannot be undone."
                color: Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                wrapMode: Text.WordWrap
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.gapS
                PrimaryButton {
                    text: "Cancel"
                    ghost: true
                    onClicked: confirmPopup.close()
                }
                PrimaryButton {
                    text: "Restore"
                    danger: true
                    onClicked: { Backend.restoreDefaults(); confirmPopup.close(); Backend.notify("Defaults restored", "success") }
                }
            }
        }
    }
}
