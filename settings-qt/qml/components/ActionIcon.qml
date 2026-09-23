import QtQuick

// Renders a freedesktop icon name through the image://icon provider, tinted.
Image {
    id: ai
    property string iconName: ""
    property color tint: Theme.textBody
    property int px: 22
    source: iconName !== "" ? "image://icon/" + tint.toString().slice(1) + "/" + iconName : ""
    sourceSize.width: px * 2; sourceSize.height: px * 2
    width: px; height: px; smooth: true; fillMode: Image.PreserveAspectFit
}
