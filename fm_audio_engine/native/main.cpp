// fmz_audio_engine : processus moteur audio partagé de PIPE FMZ (FM Audio, FM Music, Board).
// Modes :
//   fmz_audio_engine --serve                      protocole IPC v1 (stdin/stdout, JSON par ligne)
//   fmz_audio_engine --render spec.json out.wav [--start S] [--end E] [--tail SEC|auto]
//                    [--format f32|pcm16|pcm24] [--dither] [--overwrite] [--stems DIR] [--block N]
//   fmz_audio_engine --devices                    liste JSON des périphériques
//   fmz_audio_engine --version
#define NOMINMAX
#include <fcntl.h>
#include <io.h>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include "graph.h"
#include "spsc.h"
#include "midi_io.h"
#include "teststream.h"
#include "asio_backend.h"

using namespace fmz;

static const char* kEngineVersion = "0.3.0";
static const int kProtocol = 1;

// ---------------------------------------------------------------- rendu offline
struct RenderOpts {
    int64_t start = 0, end = -1;
    double tail = -1;  // < 0 : automatique (traîne déclarée des effets / instruments)
    WavWriter::Format fmt = WavWriter::F32;
    bool dither = false, overwrite = false;
    int block = 512;
};

static Json render_graph(Graph& g, const std::string& out, const RenderOpts& o, std::atomic<bool>* cancel,
                         const std::function<void(double)>& progress) {
    int64_t start = std::max<int64_t>(0, o.start);
    int64_t end = o.end >= 0 ? o.end : g.content_end();
    if (end <= start) throw std::runtime_error("plage de rendu vide");
    int64_t tail = (int64_t)std::llround((o.tail >= 0 ? o.tail : g.tail_seconds()) * g.sr);
    int64_t lat = g.total_latency;
    int64_t want = end - start + tail;          // images écrites
    int64_t total = want + lat;                  // images calculées (la latence est retirée en tête)
    WavWriter w;
    w.open(out, (int)g.sr, 2, o.fmt, o.dither, o.overwrite);
    std::vector<float> l(o.block), r(o.block);
    float* outp[2] = {l.data(), r.data()};
    double peak = 0;
    int64_t done = 0, written = 0;
    bool has_nan = false;
    try {
        while (done < total) {
            if (cancel && cancel->load()) { w.abort(); Json j = Json::object(); j.set("cancelled", Json::boolean(true)); return j; }
            int n = (int)std::min<int64_t>(o.block, total - done);
            g.process(start + done, n, outp, nullptr, 0, true);
            int64_t skip = std::max<int64_t>(0, lat - done);
            if (skip < n) {
                int k = (int)(n - skip);
                for (int i = 0; i < k; ++i) {
                    float a = l[skip + i], b = r[skip + i];
                    if (!std::isfinite(a) || !std::isfinite(b)) has_nan = true;
                    peak = std::max(peak, (double)std::max(std::abs(a), std::abs(b)));
                }
                const float* ch[2] = {l.data() + skip, r.data() + skip};
                w.write(ch, k);
                written += k;
            }
            done += n;
            if (progress && (done / o.block) % 64 == 0) progress((double)done / total);
        }
        std::string path = w.close();
        WavInfo vi = wav_info(path);  // vérification du fichier réellement écrit
        if (vi.frames != written) throw std::runtime_error("vérification : " + std::to_string(vi.frames) + " images lues pour " + std::to_string(written) + " écrites");
        Json j = Json::object();
        j.set("path", Json::str(path)); j.set("frames", Json::num((double)written)); j.set("sample_rate", Json::num(g.sr));
        j.set("peak", Json::num(peak)); j.set("latency", Json::num((double)lat)); j.set("tail", Json::num((double)tail));
        j.set("nan", Json::boolean(has_nan)); j.set("revision", Json::num((double)g.revision));
        return j;
    } catch (...) { w.abort(); throw; }
}

// Stems : chaque piste seule (les autres coupées), À TRAVERS ses bus : les effets partagés
// (réverbe de bus…) sont inclus dans le stem de chaque piste qui les alimente (politique « bus »).
static Json render_stems(const Json& spec, const std::string& dir, const RenderOpts& o, MediaPool& pool, std::atomic<bool>* cancel,
                         const std::function<void(double)>& progress) {
    Json res = Json::array();
    const auto& tracks = spec["tracks"].a;
    for (size_t k = 0; k < tracks.size(); ++k) {
        Json s = spec;
        for (size_t i = 0; i < s.o["tracks"].a.size(); ++i) {
            Json& t = s.o["tracks"].a[i];
            t.set("solo", Json::boolean(false));
            if (i != k) t.set("mute", Json::boolean(true));
        }
        if (tracks[k].getb("mute", false)) continue;
        Graph g;
        BuildResult br = g.build(s, pool, o.block);
        if (!br.ok) throw std::runtime_error(br.error);
        std::string id = tracks[k].gets("id"), name = tracks[k].gets("name", id);
        std::string safe;
        for (char c : name) safe += (strchr("\\/:*?\"<>|", c) ? '_' : c);
        Json r = render_graph(g, dir + "/" + safe + ".wav", o, cancel, [&](double p) { if (progress) progress((k + p) / tracks.size()); });
        if (r.getb("cancelled", false)) return r;
        r.set("track", Json::str(id));
        res.push(r);
    }
    Json j = Json::object(); j.set("stems", res); j.set("policy", Json::str("bus"));
    return j;
}

// ---------------------------------------------------------------- moteur temps réel
struct Msg {
    enum Kind : int { Play, Stop, Seek, Loop, NodeSet, FxSet, Note, Panic, Metro, Record, Ping } kind;
    int a = 0, b = 0;
    int64_t p = 0, q = 0;
    double v = 0;
    char key[32] = {0};
};

struct CaptureBlock { int64_t pos; int frames; };

class Engine {
public:
    MediaPool pool;
#ifdef FMZ_VST3
    Vst3Pool vst3;             // instances VST3 du temps réel, gardées entre reconstructions du graphe
#endif
    std::mutex out_mx;
    AudioStream* stream = nullptr;
    int block = 512;
    double sr = 48000;

    MidiIO midi;
    // Accordeur : le callback copie l'entrée choisie dans un petit anneau ; la hauteur est calculée par le fil de télémétrie.
    std::atomic<int> tuner_ch{-1};
    float tuner_ring[4096] = {};
    std::atomic<int64_t> tuner_w{0};
    int tuner_tick = 0;
    double tuner_hz = 0;
    std::atomic<int> midi_target{-1};
    std::atomic<bool> midi_thru{false};
    std::atomic<bool> midi_lost_flag{false};

    Engine() : cmds_(1024), garbage_(64), cap_meta_(4096) {}
    static void midi_sink(void* ctx, uint8_t s, uint8_t a, uint8_t b) { ((Engine*)ctx)->midi.send({s, a, b}); }

    void emit(const Json& j) {
        std::string s = to_json(j);
        std::lock_guard<std::mutex> lk(out_mx);
        fwrite(s.data(), 1, s.size(), stdout); fputc('\n', stdout); fflush(stdout);
    }

    // ---- appelé hors temps réel
    BuildResult load(const Json& spec) {
        auto g = std::make_unique<Graph>();
#ifdef FMZ_VST3
        g->vst3_pool = &vst3;
        vst3.begin_build();
#endif
        BuildResult r = g->build(spec, pool, block);
        if (!r.ok) return r;
#ifdef FMZ_VST3
        vst3.end_build();
#endif
        if (stream && (int)g->sr != stream->sample_rate)
            r.warnings.push_back("fréquence du projet " + std::to_string((int)g->sr) + " Hz différente du périphérique " + std::to_string(stream->sample_rate) + " Hz : lecture à la fréquence du périphérique, rééchantillonnage à prévoir");
        Graph* old = pending_.exchange(g.release());
        delete old;  // jamais pris par le callback : suppression sûre
        if (!stream) adopt_pending_offline();
        return r;
    }

    bool post(const Msg& m) {
        if (!stream) { apply(current_.load(), m); return true; }  // sans callback : application directe
        if (!cmds_.push(m)) { cmd_overflow_++; return false; }
        return true;
    }

    void collect_garbage() { Graph* g; while (garbage_.pop(g)) delete g; }

    Json devices() {
        Json d = list_devices();
#ifdef FMZ_ASIO
        list_asio_devices(d);
#endif
        return d;
    }

    std::string open(const std::string& out_id, const std::string& in_id, int want_sr, int want_buf, bool excl, const Json& test = Json()) {
        close();
        auto cb = [this](float* out, int oc, int n, const float* const* in, int ic) { audio_callback(out, oc, n, in, ic); };
        AudioStream* s = nullptr;
        bool ok;
        if (out_id.rfind("test", 0) == 0) {          // périphérique de test DÉCLARÉ (double de test)
            auto t = new TestStream();
            t->fast = test.getb("fast", true);
            t->loop_delay = (int)test.geti("loopback_delay", -1);
            t->max_frames = test.geti("max_frames", -1);
            t->out_path = test.gets("out");
            t->hold = test.getb("hold_until_play", t->fast);
            ok = t->open(want_sr > 0 ? want_sr : 48000, want_buf > 0 ? want_buf : 256, (int)test.geti("in_channels", 2), cb);
            s = t;
        } else if (out_id.rfind("asio:", 0) == 0) {    // pilote ASIO (duplex : entrées du même pilote)
#ifdef FMZ_ASIO
            auto a = new AsioStream();
            ok = a->open(out_id, in_id, want_sr, want_buf, cb);
            s = a;
#else
            return "ASIO : moteur compilé sans le SDK ASIO (fm_audio_engine/third_party/ASIOSDK absent)";
#endif
        } else {
            auto w = new WasapiStream();
            ok = w->open(out_id, in_id, want_sr, want_buf, excl, cb);
            s = w;
        }
        if (!ok) { std::string e = s->error; delete s; return e.empty() ? "ouverture impossible" : e; }
        sr = s->sample_rate;
        in_ch_ = s->in_channels;
        cap_ring_.assign((size_t)(sr * 10) * std::max(1, in_ch_), 0.f);  // 10 s d'entrées, préalloués
        cap_w_ = cap_r_ = 0;
        stream = s;
        if (!s->start()) { std::string e = s->error; delete s; stream = nullptr; return e; }
        return std::string();
    }

    void close() {
        if (!stream) return;
        stream->stop();
        delete stream; stream = nullptr;
        // le callback est arrêté : on peut reprendre le graphe courant sans course
        adopt_pending_offline();
    }

    // YIN (de Cheveigné & Kawahara) sur les 2048 derniers échantillons ; 0 = pas de note stable.
    double detect_pitch() {
        const int N = 2048, W = 1024;
        float buf[N];
        int64_t w = tuner_w.load(std::memory_order_acquire);
        if (w < N) return 0;
        double e = 0;
        for (int i = 0; i < N; ++i) { buf[i] = tuner_ring[(w - N + i) & 4095]; e += buf[i] * buf[i]; }
        if (e / N < 1e-7) return 0;
        int tmin = std::max(2, (int)(sr / 1500)), tmax = std::min(W - 1, (int)(sr / 50));
        static double d[2048];
        double run = 0;
        d[0] = 1;
        for (int t = 1; t <= tmax; ++t) {
            double s = 0;
            for (int j = 0; j < W; ++j) { double x = buf[j] - buf[j + t]; s += x * x; }
            run += s;
            d[t] = run > 0 ? s * t / run : 1;
        }
        for (int t = tmin; t < tmax; ++t)
            if (d[t] < 0.12) {
                while (t + 1 < tmax && d[t + 1] < d[t]) ++t;
                double a = d[t - 1], b = d[t], c = d[t + 1], den = a - 2 * b + c;
                double sh = std::abs(den) > 1e-12 ? 0.5 * (a - c) / den : 0;
                return sr / (t + sh);
            }
        return 0;
    }

    Json telemetry() {        Json j = Json::object();
        j.set("event", Json::str("telemetry"));
        j.set("pos", Json::num((double)pos_.load()));
        j.set("playing", Json::boolean(playing_.load()));
        j.set("recording", Json::boolean(recording_.load()));
        j.set("cmd_overflow", Json::num((double)cmd_overflow_.load()));
        j.set("rt_overrun", Json::num((double)overrun_.load()));
        j.set("load", Json::num(load_.load()));
        j.set("ping_lag", Json::num((double)ping_lag_.load()));
        if (tuner_ch.load() >= 0) { if ((tuner_tick++ & 1) == 0) tuner_hz = detect_pitch(); j.set("tuner_hz", Json::num(tuner_hz)); }
        j.set("midi_in", Json::num((double)midi.in_count.load())); j.set("midi_lost", Json::boolean(midi_lost_flag.load()));
        j.set("midi_overflow", Json::num((double)(midi.in_overflow.load() + midi.out_overflow.load())));
        if (stream) j.set("backend", Json::str(stream->backend));
        if (stream) { j.set("xruns", Json::num((double)stream->xruns.load())); j.set("device_lost", Json::boolean(stream->device_lost.load())); }
        Graph* g = current_.load();
        if (g) {
            Json m = Json::object();
            for (auto& n : g->nodes) {
                Json a = Json::array();
                a.push(Json::num(n->peak_l.exchange(0))); a.push(Json::num(n->peak_r.exchange(0))); a.push(Json::num(n->gr.load()));
                m.set(n->id, a);
            }
            j.set("meters", m);
            j.set("revision", Json::num((double)g->revision));
            j.set("latency", Json::num(g->total_latency));
        }
        Json ip = Json::array();
        for (int c = 0; c < in_ch_ && c < 8; ++c) ip.push(Json::num(in_peak_[c].exchange(0)));
        j.set("input_peak", ip);
        if (rec_frames_.load() > 0 || recording_.load()) {
            Json c = Json::object();
            c.set("frames", Json::num((double)rec_frames_.load())); c.set("overflow", Json::num((double)cap_overflow_.load()));
            c.set("error", Json::str(rec_error()));
            j.set("capture", c);
        }
        return j;
    }

    // ---- enregistrement (worker d'écriture)
    struct Take { std::string track, path, journal; std::vector<int> inputs; int64_t start = -1, frames = 0; int pass = 0; WavWriter w; };
    std::string rec_dir, rec_prefix;
    std::vector<std::unique_ptr<Take>> takes, finished;
    std::vector<std::pair<std::string, std::vector<int>>> rec_tracks;
    int64_t punch_in = -1, punch_out = -1;
    std::thread rec_thread;
    std::atomic<bool> rec_run{false};
    std::mutex rec_mx;
    std::string rec_err_;
    std::string rec_error() { std::lock_guard<std::mutex> lk(rec_mx); return rec_err_; }

    std::string record_start(const Json& j) {
        if (!stream) return "aucun périphérique ouvert";
        if (in_ch_ == 0) return "aucune entrée ouverte";
        if (rec_run) return "enregistrement déjà en cours";
        rec_dir = j.gets("dir"); rec_prefix = j.gets("name", "prise");
        if (rec_dir.empty()) return "dossier de prises manquant";
        rec_tracks.clear();
        for (auto& t : j["tracks"].a) {
            std::vector<int> ins;
            for (auto& i : t["inputs"].a) { int c = (int)i.int_or(0); if (c < 0 || c >= in_ch_) return "entrée " + std::to_string(c) + " inexistante"; ins.push_back(c); }
            if (ins.empty()) ins.push_back(0);
            rec_tracks.push_back({t.gets("id"), ins});
        }
        if (rec_tracks.empty()) return "aucune piste armée";
        punch_in = j.geti("punch_in", -1); punch_out = j.geti("punch_out", -1);
        { std::lock_guard<std::mutex> lk(rec_mx); rec_err_.clear(); }
        cap_overflow_ = 0; rec_frames_ = 0; last_pos_ = INT64_MIN; pass_ = 0;
        finished.clear(); takes.clear();
        // tampons vidés AVANT d'autoriser le callback à écrire
        CaptureBlock cb; while (cap_meta_.pop(cb)) {}
        cap_r_.store(cap_w_.load());
        rec_run = true;
        rec_thread = std::thread([this] { writer_loop(); });
        recording_ = true;
        return std::string();
    }

    Json record_stop() {
        recording_ = false;
        if (rec_run) { rec_run = false; if (rec_thread.joinable()) rec_thread.join(); }
        Json res = Json::array();
        for (auto& t : finished) {
            Json k = Json::object();
            k.set("track", Json::str(t->track)); k.set("path", Json::str(t->path)); k.set("start", Json::num((double)t->start));
            k.set("frames", Json::num((double)t->frames)); k.set("pass", Json::num(t->pass));
            Json ins = Json::array(); for (int c : t->inputs) ins.push(Json::num(c)); k.set("inputs", ins);
            res.push(k);
        }
        Json j = Json::object();
        j.set("takes", res);
        j.set("overflow", Json::num((double)cap_overflow_.load()));
        j.set("error", Json::str(rec_error()));
        double lat = stream ? (stream->out_latency_ms + stream->in_latency_ms) : 0;
        j.set("declared_latency_samples", Json::num(std::llround(lat * sr / 1000.0)));
        return j;
    }

    void shutdown() {
        if (recording_ || rec_run) record_stop();
        close();
        Graph* g = current_.exchange(nullptr); delete g;
        g = pending_.exchange(nullptr); delete g;
        collect_garbage();
    }

    // Accès direct pour le mode hors périphérique (tests) : traite n images.
    void offline_block(float* l, float* r, int n) {
        float* o[2] = {l, r};
        render(o, n, nullptr, 0);
    }

private:
    SpscQueue<Msg> cmds_;
    SpscQueue<Graph*> garbage_;
    SpscQueue<CaptureBlock> cap_meta_;
    std::atomic<Graph*> pending_{nullptr}, current_{nullptr};
    std::atomic<int64_t> pos_{0};
    std::atomic<bool> playing_{false}, recording_{false};
    std::atomic<uint64_t> cmd_overflow_{0}, overrun_{0}, cap_overflow_{0};
    std::atomic<int64_t> rec_frames_{0};
    std::atomic<double> load_{0};
    std::atomic<float> in_peak_[8] = {};
    bool loop_on_ = false; int64_t loop_s_ = 0, loop_e_ = 0;
    // mesure de latence aller-retour : impulsion émise, recherchée dans l'entrée (boucle physique ou de test)
    bool ping_req_ = false, ping_active_ = false; int ping_ch_ = 0; int64_t ping_frame_ = 0, abs_frames_ = 0;
    std::atomic<int64_t> ping_lag_{-3};
    bool metro_ = false; double metro_lvl_ = 0.5; int64_t precount_end_ = INT64_MIN;
    double click_ph_ = 0, click_t_ = 1, click_f_ = 1000;
    int in_ch_ = 0;
    std::vector<float> cap_ring_;
    std::atomic<int64_t> cap_w_{0}, cap_r_{0};
    int64_t last_pos_ = INT64_MIN; int pass_ = 0;
    std::vector<float> mix_l_ = std::vector<float>(8192), mix_r_ = std::vector<float>(8192);

    void adopt_pending_offline() {
        Graph* g = pending_.exchange(nullptr);
        // l'ancien graphe part à la poubelle : seul le fil de télémétrie le détruit (il est aussi son lecteur)
        if (g) { Graph* old = current_.exchange(g); if (old && !garbage_.push(old)) delete old; }
    }

    void apply(Graph* g, const Msg& m) {
        switch (m.kind) {
            case Msg::Play: playing_ = true; if (m.a) { pos_ = m.p; } precount_end_ = m.b ? m.q : INT64_MIN; if (g) g->all_notes_off(false); break;
            case Msg::Stop: playing_ = false; if (g) g->all_notes_off(false); break;
            case Msg::Seek: pos_ = m.p; if (g) g->all_notes_off(false); break;
            case Msg::Loop: loop_on_ = m.a != 0; loop_s_ = m.p; loop_e_ = m.q; break;
            case Msg::Metro: metro_ = m.a != 0; metro_lvl_ = m.v; break;
            case Msg::Panic: if (g) g->all_notes_off(true); break;
            case Msg::Ping: ping_req_ = true; ping_ch_ = m.a; ping_lag_ = -1; break;
            case Msg::Note: if (g) g->live_note(m.a, m.b, (int)m.v); break;
            case Msg::NodeSet:
                if (g && m.a >= 0 && m.a < (int)g->nodes.size()) {
                    Node& n = *g->nodes[m.a];
                    if (key_is(m.key, "gain_db")) n.gain_db = m.v; else if (key_is(m.key, "pan")) n.pan = m.v;
                    else if (key_is(m.key, "mute")) n.mute = m.v != 0; else if (key_is(m.key, "solo")) n.solo = m.v != 0;
                    else if (key_is(m.key, "monitor")) n.monitor = m.v != 0; else if (key_is(m.key, "polarity")) n.polarity = m.v != 0;
                }
                break;
            case Msg::FxSet:
                if (g && m.a >= 0 && m.a < (int)g->nodes.size() && m.b >= 0 && m.b < (int)g->nodes[m.a]->fx.size()) {
                    if (key_is(m.key, "bypass")) g->nodes[m.a]->fx[m.b].fx->bypass = m.v != 0;
                    else g->nodes[m.a]->fx[m.b].fx->set(m.key, m.v);
                }
                break;
            default: break;
        }
    }

    // Métronome : clics sur les temps de la carte tempo (accent sur le premier temps).
    void metronome(Graph* g, int64_t pos, int n, float* const* out) {
        bool on = metro_ || (precount_end_ != INT64_MIN && pos < precount_end_);
        if (!g) return;
        for (int i = 0; i < n; ++i) {
            if (on) {
                int64_t s = pos + i;
                double t0 = g->tempo.sample_to_tick(s), t1 = g->tempo.sample_to_tick(s + 1);
                int den = 4, num = 4; int64_t sig_tick = 0;
                for (auto& sg : g->tempo.sigs) if (sg.tick <= (int64_t)t0) { den = sg.den; num = sg.num; sig_tick = sg.tick; }
                double beat = g->tempo.ppq * 4.0 / den;
                // un temps tombe dans [t0, t1) : clic à cet échantillon
                double k = std::ceil((t0 - sig_tick) / beat);
                if (k * beat < t1 - sig_tick) {
                    int64_t bi = (int64_t)k;
                    click_t_ = 0; click_ph_ = 0; click_f_ = (((bi % num) + num) % num == 0) ? 1600 : 1000;
                }
            }
            if (click_t_ < 0.04) {
                float v = (float)(std::sin(2 * kPi * click_ph_) * std::exp(-click_t_ * 120) * metro_lvl_);
                out[0][i] += v; out[1][i] += v;
                click_ph_ += click_f_ / sr; click_t_ += 1.0 / sr;
            }
        }
    }

    void render(float* const* out, int n, const float* const* in, int ic) {
        Graph* g = current_.load(std::memory_order_acquire);
        Graph* p = pending_.exchange(nullptr, std::memory_order_acq_rel);
        if (p) {
            // échange à la frontière de bloc ; l'ancien graphe est détruit hors callback
            if (g && !garbage_.push(g)) { /* poubelle pleine : on garde l'ancien vivant (fuite bornée évitée par la taille 64) */ }
            current_.store(p, std::memory_order_release);
            g = p;
        }
        Msg m;
        while (cmds_.pop(m)) apply(g, m);
        if (g) { g->midi_sink = &Engine::midi_sink; g->midi_ctx = this; }
        // MIDI entrant : vers la piste cible (jeu en direct), panique sur all-notes-off ou débranchement
        MidiEvent me;
        int tgt = midi_target.load(std::memory_order_relaxed);
        while (midi.in_q.pop(me)) {
            uint8_t kind = me.status & 0xF0;
            if (g && (kind == 0x90 || kind == 0x80)) g->live_note(tgt, me.d1, kind == 0x90 ? me.d2 : 0);
            else if (g && kind == 0xB0 && (me.d1 == 123 || me.d1 == 120)) g->all_notes_off(me.d1 == 120);
            if (midi_thru.load(std::memory_order_relaxed)) midi.send(me);
        }
        if (midi.lost.exchange(false)) { if (g) g->all_notes_off(true); midi_lost_flag = true; }
        int done = 0;
        while (done < n) {
            int k = std::min(n - done, g ? g->max_block : n);
            float* o[2] = {out[0] + done, out[1] + done};
            int64_t pos = pos_.load(std::memory_order_relaxed);
            bool playing = playing_.load(std::memory_order_relaxed);
            if (playing && loop_on_ && loop_e_ > loop_s_ && pos < loop_e_ && pos + k > loop_e_) k = (int)(loop_e_ - pos);
            const float* ins[8];
            for (int c = 0; c < ic && c < 8; ++c) ins[c] = in[c] + done;
            if (g) g->process(pos, k, o, in ? ins : nullptr, ic, playing && (precount_end_ == INT64_MIN || pos >= precount_end_));
            else { std::fill(o[0], o[0] + k, 0.f); std::fill(o[1], o[1] + k, 0.f); }
            if (playing) metronome(g, pos, k, o);
            if (recording_.load(std::memory_order_relaxed) && in && playing && (precount_end_ == INT64_MIN || pos >= precount_end_))
                capture(ins, ic, pos, k);   // jamais pendant le précompte
            if (playing) {
                int64_t np = pos + k;
                if (loop_on_ && loop_e_ > loop_s_ && np >= loop_e_) { np = loop_s_; if (g) g->all_notes_off(false); }
                pos_.store(np, std::memory_order_relaxed);
            }
            done += k;
        }
        if (ping_active_ && in && ping_ch_ < ic) {
            for (int i = 0; i < n; ++i)
                if (abs_frames_ + i > ping_frame_ && std::abs(in[ping_ch_][i]) > 0.3f) { ping_lag_ = abs_frames_ + i - ping_frame_; ping_active_ = false; break; }
            if (ping_active_ && abs_frames_ - ping_frame_ > (int64_t)sr * 2) { ping_lag_ = -2; ping_active_ = false; }  // rien reçu en 2 s
        }
        if (ping_req_) { out[0][0] += 0.9f; out[1][0] += 0.9f; ping_frame_ = abs_frames_; ping_active_ = true; ping_req_ = false; }
        { int tc = tuner_ch.load(std::memory_order_relaxed);
          if (tc >= 0 && in && tc < ic) { int64_t w = tuner_w.load(std::memory_order_relaxed);
              for (int i = 0; i < n; ++i) tuner_ring[(w + i) & 4095] = in[tc][i];
              tuner_w.store(w + n, std::memory_order_release); } }
        abs_frames_ += n;
        for (int c = 0; c < ic && c < 8; ++c) {
            float pk = 0; for (int i = 0; i < n; ++i) pk = std::max(pk, std::abs(in[c][i]));
            if (pk > in_peak_[c].load(std::memory_order_relaxed)) in_peak_[c].store(pk, std::memory_order_relaxed);
        }
    }

    // Callback temps réel : copie dans l'anneau de capture (préalloué) et publie la position.
    void capture(const float* const* in, int ic, int64_t pos, int k) {
        int64_t cap = (int64_t)cap_ring_.size() / std::max(1, ic);
        int64_t w = cap_w_.load(std::memory_order_relaxed), r = cap_r_.load(std::memory_order_acquire);
        if (w - r + k > cap) { cap_overflow_.fetch_add(k); return; }  // débordement : compté, signalé
        // ordre : données, puis index d'écriture, puis annonce au worker (il ne lit jamais un bloc incomplet)
        for (int i = 0; i < k; ++i) {
            int64_t slot = ((w + i) % cap) * ic;
            for (int c = 0; c < ic; ++c) cap_ring_[(size_t)(slot + c)] = in[c][i];
        }
        cap_w_.store(w + k, std::memory_order_release);
        CaptureBlock b{pos, k};
        if (!cap_meta_.push(b)) { cap_w_.store(w, std::memory_order_release); cap_overflow_.fetch_add(k); }
    }

    void audio_callback(float* out, int oc, int n, const float* const* in, int ic) {
        auto t0 = std::chrono::steady_clock::now();
        float* o[2] = {mix_l_.data(), mix_r_.data()};
        if (n > (int)mix_l_.size()) n = (int)mix_l_.size();
        render(o, n, in, ic);
        for (int i = 0; i < n; ++i) {
            for (int c = 0; c < oc; ++c) out[i * oc + c] = c == 0 ? o[0][i] : (c == 1 ? o[1][i] : 0.f);
        }
        double used = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        double budget = (double)n / sr;
        double ld = used / budget;
        load_.store(std::max(ld, load_.load() * 0.95));
        if (ld > 1.0) overrun_++;
    }

    void writer_loop() {
        int64_t cap = 0;
        std::vector<float> tmp[2];
        int64_t last_flush = 0;
        while (true) {
            CaptureBlock b;
            bool got = cap_meta_.pop(b);
            if (!got) {
                if (!rec_run) break;
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
                continue;
            }
            cap = (int64_t)cap_ring_.size() / std::max(1, in_ch_);
            int64_t r = cap_r_.load(std::memory_order_acquire);
            // nouvelle passe de boucle : nouvelle prise (les prises restent des sources indépendantes)
            if (last_pos_ != INT64_MIN && b.pos < last_pos_) { finish_takes(); ++pass_; }
            last_pos_ = b.pos + b.frames;
            int64_t a = b.pos, e = b.pos + b.frames;
            if (punch_in >= 0) a = std::max(a, punch_in);
            if (punch_out >= 0) e = std::min(e, punch_out);
            if (e > a) {
                if (takes.empty()) open_takes(a);
                for (auto& t : takes) {
                    int nc = (int)t->inputs.size();
                    for (int c = 0; c < nc; ++c) tmp[c].resize((size_t)(e - a));
                    for (int64_t i = a; i < e; ++i) {
                        int64_t slot = ((r + (i - b.pos)) % cap) * in_ch_;
                        for (int c = 0; c < nc && c < 2; ++c) tmp[c][(size_t)(i - a)] = cap_ring_[(size_t)(slot + t->inputs[c])];
                    }
                    const float* ch[2] = {tmp[0].data(), nc > 1 ? tmp[1].data() : tmp[0].data()};
                    try { t->w.write(ch, e - a); t->frames += e - a; }
                    catch (const std::exception& ex) {
                        std::lock_guard<std::mutex> lk(rec_mx);
                        if (rec_err_.empty()) rec_err_ = std::string(ex.what()) + " : prise arrêtée à " + std::to_string(t->frames) + " images écrites";
                        recording_ = false;
                    }
                }
                rec_frames_ += e - a;
            }
            cap_r_.store(r + b.frames, std::memory_order_release);
            if (rec_frames_ - last_flush > sr) { last_flush = rec_frames_; for (auto& t : takes) journal(*t, false); }
        }
        finish_takes();
    }

    void open_takes(int64_t start) {
        for (auto& tr : rec_tracks) {
            auto t = std::make_unique<Take>();
            t->track = tr.first; t->inputs = tr.second; t->start = start; t->pass = pass_;
            char suffix[64]; snprintf(suffix, sizeof suffix, "_%s_p%02d", tr.first.c_str(), pass_);
            t->path = rec_dir + "/" + rec_prefix + suffix + ".wav";
            t->journal = t->path + ".journal";
            int nc = (int)std::min<size_t>(2, t->inputs.size());
            try { t->w.open(t->path, (int)sr, nc, WavWriter::F32, false, false); journal(*t, false); }
            catch (const std::exception& ex) { std::lock_guard<std::mutex> lk(rec_mx); rec_err_ = ex.what(); continue; }
            takes.push_back(std::move(t));
        }
    }

    // Journal de prise : permet de récupérer après panne ce qui a réellement été écrit.
    void journal(Take& t, bool final_) {
        Json j = Json::object();
        j.set("track", Json::str(t.track)); j.set("path", Json::str(t.path)); j.set("part", Json::str(t.path + ".part"));
        j.set("start", Json::num((double)t.start)); j.set("frames_checkpoint", Json::num((double)t.frames));
        j.set("sample_rate", Json::num(sr)); j.set("channels", Json::num((double)std::min<size_t>(2, t.inputs.size())));
        j.set("final", Json::boolean(final_));
        FILE* f = open_file(t.journal, "wb");
        if (!f) return;
        std::string s = to_json(j); fwrite(s.data(), 1, s.size(), f); fflush(f); fclose(f);
    }

    void finish_takes() {
        for (auto& t : takes) {
            try { t->w.close(); journal(*t, true); }
            catch (const std::exception& ex) { std::lock_guard<std::mutex> lk(rec_mx); rec_err_ = ex.what(); }
            finished.push_back(std::move(t));
        }
        takes.clear();
    }
};

// ---------------------------------------------------------------- IPC
struct Job { std::thread th; std::atomic<bool> cancel{false}; std::atomic<bool> done{false}; };

static int serve() {
    ComInit com;
    Engine eng;
    std::map<int, std::unique_ptr<Job>> jobs;
    int next_job = 1;
    std::atomic<bool> alive{true};
    std::thread tele([&] {
        while (alive) {
            std::this_thread::sleep_for(std::chrono::milliseconds(33));
            if (!alive) break;
            eng.emit(eng.telemetry());
            eng.collect_garbage();
        }
    });
    auto reply = [&](const Json& req, Json r) { r.set("id", req["id"]); if (!r.has("ok")) r.set("ok", Json::boolean(true)); eng.emit(r); };
    auto fail = [&](const Json& req, const std::string& e) { Json r = Json::object(); r.set("ok", Json::boolean(false)); r.set("error", Json::str(e)); reply(req, r); };
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        Json req;
        try { req = parse_json(line); } catch (const std::exception& e) { Json r = Json::object(); r.set("ok", Json::boolean(false)); r.set("error", Json::str(e.what())); eng.emit(r); continue; }
        std::string cmd = req.gets("cmd");
        try {
            if (cmd == "hello") {
                Json r = Json::object(); r.set("protocol", Json::num(kProtocol)); r.set("engine", Json::str(kEngineVersion));
                Json b = Json::array(); b.push(Json::str("wasapi"));
                Json u = Json::object();
#ifdef FMZ_ASIO
                b.push(Json::str("asio"));
#else
                u.set("asio", Json::str("moteur compilé sans le SDK ASIO"));
#endif
#ifdef FMZ_VST3
                Json pl = Json::array(); pl.push(Json::str("vst3")); r.set("plugins", pl);
#else
                u.set("vst3", Json::str("moteur compilé sans le SDK VST3"));
#endif
                r.set("backends", b); r.set("unavailable", u);
                reply(req, r);
            } else if (cmd == "devices") { Json r = Json::object(); r.set("devices", eng.devices()); reply(req, r); }
            else if (cmd == "open_device") {
                std::string e = eng.open(req.gets("output", "default"), req.gets("input"), (int)req.geti("sample_rate", 0), (int)req.geti("buffer", 0), req.getb("exclusive", false), req["test"]);
                if (!e.empty()) { fail(req, e); continue; }
                Json r = Json::object();
                r.set("sample_rate", Json::num(eng.stream->sample_rate)); r.set("buffer", Json::num(eng.stream->buffer_frames));
                r.set("out_channels", Json::num(eng.stream->out_channels)); r.set("in_channels", Json::num(eng.stream->in_channels));
                r.set("out_latency_ms", Json::num(eng.stream->out_latency_ms)); r.set("in_latency_ms", Json::num(eng.stream->in_latency_ms));
                r.set("exclusive", Json::boolean(eng.stream->exclusive)); r.set("backend", Json::str(eng.stream->backend));
                reply(req, r);
            } else if (cmd == "close_device") { eng.close(); reply(req, Json::object()); }
            else if (cmd == "load") {
                BuildResult br = eng.load(req["spec"]);
                if (!br.ok) { fail(req, br.error); continue; }
                Json r = Json::object(); Json w = Json::array(); for (auto& s : br.warnings) w.push(Json::str(s)); r.set("warnings", w);
                reply(req, r);
            } else if (cmd == "play" || cmd == "stop" || cmd == "seek" || cmd == "loop" || cmd == "metronome" || cmd == "panic" || cmd == "note" || cmd == "node" || cmd == "param" || cmd == "measure_latency") {
                Msg m{};
                if (cmd == "play") { m.kind = Msg::Play; m.a = req.has("from"); m.p = req.geti("from", 0); m.b = req.has("precount_until"); m.q = req.geti("precount_until", 0); }
                else if (cmd == "stop") m.kind = Msg::Stop;
                else if (cmd == "seek") { m.kind = Msg::Seek; m.p = req.geti("pos", 0); }
                else if (cmd == "loop") { m.kind = Msg::Loop; m.a = req.getb("on", false); m.p = req.geti("start", 0); m.q = req.geti("end", 0); }
                else if (cmd == "metronome") { m.kind = Msg::Metro; m.a = req.getb("on", false); m.v = req.get("level", 0.5); }
                else if (cmd == "panic") m.kind = Msg::Panic;
                else if (cmd == "measure_latency") { m.kind = Msg::Ping; m.a = (int)req.geti("input", 0); }
                else if (cmd == "note") { m.kind = Msg::Note; m.a = (int)req.geti("node", -1); m.b = (int)req.geti("pitch", 60); m.v = (double)req.geti("vel", 0); }
                else {
                    m.kind = cmd == "node" ? Msg::NodeSet : Msg::FxSet;
                    m.a = (int)req.geti("node", -1); m.b = (int)req.geti("fx", -1); m.v = req.get("value", 0);
                    std::string k = req.gets("key"); if (k.size() >= sizeof m.key) { fail(req, "clé trop longue"); continue; }
                    memcpy(m.key, k.c_str(), k.size() + 1);
                }
                if (!eng.post(m)) { fail(req, "file de commandes pleine (commande refusée, à renvoyer)"); continue; }
                if (m.kind == Msg::Play && eng.stream && eng.stream->backend == "test") static_cast<TestStream*>(eng.stream)->hold = false;
                reply(req, Json::object());
            } else if (cmd == "record_start") {
                std::string e = eng.record_start(req);
                if (!e.empty()) fail(req, e); else reply(req, Json::object());
            } else if (cmd == "record_stop") { reply(req, eng.record_stop()); }
            else if (cmd == "render") {
                int id = next_job++;
                auto job = std::make_unique<Job>();
                Job* jp = job.get();
                Json spec = req["spec"];
                std::string out = req.gets("out"), stems = req.gets("stems");
                RenderOpts o;
                o.start = req.geti("start", 0); o.end = req.geti("end", -1); o.tail = req.get("tail", -1);
                std::string f = req.gets("format", "f32");
                o.fmt = f == "pcm16" ? WavWriter::PCM16 : (f == "pcm24" ? WavWriter::PCM24 : WavWriter::F32);
                o.dither = req.getb("dither", o.fmt != WavWriter::F32); o.overwrite = req.getb("overwrite", false);
                job->th = std::thread([&eng, jp, id, spec, out, stems, o] {
                    Json ev = Json::object(); ev.set("event", Json::str("done")); ev.set("job", Json::num(id));
                    try {
                        MediaPool pool;
                        auto prog = [&](double p) { Json e = Json::object(); e.set("event", Json::str("progress")); e.set("job", Json::num(id)); e.set("progress", Json::num(p)); eng.emit(e); };
                        Json r;
                        if (!stems.empty()) r = render_stems(spec, stems, o, pool, &jp->cancel, prog);
                        else {
                            Graph g; BuildResult br = g.build(spec, pool, o.block);
                            if (!br.ok) throw std::runtime_error(br.error);
                            r = render_graph(g, out, o, &jp->cancel, prog);
                        }
                        ev.set("ok", Json::boolean(true)); ev.set("result", r);
                    } catch (const std::exception& e) { ev.set("ok", Json::boolean(false)); ev.set("error", Json::str(e.what())); }
                    eng.emit(ev);
                    jp->done = true;
                });
                jobs[id] = std::move(job);
                Json r = Json::object(); r.set("job", Json::num(id)); reply(req, r);
            } else if (cmd == "cancel") {
                auto it = jobs.find((int)req.geti("job", -1));
                if (it == jobs.end()) { fail(req, "travail inconnu"); continue; }
                it->second->cancel = true; reply(req, Json::object());
            } else if (cmd == "status") { Json t = eng.telemetry(); t.o.erase("event"); reply(req, t); }
            else if (cmd == "midi_devices") { Json r = MidiIO::devices(); reply(req, r); }
            else if (cmd == "midi_open") {
                std::string err;
                for (auto& i : req["inputs"].a) { std::string e = eng.midi.open_input((int)i.int_or(-1)); if (!e.empty()) err += e + "; "; }
                if (req.has("output")) { std::string e = eng.midi.open_output((int)req.geti("output", -1)); if (!e.empty()) err += e; }
                eng.midi_target = (int)req.geti("target", eng.midi_target.load());
                eng.midi_thru = req.getb("thru", false);
                if (!err.empty()) fail(req, err); else reply(req, Json::object());
            }
            else if (cmd == "tuner") { eng.tuner_ch = (int)req.geti("input", -1); eng.tuner_hz = 0; reply(req, Json::object()); }
            else if (cmd == "midi_target") { eng.midi_target = (int)req.geti("node", -1); reply(req, Json::object()); }
            else if (cmd == "midi_inject") {   // double de test : même file que le pilote MIDI
                eng.midi.inject({(uint8_t)req.geti("status", 0x90), (uint8_t)req.geti("d1", 60), (uint8_t)req.geti("d2", 100)});
                reply(req, Json::object());
            }
            else if (cmd == "midi_close") { eng.midi.close_all(); reply(req, Json::object()); }
            else if (cmd == "vst3_editor") {
#ifdef FMZ_VST3
                // éditeur du plugin : fenêtre du moteur (open=true / false ; absent = état)
                auto inst = eng.vst3.find(req.gets("node") + "#" + req.gets("slot"));
                if (!inst) { fail(req, "aucun plugin chargé à " + req.gets("node") + " / " + req.gets("slot")); continue; }
                Json r = Json::object();
                if (req["open"].type == Json::Bool && req.getb("open", false)) {
                    int w = 0, h = 0; std::string e = inst->open_editor(w, h);
                    if (!e.empty()) { fail(req, inst->name + " : " + e); continue; }
                    r.set("width", Json::num(w)); r.set("height", Json::num(h));
                } else if (req["open"].type == Json::Bool) inst->close_editor();
                r.set("open", Json::boolean(inst->editor_open())); r.set("name", Json::str(inst->name));
                reply(req, r);
#else
                fail(req, "moteur compilé sans l'hôte VST3");
#endif
            }
            else if (cmd == "vst3_state" || cmd == "vst3_params") {
#ifdef FMZ_VST3
                // instance temps réel : nœud + emplacement ("fx<N>" ou "inst")
                auto inst = eng.vst3.find(req.gets("node") + "#" + req.gets("slot"));
                if (!inst) { fail(req, "aucun plugin chargé à " + req.gets("node") + " / " + req.gets("slot")); continue; }
                Json r = Json::object();
                r.set("name", Json::str(inst->name)); r.set("latency", Json::num(inst->latency));
                r.set("edits", Json::num((double)inst->edits.load()));
                if (cmd == "vst3_state") r.set("state", Json::str(inst->get_state()));
                else r.set("params", inst->params_json());
                reply(req, r);
#else
                fail(req, "moteur compilé sans l'hôte VST3");
#endif
            }
            else if (cmd == "forget_media") { eng.pool.forget(req.gets("path")); reply(req, Json::object()); }            else if (cmd == "shutdown") { reply(req, Json::object()); break; }
            else fail(req, "commande inconnue : " + cmd);
        } catch (const std::exception& e) { fail(req, e.what()); }
        for (auto it = jobs.begin(); it != jobs.end();) {
            if (it->second->done) { it->second->th.join(); it = jobs.erase(it); } else ++it;
        }
    }
    // stdin fermé (interface disparue) ou shutdown : arrêt propre, prises finalisées
    for (auto& j : jobs) { j.second->cancel = true; }
    for (auto& j : jobs) { if (j.second->th.joinable()) j.second->th.join(); }
    alive = false;
    tele.join();      // plus aucun lecteur concurrent du graphe
    eng.shutdown();
    return 0;
}

static std::string read_text(const std::string& path) {
    FILE* f = open_file(path, "rb");
    if (!f) throw std::runtime_error("lecture impossible : " + path);
    std::string s; char buf[65536]; size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) s.append(buf, n);
    fclose(f);
    return s;
}

// Banc : temps de calcul du graphe par bloc (DSP seul, hors ordonnancement du pilote).
static int bench(const std::string& spec_path, int blocks, int block) {
    Json spec = parse_json(read_text(spec_path));
    MediaPool pool; Graph g; BuildResult br = g.build(spec, pool, block);
    if (!br.ok) { printf("{\"ok\":false,\"error\":\"%s\"}\n", br.error.c_str()); return 2; }
    std::vector<float> l(block), r(block); float* o[2] = {l.data(), r.data()};
    std::vector<double> us; us.reserve(blocks);
    for (int i = 0; i < blocks; ++i) {
        auto t0 = std::chrono::steady_clock::now();
        g.process((int64_t)i * block, block, o, nullptr, 0, true);
        us.push_back(std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count());
    }
    std::sort(us.begin(), us.end());
    auto pc = [&](double p) { return us[std::min(us.size() - 1, (size_t)(p * us.size()))]; };
    double deadline = 1e6 * block / g.sr;
    printf("{\"ok\":true,\"blocks\":%d,\"block\":%d,\"deadline_us\":%.1f,\"p50_us\":%.1f,\"p95_us\":%.1f,\"p99_us\":%.1f,\"max_us\":%.1f,\"p99_ratio\":%.3f,\"nodes\":%zu}\n",
           blocks, block, deadline, pc(0.5), pc(0.95), pc(0.99), us.back(), pc(0.99) / deadline, g.nodes.size());
    return 0;
}

int wmain(int argc, wchar_t** wargv) {
    std::vector<std::string> args;
    for (int i = 1; i < argc; ++i) args.push_back(narrow(wargv[i]));
    _setmode(_fileno(stdout), 0x8000 /*_O_BINARY*/);
    if (args.empty() || args[0] == "--version") { printf("{\"engine\":\"%s\",\"protocol\":%d}\n", kEngineVersion, kProtocol); return 0; }
    if (args[0] == "--serve") return serve();
    if (args[0] == "--bench" && args.size() >= 2) return bench(args[1], args.size() > 2 ? atoi(args[2].c_str()) : 4000, args.size() > 3 ? atoi(args[3].c_str()) : 128);
    if (args[0] == "--scan-vst3" && args.size() >= 2) {
#ifdef FMZ_VST3
        std::string s = to_json(vst3_scan(args[1])); printf("%s\n", s.c_str()); return 0;
#else
        printf("{\"error\":\"moteur compilé sans l'hôte VST3\"}\n"); return 2;
#endif
    }
    if (args[0] == "--devices") {
        ComInit com; Json d = list_devices();
#ifdef FMZ_ASIO
        list_asio_devices(d);
#endif
        std::string s = to_json(d); printf("%s\n", s.c_str()); return 0;
    }
    if (args[0] == "--render" && args.size() >= 3) {
        RenderOpts o; std::string stems;
        for (size_t i = 3; i < args.size(); ++i) {
            const std::string& a = args[i];
            auto next = [&]() -> std::string { return i + 1 < args.size() ? args[++i] : std::string(); };
            if (a == "--start") o.start = atoll(next().c_str());
            else if (a == "--end") o.end = atoll(next().c_str());
            else if (a == "--tail") { std::string t = next(); o.tail = t == "auto" ? -1 : atof(t.c_str()); }
            else if (a == "--format") { std::string f = next(); o.fmt = f == "pcm16" ? WavWriter::PCM16 : (f == "pcm24" ? WavWriter::PCM24 : WavWriter::F32); }
            else if (a == "--dither") o.dither = true;
            else if (a == "--overwrite") o.overwrite = true;
            else if (a == "--stems") stems = next();
            else if (a == "--block") o.block = std::max(1, atoi(next().c_str()));
        }
        try {
            Json spec = parse_json(read_text(args[1]));
            MediaPool pool;
            Json r;
            if (!stems.empty()) r = render_stems(spec, stems, o, pool, nullptr, nullptr);
            else {
                Graph g; BuildResult br = g.build(spec, pool, o.block);
                if (!br.ok) throw std::runtime_error(br.error);
                r = render_graph(g, args[2], o, nullptr, nullptr);
                Json w = Json::array(); for (auto& s : br.warnings) w.push(Json::str(s)); r.set("warnings", w);
            }
            r.set("ok", Json::boolean(true));
            std::string s = to_json(r); printf("%s\n", s.c_str());
            return 0;
        } catch (const std::exception& e) {
            Json r = Json::object(); r.set("ok", Json::boolean(false)); r.set("error", Json::str(e.what()));
            std::string s = to_json(r); printf("%s\n", s.c_str());
            return 2;
        }
    }
    fprintf(stderr, "usage : --serve | --render spec.json out.wav [...] | --devices | --version\n");
    return 1;
}
