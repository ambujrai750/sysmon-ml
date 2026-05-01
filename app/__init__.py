# app/__init__.py
# This file turns the 'app' folder into a Python package
# and creates the Flask application instance.

from flask import Flask
from flask_socketio import SocketIO

# SocketIO enables real-time WebSocket communication between server and browser
socketio = SocketIO(cors_allowed_origins="*", async_mode="eventlet")


def create_app():
    """
    Application Factory Pattern:
    Instead of creating the Flask app at module level,
    we wrap it in a function. This is a best practice for
    larger projects and makes testing easier.
    """
    app = Flask(
        __name__,
        template_folder="../templates",  # where HTML files live
        static_folder="../static",        # where CSS/JS files live
    )

    app.config["SECRET_KEY"] = "sysmon-secret-key-change-in-production"

    # Register all API routes (blueprints) with the app
    from app.routes import main_bp
    app.register_blueprint(main_bp)

    # Attach SocketIO to the Flask app
    socketio.init_app(app)

    return app
