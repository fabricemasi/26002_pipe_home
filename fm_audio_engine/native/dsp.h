// fmz_audio_engine : traitements (effets) temps réel.
// Contrat : prepare() alloue (hors temps réel) ; process() et set() n'allouent rien,
// ne verrouillent rien, n'écrivent rien sur disque. Paramètres documentés dans
// docs/agents/fm_audio.md, section « Effets du moteur ».
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace fmz {

constexpr double kPi = 3.14159265358979323846;
inline double db_to_lin(double db) { return db <= -120.0 ? 0.0 : std::pow(10.0, db / 20.0); }
inline double lin_to_db(double v) { return v <= 1e-6 ? -120.0 : 20.0 * std::log10(v); }
inline bool key_is(const char* k, const char* w) { return std::strcmp(k, w) == 0; }

// Biquad (RBJ Audio EQ Cookbook), forme directe transposée II.
struct Biquad {
    double b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
    double z1[2] = {0, 0}, z2[2] = {0, 0};
    enum Kind { Peak, LowShelf, HighShelf, LowPass, HighPass, BandPass, Notch, AllPass };
    void reset() { z1[0] = z1[1] = z2[0] = z2[1] = 0; }
    void design(Kind k, double sr, double f, double q, double gain_db) {
        f = std::clamp(f, 10.0, sr * 0.49);
        q = std::max(q, 0.05);
        double A = std::pow(10.0, gain_db / 40.0), w = 2 * kPi * f / sr, cw = std::cos(w), sw = std::sin(w);
        double al = sw / (2 * q), a0 = 1;
        switch (k) {
            case Peak: b0 = 1 + al * A; b1 = -2 * cw; b2 = 1 - al * A; a0 = 1 + al / A; a1 = -2 * cw; a2 = 1 - al / A; break;
            case LowShelf: { double s = 2 * std::sqrt(A) * al;
                b0 = A * ((A + 1) - (A - 1) * cw + s); b1 = 2 * A * ((A - 1) - (A + 1) * cw); b2 = A * ((A + 1) - (A - 1) * cw - s);
                a0 = (A + 1) + (A - 1) * cw + s; a1 = -2 * ((A - 1) + (A + 1) * cw); a2 = (A + 1) + (A - 1) * cw - s; break; }
            case HighShelf: { double s = 2 * std::sqrt(A) * al;
                b0 = A * ((A + 1) + (A - 1) * cw + s); b1 = -2 * A * ((A - 1) + (A + 1) * cw); b2 = A * ((A + 1) + (A - 1) * cw - s);
                a0 = (A + 1) - (A - 1) * cw + s; a1 = 2 * ((A - 1) - (A + 1) * cw); a2 = (A + 1) - (A - 1) * cw - s; break; }
            case LowPass: b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2; a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al; break;
            case HighPass: b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = (1 + cw) / 2; a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al; break;
            case BandPass: b0 = al; b1 = 0; b2 = -al; a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al; break;
            case Notch: b0 = 1; b1 = -2 * cw; b2 = 1; a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al; break;
            case AllPass: b0 = 1 - al; b1 = -2 * cw; b2 = 1 + al; a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al; break;
        }
        b0 /= a0; b1 /= a0; b2 /= a0; a1 /= a0; a2 /= a0;
    }
    inline float tick(float x, int c) {
        double y = b0 * x + z1[c];
        z1[c] = b1 * x - a1 * y + z2[c];
        z2[c] = b2 * x - a2 * y;
        if (std::abs(z1[c]) < 1e-25) z1[c] = 0;  // anti-dénormaux
        if (std::abs(z2[c]) < 1e-25) z2[c] = 0;
        return (float)y;
    }
    static Kind kind_from(const std::string& s) {
        if (s == "lowshelf") return LowShelf; if (s == "highshelf") return HighShelf;
        if (s == "lowpass") return LowPass; if (s == "highpass") return HighPass;
        if (s == "bandpass") return BandPass; if (s == "notch") return Notch;
        if (s == "allpass") return AllPass; return Peak;
    }
};

// Lissage d'un paramètre continu (~10 ms) : pas de saut audible.
struct Smooth {
    double cur = 0, target = 0, coef = 0.999;
    void prepare(double sr, double ms = 10.0) { coef = std::exp(-1.0 / (sr * ms / 1000.0)); }
    void snap(double v) { cur = target = v; }
    inline double next() { cur = target + (cur - target) * coef; return cur; }
};

class Effect {
public:
    virtual ~Effect() = default;
    virtual void prepare(double sr, int max_block) = 0;
    // x : 2 canaux (stéréo interne). sc : signal de sidechain (2 canaux) ou nullptr.
    virtual void process(float* const* x, int n, float* const* sc) = 0;
    virtual void set(const char* key, double v) = 0;  // temps réel : aucune allocation
    // Paramètre texte (chemin d'IR, etc.) : HORS temps réel, à la construction du graphe.
    // Retourne un message d'erreur vide si tout va bien.
    virtual std::string set_text(const char*, const std::string&) { return std::string(); }
    virtual int latency() const { return 0; }
    virtual void reset() {}
    virtual double tail_seconds() const { return 0.0; }
    // Réduction de gain courante (dB, ≤ 0), lue par la télémétrie.
    virtual float meter_gr() const { return 0.f; }
    bool bypass = false;
    bool wants_sidechain = false;
};

class GainFx : public Effect {
    Smooth g_; bool pol_ = false; double sr_ = 48000;
public:
    void prepare(double sr, int) override { sr_ = sr; g_.prepare(sr); g_.snap(g_.target); }
    void set(const char* k, double v) override {
        if (key_is(k, "gain_db")) g_.target = db_to_lin(v);
        else if (key_is(k, "polarity")) pol_ = v != 0;
    }
    GainFx() { g_.snap(1.0); }
    void process(float* const* x, int n, float* const*) override {
        double s = pol_ ? -1.0 : 1.0;
        for (int i = 0; i < n; ++i) { double g = g_.next() * s; x[0][i] *= (float)g; x[1][i] *= (float)g; }
    }
};

// EQ paramétrique : 6 bandes, chacune désactivable. Clés : bN_on, bN_type, bN_freq, bN_gain_db, bN_q.
class EqFx : public Effect {
public:
    static constexpr int kBands = 6;
    struct Band { bool on = false; Biquad::Kind kind = Biquad::Peak; double f = 1000, g = 0, q = 0.707; Biquad bq; };
    Band b[kBands];
    double sr_ = 48000;
    void prepare(double sr, int) override { sr_ = sr; for (auto& x : b) { x.bq.design(x.kind, sr_, x.f, x.q, x.g); x.bq.reset(); } }
    void reset() override { for (auto& x : b) x.bq.reset(); }
    void set(const char* k, double v) override {
        if (k[0] != 'b' || k[1] < '0' || k[1] >= '0' + kBands || k[2] != '_') return;
        Band& x = b[k[1] - '0'];
        const char* p = k + 3;
        if (key_is(p, "on")) x.on = v != 0;
        else if (key_is(p, "type")) x.kind = (Biquad::Kind)(int)v;
        else if (key_is(p, "freq")) x.f = v;
        else if (key_is(p, "gain_db")) x.g = v;
        else if (key_is(p, "q")) x.q = v;
        x.bq.design(x.kind, sr_, x.f, x.q, x.g);
    }
    void process(float* const* x, int n, float* const*) override {
        for (auto& band : b) {
            if (!band.on) continue;
            for (int c = 0; c < 2; ++c) for (int i = 0; i < n; ++i) x[c][i] = band.bq.tick(x[c][i], c);
        }
    }
};

// Filtre simple : type (0 passe-bas, 1 passe-haut, 2 passe-bande), freq, q.
class FilterFx : public Effect {
    Biquad bq_; int type_ = 0; double f_ = 1000, q_ = 0.707, sr_ = 48000;
    void redesign() { bq_.design(type_ == 1 ? Biquad::HighPass : type_ == 2 ? Biquad::BandPass : Biquad::LowPass, sr_, f_, q_, 0); }
public:
    void prepare(double sr, int) override { sr_ = sr; redesign(); bq_.reset(); }
    void reset() override { bq_.reset(); }
    void set(const char* k, double v) override {
        if (key_is(k, "type")) type_ = (int)v; else if (key_is(k, "freq")) f_ = v; else if (key_is(k, "q")) q_ = v;
        redesign();
    }
    void process(float* const* x, int n, float* const*) override {
        for (int c = 0; c < 2; ++c) for (int i = 0; i < n; ++i) x[c][i] = bq_.tick(x[c][i], c);
    }
};

// Détecteur d'enveloppe crête, attaque / relâchement en ms.
struct EnvFollower {
    double a = 0, r = 0, env = 0;
    void set(double sr, double att_ms, double rel_ms) {
        a = std::exp(-1.0 / (sr * std::max(att_ms, 0.01) / 1000.0));
        r = std::exp(-1.0 / (sr * std::max(rel_ms, 0.1) / 1000.0));
    }
    inline double tick(double x) { double c = x > env ? a : r; env = x + (env - x) * c; return env; }
};

// Compresseur feed-forward stéréo lié. Clés : threshold_db, ratio, attack_ms, release_ms,
// knee_db, makeup_db, sidechain (0/1 : détection sur l'entrée sidechain), mix (0..1).
class CompressorFx : public Effect {
    double sr_ = 48000, thr_ = -18, ratio_ = 4, att_ = 10, rel_ = 120, knee_ = 6, makeup_ = 0, mix_ = 1;
    EnvFollower env_; float gr_ = 0;
public:
    void prepare(double sr, int) override { sr_ = sr; env_.set(sr_, att_, rel_); }
    void reset() override { env_.env = 0; }
    void set(const char* k, double v) override {
        if (key_is(k, "threshold_db")) thr_ = v; else if (key_is(k, "ratio")) ratio_ = std::max(1.0, v);
        else if (key_is(k, "attack_ms")) att_ = v; else if (key_is(k, "release_ms")) rel_ = v;
        else if (key_is(k, "knee_db")) knee_ = std::max(0.0, v); else if (key_is(k, "makeup_db")) makeup_ = v;
        else if (key_is(k, "sidechain")) wants_sidechain = v != 0; else if (key_is(k, "mix")) mix_ = std::clamp(v, 0.0, 1.0);
        env_.set(sr_, att_, rel_);
    }
    double gain_db_for(double in_db) const {
        double over = in_db - thr_;
        if (knee_ > 0 && 2 * std::abs(over) <= knee_) {
            double t = over + knee_ / 2;
            return (1.0 / ratio_ - 1.0) * t * t / (2 * knee_);
        }
        return over > 0 ? over * (1.0 / ratio_ - 1.0) : 0.0;
    }
    void process(float* const* x, int n, float* const* sc) override {
        const float* const* det = (wants_sidechain && sc) ? sc : x;
        double mk = db_to_lin(makeup_), worst = 0;
        for (int i = 0; i < n; ++i) {
            double lvl = std::max(std::abs(det[0][i]), std::abs(det[1][i]));
            double e = env_.tick(lvl);
            double gdb = gain_db_for(lin_to_db(e));
            worst = std::min(worst, gdb);
            double g = db_to_lin(gdb) * mk;
            for (int c = 0; c < 2; ++c) x[c][i] = (float)(x[c][i] * (mix_ * g + (1 - mix_)));
        }
        gr_ = (float)worst;
    }
    float meter_gr() const override { return gr_; }
};

// Limiteur à anticipation (latence déclarée = lookahead). Clés : ceiling_db, release_ms, lookahead_ms (fixé à prepare).
class LimiterFx : public Effect {
    double sr_ = 48000, ceil_ = -1.0, rel_ = 80, look_ms_ = 5;
    int look_ = 240, pos_ = 0;
    std::vector<float> d0_, d1_, peak_;
    double g_ = 1.0, rcoef_ = 0.999; float gr_ = 0;
public:
    void prepare(double sr, int) override {
        sr_ = sr;
        look_ = std::max(1, (int)std::lround(sr * look_ms_ / 1000.0));
        d0_.assign(look_, 0.f); d1_.assign(look_, 0.f); peak_.assign(look_, 0.f);
        pos_ = 0; g_ = 1.0;
        rcoef_ = std::exp(-1.0 / (sr * rel_ / 1000.0));
    }
    void reset() override { std::fill(d0_.begin(), d0_.end(), 0.f); std::fill(d1_.begin(), d1_.end(), 0.f); std::fill(peak_.begin(), peak_.end(), 0.f); g_ = 1; }
    void set(const char* k, double v) override {
        if (key_is(k, "ceiling_db")) ceil_ = std::min(v, 0.0);
        else if (key_is(k, "release_ms")) { rel_ = std::max(1.0, v); rcoef_ = std::exp(-1.0 / (sr_ * rel_ / 1000.0)); }
        else if (key_is(k, "lookahead_ms")) look_ms_ = std::clamp(v, 0.5, 20.0);  // pris en compte au prochain prepare
    }
    int latency() const override { return look_; }
    void process(float* const* x, int n, float* const*) override {
        double c = db_to_lin(ceil_); double worst = 1.0;
        for (int i = 0; i < n; ++i) {
            float in0 = x[0][i], in1 = x[1][i];
            peak_[pos_] = std::max(std::abs(in0), std::abs(in1));
            // Crête maximale de la fenêtre d'anticipation (fenêtre courte : balayage borné).
            float m = 0; for (int j = 0; j < look_; ++j) m = std::max(m, peak_[j]);
            double need = m > c ? c / m : 1.0;
            if (need < g_) g_ = need; else g_ = need + (g_ - need) * rcoef_;
            worst = std::min(worst, g_);
            float o0 = d0_[pos_], o1 = d1_[pos_];
            d0_[pos_] = in0; d1_[pos_] = in1;
            pos_ = (pos_ + 1) % look_;
            double gg = g_;
            float y0 = (float)(o0 * gg), y1 = (float)(o1 * gg);
            x[0][i] = std::clamp(y0, (float)-c, (float)c);
            x[1][i] = std::clamp(y1, (float)-c, (float)c);
        }
        gr_ = (float)lin_to_db(worst);
    }
    float meter_gr() const override { return gr_; }
};

// Noise gate. Clés : threshold_db, attack_ms, hold_ms, release_ms, range_db (atténuation quand fermé), sidechain.
class GateFx : public Effect {
    double sr_ = 48000, thr_ = -50, att_ = 1, hold_ = 30, rel_ = 100, range_ = -80;
    EnvFollower det_; double g_ = 0; int64_t held_ = 0; float gr_ = 0;
public:
    void prepare(double sr, int) override { sr_ = sr; det_.set(sr, 0.1, 30); }
    void reset() override { det_.env = 0; g_ = 0; held_ = 0; }
    void set(const char* k, double v) override {
        if (key_is(k, "threshold_db")) thr_ = v; else if (key_is(k, "attack_ms")) att_ = v; else if (key_is(k, "hold_ms")) hold_ = v;
        else if (key_is(k, "release_ms")) rel_ = v; else if (key_is(k, "range_db")) range_ = std::min(0.0, v);
        else if (key_is(k, "sidechain")) wants_sidechain = v != 0;
    }
    void process(float* const* x, int n, float* const* sc) override {
        const float* const* det = (wants_sidechain && sc) ? sc : x;
        double floor_ = db_to_lin(range_), thr = db_to_lin(thr_);
        double ac = std::exp(-1.0 / (sr_ * std::max(att_, 0.01) / 1000.0)), rc = std::exp(-1.0 / (sr_ * std::max(rel_, 0.1) / 1000.0));
        int64_t hold_n = (int64_t)(sr_ * hold_ / 1000.0);
        double worst = 1;
        for (int i = 0; i < n; ++i) {
            double e = det_.tick(std::max(std::abs(det[0][i]), std::abs(det[1][i])));
            double target;
            if (e >= thr) { target = 1; held_ = hold_n; }
            else if (held_ > 0) { target = 1; --held_; }
            else target = 0;
            g_ = target + (g_ - target) * (target > g_ ? ac : rc);
            double gain = floor_ + (1 - floor_) * g_;
            worst = std::min(worst, gain);
            x[0][i] = (float)(x[0][i] * gain); x[1][i] = (float)(x[1][i] * gain);
        }
        gr_ = (float)lin_to_db(worst);
    }
    float meter_gr() const override { return gr_; }
};

// De-esser à bande partagée : seule la bande haute (≥ freq) est atténuée quand elle dépasse le seuil.
// Clés : freq, threshold_db, ratio, release_ms.
class DeesserFx : public Effect {
    double sr_ = 48000, f_ = 6000, thr_ = -30, ratio_ = 6, rel_ = 60;
    // Séparation Linkwitz-Riley d'ordre 4 (2 Butterworth en cascade) : bas + haut = passe-tout,
    // donc gain 1 partout quand rien n'est atténué.
    Biquad hp_, hp2_, lp_, lp2_, det_; EnvFollower env_; float gr_ = 0;
    void redesign() {
        hp_.design(Biquad::HighPass, sr_, f_, 0.7071, 0); hp2_ = hp_;
        lp_.design(Biquad::LowPass, sr_, f_, 0.7071, 0); lp2_ = lp_;
        hp_.reset(); hp2_.reset(); lp_.reset(); lp2_.reset();
        det_.design(Biquad::BandPass, sr_, f_ * 1.2, 1.0, 0); env_.set(sr_, 0.5, rel_);
    }
public:
    void prepare(double sr, int) override { sr_ = sr; redesign(); }
    void reset() override { hp_.reset(); hp2_.reset(); lp_.reset(); lp2_.reset(); det_.reset(); env_.env = 0; }
    void set(const char* k, double v) override {
        if (key_is(k, "freq")) f_ = v; else if (key_is(k, "threshold_db")) thr_ = v;
        else if (key_is(k, "ratio")) ratio_ = std::max(1.0, v); else if (key_is(k, "release_ms")) rel_ = v;
        redesign();
    }
    void process(float* const* x, int n, float* const*) override {
        double worst = 0;
        for (int i = 0; i < n; ++i) {
            double s = 0.5 * (x[0][i] + x[1][i]);
            double e = env_.tick(std::abs(det_.tick((float)s, 0)));
            double over = lin_to_db(e) - thr_;
            double gdb = over > 0 ? over * (1.0 / ratio_ - 1.0) : 0.0;
            worst = std::min(worst, gdb);
            double g = db_to_lin(gdb);
            for (int c = 0; c < 2; ++c) {
                float hi = hp2_.tick(hp_.tick(x[c][i], c), c), lo = lp2_.tick(lp_.tick(x[c][i], c), c);
                x[c][i] = (float)(lo + hi * g);
            }
        }
        gr_ = (float)worst;
    }
    float meter_gr() const override { return gr_; }
};

// Délai stéréo (4 s max). Clés : time_ms, feedback (0..0.95), mix, pingpong (0/1), lowcut, highcut.
class DelayFx : public Effect {
    double sr_ = 48000, mix_ = 0.3, fb_ = 0.35; bool ping_ = false;
    Smooth t_; std::vector<float> buf_[2]; int w_ = 0, len_ = 1; Biquad tone_;
public:
    DelayFx() { t_.snap(250); }
    void prepare(double sr, int) override {
        sr_ = sr; len_ = (int)(sr * 4.0) + 4;
        buf_[0].assign(len_, 0.f); buf_[1].assign(len_, 0.f); w_ = 0; t_.prepare(sr, 50);
        tone_.design(Biquad::LowPass, sr, 9000, 0.707, 0);
    }
    void reset() override { std::fill(buf_[0].begin(), buf_[0].end(), 0.f); std::fill(buf_[1].begin(), buf_[1].end(), 0.f); tone_.reset(); }
    void set(const char* k, double v) override {
        if (key_is(k, "time_ms")) t_.target = std::clamp(v, 1.0, 3990.0);
        else if (key_is(k, "feedback")) fb_ = std::clamp(v, 0.0, 0.95);
        else if (key_is(k, "mix")) mix_ = std::clamp(v, 0.0, 1.0);
        else if (key_is(k, "pingpong")) ping_ = v != 0;
        else if (key_is(k, "highcut")) tone_.design(Biquad::LowPass, sr_, v, 0.707, 0);
    }
    // Traîne : temps pour que les répétitions tombent sous -60 dB (plafonné à 30 s).
    double tail_seconds() const override {
        double reps = fb_ > 0.001 ? std::log(0.001) / std::log(fb_) : 1.0;
        return std::min(30.0, (reps + 1) * t_.target / 1000.0);
    }
    void process(float* const* x, int n, float* const*) override {
        for (int i = 0; i < n; ++i) {
            double d = t_.next() * sr_ / 1000.0;
            double rp = w_ - d; while (rp < 0) rp += len_;
            int i0 = (int)rp; double fr = rp - i0; int i1 = (i0 + 1) % len_;
            float y[2];
            for (int c = 0; c < 2; ++c) y[c] = (float)(buf_[c][i0] * (1 - fr) + buf_[c][i1] * fr);
            float in0 = x[0][i], in1 = x[1][i];
            float f0 = tone_.tick(y[0], 0), f1 = tone_.tick(y[1], 1);
            if (ping_) { buf_[0][w_] = (float)(0.5 * (in0 + in1) + f1 * fb_); buf_[1][w_] = (float)(f0 * fb_); }
            else { buf_[0][w_] = (float)(in0 + f0 * fb_); buf_[1][w_] = (float)(in1 + f1 * fb_); }
            w_ = (w_ + 1) % len_;
            x[0][i] = (float)(in0 * (1 - mix_) + y[0] * mix_);
            x[1][i] = (float)(in1 * (1 - mix_) + y[1] * mix_);
        }
    }
};

// Réverbération algorithmique (réseau de peignes filtrés + passe-tout, type Schroeder/Moorer).
// Clés : room (0..1), damp (0..1), width (0..1), mix (0..1), predelay_ms.
class ReverbFx : public Effect {
    struct Comb { std::vector<float> b; int p = 0; float store = 0; };
    struct AP { std::vector<float> b; int p = 0; };
    static constexpr int kC = 8, kA = 4;
    Comb comb_[2][kC]; AP ap_[2][kA];
    std::vector<float> pre_[2]; int pre_w_ = 0, pre_n_ = 0;
    double sr_ = 48000, room_ = 0.7, damp_ = 0.4, width_ = 1.0, mix_ = 0.25, pre_ms_ = 10;
public:
    void prepare(double sr, int) override {
        sr_ = sr;
        static const int ct[kC] = {1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617};
        static const int at[kA] = {556, 441, 341, 225};
        double k = sr / 44100.0;
        for (int c = 0; c < 2; ++c) {
            int spread = c ? 23 : 0;
            for (int i = 0; i < kC; ++i) { comb_[c][i].b.assign((size_t)((ct[i] + spread) * k) + 1, 0.f); comb_[c][i].p = 0; comb_[c][i].store = 0; }
            for (int i = 0; i < kA; ++i) { ap_[c][i].b.assign((size_t)((at[i] + spread) * k) + 1, 0.f); ap_[c][i].p = 0; }
            pre_[c].assign((size_t)(sr * 0.2) + 1, 0.f);
        }
        pre_w_ = 0; pre_n_ = (int)(sr * pre_ms_ / 1000.0);
    }
    void reset() override { prepare(sr_, 0); }
    double tail_seconds() const override { return 1.0 + room_ * 7.0; }
    void set(const char* k, double v) override {
        if (key_is(k, "room")) room_ = std::clamp(v, 0.0, 1.0); else if (key_is(k, "damp")) damp_ = std::clamp(v, 0.0, 1.0);
        else if (key_is(k, "width")) width_ = std::clamp(v, 0.0, 1.0); else if (key_is(k, "mix")) mix_ = std::clamp(v, 0.0, 1.0);
        else if (key_is(k, "predelay_ms")) { pre_ms_ = std::clamp(v, 0.0, 190.0); pre_n_ = (int)(sr_ * pre_ms_ / 1000.0); }
    }
    void process(float* const* x, int n, float* const*) override {
        float fb = (float)(0.7 + 0.28 * room_), d1 = (float)(damp_ * 0.4), d2 = 1 - d1;
        float wet1 = (float)(width_ / 2 + 0.5), wet2 = (float)((1 - width_) / 2);
        int plen = (int)pre_[0].size();
        for (int i = 0; i < n; ++i) {
            float in = (x[0][i] + x[1][i]) * 0.015f;
            pre_[0][pre_w_] = in;
            int rp = pre_w_ - pre_n_; if (rp < 0) rp += plen;
            float src = pre_[0][rp];
            pre_w_ = (pre_w_ + 1) % plen;
            float out[2] = {0, 0};
            for (int c = 0; c < 2; ++c) {
                for (auto& cb : comb_[c]) {
                    float y = cb.b[cb.p];
                    cb.store = y * d2 + cb.store * d1;
                    cb.b[cb.p] = src + cb.store * fb;
                    if (++cb.p >= (int)cb.b.size()) cb.p = 0;
                    out[c] += y;
                }
                for (auto& a : ap_[c]) {
                    float bo = a.b[a.p];
                    float y = -out[c] + bo;
                    a.b[a.p] = out[c] + bo * 0.5f;
                    if (++a.p >= (int)a.b.size()) a.p = 0;
                    out[c] = y;
                }
            }
            float l = out[0] * wet1 + out[1] * wet2, r = out[1] * wet1 + out[0] * wet2;
            x[0][i] = (float)(x[0][i] * (1 - mix_) + l * mix_ * 3.0);
            x[1][i] = (float)(x[1][i] * (1 - mix_) + r * mix_ * 3.0);
        }
    }
};

// Chorus stéréo (délai modulé). Clés : rate_hz, depth_ms, delay_ms, mix, feedback.
class ChorusFx : public Effect {
    double sr_ = 48000, rate_ = 0.8, depth_ = 3, base_ = 12, mix_ = 0.5, fb_ = 0, ph_ = 0;
    std::vector<float> buf_[2]; int w_ = 0, len_ = 1;
public:
    void prepare(double sr, int) override { sr_ = sr; len_ = (int)(sr * 0.1) + 4; buf_[0].assign(len_, 0); buf_[1].assign(len_, 0); w_ = 0; }
    void reset() override { std::fill(buf_[0].begin(), buf_[0].end(), 0.f); std::fill(buf_[1].begin(), buf_[1].end(), 0.f); }
    void set(const char* k, double v) override {
        if (key_is(k, "rate_hz")) rate_ = std::clamp(v, 0.01, 10.0); else if (key_is(k, "depth_ms")) depth_ = std::clamp(v, 0.0, 20.0);
        else if (key_is(k, "delay_ms")) base_ = std::clamp(v, 1.0, 50.0); else if (key_is(k, "mix")) mix_ = std::clamp(v, 0.0, 1.0);
        else if (key_is(k, "feedback")) fb_ = std::clamp(v, 0.0, 0.9);
    }
    void process(float* const* x, int n, float* const*) override {
        double inc = 2 * kPi * rate_ / sr_;
        for (int i = 0; i < n; ++i) {
            for (int c = 0; c < 2; ++c) {
                double lfo = std::sin(ph_ + (c ? kPi / 2 : 0));
                double d = (base_ + depth_ * 0.5 * (1 + lfo)) * sr_ / 1000.0;
                double rp = w_ - d; while (rp < 0) rp += len_;
                int i0 = (int)rp; double fr = rp - i0; int i1 = (i0 + 1) % len_;
                float y = (float)(buf_[c][i0] * (1 - fr) + buf_[c][i1] * fr);
                buf_[c][w_] = (float)(x[c][i] + y * fb_);
                x[c][i] = (float)(x[c][i] * (1 - mix_ * 0.5) + y * mix_);
            }
            w_ = (w_ + 1) % len_;
            ph_ += inc; if (ph_ > 2 * kPi) ph_ -= 2 * kPi;
        }
    }
};

// Suréchantillonneur ×4 (interpolation + 2 passe-bas d'ordre 2 en cascade, à 0,45·Fs d'origine)
// pour les non-linéarités : limite le repliement (anti-aliasing).
struct Oversampler4 {
    Biquad up1, up2, dn1, dn2; float last[2] = {0, 0};
    void prepare(double sr) {
        double osr = sr * 4, f = sr * 0.45;
        up1.design(Biquad::LowPass, osr, f, 0.54, 0); up2.design(Biquad::LowPass, osr, f, 1.31, 0);
        dn1 = up1; dn2 = up2; reset();
    }
    void reset() { up1.reset(); up2.reset(); dn1.reset(); dn2.reset(); last[0] = last[1] = 0; }
    template <class F> inline float run(float x, int c, F&& f) {
        float acc = 0;
        for (int k = 0; k < 4; ++k) {
            float u = up2.tick(up1.tick(k == 0 ? x * 4.0f : 0.0f, c), c);
            float y = f(u);
            acc = dn2.tick(dn1.tick(y, c), c);
        }
        return acc;
    }
};

// Saturation / distorsion. Clés : drive_db, type (0 tanh doux, 1 dur, 2 asymétrique « lampe », 3 fuzz), tone (Hz), mix, output_db.
class DistortionFx : public Effect {
    double sr_ = 48000, drive_ = 12, out_ = -6, mix_ = 1; int type_ = 0;
    Oversampler4 os_; Biquad tone_;
public:
    void prepare(double sr, int) override { sr_ = sr; os_.prepare(sr); tone_.design(Biquad::LowPass, sr, 7000, 0.707, 0); }
    void reset() override { os_.reset(); tone_.reset(); }
    void set(const char* k, double v) override {
        if (key_is(k, "drive_db")) drive_ = std::clamp(v, 0.0, 60.0); else if (key_is(k, "type")) type_ = (int)v;
        else if (key_is(k, "tone")) tone_.design(Biquad::LowPass, sr_, v, 0.707, 0);
        else if (key_is(k, "mix")) mix_ = std::clamp(v, 0.0, 1.0); else if (key_is(k, "output_db")) out_ = v;
    }
    static inline float shape(float u, int t) {
        switch (t) {
            case 1: return std::clamp(u, -1.0f, 1.0f);
            case 2: return u >= 0 ? std::tanh(u) : std::tanh(u * 0.6f) / 0.6f * 0.8f;  // asymétrique : harmoniques paires
            case 3: { float s = u >= 0 ? 1.f : -1.f; return s * (1 - std::exp(-std::abs(u) * 3)); }
            default: return std::tanh(u);
        }
    }
    void process(float* const* x, int n, float* const*) override {
        float g = (float)db_to_lin(drive_), o = (float)db_to_lin(out_);
        int t = type_;
        for (int c = 0; c < 2; ++c)
            for (int i = 0; i < n; ++i) {
                float dry = x[c][i];
                float wet = os_.run(dry * g, c, [t](float u) { return shape(u, t); });
                wet = tone_.tick(wet, c) * o;
                x[c][i] = (float)(dry * (1 - mix_) + wet * mix_);
            }
    }
};

std::unique_ptr<Effect> make_amp_effect(const std::string& type);  // amp.h (guitare)

inline std::unique_ptr<Effect> make_effect(const std::string& type) {
    if (type == "gain") return std::make_unique<GainFx>();
    if (type == "eq") return std::make_unique<EqFx>();
    if (type == "filter") return std::make_unique<FilterFx>();
    if (type == "compressor") return std::make_unique<CompressorFx>();
    if (type == "limiter") return std::make_unique<LimiterFx>();
    if (type == "gate") return std::make_unique<GateFx>();
    if (type == "deesser") return std::make_unique<DeesserFx>();
    if (type == "delay") return std::make_unique<DelayFx>();
    if (type == "reverb") return std::make_unique<ReverbFx>();
    if (type == "chorus") return std::make_unique<ChorusFx>();
    if (type == "distortion") return std::make_unique<DistortionFx>();
    return make_amp_effect(type);
}

}  // namespace fmz
