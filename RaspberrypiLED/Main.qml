import QtQuick
import QtQuick.Controls.Basic

ApplicationWindow {
    id: window
    width: 1100
    height: 880
    minimumWidth: 1000
    minimumHeight: 840
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
        anchors.top: parent.top
        anchors.topMargin: 60
        anchors.left: parent.left
        anchors.leftMargin: 40
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
                var right = width - 6
                var bottom = height - 18
                var plotTop = 18
                var plotH = bottom - plotTop

                // Fixed 60 slots so the x-axis always spans the last 60 seconds.
                var step = (right - left) / 60
                var barW = Math.max(1, step - 1.2)

                // Chart: one bar per sample, red when above the threshold.
                for (var j = 0; j < h.length; j++) {
                    var bx = left + j * step
                    var by = bottom - 2 - (h[j] - min) / range * (plotH - 4)
                    ctx.fillStyle = h[j] > ledController.threshold ? "#e74c3c" : "#2c3e50"
                    ctx.fillRect(bx, by, barW, bottom - 2 - by)
                }

                // Waveform: the trend line across the samples.
                ctx.beginPath()
                for (var k = 0; k < h.length; k++) {
                    var cx = left + k * step + barW / 2
                    var cy = bottom - 2 - (h[k] - min) / range * (plotH - 4)
                    if (k === 0) ctx.moveTo(cx, cy)
                    else ctx.lineTo(cx, cy)
                }
                ctx.strokeStyle = "#e74c3c"
                ctx.lineWidth = 2
                ctx.lineJoin = "round"
                ctx.lineCap = "round"
                ctx.stroke()

                ctx.fillStyle = "#555555"
                ctx.font = "8px sans-serif"
                ctx.textAlign = "right"
                ctx.fillText(max.toFixed(1) + "\u00b0C", left - 4, plotTop + 8)
                ctx.fillText(((min + max) / 2).toFixed(1) + "\u00b0C", left - 4, plotTop + plotH / 2 + 3)
                ctx.fillText(min.toFixed(1) + "\u00b0C", left - 4, bottom - 1)

                ctx.textAlign = "left"
                ctx.fillText("60s ago", left, height - 5)
                ctx.textAlign = "right"
                ctx.fillText("now", right, height - 5)
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

    // Right: rolling 60-second log with pause and CSV export.
    Column {
        anchors.top: parent.top
        anchors.topMargin: 60
        anchors.right: parent.right
        anchors.rightMargin: 40
        spacing: 8

        Text {
            text: "Log — last 60 s"
            font.pixelSize: 16
            color: "red"
        }

        Row {
            spacing: 0
            Text { text: "Time";    width: 80; font.pixelSize: 11; font.bold: true; color: "#333333" }
            Text { text: "Temp °C"; width: 84; font.pixelSize: 11; font.bold: true; color: "#333333" }
            Text { text: "Mode";    width: 76; font.pixelSize: 11; font.bold: true; color: "#333333" }
            Text { text: "LED";     width: 56; font.pixelSize: 11; font.bold: true; color: "#333333" }
            Text { text: "Thr. °C"; width: 70; font.pixelSize: 11; font.bold: true; color: "#333333" }
        }

        Rectangle {
            width: 366
            height: 1
            color: "#dddddd"
        }

        ListView {
            id: logView
            width: 366
            height: 220
            clip: true
            model: logModel
            delegate: Row {
                spacing: 0
                Text {
                    width: 80
                    text: model.time
                    font.pixelSize: 12
                    color: "#333333"
                }
                Text {
                    width: 84
                    text: model.temperature.toFixed(1)
                    font.pixelSize: 12
                    font.bold: model.temperature > ledController.threshold
                    color: model.temperature > ledController.threshold ? "#c0392b" : "#333333"
                }
                Text {
                    width: 76
                    text: model.mode
                    font.pixelSize: 12
                    color: model.mode === "Manual" ? "#b9770e" : "#333333"
                }
                Text {
                    width: 56
                    text: model.led
                    font.pixelSize: 12
                    font.bold: model.led === "ON"
                    color: model.led === "ON" ? "#c0392b" : "#333333"
                }
                Text {
                    width: 70
                    text: model.threshold.toFixed(1)
                    font.pixelSize: 12
                    color: "#333333"
                }
            }
        }

        Row {
            spacing: 10
            Button {
                text: paused ? "Resume" : "Pause"
                onClicked: {
                    paused = !paused
                    if (!paused)
                        refreshLog()
                }
            }
            Button {
                text: "Export CSV"
                onClicked: {
                    var path = ledController.exportLogCsv()
                    exportStatus.text = path === "" ? "Export failed" : "Saved: " + path
                }
            }
        }

        Text {
            width: 366
            text: paused ? "Paused — logging continues in the background" : " "
            font.pixelSize: 11
            color: "#b9770e"
            wrapMode: Text.Wrap
        }

        Text {
            id: exportStatus
            width: 366
            text: " "
            font.pixelSize: 11
            color: "#666666"
            wrapMode: Text.Wrap
        }
    }

    // Bottom: forecast for the coming week (Helsinki on top, Brussels below).
    Column {
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.margins: 12
        spacing: 10

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
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
                    delegate: weatherCard
                }
            }
        }

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 4

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Brussels — next 7 days"
                font.pixelSize: 16
                color: "red"
                bottomPadding: 5
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 6

                Repeater {
                    model: brusselsModel
                    delegate: weatherCard
                }
            }
        }

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 4

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Berlin — next 7 days"
                font.pixelSize: 16
                color: "red"
                bottomPadding: 5
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 6

                Repeater {
                    model: berlinModel
                    delegate: weatherCard
                }
            }
        }
    }

    ListModel { id: weatherModel }
    ListModel { id: brusselsModel }
    ListModel { id: berlinModel }
    ListModel { id: logModel }

    property bool paused: false

    // Rebuild the table from the backend's rolling 60-second log.
    function refreshLog() {
        logModel.clear()
        var entries = ledController.log
        for (var i = 0; i < entries.length; i++)
            logModel.append(entries[i])
        logView.positionViewAtEnd()
    }

    // While paused the table is frozen, but the backend keeps recording.
    Connections {
        target: ledController
        function onLogChanged() {
            if (!paused)
                refreshLog()
        }
    }

    Component {
        id: weatherCard
        Rectangle {
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
                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    source: model.iconSource
                    width: 26
                    height: 26
                    fillMode: Image.PreserveAspectFit
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

    function weatherIconSource(code) {
        if (code === 0) return "qrc:/weather/sun.svg";
        if (code <= 3) return "qrc:/weather/cloud.svg";
        if (code === 45 || code === 48) return "qrc:/weather/fog.svg";
        if (code >= 51 && code <= 57) return "qrc:/weather/rain.svg";
        if (code >= 61 && code <= 67) return "qrc:/weather/rain.svg";
        if (code >= 71 && code <= 77) return "qrc:/weather/snow.svg";
        if (code >= 80 && code <= 82) return "qrc:/weather/rain.svg";
        if (code === 85 || code === 86) return "qrc:/weather/snow.svg";
        if (code >= 95) return "qrc:/weather/thunder.svg";
        return "qrc:/weather/sun.svg";
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

    function loadWeatherFor(model, lat, lon, tz) {
        var xhr = new XMLHttpRequest();
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE && xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    model.clear();
                    for (var i = 0; i < data.daily.time.length; i++) {
                        var p = data.daily.time[i].split("-");
                        var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
                        var code = data.daily.weather_code[i];
                        model.append({
                            day: d.toLocaleDateString(Qt.locale("en_US"), "MMM. d"),
                            iconSource: weatherIconSource(code),
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
        var url = "https://api.open-meteo.com/v1/forecast?latitude=" + lat + "&longitude=" + lon +
                  "&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=" + tz + "&forecast_days=7";
        xhr.open("GET", url);
        xhr.send();
    }

    function loadWeather() {
        loadWeatherFor(weatherModel, 60.1699, 24.9384, "Europe/Helsinki");
    }

    function loadBrusselsWeather() {
        loadWeatherFor(brusselsModel, 50.8503, 4.3517, "Europe/Brussels");
    }

    function loadBerlinWeather() {
        loadWeatherFor(berlinModel, 52.5200, 13.4050, "Europe/Berlin");
    }

    Component.onCompleted: {
        localClock.text = ledController.localTime()
        helsinkiClock.text = ledController.helsinkiTime()
        loadWeather()
        loadBrusselsWeather()
        loadBerlinWeather()
        refreshLog()
    }
}
