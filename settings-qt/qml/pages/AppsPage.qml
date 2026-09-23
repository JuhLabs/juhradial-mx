import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as B
import "../components"

// Per-app HARDWARE override profiles. When an app is focused the daemon applies
// that app's DPI / SmartShift / hi-res-scroll / thumb-wheel mode. Per-app radial
// SLICES are intentionally NOT supported (the daemon does not consume them).
Item {
    id: page
    anchors.fill: parent

    readonly property string _accent: Theme.accent.toString().slice(1)

    ListModel { id: appModel }
    function loadApps() {
        appModel.clear()
        var list = Backend.appProfiles()
        for (var i = 0; i < list.length; i++) {
            var p = list[i]
            appModel.append({
                app: p.app,
                dpi: p.dpi,
                smartshiftEnabled: p.smartshiftEnabled,
                smartshiftThreshold: p.smartshiftThreshold,
                hires: p.hires,
                thumbwheel: p.thumbwheel
            })
        }
    }
    Component.onCompleted: loadApps()

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            // ===== Add application =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: addCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: addCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "App profiles"
                        subtitle: "Per-app DPI, scroll and thumb-wheel settings, applied while that app is focused"
                        icon: "image://icon/" + page._accent + "/" + Theme.iconStyle + "/apps"
                        Badge { text: appModel.count + (appModel.count === 1 ? " profile" : " profiles"); accent: appModel.count > 0 }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Add application"
                        desc: "Window class in lowercase, for example firefox, code or gimp"
                        Row {
                            spacing: Theme.gapS
                            InputField {
                                id: appField
                                width: 260; mono: true
                                placeholder: "window class"
                                anchors.verticalCenter: parent.verticalCenter
                                onAccepted: page.addFromField()
                            }
                            PrimaryButton {
                                text: "Add"
                                enabled: appField.text.trim() !== ""
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: page.addFromField()
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Suggest profiles for new apps"
                        desc: "The first time you use an app without a profile, Settings offers to create one. Each app is asked about once"
                        Toggle {
                            checked: Backend.get("app.suggest_profiles", true)
                            onToggled: (v) => Backend.setLocal("app.suggest_profiles", v)
                        }
                    }
                }
            }

            // ===== Empty state =====
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 300
                visible: appModel.count === 0
                EmptyState {
                    anchors.fill: parent; anchors.margins: 10
                    spot: "spot_apps"
                    title: "No app profiles yet"
                    body: "Add a window class above. Its overrides apply the moment that app takes focus and lift when it loses it."
                }
            }

            // ===== One card per profile =====
            Repeater {
                model: appModel
                GlassCard {
                    id: card
                    required property int index
                    required property string app
                    required property int dpi
                    required property bool smartshiftEnabled
                    required property int smartshiftThreshold
                    required property bool hires
                    required property string thumbwheel

                    // Live per-row state (seeded from the model, mutated by controls).
                    property int vDpi: dpi
                    property bool vSsEnabled: smartshiftEnabled
                    property int vSsThreshold: smartshiftThreshold
                    property bool vHires: hires
                    property string vThumbwheel: thumbwheel

                    function save() {
                        Backend.saveAppProfile(card.app, {
                            dpi: card.vDpi,
                            smartshiftEnabled: card.vSsEnabled,
                            smartshiftThreshold: card.vSsThreshold,
                            hires: card.vHires,
                            thumbwheel: card.vThumbwheel
                        })
                    }

                    Layout.fillWidth: true
                    Layout.preferredHeight: rowsCol.implicitHeight + Theme.padCard * 2
                    Column {
                        id: rowsCol
                        anchors.fill: parent; anchors.margins: Theme.padCard
                        spacing: Theme.gapS
                        CardHeader {
                            width: parent.width
                            title: card.app
                            subtitle: "Overrides while " + card.app + " is focused"
                            icon: "image://icon/" + page._accent + "/" + Theme.iconStyle + "/application-x-executable-symbolic"
                            IconButton {
                                icon: "user-trash-symbolic"; tint: Theme.textMuted; diameter: 36
                                onClicked: { Backend.removeAppProfile(card.app); page.loadApps(); Backend.notify("Profile for " + card.app + " removed", "info") }
                            }
                        }
                        Rectangle { width: parent.width; height: 1; color: Theme.border }
                        SettingRow {
                            label: "Sensitivity"
                            desc: card.vDpi + " DPI"
                            Slider {
                                width: 240; from: 400; to: 8000
                                value: card.vDpi
                                onCommitted: (v) => { card.vDpi = Math.round(v); card.save() }
                            }
                        }
                        Rectangle { width: parent.width; height: 1; color: Theme.border }
                        SettingRow {
                            label: "SmartShift"
                            desc: "Auto-switch the scroll wheel to free-spin on a flick"
                            Toggle {
                                checked: card.vSsEnabled
                                onToggled: (v) => { card.vSsEnabled = v; card.save() }
                            }
                        }
                        Rectangle { width: parent.width; height: 1; color: Theme.border
                                    visible: ssRow.visible }
                        SettingRow {
                            id: ssRow
                            visible: card.vSsEnabled
                            label: "SmartShift sensitivity"
                            desc: "How easily a flick switches to free-spin"
                            Slider {
                                width: 220; from: 1; to: 100; showValue: true; suffix: "%"
                                value: card.vSsThreshold
                                onCommitted: (v) => { card.vSsThreshold = Math.round(v); card.save() }
                            }
                        }
                        Rectangle { width: parent.width; height: 1; color: Theme.border }
                        SettingRow {
                            label: "Hi-res scrolling"
                            desc: "Smooth, high-resolution scroll wheel"
                            Toggle {
                                checked: card.vHires
                                onToggled: (v) => { card.vHires = v; card.save() }
                            }
                        }
                        Rectangle { width: parent.width; height: 1; color: Theme.border }
                        SettingRow {
                            label: "Thumb wheel"
                            desc: "What the side wheel does in this app"
                            ComboBox {
                                width: 180
                                model: Backend.thumbwheelModes()
                                currentId: card.vThumbwheel
                                onActivated2: (id) => { card.vThumbwheel = id; card.save() }
                            }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    function addFromField() {
        var cls = appField.text.trim().toLowerCase()
        if (cls === "") return
        Backend.addAppProfile(cls)
        appField.text = ""
        loadApps()
    }
}
