# score = sum (weight*features) must be equal to 1
DEFAULT_WEIGHTS = {
    "load": 0.5,        #prefers members with low workload
    "fit": 0.3,         #prefers members with required skills
    "continuity": 0.2   #prefers members already on a predecessor task
}
WORKLOAD_CAP = 20
AUTO_DISABLED_THRESHOLD = 2.0
AUTO_ENABLED_THRESHOLD = 0.9
AUTO_MAX_UNDO_RATE = 0.1
ALLOW_SELF_APPROVAL = False
OVERLOAD_RATIO = 1.5
THRESHOLDS = {
    "propose": 0.55,        #confidence below 0.55, engine asks instead of proposing
    "auto": AUTO_DISABLED_THRESHOLD,            #above any possible confidence equates to disabled auto-action
    "margin_full": 0.15,    #winning margin over runner-up that counts fully decisive
}

LOW_IMPACT_MAX_DURATION = 3
LOW_IMPACT_STATUS = "Pending"
STATUS_COMPLETE = "Complete"
PRIORITY_MIN = 0
PRIORITY_MAX = 5
PRIORITY_HIGHEST_IS_MAX = True

URGENT_BLOCKS_AUTO_AT = 0.6     #Tasks above urgency score 0.6 must never be auto-allocated.

LEARNING = {
    "lr" : 0.1,                 #Normal pairwise weight update
    "lr_strong" : 0.2,          #Used when auto-action is undone (learning when auto-action fails)
    "weight_floor" : 0.02,      #weight may not fall below this
    "threshold_step" : 0.02,    #threshold moves by per adjustment
    "threshold_min" : 0.3,      #minimum threshold value
    "threshold_max" : 0.9,      #maximum threshold value
    "min_feedback_events" : 10, #threshold adjustments will be done only after this many feedbacks
    "low_accept_rate" : 0.6,    #below this threshold, ask more
    "high_accept_rate" : 0.9,   #above this, ask less
}

AUTO_MIN_PROPOSALS = 30    
AUTO_MIN_ACCEPT_RATE = 0.95         
#Auto-action allowed only after this many proposals and a minimum of this acceptance rate.

ROLE_MEMBER = False
ROLE_LEAD = True
APPROVER_ROLES = {ROLE_LEAD}

PROPOSAL_EXPIRY_HOURS = 48  #Proposals expire after 48 hours on no approval

SETTINGS_KEY_WEIGHTS = "weights"
SETTINGS_KEY_THRESHOLDS = "thresholds"
SETTINGS_KEY_FEEDBACK_COUNTS = "feedback_counts"
ACTIONS = ("propose", "ask", "wait", "auto")
STATUSES = ("pending", "approved", "rejected", "expired", "executed_auto", "undone", "stale")

def urgency_from_priority(priority):
    span = PRIORITY_MAX - PRIORITY_MIN
    p = min(max(priority, PRIORITY_MIN), PRIORITY_MAX)
    scaled = (p - PRIORITY_MIN) / span
    return scaled if PRIORITY_HIGHEST_IS_MAX else 1.0 - scaled

def validate_config():
    if abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) > 1e-9:
        raise ValueError("Default weights must sum to 1.")
    if any(w < LEARNING["weight_floor"] for w in DEFAULT_WEIGHTS.values()):
        raise ValueError("A default weight is below the weight floor.")
    if WORKLOAD_CAP <= 0:
        raise ValueError("Workload cap must be positive.")
    low, high = LEARNING["threshold_min"], LEARNING["threshold_max"]
    if not (low <= THRESHOLDS["propose"] <= high):
        raise ValueError("The propose threshold is outside its learning range.")
    if THRESHOLDS["auto"] < THRESHOLDS["propose"]:
        raise ValueError("The auto threshold cannot be below the propose threshold.")
    if THRESHOLDS["margin_full"] <= 0:
        raise ValueError("The decisive margin must be positive.")
    if PRIORITY_MIN >= PRIORITY_MAX:
        raise ValueError("Minimum priority must be below maximum priority.")
    if not (0.0 <= URGENT_BLOCKS_AUTO_AT <= 1.0):
        raise ValueError("The urgency limit must lie between 0 and 1.")
    if not (LEARNING["low_accept_rate"] < LEARNING["high_accept_rate"]):
        raise ValueError("low_accept_rate must be below high_accept_rate.")
    if not (0 < LEARNING["lr"] <= LEARNING["lr_strong"]):
        raise ValueError("Learning rates must satisfy 0 < lr <= lr_strong.")
    if not (0.0 < AUTO_MIN_ACCEPT_RATE <= 1.0):
        raise ValueError("AUTO_MIN_ACCEPT_RATE must lie in (0, 1].")
    if AUTO_ENABLED_THRESHOLD <= THRESHOLDS["propose"]:
        raise ValueError("Auto enabled threshold cannot be above the threshold for propose.")
    if AUTO_ENABLED_THRESHOLD >= 1:
        raise ValueError("Auto enabled threshold cannot be equal to or less than 1.")
    if not (0 <= AUTO_MAX_UNDO_RATE <= 1):
        raise ValueError("Maximum undo rate must lie between 0 and 1.")
    return True

validate_config()      # fail at import time, not at the first decision
