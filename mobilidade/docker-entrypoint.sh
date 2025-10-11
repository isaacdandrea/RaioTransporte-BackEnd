#!/bin/sh
set -eu

# Ensure the application directory is the working directory
cd /app

# When running inside AWS Lambda, proxy Gunicorn through the Lambda Web Adapter.
if [ "${AWS_LAMBDA_RUNTIME_API:-}" != "" ]; then
    exec /opt/aws-lambda-adapter -- "$@"
fi

exec "$@"
