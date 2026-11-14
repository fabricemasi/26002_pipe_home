// fmz_audio_engine : lecture / écriture WAV (RIFF et RF64), chemins Unicode.
// Hors temps réel uniquement (chargement des médias, rendu offline, capture par worker).
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace fmz {

inline std::wstring widen(const std::string& u8) {
#ifdef _WIN32
    if (u8.empty()) return std::wstring();
    int n = MultiByteToWideChar(CP_UTF8, 0, u8.data(), (int)u8.size(), nullptr, 0);
    std::wstring w(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, u8.data(), (int)u8.size(), w.data(), n);
    // Chemins longs : préfixe \\?\ pour un chemin absolu à lettre de lecteur.
    if (w.size() > 240 && w.size() > 2 && w[1] == L':') {
        for (auto& c : w) if (c == L'/') c = L'\\';
        w = L"\\\\?\\" + w;
    }
    return w;
#else
    return std::wstring(u8.begin(), u8.end());
#endif
}

inline FILE* open_file(const std::string& path, const char* mode) {
#ifdef _WIN32
    std::wstring wm(mode, mode + strlen(mode));
    return _wfopen(widen(path).c_str(), wm.c_str());
#else
    return fopen(path.c_str(), mode);
#endif
}

inline bool file_exists(const std::string& path) {
    FILE* f = open_file(path, "rb");
    if (!f) return false;
    fclose(f);
    return true;
}

inline bool rename_file(const std::string& from, const std::string& to, bool replace) {
#ifdef _WIN32
    return MoveFileExW(widen(from).c_str(), widen(to).c_str(),
                       MOVEFILE_WRITE_THROUGH | (replace ? MOVEFILE_REPLACE_EXISTING : 0)) != 0;
#else
    return std::rename(from.c_str(), to.c_str()) == 0;
#endif
}

inline void remove_file(const std::string& path) {
#ifdef _WIN32
    DeleteFileW(widen(path).c_str());
#else
    std::remove(path.c_str());
#endif
}

// Audio en mémoire, canaux séparés (float32).
struct AudioData {
    int sample_rate = 48000;
    std::vector<std::vector<float>> ch;
    int64_t frames() const { return ch.empty() ? 0 : (int64_t)ch[0].size(); }
    int channels() const { return (int)ch.size(); }
};

struct WavInfo {
    int sample_rate = 0;
    int channels = 0;
    int bits = 0;
    bool is_float = false;
    int64_t frames = 0;
    int64_t data_offset = 0;
    bool rf64 = false;
};

namespace detail {
inline uint32_t rd32(const unsigned char* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
inline uint16_t rd16(const unsigned char* p) { return (uint16_t)(p[0] | (p[1] << 8)); }
inline uint64_t rd64(const unsigned char* p) { return (uint64_t)rd32(p) | ((uint64_t)rd32(p + 4) << 32); }
}

// Lit l'en-tête ; lève une exception explicite si le fichier n'est pas un WAV pris en charge.
inline WavInfo wav_probe(FILE* f) {
    using namespace detail;
    WavInfo info;
    unsigned char h[12];
    if (fread(h, 1, 12, f) != 12) throw std::runtime_error("fichier trop court");
    bool rf64 = memcmp(h, "RF64", 4) == 0 || memcmp(h, "BW64", 4) == 0;
    if (!(memcmp(h, "RIFF", 4) == 0 || rf64) || memcmp(h + 8, "WAVE", 4) != 0)
        throw std::runtime_error("pas un fichier WAV");
    info.rf64 = rf64;
    uint64_t ds64_data = 0;
    bool have_fmt = false;
    for (;;) {
        unsigned char ck[8];
        if (fread(ck, 1, 8, f) != 8) break;
        uint32_t size = rd32(ck + 4);
        long long here = _ftelli64(f);
        if (memcmp(ck, "ds64", 4) == 0) {
            unsigned char d[24];
            if (fread(d, 1, 24, f) != 24) throw std::runtime_error("ds64 tronqué");
            ds64_data = rd64(d + 8);
        } else if (memcmp(ck, "fmt ", 4) == 0) {
            unsigned char d[40] = {0};
            size_t want = size < 40 ? size : 40;
            if (fread(d, 1, want, f) != want) throw std::runtime_error("fmt tronqué");
            uint16_t tag = rd16(d);
            info.channels = rd16(d + 2);
            info.sample_rate = (int)rd32(d + 4);
            info.bits = rd16(d + 14);
            if (tag == 0xFFFE && size >= 40) tag = rd16(d + 24);  // WAVE_FORMAT_EXTENSIBLE
            if (tag == 3) info.is_float = true;
            else if (tag != 1) throw std::runtime_error("format WAV non pris en charge (tag " + std::to_string(tag) + ")");
            have_fmt = true;
        } else if (memcmp(ck, "data", 4) == 0) {
            if (!have_fmt) throw std::runtime_error("chunk data avant fmt");
            uint64_t bytes = (rf64 && size == 0xFFFFFFFFu) ? ds64_data : size;
            info.data_offset = here;
            int bpf = info.channels * (info.bits / 8);
            if (bpf <= 0) throw std::runtime_error("format invalide");
            // Fichier tronqué (prise interrompue) : on lit ce qui existe réellement.
            _fseeki64(f, 0, SEEK_END);
            long long end = _ftelli64(f);
            uint64_t avail = (uint64_t)(end - here);
            if (bytes > avail) bytes = avail;
            // Prise non finalisée (panne) : en-tête à 0 mais données présentes : on lit ce qui existe.
            if (bytes == 0 && avail > 0) bytes = avail;
            info.frames = (int64_t)(bytes / (uint64_t)bpf);
            return info;
        }
        _fseeki64(f, here + size + (size & 1), SEEK_SET);
    }
    throw std::runtime_error("chunk data absent");
}

inline WavInfo wav_info(const std::string& path) {
    FILE* f = open_file(path, "rb");
    if (!f) throw std::runtime_error("ouverture impossible : " + path);
    try { WavInfo i = wav_probe(f); fclose(f); return i; }
    catch (...) { fclose(f); throw; }
}

// Lit [start, start+count) images ; count < 0 = jusqu'à la fin.
inline AudioData wav_read(const std::string& path, int64_t start = 0, int64_t count = -1) {
    FILE* f = open_file(path, "rb");
    if (!f) throw std::runtime_error("ouverture impossible : " + path);
    AudioData out;
    try {
        WavInfo info = wav_probe(f);
        out.sample_rate = info.sample_rate;
        if (start < 0) start = 0;
        if (start > info.frames) start = info.frames;
        int64_t n = info.frames - start;
        if (count >= 0 && count < n) n = count;
        int bps = info.bits / 8, nc = info.channels;
        out.ch.assign(nc, std::vector<float>((size_t)n));
        _fseeki64(f, info.data_offset + start * nc * bps, SEEK_SET);
        const int64_t chunk = 65536;
        std::vector<unsigned char> buf((size_t)(chunk * nc * bps));
        int64_t done = 0;
        while (done < n) {
            int64_t m = n - done < chunk ? n - done : chunk;
            size_t got = fread(buf.data(), (size_t)(nc * bps), (size_t)m, f);
            for (size_t i = 0; i < got; ++i) {
                const unsigned char* p = buf.data() + i * nc * bps;
                for (int c = 0; c < nc; ++c, p += bps) {
                    float v;
                    if (info.is_float) {
                        if (bps == 4) { float x; memcpy(&x, p, 4); v = x; }
                        else { double x; memcpy(&x, p, 8); v = (float)x; }
                    } else if (bps == 2) v = (int16_t)detail::rd16(p) / 32768.0f;
                    else if (bps == 3) { int32_t x = (int32_t)((p[0] << 8) | (p[1] << 16) | ((uint32_t)p[2] << 24)) >> 8; v = x / 8388608.0f; }
                    else if (bps == 4) v = (float)((int32_t)detail::rd32(p) / 2147483648.0);
                    else v = (p[0] - 128) / 128.0f;
                    out.ch[c][(size_t)(done + i)] = v;
                }
            }
            if ((int64_t)got < m) { // fin réelle plus courte que l'en-tête : on tronque
                for (auto& c : out.ch) c.resize((size_t)(done + got));
                break;
            }
            done += m;
        }
    } catch (...) { fclose(f); throw; }
    fclose(f);
    return out;
}

// Écrivain WAV progressif : en-tête RIFF avec réserve JUNK (devient ds64 si > 4 Gio : RF64).
// Écrit dans <dest>.part puis renomme : un export annulé ou interrompu ne remplace rien.
class WavWriter {
public:
    enum Format { F32 = 0, PCM16 = 1, PCM24 = 2 };
    WavWriter() = default;
    ~WavWriter() { if (f_) abort(); }
    void open(const std::string& dest, int sample_rate, int channels, Format fmt, bool dither, bool overwrite) {
        if (!overwrite && file_exists(dest)) throw std::runtime_error("le fichier existe déjà : " + dest);
        dest_ = dest;
        tmp_ = dest + ".part";
        overwrite_ = overwrite;
        f_ = open_file(tmp_, "wb");
        if (!f_) throw std::runtime_error("écriture impossible : " + tmp_);
        sr_ = sample_rate; nc_ = channels; fmt_ = fmt; dither_ = dither && fmt != F32;
        bps_ = fmt == F32 ? 4 : (fmt == PCM16 ? 2 : 3);
        frames_ = 0;
        write_header(false);
    }
    // Écrit n images à partir de pointeurs par canal.
    void write(const float* const* chans, int64_t n) {
        buf_.resize((size_t)(n * nc_ * bps_));
        unsigned char* p = buf_.data();
        for (int64_t i = 0; i < n; ++i) {
            for (int c = 0; c < nc_; ++c) {
                float v = chans[c][i];
                if (!std::isfinite(v)) v = 0.0f;
                if (fmt_ == F32) { memcpy(p, &v, 4); p += 4; continue; }
                double scale = fmt_ == PCM16 ? 32767.0 : 8388607.0;
                double x = v * scale;
                if (dither_) x += tpdf();
                long long q = (long long)std::floor(x + 0.5);
                long long lim = (long long)scale;
                if (q > lim) q = lim;
                if (q < -lim - 1) q = -lim - 1;
                if (fmt_ == PCM16) { p[0] = (unsigned char)(q & 0xFF); p[1] = (unsigned char)((q >> 8) & 0xFF); p += 2; }
                else { p[0] = (unsigned char)(q & 0xFF); p[1] = (unsigned char)((q >> 8) & 0xFF); p[2] = (unsigned char)((q >> 16) & 0xFF); p += 3; }
            }
        }
        if (fwrite(buf_.data(), 1, buf_.size(), f_) != buf_.size())
            throw std::runtime_error("écriture interrompue (disque plein ?)");
        frames_ += n;
    }
    int64_t frames() const { return frames_; }
    // Finalise : en-tête correct, fflush, renommage atomique. Retourne le chemin final.
    std::string close() {
        write_header(true);
        fflush(f_);
        fclose(f_);
        f_ = nullptr;
        if (!rename_file(tmp_, dest_, overwrite_)) {
            remove_file(tmp_);
            throw std::runtime_error("renommage impossible vers " + dest_);
        }
        return dest_;
    }
    void abort() {
        if (f_) { fclose(f_); f_ = nullptr; }
        remove_file(tmp_);
    }
private:
    FILE* f_ = nullptr;
    std::string dest_, tmp_;
    bool overwrite_ = false, dither_ = false;
    int sr_ = 48000, nc_ = 2, bps_ = 4;
    Format fmt_ = F32;
    int64_t frames_ = 0;
    uint32_t rng_ = 0x12345678u;
    std::vector<unsigned char> buf_;
    double uni() { rng_ = rng_ * 1664525u + 1013904223u; return (rng_ >> 8) / 16777216.0; }
    double tpdf() { return uni() - uni(); }  // dither triangulaire ±1 LSB
    static void w32(unsigned char* p, uint32_t v) { p[0] = v & 0xFF; p[1] = (v >> 8) & 0xFF; p[2] = (v >> 16) & 0xFF; p[3] = (v >> 24) & 0xFF; }
    static void w16(unsigned char* p, uint16_t v) { p[0] = v & 0xFF; p[1] = (v >> 8) & 0xFF; }
    static void w64(unsigned char* p, uint64_t v) { w32(p, (uint32_t)v); w32(p + 4, (uint32_t)(v >> 32)); }
    void write_header(bool final_) {
        // RIFF(12) + JUNK/ds64(8+28) + fmt(8+16) + data(8) = 80 octets
        unsigned char h[80] = {0};
        uint64_t data_bytes = (uint64_t)frames_ * nc_ * bps_;
        bool big = final_ && data_bytes + 72 > 0xFFFFFFF0ull;
        memcpy(h, big ? "RF64" : "RIFF", 4);
        w32(h + 4, big ? 0xFFFFFFFFu : (uint32_t)(72 + data_bytes));
        memcpy(h + 8, "WAVE", 4);
        memcpy(h + 12, big ? "ds64" : "JUNK", 4);
        w32(h + 16, 28);
        if (big) { w64(h + 20, 72 + data_bytes); w64(h + 28, data_bytes); w64(h + 36, (uint64_t)frames_); }
        memcpy(h + 48, "fmt ", 4);
        w32(h + 52, 16);
        w16(h + 56, fmt_ == F32 ? 3 : 1);
        w16(h + 58, (uint16_t)nc_);
        w32(h + 60, (uint32_t)sr_);
        w32(h + 64, (uint32_t)(sr_ * nc_ * bps_));
        w16(h + 68, (uint16_t)(nc_ * bps_));
        w16(h + 70, (uint16_t)(bps_ * 8));
        memcpy(h + 72, "data", 4);
        w32(h + 76, big ? 0xFFFFFFFFu : (uint32_t)data_bytes);
        long long pos = _ftelli64(f_);
        _fseeki64(f_, 0, SEEK_SET);
        fwrite(h, 1, 80, f_);
        if (pos > 80) _fseeki64(f_, pos, SEEK_SET);
    }
};

}  // namespace fmz
