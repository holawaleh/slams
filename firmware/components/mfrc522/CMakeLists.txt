idf_component_register(
    SRCS "mfrc522.c"
    INCLUDE_DIRS "include"
    REQUIRES slam_core
    PRIV_REQUIRES esp_driver_spi esp_driver_gpio
)
