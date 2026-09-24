import QtQuick

// Small uppercase section label used inside cards to group settings.
// It IS a Text: set `text` directly. Styling is fixed to the design tokens.
Text {
    color: Theme.textMuted
    font.family: Theme.fontUI
    font.pixelSize: Theme.fsMicro
    font.weight: Font.DemiBold
    font.letterSpacing: 1.2
    font.capitalization: Font.AllUppercase
}
