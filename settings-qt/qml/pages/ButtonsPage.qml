import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import QtQuick.Shapes
import QtQuick.Controls.Basic as B
import "../components"

// Buttons: remap the physical buttons by clicking callout pins on real photos of
// the mouse (top + thumb-side), and edit the 8-slice radial menu with an
// independent wheel skin. The whole page is the "amazing user-friendly" map.
Item {
    id: page
    anchors.fill: parent

    // id -> display name for physical button actions
    property var actMap: ({})
    property string pickSlot: ""          // which physical button is being edited
    property int pickSlice: -1            // which radial slice is being edited
    property string wheelKey: Backend.get("radial.wheel", "none")
    readonly property bool mono: Theme.iconStyle === "mono"
    property bool editPins: false        // drag-to-place marker mode
    // MX Master 3/3S share one body, distinct from the MX Master 4 photos and
    // callout positions (GetDeviceName decides, like the GTK app).
    readonly property bool isMx3: Backend.deviceName.indexOf("MX Master 3") >= 0
    readonly property string pinKey: isMx3 ? "button_pins.mx3." : "button_pins."
    function pinNx(md) { return Backend.get(pinKey + md.slot + ".nx", md.nx) }
    function pinNy(md) { return Backend.get(pinKey + md.slot + ".ny", md.ny) }
    property int dirBump: 0              // nudge the gesture callout after a directional change
    // Controls the mouse reports beyond the named slots (ListControls);
    // re-read when the daemon comes back or the device name refreshes.
    property var extraControls: Backend.extraControls()
    Connections {
        target: Backend
        function onLiveChanged() { page.extraControls = Backend.extraControls() }
        function onAvailabilityChanged() { page.extraControls = Backend.extraControls() }
    }

    Component.onCompleted: {
        var a = Backend.buttonActions(), m = {}
        for (var i = 0; i < a.length; i++) m[a[i].id] = a[i].name
        actMap = m
        loadAi()
    }
    function actionName(slot, def) {
        var id = Backend.get("buttons." + slot, def)
        var text = actMap[id] || id
        if (slot === "gesture" && (page.dirBump, Backend.get("buttons.gesture_directions.enabled", false)))
            text += " + drag"
        return text
    }

    // ---- AI quick-links editor (the AI slice's submenu) ----
    ListModel { id: aiModel }
    function loadAi() {
        aiModel.clear()
        var links = Backend.aiLinks()
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
        Backend.setAiLinks(out)
    }
    property int aiPickRow: -1
    AppPicker {
        id: linkAppPicker
        title: "Open an application from the submenu"
        onPicked: (app) => {
            if (page.aiPickRow < 0) return
            var icon = Backend.cacheAppIcon(app.id)
            aiModel.setProperty(page.aiPickRow, "command", app.command)
            aiModel.setProperty(page.aiPickRow, "url", "")
            aiModel.setProperty(page.aiPickRow, "icon", icon)
            if ((aiModel.get(page.aiPickRow).name || "") === "" || aiModel.get(page.aiPickRow).name === "New link")
                aiModel.setProperty(page.aiPickRow, "name", app.name)
            page.commitAi()
        }
    }

    // physical buttons placed on each photo (normalized to the image box)
    readonly property var topBtns: [
        { slot: "middle", def: "middle_click", label: "Wheel click", nx: 0.626, ny: 0.233, cx: 0.90, cy: 0.12 },
        { slot: "shift_wheel", def: "smartshift", label: "Mode shift", nx: 0.62, ny: 0.37, cx: 0.92, cy: 0.46 }
    ]
    readonly property var sideBtns: [
        { slot: "thumb", def: "radial_menu", label: "Actions ring", nx: 0.656, ny: 0.644, cx: 0.93, cy: 0.87 },
        { slot: "horizontal_scroll", def: "scroll_left_right", label: "Thumb wheel", nx: 0.619, ny: 0.320, cx: 0.11, cy: 0.10 },
        { slot: "forward", def: "forward", label: "Forward", nx: 0.730, ny: 0.347, cx: 0.96, cy: 0.24 },
        { slot: "back", def: "back", label: "Back", nx: 0.658, ny: 0.461, cx: 0.96, cy: 0.50 },
        { slot: "gesture", def: "virtual_desktops", label: "Gesture", nx: 0.569, ny: 0.567, cx: 0.13, cy: 0.87 }
    ]

    readonly property var mx3Btns: [
        { slot: "middle", def: "middle_click", label: "Wheel click", nx: 0.60, ny: 0.11, cx: 1.32, cy: 0.08 },
        { slot: "shift_wheel", def: "smartshift", label: "Mode shift", nx: 0.59, ny: 0.37, cx: 1.32, cy: 0.36 },
        { slot: "forward", def: "forward", label: "Forward", nx: 0.26, ny: 0.35, cx: -0.34, cy: 0.20 },
        { slot: "back", def: "back", label: "Back", nx: 0.24, ny: 0.42, cx: -0.34, cy: 0.38 },
        { slot: "horizontal_scroll", def: "scroll_left_right", label: "Thumb wheel", nx: 0.30, ny: 0.55, cx: -0.34, cy: 0.56 },
        { slot: "gesture", def: "virtual_desktops", label: "Gesture", nx: 0.27, ny: 0.62, cx: -0.34, cy: 0.74 },
        { slot: "thumb", def: "radial_menu", label: "Actions ring", nx: 0.28, ny: 0.66, cx: -0.34, cy: 0.92 }
    ]

    ActionPicker {
        id: btnPicker
        title: "Assign button"
        actions: Backend.buttonActions()
        onPicked: (id) => { if (page.pickSlot !== "") { Backend.setButton(page.pickSlot, id); page.actMapBump++ } }
    }
    SliceEditor { id: sliceEd }
    property int actMapBump: 0   // nudge callout bindings after a button change

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

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
                        title: "Button mapping"
                        subtitle: "Click any marker on the mouse to reassign that button"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/input-mouse-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    // ---- MX Master 3/3S: one three-quarter photo ----
                    Item {
                        width: parent.width; height: 360
                        visible: page.isMx3
                        Shape {
                            anchors.horizontalCenter: mx3Img.horizontalCenter
                            y: mx3Img.y + mx3Img.height - 70
                            width: mx3Img.width * 1.4; height: 110
                            ShapePath {
                                strokeWidth: 0
                                fillGradient: RadialGradient {
                                    centerX: mx3Img.width * 0.7; centerY: 55
                                    focalX: mx3Img.width * 0.7; focalY: 55
                                    centerRadius: mx3Img.width * 0.7
                                    GradientStop { position: 0.0; color: "#66000000" }
                                    GradientStop { position: 0.55; color: "#00000000" }
                                }
                                startX: 0; startY: 55
                                PathArc { x: mx3Img.width * 1.4; y: 55; radiusX: mx3Img.width * 0.7; radiusY: 55 }
                                PathArc { x: 0; y: 55; radiusX: mx3Img.width * 0.7; radiusY: 55 }
                            }
                        }
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
                                model: page.isMx3 ? page.mx3Btns : []
                                MouseCallout {
                                    required property var modelData
                                    cx: modelData.cx; cy: modelData.cy
                                    editable: page.editPins
                                    Component.onCompleted: { nx = page.pinNx(modelData); ny = page.pinNy(modelData) }
                                    onMoved: (mnx, mny) => Backend.setPinPos("mx3." + modelData.slot, mnx, mny)
                                    label: modelData.label
                                    action: (page.actMapBump, page.actionName(modelData.slot, modelData.def))
                                    onClicked: {
                                        page.pickSlot = modelData.slot
                                        btnPicker.currentId = Backend.get("buttons." + modelData.slot, modelData.def)
                                        btnPicker.open()
                                    }
                                }
                            }
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom
                            text: "MX MASTER 3 / 3S"; color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                            font.weight: Font.DemiBold; font.letterSpacing: 1.5
                        }
                    }

                    RowLayout {
                        width: parent.width
                        spacing: Theme.gap
                        visible: !page.isMx3

                        // ---- top view ----
                        Item {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 300
                            Shape {
                                anchors.horizontalCenter: topImg.horizontalCenter
                                y: topImg.y + topImg.height - 70
                                width: topImg.width * 1.15; height: 110
                                ShapePath {
                                    strokeWidth: 0
                                    fillGradient: RadialGradient {
                                        centerX: topImg.width * 0.575; centerY: 55
                                        focalX: topImg.width * 0.575; focalY: 55
                                        centerRadius: topImg.width * 0.575
                                        GradientStop { position: 0.0; color: "#66000000" }
                                        GradientStop { position: 0.55; color: "#00000000" }
                                    }
                                    startX: 0; startY: 55
                                    PathArc { x: topImg.width * 1.15; y: 55; radiusX: topImg.width * 0.575; radiusY: 55 }
                                    PathArc { x: 0; y: 55; radiusX: topImg.width * 0.575; radiusY: 55 }
                                }
                            }
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
                                    model: page.topBtns
                                    MouseCallout {
                                        required property var modelData
                                        cx: modelData.cx; cy: modelData.cy
                                        editable: page.editPins
                                        Component.onCompleted: { nx = page.pinNx(modelData); ny = page.pinNy(modelData) }
                                        onMoved: (mnx, mny) => Backend.setPinPos(modelData.slot, mnx, mny)
                                        label: modelData.label
                                        action: (page.actMapBump, page.actionName(modelData.slot, modelData.def))
                                        onClicked: {
                                            page.pickSlot = modelData.slot
                                            btnPicker.currentId = Backend.get("buttons." + modelData.slot, modelData.def)
                                            btnPicker.open()
                                        }
                                    }
                                }
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom
                                text: "TOP"; color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                font.weight: Font.DemiBold; font.letterSpacing: 1.5
                            }
                        }

                        // ---- thumb-side view ----
                        Item {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1.5
                            Layout.preferredHeight: 300
                            Shape {
                                anchors.horizontalCenter: sideImg.horizontalCenter
                                y: sideImg.y + sideImg.height - 70
                                width: sideImg.width * 1.15; height: 110
                                ShapePath {
                                    strokeWidth: 0
                                    fillGradient: RadialGradient {
                                        centerX: sideImg.width * 0.575; centerY: 55
                                        focalX: sideImg.width * 0.575; focalY: 55
                                        centerRadius: sideImg.width * 0.575
                                        GradientStop { position: 0.0; color: "#66000000" }
                                        GradientStop { position: 0.55; color: "#00000000" }
                                    }
                                    startX: 0; startY: 55
                                    PathArc { x: sideImg.width * 1.15; y: 55; radiusX: sideImg.width * 0.575; radiusY: 55 }
                                    PathArc { x: 0; y: 55; radiusX: sideImg.width * 0.575; radiusY: 55 }
                                }
                            }
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
                                    model: page.sideBtns
                                    MouseCallout {
                                        required property var modelData
                                        cx: modelData.cx; cy: modelData.cy
                                        editable: page.editPins
                                        Component.onCompleted: { nx = page.pinNx(modelData); ny = page.pinNy(modelData) }
                                        onMoved: (mnx, mny) => Backend.setPinPos(modelData.slot, mnx, mny)
                                        label: modelData.label
                                        action: (page.actMapBump, page.actionName(modelData.slot, modelData.def))
                                        onClicked: {
                                            page.pickSlot = modelData.slot
                                            btnPicker.currentId = Backend.get("buttons." + modelData.slot, modelData.def)
                                            btnPicker.open()
                                        }
                                    }
                                }
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom
                                text: "THUMB SIDE"; color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                font.weight: Font.DemiBold; font.letterSpacing: 1.5
                            }
                        }
                    }
                }
            }

            // ===== Other controls (from the mouse's own REPROG_CONTROLS_V4 inventory) =====
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
                        title: "Other controls"
                        subtitle: "Buttons this mouse reports that have no marker above. Assign an action to divert one; Disabled leaves it native."
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/input-mouse-symbolic"
                        Badge { text: page.extraControls.length + " found"; accent: true }
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
                                desc: "Control " + modelData.hex + (modelData.raw_xy ? ", reports raw movement" : "")
                                ComboBox {
                                    width: 220
                                    model: Backend.buttonActions()
                                    currentId: Backend.get(modelData.key, "none")
                                    onActivated2: (id) => Backend.set(modelData.key, id)
                                }
                            }
                            Rectangle { width: parent.width; height: 1; color: Theme.border
                                        visible: index < page.extraControls.length - 1 }
                        }
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
                    spacing: Theme.gapS
                    readonly property bool on: (page.dirBump, Backend.get("buttons.gesture_directions.enabled", false))
                    CardHeader {
                        width: parent.width
                        title: "Directional gestures"
                        subtitle: "Hold the gesture button and drag to run a different action per direction. A press without dragging keeps the gesture button's own action."
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-app-grid-symbolic"
                        Toggle {
                            checked: dirCol.on
                            onToggled: (v) => { Backend.set("buttons.gesture_directions.enabled", v); page.dirBump++; page.actMapBump++ }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Repeater {
                        model: [
                            { key: "up", label: "Drag up" }, { key: "down", label: "Drag down" },
                            { key: "left", label: "Drag left" }, { key: "right", label: "Drag right" }
                        ]
                        Column {
                            required property var modelData
                            width: parent.width
                            spacing: Theme.gapS
                            SettingRow {
                                label: modelData.label
                                enabled: dirCol.on
                                opacity: dirCol.on ? 1.0 : 0.5
                                ComboBox {
                                    width: 220
                                    model: Backend.buttonActions()
                                    currentId: Backend.get("buttons.gesture_directions." + modelData.key, "none")
                                    onActivated2: (id) => Backend.set("buttons.gesture_directions." + modelData.key, id)
                                }
                            }
                            Rectangle { width: parent.width; height: 1; color: Theme.border }
                        }
                    }
                    SettingRow {
                        label: "Drag distance"
                        desc: "Movement below this many pixels counts as a click"
                        enabled: dirCol.on
                        opacity: dirCol.on ? 1.0 : 0.5
                        Slider {
                            width: 200; from: 10; to: 400; showValue: true; suffix: " px"
                            value: Backend.get("buttons.gesture_directions.threshold_px", 40)
                            onCommitted: (v) => Backend.set("buttons.gesture_directions.threshold_px", Math.round(v / 5) * 5)
                        }
                    }
                }
            }

            // ===== Radial menu =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: radialRow.implicitHeight + headRadial.implicitHeight + Theme.padCard * 2 + Theme.gap
                Column {
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        id: headRadial
                        width: parent.width
                        title: "Radial menu"
                        subtitle: "Eight actions under your thumb"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-grid-symbolic"
                        Badge { text: "Click a slice to edit"; accent: true; dot: true }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    RowLayout {
                        id: radialRow
                        width: parent.width
                        spacing: Theme.gapL

                        // ---- the 8-slice ring ----
                        Item {
                            id: ring
                            Layout.preferredWidth: 320; Layout.preferredHeight: 320
                            readonly property real cx: width / 2
                            readonly property real cy: height / 2
                            readonly property real rr: width * 0.34
                            property int hoverIndex: -1
                            property string hoverLabel: ""
                            Image {
                                anchors.centerIn: parent
                                width: parent.width; height: parent.height
                                visible: page.wheelKey !== "none"
                                source: page.wheelKey !== "none" ? Theme.wheelImage(page.wheelKey) : ""
                                sourceSize.width: 512; sourceSize.height: 512
                                smooth: true; fillMode: Image.PreserveAspectFit
                            }
                            ClassicWheel {
                                anchors.centerIn: parent
                                visible: page.wheelKey === "none"
                                size: parent.width
                            }
                            // lit slice: an accent arc rides the ring behind the hovered button
                            Shape {
                                anchors.fill: parent
                                antialiasing: true
                                opacity: ring.hoverIndex >= 0 ? 1 : 0
                                Behavior on opacity { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
                                ShapePath {
                                    strokeColor: Theme.accent
                                    strokeWidth: 3
                                    fillColor: "transparent"
                                    capStyle: ShapePath.RoundCap
                                    PathAngleArc {
                                        centerX: ring.cx; centerY: ring.cy
                                        radiusX: ring.rr + 44; radiusY: ring.rr + 44
                                        startAngle: Math.max(0, ring.hoverIndex) * 45 - 90 - 20
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
                                        startAngle: Math.max(0, ring.hoverIndex) * 45 - 90 - 20
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
                                    width: 60; height: 60
                                    property real ang: (index * 45 - 90) * Math.PI / 180
                                    x: ring.cx + ring.rr * Math.cos(ang) - width / 2
                                    y: ring.cy + ring.rr * Math.sin(ang) - height / 2
                                    scale: slotMa.containsMouse ? 1.12 : 1.0
                                    Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }

                                    // glow = state: the hovered button lights in its own colour
                                    RectangularShadow {
                                        anchors.fill: parent
                                        radius: width / 2
                                        blur: slotMa.containsMouse ? 18 : 10
                                        spread: 0
                                        color: slot.hex
                                        opacity: slotMa.containsMouse ? 0.75 : 0.28
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
                                        color: slotMa.containsMouse ? "#2B303B" : "#1B1F28"
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
                                    MouseArea {
                                        id: slotMa; anchors.fill: parent; hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onEntered: { ring.hoverIndex = slot.index; ring.hoverLabel = slot.label }
                                        onExited: if (ring.hoverIndex === slot.index) { ring.hoverIndex = -1; ring.hoverLabel = "" }
                                        onClicked: {
                                            sliceEd.row = slot.index
                                            sliceEd.open()
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                anchors.centerIn: parent
                                width: 84; height: 84; radius: 42
                                color: "#33000000"; border.color: ring.hoverIndex >= 0 ? Theme.accentFaint : Theme.border; border.width: 1
                                Column {
                                    anchors.centerIn: parent; spacing: 1
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: ring.hoverIndex >= 0 ? ring.hoverLabel : "8"
                                        color: ring.hoverIndex >= 0 ? Theme.textPrimary : Theme.textMuted
                                        font.family: ring.hoverIndex >= 0 ? Theme.fontUI : Theme.fontMono
                                        font.pixelSize: ring.hoverIndex >= 0 ? Theme.fsSmall : 20
                                        font.weight: Font.DemiBold
                                        width: Math.min(implicitWidth, 72); elide: Text.ElideRight
                                        horizontalAlignment: Text.AlignHCenter
                                    }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: ring.hoverIndex >= 0 ? "click to edit" : "actions"
                                        color: Theme.textMuted
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                    }
                                }
                            }
                        }

                        // ---- wheel skin + hint ----
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            spacing: Theme.gapS
                            SectionHeader { text: "Wheel skin"; Layout.topMargin: 4 }
                            Text {
                                Layout.fillWidth: true
                                text: "Pick the look of the radial wheel. This is separate from the app color theme, your eight actions never move."
                                color: Theme.textMuted; wrapMode: Text.WordWrap
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                            WheelPicker {
                                Layout.fillWidth: true
                                current: page.wheelKey
                                onSelected: (key) => { page.wheelKey = key; Backend.set("radial.wheel", key) }
                            }
                        }
                    }
                }
            }

            // ===== AI quick-links editor =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: aiCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: aiCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: "AI Assistant links"
                        subtitle: "Up to four links or applications under the AI slice. Brand sites keep their logo, other links show a globe."
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/applications-science-symbolic"
                        Badge { text: aiModel.count + "/4"; accent: true }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

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
                                id: nf
                                Layout.preferredWidth: 160
                                text: name; placeholder: "Name"
                                onEditingFinished: { aiModel.setProperty(index, "name", text); page.commitAi() }
                            }
                            InputField {
                                id: uf
                                Layout.fillWidth: true
                                visible: !isApp
                                mono: true
                                text: url; placeholder: "https://"
                                error: (text === "" || text.startsWith("https://") || text.startsWith("http://")) ? "" : "Link must start with https://"
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
                                    text: "App: " + command; color: Theme.textMuted
                                    font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                                }
                            }
                            IconButton {
                                icon: "application-x-executable-symbolic"; tint: Theme.textMuted; diameter: 36
                                onClicked: { page.aiPickRow = index; linkAppPicker.open() }
                            }
                            IconButton {
                                icon: "edit-clear-symbolic"; tint: Theme.textMuted; diameter: 36
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
                        text: "Add link"; ghost: true
                        enabled: aiModel.count < 4
                        onClicked: { aiModel.append({ name: "New link", url: "https://", icon: "browser", command: "" }); page.commitAi() }
                    }
                }
            }

            Item { Layout.fillHeight: true; Layout.preferredHeight: 4 }
        }
    }
}
