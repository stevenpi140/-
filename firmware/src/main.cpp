// 點陣比分看板韌體：從伺服器抓 RGB565 畫面，顯示在 HUB75 LED 面板上。
// 中文字型與版面都在伺服器處理，這裡只負責連網、抓圖、畫圖、換頁。

#include <Arduino.h>
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiManager.h>

#include "config.h"

static MatrixPanel_I2S_DMA *display = nullptr;
static Preferences prefs;
static char serverUrl[128] = DEFAULT_SERVER_URL;
static uint16_t frame[FRAME_W * FRAME_H];

static int page = 0;   // 下一次要抓的頁
static int shown = 0;  // 目前顯示中的頁
static int pageCount = 1;
static uint32_t holdUntil = 0;
static bool paused = false;
static int fails = 0;
static uint8_t brightness = 128;

// ---------- 顯示 ----------

static void setupDisplay() {
  HUB75_I2S_CFG cfg(PANEL_RES_X, PANEL_RES_Y, PANEL_CHAIN);
#if defined(BOARD_MATRIXPORTAL_S3)
  // R1, G1, B1, R2, G2, B2, A, B, C, D, E, LAT, OE, CLK
  cfg.gpio = {42, 41, 40, 38, 39, 37, 45, 36, 48, 35, 21, 47, 14, 2};
#else
  // 一般 ESP32 使用函式庫預設腳位（與 ESP32 Trinity 相同），E 腳接 GPIO 18
  cfg.gpio.e = 18;
#endif
#ifdef PANEL_DRIVER_FM6126A
  cfg.driver = HUB75_I2S_CFG::FM6126A;
#endif
  cfg.clkphase = PANEL_CLKPHASE;
  cfg.double_buff = true;  // 先畫在背景緩衝區再切換，換頁不會閃爍
  display = new MatrixPanel_I2S_DMA(cfg);
  display->begin();
  display->setBrightness8(brightness);
  display->clearScreen();
  display->flipDMABuffer();
  display->clearScreen();
}

static void showText(const char *line1, const char *line2 = nullptr, uint16_t color = 0xFFE0) {
  display->clearScreen();
  display->setTextWrap(false);
  display->setTextSize(1);
  display->setTextColor(color);
  display->setCursor(2, 2);
  display->print(line1);
  if (line2) {
    display->setTextColor(0x8410);
    display->setCursor(2, 14);
    display->print(line2);
  }
  display->flipDMABuffer();
}

static void drawFrame() {
  for (int y = 0; y < FRAME_H; y++) {
    const uint16_t *row = &frame[y * FRAME_W];
    for (int x = 0; x < FRAME_W; x++) {
      display->drawPixel(x, y, row[x]);
    }
  }
  display->flipDMABuffer();
}

// ---------- 設定 ----------

static void loadSettings() {
  prefs.begin("scoreboard", true);
  String s = prefs.getString("server", DEFAULT_SERVER_URL);
  prefs.end();
  strlcpy(serverUrl, s.c_str(), sizeof(serverUrl));
}

static void saveSettings() {
  prefs.begin("scoreboard", false);
  prefs.putString("server", serverUrl);
  prefs.end();
}

static void setupWifi() {
  WiFiManager wm;
  pinMode(PIN_BTN_RESET, INPUT_PULLUP);
  delay(50);
  if (digitalRead(PIN_BTN_RESET) == LOW) {
    showText("RESET WIFI");
    wm.resetSettings();
    delay(1000);
  }

  WiFiManagerParameter serverParam("server", "看板伺服器網址 (例: http://192.168.1.100:8080)", serverUrl,
                                   sizeof(serverUrl) - 1);
  wm.addParameter(&serverParam);
  bool shouldSave = false;
  wm.setSaveParamsCallback([&]() { shouldSave = true; });
  wm.setConfigPortalTimeout(300);

  char apName[32];
  snprintf(apName, sizeof(apName), "Scoreboard-%04X", (uint16_t)(ESP.getEfuseMac() & 0xFFFF));
  showText("CONNECTING", apName, 0x07FF);
  wm.setAPCallback([&](WiFiManager *) { showText("WiFi SETUP", apName, 0x07FF); });

  if (!wm.autoConnect(apName)) {
    showText("WiFi FAIL", "rebooting");
    delay(3000);
    ESP.restart();
  }
  if (shouldSave) {
    strlcpy(serverUrl, serverParam.getValue(), sizeof(serverUrl));
    // 去掉尾端斜線
    size_t n = strlen(serverUrl);
    while (n > 0 && serverUrl[n - 1] == '/') serverUrl[--n] = 0;
    saveSettings();
  }
  showText("WiFi OK", WiFi.localIP().toString().c_str(), 0x07E0);
  delay(800);
}

// ---------- 網路 ----------

// 抓第 p 頁畫面到 frame[]，成功回傳 true，並更新總頁數 / 停留時間 / 亮度
static bool fetchFrame(int p, uint32_t &holdMs) {
  HTTPClient http;
  String url = String(serverUrl) + "/frame?page=" + p;
  if (!http.begin(url)) return false;
  const char *keys[] = {"X-Pages", "X-Hold-Ms", "X-Brightness"};
  http.collectHeaders(keys, 3);
  http.setTimeout(6000);

  int code = http.GET();
  const size_t need = sizeof(frame);
  if (code != 200 || http.getSize() != (int)need) {
    Serial.printf("GET %s -> %d (size %d)\n", url.c_str(), code, http.getSize());
    http.end();
    return false;
  }

  // 先讀到暫存區，完整收到才覆蓋，避免畫面只更新一半
  static uint8_t buf[sizeof(frame)];
  WiFiClient *stream = http.getStreamPtr();
  size_t got = 0;
  uint32_t t0 = millis();
  while (got < need && millis() - t0 < 6000) {
    size_t avail = stream->available();
    if (avail) {
      got += stream->readBytes(buf + got, min(avail, need - got));
    } else {
      delay(1);
    }
  }
  if (got != need) {
    http.end();
    return false;
  }
  memcpy(frame, buf, need);  // ESP32 是 little-endian，與伺服器輸出的 RGB565 位元組順序一致

  pageCount = max(1L, http.header("X-Pages").toInt());
  holdMs = max(1000L, http.header("X-Hold-Ms").toInt());
  int b = http.header("X-Brightness").toInt();
  if (b > 0 && b != brightness) {
    brightness = b;
    display->setBrightness8(brightness);
  }
  http.end();
  return true;
}

// ---------- 按鈕 ----------

static bool pressed(int pin) {
  if (pin < 0) return false;
  static uint32_t last[48] = {0};
  if (digitalRead(pin) == LOW && millis() - last[pin] > 300) {
    last[pin] = millis();
    return true;
  }
  return false;
}

// ---------- 主程式 ----------

void setup() {
  Serial.begin(115200);
  setupDisplay();
  showText("SCOREBOARD", "booting...");
  loadSettings();
  setupWifi();
  if (PIN_BTN_NEXT >= 0) pinMode(PIN_BTN_NEXT, INPUT_PULLUP);
  if (PIN_BTN_PAUSE >= 0) pinMode(PIN_BTN_PAUSE, INPUT_PULLUP);
  Serial.printf("server: %s\n", serverUrl);
}

void loop() {
  if (pressed(PIN_BTN_NEXT)) {
    page = (page + 1) % pageCount;
    holdUntil = 0;
  }
  if (pressed(PIN_BTN_PAUSE)) {
    paused = !paused;
    page = shown;
  }

  if (millis() < holdUntil) {
    delay(20);
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    showText("WiFi LOST", "reconnecting");
    WiFi.reconnect();
    holdUntil = millis() + 5000;
    return;
  }

  uint32_t holdMs = 8000;
  if (fetchFrame(page, holdMs)) {
    fails = 0;
    shown = page;
    drawFrame();
    if (paused) {
      holdMs = min<uint32_t>(holdMs, 10000);  // 暫停時仍定期重抓同一頁，比分才會即時更新
    } else {
      page = (page + 1) % pageCount;
    }
    holdUntil = millis() + holdMs;
  } else {
    if (++fails >= FAILS_BEFORE_ERROR) showText("NO SERVER", serverUrl, 0xF800);
    holdUntil = millis() + 3000;
  }
}
