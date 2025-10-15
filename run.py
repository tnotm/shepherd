from shepherd import create_app
from waitress import serve

# Create the Flask app instance using our factory
app = create_app()

if __name__ == '__main__':
    # Run the app using the production-ready Waitress server
    print("Starting The Shepherd Dashboard with Waitress server...")
    serve(app, host='0.0.0.0', port=5000)