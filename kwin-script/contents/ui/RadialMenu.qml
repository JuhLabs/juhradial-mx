/**
 * JuhRadial MX - Radial Menu Overlay Component
 *
 * Proof-of-concept QML overlay for KDE Plasma 6
 *
 * Features:
 * - Frameless overlay window
 * - 8-slice radial menu with center zone
 * - Glassmorphism effect (blur + transparency)
 * - No focus stealing
 */

import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtGraphicalEffects 1.15
import org.kde.plasma.core 2.0 as PlasmaCore

Window {
    id: menuWindow

    // Window properties for overlay behavior
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.BypassWindowManagerHint | Qt.Tool
    color: "transparent"

    // Menu dimensions from UX spec
    width: 280
    height: 280

    // Don't steal focus
    property bool activeFocusOnPress: false

    // Menu state
    property int highlightedSlice: -1
    property int previousSlice: -1  // For change detection
    property bool menuVisible: false
    property var sliceActions: []

    // Menu geometry for slice calculation
    property int centerX: width / 2
    property int centerY: height / 2
    property int centerZoneRadius: 40  // 80px diameter / 2

    // Theme colors (Catppuccin Mocha defaults)
    property color backgroundColor: "#1e1e2e"
    property color surfaceColor: "#313244"
    property color accentColor: "#cba6f7"
    property color textColor: "#cdd6f4"
    property color borderColor: "#45475a"
    property real backgroundOpacity: 0.75
    property real blurRadius: 24

    // Animation timings
    property int appearDuration: reducedMotion ? 0 : 30
    property int dismissDuration: reducedMotion ? 0 : 50
    property int highlightInDuration: reducedMotion ? 0 : 80
    property int highlightOutDuration: reducedMotion ? 0 : 60

    // Accessibility: Reduced motion support (Story 2.7 AC3)
    property bool reducedMotion: false  // Set from system accessibility settings

    // Performance monitoring (AC4: GPU fallback)
    property bool blurEnabled: true
    property int frameDropCount: 0
    property int targetFrameTime: 16  // ~60fps in ms
    property int maxFrameDrops: 3     // Disable blur after 3 consecutive drops

    // ==========================================================================
    // Main Container
    // ==========================================================================

    Rectangle {
        id: menuContainer
        anchors.fill: parent
        color: "transparent"

        // Background with conditional blur effect
        Rectangle {
            id: menuBackground
            anchors.centerIn: parent
            width: 280
            height: 280
            radius: 140
            color: Qt.rgba(
                backgroundColor.r,
                backgroundColor.g,
                backgroundColor.b,
                backgroundOpacity
            )
            border.color: borderColor
            border.width: 1

            // Blur effect (requires GraphicalEffects) - conditional for performance
            layer.enabled: blurEnabled
            layer.effect: blurEnabled ? blurEffect : null

            Component {
                id: blurEffect
                GaussianBlur {
                    radius: blurRadius
                    samples: 32
                }
            }
        }

        // =======================================================================
        // 8 Slice Segments
        // =======================================================================

        Repeater {
            model: 8

            Item {
                id: sliceItem
                anchors.centerIn: parent
                width: 280
                height: 280

                property int sliceIndex: index
                property bool isHighlighted: highlightedSlice === index

                // AC3: Structural feedback - subtle scale on hover
                scale: isHighlighted ? 1.03 : 1.0
                Behavior on scale {
                    NumberAnimation {
                        duration: isHighlighted ? highlightInDuration : highlightOutDuration
                        easing.type: Easing.OutQuad
                    }
                }

                // Slice wedge shape
                Canvas {
                    id: sliceCanvas
                    anchors.fill: parent

                    // AC3: NO color tinting on hover - only structural feedback
                    // Use same base color regardless of highlight state
                    property color fillColor: surfaceColor
                    property real fillOpacity: 0.3

                    // Structural feedback: border becomes more prominent on hover
                    property color borderStrokeColor: isHighlighted ? accentColor : borderColor
                    property real borderWidth: isHighlighted ? 2.0 : 1.0
                    property real borderOpacity: isHighlighted ? 0.9 : 0.5

                    onPaint: {
                        var ctx = getContext("2d");
                        ctx.reset();

                        var centerX = width / 2;
                        var centerY = height / 2;
                        var innerRadius = 40;  // Center zone
                        var outerRadius = 130; // Outer edge

                        // Calculate angles for this slice
                        // Slice 0 = North, proceeding clockwise
                        var startAngle = (index * 45 - 112.5) * Math.PI / 180;
                        var endAngle = (index * 45 - 67.5) * Math.PI / 180;

                        // Draw wedge
                        ctx.beginPath();
                        ctx.arc(centerX, centerY, outerRadius, startAngle, endAngle);
                        ctx.arc(centerX, centerY, innerRadius, endAngle, startAngle, true);
                        ctx.closePath();

                        // Fill with base color (NO color change on hover)
                        ctx.fillStyle = Qt.rgba(
                            fillColor.r,
                            fillColor.g,
                            fillColor.b,
                            fillOpacity
                        );
                        ctx.fill();

                        // Border - structural feedback via opacity and width
                        ctx.strokeStyle = Qt.rgba(
                            borderStrokeColor.r,
                            borderStrokeColor.g,
                            borderStrokeColor.b,
                            borderOpacity
                        );
                        ctx.lineWidth = borderWidth;
                        ctx.stroke();
                    }

                    // Repaint when highlight changes
                    Connections {
                        target: menuWindow
                        function onHighlightedSliceChanged() {
                            sliceCanvas.requestPaint();
                        }
                    }
                }

                // Slice icon placeholder
                Text {
                    id: sliceIcon
                    anchors.centerIn: parent

                    // Position icon at 100px from center
                    property real iconAngle: (index * 45 - 90) * Math.PI / 180
                    property real iconDistance: 100

                    x: parent.width / 2 + Math.cos(iconAngle) * iconDistance - width / 2
                    y: parent.height / 2 + Math.sin(iconAngle) * iconDistance - height / 2

                    text: getSliceIcon(index)
                    font.pixelSize: 24
                    // AC3: Structural feedback - opacity change instead of color tint
                    color: textColor
                    opacity: isHighlighted ? 1.0 : 0.6

                    // Structural feedback animation
                    Behavior on opacity {
                        NumberAnimation {
                            duration: isHighlighted ? highlightInDuration : highlightOutDuration
                        }
                    }
                }
            }
        }

        // =======================================================================
        // Center Zone
        // =======================================================================

        Rectangle {
            id: centerZone
            anchors.centerIn: parent
            width: 80
            height: 80
            radius: 40
            color: Qt.rgba(surfaceColor.r, surfaceColor.g, surfaceColor.b, 0.5)
            border.color: borderColor
            border.width: 1

            Text {
                anchors.centerIn: parent
                text: highlightedSlice >= 0 ? "Release" : "Drag"
                font.pixelSize: 12
                color: textColor
                opacity: 0.7
            }
        }
    }

    // ==========================================================================
    // Appear/Disappear Animations
    // ==========================================================================

    opacity: menuVisible ? 1.0 : 0.0
    scale: menuVisible ? 1.0 : 0.8

    Behavior on opacity {
        NumberAnimation {
            duration: menuVisible ? appearDuration : dismissDuration
            easing.type: Easing.OutQuad
        }
    }

    Behavior on scale {
        NumberAnimation {
            duration: menuVisible ? appearDuration : dismissDuration
            easing.type: Easing.OutQuad
        }
    }

    // ==========================================================================
    // Helper Functions
    // ==========================================================================

    function getSliceIcon(index) {
        // Default icons for PoC (N, NE, E, SE, S, SW, W, NW)
        var icons = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
        return icons[index] || "?";
    }

    function show(x, y) {
        menuWindow.x = x - width / 2;
        menuWindow.y = y - height / 2;
        menuVisible = true;
        menuWindow.visible = true;
    }

    function hide() {
        menuVisible = false;
        // Hide window after animation completes
        hideTimer.start();
    }

    /**
     * Hide menu and optionally execute action (Story 2.7)
     *
     * @param executeAction - Whether to execute the selected action
     *                       AC2: If in center zone, no action is executed
     */
    function hideWithAction(executeAction) {
        var selectedSlice = highlightedSlice;

        // AC2: Center zone release - no action
        if (selectedSlice < 0) {
            console.log("JuhRadial: Released in center zone - no action");
            hide();
            return -1;
        }

        // Execute action if requested and slice is valid
        if (executeAction && selectedSlice >= 0 && selectedSlice < 8) {
            console.log("JuhRadial: Executing action for slice " + selectedSlice);
            // TODO: Emit ActionExecuted signal (Story 2.6)
        }

        hide();
        return selectedSlice;
    }

    /**
     * Set reduced motion from system settings
     * Called by KWin script after querying accessibility settings
     */
    function setReducedMotion(enabled) {
        reducedMotion = enabled;
        console.log("JuhRadial: Reduced motion " + (enabled ? "enabled" : "disabled"));
    }

    function setHighlight(sliceIndex) {
        highlightedSlice = sliceIndex;
    }

    // ==========================================================================
    // Slice Selection (Story 2.5)
    // ==========================================================================

    /**
     * Calculate which slice the cursor is in based on screen coordinates
     * Returns -1 for center zone, 0-7 for slices (N, NE, E, SE, S, SW, W, NW)
     *
     * @param screenX - Cursor X position on screen
     * @param screenY - Cursor Y position on screen
     */
    function calculateSliceFromScreen(screenX, screenY) {
        // Convert screen coordinates to menu-relative coordinates
        var localX = screenX - menuWindow.x;
        var localY = screenY - menuWindow.y;

        return calculateSlice(localX, localY);
    }

    /**
     * Calculate slice from menu-local coordinates
     * AC1: Center zone (80px diameter) returns -1
     * AC3: 8 slices at 45° each, N=0, NE=1, E=2, etc.
     */
    function calculateSlice(localX, localY) {
        var dx = localX - centerX;
        var dy = localY - centerY;

        // Check center zone (AC1: 80px diameter = 40px radius)
        var distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < centerZoneRadius) {
            return -1;
        }

        // Calculate angle (0 = North, clockwise)
        // atan2(dx, -dy) gives angle from North
        var angle = Math.atan2(dx, -dy) * (180 / Math.PI);
        angle = (angle + 360) % 360;

        // Map to slice index (each slice is 45°, offset by 22.5° for centering)
        // AC3: N=0, NE=1, E=2, SE=3, S=4, SW=5, W=6, NW=7
        return Math.floor(((angle + 22.5) % 360) / 45);
    }

    /**
     * Update highlight based on cursor position
     * Called from cursor tracking
     */
    function updateHighlightFromCursor(screenX, screenY) {
        var newSlice = calculateSliceFromScreen(screenX, screenY);

        if (newSlice !== highlightedSlice) {
            previousSlice = highlightedSlice;
            highlightedSlice = newSlice;

            // Emit slice change signal (for D-Bus and haptics)
            onSliceChanged(newSlice, previousSlice);
        }
    }

    /**
     * Signal handler for slice changes
     * Placeholder for D-Bus signal and haptic feedback (Story 5.3)
     */
    function onSliceChanged(newSlice, oldSlice) {
        console.log("JuhRadial: Slice changed from " + oldSlice + " to " + newSlice);

        // TODO: Emit D-Bus SliceSelected signal
        // TODO: Trigger haptic feedback (Story 5.3)
    }

    // Mouse area for cursor tracking within menu bounds
    MouseArea {
        id: cursorTracker
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton  // Don't capture clicks

        onPositionChanged: {
            if (menuVisible) {
                var screenX = menuWindow.x + mouse.x;
                var screenY = menuWindow.y + mouse.y;
                updateHighlightFromCursor(screenX, screenY);
            }
        }
    }

    Timer {
        id: hideTimer
        interval: dismissDuration
        onTriggered: menuWindow.visible = false
    }

    // ==========================================================================
    // Performance Monitoring (AC4: GPU Fallback)
    // ==========================================================================

    property var lastFrameTime: 0

    Timer {
        id: frameTimer
        interval: 16  // ~60fps
        repeat: true
        running: menuVisible && blurEnabled

        onTriggered: {
            var now = Date.now();
            if (lastFrameTime > 0) {
                var frameTime = now - lastFrameTime;

                if (frameTime > targetFrameTime * 1.5) {
                    // Frame took longer than expected
                    frameDropCount++;
                    console.log("JuhRadial: Frame drop detected (" + frameTime + "ms), count: " + frameDropCount);

                    if (frameDropCount >= maxFrameDrops) {
                        // Disable blur for performance
                        console.log("JuhRadial: Disabling blur for performance (3 consecutive frame drops)");
                        blurEnabled = false;
                        frameDropCount = 0;
                    }
                } else {
                    // Good frame, reset counter
                    frameDropCount = 0;
                }
            }
            lastFrameTime = now;
        }
    }

    // Reset performance monitoring when menu is shown
    onMenuVisibleChanged: {
        if (menuVisible) {
            lastFrameTime = 0;
            frameDropCount = 0;
            // Re-enable blur for each show (can be disabled if performance issues)
            // blurEnabled = true;  // Uncomment to auto-re-enable blur
        }
    }

    // ==========================================================================
    // Render Latency Logging
    // ==========================================================================

    property var showRequestTime: 0

    function showWithLatencyTracking(x, y, requestTime) {
        showRequestTime = requestTime || Date.now();
        show(x, y);
    }

    onVisibleChanged: {
        if (visible && showRequestTime > 0) {
            var latency = Date.now() - showRequestTime;
            console.log("JuhRadial: Render latency: " + latency + "ms");
            if (latency > 50) {
                console.warn("JuhRadial: Render latency exceeded 50ms target!");
            }
            showRequestTime = 0;
        }
    }
}
