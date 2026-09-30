#pragma once

#include <stdbool.h>
#include <stdbool.h>
#include "esp_err.h"
#include "slam_types.h"

// Bring up SPI and the reader. Call once, from one task only.
esp_err_t mfrc522_init(void);

// Reads the chip version register. 0x91 or 0x92 means the chip is talking.
// 0x00 or 0xFF means wiring, power or SPI is wrong.
esp_err_t mfrc522_version(uint8_t *version_out);

// Looks for a card and reads its serial number.
//   ESP_OK             - uid filled in
//   ESP_ERR_NOT_FOUND  - no card in the field (the normal case)
//   ESP_ERR_INVALID_CRC- card present but the read was corrupt, try again
//   ESP_ERR_TIMEOUT    - reader stopped responding
esp_err_t mfrc522_read_uid(slam_uid_t *uid);

// Health check and recovery, for use by the polling loop.
bool mfrc522_antenna_ok(void);
void mfrc522_recover(void);

// Puts the last card to sleep so it stops answering until it is lifted.
void mfrc522_halt(void);



