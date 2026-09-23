import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as B
import "../components"

// Gaming mode: suppress the radial overlay in fullscreen games and cycle a set
// of DPI profiles. Master switch talks to the daemon; profiles are local config.
Item {
    id: root
    anchors.fill: parent

    readonly property string _accent: Theme.accent.toString().slice(1)
    readonly property var profiles: Backend.get("gaming.dpi_profiles", [])

    // Config has no NOTIFY, so mirror the active profile and keep it fresh.
    property int activeIdx: Backend.get("gaming.active_dpi_profile", 1)

    Connections {
        target: Backend
        function onLiveChanged() {
            root.activeIdx = Backend.get("gaming.active_dpi_profile", 1)
        }
    }

    // Map a slice colour name (e.g. "blue") to its hex, falling back to accent.
    function colorHex(name) {
        var cs = Backend.sliceColors()
        for (var i = 0; i < cs.length; i++)
            if (cs[i].name === name) return cs[i].hex
        return Theme.accent
    }

    // Build the [{id,name}] model for the active-profile segmented control.
    function activeModel() {
        var out = []
        for (var i = 0; i < profiles.length; i++)
            out.push({ id: String(i), name: profiles[i].name })
        return out
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

            // ---- Hero + master switch ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: masterCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: masterCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    Item {
                        width: parent.width
                        height: Math.max(90, heroRow.implicitHeight)
                        RowLayout {
                            id: heroRow
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.pad
                            Image {
                                source: assetsDir + "/spots/spot_gaming.png"
                                sourceSize.width: 256; sourceSize.height: 256
                                Layout.preferredWidth: 90; Layout.preferredHeight: 90
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                Layout.alignment: Qt.AlignVCenter
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignVCenter
                                spacing: 4
                                Text {
                                    Layout.fillWidth: true
                                    text: "Gaming mode"
                                    color: Theme.textPrimary
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsH2
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Hide the radial overlay and flick between DPI profiles mid-game."
                                    color: Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.WordWrap
                                }
                            }
                            Toggle {
                                Layout.alignment: Qt.AlignVCenter
                                checked: Backend.gamingMode
                                onToggled: (v) => Backend.setGamingMode(v)
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Show overlay in games"
                        desc: "Keep the radial menu reachable while playing"
                        Toggle {
                            checked: !Backend.get("gaming.suppress_overlay", false)
                            onToggled: (v) => Backend.setLocal("gaming.suppress_overlay", !v)
                        }
                    }
                }
            }

            // ---- DPI profiles ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: dpiCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: dpiCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "DPI profiles"
                        subtitle: "Three speeds you can flick between mid-game"
                        icon: "image://icon/" + root._accent + "/input-mouse-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    Repeater {
                        model: root.profiles
                        Rectangle {
                            id: profRow
                            required property var modelData
                            required property int index
                            width: parent.width
                            height: 54
                            radius: Theme.radiusCtl
                            property bool active: root.activeIdx === index
                            color: active ? Theme.accentSubtle
                                          : (rowMa.containsMouse ? "#0CFFFFFF" : "transparent")
                            border.width: 1
                            border.color: active ? Theme.accent : "transparent"
                            Behavior on color { ColorAnimation { duration: Theme.dShort } }
                            Behavior on border.color { ColorAnimation { duration: Theme.dShort } }

                            MouseArea {
                                id: rowMa
                                anchors.fill: parent
                                hoverEnabled: true
                                acceptedButtons: Qt.NoButton
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.gapS + 2
                                anchors.rightMargin: Theme.gapS + 2
                                spacing: Theme.gap

                                Rectangle {
                                    Layout.preferredWidth: 12; Layout.preferredHeight: 12
                                    Layout.alignment: Qt.AlignVCenter
                                    radius: 6
                                    color: root.colorHex(profRow.modelData.color)
                                    border.width: 1; border.color: Theme.border
                                }

                                // Editable profile name, styled like the ActionPicker search field.
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 34
                                    Layout.alignment: Qt.AlignVCenter
                                    radius: Theme.radiusCtl
                                    color: "#14FFFFFF"
                                    border.width: 1
                                    border.color: nameField.activeFocus ? Theme.accent : Theme.border
                                    Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                                    B.TextField {
                                        id: nameField
                                        anchors.fill: parent
                                        anchors.leftMargin: 12; anchors.rightMargin: 12
                                        text: profRow.modelData.name
                                        color: Theme.textBody
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                        font.weight: Font.Medium
                                        verticalAlignment: Text.AlignVCenter
                                        selectByMouse: true
                                        background: Item {}
                                        onEditingFinished: Backend.setGamingProfile(profRow.index, "name", text)
                                    }
                                }

                                Badge {
                                    Layout.alignment: Qt.AlignVCenter
                                    visible: profRow.active
                                    text: "Active"; accent: true; dot: true
                                }

                                Stepper {
                                    Layout.alignment: Qt.AlignVCenter
                                    from: 200; to: 8000; step: 100
                                    value: profRow.modelData.dpi
                                    suffix: " DPI"
                                    onCommitted: (v) => Backend.setGamingProfile(profRow.index, "dpi", v)
                                }
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Active profile"
                        desc: "Which DPI is live right now"
                        SegmentedControl {
                            width: 300
                            model: root.activeModel()
                            currentId: String(root.activeIdx)
                            onActivated: (id) => {
                                root.activeIdx = parseInt(id)
                                Backend.setLocal("gaming.active_dpi_profile", parseInt(id))
                            }
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
