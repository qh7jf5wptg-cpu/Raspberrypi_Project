cmake_minimum_required(VERSION 3.16)

project(RaspberrypiLED VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 REQUIRED COMPONENTS Quick)
find_library(MOSQUITTO_LIBRARY mosquitto
    PATHS /opt/homebrew/lib /usr/local/lib
)
find_path(MOSQUITTO_INCLUDE_DIR mosquitto.h
    PATHS /opt/homebrew/include /usr/local/include
)

qt_standard_project_setup(REQUIRES 6.8)

# Content of downloaded design from Figma to Qt or similar
if (EXISTS "${CMAKE_CURRENT_LIST_DIR}/importedcontent/CMakeLists.txt")
    add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/importedcontent)
endif()

qt_add_executable(appRaspberrypiLED
    main.cpp
    ledcontroller.h
    ledcontroller.cpp
)

qt_add_qml_module(appRaspberrypiLED
    URI RaspberrypiLED
    QML_FILES
        Main.qml
)

qt_add_resources(appRaspberrypiLED "weather_icons"
    PREFIX "/weather"
    BASE "${CMAKE_CURRENT_SOURCE_DIR}/weather"
    FILES
        sun.svg
        cloud.svg
        rain.svg
        snow.svg
        thunder.svg
)


# Qt for iOS sets MACOSX_BUNDLE_GUI_IDENTIFIER automatically since Qt 6.1.
# If you are developing for iOS or macOS you should consider setting an
# explicit, fixed bundle identifier manually though.
set_target_properties(appRaspberrypiLED PROPERTIES
#    MACOSX_BUNDLE_GUI_IDENTIFIER com.example.appRaspberrypiLED
    MACOSX_BUNDLE_BUNDLE_VERSION ${PROJECT_VERSION}
    MACOSX_BUNDLE_SHORT_VERSION_STRING ${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}
    MACOSX_BUNDLE TRUE
    WIN32_EXECUTABLE TRUE
)

target_include_directories(appRaspberrypiLED PRIVATE ${MOSQUITTO_INCLUDE_DIR})

target_link_libraries(appRaspberrypiLED
    PRIVATE Qt6::Quick ${MOSQUITTO_LIBRARY}
)

install(TARGETS appRaspberrypiLED
    BUNDLE DESTINATION .
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
