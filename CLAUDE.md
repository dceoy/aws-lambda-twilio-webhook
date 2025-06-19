# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Essential Commands

### Development Setup
```bash
# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync --all-extras
```

### Testing
```bash
# Run all tests with coverage
uv run pytest

# Run specific test file
uv run pytest test/api/test_main.py

# Run tests with verbose output
uv run pytest -v
```

### Code Quality
```bash
# Run linting with Ruff
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .

# Format code with Ruff
uv run ruff format .

# Run type checking with Pyright
uv run pyright
```

### Building and Deployment
```bash
# Build Docker image locally
docker image build -t dceoy/aws-lambda-twilio-webhook:latest .

# Build with docker buildx bake (used in CI/CD)
docker buildx bake
```

## Architecture Overview

This is an AWS Lambda function that handles Twilio webhooks for voice calls. The architecture follows a clean separation of concerns:

### Core Components

1. **Lambda Handler** (`src/twiliowebhook/api/main.py`): 
   - Implements URL routing for Lambda Function URLs
   - Three endpoints: `/health` (GET), `/transfer-call` (POST), `/incoming-call/{twiml_file_stem}` (POST)
   - Uses AWS Lambda Powertools for logging and tracing

2. **TwiML Templates** (`src/twiliowebhook/twiml/`):
   - XML templates for Twilio responses
   - Templates: `connect.twiml.xml` (voice assistant), `dial.twiml.xml` (operator transfer), `gather.twiml.xml` (IVR menu), `hangup.twiml.xml`
   - Templates support dynamic value injection via placeholders

3. **Security Layer**:
   - Twilio signature validation in `src/twiliowebhook/api/twilio.py`
   - AWS SSM Parameter Store integration for secure config in `src/twiliowebhook/api/awsssm.py`
   - Defused XML parsing to prevent XXE attacks

### Request Flow

1. Twilio sends webhook to Lambda Function URL
2. Lambda handler validates Twilio signature
3. For incoming calls: Loads appropriate TwiML template based on URL parameter
4. For call transfers: Processes DTMF input and routes accordingly
5. Dynamic values (phone numbers, media URLs) are retrieved from AWS SSM and injected into templates
6. Returns TwiML XML response to Twilio

### Key Design Patterns

- **Template-based responses**: TwiML XML templates with dynamic value injection
- **Parameter Store integration**: All configuration stored securely in AWS SSM
- **Structured logging**: Correlation IDs and structured logs for observability
- **Type safety**: Strict type checking with Pyright and comprehensive type hints
- **Container deployment**: Runs as containerized Lambda function on ARM64 (Graviton)

## Testing Approach

Tests use pytest with extensive mocking of AWS services and external dependencies. When writing tests:
- Mock AWS SSM calls using `pytest-mock`
- Mock Twilio signature validation for unit tests
- Use parametrized tests for different scenarios
- Ensure both success and error paths are tested