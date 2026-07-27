#!/usr/bin/env bash
# Packages lambda_function.py and pushes it to the already-created AWS Lambda
# function, then prints (does not run) the one-time setup steps -- IAM role,
# function creation, region choice, the Alexa skill's invocation permission --
# since those touch a real AWS account and are meant to be reviewed and run
# deliberately, not silently applied by this script. Mirrors
# energy_report/deploy.sh and home_dashboard/deploy.sh's "sync the code,
# print the rest" convention, just targeting AWS instead of domus.
#
# Usage: alexa_smart_home_bridge/deploy.sh [function-name]
set -euo pipefail

FUNCTION_NAME="${1:-alexaSmartHomeBridge}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZIP_PATH="${SCRIPT_DIR}/.build/lambda.zip"

mkdir -p "${SCRIPT_DIR}/.build"
rm -f "${ZIP_PATH}"
(cd "${SCRIPT_DIR}" && zip -q "${ZIP_PATH}" lambda_function.py)
echo "==> Built ${ZIP_PATH}"

if aws lambda get-function --function-name "${FUNCTION_NAME}" >/dev/null 2>&1; then
  echo "==> Updating existing Lambda function '${FUNCTION_NAME}'"
  aws lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${ZIP_PATH}"
  echo "==> Deployed."
  exit 0
fi

echo "==> No Lambda function named '${FUNCTION_NAME}' found (or AWS CLI isn't"
echo "authenticated) -- one-time setup steps below are NOT run automatically,"
echo "since they touch a real AWS account. Review and run them deliberately:"
echo
cat <<EOF
--- 1. Region ---------------------------------------------------------------

Must match your Alexa locale: us-east-1 (US/CA/BR), eu-west-1 (UK/DE/ES/FR),
or us-west-2 (JP/AU). Pass --region explicitly on every command below if
that's not your CLI's configured default.

--- 2. IAM role (one-time) --------------------------------------------------

aws iam create-role \\
  --role-name alexa-smart-home-bridge-role \\
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy \\
  --role-name alexa-smart-home-bridge-role \\
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

--- 3. Create the function (one-time) ---------------------------------------

aws lambda create-function \\
  --function-name ${FUNCTION_NAME} \\
  --runtime python3.13 \\
  --handler lambda_function.lambda_handler \\
  --role arn:aws:iam::<ACCOUNT_ID>:role/alexa-smart-home-bridge-role \\
  --zip-file fileb://${ZIP_PATH} \\
  --timeout 10

aws lambda update-function-configuration \\
  --function-name ${FUNCTION_NAME} \\
  --environment "Variables={BASE_URL=https://domus.ardua.com}"

--- 4. Allow the Alexa skill to invoke it (one-time, needs the skill ID) ----

aws lambda add-permission \\
  --function-name ${FUNCTION_NAME} \\
  --statement-id alexa-smart-home-trigger \\
  --action lambda:InvokeFunction \\
  --principal alexa-connectedhome.amazon.com \\
  --event-source-token <YOUR_ALEXA_SKILL_ID>

--- 5. Point the Alexa skill at this function --------------------------------

In the Alexa Developer Console (Smart Home skill -> Endpoint), set the
default endpoint to this function's ARN (from step 3's output, or
\`aws lambda get-function --function-name ${FUNCTION_NAME} --query Configuration.FunctionArn\`).

--- 6. Re-run this script -----------------------------------------------------

Once the function exists, re-running \`alexa_smart_home_bridge/deploy.sh\`
will just zip and push code updates via update-function-code.
EOF
