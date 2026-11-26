#include <math.h>
#include <stdint.h>

/* Integer inputs and output keep binary floating-point out of artifact IDs.
 * The On1x caller validates both points and always uses bounded microdegrees. */
int64_t caravansary_geo_distance_m(int64_t lat1, int64_t lon1, int64_t lat2, int64_t lon2)
{
    const double radians_per_microdegree = 0.000000017453292519943295769;
    const double radius_m = 6371008.8;
    int64_t dlon = lon2 - lon1;
    if (dlon > 180000000) dlon -= 360000000;
    if (dlon < -180000000) dlon += 360000000;
    const double sy = sin((double)(lat2 - lat1) * radians_per_microdegree / 2.0);
    const double sx = sin((double)dlon * radians_per_microdegree / 2.0);
    double h = sy * sy + cos((double)lat1 * radians_per_microdegree)
        * cos((double)lat2 * radians_per_microdegree) * sx * sx;
    if (h <= 0.0) return 0;
    if (h >= 1.0) h = 1.0;
    return (int64_t)(2.0 * radius_m * atan2(sqrt(h), sqrt(1.0 - h)) + 0.5);
}
