import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1000
    height: 600
    visible: true
    title: qsTr("Filling Station — HMI")
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
                text: "Filling Station"
                font.pixelSize: 22
                font.bold: true
                color: "#172033"
            }
            Item { Layout.fillWidth: true }
            Rectangle { width: 10; height: 10; radius: 5; color: bridge.connected ? "#2ecc71" : "#c0392b" }
            Text { text: bridge.connected ? "broker connected" : "no broker"; font.pixelSize: 12; color: "#637083" }
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

                        var tankLeft = w * 0.30
                        var tankRight = w * 0.70
                        var tankTop = 70
                        var tankBottom = h - 40

                        // tank wall
                        ctx.strokeStyle = "#7f8c9b"
                        ctx.lineWidth = 4
                        ctx.strokeRect(tankLeft, tankTop, tankRight - tankLeft, tankBottom - tankTop)

                        // liquid
                        var lvl = Math.max(0, Math.min(100, num("level", 0)))
                        var liquidTop = tankBottom - (lvl / 100.0) * (tankBottom - tankTop)
                        ctx.fillStyle = "#4aa3df"
                        ctx.fillRect(tankLeft + 4, liquidTop, tankRight - tankLeft - 8, tankBottom - liquidTop - 4)

                        // setpoint line
                        var sp = Math.max(0, Math.min(100, num("setpoint", 90)))
                        var spY = tankBottom - (sp / 100.0) * (tankBottom - tankTop)
                        ctx.strokeStyle = "#e67e22"
                        ctx.lineWidth = 2
                        ctx.setLineDash([6, 4])
                        ctx.beginPath(); ctx.moveTo(tankLeft - 10, spY); ctx.lineTo(tankRight + 10, spY); ctx.stroke()
                        ctx.setLineDash([])

                        // valve (top)
                        var vx = (tankLeft + tankRight) / 2
                        ctx.fillStyle = num("valve", 0) > 0.5 ? "#2ecc71" : "#c0392b"
                        ctx.fillRect(vx - 10, tankTop - 24, 20, 18)

                        // pump (left)
                        ctx.fillStyle = num("pump", 0) > 0.5 ? "#2ecc71" : "#95a5a6"
                        ctx.fillRect(tankLeft - 70, tankBottom - 48, 50, 30)
                        ctx.fillStyle = "#7f8c9b"
                        ctx.font = "12px sans-serif"
                        ctx.textAlign = "center"
                        ctx.fillText("PUMP", tankLeft - 45, tankBottom - 18)
                        ctx.fillText("VALVE", vx, tankTop - 32)

                        // level label
                        ctx.fillStyle = "#172033"
                        ctx.font = "bold 20px sans-serif"
                        ctx.fillText(lvl.toFixed(0) + " %", (tankLeft + tankRight) / 2, liquidTop - 10)
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

                        Text { text: "TANK STATE"; font.pixelSize: 10; font.bold: true; color: "#7f8c9b" }
                        Text {
                            text: plcOnline ? tag("state", "IDLE") : "PLC OFFLINE"
                            font.pixelSize: 26
                            font.bold: true
                            color: plcOnline ? "#172033" : "#c0392b"
                        }
                        Text {
                            text: num("level", 0).toFixed(1) + " %   ·   setpoint " + num("setpoint", 90).toFixed(0) + " %"
                            font.pixelSize: 16
                            font.bold: true
                            color: "#172033"
                        }
                        Text {
                            text: "batches " + tag("batches", "0") + "   ·   mode " + tag("mode", "auto")
                            font.pixelSize: 12
                            color: "#637083"
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
                            bridge.publish("fill/command/mode", "auto")
                            bridge.publish("fill/command/start", "1")
                        }
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Stop"
                        onClicked: bridge.publish("fill/command/stop", "1")
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Reset"
                        onClicked: bridge.publish("fill/command/reset", "1")
                    }
                    Button {
                        Layout.fillWidth: true
                        text: tag("mode", "auto") === "auto" ? "Manual mode" : "Auto mode"
                        onClicked: bridge.publish("fill/command/mode",
                                                   tag("mode", "auto") === "auto" ? "manual" : "auto")
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: setColumn.implicitHeight + 24
                    radius: 12
                    color: "#ffffff"
                    border.color: "#dfe5ef"

                    ColumnLayout {
                        id: setColumn
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 4

                        Text { text: "SETPOINT"; font.pixelSize: 10; font.bold: true; color: "#7f8c9b" }
                        Slider {
                            id: setSlider
                            Layout.fillWidth: true
                            from: 5
                            to: 100
                            value: num("setpoint", 90)
                            onMoved: if (pressed)
                                bridge.publish("fill/command/setpoint", Math.round(value).toString())
                            Connections {
                                target: bridge
                                function onTagsChanged() {
                                    if (!setSlider.pressed)
                                        setSlider.value = num("setpoint", setSlider.value)
                                }
                            }
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

                        Text { text: "MANUAL"; font.pixelSize: 10; font.bold: true; color: "#7f8c9b" }

                        Button {
                            Layout.fillWidth: true
                            text: num("pump", 0) > 0.5 ? "Stop pump" : "Run pump"
                            enabled: tag("mode", "") === "manual"
                            onClicked: bridge.publish("fill/target/pump", num("pump", 0) > 0.5 ? "0" : "1")
                        }
                        Button {
                            Layout.fillWidth: true
                            text: num("valve", 0) > 0.5 ? "Close valve" : "Open valve"
                            enabled: tag("mode", "") === "manual"
                            onClicked: bridge.publish("fill/target/valve", num("valve", 0) > 0.5 ? "0" : "1")
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }
        }
    }
}
