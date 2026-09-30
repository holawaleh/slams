idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES slam_core mfrc522 lcd1602 slam_store slam_net slam_portal
    PRIV_REQUIRES nvs_flash esp_timer esp_driver_gpio esp_partition efuse esp_hw_support esp_rom
)
