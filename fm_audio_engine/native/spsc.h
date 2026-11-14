// fmz_audio_engine : file SPSC bornée sans verrou (un producteur, un consommateur).
// Capacité fixée à la construction (allocation hors temps réel) ; push/pop sans attente.
// Saturation : push retourne false (l'appelant compte et signale).
#pragma once
#include <atomic>
#include <cstddef>
#include <vector>

namespace fmz {

template <class T> class SpscQueue {
public:
    explicit SpscQueue(size_t capacity) : buf_(capacity + 1), cap_(capacity + 1) {}
    bool push(const T& v) {
        size_t w = w_.load(std::memory_order_relaxed), n = (w + 1) % cap_;
        if (n == r_.load(std::memory_order_acquire)) return false;
        buf_[w] = v;
        w_.store(n, std::memory_order_release);
        return true;
    }
    bool pop(T& v) {
        size_t r = r_.load(std::memory_order_relaxed);
        if (r == w_.load(std::memory_order_acquire)) return false;
        v = buf_[r];
        r_.store((r + 1) % cap_, std::memory_order_release);
        return true;
    }
private:
    std::vector<T> buf_;
    size_t cap_;
    alignas(64) std::atomic<size_t> w_{0};
    alignas(64) std::atomic<size_t> r_{0};
};

}  // namespace fmz
