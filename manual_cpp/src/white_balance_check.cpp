// white_balance_check.cpp - standalone helper
#include "manual_utils.hpp"
#include <iostream>
#include <filesystem>
namespace fs=std::filesystem;
int main(int argc,char*argv[]){
    std::string device="/dev/video0", backend="V4L2", values="2500,4000,5500,6500", outdir="./wb_check";
    std::string command="temp";
    for(int i=1;i<argc;++i){
        std::string a=argv[i]; auto nxt=[&](){return (i+1<argc)?argv[++i]:"";};
        if(a=="-d"||a=="--device") device=nxt();
        else if(a=="--backend") backend=nxt();
        else if(a=="--values") values=nxt();
        else if(a=="--outdir") outdir=nxt();
        else if(a=="status"||a=="auto"||a=="temp") command=a;
    }
    fs::create_directories(outdir);
    auto cap=manual::open_cam(device,backend);
    if(!cap.isOpened()){ std::cerr<<"cannot open "<<device<<"\n"; return 1;}
    if(command=="status"){
        std::cout<<"AUTO_WB="<<cap.get(cv::CAP_PROP_AUTO_WB)<<" WB_TEMPERATURE="<<cap.get(cv::CAP_PROP_WB_TEMPERATURE)<<"\n";
        auto m=manual::measure_rgb(cap,12, (fs::path(outdir)/"wb_current.jpg").string());
        std::cout<<"R="<<m.r<<" G="<<m.g<<" B="<<m.b<<"\n";
    } else if(command=="temp"){
        cap.set(cv::CAP_PROP_AUTO_WB,0);
        auto vals=manual::parse_values(values);
        std::cout<<"[";
        for(size_t i=0;i<vals.size();++i){
            double v=vals[i]; cap.set(cv::CAP_PROP_WB_TEMPERATURE,v); manual::settle(cap,6);
            std::string save=(fs::path(outdir)/("WB_TEMP_"+std::to_string((int)v)+".jpg")).string();
            auto m=manual::measure_rgb(cap,12,save);
            std::cout<<(i?",":"")<<"{\"WB_TEMP\":"<<v<<",\"R\":"<<m.r<<",\"G\":"<<m.g<<",\"B\":"<<m.b<<"}";
        }
        std::cout<<"]\n";
        cap.set(cv::CAP_PROP_AUTO_WB,1);
    }
    return 0;
}
