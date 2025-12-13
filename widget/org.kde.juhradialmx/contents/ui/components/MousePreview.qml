/*
 * MousePreview.qml - Interactive MX Master 4 Preview (Story 6.1)
 *
 * Displays an SVG image of the MX Master 4 mouse with:
 * - Gesture button zone highlighted (always visible glow)
 * - Interactive pulse animation on hover
 * - Grayscale mode when daemon/mouse unavailable
 * - Status indicator for connection state
 *
 * SPDX-License-Identifier: GPL-3.0
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import org.kde.kirigami as Kirigami

Item {
    id: mousePreview

    // Public properties
    property bool connected: true          // Daemon connected & mouse detected
    property bool mouseDetected: true      // Mouse specifically detected
    property bool daemonRunning: true      // Daemon is running
    property string statusMessage: ""      // Error/status message to display

    // Minimum size for the component
    implicitWidth: 240
    implicitHeight: 380

    // Mouse image container
    Item {
        id: mouseContainer
        anchors.centerIn: parent
        width: Math.min(parent.width * 0.9, 200)
        height: width * 1.6  // Maintain aspect ratio

        // The MX Master 4 SVG image
        Image {
            id: mouseImage
            anchors.fill: parent
            source: "../assets/mx-master-4.svg"
            sourceSize: Qt.size(200, 320)
            fillMode: Image.PreserveAspectFit
            smooth: true
            antialiasing: true

            // Apply grayscale when not connected using layer effect
            layer.enabled: !mousePreview.connected
            layer.effect: MultiEffect {
                saturation: -1.0  // Full desaturation = grayscale
            }
        }

        // Gesture button highlight overlay (pulsing glow)
        Rectangle {
            id: gestureHighlight
            visible: mousePreview.connected

            // Position over the gesture button area (left side, middle)
            x: mouseContainer.width * 0.05
            y: mouseContainer.height * 0.52
            width: mouseContainer.width * 0.2
            height: mouseContainer.width * 0.18

            radius: height / 2
            color: "transparent"
            border.width: 2
            border.color: Kirigami.Theme.highlightColor

            // Pulsing animation
            SequentialAnimation on opacity {
                running: mousePreview.connected && gestureArea.containsMouse
                loops: Animation.Infinite
                NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutQuad }
                NumberAnimation { to: 0.4; duration: 600; easing.type: Easing.InOutQuad }
            }

            // Static glow when not hovered
            opacity: gestureArea.containsMouse ? 1.0 : 0.6
        }

        // Glow effect behind gesture button
        Rectangle {
            id: gestureGlow
            visible: mousePreview.connected
            x: gestureHighlight.x - 5
            y: gestureHighlight.y - 5
            width: gestureHighlight.width + 10
            height: gestureHighlight.height + 10
            radius: height / 2
            color: Kirigami.Theme.highlightColor
            opacity: gestureArea.containsMouse ? 0.3 : 0.15

            Behavior on opacity {
                NumberAnimation { duration: 200 }
            }
        }

        // Interactive hover area for gesture button
        MouseArea {
            id: gestureArea
            x: mouseContainer.width * 0.0
            y: mouseContainer.height * 0.48
            width: mouseContainer.width * 0.3
            height: mouseContainer.width * 0.25
            hoverEnabled: true
            cursorShape: mousePreview.connected ? Qt.PointingHandCursor : Qt.ArrowCursor

            onClicked: {
                if (mousePreview.connected) {
                    gestureClickAnim.start()
                    // Emit signal for potential haptic test
                    mousePreview.gestureButtonClicked()
                }
            }
        }

        // Click animation
        SequentialAnimation {
            id: gestureClickAnim

            NumberAnimation {
                target: gestureHighlight
                property: "scale"
                to: 1.3
                duration: 100
                easing.type: Easing.OutQuad
            }
            NumberAnimation {
                target: gestureHighlight
                property: "scale"
                to: 1.0
                duration: 200
                easing.type: Easing.OutElastic
            }
        }
    }

    // Status indicator below mouse
    ColumnLayout {
        anchors.top: mouseContainer.bottom
        anchors.topMargin: Kirigami.Units.largeSpacing
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Kirigami.Units.smallSpacing

        // Connection status row
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: Kirigami.Units.smallSpacing

            // Status LED
            Rectangle {
                width: 12
                height: 12
                radius: 6
                color: {
                    if (mousePreview.connected) return Kirigami.Theme.positiveTextColor
                    if (mousePreview.daemonRunning) return Kirigami.Theme.neutralTextColor
                    return Kirigami.Theme.negativeTextColor
                }

                // Pulse animation when connected
                SequentialAnimation on opacity {
                    running: mousePreview.connected
                    loops: Animation.Infinite
                    NumberAnimation { to: 1.0; duration: 1000 }
                    NumberAnimation { to: 0.5; duration: 1000 }
                }
            }

            Label {
                text: {
                    if (mousePreview.connected) return "MX Master 4 Connected"
                    if (mousePreview.daemonRunning && !mousePreview.mouseDetected)
                        return "Mouse Not Detected"
                    if (!mousePreview.daemonRunning)
                        return "Daemon Not Running"
                    return "Disconnected"
                }
                color: mousePreview.connected
                    ? Kirigami.Theme.positiveTextColor
                    : Kirigami.Theme.disabledTextColor
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }

        // Error/status message
        Label {
            visible: mousePreview.statusMessage !== ""
            text: mousePreview.statusMessage
            color: Kirigami.Theme.negativeTextColor
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            Layout.maximumWidth: mouseContainer.width
        }

        // Gesture button label
        Label {
            visible: mousePreview.connected
            text: "Click gesture button to trigger radial menu"
            color: Kirigami.Theme.disabledTextColor
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            font.italic: true
        }
    }

    // Tooltip when hovering gesture button
    ToolTip {
        visible: gestureArea.containsMouse && mousePreview.connected
        text: "Gesture Button\nHold to open radial menu"
        delay: 500
    }

    // Signals
    signal gestureButtonClicked()
}
