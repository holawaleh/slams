#include <string.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "slam_board.h"
#include "mfrc522.h"

static const char *TAG = "rc522";

// ---- reader registers ----
#define REG_COMMAND       0x01
#define REG_COM_IRQ       0x04
#define REG_DIV_IRQ       0x05
#define REG_ERROR         0x06
#define REG_FIFO_DATA     0x09
#define REG_FIFO_LEVEL    0x0A
#define REG_CONTROL       0x0C
#define REG_BIT_FRAMING   0x0D
#define REG_COLL          0x0E
#define REG_MODE          0x11
#define REG_TX_CONTROL    0x14
#define REG_TX_ASK        0x15
#define REG_CRC_RESULT_H  0x21
#define REG_CRC_RESULT_L  0x22
#define REG_T_MODE        0x2A
#define REG_T_PRESCALER   0x2B
#define REG_T_RELOAD_H    0x2C
#define REG_T_RELOAD_L    0x2D
#define REG_VERSION       0x37

// ---- reader commands ----
#define CMD_IDLE          0x00
#define CMD_CALC_CRC      0x03
#define CMD_TRANSCEIVE    0x0C
#define CMD_SOFT_RESET    0x0F

// ---- card commands ----
#define PICC_REQA         0x26
#define PICC_HALT         0x50
#define PICC_SEL_CL1      0x93
#define PICC_SEL_CL2      0x95
#define PICC_SEL_CL3      0x97

static spi_device_handle_t s_spi;

// ---------------- low level SPI ----------------

static uint8_t reg_read(uint8_t reg)
{
    uint8_t tx[2] = { (uint8_t)(((reg << 1) & 0x7E) | 0x80), 0x00 };
    uint8_t rx[2] = { 0, 0 };
    spi_transaction_t t = {
        .length = 16,
        .tx_buffer = tx,
        .rx_buffer = rx,
    };
    if (spi_device_polling_transmit(s_spi, &t) != ESP_OK) return 0;
    return rx[1];
}

static void reg_write(uint8_t reg, uint8_t val)
{
    uint8_t tx[2] = { (uint8_t)((reg << 1) & 0x7E), val };
    spi_transaction_t t = {
        .length = 16,
        .tx_buffer = tx,
    };
    spi_device_polling_transmit(s_spi, &t);
}

static void reg_set_bits(uint8_t reg, uint8_t mask)
{
    reg_write(reg, (uint8_t)(reg_read(reg) | mask));
}

static void reg_clear_bits(uint8_t reg, uint8_t mask)
{
    reg_write(reg, (uint8_t)(reg_read(reg) & (uint8_t)~mask));
}

static void fifo_write(const uint8_t *data, uint8_t len)
{
    for (uint8_t i = 0; i < len; i++) reg_write(REG_FIFO_DATA, data[i]);
}

static void fifo_read(uint8_t *data, uint8_t len)
{
    for (uint8_t i = 0; i < len; i++) data[i] = reg_read(REG_FIFO_DATA);
}

// ---------------- reader helpers ----------------

static esp_err_t calc_crc(const uint8_t *data, uint8_t len, uint8_t *out2)
{
    reg_write(REG_COMMAND, CMD_IDLE);
    reg_write(REG_DIV_IRQ, 0x04);        // clear the CRC-done flag
    reg_write(REG_FIFO_LEVEL, 0x80);     // flush the FIFO
    fifo_write(data, len);
    reg_write(REG_COMMAND, CMD_CALC_CRC);

    for (int i = 0; i < 5000; i++) {
        if (reg_read(REG_DIV_IRQ) & 0x04) {
            reg_write(REG_COMMAND, CMD_IDLE);
            out2[0] = reg_read(REG_CRC_RESULT_L);
            out2[1] = reg_read(REG_CRC_RESULT_H);
            return ESP_OK;
        }
        esp_rom_delay_us(10);
    }
    return ESP_ERR_TIMEOUT;
}

// Send a frame to the card and collect the reply.
static esp_err_t transceive(const uint8_t *send, uint8_t send_len,
                            uint8_t *back, uint8_t *back_len,
                            uint8_t tx_last_bits)
{
    reg_write(REG_COMMAND, CMD_IDLE);
    reg_write(REG_COM_IRQ, 0x7F);        // clear every interrupt flag
    reg_write(REG_FIFO_LEVEL, 0x80);     // flush the FIFO
    fifo_write(send, send_len);
    reg_write(REG_BIT_FRAMING, tx_last_bits);
    reg_write(REG_COMMAND, CMD_TRANSCEIVE);
    reg_set_bits(REG_BIT_FRAMING, 0x80); // start sending

    // The card must answer within about 25 ms or it is not there.
    bool done = false;
    for (int i = 0; i < 2500; i++) {
        uint8_t irq = reg_read(REG_COM_IRQ);
        if (irq & 0x30) { done = true; break; }   // received, or idle
        if (irq & 0x01) break;                    // reader timer expired
        esp_rom_delay_us(10);
    }
    reg_clear_bits(REG_BIT_FRAMING, 0x80);

    if (!done) return ESP_ERR_NOT_FOUND;

    uint8_t err = reg_read(REG_ERROR);
    if (err & 0x08) return ESP_ERR_INVALID_CRC;   // two cards at once
    if (err & 0x13) return ESP_ERR_INVALID_CRC;   // buffer, parity or protocol

    if (back && back_len) {
        uint8_t n = reg_read(REG_FIFO_LEVEL);
        if (n > *back_len) return ESP_ERR_NO_MEM;
        *back_len = n;
        fifo_read(back, n);
    }
    return ESP_OK;
}

static void antenna_on(void)
{
    if (!(reg_read(REG_TX_CONTROL) & 0x03)) reg_set_bits(REG_TX_CONTROL, 0x03);
}

// ---------------- public API ----------------

esp_err_t mfrc522_init(void)
{
    gpio_config_t rst = {
        .pin_bit_mask = 1ULL << SLAM_PIN_RFID_RST,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&rst));
    gpio_set_level(SLAM_PIN_RFID_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(SLAM_PIN_RFID_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(50));

    spi_bus_config_t bus = {
        .mosi_io_num = SLAM_PIN_SPI_MOSI,
        .miso_io_num = SLAM_PIN_SPI_MISO,
        .sclk_io_num = SLAM_PIN_SPI_SCK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 64,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(SLAM_SPI_HOST, &bus, SPI_DMA_DISABLED));

    spi_device_interface_config_t dev = {
        .clock_speed_hz = SLAM_SPI_CLOCK_HZ,
        .mode = 0,
        .spics_io_num = SLAM_PIN_RFID_CS,
        .queue_size = 1,
    };
    ESP_ERROR_CHECK(spi_bus_add_device(SLAM_SPI_HOST, &dev, &s_spi));

    reg_write(REG_COMMAND, CMD_SOFT_RESET);
    vTaskDelay(pdMS_TO_TICKS(50));

    // Timer: 40 kHz tick, reload 1000, giving a 25 ms card timeout.
    reg_write(REG_T_MODE,      0x80);
    reg_write(REG_T_PRESCALER, 0xA9);
    reg_write(REG_T_RELOAD_H,  0x03);
    reg_write(REG_T_RELOAD_L,  0xE8);
    reg_write(REG_TX_ASK,      0x40);   // 100% ASK modulation
    reg_write(REG_MODE,        0x3D);   // CRC preset 0x6363
    antenna_on();

    uint8_t ver = reg_read(REG_VERSION);
    ESP_LOGI(TAG, "version register = 0x%02X", ver);

    // Can we write a value and read the same value back?
    bool spi_ok = true;
    const uint8_t probe[] = { 0xA5, 0x5A, 0x00, 0xFF, 0x3C };
    for (unsigned i = 0; i < sizeof(probe); i++) {
        reg_write(REG_T_RELOAD_L, probe[i]);
        uint8_t got = reg_read(REG_T_RELOAD_L);
        ESP_LOGI(TAG, "  scratch wrote 0x%02X read 0x%02X %s",
                 probe[i], got, (got == probe[i]) ? "ok" : "MISMATCH");
        if (got != probe[i]) spi_ok = false;
    }
    reg_write(REG_T_RELOAD_L, 0xE8);   // put the timer reload back

    ESP_LOGI(TAG, "  TxControl=0x%02X Mode=0x%02X TxASK=0x%02X Command=0x%02X",
             reg_read(REG_TX_CONTROL), reg_read(REG_MODE),
             reg_read(REG_TX_ASK), reg_read(REG_COMMAND));

    if (!spi_ok) {
        ESP_LOGE(TAG, "SPI readback failed - wiring, clock speed or power");
        return ESP_ERR_NOT_FOUND;
    }
    if (ver == 0x00 || ver == 0xFF) {
        ESP_LOGE(TAG, "reader not responding - check 3V3, SPI wiring and CS");
        return ESP_ERR_NOT_FOUND;
    }
    if (ver != 0x91 && ver != 0x92) {
        ESP_LOGW(TAG, "clone chip (version 0x%02X) - functional but unbranded", ver);
    }
    return ESP_OK;
}

esp_err_t mfrc522_version(uint8_t *version_out)
{
    if (!version_out) return ESP_ERR_INVALID_ARG;
    *version_out = reg_read(REG_VERSION);
    return ESP_OK;
}

void mfrc522_halt(void)
{
    uint8_t buf[4] = { PICC_HALT, 0x00, 0x00, 0x00 };
    if (calc_crc(buf, 2, &buf[2]) != ESP_OK) return;
    // A card that accepts HALT stays silent, so no reply is the success case.
    transceive(buf, 4, NULL, NULL, 0);
}

esp_err_t mfrc522_read_uid(slam_uid_t *uid)
{
    if (!uid) return ESP_ERR_INVALID_ARG;

    // Ask whether any card is in the field. REQA is a 7 bit frame.
    reg_clear_bits(REG_COLL, 0x80);
    uint8_t cmd = PICC_REQA;
    uint8_t atqa[2];
    uint8_t atqa_len = sizeof(atqa);
    esp_err_t err = transceive(&cmd, 1, atqa, &atqa_len, 0x07);
    if (err != ESP_OK) return err;
    if (atqa_len != 2) return ESP_ERR_INVALID_CRC;

    memset(uid, 0, sizeof(*uid));
    const uint8_t sel_cmd[3] = { PICC_SEL_CL1, PICC_SEL_CL2, PICC_SEL_CL3 };

    for (int level = 0; level < 3; level++) {
        uint8_t buf[9];
        uint8_t resp[5];
        uint8_t resp_len = sizeof(resp);

        // Ask for this cascade level's four UID bytes plus their checksum.
        buf[0] = sel_cmd[level];
        buf[1] = 0x20;
        err = transceive(buf, 2, resp, &resp_len, 0);
        if (err != ESP_OK) return err;
        if (resp_len != 5) return ESP_ERR_INVALID_CRC;

        uint8_t bcc = resp[0] ^ resp[1] ^ resp[2] ^ resp[3];
        if (bcc != resp[4]) return ESP_ERR_INVALID_CRC;

        // Select that card so it tells us whether more bytes follow.
        buf[0] = sel_cmd[level];
        buf[1] = 0x70;
        memcpy(&buf[2], resp, 5);
        if (calc_crc(buf, 7, &buf[7]) != ESP_OK) return ESP_ERR_TIMEOUT;

        uint8_t sak[3];
        uint8_t sak_len = sizeof(sak);
        err = transceive(buf, 9, sak, &sak_len, 0);
        if (err != ESP_OK) return err;
        if (sak_len != 3) return ESP_ERR_INVALID_CRC;

        // 0x88 in the first byte means this level only carries three real bytes.
        if (resp[0] == 0x88) {
            memcpy(&uid->bytes[uid->len], &resp[1], 3);
            uid->len = (uint8_t)(uid->len + 3);
        } else {
            memcpy(&uid->bytes[uid->len], &resp[0], 4);
            uid->len = (uint8_t)(uid->len + 4);
        }

        if (!(sak[0] & 0x04)) return ESP_OK;   // no cascade bit, UID complete
    }
    return ESP_ERR_INVALID_CRC;
}




// True if the antenna driver is still enabled. Cheap modules sometimes

// True if the antenna driver is still enabled. Cheap modules sometimes
// drop this after a supply dip and then read nothing, silently.
bool mfrc522_antenna_ok(void)
{
    return (reg_read(REG_TX_CONTROL) & 0x03) == 0x03;
}

// Re-enable the antenna and restore the core settings after a glitch.
void mfrc522_recover(void)
{
    reg_write(REG_COMMAND, CMD_SOFT_RESET);
    vTaskDelay(pdMS_TO_TICKS(50));
    reg_write(REG_T_MODE,      0x80);
    reg_write(REG_T_PRESCALER, 0xA9);
    reg_write(REG_T_RELOAD_H,  0x03);
    reg_write(REG_T_RELOAD_L,  0xE8);
    reg_write(REG_TX_ASK,      0x40);
    reg_write(REG_MODE,        0x3D);
    antenna_on();
    ESP_LOGW(TAG, "reader recovered");
}
