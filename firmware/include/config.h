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

// 畫面左右顛倒或錯位時可試著切換
#define PANEL_CLKPHASE false

// ===== 伺服器 =====
// 第一次開機會進入 WiFi 設定頁，可以在那裡改；這裡只是預設值
#define DEFAULT_SERVER_URL "http://192.168.1.100:8080"

// 連續失敗幾次才顯示錯誤畫面（避免偶發斷線就閃錯誤）
#define FAILS_BEFORE_ERROR 3

// ===== 按鈕 =====
// 開機時按住 BOOT 鍵 = 清除 WiFi 設定、重新進入設定頁
#define PIN_BTN_RESET 0

#if defined(BOARD_MATRIXPORTAL_S3)
// MatrixPortal S3 板上的 UP / DOWN 鍵：UP = 下一頁，DOWN = 暫停輪播（固定在目前這場）
#define PIN_BTN_NEXT 6
#define PIN_BTN_PAUSE 7
#else
#define PIN_BTN_NEXT -1
#define PIN_BTN_PAUSE -1
#endif
