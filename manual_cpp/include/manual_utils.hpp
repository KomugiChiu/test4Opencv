#pragma once
// Common helpers for manual_cpp suite - mirrors Python manual/* helpers
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/videoio.hpp>
#include <string>
#include <vector>
#include <cmath>
#include <algorithm>

namespace manual {

inline bool is_digit_string(const std::string& s) {
    if (s.empty()) return false;
    for (char c : s) if (!std::isdigit(static_cast<unsigned char>(c))) return false;
    return true;
}

inline std::string resolve_device_for_capture(const std::string& raw) {
    // Returns original if not pure digits; caller will decide int vs string
    return raw;
}

inline cv::VideoCapture open_cam(const std::string& device, const std::string& backend,
                                 int width=0, int height=0, int fps=0) {
    int bid = cv::CAP_V4L2;
    if (backend == "ANY") bid = cv::CAP_ANY;
    else if (backend == "GSTREAMER") bid = cv::CAP_GSTREAMER;
    else if (backend == "FFMPEG") bid = cv::CAP_FFMPEG;
    cv::VideoCapture cap;
    if (is_digit_string(device)) {
        cap.open(std::stoi(device), bid);
    } else {
        cap.open(device, bid);
    }
    if (!cap.isOpened()) return cap;
    if (width > 0) cap.set(cv::CAP_PROP_FRAME_WIDTH, width);
    if (height > 0) cap.set(cv::CAP_PROP_FRAME_HEIGHT, height);
    if (fps > 0) cap.set(cv::CAP_PROP_FPS, fps);
    return cap;
}

inline void settle(cv::VideoCapture& cap, int n=8) {
    cv::Mat f;
    for (int i=0;i<n;++i) cap.read(f);
}

struct BrightnessResult {
    double mean = 0;
    double stddev = 0;
    cv::Mat snap;
};

inline BrightnessResult measure_brightness(cv::VideoCapture& cap, int frames=12,
                                           const std::string& save_path="") {
    std::vector<double> means;
    cv::Mat snap;
    for (int i=0;i<frames;++i) {
        cv::Mat f;
        if (!cap.read(f) || f.empty()) continue;
        cv::Mat gray;
        cv::cvtColor(f, gray, cv::COLOR_BGR2GRAY);
        cv::Scalar m, sd;
        cv::meanStdDev(gray, m, sd);
        means.push_back(m[0]);
        if (i == frames/2) snap = f.clone();
    }
    BrightnessResult r;
    if (!means.empty()) {
        double sum=0; for(double v:means) sum+=v;
        r.mean = sum/means.size();
        double var=0; for(double v:means) var+=(v-r.mean)*(v-r.mean);
        r.stddev = std::sqrt(var/means.size());
        r.snap = snap;
        if (!save_path.empty() && !snap.empty()) cv::imwrite(save_path, snap);
    }
    return r;
}

inline double sharpness_laplacian(const cv::Mat& frame) {
    int h=frame.rows, w=frame.cols;
    double cx=0.5;
    int rw = static_cast<int>(w*cx), rh = static_cast<int>(h*cx);
    int x0 = (w-rw)/2, y0=(h-rh)/2;
    cv::Rect roi(x0,y0,rw,rh);
    cv::Mat crop = frame(roi);
    cv::Mat gray; cv::cvtColor(crop, gray, cv::COLOR_BGR2GRAY);
    cv::Mat lap; cv::Laplacian(gray, lap, CV_64F);
    cv::Scalar m, sd; cv::meanStdDev(lap, m, sd);
    return sd[0]*sd[0]; // variance
}

struct SharpnessResult {
    double lapvar = 0;
    double delta = 0;
    cv::Mat snap;
};

inline SharpnessResult measure_sharpness(cv::VideoCapture& cap, const cv::Mat& ref_gray,
                                         int frames=10, const std::string& save_path="") {
    std::vector<double> laps, diffs;
    cv::Mat snap;
    for (int i=0;i<frames;++i) {
        cv::Mat f; if (!cap.read(f) || f.empty()) continue;
        laps.push_back(sharpness_laplacian(f));
        if (!ref_gray.empty()) {
            cv::Mat g; cv::cvtColor(f,g,cv::COLOR_BGR2GRAY);
            cv::Mat diff; cv::absdiff(g, ref_gray, diff);
            diffs.push_back(cv::mean(diff)[0]);
        }
        if (i==frames/2) snap=f.clone();
    }
    SharpnessResult r;
    if (!laps.empty()) { double s=0; for(double v:laps) s+=v; r.lapvar=s/laps.size(); }
    if (!diffs.empty()) { double s=0; for(double v:diffs) s+=v; r.delta=s/diffs.size(); }
    r.snap=snap;
    if (!save_path.empty() && !snap.empty()) cv::imwrite(save_path, snap);
    return r;
}

struct RGBResult {
    double r=0,g=0,b=0;
    double cast=0;
    cv::Mat snap;
};

inline RGBResult measure_rgb(cv::VideoCapture& cap, int frames=12, const std::string& save_path="") {
    std::vector<double> rs,gs,bs;
    cv::Mat snap;
    for (int i=0;i<frames;++i) {
        cv::Mat f; if(!cap.read(f) || f.empty()) continue;
        cv::Scalar mean = cv::mean(f);
        bs.push_back(mean[0]); gs.push_back(mean[1]); rs.push_back(mean[2]);
        if (i==frames/2) snap=f.clone();
    }
    RGBResult res;
    if (!rs.empty()) {
        double sr=0,sg=0,sb=0; for(size_t i=0;i<rs.size();++i){sr+=rs[i];sg+=gs[i];sb+=bs[i];}
        res.r=sr/rs.size(); res.g=sg/gs.size(); res.b=sb/bs.size();
        res.cast=res.r-res.b;
        res.snap=snap;
        if (!save_path.empty() && !snap.empty()) cv::imwrite(save_path, snap);
    }
    return res;
}

inline std::vector<double> parse_values(const std::string& s) {
    std::vector<double> out;
    std::stringstream ss(s);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
        if (tok.empty()) continue;
        try { out.push_back(std::stod(tok)); } catch(...) {}
    }
    return out;
}

inline std::string get_opencv_version() {
    return CV_VERSION;
}

} // namespace manual
