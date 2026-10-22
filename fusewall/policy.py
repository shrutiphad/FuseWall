"""Pure admission rules shared by real reservations and advisory previews."""


def evaluate(config, policy, session, session_policy, now, repetitions, active, recent, buckets, required, model):
    if config["paused"]:
        return "organization_paused", 402
    if model not in policy["allowed_models"]:
        return "model_not_allowed", 403
    if session["status"] != "active":
        return "session_tripped", 402
    if now - session["started"] >= session_policy["duration_seconds"]:
        return "session_expired", 402
    if session["calls"] >= session_policy["max_calls"]:
        return "session_call_limit", 402
    if session_policy["loop_threshold"] and repetitions >= session_policy["loop_threshold"]:
        return "repeat_guard", 402
    if active >= policy["max_concurrent"]:
        return "concurrency_limit", 429
    if recent >= policy["rpm"]:
        return "rate_limit", 429
    for bucket in buckets:
        if bucket["spent"] + bucket["held"] + required > bucket["ceiling"]:
            return bucket["kind"] + "_budget", 402
    return "authorized", 200
