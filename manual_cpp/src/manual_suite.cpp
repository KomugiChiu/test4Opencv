// manual_suite.cpp - C++ port of manual/run_manual_suite.py
// Mirrors 6 manual items with OpenCV C++ API + evidence images
#include "manual_utils.hpp"
#include <opencv2/videoio.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/imgcodecs.hpp>
#include <yaml-cpp/yaml.h>
#include <filesystem>
#include <glob.h>
#include <fstream>
#include <cstdlib>
#include <unistd.h>
#include <iostream>
#include <sstream>
#include <iomanip>
#include <chrono>
#include <thread>
#include <map>
#include <set>
#include <regex>
#include <cstdlib>
#include <atomic>
#include <csignal>

namespace fs = std::filesystem;

static const std::vector<std::string> ITEMS_ORDER = {
    "device_index_physical_mapping",
    "exposure_visual_check",
    "autofocus_visual_check",
    "white_balance_visual_check",
    "real_usb_unplug_reconnect",
    "long_duration_stability"
};
static const std::set<std::string> REMOVED_ITEMS = {
    "multi_camera_physical_sync", "csi_camera_real_hardware"
};

struct Args {
    std::string device = "/dev/video0";
    std::string exposure_values = "50,100,200,400,800";
    std::string focus_values = "0,80,160,250";
    std::string wb_values = "2500,4000,5500,6500";
    double reconnect_window = 30;
    int long_run = 0;
    std::string evidence = "./manual_evidence_cpp";
    std::string report = "report/new/report_manual_cpp.json";
    std::string answer = "";
    std::string excel_dir = "report/new";
    bool no_excel = false;
    std::string item = "";
    bool list = false;
    std::string backend = "V4L2";
    int width = 0, height = 0;
};

void hr(const std::string& title="") {
    std::cout << "\n" << std::string(72,'=') << "\n";
    if (!title.empty()) std::cout << title << "\n" << std::string(72,'=') << "\n";
}

std::string get_opencv_version_cpp() { return CV_VERSION; }
std::string get_opencv_source_cpp() {
#ifdef OPENCV_SOURCE_LABEL
  // Compile-time label injected by CMake based on actual find_package result
  return OPENCV_SOURCE_LABEL;
#else
    const char* s = std::getenv("CPP_OPENCV_SOURCE");
    if (s && *s) return s;
    s = std::getenv("REPORT_OPENCV_SOURCE");
    if (s && *s) return s;
    return "apt";
#endif
}

std::string now_iso() {
    auto now = std::chrono::system_clock::now();
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    std::stringstream ss;
    ss << std::put_time(gmtime(&t), "%Y-%m-%dT%H:%M:%S+00:00");
    return ss.str();
}

std::string ask_verdict(const std::string& item, const std::string& auto_note, const std::string& forced) {
    std::cout << "\nAuto-measured evidence (will be written to note):\n" << auto_note << "\n";
    if (!forced.empty()) {
        std::string m = forced;
        std::transform(m.begin(), m.end(), m.begin(), ::tolower);
        std::string mapped = (m=="p"?"PASS":(m=="f"?"FAIL":"SKIP"));
        std::cout << "[non-interactive] auto verdict = " << mapped << "\n";
        return mapped;
    }
    while (true) {
        std::cout << "\n[" << item << "] Your verdict? (p=PASS / f=FAIL / s=SKIP / Enter=SKIP): " << std::flush;
        std::string raw;
        if (!std::getline(std::cin, raw)) {
            std::cout << "  [EOF -> SKIP]\n";
            return "SKIP";
        }
        std::string s=raw; s.erase(0,s.find_first_not_of(" \t\r\n")); s.erase(s.find_last_not_of(" \t\r\n")+1);
        std::transform(s.begin(), s.end(), s.begin(), ::tolower);
        if (s=="p"||s=="pass") return "PASS";
        if (s=="f"||s=="fail") return "FAIL";
        if (s==""||s=="s"||s=="skip") return "SKIP";
        std::cout << "please enter p / f / s\n";
    }
}

// ---------- manifest ----------
std::map<std::string, std::string> load_manifest(const std::string& path) {
    std::map<std::string,std::string> out;
    try {
        YAML::Node node = YAML::LoadFile(path);
        for (auto it: node) {
            std::string ref = it["test_ref"].as<std::string>();
            std::string desc = it["description"] ? it["description"].as<std::string>() : "";
            out[ref]=desc;
        }
    } catch(...) {
        // fallback hardcoded
        out["device_index_physical_mapping"]="確認 OpenCV VideoCapture index / 裝置路徑，真的對應到你以為的那顆實體攝影機";
        out["exposure_visual_check"]="目視確認 CAP_PROP_AUTO_EXPOSURE / CAP_PROP_EXPOSURE 切換後，畫面亮度是否真的隨之改變";
        out["autofocus_visual_check"]="目視確認 CAP_PROP_AUTOFOCUS / FOCUS / ZOOM / PAN / TILT 等機械相關屬性是否真的有物理動作";
        out["white_balance_visual_check"]="目視確認白平衡相關屬性(WHITE_BALANCE_BLUE_U/RED_V, AUTO_WB, WB_TEMPERATURE)是否讓畫面色彩看起來正確";
        out["real_usb_unplug_reconnect"]="驗證真實 USB 拔插情境下，ROS2 node/測試程式的斷線重連邏輯真的能恢復";
        out["long_duration_stability"]="長時間（例如 24 小時以上）穩定性觀察，確認沒有記憶體洩漏、buffer 延遲累積、意外斷線等長跑才會浮現的問題";
    }
    return out;
}

std::string find_manifest() {
    std::vector<std::string> cands = {
        "manifest_manual.yaml",
        "../manual/manifest_manual.yaml",
        "camera_toolkit/manual/manifest_manual.yaml",
        std::string(std::getenv("HOME")?std::getenv("HOME"):"")+"/Downloads/komugi/ros2_opencv/camera_toolkit/manual/manifest_manual.yaml"
    };
    // also try relative to binary location
    for (auto &p: cands) if (fs::exists(p)) return fs::canonical(p).string();
    // fallback to toolkit location
    std::string toolkit = "camera_toolkit/manual/manifest_manual.yaml";
    if (fs::exists(toolkit)) return toolkit;
    if (fs::exists("manual/manifest_manual.yaml")) return "manual/manifest_manual.yaml";
    return "manifest_manual.yaml";
}

// ---------- device mapping ----------
std::pair<std::string,std::string> ev_device_mapping(const Args& a) {
    std::stringstream ss;
    ss << "Device node mapping:\n";
    std::vector<std::tuple<std::string,std::string,std::string>> cand;
    glob_t g; glob("/sys/class/video4linux/video*",0,nullptr,&g);
    for (size_t i=0;i<g.gl_pathc;++i) {
        std::string path = g.gl_pathv[i];
        std::string node = "/dev/" + fs::path(path).filename().string();
        std::string name="?";
        std::ifstream f(path+"/name");
        if (f) std::getline(f,name);
        cv::VideoCapture cap(node, cv::CAP_V4L2);
        bool opened = cap.isOpened();
        bool ok_frame=false;
        if (opened) { cv::Mat frm; ok_frame=cap.read(frm) && !frm.empty(); }
        cap.release();
        std::string kind = (opened && ok_frame) ? "CAPTURE" : "not-capturable";
        cand.emplace_back(node,name,kind);
        char buf[256]; snprintf(buf,sizeof(buf),"  %-14s %-38s %s\n", node.c_str(), name.c_str(), kind.c_str());
        ss << buf;
    }
    globfree(&g);
    std::string usable;
    for (auto &c: cand) if (std::get<2>(c)=="CAPTURE") { if(!usable.empty()) usable+=","; usable+=std::get<0>(c); }
    ss << "capture-capable nodes: " << usable;
    std::string note = ss.str() + " | target=" + a.device;
    hr("[1/6] device_index_physical_mapping");
    std::cout << note << "\n";
    std::string verdict = ask_verdict("device_index_physical_mapping", note, a.answer);
    return {verdict, note};
}

// ---------- exposure ----------
std::pair<std::string,std::string> ev_exposure(const Args& a) {
    hr("[2/6] exposure_visual_check");
    fs::create_directories(a.evidence);
    auto cap = manual::open_cam(a.device, a.backend, a.width, a.height);
    if (!cap.isOpened()) {
        std::string note = "target="+a.device+"; cannot open device";
        return {ask_verdict("exposure_visual_check", note, a.answer), note};
    }
    // sweep
    auto vals = manual::parse_values(a.exposure_values);
    std::stringstream json;
    json << "[";
    // base auto brightness
    cap.set(cv::CAP_PROP_AUTO_EXPOSURE, 3);
    manual::settle(cap,8);
    auto base = manual::measure_brightness(cap,12,"");
    json << "{\"mode\":\"AUTO(base)\",\"requested\":\"-\",\"brightness_mean\":"<< std::fixed<<std::setprecision(1)<<base.mean<<",\"frame_std\":"<<base.stddev<<"}";
    // manual sweep
    cap.set(cv::CAP_PROP_AUTO_EXPOSURE, 1);
    for (double v: vals) {
        cap.set(cv::CAP_PROP_EXPOSURE, v);
        double got = cap.get(cv::CAP_PROP_EXPOSURE);
        manual::settle(cap,8);
        std::string save = (fs::path(a.evidence)/("exp_manual_"+std::to_string((int)v)+".jpg")).string();
        auto m = manual::measure_brightness(cap,12,save);
        double ae = cap.get(cv::CAP_PROP_AUTO_EXPOSURE);
        json << ",{\"mode\":\"MANUAL\",\"requested\":\""<<v<<"\",\"brightness_mean\":"<<m.mean<<",\"frame_std\":"<<m.stddev<<",\"get_AUTO_EXPOSURE\":"<<ae<<",\"get_EXPOSURE\":"<<got<<"}";
        std::cout << "set(EXPOSURE="<<v<<") -> get="<<got<<" brightness="<<m.mean<<" (+/-"<<m.stddev<<")\n";
    }
    cap.set(cv::CAP_PROP_AUTO_EXPOSURE, 3);
    json << "]";
    std::string summ = json.str();
    std::cout << "\n== Summary ==\n" << summ << "\n snapshots in " << a.evidence << "\n";
    std::string note = "target="+a.device+"; sweep="+a.exposure_values+"; summary="+summ;
    return {ask_verdict("exposure_visual_check", note, a.answer), note};
}

// ---------- autofocus ----------
std::pair<std::string,std::string> ev_autofocus(const Args& a) {
    hr("[3/6] autofocus_visual_check");
    fs::create_directories(a.evidence);
    auto cap = manual::open_cam(a.device, a.backend, a.width, a.height);
    if (!cap.isOpened()) {
        std::string note="target="+a.device+"; cannot open";
        return {ask_verdict("autofocus_visual_check", note, a.answer), note};
    }
    auto focus_vals = manual::parse_values(a.focus_values);
    std::vector<double> zoom_vals = {100,150,200};
    // helper lambda sweep
    auto sweep = [&](int prop, const std::vector<double>& vals, const std::string& label)->std::string {
        std::stringstream sj; sj<<"[";
        cv::Mat ref; cap.read(ref);
        cv::Mat ref_gray; if(!ref.empty()) cv::cvtColor(ref, ref_gray, cv::COLOR_BGR2GRAY);
        double initial = cap.get(prop);
        for (size_t i=0;i<vals.size();++i) {
            double v=vals[i];
            bool ok = cap.set(prop, v);
            double got = cap.get(prop);
            manual::settle(cap,6);
            std::string save = (fs::path(a.evidence)/(label+"_"+std::to_string((int)v)+".jpg")).string();
            auto m = manual::measure_sharpness(cap, ref_gray, 10, save);
            std::cout << "set("<<label<<"="<<v<<") -> "<<ok<<", get="<<got<<" sharpness="<<m.lapvar<<" delta="<<m.delta<<"\n";
            sj << (i?",":"") << "{\""<<label<<"\":"<<v<<",\"set_returned\":"<<(ok?"true":"false")<<",\"get_readback\":"<<got<<",\"sharpness_lapvar\":"<<m.lapvar<<",\"delta_vs_ref\":"<<m.delta<<"}";
        }
        cap.set(prop, initial);
        sj << "]";
        return sj.str();
    };
    cap.set(cv::CAP_PROP_AUTOFOCUS, 0);
    std::string s1 = sweep(cv::CAP_PROP_FOCUS, focus_vals, "FOCUS");
    cap.set(cv::CAP_PROP_AUTOFOCUS, 1);
    std::string s2 = sweep(cv::CAP_PROP_ZOOM, zoom_vals, "ZOOM");
    std::string note = "target="+a.device+"; FOCUS sweep="+s1+"; ZOOM sweep="+s2+"; PAN/TILT needs separate confirmation (get stuck at 0 = unsupported)";
    return {ask_verdict("autofocus_visual_check", note, a.answer), note};
}

// ---------- white balance ----------
std::pair<std::string,std::string> ev_white_balance(const Args& a) {
    hr("[4/6] white_balance_visual_check");
    fs::create_directories(a.evidence);
    auto cap = manual::open_cam(a.device, a.backend, a.width, a.height);
    if (!cap.isOpened()) {
        std::string note="target="+a.device+"; cannot open";
        return {ask_verdict("white_balance_visual_check", note, a.answer), note};
    }
    auto vals = manual::parse_values(a.wb_values);
    cap.set(cv::CAP_PROP_AUTO_WB, 0);
    std::stringstream sj; sj<<"[";
    for (size_t i=0;i<vals.size();++i) {
        double v=vals[i];
        bool ok = cap.set(cv::CAP_PROP_WB_TEMPERATURE, v);
        double got = cap.get(cv::CAP_PROP_WB_TEMPERATURE);
        manual::settle(cap,6);
        std::string save = (fs::path(a.evidence)/("WB_TEMP_"+std::to_string((int)v)+".jpg")).string();
        auto m = manual::measure_rgb(cap,12,save);
        std::cout << "set(WB_TEMP="<<v<<") -> "<<ok<<", get="<<got<<" R="<<m.r<<" G="<<m.g<<" B="<<m.b<<" cast="<<m.cast<<"\n";
        sj << (i?",":"") << "{\"WB_TEMP\":"<<v<<",\"set_returned\":"<<(ok?"true":"false")<<",\"get_readback\":"<<got<<",\"R\":"<<m.r<<",\"G\":"<<m.g<<",\"B\":"<<m.b<<",\"cast(R-B)\":"<<m.cast<<",\"snapshot\":\"WB_TEMP_"<<(int)v<<".jpg\"}";
    }
    sj << "]";
    cap.set(cv::CAP_PROP_AUTO_WB, 1);
    std::string summ = sj.str();
    std::string note = "target="+a.device+"; WB_TEMP sweep="+summ;
    return {ask_verdict("white_balance_visual_check", note, a.answer), note};
}

// ---------- reconnect ----------
std::pair<std::string,std::string> ev_reconnect(const Args& a) {
    hr("[5/6] real_usb_unplug_reconnect  (interactive window)");
    std::cout << "Next " << a.reconnect_window << " seconds:\n"
              << "  1. After stream_established >>> UNPLUG the USB cable of " << a.device << "\n"
              << "  2. After disconnect_detected wait 5-10s, then replug\n"
              << "  3. Done once you see recovered\n\n"
              << "--- live status ---\n";
    fs::create_directories(fs::path(a.evidence)/"reconnect");
    std::string outdir = (fs::path(a.evidence)/"reconnect").string();
    // Use the Python helper via subprocess if available, else native C++ loop
    // Native C++ reconnect loop
    auto start = std::chrono::steady_clock::now();
    auto elapsed = [&]()->double{
        return std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    };
    std::vector<std::map<std::string,std::string>> events;
    std::vector<std::map<std::string,std::string>> disconnects;
    int exceptions=0;
    int fail_thresh=5, good_needed=3;
    double retry=1.0;
    cv::VideoCapture cap;
    int fails=0, good=0, attempts=0;
    double last_good = elapsed();
    std::string state="RECONNECTING";
    auto log = [&](const std::string& ev, const std::string& kv=""){
        std::cout << "    | ["<< std::fixed<<std::setprecision(2)<<elapsed()<<"s] "<<ev<<" "<<kv<<"\n";
    };
    log("state from_=null to=RECONNECTING");
    double pending_detect_lat=0, pending_first_fail=0;
    bool has_pending=false;
    int frames_ok=0;
    while (elapsed() < a.reconnect_window) {
        if (state=="RECONNECTING" || state=="LOST") {
            state="RECONNECTING"; attempts++;
            log("open_attempt n="+std::to_string(attempts));
            cap = manual::open_cam(a.device, a.backend);
            if (!cap.isOpened()) { state="LOST"; std::this_thread::sleep_for(std::chrono::duration<double>(retry)); continue; }
            state="RECOVERING"; good=0; continue;
        }
        cv::Mat f; bool ok=false;
        try { ok=cap.read(f) && !f.empty(); } catch(...) { ok=false; exceptions++; log("read_exception"); }
        if (ok) {
            fails=0; good++; last_good=elapsed();
            if (state=="RECOVERING") {
                if (good>=good_needed) {
                    state="CONNECTED";
                    if (has_pending) {
                        double downtime = elapsed() - pending_first_fail;
                        std::map<std::string,std::string> rec;
                        rec["n"]=std::to_string(disconnects.size()+1);
                        rec["detect_latency_s"]=std::to_string(pending_detect_lat);
                        rec["downtime_s"]=std::to_string(downtime);
                        rec["attempts"]=std::to_string(attempts);
                        disconnects.push_back(rec);
                        log("recovered downtime="+std::to_string(downtime));
                        std::cout << "\n>>> Stream recovered! Thanks - waiting for timer... <<<\n\n";
                        has_pending=false;
                    } else {
                        log("stream_established size="+std::to_string(f.cols)+"x"+std::to_string(f.rows));
                        std::cout << "\n>>> NOW UNPLUG the USB cable! <<<\n\n";
                    }
                    attempts=0;
                } else log("recovering_frame good="+std::to_string(good));
            } else {
                frames_ok++; if(frames_ok%100==0) log("alive frames="+std::to_string(frames_ok));
            }
            continue;
        }
        if (state=="RECOVERING") { log("recover_failed_frame"); cap.release(); state="RECONNECTING"; std::this_thread::sleep_for(std::chrono::duration<double>(retry)); continue; }
        fails++;
        if (state=="CONNECTED" && fails>=fail_thresh) {
            double lat = elapsed()-last_good;
            log("disconnect_detected latency="+std::to_string(lat));
            std::cout << "\n>>> Disconnect detected! Wait 5-10s then replug USB <<<\n\n";
            pending_detect_lat=lat; pending_first_fail=elapsed(); has_pending=true;
            state="RECONNECTING";
        } else if (state!="CONNECTED") { state="LOST"; std::this_thread::sleep_for(std::chrono::duration<double>(retry)); }
    }
    cap.release();
    // write summary.json
    std::ofstream sj(outdir+"/summary.json");
    sj << "{\n  \"device\":\""<<a.device<<"\",\n  \"backend\":\""<<a.backend<<"\",\n  \"duration_s\":"<<elapsed()<<",\n  \"frames_captured\":"<<frames_ok<<",\n  \"disconnect_count\":"<<disconnects.size()<<",\n  \"disconnects\":[";
    for(size_t i=0;i<disconnects.size();++i){ if(i) sj<<","; sj<<"{}"; }
    sj << "],\n  \"exception_count\":"<<exceptions<<"\n}\n";
    std::ofstream ej(outdir+"/events.jsonl");
    ej << "{\"event\":\"state\",\"t\":0}\n";
    std::string note = "target="+a.device+"; window="+std::to_string(a.reconnect_window)+"s; disconnects=[]; exceptions="+std::to_string(exceptions);
    return {ask_verdict("real_usb_unplug_reconnect", note, a.answer), note};
}

// ---------- long run ----------
std::pair<std::string,std::string> ev_long_run(const Args& a) {
    hr("[6/6] long_duration_stability");
    if (a.long_run<=0) {
        std::string note="--long-run minutes not given; skipping long-run observation";
        std::cout << note << "\n";
        return {"SKIP", note};
    }
    auto cap = manual::open_cam(a.device, a.backend);
    if (!cap.isOpened()) return {"SKIP","cannot open device"};
    auto deadline = std::chrono::steady_clock::now() + std::chrono::minutes(a.long_run);
    int fails=0;
    std::vector<std::map<std::string,double>> samples;
    auto last_log = std::chrono::steady_clock::now();
    while (std::chrono::steady_clock::now() < deadline) {
        cv::Mat f; bool ok=cap.read(f); if(!ok) fails++;
        if (std::chrono::duration<double>(std::chrono::steady_clock::now()-last_log).count() >= 60) {
            std::ifstream st("/proc/self/status");
            std::string line; int rss=0;
            while(std::getline(st,line)) if(line.rfind("VmRSS:",0)==0){ std::stringstream ss(line.substr(6)); ss>>rss; break; }
            double tmin = std::chrono::duration<double>(std::chrono::steady_clock::now() - (deadline - std::chrono::minutes(a.long_run))).count()/60.0;
            samples.push_back({{"t_min",tmin},{"rss_kb",(double)rss}});
            std::cout << "  ["<<tmin<<"min] RSS="<<rss<<"KB fails="<<fails<<"\n";
            last_log = std::chrono::steady_clock::now();
        }
    }
    cap.release();
    std::stringstream ss; ss<<"dur="<<a.long_run<<"min, samples=[";
    for(size_t i=0;i<samples.size();++i){ if(i) ss<<","; ss<<"{}"; }
    ss<<"], fails="<<fails;
    std::string note=ss.str();
    return {ask_verdict("long_duration_stability", note, a.answer), note};
}

// ---------- excel ----------
bool write_excel(const std::vector<std::map<std::string,std::string>>& results,
                 const std::string& path, const std::string& generated_at,
                 const std::string& opencv_ver, const std::string& opencv_src, const std::string& device) {
    // Try Python openpyxl delegation
    std::string py = "import openpyxl, re, os, sys, json\n"
        "from openpyxl import Workbook\n"
        "from openpyxl.styles import Alignment, Border, Font, PatternFill, Side\n"
        "from openpyxl.utils import get_column_letter\n"
        "results=json.loads(open(sys.argv[1]).read())\n"
        "path=sys.argv[2]; gen=sys.argv[3]; ocv=sys.argv[4]; src=sys.argv[5]; dev=sys.argv[6]\n"
        "wb=Workbook(); ws=wb.active; ws.title='Summary'\n"
        "hdr_fill=PatternFill('solid',fgColor='1F4E78')\n"
        "counts={}\n"
        "for r in results: counts[r['status']]=counts.get(r['status'],0)+1\n"
        "rows=[['OpenCV Camera Manual Test Report',''],['',''],['generated_at',gen],['opencv_version',ocv],['opencv_source',src],['device',dev],['total items',len(results)],['PASS',counts.get('PASS',0)],['FAIL',counts.get('FAIL',0)],['SKIP',counts.get('SKIP',0)],['NOT_RUN',counts.get('NOT_RUN',0)]]\n"
        "for r in rows: ws.append(r)\n"
        "ws['A1'].font=Font(bold=True,size=14)\n"
        "thin=Border(*[Side(style='thin',color='BFBFBF')]*4)\n"
        "for i in range(3,len(rows)+1):\n"
        "    ws.cell(row=i,column=1).font=Font(bold=True); ws.cell(row=i,column=1).border=thin; ws.cell(row=i,column=2).border=thin\n"
        "ws.column_dimensions['A'].width=24; ws.column_dimensions['B'].width=60\n"
        "ws2=wb.create_sheet('Results')\n"
        "ws2.append(['test_ref','description','Status','note (evidence)','checked_at'])\n"
        "for r in results: ws2.append([r.get('test_ref',''),r.get('description',''),r.get('status',''),r.get('note',''),r.get('checked_at') or '-'])\n"
        "for c in ws2[1]: c.fill=hdr_fill; c.font=Font(bold=True,color='FFFFFF'); c.border=thin\n"
        "fills={'PASS':PatternFill('solid',fgColor='C6EFCE'),'FAIL':PatternFill('solid',fgColor='FFC7CE'),'SKIP':PatternFill('solid',fgColor='D9D9D9'),'NOT_RUN':PatternFill('solid',fgColor='F2F2F2')}\n"
        "fonts={'PASS':Font(color='006100'),'FAIL':Font(color='9C0006',bold=True),'SKIP':Font(color='404040'),'NOT_RUN':Font(color='808080')}\n"
        "for row in ws2.iter_rows(min_row=2):\n"
        "    st=row[2].value\n"
        "    if st in fills: row[2].fill, row[2].font = fills[st], fonts[st]\n"
        "    for c in row: c.border=thin; c.alignment=Alignment(vertical='top',wrap_text=(c.column==4))\n"
        "ws2.freeze_panes='A2'; ws2.auto_filter.ref=ws2.dimensions\n"
        "for i,w in enumerate((34,46,10,90,26),1): ws2.column_dimensions[get_column_letter(i)].width=w\n"
        "import os; os.makedirs(os.path.dirname(os.path.abspath(path)),exist_ok=True)\n"
        "wb.save(path)\n";
    const char* tmpd = std::getenv("TMPDIR");
    std::string tmp_json = std::string(tmpd && *tmpd ? tmpd : "/tmp") +
        "/manual_cpp_results_" + std::to_string(::getpid()) + ".json";
    {
        std::ofstream f(tmp_json);
        f<<"[";
        for(size_t i=0;i<results.size();++i){
            if(i) f<<",";
            f<<"{\"test_ref\":\""<<results[i].at("test_ref")<<"\",\"description\":\"\",\"status\":\""<<results[i].at("status")<<"\",\"note\":\"";
            std::string note=results[i].at("note");
            for(char c: note){ if(c=='\"') f<<"\\\""; else if(c=='\n') f<<"\\n"; else f<<c; }
            f<<"\",\"checked_at\":\""<<results[i].at("checked_at")<<"\"}";
        }
        f<<"]";
    }
    std::string src_local = get_opencv_source_cpp();
    std::string cmd = "python3 - \""+tmp_json+"\" \""+path+"\" \""+generated_at+"\" \""+opencv_ver+"\" \""+src_local+"\" \""+device+"\" << 'PYEOF'\n"+py+"\nPYEOF\n";
    int rc = std::system(cmd.c_str());
    std::error_code ec;
    fs::remove(tmp_json, ec); // best-effort temp cleanup
    return rc==0 && fs::exists(path);
}

// ---------- main ----------
int main(int argc, char* argv[]) {
    std::cout<<std::unitbuf; // live verdicts/prompts under pipes
    Args a;
    for(int i=1;i<argc;++i){
        std::string arg=argv[i];
        auto nxt=[&]()->std::string{ return (i+1<argc)? argv[++i] : ""; };
        if(arg=="--list") a.list=true;
        else if(arg=="--item") a.item=nxt();
        else if(arg=="-d"||arg=="--device") a.device=nxt();
        else if(arg=="--backend") a.backend=nxt();
        else if(arg=="--exposure-values") a.exposure_values=nxt();
        else if(arg=="--focus-values") a.focus_values=nxt();
        else if(arg=="--wb-values") a.wb_values=nxt();
        else if(arg=="--reconnect-window") a.reconnect_window=std::stod(nxt());
        else if(arg=="--long-run") a.long_run=std::stoi(nxt());
        else if(arg=="--evidence") a.evidence=nxt();
        else if(arg=="--report") a.report=nxt();
        else if(arg=="--answer") a.answer=nxt();
        else if(arg=="--excel-dir") a.excel_dir=nxt();
        else if(arg=="--no-excel") a.no_excel=true;
        else if(arg=="--help"||arg=="-h"){
            std::cout<<"Usage: manual_suite [--device /dev/video0] [--item ...] [--answer p/f/s] [--evidence DIR] [--report PATH] [--excel-dir DIR]\n";
            return 0;
        }
    }
    std::string manifest_path = find_manifest();
    auto manifest = load_manifest(manifest_path);
    std::cout<<"manifest: "<<manifest_path<<"\n";
    if(a.list){
        for(auto &k: ITEMS_ORDER) std::cout<<"["<<k<<"] "<<manifest[k]<<"\n";
        return 0;
    }
    // device existence check
    {
        std::string dev=a.device;
        std::string node;
        if(dev.rfind("/dev/",0)==0) node=dev;
        else if(manual::is_digit_string(dev)) node="/dev/video"+dev;
        if(!node.empty() && !fs::exists(node)){
            std::cerr<<"[ERROR] target device '"<<a.device<<"' ("<<node<<") does not exist.\n";
            glob_t g; glob("/sys/class/video4linux/video*",0,nullptr,&g);
            if(g.gl_pathc>0){ std::cerr<<"Available nodes:\n"; for(size_t i=0;i<g.gl_pathc;++i) std::cerr<<"  "<<g.gl_pathv[i]<<"\n"; }
            else std::cerr<<"No /dev/video* nodes\n";
            globfree(&g);
            return 2;
        }
    }
    fs::create_directories(a.evidence);
    fs::create_directories(fs::path(a.report).parent_path());
    // load existing
    std::map<std::string,std::map<std::string,std::string>> existing;
    if(fs::exists(a.report)){
        try{ YAML::Node n=YAML::LoadFile(a.report); } catch(...){
            std::ifstream f(a.report); std::string s((std::istreambuf_iterator<char>(f)),{}); // try json
            // naive: look for results
        }
        // simple json parse for existing results if present
        std::ifstream f(a.report); std::string content((std::istreambuf_iterator<char>(f)),{});
        // we keep existing empty for C++ simplicity (merge handled elsewhere)
    }
    std::vector<std::map<std::string,std::string>> results;
    auto save_now = [&](const std::vector<std::map<std::string,std::string>>& extra)->std::map<std::string,std::map<std::string,std::string>>{
        std::map<std::string,std::map<std::string,std::string>> merged;
        for(auto &ref: ITEMS_ORDER) merged[ref]={{"test_ref",ref},{"status","NOT_RUN"},{"note",""},{"checked_at",""}};
        for(auto &kv: existing) if(REMOVED_ITEMS.find(kv.first)==REMOVED_ITEMS.end()) merged[kv.first]=kv.second;
        for(auto &r: extra) merged[r.at("test_ref")]=r;
        std::string opencv_ver = get_opencv_version_cpp();
        std::string opencv_src = get_opencv_source_cpp();
        std::map<std::string,std::string> env; env["opencv_version"]=opencv_ver; env["opencv_source"]=opencv_src;
        std::ofstream out(a.report);
        out<<"{\n  \"report_type\": \"manual\",\n  \"generated_at\": \""<<now_iso()<<"\",\n  \"opencv_version\": \""<<opencv_ver<<"\",\n  \"opencv_source\": \""<<opencv_src<<"\",\n  \"environment\": {\"opencv_version\":\""<<opencv_ver<<"\",\"opencv_source\":\""<<opencv_src<<"\"},\n  \"device\": \""<<a.device<<"\",\n  \"results\": [\n";
        size_t idx=0;
        for(auto &ref: ITEMS_ORDER){
            auto &m=merged[ref];
            if(idx++) out<<",\n";
            out<<"    {\"test_ref\":\""<<m["test_ref"]<<"\",\"description\":\""<<manifest[ref]<<"\",\"status\":\""<<m["status"]<<"\",\"note\":\"";
            for(char c: m["note"]){ if(c=='\"') out<<"\\\""; else if(c=='\n') out<<"\\n"; else out<<c; }
            out<<"\",\"checked_at\":\""<<m["checked_at"]<<"\"}";
        }
        out<<"\n  ]\n}\n";
        if(!a.no_excel){
            std::vector<std::map<std::string,std::string>> vec;
            for(auto &ref: ITEMS_ORDER) vec.push_back(merged[ref]);
            write_excel(vec, (fs::path(a.excel_dir)/"report_manual_cpp.xlsx").string(), now_iso(), opencv_ver, opencv_src, a.device);
        }
        return merged;
    };

    std::vector<std::string> order = a.item.empty() ? ITEMS_ORDER : std::vector<std::string>{a.item};
    std::vector<std::map<std::string,std::string>> collected;
    for(auto &ref: order){
        if(manifest.find(ref)==manifest.end()) continue;
        std::pair<std::string,std::string> res;
        if(ref=="device_index_physical_mapping") res=ev_device_mapping(a);
        else if(ref=="exposure_visual_check") res=ev_exposure(a);
        else if(ref=="autofocus_visual_check") res=ev_autofocus(a);
        else if(ref=="white_balance_visual_check") res=ev_white_balance(a);
        else if(ref=="real_usb_unplug_reconnect") res=ev_reconnect(a);
        else if(ref=="long_duration_stability") res=ev_long_run(a);
        else continue;
        std::map<std::string,std::string> m;
        m["test_ref"]=ref; m["description"]=manifest[ref]; m["status"]=res.first; m["note"]=res.second; m["checked_at"]=now_iso();
        collected.push_back(m);
        save_now(collected);
    }
    auto final_merged = save_now(collected);
    int done=0, pass=0, fail=0;
    for(auto &kv: final_merged){ if(kv.second["status"]!="NOT_RUN") done++; if(kv.second["status"]=="PASS") pass++; if(kv.second["status"]=="FAIL") fail++; }
    hr("MANUAL SUITE SUMMARY");
    std::cout<<"  executed this run : "<<collected.size()<<"\n";
    std::cout<<"  total recorded    : "<<done<<"/"<<ITEMS_ORDER.size()<<"  (PASS="<<pass<<", FAIL="<<fail<<")\n";
    std::cout<<"  report            : "<<a.report<<"\n";
    std::cout<<"  excel             : "<<a.excel_dir<<"/report_manual_cpp.xlsx\n";
    std::cout<<"  evidence          : "<<a.evidence<<"/\n";
    std::cout<<"  opencv_version    : "<<get_opencv_version_cpp()<<"\n";
    return fail?1:0;
}
