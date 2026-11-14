// fmz_audio_engine : JSON minimal (lecture / écriture), sans dépendance.
// Utilisé UNIQUEMENT hors temps réel : construction du graphe, protocole IPC.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace fmz {

struct Json {
    enum Type { Null, Bool, Number, String, Array, Object };
    Type type = Null;
    bool b = false;
    double n = 0.0;
    std::string s;
    std::vector<Json> a;
    std::map<std::string, Json> o;

    Json() = default;
    static Json num(double v) { Json j; j.type = Number; j.n = v; return j; }
    static Json str(const std::string& v) { Json j; j.type = String; j.s = v; return j; }
    static Json boolean(bool v) { Json j; j.type = Bool; j.b = v; return j; }
    static Json array() { Json j; j.type = Array; return j; }
    static Json object() { Json j; j.type = Object; return j; }

    bool has(const std::string& k) const { return type == Object && o.count(k) > 0; }
    const Json& operator[](const std::string& k) const {
        static const Json none;
        if (type != Object) return none;
        auto it = o.find(k);
        return it == o.end() ? none : it->second;
    }
    Json& set(const std::string& k, Json v) { type = Object; o[k] = std::move(v); return o[k]; }
    void push(Json v) { type = Array; a.push_back(std::move(v)); }

    double num_or(double d) const { return type == Number ? n : (type == Bool ? (b ? 1.0 : 0.0) : d); }
    int64_t int_or(int64_t d) const { return type == Number ? (int64_t)(n < 0 ? n - 0.5 : n + 0.5) : d; }
    bool bool_or(bool d) const { return type == Bool ? b : (type == Number ? n != 0.0 : d); }
    std::string str_or(const std::string& d) const { return type == String ? s : d; }
    double get(const std::string& k, double d) const { return (*this)[k].num_or(d); }
    int64_t geti(const std::string& k, int64_t d) const { return (*this)[k].int_or(d); }
    bool getb(const std::string& k, bool d) const { return (*this)[k].bool_or(d); }
    std::string gets(const std::string& k, const std::string& d = "") const { return (*this)[k].str_or(d); }
};

class JsonParser {
public:
    explicit JsonParser(const std::string& t) : t_(t) {}
    Json parse() {
        Json v = value();
        ws();
        if (p_ != t_.size()) fail("caractères en trop");
        return v;
    }
private:
    const std::string& t_;
    size_t p_ = 0;
    [[noreturn]] void fail(const char* m) {
        throw std::runtime_error(std::string("JSON invalide (") + m + ") à " + std::to_string(p_));
    }
    void ws() { while (p_ < t_.size() && (t_[p_] == ' ' || t_[p_] == '\n' || t_[p_] == '\r' || t_[p_] == '\t')) ++p_; }
    bool lit(const char* w) {
        size_t n = strlen(w);
        if (t_.compare(p_, n, w) == 0) { p_ += n; return true; }
        return false;
    }
    Json value() {
        ws();
        if (p_ >= t_.size()) fail("fin inattendue");
        char c = t_[p_];
        if (c == '{') return object();
        if (c == '[') return array();
        if (c == '"') return Json::str(string());
        if (lit("true")) return Json::boolean(true);
        if (lit("false")) return Json::boolean(false);
        if (lit("null")) return Json();
        return number();
    }
    Json number() {
        const char* start = t_.c_str() + p_;
        char* end = nullptr;
        double v = strtod(start, &end);
        if (end == start) fail("nombre");
        p_ += (size_t)(end - start);
        return Json::num(v);
    }
    static void utf8(std::string& out, uint32_t cp) {
        if (cp < 0x80) out += (char)cp;
        else if (cp < 0x800) { out += (char)(0xC0 | (cp >> 6)); out += (char)(0x80 | (cp & 0x3F)); }
        else if (cp < 0x10000) { out += (char)(0xE0 | (cp >> 12)); out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F)); }
        else { out += (char)(0xF0 | (cp >> 18)); out += (char)(0x80 | ((cp >> 12) & 0x3F)); out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F)); }
    }
    uint32_t hex4() {
        if (p_ + 4 > t_.size()) fail("\\u");
        uint32_t v = (uint32_t)strtoul(t_.substr(p_, 4).c_str(), nullptr, 16);
        p_ += 4;
        return v;
    }
    std::string string() {
        ++p_;
        std::string out;
        while (p_ < t_.size() && t_[p_] != '"') {
            char c = t_[p_++];
            if (c != '\\') { out += c; continue; }
            if (p_ >= t_.size()) fail("échappement");
            char e = t_[p_++];
            switch (e) {
                case 'n': out += '\n'; break;
                case 't': out += '\t'; break;
                case 'r': out += '\r'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'u': {
                    uint32_t cp = hex4();
                    if (cp >= 0xD800 && cp < 0xDC00 && lit("\\u")) {
                        uint32_t lo = hex4();
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    }
                    utf8(out, cp);
                    break;
                }
                default: out += e;
            }
        }
        if (p_ >= t_.size()) fail("chaîne non fermée");
        ++p_;
        return out;
    }
    Json array() {
        ++p_;
        Json j = Json::array();
        ws();
        if (p_ < t_.size() && t_[p_] == ']') { ++p_; return j; }
        for (;;) {
            j.a.push_back(value());
            ws();
            if (p_ < t_.size() && t_[p_] == ',') { ++p_; continue; }
            if (p_ < t_.size() && t_[p_] == ']') { ++p_; return j; }
            fail("tableau");
        }
    }
    Json object() {
        ++p_;
        Json j = Json::object();
        ws();
        if (p_ < t_.size() && t_[p_] == '}') { ++p_; return j; }
        for (;;) {
            ws();
            if (p_ >= t_.size() || t_[p_] != '"') fail("clé");
            std::string k = string();
            ws();
            if (p_ >= t_.size() || t_[p_] != ':') fail(":");
            ++p_;
            j.o[k] = value();
            ws();
            if (p_ < t_.size() && t_[p_] == ',') { ++p_; continue; }
            if (p_ < t_.size() && t_[p_] == '}') { ++p_; return j; }
            fail("objet");
        }
    }
};

inline Json parse_json(const std::string& t) { return JsonParser(t).parse(); }

inline void dump_string(std::string& out, const std::string& s) {
    out += '"';
    for (unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); out += b; }
                else out += (char)c;
        }
    }
    out += '"';
}

inline void dump_json(std::string& out, const Json& j) {
    switch (j.type) {
        case Json::Null: out += "null"; break;
        case Json::Bool: out += j.b ? "true" : "false"; break;
        case Json::Number: {
            char b[40];
            if (j.n == (double)(int64_t)j.n && j.n > -9e15 && j.n < 9e15) snprintf(b, sizeof b, "%lld", (long long)j.n);
            else snprintf(b, sizeof b, "%.10g", j.n);
            out += b;
            break;
        }
        case Json::String: dump_string(out, j.s); break;
        case Json::Array: {
            out += '[';
            for (size_t i = 0; i < j.a.size(); ++i) { if (i) out += ','; dump_json(out, j.a[i]); }
            out += ']';
            break;
        }
        case Json::Object: {
            out += '{';
            bool first = true;
            for (auto& kv : j.o) {
                if (!first) out += ',';
                first = false;
                dump_string(out, kv.first);
                out += ':';
                dump_json(out, kv.second);
            }
            out += '}';
            break;
        }
    }
}

inline std::string to_json(const Json& j) { std::string s; dump_json(s, j); return s; }

}  // namespace fmz
