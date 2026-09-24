import QtQuick
import QtQuick.VectorImage

// Spot illustration. SVG masters carry a #ACCENT token that Theme.spot()
// substitutes with the live accent, so every illustration follows the theme.
// Falls back to the legacy PNG when no SVG master exists.
Item {
    id: sp
    property string name: ""
    property int size: 120
    property real dim: 1.0
    width: size; height: size
    readonly property string _src: name !== "" ? Theme.spot(name) : ""
    readonly property bool _svg: _src.toLowerCase().endsWith(".svg")
    opacity: dim
    VectorImage {
        anchors.fill: parent
        visible: sp._svg
        source: sp._svg ? sp._src : ""
        fillMode: VectorImage.PreserveAspectFit
        preferredRendererType: VectorImage.CurveRenderer
    }
    Image {
        anchors.fill: parent
        visible: !sp._svg && sp._src !== ""
        source: (!sp._svg && sp._src !== "") ? sp._src : ""
        sourceSize.width: sp.size * 2; sourceSize.height: sp.size * 2
        fillMode: Image.PreserveAspectFit; smooth: true
    }
}
