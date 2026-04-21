from mangum import Mangum
from migration_agent import app

# Mangum is an adapter for running ASGI applications in AWS Lambda
# It handles the conversion between API Gateway events and ASGI requests
handler = Mangum(app)
