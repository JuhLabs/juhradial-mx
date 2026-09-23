import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: win
    visible: true
    width: 1200; height: 800
    minimumWidth: 1000; minimumHeight: 660
    title: "JuhRadial MX"  // i18n-ignore (product name)
    color: Theme.bgBase
    // Shared ToolTip (IconButton.tip and friends) in the app's colours.
    palette.toolTipBase: Theme.surfaceSolid
    palette.toolTipText: Theme.textPrimary
    font.family: Theme.fontUI

    // One Undo pattern for every page (a Loader-loaded page reaches it as
    // Window.window.undoToast(qsTr("Macro deleted"), function () { ... })).
    // The caller translates the text; the toast offers "Undo" for 9 s.
    function undoToast(text, restore) {
        toast.show(text, "info", qsTr("Undo"), restore)
    }

    QtObject { id: nav; objectName: "nav"; property int current: (typeof initialPage !== "undefined" ? initialPage : 0) }

    // Pages can request a tab switch via Backend.goTo("<key>").
    Connections {
        target: Backend
        function onNavRequested(key) {
            for (var i = 0; i < navModel.count; i++) {
                if (navModel.get(i).key === key) { nav.current = i; break }
            }
        }
        function onToastRequested(text, kind) { toast.show(text, kind) }
        // Backend.toast (plain text) had no listener, so "keyboard not
        // reachable", autostart errors and the corrupt-config notice vanished.
        function onToast(text) { toast.show(text, "info") }
        // Pages read Backend.get() when they load; after an import or a
        // restore, re-run the active Loader so the controls show the new file.
        function onConfigReloaded() { const i = nav.current; nav.current = -1; nav.current = i }
        // A newly focused app without a profile: offer one, now if this window
        // is in front, otherwise the next time it becomes active.
        function onProfileSuggested() { if (win.active) win.offerProfile() }
    }
    onActiveChanged: if (active) offerProfile()
    function offerProfile() {
        const s = Backend.takeProfileSuggestion()
        if (!s) return
        toast.show(qsTr("First time in %1. Give it its own profile?").arg(s.name), "info", qsTr("Create profile"),
                   function() { Backend.addAppProfile(s.app); Backend.goTo("apps"); Backend.reloadPage() })
    }

    ListModel {
        id: navModel
        ListElement { label: qsTr("Dashboard"); page: "DashboardPage"; key: "dashboard"; logitechOnly: false }
        ListElement { label: qsTr("Buttons"); page: "ButtonsPage"; key: "buttons"; logitechOnly: false }
        ListElement { label: qsTr("Point & Scroll"); page: "ScrollPage"; key: "scroll"; logitechOnly: false }
        ListElement { label: qsTr("Haptics"); page: "HapticsPage"; key: "haptics"; logitechOnly: true }
        ListElement { label: qsTr("Macros"); page: "MacrosPage"; key: "macros"; logitechOnly: false }
        ListElement { label: qsTr("App profiles"); page: "AppsPage"; key: "apps"; logitechOnly: true }
        ListElement { label: qsTr("Easy-Switch"); page: "EasySwitchPage"; key: "easyswitch"; logitechOnly: true }
        ListElement { label: qsTr("Devices"); page: "DevicesPage"; key: "devices"; logitechOnly: false }
        ListElement { label: qsTr("Gaming"); page: "GamingPage"; key: "gaming"; logitechOnly: false }
        ListElement { label: qsTr("Flow"); page: "FlowPage"; key: "flow"; logitechOnly: true }
        ListElement { label: qsTr("Themes"); page: "ThemesPage"; key: "themes"; logitechOnly: false }
        ListElement { label: qsTr("Settings"); page: "SettingsPage"; key: "settings"; logitechOnly: false }
    }

    // ---- keyboard: Ctrl+K search, Ctrl+1..9 tabs ----
    Shortcut { sequences: ["Ctrl+K", "Ctrl+F"]; onActivated: search.focusInput() }
    Shortcut { sequence: "Ctrl+1"; onActivated: nav.current = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: nav.current = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: nav.current = 2 }
    Shortcut { sequence: "Ctrl+4"; onActivated: nav.current = 3 }
    Shortcut { sequence: "Ctrl+5"; onActivated: nav.current = 4 }
    Shortcut { sequence: "Ctrl+6"; onActivated: nav.current = 5 }
    Shortcut { sequence: "Ctrl+7"; onActivated: nav.current = 6 }
    Shortcut { sequence: "Ctrl+8"; onActivated: nav.current = 7 }
    Shortcut { sequence: "Ctrl+9"; onActivated: nav.current = 8 }

    // ---- background z-stack: wallpaper -> dim scrim -> vignette ----
    Image {
        id: wall
        anchors.fill: parent
        source: Theme.wallpaper
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: 1920; sourceSize.height: 1200
        asynchronous: true
        cache: true
        Behavior on opacity { NumberAnimation { duration: Theme.dLong; easing.type: Easing.OutCubic } }
    }
    // Crossfade only when the wallpaper itself changes: Theme.changed also
    // fires for icon style and reduce transparency, which made the whole
    // window blink on unrelated toggles.
    property url _wallShown: Theme.wallpaper
    Connections {
        target: Theme
        function onChanged() {
            if (Theme.wallpaper === win._wallShown) return
            win._wallShown = Theme.wallpaper
            if (Theme.reduceMotion) return
            wall.opacity = 0; fadeBack.restart()
        }
    }
    Timer { id: fadeBack; interval: 70; onTriggered: wall.opacity = 1 }

    Rectangle { anchors.fill: parent; color: "#000000"; opacity: 0.42 }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#33000000" }
            GradientStop { position: 0.5; color: "#00000000" }
            GradientStop { position: 1.0; color: "#73000000" }
        }
    }

    // ---- content ----
    RowLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 16

        GlassCard {
            rail: true
            Layout.preferredWidth: 256
            Layout.fillHeight: true
            Column {
                id: railCol
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 12
                spacing: 2
                Item {
                    id: brand
                    width: parent.width
                    height: 76
                    Image {
                        id: logoImg
                        source: assetsDir + "/logo/icons/juhradial-mx-256.png"
                        sourceSize.width: 160; sourceSize.height: 160
                        width: 54; height: 54; smooth: true
                        x: 8
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Column {
                        anchors.left: logoImg.right; anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Text {
                            text: "JuhRadial <font color='" + Theme.accent + "'>MX</font>"  // i18n-ignore (product name)
                            textFormat: Text.StyledText
                            color: Theme.textPrimary
                            font.family: Theme.fontDisplay; font.pixelSize: 19; font.weight: Font.DemiBold
                        }
                        Row {
                            spacing: 6
                            Rectangle {
                                width: 7; height: 7; radius: 4
                                anchors.verticalCenter: parent.verticalCenter
                                color: Backend.daemonAvailable ? Theme.accent : Theme.textMuted
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: Backend.daemonAvailable ? qsTr("Daemon connected") : qsTr("Daemon offline")
                                color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                            }
                        }
                    }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.border }
                Item { width: 1; height: 8 }
                Repeater {
                    model: navModel
                    NavItem {
                        label: model.label
                        icon: model.key
                        active: nav.current === index
                        visible: !(model.logitechOnly && Backend.isGeneric)
                        onClicked: nav.current = index
                    }
                }
            }
            // footer: version + a small, quiet support link
            Column {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.margins: 12
                spacing: 8
                Rectangle { width: parent.width; height: 1; color: Theme.border }
                Item {
                    width: parent.width; height: 28
                    Text {
                        anchors.left: parent.left; anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: "v" + Backend.appVersion  // i18n-ignore
                        color: Theme.textMuted
                        font.family: Theme.fontMono; font.pixelSize: Theme.fsMicro
                    }
                    Item {
                        id: support
                        anchors.right: parent.right; anchors.rightMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        width: supRow.width + 16; height: 26
                        Rectangle {
                            anchors.fill: parent; radius: 8
                            color: supMa.containsMouse ? "#12FFFFFF" : "transparent"
                            Behavior on color { ColorAnimation { duration: Theme.dShort } }
                        }
                        Row {
                            id: supRow
                            anchors.centerIn: parent; spacing: 6
                            ActionIcon {
                                iconName: "heart"; px: 13
                                tint: supMa.containsMouse ? Theme.textBody : Theme.textMuted
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: qsTr("Support")
                                color: supMa.containsMouse ? Theme.textBody : Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro; font.weight: Font.Medium
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        Accessible.role: Accessible.Link
                        Accessible.name: qsTr("Support JuhRadial MX")
                        MouseArea {
                            id: supMa; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Qt.openUrlExternally("https://paypal.me/LangbachHermstad")
                        }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gapL
                Text {
                    text: navModel.get(nav.current).label
                    color: Theme.textPrimary
                    font.family: Theme.fontDisplay; font.pixelSize: Theme.fsH1; font.weight: Font.DemiBold
                    Layout.alignment: Qt.AlignVCenter
                }
                Item { Layout.fillWidth: true; Layout.preferredWidth: 1 }
                SearchBar {
                    id: search
                    Layout.fillWidth: true
                    Layout.maximumWidth: 460
                    Layout.minimumWidth: 220
                    Layout.alignment: Qt.AlignVCenter
                }
                Item { Layout.fillWidth: true; Layout.preferredWidth: 1 }
                Row {
                    spacing: Theme.gapS
                    Layout.alignment: Qt.AlignVCenter
                    Badge {
                        text: Backend.deviceName
                        accent: Backend.daemonAvailable; dot: Backend.daemonAvailable
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    // battery as a quiet mono readout; the ring lives on the Dashboard
                    Rectangle {
                        visible: !Backend.isGeneric
                        anchors.verticalCenter: parent.verticalCenter
                        implicitWidth: batRow.width + 18; implicitHeight: 24; radius: 12
                        color: "#12FFFFFF"; border.width: 1; border.color: Theme.border
                        Row {
                            id: batRow
                            anchors.centerIn: parent; spacing: 6
                            ActionIcon {
                                anchors.verticalCenter: parent.verticalCenter
                                readonly property string sev: Theme.batterySeverity(Backend.battery, Backend.charging)
                                iconName: sev === "charging" ? "battery-full-charging-symbolic"
                                          : (sev === "low" || sev === "critical" ? "battery-low-symbolic" : "battery-good-symbolic")
                                tint: (sev === "low" || sev === "critical") ? Theme.batteryColor(Backend.battery, Backend.charging) : Theme.textBody
                                px: 14
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: Backend.battery + "%"
                                color: Theme.textBody
                                font.family: Theme.fontMono; font.pixelSize: Theme.fsMicro; font.weight: Font.DemiBold
                            }
                        }
                    }
                }
            }
            StackLayout {
                id: stack
                Layout.fillWidth: true; Layout.fillHeight: true
                currentIndex: nav.current
                Repeater {
                    model: navModel
                    // Page host: the content column is capped on wide windows
                    // and stays under the page title (a page may declare
                    // contentMaxWidth; 0 = no cap), so labels never sit a
                    // screen away from their controls.
                    Item {
                        id: host
                        readonly property int cap: pageLoader.item && pageLoader.item.contentMaxWidth !== undefined
                                                   ? pageLoader.item.contentMaxWidth : Theme.contentMaxWidth
                        property Flickable flick: null
                        Loader {
                            id: pageLoader
                            objectName: "pageLoader"
                            active: index === nav.current
                            source: Qt.resolvedUrl("pages/" + model.page + ".qml")
                            width: host.cap > 0 ? Math.min(host.width, host.cap) : host.width
                            height: host.height
                            anchors.left: parent.left
                            onLoaded: host.flick = host._findFlick(item)
                            // subtle fade + rise when a tab becomes active
                            opacity: active ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
                            transform: Translate {
                                y: pageLoader.active ? 0 : 8
                                Behavior on y { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
                            }
                        }
                        // The side gutters still scroll the page.
                        MouseArea {
                            anchors.fill: parent; z: -1
                            acceptedButtons: Qt.NoButton
                            onWheel: (w) => {
                                const f = host.flick
                                if (!f) return
                                const max = Math.max(0, f.contentHeight - f.height)
                                f.contentY = Math.max(0, Math.min(max, f.contentY - w.angleDelta.y))
                            }
                        }
                        function _findFlick(it) {
                            if (!it) return null
                            if (it instanceof Flickable) return it
                            for (let i = 0; i < it.children.length; i++) {
                                if (it.children[i] instanceof Flickable) return it.children[i]
                            }
                            return null
                        }
                    }
                }
            }
        }
    }

    Toast { id: toast; objectName: "toast" }
}
