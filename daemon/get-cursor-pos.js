// KWin script to print cursor position
// Run with: qdbus-qt6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript /path/to/this.js
print("CURSOR_POS:" + workspace.cursorPos.x + "," + workspace.cursorPos.y);
