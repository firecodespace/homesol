"""AWS Lambda entry point: serves the FastAPI app behind a function URL."""

from mangum import Mangum

from homesol.main import app

handler = Mangum(app)
