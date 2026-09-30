/**
  ******************************************************************************
  * @file    device_config.h
  * @brief   Nome del dispositivo (advertising BLE) salvato in una pagina di flash
  *          riservata, che un normale caricamento del firmware non cancella.
  ******************************************************************************
  */
#ifndef DEVICE_CONFIG_H
#define DEVICE_CONFIG_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* Advertising legacy: 31 byte - flag (3) - AD costruttore (16) - intestazione AD del nome (2) */
#define DEVCFG_NAME_MAX_LEN     10u
#define DEVCFG_DEFAULT_NAME     "DUST_X"

/* Legge il nome salvato (da chiamare prima di avviare l'advertising) */
void        DEVCFG_Init(void);

/* Nome attuale (terminato da '\0'), lunghezza in *p_len */
const char *DEVCFG_GetName(uint8_t *p_len);

/* Comando BLE 'L' + nome: salva il nome nel flash e risponde su RECDATA
 * con "L+<nome>" oppure "L-<errore>" (BUSY, NAME, SPACE, FLASH, VERIFY).
 * L'advertising usa il nuovo nome dalla prossima partenza (dopo la disconnessione). */
void        DEVCFG_RequestRename(const uint8_t *p_name, uint16_t len);

#ifdef __cplusplus
}
#endif

#endif /* DEVICE_CONFIG_H */
