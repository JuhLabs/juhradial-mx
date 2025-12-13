/**
 * Geometry calculations for radial menu
 *
 * Handles slice hit testing and position calculations
 */

import { MENU_DIAMETER, CENTER_ZONE_DIAMETER } from './menu-renderer';

/** Direction indices */
export const Direction = {
    NORTH: 0,
    NORTH_EAST: 1,
    EAST: 2,
    SOUTH_EAST: 3,
    SOUTH: 4,
    SOUTH_WEST: 5,
    WEST: 6,
    NORTH_WEST: 7,
    CENTER: -1
} as const;

/** Direction labels */
export const DirectionLabels = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

/**
 * Calculate distance from center
 */
export function distanceFromCenter(cursorX: number, cursorY: number, centerX: number, centerY: number): number {
    const dx = cursorX - centerX;
    const dy = cursorY - centerY;
    return Math.sqrt(dx * dx + dy * dy);
}

/**
 * Check if cursor is in center zone
 */
export function isInCenterZone(cursorX: number, cursorY: number, centerX: number, centerY: number): boolean {
    return distanceFromCenter(cursorX, cursorY, centerX, centerY) < (CENTER_ZONE_DIAMETER / 2);
}

/**
 * Check if cursor is within menu bounds
 */
export function isInMenuBounds(cursorX: number, cursorY: number, centerX: number, centerY: number): boolean {
    return distanceFromCenter(cursorX, cursorY, centerX, centerY) <= (MENU_DIAMETER / 2);
}

/**
 * Calculate slice index from cursor position
 * Returns -1 for center zone, 0-7 for slices
 */
export function getSliceAtPosition(cursorX: number, cursorY: number, centerX: number, centerY: number): number {
    // Check center zone first
    if (isInCenterZone(cursorX, cursorY, centerX, centerY)) {
        return Direction.CENTER;
    }

    const dx = cursorX - centerX;
    const dy = cursorY - centerY;

    // Calculate angle in degrees
    // atan2 returns angle from positive X axis, we need from negative Y (North)
    let angle = Math.atan2(dy, dx) * (180 / Math.PI);

    // Rotate so 0° is North (pointing up)
    angle = (angle + 90 + 360) % 360;

    // Each slice is 45°, offset by 22.5° so slice 0 (North) is centered on 0°
    const sliceIndex = Math.floor(((angle + 22.5) % 360) / 45);

    return sliceIndex;
}

/**
 * Get the angle range for a slice
 */
export function getSliceAngleRange(sliceIndex: number): { start: number; end: number } {
    const baseAngle = sliceIndex * 45;
    return {
        start: (baseAngle - 22.5 + 360) % 360,
        end: (baseAngle + 22.5) % 360
    };
}

/**
 * Clamp menu position to screen bounds
 */
export function clampToScreen(
    x: number,
    y: number,
    screenWidth: number,
    screenHeight: number,
    margin: number = 20
): { x: number; y: number } {
    const radius = MENU_DIAMETER / 2;

    const clampedX = Math.max(margin + radius, Math.min(screenWidth - margin - radius, x));
    const clampedY = Math.max(margin + radius, Math.min(screenHeight - margin - radius, y));

    return { x: clampedX, y: clampedY };
}

/**
 * Get icon position for a slice
 */
export function getIconPosition(sliceIndex: number, centerX: number, centerY: number, iconDistance: number = 100): { x: number; y: number } {
    // Angle for slice center (in radians)
    const angle = ((sliceIndex * 45) - 90) * (Math.PI / 180);

    return {
        x: centerX + Math.cos(angle) * iconDistance,
        y: centerY + Math.sin(angle) * iconDistance
    };
}
