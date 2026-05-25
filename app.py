"""Stone of Fist — Flask web calculator."""
import os
import sys
from pathlib import Path
from flask import Flask, render_template, request, jsonify
import converter


def _get_template_folder() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "templates")  # type: ignore[attr-defined]
    return "templates"


app = Flask(__name__, template_folder=_get_template_folder())

FISTS_OF_STONE_IMPLICITS = [
    "+3 to Evasion Rating per player level",
    "+1 to maximum Energy Shield per player level",
]

TYPE_LABELS = {
    "str": "Strength (Armour)",
    "dex": "Dexterity (Evasion)",
    "int": "Intelligence (Energy Shield)",
    "str_dex": "Str/Dex (Armour + Evasion)",
    "str_int": "Str/Int (Armour + ES)",
    "dex_int": "Dex/Int (Evasion + ES)",
    "universal": "Universal",
    "str_dex_int": "Str/Dex/Int (All)",
    "unknown": "Unknown",
}


@app.route("/")
def index():
    base_gloves = converter.load_base_gloves()

    # Group base gloves by type for the dropdown
    glove_groups: dict[str, list] = {}
    for g in base_gloves:
        t = g.get("type", "unknown")
        glove_groups.setdefault(t, []).append(g)

    # Order groups nicely
    ordered_types = ["str", "dex", "int", "str_dex", "str_int", "dex_int",
                     "str_dex_int", "universal", "unknown"]
    ordered_groups = [(t, TYPE_LABELS.get(t, t), glove_groups[t])
                      for t in ordered_types if t in glove_groups]
    # Add any unexpected types
    for t in glove_groups:
        if t not in ordered_types:
            ordered_groups.append((t, t, glove_groups[t]))

    # Map name → image URL for JS thumbnail preview
    glove_images = {g["name"]: g.get("image", "") for g in base_gloves}

    return render_template(
        "index.html",
        glove_groups=ordered_groups,
        type_labels=TYPE_LABELS,
        data_loaded=bool(base_gloves),
        glove_images=glove_images,
        local_mode=bool(os.environ.get("LOCAL_MODE")),
    )


@app.route("/api/mods")
def get_mods():
    """Return available prefix/suffix modifiers for a glove base type."""
    glove_name = request.args.get("base", "")
    glove_type = request.args.get("type", "dex")

    # If a base name is given, look up its type
    if glove_name:
        base_gloves = converter.load_base_gloves()
        for g in base_gloves:
            if g["name"] == glove_name:
                glove_type = g["type"]
                break

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
        result["mod_type"] = mod.get("type", "")  # Prefix or Suffix
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
