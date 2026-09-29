#ifndef LEDCONTROLLER_H
#define LEDCONTROLLER_H

#include <QObject>
#include <QTimer>
#include <QVariant>
#include <QList>
#include <mosquitto.h>

// Backend that reads the CPU temperature and controls the LED.
// On the Raspberry Pi it talks to real sysfs files; on macOS it falls back to
// a fake temperature and a no-op LED write so the UI can be developed anywhere.
class LedController : public QObject
{
    Q_OBJECT
    Q_PROPERTY(double temperature READ temperature NOTIFY temperatureChanged)
    Q_PROPERTY(double threshold READ threshold WRITE setThreshold NOTIFY thresholdChanged)
    Q_PROPERTY(bool autoMode READ autoMode WRITE setAutoMode NOTIFY autoModeChanged)
    Q_PROPERTY(bool manualLedOn READ manualLedOn WRITE setManualLedOn NOTIFY manualLedOnChanged)
    Q_PROPERTY(bool ledOn READ ledOn NOTIFY ledOnChanged)
    Q_PROPERTY(QVariantList history READ history NOTIFY historyChanged)

public:
    explicit LedController(QObject *parent = nullptr);
    ~LedController();

    double temperature() const { return m_temperature; }
    double threshold() const { return m_threshold; }
    bool autoMode() const { return m_autoMode; }
    bool manualLedOn() const { return m_manualLedOn; }
    bool ledOn() const { return m_ledOn; }
    QVariantList history() const;

public slots:
    void setThreshold(double threshold);
    void setAutoMode(bool on);
    void setManualLedOn(bool on);
    void refresh();
    QString localTime() const;
    QString helsinkiTime() const;

signals:
    void temperatureChanged();
    void thresholdChanged();
    void autoModeChanged();
    void manualLedOnChanged();
    void ledOnChanged();
    void historyChanged();

private:
    double readCpuTempC();
    void writeLed(bool on);
    void updateLed();
    void publishState();
    static void onMessage(struct mosquitto *mosq, void *obj, const struct mosquitto_message *msg);
    void handleMessage(const struct mosquitto_message *msg);

    QTimer m_timer;
    double m_temperature = 0.0;
    double m_threshold = 60.0;
    bool m_autoMode = true;
    bool m_manualLedOn = false;
    bool m_ledOn = false;
    int m_tick = 0;
    QList<double> m_history;
    struct mosquitto *m_mosq = nullptr;
};

#endif // LEDCONTROLLER_H
