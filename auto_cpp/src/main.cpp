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
    {'B',"VideoCapture(device, backend)"},{'B',"open()"},{'B',"isOpened()"},{'B',"getBackendName()"},
    {'B',"exception mode toggle"},{'B',"waitAny()"},{'B',"negative open case"},
    {'B',"open-only params precheck"},{'B',"backend ANY vs V4L2"},
    {'B',"grab()"},{'B',"retrieve()"},{'B',"read loop"},{'B',"release()"}};
  for(const char*n:{"FRAME_WIDTH","FRAME_HEIGHT","FPS","FOURCC","BUFFERSIZE","AUTO_EXPOSURE","EXPOSURE","GAIN","FORMAT","MODE","CONVERT_RGB"})
    v.push_back({'C',std::string("CAP_PROP_")+n+" get/set"});
  for(const char*n:{"frame not None","frame dimensions","pixel variance","freeze detection"})v.push_back({'D',n});
  v.push_back({'E',"VideoWriter.fourcc()"});v.push_back({'E',"VideoWriter(path, fourcc, fps, size)"});
  v.push_back({'E',"writer.isOpened()"});v.push_back({'E',"writer.getBackendName()"});
  v.push_back({'E',"writer.get(VIDEOWRITER_PROP_*)"});v.push_back({'E',"writer.set(VIDEOWRITER_PROP_*)"});
  v.push_back({'E',"writer.write()"});v.push_back({'E',"writer.release()"});v.push_back({'E',"VideoWriter readback"});
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
  s.add("A","build: V4L support",flag("v4l/v4l2")=="YES"?PASS:(backend=="V4L2"?FAIL:WARN),"v4l/v4l2="+flag("v4l/v4l2"));
  s.add("A","build: GStreamer support",flag("GStreamer")=="YES"?PASS:(backend=="GSTREAMER"?FAIL:WARN),"GStreamer="+flag("GStreamer"));
  try{auto ids=cv::videoio_registry::getBackends();std::string names;
    for(auto id:ids)names+=(names.empty()?"":", ")+cv::videoio_registry::getBackendName(id);
    s.add("A","registry.getBackends()",names.empty()?FAIL:PASS,names);
    if(!ids.empty())s.add("A","registry.getBackendName()",PASS,cv::videoio_registry::getBackendName(ids.front()));
    else s.add("A","registry.getBackendName()",SKIP,"no backends");
    int target=backend_id(backend=="ANY"?"V4L2":backend);
    s.add("A","registry.hasBackend(target)",cv::videoio_registry::hasBackend(api_cast(target))?PASS:WARN,"target="+(backend=="ANY"?std::string("V4L2"):backend));
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
  const std::pair<int,int>props[]={{cv::CAP_PROP_HW_ACCELERATION,0},{cv::CAP_PROP_HW_DEVICE,0},
#if defined(CAP_PROP_HW_ACCELERATION_USE_OPENCL)
      {cv::CAP_PROP_HW_ACCELERATION_USE_OPENCL,0},
#endif
      {cv::CAP_PROP_OPEN_TIMEOUT_MSEC,5000},{cv::CAP_PROP_READ_TIMEOUT_MSEC,5000}};
  std::vector<int>params;for(auto&pr:props){params.push_back(pr.first);params.push_back(pr.second);}
  VideoCapture cap;bool raised=false,opened=false;std::string err;
  try{
    if(dev.find_first_not_of("0123456789")==std::string::npos)cap.open(std::stoi(dev),api_cast(bid),params);
    else cap.open(dev,api_cast(bid),params);
    opened=cap.isOpened();
  }catch(const std::exception&e){raised=true;err=e.what();}
  cap.release();
  if(raised)s.add("B","open-only params precheck",WARN,"build rejects params with exception: "+err);
  else if(opened)s.add("B","open-only params precheck",PASS,"opened with "+std::to_string(sizeof(props)/sizeof(props[0]))+" params");
  else s.add("B","open-only params precheck",WARN,"params silently rejected");}
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
    bool ok=s.cap.set(c.pid,target);
    if(!ok){s.add("C",api,SKIP,"set() returned false");continue;}
    double got=safe_get(s.cap,c.pid);
    if(got<=-1e8){s.add("C",api,WARN,"set accepted but get failed");continue;}
    std::string why;
    if(compare(c.mode,target,got,c.tol,why))s.add("C",api,PASS,"");
    else s.add("C",api,WARN,"readback differs: "+why);
    if(c.mode!=std::string("roundtrip"))s.cap.set(c.pid,orig);}}
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
        std::to_string(ok_count)+"/"+std::to_string(frames_wanted)+" frames, "+std::to_string(s.measured_fps).substr(0,5)+" FPS");}
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
    "writer.get(VIDEOWRITER_PROP_*)","writer.set(VIDEOWRITER_PROP_*)","writer.write()","writer.release()","VideoWriter readback","VIDEOWRITER_PROP_* inventory"})
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
  bool q_ok=(q_pid>=0)&&writer.set(q_pid,90);
  s.add("E","writer.set(VIDEOWRITER_PROP_*)",q_ok?PASS:SKIP,q_ok?"QUALITY=90":"rejected");
  int written=0;for(auto&f:s.frames)writer.write(f);
  written=(int)s.frames.size();
  s.add("E","writer.write()",written>0?PASS:FAIL,std::to_string(written)+" frames written");
  writer.release();
  s.add("E","writer.release()",!writer.isOpened()?PASS:WARN,"");
  VideoCapture back(path);Mat decoded;bool ok=back.isOpened()&&back.read(decoded);back.release();
  s.add("E","VideoWriter readback",ok?PASS:FAIL,ok?("decoded "+std::to_string(decoded.cols)+"x"+std::to_string(decoded.rows)):"decode failed");}
static std::map<std::string,std::string>CAP_TO_V4L2={
  {"BRIGHTNESS","brightness"},{"CONTRAST","contrast"},{"SATURATION","saturation"},
  {"HUE","hue"},{"GAIN","gain"},{"EXPOSURE","exposure_absolute"},
  {"AUTO_EXPOSURE","exposure_auto"},{"SHARPNESS","sharpness"},{"GAMMA","gamma"},
  {"BACKLIGHT","backlight_compensation"},{"FOCUS","focus_absolute"},
  {"AUTOFOCUS","focus_auto"},{"ZOOM","zoom_absolute"},{"PAN","pan_absolute"},
  {"TILT","tilt_absolute"},{"WHITE_BALANCE_BLUE_U","white_balance_temperature"},
  {"WHITE_BALANCE_RED_V","white_balance_temperature"},{"WB_TEMPERATURE","white_balance_temperature"},
  {"AUTO_WB","white_balance_automatic"}};
static std::map<std::string,std::set<std::string>>v4l2_cache;
std::set<std::string>get_v4l2_controls(const std::string&dev_path){
  auto it=v4l2_cache.find(dev_path);if(it!=v4l2_cache.end())return it->second;
  std::set<std::string>names;
  std::string cmd="v4l2-ctl -d "+dev_path+" --list-ctrls 2>/dev/null";
  FILE*fp=popen(cmd.c_str(),"r");if(!fp){v4l2_cache[dev_path]=names;return names;}
  char buf[4096];
  while(fgets(buf,sizeof(buf),fp)){
    std::string line(buf);std::regex re(R"(\s*([a-zA-Z0-9_]+)\s+0x[0-9a-fA-F]+\s+\()");
    std::smatch m;if(std::regex_search(line,m,re))names.insert(m.str(1));}
  pclose(fp);
  std::set<std::string>lower;for(auto&n:names){std::string l=n;std::transform(l.begin(),l.end(),l.begin(),::tolower);lower.insert(l);}
  v4l2_cache[dev_path]=lower;return lower;}
bool has_v4l2_ctl(){return system("which v4l2-ctl > /dev/null 2>&1")==0;}
void test_full_sweep(Suite&s,const std::string&backend,const std::string&device){
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
          s.add("F",api,WARN,"driver declared '"+it->second+"' but get()=-1 (possible driver bug, check dmesg)");continue;}
        else{s.add("F",api,SKIP,"unsupported (get()=-1, not declared by driver '"+it->second+"')");continue;}}
      s.add("F",api,SKIP,"unsupported (get()=-1 sentinel)");continue;}
    if(blacklisted){s.add("F",api,PASS,"get()="+std::to_string(val));continue;}
    bool set_ok=s.cap.set(e.pid,val);
    if(!set_ok){
      if(std::fabs(val)>1e-9)s.add("F",api,PASS,"get()="+std::to_string(val)+"; set rejected (read-only)");
      else s.add("F",api,SKIP,"unsupported (get=0, set rejected)");continue;}
    double got=safe_get(s.cap,e.pid);
    if(got<=-1e8){s.add("F",api,WARN,"set accepted but get() failed");continue;}
    if(std::fabs(got-val)>std::max(1e-6,std::fabs(val)*1e-6))
      s.add("F",api,WARN,"roundtrip drift: "+std::to_string(val)+" -> "+std::to_string(got));
    else if(std::fabs(val)<=1e-9)s.add("F",api,WARN,"no-op roundtrip (0->0)");
    else s.add("F",api,PASS,"roundtrip "+std::to_string(val));}}
void backend_matrix(Suite&s,const std::string&dev){
  negative_open(s);open_only_precheck(s,dev,cv::CAP_V4L2);
  auto probe=[&](int bid,std::string&name)->bool{VideoCapture c;
    try{if(dev.find_first_not_of("0123456789")==std::string::npos)c.open(std::stoi(dev),bid);else c.open(dev,bid);
      if(!c.isOpened())return false;name=c.getBackendName();return true;}catch(...){return false;}};
  std::string n_any,n_v4l;bool ok_any=probe(cv::CAP_ANY,n_any);bool ok_v4l=probe(cv::CAP_V4L2,n_v4l);
  if(!ok_any||!ok_v4l){s.add("B","backend ANY vs V4L2",SKIP,"device must open under both");return;}
  if(n_any==n_v4l)s.add("B","backend ANY vs V4L2",PASS,"consistent: "+n_any);
  else s.add("B","backend ANY vs V4L2",WARN,"divergence: ANY->"+n_any+", V4L2->"+n_v4l);}
std::string escape_json(const std::string&in){std::string out;
  for(char ch:in){switch(ch){case'"':out+="\\\"";break;case'\\':out+="\\\\";break;case'\n':out+="\\n";break;case'\r':out+="\\r";break;case'\t':out+="\\t";break;
  default:if((unsigned char)ch<0x20)out+="?";else out+=ch;}}return out;}
std::string get_opencv_source_label(){
#ifdef OPENCV_SOURCE_LABEL
  return OPENCV_SOURCE_LABEL;
#else
  const char*s=std::getenv("CPP_OPENCV_SOURCE");if(s)return s;return "apt";
#endif
}
void write_json(const Suite&s,const std::string&path,const std::string&device,
                const std::string&backend,int frames){
  int pass=0,fail=0,warn=0,skip=0;
  for(auto&r:s.rows){if(r.status==PASS)++pass;else if(r.status==FAIL)++fail;else if(r.status==WARN)++warn;else ++skip;}
  size_t core_total=planned_items().size();int executed=pass+fail;
  std::string src=get_opencv_source_label();std::string ver=CV_VERSION;
  std::ofstream f(path);
  f<<"{\n  \"meta\": {\"device\": \""<<escape_json(device)<<"\", \"backend\": \""<<backend
    <<"\", \"frames\": "<<frames<<", \"tool\": \"opencv_camera_api_test_cpp\","
    <<" \"opencv_version\": \""<<ver<<"\", \"opencv_source\": \""<<src<<"\"},\n";
  f<<"  \"summary\": {\"PASS\": "<<pass<<", \"FAIL\": "<<fail<<", \"WARN\": "<<warn
    <<", \"SKIP\": "<<skip<<", \"total_checks\": "<<s.rows.size()
    <<", \"executed\": "<<executed<<", \"core_total\": "<<core_total<<"},\n";
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
    try{s.cap.release();s.add("B","release()",!s.cap.isOpened()?PASS:WARN,"");}catch(...){s.add("B","release()",WARN,"raised");}
    backend_matrix(s,args.device);
    if(!args.no_full_sweep)test_full_sweep(s,args.backend,args.device);
    else s.add("F","CAP_PROP_* full sweep",SKIP,"--no-full-sweep given");}
  int pass=0,fail=0,warn=0,skip=0;
  for(auto&r:s.rows){if(r.status==PASS)++pass;else if(r.status==FAIL)++fail;else if(r.status==WARN)++warn;else ++skip;}
  size_t core_total=planned_items().size();
  // Count only planned items that actually executed (PASS or FAIL)
  auto planned=planned_items();int planned_executed=0;
  for(auto&p:planned){for(auto&r:s.rows){if(r.api==p.second&&(r.status==PASS||r.status==FAIL)){++planned_executed;break;}}}
  int executed=planned_executed;
  double core_cov=core_total?100.0*executed/core_total:0.0;
  std::cout<<"\n"<<bold(std::string(64,'='))<<"\n"<<bold("SUMMARY")<<"\n"<<bold(std::string(64,'='))<<"\n";
  std::cout<<"  PASS  : "<<green(std::to_string(pass))
           <<dim("   (incl. F-sweep & extra checks)")<<"\n";
  std::cout<<"  FAIL  : "<<red(std::to_string(fail))<<"\n";
  std::cout<<"  WARN  : "<<yellow(std::to_string(warn))<<"\n";
  std::cout<<"  SKIP  : "<<dim(std::to_string(skip))
           <<dim("   (by-design / unsupported)")<<"\n";
  std::cout<<dim("  ----------------------------------------")<<"\n";
  std::cout<<"  total : "<<s.rows.size()<<"\n";
  int planned_skipped=0;
  for(auto&p:planned){
    bool found=false;
    for(auto&r:s.rows){if(r.api==p.second){found=true;
      if(r.status==SKIP)++planned_skipped;break;}}
    if(!found)++planned_skipped;}
  printf("  core coverage : %.1f%% (%d/%d planned executed, %d skipped)\n",
         core_cov,executed,(int)core_total,planned_skipped);
  printf("  passed ratio (all) : %.1f%% (%d/%d)\n",
         (pass+fail)?100.0*pass/(pass+fail):0.0,pass,pass+fail);
  std::cout<<"  opencv_version : "<<CV_VERSION<<"\n";
  std::cout<<"  opencv_source  : "<<get_opencv_source_label()<<"\n";
  std::cout<<"  reports : "<<args.outdir<<"/report_cpp.json\n";
  write_json(s,args.outdir+"/report_cpp.json",args.device,args.backend,args.frames);
  bool camera_missing=!s.camera_ok&&fail==0&&pass<=6;
  if(fail>0)return 1;if(camera_missing)return 2;return 0;}
