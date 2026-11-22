"""IoT-Based Campus Parking & Smart Transport Locator – Flask application factory."""
import os

from flask import Flask, g, jsonify, send_from_directory

from . import db as dbm
from .util import ApiError

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(db_path=None, seed=True):
    app = Flask(__name__, static_folder=None)
    app.config["DB_PATH"] = db_path or os.path.join(BASE, "campus.db")
    app.config["TIME_OFFSET"] = 0
    if not os.path.exists(app.config["DB_PATH"]) or os.path.getsize(app.config["DB_PATH"]) == 0:
        dbm.init_db(app.config["DB_PATH"], seed)

    from . import admin, auth, parking, transport
    for m in (auth, parking, transport, admin):
        app.register_blueprint(m.bp)

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify({"error": {"code": e.code, "message": e.message, "fields": e.fields}}), e.status

    @app.errorhandler(404)
    def nf(_):
        return jsonify({"error": {"code": "not_found", "message": "Resource not found.", "fields": {}}}), 404

    @app.errorhandler(405)
    def na(_):
        return jsonify({"error": {"code": "method_not_allowed", "message": "Method not allowed.", "fields": {}}}), 405

    @app.errorhandler(Exception)
    def boom(e):
        app.logger.exception(e)
        return jsonify({"error": {"code": "server_error", "message": "Something went wrong on the server.", "fields": {}}}), 500

    @app.teardown_appcontext
    def close(_):
        d = g.pop("db", None)
        if d is not None:
            d.close()

    static = os.path.join(BASE, "static")

    @app.get("/")
    def index():
        return send_from_directory(static, "index.html")

    @app.get("/static/<path:p>")
    def assets(p):
        return send_from_directory(static, p)

    return app
