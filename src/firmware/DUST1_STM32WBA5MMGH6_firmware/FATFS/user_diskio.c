/*-----------------------------------------------------------------------*/
/* Low level disk I/O module skeleton for FatFs     (C)ChaN, 2019        */
/*-----------------------------------------------------------------------*/
/* Modified to work with Kiwih SPI Driver and remove ST Middleware deps  */
/*-----------------------------------------------------------------------*/

#include "ff.h"
#include "diskio.h"
#include "user_diskio_spi.h" /* <--- Include il driver di Kiwih */

/* Definitions of physical drive number for each drive */
#define DEV_SD      0   /* Map SD Card to physical drive 0 */

/*-----------------------------------------------------------------------*/
/* Get Drive Status                                                      */
/*-----------------------------------------------------------------------*/
DSTATUS disk_status (
    BYTE pdrv       /* Physical drive nmuber to identify the drive */
)
{
    if (pdrv == DEV_SD) {
        return USER_SPI_status(pdrv); /* Chiamata a Kiwih */
    }
    return STA_NOINIT;
}

/*-----------------------------------------------------------------------*/
/* Initialize a Drive                                                    */
/*-----------------------------------------------------------------------*/
DSTATUS disk_initialize (
    BYTE pdrv       /* Physical drive nmuber to identify the drive */
)
{
    if (pdrv == DEV_SD) {
        return USER_SPI_initialize(pdrv); /* Chiamata a Kiwih */
    }
    return STA_NOINIT;
}

/*-----------------------------------------------------------------------*/
/* Read Sector(s)                                                        */
/*-----------------------------------------------------------------------*/
DRESULT disk_read (
    BYTE pdrv,      /* Physical drive nmuber to identify the drive */
    BYTE *buff,     /* Data buffer to store read data */
    LBA_t sector,   /* Start sector in LBA */
    UINT count      /* Number of sectors to read */
)
{
    if (pdrv == DEV_SD) {
        return USER_SPI_read(pdrv, buff, sector, count); /* Chiamata a Kiwih */
    }
    return RES_PARERR;
}

/*-----------------------------------------------------------------------*/
/* Write Sector(s)                                                       */
/*-----------------------------------------------------------------------*/
DRESULT disk_write (
    BYTE pdrv,          /* Physical drive nmuber to identify the drive */
    const BYTE *buff,   /* Data to be written */
    LBA_t sector,       /* Start sector in LBA */
    UINT count          /* Number of sectors to write */
)
{
    if (pdrv == DEV_SD) {
        return USER_SPI_write(pdrv, buff, sector, count); /* Chiamata a Kiwih */
    }
    return RES_PARERR;
}

/*-----------------------------------------------------------------------*/
/* Miscellaneous Functions                                               */
/*-----------------------------------------------------------------------*/
DRESULT disk_ioctl (
    BYTE pdrv,      /* Physical drive nmuber (0..) */
    BYTE cmd,       /* Control code */
    void *buff      /* Buffer to send/receive control data */
)
{
    if (pdrv == DEV_SD) {
        return USER_SPI_ioctl(pdrv, cmd, buff); /* Chiamata a Kiwih */
    }
    return RES_PARERR;
}

/* Opzionale: Funzione per il tempo (se serve ai file timestamp) */
__attribute__((weak)) DWORD get_fattime (void)
{
    return 0;
}
