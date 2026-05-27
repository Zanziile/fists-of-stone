"""Stone of Fist — Flask web calculator."""
import os
from flask import Flask, render_template, request, jsonify
import converter

app = Flask(__name__)

FISTS_OF_STONE_IMPLICITS = [
    "+3 to Evasion Rating per player level",
    "+1 to maximum Energy Shield per player level",
]

RUNEFORGED_FISTS_IMPLICITS = [
    "+2 to Evasion Rating per player level",
    "+1 to maximum Energy Shield per player level",
    "+1 to maximum Runic Ward per player level",
]

TYPE_CATEGORIES = [
    ("str",         "STR — Armour"),
    ("dex",         "DEX — Evasion"),
    ("int",         "INT — Energy Shield"),
    ("str_dex",     "STR/DEX — Armour + Evasion"),
    ("str_int",     "STR/INT — Armour + ES"),
    ("dex_int",     "DEX/INT — Evasion + ES"),
    ("str_dex_int", "STR/DEX/INT — All defences"),
    ("universal",   "Universal"),
]

ATTR_LABELS = {t: lbl for t, lbl in TYPE_CATEGORIES}


@app.route("/")
def index():
    # Check which types have modifier data available
    available_types = []
    for type_key, label in TYPE_CATEGORIES:
        from pathlib import Path
        path = Path("data/modifiers") / f"{type_key}.json"
        available_types.append((type_key, label, path.exists()))

    return render_template(
        "index.html",
        type_categories=available_types,
        local_mode=bool(os.environ.get("LOCAL_MODE")),
    )


@app.route("/uniques")
def uniques():
    unique_gloves = converter.load_unique_gloves()

    # Group by attribute_type for display
    order = ["str", "dex", "int", "str_dex", "str_int", "dex_int", "str_dex_int", "universal"]
    groups: dict[str, list] = {}
    for g in unique_gloves:
        t = g.get("attribute_type", "unknown")
        groups.setdefault(t, []).append(g)

    ordered_groups = [(t, ATTR_LABELS.get(t, t), groups[t]) for t in order if t in groups]
    for t in groups:
        if t not in order:
            ordered_groups.append((t, t, groups[t]))

    return render_template(
        "uniques.html",
        ordered_groups=ordered_groups,
        fists_implicits=FISTS_OF_STONE_IMPLICITS,
        runeforged_implicits=RUNEFORGED_FISTS_IMPLICITS,
    )


@app.route("/api/mods")
def get_mods():
    """Return available prefix/suffix modifiers for a glove type."""
    glove_type = request.args.get("type", "dex")
    mods_data = converter.get_all_mods_for_type(glove_type)
    return jsonify(mods_data)


@app.route("/api/convert", methods=["POST"])
def convert():
    """Convert a list of selected mods to Fists of Stone equivalents."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    selected_mods = data.get("mods", [])
    results = []
    for mod in selected_mods:
        result = converter.convert_mod(mod)
        result["mod_type"] = mod.get("type", "")
        result["name"] = mod.get("name", "")
        results.append(result)

    return jsonify({
        "results": results,
        "implicits": FISTS_OF_STONE_IMPLICITS,
    })


@app.route("/api/reload", methods=["POST"])
def reload_table():
    """Reload conversion table from disk (for live updates)."""
    converter.reload_conversion_table()
    return jsonify({"status": "ok"})


@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    """Gracefully stop the server (local standalone mode only)."""
    if not os.environ.get("LOCAL_MODE"):
        return jsonify({"error": "Not available in server mode"}), 403
    import threading
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify({"status": "shutting_down"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
