#ifndef DRAGNET_FEED_LIMITS_H
#define DRAGNET_FEED_LIMITS_H

enum { dragnet_body_max = 65536 };
#define DRAGNET_ECB_URL "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
#define DRAGNET_EUROSTAT_PATH \
    "/eurostat/api/dissemination/statistics/1.0/data/tour_occ_nim" \
    "?lang=EN&freq=M&unit=NR&nace_r2=I551-I553&c_resid=TOTAL&geo=EU27_2020&lastTimePeriod=3"
#define DRAGNET_EUROSTAT_URL "https://ec.europa.eu" DRAGNET_EUROSTAT_PATH

#endif
