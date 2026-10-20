import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1120
    height: 760
    visible: true
    title: qsTr("PickLine — Gripper + Conveyor + Filling")
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
    function atBin(binY) {
        return Math.sqrt(Math.pow(num("x", 0) - 260, 2)
                         + Math.pow(num("y", 0) - binY, 2)) <= 8
               && num("z", 0) <= 5
    }
    function binProximity(binY) {
        var dx = num("x", 0) - 260
        var dy = num("y", 0) - binY
        var dist = Math.sqrt(dx * dx + dy * dy)
        if (dist <= 8 && num("z", 0) <= 5) return "ready"
        if (dist <= 30) return "near"
        return "far"
    }
    function pickHint() {
        if (num("holding", 0) > 0) return "HOLDING PART"
        if (num("z", 0) > 5) return "lower Z to grab"
        if (atBin(20)) return "at DOWN bin — close jaws"
        if (atBin(190)) return "at UP bin — close jaws"
        return "move to a bin (260, 20 or 190)"
    }
    function fillState(key) { return tag("fill/" + key + "/state", "EMPTY") }
    function fillLevel(key) { return num("fill/" + key + "/level", 0) }
    function fillCount(key) { return tag("fill/" + key + "/count", "0") }
    function fillPickups(key) { return num("fill/" + key + "/pickups", 2) }
    function fillFilled(key) { return num("fill/" + key + "/filled", 0) }
    function fillPct(key) {
        var n = fillPickups(key)
        return n > 0 ? Math.min(100, fillFilled(key) / n * 100) : 0
    }
    function fillColor(key) {
        var s = fillState(key)
        return s === "FULL" ? "#e74c3c"
               : s === "FILLING" ? "#4aa3df"
               : s === "FAULT" ? "#e74c3c" : "#9aa7b8"
    }
    function machineRunning() {
        if (tag("mode", "auto") !== "auto") return false
        if (num("paused", 0) > 0 || num("estop", 0) > 0) return false
        var inactive = ["IDLE", "MANUAL", "FAULT", "ESTOP"]
        return inactive.indexOf(tag("state", "IDLE")) < 0
    }
    function canPause() {
        if (tag("mode", "auto") !== "auto") return false
        if (num("paused", 0) > 0 || num("estop", 0) > 0) return false
        var beforeRelease = ["TO_PICK", "LOWER_PICK", "GRIP", "LIFT_PICK", "TO_DROP", "LOWER_DROP"]
        return beforeRelease.indexOf(tag("state", "IDLE")) >= 0
    }

    property real plantSeen: 0
    property real plcSeen: 0
    property bool plantOnline: false
    property bool plcOnline: false
    property bool blinkOn: false

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

    Timer {
        interval: 450
        running: true
        repeat: true
        onTriggered: {
            blinkOn = !blinkOn
            view.requestPaint()
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
                text: "PickLine — Gripper + Conveyor + Filling"
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

                        var WX = 520.0
                        var WY = 297.0
                        var s = Math.min((w - 32) / WX, (h - 32) / WY)
                        var ox = (w - WX * s) / 2
                        var oy = (h - WY * s) / 2

                        function X(v) { return ox + (v + 25) * s }
                        function Y(v) { return oy + (292 - v) * s }

                        ctx.strokeStyle = "#c9d2e0"
                        ctx.lineWidth = 2
                        ctx.strokeRect(ox, oy, WX * s, WY * s)

                        // Left lane (route to station B), turning at the belt end.
                        var gateX = X(400)
                        ctx.fillStyle = "#f4ead8"
                        ctx.fillRect(gateX - 7 * s, Y(240), 14 * s, 140 * s)
                        ctx.strokeStyle = "#c9b58d"
                        ctx.lineWidth = 1.5
                        ctx.strokeRect(gateX - 7 * s, Y(240), 14 * s, 140 * s)

                        // Conveyor belt.
                        var beltTop = Y(100) - 10 * s
                        ctx.fillStyle = "#e9edf3"
                        ctx.fillRect(X(0) - 6, beltTop, 406 * s, 20 * s)
                        ctx.strokeStyle = "#9aa7b8"
                        ctx.lineWidth = 1.5
                        ctx.strokeRect(X(0) - 6, beltTop, 406 * s, 20 * s)
                        ctx.fillStyle = "#8a97a8"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.fillText("CONVEYOR", X(200), Y(100) + 24 * s)

                        // Straight approach lane (belt end -> station A).
                        ctx.fillStyle = "#eef3f8"
                        ctx.fillRect(X(400) - 6, beltTop, 66 * s, 20 * s)
                        ctx.strokeStyle = "#b8c4d2"
                        ctx.lineWidth = 1.5
                        ctx.strokeRect(X(400) - 6, beltTop, 66 * s, 20 * s)

                        // Fill stations beyond the two lanes.
                        function drawStation(cx, cy, key, label) {
                            var pct = fillPct(key)
                            var st = fillState(key)
                            var tankW = 20 * s
                            var tankH = 40 * s
                            var x0 = cx - tankW / 2
                            var y0 = cy - tankH / 2

                            ctx.fillStyle = "#eef1f5"
                            ctx.fillRect(x0, y0, tankW, tankH)

                            var frac = Math.max(0, Math.min(1, pct / 100))
                            var lh = frac * (tankH - 4)
                            ctx.fillStyle = "#4aa3df"
                            ctx.fillRect(x0 + 2, y0 + tankH - 2 - lh, tankW - 4, lh)

                            var borderColor = fillColor(key)
                            if (st === "FULL" && !blinkOn)
                                borderColor = "#f5b7b1"
                            ctx.strokeStyle = borderColor
                            ctx.lineWidth = 2.5
                            ctx.strokeRect(x0, y0, tankW, tankH)

                            ctx.fillStyle = "#172033"
                            ctx.font = "bold 11px sans-serif"
                            ctx.fillText(label, cx, y0 - 7)
                            ctx.fillText(pct.toFixed(0) + "%", cx, y0 + tankH + 13)
                            ctx.font = "10px sans-serif"
                            ctx.fillStyle = "#637083"
                            ctx.fillText(st, cx, y0 + tankH + 25)
                        }
                        drawStation(X(460), Y(100), "a", "FILL A")
                        drawStation(X(400), Y(240), "b", "FILL B")

                        // Drop zone.
                        ctx.fillStyle = "rgba(0,183,199,0.20)"
                        ctx.fillRect(X(0) - 8, Y(100) - 12 * s, 16, 24 * s)
                        ctx.fillStyle = "#8a97a8"
                        ctx.font = "11px sans-serif"
                        ctx.fillText("DROP", X(0), Y(100) - 18 * s)

                        // Industrial stack light above the drop point.
                        var lx = X(0)
                        var ly = Y(100) - 128
                        var lr = 11
                        var lsp = 28
                        var topY = ly - lsp - lr - 7
                        var bottomY = ly + 2 * lsp + lr + 7
                        ctx.fillStyle = "#1a2233"
                        ctx.fillRect(lx - 24, topY, 48, bottomY - topY)
                        var redOn = num("estop", 0) > 0 || tag("state", "") === "FAULT"
                        var yellowOn = num("paused", 0) > 0
                        var greenOn = machineRunning() && blinkOn
                        var blueOn = tag("fill/a/state", "") === "FULL"
                                     && tag("fill/b/state", "") === "FULL" && blinkOn
                        ctx.fillStyle = redOn ? "#e74c3c" : "#2a3448"
                        ctx.beginPath(); ctx.arc(lx, ly - lsp, lr, 0, Math.PI * 2); ctx.fill()
                        ctx.fillStyle = yellowOn ? "#f1c40f" : "#2a3448"
                        ctx.beginPath(); ctx.arc(lx, ly, lr, 0, Math.PI * 2); ctx.fill()
                        ctx.fillStyle = greenOn ? "#2ecc71" : "#2a3448"
                        ctx.beginPath(); ctx.arc(lx, ly + lsp, lr, 0, Math.PI * 2); ctx.fill()
                        ctx.fillStyle = blueOn ? "#3d82f6" : "#2a3448"
                        ctx.beginPath(); ctx.arc(lx, ly + 2 * lsp, lr, 0, Math.PI * 2); ctx.fill()

                        // Two bins.
                        function drawBin(binY, label) {
                            var st = binProximity(binY)
                            var bx = X(260) - 12
                            var by = Y(binY) - 12
                            var bs = 24
                            if (st === "ready") {
                                ctx.fillStyle = "#2ecc71"
                                ctx.strokeStyle = "#1e8449"
                                ctx.lineWidth = 3
                            } else if (st === "near") {
                                ctx.fillStyle = "#f1c40f"
                                ctx.strokeStyle = "#b7950b"
                                ctx.lineWidth = 2
                            } else {
                                ctx.fillStyle = "rgba(224,168,0,0.18)"
                                ctx.strokeStyle = "#d8b35a"
                                ctx.lineWidth = 1
                            }
                            ctx.fillRect(bx, by, bs, bs)
                            ctx.strokeRect(bx, by, bs, bs)
                            ctx.fillStyle = st === "ready" ? "#ffffff" : "#7a4a00"
                            ctx.beginPath()
                            ctx.arc(X(260), Y(binY), 5, 0, Math.PI * 2)
                            ctx.fill()
                            ctx.fillStyle = st === "ready" ? "#ffffff"
                                            : st === "near" ? "#6e5400"
                                            : "#b58a00"
                            ctx.font = "bold 11px sans-serif"
                            ctx.fillText(st === "ready" ? label + " ✓" : label,
                                         X(260), Y(binY) - 18)
                        }
                        drawBin(20, "BIN DOWN")
                        drawBin(190, "BIN UP")

                        // Sensors.
                        function sensor(cx, cy, label) {
                            ctx.beginPath()
                            ctx.arc(cx, cy, 5 * s, 0, Math.PI * 2)
                            ctx.fill()
                            ctx.fillStyle = "#8a97a8"
                            ctx.fillText(label, cx, cy - 14 * s)
                        }
                        ctx.fillStyle = num("sensor_in", 0) > 0 ? "#2ecc71" : "#b6c0ce"
                        sensor(X(30), Y(100), "IN")
                        ctx.fillStyle = num("sensor_out", 0) > 0 ? "#2ecc71" : "#b6c0ce"
                        sensor(X(370), Y(100), "OUT")
                        ctx.fillStyle = num("sensor_divert", 0) > 0 ? "#2ecc71" : "#b6c0ce"
                        sensor(gateX, Y(210), "DIV")

                        // Part.
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
                                ctx.fillText("TO B", partCx, partCy - 12 * s)
                            else if (num("part_x", 0) >= 400)
                                ctx.fillText("TO A", partCx, partCy - 12 * s)
                            else
                                ctx.fillText(num("diverter", 0) > 0.5 ? "TO B" : "TO A",
                                             partCx, partCy - 12 * s)
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
                        if (!holding && (atBin(20) || atBin(190))) {
                            ctx.strokeStyle = "#1e8449"
                            ctx.lineWidth = 3
                            ctx.beginPath()
                            ctx.arc(tx, ty, 13 * s, 0, Math.PI * 2)
                            ctx.stroke()
                        }
                    }
                }

            }

            ScrollView {
                id: rightScroll
                Layout.preferredWidth: 340
                Layout.minimumWidth: 340
                Layout.maximumWidth: 340
                Layout.fillHeight: true
                clip: true

                ColumnLayout {
                    width: rightScroll.availableWidth
                    spacing: 8

                    // Machine state.
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
                            text: !plcOnline ? "PLC OFFLINE"
                                  : tag("estop", "0") === "1" ? "EMERGENCY STOP"
                                  : tag("paused", "0") === "1" ? "PAUSED"
                                  : tag("state", "IDLE")
                                font.pixelSize: 22
                                font.bold: true
                            color: (!plcOnline || tag("state", "") === "FAULT" || tag("estop", "0") === "1") ? "#c0392b"
                                   : tag("paused", "0") === "1" ? "#e67e22"
                                   : "#172033"
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
                                      + "   ·   route " + tag("route_mode", "auto")
                                font.pixelSize: 11
                                color: "#637083"
                            }
                            Text {
                                text: "placed " + tag("placed", "0")
                                      + "   ·   entered " + tag("exited", "0")
                                      + "   ·   total " + num("fill/total", 0).toFixed(0) + " u"
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
                                text: "PICK: " + pickHint()
                                font.pixelSize: 12
                                font.bold: true
                                color: num("holding", 0) > 0 ? "#27ae60"
                                       : (atBin(20) || atBin(190)) ? "#27ae60"
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

                    // Fault controls.
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Button {
                            Layout.fillWidth: true
                            text: "Jam belt"
                            onClicked: bridge.publish("pickline/fault/jam", "1")
                        }
                        Button {
                            Layout.fillWidth: true
                            text: "Clear jam"
                            onClicked: bridge.publish("pickline/fault/clear", "1")
                        }
                    }

                    // Pause / emergency / clear belt.
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        spacing: 6
                        Button {
                            id: pauseBtn
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 0
                            text: tag("paused", "0") === "1" ? "Resume" : "Pause"
                            enabled: tag("paused", "0") === "1" || canPause()
                            onClicked: bridge.publish(
                                tag("paused", "0") === "1" ? "pickline/command/resume" : "pickline/command/pause",
                                "1")
                            background: Rectangle {
                                implicitHeight: 40
                                radius: 4
                                color: !pauseBtn.enabled ? "#9aa5b1" : "#2a3448"
                            }
                            contentItem: Text {
                                text: pauseBtn.text
                                color: "#ffffff"
                                font.pixelSize: 14
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 0
                            text: "Emergency"
                            onClicked: bridge.publish("pickline/command/estop", "1")
                        }
                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 0
                            text: "Clear belt"
                            onClicked: bridge.publish("pickline/command/clear_belt", "1")
                        }
                    }

                    // Filling stations.
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: fillColumn.implicitHeight + 20
                        radius: 12
                        color: "#ffffff"
                        border.color: "#dfe5ef"

                        ColumnLayout {
                            id: fillColumn
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 6

                            Text {
                                text: "FILLING   volume " + num("volume", 100).toFixed(0) + " u"
                                font.pixelSize: 10
                                font.bold: true
                                color: "#7f8c9b"
                            }
                            Slider {
                                id: volumeSlider
                                Layout.fillWidth: true
                                from: 10
                                to: 500
                                value: num("volume", 100)
                                onMoved: if (pressed)
                                    bridge.publish("pickline/target/volume", Math.round(value).toString())
                                Connections {
                                    target: bridge
                                    function onTagsChanged() {
                                        if (!volumeSlider.pressed)
                                            volumeSlider.value = num("volume", volumeSlider.value)
                                    }
                                }
                            }

                            Repeater {
                                model: [["a", "STATION A", "straight"], ["b", "STATION B", "left"]]
                                delegate: ColumnLayout {
                                    property string key: modelData[0]
                                    Layout.fillWidth: true
                                    spacing: 3

                                    Text {
                                        text: modelData[1] + " (" + modelData[2] + ")   " + fillState(modelData[0])
                                              + "   " + fillCount(modelData[0]) + " fills"
                                        font.pixelSize: 11
                                        font.bold: true
                                        color: fillColor(modelData[0])
                                    }
                                    Text {
                                        visible: tag("fill/" + modelData[0] + "/alarm", "").length > 0
                                        text: "⚠ " + tag("fill/" + modelData[0] + "/alarm", "")
                                        font.pixelSize: 11
                                        font.bold: true
                                        color: "#e74c3c"
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        implicitHeight: 14
                                        radius: 4
                                        color: "#eef1f5"
                                        Rectangle {
                                            height: 14
                                            width: parent.width * fillPct(modelData[0]) / 100
                                            radius: 4
                                            color: "#4aa3df"
                                        }
                                    }
                                    Row {
                                        Layout.fillWidth: true
                                        spacing: 3
                                        Repeater {
                                            model: fillPickups(key)
                                            delegate: Rectangle {
                                                width: 12
                                                height: 12
                                                radius: 6
                                                color: index < fillFilled(key) ? "#4aa3df" : "#d0d7e0"
                                            }
                                        }
                                    }
                                    Text {
                                        text: fillPct(modelData[0]).toFixed(0) + "%   ·   filled "
                                              + fillFilled(modelData[0]).toFixed(0)
                                              + " / " + fillPickups(modelData[0]).toFixed(0)
                                        font.pixelSize: 10
                                        color: "#637083"
                                    }
                                    Slider {
                                        id: pickupsSlider
                                        Layout.fillWidth: true
                                        from: 1
                                        to: 10
                                        value: fillPickups(modelData[0])
                                        onMoved: if (pressed)
                                            bridge.publish("pickline/target/fill/" + modelData[0] + "/pickups",
                                                           Math.round(value).toString())
                                        Connections {
                                            target: bridge
                                            function onTagsChanged() {
                                                if (!pickupsSlider.pressed)
                                                    pickupsSlider.value = fillPickups(modelData[0])
                                            }
                                        }
                                    }
                                    Button {
                                        Layout.fillWidth: true
                                        text: "Take out"
                                        enabled: fillState(modelData[0]) === "FULL"
                                        onClicked: bridge.publish("pickline/fill/" + modelData[0] + "/take", "1")
                                    }
                                }
                            }
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
                                text: "GAP   " + num("gap", 0.5).toFixed(1) + " s"
                                font.pixelSize: 11
                                color: "#637083"
                            }
                            Slider {
                                id: gapSlider
                                Layout.fillWidth: true
                                from: 0
                                to: 10
                                stepSize: 0.1
                                value: num("gap", 0.5)
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

                    // Pick side.
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: sideBox.implicitHeight + 20
                        radius: 12
                        color: "#ffffff"
                        border.color: "#dfe5ef"

                        ColumnLayout {
                            id: sideBox
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
                                    text: "ROUTE"
                                    font.pixelSize: 10
                                    font.bold: true
                                    color: "#7f8c9b"
                                }
                                Button {
                                    Layout.fillWidth: true
                                    text: "Auto"
                                    onClicked: bridge.publish("pickline/command/route", "auto")
                                }
                                Button {
                                    Layout.fillWidth: true
                                    text: "Straight"
                                    onClicked: bridge.publish("pickline/command/route", "straight")
                                }
                                Button {
                                    Layout.fillWidth: true
                                    text: "Left"
                                    onClicked: bridge.publish("pickline/command/route", "left")
                                }
                                Button {
                                    Layout.fillWidth: true
                                    text: "Alt"
                                    onClicked: bridge.publish("pickline/command/route", "alternate")
                                }
                            }
                        }
                    }

                    // Manual jog.
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: manualColumn.implicitHeight + 20
                        radius: 12
                        color: "#ffffff"
                        border.color: "#dfe5ef"

                        ColumnLayout {
                            id: manualColumn
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
                                        id: jogSlider
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
                                                if (!jogSlider.pressed)
                                                    jogSlider.value = num(modelData[1], jogSlider.value)
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
                                    text: "Go straight"
                                    enabled: tag("mode", "auto") === "manual"
                                    onClicked: bridge.publish("pickline/target/diverter", "0")
                                }
                                Button {
                                    Layout.fillWidth: true
                                    text: "Go left"
                                    enabled: tag("mode", "auto") === "manual"
                                    onClicked: bridge.publish("pickline/target/diverter", "1")
                                }
                            }
                            Button {
                                Layout.fillWidth: true
                                text: num("belt", 0) > 0.5 ? "Stop belt" : "Start belt"
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
}
