#include "main.h"
#include "app_common.h"
#include "log_module.h"
#include "app_ble.h"
#include "ll_sys_if.h"
#include "dbg_trace.h"
#include "ble_sensor_app.h"
#include "ble_sensor.h"
#include "stm32_rtos.h"
#include "stdlib.h" // Serve per abs()

#include "string.h"
#include "stm32_timer.h"
#include "DUST_functions.h"

#include "stm32wbaxx_hal.h"
#include "stm32wbaxx_hal_lptim.h"

#include "log_module.h"


#define DUST_CHANNELS   32u
#define SENDING_ROUND	  2
#define DUST_MAVG_WINDOW_MAX 99u

#define FRAME_SYNC1   0xAA
#define FRAME_SYNC2   0x55
#define PKT_SYNC_CAN  0xA5

#define DUST_WARMUP_SAMPLES  150u  // Ignora i primi 150 campioni (circa 1-3 secondi a seconda del clock)

uint16_t adc_val = 0;
uint8_t dust_mavg_window = 4u;   // moving average over N samples (to be tuned)
uint16_t dust_thresh_offset = 50u;
// Buffer di prova (array di uint8_t)
uint8_t test_message[] = "UART DMA TEST: Linea Operativa\r\n";
uint16_t message_size = sizeof(test_message) - 1;

// Buffer per contenere la stringa di testo da inviare
char uart_text_buffer[64];

//extern TIM_HandleTypeDef htim3;
uint16_t pwm_buf[] = {13000, 13000, 0, 0, 0, 0, 0, 0, 0, 0}; //to use in case of PWM DMA
uint8_t channel;

uint8_t spi_data[] = {0};
uint8_t size = 1;

// Buffer per inviare il "comando" (un byte dummy/comando di 16 bit)
// Nota: Userai il cast a uint8_t* in HAL_SPI_TransmitReceive_DMA
uint16_t Tx_Command_Buffer[1] = {0x0001}; // Byte dummy
uint16_t Rx_Data_Buffer[1];
uint16_t transfer_length = 1; // 1 parola (unità di 16 bit)


// Variabili globali per la frequenza PWM in modalità Automatica
uint32_t g_pwm_freq_khz = 4; // Default 4 kHz
uint32_t g_pwm_arr = 249;    // ARR default
uint32_t g_pwm_pulse = 125;  // Duty cycle al 50% default

// Variabile per il canale manuale (0-31 per il firmware, ma l'utente invia 1-32)
uint8_t g_manual_channel = 0;

volatile uint8_t g_ble_dust_stream_enabled = 0;
volatile uint8_t g_usb_dust_stream_enabled = 0;

uint8_t g_sd_save_request = 0; // Dichiarazione extern
uint8_t g_enable_sd_saving = 0;

extern uint8_t g_ram_buffer[];
extern uint32_t g_ram_head;

volatile uint8_t dcc_sel_ck = 0;

// -------------------- strutture dati per canali ------ //
typedef enum
{
    DUST_STATE_MONITORING = 0,
    DUST_STATE_CONFIRMING,
    DUST_STATE_FOUND
} DustState_t;

typedef struct
{
    // Moving average
    uint16_t mavg_buffer[DUST_MAVG_WINDOW_MAX];
    uint32_t mavg_sum;
    uint8_t  mavg_index;
    uint8_t  mavg_count;

    // Baseline (IIR lento)
    uint16_t baseline;

    // State machine
    DustState_t state;
    uint8_t  over_cnt;
    uint8_t  under_cnt;
    uint8_t refr_cnt;
    uint16_t last_raw;

    // Evento corrente
    uint16_t event_buf[DUST_EVENT_SAMPLES];
    uint8_t  event_len;
    uint32_t event_timestamp_ms;

    // Contatore particelle per canale
    uint8_t particle_count;

    uint16_t warmup_cnt; // Contatore per il riscaldamento iniziale

} DustChannelState_t;

static DustChannelState_t   g_ch[DUST_CHANNELS];
static uint8_t              g_current_channel = 0u;
static DustEventCallback_t  g_dust_cb = NULL;   // callback utente

static uint8_t              next_ch = 0u;
static uint8_t  			sending_round   = 0u;

static uint8_t uart_frame[2 + DUST_CHANNELS * 3 + 2]; // header + 32*(sync+ch+count+2B) + "\r\n"


// ---------------------------------------------- //

static const uint32_t bsrrA[32] = {
    0x00DA0000, // i=0  (00000) -> Reset PA1, PA3, PA4, PA6, PA7
    0x005A0080, // i=1  (00001) -> Set PA7
    0x009A0040, // i=2  (00010) -> Set PA6
    0x001A00C0, // i=3  (00011) -> Set PA6, PA7
    0x00CA0010, // i=4  (00100) -> Set PA4
    0x004A0090, // i=5  (00101) -> Set PA4, PA7
    0x008A0050, // i=6  (00110) -> Set PA4, PA6
    0x000A00D0, // i=7  (00111) -> Set PA4, PA6, PA7
    0x00D20008, // i=8  (01000) -> Set PA3
    0x00520088, // i=9  (01001) -> Set PA3, PA7
    0x00920048, // i=10 (01010) -> Set PA3, PA6
    0x001200C8, // i=11 (01011) -> Set PA3, PA6, PA7
    0x00C20018, // i=12 (01100) -> Set PA3, PA4
    0x00420098, // i=13 (01101) -> Set PA3, PA4, PA7
    0x00820058, // i=14 (01110) -> Set PA3, PA4, PA6
    0x000200D8, // i=15 (01111) -> Set PA3, PA4, PA6, PA7
    0x00D80002, // i=16 (10000) -> Set PA1
    0x00580082, // i=17 (10001) -> Set PA1, PA7
    0x00980042, // i=18 (10010) -> Set PA1, PA6
    0x001800C2, // i=19 (10011) -> Set PA1, PA6, PA7
    0x00C80012, // i=20 (10100) -> Set PA1, PA4
    0x00480092, // i=21 (10101) -> Set PA1, PA4, PA7
    0x00880052, // i=22 (10110) -> Set PA1, PA4, PA6
    0x000800D2, // i=23 (10111) -> Set PA1, PA4, PA6, PA7
    0x00D0000A, // i=24 (11000) -> Set PA1, PA3
    0x0050008A, // i=25 (11001) -> Set PA1, PA3, PA7
    0x0090004A, // i=26 (11010) -> Set PA1, PA3, PA6
    0x001000CA, // i=27 (11011) -> Set PA1, PA3, PA6, PA7
    0x00C0001A, // i=28 (11100) -> Set PA1, PA3, PA4
    0x0040009A, // i=29 (11101) -> Set PA1, PA3, PA4, PA7
    0x0080005A, // i=30 (11110) -> Set PA1, PA3, PA4, PA6
    0x000000DA  // i=31 (11111) -> Set PA1, PA3, PA4, PA6, PA7
};

void DATA_RECEIVED(const uint8_t *data_received, uint16_t len)
{
	uint8_t cmd = data_received[0];
	switch (cmd) {

		case '1':

			if (len >= 2 && data_received[1] == 'a')
				CHANNEL_SET(1);//LED ON, poi itereremo da 0 a 32 per selezionare i canali
			else
				CHANNEL_SET(9);//LED ON, poi itereremo da 0 a 32 per selezionare i canali

			break;

		// ------ comando debug colori led ------ //
		case 'k':

			if (data_received[1] == 'g')
			  LED_BLINKING(TIM_CHANNEL_1, pwm_buf); //green
			if (data_received[1] == 'r')
			  LED_BLINKING(TIM_CHANNEL_2, pwm_buf); //red --> questo è collegato al led della EBoard
			if (data_received[1] == 'b')
			  LED_BLINKING(TIM_CHANNEL_3, pwm_buf); //blue

			break;

		case 'A':

				HAL_LPTIM_Counter_Stop_IT(&hlptim1);
				g_ble_dust_stream_enabled = 0;
				g_usb_dust_stream_enabled = 0;
				GET_ADC_VALUES();
			break;

		// ------ Serial or Bluetooth Communication ------ //
		case 'C':

				HAL_LPTIM_Counter_Start_IT(&hlptim1);

				if (len >= 2 && data_received[1] == 'b')
				{
					g_ble_dust_stream_enabled = 1;
					g_usb_dust_stream_enabled = 0;
				}
				else //use "Cu" for USB
				{
					g_ble_dust_stream_enabled = 0;
					g_usb_dust_stream_enabled = 1;
				}
				//GET_ADC_VALUES_continous();

			break;

		// ------ Only Bluetooth communication ------ //
		case 'B':
				HAL_LPTIM_Counter_Start_IT(&hlptim1);

				g_ble_dust_stream_enabled = 1;
				g_usb_dust_stream_enabled = 0;

			break;


		// ------ Averaging Window Size ------ //
		case 'V':

		    if (len <= 1)
		    {
		        // Nessun numero dopo 'V', ignoro
		        break;
		    }

		    char tmp[4];  // max 3 cifre + '\0'
		    uint16_t num_bytes = len - 1;

		    // Limito il numero di byte copiati a sizeof(tmp)-1
		    if (num_bytes > (sizeof(tmp) - 1))
		    {
		        num_bytes = sizeof(tmp) - 1;
		    }

		    memcpy(tmp, &data_received[1], num_bytes);
		    tmp[num_bytes] = '\0';

		    int val = atoi(tmp);   // converto la stringa in intero

		    // Clamp nella banda sensata
		    if (val < 1)
		        val = 1;
		    if (val > DUST_MAVG_WINDOW_MAX)
		        val = DUST_MAVG_WINDOW_MAX;

		    dust_mavg_window = (uint8_t)val;

		break;

		// ------ SD savte to file ------ //
		case 'S': // 'S' come Save o SD

			// Se invii "S" dalla GUI, prova a scrivere il file
			//SD_Write_Test_File();

			if (len >= 2 && data_received[1] == '0')
				g_enable_sd_saving = 0;
			else
				g_enable_sd_saving = 1;

			break;

		// ------ Dust Clock Frequency selection ------ //
		case 'K':

			if (len >= 2 && data_received[1] == '5') //50kHz
			{
				HAL_GPIO_WritePin(GPIOB, GPIO_PIN_1, GPIO_PIN_RESET); //A0 = 0
				HAL_GPIO_WritePin(GPIOB, GPIO_PIN_2, GPIO_PIN_RESET); //A1 = 0
			}
			else if(len >= 2 && data_received[1] == '4') //400kHz
			{
				HAL_GPIO_WritePin(GPIOB, GPIO_PIN_1, GPIO_PIN_RESET); //A0 = 0
				HAL_GPIO_WritePin(GPIOB, GPIO_PIN_2, GPIO_PIN_SET); //A1 = 1
			}
			else //200kHz
			{
				HAL_GPIO_WritePin(GPIOB, GPIO_PIN_1, GPIO_PIN_SET); //A0 = 1
				HAL_GPIO_WritePin(GPIOB, GPIO_PIN_2, GPIO_PIN_RESET); //A1 = 0
			}
			break;

		// ------ Automatic or Manual channel iteration
		case 'M':

			if(len >= 2 && data_received[1] == 'A')
			{
				HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, GPIO_PIN_RESET); //Automatic channel selection and iteration
				Config_PA7_As_PWM();
				HAL_GPIO_WritePin(GPIOA, GPIO_PIN_11, GPIO_PIN_SET); // Reset canale corrente a 0
				HAL_GPIO_WritePin(GPIOA, GPIO_PIN_11, GPIO_PIN_RESET); // Il segnale reset torna basso
				next_ch = 0u;
				dcc_sel_ck = 0; // flag automatic
			}
			else
			{
				HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, GPIO_PIN_SET); //Manual Channel selection and iteration
				Config_PA7_As_GPIO();
				next_ch = 0u;
				dcc_sel_ck = 1;	// flag manual
			}
			break;

		// ------ Offset Dust Signal Configuration ------ //
		case 'O':

		    if (len <= 1)
		    {
		        // Nessun numero dopo 'V', ignoro
		        break;
		    }
		    else
		    {

			    char tmp[4];  // max 3 cifre + '\0'
			    uint16_t num_bytes = len - 1;

			    // Limito il numero di byte copiati a sizeof(tmp)-1
			    if (num_bytes > (sizeof(tmp) - 1))
			    {
			        num_bytes = sizeof(tmp) - 1;
			    }

				memcpy(tmp, &data_received[1], num_bytes);
			    tmp[num_bytes] = '\0';

			    int val = atoi(tmp);

			    dust_thresh_offset = val;
			}

			break;

			// ------ PWM Frequency Configuration (kHz) ------ //
			case 'F':
				if (len > 1)
				{
					char tmp[4];  // max 3 cifre + '\0'
					uint16_t num_bytes = len - 1;

					// Limito il numero di byte
					if (num_bytes > (sizeof(tmp) - 1))
					{
						num_bytes = sizeof(tmp) - 1;
					}

					memcpy(tmp, &data_received[1], num_bytes);
					tmp[num_bytes] = '\0';

					int val_khz = atoi(tmp);

					// Sicurezza: Limito la frequenza tra 1 kHz e 500 kHz
					if (val_khz >= 1 && val_khz <= 500)
					{
						g_pwm_freq_khz = val_khz;
						g_pwm_arr = (1000 / g_pwm_freq_khz) - 1;
						g_pwm_pulse = (g_pwm_arr + 1) / 2; // Mantiene il duty cycle al 50%

						// Se siamo già in modalità automatica, aggiorna i registri del timer al volo
						if (dcc_sel_ck == 0)
						{
							__HAL_TIM_SET_AUTORELOAD(&htim2, g_pwm_arr);
							__HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_3, g_pwm_pulse);
						}
					}
				}
				break;


				// ------ Manual Channel Selection ------ //
				case 'N':
					if (len > 1)
					{
						char tmp[4];
						uint16_t num_bytes = len - 1;

						if (num_bytes > (sizeof(tmp) - 1))
						{
							num_bytes = sizeof(tmp) - 1;
						}

						memcpy(tmp, &data_received[1], num_bytes);
						tmp[num_bytes] = '\0';

						int val = atoi(tmp);

						// L'utente invia da 1 a 32. In C gli array sono da 0 a 31.
						if (val >= 1 && val <= 32)
						{
							g_manual_channel = (uint8_t)(val - 1);

							// Se siamo già in modalità manuale, cambiamo subito fisicamente il canale
							if (dcc_sel_ck == 1)
							{
								CHANNEL_SET(g_manual_channel);
							}
						}
					}
					break;

		// ------ Reset ALL ------ //
		case '0':
			HAL_LPTIM_Counter_Stop_IT(&hlptim1);
			g_ble_dust_stream_enabled = 0;
			g_usb_dust_stream_enabled = 0;

			break;

		case 0xA5:

			break;

		default:

			break;
	}
}

static inline void CHANNEL_SET_Init(void)
{
	//At initialization, all the selection pins are set to 0, so CH0 is
	//selected. This avoids ESD protection of the sensor pads to be activated.
	GPIOA->BSRR = 0x00DA0000;
}

static inline void CHANNEL_SET(uint8_t channel)
{
	//channel &= 0x1F; //keep only 5 LSB bits

	GPIOA->BSRR = bsrrA[channel & 0x1F]; //select dust sensor channel
}

void LED_BLINKING(const uint32_t LED_COLOR, uint16_t *pwm_buffer)
{
	//HAL_TIM_PWM_Stop_DMA(&htim3, LED_COLOR);
	//__HAL_TIM_SET_AUTORELOAD(&htim3, 65535);
	//__HAL_TIM_SET_COMPARE(&htim3, LED_COLOR, 65535);
	HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_1);
	HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_2);
	HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_3);

	HAL_TIM_PWM_Start(&htim3, LED_COLOR);
}

void GET_ADC_VALUES()
{
	CHANNEL_SET(9);
	HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_SET); //Read dust chip values
	//HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_RESET); //Read dust chip values
	//HAL_GPIO_WritePin(GPIOB, GPIO_PIN_11, GPIO_PIN_RESET); //Do not read SD
	HAL_StatusTypeDef status;
	HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_1);

	status = HAL_SPI_TransmitReceive(&hspi3, (uint8_t*)Tx_Command_Buffer, (uint8_t*)Rx_Data_Buffer, transfer_length, 10);
    adc_val = Rx_Data_Buffer[0];
    // 2. Trasmette i 2 byte ricevuti via UART (come discusso)
    //HAL_UART_Transmit_DMA(&huart1, test_message, message_size);
    int len = sprintf(uart_text_buffer, "ADC: %d\r\n", adc_val);
    HAL_UART_Transmit_DMA(&huart1, (uint8_t*)uart_text_buffer, len);
	//status = HAL_SPI_Receive_DMA(&hspi3, spi_data, size);
}


void GET_ADC_VALUES_continous()
{

	if (hspi3.State != HAL_SPI_STATE_READY) return;

	HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_SET); //Read dust chip values

	// Il timer è configurato in One-Pulse Mode, quindi si fermerà da solo.
	__HAL_TIM_SET_COUNTER(&htim1, 0); // Resetta il contatore
	HAL_TIM_Base_Start_IT(&htim1);    // Avvia il timer con interrupt


	//HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_RESET); //Read dust chip values
	//HAL_GPIO_WritePin(GPIOB, GPIO_PIN_11, GPIO_PIN_RESET); //Do not read SD
	//HAL_StatusTypeDef status;

	//status = HAL_SPI_TransmitReceive_DMA(&hspi3, (uint8_t*)Tx_Command_Buffer, (uint8_t*)Rx_Data_Buffer, transfer_length);

	//status = HAL_SPI_Receive_DMA(&hspi3, spi_data, size);
}


// Puoi mettere questa funzione in main.c o DUST_functions.c
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    // Controlla che sia TIM1 a chiamare
    if (htim->Instance == TIM1)
    {
        // 1. Ferma il timer (sicurezza, anche se in OnePulse dovrebbe fermarsi)
        HAL_TIM_Base_Stop_IT(&htim1);

        // 2. Fine Conversione: CONVST BASSO
        // Ora i dati sono pronti nel registro dell'ADC
        HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_RESET);

        // 3. Avvia la lettura DMA
        // Se fallisce riporta CS alto per reset
        if (HAL_SPI_TransmitReceive_DMA(&hspi3, (uint8_t*)Tx_Command_Buffer, (uint8_t*)Rx_Data_Buffer, transfer_length) != HAL_OK)
        {
            HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_SET);
        }
    }
}

void HAL_LPTIM_AutoReloadMatchCallback(LPTIM_HandleTypeDef *hlptim)
{
	//HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_1); DEBUG

    // Se la lettura canali è manuale -> Selecting prossimo canale SW e HW --> POI LI METTO INSIEME
	if(dcc_sel_ck == 1)
	{
		//CHANNEL_SET(next_ch);
		CHANNEL_SET(g_manual_channel);
	}
	DUST_SetCurrentChannel(next_ch);
	GET_ADC_VALUES_continous();

}

void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef *hspi)
{
    if (hspi->Instance == SPI3)
    {
        // 1. FINE LETTURA: Riporta il pin CONVST (CS) HIGH
        // DOUT torna in 3-state e l'ADC in fase di Acquisizione.
        //HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_SET);

        uint16_t adc_val = Rx_Data_Buffer[0];
        uint32_t now_ms  = HAL_GetTick();

        //adc_val = adc_val + 1; DEBUG
        DUST_Process(g_current_channel, adc_val, now_ms);

        next_ch++;

        if (next_ch >= DUST_CHANNELS)
        {
            next_ch = 0u;
            //dust_send_pending = 1;

            sending_round++;


            if (g_enable_sd_saving == 1)
            {
    			uint16_t RAM_frame_len = DUST_BuildFrame_RAM(uart_frame, sizeof(uart_frame));

    			if(RAM_frame_len > 0)
    				DUST_Save_To_Ram(uart_frame, RAM_frame_len);
            }

            // Invio dati una volta ogni N giri
            if (sending_round >= SENDING_ROUND)
            {
            	sending_round = 0;

            	if ((huart1.gState == HAL_UART_STATE_READY) && (g_usb_dust_stream_enabled == 1))
    			{
            		DUST_SendFrame_UART();
    			}
            	else if(g_ble_dust_stream_enabled == 1)
            	{
            		UTIL_SEQ_SetTask(1U << CFG_TASK_MYDATA_UPDATE_ID, CFG_SEQ_PRIO_0);
            	}
            }

        }
		//int len = sprintf(uart_text_buffer, "CH %02u RAW:%5u FILT:%5u\r\n", g_current_dust_channel, adc_val, filtered);
		//HAL_UART_Transmit_DMA(&huart1, (uint8_t*)uart_text_buffer, len);

    }
}

// ------------------- algoritmo canali ------------------- //

static void DUST_Internal_ResetChannel(DustChannelState_t *s)
{
    memset(s->mavg_buffer, 0, sizeof(s->mavg_buffer));
    s->mavg_sum          = 0u;
    s->mavg_index        = 0u;
    s->mavg_count        = 0u;
    s->baseline        = 0u;
    s->state           = DUST_STATE_MONITORING;
    s->over_cnt        = 0u;
    s->under_cnt       = 0u;
    s->refr_cnt        = 0u;
    s->last_raw        = 0u;
    s->event_len       = 0u;
    s->event_timestamp_ms = 0u;
    s->particle_count  = 0u;
    s->warmup_cnt        = 0u;
}

// Moving average su una finestra di DUST_MAVG_WINDOW campioni
static uint16_t DUST_Internal_MAVG_Update(DustChannelState_t *s, uint16_t sample)
{
    uint8_t idx   = s->mavg_index;
    uint8_t count = s->mavg_count;

    // Finestra effettiva: clamp a [1, DUST_MAVG_WINDOW_MAX]
    uint8_t win = dust_mavg_window;
    if (win == 0u)
        win = 1u;
    if (win > DUST_MAVG_WINDOW_MAX)
        win = DUST_MAVG_WINDOW_MAX;

    if (count < win)
    {
        s->mavg_count = (uint8_t)(count + 1u);
    }

    // Rimuovo il campione vecchio dalla somma, aggiungo il nuovo
    s->mavg_sum -= s->mavg_buffer[idx];
    s->mavg_sum += sample;

    // Scrivo il nuovo campione nel buffer circolare
    s->mavg_buffer[idx] = sample;

    // Avanzo indice
    idx++;
    if (idx >= win)
    {
        idx = 0u;
    }
    s->mavg_index = idx;

    // Media: uso count se non ho ancora riempito la finestra
    uint8_t denom = s->mavg_count;
    if (denom == 0u)
    {
        return sample; // protezione, non dovrebbe succedere
    }

    uint16_t avg = (uint16_t)(s->mavg_sum / (uint32_t)denom);
    return avg;
}

// Baseline IIR: y += (x - y) >> shift
static uint16_t DUST_Internal_Baseline_Update(uint16_t prev, uint16_t x, uint8_t shift)
{
    int32_t diff = (int32_t)x - (int32_t)prev;
    prev = (uint16_t)((int32_t)prev + (diff >> shift));
    return prev;
}

// Chiama la callback utente con i dati dell'evento
static void DUST_Internal_CallCallback(uint8_t ch, DustChannelState_t *s)
{
    if (g_dust_cb == NULL)
        return;

    DustEvent_t ev;
    ev.channel      = ch;
    ev.timestamp_ms = s->event_timestamp_ms;
    ev.len          = s->event_len;
    if (ev.len > DUST_EVENT_SAMPLES)
        ev.len = DUST_EVENT_SAMPLES;

    for (uint8_t i = 0u; i < ev.len; i++)
    {
        ev.samples[i] = s->event_buf[i];
    }

    // IMPORTANTE: questa funzione viene chiamata in contesto di ISR (SPI callback).
    // Qui dentro la callback NON deve fare cose lente o bloccanti.
    g_dust_cb(&ev);
}

void DUST_Init(void)
{
    for (uint8_t ch = 0u; ch < DUST_CHANNELS; ch++)
    {
        DUST_Internal_ResetChannel(&g_ch[ch]);
    }
    g_current_channel = 0u;
    g_dust_cb         = NULL;
}

void DUST_SetCallback(DustEventCallback_t cb)
{
    g_dust_cb = cb;
}

void DUST_SetCurrentChannel(uint8_t ch)
{
    if (ch >= DUST_CHANNELS)
    {
        ch = 0u;
    }
    g_current_channel = ch;

    // QUI NON faccio niente sull'hardware: gestire mux HW
    // nella CHANNEL_SET(...)
}

// Da chiamare nella callback SPI quando arriva un nuovo sample ADC
void DUST_Process(uint8_t channel, uint16_t raw_sample, uint32_t timestamp_ms)
{
    uint8_t ch = channel;
    if (ch >= DUST_CHANNELS) return;

    DustChannelState_t *s = &g_ch[ch];

    // 1) Moving average (Sempre attiva per pulire il segnale)
    uint16_t filtered = DUST_Internal_MAVG_Update(s, raw_sample);
    s->last_raw = raw_sample;

    // --- WARM-UP ---
    // All'avvio non sappiamo dove sia il segnale. Per i primi campioni
    // ci limitiamo a inseguirlo per trovare il punto di partenza.
    if (s->warmup_cnt < DUST_WARMUP_SAMPLES)
    {
        s->warmup_cnt++;
        s->baseline = filtered;
        s->state = DUST_STATE_MONITORING;
        s->over_cnt = 0;
        return;
    }

    // Calcoliamo la differenza ASSOLUTA (per vedere sia salite che discese)
    // Cast a int32_t per gestire valori negativi prima dell'abs
    int32_t diff = (int32_t)filtered - (int32_t)s->baseline;
    uint16_t abs_diff = (uint16_t)abs(diff);

    // 4) State machine
    switch (s->state)
    {
        case DUST_STATE_MONITORING:
        {
            // Se c'è un salto brusco (in alto O in basso) maggiore della soglia
            if (abs_diff > dust_thresh_offset)
            {
                if (s->over_cnt < 255u) s->over_cnt++;

                // Se il salto persiste per un po' (filtro spike veloci)
                if (s->over_cnt >= DUST_MIN_OVER_SAMPLES)
                {
                    s->state              = DUST_STATE_CONFIRMING;
                    s->over_cnt           = 0u;
                    // Reset buffer evento
                    s->event_len          = 0u;
                    s->event_timestamp_ms = timestamp_ms;
                }
            }
            else
            {
                s->over_cnt = 0u;

                // Se il segnale è stabile (nessun salto), aggiorniamo LENTAMENTE la baseline
                // per inseguire la deriva termica (Drift)
                s->baseline = DUST_Internal_Baseline_Update(s->baseline,
                                                            filtered,
                                                            DUST_BASE_SHIFT);
            }
        } break;

        case DUST_STATE_CONFIRMING:
        {
            // Continuiamo a verificare se il segnale è ancora "lontano" dalla vecchia baseline
            // Questo gestisce il fatto che il fronte di salita dura 4-5 campioni
            if (abs_diff > dust_thresh_offset)
            {
                if (s->over_cnt < 255u) s->over_cnt++;

                // Se persiste per 4 campioni, è un gradino confermato!
                if (s->over_cnt >= 4u)
                {
                    // 1. CONTIAMO LA PARTICELLA
                    s->particle_count++;

                    // 2. CAMBIAMO STATO
                    // Non andiamo in MONITORING, ma in FOUND/STABILIZING
                    // per assorbire il resto della salita/discesa e aggiornare il riferimento.
                    s->state = DUST_STATE_FOUND;

                    // Impostiamo un tempo morto (Dead Time) in cui inseguiamo il segnale
                    // 10 campioni dovrebbero bastare per far finire la transizione del gradino
                    s->refr_cnt = 10;

                    // Salva dati evento
                    if (s->event_len < DUST_EVENT_SAMPLES) s->event_buf[s->event_len++] = filtered;
                }
            }
            else
            {
                // Era solo un rumore momentaneo, torniamo a monitorare
                s->state = DUST_STATE_MONITORING;
                s->over_cnt = 0u;
            }

        } break;

        case DUST_STATE_FOUND:
        {
            // --- FASE DI ASSESTAMENTO (LATCHING) ---
            // In questa fase sappiamo che il segnale è cambiato livello.
            // Dobbiamo aggiornare la baseline al NUOVO livello.

            // 1. Aggiornamento forzato della baseline
            // Facciamo sì che la baseline "insegua" velocemente il segnale mentre finisce di salire/scendere
            s->baseline = filtered;

            // 2. Decremento timer
            if (s->refr_cnt > 0u)
            {
                s->refr_cnt--;
            }
            else
            {
                // Fine del tempo di assestamento.
                // Ora la baseline è allineata al nuovo livello del gradino.
                // Possiamo tornare a cercare nuove variazioni rispetto a QUESTO nuovo livello.
                s->state = DUST_STATE_MONITORING;
                s->over_cnt = 0u;

                // Callback evento completato
                DUST_Internal_CallCallback(ch, s);
            }

            // Salvataggio campioni per debug
            if (s->event_len < DUST_EVENT_SAMPLES)
            {
                s->event_buf[s->event_len++] = filtered;
            }

        } break;

        default:
            s->state = DUST_STATE_MONITORING;
            break;
    }
}

uint16_t DUST_BuildFrame(uint8_t *dst, uint16_t max_len)
{
    uint8_t *p = dst;

    // Header
    *p++ = FRAME_SYNC1;
    *p++ = FRAME_SYNC2;

    // Corpo: per ogni canale -> [PKT_SYNC_CAN][CHANNEL][PARTICLES][ADC_MSB][ADC_LSB]
    for (uint8_t ch = 0; ch < DUST_CHANNELS; ch++)
    {
        uint16_t adc = g_ch[ch].last_raw;        // oppure last_filtered

        //*p++ = PKT_SYNC_CAN;
        //*p++ = ch;                               // channel number
        *p++ = g_ch[ch].particle_count;
        *p++ = (uint8_t)(adc >> 8);              // ADC_HI
        *p++ = (uint8_t)(adc & 0xFF);            // ADC_LO
    }

    // Terminatore di riga
    *p++ = '\r';
    *p++ = '\n';

    //uint16_t total_len = (uint16_t)(p - uart_frame);

    return (uint16_t)(p - dst);
    //HAL_UART_Transmit_DMA(&huart1, uart_frame, total_len);

}

void DUST_SendFrame_UART(void)
{
	uint16_t len = DUST_BuildFrame(uart_frame, sizeof(uart_frame));

	if (len == 0u)
	{
		return; // buffer troppo piccolo o errore
	}

	HAL_UART_Transmit_DMA(&huart1, uart_frame, len);
}

void HAL_COMP_TriggerCallback(COMP_HandleTypeDef *hcomp)
{
    // Verifichiamo che sia stato il COMP1
    if (hcomp->Instance == COMP1)
    {
        // Il segnale su PA2 ha appena superato 1/4 Vref.
    	// Analizziamo se è un rising o falling edge
    	uint32_t compOutput = HAL_COMP_GetOutputLevel(hcomp);

		if (compOutput == COMP_OUTPUT_LEVEL_HIGH)
		{
			// === RISING EDGE DETECTED ===
			// Il segnale è salito SOPRA la soglia
			// Accendi LED Rosso
			//LED_BLINKING(TIM_CHANNEL_2, pwm_buf); //red --> questo è collegato al led della EBoard

			//Spegniamo subito il sensore
			//HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, GPIO_PIN_RESET); //Con questa linea disattiviamo la power rail del sensore

		}
		else
		{
			// === FALLING EDGE DETECTED ===
			// Il segnale è sceso SOTTO la soglia
			// Il sensore è tornato a lavorare in codizioni sicure --> Accendi Led Verde e sensore o non fare nulla
			//LED_BLINKING(TIM_CHANNEL_1, pwm_buf); //red --> questo è collegato al led della EBoard

			//LED_BLINKING(TIM_CHANNEL_1, pwm_buf); //red --> questo è collegato al led della EBoard

			//Spegniamo subito il sensore
			//HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, GPIO_PIN_SET); //Con questa linea disattiviamo la power rail del sensore
		}

    }
}

void DUST_Save_To_Ram(uint8_t *new_data, uint16_t data_len)
{
    // 1. Controllo sicurezza: C'è spazio nel buffer?
    if ((g_ram_head + data_len) >= RAM_BUFFER_SIZE)
    {
        // Buffer pieno! Ripartiamo da zero (Circular Buffer)
        // o perdiamo il dato se non ancora salvato.
        // Per ora reset semplice per evitare crash:
        g_ram_head = 0;
    }

    // 2. SCRITTURA IN RAM (Copia veloce)
    // memcpy(destinazione, sorgente, lunghezza)
    memcpy(&g_ram_buffer[g_ram_head], new_data, data_len);

    // 3. Avanziamo l'indice
    g_ram_head += data_len;

    // 4. Controlliamo se è ora di scaricare su SD
    if (g_ram_head >= WRITE_THRESHOLD)
    {
        // Alziamo la bandierina!
        // Il while(1) nel main se ne accorgerà e fermerà tutto per salvare.
        g_sd_save_request = 1;
    }
}

uint16_t DUST_BuildFrame_RAM(uint8_t *dst, uint16_t max_len)
{
    uint8_t *p = dst;

    // Header
    *p++ = FRAME_SYNC1;
    *p++ = FRAME_SYNC2;

    // Corpo: per ogni canale -> [PKT_SYNC_CAN][CHANNEL][PARTICLES][ADC_MSB][ADC_LSB]
    for (uint8_t ch = 0; ch < DUST_CHANNELS; ch++)
    {
        uint16_t adc = g_ch[ch].last_raw;        // oppure last_filtered

        //*p++ = PKT_SYNC_CAN;
        //*p++ = ch;                               // channel number
        *p++ = (uint8_t)(adc >> 8);              // ADC_HI
        *p++ = (uint8_t)(adc & 0xFF);            // ADC_LO
    }

    // Terminatore di riga
    *p++ = '\r';
    *p++ = '\n';

    //uint16_t total_len = (uint16_t)(p - uart_frame);

    return (uint16_t)(p - dst);
    //HAL_UART_Transmit_DMA(&huart1, uart_frame, total_len);

}

// Funzione per passare alla modalità MANUALE (GPIO)
void Config_PA7_As_GPIO(void)
{
    // 1. Ferma il Timer per sicurezza
    HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_3);

    // 2. Riconfigura il pin come GPIO Output Standard
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin = GPIO_PIN_7;           // Usa PIN 7 diretto
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP; // Push-Pull normale (NO Alternate Function)
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;

    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    // 3. Imposta lo stato iniziale a 0 (LOW)
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_7, GPIO_PIN_RESET);
}

// Funzione per passare alla modalità AUTOMATICA (PWM 4kHz)
void Config_PA7_As_PWM(void)
{
    // 1. Assicuriamoci che i Clock siano attivi (serve se arriviamo da uno stop)
    __HAL_RCC_TIM2_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    // 2. Riconfigura il pin come ALTERNATE FUNCTION (lo colleghiamo al Timer)
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin = GPIO_PIN_7;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;      // Modalità Alternate Function
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF1_TIM2;   // Mappa su TIM2_CH3
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    // 3. Configura il Timer per 250us @ 96MHz
    // Prescaler 95 -> 96MHz / 96 = 1 MHz (1 tick = 1us)
    __HAL_TIM_SET_PRESCALER(&htim2, 95);

    // Periodo 249 -> 250 tick totali = 250us
    //__HAL_TIM_SET_AUTORELOAD(&htim2, 249);
    __HAL_TIM_SET_AUTORELOAD(&htim2, g_pwm_arr);

    // 4. Configura il Canale PWM (Duty 50%)
    TIM_OC_InitTypeDef sConfigOC = {0};
    sConfigOC.OCMode = TIM_OCMODE_PWM1;
    //sConfigOC.Pulse = 125; // 125us Alto, 125us Basso
    sConfigOC.Pulse = g_pwm_pulse;
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;

    // Applica configurazione al canale
    HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_3);

    // 5. Reset e Start
    __HAL_TIM_SET_COUNTER(&htim2, 0);
    HAL_TIM_GenerateEvent(&htim2, TIM_EVENTSOURCE_UPDATE); // Applica subito Prescaler
    HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_3);
}
