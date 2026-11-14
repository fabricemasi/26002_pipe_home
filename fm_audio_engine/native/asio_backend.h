// fmz_audio_engine : backend ASIO (SDK Steinberg 2.3.4, variante GPLv3 ; compilé seulement si le SDK est
// présent dans fm_audio_engine/third_party/ASIOSDK : FMZ_ASIO défini par build.py).
//
// Contraintes du SDK et des pilotes :
// - UN pilote ASIO par processus (variables globales du SDK : theAsioDriver, asioDrivers) ;
// - les pilotes sont des objets COM « apartment » : tout le cycle de vie (chargement, init, buffers,
//   start/stop, dispose, exit) se fait sur UN fil STA dédié, qui pompe les messages ; le moteur, lui,
//   est en MTA ;
// - le callback (bufferSwitch) arrive sur le fil du pilote : conversion de format + appel du callback
//   du moteur, sans allocation (tampons préalloués à l'ouverture).
#pragma once
#ifdef FMZ_ASIO
#include <condition_variable>
#include <cstring>
#include <mutex>

#include "asiosys.h"
#include "asio.h"
#include "asiodrivers.h"

extern AsioDrivers* asioDrivers;
bool loadAsioDriver(char* name);

namespace fmz {

static const char* kAsioPrefix = "asio:";

// Énumération des pilotes inscrits (registre HKLM\SOFTWARE\ASIO), sans charger aucun pilote : charger un
// pilote peut prendre la carte ou ouvrir son panneau. Fil STA à part (AsioDriverList initialise COM).
inline void list_asio_devices(Json& out) {
    std::vector<std::string> names;
    std::thread th([&] {
        CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
        {
            AsioDriverList list;
            long n = list.asioGetNumDev();
            for (long i = 0; i < n && i < 32; ++i) {
                char name[64] = {0};
                if (list.asioGetDriverName((int)i, name, sizeof name) == 0) names.emplace_back(name);
            }
        }
        CoUninitialize();
    });
    th.join();
    for (auto& nm : names) {
        Json j = Json::object();
        j.set("id", Json::str(std::string(kAsioPrefix) + nm));
        j.set("name", Json::str(nm));
        j.set("flow", Json::str("duplex"));
        j.set("backend", Json::str("asio"));
        j.set("default", Json::boolean(false));
        out.push(std::move(j));
    }
}

class AsioStream;
static std::atomic<AsioStream*> g_asio{nullptr};

class AsioStream : public AudioStream {
public:
    AsioStream() { backend = "asio"; exclusive = true; }
    ~AsioStream() override { shutdown(); }

    // out_id = "asio:<nom du pilote>" ; in_id non vide = entrées activées (8 au plus).
    bool open(const std::string& out_id, const std::string& in_id, int want_sr, int want_buffer, Callback cb) {
        if (g_asio.load()) { error = "ASIO : un pilote est déjà ouvert dans ce moteur"; return false; }
        cb_ = std::move(cb);
        driver_ = out_id.substr(strlen(kAsioPrefix));
        want_inputs_ = !in_id.empty();
        want_sr_ = want_sr; want_buffer_ = want_buffer;
        th_ = std::thread([this] { sta_main(); });
        std::unique_lock<std::mutex> lk(m_);
        cv_.wait(lk, [this] { return phase_ != Phase::Opening; });
        if (phase_ != Phase::Ready) { lk.unlock(); shutdown(); return false; }
        return true;
    }

    bool start() override { return command(Cmd::Start); }
    void stop() override { if (phase_ == Phase::Ready) command(Cmd::Stop); }

    // Appelés par les callbacks statiques du SDK (fil du pilote).
    void on_buffer(long index) {
        const int n = buffer_frames;
        for (int c = 0; c < in_channels; ++c) {
            to_float(in_info_[c].buffers[index], in_type_[c], in_[c].data(), n);
            in_ptr_[c] = in_[c].data();
        }
        float* out = out_.data();
        cb_(out, out_channels, n, in_channels ? in_ptr_ : nullptr, in_channels);
        for (int c = 0; c < out_channels; ++c) from_float(out, c, out_channels, out_info_[c].buffers[index], out_type_[c], n);
        if (post_output_) ASIOOutputReady();
    }
    long on_message(long selector, long value) {
        switch (selector) {
            case kAsioSelectorSupported:
                return (value == kAsioResetRequest || value == kAsioEngineVersion || value == kAsioResyncRequest ||
                        value == kAsioLatenciesChanged || value == kAsioSupportsTimeInfo) ? 1L : 0L;
            case kAsioEngineVersion: return 2L;
            case kAsioResetRequest: device_lost = true; return 1L;       // le moteur rouvrira (remplacement contrôlé)
            case kAsioResyncRequest: xruns++; return 1L;
            case kAsioLatenciesChanged: latencies_changed = true; return 1L;
            case kAsioSupportsTimeInfo: return 1L;
            default: return 0L;
        }
    }
    void on_rate_changed() { device_lost = true; }
    std::atomic<bool> latencies_changed{false};
    std::string driver_name() const { return driver_; }

private:
    enum class Phase { Opening, Ready, Failed, Closed };
    enum class Cmd { None, Start, Stop, Quit };
    Callback cb_;
    std::string driver_;
    bool want_inputs_ = false;
    int want_sr_ = 0, want_buffer_ = 0;
    std::thread th_;
    DWORD tid_ = 0;
    std::mutex m_;
    std::condition_variable cv_;
    Phase phase_ = Phase::Opening;
    Cmd cmd_ = Cmd::None;
    bool cmd_ok_ = false, started_ = false, buffers_ = false, inited_ = false;
    bool post_output_ = false;
    HWND hwnd_ = nullptr;
    ASIOBufferInfo infos_[2 + 8 + 8] = {};
    ASIOBufferInfo* out_info_ = infos_;
    ASIOBufferInfo* in_info_ = infos_ + 8;
    ASIOSampleType out_type_[8] = {}, in_type_[8] = {};
    ASIOCallbacks callbacks_ = {};
    std::vector<float> out_, in_[8];
    const float* in_ptr_[8] = {};

    static void cb_switch(long index, ASIOBool) { if (auto* s = g_asio.load()) s->on_buffer(index); }
    static ASIOTime* cb_switch_time(ASIOTime* t, long index, ASIOBool) { if (auto* s = g_asio.load()) s->on_buffer(index); return t; }
    static void cb_rate(ASIOSampleRate) { if (auto* s = g_asio.load()) s->on_rate_changed(); }
    static long cb_message(long sel, long val, void*, double*) { auto* s = g_asio.load(); return s ? s->on_message(sel, val) : 0L; }

    static bool supported(ASIOSampleType t) {
        switch (t) {
            case ASIOSTInt16LSB: case ASIOSTInt24LSB: case ASIOSTInt32LSB: case ASIOSTFloat32LSB: case ASIOSTFloat64LSB:
            case ASIOSTInt32LSB16: case ASIOSTInt32LSB18: case ASIOSTInt32LSB20: case ASIOSTInt32LSB24: return true;
            default: return false;
        }
    }
    static int shift_of(ASIOSampleType t) {
        switch (t) { case ASIOSTInt32LSB16: return 16; case ASIOSTInt32LSB18: return 14; case ASIOSTInt32LSB20: return 12;
                     case ASIOSTInt32LSB24: return 8; default: return 0; }
    }
    static void to_float(const void* src, ASIOSampleType t, float* dst, int n) {
        switch (t) {
            case ASIOSTFloat32LSB: memcpy(dst, src, sizeof(float) * n); break;
            case ASIOSTFloat64LSB: { auto p = (const double*)src; for (int i = 0; i < n; ++i) dst[i] = (float)p[i]; } break;
            case ASIOSTInt16LSB: { auto p = (const int16_t*)src; for (int i = 0; i < n; ++i) dst[i] = p[i] / 32768.f; } break;
            case ASIOSTInt24LSB: { auto p = (const uint8_t*)src;
                for (int i = 0; i < n; ++i) { int32_t v = (int32_t)((uint32_t)p[3 * i] << 8 | (uint32_t)p[3 * i + 1] << 16 | (uint32_t)p[3 * i + 2] << 24);
                                              dst[i] = (float)(v / 2147483648.0); } } break;
            default: { auto p = (const int32_t*)src; int sh = shift_of(t);
                for (int i = 0; i < n; ++i) dst[i] = (float)(((int64_t)p[i] << sh) / 2147483648.0); } break;
        }
    }
    static void from_float(const float* il, int c, int ch, void* dst, ASIOSampleType t, int n) {
        auto clip = [](float v) { return v > 1.f ? 1.f : (v < -1.f ? -1.f : v); };
        switch (t) {
            case ASIOSTFloat32LSB: { auto p = (float*)dst; for (int i = 0; i < n; ++i) p[i] = il[i * ch + c]; } break;
            case ASIOSTFloat64LSB: { auto p = (double*)dst; for (int i = 0; i < n; ++i) p[i] = il[i * ch + c]; } break;
            case ASIOSTInt16LSB: { auto p = (int16_t*)dst; for (int i = 0; i < n; ++i) p[i] = (int16_t)lrintf(clip(il[i * ch + c]) * 32767.f); } break;
            case ASIOSTInt24LSB: { auto p = (uint8_t*)dst;
                for (int i = 0; i < n; ++i) { int32_t v = (int32_t)lrint(clip(il[i * ch + c]) * 8388607.0);
                                              p[3 * i] = (uint8_t)v; p[3 * i + 1] = (uint8_t)(v >> 8); p[3 * i + 2] = (uint8_t)(v >> 16); } } break;
            default: { auto p = (int32_t*)dst; int sh = shift_of(t);
                for (int i = 0; i < n; ++i) p[i] = (int32_t)(llrint(clip(il[i * ch + c]) * 2147483647.0) >> sh); } break;
        }
    }

    void set_phase(Phase p) { { std::lock_guard<std::mutex> lk(m_); phase_ = p; } cv_.notify_all(); }

    static std::string err_text(ASIOError e) {
        switch (e) {
            case ASE_NotPresent: return "matériel absent ou débranché";
            case ASE_HWMalfunction: return "panne matérielle signalée par le pilote";
            case ASE_InvalidParameter: return "paramètre refusé";
            case ASE_InvalidMode: return "mode invalide : sortie du pilote inactive ou prise par une autre appli";
            case ASE_SPNotAdvancing: return "horloge à l'arrêt";
            case ASE_NoClock: return "aucune horloge";
            case ASE_NoMemory: return "mémoire insuffisante";
            default: return "code " + std::to_string(e);
        }
    }
    bool fail(const std::string& e) { error = "ASIO (" + driver_ + ") : " + e; return false; }

    bool sta_open() {
        if (!loadAsioDriver(driver_.data())) return fail("pilote introuvable ou refusé au chargement");
        ASIODriverInfo info = {};
        info.asioVersion = 2;
        // fenêtre cachée du fil STA : beaucoup de pilotes exigent un HWND valide (sysRef)
        hwnd_ = CreateWindowExW(0, L"STATIC", L"fmz_asio", WS_POPUP, 0, 0, 1, 1, nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
        info.sysRef = hwnd_;
        if (ASIOInit(&info) != ASE_OK) return fail(std::string("initialisation refusée : ") + info.errorMessage);
        inited_ = true;
        long nin = 0, nout = 0;
        if (ASIOGetChannels(&nin, &nout) != ASE_OK || nout < 1) return fail("aucune sortie");
        long mn = 0, mx = 0, pref = 0, gran = 0;
        if (ASIOGetBufferSize(&mn, &mx, &pref, &gran) != ASE_OK) return fail("taille de buffer illisible");
        long buf = pref;
        if (want_buffer_ > 0 && want_buffer_ >= mn && want_buffer_ <= mx) {
            bool ok = gran == 0 ? want_buffer_ == pref
                    : (gran == -1 ? (want_buffer_ & (want_buffer_ - 1)) == 0 : (want_buffer_ - mn) % gran == 0);
            if (ok) buf = want_buffer_;
        }
        if (want_sr_ > 0) {
            if (ASIOCanSampleRate((ASIOSampleRate)want_sr_) == ASE_OK) ASIOSetSampleRate((ASIOSampleRate)want_sr_);
        }
        ASIOSampleRate cur = 0;
        if (ASIOGetSampleRate(&cur) != ASE_OK || cur <= 0) {        // horloge non fixée : proposer 48 k puis 44,1 k
            for (double f : {48000.0, 44100.0})
                if (ASIOCanSampleRate(f) == ASE_OK && ASIOSetSampleRate(f) == ASE_OK && ASIOGetSampleRate(&cur) == ASE_OK && cur > 0) break;
            if (cur <= 0) return fail("fréquence illisible (le pilote n'accepte ni 48 000 ni 44 100 Hz)");
        }
        sample_rate = (int)(cur + 0.5);
        out_channels = (int)std::min<long>(nout, 2);
        in_channels = want_inputs_ ? (int)std::min<long>(nin, 8) : 0;
        int k = 0;
        for (int c = 0; c < out_channels; ++c, ++k) { infos_[k].isInput = ASIOFalse; infos_[k].channelNum = c; }
        for (int c = 0; c < in_channels; ++c, ++k) { infos_[k].isInput = ASIOTrue; infos_[k].channelNum = c; }
        out_info_ = infos_;
        in_info_ = infos_ + out_channels;
        callbacks_.bufferSwitch = &cb_switch;
        callbacks_.sampleRateDidChange = &cb_rate;
        callbacks_.asioMessage = &cb_message;
        callbacks_.bufferSwitchTimeInfo = &cb_switch_time;
        for (int c = 0; c < out_channels + in_channels; ++c) {
            ASIOChannelInfo ci = {};
            ci.channel = infos_[c].channelNum; ci.isInput = infos_[c].isInput;
            if (ASIOGetChannelInfo(&ci) != ASE_OK) return fail("format des canaux illisible");
            if (!supported(ci.type)) return fail("format d'échantillon non pris en charge (" + std::to_string(ci.type) + ")");
            (c < out_channels ? out_type_[c] : in_type_[c - out_channels]) = ci.type;
        }
        out_.assign((size_t)buf * out_channels, 0.f);
        for (int c = 0; c < in_channels; ++c) in_[c].assign((size_t)buf, 0.f);
        buffer_frames = (int)buf;
        g_asio = this;
        ASIOError ce = ASIOCreateBuffers(infos_, out_channels + in_channels, buf, &callbacks_);
        if (ce != ASE_OK) {
            g_asio = nullptr;
            return fail("création des buffers refusée (" + err_text(ce) + ", " + std::to_string(buf) + " échantillons, "
                        + std::to_string(out_channels) + " sorties / " + std::to_string(in_channels) + " entrées ; pilote : min "
                        + std::to_string(mn) + ", max " + std::to_string(mx) + ", préféré " + std::to_string(pref) + ", pas "
                        + std::to_string(gran) + ", " + std::to_string(nin) + " entrées / " + std::to_string(nout) + " sorties)");
        }
        buffers_ = true;
        long il = 0, ol = 0;
        if (ASIOGetLatencies(&il, &ol) == ASE_OK) {
            in_latency_ms = 1000.0 * il / sample_rate;
            out_latency_ms = 1000.0 * ol / sample_rate;
        }
        post_output_ = ASIOOutputReady() == ASE_OK;
        return true;
    }

    void sta_close() {
        if (started_) { ASIOStop(); started_ = false; }
        if (buffers_) { ASIODisposeBuffers(); buffers_ = false; }
        g_asio = nullptr;
        if (inited_) { ASIOExit(); inited_ = false; }
        if (asioDrivers) { delete asioDrivers; asioDrivers = nullptr; }
        if (hwnd_) { DestroyWindow(hwnd_); hwnd_ = nullptr; }
    }

    void sta_main() {
        CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
        tid_ = GetCurrentThreadId();
        MSG msg;
        PeekMessageW(&msg, nullptr, 0, 0, PM_NOREMOVE);              // crée la file de messages du fil
        bool ok = sta_open();
        if (!ok) sta_close();
        set_phase(ok ? Phase::Ready : Phase::Failed);
        for (bool run = ok; run;) {
            MsgWaitForMultipleObjects(0, nullptr, FALSE, 50, QS_ALLINPUT);
            while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
            std::unique_lock<std::mutex> lk(m_);
            if (cmd_ == Cmd::None) continue;
            Cmd c = cmd_;
            lk.unlock();
            bool r = true;
            if (c == Cmd::Start && !started_) { r = ASIOStart() == ASE_OK; started_ = r; if (!r) error = "ASIO : démarrage refusé"; }
            else if (c == Cmd::Stop && started_) { ASIOStop(); started_ = false; }
            else if (c == Cmd::Quit) { sta_close(); run = false; }
            lk.lock();
            cmd_ok_ = r; cmd_ = Cmd::None;
            lk.unlock();
            cv_.notify_all();
        }
        CoUninitialize();
    }

    bool command(Cmd c) {
        std::unique_lock<std::mutex> lk(m_);
        if (phase_ != Phase::Ready) return false;
        cmd_ = c;
        cv_.wait(lk, [this] { return cmd_ == Cmd::None; });
        return cmd_ok_;
    }

    void shutdown() {
        if (phase_ == Phase::Ready) command(Cmd::Quit);
        if (th_.joinable()) th_.join();
        phase_ = Phase::Closed;
    }
};

}  // namespace fmz
#endif  // FMZ_ASIO
