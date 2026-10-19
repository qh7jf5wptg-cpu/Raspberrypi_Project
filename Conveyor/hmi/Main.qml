import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1000
    height: 620
    visible: true
    title: qsTr("Conveyor — Diverter HMI")
    color: "#eef2f8"

    function tag(name, fallback) {
        var value = bridge.tags[name]
        return (value === undefined || value === null) ? fallback : String(value)
    }

    function num(name, fallback) {
        var value = Number(bridge.tags[name])
        return isNaN(value) ? fallback : value
    }

    property real plantSeen: 0
    property real plcSeen: 0
    property bool plantOnline: false
    property bool plcOnline: false

    Connections {
        target: bridge
        function onTagsChanged() {
            var now = Date.now()
            if (bridge.tags["plant/alive"] !== undefined) plantSeen = now
            if (bridge.tags["plc/alive"] !== undefined) plcSeen = now
        }
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: {
            var now = Date.now()
            plantOnline = (now - plantSeen) < 3500
            plcOnline = (now - plcSeen) < 3500
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "Conveyor — Diverter"
                font.pixelSize: 22
                font.bold: true
                color: "#172033"
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                width: 10
                height: 10
                radius: 5
                color: bridge.connected ? "#2ecc71" : "#c0392b"
            }
            Text {
                text: bridge.connected ? "broker connected" : "no broker"
                font.pixelSize: 12
                color: "#637083"
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 200
                radius: 14
                color: "#ffffff"
                border.color: "#dfe5ef"

                Canvas {
                    id: view
                    anchors.fill: parent
                    anchors.margins: 16

                    Connections {
                        target: bridge
                        function onTagsChanged() { view.requestPaint() }
                    }

                    onPaint: {
                        var ctx = getContext("2d")
                        var w = width
                        var h = height
                        ctx.clearRect(0, 0, w, h)

                        // mm -> px: x 0..400, y -20..130
                        var pad = 24
                        var sx = (w - 2 * pad) / 400.0
                        var sy = (h - 2 * pad) / 150.0
                        function X(v) { return pad + v * sx }
                        function Y(v) { return pad + (130 - v) * sy }

                        // main belt
                        ctx.fillStyle = num("belt", 1) > 0.5 ? "#8aa2bd" : "#c8d0da"
                        ctx.fillRect(X(0), Y(-8), 400 * sx, 16 * sy)

                        // divert lane
                        ctx.fillStyle = "#b8d4e6"
                        ctx.fillRect(X(244), Y(120), 12 * sx, 120 * sy)

                        // sensors
                        ctx.fillStyle = num("sensor1", 0) > 0 ? "#2ecc71" : "#95a5a6"
                        ctx.fillRect(X(116), Y(-6), 8 * sx, 12 * sy)
                        ctx.fillStyle = num("sensor2", 0) > 0 ? "#2ecc71" : "#95a5a6"
                        ctx.fillRect(X(336), Y(-6), 8 * sx, 12 * sy)

                        ctx.fillStyle = "#7f8c9b"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.fillText("S1", X(120), Y(14))
                        ctx.fillText("S2", X(340), Y(14))

                        // gate
                        var g = num("diverter", 0)
                        ctx.fillStyle = g > 0.5 ? "#e67e22" : "#7f8c9b"
                        ctx.fillRect(X(246), Y(0) - g * 20 * sy, 8 * sx, 20 * sy)

                        // part
                        var px = num("part_x", -100)
                        if (px >= 0) {
                            var py = num("part_y", 0)
                            ctx.fillStyle = "#e0a800"
                            ctx.beginPath()
                            ctx.arc(X(px), Y(py), 6, 0, Math.PI * 2)
                            ctx.fill()
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.preferredWidth: 330
                Layout.minimumWidth: 330
                Layout.maximumWidth: 330
                Layout.fillHeight: true
                spacing: 10

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: stateColumn.implicitHeight + 24
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    ColumnLayout {
                        id: stateColumn
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 3

                        Text {
                            text: "LINE STATE"
                            font.pixelSize: 10
                            font.bold: true
                            color: "#7f8c9b"
                        }
                        Text {
                            text: plcOnline ? tag("state", "IDLE") : "PLC OFFLINE"
                            font.pixelSize: 26
                            font.bold: true
                            color: plcOnline ? "#172033" : "#c0392b"
                        }
                        Text {
                            text: tag("decision", "STRAIGHT") + "   ·   mode " + tag("mode", "alternate")
                            font.pixelSize: 12
                            color: "#637083"
                        }
                        Text {
                            text: "passed " + tag("passed", "0") + "   ·   diverted " + tag("diverted", "0")
                            font.pixelSize: 14
                            font.bold: true
                            color: "#172033"
                        }
                        Text {
                            text: (plantOnline ? "plant online" : "plant OFFLINE")
                                  + "   ·   " + (plcOnline ? "PLC online" : "PLC OFFLINE")
                            font.pixelSize: 11
                            color: (plantOnline && plcOnline) ? "#2e7d32" : "#c0392b"
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 8
                    rowSpacing: 8

                    Button {
                        Layout.fillWidth: true
                        text: "Start"
                        onClicked: {
                            var m = tag("mode", "alternate")
                            if (m === "manual") m = "alternate"
                            bridge.publish("conveyor/command/mode", m)
                            bridge.publish("conveyor/command/start", "1")
                        }
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Stop"
                        onClicked: bridge.publish("conveyor/command/stop", "1")
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Reset"
                        onClicked: bridge.publish("conveyor/command/reset", "1")
                    }
                    Button {
                        Layout.fillWidth: true
                        text: tag("mode", "alternate")
                        onClicked: {
                            var next = "alternate"
                            if (tag("mode", "") === "alternate") next = "divert_all"
                            else if (tag("mode", "") === "divert_all") next = "pass_all"
                            else if (tag("mode", "") === "pass_all") next = "manual"
                            bridge.publish("conveyor/command/mode", next)
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        Text {
                            text: "MANUAL"
                            font.pixelSize: 10
                            font.bold: true
                            color: "#7f8c9b"
                        }

                        Button {
                            Layout.fillWidth: true
                            text: num("belt", 1) > 0.5 ? "Stop belt" : "Run belt"
                            enabled: tag("mode", "") === "manual"
                            onClicked: bridge.publish("conveyor/target/belt",
                                                       num("belt", 1) > 0.5 ? "0" : "1")
                        }

                        Button {
                            Layout.fillWidth: true
                            text: num("diverter", 0) > 0.5 ? "Retract diverter" : "Extend diverter"
                            enabled: tag("mode", "") === "manual"
                            onClicked: bridge.publish("conveyor/target/diverter",
                                                       num("diverter", 0) > 0.5 ? "0" : "1")
                        }

                        Item { Layout.fillHeight: true }
                    }
                }
            }
        }
    }
}
