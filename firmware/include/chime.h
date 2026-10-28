#pragma once
#include <Arduino.h>

// 整點報時：伺服器在每次畫面回應的標頭告訴看板「還有幾毫秒要報時」，看板自己倒數後播放。
// 音檔從伺服器的 /chime.pcm 下載一次存在 PSRAM，版本（X-Chime-Ver）變了才重新下載。
// 沒有喇叭的板子（HAS_SPEAKER = 0）這些函式什麼都不做。

void chimeSetup();
// 每次成功抓到畫面時呼叫；沒有 X-Chime-Id 代表接下來一小時內沒有報時
void chimeOnHeaders(long inMs, const String &id, const String &ver, int volume);
// loop() 裡呼叫：需要時下載音檔、時間到就播放（播放在背景工作，不會卡住畫面）
void chimeLoop(const char *serverUrl);
