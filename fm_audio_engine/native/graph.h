// fmz_audio_engine : graphe de mixage (pistes, bus, sends, sidechains, PDC, automation,
// clips audio, notes MIDI). Construit HORS temps réel depuis la description JSON,
// puis traité bloc par bloc par le callback OU par le rendu offline (même code).
#pragma once
#include <atomic>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include "amp.h"
#include "json.h"
#include "synth.h"
#include "wav.h"
#include "vst3_host.h"

namespace fmz {

// Carte tempo : segments de tempo constant ; la position de chaque segment est calculée
// depuis le début du segment (aucune dérive cumulative).
struct TempoMap {
    int ppq = 960;
    struct Seg { int64_t tick; double bpm; int64_t sample; };
    struct Sig { int64_t tick; int num, den; };
    std::vector<Seg> segs;
    std::vector<Sig> sigs;
    double sr = 48000;
    void build(const Json& j, double sample_rate) {
        sr = sample_rate;
        ppq = (int)j.geti("ppq", 960);
        segs.clear(); sigs.clear();
        for (auto& p : j["points"].a) segs.push_back({p.geti("tick", 0), std::max(1.0, p.get("bpm", 120)), 0});
        if (segs.empty() || segs[0].tick != 0) segs.insert(segs.begin(), {0, segs.empty() ? 120.0 : segs[0].bpm, 0});
        std::sort(segs.begin(), segs.end(), [](const Seg& a, const Seg& b) { return a.tick < b.tick; });
        for (size_t i = 1; i < segs.size(); ++i)
            segs[i].sample = segs[i - 1].sample + span(segs[i].tick - segs[i - 1].tick, segs[i - 1].bpm);
        for (auto& s : j["signatures"].a) sigs.push_back({s.geti("tick", 0), (int)s.geti("num", 4), (int)s.geti("den", 4)});
        if (sigs.empty() || sigs[0].tick != 0) sigs.insert(sigs.begin(), {0, 4, 4});
    }
    int64_t span(int64_t ticks, double bpm) const { return (int64_t)std::llround((double)ticks * 60.0 * sr / (bpm * ppq)); }
    int64_t tick_to_sample(int64_t tick) const {
        size_t k = 0;
        while (k + 1 < segs.size() && segs[k + 1].tick <= tick) ++k;
        return segs[k].sample + span(tick - segs[k].tick, segs[k].bpm);
    }
    double sample_to_tick(int64_t s) const {
        size_t k = 0;
        while (k + 1 < segs.size() && segs[k + 1].sample <= s) ++k;
        return segs[k].tick + (double)(s - segs[k].sample) * segs[k].bpm * ppq / (60.0 * sr);
    }
};

// Automation : points (échantillon, valeur), interpolation linéaire.
struct Automation {
    std::vector<std::pair<int64_t, double>> pts;
    bool empty() const { return pts.empty(); }
    double at(int64_t t) const {
        if (pts.empty()) return 0;
        if (t <= pts.front().first) return pts.front().second;
        if (t >= pts.back().first) return pts.back().second;
        size_t lo = 0, hi = pts.size() - 1;
        while (hi - lo > 1) { size_t m = (lo + hi) / 2; (pts[m].first <= t ? lo : hi) = m; }
        double f = (double)(t - pts[lo].first) / (double)(pts[hi].first - pts[lo].first);
        return pts[lo].second + (pts[hi].second - pts[lo].second) * f;
    }
    void load(const Json& j) { for (auto& p : j.a) if (p.a.size() >= 2) pts.push_back({p.a[0].int_or(0), p.a[1].num_or(0)}); std::sort(pts.begin(), pts.end()); }
};

// Ligne de retard fixe (compensation de latence d'une connexion).
struct DelayLine {
    std::vector<float> b[2]; int len = 0, w = 0, d = 0;
    void prepare(int delay, int max_block) { d = delay; len = delay + max_block + 1; b[0].assign(len, 0); b[1].assign(len, 0); w = 0; }
    void reset() { std::fill(b[0].begin(), b[0].end(), 0.f); std::fill(b[1].begin(), b[1].end(), 0.f); }
    // Écrit n échantillons et les lit retardés dans out (même taille).
    void process(const float* const* in, float* const* out, int n) {
        for (int i = 0; i < n; ++i) {
            for (int c = 0; c < 2; ++c) b[c][w] = in[c][i];
            int r = w - d; if (r < 0) r += len;
            for (int c = 0; c < 2; ++c) out[c][i] = b[c][r];
            w = (w + 1) % len;
        }
    }
};

using MediaPtr = std::shared_ptr<const AudioData>;

struct Clip {
    MediaPtr media;
    std::string path;
    int64_t start = 0, offset = 0, length = 0;   // en échantillons du projet
    double gain = 1.0, rate = 1.0;               // rate : vitesse de lecture (varispeed)
    int64_t fade_in = 0, fade_out = 0;
    int fade_in_shape = 0, fade_out_shape = 0;   // 0 linéaire, 1 puissance constante, 2 exponentielle
    bool reverse = false;
    static inline double shape(double x, int s) {
        x = std::clamp(x, 0.0, 1.0);
        if (s == 1) return std::sin(x * kPi / 2);
        if (s == 2) return x * x;
        return x;
    }
};

struct NoteEvent { int64_t at; int pitch, vel; bool on; };

struct Node;
struct Conn {
    int target = -1;          // index du nœud cible
    bool pre = false;         // send pré-fader
    double gain = 1.0;
    bool is_send = false;
    DelayLine comp;           // compensation de latence
};

struct FxSlot {
    std::unique_ptr<Effect> fx;
    std::string type;
    int sidechain = -1;       // nœud source de la détection
    std::map<std::string, Automation> autos;
};

struct Node {
    std::string id;
    bool is_bus = false, is_master = false;
    bool mute = false, solo = false, polarity = false, mono = false;
    int input_channel = -1;   // entrée du périphérique écoutée (monitoring)
    bool monitor = false;
    double gain_db = 0, pan = 0;
    Smooth g_l, g_r;
    Automation gain_auto, pan_auto;
    std::vector<Clip> clips;
    std::unique_ptr<Instrument> inst;
    std::vector<NoteEvent> events;
    std::vector<FxSlot> fx;
    std::vector<Conn> outs;
    std::vector<float> buf[2], tmp[2];
    int own_latency = 0, arrival = 0;
    std::atomic<float> peak_l{0}, peak_r{0}, gr{0};
    bool live_out = true;     // calculé par bloc (mute / solo)
    bool midi_out = false;    // notes de la piste envoyées aussi à la sortie MIDI (synthé externe)
    int midi_channel = 0;
};

struct BuildResult { bool ok = true; std::string error; std::vector<std::string> warnings; };

// Pool de médias partagé entre reconstructions (évite de recharger un fichier à chaque édition).
// Accès hors temps réel seulement.
class MediaPool {
public:
    MediaPtr get(const std::string& path, double sr, std::string& err) {
        auto it = cache_.find(path);
        if (it != cache_.end() && it->second.sr == sr) return it->second.data;
        try {
            AudioData a = wav_read(path);
            if (a.sample_rate != (int)sr) a = resample(a, (int)sr);
            auto p = std::make_shared<const AudioData>(std::move(a));
            cache_[path] = {sr, p};
            return p;
        } catch (const std::exception& e) { err = e.what(); return nullptr; }
    }
    void forget(const std::string& path) { cache_.erase(path); }
    void clear() { cache_.clear(); }
    // Rééchantillonnage par sinc fenêtré (Blackman, 32 lobes) : conversion de fréquence de qualité.
    static AudioData resample(const AudioData& in, int sr_out) {
        AudioData out; out.sample_rate = sr_out;
        double ratio = (double)sr_out / in.sample_rate;
        int64_t n_out = (int64_t)std::llround(in.frames() * ratio);
        double cutoff = std::min(1.0, ratio) * 0.97;
        const int half = 32;
        out.ch.assign(in.channels(), std::vector<float>((size_t)n_out));
        for (int c = 0; c < in.channels(); ++c) {
            const auto& x = in.ch[c];
            for (int64_t i = 0; i < n_out; ++i) {
                double center = i / ratio; int64_t c0 = (int64_t)std::floor(center);
                double acc = 0, wsum = 0;
                for (int64_t k = c0 - half + 1; k <= c0 + half; ++k) {
                    double t = center - k;
                    double sinc = std::abs(t) < 1e-9 ? 1.0 : std::sin(kPi * t * cutoff) / (kPi * t * cutoff);
                    double w = 0.42 + 0.5 * std::cos(kPi * t / half) + 0.08 * std::cos(2 * kPi * t / half);
                    double h = sinc * w * cutoff;
                    wsum += h;
                    if (k >= 0 && k < (int64_t)x.size()) acc += x[(size_t)k] * h;
                }
                out.ch[c][(size_t)i] = (float)(wsum != 0 ? acc / wsum * 1.0 : acc);
            }
        }
        return out;
    }
private:
    struct Entry { double sr; MediaPtr data; };
    std::map<std::string, Entry> cache_;
};

class Graph {
public:
    double sr = 48000;
    int max_block = 512;
    TempoMap tempo;
    std::vector<std::unique_ptr<Node>> nodes;
    std::vector<int> order;
    int master = -1;
    int total_latency = 0;
    uint64_t revision = 0;     // révision du document décrit (cohérence Undo / moteur / rendu)
    std::map<std::string, int> index;
    // Sortie MIDI des notes séquencées (posée par le moteur) : pointeur de fonction, aucune allocation.
    void (*midi_sink)(void* ctx, uint8_t status, uint8_t d1, uint8_t d2) = nullptr;
    void* midi_ctx = nullptr;
#ifdef FMZ_VST3
    // Pool des instances VST3 du TEMPS RÉEL (posé par le moteur) ; nullptr = rendu offline (instances propres).
    Vst3Pool* vst3_pool = nullptr;
#endif

    BuildResult build(const Json& spec, MediaPool& pool, int block) {
        BuildResult r;
        sr = spec.get("sample_rate", 48000);
        max_block = block;
        revision = (uint64_t)spec.geti("revision", 0);
        tempo.build(spec["tempo"], sr);
        // nœuds : pistes, bus, master
        auto add = [&](const Json& j, bool bus, bool is_master) -> Node* {
            auto n = std::make_unique<Node>();
            n->id = is_master ? "master" : j.gets("id");
            n->is_bus = bus; n->is_master = is_master;
            if (index.count(n->id)) { r.ok = false; r.error = "identifiant de nœud en double : " + n->id; return nullptr; }
            index[n->id] = (int)nodes.size();
            nodes.push_back(std::move(n));
            return nodes.back().get();
        };
        for (auto& t : spec["tracks"].a) if (!add(t, false, false)) return r;
        for (auto& b : spec["buses"].a) if (!add(b, true, false)) return r;
        add(spec["master"], true, true);
        master = index["master"];
        std::vector<const Json*> desc;
        for (auto& t : spec["tracks"].a) desc.push_back(&t);
        for (auto& b : spec["buses"].a) desc.push_back(&b);
        desc.push_back(&spec["master"]);
        for (size_t i = 0; i < nodes.size(); ++i) {
            if (!configure(*nodes[i], *desc[i], pool, r)) return r;
        }
        if (!topo(r)) return r;
        compute_latency();
        return r;
    }

    void reset_state() {
        for (auto& n : nodes) {
            for (auto& f : n->fx) f.fx->reset();
            for (auto& o : n->outs) o.comp.reset();
            if (n->inst) n->inst->all_notes_off(true);
        }
    }

    void all_notes_off(bool hard) { for (auto& n : nodes) if (n->inst) n->inst->all_notes_off(hard); }

    // Note jouée en direct (clavier MIDI) sur une piste instrument.
    void live_note(int node, int pitch, int vel) {
        if (node < 0 || node >= (int)nodes.size() || !nodes[node]->inst) return;
        if (vel > 0) nodes[node]->inst->note_on(pitch, vel); else nodes[node]->inst->note_off(pitch);
    }

    // Traite [pos, pos+n) ; out : 2 canaux. in : entrées du périphérique (monitoring) ou nullptr.
    // playing=false : seuls le monitoring et les instruments en direct sonnent.
    void process(int64_t pos, int n, float* const* out, const float* const* in, int in_ch, bool playing) {
        bool any_solo = false;
        for (auto& nd : nodes) if (!nd->is_bus && nd->solo) any_solo = true;
        for (auto& nd : nodes) {
            std::fill(nd->buf[0].begin(), nd->buf[0].begin() + n, 0.f);
            std::fill(nd->buf[1].begin(), nd->buf[1].begin() + n, 0.f);
            nd->live_out = !nd->mute && (nd->is_bus || !any_solo || nd->solo);
        }
        for (int idx : order) {
            Node& nd = *nodes[idx];
            float* b[2] = {nd.buf[0].data(), nd.buf[1].data()};
            if (!nd.is_bus) {
                if (playing) render_clips(nd, pos, n, b);
                if (nd.inst || nd.midi_out) render_instrument(nd, pos, n, b, playing);
                if (nd.monitor && in && nd.input_channel >= 0 && nd.input_channel < in_ch) {
                    const float* src = in[nd.input_channel];
                    for (int i = 0; i < n; ++i) { b[0][i] += src[i]; b[1][i] += src[i]; }
                }
            }
            if (nd.polarity) for (int c = 0; c < 2; ++c) for (int i = 0; i < n; ++i) b[c][i] = -b[c][i];
            if (nd.mono) for (int i = 0; i < n; ++i) { float m = 0.5f * (b[0][i] + b[1][i]); b[0][i] = b[1][i] = m; }
            for (auto& slot : nd.fx) {
                if (slot.fx->bypass) continue;
                for (auto& a : slot.autos) slot.fx->set(a.first.c_str(), a.second.at(pos));
                float* sc[2] = {nullptr, nullptr};
                float* const* scp = nullptr;
                if (slot.sidechain >= 0) { sc[0] = nodes[slot.sidechain]->buf[0].data(); sc[1] = nodes[slot.sidechain]->buf[1].data(); scp = sc; }
                slot.fx->process(b, n, scp);
            }
            // sends pré-fader
            for (auto& o : nd.outs) if (o.is_send && o.pre) send(nd, o, n, b);
            apply_fader(nd, pos, n, b);
            for (auto& o : nd.outs) if (!(o.is_send && o.pre)) send(nd, o, n, b);
            meter(nd, n);
        }
        Node& m = *nodes[master];
        for (int c = 0; c < 2; ++c) std::copy(m.buf[c].begin(), m.buf[c].begin() + n, out[c]);
    }

    // Durée de traîne maximale (effets et instruments), bornée.
    double tail_seconds() const {
        double t = 0;
        for (auto& n : nodes) {
            for (auto& f : n->fx) t = std::max(t, f.fx->tail_seconds());
            if (n->inst) t = std::max(t, n->inst->tail_seconds());
        }
        return std::min(t, 30.0);
    }

    int64_t content_end() const {
        int64_t e = 0;
        for (auto& n : nodes) {
            for (auto& c : n->clips) e = std::max(e, c.start + c.length);
            for (auto& ev : n->events) e = std::max(e, ev.at);
        }
        return e;
    }

private:
    bool configure(Node& nd, const Json& j, MediaPool& pool, BuildResult& r) {
        nd.gain_db = j.get("gain_db", 0); nd.pan = std::clamp(j.get("pan", 0.0), -1.0, 1.0);
        nd.mute = j.getb("mute", false); nd.solo = j.getb("solo", false); nd.polarity = j.getb("polarity", false);
        nd.mono = j.geti("channels", 2) == 1;
        nd.input_channel = (int)j.geti("input", -1); nd.monitor = j.getb("monitor", false);
        nd.midi_out = j.getb("midi_out", false); nd.midi_channel = (int)std::clamp<int64_t>(j.geti("midi_channel", 0), 0, 15);
        nd.gain_auto.load(j["automation"]["gain_db"]); nd.pan_auto.load(j["automation"]["pan"]);
        for (int c = 0; c < 2; ++c) { nd.buf[c].assign(max_block, 0.f); nd.tmp[c].assign(max_block, 0.f); }
        nd.g_l.prepare(sr); nd.g_r.prepare(sr);
        double gl, gr; pan_gains(nd, nd.gain_db, nd.pan, gl, gr); nd.g_l.snap(gl); nd.g_r.snap(gr);
        for (auto& c : j["clips"].a) {
            Clip cl;
            cl.path = c.gets("media");
            std::string err;
            cl.media = pool.get(cl.path, sr, err);
            if (!cl.media) { r.warnings.push_back("média absent : " + cl.path + " (" + err + ") : clip muet, référence conservée"); continue; }
            cl.start = c.geti("start", 0); cl.offset = c.geti("offset", 0);
            cl.length = c.geti("length", cl.media->frames() - cl.offset);
            cl.gain = db_to_lin(c.get("gain_db", 0)); cl.rate = std::clamp(c.get("rate", 1.0), 0.05, 8.0);
            cl.fade_in = c.geti("fade_in", 0); cl.fade_out = c.geti("fade_out", 0);
            cl.fade_in_shape = (int)c.geti("fade_in_shape", 0); cl.fade_out_shape = (int)c.geti("fade_out_shape", 0);
            cl.reverse = c.getb("reverse", false);
            if (c.getb("polarity", false)) cl.gain = -cl.gain;
            if (c.getb("mute", false)) continue;
            nd.clips.push_back(std::move(cl));
        }
        std::sort(nd.clips.begin(), nd.clips.end(), [](const Clip& a, const Clip& b) { return a.start < b.start; });
        const Json& ins = j["instrument"];
        if (ins.type == Json::Object && ins.gets("type").rfind("vst3:", 0) == 0) {
#ifdef FMZ_VST3
            std::string e;
            auto inst = vst3_acquire(vst3_pool, nd.id + "#inst", ins, vst3_uid_of(ins.gets("type")), sr, max_block, e);
            if (inst) {
                nd.inst = std::make_unique<Vst3Instrument>(inst);
                for (auto& kv : ins["params"].o) if (kv.second.type != Json::String) inst->set_key(kv.first.c_str(), kv.second.num_or(0));
                if (!e.empty()) r.warnings.push_back(nd.id + " : " + e);
            } else r.warnings.push_back("plugin instrument absent : " + ins.gets("name", ins.gets("type")) + " (" + e + ") : piste muette, aucun son de substitution");
#else
            r.warnings.push_back("plugin instrument " + ins.gets("name", ins.gets("type")) + " : moteur compilé sans l'hôte VST3 (piste muette)");
#endif
        } else if (ins.type == Json::Object) {
            nd.inst = make_instrument(ins.gets("type"));
            if (!nd.inst) { r.warnings.push_back("instrument inconnu ou absent : " + ins.gets("type") + " (piste muette, aucun son de substitution)"); }
            else {
                std::string e = nd.inst->configure(ins);
                if (!e.empty()) r.warnings.push_back(nd.id + " : " + e);
                nd.inst->prepare(sr);
            }
        }
        // notes : positions en ticks (carte tempo) ou en échantillons
        for (auto& clipn : j["midi_clips"].a) {
            int64_t cstart = clipn.geti("start_tick", 0), clen = clipn.geti("length_tick", INT64_MAX / 4);
            int transpose = (int)clipn.geti("transpose", 0);
            bool cmute = clipn.getb("mute", false);
            if (cmute) continue;
            for (auto& nt : clipn["notes"].a) {
                int64_t s = nt.geti("tick", 0), l = std::max<int64_t>(1, nt.geti("length", 240));
                if (s >= clen) continue;
                int64_t e = std::min(s + l, clen);
                int p = std::clamp((int)nt.geti("pitch", 60) + transpose, 0, 127), v = std::clamp((int)nt.geti("vel", 100), 1, 127);
                if (nt.getb("mute", false)) continue;
                nd.events.push_back({tempo.tick_to_sample(cstart + s), p, v, true});
                nd.events.push_back({tempo.tick_to_sample(cstart + e), p, 0, false});
            }
        }
        // note-off avant note-on au même instant (une note répétée se relance proprement)
        std::stable_sort(nd.events.begin(), nd.events.end(), [](const NoteEvent& a, const NoteEvent& b) { return a.at != b.at ? a.at < b.at : (!a.on && b.on); });
        for (size_t fi = 0; fi < j["fx"].a.size(); ++fi) {
            const Json& f = j["fx"].a[fi];
            FxSlot s; s.type = f.gets("type");
            if (s.type.rfind("vst3:", 0) == 0) {
#ifdef FMZ_VST3
                std::string e;
                auto inst = vst3_acquire(vst3_pool, nd.id + "#fx" + std::to_string(fi), f["params"], vst3_uid_of(s.type), sr, max_block, e);
                if (inst) { s.fx = std::make_unique<Vst3Fx>(inst); if (!e.empty()) r.warnings.push_back(nd.id + " : " + e); }
                else { r.warnings.push_back("plugin absent : " + f.gets("name", s.type) + " (" + e + ") : ignoré, son inchangé, signalé"); continue; }
#else
                r.warnings.push_back("plugin " + f.gets("name", s.type) + " : moteur compilé sans l'hôte VST3 (ignoré, signalé)");
                continue;
#endif
            } else s.fx = make_effect(s.type);
            if (!s.fx) { r.warnings.push_back("effet inconnu ou absent : " + s.type + " (ignoré, signalé)"); continue; }
            for (auto& kv : f["params"].o) {
                if (kv.second.type == Json::String) { std::string e = s.fx->set_text(kv.first.c_str(), kv.second.s); if (!e.empty()) r.warnings.push_back(e); }
                else s.fx->set(kv.first.c_str(), kv.second.num_or(0));
            }
            s.fx->bypass = f.getb("bypass", false);
            s.fx->prepare(sr, max_block);
            for (auto& kv : f["automation"].o) s.autos[kv.first].load(kv.second);
            std::string sc = f.gets("sidechain");
            if (!sc.empty()) {
                if (!index.count(sc)) { r.warnings.push_back("source de sidechain inconnue : " + sc); }
                else s.sidechain = index[sc];
            }
            nd.fx.push_back(std::move(s));
        }
        if (!nd.is_master) {
            Conn main; main.target = master;
            std::string tgt = j.gets("output", "master");
            if (tgt != "master") {
                if (!index.count(tgt)) { r.warnings.push_back(nd.id + " : sortie inconnue " + tgt + ", routée vers master"); }
                else main.target = index[tgt];
            }
            nd.outs.push_back(std::move(main));
            for (auto& s : j["sends"].a) {
                std::string t = s.gets("target");
                if (!index.count(t)) { r.warnings.push_back(nd.id + " : send vers bus inconnu " + t); continue; }
                Conn c; c.target = index[t]; c.is_send = true; c.pre = s.getb("pre", false); c.gain = db_to_lin(s.get("gain_db", 0));
                nd.outs.push_back(std::move(c));
            }
        }
        return true;
    }

    // Ordre topologique (Kahn). Un cycle (y compris par sidechain) est refusé.
    bool topo(BuildResult& r) {
        size_t N = nodes.size();
        std::vector<std::set<int>> adj(N);
        std::vector<int> indeg(N, 0);
        for (size_t i = 0; i < N; ++i) {
            for (auto& o : nodes[i]->outs) if (o.target >= 0 && adj[i].insert(o.target).second) indeg[o.target]++;
            for (auto& f : nodes[i]->fx) if (f.sidechain >= 0 && f.sidechain != (int)i && adj[f.sidechain].insert((int)i).second) indeg[i]++;
            for (auto& f : nodes[i]->fx) if (f.sidechain == (int)i) { r.ok = false; r.error = "sidechain sur soi-même : " + nodes[i]->id; return false; }
        }
        std::vector<int> q;
        for (size_t i = 0; i < N; ++i) if (!indeg[i]) q.push_back((int)i);
        order.clear();
        while (!q.empty()) {
            int k = q.back(); q.pop_back(); order.push_back(k);
            for (int t : adj[k]) if (--indeg[t] == 0) q.push_back(t);
        }
        if (order.size() != N) {
            std::string cyc;
            for (size_t i = 0; i < N; ++i) if (indeg[i]) cyc += nodes[i]->id + " ";
            r.ok = false; r.error = "routage cyclique refusé (pas de feedback retardé pris en charge) : " + cyc;
            return false;
        }
        return true;
    }

    // Compensation de latence par chemin : chaque entrée d'un nœud est retardée pour arriver
    // en même temps que la plus tardive.
    void compute_latency() {
        for (auto& n : nodes) { n->own_latency = 0; for (auto& f : n->fx) n->own_latency += f.fx->latency(); n->arrival = 0; }
        std::vector<int> in_max(nodes.size(), 0);
        for (int idx : order) {
            Node& nd = *nodes[idx];
            nd.arrival = in_max[idx] + nd.own_latency;
            for (auto& o : nd.outs) in_max[o.target] = std::max(in_max[o.target], nd.arrival);
        }
        for (int idx : order) {
            Node& nd = *nodes[idx];
            for (auto& o : nd.outs) o.comp.prepare(in_max[o.target] - nd.arrival, max_block);
        }
        total_latency = nodes[master]->arrival;
    }

    void pan_gains(const Node& nd, double gain_db, double pan, double& l, double& r) const {
        double g = db_to_lin(gain_db);
        if (nd.mono) { double a = (pan + 1) * kPi / 4; l = g * std::cos(a) * std::sqrt(2.0); r = g * std::sin(a) * std::sqrt(2.0); }
        else { l = g * (pan > 0 ? 1 - pan : 1); r = g * (pan < 0 ? 1 + pan : 1); }
    }

    void apply_fader(Node& nd, int64_t pos, int n, float* const* b) {
        double gdb = nd.gain_auto.empty() ? nd.gain_db : nd.gain_auto.at(pos);
        double pn = nd.pan_auto.empty() ? nd.pan : nd.pan_auto.at(pos);
        double l, r; pan_gains(nd, gdb, pn, l, r);
        if (!nd.gain_auto.empty() || !nd.pan_auto.empty()) {
            // automation : rampe linéaire jusqu'à la valeur de fin de bloc
            double gdb2 = nd.gain_auto.empty() ? gdb : nd.gain_auto.at(pos + n);
            double pn2 = nd.pan_auto.empty() ? pn : nd.pan_auto.at(pos + n);
            double l2, r2; pan_gains(nd, gdb2, pn2, l2, r2);
            for (int i = 0; i < n; ++i) { double f = (double)i / n; b[0][i] *= (float)(l + (l2 - l) * f); b[1][i] *= (float)(r + (r2 - r) * f); }
            nd.g_l.snap(l2); nd.g_r.snap(r2);
            return;
        }
        nd.g_l.target = l; nd.g_r.target = r;
        for (int i = 0; i < n; ++i) { b[0][i] *= (float)nd.g_l.next(); b[1][i] *= (float)nd.g_r.next(); }
    }

    void send(Node& nd, Conn& o, int n, float* const* b) {
        if (!nd.live_out) return;
        float* t[2] = {nd.tmp[0].data(), nd.tmp[1].data()};
        const float* src[2] = {b[0], b[1]};
        if (o.comp.d > 0) o.comp.process(src, t, n);
        else { std::copy(b[0], b[0] + n, t[0]); std::copy(b[1], b[1] + n, t[1]); }
        Node& dst = *nodes[o.target];
        float g = (float)o.gain;
        for (int c = 0; c < 2; ++c) { float* d = dst.buf[c].data(); for (int i = 0; i < n; ++i) d[i] += t[c][i] * g; }
    }

    void meter(Node& nd, int n) {
        float pl = 0, pr = 0;
        for (int i = 0; i < n; ++i) { pl = std::max(pl, std::abs(nd.buf[0][i])); pr = std::max(pr, std::abs(nd.buf[1][i])); }
        if (!nd.live_out) pl = pr = 0;
        // maximum conservé jusqu'à lecture par la télémétrie (échange atomique côté lecteur)
        float cur = nd.peak_l.load(std::memory_order_relaxed); if (pl > cur) nd.peak_l.store(pl, std::memory_order_relaxed);
        cur = nd.peak_r.load(std::memory_order_relaxed); if (pr > cur) nd.peak_r.store(pr, std::memory_order_relaxed);
        float g = 0; for (auto& f : nd.fx) g = std::min(g, f.fx->meter_gr());
        nd.gr.store(g, std::memory_order_relaxed);
    }

    void render_clips(Node& nd, int64_t pos, int n, float* const* b) {
        int64_t end = pos + n;
        for (auto& c : nd.clips) {
            if (c.start >= end) break;
            int64_t cend = c.start + c.length;
            if (cend <= pos) continue;
            const AudioData& m = *c.media;
            int64_t mf = m.frames();
            int mc = m.channels();
            int64_t i0 = std::max(pos, c.start), i1 = std::min(end, cend);
            for (int64_t t = i0; t < i1; ++t) {
                int64_t rel = t - c.start;
                double g = c.gain;
                if (c.fade_in > 0 && rel < c.fade_in) g *= Clip::shape((double)rel / c.fade_in, c.fade_in_shape);
                if (c.fade_out > 0 && rel >= c.length - c.fade_out) g *= Clip::shape((double)(c.length - rel) / c.fade_out, c.fade_out_shape);
                float s0, s1;
                if (c.rate == 1.0) {
                    int64_t src = c.reverse ? c.offset + c.length - 1 - rel : c.offset + rel;
                    if (src < 0 || src >= mf) continue;
                    s0 = m.ch[0][(size_t)src]; s1 = mc > 1 ? m.ch[1][(size_t)src] : s0;
                } else {
                    double src = c.offset + rel * c.rate;
                    if (src < 0 || src >= mf - 1) continue;
                    s0 = hermite(m.ch[0], src); s1 = mc > 1 ? hermite(m.ch[1], src) : s0;
                }
                b[0][t - pos] += (float)(s0 * g); b[1][t - pos] += (float)(s1 * g);
            }
        }
    }

    void render_instrument(Node& nd, int64_t pos, int n, float* const* b, bool playing) {
        int64_t end = pos + n;
        int done = 0;
        if (playing && !nd.events.empty()) {
            auto it = std::lower_bound(nd.events.begin(), nd.events.end(), pos, [](const NoteEvent& e, int64_t p) { return e.at < p; });
            for (; it != nd.events.end() && it->at < end; ++it) {
                int off = (int)(it->at - pos);
                if (nd.inst && off > done) { nd.inst->render(b[0] + done, b[1] + done, off - done); done = off; }
                if (nd.inst) { if (it->on) nd.inst->note_on(it->pitch, it->vel); else nd.inst->note_off(it->pitch); }
                if (nd.midi_out && midi_sink)
                    midi_sink(midi_ctx, (uint8_t)((it->on ? 0x90 : 0x80) | nd.midi_channel), (uint8_t)it->pitch, (uint8_t)(it->on ? it->vel : 0));
            }
        }
        if (nd.inst && done < n) nd.inst->render(b[0] + done, b[1] + done, n - done);
    }
};

}  // namespace fmz
