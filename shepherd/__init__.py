from flask import Flask
import os

def create_app(test_config=None):
    """The application factory. Creates and configures the Flask app."""
    # Explicitly tell Flask where the templates and static files are relative
    # to the 'shepherd' package directory (one level up).
    app = Flask(__name__,
                instance_relative_config=True,
                template_folder='../templates',
                static_folder='../static') # <-- ADDED THIS LINE
                
    app.secret_key = os.urandom(24)

    # Initialize the database
    # Import database functions AFTER app creation to avoid circular imports if needed
    from . import database
    try:
        database.init_db()
        print("[App Factory] Database initialized/verified.")
    except Exception as e:
        print(f"[App Factory] CRITICAL ERROR during database initialization: {e}")
        # Depending on severity, you might want to raise the exception
        # or handle it gracefully (e.g., show an error page).
        # For now, we'll just print it and continue.

    # Register blueprints for different route modules
    print("[App Factory] Registering blueprints...")
    try:
        from . import view_routes
        app.register_blueprint(view_routes.bp)
        print("  - Registered view_routes (main)")

        from . import api_routes
        app.register_blueprint(api_routes.bp, url_prefix='/api') # APIs live under /api
        print("  - Registered api_routes (api)")

        from . import action_routes
        app.register_blueprint(action_routes.bp) # Actions can live at root for simplicity
        print("  - Registered action_routes (actions)")

    except Exception as e:
        print(f"[App Factory] CRITICAL ERROR during blueprint registration: {e}")
        # This is likely fatal, so re-raising might be appropriate
        raise e

    print("[App Factory] Flask app created and configured successfully.")
    return app

