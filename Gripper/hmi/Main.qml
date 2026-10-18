import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1000
    height: 700
    visible: true
    title: qsTr("Gripper — Pick & Place HMI")
    color: "#eef2f8"

    function tag(name, fallback) {
        var value = bridge.tags[name]
        return (value === undefined || value === null) ? fallback : String(value)
    }

    function num(name, fallback) {
        var value = Number(bridge.tags[name])
        return isNaN(value) ? fallback : value
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: "Gripper — Pick & Place"
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

            // Top view of the work envelope.
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

                        var s = Math.min((w - 48) / 300.0, (h - 48) / 200.0)
                        var ox = (w - 300 * s) / 2
                        var oy = (h - 200 * s) / 2

                        function X(v) { return ox + v * s }
                        function Y(v) { return oy + (200 - v) * s }

                        ctx.strokeStyle = "#c9d2e0"
                        ctx.lineWidth = 2
                        ctx.strokeRect(ox, oy, 300 * s, 200 * s)

                        ctx.fillStyle = "rgba(47,109,246,0.15)"
                        ctx.fillRect(X(20) - 9, Y(20) - 9, 18, 18)
                        ctx.fillStyle = "rgba(0,183,199,0.18)"
                        ctx.fillRect(X(280) - 9, Y(180) - 9, 18, 18)

                        ctx.fillStyle = "#8a97a8"
                        ctx.font = "11px sans-serif"
                        ctx.textAlign = "center"
                        ctx.fillText("PICK", X(20), Y(20) - 16)
                        ctx.fillText("PLACE", X(280), Y(180) - 16)

                        var px = num("part_x", 20)
                        var py = num("part_y", 20)
                        ctx.fillStyle = "#e0a800"
                        ctx.beginPath()
                        ctx.arc(X(px), Y(py), 5, 0, Math.PI * 2)
                        ctx.fill()

                        var tx = X(num("x", 0))
                        var ty = Y(num("y", 0))
                        ctx.fillStyle = num("part", 0) > 0 ? "#27ae60" : "#e67e22"
                        ctx.beginPath()
                        ctx.arc(tx, ty, 9, 0, Math.PI * 2)
                        ctx.fill()

                        ctx.strokeStyle = "#ffffff"
                        ctx.lineWidth = 1.5
                        ctx.beginPath(); ctx.moveTo(tx - 13, ty); ctx.lineTo(tx + 13, ty); ctx.stroke()
                        ctx.beginPath(); ctx.moveTo(tx, ty - 13); ctx.lineTo(tx, ty + 13); ctx.stroke()
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
                            text: tag("state", "IDLE")
                            font.pixelSize: 26
                            font.bold: true
                            color: tag("state", "") === "FAULT" ? "#c0392b" : "#172033"
                        }
                        Text {
                            text: "mode " + tag("mode", "auto") + "   ·   placed " + tag("count", "0")
                            font.pixelSize: 12
                            color: "#637083"
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
                            bridge.publish("gripper/command/mode", "auto")
                            bridge.publish("gripper/command/start", "1")
                        }
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Stop"
                        onClicked: bridge.publish("gripper/command/stop", "1")
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Reset"
                        onClicked: bridge.publish("gripper/command/reset", "1")
                    }
                    Button {
                        Layout.fillWidth: true
                        text: tag("mode", "auto") === "auto" ? "Manual mode" : "Auto mode"
                        onClicked: bridge.publish(
                            "gripper/command/mode",
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
                            text: "MANUAL JOG"
                            font.pixelSize: 10
                            font.bold: true
                            color: "#7f8c9b"
                        }

                        Repeater {
                            model: [["X", "x", 300], ["Y", "y", 200], ["Z", "z", 100]]
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
                                        bridge.publish("gripper/target/" + modelData[1],
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
                                onClicked: bridge.publish("gripper/target/grip", "1")
                            }
                            Button {
                                Layout.fillWidth: true
                                text: "Close"
                                enabled: tag("mode", "auto") === "manual"
                                onClicked: bridge.publish("gripper/target/grip", "0")
                            }
                        }
                    }
                }
            }
        }
    }

}
