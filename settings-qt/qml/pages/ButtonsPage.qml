import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
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
    property string wheelKey: Backend.get("radial.wheel", "azure")
    property bool mono: Backend.get("radial.monochrome_icons", false)
    property bool editPins: false        // drag-to-place marker mode
    function pinNx(md) { return Backend.get("button_pins." + md.slot + ".nx", md.nx) }
    function pinNy(md) { return Backend.get("button_pins." + md.slot + ".ny", md.ny) }

    Component.onCompleted: {
        var a = Backend.buttonActions(), m = {}
        for (var i = 0; i < a.length; i++) m[a[i].id] = a[i].name
        actMap = m
        loadAi()
    }
    function actionName(slot, def) {
        var id = Backend.get("buttons." + slot, def)
        return actMap[id] || id
    }

    // ---- AI quick-links editor (the AI slice's submenu) ----
    ListModel { id: aiModel }
    function loadAi() {
        aiModel.clear()
        var links = Backend.aiLinks()
        for (var i = 0; i < links.length; i++)
            aiModel.append({ name: links[i].name || "", url: links[i].url || "",
                             icon: links[i].icon || "browser" })
    }
    function commitAi() {
        var out = []
        for (var i = 0; i < aiModel.count; i++) {
            var it = aiModel.get(i)
            out.push({ name: it.name, url: it.url, icon: it.icon })
        }
        Backend.setAiLinks(out)
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
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/input-mouse-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    RowLayout {
                        width: parent.width
                        spacing: Theme.gap

                        // ---- top view ----
                        Item {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 300
                            Image {
                                id: topImg
                                anchors.centerIn: parent
                                height: parent.height - 44
                                width: height * (820 / 1178)
                                source: assetsDir + "/devices/mx4_top.png"
                                sourceSize.width: 820; sourceSize.height: 1178
                                fillMode: Image.PreserveAspectFit; smooth: true
                                layer.enabled: true
                                layer.effect: MultiEffect {
                                    shadowEnabled: true
                                    shadowColor: "#000000"
                                    shadowBlur: 0.7
                                    shadowOpacity: 0.45
                                    shadowHorizontalOffset: 0
                                    shadowVerticalOffset: 0
                                }
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
                            Image {
                                id: sideImg
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 24, (parent.height - 44) * (1289 / 829))
                                height: width * (829 / 1289)
                                source: assetsDir + "/devices/mx4_side.png"
                                sourceSize.width: 1289; sourceSize.height: 829
                                fillMode: Image.PreserveAspectFit; smooth: true
                                layer.enabled: true
                                layer.effect: MultiEffect {
                                    shadowEnabled: true
                                    shadowColor: "#000000"
                                    shadowBlur: 0.7
                                    shadowOpacity: 0.45
                                    shadowHorizontalOffset: 0
                                    shadowVerticalOffset: 0
                                }
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
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/view-grid-symbolic"
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
                            Image {
                                anchors.centerIn: parent
                                width: parent.width; height: parent.height
                                source: Theme.wheelImage(page.wheelKey)
                                sourceSize.width: 512; sourceSize.height: 512
                                smooth: true; fillMode: Image.PreserveAspectFit
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
                                    property string btnImg: page.mono ? "" : Theme.sliceButton(actionId)
                                    width: 60; height: 60
                                    property real ang: (index * 45 - 90) * Math.PI / 180
                                    x: ring.cx + ring.rr * Math.cos(ang) - width / 2
                                    y: ring.cy + ring.rr * Math.sin(ang) - height / 2
                                    scale: slotMa.containsMouse ? 1.12 : 1.0
                                    Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }

                                    // custom generated button (fills the circle) with a soft glow
                                    Image {
                                        anchors.fill: parent
                                        visible: slot.btnImg !== ""
                                        source: slot.btnImg
                                        sourceSize.width: 256; sourceSize.height: 256
                                        smooth: true; fillMode: Image.PreserveAspectFit
                                        layer.enabled: slot.btnImg !== ""
                                        layer.effect: MultiEffect {
                                            shadowEnabled: true
                                            shadowColor: slot.hex
                                            shadowBlur: slotMa.containsMouse ? 0.9 : 0.45
                                            shadowOpacity: slotMa.containsMouse ? 0.85 : 0.5
                                            shadowHorizontalOffset: 0
                                            shadowVerticalOffset: 0
                                            Behavior on shadowBlur { NumberAnimation { duration: Theme.dShort } }
                                        }
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
                                        onClicked: {
                                            sliceEd.row = slot.index
                                            sliceEd.open()
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                anchors.centerIn: parent
                                width: 70; height: 70; radius: 35
                                color: "#22000000"; border.color: Theme.border; border.width: 1
                                Text {
                                    anchors.centerIn: parent; text: "8"
                                    color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: 20
                                    font.weight: Font.DemiBold
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
                        subtitle: "Opens from the AI slice. Brand sites keep their logo; custom links show a globe."
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/applications-science-symbolic"
                        Badge { text: aiModel.count + "/6"; accent: true }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    Repeater {
                        model: aiModel
                        RowLayout {
                            required property int index
                            required property string name
                            required property string url
                            width: aiCol.width
                            spacing: Theme.gapS
                            Rectangle {
                                Layout.preferredWidth: 150; Layout.preferredHeight: 38
                                radius: Theme.radiusCtl; color: "#14FFFFFF"
                                border.color: nf.activeFocus ? Theme.accent : Theme.border; border.width: 1
                                B.TextField {
                                    id: nf
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 6
                                    text: name; placeholderText: "Name"; placeholderTextColor: Theme.textMuted
                                    color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                    verticalAlignment: Text.AlignVCenter; background: Item {}
                                    onEditingFinished: { aiModel.setProperty(index, "name", text); page.commitAi() }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true; Layout.preferredHeight: 38
                                radius: Theme.radiusCtl; color: "#14FFFFFF"
                                border.color: uf.activeFocus ? Theme.accent : Theme.border; border.width: 1
                                B.TextField {
                                    id: uf
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 6
                                    text: url; placeholderText: "https://…"; placeholderTextColor: Theme.textMuted
                                    color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                    verticalAlignment: Text.AlignVCenter; background: Item {}
                                    onEditingFinished: { aiModel.setProperty(index, "url", text); page.commitAi() }
                                }
                            }
                            IconButton {
                                icon: "edit-clear-symbolic"; tint: Theme.textMuted; diameter: 36
                                onClicked: { aiModel.remove(index); page.commitAi() }
                            }
                        }
                    }

                    PrimaryButton {
                        text: "Add link"; ghost: true
                        enabled: aiModel.count < 6
                        onClicked: { aiModel.append({ name: "New link", url: "https://", icon: "browser" }); page.commitAi() }
                    }
                }
            }

            Item { Layout.fillHeight: true; Layout.preferredHeight: 4 }
        }
    }
}
