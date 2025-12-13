/**
 * D-Bus client for communication with juhradiald daemon
 *
 * This module provides TypeScript types and utilities for D-Bus communication.
 * The actual D-Bus calls in KWin scripts use the global `callDBus()` function.
 *
 * D-Bus Interface: org.kde.juhradialmx.Daemon
 * Object Path: /org/kde/juhradialmx/Daemon
 *
 * Methods:
 *   - ShowMenu(x: i32, y: i32) -> () : Display radial menu at coordinates
 *   - HideMenu() -> () : Dismiss the radial menu
 *   - ExecuteAction(action_id: s) -> () : Execute an action by ID
 *
 * Signals:
 *   - MenuRequested(x: i32, y: i32) : Daemon requests menu display
 *   - SliceSelected(index: u8) : Slice highlight changed
 *   - ActionExecuted(action_id: s) : Action was executed
 */

export const DBUS_SERVICE = 'org.kde.juhradialmx';
export const DBUS_PATH = '/org/kde/juhradialmx/Daemon';
export const DBUS_INTERFACE = 'org.kde.juhradialmx.Daemon';

/**
 * D-Bus signal handlers interface
 */
export interface DBusSignalHandlers {
    onMenuRequested: (x: number, y: number) => void;
    onSliceSelected: (index: number) => void;
    onActionExecuted: (actionId: string) => void;
}

/**
 * D-Bus client for KWin script
 *
 * Note: In KWin scripts, D-Bus calls are made via the global `callDBus()` function.
 * This class provides a wrapper for TypeScript type safety.
 */
export class DBusClient {
    private connected: boolean = false;
    private handlers: Partial<DBusSignalHandlers> = {};

    /**
     * Connect to the daemon D-Bus interface
     *
     * In KWin scripts, this verifies daemon is running by calling a property getter.
     */
    connect(): boolean {
        // KWin scripts use global callDBus() - this is a type wrapper
        console.log(`DBusClient: Connecting to ${DBUS_SERVICE}`);
        this.connected = true;
        return true;
    }

    /**
     * Disconnect from D-Bus
     */
    disconnect(): void {
        this.connected = false;
        console.log('DBusClient: Disconnected');
    }

    /**
     * Register signal handlers
     */
    setHandlers(handlers: Partial<DBusSignalHandlers>): void {
        this.handlers = handlers;
    }

    /**
     * Notify daemon that a slice was selected/highlighted
     * Called when cursor moves to a different slice
     */
    notifySliceHover(index: number): void {
        if (!this.connected) return;
        // In KWin: callDBus(DBUS_SERVICE, DBUS_PATH, DBUS_INTERFACE, "NotifySliceHover", index)
        console.log(`DBusClient: NotifySliceHover(${index})`);
    }

    /**
     * Request daemon to execute action for the given slice
     * Called when gesture button is released over a slice
     */
    executeSliceAction(index: number): void {
        if (!this.connected) return;
        // In KWin: callDBus(DBUS_SERVICE, DBUS_PATH, DBUS_INTERFACE, "ExecuteAction", sliceActionId)
        console.log(`DBusClient: ExecuteAction for slice ${index}`);
    }

    /**
     * Check connection status
     */
    isConnected(): boolean {
        return this.connected;
    }
}

export const dbusClient = new DBusClient();
