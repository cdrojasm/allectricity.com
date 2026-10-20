#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/resource.h>

namespace {
using SteadyClock = std::chrono::steady_clock;
double elapsed_ms(SteadyClock::time_point start) {
    return std::chrono::duration<double, std::milli>(SteadyClock::now() - start).count();
}
double peak_rss_mib() {
    rusage usage{};
    if (getrusage(RUSAGE_SELF, &usage) != 0) return -1.0;
#ifdef __APPLE__
    return static_cast<double>(usage.ru_maxrss) / (1024.0 * 1024.0);
#else
    return static_cast<double>(usage.ru_maxrss) / 1024.0;
#endif
}
constexpr const char* kProtocol = "SPAT-POTENTIAL-3";
constexpr const char* kProtocolV4 = "SPAT-POTENTIAL-4";
constexpr const char* kProtocolV5 = "SPAT-POTENTIAL-5";
constexpr const char* kSolverVersion = "3.6.0";
constexpr const char* kMethod =
    "galerkin-thin-wire-mom;piecewise-constant-leakage;analytic-line-integral;"
    "adaptive-graded-gauss-legendre-8;interaction-classified-far-gauss-legendre-8;"
    "same-radius-reciprocal-matrix-reuse";
constexpr const char* kLayeredMethod =
    "galerkin-thin-wire-mom;piecewise-constant-leakage;analytic-line-integral;"
    "adaptive-graded-gauss-legendre-8;interaction-classified-far-gauss-legendre-8;"
    "same-radius-reciprocal-matrix-reuse;two-layer-image-series;far-image-gauss-2x2";
constexpr const char* kAssumptions =
    "homogeneous-isotropic-semi-infinite-soil;insulating-air-boundary;quasi-static-dc;"
    "ideal-equipotential-metal-per-group;zero-net-current-for-floating-groups";
constexpr const char* kLayeredAssumptions =
    "two-layer-horizontally-stratified-isotropic-soil;insulating-air-boundary;quasi-static-dc;"
    "ideal-equipotential-metal-per-group;zero-net-current-for-floating-groups";
constexpr const char* kNLayerMethod =
    "galerkin-thin-wire-mom;piecewise-constant-leakage;analytic-line-integral;"
    "adaptive-graded-gauss-legendre-8;interaction-classified-far-gauss-legendre-8;"
    "same-radius-reciprocal-matrix-reuse;n-layer-generalized-reflection-recursion;"
    "real-exponential-image-fit-tsvd;"
    "a-posteriori-spectral-error-bound;far-image-gauss-2x2";
constexpr const char* kNLayerAssumptions =
    "horizontally-stratified-isotropic-soil-1-to-8-layers;bottom-layer-half-space;insulating-air-boundary;"
    "quasi-static-dc;ideal-equipotential-metal-per-group;zero-net-current-for-floating-groups";
constexpr const char* kUnits = "length=m;resistivity=ohm_m;current=A;potential=V;resistance=ohm";

// Operational limits. Timing and memory measured by validation/benchmark.py; see README.
#ifndef SPAT_MAX_SEGMENTS
#define SPAT_MAX_SEGMENTS 4000
#endif
constexpr std::size_t kMaxSegments = SPAT_MAX_SEGMENTS;
constexpr std::size_t kMaxPoints = 100000;
constexpr std::size_t kMaxScenarioCount = 1000;
constexpr double kMaxScenarioResultRows = 2.0e6;
constexpr double kMaxPointSegmentWork = 2.0e7;
constexpr double kMaxCoordinateM = 1.0e5;
constexpr double kMaxDepthM = 1000.0;
constexpr double kMinRadiusM = 1.0e-4;
constexpr double kMaxRadiusM = 0.5;
constexpr double kMinLengthToRadius = 5.0;
constexpr double kMaxResistivityOhmM = 1.0e6;
constexpr double kMaxCurrentA = 1.0e6;
constexpr double kMinLayerThicknessM = 0.01;
// Two-layer image series: truncation tolerance relative to the weakest direct coupling
// (1 / largest extent), and the most image orders the solver will sum before refusing.
constexpr double kImageSeriesTolerance = 1.0e-7;
constexpr int kMaxImageTerms = 2000;
constexpr double kDefaultQuadratureTolerance = 1.0e-9;
constexpr double kMinQuadratureTolerance = 1.0e-12;
constexpr double kMaxQuadratureTolerance = 1.0e-4;
double gQuadratureTolerance = kDefaultQuadratureTolerance;
std::size_t gQuadratureEvaluations = 0, gQuadratureRefinements = 0, gQuadratureMaxDepth = 0;
std::size_t gQuadratureInteractions = 0, gQuadratureMaxEvaluationsPerInteraction = 0;
// Two-layer work limits in image evaluations (one image of one segment seen from one point).
// Measured with validation/benchmark.py at about 2.5e-9 s per evaluation (Apple M5 Pro), so each
// limit is about 10 s; homogeneous requests stay far below them.
constexpr double kMaxMatrixImageWork = 4.0e9;
constexpr double kMaxPointImageWork = 4.0e9;
// N-layer kernel limits (see the "N-layer soil" section). The image-work limits above also apply.
constexpr std::size_t kMaxLayers = 8;
constexpr double kMaxLayerContrast = 1.0e4;       // max/min resistivity of the stack
constexpr int kMinKernelDensity = 6;              // exponential images per decade of depth
constexpr int kMaxKernelDensity = 12;
constexpr int kMaxKernelTerms = 120;              // fitted images per coefficient function
constexpr double kKernelDepthFactor = 17.0;       // ln(1e7): reach of the deepest fitted image
constexpr double kKernelSvdCut = 1.0e-10;         // truncation of the least-squares fit
constexpr double kKernelZeroWeight = 30.0;        // weight of lambda = 0 (far field) in the fit
constexpr double kKernelMaxErrorBound = 1.0e-4;   // refuse the request above this bound
constexpr double kKernelWarnErrorBound = 1.0e-5;  // warn above this bound
constexpr double kKernelMaxAmplification = 1.0e6; // sum |a_k| / max |f|: cancellation guard
constexpr double kMaxKernelEvaluations = 1.0e6;   // spectral evaluations to build the kernel

// Numerical acceptance limits.
constexpr double kMaxBackwardError = 1.0e-10;
constexpr double kWarnCondition = 1.0e10;
constexpr double kMaxCondition = 1.0e13;
constexpr double kMaxRelativeBalanceError = 1.0e-9;
#ifndef SPAT_DIRECT_SOLVER_MAX_SEGMENTS
#define SPAT_DIRECT_SOLVER_MAX_SEGMENTS 1500
#endif
constexpr std::size_t kDirectSolverMaxSegments = SPAT_DIRECT_SOLVER_MAX_SEGMENTS;
constexpr int kGmresRestart = 40;
constexpr int kGmresMaxIterations = 800;
constexpr double kGmresTolerance = 1.0e-12;

constexpr double kPi = 3.1415926535897932384626433832795;
constexpr std::array<double, 8> kNodes = {
    -0.9602898564975363, -0.7966664774136267, -0.5255324099163290,
    -0.1834346424956498, 0.1834346424956498, 0.5255324099163290,
    0.7966664774136267, 0.9602898564975363};
constexpr std::array<double, 8> kWeights = {
    0.1012285362903763, 0.2223810344533745, 0.3137066458778873,
    0.3626837833783620, 0.3626837833783620, 0.3137066458778873,
    0.2223810344533745, 0.1012285362903763};

struct Vec3 {
    double x{}, y{}, z{};
};

Vec3 operator-(const Vec3& a, const Vec3& b) { return {a.x-b.x, a.y-b.y, a.z-b.z}; }
Vec3 operator+(const Vec3& a, const Vec3& b) { return {a.x+b.x, a.y+b.y, a.z+b.z}; }
Vec3 operator*(const Vec3& a, double k) { return {a.x*k, a.y*k, a.z*k}; }
double dot(const Vec3& a, const Vec3& b) { return a.x*b.x + a.y*b.y + a.z*b.z; }
double norm(const Vec3& a) { return std::sqrt(dot(a, a)); }
Vec3 mirror(const Vec3& a) { return {a.x, a.y, -a.z}; }

struct Segment {
    std::string id;
    std::string group;
    std::string kind;
    Vec3 a, b;
    double radius{};
    double length{};
};

struct Point {
    std::string id;
    Vec3 p;
};

struct Group {
    double injected_current{};
    std::string origin{"none"};
    double potential{};
    double net_current{};
    double potential_spread{};
};

struct ElectricalConnection {
    std::string id, a, b;
    double resistance{};  // zero denotes an ideal bond
};

struct ExcitationScenario {
    std::string id;
    std::map<std::string, std::pair<double, std::string>> injections;
};

Vec3 at(const Segment& s, double t) { return s.a + (s.b - s.a) * t; }

double number(const std::string& text, const char* label) {
    std::size_t used = 0;
    double result;
    try { result = std::stod(text, &used); }
    catch (...) { throw std::runtime_error(std::string("invalid ") + label); }
    if (used != text.size() || !std::isfinite(result)) throw std::runtime_error(std::string("invalid ") + label);
    return result;
}

std::vector<std::string> fields(const std::string& line) {
    std::istringstream stream(line);
    std::vector<std::string> result;
    std::string token;
    while (stream >> token) result.push_back(token);
    return result;
}

std::size_t count_value(const std::string& value, const char* label, std::size_t maximum) {
    const double n = number(value, label);
    if (n < 0 || std::floor(n) != n || n > static_cast<double>(maximum))
        throw std::runtime_error(std::string("invalid ") + label + " (maximum " + std::to_string(maximum) + ")");
    return static_cast<std::size_t>(n);
}

void require_id(const std::string& id, const char* label) {
    if (id.empty() || id.size() > 80) throw std::runtime_error(std::string("invalid ") + label);
    for (unsigned char c : id)
        if (!(std::isalnum(c) || c == '_' || c == '-' || c == '.' || c == ':'))
            throw std::runtime_error(std::string("invalid ") + label + " (use letters, digits, _ . : -)");
}

void require_coordinate(const Vec3& p, const std::string& label) {
    if (std::abs(p.x) > kMaxCoordinateM || std::abs(p.y) > kMaxCoordinateM || std::abs(p.z) > kMaxDepthM)
        throw std::runtime_error(label + " coordinates exceed the supported extent");
}

// Closest distance between segments [p1,q1] and [p2,q2]; s and t are the closest parameters.
double segment_distance(const Vec3& p1, const Vec3& q1, const Vec3& p2, const Vec3& q2, double& s, double& t) {
    const Vec3 d1 = q1 - p1, d2 = q2 - p2, r = p1 - p2;
    const double a = dot(d1, d1), e = dot(d2, d2), f = dot(d2, r), c = dot(d1, r), b = dot(d1, d2);
    const double denom = a * e - b * b;
    s = denom > 1e-12 * a * e ? std::clamp((b * f - c * e) / denom, 0.0, 1.0) : 0.0;
    t = (b * s + f) / e;
    if (t < 0.0) { t = 0.0; s = std::clamp(-c / a, 0.0, 1.0); }
    else if (t > 1.0) { t = 1.0; s = std::clamp((b - c) / a, 0.0, 1.0); }
    return norm((p1 + d1 * s) - (p2 + d2 * t));
}

enum class InteractionKind { degenerate, self, shared_endpoint, t_junction, crossing, near, separated };
constexpr std::array<const char*, 7> kInteractionNames = {
    "degenerate", "self", "shared_endpoint", "t_junction", "crossing", "near", "separated"};
struct InteractionCounts {
    std::array<std::size_t, kInteractionNames.size()> categories{};
    std::size_t near_interface{0};
};

std::size_t interaction_index(InteractionKind kind) { return static_cast<std::size_t>(kind); }

InteractionKind classify_interaction(const Segment& a, const Segment& b, bool same,
                                     const std::vector<double>& interfaces, bool* near_interface = nullptr) {
    const bool finite = std::isfinite(a.length) && std::isfinite(b.length) &&
        std::isfinite(a.radius) && std::isfinite(b.radius) &&
        std::isfinite(a.a.x) && std::isfinite(a.a.y) && std::isfinite(a.a.z) &&
        std::isfinite(a.b.x) && std::isfinite(a.b.y) && std::isfinite(a.b.z) &&
        std::isfinite(b.a.x) && std::isfinite(b.a.y) && std::isfinite(b.a.z) &&
        std::isfinite(b.b.x) && std::isfinite(b.b.y) && std::isfinite(b.b.z);
    if (!finite || a.length < 5.0 * a.radius || b.length < 5.0 * b.radius) {
        if (near_interface) *near_interface = false;
        return InteractionKind::degenerate;
    }
    bool interface_flag = false;
    for (double depth : interfaces) {
        const double tolerance_a = 0.1 * a.length, tolerance_b = 0.1 * b.length;
        interface_flag = interface_flag || std::min(std::abs(-a.a.z - depth), std::abs(-a.b.z - depth)) <= tolerance_a ||
                         std::min(std::abs(-b.a.z - depth), std::abs(-b.b.z - depth)) <= tolerance_b;
    }
    if (near_interface) *near_interface = interface_flag;
    if (same) return InteractionKind::self;

    double s = 0.0, t = 0.0;
    const double gap = segment_distance(a.a, a.b, b.a, b.b, s, t);
    const double tolerance = 1.0e-6 * std::min(a.length, b.length);
    for (const Vec3& p : {a.a, a.b}) for (const Vec3& q : {b.a, b.b})
        if (norm(p - q) <= tolerance) return InteractionKind::shared_endpoint;
    if (gap <= tolerance) {
        const bool end_a = s * a.length <= tolerance || (1.0 - s) * a.length <= tolerance;
        const bool end_b = t * b.length <= tolerance || (1.0 - t) * b.length <= tolerance;
        return end_a || end_b ? InteractionKind::t_junction : InteractionKind::crossing;
    }
    if (gap < 2.0 * std::min(a.length, b.length)) return InteractionKind::near;
    return InteractionKind::separated;
}

// Integral of 1/R along a straight source line from a to b for an observation point p,
// with the thin-wire reduced kernel R = sqrt(axial^2 + perpendicular^2 + radius^2).
double line_integral(const Vec3& p, const Vec3& a, const Vec3& b, double length, double radius) {
    const Vec3 u = (b - a) * (1.0 / length);
    const Vec3 w = p - a;
    const double t = dot(w, u);
    const double perpendicular2 = std::max(dot(w, w) - t * t, 0.0);
    const double rho = std::sqrt(perpendicular2 + radius * radius);
    return std::asinh((length - t) / rho) + std::asinh(t / rho);
}

// Potential at p per unit source-segment current, without the rho/(4 pi) factor (units 1/m).
double source_potential(const Vec3& p, const Segment& source) {
    return (line_integral(p, source.a, source.b, source.length, source.radius) +
            line_integral(p, mirror(source.a), mirror(source.b), source.length, source.radius)) / source.length;
}

// Gauss-Legendre on [t0, t1] of a function of the target parameter.
template <typename F>
double gauss(F&& f, double t0, double t1) {
    double sum = 0.0;
    for (std::size_t q = 0; q < kNodes.size(); ++q) {
        ++gQuadratureEvaluations;
        sum += kWeights[q] * f(t0 + (t1 - t0) * 0.5 * (kNodes[q] + 1.0));
    }
    return 0.5 * (t1 - t0) * sum;
}

// Compare one GL8 panel with its two half-panels. Refine only where the embedded
// difference exceeds the requested relative tolerance; fail explicitly if the
// fixed depth limit cannot meet it.
template <typename F>
double adaptive_gauss(F&& f, double t0, double t1, int depth = 0) {
    const double whole = gauss(f, t0, t1);
    const double mid = 0.5 * (t0 + t1);
    const double left = gauss(f, t0, mid), right = gauss(f, mid, t1);
    const double split = left + right;
    gQuadratureMaxDepth = std::max(gQuadratureMaxDepth, static_cast<std::size_t>(depth));
    const double absolute_tolerance = 1.0e-12 * std::abs(t1 - t0);
    if (std::abs(split - whole) <= absolute_tolerance + gQuadratureTolerance * std::abs(split)) return split;
    if (depth >= 16) throw std::runtime_error("near-field quadrature did not converge (depth=" +
                                              std::to_string(depth) + ", tolerance=" +
                                              std::to_string(gQuadratureTolerance) + ", evaluations=" +
                                              std::to_string(gQuadratureEvaluations) + ")");
    ++gQuadratureRefinements;
    return adaptive_gauss(f, t0, mid, depth + 1) + adaptive_gauss(f, mid, t1, depth + 1);
}

// Integral on [from, to] graded geometrically towards `to`, where the integrand varies on `scale`.
template <typename F>
double graded(F&& f, double from, double to, double scale) {
    double result = 0.0, gap = std::abs(to - from);
    const double direction = to > from ? 1.0 : -1.0;
    while (gap > scale) {
        const double next = 0.2 * gap;
        const double lo = to - direction * gap, hi = to - direction * next;
        result += adaptive_gauss(f, std::min(lo, hi), std::max(lo, hi));
        gap = next;
    }
    const double lo = to - direction * gap;
    return result + adaptive_gauss(f, std::min(lo, to), std::max(lo, to));
}

struct NearPoint {
    double t;      // closest target parameter
    double scale;  // relative length on which the integrand varies there
};

// Integral over the target parameter [0, 1], refined towards near source points.
template <typename F>
double integrate(F&& f, std::vector<NearPoint> near) {
    const std::size_t evaluations_before = gQuadratureEvaluations;
    const auto finish = [&](double value) {
        ++gQuadratureInteractions;
        gQuadratureMaxEvaluationsPerInteraction = std::max(
            gQuadratureMaxEvaluationsPerInteraction, gQuadratureEvaluations - evaluations_before);
        return value;
    };
    if (near.empty()) return finish(adaptive_gauss(f, 0.0, 1.0));
    std::sort(near.begin(), near.end(), [](const NearPoint& a, const NearPoint& b) { return a.t < b.t; });
    double result = 0.0, left = 0.0, left_scale = 0.0;
    bool left_singular = false;
    for (std::size_t k = 0; k <= near.size(); ++k) {
        const bool right_singular = k < near.size();
        const double right = right_singular ? near[k].t : 1.0;
        const double right_scale = right_singular ? near[k].scale : 0.0;
        if (right > left) {
            const double mid = 0.5 * (left + right);
            if (left_singular && right_singular) result += graded(f, mid, left, left_scale) + graded(f, mid, right, right_scale);
            else if (left_singular) result += graded(f, right, left, left_scale);
            else if (right_singular) result += graded(f, left, right, right_scale);
            else result += adaptive_gauss(f, left, right);
        }
        left = right; left_scale = right_scale; left_singular = right_singular;
    }
    return finish(result);
}

// Galerkin coefficient: length-averaged potential over the target per unit source current (1/m).
double coefficient(const Segment& target, const Segment& source, bool same, InteractionKind interaction) {
    const double L = target.length;
    const Vec3 image_a = mirror(source.a), image_b = mirror(source.b);
    std::vector<NearPoint> near;
    const auto add_near = [&](const Vec3& a, const Vec3& b) {
        double s = 0.0, t = 0.0;
        const double gap = segment_distance(target.a, target.b, a, b, s, t);
        if (gap < 2.0 * L) near.push_back({s, std::max({gap, source.radius, 1e-6 * L}) / L});
    };
    add_near(image_a, image_b);
    if (same) {
        // Closed-form average of the direct term over the segment itself; quadrature for its image.
        const double a = target.radius;
        const double direct = 2.0 * (L * std::asinh(L / a) - std::sqrt(L * L + a * a) + a) / (L * L);
        const auto image = [&](double t) { return line_integral(at(target, t), image_a, image_b, L, a) / L; };
        return direct + (near.empty() && interaction == InteractionKind::separated
                         ? gauss(image, 0.0, 1.0) : integrate(image, near));
    }
    add_near(source.a, source.b);
    const auto potential = [&](double t) { return source_potential(at(target, t), source); };
    return near.empty() && interaction == InteractionKind::separated
        ? gauss(potential, 0.0, 1.0) : integrate(potential, near);
}

// Two-layer soil: upper layer rho1 of thickness h over a semi-infinite layer rho2, with an
// insulating air boundary at z = 0. The point-source potential is the classical image series
// (Sunde 1949; Tagg 1964) with reflection coefficient K = (rho2 - rho1) / (rho2 + rho1):
//   source and observation in layer 1: rho1 sum_{n=-inf..inf} K^|n| [1/R(t-s+2nh) + 1/R(t+s+2nh)]
//   source in layer 1, observation in 2: rho1 (1+K) sum_{n>=0} K^n [1/R(t-s+2nh) + 1/R(t+s+2nh)]
//   source in layer 2, observation in 1: rho1 (1+K) sum_{n>=0} K^n [1/R(s-t+2nh) + 1/R(s+t+2nh)]
//   source and observation in layer 2: rho2 [1/R(t-s) - K/R(t+s-2h) + (1-K^2) sum_{n>=0} K^n/R(t+s+2nh)]
// with depths s, t > 0 and R(d) = sqrt(r^2 + d^2), all over 4 pi. Every term is the potential of
// a translated or mirrored copy of the source segment, so the analytic line integral applies to each.
struct KernelDiagnostics {
    int density{0}, terms{0}, functions{0}, max_images_per_pair{0}, lambda_samples{0};
    double b_min{0.0}, b_max{0.0}, error_bound{0.0}, max_amplification{0.0}, spectral_evaluations{0.0};
};

struct Soil {
    bool layered{false};
    bool nlayer{false};        // n-layer kernel (also sets `layered`)
    double rho1{}, rho2{}, h{}, k{};
    int terms{0};              // image orders n = 0..terms
    double tail_bound{0.0};    // truncation bound relative to the weakest direct coupling
    std::vector<double> rhos;          // n-layer: top to bottom, after merging equal neighbours
    std::vector<double> thicknesses;   // n-layer: the finite layers (rhos.size() - 1 values)
    std::vector<double> interfaces;    // depths of the interfaces, increasing (two-layer: {h})
    KernelDiagnostics kernel;
};

struct Image {
    double weight;   // relative to rho1
    bool mirrored;   // z -> -z before the shift
    double shift;    // added to z
};

// Layer of a point at height z (z <= 0); a point on an interface belongs to the layer below it.
int layer_of(double z, const Soil& soil) {
    int layer = 0;
    for (double depth : soil.interfaces) if (-z >= depth) ++layer;
    return layer;
}
int layer_of(const Segment& s, const Soil& soil) { return layer_of(0.5 * (s.a.z + s.b.z), soil); }

// images[source layer][observation layer]
using ImageTable = std::vector<std::vector<std::vector<Image>>>;

ImageTable image_table(const Soil& soil) {
    ImageTable table(2, std::vector<std::vector<Image>>(2));
    const double K = soil.k, r = soil.rho2 / soil.rho1;
    auto& upper = table[0][0];
    upper = {{1.0, false, 0.0}, {1.0, true, 0.0}};
    double kn = 1.0;
    for (int n = 1; n <= soil.terms; ++n) {
        kn *= K;
        const double d = 2.0 * n * soil.h;
        upper.insert(upper.end(), {{kn, false, d}, {kn, true, d}, {kn, false, -d}, {kn, true, -d}});
    }
    kn = 1.0 + K;
    for (int n = 0; n <= soil.terms; ++n, kn *= K) {
        const double d = 2.0 * n * soil.h;
        table[0][1].insert(table[0][1].end(), {{kn, false, d}, {kn, true, d}});
        table[1][0].insert(table[1][0].end(), {{kn, false, -d}, {kn, true, d}});
    }
    auto& lower = table[1][1];
    lower = {{r, false, 0.0}, {-r * K, true, -2.0 * soil.h}};
    kn = r * (1.0 - K * K);
    for (int n = 0; n <= soil.terms; ++n, kn *= K) lower.push_back({kn, true, 2.0 * n * soil.h});
    return table;
}

Vec3 apply(const Image& image, const Vec3& p) { return {p.x, p.y, (image.mirrored ? -p.z : p.z) + image.shift}; }

// Smallest image order whose a-priori tail bound is below the tolerance. At order n every image
// lies at least 2nh - 2 Dmax away, there are at most 4 images per order with weight at most
// 2 max(1, rho2/rho1) |K|^n, so the tail beyond N is at most
//   8 max(1, rho2/rho1) |K|^(N+1) / ((1 - |K|)(2(N+1)h - 2 Dmax)),
// measured against 1 / extent, the weakest direct coupling in the problem.
void choose_image_terms(Soil& soil, double max_depth, double extent) {
    const double K = std::abs(soil.k), c = 8.0 * std::max(1.0, soil.rho2 / soil.rho1);
    for (int n = 1; n <= kMaxImageTerms; ++n) {
        const double gap = 2.0 * (n + 1) * soil.h - 2.0 * max_depth;
        if (gap <= soil.h) continue;
        const double tail = c * std::pow(K, n + 1) / ((1.0 - K) * gap) * extent;
        if (tail <= kImageSeriesTolerance) { soil.terms = n; soil.tail_bound = tail; return; }
    }
    std::ostringstream message;
    message << "two-layer image series needs more than " << kMaxImageTerms << " terms (K = " << soil.k
            << ", h = " << soil.h << " m); the resistivity contrast is too high for this solver";
    throw std::runtime_error(message.str());
}

// Integral of 1/R over an image of the source segment; images farther than 4 lengths use a
// two-point Gauss rule (relative error below about 2e-5).
double image_integral(const Vec3& p, const Segment& source, const Image& image) {
    const Vec3 a = apply(image, source.a), b = apply(image, source.b);
    const Vec3 mid = (a + b) * 0.5;
    if (norm(p - mid) > 4.0 * source.length) {
        const Vec3 half = (b - a) * (0.5 / std::sqrt(3.0));
        return 0.5 * source.length * (1.0 / norm(p - (mid - half)) + 1.0 / norm(p - (mid + half)));
    }
    return line_integral(p, a, b, source.length, source.radius);
}

// Potential at p per unit source-segment current, relative to rho1 / (4 pi) (units 1/m).
double layered_source_potential(const Vec3& p, int observation_layer, const Segment& source, int source_layer,
                                const ImageTable& table) {
    double sum = 0.0;
    for (const auto& image : table[source_layer][observation_layer]) sum += image.weight * image_integral(p, source, image);
    return sum / source.length;
}

// Galerkin coefficient in two-layer soil (relative to rho1 / (4 pi)), image by image: closed form
// for the segment itself, 2x2 Gauss for far images, graded quadrature with the analytic line
// integral for near ones.
double layered_coefficient(const Segment& target, int target_layer, const Segment& source, int source_layer,
                           bool same, InteractionKind interaction, const ImageTable& table) {
    const double L = target.length;
    constexpr double kGauss2 = 0.2113248654051871;  // (1 - 1/sqrt(3)) / 2
    const Vec3 target_mid = (target.a + target.b) * 0.5;
    double total = 0.0;
    for (const auto& image : table[source_layer][target_layer]) {
        const Vec3 a = apply(image, source.a), b = apply(image, source.b);
        if (same && !image.mirrored && image.shift == 0.0) {
            const double r = target.radius;
            total += image.weight * 2.0 * (L * std::asinh(L / r) - std::sqrt(L * L + r * r) + r) / (L * L);
            continue;
        }
        if (norm(target_mid - (a + b) * 0.5) > 4.0 * (L + source.length)) {
            double sum = 0.0;
            for (double ti : {kGauss2, 1.0 - kGauss2})
                for (double sj : {kGauss2, 1.0 - kGauss2}) sum += 1.0 / norm(at(target, ti) - (a + (b - a) * sj));
            total += image.weight * 0.25 * sum;
            continue;
        }
        Segment image_source = source;
        image_source.a = a; image_source.b = b;
        const InteractionKind image_interaction = !image.mirrored && image.shift == 0.0
            ? interaction : classify_interaction(target, image_source, false, {});
        double s = 0.0, t = 0.0;
        const double gap = segment_distance(target.a, target.b, a, b, s, t);
        std::vector<NearPoint> near;
        if (gap < 2.0 * L) near.push_back({s, std::max({gap, source.radius, 1e-6 * L}) / L});
        const auto f = [&](double u) { return line_integral(at(target, u), a, b, source.length, source.radius) / source.length; };
        total += image.weight * (near.empty() && image_interaction == InteractionKind::separated
                                 ? gauss(f, 0.0, 1.0) : integrate(f, near));
    }
    return total;
}

// ---------------------------------------------------------------------------------------------
// N-layer soil: layers k = 0..N-1 (N <= 8) with resistivity rho_k between depths d_k and d_{k+1}
// (d_0 = 0, the bottom layer is a half-space), insulating air above z = 0.
//
// Spectral form (Sunde 1949, ch. 2; Koefoed 1979, "Geosounding Principles 1", ch. 2-3). With the
// Lipschitz integral 1/R = int_0^inf exp(-lambda |dz|) J0(lambda r) dlambda, the potential at depth t
// in layer j of a unit point current at depth s in layer i is (1 / 4 pi) int F(lambda) J0(lambda r)
// dlambda with
//   F = delta_ij rho_i exp(-lambda |t - s|) + sum_{p in {u,v}, q in {A,B}} c_pq(lambda) exp(-lambda (sigma_p + tau_q + delta_pq))
// where sigma_u = s - d_i, sigma_v = d_{i+1} - s (source to the top / bottom of its layer),
// tau_A = t - d_j, tau_B = d_{j+1} - t, and delta_pq is the thickness the direct ray crosses (factored
// out analytically, so c_pq stays bounded and never underflows). c_pq follows from the stable
// generalized reflection / transmission recursion for a static layered medium (Chew, "Waves and Fields
// in Inhomogeneous Media", 1990, sec. 2.1, with zero frequency): local reflection
// K_k = (rho_k - rho_{k-1}) / (rho_k + rho_{k-1}) for a wave going down at interface k, -K_k going up,
// +1 at the insulating surface, potential transmission 1 + K_k down and 1 - K_k up. Every quantity
// is a Moebius map of exp(-2 lambda h) factors with modulus <= 1, so no exp(+lambda h) appears.
//
// Image representation: c_pq(lambda) = c_pq(inf) + sum_k a_k exp(-lambda b_k) with fixed depths
// b_k on a geometric grid (density images per decade between the thinnest layer and the reach of
// the slowest multiple reflection), fitted by truncated-SVD least squares on lambda samples (the
// real-exponential variant of the complex-image method: Chow, Yang & Srivastava, J. Appl. Phys. 71,
// 1992; Li, Chen, Fan & Lu, IEEE Trans. Power Deliv. 21(3), 2006). Each term is exactly
// a / sqrt(r^2 + (sigma + tau + delta + b)^2), i.e. a mirrored or translated copy of the source
// segment, so the analytic line integral and the two-layer quadrature apply unchanged.
//
// Error control: for every fitted function the residual e(lambda) is evaluated on a grid 2-4 times
// denser than the fit and up to 60 / b_min. Since |exp(-lambda Z) J0(lambda r)| <= min(1, sqrt(2 /
// (pi lambda r))) (Watson, "Theory of Bessel Functions", sec. 13.74), the spatial error at distance
// R <= R_max is bounded by int |e| w(lambda) dlambda; the bound, relative to the direct coupling
// min(rho_i, rho_j) / R and summed over the four terms, is reported as kernel_error_bound and the
// request is refused above kKernelMaxErrorBound.
// ---------------------------------------------------------------------------------------------

enum Combo { kUA = 0, kUB = 1, kVA = 2, kVB = 3 };

// Depth of the top of layer k.
double soil_top(const Soil& soil, int k) { return k == 0 ? 0.0 : soil.interfaces[static_cast<std::size_t>(k - 1)]; }

double vector_norm_plain(const std::vector<double>& x) {
    double value = 0.0;
    for (double v : x) value = std::hypot(value, v);
    return value;
}

struct Spectral {
    std::array<double, 4> c{};       // scaled coefficients (ohm-m)
    std::array<double, 4> delta{};   // crossed thickness factored out of each coefficient
    std::array<bool, 4> present{};
};

// Scaled coefficients c_pq(lambda) of source layer i seen in layer j; `limit` gives lambda -> inf.
Spectral spectral(const Soil& soil, int i, int j, double lambda, bool limit) {
    const auto& rho = soil.rhos;
    const auto& h = soil.thicknesses;
    const int n = static_cast<int>(rho.size());
    std::array<double, kMaxLayers + 1> top{}, e{}, x{}, up{}, down{}, k{};
    for (int m = 0; m < n; ++m) {
        top[static_cast<std::size_t>(m + 1)] = m < n - 1 ? top[static_cast<std::size_t>(m)] + h[static_cast<std::size_t>(m)] : 0.0;
        e[static_cast<std::size_t>(m)] = m < n - 1 && !limit ? std::exp(-lambda * h[static_cast<std::size_t>(m)]) : 0.0;
        x[static_cast<std::size_t>(m)] = e[static_cast<std::size_t>(m)] * e[static_cast<std::size_t>(m)];
        if (m > 0) k[static_cast<std::size_t>(m)] = (rho[static_cast<std::size_t>(m)] - rho[static_cast<std::size_t>(m - 1)]) /
                                                     (rho[static_cast<std::size_t>(m)] + rho[static_cast<std::size_t>(m - 1)]);
    }
    const auto at_ = [](auto& array, int index) -> double& { return array[static_cast<std::size_t>(index)]; };
    // up[m]: generalized reflection of an upgoing wave at the top of layer m (surface included).
    at_(up, 0) = 1.0;
    for (int m = 1; m < n; ++m) {
        const double behind = at_(up, m - 1) * at_(x, m - 1);
        at_(up, m) = (-at_(k, m) + behind) / (1.0 - at_(k, m) * behind);
    }
    // down[m]: generalized reflection of a downgoing wave in layer m-1 at interface m; down[n] = 0.
    at_(down, n) = 0.0;
    for (int m = n - 1; m >= 1; --m) {
        const double behind = (m < n - 1 ? at_(down, m + 1) : 0.0) * at_(x, m);
        at_(down, m) = (at_(k, m) + behind) / (1.0 + at_(k, m) * behind);
    }
    Spectral out;
    const double r = rho[static_cast<std::size_t>(i)];
    const bool bounded = i < n - 1;  // the source layer has a bottom interface
    const double gb = bounded ? at_(down, i + 1) : 0.0, yt = at_(up, i), ei = at_(e, i);
    const double denominator = 1.0 - yt * gb * ei * ei;
    const auto set = [&](Combo combo, double value, double delta) {
        out.c[combo] = value; out.delta[combo] = delta; out.present[combo] = true;
    };
    const auto d = [&](int index) { return at_(top, index); };
    if (j == i) {
        set(kUA, r * yt / denominator, 0.0);
        if (bounded) {
            set(kVB, r * gb / denominator, 0.0);
            set(kUB, r * gb * yt / denominator, h[static_cast<std::size_t>(i)]);
            set(kVA, r * yt * gb / denominator, h[static_cast<std::size_t>(i)]);
        }
    } else if (j < i) {
        double product = 1.0;  // transmission up through interfaces i, i-1, ..., j+1
        for (int m = i; m > j; --m) product *= (1.0 - at_(k, m)) / (1.0 - at_(k, m) * at_(up, m - 1) * at_(x, m - 1));
        const double from_u = r / denominator * product, from_v = r * gb / denominator * product;
        set(kUB, from_u, d(i) - d(j + 1));
        set(kUA, at_(up, j) * from_u, d(i) - d(j));
        if (bounded) {
            set(kVB, from_v, d(i + 1) - d(j + 1));
            set(kVA, at_(up, j) * from_v, d(i + 1) - d(j));
        }
    } else {
        double product = 1.0;  // transmission down through interfaces i+1, ..., j
        for (int m = i + 1; m <= j; ++m) {
            const double below = m < n - 1 ? at_(down, m + 1) * at_(x, m) : 0.0;
            product *= (1.0 + at_(k, m)) / (1.0 + at_(k, m) * below);
        }
        const double from_v = r / denominator * product, from_u = r * yt / denominator * product;
        set(kVA, from_v, d(j) - d(i + 1));
        set(kUA, from_u, d(j) - d(i));
        if (j < n - 1) {
            set(kVB, at_(down, j + 1) * from_v, d(j + 1) - d(i + 1));
            set(kUB, at_(down, j + 1) * from_u, d(j + 1) - d(i));
        }
    }
    return out;
}

struct KernelPlan {
    std::vector<double> b;   // fitted image depths (m), geometric
    double b_min{}, b_max{};
};

// Deterministic image grid, mirrored by the Python client for its cost estimate. The deepest image
// reaches the depth after which the slowest multiple reflection, bounded per round trip of at most
// 2 d_{N-1} by the stack contrast kappa = (max - min) / (max + min), has decayed below e^-17.
KernelPlan kernel_plan(const Soil& soil, int density) {
    KernelPlan plan;
    const double low = *std::min_element(soil.rhos.begin(), soil.rhos.end());
    const double high = *std::max_element(soil.rhos.begin(), soil.rhos.end());
    const double kappa = (high - low) / (high + low);
    plan.b_min = *std::min_element(soil.thicknesses.begin(), soil.thicknesses.end());
    plan.b_max = std::max(4.0 * plan.b_min, 2.0 * soil.interfaces.back() * kKernelDepthFactor / (1.0 - kappa));
    const int terms = static_cast<int>(std::ceil(std::log10(plan.b_max / plan.b_min) * density)) + 1;
    if (terms > kMaxKernelTerms) {
        std::ostringstream message;
        message << "n-layer kernel needs " << terms << " images per coefficient (limit " << kMaxKernelTerms
                << "); the resistivity contrast or the ratio of total depth to thinnest layer is too high";
        throw std::runtime_error(message.str());
    }
    for (int q = 0; q < terms; ++q)
        plan.b.push_back(plan.b_min * std::pow(plan.b_max / plan.b_min, static_cast<double>(q) / (terms - 1)));
    return plan;
}

std::vector<double> geometric_samples(double low, double high, std::size_t count) {
    std::vector<double> values(count);
    for (std::size_t q = 0; q < count; ++q)
        values[q] = low * std::pow(high / low, static_cast<double>(q) / static_cast<double>(count - 1));
    return values;
}

// Pseudo-inverse rows of the weighted exponential basis by one-sided Jacobi SVD (Hestenes 1958;
// Demmel & Veselic 1992), truncated at kKernelSvdCut relative to the largest singular value.
// Returns P (terms x samples) with fit coefficients a = P f for samples f.
std::vector<std::vector<double>> fit_operator(const std::vector<double>& lambda, const std::vector<double>& weight,
                                              const std::vector<double>& b) {
    const std::size_t m = lambda.size(), n = b.size();
    std::vector<std::vector<double>> column(n, std::vector<double>(m)), v(n, std::vector<double>(n, 0.0));
    for (std::size_t q = 0; q < n; ++q) {
        v[q][q] = 1.0;
        for (std::size_t s = 0; s < m; ++s) column[q][s] = weight[s] * std::exp(-lambda[s] * b[q]);
    }
    for (int sweep = 0; sweep < 80; ++sweep) {
        bool rotated = false;
        for (std::size_t p = 0; p + 1 < n; ++p) {
            for (std::size_t q = p + 1; q < n; ++q) {
                double alpha = 0.0, beta = 0.0, gamma = 0.0;
                for (std::size_t s = 0; s < m; ++s) {
                    alpha += column[p][s] * column[p][s];
                    beta += column[q][s] * column[q][s];
                    gamma += column[p][s] * column[q][s];
                }
                if (std::abs(gamma) <= 1e-15 * std::sqrt(alpha * beta)) continue;
                rotated = true;
                const double zeta = (beta - alpha) / (2.0 * gamma);
                const double t = (zeta >= 0.0 ? 1.0 : -1.0) / (std::abs(zeta) + std::sqrt(1.0 + zeta * zeta));
                const double c = 1.0 / std::sqrt(1.0 + t * t), sn = c * t;
                for (std::size_t s = 0; s < m; ++s) {
                    const double a = column[p][s], bq = column[q][s];
                    column[p][s] = c * a - sn * bq;
                    column[q][s] = sn * a + c * bq;
                }
                for (std::size_t s = 0; s < n; ++s) {
                    const double a = v[s][p], bq = v[s][q];
                    v[s][p] = c * a - sn * bq;
                    v[s][q] = sn * a + c * bq;
                }
            }
        }
        if (!rotated) break;
    }
    std::vector<double> sigma(n);
    for (std::size_t q = 0; q < n; ++q) sigma[q] = vector_norm_plain(column[q]);
    const double largest = *std::max_element(sigma.begin(), sigma.end());
    std::vector<std::vector<double>> pseudo(n, std::vector<double>(m, 0.0));
    for (std::size_t q = 0; q < n; ++q) {
        if (!(sigma[q] > kKernelSvdCut * largest)) continue;
        for (std::size_t s = 0; s < m; ++s) {
            const double u = column[q][s] / sigma[q] * weight[s] / sigma[q];
            for (std::size_t row = 0; row < n; ++row) pseudo[row][s] += v[row][q] * u;
        }
    }
    return pseudo;
}

// Image table of an n-layer soil for the (source, observation) layer pairs in use, with the fit
// diagnostics stored in soil.kernel. `max_distance` bounds every source-observation distance.
ImageTable nlayer_table(Soil& soil, const std::vector<bool>& source_layers, const std::vector<bool>& observation_layers,
                        int density, double max_distance) {
    const int n = static_cast<int>(soil.rhos.size());
    ImageTable table(static_cast<std::size_t>(n), std::vector<std::vector<Image>>(static_cast<std::size_t>(n)));
    const KernelPlan plan = kernel_plan(soil, density);
    const std::size_t terms = plan.b.size();
    soil.kernel.density = density;
    soil.kernel.terms = static_cast<int>(terms);
    soil.kernel.b_min = plan.b_min;
    soil.kernel.b_max = plan.b_max;

    // Fit samples: lambda = 0 (far field, weighted) and 3 per image over [0.002 / b_max, 40 / b_min].
    const double fit_low = 0.002 / plan.b_max, fit_high = 40.0 / plan.b_min;
    const std::size_t fit_count = static_cast<std::size_t>(
        3.0 * static_cast<double>(terms) * std::log10(fit_high / fit_low) / std::log10(plan.b_max / plan.b_min)) + 1;
    std::vector<double> fit_lambda{0.0};
    for (double value : geometric_samples(fit_low, fit_high, fit_count)) fit_lambda.push_back(value);
    std::vector<double> fit_weight(fit_lambda.size(), 1.0);
    fit_weight[0] = kKernelZeroWeight;
    // Check samples: 60 per decade over [0.001 / b_max, 60 / b_min], plus lambda = 0.
    const double check_low = 0.001 / plan.b_max, check_high = 60.0 / plan.b_min;
    const std::size_t check_count = static_cast<std::size_t>(60.0 * std::log10(check_high / check_low)) + 1;
    std::vector<double> check_lambda{0.0};
    for (double value : geometric_samples(check_low, check_high, check_count)) check_lambda.push_back(value);
    soil.kernel.lambda_samples = static_cast<int>(fit_lambda.size() + check_lambda.size());

    std::size_t functions = 0;
    for (int i = 0; i < n; ++i)
        for (int j = 0; j < n; ++j)
            if (source_layers[static_cast<std::size_t>(i)] && observation_layers[static_cast<std::size_t>(j)])
                functions += static_cast<std::size_t>((i < n - 1 ? 2 : 1) * (j < n - 1 ? 2 : 1));
    soil.kernel.spectral_evaluations = static_cast<double>(functions) * static_cast<double>(fit_lambda.size() + check_lambda.size());
    if (soil.kernel.spectral_evaluations > kMaxKernelEvaluations)
        throw std::runtime_error("n-layer kernel needs more than 1e6 spectral evaluations");

    const auto pseudo = fit_operator(fit_lambda, fit_weight, plan.b);
    std::vector<std::vector<double>> check_basis(check_lambda.size(), std::vector<double>(terms));
    for (std::size_t s = 0; s < check_lambda.size(); ++s)
        for (std::size_t q = 0; q < terms; ++q) check_basis[s][q] = std::exp(-check_lambda[s] * plan.b[q]);

    // Weights of |e(lambda)| in the spatial error bound at distance R <= max_distance.
    const double reach = max_distance / std::sqrt(2.0);
    std::vector<double> bound_weight(check_lambda.size());
    for (std::size_t s = 0; s < check_lambda.size(); ++s) {
        const double lambda = check_lambda[s];
        const double bessel = lambda > 0.0 ? std::min(1.0, std::sqrt(2.0 / (kPi * lambda * reach))) : 1.0;
        const double vertical = lambda > 0.0 && std::sqrt(2.0) / lambda <= max_distance
            ? std::sqrt(2.0) / (std::exp(1.0) * lambda) : max_distance * std::exp(-lambda * reach);
        bound_weight[s] = std::max(max_distance * bessel, vertical);
    }

    const double rho_ref = soil.rhos[0];
    for (int i = 0; i < n; ++i) {
        if (!source_layers[static_cast<std::size_t>(i)]) continue;
        for (int j = 0; j < n; ++j) {
            if (!observation_layers[static_cast<std::size_t>(j)]) continue;
            auto& images = table[static_cast<std::size_t>(i)][static_cast<std::size_t>(j)];
            if (i == j) images.push_back({soil.rhos[static_cast<std::size_t>(i)] / rho_ref, false, 0.0});
            const Spectral limit = spectral(soil, i, j, 0.0, true);
            std::vector<Spectral> fit_values, check_values;
            for (double lambda : fit_lambda) fit_values.push_back(spectral(soil, i, j, lambda, false));
            for (double lambda : check_lambda) check_values.push_back(spectral(soil, i, j, lambda, false));
            double pair_bound = 0.0;
            for (int combo = 0; combo < 4; ++combo) {
                if (!limit.present[static_cast<std::size_t>(combo)]) continue;
                const double c_inf = limit.c[static_cast<std::size_t>(combo)];
                std::vector<double> coefficients(terms, 0.0);
                double largest = 0.0;
                for (std::size_t s = 0; s < fit_lambda.size(); ++s) {
                    const double f = fit_values[s].c[static_cast<std::size_t>(combo)] - c_inf;
                    largest = std::max(largest, std::abs(f));
                    for (std::size_t q = 0; q < terms; ++q) coefficients[q] += pseudo[q][s] * f;
                }
                double total = 0.0, previous_error = 0.0, bound = 0.0;
                for (double a : coefficients) total += std::abs(a);
                if (largest > 0.0) soil.kernel.max_amplification = std::max(soil.kernel.max_amplification, total / largest);
                for (std::size_t s = 0; s < check_lambda.size(); ++s) {
                    double fitted = 0.0;
                    for (std::size_t q = 0; q < terms; ++q) fitted += coefficients[q] * check_basis[s][q];
                    const double error = std::abs(check_values[s].c[static_cast<std::size_t>(combo)] - c_inf - fitted) * bound_weight[s];
                    if (s > 0) bound += 0.5 * (error + previous_error) * (check_lambda[s] - check_lambda[s - 1]);
                    previous_error = error;
                }
                pair_bound += bound;
                // Images: separation sigma + tau + delta + beta, as a mirrored or translated copy.
                const double delta = limit.delta[static_cast<std::size_t>(combo)];
                const double di = soil_top(soil, i), dj = soil_top(soil, j);
                const double di1 = i < n - 1 ? soil_top(soil, i + 1) : 0.0, dj1 = j < n - 1 ? soil_top(soil, j + 1) : 0.0;
                const auto add = [&](double weight, double beta) {
                    const double offset = delta + beta;
                    switch (combo) {
                        case kUA: images.push_back({weight / rho_ref, true, offset - di - dj}); break;
                        case kUB: images.push_back({weight / rho_ref, false, di - dj1 - offset}); break;
                        case kVA: images.push_back({weight / rho_ref, false, di1 - dj + offset}); break;
                        default: images.push_back({weight / rho_ref, true, -(di1 + dj1 + offset)}); break;
                    }
                };
                add(c_inf, 0.0);
                for (std::size_t q = 0; q < terms; ++q) add(coefficients[q], plan.b[q]);
                ++soil.kernel.functions;
            }
            pair_bound /= std::min(soil.rhos[static_cast<std::size_t>(i)], soil.rhos[static_cast<std::size_t>(j)]);
            soil.kernel.error_bound = std::max(soil.kernel.error_bound, pair_bound);
            soil.kernel.max_images_per_pair = std::max(soil.kernel.max_images_per_pair, static_cast<int>(images.size()));
        }
    }
    if (!(soil.kernel.max_amplification <= kKernelMaxAmplification))
        throw std::runtime_error("n-layer kernel fit is numerically unstable (coefficient amplification above 1e6)");
    if (!(soil.kernel.error_bound <= kKernelMaxErrorBound)) {
        std::ostringstream message;
        message << "n-layer kernel did not converge: relative error bound " << soil.kernel.error_bound
                << " exceeds " << kKernelMaxErrorBound << "; reduce the resistivity contrast or the extent, or raise the kernel density";
        throw std::runtime_error(message.str());
    }
    return table;
}

struct Lu {
    std::vector<std::vector<double>> a;
    std::vector<std::size_t> perm;
    double min_pivot{std::numeric_limits<double>::infinity()};
    double max_pivot{};
};

struct IterativeSolution {
    std::vector<double> x;
    int iterations{};
};

double vector_norm(const std::vector<double>& x) {
    double value = 0.0;
    for (double v : x) value = std::hypot(value, v);
    return value;
}

IterativeSolution gmres(const std::vector<std::vector<double>>& a, const std::vector<double>& b,
                        const std::vector<double>& row_scale) {
    const std::size_t n = b.size();
    const int restart = std::min<int>(kGmresRestart, static_cast<int>(n));
    std::vector<double> x(n, 0.0), scaled_b(n);
    for (std::size_t i = 0; i < n; ++i) scaled_b[i] = row_scale[i] * b[i];
    const double rhs_norm = vector_norm(scaled_b);
    if (rhs_norm == 0.0) return {std::move(x), 0};
    int iterations = 0;
    while (iterations < kGmresMaxIterations) {
        std::vector<double> residual = scaled_b;
        for (std::size_t i = 0; i < n; ++i) {
            double ax = 0.0;
            for (std::size_t j = 0; j < n; ++j) ax += a[i][j] * x[j];
            residual[i] -= row_scale[i] * ax;
        }
        const double beta = vector_norm(residual);
        if (beta <= kGmresTolerance * rhs_norm) return {std::move(x), iterations};

        std::vector<std::vector<double>> basis(static_cast<std::size_t>(restart + 1), std::vector<double>(n));
        for (std::size_t i = 0; i < n; ++i) basis[0][i] = residual[i] / beta;
        std::vector<std::vector<double>> h(static_cast<std::size_t>(restart + 1), std::vector<double>(static_cast<std::size_t>(restart), 0.0));
        std::vector<double> cosine(static_cast<std::size_t>(restart)), sine(static_cast<std::size_t>(restart));
        std::vector<double> g(static_cast<std::size_t>(restart + 1), 0.0);
        g[0] = beta;
        int used = 0;
        bool converged = false;
        for (int j = 0; j < restart && iterations < kGmresMaxIterations; ++j, ++iterations) {
            std::vector<double> w(n, 0.0);
            for (std::size_t i = 0; i < n; ++i) {
                double value = 0.0;
                for (std::size_t k = 0; k < n; ++k) value += a[i][k] * basis[static_cast<std::size_t>(j)][k];
                w[i] = row_scale[i] * value;
            }
            for (int i = 0; i <= j; ++i) {
                double projection = 0.0;
                for (std::size_t k = 0; k < n; ++k) projection += w[k] * basis[static_cast<std::size_t>(i)][k];
                h[static_cast<std::size_t>(i)][static_cast<std::size_t>(j)] = projection;
                for (std::size_t k = 0; k < n; ++k) w[k] -= projection * basis[static_cast<std::size_t>(i)][k];
            }
            const double next_norm = vector_norm(w);
            h[static_cast<std::size_t>(j + 1)][static_cast<std::size_t>(j)] = next_norm;
            if (next_norm > 0.0)
                for (std::size_t k = 0; k < n; ++k) basis[static_cast<std::size_t>(j + 1)][k] = w[k] / next_norm;
            for (int i = 0; i < j; ++i) {
                const double upper = h[static_cast<std::size_t>(i)][static_cast<std::size_t>(j)];
                const double lower = h[static_cast<std::size_t>(i + 1)][static_cast<std::size_t>(j)];
                h[static_cast<std::size_t>(i)][static_cast<std::size_t>(j)] = cosine[static_cast<std::size_t>(i)] * upper + sine[static_cast<std::size_t>(i)] * lower;
                h[static_cast<std::size_t>(i + 1)][static_cast<std::size_t>(j)] = -sine[static_cast<std::size_t>(i)] * upper + cosine[static_cast<std::size_t>(i)] * lower;
            }
            const double diagonal = h[static_cast<std::size_t>(j)][static_cast<std::size_t>(j)];
            const double subdiagonal = h[static_cast<std::size_t>(j + 1)][static_cast<std::size_t>(j)];
            const double denominator = std::hypot(diagonal, subdiagonal);
            cosine[static_cast<std::size_t>(j)] = denominator == 0.0 ? 1.0 : diagonal / denominator;
            sine[static_cast<std::size_t>(j)] = denominator == 0.0 ? 0.0 : subdiagonal / denominator;
            h[static_cast<std::size_t>(j)][static_cast<std::size_t>(j)] = denominator;
            h[static_cast<std::size_t>(j + 1)][static_cast<std::size_t>(j)] = 0.0;
            g[static_cast<std::size_t>(j + 1)] = -sine[static_cast<std::size_t>(j)] * g[static_cast<std::size_t>(j)];
            g[static_cast<std::size_t>(j)] *= cosine[static_cast<std::size_t>(j)];
            used = j + 1;
            if (std::abs(g[static_cast<std::size_t>(j + 1)]) <= kGmresTolerance * rhs_norm || denominator == 0.0) {
                converged = true;
                ++iterations;
                break;
            }
        }
        std::vector<double> y(static_cast<std::size_t>(used), 0.0);
        for (int i = used; i-- > 0;) {
            double value = g[static_cast<std::size_t>(i)];
            for (int j = i + 1; j < used; ++j) value -= h[static_cast<std::size_t>(i)][static_cast<std::size_t>(j)] * y[static_cast<std::size_t>(j)];
            const double diagonal = h[static_cast<std::size_t>(i)][static_cast<std::size_t>(i)];
            if (std::abs(diagonal) < 1e-30) throw std::runtime_error("iterative solver encountered a singular Krylov system");
            y[static_cast<std::size_t>(i)] = value / diagonal;
        }
        for (int j = 0; j < used; ++j)
            for (std::size_t i = 0; i < n; ++i) x[i] += basis[static_cast<std::size_t>(j)][i] * y[static_cast<std::size_t>(j)];
        if (converged) {
            std::vector<double> check = scaled_b;
            for (std::size_t i = 0; i < n; ++i) {
                double ax = 0.0;
                for (std::size_t j = 0; j < n; ++j) ax += a[i][j] * x[j];
                check[i] -= row_scale[i] * ax;
            }
            if (vector_norm(check) <= kGmresTolerance * rhs_norm) return {std::move(x), iterations};
        }
    }
    throw std::runtime_error("iterative solver did not converge within 800 GMRES iterations");
}

Lu factor(std::vector<std::vector<double>> a) {
    const std::size_t n = a.size();
    Lu lu{std::move(a), std::vector<std::size_t>(n)};
    for (std::size_t i = 0; i < n; ++i) lu.perm[i] = i;
    for (std::size_t col = 0; col < n; ++col) {
        std::size_t pivot = col;
        for (std::size_t row = col + 1; row < n; ++row)
            if (std::abs(lu.a[row][col]) > std::abs(lu.a[pivot][col])) pivot = row;
        const double magnitude = std::abs(lu.a[pivot][col]);
        if (!(magnitude > 0.0) || !std::isfinite(magnitude))
            throw std::runtime_error("singular electrode system (zero pivot)");
        lu.min_pivot = std::min(lu.min_pivot, magnitude);
        lu.max_pivot = std::max(lu.max_pivot, magnitude);
        std::swap(lu.a[pivot], lu.a[col]);
        std::swap(lu.perm[pivot], lu.perm[col]);
        for (std::size_t row = col + 1; row < n; ++row) {
            const double factor = lu.a[row][col] / lu.a[col][col];
            lu.a[row][col] = factor;
            if (factor == 0.0) continue;
            for (std::size_t j = col + 1; j < n; ++j) lu.a[row][j] -= factor * lu.a[col][j];
        }
    }
    return lu;
}

std::vector<double> lu_solve(const Lu& lu, const std::vector<double>& b) {
    const std::size_t n = b.size();
    std::vector<double> x(n);
    for (std::size_t i = 0; i < n; ++i) {
        double v = b[lu.perm[i]];
        for (std::size_t j = 0; j < i; ++j) v -= lu.a[i][j] * x[j];
        x[i] = v;
    }
    for (std::size_t i = n; i-- > 0;) {
        double v = x[i];
        for (std::size_t j = i + 1; j < n; ++j) v -= lu.a[i][j] * x[j];
        x[i] = v / lu.a[i][i];
    }
    return x;
}

// Solves A^T x = b with the same factorisation (P A = L U).
std::vector<double> lu_solve_transpose(const Lu& lu, const std::vector<double>& b) {
    const std::size_t n = b.size();
    std::vector<double> y(n), x(n);
    for (std::size_t i = 0; i < n; ++i) {
        double v = b[i];
        for (std::size_t j = 0; j < i; ++j) v -= lu.a[j][i] * y[j];
        y[i] = v / lu.a[i][i];
    }
    for (std::size_t i = n; i-- > 0;) {
        double v = y[i];
        for (std::size_t j = i + 1; j < n; ++j) v -= lu.a[j][i] * x[j];
        x[i] = v;
    }
    std::vector<double> result(n);
    for (std::size_t i = 0; i < n; ++i) result[lu.perm[i]] = x[i];
    return result;
}

// Hager/Higham estimate of the 1-norm condition number.
double condition_1norm(const std::vector<std::vector<double>>& a, const Lu& lu) {
    const std::size_t n = a.size();
    double norm_a = 0.0;
    for (std::size_t j = 0; j < n; ++j) {
        double column = 0.0;
        for (std::size_t i = 0; i < n; ++i) column += std::abs(a[i][j]);
        norm_a = std::max(norm_a, column);
    }
    std::vector<double> x(n, 1.0 / static_cast<double>(n));
    double estimate = 0.0;
    for (int iteration = 0; iteration < 5; ++iteration) {
        const auto y = lu_solve(lu, x);
        estimate = 0.0;
        for (double v : y) estimate += std::abs(v);
        std::vector<double> sign(n);
        for (std::size_t i = 0; i < n; ++i) sign[i] = y[i] >= 0.0 ? 1.0 : -1.0;
        const auto z = lu_solve_transpose(lu, sign);
        std::size_t best = 0;
        double zx = 0.0;
        for (std::size_t i = 0; i < n; ++i) {
            zx += z[i] * x[i];
            if (std::abs(z[i]) > std::abs(z[best])) best = i;
        }
        if (std::abs(z[best]) <= zx) break;
        std::fill(x.begin(), x.end(), 0.0);
        x[best] = 1.0;
    }
    return norm_a * estimate;
}

void validate_geometry(const std::vector<Segment>& segments, bool explicit_topology) {
    for (std::size_t i = 0; i < segments.size(); ++i) {
        for (std::size_t j = i + 1; j < segments.size(); ++j) {
            const auto& p = segments[i];
            const auto& q = segments[j];
            const double tolerance = 1e-9 * std::max(p.length, q.length);
            const bool same_ends = (norm(p.a - q.a) <= tolerance && norm(p.b - q.b) <= tolerance) ||
                                   (norm(p.a - q.b) <= tolerance && norm(p.b - q.a) <= tolerance);
            if (same_ends) throw std::runtime_error("duplicate segment geometry: " + p.id + " and " + q.id);
            const Vec3 u = (p.b - p.a) * (1.0 / p.length), v = (q.b - q.a) * (1.0 / q.length);
            double s = 0.0, t = 0.0;
            const double gap = segment_distance(p.a, p.b, q.a, q.b, s, t);
            if (std::abs(std::abs(dot(u, v)) - 1.0) < 1e-9 && gap <= p.radius + q.radius) {
                const double t0 = dot(q.a - p.a, u), t1 = dot(q.b - p.a, u);
                const double overlap = std::min(p.length, std::max(t0, t1)) - std::max(0.0, std::min(t0, t1));
                if (overlap > tolerance)
                    throw std::runtime_error("overlapping collinear segments: " + p.id + " and " + q.id);
            }
            if (!explicit_topology && p.group != q.group && gap <= p.radius + q.radius)
                throw std::runtime_error("segments of different groups touch or cross: " + p.id + " and " + q.id +
                                         " (bond them in one group or separate them)");
        }
    }
}

std::vector<Segment> read_segments(std::size_t count, std::map<std::string, Group>& groups) {
    std::string line;
    std::vector<Segment> segments;
    segments.reserve(count);
    std::set<std::string> ids;
    for (std::size_t i = 0; i < count; ++i) {
        if (!std::getline(std::cin, line)) throw std::runtime_error("missing segment row");
        auto f = fields(line);
        if (f.size() != 10) throw std::runtime_error("segment row must contain id group kind x1 y1 z1 x2 y2 z2 radius");
        require_id(f[0], "segment id"); require_id(f[1], "group id"); require_id(f[2], "element kind");
        if (!ids.insert(f[0]).second) throw std::runtime_error("duplicate segment id: " + f[0]);
        Segment s{f[0], f[1], f[2],
                  {number(f[3], "x1"), number(f[4], "y1"), number(f[5], "z1")},
                  {number(f[6], "x2"), number(f[7], "y2"), number(f[8], "z2")},
                  number(f[9], "radius"), 0.0};
        require_coordinate(s.a, "segment " + s.id);
        require_coordinate(s.b, "segment " + s.id);
        s.length = norm(s.b - s.a);
        if (s.radius < kMinRadiusM || s.radius > kMaxRadiusM)
            throw std::runtime_error("segment " + s.id + " radius must be between 1e-4 and 0.5 m");
        if (s.length < kMinLengthToRadius * s.radius)
            throw std::runtime_error("segment " + s.id + " must be at least 5 radii long (thin-wire model)");
        if (s.a.z > 0 || s.b.z > 0) throw std::runtime_error("segment " + s.id + " must be at or below z=0");
        if (-0.5 * (s.a.z + s.b.z) < s.radius)
            throw std::runtime_error("segment " + s.id + " lies on the surface; its mid-point must be buried at least one radius");
        segments.push_back(s);
        groups.try_emplace(s.group, Group{});
    }
    return segments;
}

void run_request() {
    const auto request_started = SteadyClock::now();
    std::string line;
    if (!std::getline(std::cin, line) || (line != kProtocol && line != kProtocolV4 && line != kProtocolV5))
        throw std::runtime_error(std::string("expected ") + kProtocol + ", " + kProtocolV4 + " or " + kProtocolV5 + " protocol header");
    const std::string response_protocol = line;
    const bool multiple_scenarios = response_protocol == kProtocolV5;
    const bool explicit_topology = response_protocol == kProtocolV4 || multiple_scenarios;
    if (!std::getline(std::cin, line)) throw std::runtime_error("missing soil and segment count");
    auto header = fields(line);
    Soil soil;
    std::vector<std::string> warnings;
    int kernel_density = 0;
    std::vector<double> requested_layers, requested_thicknesses;  // n-layer request as given
    if (header.empty()) throw std::runtime_error("missing soil line");
    bool has_quadrature_tolerance =
        (header[0] == "homogeneous" && header.size() == 4) ||
        (header[0] == "two-layer" && header.size() == 6);
    if (header[0] == "n-layer" && header.size() >= 2)
        has_quadrature_tolerance = header.size() == 2 * count_value(header[1], "layer count", kMaxLayers) + 5;
    if (header[0] == "homogeneous" && (header.size() == 3 || header.size() == 4)) {
        soil.rho1 = soil.rho2 = number(header[1], "soil resistivity");
    } else if (header[0] == "two-layer" && (header.size() == 5 || header.size() == 6)) {
        soil.rho1 = number(header[1], "upper-layer resistivity");
        soil.rho2 = number(header[2], "lower-layer resistivity");
        soil.h = number(header[3], "upper-layer thickness");
        if (soil.h < kMinLayerThicknessM || soil.h > kMaxDepthM)
            throw std::runtime_error("upper-layer thickness must be between 0.01 and 1000 m");
        soil.layered = soil.rho1 != soil.rho2;
        soil.interfaces = {soil.h};
        if (!soil.layered) warnings.push_back("equal-layers\ttwo-layer soil with equal resistivities solved as homogeneous");
    } else if (header.size() >= 2 && header[0] == "n-layer") {
        const std::size_t count = count_value(header[1], "layer count", kMaxLayers);
        if (count == 0) throw std::runtime_error("invalid layer count (between 1 and 8 layers)");
        if (header.size() != 2 * count + 4 && header.size() != 2 * count + 5)
            throw std::runtime_error("n-layer soil line must be 'n-layer <count> <rho_1> <thickness_1> ... "
                                     "<rho_count> inf <kernel_density> <segments>'");
        std::vector<double> rhos, thicknesses;
        for (std::size_t layer = 0; layer < count; ++layer) {
            const double value = number(header[2 + 2 * layer], "layer resistivity");
            if (value <= 0 || value > kMaxResistivityOhmM)
                throw std::runtime_error("soil layer " + std::to_string(layer + 1) + " resistivity must be in (0, 1e6] ohm-m");
            rhos.push_back(value);
            const std::string& thickness = header[3 + 2 * layer];
            if (layer + 1 == count) {
                if (thickness != "inf") throw std::runtime_error("the bottom soil layer must be a half-space (thickness 'inf')");
            } else {
                if (thickness == "inf") throw std::runtime_error("only the bottom soil layer may be a half-space");
                const double value_m = number(thickness, "layer thickness");
                if (value_m < kMinLayerThicknessM || value_m > kMaxDepthM)
                    throw std::runtime_error("soil layer " + std::to_string(layer + 1) + " thickness must be between 0.01 and 1000 m");
                thicknesses.push_back(value_m);
            }
        }
        const double density = number(header[2 * count + 2], "kernel density");
        if (std::floor(density) != density || density < kMinKernelDensity || density > kMaxKernelDensity)
            throw std::runtime_error("kernel density must be an integer between 6 and 12 images per decade");
        kernel_density = static_cast<int>(density);
        const auto [low, high] = std::minmax_element(rhos.begin(), rhos.end());
        if (*high / *low > kMaxLayerContrast)
            throw std::runtime_error("n-layer resistivity contrast (max/min) exceeds 1e4; outside the validated kernel range");
        // Adjacent layers with the same resistivity are one physical layer: merge them exactly.
        soil.rhos = {rhos[0]};
        double depth = 0.0, merged_thickness = 0.0;
        for (std::size_t layer = 0; layer + 1 < count; ++layer) {
            depth += thicknesses[layer];
            merged_thickness += thicknesses[layer];
            if (rhos[layer + 1] != rhos[layer]) {
                soil.rhos.push_back(rhos[layer + 1]);
                soil.thicknesses.push_back(merged_thickness);
                soil.interfaces.push_back(depth);
                merged_thickness = 0.0;
            }
        }
        if (soil.rhos.size() < count)
            warnings.push_back("equal-layers\tadjacent layers with equal resistivity merged into " +
                               std::to_string(soil.rhos.size()) + " layer(s)");
        soil.rho1 = soil.rhos[0];
        soil.rho2 = soil.rhos.size() > 1 ? soil.rhos[1] : soil.rhos[0];
        soil.nlayer = soil.rhos.size() > 1;
        soil.layered = soil.nlayer;
        requested_layers = std::move(rhos);
        requested_thicknesses = std::move(thicknesses);
    } else {
        throw std::runtime_error("soil line must be 'homogeneous <rho> <segments>', "
                                 "'two-layer <rho_upper> <rho_lower> <upper_thickness> <segments>' or "
                                 "'n-layer <count> <rho_1> <thickness_1> ... <rho_count> inf <kernel_density> <segments>'");
    }
    for (double value : {soil.rho1, soil.rho2})
        if (value <= 0 || value > kMaxResistivityOhmM) throw std::runtime_error("soil resistivity must be in (0, 1e6] ohm-m");
    soil.k = (soil.rho2 - soil.rho1) / (soil.rho2 + soil.rho1);
    const double rho = soil.rho1;
    const std::size_t segment_index = header.size() - (has_quadrature_tolerance ? 2 : 1);
    if (has_quadrature_tolerance) {
        gQuadratureTolerance = number(header.back(), "quadrature tolerance");
        if (gQuadratureTolerance < kMinQuadratureTolerance || gQuadratureTolerance > kMaxQuadratureTolerance)
            throw std::runtime_error("quadrature tolerance must be between 1e-12 and 1e-4");
    } else gQuadratureTolerance = kDefaultQuadratureTolerance;
    gQuadratureEvaluations = gQuadratureRefinements = gQuadratureMaxDepth = 0;
    gQuadratureInteractions = gQuadratureMaxEvaluationsPerInteraction = 0;
    const std::size_t segment_count = count_value(header[segment_index], "segment count", kMaxSegments);
    if (segment_count == 0) throw std::runtime_error("segment count must be positive");

    std::map<std::string, Group> groups;
    const auto segments = read_segments(segment_count, groups);

    std::vector<ElectricalConnection> connections;
    const auto read_connections = [&]() {
      if (explicit_topology) {
        std::set<std::string> connection_ids;
        const auto read_connection_section = [&](const char* label, bool bond) {
            if (!std::getline(std::cin, line)) throw std::runtime_error(std::string("missing ") + label + " section");
            const auto section = fields(line);
            if (section.size() != 2 || section[0] != label)
                throw std::runtime_error(std::string("expected ") + label + " <count>");
            const std::size_t count = count_value(section[1], "connection count", 100000);
            for (std::size_t i = 0; i < count; ++i) {
                if (!std::getline(std::cin, line)) throw std::runtime_error("missing connection row");
                const auto f = fields(line);
                if (f.size() != (bond ? 3u : 4u))
                    throw std::runtime_error(bond ? "bond row must contain id group_a group_b" :
                                             "resistor row must contain id group_a group_b resistance_ohm");
                require_id(f[0], "connection id"); require_id(f[1], "connection group"); require_id(f[2], "connection group");
                if (!connection_ids.insert(f[0]).second) throw std::runtime_error("duplicate connection id: " + f[0]);
                if (f[1] == f[2]) throw std::runtime_error("connection must join two different groups: " + f[0]);
                if (!groups.count(f[1]) || !groups.count(f[2])) throw std::runtime_error("connection references a group without electrode segments: " + f[0]);
                double resistance = 0.0;
                if (!bond) {
                    resistance = number(f[3], "connection resistance");
                    if (resistance < 1e-9 || resistance > 1e9)
                        throw std::runtime_error("connection resistance must be between 1e-9 and 1e9 ohm");
                }
                connections.push_back({f[0], f[1], f[2], resistance});
            }
        };
        read_connection_section("BOND", true);
        read_connection_section("RESISTOR", false);
      }
    };

    std::vector<ExcitationScenario> scenarios;
    if (multiple_scenarios) {
        read_connections();
        if (!std::getline(std::cin, line)) throw std::runtime_error("missing SCENARIOS section");
        const auto section = fields(line);
        if (section.size() != 2 || section[0] != "SCENARIOS") throw std::runtime_error("expected SCENARIOS <count>");
        const std::size_t scenario_count = count_value(section[1], "scenario count", kMaxScenarioCount);
        if (scenario_count == 0) throw std::runtime_error("scenario count must be positive");
        std::set<std::string> scenario_ids;
        for (std::size_t s = 0; s < scenario_count; ++s) {
            if (!std::getline(std::cin, line)) throw std::runtime_error("missing scenario header");
            const auto f = fields(line);
            if (f.size() != 3 || f[0] != "SCENARIO") throw std::runtime_error("scenario header must contain SCENARIO id injection_count");
            require_id(f[1], "scenario id");
            if (!scenario_ids.insert(f[1]).second) throw std::runtime_error("duplicate scenario id: " + f[1]);
            const std::size_t injection_count = count_value(f[2], "scenario injection count", groups.size());
            ExcitationScenario scenario{f[1], {}};
            for (std::size_t i = 0; i < injection_count; ++i) {
                if (!std::getline(std::cin, line)) throw std::runtime_error("missing scenario injection row");
                const auto injection = fields(line);
                if (injection.size() != 3) throw std::runtime_error("injection row must contain group id, current in amperes and origin");
                require_id(injection[0], "injection group id"); require_id(injection[2], "injection origin");
                if (!groups.count(injection[0])) throw std::runtime_error("injection group has no electrode segments: " + injection[0]);
                const double current = number(injection[1], "injected current");
                if (std::abs(current) > kMaxCurrentA) throw std::runtime_error("injected current magnitude exceeds 1e6 A");
                if (!scenario.injections.emplace(injection[0], std::make_pair(current, injection[2])).second)
                    throw std::runtime_error("duplicate group injection in scenario: " + injection[0]);
            }
            scenarios.push_back(std::move(scenario));
        }
    } else {
        if (!std::getline(std::cin, line)) throw std::runtime_error("missing injection count");
        const auto injection_header = fields(line);
        if (injection_header.size() != 1) throw std::runtime_error("injection count line must have one value");
        const std::size_t injection_count = count_value(injection_header[0], "injection count", groups.size());
        ExcitationScenario scenario{"default", {}};
        for (std::size_t i = 0; i < injection_count; ++i) {
            if (!std::getline(std::cin, line)) throw std::runtime_error("missing injection row");
            const auto f = fields(line);
            if (f.size() != 3) throw std::runtime_error("injection row must contain group id, current in amperes and origin");
            require_id(f[0], "injection group id"); require_id(f[2], "injection origin");
            if (!groups.count(f[0])) throw std::runtime_error("injection group has no electrode segments: " + f[0]);
            const double current = number(f[1], "injected current");
            if (std::abs(current) > kMaxCurrentA) throw std::runtime_error("injected current magnitude exceeds 1e6 A");
            if (!scenario.injections.emplace(f[0], std::make_pair(current, f[2])).second)
                throw std::runtime_error("duplicate group injection: " + f[0]);
        }
        read_connections();
        scenarios.push_back(std::move(scenario));
    }

    if (!std::getline(std::cin, line)) throw std::runtime_error("missing point count");
    const auto point_header = fields(line);
    if (point_header.size() != 1) throw std::runtime_error("point count line must have one value");
    const std::size_t point_count = count_value(point_header[0], "point count", kMaxPoints);
    if (static_cast<double>(point_count) * static_cast<double>(segment_count) > kMaxPointSegmentWork)
        throw std::runtime_error("points x segments exceeds 2e7; split the surface query into batches");
    const double scenario_rows = static_cast<double>(scenarios.size()) *
        static_cast<double>(segment_count + point_count + groups.size() + connections.size() + 128);
    if (scenario_rows > kMaxScenarioResultRows)
        throw std::runtime_error("multi-scenario response exceeds the supported output row budget");
    std::vector<Point> points;
    points.reserve(point_count);
    std::set<std::string> point_ids;
    for (std::size_t i = 0; i < point_count; ++i) {
        if (!std::getline(std::cin, line)) throw std::runtime_error("missing point row");
        auto f = fields(line);
        if (f.size() != 4) throw std::runtime_error("point row must contain id x y z");
        require_id(f[0], "point id");
        if (!point_ids.insert(f[0]).second) throw std::runtime_error("duplicate point id: " + f[0]);
        Point p{f[0], {number(f[1], "point x"), number(f[2], "point y"), number(f[3], "point z")}};
        require_coordinate(p.p, "point " + p.id);
        if (p.p.z < 0) throw std::runtime_error("potential query points must be at or above z=0");
        points.push_back(p);
    }
    if (!std::getline(std::cin, line) || line != "END") throw std::runtime_error("expected END protocol marker");
    validate_geometry(segments, explicit_topology);
    ImageTable table;
    const auto kernel_started = SteadyClock::now();
    double kernel_setup_ms = 0.0;
    std::vector<int> layers(segments.size(), 0);
    double matrix_image_work = 0.0, point_image_work = 0.0;
    if (soil.layered) {
        double max_depth = 0.0, low_x = 0.0, high_x = 0.0, low_y = 0.0, high_y = 0.0;
        bool first = true;
        const auto extend = [&](const Vec3& p) {
            if (first) { low_x = high_x = p.x; low_y = high_y = p.y; first = false; }
            low_x = std::min(low_x, p.x); high_x = std::max(high_x, p.x);
            low_y = std::min(low_y, p.y); high_y = std::max(high_y, p.y);
        };
        for (std::size_t i = 0; i < segments.size(); ++i) {
            const auto& s = segments[i];
            const double top = std::min(-s.a.z, -s.b.z), bottom = std::max(-s.a.z, -s.b.z);
            for (double depth : soil.interfaces) {
                const double tolerance = 1e-9 * std::max(1.0, depth);
                if (top < depth - tolerance && bottom > depth + tolerance) {
                    std::ostringstream message;
                    message << "segment " << s.id << " crosses the soil interface at " << depth
                            << " m; split it at the interface depth (the Python client does this automatically)";
                    throw std::runtime_error(message.str());
                }
            }
            max_depth = std::max(max_depth, bottom);
            extend(s.a); extend(s.b);
            layers[i] = layer_of(s, soil);
        }
        for (const auto& point : points) {
            if (soil.nlayer && point.p.z != 0.0)
                throw std::runtime_error("n-layer potential query points must lie on the surface (z = 0); point " + point.id);
            extend(point.p); max_depth = std::max(max_depth, std::abs(point.p.z));
        }
        const double extent = std::max(1.0, std::hypot(high_x - low_x, high_y - low_y) + 2.0 * max_depth);
        const std::size_t layer_count = soil.nlayer ? soil.rhos.size() : 2;
        std::vector<double> per_layer(layer_count, 0.0);
        for (int layer : layers) per_layer[static_cast<std::size_t>(layer)] += 1.0;
        if (soil.nlayer) {
            std::vector<bool> sources(layer_count, false), observers(layer_count, false);
            for (std::size_t layer = 0; layer < layer_count; ++layer) sources[layer] = observers[layer] = per_layer[layer] > 0.0;
            if (!points.empty()) observers[0] = true;
            // Every image lies within 2 d_{N-1} plus the deepest fitted image of the pair's direct path.
            table = nlayer_table(soil, sources, observers, kernel_density, extent + 2.0 * soil.interfaces.back());
            if (soil.kernel.error_bound > kKernelWarnErrorBound) {
                std::ostringstream message;
                message << "kernel-error\tn-layer kernel relative error bound " << soil.kernel.error_bound << " above 1e-5";
                warnings.push_back(message.str());
            }
        } else {
            choose_image_terms(soil, max_depth, extent);
            table = image_table(soil);
        }
        double matrix_work = 0.0, point_work = 0.0;
        for (std::size_t target = 0; target < layer_count; ++target)
            for (std::size_t source = 0; source < layer_count; ++source)
                matrix_work += per_layer[target] * per_layer[source] * static_cast<double>(table[source][target].size());
        for (std::size_t source = 0; source < layer_count; ++source)
            point_work += static_cast<double>(points.size()) * per_layer[source] * static_cast<double>(table[source][0].size());
        const std::string label = soil.nlayer ? "n-layer" : "two-layer";
        if (matrix_work > kMaxMatrixImageWork)
            throw std::runtime_error(label + " system needs more than 4e9 image evaluations; use fewer segments");
        if (point_work > kMaxPointImageWork)
            throw std::runtime_error(label + " surface query needs more than 4e9 image evaluations; split the "
                                     "points into smaller batches");
        matrix_image_work = matrix_work;
        point_image_work = point_work;
    }
    kernel_setup_ms = elapsed_ms(kernel_started);

    // Contract ideal bonds, then retain separate nodes for finite resistors.
    const auto assembly_started = SteadyClock::now();
    std::vector<std::string> group_ids;
    std::map<std::string, std::size_t> group_index;
    std::map<std::string, std::string> parent;
    for (const auto& [id, unused] : groups) { (void)unused; parent[id] = id; }
    const auto root = [&](const std::string& id) {
        std::string current = id;
        while (parent.at(current) != current) current = parent.at(current);
        return current;
    };
    for (const auto& connection : connections) if (connection.resistance == 0.0) {
        const std::string a = root(connection.a), b = root(connection.b);
        if (a != b) parent[std::max(a, b)] = std::min(a, b);
    }
    std::map<std::string, std::size_t> node_index;
    for (const auto& [id, unused] : groups) {
        (void)unused;
        const std::string representative = root(id);
        if (!node_index.count(representative)) {
            node_index[representative] = group_ids.size();
            group_ids.push_back(representative);
        }
        group_index[id] = node_index.at(representative);
    }
    const std::size_t n = segments.size(), g = group_ids.size(), size = n + g;
    std::vector<std::vector<double>> matrix(size, std::vector<double>(size, 0.0));
    std::vector<double> rhs(size, 0.0);
    InteractionCounts interaction_counts;
    std::size_t reciprocal_entries_reused = 0;
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = 0; j < n; ++j) {
            // With equal soft-core radii the Galerkin Green coefficient is reciprocal. Reuse
            // the already assembled transposed entry; unequal radii keep both directed values.
            if (j < i && segments[i].radius == segments[j].radius) {
                matrix[i][j] = matrix[j][i];
                ++reciprocal_entries_reused;
                continue;
            }
            bool near_interface = false;
            const InteractionKind interaction = classify_interaction(
                segments[i], segments[j], i == j, soil.interfaces, &near_interface);
            if (i <= j) {
                ++interaction_counts.categories[interaction_index(interaction)];
                if (near_interface) ++interaction_counts.near_interface;
            }
            matrix[i][j] = soil.layered
                ? layered_coefficient(segments[i], layers[i], segments[j], layers[j], i == j, interaction, table)
                : coefficient(segments[i], segments[j], i == j, interaction);
        }
        matrix[i][n + group_index.at(segments[i].group)] = -1.0;
    }
    for (std::size_t j = 0; j < n; ++j) matrix[n + group_index.at(segments[j].group)][j] = 1.0;
    const double factor_v = rho / (4.0 * kPi);
    for (const auto& connection : connections) if (connection.resistance > 0.0) {
        const std::size_t a = group_index.at(connection.a), b = group_index.at(connection.b);
        if (a == b) throw std::runtime_error("resistor endpoints are already joined by ideal bonds: " + connection.id);
        const double conductance = factor_v / connection.resistance;
        matrix[n + a][n + a] += conductance;
        matrix[n + b][n + b] += conductance;
        matrix[n + a][n + b] -= conductance;
        matrix[n + b][n + a] -= conductance;
    }

    std::vector<double> row_scale(size, 1.0);
    for (std::size_t i = 0; i < size; ++i) {
        double row_sum = 0.0;
        for (double value : matrix[i]) row_sum += std::abs(value);
        if (row_sum > 0.0) row_scale[i] = 1.0 / row_sum;
    }
    const double assembly_ms = elapsed_ms(assembly_started);
    double condition = -1.0, pivot_ratio = -1.0;
    double factorization_ms = 0.0, condition_estimation_ms = 0.0;
    const bool iterative_solver = n > kDirectSolverMaxSegments;
    std::optional<Lu> lu;
    if (iterative_solver) {
        warnings.push_back("iterative-solver\tGMRES with row equilibration; 1-norm condition and LU pivot ratio are not estimated");
    } else {
        const auto factor_started = SteadyClock::now();
        lu = factor(matrix);
        factorization_ms = elapsed_ms(factor_started);
        const auto condition_started = SteadyClock::now();
        condition = condition_1norm(matrix, *lu);
        condition_estimation_ms = elapsed_ms(condition_started);
        pivot_ratio = lu->min_pivot / lu->max_pivot;
    }
    if (!iterative_solver && (!std::isfinite(condition) || condition > kMaxCondition))
        throw std::runtime_error("ill-conditioned electrode system (1-norm condition estimate above 1e13)");
    if (!iterative_solver && condition > kWarnCondition) warnings.push_back("ill-conditioned\t1-norm condition estimate above 1e10");

    std::cout << std::setprecision(17) << response_protocol << "\tOK\n";
    const auto common_warnings = warnings;
    for (const auto& scenario : scenarios) {
        warnings = common_warnings;
        std::fill(rhs.begin(), rhs.end(), 0.0);
        for (auto& [id, group] : groups) {
            (void)id;
            group.injected_current = 0.0;
            group.origin = "none";
            group.net_current = 0.0;
        }
        double total_injection = 0.0;
        for (const auto& [id, input] : scenario.injections) {
            groups[id].injected_current = input.first;
            groups[id].origin = input.second;
            total_injection += std::abs(input.first);
            rhs[n + group_index.at(id)] += input.first;
        }
        if (total_injection == 0.0) warnings.push_back("no-injection\tall group currents are zero; every potential is zero");
        const auto solve_started = SteadyClock::now();
        std::vector<double> solution;
        int solver_iterations = 0;
        if (iterative_solver) {
            auto solved = gmres(matrix, rhs, row_scale);
            solution = std::move(solved.x);
            solver_iterations = solved.iterations;
        } else {
            solution = lu_solve(*lu, rhs);
        }
        const double solve_ms = elapsed_ms(solve_started);
        double residual = 0.0, norm_a = 0.0, norm_x = 0.0, norm_b = 0.0;
    for (std::size_t i = 0; i < size; ++i) {
        double row_value = -rhs[i], row_norm = 0.0;
        for (std::size_t j = 0; j < size; ++j) { row_value += matrix[i][j] * solution[j]; row_norm += std::abs(matrix[i][j]); }
        residual = std::max(residual, std::abs(row_value));
        norm_a = std::max(norm_a, row_norm);
        norm_x = std::max(norm_x, std::abs(solution[i]));
        norm_b = std::max(norm_b, std::abs(rhs[i]));
    }
    const double scale = norm_a * norm_x + norm_b;
    const double backward_error = scale > 0.0 ? residual / scale : 0.0;
    for (double v : solution)
        if (!std::isfinite(v)) throw std::runtime_error("solver produced a non-finite result");
    if (backward_error > kMaxBackwardError)
        throw std::runtime_error("solver residual above acceptance limit");

    double max_balance_error = 0.0;
    std::vector<double> node_potential(g, 0.0), node_injection(g, 0.0), node_leakage(g, 0.0);
    for (const auto& [id, group] : groups) {
        const std::size_t gi = group_index.at(id);
        node_potential[gi] = factor_v * solution[n + gi];
        node_injection[gi] += group.injected_current;
    }
    for (std::size_t gi = 0; gi < g; ++gi) {
        double low = std::numeric_limits<double>::infinity(), high = -low;
        for (std::size_t i = 0; i < n; ++i) {
            if (group_index.at(segments[i].group) != gi) continue;
            node_leakage[gi] += solution[i];
            double v = 0.0;
            for (std::size_t j = 0; j < n; ++j) v += matrix[i][j] * solution[j];
            low = std::min(low, v); high = std::max(high, v);
        }
        for (auto& [id, group] : groups) if (group_index.at(id) == gi) {
            group.potential = node_potential[gi];
            group.potential_spread = factor_v * (high - low);
        }
    }
    std::vector<double> node_residual(g, 0.0);
    for (std::size_t gi = 0; gi < g; ++gi) node_residual[gi] = node_leakage[gi] - node_injection[gi];
    for (const auto& connection : connections) if (connection.resistance > 0.0) {
        const std::size_t a = group_index.at(connection.a), b = group_index.at(connection.b);
        const double current = (node_potential[a] - node_potential[b]) / connection.resistance;
        node_residual[a] += current; node_residual[b] -= current;
    }
    for (std::size_t gi = 0; gi < g; ++gi)
        max_balance_error = std::max(max_balance_error, std::abs(node_residual[gi]) / std::max(1.0, total_injection));
    if (max_balance_error > kMaxRelativeBalanceError)
        throw std::runtime_error("current balance error above acceptance limit");

    if (multiple_scenarios) std::cout << "SCENARIO\t" << scenario.id << '\n';
    std::cout << "META\tprotocol\t" << response_protocol << '\n'
              << "META\tsolver_version\t" << kSolverVersion << '\n'
              << "META\tmethod\t" << (soil.nlayer ? kNLayerMethod : soil.layered ? kLayeredMethod : kMethod)
              << (iterative_solver ? ";gmres-row-equilibrated" : ";lu-partial-pivoting") << '\n'
              << "META\tassumptions\t"
              << (!requested_layers.empty() ? kNLayerAssumptions : soil.layered ? kLayeredAssumptions : kAssumptions) << '\n'
              << "META\tunits\t" << kUnits << '\n';
    if (!requested_layers.empty()) {
        const auto stack = [](const std::vector<double>& rhos, const std::vector<double>& thicknesses) {
            std::ostringstream text;
            text << std::setprecision(12);
            for (std::size_t layer = 0; layer < rhos.size(); ++layer) {
                if (layer) text << ';';
                text << rhos[layer] << ':';
                if (layer < thicknesses.size()) text << thicknesses[layer]; else text << "inf";
            }
            return text.str();
        };
        std::cout << "META\tsoil_model\tn-layer\n"
                  << "META\tsoil_layer_count\t" << requested_layers.size() << '\n'
                  << "META\tsoil_layers_resistivity_ohm_m_thickness_m\t" << stack(requested_layers, requested_thicknesses) << '\n'
                  << "META\tsoil_solved_layers\t" << stack(soil.nlayer ? soil.rhos : std::vector<double>{soil.rho1}, soil.thicknesses) << '\n'
                  << "META\tkernel_limits\tmax_layers=8;max_contrast=1e4;kernel_density=6..12;max_images_per_function=120;"
                     "max_error_bound=1e-4;max_amplification=1e6;max_spectral_evaluations=1e6;"
                     "max_matrix_image_work=4e9;max_point_image_work=4e9;min_thickness_m=0.01;max_thickness_m=1000\n";
    } else if (soil.layered)
        std::cout << "META\tsoil_model\ttwo-layer\n"
                  << "META\tsoil_upper_resistivity_ohm_m\t" << soil.rho1 << '\n'
                  << "META\tsoil_lower_resistivity_ohm_m\t" << soil.rho2 << '\n'
                  << "META\tsoil_upper_thickness_m\t" << soil.h << '\n'
                  << "META\tsoil_reflection_coefficient\t" << soil.k << '\n';
    else
        std::cout << "META\tsoil_model\thomogeneous\n"
                  << "META\tsoil_resistivity_ohm_m\t" << rho << '\n';
    std::cout << "META\tsegment_count\t" << n << '\n'
              << "META\tgroup_count\t" << groups.size() << '\n'
              << "META\telectrical_node_count\t" << g << '\n'
              << "META\tpoint_count\t" << points.size() << '\n';
    std::cout << "DIAG\tbackward_error\t" << backward_error << '\n'
              << "DIAG\tcondition_1norm_estimate\t" << condition << '\n'
              << "DIAG\tpivot_ratio\t" << pivot_ratio << '\n'
              << "DIAG\tsolver_iterations\t" << solver_iterations << '\n'
              << "DIAG\tmax_relative_balance_error\t" << max_balance_error << '\n'
              << "DIAG\tquadrature_tolerance\t" << gQuadratureTolerance << '\n'
              << "DIAG\tquadrature_evaluations\t" << gQuadratureEvaluations << '\n'
              << "DIAG\tquadrature_refinements\t" << gQuadratureRefinements << '\n'
              << "DIAG\tquadrature_max_depth\t" << gQuadratureMaxDepth << '\n'
              << "DIAG\tquadrature_interactions\t" << gQuadratureInteractions << '\n'
              << "DIAG\tquadrature_max_evaluations_per_interaction\t" << gQuadratureMaxEvaluationsPerInteraction << '\n'
              << "DIAG\tquadrature_converged\t1\n"
              << "DIAG\tprofile_kernel_setup_ms\t" << kernel_setup_ms << '\n'
              << "DIAG\tprofile_matrix_assembly_ms\t" << assembly_ms << '\n'
              << "DIAG\tprofile_factorization_ms\t" << factorization_ms << '\n'
              << "DIAG\tprofile_solve_ms\t" << solve_ms << '\n'
              << "DIAG\tprofile_condition_estimation_ms\t" << condition_estimation_ms << '\n';
    for (std::size_t i = 0; i < kInteractionNames.size(); ++i)
        std::cout << "DIAG\tinteraction_" << kInteractionNames[i] << "_pairs\t"
                  << interaction_counts.categories[i] << '\n';
    std::cout << "DIAG\tinteraction_near_interface_pairs\t" << interaction_counts.near_interface << '\n'
              << "DIAG\tmatrix_reciprocal_entries_reused\t" << reciprocal_entries_reused << '\n';
    if (soil.nlayer)
        std::cout << "DIAG\tkernel_density\t" << soil.kernel.density << '\n'
                  << "DIAG\tkernel_terms\t" << soil.kernel.terms << '\n'
                  << "DIAG\tkernel_functions\t" << soil.kernel.functions << '\n'
                  << "DIAG\tkernel_images_per_pair_max\t" << soil.kernel.max_images_per_pair << '\n'
                  << "DIAG\tkernel_lambda_samples\t" << soil.kernel.lambda_samples << '\n'
                  << "DIAG\tkernel_spectral_evaluations\t" << soil.kernel.spectral_evaluations << '\n'
                  << "DIAG\tkernel_image_depth_min_m\t" << soil.kernel.b_min << '\n'
                  << "DIAG\tkernel_image_depth_max_m\t" << soil.kernel.b_max << '\n'
                  << "DIAG\tkernel_error_bound\t" << soil.kernel.error_bound << '\n'
                  << "DIAG\tkernel_max_amplification\t" << soil.kernel.max_amplification << '\n'
                  << "DIAG\tmatrix_image_work\t" << matrix_image_work << '\n'
                  << "DIAG\tpoint_image_work\t" << point_image_work << '\n';
    else
        std::cout << "DIAG\timage_terms\t" << soil.terms << '\n'
                  << "DIAG\timage_series_tail_bound\t" << soil.tail_bound << '\n';
    for (const auto& warning : warnings) std::cout << "WARNING\t" << warning << '\n';
    for (std::size_t i = 0; i < n; ++i) std::cout << "SEGMENT\t" << segments[i].id << '\t' << solution[i] << '\n';
    for (const auto& [id, group] : groups) {
        const std::size_t gi = group_index.at(id);
        const double potential = node_potential[gi];
        std::cout << "GROUP\t" << id << '\t' << group.injected_current << '\t' << potential << '\t';
        if (std::abs(group.injected_current) > 1e-12) std::cout << potential / group.injected_current;
        else std::cout << "null";
        std::cout << '\t' << group.origin << '\t' << node_residual[gi]
                  << '\t' << group.potential_spread << '\n';
    }
    for (const auto& connection : connections) if (connection.resistance > 0.0) {
        const double current = (node_potential[group_index.at(connection.a)] - node_potential[group_index.at(connection.b)]) / connection.resistance;
        std::cout << "CONNECTION\t" << connection.id << '\t' << current << '\n';
    }
    const auto points_started = SteadyClock::now();
    for (const auto& point : points) {
        double potential = 0.0;
        if (soil.layered) {
            const int observation_layer = layer_of(point.p.z, soil);
            for (std::size_t j = 0; j < n; ++j)
                potential += layered_source_potential(point.p, observation_layer, segments[j], layers[j], table) * solution[j];
        } else {
            for (std::size_t j = 0; j < n; ++j) potential += source_potential(point.p, segments[j]) * solution[j];
        }
        std::cout << "POINT\t" << point.id << '\t' << factor_v * potential << '\n';
    }
    const double point_evaluation_ms = elapsed_ms(points_started);
    std::cout << "DIAG\tprofile_point_evaluation_ms\t" << point_evaluation_ms << '\n'
              << "DIAG\tprofile_request_total_ms\t" << elapsed_ms(request_started) << '\n'
              << "DIAG\tprofile_peak_rss_mib\t" << peak_rss_mib() << '\n';
    if (multiple_scenarios) std::cout << "END_SCENARIO\n";
    }
    std::cout << "END\n";
}
}  // namespace

int main() {
    std::ios::sync_with_stdio(false);
    try {
        run_request();
        return 0;
    } catch (const std::exception& error) {
        std::cout << kProtocol << "\tERROR\t" << error.what() << '\n';
        return 2;
    }
}
