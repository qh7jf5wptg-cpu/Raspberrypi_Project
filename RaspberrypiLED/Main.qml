import QtQuick
import QtQuick.Controls.Basic

ApplicationWindow {
    id: window
    width: 950
    height: 775
    minimumWidth: 640
    minimumHeight: 640
    visible: true
    title: qsTr("Raspberrypi LED")

    // Refresh the clocks every second.
    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: {
            localClock.text = ledController.localTime()
            helsinkiClock.text = ledController.helsinkiTime()
        }
    }

    // Top-left: local (Berlin) time.
    Column {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: 12
        Text {
            text: "Local (Berlin)"
            font.pixelSize: 12
            color: "#32c26e"
        }
        Text {
            id: localClock
            font.pixelSize: 22
            font.bold: true
            color: "blue"
        }
    }

    // Top-right: Helsinki time.
    Column {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 12
        Text {
            text: "Fin"
            font.pixelSize: 12
            color: "#32c26e"
            anchors.right: parent.right
        }
        Text {
            id: helsinkiClock
            font.pixelSize: 22
            font.bold: true
            color: "blue"
            anchors.right: parent.right
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 18

        Canvas {
            id: historyChart
            anchors.horizontalCenter: parent.horizontalCenter
            width: 400
            height: 116
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                ctx.fillStyle = "#f2f3f5"
                ctx.fillRect(0, 0, width, height)
                ctx.fillStyle = "#666666"
                ctx.font = "9px sans-serif"
                ctx.textAlign = "left"
                ctx.fillText("CPU temp - last 60 s", 6, 11)

                var h = ledController.history
                if (h.length < 2)
                    return

                var min = h[0], max = h[0]
                for (var i = 1; i < h.length; i++) {
                    if (h[i] < min) min = h[i]
                    if (h[i] > max) max = h[i]
                }
                var range = max - min
                if (range < 1) range = 1

                var left = 40
                var bottom = height - 18
                var plotTop = 18
                var plotH = bottom - plotTop
                var barW = 4
                var step = barW + 1

                for (var j = 0; j < h.length; j++) {
                    var y = bottom - 2 - (h[j] - min) / range * (plotH - 4)
                    var bh = bottom - y
                    ctx.fillStyle = h[j] > ledController.threshold ? "#e74c3c" : "#2c3e50"
                    ctx.fillRect(left + j * step, y, barW, bh)
                }

                ctx.strokeStyle = "#e74c3c"
                ctx.lineWidth = 1.5
                ctx.beginPath()
                for (var k = 0; k < h.length; k++) {
                    var cx = left + k * step + barW / 2
                    var cy = bottom - 2 - (h[k] - min) / range * (plotH - 4)
                    if (k === 0) ctx.moveTo(cx, cy)
                    else ctx.lineTo(cx, cy)
                }
                ctx.stroke()

                ctx.fillStyle = "#555555"
                ctx.font = "8px sans-serif"
                ctx.textAlign = "right"
                ctx.fillText(max.toFixed(1) + "\u00b0C", left - 4, plotTop + 8)
                ctx.fillText(((min + max) / 2).toFixed(1) + "\u00b0C", left - 4, plotTop + plotH / 2 + 3)
                ctx.fillText(min.toFixed(1) + "\u00b0C", left - 4, bottom - 1)

                var endX = left + (h.length - 1) * step + barW
                ctx.textAlign = "left"
                ctx.fillText("60s ago", left, height - 5)
                ctx.textAlign = "right"
                ctx.fillText("now", endX, height - 5)
            }

            Connections {
                target: ledController
                onHistoryChanged: historyChart.requestPaint()
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: ledController.temperature.toFixed(1) + " °C"
            font.pixelSize: 56
            color: ledController.ledOn ? "#c0392b" : "#2c3e50"
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            enabled: ledController.autoMode

            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: "Threshold:"
            }

            TextField {
                id: thresholdField
                width: 120
                horizontalAlignment: TextInput.AlignHCenter
                inputMethodHints: Qt.ImhFormattedNumbersOnly
                validator: DoubleValidator { bottom: 0; top: 150; decimals: 1 }
                text: ledController.threshold.toFixed(1)
                onEditingFinished: {
                    if (acceptableInput)
                        ledController.setThreshold(Number(text))
                    else
                        text = ledController.threshold.toFixed(1)
                }
            }

            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: "°C"
            }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 16

            Switch {
                text: "Automatic mode"
                checked: ledController.autoMode
                onToggled: ledController.setAutoMode(checked)
            }

            Switch {
                text: "Force LED on"
                enabled: !ledController.autoMode
                checked: ledController.manualLedOn
                onToggled: ledController.setManualLedOn(checked)
            }

            Rectangle {
                width: 160
                height: 40
                radius: 20
                color: ledController.ledOn ? "#e74c3c" : "#2c3e50"

                Text {
                    anchors.centerIn: parent
                    text: ledController.ledOn ? "LED ON" : "LED OFF"
                    color: "white"
                    font.bold: true
                }
            }
        }
    }

    // Bottom: Helsinki forecast for the coming week.
    Column {
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.margins: 12
        spacing: 4

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Helsinki — next 7 days"
            font.pixelSize: 16
            color: "red"
            bottomPadding: 5
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 6

            Repeater {
                model: weatherModel
                delegate: Rectangle {
                    width: 82
                    height: 104
                    radius: 6
                    color: "#f2f3f5"

                    Column {
                        anchors.centerIn: parent
                        spacing: 3
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: model.day
                            font.pixelSize: 11
                            font.bold: true
                            color: "#333333"
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: model.icon
                            font.pixelSize: 26
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: model.cond
                            font.pixelSize: 10
                            color: "#666666"
                        }
                        Row {
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 7
                            Text {
                                text: model.hi + "°"
                                font.pixelSize: 12
                                color: "#c0392b"
                            }
                            Text {
                                text: model.lo + "°"
                                font.pixelSize: 12
                                color: "#2980b9"
                            }
                        }
                    }
                }
            }
        }
    }

    ListModel { id: weatherModel }

    function weatherIcon(code) {
        if (code === 0) return "☀️";
        if (code <= 3) return "🌤️";
        if (code === 45 || code === 48) return "🌫️";
        if (code >= 51 && code <= 57) return "🌧️";
        if (code >= 61 && code <= 67) return "🌧️";
        if (code >= 71 && code <= 77) return "❄️";
        if (code >= 80 && code <= 82) return "🌦️";
        if (code === 85 || code === 86) return "🌨️";
        if (code >= 95) return "⛈️";
        return "🌡️";
    }

    function weatherLabel(code) {
        if (code === 0) return "Clear";
        if (code <= 3) return "Cloudy";
        if (code === 45 || code === 48) return "Fog";
        if (code >= 51 && code <= 57) return "Drizzle";
        if (code >= 61 && code <= 67) return "Rain";
        if (code >= 71 && code <= 77) return "Snow";
        if (code >= 80 && code <= 82) return "Showers";
        if (code === 85 || code === 86) return "Snow";
        if (code >= 95) return "Thunder";
        return "—";
    }

    function loadWeather() {
        var xhr = new XMLHttpRequest();
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE && xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    weatherModel.clear();
                    for (var i = 0; i < data.daily.time.length; i++) {
                        var p = data.daily.time[i].split("-");
                        var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
                        var code = data.daily.weather_code[i];
                        weatherModel.append({
                            day: d.toLocaleDateString(Qt.locale("en_US"), "MMM. d"),
                            icon: weatherIcon(code),
                            cond: weatherLabel(code),
                            hi: Math.round(data.daily.temperature_2m_max[i]),
                            lo: Math.round(data.daily.temperature_2m_min[i])
                        });
                    }
                } catch (e) {
                    console.log("weather parse failed:", e);
                }
            }
        };
        xhr.open("GET", "https://api.open-meteo.com/v1/forecast?latitude=60.1699&longitude=24.9384&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=Europe/Helsinki&forecast_days=7");
        xhr.send();
    }

    Component.onCompleted: {
        localClock.text = ledController.localTime()
        helsinkiClock.text = ledController.helsinkiTime()
        loadWeather()
    }
}
