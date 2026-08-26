# auto_cpp — C++ 版自動化 API 涵蓋率測試

Python `auto/opencv_camera_api_test.py` 的 C++ 改寫，A~G 七組檢查對等移植。

## 建置

```bash
cmake -S auto_cpp -B auto_cpp/build -DCMAKE_PREFIX_PATH="$PWD/build"
cmake --build auto_cpp/build -j$(nproc)
```

## 執行

```bash
./auto_cpp/build/opencv_camera_api_test_cpp \
    --device /dev/video0 --backend V4L2 --frames 30 \
    [--outdir ./report/new] [--list-only] [--no-full-sweep]
```

Exit codes: 0 全綠 / 1 有 FAIL / 2 無相機。

## 與 Python 版的差異

| | auto/ (Python) | auto_cpp/ (C++) |
|---|---|---|
| OpenCV | pip 5.0.0 | source build 或 apt |
| 屬性表來源 | dir(cv2) | Header 即時萃取（每次 cmake） |
| 報告 | md/json/xlsx | json |
| 涵蓋率 | core/full 三級 | core |
