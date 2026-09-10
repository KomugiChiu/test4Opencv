// manual_cpp - C++ driver for the 6-item manual camera test suite.
//
// Collects objective evidence automatically (brightness / sharpness /
// color-cast metrics + snapshots) and asks the operator for the verdict.
// Writes report_manual_cpp.json compatible with generate_combined_report.py.

#include <opencv2/videoio.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/imgcodecs.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <unistd.h>

namespace fs = std::filesystem;
using cv::Mat;

static const char* PASS = "PASS";
static const char* FAIL = "FAIL";
static const char* SKIP = "SKIP";

bool g_color = true;
std::string g_answer;                 // "" = interactive
std::string g_outdir = "./report/new";
std::string g_device = "/dev/video0";
int g_reconnect_window = 30;
int g_long_run_min = 0;

std::string paint(const char* code, const std::string& t) {
  return g_color ? "\033[" + std::string(code) + "m" + t + "\033[0m" : t;
}
std::string green(const std::string& t) { return paint("32", t); }
std::string red(const std::string& t)   { return paint("31", t); }
std::string yellow(const std::string& t){ return paint("33", t); }
std::string bold(const std::string& t)  { return paint("1", t); }

std::string now_utc() {
  std::time_t t = std::time(nullptr);
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&t));
  return buf;
}

std::string escape_json(const std::string& in) {
  std::string out;
  for (char ch : in) {
    switch (ch) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (static_cast<unsigned char>(ch) < 0x20) out += "?";
        else out += ch;
    }
  }
  return out;
}

struct VideoNode { std::string node, name; };

std::vector<VideoNode> video_nodes() {
  std::vector<VideoNode> out;
  std::error_code ec;
  for (auto& e : fs::directory_iterator("/sys/class/video4linux")) {
    VideoNode n;
    n.node = "/dev/" + e.path().filename().string();
    std::ifstream f((e.path() / "name").string());
    std::getline(f, n.name);
    out.push_back(n);
  }
  std::sort(out.begin(), out.end(),
            [](auto& a, auto& b) { return a.node < b.node; });
  return out;
}

bool open_capture(cv::VideoCapture& cap, const std::string& dev) {
  try {
    if (!dev.empty() && dev.find_first_not_of("0123456789") == std::string::npos)
      cap.open(std::stoi(dev), cv::CAP_V4L2);
    else
      cap.open(dev, cv::CAP_V4L2);
  } catch (...) {
    return false;
  }
  return cap.isOpened();
}

double gray_mean(const Mat& f) {
  Mat g;
  cvtColor(f, g, cv::COLOR_BGR2GRAY);
  return cv::mean(g)[0];
}

double sharpness(const Mat& f) {          // Laplacian variance, center ROI
  int h = f.rows, w = f.cols;
  Mat roi = f(cv::Range(h / 4, h * 3 / 4), cv::Range(w / 4, w * 3 / 4));
  Mat g;
  cvtColor(roi, g, cv::COLOR_BGR2GRAY);
  Mat dst;
  cv::Laplacian(g, dst, CV_64F);
  double sum = 0, sumsq = 0;
  for (int y = 0; y < dst.rows; ++y)
    for (int x = 0; x < dst.cols; ++x) {
      double v = dst.at<double>(y, x);
      sum += v; sumsq += v * v;
    }
  double n = static_cast<double>(dst.total());
  double mean = sum / n;
  return sumsq / n - mean * mean;
}

void settle(cv::VideoCapture& cap, int n) {
  Mat tmp;
  for (int i = 0; i < n; ++i) cap.read(tmp);
}

double safe_get_focus(cv::VideoCapture& cap) {
  try {
    double v = cap.get(cv::CAP_PROP_FOCUS);
    return std::isnan(v) ? 0.0 : v;
  } catch (...) {
    return 0.0;
  }
}

std::string snap_path(const std::string& name) {
  fs::create_directories(g_outdir + "/manual_evidence_cpp");
  return g_outdir + "/manual_evidence_cpp/" + name;
}

// ------------------------------------------------------------------ report
struct ItemResult {
  std::string test_ref, description, status, note, checked_at;
};

class Report {
 public:
  std::vector<std::string> order;
  std::map<std::string, std::string> descriptions;
  std::vector<ItemResult> results;

  void record(const std::string& ref, const std::string& status,
              const std::string& note) {
    for (auto& r : results)
      if (r.test_ref == ref) {
        r.status = status; r.note = note; r.checked_at = now_utc();
        return;
      }
    results.push_back({ref, descriptions.count(ref) ? descriptions.at(ref) : "",
                       status, note, now_utc()});
  }
  void record(const ItemResult& r) {
    for (auto& x : results)
      if (x.test_ref == r.test_ref) { x = r; return; }
    ItemResult c = r;
    if (c.description.empty())
      c.description = descriptions.count(c.test_ref)
                          ? descriptions.at(c.test_ref) : "";
    if (c.checked_at.empty()) c.checked_at = now_utc();
    results.push_back(c);
  }

  void save(const std::string& path) {
    std::map<std::string, ItemResult> merged;
    for (const auto& ref : order)
      merged[ref] = {ref,
                     descriptions.count(ref) ? descriptions.at(ref) : "",
                     "NOT_RUN", "", ""};
    for (auto& r : results) merged[r.test_ref] = r;

    std::ofstream f(path);
    f << "{\n  \"report_type\": \"manual_cpp\",\n"
      << "  \"generated_at\": \"" << now_utc() << "\",\n"
      << "  \"meta\": {\"tool\": \"manual_cpp\", \"device\": \""
      << escape_json(g_device) << "\"},\n"
      << "  \"results\": [\n";
    bool first = true;
    for (const auto& ref : order) {
      auto& r = merged[ref];
      if (!first) f << ",\n";
      f << "    {\"group\": \"" << ref << "\", "
        << "\"api\": \"operator verdict\", "
        << "\"status\": \"" << r.status << "\", "
        << "\"message\": \"" << escape_json(r.note) << "\"}";
      first = false;
    }
    f << "\n";
    f << "  ]\n}\n";
  }
};

static Report g_report;
static const char* ITEM_ORDER[] = {
    "device_index_physical_mapping",
    "exposure_visual_check",
    "autofocus_visual_check",
    "white_balance_visual_check",
    "real_usb_unplug_reconnect",
    "long_duration_stability",
};
static const int ITEM_N = sizeof(ITEM_ORDER) / sizeof(ITEM_ORDER[0]);

std::string ask_verdict(const std::string& item, const std::string& note) {
  std::cout << "\nAuto-measured evidence (written to note):\n"
            << note << "\n";
  if (!g_answer.empty()) {
    std::string m = g_answer == "p" ? PASS
                  : g_answer == "f" ? FAIL : SKIP;
    std::cout << "[non-interactive] verdict = " << m << "\n";
    return m;
  }
  while (true) {
    std::cout << "\n[" << item << "] Your verdict? (p=PASS / f=FAIL / "
              << "s=SKIP / Enter=SKIP): " << std::flush;
    std::string raw;
    try {
      std::getline(std::cin, raw);
    } catch (...) {
      return SKIP;
    }
    if (std::cin.eof()) return SKIP;
    // trim
    while (!raw.empty() && (raw.back() == '\r' || raw.back() == ' '))
      raw.pop_back();
    if (raw == "p" || raw == "pass") return PASS;
    if (raw == "f" || raw == "fail") return FAIL;
    if (raw.empty() || raw == "s" || raw == "skip") return SKIP;
    std::cout << "please answer p / f / s\n";
  }
}

void hr(const std::string& t) {
  std::cout << "\n" << bold(std::string(70, '=')) << "\n"
            << bold(t) << "\n" << bold(std::string(70, '=')) << "\n";
}

// ------------------------------------------------------- item 1: mapping
ItemResult run_device_mapping() {
  hr("[1/6] device_index_physical_mapping");
  std::ostringstream note;
  note << "Device node mapping:";
  for (auto& n : video_nodes()) {
    cv::VideoCapture cap;
    bool cap_ok = open_capture(cap, n.node);
    Mat f;
    bool frame_ok = cap_ok && cap.read(f) && !f.empty();
    cap.release();
    note << "\n  " << n.node << "  " << n.name << "  "
         << (frame_ok ? "CAPTURE" : "not-capturable");
    std::cout << "  " << n.node << "  " << n.name
              << (frame_ok ? "  [CAPTURE]" : "  [not-capturable]") << "\n";
  }
  ItemResult r{"device_index_physical_mapping",
               "Confirm index/node to physical camera mapping", "", "",
               now_utc()};
  r.note = escape_json(note.str());
  r.status = ask_verdict(r.test_ref, note.str());
  return r;
}

// ------------------------------------------------------ item 2: exposure
ItemResult run_exposure() {
  hr("[2/6] exposure_visual_check");
  cv::VideoCapture cap;
  if (!open_capture(cap, g_device)) {
    ItemResult r{"exposure_visual_check",
                 "Exposure sweep brightness response", SKIP,
                 "cannot open " + g_device, now_utc()};
    g_report.record(r);
    return r;
  }

  auto last_frame = [&](cv::VideoCapture& c) -> Mat {
    Mat f;
    if (!c.read(f)) f = Mat();
    return f;
  };
  std::vector<double> values = {50, 100, 200, 400, 800};
  cap.set(cv::CAP_PROP_AUTO_EXPOSURE, 3.0);      // auto
  settle(cap, 8);
  Mat base_frame = last_frame(cap);
  double base = base_frame.empty() ? -1 : gray_mean(base_frame);
  std::cout << "AUTO base brightness=" << base << "\n";
  cap.set(cv::CAP_PROP_AUTO_EXPOSURE, 1.0);      // manual
  std::ostringstream note;
  note << "brightness sweep: ";
  for (double v : values) {
    cap.set(cv::CAP_PROP_EXPOSURE, v);
    settle(cap, 6);
    Mat f;
    if (!cap.read(f)) continue;
    double b = gray_mean(f);
    note << v << ":" << static_cast<int>(b) << " ";
    std::string p = snap_path("exp_manual_" + std::to_string((int)v) + ".jpg");
    imwrite(p, f);
    std::cout << "  EXPOSURE=" << v << " brightness=" << b
              << " -> " << p << "\n";
  }
  cap.set(cv::CAP_PROP_AUTO_EXPOSURE, 3.0);      // restore auto
  ItemResult r{"exposure_visual_check", "", "", "", now_utc()};
  r.note = escape_json(note.str());
  r.status = ask_verdict(r.test_ref, note.str());
  cap.release();
  return r;
}

// ------------------------------------------------------ item 3: autofocus
ItemResult run_autofocus() {
  hr("[3/6] autofocus_visual_check");
  cv::VideoCapture cap;
  if (!open_capture(cap, g_device)) {
    ItemResult r{"autofocus_visual_check",
                 "Focus/zoom sharpness response", SKIP,
                 "cannot open " + g_device, now_utc()};
    g_report.record(r);
    return r;
  }
  double orig_focus = safe_get_focus(cap);
  cap.set(cv::CAP_PROP_AUTOFOCUS, 0.0);          // manual focus
  std::ostringstream note;
  note << "focus sweep (sharpness=laplacian var): ";
  for (double v : {0.0, 80.0, 160.0, 250.0}) {
    cap.set(cv::CAP_PROP_FOCUS, v);
    settle(cap, 6);
    Mat f;
    if (!cap.read(f)) continue;
    double sh = sharpness(f);
    note << v << ":" << static_cast<int>(sh) << " ";
    std::string p = snap_path("focus_" + std::to_string((int)v) + ".jpg");
    imwrite(p, f);
    std::cout << "  FOCUS=" << v << " sharpness=" << sh
              << " -> " << p << "\n";
  }
  cap.set(cv::CAP_PROP_AUTOFOCUS, 1.0);
  cap.set(cv::CAP_PROP_FOCUS, orig_focus);
  ItemResult r{"autofocus_visual_check",
               "Focus/zoom sharpness response", "", "", now_utc()};
  r.note = escape_json(note.str());
  r.status = ask_verdict(r.test_ref, note.str());
  cap.release();
  return r;
}

// --------------------------------------------------- item 4: white balance
ItemResult run_whitebalance() {
  hr("[4/6] white_balance_visual_check");
  cv::VideoCapture cap;
  if (!open_capture(cap, g_device)) {
    ItemResult r{"white_balance_visual_check",
                 "White-balance color cast response", SKIP,
                 "cannot open " + g_device, now_utc()};
    g_report.record(r);
    return r;
  }
  cap.set(cv::CAP_PROP_AUTO_WB, 0.0);
  std::ostringstream note;
  note << "WB_TEMP sweep cast(R-B): ";
  for (double t : {2500.0, 4000.0, 5500.0, 6500.0}) {
    cap.set(cv::CAP_PROP_WB_TEMPERATURE, t);
    settle(cap, 6);
    Mat f;
    if (!cap.read(f)) continue;
    double b = cv::mean(f)[0], g = cv::mean(f)[1], rr = cv::mean(f)[2];
    double cast = rr - b;
    note << t << ":" << static_cast<int>(cast) << " ";
    std::string pth =
        snap_path("wb_" + std::to_string((int)t) + ".jpg");
    imwrite(pth, f);
    std::cout << "  WB_TEMP=" << t << " R=" << rr << " G=" << g
              << " B=" << b << " cast=" << cast << " -> " << pth << "\n";
  }
  cap.set(cv::CAP_PROP_AUTO_WB, 1.0);
  ItemResult r{"white_balance_visual_check",
               "White-balance color cast response", "", "", now_utc()};
  r.note = escape_json(note.str());
  r.status = ask_verdict(r.test_ref, note.str());
  cap.release();
  return r;
}

// ----------------------------------------------------- item 5: reconnect
ItemResult run_reconnect(int window_sec) {
  hr("[5/6] real_usb_unplug_reconnect (interactive window)");
  std::cout << "Within " << window_sec << "s:\n"
            << "  1. after stream_established -> UNPLUG the camera\n"
            << "  2. after disconnect_detected wait 5-10s\n"
            << "  3. replug; done when recovered\n\n--- live ---\n";

  cv::VideoCapture cap;
  if (!open_capture(cap, g_device)) {
    ItemResult r{"real_usb_unplug_reconnect",
                 "Real USB unplug/reconnect recovery", SKIP,
                 "cannot open " + g_device, now_utc()};
    g_report.record(r);
    return r;
  }
  auto t0 = std::chrono::steady_clock::now();
  auto elapsed = [&] {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0)
        .count();
  };
  Mat f;
  int consecutive_fail = 0, ok_frames = 0;
  double last_good = 0, detect_latency = -1, downtime_start = 0;
  int disconnects = 0;
  bool connected = false;
  std::ostringstream note;

  while (elapsed() < window_sec) {
    bool ok = cap.read(f) && !f.empty();
    if (ok) {
      ++ok_frames;
      last_good = elapsed();
      if (!connected && consecutive_fail == 0) {
        connected = true;
        if (disconnects == 0) {
          std::cout << "[live] stream_established size=" << f.cols
                    << "x" << f.rows << "\n";
          std::cout << "\n>>> NOW UNPLUG the USB cable! <<<\n\n";
        } else {
          ++disconnects;
          double dt = elapsed() - downtime_start;
          std::cout << "[live] recovered #" << disconnects
                    << " downtime=" << dt << "s\n";
          note << "recovered#" << disconnects
               << "(downtime=" << (int)dt << "s) ";
          std::cout << "\n>>> Stream recovered! <<<\n\n";
        }
        consecutive_fail = 0;
      }
      continue;
    }
    ++consecutive_fail;
    if (connected && consecutive_fail >= 5) {
      detect_latency = elapsed() - last_good;
      downtime_start = elapsed();
      connected = false;
      std::cout << "[live] disconnect_detected latency="
                << detect_latency << "s\n";
      std::cout << "\n>>> Disconnect detected! Wait 5-10s then replug <<<\n\n";
    }
    if (!connected)
      std::this_thread::sleep_for(
          std::chrono::milliseconds(500));
  }
  cap.release();
  if (note.str().empty()) note << "no recovery event within window";
  std::ostringstream full;
  full << "window=" << window_sec << "s; frames=" << ok_frames << "; "
       << note.str();
  ItemResult r{"real_usb_unplug_reconnect",
               "Real USB unplug/reconnect recovery", "", "", now_utc()};
  r.note = escape_json(full.str());
  r.status = ask_verdict(r.test_ref, full.str());
  return r;
}

// ------------------------------------------------------ item 6: long run
ItemResult run_longrun(int minutes) {
  hr("[6/6] long_duration_stability");
  if (minutes <= 0) {
    ItemResult r{"long_duration_stability",
                 "Long-duration stability observation", SKIP,
                 "--long-run not given", now_utc()};
    g_report.record(r);
    return r;
  }
  cv::VideoCapture cap;
  if (!open_capture(cap, g_device)) {
    ItemResult r{"long_duration_stability",
                 "Long-duration stability observation", SKIP,
                 "cannot open " + g_device, now_utc()};
    g_report.record(r);
    return r;
  }
  auto deadline = std::chrono::steady_clock::now() +
                  std::chrono::minutes(minutes);
  int fails = 0, samples = 0;
  long peak_rss_kb = 0;
  while (std::chrono::steady_clock::now() < deadline) {
    Mat frame;
    if (!cap.read(frame)) ++fails;
    std::ifstream st("/proc/self/status");
    std::string line;
    while (std::getline(st, line))
      if (line.rfind("VmRSS:", 0) == 0) {
        long kb = std::atol(line.c_str() + 6);
        peak_rss_kb = std::max(peak_rss_kb, kb);
        break;
      }
    ++samples;
    std::this_thread::sleep_for(std::chrono::seconds(60));
  }
  cap.release();
  std::ostringstream note;
  note << "duration=" << minutes << "min fails=" << fails
       << " peakRSS=" << peak_rss_kb << "KB samples=" << samples;
  ItemResult r{"long_duration_stability",
               "Long-duration stability observation", "", "", now_utc()};
  r.note = escape_json(note.str());
  r.status = ask_verdict(r.test_ref, note.str());
  return r;
}

// ------------------------------------------------------------------- main
struct Args {
  std::string device = "/dev/video0";
  std::string outdir = "./report/new";
  std::string answer;
  std::string item;
  int reconnect_window = 30;
  int long_run = 0;
  bool list_only = false;
};

Args parse_args(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    auto next = [&]() -> std::string {
      return (i + 1 < argc) ? std::string(argv[++i]) : std::string();
    };
    if (arg == "-d" || arg == "--device") a.device = next();
    else if (arg == "--outdir") a.outdir = next();
    else if (arg == "--answer") a.answer = next();
    else if (arg == "--item") a.item = next();
    else if (arg == "--reconnect-window")
      a.reconnect_window = std::atoi(next().c_str());
    else if (arg == "--long-run") a.long_run = std::atoi(next().c_str());
    else if (arg == "--list") a.list_only = true;
    else if (arg == "-h" || arg == "--help") {
      std::cout <<
          "Usage: manual_cpp [options]\n"
          "  -d, --device PATH|N     camera node (default /dev/video0)\n"
          "      --outdir DIR        report output dir (./report/new)\n"
          "      --answer p|f|s      non-interactive verdict\n"
          "      --item NAME         run a single item\n"
          "      --reconnect-window S   item5 window seconds (30)\n"
          "      --long-run MIN      item6 duration minutes\n"
          "      --list              list items and exit\n";
      std::exit(0);
    }
  }
  return a;
}

std::string description_of(const std::string& ref) {
  static const std::map<std::string, std::string> m = {
      {"device_index_physical_mapping",
       "Confirm index/node to physical camera mapping"},
      {"exposure_visual_check", "Exposure sweep brightness response"},
      {"autofocus_visual_check", "Focus/zoom sharpness response"},
      {"white_balance_visual_check", "White-balance color cast response"},
      {"real_usb_unplug_reconnect", "Real USB unplug/reconnect recovery"},
      {"long_duration_stability", "Long-duration stability observation"},
  };
  auto it = m.find(ref);
  return it != m.end() ? it->second : "";
}

void ensure_device_exists(const std::string& dev) {
  std::string node = dev;
  if (dev.empty() || dev.find_first_not_of("0123456789") == std::string::npos)
    node = "/dev/video" +
           (dev.find_first_not_of("0123456789") == std::string::npos ? dev : "");
  else if (dev.rfind("/dev/", 0) != 0)
    return;                                   // URLs / pipelines: skip
  if (fs::exists(fs::path(node))) return;
  std::cerr << "[ERROR] target device '" << dev << "' (" << node
            << ") does not exist.\nAvailable video nodes:\n";
  for (auto& n : video_nodes())
    std::cerr << "  " << n.node << "  " << n.name << "\n";
  std::cerr << "Plug in the camera or pass -d/--device with an existing node.\n";
  std::exit(2);
}

int main(int argc, char** argv) {
  std::cout<<std::unitbuf; // live output under pipes
  Args args = parse_args(argc, argv);
  g_color = isatty(1);
  g_answer = args.answer;
  g_device = args.device;
  g_outdir = args.outdir;
  g_reconnect_window = args.reconnect_window;
  g_long_run_min = args.long_run;

  for (const char* ref : ITEM_ORDER)
    g_report.descriptions[ref] = description_of(ref);
  std::vector<std::string> order(ITEM_ORDER, ITEM_ORDER + ITEM_N);
  g_report.order = order;

  if (args.list_only) {
    for (const char* ref : ITEM_ORDER)
      std::cout << "[" << ref << "] "
                << description_of(ref) << "\n";
    return 0;
  }

  ensure_device_exists(args.device);
  fs::create_directories(args.outdir);

  using Runner = ItemResult (*)();
  static const std::map<std::string, Runner> runners = {
      {"device_index_physical_mapping", run_device_mapping},
      {"exposure_visual_check", run_exposure},
      {"autofocus_visual_check", run_autofocus},
      {"white_balance_visual_check", run_whitebalance},
      {"real_usb_unplug_reconnect",
       [] { return run_reconnect(g_reconnect_window); }},
      {"long_duration_stability",
       [] { return run_longrun(g_long_run_min); }},
  };

  std::vector<std::string> selected =
      args.item.empty()
          ? std::vector<std::string>(ITEM_ORDER, ITEM_ORDER + ITEM_N)
          : std::vector<std::string>{args.item};

  int fails = 0;
  for (const auto& ref : selected) {
    auto it = runners.find(ref);
    if (it == runners.end()) continue;
    try {
      ItemResult r = it->second();
      r.description = description_of(ref);
      g_report.record(ref, r.status, r.note);
      if (r.status == FAIL) ++fails;
    } catch (const std::exception& e) {
      g_report.record(ref, SKIP,
                      std::string("runner error: ") + e.what());
    }
    fs::create_directories(args.outdir);
    std::ostringstream p;
    p << args.outdir << "/report_manual_cpp.json";
    g_report.save(p.str());                    // incremental save per item
  }

  int done = 0, passed = 0;
  for (auto& r : g_report.results)
    if (r.status != "NOT_RUN") {
      ++done;
      if (r.status == PASS) ++passed;
    }
  std::cout << "\n" << bold(std::string(60, '=')) << "\n"
            << bold("MANUAL SUITE SUMMARY") << "\n"
            << bold(std::string(60, '=')) << "\n"
            << "  executed this run : " << selected.size() << "\n"
            << "  total recorded    : " << done << "/" << ITEM_N
            << "  (PASS=" << passed << ", FAIL=" << fails << ")\n"
            << "  report : "
            << (fs::path(args.outdir) / "report_manual_cpp.json").string()
            << "\n";
  return fails ? 1 : 0;
}
