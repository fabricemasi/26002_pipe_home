// fmz_audio_engine : backend WASAPI (partagé ou exclusif, piloté par événement).
// ASIO : voir asio_backend.h (compilé si le SDK est présent).
#pragma once
#include <atomic>
#include <functional>
#include <string>
#include <thread>
#include <vector>
#include "json.h"
#include "wav.h"

#include <initguid.h>
#include <audioclient.h>
#include <propsys.h>
#include <avrt.h>
#include <functiondiscoverykeys_devpkey.h>
#include <mmdeviceapi.h>

namespace fmz {

inline std::string narrow(const wchar_t* w) {
    if (!w) return std::string();
    int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
    std::string s(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, w, -1, s.data(), n, nullptr, nullptr);
    return s;
}

template <class T> struct ComPtr {
    T* p = nullptr;
    ~ComPtr() { if (p) p->Release(); }
    T** put() { if (p) { p->Release(); p = nullptr; } return &p; }
    T* operator->() const { return p; }
    explicit operator bool() const { return p != nullptr; }
};

struct ComInit {
    HRESULT hr;
    ComInit() { hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED); }
    ~ComInit() { if (SUCCEEDED(hr)) CoUninitialize(); }
};

inline std::string hr_text(HRESULT hr) {
    char b[32]; snprintf(b, sizeof b, "0x%08lX", (unsigned long)hr);
    switch (hr) {
        case AUDCLNT_E_DEVICE_IN_USE: return std::string("périphérique occupé (mode exclusif pris par une autre appli) ") + b;
        case AUDCLNT_E_DEVICE_INVALIDATED: return std::string("périphérique débranché ou invalidé ") + b;
        case AUDCLNT_E_UNSUPPORTED_FORMAT: return std::string("format non pris en charge ") + b;
        case AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED: return std::string("taille de buffer non alignée ") + b;
        case E_ACCESSDENIED: return std::string("accès refusé (confidentialité du micro Windows ?) ") + b;
        default: return std::string("erreur WASAPI ") + b;
    }
}

// Énumération : sorties et entrées actives, défaut, format de mixage.
inline Json list_devices() {
    Json out = Json::array();
    ComPtr<IMMDeviceEnumerator> en;
    if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), (void**)en.put()))) return out;
    for (int flow = 0; flow < 2; ++flow) {
        EDataFlow df = flow == 0 ? eRender : eCapture;
        std::string def_id;
        ComPtr<IMMDevice> def;
        if (SUCCEEDED(en->GetDefaultAudioEndpoint(df, eConsole, def.put()))) { LPWSTR id = nullptr; def->GetId(&id); def_id = narrow(id); CoTaskMemFree(id); }
        ComPtr<IMMDeviceCollection> col;
        if (FAILED(en->EnumAudioEndpoints(df, DEVICE_STATE_ACTIVE, col.put()))) continue;
        UINT n = 0; col->GetCount(&n);
        for (UINT i = 0; i < n; ++i) {
            ComPtr<IMMDevice> d;
            if (FAILED(col->Item(i, d.put()))) continue;
            LPWSTR id = nullptr; d->GetId(&id);
            Json j = Json::object();
            j.set("id", Json::str(narrow(id))); CoTaskMemFree(id);
            j.set("flow", Json::str(flow == 0 ? "output" : "input"));
            j.set("backend", Json::str("wasapi"));
            j.set("default", Json::boolean(j.gets("id") == def_id));
            ComPtr<IPropertyStore> ps;
            if (SUCCEEDED(d->OpenPropertyStore(STGM_READ, ps.put()))) {
                PROPVARIANT v; PropVariantInit(&v);
                if (SUCCEEDED(ps->GetValue(PKEY_Device_FriendlyName, &v)) && v.vt == VT_LPWSTR) j.set("name", Json::str(narrow(v.pwszVal)));
                PropVariantClear(&v);
            }
            ComPtr<IAudioClient> ac;
            if (SUCCEEDED(d->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)ac.put()))) {
                WAVEFORMATEX* wf = nullptr;
                if (SUCCEEDED(ac->GetMixFormat(&wf))) {
                    j.set("sample_rate", Json::num(wf->nSamplesPerSec)); j.set("channels", Json::num(wf->nChannels));
                    CoTaskMemFree(wf);
                }
                REFERENCE_TIME def_p = 0, min_p = 0;
                if (SUCCEEDED(ac->GetDevicePeriod(&def_p, &min_p))) { j.set("period_ms", Json::num(def_p / 10000.0)); j.set("min_period_ms", Json::num(min_p / 10000.0)); }
            }
            out.push(std::move(j));
        }
    }
    return out;
}

// Flux duplex : une sortie (obligatoire) et une entrée facultative. Le callback reçoit
// (sortie entrelacée float, canaux de sortie, images, entrées désentrelacées, nb d'entrées).
// Interface commune des flux (WASAPI réel, périphérique de test déclaré).
class AudioStream {
public:
    using Callback = std::function<void(float* out, int out_ch, int frames, const float* const* in, int in_ch)>;
    std::string error;
    int sample_rate = 0, out_channels = 0, in_channels = 0, buffer_frames = 0;
    double out_latency_ms = 0, in_latency_ms = 0;
    bool exclusive = false;
    std::string backend = "wasapi";
    std::atomic<bool> device_lost{false};
    std::atomic<uint64_t> xruns{0};
    virtual ~AudioStream() = default;
    virtual bool start() = 0;
    virtual void stop() = 0;
};

class WasapiStream : public AudioStream {
public:
    bool open(const std::string& out_id, const std::string& in_id, int want_sr, int want_buffer, bool want_exclusive, Callback cb) {
        cb_ = std::move(cb);
        ComPtr<IMMDeviceEnumerator> en;
        HRESULT hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), (void**)en.put());
        if (FAILED(hr)) { error = hr_text(hr); return false; }
        if (!activate(en, out_id, eRender, out_dev_, out_ac_)) return false;
        WAVEFORMATEX* mix = nullptr;
        out_ac_->GetMixFormat(&mix);
        WAVEFORMATEXTENSIBLE fmt = make_float_format(want_sr > 0 ? want_sr : (int)mix->nSamplesPerSec, mix->nChannels);
        CoTaskMemFree(mix);
        REFERENCE_TIME def_p = 0, min_p = 0; out_ac_->GetDevicePeriod(&def_p, &min_p);
        AUDCLNT_SHAREMODE mode = want_exclusive ? AUDCLNT_SHAREMODE_EXCLUSIVE : AUDCLNT_SHAREMODE_SHARED;
        REFERENCE_TIME per = 0;
        if (want_exclusive) {
            per = want_buffer > 0 ? (REFERENCE_TIME)(10000000.0 * want_buffer / fmt.Format.nSamplesPerSec + 0.5) : def_p;
            if (per < min_p) per = min_p;
            if (out_ac_->IsFormatSupported(mode, (WAVEFORMATEX*)&fmt, nullptr) != S_OK) {
                error = "mode exclusif : format float " + std::to_string(fmt.Format.nSamplesPerSec) + " Hz refusé par le pilote";
                return false;
            }
        }
        DWORD flags = AUDCLNT_STREAMFLAGS_EVENTCALLBACK;
        if (!want_exclusive) flags |= AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY;
        hr = out_ac_->Initialize(mode, flags, want_exclusive ? per : 0, want_exclusive ? per : 0, (WAVEFORMATEX*)&fmt, nullptr);
        if (hr == AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED) {
            UINT32 frames = 0; out_ac_->GetBufferSize(&frames);
            per = (REFERENCE_TIME)(10000000.0 * frames / fmt.Format.nSamplesPerSec + 0.5);
            out_ac_.put();
            if (!activate(en, out_id, eRender, out_dev_, out_ac_)) return false;
            hr = out_ac_->Initialize(mode, flags, per, per, (WAVEFORMATEX*)&fmt, nullptr);
        }
        if (FAILED(hr)) { error = "sortie : " + hr_text(hr); return false; }
        exclusive = want_exclusive;
        sample_rate = fmt.Format.nSamplesPerSec; out_channels = fmt.Format.nChannels;
        UINT32 bf = 0; out_ac_->GetBufferSize(&bf); buffer_frames = (int)bf;
        REFERENCE_TIME lat = 0; out_ac_->GetStreamLatency(&lat);
        out_latency_ms = lat / 10000.0 + 1000.0 * bf / sample_rate;
        ev_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        out_ac_->SetEventHandle(ev_);
        hr = out_ac_->GetService(__uuidof(IAudioRenderClient), (void**)render_.put());
        if (FAILED(hr)) { error = hr_text(hr); return false; }
        if (!in_id.empty()) {
            if (!activate(en, in_id, eCapture, in_dev_, in_ac_)) return false;
            WAVEFORMATEX* imix = nullptr; in_ac_->GetMixFormat(&imix);
            WAVEFORMATEXTENSIBLE ifmt = make_float_format(sample_rate, imix->nChannels);
            CoTaskMemFree(imix);
            hr = in_ac_->Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
                                    200000, 0, (WAVEFORMATEX*)&ifmt, nullptr);
            if (FAILED(hr)) { error = "entrée : " + hr_text(hr); return false; }
            in_channels = ifmt.Format.nChannels;
            REFERENCE_TIME il = 0; in_ac_->GetStreamLatency(&il); in_latency_ms = il / 10000.0;
            hr = in_ac_->GetService(__uuidof(IAudioCaptureClient), (void**)capture_.put());
            if (FAILED(hr)) { error = hr_text(hr); return false; }
            // tampon d'entrée : 2 s, préalloué
            ring_len_ = sample_rate * 2;
            for (int c = 0; c < in_channels && c < 8; ++c) ring_[c].assign(ring_len_, 0.f);
            for (int c = 0; c < 8; ++c) in_block_[c].assign(bf + 4096, 0.f);
        }
        return true;
    }

    bool start() override {
        running_ = true;
        if (in_ac_) in_ac_->Start();
        // préremplissage en silence
        UINT32 bf = 0; out_ac_->GetBufferSize(&bf);
        BYTE* data = nullptr;
        if (SUCCEEDED(render_->GetBuffer(bf, &data))) render_->ReleaseBuffer(bf, AUDCLNT_BUFFERFLAGS_SILENT);
        HRESULT hr = out_ac_->Start();
        if (FAILED(hr)) { error = hr_text(hr); running_ = false; return false; }
        th_ = std::thread([this] { loop(); });
        return true;
    }

    void stop() override {
        running_ = false;
        if (th_.joinable()) th_.join();
        if (out_ac_) out_ac_->Stop();
        if (in_ac_) in_ac_->Stop();
        if (ev_) { CloseHandle(ev_); ev_ = nullptr; }
    }
    ~WasapiStream() override { stop(); }

private:
    Callback cb_;
    ComPtr<IMMDevice> out_dev_, in_dev_;
    ComPtr<IAudioClient> out_ac_, in_ac_;
    ComPtr<IAudioRenderClient> render_;
    ComPtr<IAudioCaptureClient> capture_;
    HANDLE ev_ = nullptr;
    std::thread th_;
    std::atomic<bool> running_{false};
    std::vector<float> ring_[8], in_block_[8];
    int ring_len_ = 0; int64_t ring_w_ = 0, ring_r_ = 0;

    static WAVEFORMATEXTENSIBLE make_float_format(int sr, int ch) {
        WAVEFORMATEXTENSIBLE f = {};
        f.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE; f.Format.nChannels = (WORD)ch; f.Format.nSamplesPerSec = sr;
        f.Format.wBitsPerSample = 32; f.Format.nBlockAlign = (WORD)(ch * 4); f.Format.nAvgBytesPerSec = sr * ch * 4;
        f.Format.cbSize = 22; f.Samples.wValidBitsPerSample = 32;
        f.dwChannelMask = ch == 1 ? SPEAKER_FRONT_CENTER : (ch == 2 ? (SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT) : 0);
        f.SubFormat = KSDATAFORMAT_SUBTYPE_IEEE_FLOAT;
        return f;
    }

    bool activate(ComPtr<IMMDeviceEnumerator>& en, const std::string& id, EDataFlow df, ComPtr<IMMDevice>& dev, ComPtr<IAudioClient>& ac) {
        HRESULT hr;
        if (id.empty() || id == "default") hr = en->GetDefaultAudioEndpoint(df, eConsole, dev.put());
        else hr = en->GetDevice(widen(id).c_str(), dev.put());
        if (FAILED(hr)) { error = "périphérique introuvable : " + id + " (" + hr_text(hr) + ")"; return false; }
        hr = dev->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)ac.put());
        if (FAILED(hr)) { error = hr_text(hr); return false; }
        return true;
    }

    // Lit tout ce que l'entrée a capturé dans l'anneau (sans attente).
    void pull_input() {
        UINT32 pk = 0;
        while (SUCCEEDED(capture_->GetNextPacketSize(&pk)) && pk > 0) {
            BYTE* data = nullptr; UINT32 frames = 0; DWORD fl = 0;
            HRESULT hr = capture_->GetBuffer(&data, &frames, &fl, nullptr, nullptr);
            if (hr == AUDCLNT_E_DEVICE_INVALIDATED) { device_lost = true; return; }
            if (FAILED(hr)) return;
            const float* f = (const float*)data;
            for (UINT32 i = 0; i < frames; ++i) {
                int64_t w = ring_w_ % ring_len_;
                for (int c = 0; c < in_channels && c < 8; ++c) ring_[c][w] = (fl & AUDCLNT_BUFFERFLAGS_SILENT) ? 0.f : f[i * in_channels + c];
                ++ring_w_;
            }
            if (fl & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY) xruns++;
            capture_->ReleaseBuffer(frames);
        }
        if (ring_w_ - ring_r_ > ring_len_) { ring_r_ = ring_w_ - ring_len_; xruns++; }
    }

    void loop() {
        DWORD task = 0;
        HANDLE mm = AvSetMmThreadCharacteristicsW(L"Pro Audio", &task);
        UINT32 bf = 0; out_ac_->GetBufferSize(&bf);
        const float* inp[8];
        while (running_) {
            DWORD w = WaitForSingleObject(ev_, 200);
            if (!running_) break;
            if (w != WAIT_OBJECT_0) { xruns++; continue; }
            UINT32 pad = 0;
            HRESULT hr = out_ac_->GetCurrentPadding(&pad);
            if (hr == AUDCLNT_E_DEVICE_INVALIDATED) { device_lost = true; break; }
            UINT32 avail = exclusive ? bf : bf - pad;
            if (avail == 0) continue;
            if (capture_) {
                pull_input();
                int64_t have = ring_w_ - ring_r_;
                for (int c = 0; c < in_channels && c < 8; ++c) {
                    for (UINT32 i = 0; i < avail; ++i)
                        in_block_[c][i] = (int64_t)i < have ? ring_[c][(ring_r_ + i) % ring_len_] : 0.f;
                    inp[c] = in_block_[c].data();
                }
                ring_r_ += std::min<int64_t>(have, avail);
            }
            BYTE* data = nullptr;
            hr = render_->GetBuffer(avail, &data);
            if (hr == AUDCLNT_E_DEVICE_INVALIDATED) { device_lost = true; break; }
            if (FAILED(hr)) { xruns++; continue; }
            cb_((float*)data, out_channels, (int)avail, capture_ ? inp : nullptr, capture_ ? std::min(in_channels, 8) : 0);
            render_->ReleaseBuffer(avail, 0);
        }
        if (mm) AvRevertMmThreadCharacteristics(mm);
    }
};

}  // namespace fmz
