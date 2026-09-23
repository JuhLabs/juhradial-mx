import QtQuick
import QtQuick.Controls.Basic as B

// "Pick application" popup: the installed applications as the desktop menu
// lists them, with search and keyboard navigation. Emits picked(app) with
// {id, name, command, icon}; the caller caches the icon through
// Backend.cacheAppIcon(id) so the overlay can draw it on the wheel.
B.Popup {
    id: pop
    property string title: qsTr("Pick an application")
    signal picked(var app)

    modal: true
    dim: true
    focus: true
    width: 460
    height: Math.min(600, parent ? parent.height - 80 : 600)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside

    property var _apps: []
    property string _q: ""
    readonly property var _shown: {
        var q = _q.toLowerCase(), out = []
        for (var i = 0; i < _apps.length; i++) {
            var a = _apps[i]
            if (q === "" || (a.name || "").toLowerCase().indexOf(q) >= 0
                    || (a.command || "").toLowerCase().indexOf(q) >= 0)
                out.push(a)
        }
        return out
    }

    function choose(i) {
        if (i >= 0 && i < _shown.length) { pop.picked(_shown[i]); pop.close() }
    }

    onAboutToShow: {
        _q = ""; search.text = ""
        if (_apps.length === 0) _apps = Backend.listApplications()
        list.currentIndex = 0
        search.forceActiveFocus()
    }

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
                placeholderText: qsTr("Search applications…")
                placeholderTextColor: Theme.textMuted
                color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                verticalAlignment: Text.AlignVCenter
                background: Item {}
                onTextChanged: { pop._q = text; list.currentIndex = 0 }
                Keys.onDownPressed: list.incrementCurrentIndex()
                Keys.onUpPressed: list.decrementCurrentIndex()
                Keys.onReturnPressed: pop.choose(list.currentIndex)
                Keys.onEnterPressed: pop.choose(list.currentIndex)
            }
        }
        ListView {
            id: list
            width: parent.width
            height: pop.height - 130
            clip: true
            model: pop._shown
            spacing: 4
            boundsBehavior: Flickable.StopAtBounds
            B.ScrollBar.vertical: B.ScrollBar { policy: B.ScrollBar.AsNeeded }
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: list.width - 8
                height: 52
                radius: 11
                readonly property bool current: list.currentIndex === index
                color: current ? Theme.accentSubtle : (rowMa.containsMouse ? "#16FFFFFF" : "#0CFFFFFF")
                border.width: 1
                border.color: current ? Theme.accent : Theme.border
                Behavior on color { ColorAnimation { duration: Theme.dShort } }
                Row {
                    anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 12
                    Image {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 30; height: 30; smooth: true
                        fillMode: Image.PreserveAspectFit
                        sourceSize.width: 60; sourceSize.height: 60
                        source: (modelData.icon || "") === "" ? ""
                              : (modelData.icon.startsWith("/") ? "file://" + modelData.icon
                                                                 : "image://icon/raw/" + modelData.icon)
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 42
                        spacing: 1
                        Text {
                            width: parent.width; elide: Text.ElideRight
                            text: modelData.name; color: Theme.textBody
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
                        }
                        Text {
                            width: parent.width; elide: Text.ElideRight
                            text: modelData.command; color: Theme.textMuted
                            font.family: Theme.fontMono; font.pixelSize: Theme.fsMicro
                        }
                    }
                }
                MouseArea {
                    id: rowMa; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: pop.choose(index)
                }
            }
            EmptyState {
                anchors.centerIn: parent
                width: parent.width - 40
                visible: pop._shown.length === 0
                title: pop._apps.length === 0 ? qsTr("No applications found") : qsTr("No match")
                body: pop._apps.length === 0
                      ? qsTr("The desktop menu database is empty or unreadable.")
                      : qsTr("Try another name, or the command it runs.")
            }
        }
    }
}
