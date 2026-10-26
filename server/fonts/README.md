# 字型

預設會自動使用系統裡的點陣中文字型，Raspberry Pi / Debian / Ubuntu 安裝方式：

```bash
sudo apt install fonts-wqy-zenhei fonts-unifont
```

- 小字（12px）：文泉驛點陣正黑 `wqy-zenhei.ttc`（內嵌 12px 點陣）
- 大字（16px，隊名）：GNU Unifont `unifont.otf`

想要更漂亮的 12px 字型，可以把 [Fusion Pixel Font](https://github.com/TakWolf/fusion-pixel-font)（OFL 授權）
的 `fusion-pixel-12px-proportional-zh_hant.otf` 放在這個資料夾，程式會優先使用。

Windows / macOS 沒有上述字型時，可以把字型檔放到這裡，並在 `config.yaml` 的 `display.fonts` 指定路徑。
