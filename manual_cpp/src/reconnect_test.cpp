// reconnect_test.cpp - standalone USB reconnect helper (C++ port of usb_unplug_reconnect_test.py)
#include "manual_utils.hpp"
#include <iostream>
#include <filesystem>
#include <chrono>
#include <thread>
#include <fstream>
namespace fs=std::filesystem;
int main(int argc,char*argv[]){
    std::cout<<std::unitbuf; // live progress under pipes (reconnect window)
    std::string device="/dev/video0", backend="V4L2", outdir="./reconnect_report";
    double max_duration=30; int fail_thresh=5, good_needed=3; double retry=1.0;
    for(int i=1;i<argc;++i){
        std::string a=argv[i]; auto nxt=[&](){return (i+1<argc)?argv[++i]:"";};
        if(a=="--device") device=nxt();
        else if(a=="-d") device=nxt();
        else if(a=="--backend") backend=nxt();
        else if(a=="--max-duration") max_duration=std::stod(nxt());
        else if(a=="--outdir") outdir=nxt();
        else if(a=="--fail-threshold") fail_thresh=std::stoi(nxt());
    }
    fs::create_directories(outdir);
    auto start=std::chrono::steady_clock::now();
    auto elapsed=[&](){return std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();};
    std::ofstream ej(outdir+"/events.jsonl"), sj(outdir+"/summary.json");
    cv::VideoCapture cap; int fails=0, good=0, attempts=0, frames_ok=0, exceptions=0;
    double last_good=elapsed(); std::string state="RECONNECTING";
    auto log=[&](const std::string& ev){ std::cout<<"["<<elapsed()<<"s] "<<ev<<"\n"; ej<<"{\"t\":"<<elapsed()<<",\"event\":\""<<ev<<"\"}\n"<<std::flush; };
    log("state to RECONNECTING");
    while(elapsed()<max_duration){
        if(state=="RECONNECTING"||state=="LOST"){
            state="RECONNECTING"; attempts++; log("open_attempt n="+std::to_string(attempts));
            cap=manual::open_cam(device,backend);
            if(!cap.isOpened()){ state="LOST"; std::this_thread::sleep_for(std::chrono::duration<double>(retry)); continue;}
            state="RECOVERING"; good=0; continue;
        }
        cv::Mat f; bool ok=false;
        try{ ok=cap.read(f)&&!f.empty(); }catch(...){ ok=false; exceptions++; log("read_exception"); }
        if(ok){
            fails=0; good++; last_good=elapsed();
            if(state=="RECOVERING"){
                if(good>=good_needed){ state="CONNECTED"; log("stream_established"); }
                else log("recovering_frame");
            } else { frames_ok++; if(frames_ok%100==0) log("alive frames="+std::to_string(frames_ok)); }
            continue;
        }
        if(state=="RECOVERING"){ log("recover_failed_frame"); cap.release(); state="RECONNECTING"; std::this_thread::sleep_for(std::chrono::duration<double>(retry)); continue;}
        fails++; if(state=="CONNECTED"&&fails>=fail_thresh){ log("disconnect_detected"); state="RECONNECTING"; }
        else if(state!="CONNECTED"){ state="LOST"; std::this_thread::sleep_for(std::chrono::duration<double>(retry));}
    }
    cap.release();
    sj<<"{\"device\":\""<<device<<"\",\"duration_s\":"<<elapsed()<<",\"frames_captured\":"<<frames_ok<<",\"exception_count\":"<<exceptions<<"}\n";
    std::cout<<"summary: frames="<<frames_ok<<" exceptions="<<exceptions<<"\n";
    return exceptions?1:0;
}
