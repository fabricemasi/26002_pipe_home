// fmz_audio_engine : guitare (pédale overdrive, simulation d'ampli non linéaire, cabinet IR).
// Une IR de cabinet est LINÉAIRE : elle ne remplace pas l'ampli. L'ampli (« amp ») est un
// modèle non linéaire à étages suréchantillonnés ×4 ; le cabinet (« cabinet ») convolue une IR.
#pragma once
#include <complex>
#include "dsp.h"
#include "wav.h"

namespace fmz {

// FFT complexe radix-2 itérative, tables précalculées (prepare hors temps réel).
class FFT {
public:
    void prepare(int n) {
        n_ = n; tw_.resize(n / 2); rev_.resize(n);
        for (int i = 0; i < n / 2; ++i) tw_[i] = std::polar(1.0f, (float)(-2 * kPi * i / n));
        int bits = 0; while ((1 << bits) < n) ++bits;
        for (int i = 0; i < n; ++i) { int r = 0; for (int b = 0; b < bits; ++b) if (i & (1 << b)) r |= 1 << (bits - 1 - b); rev_[i] = r; }
    }
    int size() const { return n_; }
    void run(std::complex<float>* a, bool inverse) const {
        for (int i = 0; i < n_; ++i) if (i < rev_[i]) std::swap(a[i], a[rev_[i]]);
        for (int len = 2; len <= n_; len <<= 1) {
            int step = n_ / len;
            for (int i = 0; i < n_; i += len)
                for (int j = 0; j < len / 2; ++j) {
                    std::complex<float> w = tw_[j * step];
                    if (inverse) w = std::conj(w);
                    std::complex<float> u = a[i + j], v = a[i + j + len / 2] * w;
                    a[i + j] = u + v; a[i + j + len / 2] = u - v;
                }
        }
        if (inverse) { float s = 1.0f / n_; for (int i = 0; i < n_; ++i) a[i] *= s; }
    }
private:
    int n_ = 0;
    std::vector<std::complex<float>> tw_;
    std::vector<int> rev_;
};

// Convolution sans latence : tête directe (B premiers coefficients) + queue en partitions FFT.
class Convolver {
public:
    static constexpr int B = 256;
    void prepare(const std::vector<float>& ir) {
        ir_len_ = (int)ir.size();
        head_.assign(B, 0.f);
        for (int i = 0; i < std::min(B, ir_len_); ++i) head_[i] = ir[i];
        hist_.assign(B, 0.f); hp_ = 0;
        fft_.prepare(2 * B);
        parts_ = ir_len_ > B ? (ir_len_ + B - 1) / B : 1;
        H_.assign((size_t)parts_ * 2 * B, {0, 0});
        for (int k = 1; k < parts_; ++k) {
            std::complex<float>* h = &H_[(size_t)k * 2 * B];
            for (int i = 0; i < B && k * B + i < ir_len_; ++i) h[i] = ir[k * B + i];
            fft_.run(h, false);
        }
        fdl_.assign((size_t)parts_ * 2 * B, {0, 0});
        fpos_ = 0;
        inblk_.assign(B, 0.f); in_n_ = 0;
        tail_.assign(3 * B, 0.f); tail_r_ = 0;
        work_.assign(2 * B, {0, 0}); acc_.assign(2 * B, {0, 0});
    }
    bool ready() const { return ir_len_ > 0; }
    void reset() { std::fill(hist_.begin(), hist_.end(), 0.f); std::fill(fdl_.begin(), fdl_.end(), std::complex<float>()); std::fill(tail_.begin(), tail_.end(), 0.f); in_n_ = 0; }
    inline float tick(float x) {
        // tête : FIR direct sur l'historique circulaire
        hist_[hp_] = x;
        float y = 0; int idx = hp_;
        for (int k = 0; k < B; ++k) { y += head_[k] * hist_[idx]; if (--idx < 0) idx = B - 1; }
        hp_ = (hp_ + 1) % B;
        // queue : sortie déjà calculée pour ce temps
        y += tail_[tail_r_]; tail_[tail_r_] = 0; tail_r_ = (tail_r_ + 1) % (3 * B);
        inblk_[in_n_++] = x;
        if (in_n_ == B) { in_n_ = 0; block_done(); }
        return y;
    }
private:
    int ir_len_ = 0, parts_ = 1, hp_ = 0, fpos_ = 0, in_n_ = 0, tail_r_ = 0;
    std::vector<float> head_, hist_, inblk_, tail_;
    std::vector<std::complex<float>> H_, fdl_, work_, acc_;
    FFT fft_;
    void block_done() {
        if (parts_ < 2) return;
        std::complex<float>* X = &fdl_[(size_t)fpos_ * 2 * B];
        for (int i = 0; i < B; ++i) { X[i] = inblk_[i]; X[B + i] = 0; }
        fft_.run(X, false);
        std::fill(acc_.begin(), acc_.end(), std::complex<float>());
        for (int k = 1; k < parts_; ++k) {
            int slot = fpos_ - (k - 1); if (slot < 0) slot += parts_;
            const std::complex<float>* Xs = &fdl_[(size_t)slot * 2 * B];
            const std::complex<float>* Hk = &H_[(size_t)k * 2 * B];
            for (int i = 0; i < 2 * B; ++i) acc_[i] += Xs[i] * Hk[i];
        }
        fft_.run(acc_.data(), true);
        // le bloc qui vient de se terminer commence la sortie au prochain échantillon (tail_r_)
        for (int i = 0; i < 2 * B; ++i) tail_[(tail_r_ + i) % (3 * B)] += acc_[i].real();
        fpos_ = (fpos_ + 1) % parts_;
    }
};

// Cabinet : IR chargée (`ir` = chemin WAV, ramenée à la fréquence du projet par
// interpolation linéaire, 1 s max) ; sans IR, modèle de haut-parleur par filtres, signalé comme tel.
// Clés : mix, output_db, low_cut, high_cut.
class CabinetFx : public Effect {
    double sr_ = 48000, mix_ = 1, out_ = 0;
    std::vector<float> ir_raw_; int ir_sr_ = 0;
    Convolver conv_[2];
    Biquad hp_, lp_, pk_;
    double lc_ = 80, hc_ = 6000;
public:
    std::string ir_path;
    std::string set_text(const char* k, const std::string& v) override {
        if (!key_is(k, "ir")) return std::string();
        try {
            AudioData a = wav_read(v);
            if (a.frames() == 0) return "IR vide : " + v;
            int64_t n = std::min<int64_t>(a.frames(), a.sample_rate);
            ir_raw_.assign(a.ch[0].begin(), a.ch[0].begin() + n);
            ir_sr_ = a.sample_rate; ir_path = v;
        } catch (const std::exception& e) { return std::string("IR illisible : ") + e.what(); }
        return std::string();
    }
    void prepare(double sr, int) override {
        sr_ = sr;
        if (!ir_raw_.empty()) {
            double ratio = (double)ir_sr_ / sr;
            int n = (int)(ir_raw_.size() / ratio);
            std::vector<float> ir(n);
            for (int i = 0; i < n; ++i) {
                double p = i * ratio; int i0 = (int)p; double f = p - i0;
                float a = ir_raw_[i0], b = i0 + 1 < (int)ir_raw_.size() ? ir_raw_[i0 + 1] : 0.f;
                ir[i] = (float)(a + (b - a) * f);
            }
            conv_[0].prepare(ir); conv_[1].prepare(ir);
        }
        hp_.design(Biquad::HighPass, sr, lc_, 0.707, 0); lp_.design(Biquad::LowPass, sr, hc_, 0.9, 0);
        pk_.design(Biquad::Peak, sr, 2500, 1.2, 4);
    }
    void reset() override { conv_[0].reset(); conv_[1].reset(); hp_.reset(); lp_.reset(); pk_.reset(); }
    void set(const char* k, double v) override {
        if (key_is(k, "mix")) mix_ = std::clamp(v, 0.0, 1.0); else if (key_is(k, "output_db")) out_ = v;
        else if (key_is(k, "low_cut")) { lc_ = v; hp_.design(Biquad::HighPass, sr_, lc_, 0.707, 0); }
        else if (key_is(k, "high_cut")) { hc_ = v; lp_.design(Biquad::LowPass, sr_, hc_, 0.9, 0); }
    }
    bool has_ir() const { return conv_[0].ready(); }
    double tail_seconds() const override { return 1.0; }
    void process(float* const* x, int n, float* const*) override {
        float o = (float)db_to_lin(out_);
        for (int c = 0; c < 2; ++c)
            for (int i = 0; i < n; ++i) {
                float dry = x[c][i], wet;
                if (conv_[c].ready()) wet = conv_[c].tick(dry);
                else wet = lp_.tick(pk_.tick(hp_.tick(dry, c), c), c);
                x[c][i] = (float)((dry * (1 - mix_) + wet * mix_) * o);
            }
    }
};

// Pédale overdrive (type « tube screamer » générique) : bosse de médiums, écrêtage doux suréchantillonné.
// Clés : drive (0..1), tone (0..1), level_db.
class OverdriveFx : public Effect {
    double sr_ = 48000, drive_ = 0.5, tone_ = 0.5, level_ = 0;
    Biquad pre_, post_; Oversampler4 os_;
    void redesign() { pre_.design(Biquad::HighPass, sr_, 720, 0.707, 0); post_.design(Biquad::LowPass, sr_, 1000 + tone_ * 7000, 0.707, 0); }
public:
    void prepare(double sr, int) override { sr_ = sr; os_.prepare(sr); redesign(); }
    void reset() override { pre_.reset(); post_.reset(); os_.reset(); }
    void set(const char* k, double v) override {
        if (key_is(k, "drive")) drive_ = std::clamp(v, 0.0, 1.0); else if (key_is(k, "tone")) tone_ = std::clamp(v, 0.0, 1.0);
        else if (key_is(k, "level_db")) level_ = v;
        redesign();
    }
    void process(float* const* x, int n, float* const*) override {
        float g = (float)db_to_lin(6 + drive_ * 40), lv = (float)db_to_lin(level_ - 6);
        for (int c = 0; c < 2; ++c)
            for (int i = 0; i < n; ++i) {
                float in = x[c][i];
                float mid = pre_.tick(in, c);
                float clipped = os_.run(mid * g, c, [](float u) { return std::tanh(u); });
                // le signal non filtré passe aussi (mélange clean/clip du circuit d'origine)
                x[c][i] = post_.tick(clipped + (in - mid), c) * lv;
            }
    }
};

// Simulation d'ampli non linéaire : préampli 2 étages (asymétrique, polarisé), tonestack,
// présence, étage de puissance avec « sag » (compression dépendant de l'enveloppe).
// Clés : channel (0 clair, 1 crunch, 2 lead), gain (0..1), bass, mid, treble, presence (-12..12 dB), master_db, sag (0..1).
class AmpFx : public Effect {
    double sr_ = 48000, gain_ = 0.5, bass_ = 0, mid_ = 0, treble_ = 0, presence_ = 0, master_ = -6, sag_ = 0.3;
    int channel_ = 1;
    Biquad couple_, bassf_, midf_, trebf_, presf_, inter_;
    Oversampler4 os1_, os2_;
    EnvFollower env_;
    void redesign() {
        couple_.design(Biquad::HighPass, sr_, 90, 0.707, 0);
        bassf_.design(Biquad::LowShelf, sr_, 120, 0.7, bass_);
        midf_.design(Biquad::Peak, sr_, 700, 0.8, mid_);
        trebf_.design(Biquad::HighShelf, sr_, 3000, 0.7, treble_);
        presf_.design(Biquad::HighShelf, sr_, 4500, 0.7, presence_);
        inter_.design(Biquad::LowPass, sr_, 9000, 0.707, 0);
        env_.set(sr_, 5, 150);
    }
public:
    void prepare(double sr, int) override { sr_ = sr; os1_.prepare(sr); os2_.prepare(sr); redesign(); }
    void reset() override { os1_.reset(); os2_.reset(); couple_.reset(); bassf_.reset(); midf_.reset(); trebf_.reset(); presf_.reset(); inter_.reset(); env_.env = 0; }
    void set(const char* k, double v) override {
        if (key_is(k, "channel")) channel_ = std::clamp((int)v, 0, 2); else if (key_is(k, "gain")) gain_ = std::clamp(v, 0.0, 1.0);
        else if (key_is(k, "bass")) bass_ = std::clamp(v, -12.0, 12.0); else if (key_is(k, "mid")) mid_ = std::clamp(v, -12.0, 12.0);
        else if (key_is(k, "treble")) treble_ = std::clamp(v, -12.0, 12.0); else if (key_is(k, "presence")) presence_ = std::clamp(v, -12.0, 12.0);
        else if (key_is(k, "master_db")) master_ = v; else if (key_is(k, "sag")) sag_ = std::clamp(v, 0.0, 1.0);
        redesign();
    }
    // Triode simplifiée : courbe asymétrique avec polarisation (harmoniques paires), bornée.
    static inline float triode(float u) {
        const float bias = 0.2f;
        float y = std::tanh(u + bias) - std::tanh(bias);
        return u < -1.5f ? y * 0.85f : y;
    }
    void process(float* const* x, int n, float* const*) override {
        static const double base_db[3] = {0, 18, 32};
        float g1 = (float)db_to_lin(base_db[channel_] + gain_ * 24), g2 = (float)db_to_lin(channel_ * 6 + gain_ * 12);
        float m = (float)db_to_lin(master_);
        for (int i = 0; i < n; ++i) {
            double e = env_.tick(std::max(std::abs(x[0][i]), std::abs(x[1][i])));
            float sag = (float)(1.0 / (1.0 + sag_ * 4.0 * e));
            for (int c = 0; c < 2; ++c) {
                float v = couple_.tick(x[c][i], c);
                v = os1_.run(v * g1, c, triode);
                v = inter_.tick(v, c);
                v = trebf_.tick(midf_.tick(bassf_.tick(v, c), c), c);
                v = os2_.run(v * g2 * sag, c, triode);
                v = presf_.tick(v, c);
                float p = std::tanh(v * 1.5f) / 1.5f;  // étage de puissance (écrêtage doux)
                x[c][i] = p * m;
            }
        }
    }
};

inline std::unique_ptr<Effect> make_amp_effect(const std::string& type) {
    if (type == "amp") return std::make_unique<AmpFx>();
    if (type == "cabinet") return std::make_unique<CabinetFx>();
    if (type == "overdrive") return std::make_unique<OverdriveFx>();
    return nullptr;
}

}  // namespace fmz
