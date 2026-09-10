# Camera Toolkit — Prebuilt Runtime (execute-only)

此目錄是預編譯包：OpenCV selfbuild + C++ 測試 binaries + test scripts。
**只能執行，不能重編**（無 `opencv_source_code/`、無 CMakeLists）。
要從源碼編譯請回 toolkit repo 跑 `make prebuild`。

## 0. 環境需求（目標機先裝，`install/` 本地跑可跳過）

```bash
sudo apt-get install -y libavcodec60 libavformat60 libavutil58 libswscale7 \
  libtiff6 libopenexr-3-1-30 libyaml-cpp0.8 python3-yaml python3-pip v4l-utils
pip3 install openpyxl   # 只要 xlsx 報告才需要；json/log 不用
```

aarch64 包只能跑在 arm64 板（或 x86 上用 `qemu-aarch64-static`  smoke）；
x86_64 包上 arm64 會直接報錯。

## 1. 開箱即跑（免設定，`PREBUILT_ROOT` 自動偵測）

總指揮（一鍵跑全套，無任何編譯選項；cpp 路徑全固定為包內 `bin/` + `lib/`）：

```bash
./run_test.sh --device /dev/video0                              # all = auto,auto-cpp,manual,manual-cpp,official+combined
./run_test.sh --device /dev/video0 --suites auto,manual-cpp --dry-run
./run_test.sh --suites official --filter '*videoio_v4l2*'       # 需先有 opencv_extra/testdata（§2）
./run_test.sh --suites auto --frames 60                         # 只要 Python 版（auto=py，auto-cpp=C++）
```

`auto` / `manual` 跑包內 `auto/*.py` / `manual/*.py`（需 `cv2+numpy`，
`run_test.sh` 啟動時自動 `pip install opencv-python-headless numpy` 補上；
注意測的是 pip 的 cv2，不是包內 selfbuild）。
`install_prebuilt.sh`（一律 `sudo`，root 也一樣）會先裝好：
`pip install opencv-python-headless numpy openpyxl`。

互動：直接跑 `./run_test.sh` 會依序問 `device / backend / suites`
（Enter = 預設），再問是否改進階參數（`frames/reconnect/long-run/answer/filter/outdir`）；
CLI 有給的項自動跳過不問；非 tty（CI/pipe）全用預設靜默跑。
cpp 路徑、`PREBUILT_ROOT`、testdata URL 等基礎設施是固定的，不問。

設定檔 `run_config.prebuilt.yaml`（與 `run_test.sh` 同目錄，含全部 per-run 預設）：
優先順序 **CLI > 互動輸入 > 此檔 > 內建**。只放會變的選項
（`device/backend/suites/frames/reconnect_window/long_run/answer/filter/outdir/fetch_testdata/console_output/combined_report`），
cpp 路徑故意不可配。寫壞的值會 WARN 並退回預設。

附帶：啟動時自動補 `openpyxl`（缺就 pip 裝，失敗則跳過 xlsx、json/log 照跑）；
official 的 gtest log 預設 live 印出（`--no-console-output` 可關）。

單跑各套件：

```bash
./scripts/run_test_auto.sh --device /dev/video0 --backend V4L2 --no-build
./scripts/run_test_manual.sh -d /dev/video0 --outdir ./rpt
```

`scripts/` 下的 wrapper 偵測到自己身處包內（`../bin/` 存在）會自動指向包內
binary + `lib/`，並跳過 `git/cmake/apt`。`--no-build` 可省略。
`setup_vars.sh` 是備用：`source ./scripts/setup_vars.sh` 會補 `LD_LIBRARY_PATH` +
`PREBUILT_ROOT`（cross 件靠 `$ORIGIN` RPATH，本來就不需要它）。

常用參數：`run_test_auto.sh` 吃 `--device/--backend/--frames/--width/--height/--fps/--outdir/--list-only`；
`run_test_manual.sh` 吃 `-d/--item/--answer p|f|s/--outdir/--list`。
產物：`report_cpp.json(+.xlsx)`、`report_manual_cpp.json(+.xlsx)`、`manual_evidence_cpp/`。

## 2. 官方 gtest（testdata 自動抓，包內不含）

選了 `official` 但 `opencv_extra/testdata` 缺失時，`run_test.sh` 會**自動抓**
（`git sparse-checkout`，需外網），不用手動跑 `install_prebuilt.sh`：

```bash
./run_test.sh --device /dev/video0 --suites official
# 缺 testdata → 自動抓 full（testdata/cv + testdata/highgui，~389M）→ 續跑

./run_test.sh --suites official --fetch-testdata slim   # 只抓 videoio 實際用量（~33M）
./run_test.sh --suites official --fetch-testdata skip   # 不抓，缺件直接 exit 2
```

```bash
# 任選其一：full 389M（含 cv/，過 preflight）/ slim ~33M（videoio 實際用量）
bash /path/to/install_prebuilt.sh --tarball <name>.tar.gz --prefix . --fetch-testdata full
# 或只要 official 跑得動，testdata 目錄結構對即可：
python3 ./scripts/run_official_videoio_test.py \
  -e ./opencv_extra -d /dev/video0 -f '*videoio_v4l2*' -o ./rpt
#   -e = 含 opencv_extra/testdata 的環境根目錄
#   -b = 另指 build dir（預設讀包內 bin/，免給）
#   不給 -d 時 v4l2 案例顯示 OK 但 0ms（靜默跳過，沒真測）
```

產物：`rpt/videoio_gtest.log` + `rpt/report_offical.xlsx`（檔名拼字沿用上游）。

## 3. 三區合併報告

```bash
python3 ./scripts/generate_combined_report.py \
  --auto ./rpt/report_cpp.json --manual ./rpt/report_manual_cpp.json \
  --official-log ./rpt/videoio_gtest.log --outdir ./rpt
# → ./rpt/combined_report.xlsx；exit 0=無 FAIL，1=有 FAIL
```

## 4. 疑難排解

| 現象 | 解法 |
|---|---|
| `ERROR: --no-build but binary missing` | 包沒解完整，重解 tarball |
| `ldd bin/... \| grep "not found"` | §0 的 apt libs 沒裝齊（版號要對： noble = `libavcodec60/tiff6/OpenEXR-3_1`） |
| `aarch64 package on x86_64 host` | 拿錯包，aarch64 包只能上 arm64 板 |
| absolute `/home/` RUNPATH 警告 | 忽略，`LD_LIBRARY_PATH` fallback 會蓋掉；有 `patchelf` 的 builder 已在打包時改寫 |
| 要 xlsx 卻沒產出 | 裝 `openpyxl`（§0）；json/log 不受影響 |

版本溯源見 `VERSION.json`（opencv commit / ffmpeg / arch / cross / 建置時間）。
