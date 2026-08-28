// opencv_camera_api_test.cpp - C++ port of the auto API coverage suite.
#include <opencv2/videoio.hpp>
#include <opencv2/videoio/registry.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/core/utils/logger.hpp>
#include "cap_prop_table.hpp"
using cv::Mat; using cv::VideoCapture; using cv::VideoWriter;
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
#if defined(_WIN32)
#  include <io.h>
#else
#  include <unistd.h>
#endif
#include <sys/stat.h>
namespace {
const char* PASS="PASS"; const char* FAIL="FAIL"; const char* WARN="WARN"; const char* SKIP="SKIP";
bool g_color=true;
std::string paint(const char*c,const std::string&t){return g_color?"\033["+std::string(c)+"m"+t+"\033[0m":t;}
std::string green(const std::string&t){return paint("32",t);}
std::string red(const std::string&t){return paint("31",t);}
std::string yellow(const std::string&t){return paint("33",t);}
std::string dim(const std::string&t){return paint("2",t);}
std::string bold(const std::string&t){return paint("1",t);}
std::string cyan(const std::string&t){return paint("36",t);}
struct Result { std::string group,api,status,message; };
class Suite {
public:
  std::vector<Result> rows; cv::VideoCapture cap; bool camera_ok=false;
  std::vector<cv::Mat> frames; int ok_read=0,total_read=0; double measured_fps=0.0;
  std::map<std::string,double> observed; std::string observed_fourcc;
  bool has_api(const std::string&api)const{for(auto&r:rows)if(r.api==api)return true;return false;}
  void add(const std::string&g,const std::string&api,const std::string&st,const std::string&msg=""){
    rows.push_back({g,api,st,msg});
    std::string head="["+g+"] "+api;
    if(head.size()<62)head+=std::string(62-head.size(),'.');
    std::string mark = st==PASS?green(st):st==FAIL?red(st):st==WARN?yellow(st):dim(st);
    std::cout<<head+" "+mark+(msg.empty()?"":" "+msg)+"\n";std::cout.flush();
  }
};
std::string fourcc_to_str(int v){std::string s;for(int i=0;i<4;++i){char c=(char)((v>>(8*i))&0xFF);s+=(c>=0x20&&c<=0x7E)?c:'?';}return s;}
cv::VideoCaptureAPIs api_cast(int v){return static_cast<cv::VideoCaptureAPIs>(v);}
template<typename T> double safe_get(T&obj,int prop){try{double v=obj.get(prop);return std::isnan(v)?-1e9:v;}catch(...){return -1e9;}}
// OpenCV 5.x throws on read-only/invalid set(); treat as plain rejection.
template<typename T> bool safe_set(T&obj,int prop,double v){try{return obj.set(prop,v);}catch(...){return false;}}
bool family_applicable(const char*tok,const std::string&be){
  std::string t=tok?tok:""; if(t.empty())return true;
  if(t=="V4L")return be=="ANY"||be=="V4L2"; if(t=="GSTREAMER")return be=="ANY"||be=="GSTREAMER"; return false;}
int backend_id(const std::string&n){if(n=="V4L2")return cv::CAP_V4L2;if(n=="GSTREAMER")return cv::CAP_GSTREAMER;if(n=="FFMPEG")return cv::CAP_FFMPEG;return cv::CAP_ANY;}
void os_mkdir(const std::string&p){
#if defined(_WIN32)
  _mkdir(p.c_str());
#else
  mkdir(p.c_str(),0755);
#endif
}
std::vector<std::pair<char,std::string>> planned_items(){
  std::vector<std::pair<char,std::string>>v={
    {'A',"OpenCV version"},{'A',"build: V4L support"},{'A',"build: GStreamer support"},
    {'A',"registry.getBackends()"},{'A',"registry.getBackendName()"},{'A',"registry.hasBackend(target)"},
    {'A',"registry.getCameraBackends()"},{'A',"registry.getStreamBackends()"},{'A',"registry.getWriterBackends()"},
    {'A',"registry.isBackendBuiltIn()"},{'A',"registry.getCameraBackendPluginVersion()"},
    {'A',"registry.getStreamBackendPluginVersion()"},{'A',"registry.getWriterBackendPluginVersion()"},
    {'A',"registry.getStreamBufferedBackends()"},{'A',"registry.getStreamBufferedBackendPluginVersion()"},
    {'B',"VideoCapture(device, backend)"},{'B',"open()"},{'B',"isOpened()"},{'B',"getBackendName()"},
    {'B',"exception mode toggle"},{'B',"waitAny()"},{'B',"negative open case"},
    {'B',"open-only params precheck"},{'B',"backend ANY vs V4L2"},
    {'B',"grab()"},{'B',"retrieve()"},{'B',"read loop"},{'B',"operator>>"},{'B',"release()"},
    {'B',"open(String filename, apiPreference)"},{'B',"open(int,api,params)"},{'B',"open(String,api,params)"},{'B',"open(IStreamReader,api,params)"}};
  for(const char*n:{"FRAME_WIDTH","FRAME_HEIGHT","FPS","FOURCC","BUFFERSIZE","AUTO_EXPOSURE","EXPOSURE","GAIN","FORMAT","MODE","CONVERT_RGB"})
    v.push_back({'C',std::string("CAP_PROP_")+n+" get/set"});
  for(const char*n:{"frame not None","frame dimensions","pixel variance","freeze detection"})v.push_back({'D',n});
  v.push_back({'E',"VideoWriter.fourcc()"});v.push_back({'E',"VideoWriter(path, fourcc, fps, size)"});
  v.push_back({'E',"writer.isOpened()"});v.push_back({'E',"writer.getBackendName()"});
  v.push_back({'E',"writer.get(VIDEOWRITER_PROP_*)"});v.push_back({'E',"writer.set(VIDEOWRITER_PROP_*)"});
  v.push_back({'E',"writer.write()"});v.push_back({'E',"operator<<"});v.push_back({'E',"writer.release()"});v.push_back({'E',"VideoWriter readback"});
  v.push_back({'E',"VideoWriter with apiPreference"});v.push_back({'E',"VideoWriter with params"});v.push_back({'E',"VideoWriter with apiPreference+params"});
  v.push_back({'E',"open(String,apiPreference)"});v.push_back({'E',"open(String,fourcc,fps,Size,params)"});v.push_back({'E',"open(String,api,fourcc,fps,Size,params)"});
  v.push_back({'E',"VIDEOWRITER_PROP_* inventory"});v.push_back({'F',"CAP_PROP_* full sweep"});
  v.push_back({'G',"negotiated fmt within v4l2-ctl advertised list"});
  return v;
}
void skip_rest(Suite&s,const std::string&why){
  for(auto&item:planned_items()){if(item.first=='A')continue;if(!s.has_api(item.second))s.add(std::string(1,item.first),item.second,SKIP,why);}
}
void parse_video_io(const std::string&info,std::map<std::string,std::string>&out){
  bool active=false;std::istringstream ss(info);std::string line;
  static const std::regex kv(R"((.+?):\s*(YES|NO)(?:\s+\(.*?\))?\s*$)");
  auto trim=[](std::string x){while(!x.empty()&&(x.front()==' '||x.front()=='\t'))x.erase(x.begin());while(!x.empty()&&(x.back()==' '||x.back()=='\t'))x.pop_back();return x;};
  while(std::getline(ss,line)){auto t=trim(line);
    if(t.rfind("Video I/O",0)==0){active=true;continue;}
    if(!active)continue;if(t.empty())break;std::smatch m;
    if(std::regex_match(t,m,kv))out[m.str(1)]=m.str(2);}
}
void env_check(Suite&s,const std::string&backend){
  s.add("A","OpenCV version",PASS,CV_VERSION);
#ifdef OPENCV_SOURCE_LABEL
  s.add("A","opencv_source",PASS,OPENCV_SOURCE_LABEL);
#endif
  std::map<std::string,std::string>vio;parse_video_io(cv::getBuildInformation(),vio);
  auto flag=[&](const std::string&k){auto it=vio.find(k);return it==vio.end()?"unknown":it->second;};
  if(family_applicable("V4L",backend))
    s.add("A","build: V4L support",flag("v4l/v4l2")=="YES"?PASS:FAIL,"v4l/v4l2="+flag("v4l/v4l2"));
  else
    s.add("A","build: V4L support",SKIP,std::string("not applicable: backend=")+backend+" (build has v4l/v4l2="+flag("v4l/v4l2")+")");
  if(family_applicable("GSTREAMER",backend))
    s.add("A","build: GStreamer support",flag("GStreamer")=="YES"?PASS:FAIL,"GStreamer="+flag("GStreamer"));
  else
    s.add("A","build: GStreamer support",SKIP,std::string("not applicable: backend=")+backend+" (build has GStreamer="+flag("GStreamer")+")");
  try{auto ids=cv::videoio_registry::getBackends();std::string names;
    for(auto id:ids)names+=(names.empty()?"":", ")+cv::videoio_registry::getBackendName(id);
    s.add("A","registry.getBackends()",names.empty()?FAIL:PASS,names);
    if(!ids.empty())s.add("A","registry.getBackendName()",PASS,cv::videoio_registry::getBackendName(ids.front()));
    else s.add("A","registry.getBackendName()",SKIP,"no backends");
    int target=backend_id(backend=="ANY"?"V4L2":backend);
    s.add("A","registry.hasBackend(target)",cv::videoio_registry::hasBackend(api_cast(target))?PASS:WARN,"target="+(backend=="ANY"?std::string("V4L2"):backend));
    // [A] camera/stream/writer backends list + isBackendBuiltIn
    try{
      auto cids=cv::videoio_registry::getCameraBackends(); std::string cnames;
      for(auto id:cids) cnames+=(cnames.empty()?"":", ")+cv::videoio_registry::getBackendName(id);
      s.add("A","registry.getCameraBackends()",cnames.empty()?WARN:PASS,cnames.empty()?"empty list":cnames);
      auto sids=cv::videoio_registry::getStreamBackends(); std::string snames;
      for(auto id:sids) snames+=(snames.empty()?"":", ")+cv::videoio_registry::getBackendName(id);
      s.add("A","registry.getStreamBackends()",snames.empty()?WARN:PASS,snames.empty()?"empty list":snames);
      auto wids=cv::videoio_registry::getWriterBackends(); std::string wnames;
      for(auto id:wids) wnames+=(wnames.empty()?"":", ")+cv::videoio_registry::getBackendName(id);
      s.add("A","registry.getWriterBackends()",wnames.empty()?WARN:PASS,wnames.empty()?"empty list":wnames);
      bool bi=cv::videoio_registry::isBackendBuiltIn(api_cast(target));
      s.add("A","registry.isBackendBuiltIn()",PASS,std::string(backend=="ANY"?"V4L2":backend)+(bi?" builtIn":" plugin"));
    }catch(const std::exception&e){ s.add("A","registry.getCameraBackends()",WARN,std::string("raised: ")+e.what()); }
#if CV_VERSION_MAJOR >= 5
    // [5.x] memory-buffer capture surface: VideoCapture(buffer) backends.
    // Device-less capability -> not applicable under an explicit device
    // backend such as V4L2.
    if(backend=="V4L2"){
      s.add("A","registry.getStreamBufferedBackends()",SKIP,"not applicable: backend=V4L2 (memory-buffer capture)");
      s.add("A","registry.getStreamBufferedBackendPluginVersion()",SKIP,"not applicable: backend=V4L2 (memory-buffer capture)");
    }else{
      auto sb=cv::videoio_registry::getStreamBufferedBackends();std::string sbnames;
      for(auto id:sb)sbnames+=(sbnames.empty()?"":", ")+cv::videoio_registry::getBackendName(id);
      s.add("A","registry.getStreamBufferedBackends()",sbnames.empty()?WARN:PASS,sbnames.empty()?"empty list":sbnames);
      int plugin_hit=-1;
      for(auto id:sb)
        if(!cv::videoio_registry::isBackendBuiltIn(api_cast(id))){plugin_hit=(int)id;break;}
      if(plugin_hit<0)
        s.add("A","registry.getStreamBufferedBackendPluginVersion()",SKIP,
              "no plugin backend in buffer-capture list"+(sb.empty()?std::string():std::string(" ("+std::to_string(sb.size())+" builtin)")));
      else{
        int vabi=0,vapi=0;
        std::string desc=cv::videoio_registry::getStreamBufferedBackendPluginVersion(api_cast(plugin_hit),vabi,vapi);
        s.add("A","registry.getStreamBufferedBackendPluginVersion()",PASS,
              cv::videoio_registry::getBackendName(api_cast(plugin_hit))+" plugin="+desc);}
    }
    // stream/writer plugin-version variants: registry info queries,
    // independent of the selected backend -> run under any backend.
    {
      auto first_plugin=[](const std::vector<cv::VideoCaptureAPIs>&ids)->int{
        for(auto id:ids){
          if(!cv::videoio_registry::isBackendBuiltIn(api_cast(id))
             &&cv::videoio_registry::hasBackend(api_cast(id)))
            return (int)id;}
        return -1;};
      auto report_pv=[&](const char*label,int hit,
                         std::string(*fn)(cv::VideoCaptureAPIs,int&,int&)){
        if(hit<0){s.add("A",label,SKIP,"no available plugin backend");return;}
        int vabi=0,vapi=0;
        try{std::string d=fn(api_cast(hit),vabi,vapi);
          s.add("A",label,PASS,cv::videoio_registry::getBackendName(api_cast(hit))+" plugin="+d);}
        catch(const std::exception&e){
          s.add("A",label,WARN,cv::videoio_registry::getBackendName(api_cast(hit))+" raised: "+e.what());}};
      {auto ids=cv::videoio_registry::getCameraBackends();
       report_pv("registry.getCameraBackendPluginVersion()",first_plugin(ids),
                 &cv::videoio_registry::getCameraBackendPluginVersion);}
      {auto ids=cv::videoio_registry::getStreamBackends();
       report_pv("registry.getStreamBackendPluginVersion()",first_plugin(ids),
                 &cv::videoio_registry::getStreamBackendPluginVersion);}
      {auto ids=cv::videoio_registry::getWriterBackends();
       report_pv("registry.getWriterBackendPluginVersion()",first_plugin(ids),
                 &cv::videoio_registry::getWriterBackendPluginVersion);}
    }
#endif
  }catch(const std::exception&e){s.add("A","registry.*",FAIL,e.what());}
}
void capture_extras(Suite&s){
  try{s.add("B","getBackendName()",PASS,s.cap.getBackendName());}catch(const std::exception&e){s.add("B","getBackendName()",FAIL,e.what());}
  try{bool old=s.cap.getExceptionMode();s.cap.setExceptionMode(!old);bool now=s.cap.getExceptionMode();s.cap.setExceptionMode(old);
    s.add("B","exception mode toggle",(now!=old)?PASS:WARN,"toggled and restored");}catch(const std::exception&e){s.add("B","exception mode toggle",SKIP,e.what());}
#if CV_VERSION_MAJOR > 4 || (CV_VERSION_MAJOR == 4 && (CV_VERSION_MINOR > 5 || (CV_VERSION_MINOR == 5 && CV_VERSION_PATCH >= 5)))
  try{std::vector<int>ready;std::vector<cv::VideoCapture>caps{s.cap};
    bool ok=cv::VideoCapture::waitAny(caps,ready,1500000000LL);
    s.add("B","waitAny()",ok?PASS:WARN,"single-camera probe");}catch(const std::exception&e){s.add("B","waitAny()",SKIP,e.what());}
#else
  s.add("B","waitAny()",SKIP,"not available before OpenCV 4.5.5");
#endif
}
void negative_open(Suite&s){
  const std::string ghost="/dev/video63";VideoCapture cap;
  try{cap.open(ghost,api_cast(cv::CAP_V4L2));}catch(const std::exception&e){s.add("B","negative open case",WARN,std::string("raised: ")+e.what());return;}
  bool opened=cap.isOpened();cap.release();
  if(opened)s.add("B","negative open case",FAIL,ghost+" unexpectedly opened");
  else s.add("B","negative open case",PASS,ghost+" correctly refused");}
void open_only_precheck(Suite&s,const std::string&dev,int bid){
  struct P{const char*name;int pid;int value;};
  const P props[]={
    {"CAP_PROP_HW_ACCELERATION",cv::CAP_PROP_HW_ACCELERATION,0},
    {"CAP_PROP_HW_DEVICE",cv::CAP_PROP_HW_DEVICE,0},
#if defined(CAP_PROP_HW_ACCELERATION_USE_OPENCL)
    {"CAP_PROP_HW_ACCELERATION_USE_OPENCL",cv::CAP_PROP_HW_ACCELERATION_USE_OPENCL,0},
#endif
    {"CAP_PROP_OPEN_TIMEOUT_MSEC",cv::CAP_PROP_OPEN_TIMEOUT_MSEC,5000},
    {"CAP_PROP_READ_TIMEOUT_MSEC",cv::CAP_PROP_READ_TIMEOUT_MSEC,5000}};
  const size_t n_params=sizeof(props)/sizeof(props[0]);
  auto try_open=[&](const std::vector<int>&params)->bool{
    VideoCapture cap;bool opened=false;
    try{
      if(dev.find_first_not_of("0123456789")==std::string::npos)cap.open(std::stoi(dev),api_cast(bid),params);
      else cap.open(dev,api_cast(bid),params);
      opened=cap.isOpened();
    }catch(...){opened=false;}
    cap.release();
    return opened;};
  if(!try_open({})){
    s.add("B","open-only params precheck",SKIP,
          "baseline open() without params failed; cannot evaluate open-time params");
    return;}
  std::vector<size_t>ok_idx,bad_idx;
  for(size_t k=0;k<n_params;++k)
    ((try_open({props[k].pid,props[k].value})?ok_idx:bad_idx).push_back(k));
  if(ok_idx.empty()){
    s.add("B","open-only params precheck",WARN,
          "backend rejects every open-time param ("+std::to_string(n_params)+")");
    return;}
  // Verdict follows API capability: any working param => usable => PASS.
  std::vector<int>combo;
  std::string ok_list,rej;
  for(size_t k:ok_idx){if(!ok_list.empty())ok_list+=", ";ok_list+=props[k].name;
    combo.push_back(props[k].pid);combo.push_back(props[k].value);}
  for(size_t k:bad_idx){if(!rej.empty())rej+=", ";rej+=props[k].name;}
  bool combo_ok=try_open(combo);
  if(combo_ok)
    s.add("B","open-only params precheck",PASS,
          "open-time params usable ("+std::to_string(ok_idx.size())+"/"+std::to_string(n_params)+"): "+ok_list
          +(rej.empty()?"":"; rejected: "+rej));
  else
    s.add("B","open-only params precheck",WARN,
          "params OK individually but supported-combo rejected");}
struct PropCase{const char*name;int pid;double value;const char*mode;double tol;};
bool compare(const std::string&mode,double exp,double act,double tol,std::string&why){
  if(mode=="exact"){if(std::llround(act)!=std::llround(exp)){why="expected "+std::to_string(exp)+", got "+std::to_string(act);return false;}return true;}
  if(mode=="approx"){if(std::fabs(act-exp)>tol){why="expected ~"+std::to_string(exp)+" got "+std::to_string(act);return false;}return true;}
  if(mode=="bool")return(act!=0)==(exp!=0);
  if(mode=="fourcc")return fourcc_to_str((int)act)==fourcc_to_str((int)exp);
  if(mode=="roundtrip"){if(std::fabs(act-exp)>1e-6){why="roundtrip changed: "+std::to_string(exp)+" -> "+std::to_string(act);return false;}return true;}
  why="unknown mode";return false;}
void test_properties(Suite&s){
  const PropCase cases[]={
    {"FRAME_WIDTH",cv::CAP_PROP_FRAME_WIDTH,640,"exact",0},{"FRAME_HEIGHT",cv::CAP_PROP_FRAME_HEIGHT,480,"exact",0},
    {"FPS",cv::CAP_PROP_FPS,30,"approx",1.0},
    {"FOURCC",cv::CAP_PROP_FOURCC,(double)cv::VideoWriter::fourcc('M','J','P','G'),"fourcc",0},
    {"BUFFERSIZE",cv::CAP_PROP_BUFFERSIZE,1,"exact",0},
    {"AUTO_EXPOSURE",cv::CAP_PROP_AUTO_EXPOSURE,0,"roundtrip",0},
    {"EXPOSURE",cv::CAP_PROP_EXPOSURE,-6.0,"approx",0.75},
    {"GAIN",cv::CAP_PROP_GAIN,0,"roundtrip",0},{"FORMAT",cv::CAP_PROP_FORMAT,0,"roundtrip",0},
    {"MODE",cv::CAP_PROP_MODE,0,"roundtrip",0},{"CONVERT_RGB",cv::CAP_PROP_CONVERT_RGB,1,"bool",0}};
  for(auto&c:cases){std::string api=std::string("CAP_PROP_")+c.name+" get/set";
    double orig=safe_get(s.cap,c.pid);
    double target=(c.mode==std::string("roundtrip"))?orig:c.value;
    if(target<=-1e8){s.add("C",api,SKIP,"get() returned nothing");continue;}
    bool ok=safe_set(s.cap,c.pid,target);
    if(!ok){s.add("C",api,SKIP,"set() returned false");continue;}
    double got=safe_get(s.cap,c.pid);
    if(got<=-1e8){s.add("C",api,WARN,"set accepted but get failed");continue;}
    std::string why;
    if(compare(c.mode,target,got,c.tol,why))s.add("C",api,PASS,"");
    else s.add("C",api,WARN,"readback differs: "+why);
    if(c.mode!=std::string("roundtrip"))safe_set(s.cap,c.pid,orig);}}
void lifecycle_reads(Suite&s,int frames_wanted){
  for(int i=0;i<5;++i)if(!s.cap.grab())break;
  bool ok_grab=s.cap.grab();Mat img;
  if(ok_grab)ok_grab=s.cap.retrieve(img);
  s.add("B","retrieve()",ok_grab?PASS:FAIL,ok_grab?("frame "+std::to_string(img.cols)+"x"+std::to_string(img.rows)):"");
  for(int i=0;i<3&&s.cap.read(img);++i){}
  int ok_count=0;auto t0=std::chrono::steady_clock::now();
  for(int i=0;i<frames_wanted;++i){bool ok=s.cap.read(img);if(!ok)continue;++ok_count;s.frames.push_back(img.clone());}
  double sec=std::chrono::duration<double>(std::chrono::steady_clock::now()-t0).count();
  s.measured_fps=sec>0?ok_count/sec:0.0;s.ok_read=ok_count;s.total_read=frames_wanted;
  double rate=frames_wanted?(double)ok_count/frames_wanted:0;
  s.add("B","read loop",rate==1.0?PASS:(rate>=0.8?WARN:FAIL),
        std::to_string(ok_count)+"/"+std::to_string(frames_wanted)+" frames, "+std::to_string(s.measured_fps).substr(0,5)+" FPS");
  // operator>> (Mat) — syntax sugar for read()
  try{
    Mat op; s.cap >> op;
    bool ok = !op.empty();
    s.add("B","operator>>", ok?PASS:WARN, ok?("frame "+std::to_string(op.cols)+"x"+std::to_string(op.rows)):"empty (operator>> returned no frame)");
    if(ok && s.frames.empty()) s.frames.push_back(op.clone());
  }catch(const std::exception&e){ s.add("B","operator>>",WARN,std::string("raised: ")+e.what()); }
  catch(...){ s.add("B","operator>>",WARN,"raised unknown"); }
}
void frame_quality(Suite&s){
  auto&fs=s.frames;
  if(fs.empty()){s.add("D","frame not None",FAIL,"no frames");s.add("D","frame dimensions",SKIP,"no frames");
    s.add("D","pixel variance",SKIP,"no frames");s.add("D","freeze detection",SKIP,"no frames");return;}
  s.add("D","frame not None",PASS,std::to_string(fs.size())+" frames captured");
  s.add("D","frame dimensions",PASS,std::to_string(fs[0].cols)+"x"+std::to_string(fs[0].rows));
  Mat gray0;cvtColor(fs[0],gray0,cv::COLOR_BGR2GRAY);cv::Scalar m,sd;meanStdDev(gray0,m,sd);
  if(sd[0]<2.0)s.add("D","pixel variance",FAIL,"std="+std::to_string(sd[0])+" uniform?");
  else s.add("D","pixel variance",PASS,"std="+std::to_string(sd[0]).substr(0,5)+" mean="+std::to_string(m[0]).substr(0,6));
  int frozen=0,pairs=0;
  for(size_t i=1;i<fs.size();++i){Mat ga,gb;cvtColor(fs[i-1],ga,cv::COLOR_BGR2GRAY);cvtColor(fs[i],gb,cv::COLOR_BGR2GRAY);
    ++pairs;double d=cv::mean(cv::abs(ga-gb))[0];if(d<0.5)++frozen;}
  if(pairs&&frozen==pairs)s.add("D","freeze detection",WARN,"all pairs identical");
  else if(pairs)s.add("D","freeze detection",PASS,std::to_string(pairs-frozen)+"/"+std::to_string(pairs)+" pairs show motion");
  else s.add("D","freeze detection",SKIP,"single frame");}
void parse_v4l2_formats(const std::string&text,std::map<std::string,std::set<std::pair<int,int>>>&out){
  static const std::regex re_fmt(R"(^\s*\[\d+\]:\s*'([A-Za-z0-9]{4})')");
  static const std::regex re_size(R"(Size:\s*Discrete\s+(\d+)x(\d+))");
  std::istringstream ss(text);std::string line;std::string cur;std::smatch m;
  while(std::getline(ss,line)){
    if(std::regex_search(line,m,re_fmt)){cur=m.str(1);out[cur];continue;}
    if(std::regex_search(line,m,re_size)&&!cur.empty())out[cur].insert({std::stoi(m.str(1)),std::stoi(m.str(2))});}}
std::string parse_v4l2_current_format(const std::string&text){
  static const std::regex re(R"(Pixel Format\s*:\s*'([A-Za-z0-9]{4})')");
  std::smatch m;if(std::regex_search(text,m,re))return m.str(1);return "";}
void v4l2_crosscheck(Suite&s,const std::string&device){
  std::string dev_arg;
  if(!device.empty()){std::string d=device;
    if(d.find_first_not_of("0123456789")==std::string::npos)d="/dev/video"+d;
    dev_arg=" -d "+d;}
  std::string cmd="v4l2-ctl"+dev_arg+" --list-formats-ext 2>/dev/null";
  FILE*fp=popen(cmd.c_str(),"r");
  if(!fp){s.add("G","negotiated fmt within v4l2-ctl advertised list",SKIP,"v4l2-ctl not installed");return;}
  std::string text;char buf[4096];
  while(fgets(buf,sizeof(buf),fp))text+=buf;pclose(fp);
  std::map<std::string,std::set<std::pair<int,int>>>formats;
  parse_v4l2_formats(text,formats);
  if(formats.empty()){s.add("G","negotiated fmt within v4l2-ctl advertised list",SKIP,"could not parse output");return;}
  std::string fcc=s.observed_fourcc;
  std::transform(fcc.begin(),fcc.end(),fcc.begin(),::toupper);
  while(!fcc.empty()&&fcc.back()=='?')fcc.pop_back();
  if(fcc.empty()){
    std::string cmd_get="v4l2-ctl"+dev_arg+" --get-fmt-video 2>/dev/null";
    FILE*fp2=popen(cmd_get.c_str(),"r");
    if(fp2){std::string txt2;char buf2[4096];while(fgets(buf2,sizeof(buf2),fp2))txt2+=buf2;pclose(fp2);
      std::string fb=parse_v4l2_current_format(txt2);
      if(!fb.empty()){fcc=fb;std::transform(fcc.begin(),fcc.end(),fcc.begin(),::toupper);}}}
  if(fcc.empty()){s.add("G","negotiated fmt within v4l2-ctl advertised list",SKIP,"could not read FOURCC (fallback empty)");return;}
  int w=(int)s.observed["width"];int h=(int)s.observed["height"];
  auto it=formats.find(fcc);
  if(it==formats.end()){s.add("G","negotiated fmt within v4l2-ctl advertised list",FAIL,"fourcc '"+fcc+"' not advertised");return;}
  bool has_size=it->second.count({w,h})>0;
  s.add("G","negotiated fmt within v4l2-ctl advertised list",has_size?PASS:WARN,
        std::to_string(w)+"x"+std::to_string(h)+"@"+fcc+(has_size?" within driver modes (" : " negotiated but missing from list (")+std::to_string(it->second.size())+" modes)");}
Mat synthetic_frame(int w=320,int h=240,int shift=0){
  Mat base(h,w,CV_8UC1);
  for(int y=0;y<h;++y)for(int x=0;x<w;++x)base.at<uchar>(y,x)=(uchar)((x*255/std::max(1,w-1)+shift)%256);
  Mat bgr;cvtColor(base,bgr,cv::COLOR_GRAY2BGR);return bgr;}
void test_writer(Suite&s,const std::string&outdir){
  try{int fcc=cv::VideoWriter::fourcc('M','J','P','G');s.add("E","VideoWriter.fourcc()",PASS,"MJPG="+std::to_string(fcc));}catch(...){s.add("E","VideoWriter.fourcc()",FAIL,"raised");}
  struct Cand{const char*fourcc;const char*ext;};
  const Cand candidates[]={{"MJPG","avi"},{"X264","mp4"},{"MP4V","mp4"}};
  VideoWriter writer;std::string path,used;
  for(auto&cand:candidates){path=outdir+"/writer_cpp_test."+cand.ext;
    writer.open(path,cv::VideoWriter::fourcc(cand.fourcc[0],cand.fourcc[1],cand.fourcc[2],cand.fourcc[3]),30.0,cv::Size(640,480));
    if(writer.isOpened()){used=cand.fourcc;break;}writer.release();}
  if(!writer.isOpened()){for(const char*api:{"VideoWriter(path, fourcc, fps, size)","writer.isOpened()","writer.getBackendName()",
    "writer.get(VIDEOWRITER_PROP_*)","writer.set(VIDEOWRITER_PROP_*)","writer.write()","operator<<","writer.release()","VideoWriter readback","VIDEOWRITER_PROP_* inventory"})
    s.add("E",api,SKIP,"no usable encoder");return;}
  s.add("E","VideoWriter(path, fourcc, fps, size)",PASS,"fourcc="+used);
  s.add("E","writer.isOpened()",writer.isOpened()?PASS:FAIL,"");
  try{s.add("E","writer.getBackendName()",PASS,writer.getBackendName());}catch(...){s.add("E","writer.getBackendName()",SKIP,"unavailable");}
  for(size_t i=0;i<camprops::WRITER_PROPS_N;++i){auto&wp=camprops::WRITER_PROPS[i];
    double v=safe_get(writer,wp.pid);std::string api=std::string("writer.get(")+wp.name+")";
    if(v<=-1e8||v==-1.0)s.add("E",api,SKIP,"unsupported (-1 sentinel)");
    else s.add("E",api,PASS,std::string(wp.name)+"="+std::to_string(v).substr(0,6));}
  s.add("E","VIDEOWRITER_PROP_* inventory",PASS,std::to_string(camprops::WRITER_PROPS_N)+" probed");
  int q_pid=-1;
  for(size_t i=0;i<camprops::WRITER_PROPS_N;++i)
    if(strcmp(camprops::WRITER_PROPS[i].name,"VIDEOWRITER_PROP_QUALITY")==0)q_pid=camprops::WRITER_PROPS[i].pid;
  bool q_ok=(q_pid>=0)&&safe_set(writer,q_pid,90);
  s.add("E","writer.set(VIDEOWRITER_PROP_*)",q_ok?PASS:SKIP,q_ok?"QUALITY=90":"rejected");
  int written=0;for(auto&f:s.frames)writer.write(f);
  written=(int)s.frames.size();
  s.add("E","writer.write()",written>0?PASS:FAIL,std::to_string(written)+" frames written");
  // operator<< — syntax sugar for write()
  try{
    Mat extra = synthetic_frame(640,480, written % 256);
    writer << extra;
    s.add("E","operator<<",PASS,"via << synthetic frame");
    ++written;
  }catch(const std::exception&e){ s.add("E","operator<<",WARN,std::string("raised: ")+e.what()); }
  catch(...){ s.add("E","operator<<",WARN,"raised unknown"); }
  writer.release();
  s.add("E","writer.release()",!writer.isOpened()?PASS:WARN,"");
  VideoCapture back(path);Mat decoded;bool ok=back.isOpened()&&back.read(decoded);back.release();
  s.add("E","VideoWriter readback",ok?PASS:FAIL,ok?("decoded "+std::to_string(decoded.cols)+"x"+std::to_string(decoded.rows)):"decode failed");}
void test_capture_open_overloads(Suite&s,const std::string&device,const std::string&outdir){
  // Sample file from previous writer test
  std::string sample = outdir+"/writer_cpp_test.avi";
  struct stat st; bool sample_exists = (stat(sample.c_str(),&st)==0 && st.st_size>0);
  if(!sample_exists){
    // fallback: try any writer file
    sample = outdir+"/writer_test.avi";
    sample_exists = (stat(sample.c_str(),&st)==0 && st.st_size>0);
  }
  // 1) open(String filename, apiPreference) — explicit open
  try{
    if(!sample_exists) s.add("B","open(String filename, apiPreference)",SKIP,"no sample file (writer not created)");
    else{
      VideoCapture cap; bool opened=false;
      try{ opened = cap.open(sample, cv::CAP_FFMPEG); }catch(...){ opened=false; }
      bool isOpen = false; try{ isOpen = cap.isOpened(); }catch(...){}
      s.add("B","open(String filename, apiPreference)", (opened&&isOpen)?PASS:WARN, sample+(isOpen?" opened":" not opened"));
      // also test constructor overload
      try{ VideoCapture cap2(sample, cv::CAP_FFMPEG); s.add("B","open(String filename, apiPreference)", cap2.isOpened()?PASS:WARN,"via ctor "+sample); cap2.release(); }catch(const std::exception&e){ s.add("B","open(String filename, apiPreference)",WARN,std::string("ctor raised: ")+e.what()); }
      cap.release();
    }
  }catch(const std::exception&e){ s.add("B","open(String filename, apiPreference)",WARN,std::string("raised: ")+e.what()); }
  // 2) open(String, api, params) — vector<int> params
  try{
    if(!sample_exists) s.add("B","open(String,api,params)",SKIP,"no sample file");
    else{
      std::vector<int> params = {cv::CAP_PROP_OPEN_TIMEOUT_MSEC, 5000};
      VideoCapture cap; bool opened=false;
      try{ opened = cap.open(sample, cv::CAP_FFMPEG, params); }catch(...){ opened=false; }
      s.add("B","open(String,api,params)", (opened&&cap.isOpened())?PASS:WARN, "params OPEN_TIMEOUT_MSEC=5000");
      cap.release();
    }
  }catch(const std::exception&e){ s.add("B","open(String,api,params)",WARN,std::string("raised: ")+e.what()); }
  // 3) open(int, api, params) — device with params
  try{
    std::vector<int> params = {cv::CAP_PROP_READ_TIMEOUT_MSEC, 5000};
    VideoCapture cap; bool opened=false;
    try{
      if(device.find_first_not_of("0123456789")==std::string::npos) opened = cap.open(std::stoi(device), cv::CAP_V4L2, params);
      else opened = cap.open(device, cv::CAP_V4L2, params);
    }catch(...){ opened=false; }
    s.add("B","open(int,api,params)", (opened&&cap.isOpened())?PASS:WARN, "params READ_TIMEOUT_MSEC=5000");
    cap.release();
  }catch(const std::exception&e){ s.add("B","open(int,api,params)",WARN,std::string("raised: ")+e.what()); }
  // 4) open(IStreamReader, api, params) — memory stream
#if CV_VERSION_MAJOR >= 4
  try{
    if(!sample_exists) s.add("B","open(IStreamReader,api,params)",SKIP,"no sample file for MemReader");
    else{
      struct MemReader : public cv::IStreamReader{
        std::vector<char> data; size_t pos=0;
        explicit MemReader(const std::string& p){ std::ifstream f(p,std::ios::binary); if(f) data.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()); }
        long long read(char* buf, long long sz) override{
          long long rem = (long long)data.size()-(long long)pos; long long n = std::min(sz, rem); if(n<=0) return 0; memcpy(buf, data.data()+pos, (size_t)n); pos+=n; return n;
        }
        long long seek(long long off, int org) override{
          size_t np=0; if(org==SEEK_SET) np = (size_t)off; else if(org==SEEK_CUR) np = pos + (size_t)off; else if(org==SEEK_END) np = data.size() + (size_t)off; else return -1; if(np>data.size()) return -1; pos=np; return (long long)pos;
        }
      };
      auto reader = cv::makePtr<MemReader>(sample);
      if(reader->data.empty()){
        s.add("B","open(IStreamReader,api,params)",SKIP,"MemReader empty");
      }else{
        // ctor overload
        bool ctor_ok=false, open_ok=false;
        try{ VideoCapture c2(reader, cv::CAP_FFMPEG, std::vector<int>{}); ctor_ok = c2.isOpened(); if(ctor_ok){ Mat f; ctor_ok = c2.read(f) && !f.empty(); } c2.release(); }catch(...){ ctor_ok=false; }
        s.add("B","open(IStreamReader,api,params)", ctor_ok?PASS:WARN, ctor_ok?"via ctor+read":"ctor open/read failed (buffer/FFMPEG may not support)");
        // open overload
        try{ VideoCapture cap; std::vector<int> p; open_ok = cap.open(reader, cv::CAP_FFMPEG, p); if(open_ok) open_ok = cap.isOpened(); cap.release(); }catch(...){ open_ok=false; }
        // report open separately if ctor already reported, use same api name (dedup handled)
        if(!ctor_ok) s.add("B","open(IStreamReader,api,params)", open_ok?PASS:WARN, open_ok?"via open()":"open() failed");
      }
    }
  }catch(const std::exception&e){ s.add("B","open(IStreamReader,api,params)",WARN,std::string("raised: ")+e.what()); }
#else
  s.add("B","open(IStreamReader,api,params)",SKIP,"IStreamReader requires OpenCV >=4");
#endif
}
void test_writer_overloads(Suite&s,const std::string&outdir){
  Mat frame = synthetic_frame(640,480,0);
  // 1) VideoWriter with apiPreference
  try{
    std::string p = outdir+"/writer_api_test.avi";
    VideoWriter w(p, cv::CAP_FFMPEG, cv::VideoWriter::fourcc('M','J','P','G'), 30.0, cv::Size(640,480), true);
    bool ok = w.isOpened(); if(ok){ w.write(frame); w.release(); s.add("E","VideoWriter with apiPreference",PASS,p+" CAP_FFMPEG"); }
    else s.add("E","VideoWriter with apiPreference",WARN,"isOpened false "+p);
    // also test open() with apiPreference
    VideoWriter w2; bool ok2 = w2.open(p, cv::CAP_FFMPEG, cv::VideoWriter::fourcc('M','J','P','G'), 30.0, cv::Size(640,480), true);
    s.add("E","open(String,apiPreference)", ok2&&w2.isOpened()?PASS:WARN, ok2?"open apiPreference OK":"open apiPreference failed"); if(w2.isOpened()){ w2.write(frame); w2.release(); }
  }catch(const std::exception&e){ s.add("E","VideoWriter with apiPreference",WARN,std::string("raised: ")+e.what()); s.add("E","open(String,apiPreference)",WARN,std::string("raised: ")+e.what()); }
  // 2) VideoWriter with params
  try{
    std::string p = outdir+"/writer_params_test.avi";
    std::vector<int> params = {cv::VIDEOWRITER_PROP_IS_COLOR, 1};
    VideoWriter w(p, cv::VideoWriter::fourcc('M','J','P','G'), 30.0, cv::Size(640,480), params);
    bool ok = w.isOpened(); if(ok){ w.write(frame); w.release(); s.add("E","VideoWriter with params",PASS,"IS_COLOR=1"); }
    else s.add("E","VideoWriter with params",WARN,"isOpened false "+p);
    // open with params
    VideoWriter w2; bool ok2 = w2.open(p, cv::VideoWriter::fourcc('M','J','P','G'), 30.0, cv::Size(640,480), params);
    s.add("E","open(String,fourcc,fps,Size,params)", ok2&&w2.isOpened()?PASS:WARN, ok2?"open params OK":"open params failed"); if(w2.isOpened()){ w2.write(frame); w2.release(); }
  }catch(const std::exception&e){ s.add("E","VideoWriter with params",WARN,std::string("raised: ")+e.what()); s.add("E","open(String,fourcc,fps,Size,params)",WARN,std::string("raised: ")+e.what()); }
  // 3) VideoWriter with apiPreference+params
  try{
    std::string p = outdir+"/writer_api_params_test.avi";
    std::vector<int> params = {cv::VIDEOWRITER_PROP_IS_COLOR, 1};
    VideoWriter w(p, cv::CAP_FFMPEG, cv::VideoWriter::fourcc('M','J','P','G'), 30.0, cv::Size(640,480), params);
    bool ok = w.isOpened(); if(ok){ w.write(frame); w.release(); s.add("E","VideoWriter with apiPreference+params",PASS,"api+IS_COLOR=1"); }
    else s.add("E","VideoWriter with apiPreference+params",WARN,"isOpened false "+p);
    VideoWriter w2; bool ok2 = w2.open(p, cv::CAP_FFMPEG, cv::VideoWriter::fourcc('M','J','P','G'), 30.0, cv::Size(640,480), params);
    s.add("E","open(String,api,fourcc,fps,Size,params)", ok2&&w2.isOpened()?PASS:WARN, ok2?"open api+params OK":"open api+params failed"); if(w2.isOpened()){ w2.write(frame); w2.release(); }
  }catch(const std::exception&e){ s.add("E","VideoWriter with apiPreference+params",WARN,std::string("raised: ")+e.what()); s.add("E","open(String,api,fourcc,fps,Size,params)",WARN,std::string("raised: ")+e.what()); }
}
static std::map<std::string,std::string>CAP_TO_V4L2={
  {"BRIGHTNESS","brightness"},{"CONTRAST","contrast"},{"SATURATION","saturation"},
  {"HUE","hue"},{"GAIN","gain"},{"EXPOSURE","exposure_absolute"},
  {"AUTO_EXPOSURE","exposure_auto"},{"SHARPNESS","sharpness"},{"GAMMA","gamma"},
  {"BACKLIGHT","backlight_compensation"},{"FOCUS","focus_absolute"},
  {"AUTOFOCUS","focus_auto"},{"ZOOM","zoom_absolute"},{"PAN","pan_absolute"},
  {"TILT","tilt_absolute"},
  {"WHITE_BALANCE_BLUE_U","white_balance_blue_channel"},
  {"WHITE_BALANCE_RED_V","white_balance_red_channel"},
  {"WB_TEMPERATURE","white_balance_temperature"},
  {"AUTO_WB","white_balance_automatic"}};
struct CtrlInfo{int min=0,max=0,def=0;bool declared=false;};
static std::map<std::string,std::map<std::string,CtrlInfo>>v4l2_cache;
std::map<std::string,CtrlInfo>get_v4l2_controls(const std::string&dev_path){
  auto it=v4l2_cache.find(dev_path);if(it!=v4l2_cache.end())return it->second;
  std::map<std::string,CtrlInfo>ctrls;
  std::string cmd="v4l2-ctl -d "+dev_path+" --list-ctrls 2>/dev/null";
  FILE*fp=popen(cmd.c_str(),"r");if(fp){
    char buf[4096];
    static const std::regex re(R"(\s*([a-zA-Z0-9_]+)\s+0x[0-9a-fA-F]+\s+\((\w+)\)\s*:(.*))");
    while(fgets(buf,sizeof(buf),fp)){
      std::string line(buf);std::smatch m;
      if(!std::regex_search(line,m,re))continue;
      CtrlInfo info;info.declared=true;std::string rest=m.str(3);
      auto grab=[&](const char*k)->int{
        std::smatch mm;
        if(std::regex_search(rest,mm,std::regex(std::string("\\b")+k+"=(-?\\d+)")))return std::stoi(mm.str(1));
        return 0;};
      info.min=grab("min");info.max=grab("max");info.def=grab("default");
      ctrls[m.str(1)]=info;
      std::string lower=m.str(1);std::transform(lower.begin(),lower.end(),lower.begin(),::tolower);
      ctrls[lower]=info;}
    pclose(fp);}
  v4l2_cache[dev_path]=ctrls;return ctrls;}
bool has_v4l2_ctl(){return system("which v4l2-ctl > /dev/null 2>&1")==0;}
void test_full_sweep(Suite&s,const std::string&backend,const std::string&device){
  if(!s.cap.isOpened()){
    s.add("F","CAP_PROP_* full sweep",SKIP,
          "capture already closed before sweep (ordering bug)");
    return;}
  for(size_t i=0;i<camprops::PROP_TABLE_N;++i){
    const auto&e=camprops::PROP_TABLE[i];std::string api=e.name;
    const char*label=camprops::FAMILY_LABELS[e.fam];
    if(!family_applicable(camprops::FAMILY_TOKENS[e.fam],backend)){
      s.add("F",api,SKIP,std::string("by-design: ")+label+"-only property, backend="+backend);continue;}
    double val=safe_get(s.cap,e.pid);
    if(val<=-1e8){s.add("F",api,SKIP,"get() raised or NaN");continue;}
    bool is_sentinel=(val==-1.0);
    std::string name=e.name;bool blacklisted=e.no_set;
    if(!blacklisted&&(name=="SETTINGS"||name=="GUID"||name=="POS_MSEC"||name=="POS_FRAMES"||name=="POS_AVI_RATIO"||name=="FRAME_COUNT"))blacklisted=true;
    if(is_sentinel){
      std::string dev_path=device;
      if(!dev_path.empty()&&dev_path.find_first_not_of("0123456789")==std::string::npos)dev_path="/dev/video"+dev_path;
      std::string short_name=name.rfind("CAP_PROP_",0)==0?name.substr(9):name;
      auto it=CAP_TO_V4L2.find(short_name);
      if(it!=CAP_TO_V4L2.end()&&has_v4l2_ctl()){
        auto ctrls=get_v4l2_controls(dev_path);
        std::string lower_key=it->second;
        std::transform(lower_key.begin(),lower_key.end(),lower_key.begin(),::tolower);
        if(ctrls.count(lower_key)){
          if(!s.cap.isOpened()){
            s.add("F",api,SKIP,"get()=-1 (capture closed mid-sweep)");continue;}
          s.add("F",api,WARN,"driver declared '"+it->second+"' but get()=-1 (possible driver bug, check dmesg)");continue;}
        else{s.add("F",api,SKIP,"unsupported (get()=-1, not declared by driver '"+it->second+"')");continue;}}
      s.add("F",api,SKIP,"unsupported (get()=-1 sentinel)");continue;}
    if(blacklisted){s.add("F",api,PASS,"get()="+std::to_string(val));continue;}
    bool set_ok=safe_set(s.cap,e.pid,val);
    if(!set_ok){
      if(std::fabs(val)>1e-9)s.add("F",api,PASS,"get()="+std::to_string(val)+"; set rejected (read-only)");
      else s.add("F",api,SKIP,"unsupported (get=0, set rejected)");continue;}
    double got=safe_get(s.cap,e.pid);
    if(got<=-1e8){s.add("F",api,WARN,"set accepted but get() failed");continue;}
    if(std::fabs(got-val)>std::max(1e-6,std::fabs(val)*1e-6))
      s.add("F",api,WARN,"roundtrip drift: "+std::to_string(val)+" -> "+std::to_string(got));
    else if(std::fabs(val)<=1e-9){
      // Current value is 0: writing 0 back proves nothing.  If the driver
      // declares this control, probe with a non-zero in-range value.
      bool handled=false;
      std::string short_name2=name.rfind("CAP_PROP_",0)==0?name.substr(9):name;
      auto it2=CAP_TO_V4L2.find(short_name2);
      std::string dev_path=device;
      if(!dev_path.empty()&&dev_path.find_first_not_of("0123456789")==std::string::npos)dev_path="/dev/video"+dev_path;
      auto ctrls=has_v4l2_ctl()?get_v4l2_controls(dev_path):std::map<std::string,CtrlInfo>{};
      if(it2!=CAP_TO_V4L2.end()&&!ctrls.empty()){
        std::string lower_key=it2->second;
        std::transform(lower_key.begin(),lower_key.end(),lower_key.begin(),::tolower);
        auto ci=ctrls.find(lower_key);
        if(ci==ctrls.end()){
          s.add("F",api,SKIP,"unsupported (get=0 set noop, not declared by driver '"+it2->second+"')");handled=true;}
        else{
          int probe=ci->second.def?ci->second.def:(ci->second.max>0?ci->second.max:ci->second.min);
          if(probe){
            bool pok=safe_set(s.cap,e.pid,(double)probe);
            double got2=pok?safe_get(s.cap,e.pid):-1e9;
            bool changed=got2>-1e8&&std::fabs(got2-(double)probe)<=std::max(1e-6,std::fabs((double)probe)*1e-6);
            safe_set(s.cap,e.pid,val);
            if(changed){s.add("F",api,PASS,"probe roundtrip 0 -> "+std::to_string(probe)+" (restored)");handled=true;}
            else{s.add("F",api,WARN,"no-op roundtrip (0->0); driver declares '"+it2->second+"' but write has no effect");handled=true;}}}
        if(!handled)s.add("F",api,WARN,"no-op roundtrip (0->0); support unproven");
        handled=true;}
      if(!handled)s.add("F",api,WARN,"no-op roundtrip (0->0); support unproven");}
    else s.add("F",api,PASS,"roundtrip "+std::to_string(val));}}
void backend_matrix(Suite&s,const std::string&dev,const std::string&want_backend){
  negative_open(s);open_only_precheck(s,dev,cv::CAP_V4L2);
  const int sel_bid=(want_backend=="ANY")?cv::CAP_V4L2:backend_id(want_backend);
  const std::string sel_name=(want_backend=="ANY")?"V4L2":want_backend;
  auto probe=[&](int bid,std::string&name)->bool{VideoCapture c;
    try{if(dev.find_first_not_of("0123456789")==std::string::npos)c.open(std::stoi(dev),bid);else c.open(dev,bid);
      if(!c.isOpened())return false;name=c.getBackendName();return true;}catch(...){return false;}};
  std::string n_any,n_sel;bool ok_any=probe(cv::CAP_ANY,n_any);bool ok_sel=probe(sel_bid,n_sel);
  if(!ok_any||!ok_sel){s.add("B","backend ANY vs V4L2",SKIP,
      std::string("device must open under both (ANY=")+(ok_any?"y":"n")+
      ", "+sel_name+"="+(ok_sel?"y":"n")+")");return;}
  if(n_any==n_sel)
    s.add("B","backend ANY vs V4L2",PASS,"consistent backend via ANY and "+sel_name+": "+n_any);
  else if(want_backend=="ANY")
    s.add("B","backend ANY vs V4L2",WARN,"divergence: CAP_ANY resolves to "+n_any+", CAP_"+sel_name+" to "+n_sel);
  else
    s.add("B","backend ANY vs V4L2",PASS,"note: CAP_ANY resolves to "+n_any+", explicit "+sel_name+
          " to "+n_sel+" (run unaffected: explicit backend)");}
std::string escape_json(const std::string&in){std::string out;
  for(char ch:in){switch(ch){case'"':out+="\\\"";break;case'\\':out+="\\\\";break;case'\n':out+="\\n";break;case'\r':out+="\\r";break;case'\t':out+="\\t";break;
  default:if((unsigned char)ch<0x20)out+="?";else out+=ch;}}return out;}
struct Metrics{
  int pass=0,fail=0,warn=0,skip=0,total=0;
  int core_pass=0,core_skip=0,core_rows=0;
  int core_total=0,core_executed=0;   // distinct (group,api), excluding [F]
  int f_pass=0,f_fail=0,f_warn=0,f_skip=0,f_total=0;};
Metrics build_metrics(const std::vector<Result>&rows){
  Metrics m;m.total=(int)rows.size();
  std::set<std::pair<std::string,std::string>>ckey,ekey;
  for(auto&r:rows){
    bool isF=(r.group=="F");
    if(r.status==PASS)++m.pass;else if(r.status==FAIL)++m.fail;
    else if(r.status==WARN)++m.warn;else ++m.skip;
    if(isF){if(r.status==PASS)++m.f_pass;else if(r.status==FAIL)++m.f_fail;
      else if(r.status==WARN)++m.f_warn;else ++m.f_skip;}
    else{++m.core_rows;if(r.status==PASS)++m.core_pass;if(r.status==SKIP)++m.core_skip;
      ckey.insert({r.group,r.api});
      if(r.status==PASS||r.status==FAIL)ekey.insert({r.group,r.api});}}
  m.core_total=(int)ckey.size();m.core_executed=(int)ekey.size();
  m.f_total=m.f_pass+m.f_fail+m.f_warn+m.f_skip;
  return m;}
static double pct(int a,int b){return b>0?100.0*a/b:0.0;}
std::string get_opencv_source_label(){
#ifdef OPENCV_SOURCE_LABEL
  return OPENCV_SOURCE_LABEL;
#else
  const char*s=std::getenv("CPP_OPENCV_SOURCE");if(s)return s;return "apt";
#endif
}
void write_json(const Suite&s,const std::string&path,const std::string&device,
                const std::string&backend,int frames,const Metrics&m){
  size_t core_total=m.core_total;int executed=m.core_executed;
  std::string src=get_opencv_source_label();std::string ver=CV_VERSION;
  std::ofstream f(path);
  f<<"{\n  \"meta\": {\"device\": \""<<escape_json(device)<<"\", \"backend\": \""<<backend
    <<"\", \"frames\": "<<frames<<", \"tool\": \"opencv_camera_api_test_cpp\","
    <<" \"opencv_version\": \""<<ver<<"\", \"opencv_source\": \""<<src<<"\"},\n";
  f<<"  \"summary\": {\"PASS\": "<<m.pass<<", \"FAIL\": "<<m.fail<<", \"WARN\": "<<m.warn
    <<", \"SKIP\": "<<m.skip<<", \"total_checks\": "<<s.rows.size()
    <<", \"executed\": "<<executed<<", \"core_total\": "<<core_total;
  f<<", \"pass_rate_percent\": "<<pct(m.pass,m.total)
    <<", \"pass_rate_excl_skip_percent\": "<<pct(m.pass,m.total-m.skip)
    <<", \"core_pass_rate_percent\": "<<pct(m.core_pass,m.core_rows)
    <<", \"core_pass_rate_excl_skip_percent\": "<<pct(m.core_pass,m.core_rows-m.core_skip)
    <<", \"sweep_f_total\": "<<m.f_total
    <<", \"sweep_f_pass_rate_percent\": "<<pct(m.f_pass,m.f_total)
    <<", \"sweep_f_pass_rate_excl_skip_percent\": "<<pct(m.f_pass,m.f_pass+m.f_fail)
    <<"},\n";
  f<<"  \"environment\": {\"opencv_version\": \""<<ver<<"\", \"opencv_source\": \""<<src<<"\"},\n";
  f<<"  \"results\": [\n";
  for(size_t i=0;i<s.rows.size();++i){auto&r=s.rows[i];
    f<<"    {\"group\": \""<<escape_json(r.group)<<"\", \"api\": \""<<escape_json(r.api)
      <<"\", \"status\": \""<<r.status<<"\", \"message\": \""<<escape_json(r.message)<<"\"}"
      <<(i+1<s.rows.size()?",":"")<<"\n";}
  f<<"  ]\n}\n";}
} // namespace
struct Args{std::string device="/dev/video0";std::string backend="V4L2";int frames=30;
  bool list_only=false;bool no_full_sweep=false;std::string outdir="./report/new";};
Args parse_args(int argc,char**argv){Args a;
  for(int i=1;i<argc;++i){std::string arg=argv[i];
    auto next=[&]()->std::string{return(i+1<argc)?argv[++i]:"";};
    if(arg=="--device")a.device=next();else if(arg=="--backend")a.backend=next();
    else if(arg=="--frames")a.frames=atoi(next().c_str());else if(arg=="--outdir")a.outdir=next();
    else if(arg=="--list-only")a.list_only=true;else if(arg=="--no-full-sweep")a.no_full_sweep=true;
    else if(arg=="--help"||arg=="-h"){std::cout<<"Usage: opencv_camera_api_test_cpp [options]\n"
      "  --device PATH|N     camera node\n  --backend NAME      backend\n  --frames N          read-loop frames\n"
      "  --outdir DIR        report dir\n  --list-only         print inventory\n  --no-full-sweep     skip F group\n";exit(0);}}
  return a;}
void print_inventory(){std::cout<<bold("OpenCV Camera API Test (C++) inventory")<<"\n";
  std::cout<<"opencv : "<<CV_VERSION<<"\n";auto planned=planned_items();char cur=0;
  for(auto&item:planned){if(item.first!=cur){cur=item.first;std::cout<<cyan("\n["+std::string(1,cur)+"]")<<"\n";}std::cout<<"    - "<<item.second<<"\n";}
  std::cout<<"\nCAP_PROP table: "<<camprops::PROP_TABLE_N<<"\n";}
int main(int argc,char**argv){
  Args args=parse_args(argc,argv);
  cv::utils::logging::setLogLevel(cv::utils::logging::LOG_LEVEL_ERROR);
  if(args.list_only){print_inventory();return 0;}
  g_color=isatty(1);Suite s;
  std::cout<<bold("OpenCV Camera API Test (C++)")<<"\n  device="<<args.device
    <<" backend="<<args.backend<<" frames="<<args.frames<<" outdir="<<args.outdir<<"\n";
  std::cout<<bold("\n== [A] Environment ==")<<"\n";env_check(s,args.backend);
  std::cout<<bold("\n== [B] Lifecycle ==")<<"\n";int bid=backend_id(args.backend);
  try{if(args.device.find_first_not_of("0123456789")==std::string::npos)
      s.cap.open(std::stoi(args.device),api_cast(bid));
    else s.cap.open(args.device,api_cast(bid));
  }catch(const std::exception&e){s.add("B","VideoCapture(device, backend)",FAIL,e.what());}
  s.add("B","VideoCapture(device, backend)",s.cap.isOpened()?PASS:FAIL,s.cap.isOpened()?"":"open failed");
  bool opened=s.cap.isOpened();
  if(opened){s.add("B","open()",PASS,"");
    s.observed["width"]=safe_get(s.cap,cv::CAP_PROP_FRAME_WIDTH);
    s.observed["height"]=safe_get(s.cap,cv::CAP_PROP_FRAME_HEIGHT);
    s.observed["fps"]=safe_get(s.cap,cv::CAP_PROP_FPS);
    double fcc=safe_get(s.cap,cv::CAP_PROP_FOURCC);
    s.observed_fourcc=fcc<=-1e8?"":fourcc_to_str((int)fcc);
    s.add("B","isOpened()",PASS,"stream ready ("+std::to_string((int)s.observed["width"])+"x"+std::to_string((int)s.observed["height"])+"@"+s.observed_fourcc+")");}
  else{s.add("B","open()",FAIL,"returned false");s.add("B","isOpened()",FAIL,"stream not ready");}
  if(!opened)skip_rest(s,"camera failed to open");
  else{capture_extras(s);test_properties(s);lifecycle_reads(s,args.frames);frame_quality(s);
    v4l2_crosscheck(s,args.device);os_mkdir(args.outdir);test_writer(s,args.outdir);
    test_capture_open_overloads(s,args.device,args.outdir);
    test_writer_overloads(s,args.outdir);
    // [F] must run while the capture is still open: get()/set() on a
    // released cap returns -1 and poisons the whole sweep.
    if(!args.no_full_sweep)test_full_sweep(s,args.backend,args.device);
    else s.add("F","CAP_PROP_* full sweep",SKIP,"--no-full-sweep given");
    try{s.cap.release();s.add("B","release()",!s.cap.isOpened()?PASS:WARN,"");}catch(...){s.add("B","release()",WARN,"raised");}
    backend_matrix(s,args.device,args.backend);}
  Metrics m=build_metrics(s.rows);
  std::cout<<"\n"<<bold(std::string(64,'='))<<"\n"<<bold("SUMMARY")<<"\n"<<bold(std::string(64,'='))<<"\n";
  std::cout<<"  PASS  : "<<green(std::to_string(m.pass))<<dim("   (incl. F-sweep & extra checks)")<<"\n";
  std::cout<<"  FAIL  : "<<red(std::to_string(m.fail))<<"\n";
  std::cout<<"  WARN  : "<<yellow(std::to_string(m.warn))<<"\n";
  std::cout<<"  SKIP  : "<<dim(std::to_string(m.skip))<<dim("   (by-design / unsupported)")<<"\n";
  std::cout<<dim("  ----------------------------------------")<<"\n";
  std::cout<<"  total : "<<m.total<<"\n";
  char buf1[16],buf2[16],buf3[16],buf4[16],buf5[16],buf6[16];
  snprintf(buf1,sizeof(buf1),"%.1f",pct(m.pass,m.total));
  snprintf(buf2,sizeof(buf2),"%.1f",pct(m.pass,m.total-m.skip));
  snprintf(buf3,sizeof(buf3),"%.1f",pct(m.core_pass,m.core_rows));
  snprintf(buf4,sizeof(buf4),"%.1f",pct(m.core_pass,m.core_rows-m.core_skip));
  snprintf(buf5,sizeof(buf5),"%.1f",pct(m.f_pass,m.f_total));
  snprintf(buf6,sizeof(buf6),"%.1f",pct(m.f_pass,m.f_pass+m.f_fail));
  std::cout<<"  pass rate (all)       : "<<bold(std::string(buf1)+"%")
           <<" (PASS "<<m.pass<<" / total "<<m.total<<")\n";
  std::cout<<"  pass rate (excl SKIP) : "<<bold(std::string(buf2)+"%")
           <<" (PASS "<<m.pass<<" / "<<(m.total-m.skip)<<")\n";
  std::cout<<"  core (excl [F])       : "<<bold(std::string(buf3)+"%")<<" all | "
           <<bold(std::string(buf4)+"%")<<" excl SKIP"
           <<" (planned "<<m.core_total<<", executed "<<m.core_executed<<")\n";
  std::cout<<"  sweep [F]             : "<<bold(std::string(buf5)+"%")<<" all | "
           <<bold(std::string(buf6)+"%")<<" excl SKIP"
           <<" (WARN "<<m.f_warn<<", SKIP "<<m.f_skip<<", total "<<m.f_total<<")\n";
  std::cout<<"  opencv_version : "<<CV_VERSION<<"\n";
  std::cout<<"  opencv_source  : "<<get_opencv_source_label()<<"\n";
  std::cout<<"  reports : "<<args.outdir<<"/report_cpp.json\n";
  write_json(s,args.outdir+"/report_cpp.json",args.device,args.backend,args.frames,m);
  bool camera_missing=!s.camera_ok&&m.fail==0&&m.pass<=6;
  if(m.fail>0)return 1;if(camera_missing)return 2;return 0;}
