/**
 ******************************************************************************
  * @file    user_diskio_spi.h
  * @brief   This file contains the common defines and functions prototypes for
  *          the user_diskio_spi driver implementation
  ******************************************************************************
  * Portions copyright (C) 2014, ChaN, all rights reserved.
  * Portions copyright (C) 2017, kiwih, all rights reserved.
  *
  * This software is a free software and there is NO WARRANTY.
  * No restriction on use. You can use, modify and redistribute it for
  * personal, non-profit or commercial products UNDER YOUR RESPONSIBILITY.
  * Redistributions of source code must retain the above copyright notice.
  *
  ******************************************************************************
  */

#ifndef USER_DISKIO_SPI_H
#define USER_DISKIO_SPI_H

#include "main.h"   // Per le definizioni HAL e GPIO
#include "ff.h"     // Per i tipi DSTATUS, DRESULT
#include "diskio.h" // Per i tipi BYTE, UINT

// --- AGGIUNTA FONDAMENTALE ---
// Collega i nomi generici al tuo hardware reale
#define SD_SPI_HANDLE hspi3       // La tua SPI (assicurati sia hspi3)
#define SD_CS_GPIO_Port GPIOB     // La porta del Chip Select
#define SD_CS_Pin GPIO_PIN_11     // Il Pin del Chip Select
// -----------------------------

// Prototipi (Senza inline)
DSTATUS USER_SPI_initialize (BYTE pdrv);
DSTATUS USER_SPI_status (BYTE pdrv);
DRESULT USER_SPI_read (BYTE pdrv, BYTE *buff, LBA_t sector, UINT count);
DRESULT USER_SPI_write (BYTE pdrv, const BYTE *buff, LBA_t sector, UINT count);
DRESULT USER_SPI_ioctl (BYTE pdrv, BYTE cmd, void *buff);

#endif
