#pragma once

// ---- MFRC522 on VSPI ----
#define SLAM_PIN_RFID_CS      5
#define SLAM_PIN_RFID_RST     4
#define SLAM_PIN_SPI_SCK      18
#define SLAM_PIN_SPI_MISO     19
#define SLAM_PIN_SPI_MOSI     23
#define SLAM_SPI_HOST         SPI3_HOST
#define SLAM_SPI_CLOCK_HZ     (1 * 1000 * 1000)

// ---- 1602 LCD over PCF8574 ----
#define SLAM_PIN_I2C_SDA      21
#define SLAM_PIN_I2C_SCL      22
#define SLAM_I2C_PORT         I2C_NUM_0
#define SLAM_I2C_CLOCK_HZ     100000
#define SLAM_LCD_ADDR         0x27

// ---- Indicators and input ----
#define SLAM_PIN_BUZZER       2
#define SLAM_PIN_LED          13
#define SLAM_PIN_CONFIG_BTN   15

// ---- Flash supply ----
// GPIO12 (MTDI) picks the flash voltage at reset: low 3.3 V, high 1.8 V.
// On these boards it is sometimes high at reset, which runs the 3.3 V
// flash at 1.8 V: it still reads, but silently ignores every write.
// With this set, the firmware switches the flash supply back to 3.3 V at
// startup. Set it to 0 on a module with 1.8 V flash (some WROVER), or
// 3.3 V would damage that flash.
#define SLAM_FLASH_IS_3V3     1

// ---- Timing budgets ----
#define SLAM_RFID_POLL_MS         100
#define SLAM_DEBOUNCE_HARD_MS     2000
#define SLAM_DEBOUNCE_UNKNOWN_MS  10000   // short: registering a card means tapping it again
#define SLAM_UPLOAD_BATCH_MAX     25
#define SLAM_UPLOAD_FLUSH_MS      60000


