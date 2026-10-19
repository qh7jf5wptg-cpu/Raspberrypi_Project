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

    function gripState() { return num("grip", 1) > 0.5 ? "OPEN" : "CLOSED" }
    function holdingState() { return num("holding", 0) > 0 ? "HOLDING PART" : "EMPTY" }
    function beltState() {
        if (num("holding", 0) > 0) return "waiting (part held)"
        if (num("part_x", -1) < 0) return "empty"
        return num("part_y", 0) > 100 ? "part diverting" : "part on belt"
    }

    property real plantSeen: 0
    property real plcSeen: 0
    property bool plantOnline: false
    property bool plcOnline: false

    Connections {
        target: bridge
        function onTagsChanged() {
            var now = Date.now()
            if (bridge.tags["plant/alive"] !== undefined) {
                plantSeen = now
                plantOnline = true
            }
            if (bridge.tags["plc/alive"] !== undefined) {
                plcSeen = now
                plcOnline = true
            }
        }
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: {
            var now = Date.now()
            plantOnline = (now - plantSeen) < 5000
            plcOnline = (now - plcSeen) < 5000
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: "PickLine — Gripper + Conveyor"
                font.pixelSize: 20
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
            spacing: 14

            // Top view: belt along the middle, bins at right, side lane at the end.
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

                        // Side lane: turns +Y at the END of the belt (x = 400).
                        var gateX = X(400)
                        ctx.fillStyle = "#f4ead8"
                        ctx.fillRect(gateX - 7 * s, Y(220), 14 * s, 120 * s)
                        ctx.strokeStyle = "#c9b58d"
                        ctx.lineWidth = 1.5
                        ctx.strokeRect(gateX - 7 * s, Y(220), 14 * s, 120 * s)
                        ctx.fillStyle = "#9a8460"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.fillText("DIVERT", gateX, Y(220) - 8 * s)

                        // Conveyor belt (straight run).
                        var beltTop = Y(100) - 10 * s
                        ctx.fillStyle = "#e9edf3"
                        ctx.fillRect(X(0) - 6, beltTop, 406 * s, 20 * s)
                        ctx.strokeStyle = "#9aa7b8"
                        ctx.lineWidth = 1.5
                        ctx.strokeRect(X(0) - 6, beltTop, 406 * s, 20 * s)
                        ctx.fillStyle = "#8a97a8"
                        ctx.fillText("CONVEYOR", X(200), Y(100) + 24 * s)

                        // End gate (direction changes only here).
                        ctx.fillStyle = num("diverter", 0) > 0.5 ? "#e74c3c" : "#95a5a6"
                        ctx.fillRect(gateX - 3, Y(100) - 16 * s, 6, 16 * s)
                        ctx.fillText("GATE", gateX, Y(100) - 22 * s)

                        // Drop zone (belt infeed).
                        ctx.fillStyle = "rgba(0,183,199,0.20)"
                        ctx.fillRect(X(0) - 8, Y(100) - 12 * s, 16, 24 * s)
                        ctx.fillText("DROP", X(0), Y(100) - 18 * s)

                        // Two bins.
                        ctx.fillStyle = "rgba(224,168,0,0.18)"
                        ctx.fillRect(X(260) - 11, Y(20) - 11, 22, 22)
                        ctx.fillRect(X(260) - 11, Y(190) - 11, 22, 22)
                        ctx.fillStyle = "#b58a00"
                        ctx.fillText("BIN DOWN", X(260), Y(20) - 16)
                        ctx.fillText("BIN UP", X(260), Y(190) - 16)

                        // Sensors.
                        function sensor(cx, cy, label) {
                            ctx.beginPath()
                            ctx.arc(cx, cy, 5 * s, 0, Math.PI * 2)
                            ctx.fill()
                            ctx.fillText(label, cx, cy - 14 * s)
                        }
                        ctx.fillStyle = num("sensor_in", 0) > 0 ? "#2ecc71" : "#b6c0ce"
                        sensor(X(30), Y(100), "IN")
                        ctx.fillStyle = num("sensor_out", 0) > 0 ? "#2ecc71" : "#b6c0ce"
                        sensor(X(370), Y(100), "OUT")
                        ctx.fillStyle = num("sensor_divert", 0) > 0 ? "#2ecc71" : "#b6c0ce"
                        sensor(gateX, Y(210), "DIV")

                        // Part: follows the tool while held, rides the line otherwise.
                        var holding = num("holding", 0) > 0
                        var partOnLine = !holding && num("part_x", -1) >= 0
                        var ppx = holding ? num("x", 0) : num("part_x", -1)
                        var ppy = holding ? num("y", 0) : num("part_y", -1)
                        if (holding || partOnLine) {
                            var partCx = X(ppx)
                            var partCy = Y(ppy)
                            var partR = holding ? 7 * s : 6 * s
                            ctx.fillStyle = holding ? "#f39c12" : "#e0a800"
                            ctx.beginPath()
                            ctx.arc(partCx, partCy, partR, 0, Math.PI * 2)
                            ctx.fill()
                            ctx.strokeStyle = holding ? "#27ae60" : "#8a6d00"
                            ctx.lineWidth = 2
                            ctx.stroke()

                            ctx.fillStyle = "#172033"
                            ctx.font = "bold 11px sans-serif"
                            ctx.textAlign = "center"
                            if (holding)
                                ctx.fillText("HOLDING", partCx, partCy - 12 * s)
                            else if (num("part_y", 0) > 100)
                                ctx.fillText("DIVERT", partCx, partCy - 12 * s)
                            else
                                ctx.fillText("PART", partCx, partCy - 12 * s)
                        }

                        // Gantry tool crosshair (green while holding, orange when empty).
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
                Layout.preferredWidth: 320
                Layout.minimumWidth: 320
                Layout.maximumWidth: 320
                Layout.fillHeight: true
                spacing: 7

                // Machine state (with compact axis readout).
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: stateColumn.implicitHeight + 20
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    ColumnLayout {
                        id: stateColumn
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 2

                        Text {
                            text: "MACHINE STATE"
                            font.pixelSize: 10
                            font.bold: true
                            color: "#7f8c9b"
                        }
                        Text {
                            text: plcOnline ? tag("state", "IDLE") : "PLC OFFLINE"
                            font.pixelSize: 22
                            font.bold: true
                            color: (!plcOnline || tag("state", "") === "FAULT") ? "#c0392b" : "#172033"
                        }
                        Text {
                            text: "X " + num("x", 0).toFixed(0)
                                  + "   Y " + num("y", 0).toFixed(0)
                                  + "   Z " + num("z", 0).toFixed(0) + " mm"
                            font.pixelSize: 12
                            color: "#637083"
                        }
                        Text {
                            text: "mode " + tag("mode", "auto")
                                  + "   ·   side " + tag("side", "down")
                                  + "   ·   route " + tag("decision", "STRAIGHT")
                            font.pixelSize: 11
                            color: "#637083"
                        }
                        Text {
                            text: "placed " + tag("placed", "0")
                                  + "   ·   straight " + tag("passed", "0")
                                  + "   ·   diverted " + tag("diverted", "0")
                            font.pixelSize: 11
                            color: "#637083"
                        }
                        Text {
                            text: "GRIPPER: " + holdingState() + "   ·   jaws " + gripState()
                            font.pixelSize: 12
                            font.bold: true
                            color: num("holding", 0) > 0 ? "#27ae60" : "#637083"
                        }
                        Text {
                            text: "BELT: " + beltState()
                            font.pixelSize: 12
                            font.bold: true
                            color: num("holding", 0) > 0 ? "#637083"
                                   : num("part_x", -1) < 0 ? "#637083"
                                   : num("part_y", 0) > 100 ? "#e74c3c"
                                   : "#e67e22"
                        }
                        Text {
                            text: (plantOnline ? "plant online" : "plant OFFLINE")
                                  + "   ·   " + (plcOnline ? "PLC online" : "PLC OFFLINE")
                            font.pixelSize: 10
                            color: (plantOnline && plcOnline) ? "#2e7d32" : "#c0392b"
                        }
                        Text {
                            visible: tag("alarm", "").length > 0
                            text: tag("alarm", "")
                            font.pixelSize: 11
                            color: "#c0392b"
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }

                // Commands.
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 7
                    rowSpacing: 7

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

                // Gap and belt speed.
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: tuners.implicitHeight + 20
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    ColumnLayout {
                        id: tuners
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 5

                        Text {
                            text: "GAP   " + num("gap", 1.5).toFixed(1) + " s"
                            font.pixelSize: 11
                            color: "#637083"
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

                        Text {
                            text: "BELT SPEED   " + num("speed", 90).toFixed(0) + " mm/s"
                            font.pixelSize: 11
                            color: "#637083"
                        }
                        Slider {
                            id: speedSlider
                            Layout.fillWidth: true
                            from: 20
                            to: 250
                            value: num("speed", 90)
                            onMoved: if (pressed)
                                bridge.publish("pickline/target/speed", Math.round(value).toString())
                            Connections {
                                target: bridge
                                function onTagsChanged() {
                                    if (!speedSlider.pressed)
                                        speedSlider.value = num("speed", speedSlider.value)
                                }
                            }
                        }
                    }
                }

                // Pick side and end routing.
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: route.implicitHeight + 20
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    ColumnLayout {
                        id: route
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 5

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text {
                                text: "SIDE"
                                font.pixelSize: 10
                                font.bold: true
                                color: "#7f8c9b"
                            }
                            Button {
                                Layout.fillWidth: true
                                text: "Down"
                                onClicked: bridge.publish("pickline/command/side", "down")
                            }
                            Button {
                                Layout.fillWidth: true
                                text: "Up"
                                onClicked: bridge.publish("pickline/command/side", "up")
                            }
                            Button {
                                Layout.fillWidth: true
                                text: "Alt"
                                onClicked: bridge.publish("pickline/command/side", "alternate")
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text {
                                text: "END"
                                font.pixelSize: 10
                                font.bold: true
                                color: "#7f8c9b"
                            }
                            Button {
                                Layout.fillWidth: true
                                text: "Pass"
                                onClicked: bridge.publish("pickline/command/divert", "pass")
                            }
                            Button {
                                Layout.fillWidth: true
                                text: "Divert"
                                onClicked: bridge.publish("pickline/command/divert", "divert")
                            }
                            Button {
                                Layout.fillWidth: true
                                text: "Alt"
                                onClicked: bridge.publish("pickline/command/divert", "alternate")
                            }
                        }
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
                        anchors.margins: 10
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
                                    font.pixelSize: 10
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
                            spacing: 6
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

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Button {
                                Layout.fillWidth: true
                                text: num("belt", 0) > 0.5 ? "Stop belt" : "Start belt"
                                enabled: tag("mode", "auto") === "manual"
                                onClicked: bridge.publish("pickline/target/belt",
                                                           num("belt", 0) > 0.5 ? "0" : "1")
                            }
                            Button {
                                Layout.fillWidth: true
                                text: num("diverter", 0) > 0.5 ? "Retract gate" : "Extend gate"
                                enabled: tag("mode", "auto") === "manual"
                                onClicked: bridge.publish("pickline/target/diverter",
                                                           num("diverter", 0) > 0.5 ? "0" : "1")
                            }
                        }
                    }
                }
            }
        }
    }
}
