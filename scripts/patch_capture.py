from pathlib import Path
import sys
w=Path(__file__).resolve().parents[1]
p=w/'vendor/zed-open-capture/include/videocapture.hpp'
if 'setFrameCallback' in p.read_text():
 print('Local capture patch already applied; leave files untouched. See evidence/open_capture.patch for the final changes.')
 sys.exit(0)
s=p.read_text().replace('#include <thread>','#include <thread>\n#include <functional>\n#include <atomic>')
s=s.replace('uint8_t* data = nullptr;', '''int64_t v4l2_sec=0, v4l2_usec=0;
    uint32_t sequence=0, flags=0, bytesused=0, buffer_length=0;
    uint32_t stride=0, pixel_format=0, field=0;
    uint64_t dq_before_ns=0, dq_after_ns=0, dq_realtime_ns=0;
    bool payload_valid=false;
    uint8_t* data = nullptr;''')
s=s.replace('bool initializeVideo( int devId=-1 );','''bool initializeVideo( int devId=-1 );
    // Set before initializeVideo. Called synchronously for EVERY dequeued buffer;
    // payload is valid only for the duration of the callback.
    void setFrameCallback(std::function<void(const Frame&)> cb) { mFrameCallback=cb; }''')
s=s.replace('Frame mLastFrame;', 'std::function<void(const Frame&)> mFrameCallback;\n    Frame mLastFrame;')
for name in ['mNewFrame','mStopCapture','mGrabRunning']:
 import re
 s=re.sub(r'bool '+name+r'\s*=\s*(true|false);',r'std::atomic<bool> '+name+r'{\1};',s)
p.write_text(s)
p=w/'vendor/zed-open-capture/src/videocapture.cpp';s=p.read_text()
s=s.replace('#include <sstream>','#include <sstream>\n#include <time.h>')
s=s.replace('if (mFileDesc)\n','if (mFileDesc >= 0)\n')
s=s.replace('mChannels = fmt.fmt.pix.bytesperline / mWidth;', '''mChannels = 2;
    if (fmt.fmt.pix.pixelformat != V4L2_PIX_FMT_YUYV || fmt.fmt.pix.bytesperline < mWidth*2)
        return false;
    mLastFrame.stride = fmt.fmt.pix.bytesperline;
    mLastFrame.pixel_format = fmt.fmt.pix.pixelformat;''')
s=s.replace('int bufSize = mLastFrame.width * mLastFrame.height * mLastFrame.channels;', 'size_t bufSize = size_t(mLastFrame.stride) * mLastFrame.height;')
# Preserve existing image controls instead of silently resetting exposure/gain.
start=s.index('    resetAECAGC();',s.index('bool VideoCapture::initializeVideo'))
end=s.index('    return mInitialized;',start)
s=s[:start]+'    // Capture-only fork: preserve current exposure, gain, color and orientation.\n'+s[end:]
a=s.index('void VideoCapture::grabThreadFunc()');b=s.index('const Frame& VideoCapture::getLastFrame',a)
s=s[:a]+'''static uint64_t traceClock(clockid_t id) {
    timespec ts{}; clock_gettime(id, &ts);
    return uint64_t(ts.tv_sec)*1000000000ULL+ts.tv_nsec;
}
void VideoCapture::grabThreadFunc()
{
    mNewFrame=false; mFirstFrame=true; mGrabRunning=true;
    while (!mStopCapture) {
        fd_set fds; FD_ZERO(&fds); FD_SET(mFileDesc, &fds);
        timeval timeout{0, 100000};
        int ready=select(mFileDesc+1, &fds, nullptr, nullptr, &timeout);
        if (ready<=0) { if (ready<0 && errno!=EINTR) break; continue; }
        v4l2_buffer buf{};
        buf.type=V4L2_BUF_TYPE_VIDEO_CAPTURE; buf.memory=V4L2_MEMORY_MMAP;
        uint64_t before=traceClock(CLOCK_MONOTONIC);
        int ret;
        { std::lock_guard<std::mutex> lock(mComMutex); ret=ioctl(mFileDesc, VIDIOC_DQBUF, &buf); }
        uint64_t after=traceClock(CLOCK_MONOTONIC), wall=traceClock(CLOCK_REALTIME);
        if(ret!=0) { if(errno==EAGAIN || errno==EINTR) continue; break; }
        if(buf.index>=mBufCount) break;
        const uint64_t raw=uint64_t(buf.timestamp.tv_sec)*1000000000ULL+uint64_t(buf.timestamp.tv_usec)*1000ULL;
        if(mFirstFrame) { mStartTs=wall; mInitTs=raw; mFirstFrame=false; }
        {
            std::lock_guard<std::mutex> lock(mBufMutex);
            Frame f=mLastFrame;
            f.frame_id=++mLastFrame.frame_id;
            f.timestamp=(raw>=mInitTs)?mStartTs+(raw-mInitTs):0;
            f.v4l2_sec=buf.timestamp.tv_sec; f.v4l2_usec=buf.timestamp.tv_usec;
            f.sequence=buf.sequence; f.flags=buf.flags; f.bytesused=buf.bytesused;
            f.buffer_length=buf.length; f.field=buf.field;
            f.dq_before_ns=before; f.dq_after_ns=after; f.dq_realtime_ns=wall;
            f.data=static_cast<uint8_t*>(mBuffers[buf.index].start);
            f.payload_valid=f.data!=MAP_FAILED && f.data!=nullptr &&
                buf.bytesused>=size_t(f.stride)*f.height &&
                buf.bytesused<=mBuffers[buf.index].length && !(buf.flags & V4L2_BUF_FLAG_ERROR);
            if(mFrameCallback) mFrameCallback(f);
            else if(f.payload_valid) {
                memcpy(mLastFrame.data, f.data, size_t(f.stride)*f.height);
                mLastFrame.timestamp=f.timestamp; mNewFrame=true;
            }
        }
        { std::lock_guard<std::mutex> lock(mComMutex);
          if(ioctl(mFileDesc, VIDIOC_QBUF, &buf)!=0) break; }
    }
    mGrabRunning=false;
}
''' + s[b:]
s=s.replace('mGrabThread = std::thread( &VideoCapture::grabThreadFunc,this );','mStopCapture = false;\n    mGrabThread = std::thread( &VideoCapture::grabThreadFunc,this );')
p.write_text(s)
p=w/'vendor/zed-open-capture/include/sensorcapture.hpp';s=p.read_text().replace('#include <thread>','#include <thread>\n#include <functional>\n#include <atomic>')
s=s.replace('bool initializeSensors( int sn=-1 );','''bool initializeSensors( int sn=-1 );
    // Complete HID reports, before any float conversion, rebase, sync or first-sample skip.
    using RawCallback=std::function<void(const uint8_t*,size_t,uint64_t,uint64_t,uint64_t)>;
    void setRawCallback(RawCallback cb) { mRawCallback=cb; }''')
s=s.replace('data::Imu mLastIMUData;', 'RawCallback mRawCallback;\n    data::Imu mLastIMUData;')
for name in ['mStopCapture','mGrabRunning']:
 import re
 s=re.sub(r'bool '+name+r'\s*=\s*(true|false);',r'std::atomic<bool> '+name+r'{\1};',s)
p.write_text(s)
p=w/'vendor/zed-open-capture/src/sensorcapture.cpp';s=p.read_text().replace('#include <sstream>','#include <sstream>\n#include <time.h>')
s=s.replace('mGrabThread = std::thread( &SensorCapture::grabThreadFunc,this );','mStopCapture = false;\n    mGrabThread = std::thread( &SensorCapture::grabThreadFunc,this );')
s=s.replace('void SensorCapture::grabThreadFunc()\n{\n    mStopCapture = false;','void SensorCapture::grabThreadFunc()\n{')
s=s.replace('int res = hid_read_timeout( mDevHandle, usbBuf, 64, 2000 );','''auto traceClock=[](clockid_t id) { timespec ts{}; clock_gettime(id,&ts);
            return uint64_t(ts.tv_sec)*1000000000ULL+ts.tv_nsec; };
        uint64_t before=traceClock(CLOCK_MONOTONIC);
        int res = hid_read_timeout( mDevHandle, usbBuf, 64, 2000 );
        uint64_t after=traceClock(CLOCK_MONOTONIC), wall=traceClock(CLOCK_REALTIME);
        if(res>0 && mRawCallback) mRawCallback(usbBuf,size_t(res),before,after,wall);''')
p.write_text(s)
print('Patched isolated Open Capture snapshot')
