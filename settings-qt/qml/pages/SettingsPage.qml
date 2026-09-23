import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as QQC
import "../components"

// App-wide preferences: appearance, language/desktop, startup, about and reset.
Item {
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
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/preferences-desktop-theme-symbolic"
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
                                        border.color: Theme.index === index ? Theme.textPrimary : Theme.border
                                        Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                                        scale: swMa.containsMouse || Theme.index === index ? 1.18 : 1.0
                                        Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }
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
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/view-grid-symbolic"
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
                        label: "Monochrome icons"
                        desc: "Use flat single-colour glyphs instead of the coloured buttons"
                        Toggle {
                            checked: Backend.get("radial.monochrome_icons", false)
                            onToggled: (v) => Backend.setLocal("radial.monochrome_icons", v)
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
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/preferences-desktop-locale-symbolic"
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
                    Text {
                        leftPadding: 2
                        text: "Restart the app to fully apply a new language."
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
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
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/system-run-symbolic"
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
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/help-about-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Column {
                        width: parent.width
                        spacing: 4
                        Text {
                            text: "App version " + Backend.appVersion
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        Text {
                            text: "Daemon version " + Backend.daemonVersion
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        Text {
                            text: "Device mode " + Backend.deviceMode
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        Text {
                            text: "JuhRadial MX by JuhLabs"
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
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
                    onClicked: { Backend.restoreDefaults(); confirmPopup.close() }
                }
            }
        }
    }
}
