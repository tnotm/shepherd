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
    
    # Register the routes (web pages) from our routes file
    from . import routes
    app.register_blueprint(routes.bp)

    print("Flask app created and configured.")
    return app