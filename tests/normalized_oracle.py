"""Independent expected v1 normalized payloads from the frozen CSV snapshots."""
from datetime import date


def from_csv(kind, row):
    """Return (data, times, units), independent of On1x serialization."""
    times = {key: row[key] for key in ("observed_at", "ingested_at")}
    units = {"currency": row["currency"], "price_basis": "whole_stay"}
    if kind == "hospitality.offer":
        data = {key: row[key] for key in ("arrival", "departure", "valid_from", "valid_to")}
        for name in ("adult", "child", "total"):
            data[name + "_capacity"] = int(row[name + "_cap"])
        data["guest_payable_cents"] = sum(int(row[k]) for k in
                                          ("total_cents", "fees_cents", "taxes_cents"))
        data["bookable"] = {"0": False, "1": True}[row["bookable"]]
    elif kind == "hospitality.scenario":
        data = {key: row[key] for key in ("arrival", "departure", "decision_at", "curve")}
        for key in ("adults", "children", "max_rooms", "min_properties",
                    "target_bps", "max_age_days", "search_budget"):
            data[key] = int(row[key])
        data["nights"] = (date.fromisoformat(row["departure"]) -
                          date.fromisoformat(row["arrival"])).days
    elif kind == "pricing.valuation":
        units["price_basis"] = "room_night"
        data = {key: int(row[key]) for key in
                ("current_cents", "floor_cents", "cap_cents", "max_move_cents", "shortcut_cents")}
    else:
        raise ValueError(f"Unexpected normalized kind: {kind}")
    return data, times, units
