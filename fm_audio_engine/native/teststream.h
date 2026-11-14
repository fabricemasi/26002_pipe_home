// fmz_audio_engine : PÉRIPHÉRIQUE DE TEST DÉCLARÉ (double de test, jamais présenté comme un vrai
// matériel). Horloge simulée (temps réel ou accélérée), entrées synthétiques déterministes,
// sortie écrite dans un WAV, bouclage simulé sortie -> entrée avec un retard connu.
// Sert à tester capture, punch, boucles, métronome et mesure de latence sans matériel ;
// une validation sur ce périphérique ne valide NI ASIO NI la latence d'un vrai matériel.
#pragma once
#include <chrono>
#include <thread>
#include "wasapi.h"

namespace fmz {

class TestStream : public AudioStream {
public:
    bool fast = true;              // false : rythme temps réel (sleep)
    int loop_delay = -1;           // >= 0 : entrée 0 = sortie gauche retardée de N échantillons
    int64_t max_frames = -1;       // arrêt automatique (sécurité des tests)
    std::string out_path;          // sortie écrite ici (WAV float) si non vide
    std::atomic<bool> hold{false}; // horloge figée jusqu'à la première lecture (sorties déterministes)

    bool open(int sr, int block, int in_ch, Callback cb) {
        cb_ = std::move(cb);
        backend = "test";
        sample_rate = sr; buffer_frames = block; out_channels = 2; in_channels = in_ch;
        out_latency_ms = 1000.0 * block / sr; in_latency_ms = 1000.0 * block / sr;
        out_.assign((size_t)block * 2, 0.f);
        for (int c = 0; c < in_ch && c < 8; ++c) in_[c].assign(block, 0.f);
        if (loop_delay >= 0) { ring_.assign((size_t)loop_delay + block + 1, 0.f); }
        if (!out_path.empty()) {
            try { writer_.open(out_path, sr, 2, WavWriter::F32, false, true); writing_ = true; }
            catch (const std::exception& e) { error = e.what(); return false; }
        }
        return true;
    }
    bool start() override { running_ = true; th_ = std::thread([this] { loop(); }); return true; }
    void stop() override {
        running_ = false;
        if (th_.joinable()) th_.join();
        if (writing_) { try { writer_.close(); } catch (...) {} writing_ = false; }
    }
    ~TestStream() override { stop(); }
    int64_t frames() const { return frame_.load(); }

private:
    Callback cb_;
    std::thread th_;
    std::atomic<bool> running_{false};
    std::atomic<int64_t> frame_{0};
    std::vector<float> out_, in_[8], ring_;
    int64_t ring_w_ = 0;
    WavWriter writer_;
    bool writing_ = false;

    void loop() {
        const int n = buffer_frames;
        const float* inp[8];
        auto next = std::chrono::steady_clock::now();
        std::vector<float> l(n), r(n);
        while (running_) {
            if (hold.load()) { std::this_thread::sleep_for(std::chrono::milliseconds(1)); next = std::chrono::steady_clock::now(); continue; }
            int64_t f0 = frame_.load();
            if (max_frames >= 0 && f0 >= max_frames) break;
            for (int c = 0; c < in_channels && c < 8; ++c) {
                for (int i = 0; i < n; ++i) {
                    int64_t k = f0 + i;
                    float v;
                    if (c == 0 && loop_delay >= 0) {
                        int64_t rd = ring_w_ + i - loop_delay;
                        v = rd >= 0 ? ring_[(size_t)(rd % (int64_t)ring_.size())] : 0.f;
                    } else if (c == 0) v = (float)(0.5 * std::sin(2 * kPi * 440.0 * (double)k / sample_rate));
                    else v = (k % (sample_rate / 2) == 0) ? 0.8f : 0.f;   // impulsion toutes les 0,5 s
                    in_[c][i] = v;
                }
                inp[c] = in_[c].data();
            }
            cb_(out_.data(), 2, n, in_channels ? inp : nullptr, in_channels);
            for (int i = 0; i < n; ++i) { l[i] = out_[i * 2]; r[i] = out_[i * 2 + 1]; }
            if (loop_delay >= 0) {
                // la sortie est écrite APRÈS la lecture de l'entrée du même bloc : retard total = loop_delay
                for (int i = 0; i < n; ++i) ring_[(size_t)((ring_w_ + i) % (int64_t)ring_.size())] = l[i];
                ring_w_ += n;
            }
            if (writing_) { const float* ch[2] = {l.data(), r.data()}; try { writer_.write(ch, n); } catch (...) { writing_ = false; } }
            frame_ += n;
            if (!fast) {
                next += std::chrono::nanoseconds((int64_t)(1e9 * n / sample_rate));
                std::this_thread::sleep_until(next);
            }
        }
    }
};

}  // namespace fmz
