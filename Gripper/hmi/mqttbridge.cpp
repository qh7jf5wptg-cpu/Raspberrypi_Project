#include "mqttbridge.h"

#include <QByteArray>

MqttBridge::MqttBridge(QObject *parent)
    : QObject(parent)
{
    mosquitto_lib_init();
    m_mosq = mosquitto_new("gripper_hmi", true, this);
    if (!m_mosq)
        return;

    mosquitto_connect_callback_set(m_mosq, &MqttBridge::onConnect);
    mosquitto_message_callback_set(m_mosq, &MqttBridge::onMessage);

    const QByteArray broker = qEnvironmentVariable("MQTT_BROKER", "localhost").toUtf8();
    if (mosquitto_connect(m_mosq, broker.constData(), 1883, 60) != MOSQ_ERR_SUCCESS)
        m_needReconnect = true;

    // Pump the network on the GUI thread - no worker thread, no locking.
    m_pump.setInterval(20);
    connect(&m_pump, &QTimer::timeout, this, &MqttBridge::pump);
    m_pump.start();
}

MqttBridge::~MqttBridge()
{
    m_pump.stop();
    if (m_mosq) {
        mosquitto_disconnect(m_mosq);
        mosquitto_destroy(m_mosq);
    }
    mosquitto_lib_cleanup();
}

void MqttBridge::publish(const QString &topic, const QString &payload)
{
    if (!m_mosq)
        return;
    const QByteArray t = topic.toUtf8();
    const QByteArray p = payload.toUtf8();
    mosquitto_publish(m_mosq, nullptr, t.constData(), p.size(), p.constData(), 0, false);
}

void MqttBridge::pump()
{
    if (!m_mosq)
        return;

    if (m_needReconnect) {
        if (mosquitto_reconnect(m_mosq) != MOSQ_ERR_SUCCESS)
            return;
        m_needReconnect = false;
    }

    if (mosquitto_loop(m_mosq, 0, 1) != MOSQ_ERR_SUCCESS) {
        m_needReconnect = true;
        if (m_connected) {
            m_connected = false;
            emit connectedChanged();
        }
    }

    if (m_dirty) {
        m_dirty = false;
        emit tagsChanged();
    }
}

void MqttBridge::onConnect(struct mosquitto *, void *obj, int rc)
{
    MqttBridge *self = static_cast<MqttBridge *>(obj);
    const bool ok = (rc == 0);
    if (ok)
        mosquitto_subscribe(self->m_mosq, nullptr, "gripper/#", 0);
    if (self->m_connected != ok) {
        self->m_connected = ok;
        emit self->connectedChanged();
    }
}

void MqttBridge::onMessage(struct mosquitto *, void *obj,
                           const struct mosquitto_message *msg)
{
    MqttBridge *self = static_cast<MqttBridge *>(obj);
    if (!msg || !msg->topic)
        return;

    const QString topic = QString::fromUtf8(msg->topic);
    const QString key = topic.section(QLatin1Char('/'), 1);
    const QString payload = QString::fromUtf8(
        static_cast<const char *>(msg->payload), msg->payloadlen);

    self->m_tags[key] = payload;
    self->m_dirty = true;
}
