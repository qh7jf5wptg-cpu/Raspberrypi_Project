import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1100
    height: 700
    visible: true
    title: qsTr("PickLine — Gripper + Conveyor HMI")
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
            spacing: 8

            Text {
                text: "PickLine — Gripper + Conveyor"
                font.pixelSize: 22
                font.bold: true
                color: "#172033"
            }
            Item { Layout.fillWidth: true }
            Rectangle { width: 10; height: 10; radius: 5; color: bridge.connected ? "#2ecc71" : "#c0392b" }
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

            // Top view: belt along the bottom, gantry picking from the bin.
            Rectangle {
                id: canvasPanel
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

                        // World: X 0..400 (belt), Y 0..220 (gantry area).
                        var s = Math.min((w - 48) / 400.0, (h - 48) / 220.0)
                        var ox = (w - 400 * s) / 2
                        var oy = (h - 220 * s) / 2

                        function X(v) { return ox + v * s }
                        function Y(v) { return oy + (220 - v) * s }

                        // Envelope.
                        ctx.strokeStyle = "#c9d2e0"
                        ctx.lineWidth = 2
                        ctx.strokeRect(ox, oy, 400 * s, 220 * s)

                        // Conveyor belt.
                        var beltTop = Y(100) - 10 * s
                        var beltBottom = Y(100) + 10 * s
                        ctx.fillStyle = "#e9edf3"
                        ctx.fillRect(X(0) - 6, beltTop, 406 * s, 20 * s)
                        ctx.strokeStyle = "#9aa7b8"
                        ctx.lineWidth = 1.5
                        ctx.strokeRect(X(0) - 6, beltTop, 406 * s, 20 * s)
                        ctx.fillStyle = "#8a97a8"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.fillText("CONVEYOR", X(200), beltBottom + 14 * s)

                        // Drop zone (belt infeed).
                        ctx.fillStyle = "rgba(0,183,199,0.20)"
                        ctx.fillRect(X(0) - 8, Y(100) - 12 * s, 16, 24 * s)
                        ctx.fillText("DROP", X(0), Y(100) - 18 * s)

                        // Bin.
                        ctx.fillStyle = "rgba(224,168,0,0.18)"
                        ctx.fillRect(X(260) - 11, Y(20) - 11, 22, 22)
                        ctx.fillStyle = "#b58a00"
                        ctx.fillText("BIN", X(260), Y(20) - 16)

                        // Sensors.
                        function sensor(cx, label) {
                            ctx.beginPath()
                            ctx.arc(cx, Y(100), 5 * s, 0, Math.PI * 2)
                            ctx.fill()
                            ctx.fillText(label, cx, Y(100) - 16 * s)
                        }
                        ctx.fillStyle = num("sensor_in", 0) > 0 ? "#2ecc71" : "#b6c0ce"
                        sensor(X(30), "IN")
                        ctx.fillStyle = num("sensor_out", 0) > 0 ? "#2ecc71" : "#b6c0ce"
                        sensor(X(370), "OUT")

                        // Part on the belt.
                        var bp = num("belt_pos", -1)
                        if (bp >= 0) {
                            ctx.fillStyle = "#e0a800"
                            ctx.beginPath()
                            ctx.arc(X(bp), Y(100), 5 * s, 0, Math.PI * 2)
                            ctx.fill()
                        }

                        // Held part follows the tool.
                        var holding = num("holding", 0) > 0
                        var px = holding ? num("part_x", num("x", 0)) : -1
                        var py = holding ? num("part_y", num("y", 0)) : -1
                        if (holding && px >= 0 && py >= 0) {
                            ctx.fillStyle = "#e0a800"
                            ctx.beginPath()
                            ctx.arc(X(px), Y(py), 4 * s, 0, Math.PI * 2)
                            ctx.fill()
                        }

                        // Gantry tool crosshair.
                        var tx = X(num("x", 0))
                        var ty = Y(num("y", 0))
                        ctx.fillStyle = holding ? "#27ae60" : "#e67e22"
                        ctx.beginPath()
                        ctx.arc(tx, ty, 8 * s, 0, Math.PI * 2)
                        ctx.fill()
                        ctx.strokeStyle = "#ffffff"
                        ctx.lineWidth = 1.5
                        ctx.beginPath(); ctx.moveTo(tx - 12 * s, ty); ctx.lineTo(tx + 12 * s, ty); ctx.stroke()
                        ctx.beginPath(); ctx.moveTo(tx, ty - 12 * s); ctx.lineTo(tx, ty + 12 * s); ctx.stroke()
                    }
                }
            }

            ColumnLayout {
                id: rightPanel
                Layout.preferredWidth: 330
                Layout.minimumWidth: 330
                Layout.maximumWidth: 330
                Layout.fillHeight: true
                spacing: 10

                // Machine state.
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
                            text: "MACHINE STATE"
                            font.pixelSize: 10
                            font.bold: true
                            color: "#7f8c9b"
                        }
                        Text {
                            text: plcOnline ? tag("state", "IDLE") : "PLC OFFLINE"
                            font.pixelSize: 26
                            font.bold: true
                            color: (!plcOnline || tag("state", "") === "FAULT") ? "#c0392b" : "#172033"
                        }
                        Text {
                            text: "mode " + tag("mode", "auto")
                                  + "   ·   placed " + tag("placed", "0")
                                  + "   ·   exited " + tag("exited", "0")
                            font.pixelSize: 12
                            color: "#637083"
                        }
                        Text {
                            text: (plantOnline ? "plant online" : "plant OFFLINE")
                                  + "   ·   " + (plcOnline ? "PLC online" : "PLC OFFLINE")
                            font.pixelSize: 11
                            color: (plantOnline && plcOnline) ? "#2e7d32" : "#c0392b"
                        }
                        Text {
                            visible: tag("alarm", "").length > 0
                            text: tag("alarm", "")
                            font.pixelSize: 12
                            color: "#c0392b"
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }

                // Axis readouts.
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 66
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 10

                        Repeater {
                            model: ["x", "y", "z"]
                            delegate: ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                Text {
                                    text: modelData.toUpperCase()
                                    font.pixelSize: 10
                                    font.bold: true
                                    color: "#7f8c9b"
                                }
                                Text {
                                    text: num(modelData, 0).toFixed(0) + " mm"
                                    font.pixelSize: 18
                                    font.bold: true
                                    color: "#172033"
                                }
                            }
                        }
                    }
                }

                // Gap between exit and the next pick.
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: gapColumn.implicitHeight + 24
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    ColumnLayout {
                        id: gapColumn
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 4

                        Text {
                            text: "GAP AFTER EXIT"
                            font.pixelSize: 10
                            font.bold: true
                            color: "#7f8c9b"
                        }
                        Text {
                            text: num("gap", 1.5).toFixed(1) + " s"
                            font.pixelSize: 18
                            font.bold: true
                            color: "#172033"
                        }
                        Slider {
                            id: gapSlider
                            Layout.fillWidth: true
                            from: 0
                            to: 10
                            stepSize: 0.1
                            value: num("gap", 1.5)
                            onMoved: if (pressed)
                                bridge.publish("pickline/command/gap", value.toFixed(1))
                            Connections {
                                target: bridge
                                function onTagsChanged() {
                                    if (!gapSlider.pressed)
                                        gapSlider.value = num("gap", gapSlider.value)
                                }
                            }
                        }
                    }
                }

                // Commands.
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 8
                    rowSpacing: 8

                    Button {
                        Layout.fillWidth: true
                        text: "Start"
                        onClicked: {
                            bridge.publish("pickline/command/mode", "auto")
                            bridge.publish("pickline/command/start", "1")
                        }
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Stop"
                        onClicked: bridge.publish("pickline/command/stop", "1")
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Reset"
                        onClicked: bridge.publish("pickline/command/reset", "1")
                    }
                    Button {
                        Layout.fillWidth: true
                        text: tag("mode", "auto") === "auto" ? "Manual mode" : "Auto mode"
                        onClicked: bridge.publish(
                            "pickline/command/mode",
                            tag("mode", "auto") === "auto" ? "manual" : "auto")
                    }
                }

                // Manual jog.
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 2

                        Text {
                            text: "MANUAL"
                            font.pixelSize: 10
                            font.bold: true
                            color: "#7f8c9b"
                        }

                        Repeater {
                            model: [["X", "x", 300], ["Y", "y", 220], ["Z", "z", 100]]
                            delegate: ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                Text {
                                    text: modelData[0] + "   " + num(modelData[1], 0).toFixed(0) + " mm"
                                    font.pixelSize: 12
                                    color: "#637083"
                                }

                                Slider {
                                    id: slider
                                    Layout.fillWidth: true
                                    from: 0
                                    to: modelData[2]
                                    enabled: tag("mode", "auto") === "manual"
                                    onMoved: if (pressed)
                                        bridge.publish("pickline/target/" + modelData[1],
                                                       Math.round(value).toString())

                                    Connections {
                                        target: bridge
                                        function onTagsChanged() {
                                            if (!slider.pressed)
                                                slider.value = num(modelData[1], slider.value)
                                        }
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Button {
                                Layout.fillWidth: true
                                text: "Open"
                                enabled: tag("mode", "auto") === "manual"
                                onClicked: bridge.publish("pickline/target/grip", "1")
                            }
                            Button {
                                Layout.fillWidth: true
                                text: "Close"
                                enabled: tag("mode", "auto") === "manual"
                                onClicked: bridge.publish("pickline/target/grip", "0")
                            }
                        }

                        Button {
                            Layout.fillWidth: true
                            text: num("belt", 0) > 0.5 ? "Stop belt" : "Run belt"
                            enabled: tag("mode", "auto") === "manual"
                            onClicked: bridge.publish("pickline/target/belt",
                                                       num("belt", 0) > 0.5 ? "0" : "1")
                        }
                    }
                }
            }
        }
    }
}
