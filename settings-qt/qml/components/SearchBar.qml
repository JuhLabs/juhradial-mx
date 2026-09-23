import QtQuick
import QtQuick.Controls.Basic as B

// Global settings search. A glass pill in the page header that searches every
// setting across all tabs (Backend.searchIndex()) and, on select, jumps to the
// owning tab via Backend.openSearchResult() which also flags the exact row to
// flash + scroll into view (handled in SettingRow).
Item {
    id: sb
    implicitHeight: 38
    implicitWidth: 360

    property var _all: []
    property var _results: []
    property int _hi: 0

    Component.onCompleted: _all = Backend.searchIndex()

    function focusInput() { field.forceActiveFocus(); field.selectAll() }

    function _score(e, q) {
        var lbl = (e.label || "").toLowerCase()
        var hay = (lbl + " " + (e.section || "") + " " + (e.tab || "") + " "
                   + (e.keywords || "")).toLowerCase()
        var toks = q.split(/\s+/).filter(function (t) { return t.length > 0 })
        if (toks.length === 0) return -1
        var sc = 0
        for (var i = 0; i < toks.length; i++) {
            var t = toks[i]
            if (hay.indexOf(t) < 0) return -1
            if (lbl.indexOf(t) === 0) sc += 80
            else if (lbl.indexOf(t) >= 0) sc += 50
            else if ((e.tab || "").toLowerCase().indexOf(t) >= 0) sc += 20
            else sc += 10
        }
        if (lbl === q) sc += 100
        return sc
    }

    function _update() {
        var q = field.text.trim().toLowerCase()
        if (q === "") { _results = []; resultsPop.close(); return }
        var scored = []
        for (var i = 0; i < _all.length; i++) {
            var s = _score(_all[i], q)
            if (s >= 0) scored.push({ e: _all[i], s: s })
        }
        scored.sort(function (a, b) { return b.s - a.s })
        var out = []
        for (var j = 0; j < scored.length && j < 8; j++) out.push(scored[j].e)
        _results = out
        _hi = 0
        if (out.length > 0) resultsPop.open(); else resultsPop.close()
    }

    function _choose(e) {
        if (!e) return
        Backend.openSearchResult(e.tabKey, e.label)
        field.text = ""
        _results = []
        resultsPop.close()
        field.focus = false
    }

    // ---- the pill ----
    Rectangle {
        id: pill
        anchors.fill: parent
        radius: Theme.radiusPill
        color: field.activeFocus ? Theme.surfaceGlassHi : "#14FFFFFF"
        border.width: 1
        border.color: field.activeFocus ? Theme.accent : Theme.border
        Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
        Behavior on color { ColorAnimation { duration: Theme.dShort } }

        Image {
            id: glass
            source: "image://icon/" + (field.activeFocus ? Theme.accent.toString().slice(1) : "9AA3B2") + "/" + Theme.iconStyle + "/system-search-symbolic"
            sourceSize.width: 32; sourceSize.height: 32
            width: 16; height: 16; smooth: true
            anchors.left: parent.left; anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
        }

        B.TextField {
            id: field
            anchors.left: glass.right; anchors.leftMargin: 9
            anchors.right: clearBtn.left; anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            height: parent.height
            placeholderText: qsTr("Search all settings…")
            placeholderTextColor: Theme.textMuted
            color: Theme.textBody
            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
            verticalAlignment: Text.AlignVCenter
            selectionColor: Theme.accentSubtle
            selectedTextColor: Theme.textPrimary
            background: Item {}
            onTextChanged: sb._update()
            onActiveFocusChanged: if (activeFocus && text.length > 0) sb._update()

            Keys.onDownPressed: if (sb._results.length) sb._hi = Math.min(sb._hi + 1, sb._results.length - 1)
            Keys.onUpPressed: if (sb._results.length) sb._hi = Math.max(sb._hi - 1, 0)
            Keys.onReturnPressed: sb._choose(sb._results[sb._hi])
            Keys.onEnterPressed: sb._choose(sb._results[sb._hi])
            Keys.onEscapePressed: { text = ""; resultsPop.close(); focus = false }
        }

        // clear button (only when there is text)
        Item {
            id: clearBtn
            width: 24; height: 24
            anchors.right: parent.right; anchors.rightMargin: 7
            anchors.verticalCenter: parent.verticalCenter
            visible: field.text.length > 0
            Image {
                anchors.centerIn: parent
                source: "image://icon/9AA3B2/" + Theme.iconStyle + "/edit-clear-symbolic"
                sourceSize.width: 28; sourceSize.height: 28
                width: 15; height: 15; smooth: true
                opacity: clearMa.containsMouse ? 1.0 : 0.7
            }
            MouseArea {
                id: clearMa; anchors.fill: parent; hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { field.text = ""; field.forceActiveFocus() }
            }
        }
    }

    // ---- results dropdown ----
    B.Popup {
        id: resultsPop
        y: sb.height + 6
        x: 0
        width: Math.max(sb.width, 340)
        padding: 6
        modal: false
        focus: false
        closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside
        implicitHeight: Math.min(list.contentHeight + 12, 360)

        background: Rectangle {
            radius: Theme.radiusCard
            color: Theme.surfaceGlassHi
            border.color: Theme.borderStrong; border.width: 1
        }

        contentItem: ListView {
            id: list
            implicitHeight: contentHeight
            clip: true
            model: sb._results
            boundsBehavior: Flickable.StopAtBounds
            B.ScrollBar.vertical: B.ScrollBar { policy: B.ScrollBar.AsNeeded }
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: ListView.view.width
                height: 46
                radius: Theme.radiusCtl
                color: index === sb._hi ? Theme.accentSubtle
                       : (rowMa.containsMouse ? "#12FFFFFF" : "transparent")
                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 10; anchors.rightMargin: 10
                    spacing: 10
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 16
                        spacing: 2
                        Text {
                            text: modelData.label
                            color: index === sb._hi ? Theme.accent : Theme.textBody
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight; width: parent.width
                        }
                        Text {
                            text: modelData.section !== ""
                                  ? modelData.tab + "  ·  " + modelData.section
                                  : modelData.tab
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                            elide: Text.ElideRight; width: parent.width
                        }
                    }
                }
                MouseArea {
                    id: rowMa; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onEntered: sb._hi = index
                    onClicked: sb._choose(modelData)
                }
            }
        }
    }
}
