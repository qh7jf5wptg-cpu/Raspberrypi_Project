#include "ledcontroller.h"

#include <QFile>
#include <cmath>
#include <QDateTime>
#include <QTimeZone>

LedController::LedController(QObject *parent)
    : QObject(parent)
{
    m_timer.setInterval(1000);
    connect(&m_timer, &QTimer::timeout, this, &LedController::refresh);
    m_timer.start();
    refresh();

    mosquitto_lib_init();
    m_mosq = mosquitto_new("raspberrypi_led", true, this);
    if (m_mosq) {
        const QByteArray broker = qEnvironmentVariable("MQTT_BROKER", "localhost").toUtf8();
        mosquitto_connect(m_mosq, broker.constData(), 1883, 60);
        mosquitto_loop_start(m_mosq);
        mosquitto_message_callback_set(m_mosq, LedController::onMessage);
        mosquitto_subscribe(m_mosq, nullptr, "machine/command/#", 0);
    }
}

LedController::~LedController()
{
    if (m_mosq) {
        mosquitto_loop_stop(m_mosq, true);
        mosquitto_destroy(m_mosq);
    }
    mosquitto_lib_cleanup();
}

QString LedController::localTime() const
{
    return QDateTime::currentDateTime()
        .toTimeZone(QTimeZone("Europe/Berlin"))
        .toString("HH:mm:ss");
}

QString LedController::helsinkiTime() const
{
    return QDateTime::currentDateTime()
        .toTimeZone(QTimeZone("Europe/Helsinki"))
        .toString("HH:mm:ss");
}

QVariantList LedController::history() const
{
    QVariantList list;
    list.reserve(m_history.size());
    for (double v : m_history)
        list.append(v);
    return list;
}

void LedController::refresh()
{
    const double t = readCpuTempC();

    m_history.append(t);
    if (m_history.size() > 60)
        m_history.removeFirst();
    emit historyChanged();

    if (t != m_temperature) {
        m_temperature = t;
        emit temperatureChanged();
    }
    updateLed();
    publishState();
}

void LedController::setThreshold(double threshold)
{
    if (threshold != m_threshold) {
        m_threshold = threshold;
        emit thresholdChanged();
        updateLed();
        publishState();
    }
}

void LedController::setAutoMode(bool on)
{
    if (on != m_autoMode) {
        m_autoMode = on;
        emit autoModeChanged();
        updateLed();
        publishState();
    }
}

void LedController::setManualLedOn(bool on)
{
    if (on != m_manualLedOn) {
        m_manualLedOn = on;
        emit manualLedOnChanged();
        updateLed();
        publishState();
    }
}

void LedController::updateLed()
{
    const bool shouldBeOn = m_autoMode ? (m_temperature > m_threshold) : m_manualLedOn;
    if (shouldBeOn != m_ledOn) {
        m_ledOn = shouldBeOn;
        writeLed(m_ledOn);
        emit ledOnChanged();
    }
}

void LedController::onMessage(struct mosquitto *, void *obj, const struct mosquitto_message *msg)
{
    LedController *self = static_cast<LedController *>(obj);
    self->handleMessage(msg);
}

void LedController::handleMessage(const struct mosquitto_message *msg)
{
    if (!msg || !msg->topic)
        return;

    const QByteArray topic(msg->topic);
    const QByteArray payload(static_cast<const char *>(msg->payload), msg->payloadlen);

    if (topic == "machine/command/led") {
        if (payload == "1") {
            setAutoMode(false);
            setManualLedOn(true);
        } else if (payload == "0") {
            setManualLedOn(false);
        }
    } else if (topic == "machine/command/mode") {
        if (payload == "manual")
            setAutoMode(false);
        else if (payload == "auto")
            setAutoMode(true);
    } else if (topic == "machine/command/threshold") {
        bool ok = false;
        const double t = payload.toDouble(&ok);
        if (ok)
            setThreshold(t);
    }
}

void LedController::publishState()
{
    if (!m_mosq)
        return;

    const QByteArray temp = QByteArray::number(m_temperature, 'f', 1);
    const QByteArray led = m_ledOn ? QByteArray("1") : QByteArray("0");
    const QByteArray threshold = QByteArray::number(m_threshold, 'f', 1);
    const QByteArray mode = m_autoMode ? QByteArray("auto") : QByteArray("manual");

    mosquitto_publish(m_mosq, nullptr, "machine/temperature", temp.size(), temp.constData(), 0, false);
    mosquitto_publish(m_mosq, nullptr, "machine/led", led.size(), led.constData(), 0, false);
    mosquitto_publish(m_mosq, nullptr, "machine/threshold", threshold.size(), threshold.constData(), 0, false);
    mosquitto_publish(m_mosq, nullptr, "machine/mode", mode.size(), mode.constData(), 0, false);
}

double LedController::readCpuTempC()
{
    QFile f(QString::fromLatin1("/sys/class/thermal/thermal_zone0/temp"));
    if (f.open(QIODevice::ReadOnly | QIODevice::Text)) {
        const QByteArray data = f.readAll().trimmed();
        bool ok = false;
        const int millideg = data.toInt(&ok);
        if (ok) {
            return millideg / 1000.0;
        }
    }

    // No real sensor (e.g. on macOS): fake a slowly moving value.
    ++m_tick;
    return 45.0 + 10.0 * std::sin(m_tick * 0.05);
}

void LedController::writeLed(bool on)
{
    // The Pi's onboard LED defaults to an SD-activity trigger, so switch it
    // to manual control before writing the brightness.
    const char *bases[] = {
        "/sys/class/leds/led0",
        "/sys/class/leds/ACT",
    };
    for (const char *base : bases) {
        QFile trigger(QString::fromLatin1(base) + "/trigger");
        if (trigger.open(QIODevice::WriteOnly | QIODevice::Text)) {
            trigger.write("none\n");
            trigger.close();
        }

        QFile brightness(QString::fromLatin1(base) + "/brightness");
        if (brightness.open(QIODevice::WriteOnly | QIODevice::Text)) {
            brightness.write(on ? "1\n" : "0\n");
            brightness.flush();
            brightness.close();
            return;
        }
    }
    // No writable LED (macOS, or a permission/trigger issue on the Pi): no-op.
}
