import QtQuick

// SpotImage.qml without QtQuick.VectorImage (Qt older than 6.8, or the module
// is not installed): the same accent-coloured file from Theme.spot(), decoded
// by the SVG image plugin at twice the shown size.
Item {
    id: sp
    property string name: ""
    property int size: 120
    property real dim: 1.0
    width: size; height: size
    readonly property string _src: name !== "" ? Theme.spot(name) : ""
    opacity: dim
    Image {
        anchors.fill: parent
        visible: sp._src !== ""
        source: sp._src
        sourceSize.width: sp.size * 2; sourceSize.height: sp.size * 2
        fillMode: Image.PreserveAspectFit; smooth: true
    }
}
