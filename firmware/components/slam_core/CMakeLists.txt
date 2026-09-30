idf_component_register(
    SRCS "slam_core.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_timer
    PRIV_REQUIRES nvs_flash esp_hw_support
)
