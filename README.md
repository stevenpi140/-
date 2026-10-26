# 點陣比分看板（中職／MLB／NBA／TPBL／PLG）

用 ESP32 + HUB75 全彩 LED 點陣面板做的桌上比分看板。它會顯示今天你追蹤的球隊有哪些比賽，比賽進行中每 15 秒更新一次比分。

![預覽](docs/preview.png)

> 上圖是用 `--demo` 假資料產生的 LED 模擬圖，只用來看版面，不是真實比分。

## 架構

```
 ┌──────────── 伺服器（樹莓派／家裡電腦／NAS，常開） ────────────┐
 │  抓資料：中職官網、MLB Stats API、ESPN(NBA)、TPBL API、PLG 官網  │
 │  整理成統一格式 → 依追蹤清單篩選 → 用點陣中文字型畫成 128×64 圖 │
 │  GET /frame?page=N  → 16KB RGB565 原始畫面                       │
 └───────────────────────────────┬──────────────────────────────────┘
                                 │ 區網 HTTP
 ┌───────────────────────────────▼──────────────────────────────────┐
 │  ESP32（MatrixPortal S3）→ HUB75 → 兩片 64×64 LED 面板（128×64） │
 └──────────────────────────────────────────────────────────────────┘
```

**為什麼要另外跑一個伺服器？** 繁體中文字型有好幾 MB，ESP32 放不下完整字集；五個聯盟的資料來源有的是 JSON、有的要解析 HTML、有的要先拿驗證 token，在 ESP32 上寫會很痛苦，官網一改版還得重新燒錄。改成在伺服器端把畫面畫好再傳過去，韌體只要負責「抓圖、顯示」，之後要修正資料來源或調整版面，都只要改伺服器的 Python。

## 硬體清單

| 項目 | 推薦規格 | 數量 | 參考價（NT$） | 備註 |
|---|---|---|---|---|
| LED 點陣面板 | **P3 64×64 全彩 HUB75（HUB75E，1/32 掃）** | 2 | 每片 350–700 | 單片 19.2×19.2 cm，兩片並排成 **38.4×19.2 cm、128×64 點**。蝦皮／淘寶搜尋「P3 全彩 LED 模組 64x64 HUB75」 |
| 控制板 | **Adafruit MatrixPortal S3**（ESP32-S3） | 1 | 700–900 | 直接插在面板的 HUB75 排針上，免接線；板上有兩顆按鍵 |
| 電源 | 5V **8A 以上**變壓器（DC 5.5mm 或電源供應器） | 1 | 300–500 | 一片 64×64 全白約 4A。看板大多是黑底，實際用電少很多，但仍要保留餘裕 |
| 排線／電源線 | 面板通常會附 HUB75 排線＋電源線 | — | — | 兩片串接要用一條 HUB75 排線（第一片 OUT → 第二片 IN） |
| 伺服器 | Raspberry Pi Zero 2 W／Pi 4，或任何常開的電腦 | 1 | 600–2000 | 開發階段先用自己的電腦就可以 |
| 選配 | 壓克力黑色濾光板、3D 列印外殼、M3 磁鐵螺絲 | — | — | 黑色半透明壓克力蓋在面板前，畫面對比會好很多 |

**其他尺寸的面板：**

- **P2.5 64×64**：一片 16×16 cm，兩片並排 32×16 cm，點距更細、更精緻。
- **P4 64×32**：一片 25.6×12.8 cm，實體比較大，但兩片只有 128×32 點，中文只能排兩行。目前的版面是照 128×64 設計的，用 128×32 要另外調整 `render.py`。

**不用 MatrixPortal 的話：** 也可以用一般 ESP32 DevKit 加杜邦線，或 Brian Lough 的 ESP32 Trinity 板，韌體請選 `esp32dev` 這個 env，腳位見下方說明。

### 接線

1. 兩片面板背面箭頭朝同一個方向。左邊那片的 **HUB75 IN** 接 MatrixPortal，左邊的 **OUT** 用排線接右邊那片的 **IN**。
2. 面板的電源線（紅 5V、黑 GND）接到 5V 變壓器。
3. MatrixPortal S3 用 USB-C 供電，它和面板透過 HUB75 排線共地。
4. **64×64 面板需要 E 位址線**：MatrixPortal S3 背面有「Address E」跳線焊點，要依 [Adafruit 的說明](https://learn.adafruit.com/adafruit-matrixportal-s3) 焊接，否則畫面只會亮一半或重複。
5. 一般 ESP32 的接線用函式庫的預設腳位：R1 25、G1 26、B1 27、R2 14、G2 12、B2 13、A 23、B 19、C 5、D 17、**E 18**、LAT 4、OE 15、CLK 16。

## 軟體

### 1. 伺服器（先在自己的電腦跑）

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml                   # 編輯你要追蹤的球隊

# 字型（Raspberry Pi / Ubuntu）
sudo apt install fonts-wqy-zenhei fonts-unifont
```

先不用硬體，看看畫面長什麼樣子：

```bash
python -m scoreboard preview --demo     # 假資料，看版面
python -m scoreboard preview            # 抓今天的真實資料
# 輸出在 preview/ 資料夾：page0_overview.png、page1_game.png ...
```

確認各聯盟資料來源能不能抓：

```bash
python -m scoreboard probe              # 全部聯盟
python -m scoreboard probe cpbl --date 2026-10-26
# 原始回應會存在 probe/，官網改版時拿來對照欄位
```

啟動伺服器：

```bash
python -m scoreboard serve --port 8080
```

接著用瀏覽器開 `http://localhost:8080/`，就能看到目前輪播的每一頁（每 10 秒自動更新）。

| 網址 | 用途 |
|---|---|
| `/` | 網頁預覽所有頁面 |
| `/frame?page=N` | 給 ESP32 用的 RGB565 原始畫面（標頭帶 `X-Pages`、`X-Hold-Ms`、`X-Brightness`） |
| `/api/games` | 今天的比賽（JSON） |
| `/api/status` | 各聯盟最後更新時間與錯誤訊息 |
| `POST /api/refresh` | 立刻重抓 |

**放到樹莓派常駐**（systemd）：

```ini
# /etc/systemd/system/scoreboard.service
[Unit]
Description=Scoreboard
After=network-online.target

[Service]
WorkingDirectory=/home/pi/scoreboard/server
ExecStart=/home/pi/scoreboard/server/.venv/bin/python -m scoreboard serve --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now scoreboard
```

### 2. 韌體（ESP32）

1. 安裝 [VS Code + PlatformIO](https://platformio.org/install/ide?install=vscode)。
2. 打開 `firmware/` 資料夾。面板尺寸不同的話，先改 `include/config.h`。
3. 接上 MatrixPortal S3，執行 `pio run -e matrixportal_s3 -t upload`（一般 ESP32 用 `-e esp32dev`）。
4. 第一次開機時，面板會顯示 `Scoreboard-XXXX`。用手機連上這個 WiFi，在跳出的頁面選擇家裡的 WiFi，並填入**伺服器網址**（例如 `http://192.168.1.100:8080`）。
5. 之後想重新設定，就在開機時按住 **BOOT** 鍵。

MatrixPortal S3 板上的按鍵：**UP** 切到下一頁，**DOWN** 暫停輪播，固定顯示目前這場（比分仍會持續更新）。

## 畫面說明

- **總覽頁**：今天所有追蹤中的比賽，每列一場。左邊色條代表聯盟，接著是客隊、比分（未開打就顯示開打時間）、主隊、狀態（`7下`、`Q3`、`終`）。
- **單場頁**：第一列是聯盟、賽事名稱（總冠軍賽G6、世界大賽G3）和場地；中間是兩隊與大字比分。上面是客隊、下面是主隊，和官方記分板的順序一樣。
  - 棒球比賽中：會顯示局數、出局燈、壘包，進攻方比分旁有黃色小三角形。
  - 未開打：會顯示開打時間、倒數時間和先發投手。
  - 終場：輸球那隊會變暗。
- **沒比賽時**：顯示大時鐘和日期。
- 夜間（預設 23:30–07:00）自動調暗；有比賽進行中時則維持正常亮度。

## 資料來源

| 聯盟 | 來源 | 穩定度 |
|---|---|---|
| MLB | `statsapi.mlb.com`（MLB 官方 Stats API） | 高，免金鑰 |
| NBA | ESPN `site.api.espn.com` scoreboard | 高，非官方但已經用了很多年 |
| 中職 | 中職官網 `cpbl.com.tw` 的 `/schedule/getgamedatas`、`/box/getlive` | 中，非公開介面，需要 token |
| TPBL | `api.tpbl.basketball`（官網前端使用的 API） | 中，未公開文件化 |
| PLG | `pleagueofficial.com` 賽程頁 HTML ＋ `/api/boxscore.preciser.php` | 中低，解析 HTML，官網改版就要調整 |

所有來源都是公開網頁背後的資料，請保持合理的更新頻率（預設比賽中 15 秒、平時 10 分鐘），不要調得太頻繁。

> ⚠️ **中職、TPBL、PLG 的解析器還沒有連到真實網站驗證過。** 開發環境連不到這些網站，欄位名稱是參考社群開源專案的整理寫的。第一次使用時請先跑 `python -m scoreboard probe`，如果某個聯盟抓不到或欄位不對，`probe/` 資料夾裡的原始回應可以拿來修正 `server/scoreboard/leagues/` 底下對應的檔案。MLB 和 NBA 用的是格式穩定、文件齊全的 API。

## 測試

```bash
cd server && python -m pytest -q
```

## 疑難排解

| 狀況 | 處理 |
|---|---|
| 面板只亮一半、或上下重複 | 64×64 面板的 E 腳沒接好：MatrixPortal 要焊 Address E 跳線，一般 ESP32 要接 GPIO18 |
| 開機全黑或花屏 | 打開 `config.h` 的 `PANEL_DRIVER_FM6126A` |
| 顏色或左右錯位 | 切換 `PANEL_CLKPHASE` |
| 面板顯示 `NO SERVER` | 確認伺服器網址、電腦防火牆有開 8080 埠，以及 ESP32 和伺服器在同一個網段 |
| 某聯盟沒有資料 | 開 `/api/status` 看錯誤訊息，再跑 `python -m scoreboard probe <聯盟>` |
| 隊名縮寫不對 | 在 `config.yaml` 的 `aliases` 裡覆寫，或修改 `scoreboard/teams.py` |
