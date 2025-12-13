/**
 * JuhRadial MX KWin Script
 *
 * Radial menu overlay renderer for KDE Plasma 6 / KWin
 * Listens to D-Bus signals from juhradiald daemon
 */

import { menuRenderer } from './menu-renderer';
import { dbusClient } from './dbus-client';
import { themeLoader } from './theme-loader';
import { geometry } from './geometry';

// D-Bus interface constants
const DBUS_SERVICE = 'org.kde.juhradialmx';
const DBUS_PATH = '/org/kde/juhradialmx/Daemon';
const DBUS_INTERFACE = 'org.kde.juhradialmx.Daemon';

/**
 * Initialize the KWin script
 */
function init(): void {
    console.log('JuhRadial MX KWin script initializing...');

    // TODO: Connect to D-Bus signals from daemon
    // - MenuRequested(x, y, profile)
    // - MenuDismissed()
    // - SliceHovered(index)

    // TODO: Load current theme
    // TODO: Set up menu overlay QML component

    console.log('JuhRadial MX KWin script ready');
}

/**
 * Handle MenuRequested signal from daemon
 */
function onMenuRequested(x: number, y: number, profile: string): void {
    console.log(`Menu requested at (${x}, ${y}) with profile: ${profile}`);

    // TODO: Calculate clamped position (20px margin from edges)
    // TODO: Show overlay at position
    // TODO: Start tracking cursor for slice selection
}

/**
 * Handle MenuDismissed signal from daemon
 */
function onMenuDismissed(): void {
    console.log('Menu dismissed');

    // TODO: Hide overlay with fade animation
    // TODO: Stop cursor tracking
}

/**
 * Calculate selected slice based on cursor position
 */
function calculateSelectedSlice(cursorX: number, cursorY: number, centerX: number, centerY: number): number {
    const dx = cursorX - centerX;
    const dy = cursorY - centerY;

    // Check if in center zone (80px diameter)
    const distanceFromCenter = Math.sqrt(dx * dx + dy * dy);
    if (distanceFromCenter < 40) {
        return -1; // Center zone, no slice
    }

    // Calculate angle and map to slice (0-7)
    // N=0, NE=1, E=2, SE=3, S=4, SW=5, W=6, NW=7
    let angle = Math.atan2(dy, dx) * (180 / Math.PI);
    angle = (angle + 90 + 360) % 360; // Rotate so 0° is North

    const sliceIndex = Math.floor(((angle + 22.5) % 360) / 45);
    return sliceIndex;
}

// Initialize on script load
init();

export { onMenuRequested, onMenuDismissed, calculateSelectedSlice };
