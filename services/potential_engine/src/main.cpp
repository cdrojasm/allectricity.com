#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr const char* kProtocol = "SPAT-POTENTIAL-2";
constexpr const char* kSolverVersion = "2.0.0";
constexpr const char* kMethod =
    "galerkin-thin-wire-mom;piecewise-constant-leakage;analytic-line-integral;"
    "graded-gauss-legendre-8;lu-partial-pivoting";
constexpr const char* kAssumptions =
    "homogeneous-isotropic-semi-infinite-soil;insulating-air-boundary;quasi-static-dc;"
    "ideal-equipotential-metal-per-group;zero-net-current-for-floating-groups";
constexpr const char* kUnits = "length=m;resistivity=ohm_m;current=A;potential=V;resistance=ohm";

// Operational limits. Timing and memory measured by validation/benchmark.py; see README.
#ifndef SPAT_MAX_SEGMENTS
#define SPAT_MAX_SEGMENTS 1500
#endif
constexpr std::size_t kMaxSegments = SPAT_MAX_SEGMENTS;
constexpr std::size_t kMaxPoints = 100000;
constexpr double kMaxPointSegmentWork = 2.0e7;
constexpr double kMaxCoordinateM = 1.0e5;
constexpr double kMaxDepthM = 1000.0;
constexpr double kMinRadiusM = 1.0e-4;
constexpr double kMaxRadiusM = 0.5;
constexpr double kMinLengthToRadius = 5.0;
constexpr double kMaxResistivityOhmM = 1.0e6;
constexpr double kMaxCurrentA = 1.0e6;

// Numerical acceptance limits.
constexpr double kMaxBackwardError = 1.0e-10;
constexpr double kWarnCondition = 1.0e10;
constexpr double kMaxCondition = 1.0e13;
constexpr double kMaxRelativeBalanceError = 1.0e-9;

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
    for (std::size_t q = 0; q < kNodes.size(); ++q) sum += kWeights[q] * f(t0 + (t1 - t0) * 0.5 * (kNodes[q] + 1.0));
    return 0.5 * (t1 - t0) * sum;
}

// Integral on [from, to] graded geometrically towards `to`, where the integrand varies on `scale`.
template <typename F>
double graded(F&& f, double from, double to, double scale) {
    double result = 0.0, gap = std::abs(to - from);
    const double direction = to > from ? 1.0 : -1.0;
    while (gap > scale) {
        const double next = 0.2 * gap;
        const double lo = to - direction * gap, hi = to - direction * next;
        result += gauss(f, std::min(lo, hi), std::max(lo, hi));
        gap = next;
    }
    const double lo = to - direction * gap;
    return result + gauss(f, std::min(lo, to), std::max(lo, to));
}

struct NearPoint {
    double t;      // closest target parameter
    double scale;  // relative length on which the integrand varies there
};

// Integral over the target parameter [0, 1], refined towards near source points.
template <typename F>
double integrate(F&& f, std::vector<NearPoint> near) {
    if (near.empty()) return gauss(f, 0.0, 1.0);
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
            else result += gauss(f, left, right);
        }
        left = right; left_scale = right_scale; left_singular = right_singular;
    }
    return result;
}

// Galerkin coefficient: length-averaged potential over the target per unit source current (1/m).
double coefficient(const Segment& target, const Segment& source, bool same) {
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
        return direct + integrate(image, near);
    }
    add_near(source.a, source.b);
    return integrate([&](double t) { return source_potential(at(target, t), source); }, near);
}

struct Lu {
    std::vector<std::vector<double>> a;
    std::vector<std::size_t> perm;
    double min_pivot{std::numeric_limits<double>::infinity()};
    double max_pivot{};
};

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

void validate_geometry(const std::vector<Segment>& segments) {
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
            if (p.group != q.group && gap <= p.radius + q.radius)
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
    std::string line;
    if (!std::getline(std::cin, line) || line != kProtocol)
        throw std::runtime_error(std::string("expected ") + kProtocol + " protocol header");
    if (!std::getline(std::cin, line)) throw std::runtime_error("missing soil and segment count");
    auto header = fields(line);
    if (header.size() != 2) throw std::runtime_error("soil line must contain resistivity and segment count");
    const double rho = number(header[0], "soil resistivity");
    const std::size_t segment_count = count_value(header[1], "segment count", kMaxSegments);
    if (rho <= 0 || rho > kMaxResistivityOhmM) throw std::runtime_error("soil resistivity must be in (0, 1e6] ohm-m");
    if (segment_count == 0) throw std::runtime_error("segment count must be positive");

    std::map<std::string, Group> groups;
    const auto segments = read_segments(segment_count, groups);

    if (!std::getline(std::cin, line)) throw std::runtime_error("missing injection count");
    const auto injection_header = fields(line);
    if (injection_header.size() != 1) throw std::runtime_error("injection count line must have one value");
    const std::size_t injection_count = count_value(injection_header[0], "injection count", groups.size());
    std::set<std::string> injection_ids;
    for (std::size_t i = 0; i < injection_count; ++i) {
        if (!std::getline(std::cin, line)) throw std::runtime_error("missing injection row");
        auto f = fields(line);
        if (f.size() != 3) throw std::runtime_error("injection row must contain group id, current in amperes and origin");
        require_id(f[0], "injection group id");
        require_id(f[2], "injection origin");
        auto it = groups.find(f[0]);
        if (it == groups.end()) throw std::runtime_error("injection group has no electrode segments: " + f[0]);
        if (!injection_ids.insert(f[0]).second) throw std::runtime_error("duplicate group injection: " + f[0]);
        const double current = number(f[1], "injected current");
        if (std::abs(current) > kMaxCurrentA) throw std::runtime_error("injected current magnitude exceeds 1e6 A");
        it->second.injected_current = current;
        it->second.origin = f[2];
    }

    if (!std::getline(std::cin, line)) throw std::runtime_error("missing point count");
    const auto point_header = fields(line);
    if (point_header.size() != 1) throw std::runtime_error("point count line must have one value");
    const std::size_t point_count = count_value(point_header[0], "point count", kMaxPoints);
    if (static_cast<double>(point_count) * static_cast<double>(segment_count) > kMaxPointSegmentWork)
        throw std::runtime_error("points x segments exceeds 2e7; split the surface query into batches");
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
    validate_geometry(segments);

    std::vector<std::string> warnings;
    double total_injection = 0.0;
    for (const auto& [id, group] : groups) { (void)id; total_injection += std::abs(group.injected_current); }
    if (total_injection == 0.0) warnings.push_back("no-injection\tall group currents are zero; every potential is zero");

    // Unknowns: n segment currents, then g group potentials (scaled by 4 pi / rho).
    std::vector<std::string> group_ids;
    std::map<std::string, std::size_t> group_index;
    for (const auto& [id, unused] : groups) { (void)unused; group_index[id] = group_ids.size(); group_ids.push_back(id); }
    const std::size_t n = segments.size(), g = group_ids.size(), size = n + g;
    std::vector<std::vector<double>> matrix(size, std::vector<double>(size, 0.0));
    std::vector<double> rhs(size, 0.0);
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = 0; j < n; ++j) matrix[i][j] = coefficient(segments[i], segments[j], i == j);
        matrix[i][n + group_index.at(segments[i].group)] = -1.0;
    }
    for (std::size_t j = 0; j < n; ++j) matrix[n + group_index.at(segments[j].group)][j] = 1.0;
    for (std::size_t gi = 0; gi < g; ++gi) rhs[n + gi] = groups[group_ids[gi]].injected_current;

    const Lu lu = factor(matrix);
    const auto solution = lu_solve(lu, rhs);
    const double condition = condition_1norm(matrix, lu);
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
    if (!std::isfinite(condition) || condition > kMaxCondition)
        throw std::runtime_error("ill-conditioned electrode system (1-norm condition estimate above 1e13)");
    if (backward_error > kMaxBackwardError)
        throw std::runtime_error("solver residual above acceptance limit");
    if (condition > kWarnCondition) warnings.push_back("ill-conditioned\t1-norm condition estimate above 1e10");

    const double factor_v = rho / (4.0 * kPi);
    double max_balance_error = 0.0;
    for (std::size_t gi = 0; gi < g; ++gi) {
        auto& group = groups[group_ids[gi]];
        group.potential = factor_v * solution[n + gi];
        double low = std::numeric_limits<double>::infinity(), high = -low;
        for (std::size_t i = 0; i < n; ++i) {
            if (group_index.at(segments[i].group) != gi) continue;
            group.net_current += solution[i];
            double v = 0.0;
            for (std::size_t j = 0; j < n; ++j) v += matrix[i][j] * solution[j];
            low = std::min(low, v); high = std::max(high, v);
        }
        group.potential_spread = factor_v * (high - low);
        const double error = std::abs(group.net_current - group.injected_current);
        max_balance_error = std::max(max_balance_error, error / std::max(1.0, total_injection));
    }
    if (max_balance_error > kMaxRelativeBalanceError)
        throw std::runtime_error("current balance error above acceptance limit");

    std::cout << std::setprecision(12) << kProtocol << "\tOK\n";
    std::cout << "META\tprotocol\t" << kProtocol << '\n'
              << "META\tsolver_version\t" << kSolverVersion << '\n'
              << "META\tmethod\t" << kMethod << '\n'
              << "META\tassumptions\t" << kAssumptions << '\n'
              << "META\tunits\t" << kUnits << '\n'
              << "META\tsoil_resistivity_ohm_m\t" << rho << '\n'
              << "META\tsegment_count\t" << n << '\n'
              << "META\tgroup_count\t" << g << '\n'
              << "META\tpoint_count\t" << points.size() << '\n';
    std::cout << "DIAG\tbackward_error\t" << backward_error << '\n'
              << "DIAG\tcondition_1norm_estimate\t" << condition << '\n'
              << "DIAG\tpivot_ratio\t" << lu.min_pivot / lu.max_pivot << '\n'
              << "DIAG\tmax_relative_balance_error\t" << max_balance_error << '\n';
    for (const auto& warning : warnings) std::cout << "WARNING\t" << warning << '\n';
    for (std::size_t i = 0; i < n; ++i) std::cout << "SEGMENT\t" << segments[i].id << '\t' << solution[i] << '\n';
    for (const auto& id : group_ids) {
        const auto& group = groups[id];
        std::cout << "GROUP\t" << id << '\t' << group.injected_current << '\t' << group.potential << '\t';
        if (std::abs(group.injected_current) > 1e-12) std::cout << group.potential / group.injected_current;
        else std::cout << "null";
        std::cout << '\t' << group.origin << '\t' << group.net_current - group.injected_current
                  << '\t' << group.potential_spread << '\n';
    }
    for (const auto& point : points) {
        double potential = 0.0;
        for (std::size_t j = 0; j < n; ++j) potential += source_potential(point.p, segments[j]) * solution[j];
        std::cout << "POINT\t" << point.id << '\t' << factor_v * potential << '\n';
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
