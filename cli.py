from waitress import serve
from server import app

def main():
    serve(app, host="0.0.0.0", port=8069)