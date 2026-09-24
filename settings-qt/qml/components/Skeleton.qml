import QtQuick

// Loading placeholder: a rounded block with a slow sheen. Replaces spinners
// where content is about to appear in place (hero, battery, readouts).
Rectangle {
    id: sk
    property real sheenWidth: 0.4
    radius: 8
    color: "#14FFFFFF"
    clip: true
    Rectangle {
        id: sheen
        width: parent.width * sk.sheenWidth; height: parent.height
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#00FFFFFF" }
            GradientStop { position: 0.5; color: "#18FFFFFF" }
            GradientStop { position: 1.0; color: "#00FFFFFF" }
        }
        NumberAnimation on x {
            from: -sheen.width; to: sk.width
            duration: 1400; loops: Animation.Infinite
            running: sk.visible
        }
    }
}
