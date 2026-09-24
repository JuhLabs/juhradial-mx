import QtQuick
import QtQuick.Controls.Basic as B

// Key art gallery: the bundled art in two sets (Artsy fills the key, Minimal
// sits above the label), with search and keyboard navigation. Emits
// picked(id) with a "<set>/<name>" reference.
B.Popup {
    id: pop
    property string currentId: ""
    signal picked(string id)

    modal: true
    dim: true
    focus: true
    width: 560
    height: Math.min(640, parent ? parent.height - 80 : 640)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside

    property var _art: []
    property string _set: "artsy"
    property string _q: ""
    readonly property var _shown: {
        var q = _q.toLowerCase(), out = []
        for (var i = 0; i < _art.length; i++) {
            var a = _art[i]
            if (a.set === _set && (q === "" || a.name.toLowerCase().indexOf(q) >= 0)) out.push(a)
        }
        return out
    }

    function choose(i) {
        if (i >= 0 && i < _shown.length) { pop.picked(_shown[i].id); pop.close() }
    }

    onAboutToShow: {
        if (_art.length === 0) _art = Backend.keypadArt()
        _q = ""; search.text = ""
        if (currentId.indexOf("/") > 0) _set = currentId.split("/")[0]
        var at = 0
        for (var i = 0; i < _shown.length; i++) if (_shown[i].id === currentId) { at = i; break }
        grid.currentIndex = at
        search.forceActiveFocus()
    }
    onOpened: grid.positionViewAtIndex(grid.currentIndex, GridView.Contain)

    background: Rectangle {
        radius: Theme.radiusCard; color: Theme.surfaceGlassHi
        border.color: Theme.borderStrong; border.width: 1
    }
    B.Overlay.modal: Rectangle { color: "#99000000" }

    contentItem: Column {
        spacing: 12
        Text {
            text: qsTr("Choose key art"); color: Theme.textPrimary
            font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
        }
        Row {
            width: parent.width; spacing: 12
            SegmentedControl {
                id: sets
                width: 220; height: 38
                model: Backend.keypadArtSets()
                currentId: pop._set
                accessibleName: qsTr("Art style")
                onActivated: (id) => { pop._set = id; grid.currentIndex = 0 }
            }
            Rectangle {
                width: parent.width - sets.width - 12; height: 38; radius: Theme.radiusCtl
                color: "#14FFFFFF"; border.color: search.activeFocus ? Theme.accent : Theme.border; border.width: 1
                Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                B.TextField {
                    id: search
                    anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                    placeholderText: qsTr("Search art…")
                    placeholderTextColor: Theme.textMuted
                    color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                    verticalAlignment: Text.AlignVCenter
                    background: Item {}
                    Accessible.name: qsTr("Search art")
                    onTextChanged: { pop._q = text; grid.currentIndex = 0 }
                    Keys.onDownPressed: grid.moveCurrentIndexDown()
                    Keys.onUpPressed: grid.moveCurrentIndexUp()
                    Keys.onRightPressed: (e) => { if (text === "" || cursorPosition === text.length) grid.moveCurrentIndexRight(); else e.accepted = false }
                    Keys.onLeftPressed: (e) => { if (text === "" || cursorPosition === 0) grid.moveCurrentIndexLeft(); else e.accepted = false }
                    Keys.onReturnPressed: pop.choose(grid.currentIndex)
                    Keys.onEnterPressed: pop.choose(grid.currentIndex)
                }
            }
        }
        GridView {
            id: grid
            width: parent.width
            height: pop.height - 140
            clip: true
            model: pop._shown
            cellWidth: Math.floor(width / 5); cellHeight: cellWidth + 22
            boundsBehavior: Flickable.StopAtBounds
            B.ScrollBar.vertical: B.ScrollBar { policy: B.ScrollBar.AsNeeded }
            delegate: Item {
                id: cell
                required property var modelData
                required property int index
                readonly property bool cursor: grid.currentIndex === index
                readonly property bool current: pop.currentId === modelData.id
                width: grid.cellWidth; height: grid.cellHeight
                Accessible.role: Accessible.Button
                Accessible.name: modelData.name
                Accessible.onPressAction: pop.choose(index)
                Rectangle {
                    id: tile
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 4; width: parent.width - 12; height: width
                    radius: 10; color: "#070b14"
                    border.width: cell.cursor ? 2 : 1
                    border.color: (cell.cursor || cell.current) ? Theme.accent
                                  : (tileMa.containsMouse ? Theme.borderStrong : Theme.border)
                    Image {
                        anchors.fill: parent; anchors.margins: 3
                        source: "file://" + cell.modelData.path
                        sourceSize.width: 180; sourceSize.height: 180
                        asynchronous: true; smooth: true; fillMode: Image.PreserveAspectFit
                    }
                }
                Text {
                    anchors.top: tile.bottom; anchors.topMargin: 3
                    width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                    text: cell.modelData.name; color: cell.current ? Theme.accent : Theme.textMuted
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                }
                MouseArea {
                    id: tileMa; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: pop.choose(cell.index)
                }
            }
            EmptyState {
                anchors.centerIn: parent
                width: parent.width - 40
                visible: pop._shown.length === 0
                title: qsTr("No match")
                body: qsTr("Try another word.")
            }
        }
    }
}
