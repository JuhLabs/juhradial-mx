import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as QQC
import QtQuick.Dialogs
import QtQuick.Window
import "../components"

// App-wide preferences. "Window" is this app's own look; "Radial menu" is the
// on-screen ring (size, icons, behaviour) with a live preview beside it.
Item {
    id: page
    anchors.fill: parent

    // Actions Ring geometry (radial.outer_radius / inner_radius / icon_scale,
    // null = theme default) and Automatic (radial.auto_fit).
    property var geo: Backend.ringGeometry()
    function reloadGeo() { geo = Backend.ringGeometry() }
    // Live slider values so the preview follows a drag before it is saved.
    property real liveOuter: geo.outer
    property real liveInner: geo.inner
    property real liveIcon: geo.icon
    onGeoChanged: { liveOuter = geo.outer; liveInner = geo.inner; liveIcon = geo.icon }
    readonly property real screenScale: Backend.screenRingScale(Screen.height)

    property var autostart: Backend.autostartStatus()
    property var services: Backend.serviceStatus()
    function refreshStatus() { autostart = Backend.autostartStatus(); services = Backend.serviceStatus() }
    Connections {
        target: Backend
        function onConfigChanged() { page.autostart = Backend.autostartStatus() }
        function onAvailabilityChanged() { page.services = Backend.serviceStatus() }
    }
    readonly property string _accent: Theme.accent.toString().slice(1)
    function _icon(name) { return "image://icon/" + _accent + "/" + Theme.iconStyle + "/" + name }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            // ---- Radial menu: the ring on screen ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: radCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: radCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Radial menu"); subtitle: qsTr("Size, icons and behaviour of the on-screen ring")
                        icon: page._icon("view-grid-symbolic")
                        PrimaryButton {
                            text: qsTr("Show on screen"); ghost: true
                            enabled: Backend.daemonAvailable
                            onClicked: Backend.showMenuPreview()
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Row {
                        width: parent.width
                        spacing: Theme.gapL
                        Column {
                            width: 220; spacing: Theme.gapS
                            RingPreview {
                                width: 220; height: 220
                                outer: page.geo.auto ? page.geo.outerDefault : page.liveOuter
                                inner: page.geo.auto ? page.geo.innerDefault : page.liveInner
                                iconScale: page.geo.auto ? 1.0 : page.liveIcon
                                outerMax: Math.max(220, page.geo.auto ? page.geo.outerDefault : page.liveOuter)
                            }
                            Text {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                                text: qsTr("On this screen: %1 px across").arg(
                                          Math.round((page.geo.auto ? page.geo.outerDefault : page.liveOuter) * 2 * page.screenScale))
                                color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                            }
                        }
                        Column {
                            width: parent.width - 220 - Theme.gapL
                            spacing: 0
                            SettingRow {
                                label: qsTr("Automatic size")
                                desc: page.geo.auto
                                      ? qsTr("Ring, centre zone and icons fit each monitor. Turn off to set them yourself.")
                                      : qsTr("Your own sizes below, scaled to each monitor.")
                                Toggle {
                                    checked: page.geo.auto
                                    onToggled: (v) => { Backend.setAutoFit(v); page.reloadGeo() }
                                }
                            }
                            SettingRow {
                                label: qsTr("Ring size")
                                desc: qsTr("Outer radius. Icons, submenus and the centre label scale with it")
                                enabled: !page.geo.auto
                                opacity: enabled ? 1 : 0.5
                                Slider {
                                    width: 190; showValue: true; suffix: " px"; stepSize: 5
                                    from: page.geo.outerMin; to: page.geo.outerMax
                                    value: page.geo.auto ? page.geo.outerDefault : page.geo.outer
                                    onMoved: (v) => page.liveOuter = v
                                    onCommitted: (v) => { Backend.setRingOuter(Math.round(v)); page.reloadGeo() }
                                }
                            }
                            SettingRow {
                                label: qsTr("Center zone")
                                desc: qsTr("Dead zone in the middle where nothing is selected")
                                enabled: !page.geo.auto
                                opacity: enabled ? 1 : 0.5
                                Slider {
                                    width: 190; showValue: true; suffix: " px"; stepSize: 1
                                    from: page.geo.innerMin
                                    to: (page.geo.auto ? page.geo.outerDefault : page.liveOuter) - page.geo.margin
                                    value: page.geo.auto ? page.geo.innerDefault : page.geo.inner
                                    onMoved: (v) => page.liveInner = v
                                    onCommitted: (v) => { Backend.setRingInner(Math.round(v)); page.reloadGeo() }
                                }
                            }
                            SettingRow {
                                label: qsTr("Icon size")
                                desc: qsTr("Bigger or smaller slice icons, the ring stays the same")
                                enabled: !page.geo.auto
                                opacity: enabled ? 1 : 0.5
                                Slider {
                                    width: 190; showValue: true; suffix: "%"; stepSize: 5
                                    from: Math.round(page.geo.iconMin * 100); to: Math.round(page.geo.iconMax * 100)
                                    value: Math.round((page.geo.auto ? 1.0 : page.geo.icon) * 100)
                                    onMoved: (v) => page.liveIcon = v / 100
                                    onCommitted: (v) => { Backend.setIconScale(v / 100); page.reloadGeo() }
                                }
                            }
                            Item {
                                width: parent.width; height: resetGeo.implicitHeight + Theme.gapS
                                PrimaryButton {
                                    id: resetGeo
                                    anchors.right: parent.right; anchors.bottom: parent.bottom
                                    text: qsTr("Default sizes"); ghost: true
                                    enabled: !page.geo.auto && page.geo.custom
                                    onClicked: { Backend.resetRingGeometry(); page.reloadGeo() }
                                }
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Icon style")
                        desc: qsTr("How the slice icons are drawn, in the ring and in this window")
                        Row {
                            spacing: Theme.gapS
                            Repeater {
                                model: [
                                    { id: "mono", name: qsTr("Mono") },
                                    { id: "mono2", name: qsTr("Mono 2") },
                                    { id: "line", name: qsTr("Line") },
                                    { id: "classic", name: qsTr("Classic") }
                                ]
                                // Picture chip: the Files slice in that style.
                                Item {
                                    id: chip
                                    required property var modelData
                                    readonly property bool sel: Theme.iconStyle === modelData.id
                                    width: 78; height: 74
                                    activeFocusOnTab: true
                                    Accessible.role: Accessible.RadioButton
                                    Accessible.name: modelData.name
                                    Accessible.checked: sel
                                    Keys.onSpacePressed: pick()
                                    Keys.onReturnPressed: pick()
                                    function pick() {
                                        Theme.setIconStyle(modelData.id)
                                        // The overlay reads radial.icon_style on every
                                        // open; monochrome_icons stays in step for older readers.
                                        Backend.setLocal("radial.icon_style", modelData.id)
                                        Backend.setLocal("radial.monochrome_icons", modelData.id.startsWith("mono"))
                                    }
                                    Rectangle {
                                        anchors.fill: parent; radius: Theme.radiusCtl
                                        color: chip.sel ? Theme.accentSubtle : (chipMa.containsMouse ? "#12FFFFFF" : "#0AFFFFFF")
                                        border.width: chip.sel ? 2 : 1
                                        border.color: chip.sel ? Theme.accent : Theme.border
                                    }
                                    FocusHalo { active: chip.activeFocus; radius: Theme.radiusCtl }
                                    Image {
                                        visible: !chip.modelData.id.startsWith("mono")
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        y: 8; width: 36; height: 36
                                        source: chip.modelData.id === "classic"
                                                ? assetsDir + "/slices/classic/btn_files.png"
                                                : assetsDir + "/slices/btn_files.png"
                                        sourceSize.width: 96; sourceSize.height: 96
                                        smooth: true; fillMode: Image.PreserveAspectFit
                                    }
                                    Rectangle {
                                        visible: chip.modelData.id.startsWith("mono")
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        y: 8; width: 36; height: 36; radius: 18
                                        color: "#1B1F28"; border.width: 1.5; border.color: Theme.borderStrong
                                        Image {
                                            anchors.centerIn: parent; width: 18; height: 18
                                            source: "image://icon/" + Theme.textBody.toString().slice(1) + "/" + chip.modelData.id + "/folder-symbolic"
                                            sourceSize.width: 36; sourceSize.height: 36
                                        }
                                    }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                                        width: parent.width - 8
                                        horizontalAlignment: Text.AlignHCenter
                                        // Long translations shrink to the chip instead of spilling out.
                                        fontSizeMode: Text.HorizontalFit; minimumPixelSize: 8
                                        text: chip.modelData.name
                                        color: chip.sel ? Theme.textPrimary : Theme.textBody
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                        font.weight: chip.sel ? Font.DemiBold : Font.Medium
                                    }
                                    MouseArea {
                                        id: chipMa; anchors.fill: parent; hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: chip.pick()
                                    }
                                }
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Simplified wheel")
                        desc: qsTr("Hide the ring and show only the action icons")
                        Toggle {
                            checked: Backend.get("radial.minimal_mode", false)
                            onToggled: (v) => Backend.setLocal("radial.minimal_mode", v)
                        }
                    }
                    SettingRow {
                        label: qsTr("Menu background blur")
                        desc: Backend.isKde ? qsTr("Frost what is behind the ring")
                                            : qsTr("Only KDE Plasma can frost the background behind the ring")
                        enabled: Backend.isKde
                        Toggle {
                            checked: Backend.isKde && Backend.get("blur_enabled", true)
                            onToggled: (v) => Backend.setLocal("blur_enabled", v)
                        }
                    }
                    SettingRow {
                        label: qsTr("Click outside to close")
                        desc: qsTr("After a quick tap the menu stays open; a click anywhere outside the ring closes it")
                        Toggle {
                            checked: Backend.get("radial.click_outside_closes", true)
                            onToggled: (v) => Backend.setLocal("radial.click_outside_closes", v)
                        }
                    }
                }
            }

            // ---- Window: this app's own look ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: winCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: winCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Window"); subtitle: qsTr("How this settings window looks")
                        icon: page._icon("preferences-desktop-theme-symbolic")
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Theme")
                        desc: qsTr("Currently %1").arg(Theme.name)
                        Column {
                            spacing: Theme.gapS
                            Row {
                                id: swatchRow
                                spacing: 6
                                Repeater {
                                    model: Theme.themeList()
                                    Rectangle {
                                        id: sw
                                        required property var modelData
                                        required property int index
                                        width: 28; height: 28; radius: 14
                                        color: modelData.accent
                                        border.width: Theme.index === index ? 2 : 1
                                        border.color: Theme.index === index ? Theme.textPrimary
                                                      : (swMa.containsMouse ? "#AAFFFFFF" : Theme.border)
                                        activeFocusOnTab: true
                                        Accessible.role: Accessible.RadioButton
                                        Accessible.name: modelData.name
                                        Accessible.checked: Theme.index === index
                                        Keys.onSpacePressed: Theme.setIndex(index)
                                        Keys.onReturnPressed: Theme.setIndex(index)
                                        FocusHalo { active: sw.activeFocus; radius: 14; margin: 2 }
                                        Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                                        MouseArea {
                                            id: swMa; anchors.fill: parent; hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: Theme.setIndex(sw.index)
                                        }
                                    }
                                }
                            }
                            Text {
                                anchors.right: swatchRow.right
                                text: qsTr("Wallpapers and wheel skins in Themes")
                                color: themesMa.containsMouse ? Theme.accentHover : Theme.accent
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                font.underline: themesMa.containsMouse
                                Accessible.role: Accessible.Link
                                Accessible.name: text
                                MouseArea {
                                    id: themesMa; anchors.fill: parent; hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Backend.goTo("themes")
                                }
                            }
                        }
                    }
                    SettingRow {
                        label: qsTr("Reduce transparency")
                        desc: qsTr("Solid cards instead of frosted glass. Easier to read, lighter on the GPU.")
                        Toggle {
                            checked: Theme.reduceTransparency
                            onToggled: (v) => Theme.setReduceTransparency(v)
                        }
                    }
                    SettingRow {
                        label: qsTr("Reduce motion")
                        desc: Theme.reduceMotion && !Theme.reduceMotionSetting
                              ? qsTr("Your desktop asks for less animation, so it is already on.")
                              : qsTr("No fades, slides or crossfades in this window.")
                        Toggle {
                            checked: Theme.reduceMotionSetting
                            onToggled: (v) => { Backend.setLocal("app.reduce_motion", v); Theme.setReduceMotion(v) }
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
                        title: qsTr("Language & desktop"); subtitle: qsTr("Interface language and desktop integration")
                        icon: page._icon("preferences-desktop-locale-symbolic")
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Language")
                        desc: qsTr("For this window and the radial menu")
                        ComboBox {
                            width: 220
                            model: Backend.languages()
                            currentId: Backend.get("language", "system")
                            onActivated2: (id) => Backend.setLocal("language", id)
                        }
                    }
                    Row {
                        visible: Backend.languageNeedsRestart
                        leftPadding: 2; spacing: Theme.gapS
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("The new language is used after a restart.")
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        PrimaryButton {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("Restart now"); ghost: true
                            onClicked: Backend.restartApp()
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Desktop environment")
                        desc: qsTr("Picks the screenshot tool, file manager and note app for the default slices")
                        ComboBox {
                            width: 220
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
                            text: qsTr("Apply desktop defaults…")
                            ghost: true
                            onClicked: {
                                dePopup.preview = Backend.deDefaultsPreview(Backend.get("desktop_environment", "auto"))
                                if (dePopup.preview.changes.length === 0)
                                    Backend.notify(qsTr("The slices already match %1").arg(dePopup.preview.desktop), "info")
                                else
                                    dePopup.open()
                            }
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
                        title: qsTr("Startup"); subtitle: qsTr("Launch behaviour, tray and updates")
                        icon: page._icon("system-run-symbolic")
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Start at login")
                        desc: page.autostart.ok ? (page.autostart.text || qsTr("Run JuhRadial MX automatically when you log in"))
                                                : page.autostart.text
                        Row {
                            spacing: Theme.gapS
                            PrimaryButton {
                                visible: !page.autostart.ok
                                anchors.verticalCenter: parent.verticalCenter
                                text: qsTr("Repair"); ghost: true
                                onClicked: { Backend.repairAutostart(); page.refreshStatus() }
                            }
                            Toggle {
                                anchors.verticalCenter: parent.verticalCenter
                                checked: Backend.get("app.start_at_login", true)
                                onToggled: (v) => { Backend.setStartAtLogin(v); page.refreshStatus() }
                            }
                        }
                    }
                    SettingRow {
                        label: qsTr("Show tray icon")
                        desc: qsTr("When hidden, open Settings from your app launcher. Notifications still appear.")
                        Toggle {
                            checked: Backend.get("app.show_tray_icon", true)
                            onToggled: (v) => Backend.setLocal("app.show_tray_icon", v)
                        }
                    }
                    SettingRow {
                        label: qsTr("Check for updates")
                        desc: Backend.updateStatus + " " + qsTr("Asks GitHub once a day; nothing about you is sent.")
                        Row {
                            spacing: Theme.gapS
                            PrimaryButton {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: Backend.updateAvailable
                                text: qsTr("Download %1").arg(Backend.latestVersion)
                                onClicked: Qt.openUrlExternally(Backend.latestReleaseUrl)
                            }
                            PrimaryButton {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: !Backend.updateAvailable
                                text: qsTr("Check now"); ghost: true
                                onClicked: Backend.checkForUpdates(true)
                            }
                            Toggle {
                                anchors.verticalCenter: parent.verticalCenter
                                checked: Backend.get("app.check_updates", true)
                                onToggled: (v) => Backend.setLocal("app.check_updates", v)
                            }
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
                        title: qsTr("Backup"); subtitle: qsTr("Keep a copy of your setup or move it to another machine")
                        icon: page._icon("document-save-symbolic")
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Export settings")
                        desc: qsTr("One zip file with your configuration, profiles, macros, slice icons and themes. Flow pairing keys stay on this machine")
                        PrimaryButton {
                            text: qsTr("Export…"); ghost: true
                            onClicked: { exportDialog.selectedFile = Backend.suggestedBackupUrl(); exportDialog.open() }
                        }
                    }
                    SettingRow {
                        label: qsTr("Import settings")
                        desc: qsTr("See what a backup holds before it replaces anything. The current files are kept, and Undo puts them back")
                        PrimaryButton {
                            text: qsTr("Import…"); ghost: true
                            onClicked: importDialog.open()
                        }
                    }
                }
            }

            // ---- Troubleshooting ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: tsCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: tsCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Troubleshooting"); subtitle: qsTr("When something does not respond")
                        icon: page._icon("dialog-information-symbolic")
                        IconButton {
                            icon: "view-refresh-symbolic"; tint: Theme.textMuted; diameter: 32
                            tip: qsTr("Check again")
                            onClicked: page.refreshStatus()
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Background service")
                        desc: page.services.daemon ? qsTr("Running, version %1").arg(Backend.daemonVersion)
                                                   : qsTr("Not running. Buttons, haptics and the ring do not work without it.")
                        PrimaryButton {
                            text: page.services.daemon ? qsTr("Restart") : qsTr("Start")
                            ghost: page.services.daemon
                            onClicked: Backend.restartDaemon()
                        }
                    }
                    SettingRow {
                        label: qsTr("Radial menu")
                        desc: page.services.overlay ? qsTr("Running")
                                                    : qsTr("Not running. The gesture button has nothing to open.")
                        PrimaryButton {
                            text: page.services.overlay ? qsTr("Restart") : qsTr("Start")
                            ghost: page.services.overlay
                            onClicked: Backend.restartOverlay()
                        }
                    }
                    Flow {
                        width: parent.width
                        spacing: Theme.gapS
                        topPadding: Theme.gapS
                        PrimaryButton { text: qsTr("Open log"); ghost: true; onClicked: Backend.openLog() }
                        PrimaryButton { text: qsTr("Copy system info"); ghost: true; onClicked: Backend.copySystemInfo() }
                        PrimaryButton { text: qsTr("Report a bug"); ghost: true; onClicked: Backend.reportBug() }
                    }
                }
            }

            // ---- Plugins ----
            GlassCard {
                id: pluginCard
                Layout.fillWidth: true
                Layout.preferredHeight: pluginCol.implicitHeight + Theme.padCard * 2
                property var rows: []
                property bool loading: true
                function reload() { loading = true; Backend.requestPlugins() }
                Component.onCompleted: reload()
                Connections {
                    target: Backend
                    function onPluginsReady(list) { pluginCard.rows = list; pluginCard.loading = false }
                }
                Column {
                    id: pluginCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Plugins"); subtitle: qsTr("Extra actions for the ring, from plugin folders")
                        icon: page._icon("folder-symbolic")
                        Row {
                            spacing: Theme.gapS
                            IconButton {
                                icon: "view-refresh-symbolic"; tint: Theme.textMuted; diameter: 32
                                tip: qsTr("Look for new plugins")
                                onClicked: pluginCard.reload()
                            }
                            PrimaryButton { text: qsTr("How to write one"); ghost: true; onClicked: Qt.openUrlExternally(Backend.links.plugins) }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    EmptyState {
                        visible: !pluginCard.loading && pluginCard.rows.length === 0
                        width: parent.width
                        title: qsTr("No plugins yet")
                        body: qsTr("A plugin is a folder with a plugin.json that adds actions: a command, a D-Bus call or a script. They show up in the slice picker without a restart.")
                        PrimaryButton { text: qsTr("Open plugins folder"); onClicked: Backend.openPluginsFolder() }
                    }
                    Repeater {
                        model: pluginCard.rows
                        SettingRow {
                            required property var modelData
                            label: modelData.name + (modelData.version ? "  " + modelData.version : "")
                            desc: modelData.error !== "" ? modelData.folder + ": " + modelData.error
                                                         : (modelData.description || modelData.folder)
                            Badge {
                                text: modelData.error !== "" ? qsTr("Not loaded")
                                      : qsTr("%n action(s)", "", modelData.actions)
                                accent: modelData.error === ""
                                tint: modelData.error !== "" ? Theme.danger : Theme.accent
                            }
                        }
                    }
                    PrimaryButton {
                        visible: pluginCard.rows.length > 0
                        text: qsTr("Open plugins folder"); ghost: true
                        onClicked: Backend.openPluginsFolder()
                    }
                }
            }

            // ---- About ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: aboutCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: aboutCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("About"); subtitle: qsTr("Versions, links and credits")
                        icon: page._icon("help-about-symbolic")
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Flow {
                        width: parent.width
                        spacing: Theme.gapL
                        Repeater {
                            model: [
                                { l: qsTr("App"), v: Backend.appVersion },
                                { l: qsTr("Daemon"), v: Backend.daemonVersion },
                                { l: qsTr("Device mode"), v: Backend.deviceMode }
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
                    Flow {
                        width: parent.width
                        spacing: Theme.gapS
                        Repeater {
                            model: [
                                { t: qsTr("Documentation"), u: Backend.links.docs },
                                { t: qsTr("GitHub"), u: Backend.links.repo },
                                { t: qsTr("Changelog"), u: Backend.links.changelog },
                                { t: qsTr("License"), u: Backend.links.license }
                            ]
                            PrimaryButton {
                                required property var modelData
                                text: modelData.t; ghost: true
                                onClicked: Qt.openUrlExternally(modelData.u)
                            }
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("No telemetry. JuhRadial MX sends nothing about you; the only network request is the optional daily update check.")
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("By JuhLabs, with code from @gcarmin, @frizikk and @iceteaSA, and fixes shaped by everyone who reported an issue.")
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: qsTr("Restore defaults")
                        desc: qsTr("Resets every setting on these tabs. Macros and app profiles are kept, and Undo brings your settings back.")
                        PrimaryButton {
                            text: qsTr("Restore defaults…")
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
        title: qsTr("Export JuhRadial MX settings")
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("Zip archive (*.zip)")]
        defaultSuffix: "zip"
        onAccepted: Backend.exportBackup(selectedFile.toString())
    }
    FileDialog {
        id: importDialog
        title: qsTr("Import JuhRadial MX settings")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("Zip archive (*.zip)"), qsTr("All files (*)")]
        onAccepted: {
            importPopup.url = selectedFile.toString()
            importPopup.info = Backend.inspectBackup(importPopup.url)
            importPopup.open()
        }
    }

    // Dark glass popup shell shared by the three confirmations below.
    component GlassPopup: QQC.Popup {
        width: 420
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
    }

    // ---- Import preview ----
    GlassPopup {
        id: importPopup
        property string url: ""
        property var info: ({})
        contentItem: Column {
            spacing: Theme.gapL
            Text {
                width: parent.width
                text: importPopup.info.ok ? qsTr("Import this backup?") : qsTr("Cannot import this file")
                color: Theme.textPrimary
                font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: !importPopup.info.ok ? (importPopup.info.error || "")
                      : (importPopup.info.created ? qsTr("Made %1").arg(importPopup.info.created) : "")
                visible: text !== ""
                color: Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
            }
            Text {
                visible: importPopup.info.ok === true
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTr("Replaces: %1").arg([
                    importPopup.info.config ? qsTr("settings") : "",
                    importPopup.info.profiles ? qsTr("app profiles") : "",
                    importPopup.info.macros ? qsTr("%n macro file(s)", "", importPopup.info.macros) : "",
                    importPopup.info.icons ? qsTr("%n icon(s)", "", importPopup.info.icons) : "",
                    importPopup.info.themes ? qsTr("%n theme(s)", "", importPopup.info.themes) : ""
                ].filter(function (s) { return s !== "" }).join(", "))
                color: Theme.textBody
                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.gapS
                PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: importPopup.close() }
                PrimaryButton {
                    visible: importPopup.info.ok === true
                    text: qsTr("Import")
                    onClicked: {
                        importPopup.close()
                        if (Backend.importBackup(importPopup.url))
                            Window.window.undoToast(qsTr("Settings imported"), function () { Backend.undoImport() })
                    }
                }
            }
        }
    }

    // ---- Apply desktop defaults: preview the slice changes first ----
    GlassPopup {
        id: dePopup
        property var preview: ({ desktop: "", changes: [] })
        contentItem: Column {
            spacing: Theme.gapL
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTr("Use the %1 apps?").arg(dePopup.preview.desktop)
                color: Theme.textPrimary
                font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
            }
            Column {
                width: parent.width; spacing: 4
                Repeater {
                    model: dePopup.preview.changes
                    Text {
                        required property var modelData
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("%1: %2 to %3").arg(modelData.label).arg(modelData.old || qsTr("nothing")).arg(modelData.to)
                        color: Theme.textBody
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                }
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.gapS
                PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: dePopup.close() }
                PrimaryButton {
                    text: qsTr("Apply")
                    onClicked: { dePopup.close(); Backend.applyDeDefaults(Backend.get("desktop_environment", "auto")) }
                }
            }
        }
    }

    // ---- Restore-defaults confirmation ----
    GlassPopup {
        id: confirmPopup
        contentItem: Column {
            spacing: Theme.gapL
            Text {
                width: parent.width
                text: qsTr("Restore defaults?")
                color: Theme.textPrimary
                font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTr("Buttons, ring slices, pointer and scroll, haptics, gaming, Flow and these settings go back to their defaults. Your macros and app profiles stay. A copy is kept so you can undo.")
                color: Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.gapS
                PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: confirmPopup.close() }
                PrimaryButton {
                    text: qsTr("Restore")
                    danger: true
                    onClicked: {
                        confirmPopup.close()
                        if (Backend.restoreDefaults())
                            Window.window.undoToast(qsTr("Settings restored to defaults"),
                                                    function () { Backend.undoRestoreDefaults() })
                    }
                }
            }
        }
    }
}
