import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "../components"

// Themes: the app's colour theme (or Automatic, following the desktop accent),
// and the look of the radial menu in one card: a live preview of your own
// ring, the wheel skin, the ring surface palette and the icon style, with
// Show on screen. Every change can be undone from its toast.
Item {
    id: page
    anchors.fill: parent

    property int bump: 0
    // "" (fresh install) and "none" both mean the Classic ring.
    readonly property string wheelKey: {
        page.bump
        return Backend.wheelSkin
    }
    // The palette behind the Classic Light skin (0.4.4's white classic ring).
    readonly property string lightClassic: "github-light"
    readonly property string palette: (bump, Backend.get("theme", "phosphor"))
    readonly property var geo: (bump, Backend.ringGeometry())
    readonly property var palettes: Backend.ringPalettes()
    // Hovering a skin or a ring colour previews it on the ring (keys, "" = none).
    property string hoverSkin: ""
    property string hoverPalette: ""
    Connections {
        target: Backend
        function onConfigChanged() { page.bump++ }
        function onConfigReloaded() { page.bump++ }
    }

    function nameOf(list, key, field) {
        for (var i = 0; i < list.length; i++) if (list[i][field] === key) return list[i].name
        return key
    }
    function setTheme(i) {
        var before = Theme.index, wasAuto = Theme.auto
        if (i === before && !wasAuto) return
        Theme.setIndex(i)
        Window.window.undoToast(qsTr("Theme: %1").arg(Theme.name), function () {
            if (wasAuto) Theme.setAuto(true); else Theme.setIndex(before)
        })
    }
    function setSkin(key) {
        var before = Backend.get("radial.wheel", ""), beforeTheme = page.palette
        if (key === page.wheelKey) return
        Backend.setWheelSkin(key)
        Window.window.undoToast(qsTr("Wheel skin changed"), function () {
            Backend.set("radial.wheel", before)
            Backend.set("theme", beforeTheme)
        })
    }
    function setPalette(key) {
        var before = page.palette
        if (key === before) return
        Backend.set("theme", key)
        Window.window.undoToast(qsTr("Ring colours changed"), function () { Backend.set("theme", before) })
    }
    // Same writes as Settings > Icon style: the overlay reads radial.icon_style.
    function setIconStyle(id) {
        Theme.setIconStyle(id)
        Backend.setLocal("radial.icon_style", id)
        Backend.setLocal("radial.monochrome_icons", id === "mono")
    }
    function resetLook() {
        var t = Theme.index, a = Theme.auto, w = Backend.get("radial.wheel", ""), p = page.palette, s = Theme.iconStyle
        Theme.setIndex(0); Backend.set("radial.wheel", "none"); Backend.set("theme", "phosphor"); page.setIconStyle("mono")
        Window.window.undoToast(qsTr("Look reset"), function () {
            if (a) Theme.setAuto(true); else Theme.setIndex(t)
            Backend.set("radial.wheel", w); Backend.set("theme", p); page.setIconStyle(s)
        })
    }

    // A selectable tile: radio semantics, keyboard, a focus halo distinct from
    // the selection ring.
    component Choice: Item {
        id: ch
        property bool sel: false
        property string name: ""
        readonly property bool hovered: chHover.hovered
        signal chosen
        HoverHandler { id: chHover }
        activeFocusOnTab: true
        Accessible.role: Accessible.RadioButton
        Accessible.name: name
        Accessible.checkable: true
        Accessible.checked: sel
        Accessible.onPressAction: chosen()
        Keys.onSpacePressed: chosen()
        Keys.onReturnPressed: chosen()
        FocusHalo { active: ch.activeFocus; radius: 14; margin: 3 }
        TapHandler { onTapped: ch.chosen() }
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

            // ===== Colour theme =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: themeCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: themeCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: qsTr("Colour theme")
                        subtitle: qsTr("An accent and a matched wallpaper for this app. The radial menu uses the accent.")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/preferences-desktop-theme-symbolic"
                        Row {
                            spacing: Theme.gapS
                            Badge { text: Theme.auto ? qsTr("Automatic: %1").arg(Theme.name) : Theme.name; accent: true; dot: true }
                            PrimaryButton { text: qsTr("Reset look"); ghost: true; onClicked: page.resetLook() }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    // Automatic: follow the desktop accent
                    SettingRow {
                        width: parent.width
                        label: qsTr("Match the desktop accent")
                        desc: Theme.desktopAccent !== ""
                              ? qsTr("Picks the theme closest to your desktop's accent colour")
                              : qsTr("Your desktop does not report an accent colour")
                        Row {
                            spacing: Theme.gapS
                            Rectangle {
                                visible: Theme.desktopAccent !== ""
                                anchors.verticalCenter: parent.verticalCenter
                                width: 18; height: 18; radius: 9
                                color: Theme.desktopAccent !== "" ? Theme.desktopAccent : "transparent"
                                border.width: 1; border.color: Theme.borderStrong
                            }
                            Toggle {
                                enabled: Theme.desktopAccent !== ""
                                checked: Theme.auto
                                onToggled: (v) => Theme.setAuto(v)
                            }
                        }
                    }

                    GridLayout {
                        id: grid
                        width: parent.width
                        // full rows for the 12 themes
                        columns: width >= 1100 ? 6 : (width >= 700 ? 4 : 3)
                        columnSpacing: Theme.gap
                        rowSpacing: Theme.gap
                        Repeater {
                            model: Theme.themeList()
                            Choice {
                                id: tile
                                required property var modelData
                                required property int index
                                sel: Theme.index === index
                                name: modelData.name
                                Layout.fillWidth: true
                                Layout.preferredHeight: 128
                                onChosen: page.setTheme(index)
                                HoverHandler { id: hov }
                                Rectangle {
                                    anchors.fill: parent; radius: 14
                                    color: Theme.surfaceSolid
                                    border.width: tile.sel ? 2 : 1
                                    border.color: tile.sel ? modelData.accent : (hov.hovered ? Theme.borderStrong : Theme.border)
                                    Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                                    clip: true
                                    Image {
                                        anchors.fill: parent; anchors.margins: 1
                                        source: modelData.wallpaper
                                        sourceSize.width: 240; sourceSize.height: 128
                                        asynchronous: true
                                        fillMode: Image.PreserveAspectCrop; smooth: true
                                        opacity: 0.85
                                    }
                                    // the ring in this accent: what a theme changes on the menu
                                    Item {
                                        anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10
                                        width: 44; height: 44
                                        Rectangle { anchors.fill: parent; radius: 22; color: "#C0101216"; border.width: 5; border.color: "#33FFFFFF" }
                                        Rectangle {
                                            width: 12; height: 12; radius: 6; color: modelData.accent
                                            x: 16; y: 2
                                        }
                                        Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: "#80000000"; border.width: 1; border.color: modelData.accent }
                                    }
                                    Rectangle {
                                        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                                        height: 44
                                        gradient: Gradient {
                                            GradientStop { position: 0.0; color: "#00000000" }
                                            GradientStop { position: 1.0; color: "#B3000000" }
                                        }
                                    }
                                    Row {
                                        anchors.left: parent.left; anchors.bottom: parent.bottom
                                        anchors.margins: 10; spacing: 8
                                        Rectangle {
                                            width: 16; height: 16; radius: 8; color: modelData.accent
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Text {
                                            text: modelData.name; color: "#FFFFFF"
                                            anchors.verticalCenter: parent.verticalCenter
                                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                            font.weight: tile.sel ? Font.DemiBold : Font.Medium
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ===== Radial menu look =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: lookCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: lookCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: qsTr("Radial menu look")
                        subtitle: qsTr("%1 skin, %2 ring colours, %3 icons")
                                  .arg(page.nameOf(Theme.wheelList(), page.wheelKey, "key"))
                                  .arg(page.nameOf(page.palettes, page.palette, "id"))
                                  .arg(Theme.iconStyle === "mono" ? qsTr("mono") : (Theme.iconStyle === "classic" ? qsTr("classic") : qsTr("line")))
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-grid-symbolic"
                        PrimaryButton { text: qsTr("Show on screen"); ghost: true; onClicked: Backend.showMenuPreview() }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    RowLayout {
                        width: parent.width
                        spacing: Theme.gapL
                        RingPreview {
                            Layout.preferredWidth: 240; Layout.preferredHeight: 240
                            Layout.alignment: Qt.AlignTop
                            outer: page.geo.outer; inner: page.geo.inner
                            iconScale: page.geo.icon; outerMax: page.geo.outerMax
                            skin: page.hoverSkin
                            paletteKey: page.hoverPalette
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            spacing: Theme.gapS

                            SectionHeader { text: qsTr("Wheel skin") }
                            Flow {
                                Layout.fillWidth: true
                                spacing: Theme.gapS
                                Repeater {
                                    model: Theme.wheelList()
                                    Choice {
                                        id: sk
                                        required property var modelData
                                        sel: page.wheelKey === modelData.key
                                        name: modelData.name
                                        width: 120; height: 146
                                        onChosen: page.setSkin(modelData.key)
                                        onHoveredChanged: {
                                            var key = modelData.key === "classic-light" ? "none" : modelData.key
                                            page.hoverSkin = hovered ? key : (page.hoverSkin === key ? "" : page.hoverSkin)
                                            if (modelData.key === "classic-light")
                                                page.hoverPalette = hovered ? page.lightClassic : (page.hoverPalette === page.lightClassic ? "" : page.hoverPalette)
                                        }
                                        Rectangle {
                                            anchors.fill: parent; radius: 14
                                            color: sk.sel ? Theme.accentSubtle : "#0CFFFFFF"
                                            border.width: sk.sel ? 2 : 1
                                            border.color: sk.sel ? Theme.accent : Theme.border
                                            Column {
                                                anchors.centerIn: parent; spacing: 4
                                                Item {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    width: 88; height: 88
                                                    Image {
                                                        anchors.fill: parent; visible: modelData.image !== ""
                                                        source: modelData.image; sourceSize.width: 176; sourceSize.height: 176
                                                        smooth: true; asynchronous: true
                                                    }
                                                    ClassicWheel {
                                                        anchors.centerIn: parent; visible: modelData.image === ""; size: 88
                                                        fill: modelData.light ? "#FFFFFF" : "#1B1F28"
                                                        hi: modelData.light ? "#EEF1F4" : "#2A303C"
                                                        stroke: modelData.light ? "#D8DEE4" : "#38FFFFFF"
                                                    }
                                                }
                                                Text {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    text: modelData.name; color: Theme.textBody
                                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.Medium
                                                }
                                                Text {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    text: modelData.image === "" ? qsTr("Uses your accent") : qsTr("Fixed colours")
                                                    color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            SectionHeader { text: qsTr("Ring colours"); Layout.topMargin: Theme.gapS }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                text: qsTr("The surface of the Classic ring and its menus. Light rings suit light desktops.")
                                color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 6
                                Repeater {
                                    model: page.palettes
                                    Choice {
                                        id: pc
                                        required property var modelData
                                        sel: page.palette === modelData.id
                                        name: modelData.name
                                        width: pcTxt.implicitWidth + 44; height: 34
                                        onChosen: page.setPalette(modelData.id)
                                        onHoveredChanged: page.hoverPalette = hovered ? modelData.id : (page.hoverPalette === modelData.id ? "" : page.hoverPalette)
                                        Rectangle {
                                            anchors.fill: parent; radius: 17
                                            color: pc.sel ? Theme.accentSubtle : "#0CFFFFFF"
                                            border.width: 1; border.color: pc.sel ? Theme.accent : Theme.border
                                            Row {
                                                anchors.centerIn: parent; spacing: 8
                                                Rectangle {
                                                    width: 14; height: 14; radius: 7
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    color: modelData.base
                                                    border.width: 2; border.color: modelData.border
                                                }
                                                Text {
                                                    id: pcTxt
                                                    text: modelData.name; color: pc.sel ? Theme.accent : Theme.textBody
                                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            SettingRow {
                                Layout.fillWidth: true
                                label: qsTr("Icon style")
                                desc: qsTr("Ring size, icon size and the centre zone are in Settings")
                                Row {
                                    spacing: Theme.gapS
                                    PrimaryButton {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: qsTr("Ring size"); ghost: true
                                        onClicked: Backend.goTo("settings")
                                    }
                                    SegmentedControl {
                                        width: 240
                                        accessibleName: qsTr("Icon style")
                                        model: [{ id: "mono", name: qsTr("Mono") }, { id: "line", name: qsTr("Line") },
                                                { id: "classic", name: qsTr("Classic") }]
                                        currentId: Theme.iconStyle
                                        onActivated: (id) => page.setIconStyle(id)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
