"""Every tunable constant of the pipeline. ML refines these from data."""

# Minute aggregation (§5.1)
SQI_VALID = 50
MIN_VALID_SECONDS = 20
HARD_MIN_VALID_SECONDS = 40
STD_PRESSURE_HPA = 1013.25
MMHG_PER_HPA = 0.750062

# Context (§5.3)
OFF_WORN_FRAC = 0.5
OFF_SQI = 20
ACTIVE_ACT_MG = 60
ACTIVE_COOLDOWN_S = 5 * 60
SLEEP_ACT_MG = 8
SLEEP_RUN_MIN = 15
SLEEP_HR_MARGIN = 5
SLEEP_DEFAULT_REST_HR = 60
REST_HR_MIN_VALUES = 120

# Baseline (§6)
BASELINE_WINDOW_S = 14 * 86400
CELL_READY_VALUES = 120
CELL_READY_DAYS = 3
MAD_TO_SIGMA = 1.4826
SIGMA_FLOOR = {"hr": 3.0, "spo2": 1.0, "rr": 1.5, "skin_t": 0.3, "hrv": 8.0}
BAND_SIGMAS = 2.0
TOD_HOURS = 4
LEARN_MAX_Z = 2.5
LEARNED_DAYS = 7
LEARNED_READY_PCT = 75

# (metric, ctx_name) -> (med, sigma); ctx None = any context. Sigma is doubled on use.
TYPICAL_NORM = {
    ("hr", "rest"): (60.0, 10.0),
    ("hr", "sleep"): (52.0, 8.0),
    ("spo2", None): (97.0, 1.5),
    ("rr", None): (14.0, 3.0),
    ("skin_t", None): (33.5, 1.5),
}
TYPICAL_SIGMA_FACTOR = 2.0

# Levels by personal norm (§7.1)
WATCH_Z = 2.0
WATCH_RUN_MIN = 5
ALERT_Z = 3.0
ALERT_RUN_MIN = 3

# Hard thresholds (§7.2), compared after rounding half-up to an integer
SPO2_CRITICAL_MAX = 91
SPO2_ALERT_MAX = 93
HR_CRITICAL_MIN = 131
HR_ALERT_MIN = 111
HR_LOW_MAX = 40
RR_CRITICAL_LOW_MAX = 8
RR_CRITICAL_HIGH_MIN = 25
RR_ALERT_MIN = 21

# Environment (§7.3)
PPCO2_WINDOW_S = 3600
PPCO2_MIN_VALUES = 30
PPCO2_WATCH = 3.0
PPCO2_ALERT = 5.3
PPCO2_CRITICAL = 10.0
PRESS_DROP_WINDOW_S = 600
PRESS_DROP_ALERT = 0.02
PRESS_MEDIAN_WINDOW_S = 86400
PRESS_MEDIAN_CRITICAL = 0.10
PRESS_MEDIAN_REFRESH_S = 600

# Hysteresis (§7.4)
LEVEL_DOWN_MIN = 10

# Incident trend (§7.5): change over 10 minutes below this is "stable"
SLOPE_WINDOW_S = 10 * 60
TREND_STABLE_10MIN = {
    "hr": 1.5,
    "spo2": 0.5,
    "rr": 0.75,
    "skin_t": 0.15,
    "hrv": 4.0,
    "ppco2": 0.2,
    "press": 1.0,
}
