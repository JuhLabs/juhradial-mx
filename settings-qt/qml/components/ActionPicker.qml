import QtQuick
import QtQuick.Controls.Basic as B

// Reusable action chooser popup. Call open() after setting `actions` (a list of
// {id, name, icon?, hex?, groupName?, hidden?}) and `title`. Emits picked(id).
// Entries with a groupName are shown under that heading; hidden ones are
// never offered. Search has focus on open; arrows move, Enter picks, Esc
// closes. Used by the button map and the ring slice editor.
B.Popup {
    id: pop
    property var actions: []
    property string title: qsTr("Choose an action")
    property string currentId: ""
    signal picked(string id)

    modal: true
    dim: true
    focus: true
    width: 480
    height: Math.min(600, parent ? parent.height - 80 : 600)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside

    property string _q: ""
    property int _cursor: 0
    readonly property int _cols: 2

    // Offered entries matching the search, in order.
    readonly property var _shown: {
        var q = _q.toLowerCase(), out = []
        for (var i = 0; i < actions.length; i++) {
            var a = actions[i]
            if (a.hidden) continue
            if (q === "" || (a.name || "").toLowerCase().indexOf(q) >= 0
                    || (a.groupName || "").toLowerCase().indexOf(q) >= 0)
                out.push(a)
        }
        return out
    }
    // [{name, items: [{a, i}]}] where i is the index in _shown.
    readonly property var _groups: {
        var out = [], cur = null
        for (var i = 0; i < _shown.length; i++) {
            var g = _shown[i].groupName || ""
            if (!cur || cur.name !== g) { cur = { name: g, items: [] }; out.push(cur) }
            cur.items.push({ a: _shown[i], i: i })
        }
        return out
    }

    function _move(d) {
        if (_shown.length === 0) return
        _cursor = Math.max(0, Math.min(_shown.length - 1, _cursor + d))
    }
    function _choose(i) {
        if (i < 0 || i >= _shown.length) return
        pop.picked(_shown[i].id)
        pop.close()
    }

    onAboutToShow: {
        _q = ""; search.text = ""
        var at = 0
        for (var i = 0; i < _shown.length; i++) if (_shown[i].id === currentId) { at = i; break }
        _cursor = at
        search.forceActiveFocus()
    }
    // Scroll to the current action once the grid has its layout and the
    // popup its final height.
    function _revealCursor() { var c = _cursor; _cursor = -1; _cursor = c }
    onOpened: _revealCursor()

    background: Rectangle {
        radius: Theme.radiusCard; color: Theme.surfaceGlassHi
        border.color: Theme.borderStrong; border.width: 1
    }
    B.Overlay.modal: Rectangle { color: "#99000000" }

    contentItem: Column {
        spacing: 12
        Text {
            text: pop.title; color: Theme.textPrimary
            font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
        }
        Rectangle {
            width: parent.width; height: 38; radius: Theme.radiusCtl
            color: "#14FFFFFF"; border.color: search.activeFocus ? Theme.accent : Theme.border; border.width: 1
            Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
            B.TextField {
                id: search
                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                placeholderText: qsTr("Search actions…")
                placeholderTextColor: Theme.textMuted
                color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                verticalAlignment: Text.AlignVCenter
                background: Item {}
                Accessible.name: qsTr("Search actions")
                onTextChanged: { pop._q = text; pop._cursor = 0 }
                Keys.onDownPressed: pop._move(pop._cols)
                Keys.onUpPressed: pop._move(-pop._cols)
                Keys.onRightPressed: (e) => { if (text === "" || cursorPosition === text.length) pop._move(1); else e.accepted = false }
                Keys.onLeftPressed: (e) => { if (text === "" || cursorPosition === 0) pop._move(-1); else e.accepted = false }
                Keys.onReturnPressed: pop._choose(pop._cursor)
                Keys.onEnterPressed: pop._choose(pop._cursor)
            }
        }
        B.ScrollView {
            id: scroller
            width: parent.width
            height: pop.height - 130
            clip: true
            B.ScrollBar.horizontal.policy: B.ScrollBar.AlwaysOff
            onHeightChanged: if (pop.opened && height > 0) pop._revealCursor()
            Column {
                width: pop.width - 36
                spacing: 10
                Repeater {
                    model: pop._groups
                    Column {
                        required property var modelData
                        width: parent.width
                        spacing: 6
                        Text {
                            visible: modelData.name !== ""
                            text: modelData.name; color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                            font.weight: Font.DemiBold; font.letterSpacing: 0.6
                        }
                        Grid {
                            width: parent.width
                            columns: pop._cols; spacing: 8
                            Repeater {
                                model: modelData.items
                                Rectangle {
                                    id: cell
                                    required property var modelData
                                    readonly property var act: modelData.a
                                    readonly property bool cursor: pop._cursor === modelData.i
                                    readonly property bool current: pop.currentId === act.id
                                    width: (pop.width - 44) / 2
                                    height: 46
                                    radius: 11
                                    color: current ? Theme.accentSubtle
                                           : ((rowMa.containsMouse || cursor) ? "#16FFFFFF" : "#0CFFFFFF")
                                    border.width: cursor ? 2 : 1
                                    border.color: (current || cursor) ? Theme.accent : Theme.border
                                    Behavior on color { ColorAnimation { duration: Theme.dShort } }
                                    Accessible.role: Accessible.Button
                                    Accessible.name: act.name
                                    Accessible.onPressAction: pop._choose(modelData.i)
                                    // keep the keyboard cursor in view (after layout)
                                    function reveal() {
                                        if (scroller.height <= 0) return
                                        var f = scroller.contentItem
                                        var y = cell.mapToItem(f.contentItem, 0, 0).y
                                        if (y < f.contentY) f.contentY = Math.max(0, y - 24)
                                        else if (y + height > f.contentY + scroller.height)
                                            f.contentY = y + height - scroller.height + 8
                                    }
                                    onCursorChanged: if (cursor) Qt.callLater(reveal)
                                    Row {
                                        anchors.fill: parent; anchors.leftMargin: 12; spacing: 11
                                        Item {
                                            width: 30; height: 30
                                            anchors.verticalCenter: parent.verticalCenter
                                            property string btn: (Theme.iconStyle, Theme.sliceButton(cell.act.id || ""))
                                            Image {
                                                anchors.fill: parent; visible: parent.btn !== ""
                                                source: parent.btn; sourceSize.width: 96; sourceSize.height: 96
                                                smooth: true; fillMode: Image.PreserveAspectFit
                                            }
                                            Rectangle {
                                                anchors.fill: parent; radius: 8; visible: parent.btn === ""
                                                color: cell.act.hex ? Qt.rgba(0, 0, 0, 0.25) : "transparent"
                                                ActionIcon {
                                                    anchors.centerIn: parent
                                                    iconName: cell.act.icon || ""
                                                    tint: cell.act.hex ? cell.act.hex : Theme.accent
                                                    px: 18
                                                }
                                            }
                                        }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: parent.width - 60
                                            text: cell.act.name; color: Theme.textBody; elide: Text.ElideRight
                                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.Medium
                                        }
                                    }
                                    MouseArea {
                                        id: rowMa; anchors.fill: parent; hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: pop._choose(cell.modelData.i)
                                    }
                                }
                            }
                        }
                    }
                }
                EmptyState {
                    width: parent.width
                    visible: pop._shown.length === 0
                    title: qsTr("No match")
                    body: qsTr("Try another word.")
                }
            }
        }
    }
}
