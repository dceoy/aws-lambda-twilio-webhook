aws-lambda-twilio-webhook
=========================

A secure, containerized AWS Lambda function for handling Twilio webhooks with voice call processing capabilities. This serverless application provides an intelligent Interactive Voice Response (IVR) system with operator transfer functionality, birthdate collection, and secure TwiML template-based responses.

[![CI/CD](https://github.com/dceoy/aws-lambda-twilio-webhook/actions/workflows/ci.yml/badge.svg)](https://github.com/dceoy/aws-lambda-twilio-webhook/actions/workflows/ci.yml)

## Features

- **Secure Webhook Processing**: Validates Twilio signature requests to ensure authenticity
- **Template-based TwiML Responses**: Dynamic XML template system with parameter injection
- **Interactive Voice Response (IVR)**: DTMF input collection with customizable prompts
- **Operator Transfer**: Seamless call routing to human operators
- **Birthdate Collection**: Specialized flows for gathering and validating user birthdate information
- **AWS Integration**: Secure configuration management using AWS Systems Manager Parameter Store
- **Containerized Deployment**: ARM64 optimized Docker container for AWS Lambda
- **Observability**: Structured logging with AWS Lambda Powertools and X-Ray tracing
- **Security**: XML External Entity (XXE) attack prevention with defused XML parsing

## Prerequisites

- **Python**: 3.13 or higher
- **UV**: Fast Python package installer and resolver ([installation guide](https://docs.astral.sh/uv/getting-started/installation/))
- **Docker**: For containerized builds and deployment
- **AWS Account**: For Lambda deployment and SSM Parameter Store
- **Twilio Account**: For webhook configuration and phone number management

## Installation

### Development Setup

Install UV package manager (if not already installed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Clone the repository and install dependencies:
```bash
git clone https://github.com/dceoy/aws-lambda-twilio-webhook.git
cd aws-lambda-twilio-webhook
uv sync --all-extras
```

## Usage

### API Endpoints

The Lambda function exposes three main endpoints via AWS Lambda Function URLs:

#### Health Check
```http
GET /health
```
Returns health status of the Lambda function.

#### Incoming Call Handler
```http
POST /incoming-call/{twiml_file_stem}
```
Handles incoming Twilio voice calls and returns appropriate TwiML responses based on the template specified in `twiml_file_stem`.

**Available Templates:**
- `connect` - Connects to voice assistant
- `gather` - IVR menu with DTMF collection
- `dial` - Direct operator transfer
- `birthdate` - Birthdate collection flow
- `hangup` - Call termination

#### Call Transfer Handler
```http
POST /transfer-call
```
Processes DTMF input from IVR interactions and routes calls accordingly.

### Configuration

The application uses AWS Systems Manager Parameter Store for secure configuration management. Required parameters include:

- Twilio authentication token
- Phone numbers for call routing
- Media URLs for voice prompts
- Other service-specific configurations

### TwiML Templates

Templates are located in `src/twiliowebhook/twiml/` and support dynamic value injection:

```xml
<!-- Example: connect.twiml.xml -->
<Response>
    <Connect>
        <ConversationRelay
            url="{conversation_relay_url}"
            welcomeGreeting="{welcome_greeting_url}"
        />
    </Connect>
</Response>
```

Values in `{}` placeholders are dynamically replaced with configuration from AWS SSM.

## Development

### Testing

Run the complete test suite:
```bash
uv run pytest
```

Run specific test file:
```bash
uv run pytest test/api/test_main.py
```

Run tests with verbose output and coverage:
```bash
uv run pytest -v --cov=src --cov-report=term-missing
```

### Code Quality

Format code:
```bash
uv run ruff format .
```

Lint code:
```bash
uv run ruff check .
```

Auto-fix linting issues:
```bash
uv run ruff check --fix .
```

Type checking:
```bash
uv run pyright
```

## Deployment

### Docker Build

Build the container image locally:
```bash
docker image build -t dceoy/aws-lambda-twilio-webhook:latest .
```

Build using docker buildx (used in CI/CD):
```bash
docker buildx bake
```

### AWS Lambda Deployment

1. **Build and push the container image** to Amazon ECR
2. **Create Lambda function** from container image
3. **Configure Lambda Function URL** for HTTP endpoint access
4. **Set up AWS SSM parameters** for configuration
5. **Configure Twilio webhook URL** to point to your Lambda Function URL

### Environment Variables

Required environment variables for the Lambda function:
- `AWS_REGION` - AWS region for SSM Parameter Store access
- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARN, ERROR)

## Architecture

### Project Structure

```
src/twiliowebhook/
├── api/
│   ├── main.py          # Lambda handler and URL routing
│   ├── twilio.py        # Twilio signature validation
│   ├── awsssm.py        # AWS SSM Parameter Store integration
│   ├── xml.py           # Secure XML processing utilities
│   └── constants.py     # Application constants
├── twiml/               # TwiML XML templates
│   ├── connect.twiml.xml
│   ├── gather.twiml.xml
│   ├── dial.twiml.xml
│   ├── birthdate*.twiml.xml
│   └── hangup.twiml.xml
└── Dockerfile           # Container build configuration

test/                    # Comprehensive test suite
├── api/
│   ├── test_main.py
│   ├── test_twilio.py
│   ├── test_awsssm.py
│   └── test_xml.py
```

### Request Flow

1. **Twilio Webhook** → AWS Lambda Function URL
2. **Signature Validation** → Verify request authenticity
3. **URL Routing** → Route to appropriate handler
4. **Template Processing** → Load and process TwiML template
5. **Parameter Injection** → Fetch values from AWS SSM and inject into template
6. **TwiML Response** → Return XML response to Twilio

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes following the coding standards
4. Run tests and ensure they pass (`uv run pytest`)
5. Run code quality checks (`uv run ruff check . && uv run pyright`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Coding Standards

- Follow PEP 8 style guidelines (enforced by Ruff)
- Maintain type hints for all functions (checked by Pyright)
- Write comprehensive tests for new functionality
- Update documentation for any API changes
- Use Google-style docstrings

## License

This project is licensed under the terms specified in the [LICENSE](LICENSE) file.

## Support

For questions, issues, or contributions, please use the [GitHub Issues](https://github.com/dceoy/aws-lambda-twilio-webhook/issues) page.
