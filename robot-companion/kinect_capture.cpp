/**
 * kinect_capture.cpp
 * RGB-only Kinect v2 frame grabber via libfreenect2.
 * Writes frames to stdout as: [4-byte little-endian JPEG size][JPEG data]
 * Stderr is used for status/debug messages.
 *
 * Build:
 *   g++ -O2 -o kinect_capture kinect_capture.cpp \
 *       -I/usr/local/include -L/usr/local/lib \
 *       -lfreenect2 -lturbojpeg \
 *       -Wl,-rpath,/usr/local/lib
 */

#include <iostream>
#include <csignal>
#include <cstdio>
#include <stdint.h>
#include <vector>

#include <libfreenect2/libfreenect2.hpp>
#include <libfreenect2/frame_listener_impl.h>
#include <libfreenect2/packet_pipeline.h>
#include <libfreenect2/logger.h>

#include <turbojpeg.h>

static volatile bool g_shutdown = false;

void sigint_handler(int) { g_shutdown = true; }

// Suppress libfreenect2 noise — only show warnings+
class QuietLogger : public libfreenect2::Logger {
public:
    QuietLogger() { level_ = libfreenect2::Logger::Warning; }
    void log(Level level, const std::string &msg) override {
        if (level <= libfreenect2::Logger::Warning)
            std::cerr << "[freenect2] " << msg << std::endl;
    }
};

int main(int, char **) {
    signal(SIGINT,  sigint_handler);
    signal(SIGTERM, sigint_handler);

    libfreenect2::setGlobalLogger(new QuietLogger());

    libfreenect2::Freenect2 freenect2;
    int num = freenect2.enumerateDevices();
    if (num == 0) {
        std::cerr << "No Kinect v2 devices found." << std::endl;
        return 1;
    }
    std::cerr << "Found " << num << " Kinect v2 device(s)." << std::endl;

    std::string serial = freenect2.getDefaultDeviceSerialNumber();
    std::cerr << "Opening device: " << serial << std::endl;

    // CpuPacketPipeline — no GPU dependency
    libfreenect2::CpuPacketPipeline *pipeline = new libfreenect2::CpuPacketPipeline();
    libfreenect2::Freenect2Device *dev = freenect2.openDevice(serial, pipeline);
    if (!dev) {
        std::cerr << "Failed to open Kinect v2 device." << std::endl;
        return 1;
    }

    // RGB-only listener
    libfreenect2::SyncMultiFrameListener listener(libfreenect2::Frame::Color);
    libfreenect2::FrameMap frames;
    dev->setColorFrameListener(&listener);

    // Start RGB stream only (depth=false saves CPU significantly)
    if (!dev->startStreams(true, false)) {
        std::cerr << "Failed to start Kinect v2 streams." << std::endl;
        dev->close();
        return 1;
    }
    std::cerr << "Kinect v2 RGB stream started (1920x1080)." << std::endl;

    // TurboJPEG compressor
    tjhandle tj = tjInitCompress();
    if (!tj) {
        std::cerr << "TurboJPEG init failed." << std::endl;
        dev->stop(); dev->close();
        return 1;
    }

    unsigned char *jpeg_buf = nullptr;
    unsigned long  jpeg_sz  = 0;

    while (!g_shutdown) {
        if (!listener.waitForNewFrame(frames, 1000)) {
            continue;  // timeout, retry
        }

        libfreenect2::Frame *rgb = frames[libfreenect2::Frame::Color];

        // Kinect RGB frame: BGRX, 4 bytes/pixel, 1920x1080
        // TurboJPEG: compress BGRA → JPEG
        int rc = tjCompress2(
            tj,
            rgb->data,
            (int)rgb->width, 0, (int)rgb->height,
            TJPF_BGRX,
            &jpeg_buf, &jpeg_sz,
            TJSAMP_420,
            78,             // JPEG quality (78 is a good bandwidth/quality balance)
            TJFLAG_FASTDCT
        );

        listener.release(frames);

        if (rc != 0) {
            std::cerr << "TurboJPEG compress error: " << tjGetErrorStr() << std::endl;
            continue;
        }

        // Write 4-byte LE length prefix then JPEG payload
        uint32_t sz32 = (uint32_t)jpeg_sz;
        if (fwrite(&sz32, 4, 1, stdout) != 1) break;
        if (fwrite(jpeg_buf, 1, jpeg_sz, stdout) != jpeg_sz) break;
        fflush(stdout);
    }

    if (jpeg_buf) tjFree(jpeg_buf);
    tjDestroy(tj);

    std::cerr << "Shutting down..." << std::endl;
    dev->stop();
    dev->close();
    std::cerr << "Done." << std::endl;
    return 0;
}
