// fmz_audio_engine : HÔTE VST3 (SDK Steinberg 3.8.1, MIT ; compilé si le SDK est présent dans
// fm_audio_engine/third_party/vst3sdk : FMZ_VST3 défini par build.py).
//
// - Référence d'un plugin dans le projet : type "vst3:<UID de classe, 32 hex>" + paramètre texte "path"
//   (module .vst3) ; "state" = état du composant en base64 ; paramètres numériques "p<id>" (normalisés 0..1).
// - Modules chargés UNE fois (cache), jamais déchargés pendant la vie du moteur.
// - Temps réel : les instances sont gardées d'une reconstruction du graphe à l'autre (Vst3Pool, clé
//   nœud#fxN / nœud#inst) : une édition ne recharge pas le plugin et ne coupe pas ses traînes. Le rendu
//   offline crée SES instances (mode kOffline), jamais celles du temps réel.
// - Paramètres : écrits par n'importe quel fil dans des atomiques, livrés au plugin au bloc suivant
//   (IParameterChanges préalloué) ; aucune allocation dans le callback.
// - Plugin absent / refusé : SIGNALÉ (avertissement du chargement), effet laissé de côté (son inchangé),
//   instrument muet ; jamais un autre son à la place.
#pragma once
#ifdef FMZ_VST3
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <condition_variable>
#include <functional>
#include <unordered_map>

#include "public.sdk/source/vst/hosting/module.h"
#include "public.sdk/source/vst/hosting/hostclasses.h"
#include "public.sdk/source/vst/hosting/plugprovider.h"
#include "public.sdk/source/vst/hosting/processdata.h"
#include "public.sdk/source/vst/hosting/parameterchanges.h"
#include "public.sdk/source/vst/hosting/eventlist.h"
#include "public.sdk/source/vst/hosting/connectionproxy.h"
#include "public.sdk/source/vst/utility/stringconvert.h"
#include "public.sdk/source/common/memorystream.h"
#include "pluginterfaces/vst/ivstaudioprocessor.h"
#include "pluginterfaces/vst/ivstcomponent.h"
#include "pluginterfaces/vst/ivsteditcontroller.h"
#include "pluginterfaces/vst/ivstprocesscontext.h"
#include "pluginterfaces/vst/ivstevents.h"
#include "pluginterfaces/gui/iplugview.h"

namespace fmz {

namespace sv = Steinberg::Vst;
using Steinberg::IPtr;
using Steinberg::tresult;
using Steinberg::kResultOk;
using Steinberg::kResultTrue;

// ---------------------------------------------------------------- base64 (états)
inline std::string b64_encode(const char* p, size_t n) {
    static const char* T = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string o; o.reserve((n + 2) / 3 * 4);
    for (size_t i = 0; i < n; i += 3) {
        uint32_t v = (uint8_t)p[i] << 16 | (i + 1 < n ? (uint8_t)p[i + 1] << 8 : 0) | (i + 2 < n ? (uint8_t)p[i + 2] : 0);
        o += T[v >> 18 & 63]; o += T[v >> 12 & 63];
        o += i + 1 < n ? T[v >> 6 & 63] : '='; o += i + 2 < n ? T[v & 63] : '=';
    }
    return o;
}
inline std::string b64_decode(const std::string& s) {
    auto val = [](char c) -> int {
        if (c >= 'A' && c <= 'Z') return c - 'A'; if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52; if (c == '+') return 62; if (c == '/') return 63; return -1; };
    std::string o; uint32_t acc = 0; int bits = 0;
    for (char c : s) { int v = val(c); if (v < 0) continue; acc = acc << 6 | v; bits += 6; if (bits >= 8) { bits -= 8; o += (char)(acc >> bits & 255); } }
    return o;
}

// ---------------------------------------------------------------- modules et contexte hôte
inline sv::HostApplication* vst3_host_context() {
    static IPtr<sv::HostApplication> host = Steinberg::owned(new sv::HostApplication());
    static bool once = [] { sv::PluginContextFactory::instance().setPluginContext(host); return true; }();
    (void)once;
    return host.get();
}

inline VST3::Hosting::Module::Ptr vst3_module(const std::string& path, std::string& err) {
    static std::mutex m;
    static std::map<std::string, VST3::Hosting::Module::Ptr> mods;
    std::lock_guard<std::mutex> lk(m);
    auto it = mods.find(path);
    if (it != mods.end()) return it->second;
    auto mod = VST3::Hosting::Module::create(path, err);
    if (mod) mods[path] = mod;
    return mod;
}

inline std::string vst3_uid_of(const std::string& type) { return type.rfind("vst3:", 0) == 0 ? type.substr(5) : type; }

// ---------------------------------------------------------------- éditeurs (fenêtres du moteur)
// Un fil d'interface unique (STA OLE, boucle de messages) porte toutes les fenêtres d'éditeurs ; les
// commandes y sont exécutées de façon synchrone (run). L'audio n'attend jamais ce fil.
class Vst3UiThread {
public:
    static Vst3UiThread& get() { static Vst3UiThread t; return t; }
    void run(std::function<void()> fn) {
        ensure();
        if (GetCurrentThreadId() == tid_) { fn(); return; }
        Job job; job.fn = std::move(fn);
        while (!PostThreadMessageW(tid_, kMsg, 0, (LPARAM)&job)) Sleep(1);
        std::unique_lock<std::mutex> lk(job.m);
        job.cv.wait(lk, [&] { return job.done; });
    }
private:
    static const UINT kMsg = WM_APP + 7;
    struct Job { std::function<void()> fn; std::mutex m; std::condition_variable cv; bool done = false; };
    DWORD tid_ = 0;
    std::once_flag once_;
    void ensure() {
        std::call_once(once_, [this] {
            std::mutex m; std::condition_variable cv; bool ready = false;
            std::thread([&, this] {
                MSG msg;
                PeekMessageW(&msg, nullptr, 0, 0, PM_NOREMOVE);
                OleInitialize(nullptr);
                { std::lock_guard<std::mutex> lk(m); tid_ = GetCurrentThreadId(); ready = true; cv.notify_all(); }
                while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
                    if (msg.hwnd == nullptr && msg.message == kMsg) {
                        Job* j = (Job*)msg.lParam;
                        try { j->fn(); } catch (...) {}
                        std::lock_guard<std::mutex> lk(j->m); j->done = true; j->cv.notify_all();
                    } else { TranslateMessage(&msg); DispatchMessageW(&msg); }
                }
            }).detach();
            std::unique_lock<std::mutex> lk(m);
            cv.wait(lk, [&] { return ready; });
        });
    }
};

class Vst3Editor : public Steinberg::IPlugFrame {
public:
    HWND hwnd = nullptr;
    IPtr<Steinberg::IPlugView> view;
    std::atomic<bool> closed{false};
    int width = 0, height = 0;

    tresult PLUGIN_API queryInterface(const Steinberg::TUID iid, void** obj) override {
        if (Steinberg::FUnknownPrivate::iidEqual(iid, Steinberg::IPlugFrame::iid) || Steinberg::FUnknownPrivate::iidEqual(iid, Steinberg::FUnknown::iid)) {
            *obj = static_cast<Steinberg::IPlugFrame*>(this); return kResultOk; }
        *obj = nullptr; return Steinberg::kNoInterface;
    }
    Steinberg::uint32 PLUGIN_API addRef() override { return 1; }
    Steinberg::uint32 PLUGIN_API release() override { return 1; }
    tresult PLUGIN_API resizeView(Steinberg::IPlugView* v, Steinberg::ViewRect* r) override {
        if (!hwnd || !r) return Steinberg::kResultFalse;
        place(r->getWidth(), r->getHeight(), false);
        v->onSize(r);
        return kResultOk;
    }

    // Fil d'interface seulement.
    bool open(sv::IEditController* ctrl, const std::string& title, std::string& err) {
        view = Steinberg::owned(ctrl->createView(sv::ViewType::kEditor));
        if (!view) { err = "ce plugin n'a pas d'éditeur"; return false; }
        if (view->isPlatformTypeSupported(Steinberg::kPlatformTypeHWND) != kResultTrue) { view = nullptr; err = "éditeur non pris en charge sous Windows"; return false; }
        static bool registered = [] {
            WNDCLASSEXW wc{sizeof wc}; wc.lpfnWndProc = &Vst3Editor::proc; wc.hInstance = GetModuleHandleW(nullptr);
            wc.hCursor = LoadCursorW(nullptr, IDC_ARROW); wc.lpszClassName = L"FMZVst3Editor"; wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
            return RegisterClassExW(&wc) != 0; }();
        (void)registered;
        hwnd = CreateWindowExW(0, L"FMZVst3Editor", widen(title).c_str(), kStyle, CW_USEDEFAULT, CW_USEDEFAULT, 400, 300,
                               nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
        if (!hwnd) { view = nullptr; err = "fenêtre impossible à créer"; return false; }
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)this);
        view->setFrame(this);
        Steinberg::ViewRect r;
        if (view->getSize(&r) != kResultOk || r.getWidth() <= 0) r = Steinberg::ViewRect(0, 0, 400, 300);
        place(r.getWidth(), r.getHeight(), true);
        if (view->attached(hwnd, Steinberg::kPlatformTypeHWND) != kResultOk) { close(); err = "le plugin refuse d'ouvrir son éditeur"; return false; }
        ShowWindow(hwnd, SW_SHOWNORMAL);
        SetForegroundWindow(hwnd);
        return true;
    }
    void close() {
        if (view) { view->removed(); view->setFrame(nullptr); view = nullptr; }
        if (hwnd) { SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0); DestroyWindow(hwnd); hwnd = nullptr; }
        closed = true;
    }

private:
    static const DWORD kStyle = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    void place(int w, int h, bool center) {
        width = w; height = h;
        RECT wr{0, 0, w, h};
        AdjustWindowRectEx(&wr, kStyle, FALSE, 0);
        UINT fl = SWP_NOZORDER | SWP_NOACTIVATE | (center ? 0 : SWP_NOMOVE);
        int x = (GetSystemMetrics(SM_CXSCREEN) - (wr.right - wr.left)) / 2, y = (GetSystemMetrics(SM_CYSCREEN) - (wr.bottom - wr.top)) / 3;
        SetWindowPos(hwnd, nullptr, x, y, wr.right - wr.left, wr.bottom - wr.top, fl);
    }
    static LRESULT CALLBACK proc(HWND h, UINT msg, WPARAM wp, LPARAM lp) {
        auto* ed = (Vst3Editor*)GetWindowLongPtrW(h, GWLP_USERDATA);
        if (msg == WM_CLOSE && ed) { ed->close(); return 0; }       // fermée par l'utilisateur : la vue est rendue au plugin
        return DefWindowProcW(h, msg, wp, lp);
    }
};

// ---------------------------------------------------------------- instance
class Vst3Instance : public sv::IComponentHandler {
public:
    std::string path, uid, name, error;
    bool instrument = false, offline = false, active = false;
    double sr = 0; int block = 0;
    int latency = 0; double tail_s = 0;
    std::string state_sig;                     // dernier état appliqué ou capturé (évite de réappliquer le sien)
    std::atomic<bool> latency_changed{false};
    std::atomic<uint64_t> edits{0};            // modifications venues de l'éditeur du plugin

    ~Vst3Instance() { unload(); }

    // FUnknown : durée de vie gérée par shared_ptr (le plugin ne la possède jamais)
    tresult PLUGIN_API queryInterface(const Steinberg::TUID iid, void** obj) override {
        if (Steinberg::FUnknownPrivate::iidEqual(iid, sv::IComponentHandler::iid) || Steinberg::FUnknownPrivate::iidEqual(iid, Steinberg::FUnknown::iid)) {
            *obj = static_cast<sv::IComponentHandler*>(this); return kResultOk; }
        *obj = nullptr; return Steinberg::kNoInterface;
    }
    Steinberg::uint32 PLUGIN_API addRef() override { return 1; }
    Steinberg::uint32 PLUGIN_API release() override { return 1; }
    // IComponentHandler (éditeur du plugin -> paramètres livrés au processeur)
    tresult PLUGIN_API beginEdit(sv::ParamID) override { return kResultOk; }
    tresult PLUGIN_API performEdit(sv::ParamID id, sv::ParamValue v) override { queue(id, v); edits++; return kResultOk; }
    tresult PLUGIN_API endEdit(sv::ParamID) override { return kResultOk; }
    tresult PLUGIN_API restartComponent(Steinberg::int32 flags) override {
        if (flags & sv::kLatencyChanged) latency_changed = true;
        return kResultOk;
    }

    // Chargement complet (HORS temps réel). Retourne un message vide si tout va bien.
    std::string load(const std::string& path_, const std::string& uid_, double sr_, int block_, bool offline_) {
        path = path_; uid = uid_; sr = sr_; block = std::max(16, block_); offline = offline_;
        vst3_host_context();
        std::string err;
        mod_ = vst3_module(path, err);
        if (!mod_) return "module illisible : " + path + (err.empty() ? "" : " (" + err + ")");
        auto id = VST3::UID::fromString(uid);
        if (!id) return "identifiant de classe invalide : " + uid;
        const auto& f = mod_->getFactory();
        for (auto& ci : f.classInfos())
            if (ci.ID() == *id) { name = ci.name(); instrument = ci.subCategoriesString().find("Instrument") != std::string::npos; }
        if (name.empty()) return "classe " + uid + " absente du module " + path;
        comp_ = f.createInstance<sv::IComponent>(*id);
        if (!comp_) return "instanciation refusée : " + name;
        if (comp_->initialize(vst3_host_context()) != kResultOk) { comp_ = nullptr; return "initialisation refusée : " + name; }
        proc_ = Steinberg::U::cast<sv::IAudioProcessor>(comp_);
        if (!proc_) return "pas de processeur audio : " + name;
        ctrl_ = Steinberg::U::cast<sv::IEditController>(comp_);
        if (!ctrl_) {
            Steinberg::TUID cid;
            if (comp_->getControllerClassId(cid) == kResultOk) {
                ctrl_ = f.createInstance<sv::IEditController>(VST3::UID(cid));
                if (ctrl_ && ctrl_->initialize(vst3_host_context()) != kResultOk) ctrl_ = nullptr;
                separate_ctrl_ = ctrl_ != nullptr;
            }
        }
        if (ctrl_) {
            ctrl_->setComponentHandler(this);
            if (separate_ctrl_) {
                auto cp1 = Steinberg::U::cast<sv::IConnectionPoint>(comp_), cp2 = Steinberg::U::cast<sv::IConnectionPoint>(ctrl_);
                if (cp1 && cp2) {
                    conn_c_ = Steinberg::owned(new sv::ConnectionProxy(cp1)); conn_e_ = Steinberg::owned(new sv::ConnectionProxy(cp2));
                    conn_c_->connect(cp2); conn_e_->connect(cp1);
                }
            }
        }
        // bus : entrée principale stéréo (effet), sortie stéréo
        Steinberg::int32 nai = comp_->getBusCount(sv::kAudio, sv::kInput), nao = comp_->getBusCount(sv::kAudio, sv::kOutput);
        if (nao < 1) return "aucune sortie audio : " + name;
        std::vector<sv::SpeakerArrangement> ins(nai, sv::SpeakerArr::kStereo), outs(nao, sv::SpeakerArr::kStereo);
        proc_->setBusArrangements(ins.data(), nai, outs.data(), nao);
        for (Steinberg::int32 i = 0; i < nai; ++i) comp_->activateBus(sv::kAudio, sv::kInput, i, i == 0);
        for (Steinberg::int32 i = 0; i < nao; ++i) comp_->activateBus(sv::kAudio, sv::kOutput, i, i == 0);
        if (comp_->getBusCount(sv::kEvent, sv::kInput) > 0) { comp_->activateBus(sv::kEvent, sv::kInput, 0, true); instrument = instrument || nai == 0; }
        if (proc_->canProcessSampleSize(sv::kSample32) != kResultTrue) return "32 bits flottants refusés : " + name;
        sv::ProcessSetup ps{offline ? sv::kOffline : sv::kRealtime, sv::kSample32, block, sr};
        if (proc_->setupProcessing(ps) != kResultOk) return "configuration refusée : " + name;
        // paramètres
        if (ctrl_) {
            Steinberg::int32 n = ctrl_->getParameterCount();
            ids_.resize(n); pending_.reset(new std::atomic<double>[std::max(1, n)]); dirty_.reset(new std::atomic<bool>[std::max(1, n)]);
            for (Steinberg::int32 i = 0; i < n; ++i) {
                sv::ParameterInfo pi{}; ctrl_->getParameterInfo(i, pi);
                ids_[i] = pi.id; index_[pi.id] = i; pending_[i] = 0; dirty_[i] = false;
            }
            changes_.setMaxParameters(std::max(1, n));
        }
        // tampons : préalloués ici, jamais dans le callback
        pd_.prepare(*comp_, 0, sv::kSample32);
        for (auto& b : scratch_) b.assign((size_t)block, 0.f);
        zeros_.assign((size_t)block, 0.f);
        events_.setMaxSize(512);
        pd_.inputParameterChanges = &changes_;
        pd_.outputParameterChanges = &out_changes_;
        out_changes_.setMaxParameters(64);
        pd_.inputEvents = &events_;
        ctx_.sampleRate = sr; ctx_.tempo = 120; ctx_.state = sv::ProcessContext::kTempoValid;
        pd_.processContext = &ctx_;
        pd_.symbolicSampleSize = sv::kSample32;
        pd_.processMode = offline ? sv::kOffline : sv::kRealtime;
        if (comp_->setActive(true) != kResultOk) return "activation refusée : " + name;
        active = true;
        latency = (int)proc_->getLatencySamples();
        Steinberg::uint32 t = proc_->getTailSamples();
        tail_s = t == sv::kInfiniteTail ? 10.0 : std::min(10.0, t / sr);
        proc_->setProcessing(true);
        return std::string();
    }

    // ---- éditeur (fenêtre du moteur, fil d'interface)
    std::string open_editor(int& w, int& h) {
        if (!ctrl_) return "ce plugin n'a pas de contrôleur";
        std::string err;
        Vst3UiThread::get().run([&] {
            if (editor_ && !editor_->closed) { SetForegroundWindow(editor_->hwnd); }
            else {
                editor_.reset(new Vst3Editor());
                if (!editor_->open(ctrl_.get(), name, err)) editor_.reset();
            }
            if (editor_) { w = editor_->width; h = editor_->height; }
        });
        return err;
    }
    void close_editor() {
        Vst3UiThread::get().run([&] { if (editor_) { editor_->close(); editor_.reset(); } });
    }
    bool editor_open() {
        bool r = false;
        Vst3UiThread::get().run([&] { r = editor_ && !editor_->closed; });
        return r;
    }

    void unload() {
        if (editor_) close_editor();                 // la vue est rendue AVANT de terminer le plugin
        if (proc_ && active) proc_->setProcessing(false);
        if (comp_ && active) comp_->setActive(false);
        active = false;
        pd_.unprepare();
        if (conn_c_) { conn_c_->disconnect(); conn_c_ = nullptr; }
        if (conn_e_) { conn_e_->disconnect(); conn_e_ = nullptr; }
        if (ctrl_) { ctrl_->setComponentHandler(nullptr); if (separate_ctrl_) ctrl_->terminate(); ctrl_ = nullptr; }
        proc_ = nullptr;
        if (comp_) { comp_->terminate(); comp_ = nullptr; }
    }

    // ---- état (HORS temps réel)
    std::string get_state() {
        if (!comp_) return std::string();
        IPtr<Steinberg::MemoryStream> ms = Steinberg::owned(new Steinberg::MemoryStream());
        if (comp_->getState(ms) != kResultOk) return std::string();
        std::string s = b64_encode(ms->getData(), (size_t)ms->getSize());
        state_sig = s;
        return s;
    }
    std::string set_state(const std::string& b64) {
        if (!comp_ || b64.empty() || b64 == state_sig) return std::string();
        std::string raw = b64_decode(b64);
        IPtr<Steinberg::MemoryStream> ms = Steinberg::owned(new Steinberg::MemoryStream((void*)raw.data(), (Steinberg::TSize)raw.size()));
        if (comp_->setState(ms) != kResultOk) return "état refusé par " + name;
        if (ctrl_) {
            Steinberg::int64 pos = 0; ms->seek(0, Steinberg::IBStream::kIBSeekSet, &pos);
            ctrl_->setComponentState(ms);
        }
        state_sig = b64;
        return std::string();
    }

    // ---- paramètres (n'importe quel fil ; aucune allocation)
    void queue(sv::ParamID id, double v) {
        auto it = index_.find(id);
        if (it == index_.end()) return;
        pending_[it->second].store(std::clamp(v, 0.0, 1.0), std::memory_order_relaxed);
        dirty_[it->second].store(true, std::memory_order_release);
        any_dirty_.store(true, std::memory_order_release);
    }
    void set_key(const char* key, double v) {
        if (key[0] != 'p' || !isdigit((unsigned char)key[1])) return;
        queue((sv::ParamID)strtoul(key + 1, nullptr, 10), v);
    }
    Json params_json() const {
        Json a = Json::array();
        if (!ctrl_) return a;
        for (size_t i = 0; i < ids_.size(); ++i) {
            sv::ParameterInfo pi{}; ctrl_->getParameterInfo((Steinberg::int32)i, pi);
            Json p = Json::object();
            p.set("id", Json::num(pi.id)); p.set("key", Json::str("p" + std::to_string(pi.id)));
            p.set("title", Json::str(VST3::StringConvert::convert(pi.title))); p.set("units", Json::str(VST3::StringConvert::convert(pi.units)));
            p.set("default", Json::num(pi.defaultNormalizedValue)); p.set("value", Json::num(ctrl_->getParamNormalized(pi.id)));
            p.set("steps", Json::num(pi.stepCount)); p.set("automatable", Json::boolean((pi.flags & sv::ParameterInfo::kCanAutomate) != 0));
            a.push(std::move(p));
        }
        return a;
    }

    // ---- événements (fil audio)
    void note(int pitch, int vel, bool on) {
        sv::Event e{};
        e.busIndex = 0; e.sampleOffset = 0; e.flags = sv::Event::kIsLive;
        if (on) { e.type = sv::Event::kNoteOnEvent; e.noteOn.pitch = (Steinberg::int16)pitch; e.noteOn.velocity = vel / 127.f; e.noteOn.noteId = -1; held_[pitch] = true; }
        else { e.type = sv::Event::kNoteOffEvent; e.noteOff.pitch = (Steinberg::int16)pitch; e.noteOff.velocity = 0.f; e.noteOff.noteId = -1; held_[pitch] = false; }
        events_.addEvent(e);
    }
    void all_notes_off() { for (int p = 0; p < 128; ++p) if (held_[p]) note(p, 0, false); }

    // ---- traitement (fil audio). in : 2 canaux ou nullptr ; out : 2 canaux ; add : ajoute au lieu d'écrire.
    void process(const float* const* in, const float* const* sc, float* const* out, int n, bool add) {
        if (!active) return;
        for (int off = 0; off < n; off += block) {
            int m = std::min(block, n - off);
            if (any_dirty_.exchange(false, std::memory_order_acquire)) {
                changes_.clearQueue();
                for (size_t i = 0; i < ids_.size(); ++i)
                    if (dirty_[i].exchange(false, std::memory_order_acquire)) {
                        Steinberg::int32 qi = 0, pi = 0;
                        if (auto* q = changes_.addParameterData(ids_[i], qi)) q->addPoint(0, pending_[i].load(std::memory_order_relaxed), pi);
                    }
            }
            for (int b = 0; b < pd_.numInputs; ++b) {
                auto& bus = pd_.inputs[b];
                for (Steinberg::int32 c = 0; c < bus.numChannels; ++c) {
                    const float* src = b == 0 ? (in ? in[std::min<int>(c, 1)] + off : zeros_.data())
                                              : (sc ? sc[std::min<int>(c, 1)] + off : zeros_.data());
                    bus.channelBuffers32[c] = const_cast<float*>(src);
                }
                bus.silenceFlags = 0;
            }
            for (int b = 0; b < pd_.numOutputs; ++b) {
                auto& bus = pd_.outputs[b];
                for (Steinberg::int32 c = 0; c < bus.numChannels; ++c) bus.channelBuffers32[c] = scratch_[b == 0 ? std::min<int>(c, 1) : 2].data();
            }
            pd_.numSamples = m;
            ctx_.projectTimeSamples = pos_;
            out_changes_.clearQueue();
            proc_->process(pd_);
            if (off + m >= n || true) { events_.clear(); changes_.clearQueue(); }
            pos_ += m;
            int oc = pd_.numOutputs > 0 ? pd_.outputs[0].numChannels : 0;
            const float* L = scratch_[0].data();
            const float* R = oc > 1 ? scratch_[1].data() : L;
            if (add) for (int i = 0; i < m; ++i) { out[0][off + i] += L[i]; out[1][off + i] += R[i]; }
            else for (int i = 0; i < m; ++i) { out[0][off + i] = L[i]; out[1][off + i] = R[i]; }
        }
    }

    sv::IEditController* controller() const { return ctrl_.get(); }

private:
    VST3::Hosting::Module::Ptr mod_;
    IPtr<sv::IComponent> comp_;
    IPtr<sv::IAudioProcessor> proc_;
    IPtr<sv::IEditController> ctrl_;
    IPtr<sv::ConnectionProxy> conn_c_, conn_e_;
    bool separate_ctrl_ = false;
    std::unique_ptr<Vst3Editor> editor_;
    sv::HostProcessData pd_;
    sv::ParameterChanges changes_, out_changes_;
    sv::EventList events_;
    sv::ProcessContext ctx_{};
    std::vector<float> scratch_[3], zeros_;
    std::vector<sv::ParamID> ids_;
    std::unordered_map<sv::ParamID, int> index_;
    std::unique_ptr<std::atomic<double>[]> pending_;
    std::unique_ptr<std::atomic<bool>[]> dirty_;
    std::atomic<bool> any_dirty_{false};
    bool held_[128] = {};
    int64_t pos_ = 0;
};

// ---------------------------------------------------------------- pool temps réel
class Vst3Pool {
public:
    std::shared_ptr<Vst3Instance> get(const std::string& key, const std::string& path, const std::string& uid, double sr, int block, std::string& err) {
        std::lock_guard<std::mutex> lk(m_);
        used_.insert(key);
        auto it = live_.find(key);
        if (it != live_.end() && it->second->path == path && it->second->uid == uid && it->second->sr == sr && it->second->block == block)
            return it->second;
        auto inst = std::make_shared<Vst3Instance>();
        err = inst->load(path, uid, sr, block, false);
        if (!err.empty()) { live_.erase(key); return nullptr; }
        live_[key] = inst;
        return inst;
    }
    std::shared_ptr<Vst3Instance> find(const std::string& key) {
        std::lock_guard<std::mutex> lk(m_);
        auto it = live_.find(key);
        return it == live_.end() ? nullptr : it->second;
    }
    void begin_build() { std::lock_guard<std::mutex> lk(m_); used_.clear(); }
    // Les instances absentes du dernier graphe quittent le pool (l'ancien graphe les garde jusqu'à sa destruction).
    void end_build() {
        std::lock_guard<std::mutex> lk(m_);
        for (auto it = live_.begin(); it != live_.end();) it = used_.count(it->first) ? std::next(it) : live_.erase(it);
    }
    bool any_latency_changed() {
        std::lock_guard<std::mutex> lk(m_);
        bool r = false;
        for (auto& kv : live_) r = kv.second->latency_changed.exchange(false) || r;
        return r;
    }
private:
    std::mutex m_;
    std::map<std::string, std::shared_ptr<Vst3Instance>> live_;
    std::set<std::string> used_;
};

inline std::shared_ptr<Vst3Instance> vst3_acquire(Vst3Pool* pool, const std::string& key, const Json& spec, const std::string& uid,
                                                  double sr, int block, std::string& err) {
    std::string path = spec.gets("path");
    if (path.empty()) { err = "chemin du module absent"; return nullptr; }
    std::shared_ptr<Vst3Instance> inst;
    if (pool) inst = pool->get(key, path, uid, sr, block, err);
    else {
        inst = std::make_shared<Vst3Instance>();
        err = inst->load(path, uid, sr, block, true);
        if (!err.empty()) return nullptr;
    }
    if (inst) {
        std::string st = spec.gets("state");
        if (!st.empty()) { std::string e = inst->set_state(st); if (!e.empty()) err = e; }
    }
    return inst;
}

// ---------------------------------------------------------------- effet et instrument du graphe
class Vst3Fx : public Effect {
public:
    explicit Vst3Fx(std::shared_ptr<Vst3Instance> i) : inst(std::move(i)) { wants_sidechain = true; }
    void prepare(double, int) override {}
    void process(float* const* x, int n, float* const* sc) override {
        const float* in[2] = {x[0], x[1]};
        const float* s2[2] = {sc ? sc[0] : nullptr, sc ? sc[1] : nullptr};
        inst->process(in, sc ? s2 : nullptr, x, n, false);
    }
    void set(const char* key, double v) override { inst->set_key(key, v); }
    int latency() const override { return inst->latency; }
    double tail_seconds() const override { return inst->tail_s; }
    std::shared_ptr<Vst3Instance> inst;
};

class Vst3Instrument : public Instrument {
public:
    explicit Vst3Instrument(std::shared_ptr<Vst3Instance> i) : inst(std::move(i)) {}
    void prepare(double) override {}
    void note_on(int pitch, int vel) override { inst->note(pitch, vel, true); }
    void note_off(int pitch) override { inst->note(pitch, 0, false); }
    void all_notes_off(bool) override { inst->all_notes_off(); }
    void render(float* l, float* r, int n) override { float* o[2] = {l, r}; inst->process(nullptr, nullptr, o, n, true); }
    void set(const char* key, double v) override { inst->set_key(key, v); }
    int active_voices() const override { return 0; }
    double tail_seconds() const override { return std::max(0.5, inst->tail_s); }
    std::shared_ptr<Vst3Instance> inst;
};

// ---------------------------------------------------------------- scan (processus isolé : --scan-vst3)
// Lit les classes du module et instancie chaque classe audio pour en lire bus, paramètres et latence.
// Un plugin qui plante ou se bloque tue CE processus seulement : l'appelant (plugins.py) met le module
// en quarantaine.
inline Json vst3_scan(const std::string& path) {
    Json r = Json::object();
    r.set("path", Json::str(path));
    std::string err;
    auto mod = vst3_module(path, err);
    if (!mod) { r.set("error", Json::str("module illisible" + (err.empty() ? std::string() : " : " + err))); return r; }
    Json classes = Json::array();
    const auto& f = mod->getFactory();
    r.set("vendor", Json::str(f.info().vendor()));
    for (auto& ci : f.classInfos()) {
        if (ci.category() != kVstAudioEffectClass) continue;
        Json c = Json::object();
        c.set("uid", Json::str(ci.ID().toString())); c.set("name", Json::str(ci.name()));
        c.set("sub", Json::str(ci.subCategoriesString())); c.set("vendor", Json::str(ci.vendor())); c.set("version", Json::str(ci.version()));
        Vst3Instance inst;
        std::string e = inst.load(path, ci.ID().toString(), 48000, 512, true);
        c.set("instrument", Json::boolean(inst.instrument));
        if (!e.empty()) c.set("error", Json::str(e));
        else { c.set("latency", Json::num(inst.latency)); c.set("params", Json::num((double)inst.params_json().a.size())); }
        classes.push(std::move(c));
    }
    r.set("classes", classes);
    return r;
}

}  // namespace fmz
#endif  // FMZ_VST3
