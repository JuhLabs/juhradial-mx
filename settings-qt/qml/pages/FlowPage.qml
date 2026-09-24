import QtQuick
import QtQuick.Layouts
import "../components"

// Flow: move the cursor (and the mouse, and the clipboard) to the computer
// next to this one. The switch applies at once (the overlay follows the
// config), computers must be approved before they get anything, the other
// computer is placed on a side of this screen, and the Easy-Switch channels
// tell the mouse where to go with the cursor.
Item {
    id: page
    anchors.fill: parent

    readonly property string _ic: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/"
    property int bump: 0
    function cfg(path, def) { page.bump; return Backend.get(path, def) }

    readonly property bool flowOn: cfg("flow.enabled", false)
    readonly property bool usable: !Backend.isGeneric
    property var status: ({ running: false, peers: [], trusted: [], clipboardTool: "x", clipboardHint: "" })
    property var firewall: null
    function refresh() { page.status = Backend.flowStatus() }
    Component.onCompleted: refresh()
    Timer { interval: 3000; repeat: true; running: page.visible && page.flowOn; onTriggered: page.refresh() }
    // The overlay needs a moment to start or stop the Flow server.
    Timer { id: settle; interval: 1500; onTriggered: page.refresh() }
    Connections {
        target: Backend
        function onConfigChanged() { page.bump++ }
    }

    readonly property var pending: (status.peers || []).filter(p => p.state === "pending")
    readonly property var connected: (status.peers || []).filter(p => p.state === "trusted")
    readonly property string stateText: {
        if (!page.flowOn) return qsTr("Off")
        if (!page.status.running) return qsTr("Starting…")
        if (page.connected.length) return qsTr("Connected to %1").arg(page.connected[0].hostname || qsTr("a computer"))
        if (page.pending.length) return qsTr("Waiting for your approval")
        return qsTr("Listening for your other computer")
    }
    function platformName(p) {
        return ({ macos: qsTr("Mac"), darwin: qsTr("Mac"), windows: qsTr("Windows"), linux: qsTr("Linux") })[p] || qsTr("Computer")
    }
    // Edge dwell (overlay/flow/edge_detector.py): 350 ms x (1.8 - 1.6 x s/100).
    function dwellMs(s) { return Math.round(350 * (1.8 - 1.6 * s / 100)) }
    function pushWord(s) {
        return s >= 75 ? qsTr("Light touch") : s >= 40 ? qsTr("Normal push") : qsTr("Firm push")
    }
    readonly property int hostCount: Math.max(2, Backend.numHosts)
    function hostModel() {
        var out = [{ id: "", name: qsTr("Not set") }]
        for (var i = 0; i < page.hostCount; i++) {
            var n = Backend.hostNames[i] || ""
            out.push({ id: String(i), name: n !== "" ? qsTr("%1: %2").arg(i + 1).arg(n) : qsTr("Channel %1").arg(i + 1) })
        }
        return out
    }
    function setChannel(key, id) {
        Backend.setLocal(key, id === "" ? null : parseInt(id))
    }
    function channelId(path) {
        var v = page.cfg(path, null)
        return v === null || v === undefined ? "" : String(v)
    }
    readonly property string localChannel: channelId("flow.local_host_index")
    readonly property string remoteChannel: channelId("flow.remote_host_index")

    component Divider: Rectangle { width: parent ? parent.width : 400; height: 1; color: Theme.border }

    // One computer in the Computers list.
    component PeerRow: Rectangle {
        id: pr
        property var peer: ({})
        property bool asking: peer.state === "pending"
        property bool online: true
        width: parent ? parent.width : 400
        height: prRow.implicitHeight + 20
        radius: Theme.radiusCtl
        color: asking ? Theme.accentSubtle : "transparent"
        border.width: 1; border.color: asking ? Theme.accentFaint : Theme.border
        activeFocusOnTab: true
        Accessible.role: Accessible.ListItem
        Accessible.name: (peer.hostname || "") + ". " + (asking ? qsTr("Waiting for your approval") : online ? qsTr("Connected") : qsTr("Not connected"))
        FocusHalo { active: pr.activeFocus; radius: Theme.radiusCtl }
        RowLayout {
            id: prRow
            anchors.left: parent.left; anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 14; anchors.rightMargin: 10
            spacing: Theme.gapS
            Rectangle {
                Layout.preferredWidth: 10; Layout.preferredHeight: 10; radius: 5
                color: pr.asking ? "#F5B22A" : pr.online ? "#2FBF71" : Theme.textMuted
            }
            Column {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: (pr.peer.hostname || qsTr("Unnamed computer")) + "  ·  " + page.platformName(pr.peer.platform)
                    color: Theme.textPrimary
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: pr.asking
                          ? qsTr("Wants to use Flow with this computer%1. Code %2").arg(pr.peer.ip ? qsTr(" from %1").arg(pr.peer.ip) : "").arg(pr.peer.fingerprint)
                          : pr.online ? qsTr("Connected%1").arg(pr.peer.ip ? qsTr(" from %1").arg(pr.peer.ip) : "")
                                      : qsTr("Approved, not connected right now")
                    color: Theme.textMuted
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                }
            }
            PrimaryButton {
                visible: pr.asking
                text: qsTr("Turn away"); ghost: true
                onClicked: { Backend.denyFlowPeer(pr.peer.fingerprint, pr.peer.hostname || "", pr.peer.platform || ""); page.refresh() }
            }
            PrimaryButton {
                visible: pr.asking
                text: qsTr("Approve")
                onClicked: { Backend.approveFlowPeer(pr.peer.fingerprint, pr.peer.hostname || "", pr.peer.platform || ""); page.refresh() }
            }
            PrimaryButton {
                visible: !pr.asking && (pr.peer.fingerprint || "") !== ""
                text: qsTr("Forget"); ghost: true
                onClicked: { Backend.forgetFlowPeer(pr.peer.fingerprint); page.refresh() }
            }
        }
    }

    // A side of the arrangement diagram: click to put the other computer there.
    component SideSlot: Rectangle {
        id: ss
        property string side: ""
        readonly property bool chosen: page.cfg("flow.direction", "right") === side
        readonly property string sideName: ({ left: qsTr("Left"), right: qsTr("Right"), top: qsTr("Above"), bottom: qsTr("Below") })[side] || ""
        radius: 10
        color: chosen ? Theme.accentSubtle : (ssMa.containsMouse ? "#10FFFFFF" : "transparent")
        border.width: 1; border.color: chosen ? Theme.accent : Theme.border
        opacity: page.usable ? 1 : 0.5
        activeFocusOnTab: true
        Accessible.role: Accessible.RadioButton
        Accessible.checked: chosen
        Accessible.name: sideName
        Keys.onSpacePressed: Backend.setLocal("flow.direction", ss.side)
        Keys.onReturnPressed: Backend.setLocal("flow.direction", ss.side)
        FocusHalo { active: ss.activeFocus; radius: 10 }
        Column {
            anchors.centerIn: parent
            spacing: 2
            visible: ss.chosen
            ActionIcon { anchors.horizontalCenter: parent.horizontalCenter; iconName: "computer-symbolic"; tint: Theme.accent; px: 22 }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: page.connected.length ? page.connected[0].hostname : qsTr("Other computer")
                color: Theme.textPrimary; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
            }
        }
        Text {
            anchors.centerIn: parent
            visible: !ss.chosen
            text: ss.sideName; color: Theme.textMuted
            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
        }
        MouseArea {
            id: ssMa
            anchors.fill: parent; hoverEnabled: true
            enabled: page.usable
            cursorShape: Qt.PointingHandCursor
            onClicked: Backend.setLocal("flow.direction", ss.side)
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

            // ---- master ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: masterCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: masterCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Flow")
                        subtitle: qsTr("Move the cursor, the mouse and what you copy to the computer next to this one")
                        icon: page._ic + "flow"
                        Row {
                            spacing: Theme.gapS
                            Badge {
                                anchors.verticalCenter: parent.verticalCenter
                                text: page.stateText; dot: true
                                accent: page.flowOn && page.status.running
                            }
                            Toggle {
                                anchors.verticalCenter: parent.verticalCenter
                                accessibleName: qsTr("Flow")
                                enabled: page.usable
                                checked: page.flowOn
                                onToggled: (v) => { Backend.setLocal("flow.enabled", v); settle.restart() }
                            }
                        }
                    }
                    Text {
                        visible: !page.usable
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("Flow needs a Logitech mouse with Easy-Switch. This mouse runs in generic mode.")
                        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    Divider { visible: !page.flowOn && page.usable }
                    RowLayout {
                        width: parent.width
                        visible: !page.flowOn && page.usable
                        spacing: Theme.pad
                        SpotImage { name: "spot_flow"; size: 104; Layout.alignment: Qt.AlignVCenter }
                        Text {
                            Layout.fillWidth: true
                            text: qsTr("Push the cursor past the edge of this screen and it appears on your Mac. The mouse switches with it, and what you copied comes along.")
                            color: Theme.textBody; wrapMode: Text.WordWrap
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                        }
                    }
                }
            }

            // ---- computers ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: pcCol.implicitHeight + Theme.padCard * 2
                visible: page.usable && page.flowOn
                Column {
                    id: pcCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Computers")
                        subtitle: qsTr("A computer gets nothing from this one until you approve it here")
                        icon: page._ic + "devices"
                        IconButton {
                            icon: "view-refresh-symbolic"; tint: Theme.textMuted; diameter: 30
                            tip: qsTr("Check again"); Accessible.name: qsTr("Check again")
                            onClicked: page.refresh()
                        }
                    }
                    Divider {}
                    Repeater {
                        model: page.pending
                        PeerRow { required property var modelData; peer: modelData; width: pcCol.width }
                    }
                    Repeater {
                        model: page.status.trusted || []
                        PeerRow { required property var modelData; peer: modelData; online: modelData.connected; width: pcCol.width }
                    }
                    // Logi Options+ peers (paired there) have no fingerprint here.
                    Repeater {
                        model: page.connected.filter(p => (p.fingerprint || "") === "")
                        PeerRow { required property var modelData; peer: modelData; width: pcCol.width }
                    }
                    Text {
                        visible: page.pending.length === 0 && (page.status.trusted || []).length === 0 && page.connected.length === 0
                        width: parent.width; wrapMode: Text.WordWrap
                        text: page.status.running
                              ? qsTr("No other computer yet. Open JuhFlow on your Mac (see Set up your Mac below); it finds this computer and asks to connect.")
                              : qsTr("Flow is starting. If this stays, restart the radial menu from Settings > Troubleshooting.")
                        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                }
            }

            // ---- arrangement + channels ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: arCol.implicitHeight + Theme.padCard * 2
                visible: page.usable
                Column {
                    id: arCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Where is the other computer")
                        subtitle: qsTr("Click the side of this screen it sits on. The cursor crosses over there")
                        icon: page._ic + "view-dual-symbolic"
                    }
                    Divider {}
                    Item {
                        width: parent.width; height: 250
                        Item {
                            id: board
                            anchors.centerIn: parent
                            width: Math.min(parent.width, 560); height: parent.height
                            Rectangle {
                                id: me
                                anchors.centerIn: parent
                                width: 190; height: 120; radius: 12
                                color: "#14FFFFFF"; border.width: 1; border.color: Theme.borderStrong
                                Column {
                                    anchors.centerIn: parent
                                    spacing: 4
                                    ActionIcon { anchors.horizontalCenter: parent.horizontalCenter; iconName: "computer-symbolic"; tint: Theme.textBody; px: 26 }
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: qsTr("This computer"); color: Theme.textPrimary
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                    }
                                }
                            }
                            SideSlot { side: "left"; anchors.right: me.left; anchors.rightMargin: 12; anchors.verticalCenter: me.verticalCenter; width: 150; height: 120 }
                            SideSlot { side: "right"; anchors.left: me.right; anchors.leftMargin: 12; anchors.verticalCenter: me.verticalCenter; width: 150; height: 120 }
                            SideSlot { side: "top"; anchors.bottom: me.top; anchors.bottomMargin: 10; anchors.horizontalCenter: me.horizontalCenter; width: 190; height: 50 }
                            SideSlot { side: "bottom"; anchors.top: me.bottom; anchors.topMargin: 10; anchors.horizontalCenter: me.horizontalCenter; width: 190; height: 50 }
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Screen")
                        desc: qsTr("With several screens, the one whose edge leads to the other computer")
                        ComboBox {
                            width: 240
                            enabled: page.usable
                            accessibleName: qsTr("Screen")
                            model: Backend.flowScreens()
                            currentId: page.cfg("flow.monitor", "")
                            onActivated2: (id) => Backend.setLocal("flow.monitor", id)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("This computer's channel")
                        desc: page.localChannel === ""
                              ? qsTr("Not set: the mouse does not come back with the cursor. It is on channel %1 now").arg(Backend.currentHost + 1)
                              : qsTr("The Easy-Switch channel the mouse uses for this computer")
                        ComboBox {
                            width: 240
                            accessibleName: qsTr("This computer's channel")
                            model: page.hostModel()
                            currentId: page.localChannel
                            onActivated2: (id) => page.setChannel("flow.local_host_index", id)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("The other computer's channel")
                        desc: page.remoteChannel === ""
                              ? qsTr("Not set: the mouse stays here when the cursor leaves")
                              : qsTr("The mouse switches to this channel when the cursor crosses over")
                        ComboBox {
                            width: 240
                            accessibleName: qsTr("The other computer's channel")
                            model: page.hostModel()
                            currentId: page.remoteChannel
                            onActivated2: (id) => page.setChannel("flow.remote_host_index", id)
                        }
                    }
                }
            }

            // ---- behaviour (readable while off; only the controls dim) ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: bhCol.implicitHeight + Theme.padCard * 2
                visible: page.usable
                Column {
                    id: bhCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Behaviour")
                        icon: page._ic + "preferences-system-symbolic"
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Move the cursor across the edge")
                        desc: qsTr("Off: Flow still shares the clipboard, the cursor stays here")
                        Toggle {
                            enabled: page.flowOn
                            accessibleName: qsTr("Move the cursor across the edge")
                            checked: page.cfg("flow.edge_trigger", true)
                            onToggled: (v) => Backend.setLocal("flow.edge_trigger", v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("How firmly to push")
                        desc: qsTr("%1: the cursor crosses after %2 ms at the edge, so scrollbars and docks stay usable")
                              .arg(page.pushWord(pushSlider.shown)).arg(page.dwellMs(pushSlider.shown))
                        Slider {
                            id: pushSlider
                            width: 220; from: 0; to: 100; stepSize: 5
                            enabled: page.flowOn
                            accessibleName: qsTr("How firmly to push")
                            accessibleDescription: qsTr("Left is a firm push, right a light touch")
                            value: page.cfg("flow.edge_sensitivity", 50)
                            onCommitted: (v) => Backend.setLocal("flow.edge_sensitivity", Math.round(v))
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Share clipboard")
                        desc: page.status.clipboardTool === ""
                              ? qsTr("Install %1 first: without it nothing is copied across").arg(page.status.clipboardHint)
                              : qsTr("Text only, and only with computers you approved")
                        Toggle {
                            enabled: page.flowOn
                            accessibleName: qsTr("Share clipboard")
                            checked: page.cfg("flow.share_clipboard", true)
                            onToggled: (v) => Backend.setLocal("flow.share_clipboard", v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Show the edge glow")
                        desc: qsTr("A soft light on the edge that leads to the other computer")
                        Toggle {
                            enabled: page.flowOn
                            accessibleName: qsTr("Show the edge glow")
                            checked: !page.cfg("flow.hide_indicator", false)
                            onToggled: (v) => Backend.setLocal("flow.hide_indicator", !v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Use the whole edge")
                        desc: qsTr("Cross anywhere along the edge, not only where the glow is")
                        Toggle {
                            enabled: page.flowOn
                            accessibleName: qsTr("Use the whole edge")
                            checked: page.cfg("flow.extend_edge_zone", false)
                            onToggled: (v) => Backend.setLocal("flow.extend_edge_zone", v)
                        }
                    }
                }
            }

            // ---- set up the Mac ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: suCol.implicitHeight + Theme.padCard * 2
                visible: page.usable
                Column {
                    id: suCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: 8
                    CardHeader {
                        width: parent.width
                        title: qsTr("Set up your Mac")
                        subtitle: qsTr("JuhFlow is the small companion app on the other side. Windows is planned")
                        icon: page._ic + "help-about-symbolic"
                        PrimaryButton {
                            text: qsTr("Get JuhFlow"); ghost: true
                            onClicked: Backend.openJuhFlow()
                        }
                    }
                    Divider {}
                    Repeater {
                        model: [qsTr("1. Pair the mouse with each computer on its own Easy-Switch channel, then set both channels above."),
                                qsTr("2. Keep both computers on the same network."),
                                qsTr("3. Install and open JuhFlow on the Mac. It finds this computer by itself."),
                                qsTr("4. Approve the Mac under Computers when it asks. Nothing is shared before that.")]
                        Text {
                            required property string modelData
                            width: suCol.width; wrapMode: Text.WordWrap
                            text: modelData
                            color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                    }
                    Divider {}
                    RowLayout {
                        width: parent.width
                        spacing: Theme.gapS
                        Text {
                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                            text: !page.firewall ? qsTr("Nothing shows up? A firewall may block Flow.")
                                  : page.firewall.firewall === "" ? qsTr("No firewall service is running here, so Flow is not blocked by one.")
                                  : page.firewall.open === true ? qsTr("%1 lets Flow through.").arg(page.firewall.firewall)
                                  : qsTr("%1 may block Flow. Open its ports with this command in a terminal:").arg(page.firewall.firewall)
                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                        PrimaryButton {
                            text: qsTr("Check the firewall"); ghost: true
                            onClicked: page.firewall = Backend.flowFirewall()
                        }
                    }
                    Rectangle {
                        visible: !!page.firewall && page.firewall.command !== "" && page.firewall.open !== true
                        width: parent.width; height: fwRow.implicitHeight + 16
                        radius: Theme.radiusCtl; color: "#12FFFFFF"
                        RowLayout {
                            id: fwRow
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 12; anchors.rightMargin: 6
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                                text: page.firewall ? page.firewall.command : ""
                                color: Theme.textBody; font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                            }
                            IconButton {
                                icon: "edit-copy-symbolic"; tint: Theme.textMuted; diameter: 30
                                tip: qsTr("Copy the command"); Accessible.name: qsTr("Copy the command")
                                onClicked: Backend.copyText(page.firewall.command, qsTr("Command"))
                            }
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
