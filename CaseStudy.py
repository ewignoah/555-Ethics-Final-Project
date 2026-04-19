# game.py — Hospital Admin: da Vinci adoption (terminal CYOA, quarterly, 2 years)
import random
import sys
import time

STEP_MONTHS = 3
QUARTERS = 8

TUNING = {
    # event pacing 
    "EVENT_RATE": 1.9,
    "BASE_MALF_QTR": 0.075,
    "BASE_PR_QTR": 0.033,
    "BASE_LAWSUIT_QTR": 0.055,
    "MAJOR_MALF_BASE": 0.38,

    # finance model
    "MAINT_PER_YEAR": 400_000,
    "REV_PER_CASE": 4_500,
    "ROBOT_FEE_PER_CASE": 2_400,
    "ROBOT_FEE_HIT_FRAC": 0.55,
    "OVERHEAD_PER_CASE": 260.0,

    # latent dynamics
    "ADVERSE_PRESSURE_DECAY": 0.88,
    "MEDIA_HEAT_DECAY": 0.85,
    "TRAINING_DECAY_MIN": 4,
    "TRAINING_DECAY_MAX": 6,
    "BASE_ADVERSE_BUILD": 0.04,

    # adoption decision impacts
    "INSTALL": {
        "buy":   {"label": "Buy outright",        "budget": -2_400_000, "installed": True,  "media_heat": +0.05},
        },

    # training decision impacts
    "TRAINING_OPTIONS": {
        "1": {"label": "Minimal",   "budget":  -200_000, "training_level": +4,  "adverse_pressure": +0.03},
        "2": {"label": "Moderate",  "budget": -400_000, "training_level": +12, "reputation": +1.0, "adverse_pressure": -0.03},
        "3": {"label": "Intensive", "budget": -750_000, "training_level": +25, "reputation": +2.0, "legal_risk_mult": 0.90, "adverse_pressure": -0.06},
        "none": {"label": "Skip training", "budget": 0, "adverse_pressure": +0.03},  # applied only if installed
    },

    # marketing decision impacts (FIX: always include adverse_pressure so no KeyError)
    "MARKETING": {
        "label": "Increase marketing",
        "budget": -300_000,
        "cases_per_month": +10,
        "media_heat": +0.03,
        "adverse_pressure": +0.00,
        "training_threshold_unready": 45.0,
        "reputation_if_unready": -5.0,
        "media_heat_if_unready": +0.08,
        "adverse_pressure_if_unready": +0.06,
    },

    # malfunction impacts (more catastrophic)
    "MALFUNCTION_IMPACTS": {
        "minor": {"patient_safety": -10, "reputation": -10, "budget": -350_000,   "adverse_pressure": +0.40, "media_heat": +0.14, "legal_risk": +0.020},
        "major": {"patient_safety": -30, "reputation": -28, "budget": -1_750_000, "adverse_pressure": +1.00, "media_heat": +0.45, "legal_risk": +0.080},
    },

    # malfunction response impacts
    "MALFUNCTION_RESPONSE": {
        "1": {"label": "Stand-down + RCA", "budget": -350_000, "training_level": +8, "patient_safety": +6,
              "adverse_pressure_mult": 0.70, "media_heat_mult": 0.88, "legal_risk_mult": 0.84},
        "2": {"label": "Vendor service",  "budget": -220_000, "training_level": +4, "patient_safety": +3,
              "adverse_pressure_mult": 0.84, "legal_risk_mult": 0.92},
        "3": {"label": "Continue ops",    "budget": 0, "reputation": -10.0,
              "media_heat": +0.25, "adverse_pressure": +0.25, "legal_risk": +0.040},
    },

    # PR boost impacts + post-PR volume bump
    "PR_BOOST_IMPACTS": {"reputation": +10, "patient_safety": +4, "media_heat": +0.12},
    "PR_BOOST_CASES_BONUS": {"min": 2, "max": 6},  # moderate bump in cases/mo after PR boost

    # PR spotlight response: now costs money and changes volume by randomized ranges
    "PR_RESPONSE": {
        "1": {"label": "Conservative messaging", "budget": -50_000,
              "cases_bonus_range": (1, 4),
              "media_heat_mult": 0.92, "legal_risk_mult": 0.97, "adverse_pressure_mult": 0.95},
        "2": {"label": "Big marketing push", "budget": -200_000,
              "cases_bonus_range": (6, 16),
              "unready_training_threshold": 60.0, "reputation_if_unready": -4, "media_heat_if_unready": +0.12, "adverse_pressure_if_unready": +0.10},
        "3": {"label": "Recruit top talent", "budget": -450_000,
              "cases_bonus_range": (2, 6),
              "training_level": +10,
              "legal_risk_mult": 0.95, "adverse_pressure_mult": 0.92},
    },

    # lawsuit response parameters (catastrophic)
    "LAWSUIT": {
        "payout_min": 1_200_000,
        "payout_max": 6_500_000,
        "legal_fees_min": 350_000,
        "legal_fees_max": 900_000,
        "win_prob_base": 0.15,
        "win_prob_scale": 0.55,
        "settle_frac_min": 0.70,
        "settle_frac_max": 0.98,
        "program_cost_min": 250_000,
        "program_cost_max": 650_000,
        "audit_cost_min": 350_000,
        "audit_cost_max": 900_000,
        "residual_frac_min": 0.45,
        "residual_frac_max": 0.80,
        "always_media_heat": +0.18,
        "always_legal_risk_mult": 0.97,
    },

    # low-reputation meta response impacts
    "LOW_REP_RESPONSE": {
        "1": {"label": "Transparency + patient support", "budget": -400_000,
              "media_heat_mult": 0.70, "adverse_pressure_mult": 0.75, "legal_risk_mult": 0.82},
        "2": {"label": "Quiet settlements", "budget": -250_000,
              "media_heat_mult": 0.88, "adverse_pressure_mult": 0.92, "legal_risk_mult": 0.92},
        "3": {"label": "Downplay + push volume", "budget": 0,
              "media_heat": +0.35, "adverse_pressure": +0.30, "legal_risk": +0.070},
    },
}

state = {
    "month": 1,
    "budget": 4_500_000.0,
    "reputation": 60.0,
    "patient_safety": 75.0,
    "training_level": 20.0,
    "cases_per_month": 60,
    "installed": False,
    "legal_risk": 0.03,
    "adverse_pressure": 0.12,
    "media_heat": 0.08,
}

events = []

# ---------------- helpers ----------------
def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def scaled_prob(p):
    return clamp(p * TUNING["EVENT_RATE"], 0.0, 0.95)

def quarter_number():
    return ((state["month"] - 1) // STEP_MONTHS) + 1

def pct01(x):
    return f"{clamp(x, 0.0, 1.0) * 100:.0f}%"

def money_delta(x):
    if x == 0:
        return "$0"
    sign = "-" if x < 0 else "+"
    return f"{sign}${abs(x):,.0f}"

def financial_only(delta: dict) -> str:
    b = float(delta.get("budget", 0.0))
    return f"Cost: {money_delta(b)}"

def apply_delta(delta: dict):
    for k, v in delta.items():
        if k == "label":
            continue
        if k == "installed":
            state["installed"] = bool(v)
        elif k in state and isinstance(v, (int, float)):
            state[k] += float(v)

def apply_mult(mult: dict):
    for k, v in mult.items():
        if k.endswith("_mult"):
            base_key = k[:-5]
            if base_key in state:
                state[base_key] *= float(v)

def clamp_state():
    state["reputation"] = clamp(state["reputation"], 0, 100)
    state["patient_safety"] = clamp(state["patient_safety"], 0, 100)
    state["training_level"] = clamp(state["training_level"], 0, 100)
    state["cases_per_month"] = int(max(0, state["cases_per_month"]))
    state["legal_risk"] = clamp(state["legal_risk"], 0.01, 0.60)
    state["adverse_pressure"] = clamp(state["adverse_pressure"], 0.0, 1.0)
    state["media_heat"] = clamp(state["media_heat"], 0.0, 1.0)

def add_event(evt_type, data=None):
    events.append({"type": evt_type, "data": data or {}})

def pop_all_events():
    out = events[:]
    events.clear()
    return out

def print_state():
    print("\n--- Month {:02d} (Quarter {}) Summary ---".format(state["month"], quarter_number()))
    print(f"Budget: ${state['budget']:,.0f}")
    print(f"Reputation: {state['reputation']:.0f}/100")
    print(f"Patient safety: {state['patient_safety']:.0f}/100")
    print(f"Training level: {state['training_level']:.0f}/100")
    print(f"Monthly cases: {state['cases_per_month']}")
    print(f"Installed da Vinci: {state['installed']}")
    print(f"Adverse pressure: {pct01(state['adverse_pressure'])}")
    print(f"Media heat: {pct01(state['media_heat'])}")
    print("-----------------------------\n")

# ---------------- decisions ----------------
def decision_install():
    inst = TUNING["INSTALL"]
    print("You are offered a da Vinci system.")
    print(f"{inst['buy']['label']} — {financial_only(inst['buy'])}")

    input("Press Enter to proceed with purchase...")

    apply_delta(inst["buy"])
    clamp_state()
    print(f"Chosen: {inst['buy']['label']}.")

def decision_training():
    opts = TUNING["TRAINING_OPTIONS"]
    print("Training options (financials only; improves readiness and can reduce risk over time):")
    for k in ("1", "2", "3"):
        print(f"{k}) {opts[k]['label']} — {financial_only(opts[k])}")
    print("Press Enter to skip training (may increase future risk).")
    c = input("Choose 1-3 (or Enter to skip): ").strip()

    if c in ("1", "2", "3"):
        delta = opts[c]
        apply_delta(delta)
        if "legal_risk_mult" in delta:
            state["legal_risk"] *= delta["legal_risk_mult"]
        clamp_state()
        print(f"Chosen: {delta['label']}.")
    else:
        print("Training skipped.")
        if state["installed"]:
            delta = opts["none"]
            apply_delta(delta)
            clamp_state()

def decision_marketing():
    m = TUNING["MARKETING"]
    print("Marketing option (financials only):")
    print(f"- {m['label']} — Cost: {money_delta(m['budget'])} (may increase volume; may increase scrutiny if unready)")
    confirm = input("Proceed with marketing? (y/n): ").strip().lower()
    if confirm != "y":
        print("Marketing canceled.")
        return

    # FIX: robust to missing keys; also TUNING now includes adverse_pressure
    for k in ("budget", "cases_per_month", "media_heat", "adverse_pressure"):
        if k in m:
            state[k] += float(m[k])

    if state["training_level"] < m["training_threshold_unready"]:
        state["reputation"] += m["reputation_if_unready"]
        state["media_heat"] += m["media_heat_if_unready"]
        state["adverse_pressure"] += m["adverse_pressure_if_unready"]

    clamp_state()
    print("Marketing executed.")

# ---------------- quarterly sim ----------------
def quarterly_operations():
    months = STEP_MONTHS
    cases_qtr = state["cases_per_month"] * months

    rev = TUNING["REV_PER_CASE"]
    fee = TUNING["ROBOT_FEE_PER_CASE"] if state["installed"] else 0.0
    revenue = cases_qtr * (rev - fee * TUNING["ROBOT_FEE_HIT_FRAC"])

    maintenance_qtr = (TUNING["MAINT_PER_YEAR"] / 12.0) * months if state["installed"] else 0.0
    overhead_qtr = cases_qtr * TUNING["OVERHEAD_PER_CASE"]
    state["budget"] += revenue - maintenance_qtr - overhead_qtr

    rep_drift = (state["patient_safety"] - 75) * 0.02 * months
    state["reputation"] = clamp(state["reputation"] + rep_drift, 0, 100)

    decay = random.randint(TUNING["TRAINING_DECAY_MIN"], TUNING["TRAINING_DECAY_MAX"])
    state["training_level"] = clamp(state["training_level"] - decay, 0, 100)

    if state["installed"]:
        rep = state["reputation"] / 100.0
        safety = state["patient_safety"] / 100.0
        volume_factor = clamp(state["cases_per_month"] / 90.0, 0.6, 1.8)
        learn = months * (0.6 + 0.45 * rep + 0.25 * safety) * 0.7 * volume_factor
        state["training_level"] = clamp(state["training_level"] + learn, 0, 100)

    training = state["training_level"] / 100.0
    safety = state["patient_safety"] / 100.0
    volume_factor = clamp(state["cases_per_month"] / 70.0, 0.7, 1.8)

    baseline_adverse = TUNING["BASE_ADVERSE_BUILD"] * (1.25 - 0.80 * training) * (1.15 - 0.55 * safety) * volume_factor
    baseline_adverse *= (1.05 - 0.30 * (state["reputation"] / 100.0))
    state["adverse_pressure"] = clamp(state["adverse_pressure"] + clamp(baseline_adverse, 0.0, 0.15), 0.0, 1.0)

    state["adverse_pressure"] = clamp(state["adverse_pressure"] * TUNING["ADVERSE_PRESSURE_DECAY"], 0.0, 1.0)
    state["media_heat"] = clamp(state["media_heat"] * TUNING["MEDIA_HEAT_DECAY"], 0.0, 1.0)

    baseline_shift = (
        + 0.014 * state["adverse_pressure"]
        + 0.006 * state["media_heat"]
        - 0.004 * training
        - 0.003 * safety
        - 0.002 * (state["reputation"] / 100.0)
    )
    state["legal_risk"] = clamp(state["legal_risk"] + baseline_shift, 0.01, 0.50)
    clamp_state()

# ---------------- events generation ----------------
def random_events_quarter():
    training = state["training_level"] / 100.0
    rep = state["reputation"] / 100.0
    safety = state["patient_safety"] / 100.0
    volume_factor = clamp(state["cases_per_month"] / 90.0, 0.6, 1.9)

    if state["installed"]:
        base = TUNING["BASE_MALF_QTR"]
        malf_prob = base * (1.35 - 0.98 * training) * (1.20 - 0.70 * safety) * volume_factor * (1.12 - 0.40 * rep)
        malf_prob *= (1.0 + 1.0 * state["adverse_pressure"])
        malf_prob = scaled_prob(malf_prob)
        if random.random() < malf_prob:
            major_p = TUNING["MAJOR_MALF_BASE"] + 0.45 * (1 - training) + 0.30 * (1 - safety) + 0.25 * state["adverse_pressure"]
            major_p = clamp(major_p, 0.12, 0.90)
            severity = "major" if random.random() < major_p else "minor"
            add_event("malfunction", {"severity": severity})

    if state["installed"]:
        base = TUNING["BASE_PR_QTR"]
        pr_prob = base * (0.35 + 0.80 * (state["training_level"] / 100.0)) * (0.60 + 0.60 * rep) * (0.85 + 0.30 * safety)
        pr_prob = scaled_prob(pr_prob)
        if random.random() < pr_prob:
            add_event("pr_boost", {})

    pressure = (
        state["legal_risk"] +
        1.05 * state["adverse_pressure"] +
        0.55 * state["media_heat"] +
        0.35 * (1 - rep)
    )
    pressure *= (1.08 - 0.30 * training) * (1.10 - 0.32 * safety)
    pressure = clamp(pressure, 0.0, 2.5)

    lawsuit_prob = scaled_prob(TUNING["BASE_LAWSUIT_QTR"] * pressure)
    lawsuit_prob = clamp(lawsuit_prob, 0.0, 0.65)
    if random.random() < lawsuit_prob:
        L = TUNING["LAWSUIT"]
        payout = random.randint(L["payout_min"], L["payout_max"])
        add_event("lawsuit", {"payout": payout})

# ---------------- event handling ----------------
def handle_malfunction_event(severity: str):
    impacts = TUNING["MALFUNCTION_IMPACTS"][severity]
    print(f"\nEVENT: Device malfunction ({severity}). Financial hit: {money_delta(impacts['budget'])}.")
    print("Non-financially: this can hurt safety and reputation, and raise future legal exposure.")
    apply_delta(impacts)
    clamp_state()

    resp = TUNING["MALFUNCTION_RESPONSE"]
    print("\nOperational response options (financials only):")
    for k in ("1", "2", "3"):
        print(f"{k}) {resp[k]['label']} — {financial_only(resp[k])} (may change future risk/safety/reputation)")
    r = input("Choose 1-3: ").strip()
    r = r if r in ("1", "2", "3") else "2"

    chosen = resp[r]
    apply_delta({k: v for k, v in chosen.items() if k in state and not k.endswith("_mult")})
    apply_mult(chosen)
    if "legal_risk_mult" in chosen:
        state["legal_risk"] *= chosen["legal_risk_mult"]
    clamp_state()

def handle_pr_boost_event():
    imp = TUNING["PR_BOOST_IMPACTS"]
    print("\nEVENT: High-profile success (PR boost).")
    print("Non-financially: improves reputation and can attract more cases.")
    apply_delta(imp)

    # moderate automatic bump in cases
    bonus = random.randint(TUNING["PR_BOOST_CASES_BONUS"]["min"], TUNING["PR_BOOST_CASES_BONUS"]["max"])
    state["cases_per_month"] += bonus
    clamp_state()

    resp = TUNING["PR_RESPONSE"]
    print("\nHow do you message/market after the boost? (financials only):")
    for k in ("1", "2", "3"):
        label = resp[k]["label"]
        cost = resp[k].get("budget", 0)
        rng = resp[k].get("cases_bonus_range", (0, 0))
        print(f"{k}) {label} — Cost: {money_delta(cost)} (may increase volume by a small/medium/large amount)")
    r = input("Choose 1-3: ").strip()
    r = r if r in ("1", "2", "3") else "1"

    chosen = resp[r]
    # apply the financial cost immediately
    state["budget"] += float(chosen.get("budget", 0.0))

    # apply randomized volume bump
    lo, hi = chosen.get("cases_bonus_range", (0, 0))
    if hi > 0:
        state["cases_per_month"] += random.randint(int(lo), int(hi))

    # apply any other tuned effects (not shown numerically to user)
    apply_delta({k: v for k, v in chosen.items() if k in state and not k.endswith("_mult") and k != "budget"})
    apply_mult(chosen)
    if "legal_risk_mult" in chosen:
        state["legal_risk"] *= chosen["legal_risk_mult"]

    # readiness penalty for "big push"
    if r == "2":
        thresh = chosen.get("unready_training_threshold", 60.0)
        if state["training_level"] < thresh:
            state["reputation"] += chosen.get("reputation_if_unready", -4)
            state["media_heat"] += chosen.get("media_heat_if_unready", +0.12)
            state["adverse_pressure"] += chosen.get("adverse_pressure_if_unready", +0.10)

    clamp_state()

def handle_lawsuit_event(payout: int):
    L = TUNING["LAWSUIT"]
    print("\nEVENT: Lawsuit filed.")
    print(f"Financial exposure (if it goes badly): up to ${payout:,.0f}.")
    print("Non-financially: a single lawsuit can be catastrophic for reputation and oversight.")

    print("\nResponse options (financial ranges only):")
    print(f"1) Fight (legal fees ${L['legal_fees_min']:,.0f}–${L['legal_fees_max']:,.0f}; outcome uncertain)")
    print("2) Early settlement + support (very expensive, may limit damage)")
    print("3) Audit + improvements (expensive, may reduce long-term risk)")
    print("4) Stonewall / delay (cheap now; often worsens consequences)")
    r = input("Choose 1-4: ").strip()
    r = r if r in ("1", "2", "3", "4") else "2"

    if r == "1":
        legal_fees = random.randint(L["legal_fees_min"], L["legal_fees_max"])
        state["budget"] -= legal_fees

        strength = (
            0.40 * (state["training_level"] / 100.0) +
            0.40 * (state["patient_safety"] / 100.0) +
            0.20 * (state["reputation"] / 100.0)
        )
        win_prob = clamp(L["win_prob_base"] + L["win_prob_scale"] * strength, 0.12, 0.80)

        if random.random() < win_prob:
            print("RESULT: Defense succeeds (you avoid the worst-case payout).")
            state["reputation"] += 2
            state["media_heat"] *= 0.86
            state["adverse_pressure"] *= 0.88
            state["legal_risk"] *= 0.90
        else:
            print("RESULT: Case goes against you (catastrophic).")
            state["budget"] -= payout
            state["reputation"] -= 22
            state["patient_safety"] -= 10
            state["media_heat"] += 0.40
            state["adverse_pressure"] += 0.30
            state["legal_risk"] += 0.070

    elif r == "2":
        settlement = int(payout * random.uniform(L["settle_frac_min"], L["settle_frac_max"]))
        program_cost = random.randint(L["program_cost_min"], L["program_cost_max"])
        state["budget"] -= (settlement + program_cost)
        state["reputation"] -= 6
        state["patient_safety"] += 2
        state["media_heat"] *= 0.80
        state["adverse_pressure"] *= 0.78
        state["legal_risk"] *= 0.85
        print(f"RESULT: Settlement paid: ${settlement:,.0f} (plus support program costs).")

    elif r == "3":
        audit_cost = random.randint(L["audit_cost_min"], L["audit_cost_max"])
        residual = int(payout * random.uniform(L["residual_frac_min"], L["residual_frac_max"]))
        state["budget"] -= (audit_cost + residual)
        state["reputation"] -= 10
        state["training_level"] += 8
        state["patient_safety"] += 6
        state["media_heat"] *= 0.78
        state["adverse_pressure"] *= 0.70
        state["legal_risk"] *= 0.83
        print(f"RESULT: Audit + residual costs paid (residual settlement: ${residual:,.0f}).")

    else:
        print("RESULT: Stonewalling raises scrutiny and worsens downstream outcomes.")
        state["reputation"] -= 14
        state["media_heat"] += 0.45
        state["adverse_pressure"] += 0.30
        state["legal_risk"] += 0.090

    state["media_heat"] += L["always_media_heat"]
    state["legal_risk"] *= L["always_legal_risk_mult"]
    clamp_state()

def handle_events():
    evts = pop_all_events()
    if not evts:
        return
    for evt in evts:
        if evt["type"] == "malfunction":
            handle_malfunction_event(evt["data"].get("severity", "minor"))
        elif evt["type"] == "pr_boost":
            handle_pr_boost_event()
        elif evt["type"] == "lawsuit":
            handle_lawsuit_event(int(evt["data"].get("payout", 2_000_000)))

def low_rep_branch():
    if state["reputation"] >= 40:
        return
    resp = TUNING["LOW_REP_RESPONSE"]
    print("\nReputation is low. Response options (financials only):")
    for k in ("1", "2", "3"):
        print(f"{k}) {resp[k]['label']} — {financial_only(resp[k])} (may affect future trust/scrutiny)")
    r = input("Choose 1-3: ").strip()
    r = r if r in ("1", "2", "3") else "2"

    chosen = resp[r]
    apply_delta({k: v for k, v in chosen.items() if k in state and not k.endswith("_mult")})
    apply_mult(chosen)
    if "legal_risk_mult" in chosen:
        state["legal_risk"] *= chosen["legal_risk_mult"]
    if "media_heat" in chosen:
        state["media_heat"] += chosen["media_heat"]
    if "adverse_pressure" in chosen:
        state["adverse_pressure"] += chosen["adverse_pressure"]
    if "legal_risk" in chosen:
        state["legal_risk"] += chosen["legal_risk"]
    clamp_state()

def check_end_conditions():
    if state["budget"] <= 0:
        print("You have run out of funds. Game over.")
        return True
    if state["patient_safety"] <= 20:
        print("Patient safety has collapsed. Regulatory shutdown. Game over.")
        return True
    if state["reputation"] <= 10:
        print("Reputation destroyed. Board removed you. Game over.")
        return True
    if quarter_number() > QUARTERS:
        print("\n--- End of 24 months ---")
        print_state()
        return True
    return False

# ---------------- main loop ----------------
def main():
    print("Hospital Admin: da Vinci adoption (quarters).")
    print(f"Each turn advances {STEP_MONTHS} months. Total: {STEP_MONTHS * QUARTERS} months.")
    print("You will see decision costs; non-financial effects are described qualitatively.\n")

    while True:
        print_state()

        if not state["installed"]:
            decision_install()

        print("\nOperational choices this quarter:")
        print("1) Choose training program")
        print("2) Increase marketing")
        print("3) Do nothing / continue")
        choice = input("Choose 1-3 (or 'q' to quit): ").strip()

        if choice == "1":
            decision_training()
        elif choice == "2":
            decision_marketing()
        elif choice.lower() == "q":
            print("Quitting.")
            sys.exit(0)

        quarterly_operations()
        random_events_quarter()
        handle_events()
        low_rep_branch()

        if check_end_conditions():
            break

        state["month"] += STEP_MONTHS
        time.sleep(0.2)

if __name__ == "__main__":
    main()