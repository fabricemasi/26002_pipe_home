// fmz_audio_engine : instruments internes (synthétiseur, boîte à rythmes, sampler).
// configure() est appelé HORS temps réel (construction du graphe) ; note_on/off, render, set
// sont temps réel : aucune allocation (voix préallouées, vol de voix le plus ancien).
#pragma once
#include "dsp.h"
#include "json.h"
#include "wav.h"

namespace fmz {

inline double midi_hz(double note) { return 440.0 * std::pow(2.0, (note - 69.0) / 12.0); }

struct ADSR {
    enum St { Off, A, D, S, R } st = Off;
    double v = 0, a = 0.005, d = 0.1, s = 0.7, r = 0.2, sr = 48000;
    void on() { st = A; }
    void off() { if (st != Off) st = R; }
    void kill() { st = Off; v = 0; }
    inline double tick() {
        switch (st) {
            case A: v += 1.0 / std::max(1.0, a * sr); if (v >= 1) { v = 1; st = D; } break;
            case D: v -= (1 - s) / std::max(1.0, d * sr); if (v <= s) { v = s; st = S; } break;
            case S: break;
            case R: v -= std::max(v, 0.001) / std::max(1.0, r * sr) * 4.0; if (v <= 1e-4) { v = 0; st = Off; } break;
            default: v = 0;
        }
        return v;
    }
    bool active() const { return st != Off; }
};

class Instrument {
public:
    virtual ~Instrument() = default;
    virtual std::string configure(const Json&) { return std::string(); }
    virtual void prepare(double sr) = 0;
    virtual void note_on(int pitch, int vel) = 0;
    virtual void note_off(int pitch) = 0;
    virtual void all_notes_off(bool hard) = 0;  // hard : coupe net (panique) ; sinon relâchement
    virtual void render(float* l, float* r, int n) = 0;  // AJOUTE au tampon
    virtual void set(const char*, double) {}
    virtual int active_voices() const = 0;
    virtual double tail_seconds() const { return 2.0; }
};

// Synthétiseur soustractif polyphonique (16 voix) : 2 oscillateurs PolyBLEP, filtre d'état
// TPT passe-bas résonant, enveloppes ampli et filtre, sensibilité à la vélocité.
// Clés : osc1_wave, osc2_wave (0 scie, 1 carré, 2 sinus, 3 triangle), osc2_semi, osc2_detune (cents),
// osc_mix, cutoff (Hz), resonance (0..1), filter_env (octaves), attack, decay, sustain, release,
// f_attack, f_decay, f_sustain, f_release, vel_sens, gain_db.
class SynthInstrument : public Instrument {
    static constexpr int kVoices = 16;
    struct Voice {
        int note = -1; double vel = 0, ph1 = 0, ph2 = 0, inc1 = 0, inc2 = 0; uint64_t age = 0;
        ADSR amp, flt; double ic1 = 0, ic2 = 0, tri1 = 0, tri2 = 0;
    };
    Voice v_[kVoices]; uint64_t clock_ = 0; double sr_ = 48000;
    int w1_ = 0, w2_ = 1; double semi_ = 0, det_ = 7, mix_ = 0.5, cut_ = 1800, res_ = 0.2, fenv_ = 2.5, vs_ = 0.7, gain_ = -12;
    double A_[4] = {0.005, 0.25, 0.7, 0.3}, F_[4] = {0.002, 0.3, 0.3, 0.3};
    static inline double blep(double t, double dt) {
        if (t < dt) { t /= dt; return t + t - t * t - 1.0; }
        if (t > 1.0 - dt) { t = (t - 1.0) / dt; return t * t + t + t + 1.0; }
        return 0.0;
    }
    static inline double osc(int w, double ph, double dt, double& tri) {
        switch (w) {
            case 0: return 2 * ph - 1 - blep(ph, dt);
            case 1: { double s = ph < 0.5 ? 1 : -1; s += blep(ph, dt); s -= blep(std::fmod(ph + 0.5, 1.0), dt); return s; }
            case 3: { double sq = (ph < 0.5 ? 1 : -1) + blep(ph, dt) - blep(std::fmod(ph + 0.5, 1.0), dt);
                      tri = dt * 4 * sq + (1 - dt * 0.5) * tri; return tri; }
            default: return std::sin(2 * kPi * ph);
        }
    }
    void env_params(Voice& x) {
        x.amp.a = A_[0]; x.amp.d = A_[1]; x.amp.s = A_[2]; x.amp.r = A_[3]; x.amp.sr = sr_;
        x.flt.a = F_[0]; x.flt.d = F_[1]; x.flt.s = F_[2]; x.flt.r = F_[3]; x.flt.sr = sr_;
    }
public:
    std::string configure(const Json& j) override {
        if (j["params"].type == Json::Object) for (auto& kv : j["params"].o) set(kv.first.c_str(), kv.second.num_or(0));
        return std::string();
    }
    void prepare(double sr) override { sr_ = sr; for (auto& x : v_) { x = Voice(); env_params(x); } }
    void set(const char* k, double v) override {
        if (key_is(k, "osc1_wave")) w1_ = (int)v; else if (key_is(k, "osc2_wave")) w2_ = (int)v;
        else if (key_is(k, "osc2_semi")) semi_ = v; else if (key_is(k, "osc2_detune")) det_ = v;
        else if (key_is(k, "osc_mix")) mix_ = std::clamp(v, 0.0, 1.0); else if (key_is(k, "cutoff")) cut_ = std::clamp(v, 20.0, 20000.0);
        else if (key_is(k, "resonance")) res_ = std::clamp(v, 0.0, 0.98); else if (key_is(k, "filter_env")) fenv_ = v;
        else if (key_is(k, "vel_sens")) vs_ = std::clamp(v, 0.0, 1.0); else if (key_is(k, "gain_db")) gain_ = v;
        else if (key_is(k, "attack")) A_[0] = v; else if (key_is(k, "decay")) A_[1] = v; else if (key_is(k, "sustain")) A_[2] = v; else if (key_is(k, "release")) A_[3] = v;
        else if (key_is(k, "f_attack")) F_[0] = v; else if (key_is(k, "f_decay")) F_[1] = v; else if (key_is(k, "f_sustain")) F_[2] = v; else if (key_is(k, "f_release")) F_[3] = v;
    }
    void note_on(int pitch, int vel) override {
        Voice* best = nullptr;
        for (auto& x : v_) if (!x.amp.active()) { best = &x; break; }
        if (!best) { best = &v_[0]; for (auto& x : v_) if (x.age < best->age) best = &x; }  // vol de la plus ancienne
        Voice& x = *best;
        x.note = pitch; x.vel = vel / 127.0; x.age = ++clock_;
        x.inc1 = midi_hz(pitch) / sr_; x.inc2 = midi_hz(pitch + semi_ + det_ / 100.0) / sr_;
        x.ph1 = 0; x.ph2 = 0.25; x.ic1 = x.ic2 = 0; x.tri1 = x.tri2 = 0;
        env_params(x); x.amp.v = 0; x.flt.v = 0; x.amp.on(); x.flt.on();
    }
    void note_off(int pitch) override { for (auto& x : v_) if (x.note == pitch && x.amp.st != ADSR::R && x.amp.active()) { x.amp.off(); x.flt.off(); } }
    void all_notes_off(bool hard) override { for (auto& x : v_) { if (hard) { x.amp.kill(); x.flt.kill(); x.note = -1; } else { x.amp.off(); x.flt.off(); } } }
    int active_voices() const override { int n = 0; for (auto& x : v_) n += x.amp.active(); return n; }
    double tail_seconds() const override { return A_[3] + 0.1; }
    void render(float* l, float* r, int n) override {
        double g = db_to_lin(gain_);
        for (auto& x : v_) {
            if (!x.amp.active()) continue;
            double vg = (1 - vs_) + vs_ * x.vel;
            for (int i = 0; i < n; ++i) {
                double s = osc(w1_, x.ph1, x.inc1, x.tri1) * (1 - mix_) + osc(w2_, x.ph2, x.inc2, x.tri2) * mix_;
                x.ph1 += x.inc1; if (x.ph1 >= 1) x.ph1 -= 1;
                x.ph2 += x.inc2; if (x.ph2 >= 1) x.ph2 -= 1;
                double fe = x.flt.tick();
                double fc = std::min(cut_ * std::pow(2.0, fenv_ * fe), sr_ * 0.45);
                // SVF TPT (Zavalishin), sortie passe-bas
                double gg = std::tan(kPi * fc / sr_), k = 2 - 2 * res_;
                double a1 = 1 / (1 + gg * (gg + k)), a2 = gg * a1, a3 = gg * a2;
                double v3 = s - x.ic2, v1 = a1 * x.ic1 + a2 * v3, v2 = x.ic2 + a2 * x.ic1 + a3 * v3;
                x.ic1 = 2 * v1 - x.ic1; x.ic2 = 2 * v2 - x.ic2;
                double out = v2 * x.amp.tick() * vg * g;
                l[i] += (float)out; r[i] += (float)out;
                if (!x.amp.active()) { x.note = -1; break; }
            }
        }
    }
};

// Lecture d'un échantillon avec interpolation d'Hermite (4 points).
inline float hermite(const std::vector<float>& d, double pos) {
    int64_t i = (int64_t)pos; double f = pos - i; int64_t n = (int64_t)d.size();
    auto at = [&](int64_t k) { return k < 0 || k >= n ? 0.0f : d[(size_t)k]; };
    float xm1 = at(i - 1), x0 = at(i), x1 = at(i + 1), x2 = at(i + 2);
    float c1 = 0.5f * (x1 - xm1), c2 = xm1 - 2.5f * x0 + 2 * x1 - 0.5f * x2, c3 = 0.5f * (x2 - xm1) + 1.5f * (x0 - x1);
    return ((c3 * (float)f + c2) * (float)f + c1) * (float)f + x0;
}

// Sampler multi-zones. configure : {"zones":[{"path","root","lo","hi","vlo","vhi","loop_start","loop_end","gain_db"}],
// "params":{attack,decay,sustain,release,gain_db}}. Un sample absent est SIGNALÉ (erreur), jamais remplacé par un autre son.
class SamplerInstrument : public Instrument {
public:
    struct Zone { std::vector<float> l, r; int sr = 48000, root = 60, lo = 0, hi = 127, vlo = 1, vhi = 127; int64_t ls = -1, le = -1; double gain = 1; bool one_shot = false; };
    std::vector<Zone> zones;
    std::string configure(const Json& j) override {
        std::string err;
        for (auto& z : j["zones"].a) {
            Zone zn;
            try {
                AudioData a = wav_read(z.gets("path"));
                zn.l = a.ch[0]; zn.r = a.channels() > 1 ? a.ch[1] : a.ch[0]; zn.sr = a.sample_rate;
            } catch (const std::exception& e) { err += std::string("sample absent ou illisible : ") + z.gets("path") + " (" + e.what() + "); "; continue; }
            zn.root = (int)z.geti("root", 60); zn.lo = (int)z.geti("lo", 0); zn.hi = (int)z.geti("hi", 127);
            zn.vlo = (int)z.geti("vlo", 1); zn.vhi = (int)z.geti("vhi", 127);
            zn.ls = z.geti("loop_start", -1); zn.le = z.geti("loop_end", -1);
            zn.gain = db_to_lin(z.get("gain_db", 0)); zn.one_shot = z.getb("one_shot", false);
            zones.push_back(std::move(zn));
        }
        if (j["params"].type == Json::Object) for (auto& kv : j["params"].o) set(kv.first.c_str(), kv.second.num_or(0));
        return err;
    }
    void prepare(double sr) override { sr_ = sr; for (auto& v : v_) v = Voice(); }
    void set(const char* k, double v) override {
        if (key_is(k, "attack")) A_[0] = v; else if (key_is(k, "decay")) A_[1] = v; else if (key_is(k, "sustain")) A_[2] = v;
        else if (key_is(k, "release")) A_[3] = v; else if (key_is(k, "gain_db")) gain_ = v;
    }
    void note_on(int pitch, int vel) override {
        for (size_t zi = 0; zi < zones.size(); ++zi) {
            const Zone& z = zones[zi];
            if (pitch < z.lo || pitch > z.hi || vel < z.vlo || vel > z.vhi) continue;
            Voice* best = nullptr;
            for (auto& x : v_) if (!x.env.active()) { best = &x; break; }
            if (!best) { best = &v_[0]; for (auto& x : v_) if (x.age < best->age) best = &x; }
            Voice& x = *best;
            x.zone = (int)zi; x.note = pitch; x.vel = vel / 127.0; x.age = ++clock_; x.pos = 0;
            x.inc = std::pow(2.0, (pitch - z.root) / 12.0) * z.sr / sr_;
            x.env.a = A_[0]; x.env.d = A_[1]; x.env.s = A_[2]; x.env.r = A_[3]; x.env.sr = sr_; x.env.v = 0; x.env.on();
        }
    }
    void note_off(int pitch) override { for (auto& x : v_) if (x.note == pitch && x.zone >= 0 && !zones[x.zone].one_shot) x.env.off(); }
    void all_notes_off(bool hard) override { for (auto& x : v_) { if (hard) { x.env.kill(); x.zone = -1; } else x.env.off(); } }
    int active_voices() const override { int n = 0; for (auto& x : v_) n += x.env.active(); return n; }
    void render(float* l, float* r, int n) override {
        double g = db_to_lin(gain_);
        for (auto& x : v_) {
            if (!x.env.active() || x.zone < 0) continue;
            const Zone& z = zones[x.zone];
            int64_t len = (int64_t)z.l.size();
            for (int i = 0; i < n; ++i) {
                if (z.le > z.ls && z.ls >= 0 && x.pos >= z.le && x.env.st != ADSR::R) x.pos -= (double)(z.le - z.ls);
                if (x.pos >= len - 1) { x.env.kill(); break; }
                double e = x.env.tick() * x.vel * z.gain * g;
                l[i] += (float)(hermite(z.l, x.pos) * e);
                r[i] += (float)(hermite(z.r, x.pos) * e);
                x.pos += x.inc;
                if (!x.env.active()) break;
            }
        }
    }
private:
    static constexpr int kVoices = 32;
    struct Voice { int zone = -1, note = -1; double vel = 0, pos = 0, inc = 1; uint64_t age = 0; ADSR env; };
    Voice v_[kVoices]; uint64_t clock_ = 0; double sr_ = 48000, gain_ = 0;
    double A_[4] = {0.001, 0.1, 1.0, 0.15};
};

// Boîte à rythmes synthétique (sons générés, pas de samples tiers) avec remplacement facultatif
// d'un pad par un sample (configure : {"pads": {"36": "kick.wav", ...}}).
// Notes GM : 36 grosse caisse, 37 rimshot, 38/40 caisse claire, 39 clap, 42/44 charleston fermé,
// 46 charleston ouvert (étouffé par 42/44), 41/43/45/47/48/50 toms, 49/57 crash, 51 ride.
// Clés : <pad>_tune (demi-tons), <pad>_decay (facteur), <pad>_level_db, gain_db ; pad = kick, snare, hat, clap, tom, cymbal, rim.
class DrumInstrument : public Instrument {
    enum Kind { Kick, Snare, HatC, HatO, Clap, Tom, Cymbal, Rim, None };
    struct Voice { Kind k = None; int note = -1; double t = 0, vel = 0, f0 = 0, ph = 0; Biquad bp; bool on = false; int sample = -1; double spos = 0, sinc = 1; };
    static constexpr int kVoices = 24;
    Voice v_[kVoices]; int next_ = 0; double sr_ = 48000, gain_ = -6;
    uint32_t rng_ = 22222;
    double tune_[8] = {0}, decay_[8] = {1, 1, 1, 1, 1, 1, 1, 1}, level_[8] = {0};
    struct Pad { int note; std::vector<float> l, r; int sr; };
    std::vector<Pad> pads_;
    inline double noise() { rng_ = rng_ * 1664525u + 1013904223u; return (rng_ >> 8) / 8388608.0 - 1.0; }
    static Kind kind_of(int n) {
        switch (n) {
            case 35: case 36: return Kick; case 37: return Rim; case 38: case 40: return Snare; case 39: return Clap;
            case 42: case 44: return HatC; case 46: return HatO; case 41: case 43: case 45: case 47: case 48: case 50: return Tom;
            case 49: case 51: case 52: case 55: case 57: case 59: return Cymbal; default: return None;
        }
    }
    static int pad_index(const char* k, const char** rest) {
        static const char* names[8] = {"kick", "snare", "hat", "hat", "clap", "tom", "cymbal", "rim"};
        for (int i = 0; i < 8; ++i) { size_t L = strlen(names[i]); if (strncmp(k, names[i], L) == 0 && k[L] == '_') { *rest = k + L + 1; return i; } }
        return -1;
    }
public:
    std::string configure(const Json& j) override {
        std::string err;
        if (j["pads"].type == Json::Object)
            for (auto& kv : j["pads"].o) {
                try { AudioData a = wav_read(kv.second.str_or("")); pads_.push_back({atoi(kv.first.c_str()), a.ch[0], a.channels() > 1 ? a.ch[1] : a.ch[0], a.sample_rate}); }
                catch (const std::exception& e) { err += "pad " + kv.first + " : sample illisible (" + e.what() + "); "; }
            }
        if (j["params"].type == Json::Object) for (auto& kv : j["params"].o) set(kv.first.c_str(), kv.second.num_or(0));
        return err;
    }
    void prepare(double sr) override { sr_ = sr; for (auto& v : v_) v = Voice(); }
    void set(const char* k, double v) override {
        if (key_is(k, "gain_db")) { gain_ = v; return; }
        const char* rest = nullptr; int p = pad_index(k, &rest);
        if (p < 0) return;
        if (key_is(rest, "tune")) tune_[p] = v; else if (key_is(rest, "decay")) decay_[p] = std::clamp(v, 0.1, 4.0); else if (key_is(rest, "level_db")) level_[p] = v;
        if (p == HatC) { tune_[HatO] = tune_[HatC]; decay_[HatO] = decay_[HatC]; level_[HatO] = level_[HatC]; }
    }
    void note_on(int pitch, int vel) override {
        Kind k = kind_of(pitch);
        int sample = -1;
        for (size_t i = 0; i < pads_.size(); ++i) if (pads_[i].note == pitch) sample = (int)i;
        if (k == None && sample < 0) return;
        if (k == HatC) for (auto& x : v_) if (x.k == HatO) x.on = false;  // étouffement du charleston ouvert
        Voice& x = v_[next_]; next_ = (next_ + 1) % kVoices;
        x = Voice(); x.k = k; x.note = pitch; x.vel = vel / 127.0; x.on = true; x.sample = sample;
        if (sample >= 0) { x.sinc = (double)pads_[sample].sr / sr_; return; }
        double tn = std::pow(2.0, tune_[k] / 12.0);
        switch (k) {
            case Kick: x.f0 = 50 * tn; break;
            case Snare: x.f0 = 185 * tn; x.bp.design(Biquad::HighPass, sr_, 1200 * tn, 0.7, 0); break;
            case HatC: case HatO: x.bp.design(Biquad::HighPass, sr_, 7000 * tn, 0.7, 0); break;
            case Clap: x.bp.design(Biquad::BandPass, sr_, 1100 * tn, 1.5, 0); break;
            case Tom: x.f0 = (80 + (pitch - 41) * 18) * tn; break;
            case Cymbal: x.bp.design(Biquad::HighPass, sr_, 5000 * tn, 0.7, 0); break;
            case Rim: x.f0 = 1700 * tn; x.bp.design(Biquad::BandPass, sr_, 2500 * tn, 4, 0); break;
            default: break;
        }
    }
    void note_off(int) override {}  // sons percussifs : la durée ne dépend pas du relâchement
    void all_notes_off(bool) override { for (auto& x : v_) x.on = false; }
    int active_voices() const override { int n = 0; for (auto& x : v_) n += x.on; return n; }
    void render(float* l, float* r, int n) override {
        double g = db_to_lin(gain_);
        for (auto& x : v_) {
            if (!x.on) continue;
            double lv = db_to_lin(level_[x.k == None ? 0 : x.k]) * x.vel * g;
            if (x.sample >= 0) {
                const Pad& p = pads_[x.sample];
                for (int i = 0; i < n; ++i) {
                    if (x.spos >= p.l.size() - 1) { x.on = false; break; }
                    l[i] += (float)(hermite(p.l, x.spos) * lv); r[i] += (float)(hermite(p.r, x.spos) * lv);
                    x.spos += x.sinc;
                }
                continue;
            }
            double dk = decay_[x.k];
            for (int i = 0; i < n; ++i) {
                double t = x.t, s = 0;
                switch (x.k) {
                    case Kick: { double f = x.f0 * (1 + 3 * std::exp(-t * 30)); x.ph += f / sr_; s = std::sin(2 * kPi * x.ph) * std::exp(-t * 7 / dk) + (t < 0.003 ? noise() * 0.3 : 0); if (t > 1.2 * dk) x.on = false; break; }
                    case Snare: { x.ph += x.f0 / sr_; s = std::sin(2 * kPi * x.ph) * std::exp(-t * 25 / dk) * 0.5 + x.bp.tick((float)noise(), 0) * std::exp(-t * 14 / dk) * 0.8; if (t > 0.6 * dk) x.on = false; break; }
                    case HatC: s = x.bp.tick((float)noise(), 0) * std::exp(-t * 60 / dk) * 0.5; if (t > 0.2 * dk) x.on = false; break;
                    case HatO: s = x.bp.tick((float)noise(), 0) * std::exp(-t * 6 / dk) * 0.45; if (t > 1.2 * dk) x.on = false; break;
                    case Clap: { double env = 0; for (int b = 0; b < 3; ++b) { double tb = t - b * 0.011; if (tb >= 0) env = std::max(env, std::exp(-tb * 120)); } env = std::max(env, t > 0.022 ? std::exp(-(t - 0.022) * 12 / dk) * 0.6 : 0.0); s = x.bp.tick((float)noise(), 0) * env * 1.2; if (t > 0.5 * dk) x.on = false; break; }
                    case Tom: { double f = x.f0 * (1 + 0.6 * std::exp(-t * 20)); x.ph += f / sr_; s = std::sin(2 * kPi * x.ph) * std::exp(-t * 6 / dk); if (t > 1.0 * dk) x.on = false; break; }
                    case Cymbal: s = x.bp.tick((float)noise(), 0) * std::exp(-t * 2.5 / dk) * 0.35; if (t > 2.5 * dk) x.on = false; break;
                    case Rim: { x.ph += x.f0 / sr_; s = (std::sin(2 * kPi * x.ph) * 0.5 + x.bp.tick((float)noise(), 0)) * std::exp(-t * 80 / dk); if (t > 0.1 * dk) x.on = false; break; }
                    default: x.on = false;
                }
                x.t += 1.0 / sr_;
                l[i] += (float)(s * lv); r[i] += (float)(s * lv);
                if (!x.on) break;
            }
        }
    }
};

inline std::unique_ptr<Instrument> make_instrument(const std::string& type) {
    if (type == "synth") return std::make_unique<SynthInstrument>();
    if (type == "sampler") return std::make_unique<SamplerInstrument>();
    if (type == "drums") return std::make_unique<DrumInstrument>();
    return nullptr;
}

}  // namespace fmz
