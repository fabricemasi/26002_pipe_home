// Plugins VST3 DE TEST du moteur FM Audio / FM Music, compilés depuis le SDK VST3 3.8.1 (MIT) par
// fm_audio_engine/build.py (build_test_plugins). Ils servent aux tests automatiques de l'hôte, jamais à
// l'utilisateur. Résultats CONNUS d'avance :
// - « FMZ Test Gain » (effet, avec un éditeur minimal) : sortie = entrée retardée de 64 échantillons × (2 × Gain normalisé), latence
//   déclarée 64 ; état = valeur du Gain (+ signature) ;
// - « FMZ Test Synth » (instrument) : une sinusoïde par note (fréquence de la note, amplitude = vélocité/127
//   × 2 × Level), coupée net au note-off.
// Modules « défectueux » pour la quarantaine du scan : FMZ_BAD_CRASH = « FMZ Test Crash » plante à
// l'initialisation ; FMZ_BAD_HANG = « FMZ Test Hang » s'y bloque.
#include "public.sdk/source/vst/vstsinglecomponenteffect.h"
#include "public.sdk/source/main/pluginfactory.h"
#include "pluginterfaces/vst/ivstparameterchanges.h"
#include "pluginterfaces/vst/ivstevents.h"
#include "pluginterfaces/base/ibstream.h"
#include "base/source/fstreamer.h"
#include "public.sdk/source/common/pluginview.h"
#include <cmath>
#include <cstring>
#include <windows.h>

using namespace Steinberg;
using namespace Steinberg::Vst;

static const int32 kMagic = 0x464D5A31;   // "FMZ1"

static ParamValue last_value(ProcessData& d, ParamID id, ParamValue cur) {
    if (!d.inputParameterChanges) return cur;
    int32 n = d.inputParameterChanges->getParameterCount();
    for (int32 i = 0; i < n; ++i) {
        IParamValueQueue* q = d.inputParameterChanges->getParameterData(i);
        if (!q || q->getParameterId() != id) continue;
        int32 c = q->getPointCount(), off = 0; ParamValue v = cur;
        if (c > 0 && q->getPoint(c - 1, off, v) == kResultOk) cur = v;
    }
    return cur;
}

#if !defined(FMZ_BAD_CRASH) && !defined(FMZ_BAD_HANG)
static const FUID kGainUID(0x464D5A31, 0x4741494E, 0x54455354, 0x00000001);
static const FUID kSynthUID(0x464D5A31, 0x53594E54, 0x54455354, 0x00000002);

// Éditeur minimal (fenêtre Win32 enfant) : sert à tester l'ouverture / fermeture des éditeurs par l'hôte.
class FmzView : public CPluginView {
public:
    FmzView() { ViewRect r(0, 0, 320, 120); setRect(r); }
    tresult PLUGIN_API isPlatformTypeSupported(FIDString t) override { return FIDStringsEqual(t, kPlatformTypeHWND) ? kResultTrue : kResultFalse; }
    void attachedToParent() override {
        child_ = CreateWindowExW(0, L"STATIC", L"FMZ Test Gain : éditeur de test", WS_CHILD | WS_VISIBLE | SS_CENTER,
                                 0, 0, 320, 120, (HWND)systemWindow, nullptr, GetModuleHandleW(nullptr), nullptr);
    }
    void removedFromParent() override { if (child_) { DestroyWindow(child_); child_ = nullptr; } }
private:
    HWND child_ = nullptr;
};

class FmzGain : public SingleComponentEffect {
public:
    IPlugView* PLUGIN_API createView(FIDString name) override {
        return FIDStringsEqual(name, ViewType::kEditor) ? new FmzView() : nullptr;
    }
    static const int kLat = 64;
    static FUnknown* create(void*) { return (IAudioProcessor*)new FmzGain; }
    tresult PLUGIN_API initialize(FUnknown* ctx) override {
        tresult r = SingleComponentEffect::initialize(ctx);
        if (r != kResultOk) return r;
        addAudioInput(STR16("In"), SpeakerArr::kStereo);
        addAudioOutput(STR16("Out"), SpeakerArr::kStereo);
        parameters.addParameter(STR16("Gain"), STR16("x2"), 0, 0.5, ParameterInfo::kCanAutomate, 0);
        return kResultOk;
    }
    tresult PLUGIN_API setBusArrangements(SpeakerArrangement* in, int32 ni, SpeakerArrangement* out, int32 no) override {
        if (ni == 1 && no == 1 && in[0] == SpeakerArr::kStereo && out[0] == SpeakerArr::kStereo)
            return SingleComponentEffect::setBusArrangements(in, ni, out, no);
        return kResultFalse;
    }
    tresult PLUGIN_API canProcessSampleSize(int32 s) override { return s == kSample32 ? kResultTrue : kResultFalse; }
    uint32 PLUGIN_API getLatencySamples() override { return kLat; }
    tresult PLUGIN_API setActive(TBool st) override { memset(dl_, 0, sizeof dl_); w_ = 0; return SingleComponentEffect::setActive(st); }
    tresult PLUGIN_API process(ProcessData& d) override {
        gain_ = last_value(d, 0, gain_);
        if (d.numSamples <= 0 || d.numInputs < 1 || d.numOutputs < 1) return kResultOk;
        float g = (float)(gain_ * 2.0);
        for (int32 i = 0; i < d.numSamples; ++i) {
            for (int c = 0; c < 2; ++c) {
                float x = d.inputs[0].channelBuffers32[c][i];
                float y = dl_[c][w_];
                dl_[c][w_] = x;
                d.outputs[0].channelBuffers32[c][i] = y * g;
            }
            w_ = (w_ + 1) % kLat;
        }
        return kResultOk;
    }
    tresult PLUGIN_API setState(IBStream* s) override {
        IBStreamer st(s, kLittleEndian);
        int32 m = 0; double g = 0.5;
        if (!st.readInt32(m) || m != kMagic || !st.readDouble(g)) return kResultFalse;
        gain_ = g;
        setParamNormalized(0, g);
        return kResultOk;
    }
    tresult PLUGIN_API getState(IBStream* s) override {
        IBStreamer st(s, kLittleEndian);
        st.writeInt32(kMagic); st.writeDouble(gain_);
        return kResultOk;
    }
private:
    double gain_ = 0.5;
    float dl_[2][kLat] = {};
    int w_ = 0;
};

class FmzSynth : public SingleComponentEffect {
public:
    static FUnknown* create(void*) { return (IAudioProcessor*)new FmzSynth; }
    tresult PLUGIN_API initialize(FUnknown* ctx) override {
        tresult r = SingleComponentEffect::initialize(ctx);
        if (r != kResultOk) return r;
        addEventInput(STR16("MIDI"), 16);
        addAudioOutput(STR16("Out"), SpeakerArr::kStereo);
        parameters.addParameter(STR16("Level"), nullptr, 0, 0.5, ParameterInfo::kCanAutomate, 0);
        return kResultOk;
    }
    tresult PLUGIN_API setBusArrangements(SpeakerArrangement* in, int32 ni, SpeakerArrangement* out, int32 no) override {
        if (ni == 0 && no == 1 && out[0] == SpeakerArr::kStereo) return SingleComponentEffect::setBusArrangements(in, ni, out, no);
        return kResultFalse;
    }
    tresult PLUGIN_API canProcessSampleSize(int32 s) override { return s == kSample32 ? kResultTrue : kResultFalse; }
    tresult PLUGIN_API setupProcessing(ProcessSetup& s) override { sr_ = s.sampleRate; return SingleComponentEffect::setupProcessing(s); }
    tresult PLUGIN_API setActive(TBool st) override { for (auto& v : v_) v.on = false; return SingleComponentEffect::setActive(st); }
    tresult PLUGIN_API process(ProcessData& d) override {
        level_ = last_value(d, 0, level_);
        if (d.numOutputs < 1 || d.numSamples <= 0) return kResultOk;
        float* l = d.outputs[0].channelBuffers32[0];
        float* r = d.outputs[0].channelBuffers32[1];
        int32 ne = d.inputEvents ? d.inputEvents->getEventCount() : 0, ei = 0;
        for (int32 i = 0; i < d.numSamples; ++i) {
            Event e;
            while (ei < ne && d.inputEvents->getEvent(ei, e) == kResultOk && e.sampleOffset <= i) {
                if (e.type == Event::kNoteOnEvent && e.noteOn.velocity > 0) start(e.noteOn.pitch, e.noteOn.velocity);
                else if (e.type == Event::kNoteOnEvent || e.type == Event::kNoteOffEvent)
                    stop(e.type == Event::kNoteOnEvent ? e.noteOn.pitch : e.noteOff.pitch);
                ++ei;
            }
            double s = 0;
            for (auto& v : v_) if (v.on) { s += v.amp * std::sin(v.ph); v.ph += v.inc; if (v.ph > 6.283185307179586) v.ph -= 6.283185307179586; }
            float y = (float)(s * level_ * 2.0);
            l[i] = y; r[i] = y;
        }
        d.outputs[0].silenceFlags = 0;
        return kResultOk;
    }
private:
    struct Voice { bool on = false; int pitch = 0; double ph = 0, inc = 0, amp = 0; };
    Voice v_[8];
    double sr_ = 48000, level_ = 0.5;
    void start(int p, float vel) {
        Voice* v = &v_[0];
        for (auto& x : v_) if (!x.on) { v = &x; break; }
        v->on = true; v->pitch = p; v->ph = 0;
        v->inc = 6.283185307179586 * 440.0 * std::pow(2.0, (p - 69) / 12.0) / sr_;
        v->amp = vel;                                   // VST3 : vélocité normalisée 0..1
    }
    void stop(int p) { for (auto& x : v_) if (x.on && x.pitch == p) x.on = false; }
};

BEGIN_FACTORY_DEF("FMZ Test", "", "")
    DEF_CLASS2(INLINE_UID_FROM_FUID(kGainUID), PClassInfo::kManyInstances, kVstAudioEffectClass, "FMZ Test Gain", 0,
               "Fx", "1.0.0", kVstVersionString, FmzGain::create)
    DEF_CLASS2(INLINE_UID_FROM_FUID(kSynthUID), PClassInfo::kManyInstances, kVstAudioEffectClass, "FMZ Test Synth", 0,
               "Instrument|Synth", "1.0.0", kVstVersionString, FmzSynth::create)
END_FACTORY

#elif defined(FMZ_BAD_CRASH)

static const FUID kCrashUID(0x464D5A31, 0x43524153, 0x54455354, 0x00000003);

class FmzCrash : public SingleComponentEffect {
public:
    static FUnknown* create(void*) { return (IAudioProcessor*)new FmzCrash; }
    tresult PLUGIN_API initialize(FUnknown*) override {
        volatile int* p = nullptr;
        *p = 1;                                         // violation d'accès VOULUE
        return kResultOk;
    }
};

BEGIN_FACTORY_DEF("FMZ Test", "", "")
    DEF_CLASS2(INLINE_UID_FROM_FUID(kCrashUID), PClassInfo::kManyInstances, kVstAudioEffectClass, "FMZ Test Crash", 0,
               "Fx", "1.0.0", kVstVersionString, FmzCrash::create)
END_FACTORY

#else   // FMZ_BAD_HANG

static const FUID kHangUID(0x464D5A31, 0x48414E47, 0x54455354, 0x00000004);

class FmzHang : public SingleComponentEffect {
public:
    static FUnknown* create(void*) { return (IAudioProcessor*)new FmzHang; }
    tresult PLUGIN_API initialize(FUnknown*) override { Sleep(120000); return kResultFalse; }   // blocage VOULU
};

BEGIN_FACTORY_DEF("FMZ Test", "", "")
    DEF_CLASS2(INLINE_UID_FROM_FUID(kHangUID), PClassInfo::kManyInstances, kVstAudioEffectClass, "FMZ Test Hang", 0,
               "Fx", "1.0.0", kVstVersionString, FmzHang::create)
END_FACTORY

#endif
