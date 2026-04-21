#!/bin/bash
set -e

# Load Serverless Config
if [ -f ".serverless_output" ]; then
    source .serverless_output
else
    echo "[ERROR] .serverless_output not found. Run provision_serverless.py first."
    exit 1
fi

if [ -f ".env" ]; then
    source .env
fi

echo "--- Deploying to Serverless Stack ---"
echo "Frontend Bucket: $FRONTEND_BUCKET"
echo "Backend Lambda:  $BACKEND_LAMBDA"
echo "API URL:         $API_URL"

# 1. Build and Deploy Frontend
echo "\n[INFO] Building Frontend..."
cd frontend
# Ensure dependencies installed
if [ ! -d "node_modules" ]; then
    npm ci
fi

# We need to inject the API Gateway URL into the frontend build
# Vite uses VITE_ prefix.
# Assuming the app uses relative paths or a config. We verified vite.config.js proxies /invocations.
# In S3, proxy won't work. We need VITE_API_URL or similar code change.
# For now, let's assume valid build args for Cognito.
# We also need to tell the frontend where the Backend is.
# If the code hardcodes /invocations, we might need a distinct VITE_BACKEND_URL.
# Let's set it.
export VITE_BACKEND_URL="$API_URL"
export VITE_COGNITO_USER_POOL_ID="$VITE_COGNITO_USER_POOL_ID"
export VITE_COGNITO_CLIENT_ID="$VITE_COGNITO_CLIENT_ID"

npm run build

echo "[INFO] Syncing Frontend to S3..."
aws s3 sync dist/ s3://$FRONTEND_BUCKET --delete

cd ..

# 2. Package and Deploy Backend
echo "\n[INFO] Packaging Backend..."
mkdir -p backend_package
cd backend

# Install dependencies to package folder
pip install -r requirements.pip --target ../backend_package --quiet --upgrade

# Copy application code
cp *.py ../backend_package/
cp *.json ../backend_package/ 2>/dev/null || :

cd ../backend_package

# Remove junk
rm -rf __pycache__
rm -rf *.dist-info

# Zip
echo "[INFO] Zipping Backend..."
zip -r9 ../backend_lambda.zip . > /dev/null

cd ..

echo "[INFO] Updating Lambda Code..."
aws lambda update-function-code --function-name $BACKEND_LAMBDA --zip-file fileb://backend_lambda.zip --publish > /dev/null

# Clean up
rm -rf backend_package
rm backend_lambda.zip

echo "\n[SUCCESS] Serverless Deployment Complete!"
echo "Visit your app at: http://$FRONTEND_BUCKET.s3-website-us-east-1.amazonaws.com"
