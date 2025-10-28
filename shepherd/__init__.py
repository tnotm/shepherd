from flask import Flask
import os

def create_app(test_config=None):
    """The application factory. Creates and configures the Flask app."""
    # By adding template_folder, we explicitly tell Flask to look for the templates
    # directory one level "up" from this file, which is the project's root directory.
    app = Flask(__name__, instance_relative_config=True, template_folder='../templates')
    app.secret_key = os.urandom(24)

    # Initialize the database
    from . import database
    database.init_db()
    
    # --- NEW: Register all our new blueprints ---

    # Register the page-serving routes
    from . import view_routes
    app.register_blueprint(view_routes.bp)

    # Register the API routes (with /api prefix)
    from . import api_routes
    app.register_blueprint(api_routes.bp)

    # Register the action/form routes
    from . import action_routes
    app.register_blueprint(action_routes.bp)
    
    # The old 'routes.py' is no longer imported or used.

    print("Flask app created and configured with modular routes.")
    return app
