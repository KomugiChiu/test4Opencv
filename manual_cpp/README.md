# manual_cpp — C++ 版手動測試套件

Python `manual/*` 的 C++ 對等移植，6 項 `manifest_manual.yaml` 行為完全對齊。

## 對應表

| Python | C++ | 行為 |
|---|---|---|
| `run_manual_suite.py` | `src/manual_suite.cpp` → `manual_suite` | 總驅動：依序證據採集 → `ask_verdict(p/f/s)` → `report_manual.json` + `report_manual.xlsx` |
| `exposure_visual_check.py` | `src/exposure_check.cpp` → `exposure_check` | `AUTO_EXPOSURE 3/1` + `EXPOSURE` sweep，灰階 `mean/std` + `exp_manual_*.jpg` |
| `autofocus_visual_check.py` | `src/autofocus_check.cpp` → `autofocus_check` | `AUTOFOCUS/FOCUS/ZOOM` sweep，中心 ROI Laplacian `var` + `delta` + `FOCUS_*.jpg / ZOOM_*.jpg` |
| `white_balance_visual_check.py` | `src/white_balance_check.cpp` → `white_balance_check` | `AUTO_WB 0/1` + `WB_TEMPERATURE` sweep，`R/G/B` + `cast(R-B)` + `WB_TEMP_*.jpg` |
| `usb_unplug_reconnect_test.py` | `src/reconnect_test.cpp` → `reconnect_test` | 重連狀態機 `RECONNECTING→RECOVERING→CONNECTED→LOST`，`events.jsonl / summary.json` |
| `long_duration_stability` | `manual_suite.cpp:ev_long_run` | `--long-run MINUTES` 迴圈 + `/proc/self/status VmRSS` 採樣 |
| `device_index_physical_mapping` | `manual_suite.cpp:ev_device_mapping` | `glob /sys/class/video4linux/video*` + `VideoCapture::read()` 探測 |

## 建置

```bash
cmake -S manual_cpp -B manual_cpp/build -DCMAKE_PREFIX_PATH="$PWD/build"
cmake --build manual_cpp/build -j$(nproc)
```

依賴：`OpenCV >=5` (`core imgproc videoio`) + `yaml-cpp` (0.7)，`openpyxl` (僅 Excel 生成時委託 Python，若缺則僅產生 JSON)。

## 執行

```bash
# 列出項目
./manual_cpp/build/manual_suite --list
# 全量互動式（與 Python 版同，報告名加 _cpp 以避免覆蓋 Python 的 report_manual.json）
./manual_cpp/build/manual_suite -d /dev/video0 --evidence ./manual_evidence_cpp --report ./report/new/report_manual_cpp.json
# 單項非互動式（CI 用）
./manual_cpp/build/manual_suite -d 0 --item exposure_visual_check --answer p \
  --evidence ./report/2026-08-24/manual_evidence_cpp --report ./report/2026-08-24/report_manual_cpp.json

# 單獨 helper
./manual_cpp/build/exposure_check -d 0 sweep --values 50,100,200 --outdir ./exp_check
./manual_cpp/build/autofocus_check -d 0 focus --values 0,80,160,250 --outdir ./focus_check
./manual_cpp/build/white_balance_check -d 0 temp --values 2500,4000,5500 --outdir ./wb_check
./manual_cpp/build/reconnect_test --device /dev/video0 --max-duration 45 --outdir ./reconnect
# 便捷腳本（自動 N->/dev/videoN、自動建置）
./manual_cpp/run_test.sh --list
./manual_cpp/run_test.sh -d 0 --answer p --outdir ./report/2026-08-24
```

參數與 Python 版一致：`-d/--device` 支援 `N`→`/dev/videoN`、`--exposure-values`、`--focus-values`、`--wb-values`、`--reconnect-window`、`--long-run`、`--answer p/f/s`、`--no-excel`。

## 產物

與 Python 版同構（供 `generate_combined_report.py` 消費）：

```
<evidence>/exp_manual_*.jpg (5)
<evidence>/FOCUS_*.jpg (4) + ZOOM_*.jpg (3)
<evidence>/WB_TEMP_*.jpg (4)
<evidence>/reconnect/events.jsonl + summary.json
<report>/report_manual_cpp.json  {report_type, generated_at, opencv_version, environment, device, results[6]}  # 已加 _cpp 後綴，避免與 Python 的 report_manual.json 衝突
<report>/report_manual_cpp.xlsx  Summary (含 opencv_version/device) + Results
# evidence 預設 manual_evidence_cpp，Python 版為 manual_evidence，二者可並存於同一 <report_dir>/
```

`opencv_version` 來自 `CV_VERSION`，與 `manual/run_manual_suite.py` 新增欄位一致。

## 與 Python 版差異

|  | Python | C++ |
|---|---|---|
| 依賴 | `opencv-python` 4.5 / `yaml` `openpyxl` | `build/` 編譯出的 5.1.0-dev + `yaml-cpp`；Excel 透過委派 Python `openpyxl` 生成，無則僅 JSON |
| helper 呼叫 | `subprocess.run` + JSON 行解析 | 直接函式呼叫（`manual_suite` 內聯），`exposure_check` 等亦可獨立執行 |
| YAML | `PyYAML` | `yaml-cpp`；缺 `manifest_manual.yaml` 時回退硬編碼描述 |
| 影像計算 | `numpy` | `cv::meanStdDev` / `cv::Laplacian` / `cv::mean` 等價 |
