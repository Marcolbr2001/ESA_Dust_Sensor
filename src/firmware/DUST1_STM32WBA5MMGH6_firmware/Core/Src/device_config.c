/**
  ******************************************************************************
  * @file    device_config.c
  * @brief   Nome del dispositivo (advertising BLE) salvato nel flash.
  *
  * - Pagina 125 (0x080FA000), subito prima delle 2 pagine dello SNVMA (126-127,
  *   dati del BLE). Un normale caricamento del firmware (CubeIDE, CubeProgrammer
  *   senza "Full chip erase") cancella solo le pagine occupate dall'immagine,
  *   quindi il nome resta; una cancellazione completa lo riporta a DUST_X.
  * - Si scrive via BLE con il comando 'L' + nome (GUI, tab Connection) oppure in
  *   programmazione con il file .hex creato da Tools/make_device_name.py.
  * - Record di 48 byte (3 quad-word: il flash si programma a 128 bit): magic "DCFG",
  *   versione, lunghezza, nome, riservato, CRC-32 (lo stesso di zlib.crc32).
  * - Le scritture passano dal Flash Manager, come quelle dello stack BLE, così non
  *   interferiscono con la radio.
  ******************************************************************************
  */
#include "main.h"
#include "app_common.h"
#include "flash_manager.h"
#include "ble_sensor_app.h"
#include "device_config.h"

#include <stddef.h>
#include <string.h>

#define DEVCFG_MAGIC      0x47464344u                                      /* "DCFG" */
#define DEVCFG_VERSION    1u
#define DEVCFG_PAGE       (CFG_SNVMA_START_SECTOR_ID - 1u)                 /* 125 */
#define DEVCFG_ADDR       (FLASH_BASE + (DEVCFG_PAGE * FLASH_PAGE_SIZE))   /* 0x080FA000 */

typedef struct
{
  uint32_t magic;
  uint16_t version;
  uint16_t name_len;
  char     name[32];
  uint32_t reserved;
  uint32_t crc;          /* CRC-32 dei 44 byte precedenti */
} DevCfg_Record_t;

_Static_assert(sizeof(DevCfg_Record_t) == 48u, "il record deve essere di 3 quad-word");
_Static_assert((offsetof(DevCfg_Record_t, name) == 8u) && (offsetof(DevCfg_Record_t, crc) == 44u),
               "formato usato anche da Tools/make_device_name.py");

typedef enum
{
  DEVCFG_IDLE,
  DEVCFG_WAIT_ERASE,     /* Flash Manager occupato: richiama con FM_OPERATION_AVAILABLE */
  DEVCFG_ERASING,
  DEVCFG_WAIT_WRITE,
  DEVCFG_WRITING
} DevCfg_State_t;

/* Fine dell'immagine del firmware nel flash (simboli dello script del linker) */
extern uint32_t _sidata;
extern uint32_t _sdata;
extern uint32_t _edata;

static void DEVCFG_FlashCallback(FM_FlashOp_Status_t Status);

static char s_name[DEVCFG_NAME_MAX_LEN + 1u] = DEVCFG_DEFAULT_NAME;
static uint8_t s_name_len = (uint8_t)(sizeof(DEVCFG_DEFAULT_NAME) - 1u);

static DevCfg_State_t s_state = DEVCFG_IDLE;
static DevCfg_Record_t s_record;   /* sorgente di FM_Write, deve restare valida fino alla fine */
static FM_CallbackNode_t s_fm_node = { .Callback = DEVCFG_FlashCallback };

static uint32_t devcfg_crc32(const void *p_data, uint32_t len)
{
  const uint8_t *p = (const uint8_t *)p_data;
  uint32_t crc = 0xFFFFFFFFu;

  while (len-- > 0u)
  {
    crc ^= *p++;
    for (uint8_t k = 0u; k < 8u; k++)
    {
      crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
  }
  return ~crc;
}

/* Lettere, cifre, '_' e '-': il nome finisce nell'advertising e nella lista della GUI */
static uint8_t devcfg_name_valid(const char *p_name, uint16_t len)
{
  if ((len == 0u) || (len > DEVCFG_NAME_MAX_LEN))
  {
    return 0u;
  }
  for (uint16_t i = 0u; i < len; i++)
  {
    char c = p_name[i];
    if (!(((c >= 'A') && (c <= 'Z')) || ((c >= 'a') && (c <= 'z')) ||
          ((c >= '0') && (c <= '9')) || (c == '_') || (c == '-')))
    {
      return 0u;
    }
  }
  return 1u;
}

/* La pagina è del nome solo se l'immagine del firmware finisce prima */
static uint8_t devcfg_page_is_free(void)
{
  uint32_t image_end = (uint32_t)&_sidata + ((uint32_t)&_edata - (uint32_t)&_sdata);
  return (image_end <= DEVCFG_ADDR) ? 1u : 0u;
}

static uint8_t devcfg_record_valid(const DevCfg_Record_t *p_rec)
{
  return ((p_rec->magic == DEVCFG_MAGIC) && (p_rec->version == DEVCFG_VERSION) &&
          (devcfg_name_valid(p_rec->name, p_rec->name_len) != 0u) &&
          (devcfg_crc32(p_rec, offsetof(DevCfg_Record_t, crc)) == p_rec->crc)) ? 1u : 0u;
}

static void devcfg_finish(const char *p_reply)
{
  s_state = DEVCFG_IDLE;
  BLE_SENSOR_APP_SendReply(p_reply);
}

static void devcfg_start_erase(void)
{
  FM_Cmd_Status_t status = FM_Erase(DEVCFG_PAGE, 1u, &s_fm_node);

  if (status == FM_OK)
  {
    s_state = DEVCFG_ERASING;
  }
  else if (status == FM_BUSY)
  {
    s_state = DEVCFG_WAIT_ERASE;
  }
  else
  {
    devcfg_finish("L-FLASH");
  }
}

static void devcfg_start_write(void)
{
  FM_Cmd_Status_t status = FM_Write((uint32_t *)&s_record, (uint32_t *)DEVCFG_ADDR,
                                    (int32_t)(sizeof(s_record) / sizeof(uint32_t)), &s_fm_node);

  if (status == FM_OK)
  {
    s_state = DEVCFG_WRITING;
  }
  else if (status == FM_BUSY)
  {
    s_state = DEVCFG_WAIT_WRITE;
  }
  else
  {
    devcfg_finish("L-FLASH");
  }
}

/* Rilegge il flash: il nome in RAM (e quindi nell'advertising) cambia solo se la scrittura è andata bene */
static void devcfg_verify(void)
{
  char reply[2u + DEVCFG_NAME_MAX_LEN + 1u];

  if (memcmp((const void *)DEVCFG_ADDR, &s_record, sizeof(s_record)) != 0)
  {
    devcfg_finish("L-VERIFY");
    return;
  }
  memcpy(s_name, s_record.name, s_record.name_len);
  s_name[s_record.name_len] = '\0';
  s_name_len = (uint8_t)s_record.name_len;

  reply[0] = 'L';
  reply[1] = '+';
  memcpy(&reply[2], s_name, (size_t)s_name_len + 1u);
  devcfg_finish(reply);
}

static void DEVCFG_FlashCallback(FM_FlashOp_Status_t Status)
{
  switch (s_state)
  {
    case DEVCFG_WAIT_ERASE:
      if (Status == FM_OPERATION_AVAILABLE)
      {
        devcfg_start_erase();
      }
      break;

    case DEVCFG_ERASING:
      if (Status == FM_OPERATION_COMPLETE)
      {
        devcfg_start_write();
      }
      break;

    case DEVCFG_WAIT_WRITE:
      if (Status == FM_OPERATION_AVAILABLE)
      {
        devcfg_start_write();
      }
      break;

    case DEVCFG_WRITING:
      if (Status == FM_OPERATION_COMPLETE)
      {
        devcfg_verify();
      }
      break;

    default:
      break;
  }
}

void DEVCFG_Init(void)
{
  const DevCfg_Record_t *p_flash = (const DevCfg_Record_t *)DEVCFG_ADDR;

  if ((devcfg_page_is_free() != 0u) && (devcfg_record_valid(p_flash) != 0u))
  {
    memcpy(s_name, p_flash->name, p_flash->name_len);
    s_name[p_flash->name_len] = '\0';
    s_name_len = (uint8_t)p_flash->name_len;
  }
}

const char *DEVCFG_GetName(uint8_t *p_len)
{
  if (p_len != NULL)
  {
    *p_len = s_name_len;
  }
  return s_name;
}

void DEVCFG_RequestRename(const uint8_t *p_name, uint16_t len)
{
  /* Il nome finisce al primo '\0' (la GUI lo aggiunge): se la caratteristica dei comandi fosse
   * a lunghezza fissa, lo stack passerebbe tutti i suoi 20 byte, compresi i resti dei comandi
   * precedenti, e il nome risulterebbe non valido */
  uint16_t n = 0u;
  while ((n < len) && (p_name[n] != 0u))
  {
    n++;
  }
  len = n;

  if (s_state != DEVCFG_IDLE)
  {
    BLE_SENSOR_APP_SendReply("L-BUSY");
    return;
  }
  if (devcfg_name_valid((const char *)p_name, len) == 0u)
  {
    BLE_SENSOR_APP_SendReply("L-NAME");
    return;
  }
  if (devcfg_page_is_free() == 0u)
  {
    BLE_SENSOR_APP_SendReply("L-SPACE");
    return;
  }

  memset(&s_record, 0, sizeof(s_record));
  s_record.magic = DEVCFG_MAGIC;
  s_record.version = DEVCFG_VERSION;
  s_record.name_len = len;
  memcpy(s_record.name, p_name, len);
  s_record.reserved = 0xFFFFFFFFu;
  s_record.crc = devcfg_crc32(&s_record, offsetof(DevCfg_Record_t, crc));

  if (memcmp((const void *)DEVCFG_ADDR, &s_record, sizeof(s_record)) == 0)
  {
    devcfg_verify();   /* nome già salvato: niente cancellazione del flash */
    return;
  }
  devcfg_start_erase();
}
