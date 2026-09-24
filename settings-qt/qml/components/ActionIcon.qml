import QtQuick

// Renders a freedesktop icon name through the image://icon provider, tinted.
// An absolute path (an application icon picked for a slice, cached under
// ~/.config/juhradial/icons/) is shown as-is in its own colours, the way the
// overlay draws it on the wheel.
Image {
    id: ai
    property string iconName: ""
    property color tint: Theme.textBody
    property int px: 22
    readonly property bool isFile: iconName.startsWith("/")
    source: iconName === "" ? ""
          : (isFile ? "file://" + iconName
                    : "image://icon/" + tint.toString().slice(1) + "/" + Theme.iconStyle + "/" + iconName)
    sourceSize.width: px * 2; sourceSize.height: px * 2
    width: px; height: px; smooth: true; fillMode: Image.PreserveAspectFit
}
