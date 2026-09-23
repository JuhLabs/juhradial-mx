import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Effects
import "components"

ApplicationWindow {
    id: win
    visible: true
    width: 1200; height: 800
    minimumWidth: 1000; minimumHeight: 660
    title: "JuhRadial MX"
    color: Theme.bgBase

    QtObject { id: nav; objectName: "nav"; property int current: (typeof initialPage !== "undefined" ? initialPage : 0) }

    // Pages can request a tab switch via Backend.goTo("<key>").
    Connections {
        target: Backend
        function onNavRequested(key) {
            for (var i = 0; i < navModel.count; i++) {
                if (navModel.get(i).key === key) { nav.current = i; break }
            }
        }
    }

    ListModel {
        id: navModel
        ListElement { label: "Dashboard"; page: "DashboardPage"; key: "dashboard"; logitechOnly: false }
        ListElement { label: "Buttons"; page: "ButtonsPage"; key: "buttons"; logitechOnly: false }
        ListElement { label: "Point & Scroll"; page: "ScrollPage"; key: "scroll"; logitechOnly: false }
        ListElement { label: "Haptics"; page: "HapticsPage"; key: "haptics"; logitechOnly: true }
        ListElement { label: "Macros"; page: "MacrosPage"; key: "macros"; logitechOnly: false }
        ListElement { label: "App profiles"; page: "AppsPage"; key: "apps"; logitechOnly: true }
        ListElement { label: "Easy-Switch"; page: "EasySwitchPage"; key: "easyswitch"; logitechOnly: true }
        ListElement { label: "Devices"; page: "DevicesPage"; key: "devices"; logitechOnly: false }
        ListElement { label: "Gaming"; page: "GamingPage"; key: "gaming"; logitechOnly: false }
        ListElement { label: "Flow"; page: "FlowPage"; key: "flow"; logitechOnly: true }
        ListElement { label: "Themes"; page: "ThemesPage"; key: "themes"; logitechOnly: false }
        ListElement { label: "Settings"; page: "SettingsPage"; key: "settings"; logitechOnly: false }
    }

    // ---- background z-stack: wallpaper -> dim scrim -> vignette ----
    Image {
        id: wall
        anchors.fill: parent
        source: Theme.wallpaper
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: 1920; sourceSize.height: 1200
        asynchronous: true
        cache: true
        Behavior on opacity { NumberAnimation { duration: 340; easing.type: Easing.OutCubic } }
    }
    Connections {
        target: Theme
        function onChanged() { wall.opacity = 0; fadeBack.restart() }
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
            Layout.preferredWidth: 272
            Layout.fillHeight: true
            Column {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 3
                Item {
                    id: brand
                    width: parent.width
                    height: 80
                    property bool hovered: brandHover.hovered
                    Image {
                        id: logoImg
                        source: assetsDir + "/logo/icons/juhradial-mx-256.png"
                        sourceSize.width: 220; sourceSize.height: 220
                        width: 74; height: 74; smooth: true
                        x: 0
                        anchors.verticalCenter: parent.verticalCenter
                        scale: brand.hovered ? 1.05 : 1.0
                        Behavior on scale { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutBack } }
                        // light is state: the orb glows accent only while the
                        // daemon is connected, else a neutral ambient shadow.
                        layer.enabled: true
                        layer.effect: MultiEffect {
                            shadowEnabled: true
                            shadowColor: Backend.daemonAvailable ? Theme.accent : "#000000"
                            shadowBlur: 0.62
                            shadowOpacity: Backend.daemonAvailable ? 0.55 : 0.4
                            shadowHorizontalOffset: 0
                            shadowVerticalOffset: 0
                        }
                    }
                    Text {
                        anchors.left: logoImg.right; anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - logoImg.width - 14
                        text: "JuhRadial <font color='" + Theme.accent + "'>MX</font>"
                        textFormat: Text.StyledText
                        color: Theme.textPrimary
                        font.family: Theme.fontUI; font.pixelSize: 21; font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    HoverHandler { id: brandHover }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.border }
                Item { width: 1; height: 6 }
                Repeater {
                    model: navModel
                    NavItem {
                        label: model.label
                        icon: assetsDir + "/icons/nav/" + model.key + ".png"
                        active: nav.current === index
                        visible: !(model.logitechOnly && Backend.isGeneric)
                        onClicked: nav.current = index
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
                    Layout.fillWidth: true
                    Layout.maximumWidth: 460
                    Layout.minimumWidth: 220
                    Layout.alignment: Qt.AlignVCenter
                }
                Item { Layout.fillWidth: true; Layout.preferredWidth: 1 }
                Text {
                    text: Backend.deviceName + "   v" + Backend.appVersion
                    color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    Layout.alignment: Qt.AlignVCenter
                }
            }
            StackLayout {
                id: stack
                Layout.fillWidth: true; Layout.fillHeight: true
                currentIndex: nav.current
                Repeater {
                    model: navModel
                    Loader {
                        id: pageLoader
                        objectName: "pageLoader"
                        active: index === nav.current
                        source: Qt.resolvedUrl("pages/" + model.page + ".qml")
                        // subtle fade + rise when a tab becomes active
                        opacity: active ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
                        transform: Translate {
                            y: pageLoader.active ? 0 : 10
                            Behavior on y { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
                        }
                    }
                }
            }
        }
    }

    // ---- startup loader: the JuhRadial MX orb, glowing + breathing, inside a
    //      rotating accent ring. Replaces the bare spinner. ----
    Rectangle {
        id: splash
        anchors.fill: parent
        color: Theme.bgBase
        visible: opacity > 0.01

        Column {
            anchors.centerIn: parent
            spacing: 26

            Item {
                width: 156; height: 156
                anchors.horizontalCenter: parent.horizontalCenter

                BusyRing {
                    size: 156
                    color: Theme.accent
                    anchors.centerIn: parent
                    opacity: 0.9
                }

                Image {
                    id: splashLogo
                    source: assetsDir + "/logo/icons/juhradial-mx-256.png"
                    sourceSize.width: 256; sourceSize.height: 256
                    width: 96; height: 96; smooth: true
                    anchors.centerIn: parent
                    // glowing orb that breathes; the glow pulses with the scale
                    layer.enabled: true
                    layer.effect: MultiEffect {
                        shadowEnabled: true
                        shadowColor: Theme.accent
                        shadowBlur: 1.0
                        shadowOpacity: 0.55 + (splashLogo.scale - 0.94) * 2.4
                        shadowHorizontalOffset: 0
                        shadowVerticalOffset: 0
                    }
                    SequentialAnimation on scale {
                        running: splash.visible
                        loops: Animation.Infinite
                        NumberAnimation { from: 0.94; to: 1.06; duration: 950; easing.type: Easing.InOutSine }
                        NumberAnimation { from: 1.06; to: 0.94; duration: 950; easing.type: Easing.InOutSine }
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "JuhRadial <font color='" + Theme.accent + "'>MX</font>"
                textFormat: Text.StyledText
                color: Theme.textPrimary
                font.family: Theme.fontDisplay; font.pixelSize: 19; font.weight: Font.DemiBold
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Loading your device…"
                color: Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
        }

        Behavior on opacity { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }
        Component.onCompleted: hideSplash.start()
        Timer { id: hideSplash; interval: 1100; onTriggered: splash.opacity = 0 }
    }
}
