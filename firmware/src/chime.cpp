#include "chime.h"

#include "config.h"

#if HAS_SPEAKER

#include <HTTPClient.h>
#include <driver/i2s.h>

#include "es8311.h"

static const i2s_port_t PORT = I2S_NUM_1;
static ES8311 codec;
static bool ready = false;

static int16_t *pcm = nullptr;  // 單聲道樣本，放在 PSRAM
static size_t pcmSamples = 0;
static String pcmVer;  // 目前 PSRAM 裡音檔的版本

static String wantVer;       // 伺服器上音檔的版本
static String pendingId;     // 等待中的報時編號
static String lastPlayedId;  // 已經播過的報時編號（整點後 30 秒內伺服器會重複告知，靠這個避免重播）
static uint32_t dueAt = 0;
static bool due = false;
static int volume = 70;
static volatile bool playing = false;

void chimeSetup() {
  pinMode(PIN_AUDIO_PA, OUTPUT);
  digitalWrite(PIN_AUDIO_PA, LOW);  // 不播放時關掉功放，喇叭才不會有底噪

  i2s_config_t c = {};
  c.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  c.sample_rate = CHIME_SAMPLE_RATE;
  c.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  c.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
  c.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  c.dma_buf_count = 8;
  c.dma_buf_len = 1000;  // 8 x 1000 frames ≈ 170ms 緩衝，WiFi 忙的時候也不會斷音
  c.use_apll = false;
  c.tx_desc_auto_clear = true;
  c.mclk_multiple = I2S_MCLK_MULTIPLE_256;  // MCLK = 256 x 48kHz = 12.288MHz，ES8311 設定是用這個比例

  i2s_pin_config_t pins = {};
  pins.mck_io_num = PIN_I2S_MCLK;
  pins.bck_io_num = PIN_I2S_BCLK;
  pins.ws_io_num = PIN_I2S_LRC;
  pins.data_out_num = PIN_I2S_DOUT;
  pins.data_in_num = I2S_PIN_NO_CHANGE;

  if (i2s_driver_install(PORT, &c, 0, nullptr) != ESP_OK || i2s_set_pin(PORT, &pins) != ESP_OK) {
    Serial.println("chime: I2S init failed");
    return;
  }
  if (!codec.begin(PIN_CODEC_SDA, PIN_CODEC_SCL, 400000)) {
    Serial.println("chime: ES8311 not found");
    return;
  }
  codec.setVolume(volume);
  ready = true;
  Serial.println("chime: ready");
}

void chimeOnHeaders(long inMs, const String &id, const String &ver, int vol) {
  if (ver.length()) wantVer = ver;
  if (vol >= 0) volume = constrain(vol, 0, 100);
  if (id.isEmpty() || inMs < 0) {
    if (!playing) due = false;
    return;
  }
  if (id == lastPlayedId) return;
  pendingId = id;
  dueAt = millis() + (uint32_t)inMs;  // 每次回應都重新校正倒數
  due = true;
}

static bool download(const char *serverUrl) {
  HTTPClient http;
  String url = String(serverUrl) + "/chime.pcm";
  if (!http.begin(url)) return false;
  const char *keys[] = {"X-Chime-Ver"};
  http.collectHeaders(keys, 1);
  http.setTimeout(10000);
  int code = http.GET();
  int size = http.getSize();
  if (code != 200 || size <= 0 || size > CHIME_MAX_BYTES) {
    Serial.printf("chime: GET %s -> %d (size %d)\n", url.c_str(), code, size);
    http.end();
    return false;
  }
  uint8_t *buf = (uint8_t *)ps_malloc(size);
  if (!buf) {
    http.end();
    return false;
  }
  WiFiClient *stream = http.getStreamPtr();
  size_t got = 0;
  uint32_t t0 = millis();
  while (got < (size_t)size && millis() - t0 < 30000) {
    size_t avail = stream->available();
    if (avail) {
      got += stream->readBytes(buf + got, min(avail, (size_t)size - got));
    } else {
      delay(1);
    }
  }
  String ver = http.header("X-Chime-Ver");
  http.end();
  if (got != (size_t)size) {
    free(buf);
    return false;
  }
  free(pcm);
  pcm = (int16_t *)buf;
  pcmSamples = size / 2;
  pcmVer = ver.length() ? ver : wantVer;
  Serial.printf("chime: downloaded %u bytes (%s)\n", (unsigned)size, pcmVer.c_str());
  return true;
}

static void playTask(void *) {
  digitalWrite(PIN_AUDIO_PA, HIGH);
  vTaskDelay(pdMS_TO_TICKS(30));  // 等功放穩定，開頭才不會被吃掉
  static int16_t out[512];       // 256 個雙聲道 frame（單聲道複製到左右聲道）
  for (size_t i = 0; i < pcmSamples;) {
    size_t n = min((size_t)256, pcmSamples - i);
    for (size_t k = 0; k < n; k++) out[2 * k] = out[2 * k + 1] = pcm[i + k];
    size_t written;
    i2s_write(PORT, out, n * 4, &written, portMAX_DELAY);
    i += n;
  }
  vTaskDelay(pdMS_TO_TICKS(250));  // 讓 DMA 裡剩下的聲音播完
  i2s_zero_dma_buffer(PORT);
  digitalWrite(PIN_AUDIO_PA, LOW);
  playing = false;
  vTaskDelete(nullptr);
}

void chimeLoop(const char *serverUrl) {
  if (!ready || playing) return;
  static uint32_t lastTry = 0;
  if (wantVer.length() && wantVer != pcmVer && millis() - lastTry > 30000) {
    lastTry = millis();
    download(serverUrl);  // 失敗的話 30 秒後再試
  }
  if (!due || (int32_t)(millis() - dueAt) < 0) return;
  due = false;
  lastPlayedId = pendingId;
  if (!pcm || (int32_t)(millis() - dueAt) > 60000) return;  // 沒有音檔，或已經晚太久就不播了
  codec.setVolume(volume);
  playing = true;
  // 優先權比 loop() 高，loop() 在抓畫面時聲音也不會斷；i2s_write 等 DMA 時會讓出 CPU
  xTaskCreatePinnedToCore(playTask, "chime", 4096, nullptr, 3, nullptr, 1);
}

#else

void chimeSetup() {}
void chimeOnHeaders(long, const String &, const String &, int) {}
void chimeLoop(const char *) {}

#endif
