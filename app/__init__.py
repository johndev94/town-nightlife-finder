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

    from .views import bp

    app.register_blueprint(bp)
    return app
