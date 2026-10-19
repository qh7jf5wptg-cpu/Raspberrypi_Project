#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>

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
    engine.loadFromModule("ConveyorHMI", "Main");

    return app.exec();
}
