#ifndef MQTTBRIDGE_H
#define MQTTBRIDGE_H

#include <QObject>
#include <QTimer>
#include <QVariantMap>
#include <mosquitto.h>

// Small MQTT bridge: every gripper/<tag> message becomes an entry in the
// "tags" map, and publish() sends a command back to the plant or PLC.
class MqttBridge : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QVariantMap tags READ tags NOTIFY tagsChanged)
    Q_PROPERTY(bool connected READ connected NOTIFY connectedChanged)

public:
    explicit MqttBridge(QObject *parent = nullptr);
    ~MqttBridge();

    QVariantMap tags() const { return m_tags; }
    bool connected() const { return m_connected; }

    Q_INVOKABLE void publish(const QString &topic, const QString &payload);

signals:
    void tagsChanged();
    void connectedChanged();

private slots:
    void pump();

private:
    static void onConnect(struct mosquitto *mosq, void *obj, int rc);
    static void onMessage(struct mosquitto *mosq, void *obj,
                          const struct mosquitto_message *msg);

    struct mosquitto *m_mosq = nullptr;
    QTimer m_pump;
    QVariantMap m_tags;
    bool m_connected = false;
    bool m_needReconnect = false;
    bool m_dirty = false;
};

#endif // MQTTBRIDGE_H
