idf_component_register(
    SRCS "lcd1602.c"
    INCLUDE_DIRS "include"
    REQUIRES slam_core
    PRIV_REQUIRES esp_driver_i2c
)
