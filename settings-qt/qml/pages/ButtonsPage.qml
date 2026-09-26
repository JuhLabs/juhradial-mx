import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import QtQuick.Shapes
import QtQuick.Window
import QtQuick.Controls.Basic as B
import "../components"
import "../components/keys.js" as KeyNames

// Buttons: remap the physical buttons from callout pins on photos of the
// mouse (or a plain list), for all apps, this mouse only, or one app; edit
// the Actions Ring's eight slices; quick links; directional gestures; and any
// other control the mouse reports.
Item {
    id: page
    anchors.fill: parent

    // ---- state ----
    property var actMap: ({})             // action id -> display name
    property string scope: ""             // "" all apps, "@mouse", or an app class
    property var scopes: []
    property string pickSlot: ""          // button being edited
    property int bump: 0                  // re-read bindings after a change
    // "" (fresh install) and "none" both mean the Classic ring.
    property string wheelKey: Backend.get("radial.wheel", "") || "none"
    readonly property bool mono: Theme.iconStyle.startsWith("mono")
    property bool editPins: false         // drag-to-place marker mode
    property string flashSlot: ""         // lit for a moment when pressed on the mouse
    property var macroBinds: ({})         // slot -> {id, name} of a macro bound to it
    property int dirBump: 0
    // MX Master 3/3S share one body; any other named mouse gets the honest
    // list instead of MX Master 4 photos.
    readonly property string devName: Backend.deviceName
    readonly property bool isMx3: devName.indexOf("MX Master 3") >= 0
    readonly property bool knownArt: devName === "" || devName.indexOf("MX Master") >= 0
    readonly property bool listView: !knownArt || page.width < 760
                                     || (page.bump, Backend.get("ui.buttons_list_view", false))
    readonly property bool scopeIsApp: scope !== "" && scope !== "@mouse"
    readonly property string pinKey: isMx3 ? "button_pins.mx3." : "button_pins."
    function pinNx(md) { return Backend.get(pinKey + md.slot + ".nx", md.nx) }
    function pinNy(md) { return Backend.get(pinKey + md.slot + ".ny", md.ny) }
    property var extraControls: []
    // What a plain press of the gesture button does (the D-pad's centre).
    readonly property string gestureClickText:
        (page.bump, actMap[Backend.buttonAction("", "gesture", "virtual_desktops")] || "")

    Connections {
        target: Backend
        function onControlsReady(list) { page.extraControls = list }
        function onAvailabilityChanged() { Backend.requestControls(); Backend.requestMacroBindings() }
        function onButtonPressed(slot) { page.flashSlot = slot; flashTimer.restart() }
        function onMacroBindingsReady(map) { page.macroBinds = map }
        function onMacrosChanged() { Backend.requestMacroBindings() }
        function onConfigReloaded() { page.reloadScopes(); page.bump++ }
    }
    Timer { id: flashTimer; interval: 600; onTriggered: page.flashSlot = "" }

    Component.onCompleted: {
        var a = Backend.buttonActions(), m = {}
        for (var i = 0; i < a.length; i++) m[a[i].id] = a[i].name
        actMap = m
        reloadScopes()
        loadAi()
        Backend.requestControls()
        Backend.requestMacroBindings()
    }
    function reloadScopes() {
        scopes = Backend.buttonScopes()
        if (!scopes.some(function (s) { return s.id === page.scope })) scope = ""
    }

    // ---- the buttons ----
    readonly property var allSlots: [
        { slot: "thumb", def: "radial_menu", label: qsTr("Actions ring") },
        { slot: "gesture", def: "virtual_desktops", label: qsTr("Gesture") },
        { slot: "middle", def: "middle_click", label: qsTr("Wheel click") },
        { slot: "shift_wheel", def: "smartshift", label: qsTr("Mode shift") },
        { slot: "back", def: "back", label: qsTr("Back") },
        { slot: "forward", def: "forward", label: qsTr("Forward") },
        { slot: "horizontal_scroll", def: "scroll_left_right", label: qsTr("Thumb wheel") }
    ]
    function slotInfo(slot) {
        for (var i = 0; i < allSlots.length; i++) if (allSlots[i].slot === slot) return allSlots[i]
        return { slot: slot, def: "none", label: slot }
    }
    // physical buttons placed on each photo (normalized to the image box)
    readonly property var topBtns: [
        { slot: "middle", def: "middle_click", label: qsTr("Wheel click"), nx: 0.626, ny: 0.233, cx: 0.90, cy: 0.12 },
        { slot: "shift_wheel", def: "smartshift", label: qsTr("Mode shift"), nx: 0.62, ny: 0.37, cx: 0.92, cy: 0.46 }
    ]
    readonly property var sideBtns: [
        { slot: "thumb", def: "radial_menu", label: qsTr("Actions ring"), nx: 0.656, ny: 0.644, cx: 0.93, cy: 0.87 },
        { slot: "horizontal_scroll", def: "scroll_left_right", label: qsTr("Thumb wheel"), nx: 0.619, ny: 0.320, cx: 0.11, cy: 0.10 },
        { slot: "forward", def: "forward", label: qsTr("Forward"), nx: 0.730, ny: 0.347, cx: 0.96, cy: 0.24 },
        { slot: "back", def: "back", label: qsTr("Back"), nx: 0.658, ny: 0.461, cx: 0.96, cy: 0.50 },
        { slot: "gesture", def: "virtual_desktops", label: qsTr("Gesture"), nx: 0.569, ny: 0.567, cx: 0.13, cy: 0.87 }
    ]
    readonly property var mx3Btns: [
        { slot: "middle", def: "middle_click", label: qsTr("Wheel click"), nx: 0.60, ny: 0.11, cx: 1.32, cy: 0.08 },
        { slot: "shift_wheel", def: "smartshift", label: qsTr("Mode shift"), nx: 0.59, ny: 0.37, cx: 1.32, cy: 0.36 },
        { slot: "forward", def: "forward", label: qsTr("Forward"), nx: 0.26, ny: 0.35, cx: -0.34, cy: 0.20 },
        { slot: "back", def: "back", label: qsTr("Back"), nx: 0.24, ny: 0.42, cx: -0.34, cy: 0.38 },
        { slot: "horizontal_scroll", def: "scroll_left_right", label: qsTr("Thumb wheel"), nx: 0.30, ny: 0.55, cx: -0.34, cy: 0.56 },
        { slot: "gesture", def: "virtual_desktops", label: qsTr("Gesture"), nx: 0.27, ny: 0.62, cx: -0.34, cy: 0.74 },
        { slot: "thumb", def: "radial_menu", label: qsTr("Actions ring"), nx: 0.28, ny: 0.66, cx: -0.34, cy: 0.92 }
    ]

    // ---- what a button does, as text ----
    function customText(slot) {
        var c = Backend.customAction(page.scope, slot)
        if (!c.kind) return qsTr("Custom action (not set)")
        if (c.kind === "shortcut") return KeyNames.pretty(c.value)
        if (c.label) return c.label
        if (c.kind === "url") return c.value.replace(/^(https?:\/\/|mailto:)/i, "")
        return c.value
    }
    function actionText(slot, def) {
        page.bump
        // The thumb wheel is set by its mode (thumbwheel.mode), not as a button.
        if (slot === "horizontal_scroll") {
            var tw = Backend.thumbwheelMode, modes = Backend.thumbwheelModes()
            for (var k = 0; k < modes.length; k++) if (modes[k].id === tw) return modes[k].name
            return tw
        }
        var id = Backend.buttonAction(page.scope, slot, def)
        var text = id === "custom" ? customText(slot) : (actMap[id] || id)
        if (slot === "gesture" && (page.dirBump, Backend.get("buttons.gesture_directions.enabled", false)))
            text = qsTr("%1 + drag").arg(text)
        return text
    }
    function isChanged(slot, def) {
        page.bump
        if (slot === "horizontal_scroll") return Backend.thumbwheelMode !== "off"
        if (page.scope !== "") return Backend.hasOverride(page.scope, slot)
        return Backend.buttonAction("", slot, def) !== def
    }
    // A macro bound to a remapped button never runs: the remap wins.
    function macroNote(slot, def) {
        page.bump
        var m = page.macroBinds[slot]
        if (!m) return ""
        return Backend.buttonAction("", slot, def) !== def
            ? qsTr("Macro “%1” never runs").arg(m.name) : qsTr("Macro: %1").arg(m.name)
    }
    readonly property var conflicts: {
        page.bump
        var out = []
        for (var i = 0; i < allSlots.length; i++) {
            var s = allSlots[i], m = macroBinds[s.slot]
            if (m && Backend.buttonAction("", s.slot, s.def) !== s.def)
                out.push({ slot: s.slot, def: s.def, label: s.label, macro: m })
        }
        return out
    }

    // ---- editing ----
    function openPickerFor(slot, def) {
        if (slot === "horizontal_scroll") {
            if (page.scopeIsApp) {
                Backend.notify(qsTr("An app's thumb wheel is set on the App profiles tab."), "info")
                return
            }
            twPicker.currentId = Backend.thumbwheelMode
            twPicker.open()
            return
        }
        page.pickSlot = slot
        var list = []
        if (page.scope !== "" && Backend.hasOverride(page.scope, slot))
            list.push({ id: "__follow", name: qsTr("Same as all apps"), icon: "edit-undo-symbolic", groupName: "" })
        else if (page.scope === "" && Backend.buttonAction("", slot, def) !== def)
            list.push({ id: "__default", name: qsTr("Default: %1").arg(actMap[def] || def),
                        icon: "edit-undo-symbolic", groupName: "" })
        var names = Backend.hostNames
        var acts = Backend.buttonActions().map(function (a) {
            var n = ["host1", "host2", "host3"].indexOf(a.id)
            if (n >= 0 && names[n]) a.name = qsTr("Switch to %1").arg(names[n])
            return a
        })
        btnPicker.actions = list.concat(acts)
        btnPicker.currentId = Backend.buttonAction(page.scope, slot, def)
        btnPicker.title = qsTr("%1 does").arg(slotInfo(slot).label)
        btnPicker.open()
    }
    function pick(slot, id) {
        if (id === "__follow" || id === "__default") Backend.restoreButton(page.scope, slot)
        else if (id === "custom") { customEd.openFor(page.scope, slot, slotInfo(slot).label); return }
        else Backend.setButtonIn(page.scope, slot, id)
        page.bump++
    }
    function resetCard() {
        var sc = page.scope
        var snap = Backend.resetButtonMap(sc)
        page.bump++
        Window.window.undoToast(sc === "" ? qsTr("Buttons back to their defaults")
                                          : qsTr("Buttons follow all apps again"),
                                function () { Backend.undoResetButtonMap(sc, snap); page.bump++ })
    }

    ActionPicker {
        id: twPicker
        title: qsTr("Thumb wheel does")
        actions: Backend.thumbwheelModes().map(function (m) { return { id: m.id, name: m.name, icon: "input-mouse-symbolic" } })
        onPicked: (id) => { Backend.setThumbwheelMode(id); page.bump++ }
    }
    ActionPicker {
        id: btnPicker
        onPicked: (id) => page.pick(page.pickSlot, id)
    }
    CustomActionEditor { id: customEd; onSaved: { page.bump++; page.dirBump++ } }
    SliceEditor { id: sliceEd }

    // ---- Quick links editor (each submenu slice's own links) ----
    ListModel { id: aiModel }
    property var linkRows: Backend.submenuRows()
    property int linkRow: linkRows.length ? linkRows[0].row : -1
    function loadAi() {
        aiModel.clear()
        linkRows = Backend.submenuRows()
        if (linkRows.length && !linkRows.some(function (r) { return r.row === linkRow }))
            linkRow = linkRows[0].row
        if (linkRow < 0) return
        var links = Backend.linksFor(linkRow)
        for (var i = 0; i < links.length; i++)
            aiModel.append({ name: links[i].name || "", url: links[i].url || "",
                             icon: links[i].icon || "browser", command: links[i].command || "" })
    }
    function commitAi() {
        var out = []
        for (var i = 0; i < aiModel.count; i++) {
            var it = aiModel.get(i)
            out.push({ name: it.name, url: it.url, icon: it.icon, command: it.command })
        }
        Backend.setLinksFor(page.linkRow, out)
    }
    property int aiPickRow: -1
    AppPicker {
        id: linkAppPicker
        title: qsTr("Open an application from the submenu")
        onPicked: (app) => {
            if (page.aiPickRow < 0) return
            var icon = Backend.cacheAppIcon(app.id)
            aiModel.setProperty(page.aiPickRow, "command", app.command)
            aiModel.setProperty(page.aiPickRow, "url", "")
            aiModel.setProperty(page.aiPickRow, "icon", icon)
            var cur = aiModel.get(page.aiPickRow).name || ""
            if (cur === "" || cur === qsTr("New link"))
                aiModel.setProperty(page.aiPickRow, "name", app.name)
            page.commitAi()
        }
    }

    // One callout on a photo; the same for every view.
    component Callout: MouseCallout {
        required property var modelData
        cx: modelData.cx; cy: modelData.cy
        editable: page.editPins
        label: modelData.label
        action: page.actionText(modelData.slot, modelData.def)
        changed: page.isChanged(modelData.slot, modelData.def)
        note: page.macroNote(modelData.slot, modelData.def)
        selected: page.flashSlot === modelData.slot || (btnPicker.opened && page.pickSlot === modelData.slot)
        Component.onCompleted: { nx = page.pinNx(modelData); ny = page.pinNy(modelData) }
        onClicked: page.openPickerFor(modelData.slot, modelData.def)
    }
    // Soft floor shadow under a product photo.
    component FloorShadow: Shape {
        required property Item img
        property real spread: 1.15
        anchors.horizontalCenter: img.horizontalCenter
        y: img.y + img.height - 70
        width: img.width * spread; height: 110
        ShapePath {
            strokeWidth: 0
            fillGradient: RadialGradient {
                centerX: img.width * spread / 2; centerY: 55
                focalX: img.width * spread / 2; focalY: 55
                centerRadius: img.width * spread / 2
                GradientStop { position: 0.0; color: "#66000000" }
                GradientStop { position: 0.55; color: "#00000000" }
            }
            startX: 0; startY: 55
            PathArc { x: img.width * spread; y: 55; radiusX: img.width * spread / 2; radiusY: 55 }
            PathArc { x: 0; y: 55; radiusX: img.width * spread / 2; radiusY: 55 }
        }
    }
    component ViewLabel: Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        color: Theme.textMuted
        font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
        font.weight: Font.DemiBold; font.letterSpacing: 1.5
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

            // ===== Offline banner =====
            Rectangle {
                Layout.fillWidth: true
                visible: !Backend.daemonAvailable
                implicitHeight: offRow.implicitHeight + 24
                radius: Theme.radiusCard
                color: Theme.dangerSubtle; border.width: 1; border.color: Theme.danger
                RowLayout {
                    id: offRow
                    anchors.fill: parent; anchors.margins: 12
                    spacing: Theme.gap
                    ActionIcon { iconName: "dialog-warning-symbolic"; tint: Theme.danger; px: 20 }
                    Text {
                        Layout.fillWidth: true; wrapMode: Text.WordWrap
                        text: qsTr("The JuhRadial MX service is not running. Changes are saved and apply when it starts.")
                        color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    PrimaryButton {
                        text: qsTr("Troubleshoot"); ghost: true
                        onClicked: Backend.goTo("settings")
                    }
                }
            }

            // ===== Button mapping =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: mapCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: mapCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: qsTr("Button mapping")
                        subtitle: page.knownArt
                                  ? qsTr("Click a marker to reassign a button, or press it on the mouse to find it")
                                  : qsTr("%1: press a button on the mouse to find it in the list").arg(page.devName)
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/input-mouse-symbolic"
                        Row {
                            spacing: 6
                            IconButton {
                                visible: page.knownArt && !page.listView
                                icon: "input-mouse-symbolic"; diameter: 34
                                tint: page.editPins ? Theme.accent : Theme.textMuted
                                tip: page.editPins ? qsTr("Done adjusting markers") : qsTr("Adjust markers")
                                onClicked: page.editPins = !page.editPins
                            }
                            IconButton {
                                visible: page.knownArt && page.width >= 760
                                icon: page.listView ? "view-grid-symbolic" : "view-list-symbolic"; diameter: 34
                                tint: Theme.textMuted
                                tip: page.listView ? qsTr("Show the mouse") : qsTr("Show as a list")
                                onClicked: { Backend.setLocal("ui.buttons_list_view", !page.listView); page.bump++ }
                            }
                            IconButton {
                                icon: "edit-undo-symbolic"; diameter: 34; tint: Theme.textMuted
                                tip: page.scope === "" ? qsTr("Reset all buttons to their defaults")
                                                       : qsTr("Make every button follow all apps")
                                onClicked: page.resetCard()
                            }
                        }
                    }

                    // scope: all apps, this mouse only, or one app
                    RowLayout {
                        width: parent.width
                        spacing: Theme.gap
                        Text {
                            text: qsTr("Editing for")
                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        ComboBox {
                            Layout.preferredWidth: 240
                            accessibleName: qsTr("Editing for")
                            model: page.scopes
                            currentId: page.scope
                            onActivated2: (id) => { page.scope = id; page.bump++ }
                        }
                        Text {
                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                            text: page.scope === ""
                                  ? (page.scopes.length > 1 ? "" : qsTr("Add apps on the App profiles tab to give them their own buttons."))
                                  : (page.scope === "@mouse"
                                     ? qsTr("Only this mouse. Buttons you leave alone follow all apps.")
                                     : qsTr("Only while %1 has focus. Buttons you leave alone follow all apps.").arg(page.scope))
                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    Text {
                        visible: page.editPins && !page.listView
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("Drag each marker onto its button. Positions are saved as you go.")
                        color: Theme.accent; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }

                    // ---- a macro and a remap on the same button ----
                    Repeater {
                        model: page.conflicts
                        Rectangle {
                            required property var modelData
                            width: mapCol.width
                            implicitHeight: cRow.implicitHeight + 16
                            radius: Theme.radiusCtl
                            color: Theme.dangerSubtle; border.width: 1; border.color: Theme.danger
                            RowLayout {
                                id: cRow
                                anchors.fill: parent; anchors.margins: 8; anchors.leftMargin: 12
                                spacing: Theme.gapS
                                Text {
                                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                                    text: qsTr("%1 is remapped, so the macro “%2” bound to it never runs.")
                                          .arg(modelData.label).arg(modelData.macro.name)
                                    color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                }
                                PrimaryButton {
                                    text: qsTr("Keep remap"); ghost: true
                                    onClicked: { Backend.setMacroTrigger(modelData.macro.id, ""); Backend.requestMacroBindings() }
                                }
                                PrimaryButton {
                                    text: qsTr("Keep macro"); ghost: true
                                    onClicked: { Backend.restoreButton("", modelData.slot); page.bump++ }
                                }
                            }
                        }
                    }

                    // ---- list view (narrow windows, other mice, or by choice) ----
                    Column {
                        visible: page.listView
                        width: parent.width
                        Repeater {
                            model: page.allSlots
                            Item {
                                id: lrow
                                required property var modelData
                                width: parent.width; height: srow.height
                                readonly property bool changed: page.isChanged(modelData.slot, modelData.def)
                                // lit for a moment when the button is pressed on the mouse
                                Rectangle {
                                    anchors.fill: parent
                                    anchors.leftMargin: -8; anchors.rightMargin: -8
                                    radius: Theme.radiusCtl
                                    color: Theme.accentSubtle
                                    opacity: page.flashSlot === lrow.modelData.slot ? 1 : 0
                                    Behavior on opacity { NumberAnimation { duration: Theme.dShort } }
                                }
                                SettingRow {
                                    id: srow
                                    width: parent.width
                                    label: lrow.modelData.label
                                    desc: page.actionText(lrow.modelData.slot, lrow.modelData.def)
                                          + (page.macroNote(lrow.modelData.slot, lrow.modelData.def) !== ""
                                             ? " · " + page.macroNote(lrow.modelData.slot, lrow.modelData.def) : "")
                                    Row {
                                        spacing: 6
                                        Rectangle {
                                            visible: lrow.changed
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: 6; height: 6; radius: 3; color: Theme.accent
                                        }
                                        IconButton {
                                            visible: lrow.changed && lrow.modelData.slot !== "horizontal_scroll"
                                            icon: "edit-undo-symbolic"; diameter: 32; tint: Theme.textMuted
                                            tip: page.scope === "" ? qsTr("Back to the default") : qsTr("Follow all apps")
                                            onClicked: { Backend.restoreButton(page.scope, lrow.modelData.slot); page.bump++ }
                                        }
                                        PrimaryButton {
                                            text: qsTr("Change"); ghost: true
                                            onClicked: page.openPickerFor(lrow.modelData.slot, lrow.modelData.def)
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // ---- MX Master 3/3S: one three-quarter photo ----
                    Item {
                        width: parent.width; height: 360
                        visible: page.isMx3 && !page.listView
                        FloorShadow { img: mx3Img; spread: 1.4 }
                        Image {
                            id: mx3Img
                            anchors.centerIn: parent
                            height: parent.height - 44
                            width: height * (549 / 804)
                            source: page.isMx3 ? assetsDir + "/devices/mx3_quarter.png" : ""
                            asynchronous: true
                            sourceSize.width: 549; sourceSize.height: 804
                            fillMode: Image.PreserveAspectFit; smooth: true
                        }
                        Item {
                            anchors.fill: mx3Img
                            Repeater {
                                model: page.isMx3 && !page.listView ? page.mx3Btns : []
                                Callout { onMoved: (mnx, mny) => Backend.setPinPos("mx3." + modelData.slot, mnx, mny) }
                            }
                        }
                        ViewLabel { text: "MX MASTER 3 / 3S" }  // i18n-ignore
                    }

                    // ---- MX Master 4: top + thumb side ----
                    RowLayout {
                        width: parent.width
                        spacing: Theme.gap
                        visible: !page.isMx3 && !page.listView

                        Item {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 300
                            FloorShadow { img: topImg }
                            Image {
                                id: topImg
                                anchors.centerIn: parent
                                height: parent.height - 44
                                width: height * (820 / 1178)
                                source: assetsDir + "/devices/mx4_top.png"
                                asynchronous: true
                                sourceSize.width: 820; sourceSize.height: 1178
                                fillMode: Image.PreserveAspectFit; smooth: true
                            }
                            Item {
                                anchors.fill: topImg
                                Repeater {
                                    model: !page.isMx3 && !page.listView ? page.topBtns : []
                                    Callout { onMoved: (mnx, mny) => Backend.setPinPos(modelData.slot, mnx, mny) }
                                }
                            }
                            ViewLabel { text: qsTr("TOP") }
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1.5
                            Layout.preferredHeight: 300
                            FloorShadow { img: sideImg }
                            Image {
                                id: sideImg
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 24, (parent.height - 44) * (1289 / 829))
                                height: width * (829 / 1289)
                                source: assetsDir + "/devices/mx4_side.png"
                                asynchronous: true
                                sourceSize.width: 1289; sourceSize.height: 829
                                fillMode: Image.PreserveAspectFit; smooth: true
                            }
                            Item {
                                anchors.fill: sideImg
                                Repeater {
                                    model: !page.isMx3 && !page.listView ? page.sideBtns : []
                                    Callout { onMoved: (mnx, mny) => Backend.setPinPos(modelData.slot, mnx, mny) }
                                }
                            }
                            ViewLabel { text: qsTr("THUMB SIDE") }
                        }
                    }
                }
            }

            // ===== Actions Ring =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: ringCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: ringCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: qsTr("Actions Ring")
                        subtitle: qsTr("Eight actions under your thumb. Click a slice to edit it, drag it onto another to swap them.")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-grid-symbolic"
                        PrimaryButton {
                            text: qsTr("Show on screen"); ghost: true
                            onClicked: Backend.showMenuPreview()
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    RowLayout {
                        width: parent.width
                        spacing: Theme.gapL

                        // ---- the 8-slice ring ----
                        Item {
                            id: ring
                            Layout.preferredWidth: 320; Layout.preferredHeight: 320
                            Layout.alignment: Qt.AlignTop
                            readonly property real cx: width / 2
                            readonly property real cy: height / 2
                            readonly property real rr: width * 0.34
                            property int hoverIndex: -1
                            property string hoverLabel: ""
                            property int dragFrom: -1
                            property int dragTo: -1
                            readonly property int litIndex: dragFrom >= 0 ? dragTo : hoverIndex
                            // Slice under a point on the ring (-1 in the centre).
                            function indexAt(p) {
                                var dx = p.x - cx, dy = p.y - cy
                                if (Math.sqrt(dx * dx + dy * dy) < 50) return -1
                                var a = Math.atan2(dy, dx) * 180 / Math.PI + 90
                                return Math.round((((a % 360) + 360) % 360) / 45) % 8
                            }
                            ClassicWheel {
                                anchors.centerIn: parent
                                size: parent.width
                                material: page.wheelKey !== "none" ? Theme.wheelImage(page.wheelKey) : ""
                            }
                            // lit slice: an accent arc rides the ring behind the hovered (or drop) slice
                            Shape {
                                anchors.fill: parent
                                antialiasing: true
                                opacity: ring.litIndex >= 0 ? 1 : 0
                                Behavior on opacity { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
                                ShapePath {
                                    strokeColor: Theme.accent
                                    strokeWidth: 3
                                    fillColor: "transparent"
                                    capStyle: ShapePath.RoundCap
                                    PathAngleArc {
                                        centerX: ring.cx; centerY: ring.cy
                                        radiusX: ring.rr + 44; radiusY: ring.rr + 44
                                        startAngle: Math.max(0, ring.litIndex) * 45 - 90 - 20
                                        sweepAngle: 40
                                        Behavior on startAngle { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
                                    }
                                }
                                ShapePath {
                                    strokeColor: Theme.accentGlow
                                    strokeWidth: 12
                                    fillColor: "transparent"
                                    capStyle: ShapePath.RoundCap
                                    PathAngleArc {
                                        centerX: ring.cx; centerY: ring.cy
                                        radiusX: ring.rr + 44; radiusY: ring.rr + 44
                                        startAngle: Math.max(0, ring.litIndex) * 45 - 90 - 20
                                        sweepAngle: 40
                                        Behavior on startAngle { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
                                    }
                                }
                            }
                            Repeater {
                                model: Slices
                                Item {
                                    id: slot
                                    required property int index
                                    required property string icon
                                    required property string hex
                                    required property string label
                                    required property string actionId
                                    property string btnImg: (page.mono || icon.startsWith("/")) ? "" : (Theme.iconStyle, Theme.sliceButton(actionId))
                                    readonly property bool lit: slotMa.containsMouse || ring.dragTo === index
                                    width: 60; height: 60
                                    property real ang: (index * 45 - 90) * Math.PI / 180
                                    x: ring.cx + ring.rr * Math.cos(ang) - width / 2
                                    y: ring.cy + ring.rr * Math.sin(ang) - height / 2
                                    opacity: ring.dragFrom === index ? 0.45 : 1

                                    activeFocusOnTab: true
                                    Accessible.role: Accessible.Button
                                    Accessible.name: qsTr("Slice %1: %2").arg(index + 1).arg(label)
                                    Accessible.onPressAction: { sliceEd.row = slot.index; sliceEd.open() }
                                    Keys.onReturnPressed: { sliceEd.row = slot.index; sliceEd.open() }
                                    Keys.onSpacePressed: { sliceEd.row = slot.index; sliceEd.open() }
                                    FocusHalo { active: slot.activeFocus; radius: slot.width / 2 }

                                    // glow = state: the hovered button lights in its own colour
                                    RectangularShadow {
                                        anchors.fill: parent
                                        radius: width / 2
                                        blur: slot.lit ? 18 : 10
                                        spread: 0
                                        color: slot.hex
                                        opacity: slot.lit ? 0.75 : 0.28
                                        Behavior on opacity { NumberAnimation { duration: Theme.dShort } }
                                        Behavior on blur { NumberAnimation { duration: Theme.dShort } }
                                    }
                                    // composed button (disc + glyph)
                                    Image {
                                        anchors.fill: parent
                                        visible: slot.btnImg !== ""
                                        source: slot.btnImg
                                        sourceSize.width: 256; sourceSize.height: 256
                                        smooth: true; fillMode: Image.PreserveAspectFit
                                    }
                                    // fallback: dark disc + tinted glyph (also monochrome mode)
                                    Rectangle {
                                        anchors.fill: parent; radius: width / 2
                                        visible: slot.btnImg === ""
                                        color: slot.lit ? "#2B303B" : "#1B1F28"
                                        border.color: page.mono ? Theme.borderStrong : slot.hex
                                        border.width: 2
                                        Behavior on color { ColorAnimation { duration: Theme.dShort } }
                                    }
                                    ActionIcon {
                                        anchors.centerIn: parent
                                        visible: slot.btnImg === ""
                                        iconName: slot.icon
                                        tint: page.mono ? Theme.textBody : slot.hex
                                        px: 34
                                    }
                                    // hover lifts the border, nothing scales
                                    Rectangle {
                                        anchors.fill: parent; anchors.margins: -3
                                        radius: width / 2; color: "transparent"
                                        border.width: 2; border.color: Theme.accent
                                        opacity: slot.lit ? 1 : 0
                                        Behavior on opacity { NumberAnimation { duration: Theme.dShort } }
                                    }
                                    MouseArea {
                                        id: slotMa; anchors.fill: parent; hoverEnabled: true
                                        cursorShape: ring.dragFrom >= 0 ? Qt.ClosedHandCursor : Qt.PointingHandCursor
                                        preventStealing: true
                                        property point start
                                        property bool moved: false
                                        onEntered: { ring.hoverIndex = slot.index; ring.hoverLabel = slot.label }
                                        onExited: if (ring.hoverIndex === slot.index) { ring.hoverIndex = -1; ring.hoverLabel = "" }
                                        onPressed: (m) => { start = Qt.point(m.x, m.y); moved = false }
                                        onPositionChanged: (m) => {
                                            if (!pressed) return
                                            if (!moved && Math.abs(m.x - start.x) + Math.abs(m.y - start.y) > 10) {
                                                moved = true
                                                ring.dragFrom = slot.index
                                            }
                                            if (moved) ring.dragTo = ring.indexAt(mapToItem(ring, m.x, m.y))
                                        }
                                        onReleased: {
                                            if (moved && ring.dragTo >= 0 && ring.dragTo !== slot.index)
                                                Slices.swap(slot.index, ring.dragTo)
                                            ring.dragFrom = -1; ring.dragTo = -1
                                        }
                                        onClicked: if (!moved) { sliceEd.row = slot.index; sliceEd.open() }
                                    }
                                }
                            }
                            Rectangle {
                                anchors.centerIn: parent
                                width: 84; height: 84; radius: 42
                                color: "#33000000"; border.color: ring.litIndex >= 0 ? Theme.accentFaint : Theme.border; border.width: 1
                                Column {
                                    anchors.centerIn: parent; spacing: 1
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: ring.dragFrom >= 0 ? qsTr("swap") : (ring.hoverIndex >= 0 ? ring.hoverLabel : "8")
                                        color: ring.hoverIndex >= 0 || ring.dragFrom >= 0 ? Theme.textPrimary : Theme.textMuted
                                        font.family: ring.hoverIndex >= 0 ? Theme.fontUI : Theme.fontMono
                                        font.pixelSize: ring.hoverIndex >= 0 ? Theme.fsSmall : 20
                                        font.weight: Font.DemiBold
                                        width: Math.min(implicitWidth, 72); elide: Text.ElideRight
                                        horizontalAlignment: Text.AlignHCenter
                                    }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: ring.hoverIndex >= 0 ? qsTr("click to edit") : qsTr("actions")
                                        color: Theme.textMuted
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                    }
                                }
                            }
                        }

                        // ---- wheel skin + ring size ----
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            spacing: Theme.gapS
                            SectionHeader { text: qsTr("Wheel skin"); Layout.topMargin: 4 }
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("The look of the ring. Separate from the app theme: your eight actions never move.")
                                color: Theme.textMuted; wrapMode: Text.WordWrap
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                            WheelPicker {
                                Layout.fillWidth: true
                                current: Backend.wheelSkin
                                onSelected: (key) => { Backend.setWheelSkin(key); page.wheelKey = Backend.get("radial.wheel", "") || "none" }
                            }
                            SettingRow {
                                Layout.fillWidth: true
                                label: qsTr("Ring size")
                                desc: (page.bump, Backend.ringGeometry().auto)
                                      ? qsTr("Automatic: fits each screen")
                                      : qsTr("Your own size, set in Settings")
                                Row {
                                    spacing: Theme.gapS
                                    Toggle {
                                        anchors.verticalCenter: parent.verticalCenter
                                        accessibleName: qsTr("Automatic size")
                                        checked: (page.bump, Backend.ringGeometry().auto)
                                        onToggled: (v) => { Backend.setAutoFit(v); page.bump++ }
                                    }
                                    PrimaryButton {
                                        text: qsTr("More"); ghost: true
                                        onClicked: Backend.openSearchResult("settings", qsTr("Automatic size"))
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ===== Quick links editor =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: aiCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: aiCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: qsTr("Quick links")
                        subtitle: page.linkRows.length
                                  ? qsTr("Up to four links or applications under a submenu slice. Brand sites keep their logo, other links show a globe.")
                                  : qsTr("Give a ring slice the submenu action to add links here.")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/applications-science-symbolic"
                        Row {
                            spacing: Theme.gapS
                            ComboBox {
                                visible: page.linkRows.length > 1
                                width: 180
                                accessibleName: qsTr("Submenu slice")
                                model: page.linkRows.map(function (r) { return { id: String(r.row), name: r.label } })
                                currentId: String(page.linkRow)
                                onActivated2: (id) => { page.linkRow = parseInt(id); page.loadAi() }
                            }
                            Badge { visible: page.linkRow >= 0; text: aiModel.count + "/4"; accent: true }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    // A submenu without links of its own (#118): it starts empty
                    // here, and says what the wheel shows until you add one.
                    Row {
                        visible: page.linkRow >= 0 && aiModel.count === 0
                        width: parent.width
                        spacing: Theme.gapS
                        Text {
                            width: parent.width - editAi.width - Theme.gapS
                            anchors.verticalCenter: parent.verticalCenter
                            wrapMode: Text.WordWrap
                            text: qsTr("While this list is empty the submenu shows the AI assistants: %1.")
                                  .arg(Backend.defaultQuickLinks().map(function (l) { return l.name }).join(", "))
                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        PrimaryButton {
                            id: editAi
                            text: qsTr("Edit the AI links"); ghost: true
                            onClicked: {
                                var links = Backend.defaultQuickLinks()
                                for (var i = 0; i < links.length; i++) aiModel.append(links[i])
                                page.commitAi()
                            }
                        }
                    }

                    Repeater {
                        model: aiModel
                        RowLayout {
                            required property int index
                            required property string name
                            required property string url
                            required property string icon
                            required property string command
                            readonly property bool isApp: command !== ""
                            width: aiCol.width
                            spacing: Theme.gapS
                            ActionIcon {
                                Layout.alignment: Qt.AlignVCenter
                                iconName: isApp && icon.startsWith("/") ? icon : "web-browser-symbolic"
                                tint: Theme.textMuted; px: isApp ? 22 : 18
                            }
                            InputField {
                                Layout.preferredWidth: 160
                                text: name; placeholder: qsTr("Name")
                                onEditingFinished: { aiModel.setProperty(index, "name", text); page.commitAi() }
                            }
                            InputField {
                                Layout.fillWidth: true
                                visible: !isApp
                                mono: true
                                accessibleName: qsTr("Link")
                                text: url; placeholder: "https://"  // i18n-ignore
                                error: (text === "" || text.startsWith("https://") || text.startsWith("http://")) ? "" : qsTr("A link starts with https://")
                                onEditingFinished: { aiModel.setProperty(index, "url", text); page.commitAi() }
                            }
                            // an application row: its command, read-only; clear turns it back into a link
                            Rectangle {
                                Layout.fillWidth: true
                                visible: isApp
                                height: 38; radius: Theme.radiusCtl
                                color: "#0CFFFFFF"; border.color: Theme.border; border.width: 1
                                Text {
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                                    verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                                    text: qsTr("App: %1").arg(command); color: Theme.textMuted
                                    font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                                }
                            }
                            PrimaryButton {
                                text: qsTr("Pick application"); ghost: true
                                Accessible.description: qsTr("Open an application instead")
                                onClicked: { page.aiPickRow = index; linkAppPicker.open() }
                            }
                            IconButton {
                                icon: "edit-clear-symbolic"; tint: Theme.textMuted; diameter: 36
                                tip: isApp ? qsTr("Make it a link again") : qsTr("Remove this link")
                                onClicked: {
                                    if (isApp) {
                                        aiModel.setProperty(index, "command", ""); aiModel.setProperty(index, "icon", "browser")
                                        aiModel.setProperty(index, "url", "https://")
                                    } else {
                                        aiModel.remove(index)
                                    }
                                    page.commitAi()
                                }
                            }
                        }
                    }

                    PrimaryButton {
                        text: qsTr("Add link"); ghost: true
                        enabled: aiModel.count < 4 && page.linkRow >= 0
                        onClicked: { aiModel.append({ name: qsTr("New link"), url: "https://", icon: "browser", command: "" }); page.commitAi() }
                    }
                }
            }

            // ===== Directional gestures (gesture button + drag) =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: dirCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: dirCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    readonly property bool on: (page.dirBump, Backend.get("buttons.gesture_directions.enabled", false))
                    function setDir(key, id) { Backend.set("buttons.gesture_directions." + key, id); page.dirBump++ }
                    function preset(p) {
                        var map = {
                            desktops: { up: "task_switcher", down: "show_desktop", left: "switch_desktop_left", right: "switch_desktop_right" },
                            browser: { up: "tab_reopen", down: "tab_close", left: "back", right: "forward" },
                            editing: { up: "copy", down: "paste", left: "undo", right: "redo" },
                            media: { up: "volume_up", down: "volume_down", left: "mute", right: "play_pause" }
                        }[p]
                        for (var k in map) Backend.setLocal("buttons.gesture_directions." + k, map[k])
                        Backend.reloadConfig()
                        page.dirBump++
                    }
                    CardHeader {
                        width: parent.width
                        title: qsTr("Directional gestures")
                        subtitle: qsTr("Hold the gesture button and drag to run a different action per direction. The corners are optional diagonals. A press without dragging keeps the gesture button's own action.")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-app-grid-symbolic"
                        Toggle {
                            checked: dirCol.on
                            accessibleName: qsTr("Directional gestures")
                            onToggled: (v) => { Backend.set("buttons.gesture_directions.enabled", v); page.dirBump++; page.bump++ }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border; visible: dirCol.on }

                    // presets
                    Flow {
                        visible: dirCol.on
                        width: parent.width; spacing: Theme.gapS
                        Text {
                            height: 38; verticalAlignment: Text.AlignVCenter
                            text: qsTr("Start from")
                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        PrimaryButton { text: qsTr("Desktops"); ghost: true; onClicked: dirCol.preset("desktops") }
                        PrimaryButton { text: qsTr("Browser"); ghost: true; onClicked: dirCol.preset("browser") }
                        PrimaryButton { text: qsTr("Editing"); ghost: true; onClicked: dirCol.preset("editing") }
                        PrimaryButton { text: qsTr("Media"); ghost: true; onClicked: dirCol.preset("media") }
                    }

                    // the D-pad: each direction where the drag goes
                    Grid {
                        visible: dirCol.on
                        anchors.horizontalCenter: parent.horizontalCenter
                        columns: 3; rowSpacing: Theme.gapS; columnSpacing: Theme.gapS
                        horizontalItemAlignment: Grid.AlignHCenter
                        verticalItemAlignment: Grid.AlignVCenter
                        Repeater {
                            // angle: the up arrow turned clockwise to point the way the drag goes
                            model: [
                                { key: "up_left", label: qsTr("Drag up-left"), angle: 315 }, { key: "up", label: qsTr("Drag up"), angle: 0 }, { key: "up_right", label: qsTr("Drag up-right"), angle: 45 },
                                { key: "left", label: qsTr("Drag left"), angle: 270 }, { key: "click" }, { key: "right", label: qsTr("Drag right"), angle: 90 },
                                { key: "down_left", label: qsTr("Drag down-left"), angle: 225 }, { key: "down", label: qsTr("Drag down"), angle: 180 }, { key: "down_right", label: qsTr("Drag down-right"), angle: 135 }
                            ]
                            Item {
                                required property var modelData
                                width: 200; height: 70
                                Column {
                                    visible: modelData.key !== "" && modelData.key !== "click"
                                    anchors.centerIn: parent
                                    spacing: 4
                                    Row {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        spacing: 4
                                        ActionIcon {
                                            anchors.verticalCenter: parent.verticalCenter
                                            iconName: "go-up"; rotation: modelData.angle || 0
                                            tint: Theme.textMuted; px: 14
                                        }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: modelData.label || ""
                                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                        }
                                    }
                                    ComboBox {
                                        width: 196
                                        accessibleName: modelData.label || ""
                                        model: Backend.directionActions()
                                        currentId: (page.dirBump, Backend.get("buttons.gesture_directions." + modelData.key, "none"))
                                        // Custom: the editor saves buttons.custom.gesture_<direction>
                                        // and sets the direction to it (directions are global).
                                        onActivated2: (id) => {
                                            if (id === "custom") customEd.openFor("", "gesture_" + modelData.key, modelData.label)
                                            else dirCol.setDir(modelData.key, id)
                                        }
                                    }
                                }
                                Rectangle {
                                    visible: modelData.key === "click"
                                    anchors.centerIn: parent
                                    width: 150; height: 56; radius: Theme.radiusCtl
                                    color: Theme.surfaceInset; border.width: 1; border.color: Theme.border
                                    Column {
                                        anchors.centerIn: parent; spacing: 2
                                        Text {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: qsTr("Press without dragging")
                                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                        }
                                        Text {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            width: Math.min(implicitWidth, 136); elide: Text.ElideRight
                                            text: page.gestureClickText
                                            color: Theme.textBody; font.family: Theme.fontUI
                                            font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                        }
                                    }
                                }
                            }
                        }
                    }
                    SettingRow {
                        visible: dirCol.on
                        label: qsTr("Drag distance")
                        desc: qsTr("Sensor counts at 1000 DPI below which a press is a click, scaled to the mouse's current DPI so the same flick registers at any DPI. 15 is about 0.4 mm; forward and back drags are short, so keep it low.")
                        Slider {
                            width: 200; from: 1; to: 400; showValue: true; suffix: ""
                            value: Backend.get("buttons.gesture_directions.threshold_px", 15)
                            onCommitted: (v) => Backend.set("buttons.gesture_directions.threshold_px", Math.round(v))
                        }
                    }
                }
            }

            // ===== Other controls (the mouse's own REPROG_CONTROLS_V4 inventory) =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: extraCol.implicitHeight + Theme.padCard * 2
                visible: page.extraControls.length > 0
                Column {
                    id: extraCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Other controls")
                        subtitle: qsTr("Buttons this mouse reports that have no marker above. Assign an action to divert one; Disabled leaves it native.")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/input-mouse-symbolic"
                        Badge { text: qsTr("%n found", "", page.extraControls.length); accent: true }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Repeater {
                        model: page.extraControls
                        Column {
                            required property var modelData
                            required property int index
                            width: parent.width
                            spacing: Theme.gapS
                            SettingRow {
                                label: modelData.name
                                desc: modelData.raw_xy ? qsTr("Reports raw movement") : ""
                                Accessible.description: modelData.hex
                                ComboBox {
                                    width: 220
                                    accessibleName: modelData.name
                                    model: Backend.gestureActions()
                                    currentId: (page.bump, Backend.buttonAction(page.scope, modelData.hex, "none"))
                                    onActivated2: (id) => { Backend.setButtonIn(page.scope, modelData.hex, id); page.bump++ }
                                }
                            }
                            Rectangle { width: parent.width; height: 1; color: Theme.border
                                        visible: index < page.extraControls.length - 1 }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true; Layout.preferredHeight: 4 }
        }
    }
}
