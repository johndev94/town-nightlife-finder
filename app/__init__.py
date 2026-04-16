import json
from pathlib import Path

from flask import Flask

from .db import close_db, init_app


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_mapping(
        SECRET_KEY="dev-secret-key",
        DATABASE=str(Path(app.root_path).parent / "nightlife.db"),
    )

    if test_config:
        app.config.update(test_config)

    init_app(app)
    app.teardown_appcontext(close_db)

    @app.context_processor
    def inject_vite_assets():
        manifest_path = Path(app.static_folder) / "dist" / ".vite" / "manifest.json"
        vite_assets = None
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            entry = manifest.get("index.html")
            if entry is None:
                entry = next(
                    (value for value in manifest.values() if isinstance(value, dict) and value.get("isEntry")),
                    None,
                )
            if entry:
                vite_assets = {
                    "js": f"dist/{entry['file']}",
                    "css": [f"dist/{asset}" for asset in entry.get("css", [])],
                }
        return {"vite_assets": vite_assets}

    from .views import bp

    app.register_blueprint(bp)
    return app
