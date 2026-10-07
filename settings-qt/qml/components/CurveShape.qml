import QtQuick.Shapes

// A Shape drawn by the curve renderer (antialiased without multisampling),
// which Qt has from 6.6. +nocurve/CurveShape.qml is the plain Shape.
Shape { preferredRendererType: Shape.CurveRenderer }
