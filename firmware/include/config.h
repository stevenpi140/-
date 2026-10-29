#pragma once

// ===== 面板設定 =====
// 兩片 64x64 串接 = 128x64（伺服器 config.yaml 的 display.width/height 要一致）
#define PANEL_RES_X 64
#define PANEL_RES_Y 64
#define PANEL_CHAIN 2

#define FRAME_W (PANEL_RES_X * PANEL_CHAIN)
#define FRAME_H PANEL_RES_Y

// 某些面板（FM6126A 驅動晶片）開機全黑或亂碼時，把這行打開
// #define PANEL_DRIVER_FM6126A
#if defined(BOARD_WAVESHARE_S3)
// 微雪官方範例搭配自家面板都設定 FM6126A；畫面異常時可以註解掉這行試試
#define PANEL_DRIVER_FM6126A
#endif

// 畫面左右顛倒或錯位時可試著切換
#define PANEL_CLKPHASE false

// ===== 伺服器 =====
// 第一次開機會進入 WiFi 設定頁，可以在那裡改；這裡只是預設值
#define DEFAULT_SERVER_URL "http://192.168.1.100:8080"

// 連續失敗幾次才顯示錯誤畫面（避免偶發斷線就閃錯誤）
#define FAILS_BEFORE_ERROR 3

// ===== 按鈕 =====
// 開機後 2 秒內按住 BOOT 鍵 = 清除 WiFi 設定、重新進入設定頁（接電之前就按著會進入燒錄模式）
#define PIN_BTN_RESET 0

#if defined(BOARD_MATRIXPORTAL_S3)
// MatrixPortal S3 板上的 UP / DOWN 鍵：UP = 下一頁，DOWN = 暫停輪播（固定在目前這場）
#define PIN_BTN_NEXT 6
#define PIN_BTN_PAUSE 7
#else
#define PIN_BTN_NEXT -1
#define PIN_BTN_PAUSE -1
#endif

// ===== OTA 無線更新 =====
// 密碼在 platformio.ini 的 [ota] password 設定；這裡只是沒透過 PlatformIO 編譯時的備用值
#ifndef OTA_PASSWORD
#define OTA_PASSWORD "scoreboard"
#endif
// 區網名稱：scoreboard.local
#define OTA_HOSTNAME "scoreboard"

// ===== 整點報時（喇叭）=====
// 時間表和音檔都在伺服器的 config.yaml（chime 區段）設定；只有板子上有喇叭的才會發聲
#if defined(BOARD_WAVESHARE_S3)
// 微雪 ESP32-S3-RGB-Matrix：ES8311 音訊晶片 + 功放，腳位取自微雪官方範例 09_Music_Player
#define HAS_SPEAKER 1
#define PIN_CODEC_SDA 47
#define PIN_CODEC_SCL 48
#define PIN_I2S_MCLK 12
#define PIN_I2S_BCLK 43
#define PIN_I2S_LRC 38
#define PIN_I2S_DOUT 21
#define PIN_AUDIO_PA 11  // 功放開關，HIGH = 開
#else
#define HAS_SPEAKER 0
#endif
#define CHIME_SAMPLE_RATE 48000               // 伺服器轉好的格式：48kHz、16-bit、單聲道
#define CHIME_MAX_BYTES (4 * 1024 * 1024)     // 最長約 40 秒，放在 PSRAM
