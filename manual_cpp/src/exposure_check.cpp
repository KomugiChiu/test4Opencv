// exposure_check.cpp - standalone helper for exposure_visual_check
#include "manual_utils.hpp"
#include <iostream>
#include <filesystem>
namespace fs = std::filesystem;
int main(int argc, char* argv[]) {
    std::cout<<std::unitbuf; // live sweep progress under pipes
    std::string device="/dev/video0", backend="V4L2", values="10,50,100,200,400";
    std::string command="sweep", outdir="./exp_check";
    int frames=12, settle_n=8;
    for(int i=1;i<argc;++i){
        std::string a=argv[i]; auto nxt=[&](){return (i+1<argc)?argv[++i]:"";};
        if(a=="-d"||a=="--device") device=nxt();
        else if(a=="--backend") backend=nxt();
        else if(a=="--values") values=nxt();
        else if(a=="--value") values=nxt();
        else if(a=="--outdir") outdir=nxt();
        else if(a=="status"||a=="auto"||a=="manual"||a=="sweep") command=a;
    }
    fs::create_directories(outdir);
    auto cap = manual::open_cam(device, backend);
    if(!cap.isOpened()){ std::cerr<<"cannot open "<<device<<"\n"; return 1; }
    if(command=="status"){
        double ae=cap.get(cv::CAP_PROP_AUTO_EXPOSURE), ex=cap.get(cv::CAP_PROP_EXPOSURE);
        std::cout<<"AUTO_EXPOSURE="<<ae<<" EXPOSURE="<<ex<<"\n";
        auto m=manual::measure_brightness(cap,6);
        std::cout<<"brightness mean="<<m.mean<<" +/-"<<m.stddev<<"\n";
    } else if(command=="sweep"){
        cap.set(cv::CAP_PROP_AUTO_EXPOSURE,1);
        auto vals=manual::parse_values(values);
        std::cout<<"[";
        for(size_t i=0;i<vals.size();++i){
            double v=vals[i];
            cap.set(cv::CAP_PROP_EXPOSURE,v);
            manual::settle(cap,settle_n);
            std::string save=(fs::path(outdir)/("exp_manual_"+std::to_string((int)v)+".jpg")).string();
            auto m=manual::measure_brightness(cap,frames,save);
            double ae=cap.get(cv::CAP_PROP_AUTO_EXPOSURE), ex=cap.get(cv::CAP_PROP_EXPOSURE);
            std::cout<<(i?",":"")<<"{\"mode\":\"MANUAL\",\"requested\":"<<v<<",\"brightness_mean\":"<<m.mean<<",\"get_EXPOSURE\":"<<ex<<"}";
        }
        std::cout<<"]\n";
        cap.set(cv::CAP_PROP_AUTO_EXPOSURE,3);
    }
    return 0;
}
