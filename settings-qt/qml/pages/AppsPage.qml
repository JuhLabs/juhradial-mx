import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "../components"

// App profiles: settings that change while one app is in front. A profile
// overrides only what you switch on; everything else follows your global
// settings. Profiles can also carry their own radial menu and buttons.
Item {
    id: page
    anchors.fill: parent

    property int bump: 0
    property string openApp: ""
    property string filter: ""
    property string pickFor: ""      // "add" or "copy:<app>"
    Connections {
        target: Backend
        function onConfigChanged() { page.bump++ }
        function onConfigReloaded() { page.bump++ }
    }
    Component.onCompleted: Backend.readHapticDevice()   // also reports focus tracking

    readonly property var profiles: (page.bump, Backend.appProfiles())
    readonly property var shown: profiles.filter(function (p) {
        var f = page.filter.trim().toLowerCase()
        return f === "" || p.name.toLowerCase().indexOf(f) >= 0 || p.app.indexOf(f) >= 0
    })
    readonly property var recent: (page.bump, Backend.recentApps())
    readonly property bool tracking: Backend.hapticDevice.tracking !== false

    function reload() { page.bump++ }
    function add(cls) {
        Backend.addAppProfile(cls)
        page.openApp = cls.trim().toLowerCase()
        page.reload()
    }
    function remove(app, name) {
        var old = Backend.removeAppProfile(app)
        page.reload()
        Window.window.undoToast(qsTr("Profile for %1 removed").arg(name), function () {
            Backend.restoreAppProfile(app, old); page.reload()
        })
    }
    function chips(p) {
        var out = []
        if (p.overrides.dpi) out.push(qsTr("%1 DPI").arg(p.dpi))
        if (p.overrides.smartshift) out.push(p.smartshiftEnabled ? qsTr("SmartShift") : qsTr("Ratchet"))
        if (p.overrides.hires) out.push(p.hires ? qsTr("Smooth") : qsTr("Line by line"))
        if (p.overrides.thumbwheel) out.push(qsTr("Thumb wheel"))
        if (p.ownRing) out.push(qsTr("Own ring"))
        if (p.buttons > 0) out.push(qsTr("%n button(s)", "", p.buttons))
        return out
    }

    component Divider: Rectangle { width: parent ? parent.width : 400; height: 1; color: Theme.border }

    // One profile: a compact row that opens into its editor.
    component ProfileCard: GlassCard {
        id: card
        required property var modelData
        readonly property var p: modelData
        readonly property bool open: page.openApp === p.app
        readonly property bool active: Backend.activeProfile === p.app
        property var ov: p.overrides
        // the slice chips below read the open app's own ring
        onOpenChanged: if (open && p.ownRing) Backend.editAppSlices(p.app)
        Layout.fillWidth: true
        Layout.preferredHeight: cardCol.implicitHeight + Theme.padCard * 2

        function save(patch) {
            var o = { dpi: card.p.dpi, smartshiftEnabled: card.p.smartshiftEnabled,
                      smartshiftThreshold: card.p.smartshiftThreshold, hires: card.p.hires,
                      thumbwheel: card.p.thumbwheel,
                      overrides: { dpi: card.ov.dpi, smartshift: card.ov.smartshift,
                                   hires: card.ov.hires, thumbwheel: card.ov.thumbwheel } }
            for (var k in patch) {
                if (k === "overrides") { for (var j in patch.overrides) o.overrides[j] = patch.overrides[j] }
                else o[k] = patch[k]
            }
            Backend.saveAppProfile(card.p.app, o)
            page.reload()
        }

        Column {
            id: cardCol
            anchors.fill: parent; anchors.margins: Theme.padCard
            spacing: Theme.gapS

            // header row
            Item {
                width: parent.width; height: 44
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: card.p.name + (card.open ? qsTr(", open") : "")
                Keys.onSpacePressed: page.openApp = card.open ? "" : card.p.app
                Keys.onReturnPressed: page.openApp = card.open ? "" : card.p.app
                FocusHalo { active: parent.activeFocus; radius: Theme.radiusCtl }
                MouseArea {
                    anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: page.openApp = card.open ? "" : card.p.app
                }
                RowLayout {
                    anchors.fill: parent
                    spacing: Theme.gapS
                    Image {
                        id: appIcon
                        Layout.preferredWidth: 32; Layout.preferredHeight: 32
                        source: card.p.icon !== "" ? "image://icon/raw/" + card.p.icon : ""
                        visible: status === Image.Ready && implicitWidth > 1
                        sourceSize.width: 64; sourceSize.height: 64
                    }
                    Rectangle {
                        visible: !appIcon.visible
                        Layout.preferredWidth: 32; Layout.preferredHeight: 32; radius: 8
                        color: Theme.accentFaint
                        Text { anchors.centerIn: parent; text: card.p.name.charAt(0).toUpperCase(); color: Theme.accent
                               font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold }
                    }
                    Column {
                        Layout.fillWidth: true
                        spacing: 2
                        Row {
                            spacing: 8
                            Text { text: card.p.name; color: Theme.textPrimary
                                   font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold }
                            Text { text: card.p.app; color: Theme.textMuted; anchors.baseline: parent.children[0].baseline
                                   font.family: Theme.fontMono; font.pixelSize: Theme.fsMicro }
                        }
                        Text {
                            width: parent.width; elide: Text.ElideRight
                            text: page.chips(card.p).length ? page.chips(card.p).join("  ·  ") : qsTr("Nothing overridden yet: open it to choose")
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                    }
                    Badge { visible: card.active; text: qsTr("Active now"); accent: true; dot: true }
                    Canvas {
                        Layout.preferredWidth: 12; Layout.preferredHeight: 8
                        rotation: card.open ? 180 : 0
                        onPaint: { var c = getContext("2d"); c.reset(); c.strokeStyle = Theme.textMuted; c.lineWidth = 1.6
                                   c.beginPath(); c.moveTo(1, 1); c.lineTo(6, 7); c.lineTo(11, 1); c.stroke() }
                    }
                }
            }

            // editor
            Column {
                visible: card.open
                width: parent.width
                spacing: Theme.gapS
                Divider {}
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: qsTr("Switch on what this app changes. Anything left off follows your global settings.")
                    color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                }
                SettingRow {
                    label: qsTr("Pointer speed (DPI)")
                    desc: card.ov.dpi ? qsTr("Overridden for this app") : qsTr("Follows Point & Scroll")
                    Toggle { checked: card.ov.dpi; accessibleName: qsTr("Override pointer speed")
                             onToggled: (v) => card.save({ overrides: { dpi: v } }) }
                }
                DpiControl {
                    visible: card.ov.dpi
                    width: parent.width
                    value: card.p.dpi
                    accessibleName: qsTr("DPI for %1").arg(card.p.name)
                    onCommitted: (v) => card.save({ dpi: v })
                }
                Divider {}
                SettingRow {
                    label: qsTr("Scroll wheel")
                    desc: card.ov.smartshift ? (card.p.smartshiftEnabled ? qsTr("SmartShift in this app") : qsTr("Always clicks in this app"))
                                             : qsTr("Follows Point & Scroll")
                    Row {
                        spacing: Theme.gapS
                        SegmentedControl {
                            visible: card.ov.smartshift
                            width: 220
                            accessibleName: qsTr("Wheel mode for %1").arg(card.p.name)
                            model: [{ id: "ratchet", name: qsTr("Ratchet") }, { id: "smartshift", name: qsTr("SmartShift") }]
                            currentId: card.p.smartshiftEnabled ? "smartshift" : "ratchet"
                            onActivated: (id) => card.save({ smartshiftEnabled: id === "smartshift" })
                        }
                        Toggle { anchors.verticalCenter: parent.verticalCenter
                                 checked: card.ov.smartshift; accessibleName: qsTr("Override the scroll wheel")
                                 onToggled: (v) => card.save({ overrides: { smartshift: v } }) }
                    }
                }
                SettingRow {
                    visible: card.ov.smartshift && card.p.smartshiftEnabled
                    label: qsTr("SmartShift threshold")
                    Slider {
                        width: 220; from: 1; to: 100; stepSize: 1; pageStep: 10
                        showValue: true; suffix: "%"
                        accessibleName: qsTr("SmartShift threshold for %1").arg(card.p.name)
                        value: card.p.smartshiftThreshold
                        onCommitted: (v) => card.save({ smartshiftThreshold: Math.round(v) })
                    }
                }
                Divider {}
                SettingRow {
                    label: qsTr("Smooth scrolling")
                    desc: card.ov.hires ? (card.p.hires ? qsTr("On in this app") : qsTr("Off in this app")) : qsTr("Follows Point & Scroll")
                    Row {
                        spacing: Theme.gapS
                        SegmentedControl {
                            visible: card.ov.hires
                            width: 160
                            accessibleName: qsTr("Smooth scrolling for %1").arg(card.p.name)
                            model: [{ id: "on", name: qsTr("On") }, { id: "off", name: qsTr("Off") }]
                            currentId: card.p.hires ? "on" : "off"
                            onActivated: (id) => card.save({ hires: id === "on" })
                        }
                        Toggle { anchors.verticalCenter: parent.verticalCenter
                                 checked: card.ov.hires; accessibleName: qsTr("Override smooth scrolling")
                                 onToggled: (v) => card.save({ overrides: { hires: v } }) }
                    }
                }
                Divider {}
                SettingRow {
                    label: qsTr("Thumb wheel")
                    desc: card.ov.thumbwheel ? qsTr("Overridden for this app") : qsTr("Follows Point & Scroll")
                    Row {
                        spacing: Theme.gapS
                        ComboBox {
                            visible: card.ov.thumbwheel
                            width: 240
                            accessibleName: qsTr("Thumb wheel for %1").arg(card.p.name)
                            model: Backend.thumbwheelModes()
                            currentId: card.p.thumbwheel
                            onActivated2: (id) => card.save({ thumbwheel: id })
                        }
                        Toggle { anchors.verticalCenter: parent.verticalCenter
                                 checked: card.ov.thumbwheel; accessibleName: qsTr("Override the thumb wheel")
                                 onToggled: (v) => card.save({ overrides: { thumbwheel: v } }) }
                    }
                }
                Divider {}
                SettingRow {
                    label: qsTr("Radial menu")
                    desc: card.p.ownRing ? qsTr("This app has its own slices") : qsTr("The same ring as everywhere")
                    SegmentedControl {
                        width: 240
                        accessibleName: qsTr("Radial menu for %1").arg(card.p.name)
                        model: [{ id: "global", name: qsTr("Same") }, { id: "own", name: qsTr("Its own") }]
                        currentId: card.p.ownRing ? "own" : "global"
                        onActivated: (id) => { Backend.setAppOwnRing(card.p.app, id === "own"); page.reload() }
                    }
                }
                Flow {
                    visible: card.p.ownRing
                    width: parent.width
                    spacing: 6
                    Repeater {
                        model: card.p.ownRing && card.open ? 8 : 0
                        Rectangle {
                            id: slot
                            required property int index
                            readonly property var d: (page.bump, Backend.appSlices.sliceAt(index))
                            width: slotTxt.implicitWidth + 28; height: 32; radius: 8
                            color: slotHov.hovered ? "#1CFFFFFF" : "#12FFFFFF"
                            border.color: Theme.border; border.width: 1
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: qsTr("Slice %1: %2").arg(index + 1).arg(slot.d.label || "")
                            Keys.onReturnPressed: slot.edit()
                            Keys.onSpacePressed: slot.edit()
                            function edit() {
                                Backend.editAppSlices(card.p.app)
                                appSliceEd.model = Backend.appSlices
                                appSliceEd.row = slot.index
                                appSliceEd.reload()
                                appSliceEd.open()
                            }
                            FocusHalo { active: slot.activeFocus; radius: 8 }
                            HoverHandler { id: slotHov; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: slot.edit() }
                            Text {
                                id: slotTxt
                                anchors.centerIn: parent
                                text: (slot.index + 1) + "  " + (slot.d.label || "")
                                color: Theme.textBody
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                        }
                    }
                }
                Divider {}
                SettingRow {
                    label: qsTr("Buttons")
                    desc: card.p.buttons > 0 ? qsTr("%n button(s) do something else in this app", "", card.p.buttons)
                                             : qsTr("Pick this app in the scope switcher on the Buttons tab")
                    PrimaryButton { text: qsTr("Buttons"); ghost: true; onClicked: Backend.goTo("buttons") }
                }
                Divider {}
                Row {
                    spacing: Theme.gapS
                    // Try the profile without switching windows (a minute).
                    PrimaryButton {
                        readonly property bool trying: Backend.trialApp === card.p.app
                        text: trying ? qsTr("Stop trying") : qsTr("Try now")
                        ghost: !trying
                        onClicked: trying ? Backend.stopAppProfileTrial() : Backend.tryAppProfile(card.p.app)
                    }
                    PrimaryButton {
                        text: qsTr("Copy to another app"); ghost: true
                        onClicked: { page.pickFor = "copy:" + card.p.app; picker.open() }
                    }
                    PrimaryButton {
                        text: qsTr("Remove profile"); ghost: true; danger: true
                        onClicked: page.remove(card.p.app, card.p.name)
                    }
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

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: topCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: topCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("App profiles")
                        subtitle: qsTr("Settings that change while one app is in front")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/apps"
                        PrimaryButton { text: qsTr("Choose an app"); onClicked: { page.pickFor = "add"; picker.open() } }
                    }
                    Text {
                        visible: !page.tracking
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("Your desktop does not tell JuhRadial which window is in front, so profiles cannot switch here. On GNOME Wayland this needs the JuhRadial GNOME extension.")
                        color: Theme.danger
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Add by window class")
                        desc: qsTr("For apps without a menu entry, for example steam_app_730")
                        Row {
                            spacing: Theme.gapS
                            InputField {
                                id: classField
                                width: 240; mono: true
                                placeholder: qsTr("window class")
                                accessibleName: qsTr("Window class")
                                error: Backend.appProfileError(text)
                                onAccepted: if (error === "" && text.trim() !== "") { page.add(text); text = "" }
                            }
                            PrimaryButton {
                                text: qsTr("Add"); ghost: true
                                enabled: classField.text.trim() !== "" && classField.error === ""
                                onClicked: { page.add(classField.text); classField.text = "" }
                            }
                        }
                    }
                    SettingRow {
                        visible: page.recent.length > 0
                        label: qsTr("Recently used")
                        desc: qsTr("Apps you used since JuhRadial started, one click to add")
                    }
                    Flow {
                        visible: page.recent.length > 0
                        width: parent.width
                        spacing: 6
                        Repeater {
                            model: page.recent
                            PrimaryButton {
                                required property var modelData
                                text: "+ " + modelData.name; ghost: true
                                onClicked: page.add(modelData.app)
                            }
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Suggest profiles for new apps")
                        desc: qsTr("The first time you use an app without a profile, Settings offers one. Each app is asked about once")
                        Toggle {
                            checked: (page.bump, Backend.get("app.suggest_profiles", true))
                            onToggled: (v) => Backend.setLocal("app.suggest_profiles", v)
                        }
                    }
                }
            }

            InputField {
                visible: page.profiles.length > 4
                Layout.preferredWidth: 320
                placeholder: qsTr("Filter profiles")
                accessibleName: qsTr("Filter profiles")
                onTextEdited: page.filter = text
            }

            EmptyState {
                visible: page.profiles.length === 0
                Layout.fillWidth: true
                title: qsTr("No app profiles yet")
                body: qsTr("Give an app its own DPI, wheel, buttons or radial menu. It switches in when the app comes to the front.")
                PrimaryButton { text: qsTr("Choose an app"); onClicked: { page.pickFor = "add"; picker.open() } }
            }

            Repeater {
                model: page.shown
                ProfileCard {}
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    AppPicker {
        id: picker
        title: page.pickFor === "add" ? qsTr("Make a profile for") : qsTr("Copy the profile to")
        onPicked: (app) => {
            var cls = Backend.appClassFor(app.id)
            if (page.pickFor === "add") {
                if (Backend.appProfileError(cls) === "") page.add(cls)
                else page.openApp = cls
            } else {
                Backend.copyAppProfile(page.pickFor.slice(5), cls)
                page.reload()
            }
        }
    }
    SliceEditor { id: appSliceEd; onClosed: page.reload() }
}
