#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QTimer>

#include "mqttbridge.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);

    MqttBridge bridge;

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty("bridge", &bridge);

    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreationFailed,
        &app,
        []() { QCoreApplication::exit(-1); },
        Qt::QueuedConnection);
    engine.loadFromModule("PickLineHMI", "Main");

    // Optional: render one frame to a PNG and exit (used to generate screenshots).
    const QString shotPath = qEnvironmentVariable("PICKLINE_HMI_SHOT");
    if (!shotPath.isEmpty()) {
        const int delay = qEnvironmentVariableIntValue("PICKLINE_HMI_SHOT_DELAY");
        QTimer::singleShot(delay > 0 ? delay : 3500, [&engine, shotPath]() {
            for (QObject *obj : engine.rootObjects()) {
                if (auto *win = qobject_cast<QQuickWindow *>(obj)) {
                    win->grabWindow().save(shotPath);
                    QCoreApplication::quit();
                    break;
                }
            }
        });
    }

    return app.exec();
}
