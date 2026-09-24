import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Dialogs
import QtQuick.Controls.Basic as B
import "../components"
import "../components/keys.js" as KeyNames

// Macros: record what you type (live feed of the keys and the keyboards being
// read), review the recording and name it, then keep a library of macros to
// run, edit, bind to a mouse button, export or delete (with Undo). A ring
// slice or any button can run one too ("Run macro" / custom action).
Item {
    id: root
    anchors.fill: parent

    property var macros: []
    readonly property bool hasMacros: macros && macros.length > 0
    property var status: ({})           // live recording status
    property var draft: null            // the recording under review
    property var triggerNames: ({})

    function refresh() { macros = Backend.listMacros() }
    Component.onCompleted: {
        var opts = Backend.macroTriggerOptions(), m = {}
        for (var i = 0; i < opts.length; i++) m[opts[i].value] = opts[i].name
        triggerNames = m
        refresh()
    }
    Connections {
        target: Backend
        function onMacrosChanged() { root.refresh() }
        function onRecordingStatusReady(st) { root.status = st }
    }
    Timer {
        interval: 350; repeat: true
        running: root.visible && Backend.recording
        onTriggered: Backend.requestRecordingStatus()
    }
    // Esc stops a running macro.
    Shortcut {
        sequence: "Esc"
        enabled: root.visible && Backend.macroRunning
        onActivated: Backend.stopMacro()
    }

    function record() {
        root.draft = null
        root.status = {}
        Backend.startMacroRecording()
    }
    function stop() {
        var d = Backend.stopMacroRecording()
        root.draft = d.steps ? d : null
        if (root.draft) Qt.callLater(function () { draftName.field.forceActiveFocus() })
    }
    function saveDraft() {
        if (Backend.saveDraft(draftName.text)) { root.draft = null; draftName.text = "" }
    }
    function seconds(ms) { return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) }
    function summary(m) {
        var s = Backend.macroSummary(m), parts = [qsTr("%n step(s)", "", s.steps)]
        if (s.ms > 0) parts.push(qsTr("%1 s").arg(seconds(s.ms)))
        if (m.repeat_mode === "repeat_n") parts.push(qsTr("%1× in a row").arg(m.repeat_count || 1))
        else if (m.repeat_mode === "while_holding") parts.push(qsTr("while held"))
        else if (m.repeat_mode === "toggle") parts.push(qsTr("on / off"))
        return parts.join(" · ")
    }
    function remove(m) {
        var json = Backend.deleteMacro(String(m.id))
        if (json !== "")
            Window.window.undoToast(qsTr("“%1” deleted").arg(m.name || m.id), function () { Backend.restoreMacro(json) })
    }

    MacroEditor { id: macroEditor }
    MacroBindDialog { id: bindDialog }
    FileDialog {
        id: exportDialog
        property string macroId: ""
        fileMode: FileDialog.SaveFile
        nameFilters: [qsTr("Macro files (*.json)")]
        onAccepted: Backend.exportMacro(macroId, selectedFile.toString())
    }
    FileDialog {
        id: importDialog
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("Macro files (*.json)")]
        onAccepted: Backend.importMacro(selectedFile.toString())
    }
    // "…" menu of a library row
    B.Popup {
        id: rowMenu
        property var macro: ({})
        property Item row: null
        padding: 6
        background: Rectangle { radius: Theme.radiusCtl; color: Theme.surfaceGlassHi; border.color: Theme.borderStrong; border.width: 1 }
        contentItem: Column {
            spacing: 2
            Repeater {
                model: [
                    { id: "rename", name: qsTr("Rename"), key: "F2" },
                    { id: "bind", name: qsTr("Bind to a button…"), key: "" },
                    { id: "duplicate", name: qsTr("Duplicate"), key: "" },
                    { id: "export", name: qsTr("Export…"), key: "" },
                    { id: "delete", name: qsTr("Delete"), key: "Del" }
                ]
                Rectangle {
                    required property var modelData
                    width: 220; height: 36; radius: 8
                    color: itemMa.containsMouse ? "#18FFFFFF" : "transparent"
                    Accessible.role: Accessible.MenuItem
                    Accessible.name: modelData.name
                    Text {
                        anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter
                        text: modelData.name
                        color: modelData.id === "delete" ? Theme.danger : Theme.textBody
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    Text {
                        anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                        text: modelData.key; color: Theme.textMuted
                        font.family: Theme.fontMono; font.pixelSize: Theme.fsMicro
                    }
                    MouseArea {
                        id: itemMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            var m = rowMenu.macro, row = rowMenu.row
                            rowMenu.close()
                            if (modelData.id === "rename" && row) row.rename()
                            else if (modelData.id === "bind") bindDialog.bindFor(String(m.id), m.name || m.id, m.assigned_trigger || "")
                            else if (modelData.id === "duplicate") Backend.duplicateMacro(String(m.id))
                            else if (modelData.id === "export") {
                                exportDialog.macroId = String(m.id)
                                exportDialog.open()
                            }
                            else if (modelData.id === "delete") root.remove(m)
                        }
                    }
                }
            }
        }
    }
    // starter macros
    B.Popup {
        id: templateMenu
        padding: 8
        background: Rectangle { radius: Theme.radiusCtl; color: Theme.surfaceGlassHi; border.color: Theme.borderStrong; border.width: 1 }
        contentItem: Column {
            spacing: 2
            Repeater {
                model: Backend.macroTemplates()
                Rectangle {
                    required property var modelData
                    width: 300; height: tCol.implicitHeight + 14; radius: 8
                    color: tMa.containsMouse ? "#18FFFFFF" : "transparent"
                    Accessible.role: Accessible.MenuItem
                    Accessible.name: modelData.name
                    Column {
                        id: tCol
                        anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 24
                        Text { text: modelData.name; color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.Medium }
                        Text { text: modelData.desc; width: parent.width; wrapMode: Text.WordWrap; color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro }
                    }
                    MouseArea {
                        id: tMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            templateMenu.close()
                            var id = Backend.createMacroFromTemplate(modelData.id)
                            if (id !== "") macroEditor.edit(id)
                        }
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

            // ===== Record =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: recCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: recCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: qsTr("Record a macro")
                        subtitle: qsTr("Records the keys you press and the mouse buttons you click. Pointer movement is not recorded; add scrolling and pauses in the editor.")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/applications-development-symbolic"
                        PrimaryButton {
                            visible: root.draft === null
                            text: Backend.recording ? qsTr("Stop") : qsTr("Record")
                            danger: Backend.recording
                            enabled: Backend.daemonAvailable
                            onClicked: Backend.recording ? root.stop() : root.record()
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border; visible: Backend.recording || root.draft !== null }

                    // ---- live feed while recording ----
                    Column {
                        visible: Backend.recording
                        width: parent.width
                        spacing: Theme.gapS
                        Row {
                            spacing: 8
                            Rectangle {
                                width: 10; height: 10; radius: 5
                                anchors.verticalCenter: parent.verticalCenter
                                color: Theme.danger
                                SequentialAnimation on opacity {
                                    running: root.visible && Backend.recording && !Theme.reduceMotion
                                    loops: Animation.Infinite
                                    NumberAnimation { from: 1.0; to: 0.25; duration: Theme.dLong; easing.type: Easing.InOutSine }
                                    NumberAnimation { from: 0.25; to: 1.0; duration: Theme.dLong; easing.type: Easing.InOutSine }
                                }
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: (root.status.devices || []).length
                                      ? qsTr("Recording from %1").arg(root.status.devices.join(", "))
                                      : qsTr("Recording")
                                color: Theme.textPrimary
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                            }
                        }
                        Text {
                            text: root.status.count ? qsTr("%n key event(s) so far", "", root.status.count)
                                                    : qsTr("Type your sequence now, then press Stop.")
                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        // the latest keys, as keycaps
                        Row {
                            spacing: 4
                            Repeater {
                                model: (root.status.recent || []).filter(function (e) { return e.down })
                                Rectangle {
                                    required property var modelData
                                    height: 26; width: kTxt.implicitWidth + 14; radius: 5
                                    color: Theme.surfaceInset; border.width: 1; border.color: Theme.borderStrong
                                    Text {
                                        id: kTxt; anchors.centerIn: parent
                                        text: modelData.mouse ? qsTr("%1 click").arg(modelData.key) : KeyNames.prettyKey(modelData.key)
                                        color: Theme.textPrimary
                                        font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                    }
                                }
                            }
                        }
                    }

                    // ---- review the recording: name it, save, re-record or discard ----
                    Column {
                        visible: root.draft !== null
                        width: parent.width
                        spacing: Theme.gapS
                        Text {
                            text: root.draft ? qsTr("Recorded %n step(s)", "", root.draft.steps)
                                               + (root.draft.ms > 0 ? " · " + qsTr("%1 s").arg(root.seconds(root.draft.ms)) : "") : ""
                            color: Theme.textPrimary
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                        }
                        Flow {
                            width: parent.width; spacing: 4
                            Repeater {
                                model: root.draft ? root.draft.rows.filter(function (r) { return r.kind === "keys" }).slice(0, 24) : []
                                Rectangle {
                                    required property var modelData
                                    height: 26; width: cTxt.implicitWidth + 14; radius: 5
                                    color: Theme.surfaceInset; border.width: 1; border.color: Theme.borderStrong
                                    Text {
                                        id: cTxt; anchors.centerIn: parent
                                        text: KeyNames.pretty(modelData.chord)
                                        color: Theme.textPrimary
                                        font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                    }
                                }
                            }
                        }
                        RowLayout {
                            width: parent.width
                            spacing: Theme.gapS
                            InputField {
                                id: draftName
                                Layout.fillWidth: true
                                accessibleName: qsTr("Macro name")
                                placeholder: qsTr("Name this macro")
                                onAccepted: root.saveDraft()
                            }
                            PrimaryButton { text: qsTr("Discard"); ghost: true; onClicked: { Backend.discardDraft(); root.draft = null } }
                            PrimaryButton { text: qsTr("Record again"); ghost: true; onClicked: { Backend.discardDraft(); root.record() } }
                            PrimaryButton { text: qsTr("Save"); onClicked: root.saveDraft() }
                        }
                    }
                }
            }

            // ===== Library =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: libCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: libCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Your macros")
                        subtitle: qsTr("Bind one to the Back, Forward or wheel button, or run it from a ring slice or any button (Custom action).")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-list-symbolic"
                        Row {
                            spacing: Theme.gapS
                            PrimaryButton {
                                id: tplBtn
                                text: qsTr("Templates"); ghost: true
                                onClicked: { templateMenu.parent = tplBtn; templateMenu.x = tplBtn.width - 300; templateMenu.y = tplBtn.height + 4; templateMenu.open() }
                            }
                            PrimaryButton { text: qsTr("Import…"); ghost: true; onClicked: importDialog.open() }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    // a macro is playing
                    Rectangle {
                        visible: Backend.macroRunning
                        width: parent.width; height: 48; radius: Theme.radiusCtl
                        color: Theme.accentSubtle; border.width: 1; border.color: Theme.accent
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 8
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("A macro is running. Esc stops it.")
                                color: Theme.textPrimary; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                            PrimaryButton { text: qsTr("Stop"); danger: true; onClicked: Backend.stopMacro() }
                        }
                    }

                    EmptyState {
                        visible: !root.hasMacros
                        width: parent.width
                        spot: "spot_macros"
                        title: qsTr("No macros yet")
                        body: qsTr("Record a key sequence once, or start from a template.")
                        PrimaryButton { text: qsTr("Record"); ghost: true; enabled: Backend.daemonAvailable; onClicked: root.record() }
                    }

                    Repeater {
                        model: root.macros
                        Rectangle {
                            id: mRow
                            required property var modelData
                            required property int index
                            readonly property string mid: String(modelData.id)
                            property bool renaming: false
                            function rename() { renaming = true; Qt.callLater(function () { nameEdit.field.forceActiveFocus(); nameEdit.field.selectAll() }) }
                            width: libCol.width
                            height: 64
                            radius: Theme.radiusCtl
                            color: rowHover.hovered || activeFocus ? "#16FFFFFF" : "#10FFFFFF"
                            border.width: 1; border.color: activeFocus ? Theme.accent : Theme.border
                            Behavior on color { ColorAnimation { duration: Theme.dShort } }
                            HoverHandler { id: rowHover }
                            activeFocusOnTab: true
                            Accessible.role: Accessible.ListItem
                            Accessible.name: (modelData.name || modelData.id) + ", " + root.summary(modelData)
                            Accessible.description: qsTr("Enter edits, F2 renames, Ctrl+R runs, Delete deletes")
                            Keys.onReturnPressed: macroEditor.edit(mid)
                            Keys.onDeletePressed: root.remove(modelData)
                            Keys.onPressed: (e) => {
                                if (e.key === Qt.Key_F2) { rename(); e.accepted = true }
                                else if (e.key === Qt.Key_R && (e.modifiers & Qt.ControlModifier)) { Backend.runMacro(mid); e.accepted = true }
                            }
                            MouseArea { anchors.fill: parent; onDoubleClicked: macroEditor.edit(mRow.mid) }

                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 8
                                spacing: Theme.gapS
                                ActionIcon { iconName: "macros"; tint: Theme.accent; px: 18 }
                                Column {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text {
                                        visible: !mRow.renaming
                                        width: parent.width; elide: Text.ElideRight
                                        text: mRow.modelData.name || qsTr("Untitled macro")
                                        color: Theme.textPrimary
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
                                    }
                                    InputField {
                                        id: nameEdit
                                        visible: mRow.renaming
                                        width: Math.min(300, parent.width)
                                        accessibleName: qsTr("Macro name")
                                        text: mRow.modelData.name || ""
                                        onEditingFinished: {
                                            if (!mRow.renaming) return
                                            mRow.renaming = false
                                            if (text.trim() !== "" && text !== (mRow.modelData.name || ""))
                                                Backend.setMacroMeta(mRow.mid, "name", text.trim())
                                        }
                                    }
                                    Text {
                                        text: root.summary(mRow.modelData)
                                        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                    }
                                }
                                Badge {
                                    visible: !!mRow.modelData.assigned_trigger
                                    text: root.triggerNames[mRow.modelData.assigned_trigger || ""] || (mRow.modelData.assigned_trigger || "")
                                    accent: true
                                }
                                IconButton {
                                    icon: "media-playback-start-symbolic"; tint: Theme.accent
                                    tip: qsTr("Run (Ctrl+R)")
                                    onClicked: Backend.runMacro(mRow.mid)
                                }
                                IconButton {
                                    icon: "input-mouse-symbolic"; tint: Theme.textBody
                                    tip: qsTr("Bind to a button")
                                    onClicked: bindDialog.bindFor(mRow.mid, mRow.modelData.name || mRow.mid, mRow.modelData.assigned_trigger || "")
                                }
                                IconButton {
                                    icon: "document-edit-symbolic"; tint: Theme.textBody
                                    tip: qsTr("Edit (Enter)")
                                    onClicked: macroEditor.edit(mRow.mid)
                                }
                                IconButton {
                                    id: moreBtn
                                    icon: "open-menu-symbolic"; tint: Theme.textMuted
                                    tip: qsTr("More")
                                    onClicked: {
                                        rowMenu.macro = mRow.modelData; rowMenu.row = mRow
                                        rowMenu.parent = moreBtn
                                        rowMenu.x = moreBtn.width - 232; rowMenu.y = moreBtn.height + 4
                                        rowMenu.open()
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        visible: root.hasMacros
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("A button remapped on the Buttons tab runs its remap, not a macro bound to it.")
                        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                    }
                }
            }
            Item { Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
