import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import "../components"

// Landing dashboard: the device on a lit stage that says whether the mouse is
// reachable, what needs fixing, one strip of live readouts, the Actions Ring
// (hover names a slice, click edits it) and the button map (click a row to
// change it). No hover scaling: hover lights a border, light means state.
Item {
    id: page
    anchors.fill: parent
    // The dashboard's bento grid wants a wider column than the other pages.
    property int contentMaxWidth: Theme.contentMaxWidthWide

    property int bump: 0
    property var actMap: ({})
    // "" (fresh install) and "none" both mean the Classic ring.
    property string wheelKey: Backend.get("radial.wheel", "") || "none"
    readonly property bool mono: Theme.iconStyle.startsWith("mono")
    readonly property bool primed: Backend.primed || !Backend.daemonAvailable
    readonly property string link: Backend.linkState
    readonly property bool reachable: Backend.daemonAvailable && link === "connected"
    readonly property bool easySwitchSlot: (bump, Backend.get("radial_menu.easy_switch_shortcuts", false))
    property var health: []
    function refreshHealth() { health = Backend.healthIssues() }
    readonly property bool kbOn: (bump, Backend.get("keyboard.mx_keys.enabled", false))
    property var kb: ({})               // async (a keyboard probe can take seconds)
    readonly property var steps: (bump, Backend.onboarding())
    property string pickSlot: ""
    property int hoverSlice: -1

    function _cap(s) { return s.length ? s.charAt(0).toUpperCase() + s.slice(1) : s }
    Component.onCompleted: {
        var a = Backend.buttonActions(), m = {}
        for (var i = 0; i < a.length; i++) m[a[i].id] = a[i].name
        actMap = m
        refreshHealth()
        if (kbOn) Backend.requestKeyboardInfo()
    }
    Timer { id: refreshLater; interval: 2500; onTriggered: page.refreshHealth() }
    Timer { interval: 5000; repeat: true; running: page.visible; onTriggered: page.refreshHealth() }
    function actionName(slot, def) {
        page.bump
        var id = Backend.buttonAction("", slot, def)
        return id === "custom" ? qsTr("Custom action") : (actMap[id] || id)
    }
    // Which button opens the ring, for the "Opens with" hint.
    readonly property string ringButton: {
        page.bump
        var slots = Backend.buttonSlots()
        for (var i = 0; i < slots.length; i++)
            if (Backend.buttonAction("", slots[i].slot, slots[i].default) === "radial_menu") return slots[i].name
        return ""
    }
    readonly property string linkText: {
        if (!Backend.daemonAvailable) return qsTr("Service not running")
        var via = { bolt: qsTr("Bolt receiver"), unifying: qsTr("Unifying receiver"),
                    bluetooth: qsTr("Bluetooth"), usb: qsTr("USB") }[Backend.transport]
        switch (link) {
        case "connected": return via ? qsTr("Connected via %1").arg(via) : qsTr("Connected")
        case "asleep": return qsTr("Asleep")
        case "away": return qsTr("On another computer")
        default: return qsTr("Not found")
        }
    }
    readonly property string readiness: {
        var c = Backend.caps, have = []
        if (c.haptics) have.push(qsTr("haptics"))
        if (c.smartshift) have.push(qsTr("SmartShift"))
        if (c.thumbwheel) have.push(qsTr("thumb wheel"))
        if (c.dpi) have.push(qsTr("DPI"))
        return have.length ? qsTr("Ready: %1").arg(have.join(", ")) : ""
    }

    Connections {
        target: Backend
        function onLiveChanged() { page.wheelKey = Backend.get("radial.wheel", "") || "none" }
        function onConfigChanged() { page.bump++ }
        function onAvailabilityChanged() { page.refreshHealth() }
        function onPrimedChanged() { page.refreshHealth() }
        function onKeyboardInfoReady(info) { page.kb = info || {} }
    }

    ActionPicker {
        id: picker
        onPicked: (id) => {
            if (id === "custom") { customEd.openFor("", page.pickSlot, page.slotName(page.pickSlot)); return }
            Backend.setButtonIn("", page.pickSlot, id)
            page.bump++
            Backend.notify(qsTr("Saved"), "success")
        }
    }
    CustomActionEditor { id: customEd; onSaved: page.bump++ }
    SliceEditor { id: sliceEd }
    function slotName(slot) {
        var slots = Backend.buttonSlots()
        for (var i = 0; i < slots.length; i++) if (slots[i].slot === slot) return slots[i].name
        return slot
    }

    // One readout cell of the instrument strip: icon, mono value, muted label.
    // A changed value crossfades in.
    component Instrument: Item {
        id: cell
        property string icon: ""
        property string value: ""
        property string label: ""
        property string toTab: ""
        property bool live: false
        Layout.fillWidth: true
        Layout.minimumWidth: 150
        Layout.preferredHeight: 72
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: label + ": " + value
        Keys.onReturnPressed: if (toTab !== "") Backend.goTo(toTab)
        Keys.onSpacePressed: if (toTab !== "") Backend.goTo(toTab)
        onValueChanged: if (!Theme.reduceMotion) fade.restart()
        FocusHalo { active: cell.activeFocus; radius: Theme.radiusCtl }
        Rectangle {
            anchors.fill: parent; anchors.margins: 6
            radius: Theme.radiusCtl
            color: cellMa.containsMouse ? "#12FFFFFF" : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.dShort } }
        }
        Row {
            anchors.left: parent.left; anchors.leftMargin: 14
            anchors.right: parent.right; anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            Rectangle {
                width: 34; height: 34; radius: 10
                anchors.verticalCenter: parent.verticalCenter
                color: cell.live ? Theme.accentSubtle : "#12FFFFFF"
                border.width: 1; border.color: cell.live ? Theme.accentFaint : Theme.border
                ActionIcon {
                    anchors.centerIn: parent
                    iconName: cell.icon; px: 18
                    tint: cell.live ? Theme.accent : Theme.textBody
                }
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 46
                spacing: 2
                Text {
                    id: valTxt
                    width: parent.width; elide: Text.ElideRight
                    text: cell.value; color: Theme.textPrimary
                    font.family: Theme.fontMono; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                    NumberAnimation on opacity { id: fade; from: 0.2; to: 1; duration: 220; running: false }
                }
                Text {
                    width: parent.width; elide: Text.ElideRight
                    text: cell.label; color: Theme.textMuted
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                }
            }
        }
        MouseArea {
            id: cellMa; anchors.fill: parent; hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: if (cell.toTab !== "") Backend.goTo(cell.toTab)
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

            // ---- update available ----
            Rectangle {
                Layout.fillWidth: true
                visible: Backend.updateAvailable && Backend.get("app.check_updates", true)
                implicitHeight: 52; radius: Theme.radiusCard
                color: Theme.accentSubtle; border.width: 1; border.color: Theme.accent
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 8
                    Text {
                        Layout.fillWidth: true; elide: Text.ElideRight
                        text: qsTr("JuhRadial MX %1 is out.").arg(Backend.latestVersion)
                        color: Theme.textPrimary; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    PrimaryButton { text: qsTr("What's new"); ghost: true; onClicked: Qt.openUrlExternally(Backend.latestReleaseUrl) }
                }
            }

            // ---- Hero: the device on a lit stage ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 176
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.pad
                    spacing: Theme.pad
                    visible: page.primed

                    Item {
                        Layout.preferredWidth: 210; Layout.preferredHeight: 134
                        Layout.alignment: Qt.AlignVCenter
                        opacity: page.reachable ? 1 : 0.45
                        Behavior on opacity { NumberAnimation { duration: Theme.dLong } }
                        // stage: a soft accent pool under the device (light is
                        // state: it glows only while the mouse is reachable)
                        Shape {
                            anchors.centerIn: parent
                            width: 230; height: 90
                            y: parent.height - 62
                            ShapePath {
                                strokeWidth: 0
                                fillGradient: RadialGradient {
                                    centerX: 115; centerY: 45; centerRadius: 115
                                    focalX: 115; focalY: 45
                                    GradientStop { position: 0.0; color: page.reachable ? Theme.accentSubtle : "#20FFFFFF" }
                                    GradientStop { position: 0.6; color: "#00000000" }
                                }
                                startX: 0; startY: 45
                                PathArc { x: 230; y: 45; radiusX: 115; radiusY: 45 }
                                PathArc { x: 0; y: 45; radiusX: 115; radiusY: 45 }
                            }
                        }
                        Image {
                            anchors.centerIn: parent
                            readonly property bool mx3: Backend.deviceName.indexOf("MX Master 3") >= 0
                            source: assetsDir + (mx3 ? "/devices/mx3_quarter.png" : "/devices/mx4_side.png")
                            sourceSize.width: mx3 ? 549 : 1289; sourceSize.height: mx3 ? 804 : 829
                            width: mx3 ? 96 : 200; height: mx3 ? 140 : 128
                            fillMode: Image.PreserveAspectFit
                            smooth: true; asynchronous: true
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        spacing: Theme.gapS
                        Text {
                            text: Backend.deviceName !== "" ? Backend.deviceName : qsTr("No mouse yet")
                            color: Theme.textPrimary
                            font.family: Theme.fontDisplay; font.pixelSize: Theme.fsH1; font.weight: Font.DemiBold
                            Layout.fillWidth: true; elide: Text.ElideRight
                        }
                        Flow {
                            Layout.fillWidth: true
                            spacing: Theme.gapS
                            Badge { text: page.linkText; accent: page.reachable; dot: true }
                            Badge {
                                visible: Backend.activeProfile !== ""
                                text: qsTr("Profile: %1").arg(Backend.activeProfile)
                            }
                            Badge {
                                visible: page.kbOn && (page.kb.battery || 0) > 0
                                text: qsTr("Keyboard %1%").arg(page.kb.battery || 0)
                            }
                        }
                        Text {
                            text: !Backend.daemonAvailable
                                  ? qsTr("Start the background service to control this mouse.")
                                  : (page.reachable ? page.readiness
                                                    : qsTr("Settings you change are saved and applied when the mouse is back."))
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            Layout.fillWidth: true; elide: Text.ElideRight
                        }
                    }

                    Column {
                        Layout.alignment: Qt.AlignVCenter
                        spacing: 4
                        BatteryRing {
                            percent: Backend.battery
                            charging: Backend.charging
                            size: 118
                            opacity: page.reachable ? 1 : 0.6
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            visible: !page.reachable && Backend.battery > 0
                            text: qsTr("last reading")
                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                        }
                    }
                }
                // first load: placeholders until the service has answered
                Row {
                    anchors.fill: parent; anchors.margins: Theme.pad
                    spacing: Theme.pad
                    visible: !page.primed
                    Skeleton { width: 200; height: 120; anchors.verticalCenter: parent.verticalCenter }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 10
                        Skeleton { width: 260; height: 28 }
                        Skeleton { width: 180; height: 20 }
                    }
                }
            }

            // ---- health: what needs a fix, with the fix ----
            Repeater {
                model: page.health
                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 52; radius: Theme.radiusCard
                    color: Theme.dangerSubtle; border.width: 1; border.color: Theme.danger
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 8
                        spacing: Theme.gapS
                        ActionIcon { iconName: "dialog-warning-symbolic"; tint: Theme.danger; px: 18 }
                        Text {
                            Layout.fillWidth: true; elide: Text.ElideRight
                            text: modelData.text
                            color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        PrimaryButton {
                            visible: modelData.id === "daemon"
                            text: qsTr("Start service"); ghost: true
                            onClicked: Backend.restartDaemon()
                        }
                        PrimaryButton {
                            visible: modelData.id === "overlay"
                            text: qsTr("Start it"); ghost: true
                            onClicked: { Backend.restartOverlay(); refreshLater.restart() }
                        }
                        PrimaryButton {
                            visible: modelData.id === "access" || modelData.id === "version"
                            text: qsTr("Open log"); ghost: true
                            onClicked: Backend.openLog()
                        }
                        PrimaryButton {
                            visible: modelData.id === "autostart"
                            text: qsTr("Fix"); ghost: true
                            onClicked: { Backend.setStartAtLogin(true); page.refreshHealth() }
                        }
                        PrimaryButton {
                            text: qsTr("Copy diagnostics"); ghost: true
                            onClicked: Backend.copySystemInfo()
                        }
                    }
                }
            }

            // ---- getting started (first launch) ----
            GlassCard {
                Layout.fillWidth: true
                visible: page.steps.length > 0 && Backend.daemonAvailable
                Layout.preferredHeight: gsCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: gsCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Getting started")
                        subtitle: qsTr("Three things worth trying first. This card goes away when you are done.")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/emblem-ok-symbolic"
                        PrimaryButton { text: qsTr("Done"); ghost: true; onClicked: { Backend.finishOnboarding(); page.bump++ } }
                    }
                    Repeater {
                        model: page.steps
                        Row {
                            required property var modelData
                            spacing: 10
                            Rectangle {
                                width: 20; height: 20; radius: 10
                                anchors.verticalCenter: parent.verticalCenter
                                color: modelData.done ? Theme.accent : "transparent"
                                border.width: 1.5; border.color: modelData.done ? Theme.accent : Theme.borderStrong
                                ActionIcon { anchors.centerIn: parent; visible: modelData.done; iconName: "emblem-ok-symbolic"; tint: Theme.bgBase; px: 12 }
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.id === "ring"
                                      ? (page.ringButton !== "" ? qsTr("Open the Actions Ring: hold the %1").arg(page.ringButton)
                                                                : qsTr("Open the Actions Ring"))
                                      : (modelData.id === "button" ? qsTr("Change what a button does (click a row below)")
                                                                   : qsTr("Pick a wheel skin on the Buttons tab"))
                                color: modelData.done ? Theme.textMuted : Theme.textBody
                                font.strikeout: modelData.done
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                        }
                    }
                }
            }

            // ---- Instrument strip: every live readout in one card ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: strip.implicitHeight + 2
                GridLayout {
                    id: strip
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 1
                    columns: page.width >= 1150 ? 6 : 3
                    rowSpacing: 0; columnSpacing: 0
                    Instrument { icon: "scroll"; value: Backend.dpiSupported ? String(Backend.dpi) : "–"; label: qsTr("DPI"); toTab: "scroll" }
                    Instrument {
                        icon: "scroll"
                        value: {
                            var m = Backend.wheelMode
                            return m === "smartshift" ? qsTr("SmartShift") : m === "ratchet" ? qsTr("Ratchet")
                                 : m === "freespin" ? qsTr("Free-spin") : page._cap(m)
                        }
                        toTab: "scroll"
                        label: qsTr("Wheel mode")
                    }
                    Instrument {
                        icon: "haptics"
                        value: Backend.hapticsEnabled ? qsTr("On") : qsTr("Off"); label: qsTr("Haptics")
                        live: Backend.hapticsEnabled; toTab: "haptics"
                    }
                    Instrument {
                        icon: "easyswitch"
                        value: !Backend.hostsKnown ? qsTr("Unknown")
                               : (Backend.hostNames[Backend.currentHost] || qsTr("Computer %1").arg(Backend.currentHost + 1))
                        label: Backend.hostsKnown ? qsTr("Easy-Switch, %1 of %2").arg(Backend.currentHost + 1).arg(Backend.numHosts)
                                                  : qsTr("Easy-Switch")
                        live: Backend.hostsKnown && Backend.numHosts > 1; toTab: "easyswitch"
                    }
                    Instrument {
                        icon: "gaming"
                        value: Backend.gamingMode ? qsTr("On") : qsTr("Off"); label: qsTr("Gaming mode")
                        live: Backend.gamingMode; toTab: "gaming"
                    }
                    Instrument {
                        icon: "flow"
                        value: (page.bump, Backend.get("flow.enabled", false)) ? qsTr("On") : qsTr("Off"); label: qsTr("Flow")
                        live: (page.bump, Backend.get("flow.enabled", false)); toTab: "flow"
                    }
                }
            }

            // ---- Actions Ring + button map, side by side ----
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap

                GlassCard {
                    id: radialCard
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 340
                    lit: radHov.hovered
                    HoverHandler { id: radHov }
                    Column {
                        anchors.fill: parent; anchors.margins: Theme.padCard
                        spacing: Theme.gapS
                        CardHeader {
                            width: parent.width
                            title: qsTr("Actions Ring")
                            subtitle: page.ringButton !== "" ? qsTr("Opens with: %1 (hold)").arg(page.ringButton)
                                                             : qsTr("No button opens it yet")
                            icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-grid-symbolic"
                            PrimaryButton { text: qsTr("Open Buttons"); ghost: true; onClicked: Backend.goTo("buttons") }
                        }
                        Item {
                            id: ringBox
                            width: parent.width
                            height: parent.height - 56
                            readonly property real rr: Math.min(width, height) * 0.36
                            Image {
                                anchors.centerIn: parent
                                width: Math.min(parent.width, parent.height)
                                height: width
                                visible: page.wheelKey !== "none"
                                source: page.wheelKey !== "none" ? Theme.wheelImage(page.wheelKey) : ""
                                sourceSize.width: 512; sourceSize.height: 512
                                fillMode: Image.PreserveAspectFit; smooth: true
                            }
                            ClassicWheel {
                                anchors.centerIn: parent
                                visible: page.wheelKey === "none"
                                size: Math.min(parent.width, parent.height)
                            }
                            Repeater {
                                model: Slices
                                Item {
                                    id: sl
                                    required property int index
                                    required property string icon
                                    required property string hex
                                    required property string label
                                    required property string actionId
                                    // Easy-Switch shortcuts replace slot 6 on the real ring.
                                    readonly property bool easy: page.easySwitchSlot && index === 5
                                    property string btnImg: (easy || page.mono || icon.startsWith("/")) ? "" : (Theme.iconStyle, Theme.sliceButton(actionId))
                                    width: 38; height: 38
                                    x: ringBox.width / 2 + ringBox.rr * Math.cos((index * 45 - 90) * Math.PI / 180) - width / 2
                                    y: ringBox.height / 2 + ringBox.rr * Math.sin((index * 45 - 90) * Math.PI / 180) - height / 2
                                    activeFocusOnTab: true
                                    Accessible.role: Accessible.Button
                                    Accessible.name: qsTr("Slice %1: %2").arg(index + 1).arg(easy ? qsTr("Easy-Switch") : label)
                                    Keys.onReturnPressed: { sliceEd.row = index; sliceEd.open() }
                                    FocusHalo { active: sl.activeFocus; radius: sl.width / 2 }
                                    Image {
                                        anchors.fill: parent; visible: sl.btnImg !== ""
                                        source: sl.btnImg; sourceSize.width: 128; sourceSize.height: 128
                                        smooth: true; fillMode: Image.PreserveAspectFit
                                    }
                                    Rectangle {
                                        anchors.fill: parent; radius: width / 2
                                        visible: sl.btnImg === ""
                                        color: "#1B1F28"; border.width: 1.5
                                        border.color: page.mono || sl.easy ? Theme.borderStrong : sl.hex
                                    }
                                    ActionIcon {
                                        anchors.centerIn: parent; visible: sl.btnImg === ""
                                        iconName: sl.easy ? "easy-switch" : sl.icon
                                        tint: page.mono || sl.easy ? Theme.textBody : sl.hex; px: 18
                                    }
                                    Rectangle {
                                        anchors.fill: parent; anchors.margins: -3; radius: width / 2
                                        color: "transparent"; border.width: 2; border.color: Theme.accent
                                        opacity: slMa.containsMouse ? 1 : 0
                                        Behavior on opacity { NumberAnimation { duration: Theme.dShort } }
                                    }
                                    MouseArea {
                                        id: slMa; anchors.fill: parent; hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onEntered: page.hoverSlice = sl.index
                                        onExited: if (page.hoverSlice === sl.index) page.hoverSlice = -1
                                        onClicked: { sliceEd.row = sl.index; sliceEd.open() }
                                    }
                                }
                            }
                            // the hovered slice's name in the middle
                            Text {
                                anchors.centerIn: parent
                                width: 90; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                                visible: page.hoverSlice >= 0
                                text: page.hoverSlice < 0 ? ""
                                      : (page.easySwitchSlot && page.hoverSlice === 5 ? qsTr("Easy-Switch")
                                         : Slices.sliceAt(page.hoverSlice).label || "")
                                color: Theme.textPrimary
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                            }
                        }
                    }
                }

                GlassCard {
                    id: bmapCard
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.preferredHeight: 340
                    lit: bmHov.hovered
                    HoverHandler { id: bmHov }
                    Column {
                        anchors.fill: parent; anchors.margins: Theme.padCard
                        spacing: 2
                        CardHeader {
                            width: parent.width
                            title: qsTr("Button map")
                            subtitle: qsTr("Click a button to change it")
                            icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/input-mouse-symbolic"
                            PrimaryButton { text: qsTr("Open Buttons"); ghost: true; onClicked: Backend.goTo("buttons") }
                        }
                        Item { width: 1; height: 4 }
                        Rectangle { width: parent.width; height: 1; color: Theme.border }
                        Repeater {
                            model: Backend.buttonSlots().filter(function (s) { return s.slot !== "horizontal_scroll" })
                            Item {
                                id: mapRow
                                required property var modelData
                                required property int index
                                width: parent.width; height: 38
                                activeFocusOnTab: true
                                Accessible.role: Accessible.Button
                                Accessible.name: modelData.name + ": " + page.actionName(modelData.slot, modelData.default)
                                function edit() {
                                    page.pickSlot = modelData.slot
                                    picker.actions = Backend.buttonActions()
                                    picker.currentId = Backend.buttonAction("", modelData.slot, modelData.default)
                                    picker.title = qsTr("%1 does").arg(modelData.name)
                                    picker.open()
                                }
                                Keys.onReturnPressed: edit()
                                Keys.onSpacePressed: edit()
                                FocusHalo { active: mapRow.activeFocus; radius: 8 }
                                Rectangle {
                                    anchors.fill: parent; anchors.leftMargin: -8; anchors.rightMargin: -8
                                    radius: 8; color: rowMa.containsMouse ? "#12FFFFFF" : "transparent"
                                    Behavior on color { ColorAnimation { duration: Theme.dShort } }
                                }
                                Text {
                                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.name; color: Theme.textBody
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                }
                                Rectangle {
                                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                    radius: 7; color: Theme.accentSubtle
                                    border.width: 1; border.color: Theme.accentFaint
                                    implicitWidth: Math.min(actT.implicitWidth + 18, mapRow.width * 0.6); height: 24
                                    Text {
                                        id: actT; anchors.centerIn: parent
                                        width: Math.min(implicitWidth, mapRow.width * 0.6 - 18); elide: Text.ElideRight
                                        text: page.actionName(modelData.slot, modelData.default)
                                        color: Theme.accent
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                    }
                                }
                                Rectangle {
                                    anchors.bottom: parent.bottom; width: parent.width; height: 1
                                    color: Theme.border; visible: index < 5
                                }
                                MouseArea {
                                    id: rowMa; anchors.fill: parent; hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: mapRow.edit()
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
