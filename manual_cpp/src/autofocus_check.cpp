// autofocus_check.cpp - standalone helper for autofocus_visual_check
#include "manual_utils.hpp"
#include <iostream>
#include <filesystem>
namespace fs=std::filesystem;
int main(int argc,char*argv[]){
    std::string device="/dev/video0", backend="V4L2", values="0,80,160,250", outdir="./focus_check";
    std::string command="focus";
    for(int i=1;i<argc;++i){
        std::string a=argv[i]; auto nxt=[&](){return (i+1<argc)?argv[++i]:"";};
        if(a=="-d"||a=="--device") device=nxt();
        else if(a=="--backend") backend=nxt();
        else if(a=="--values") values=nxt();
        else if(a=="--outdir") outdir=nxt();
        else if(a=="status"||a=="focus"||a=="zoom"||a=="pantilt"||a=="autofocus") command=a;
    }
    fs::create_directories(outdir);
    auto cap=manual::open_cam(device,backend);
    if(!cap.isOpened()){ std::cerr<<"cannot open "<<device<<"\n"; return 1;}
    if(command=="status"){
        std::cout<<"AUTOFOCUS="<<cap.get(cv::CAP_PROP_AUTOFOCUS)<<" FOCUS="<<cap.get(cv::CAP_PROP_FOCUS)<<" ZOOM="<<cap.get(cv::CAP_PROP_ZOOM)<<"\n";
        auto m=manual::measure_sharpness(cap, cv::Mat(),10);
        std::cout<<"sharpness "<<m.lapvar<<"\n";
    } else if(command=="focus"){
        cap.set(cv::CAP_PROP_AUTOFOCUS,0);
        auto vals=manual::parse_values(values);
        cv::Mat ref; cap.read(ref); cv::Mat rg; if(!ref.empty()) cv::cvtColor(ref,rg,cv::COLOR_BGR2GRAY);
        std::cout<<"[";
        for(size_t i=0;i<vals.size();++i){
            double v=vals[i]; cap.set(cv::CAP_PROP_FOCUS,v); manual::settle(cap,6);
            std::string save=(fs::path(outdir)/("FOCUS_"+std::to_string((int)v)+".jpg")).string();
            auto m=manual::measure_sharpness(cap,rg,10,save);
            std::cout<<(i?",":"")<<"{\"FOCUS\":"<<v<<",\"sharpness\":"<<m.lapvar<<"}";
        }
        std::cout<<"]\n";
        cap.set(cv::CAP_PROP_AUTOFOCUS,1);
    } else if(command=="zoom"){
        auto vals=manual::parse_values(values);
        cv::Mat ref; cap.read(ref); cv::Mat rg; if(!ref.empty()) cv::cvtColor(ref,rg,cv::COLOR_BGR2GRAY);
        std::cout<<"[";
        for(size_t i=0;i<vals.size();++i){
            double v=vals[i]; cap.set(cv::CAP_PROP_ZOOM,v); manual::settle(cap,6);
            std::string save=(fs::path(outdir)/("ZOOM_"+std::to_string((int)v)+".jpg")).string();
            auto m=manual::measure_sharpness(cap,rg,10,save);
            std::cout<<(i?",":"")<<"{\"ZOOM\":"<<v<<",\"sharpness\":"<<m.lapvar<<"}";
        }
        std::cout<<"]\n";
    }
    return 0;
}
