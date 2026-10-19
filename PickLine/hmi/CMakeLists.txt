cmake_minimum_required(VERSION 3.16)

project(PickLineHMI VERSION 0.1 LANGUAGES CXX)

find_package(Qt6 REQUIRED COMPONENTS Quick)
find_library(MOSQUITTO_LIBRARY mosquitto
    PATHS /opt/homebrew/lib /usr/local/lib
)
find_path(MOSQUITTO_INCLUDE_DIR mosquitto.h
    PATHS /opt/homebrew/include /usr/local/include
)

qt_standard_project_setup(REQUIRES 6.8)

qt_add_executable(appPickLineHMI
    main.cpp
    mqttbridge.h
    mqttbridge.cpp
)

qt_add_qml_module(appPickLineHMI
    URI PickLineHMI
    QML_FILES
        Main.qml
)

set_target_properties(appPickLineHMI PROPERTIES
    MACOSX_BUNDLE TRUE
    WIN32_EXECUTABLE TRUE
)

target_include_directories(appPickLineHMI PRIVATE ${MOSQUITTO_INCLUDE_DIR})
target_link_libraries(appPickLineHMI PRIVATE Qt6::Quick ${MOSQUITTO_LIBRARY})
