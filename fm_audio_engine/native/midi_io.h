// fmz_audio_engine : MIDI entrant / sortant réel (winmm). Les rappels du pilote MIDI (fil système)
// déposent les événements dans une file bornée lue par le callback audio (aucune attente côté
// temps réel) ; la sortie MIDI passe par un fil dédié (midiOutShortMsg n'est jamais appelé depuis
// le callback audio). Périphérique débranché : signalé (MIM_CLOSE / erreur), toutes notes coupées.
#pragma once
#include <mutex>
#include <thread>
#include "json.h"
#include "spsc.h"
#include "wasapi.h"

#include <mmsystem.h>

namespace fmz {

struct MidiEvent { uint8_t status, d1, d2; };

class MidiIO {
public:
    SpscQueue<MidiEvent> in_q{4096};
    std::atomic<uint64_t> in_overflow{0}, in_count{0};
    std::atomic<bool> lost{false};

    static Json devices() {
        Json j = Json::object(), ins = Json::array(), outs = Json::array();
        UINT ni = midiInGetNumDevs(), no = midiOutGetNumDevs();
        for (UINT i = 0; i < ni; ++i) {
            MIDIINCAPSW c{}; if (midiInGetDevCapsW(i, &c, sizeof c) != MMSYSERR_NOERROR) continue;
            Json d = Json::object(); d.set("index", Json::num(i)); d.set("name", Json::str(narrow(c.szPname))); ins.push(d);
        }
        for (UINT i = 0; i < no; ++i) {
            MIDIOUTCAPSW c{}; if (midiOutGetDevCapsW(i, &c, sizeof c) != MMSYSERR_NOERROR) continue;
            Json d = Json::object(); d.set("index", Json::num(i)); d.set("name", Json::str(narrow(c.szPname))); outs.push(d);
        }
        j.set("inputs", ins); j.set("outputs", outs);
        return j;
    }

    std::string open_input(int index) {
        HMIDIIN h = nullptr;
        MMRESULT r = midiInOpen(&h, (UINT)index, (DWORD_PTR)&MidiIO::in_proc, (DWORD_PTR)this, CALLBACK_FUNCTION);
        if (r != MMSYSERR_NOERROR) return "entrée MIDI " + std::to_string(index) + " : ouverture impossible (code " + std::to_string(r) + ", occupée ou absente)";
        midiInStart(h);
        ins_.push_back(h);
        return std::string();
    }

    std::string open_output(int index) {
        close_output();
        MMRESULT r = midiOutOpen(&out_, (UINT)index, 0, 0, CALLBACK_NULL);
        if (r != MMSYSERR_NOERROR) { out_ = nullptr; return "sortie MIDI " + std::to_string(index) + " : ouverture impossible (code " + std::to_string(r) + ")"; }
        out_run_ = true;
        out_th_ = std::thread([this] { out_loop(); });
        return std::string();
    }

    // Événement vers la sortie MIDI : depuis le callback audio (file bornée, sans attente).
    bool send(const MidiEvent& e) { if (!out_) return false; if (!out_q_.push(e)) { out_overflow++; return false; } return true; }
    // Injection d'un événement d'entrée (double de test, même chemin que le pilote).
    void inject(const MidiEvent& e) { std::lock_guard<std::mutex> lk(prod_mx_); if (!in_q.push(e)) in_overflow++; else in_count++; }

    void close_all() {
        for (auto h : ins_) { midiInStop(h); midiInReset(h); midiInClose(h); }
        ins_.clear();
        close_output();
    }
    ~MidiIO() { close_all(); }
    std::atomic<uint64_t> out_overflow{0};

private:
    std::vector<HMIDIIN> ins_;
    HMIDIOUT out_ = nullptr;
    SpscQueue<MidiEvent> out_q_{4096};
    std::thread out_th_;
    std::atomic<bool> out_run_{false};
    std::mutex prod_mx_;          // plusieurs entrées : rappels sérialisés côté producteur (hors temps réel)

    void close_output() {
        out_run_ = false;
        if (out_th_.joinable()) out_th_.join();
        if (out_) {
            for (int ch = 0; ch < 16; ++ch) midiOutShortMsg(out_, (DWORD)(0xB0 | ch) | (123 << 8));   // all notes off
            midiOutReset(out_); midiOutClose(out_); out_ = nullptr;
        }
    }
    void out_loop() {
        while (out_run_) {
            MidiEvent e;
            bool any = false;
            while (out_q_.pop(e)) { midiOutShortMsg(out_, (DWORD)e.status | ((DWORD)e.d1 << 8) | ((DWORD)e.d2 << 16)); any = true; }
            if (!any) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    }
    static void CALLBACK in_proc(HMIDIIN, UINT msg, DWORD_PTR inst, DWORD_PTR p1, DWORD_PTR) {
        auto* self = (MidiIO*)inst;
        if (msg == MIM_DATA) {
            MidiEvent e{(uint8_t)(p1 & 0xFF), (uint8_t)((p1 >> 8) & 0x7F), (uint8_t)((p1 >> 16) & 0x7F)};
            if ((e.status & 0xF0) == 0xF0) return;   // horloge / sysex temps réel ignorés ici
            self->inject(e);
        } else if (msg == MIM_CLOSE) {
            self->lost = true;
        }
    }
};

}  // namespace fmz
