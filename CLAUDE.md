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

## Web Search Instructions

For tasks requiring web search, always use Gemini CLI (`gemini` command) instead of the built-in web search tools (WebFetch and WebSearch).
Gemini CLI is an AI workflow tool that provides reliable web search capabilities.

### Usage

```sh
# Basic search query
gemini --sandbox --prompt "WebSearch: <query>"

# Example: Search for latest news
gemini --sandbox --prompt "WebSearch: What are the latest developments in AI?"
```

### Policy

When users request information that requires web search:

1. Use `gemini --sandbox --prompt` command via terminal
2. Parse and present the Gemini response appropriately

This ensures consistent and reliable web search results through the Gemini API.

## Code Design Principles

Follow Robert C. Martin's SOLID and Clean Code principles:

### SOLID Principles

1. **SRP (Single Responsibility)**: One reason to change per class; separate concerns (e.g., storage vs formatting vs calculation)
2. **OCP (Open/Closed)**: Open for extension, closed for modification; use polymorphism over if/else chains
3. **LSP (Liskov Substitution)**: Subtypes must be substitutable for base types without breaking expectations
4. **ISP (Interface Segregation)**: Many specific interfaces over one general; no forced unused dependencies
5. **DIP (Dependency Inversion)**: Depend on abstractions, not concretions; inject dependencies

### Clean Code Practices

- **Naming**: Intention-revealing, pronounceable, searchable names (`daysSinceLastUpdate` not `d`)
- **Functions**: Small, single-task, verb names, 0-3 args, extract complex logic
- **Classes**: Follow SRP, high cohesion, descriptive names
- **Error Handling**: Exceptions over error codes, no null returns, provide context, try-catch-finally first
- **Testing**: TDD, one assertion/test, FIRST principles (Fast, Independent, Repeatable, Self-validating, Timely), Arrange-Act-Assert pattern
- **Code Organization**: Variables near usage, instance vars at top, public then private functions, conceptual affinity
- **Comments**: Self-documenting code preferred, explain "why" not "what", delete commented code
- **Formatting**: Consistent, vertical separation, 88-char limit, team rules override preferences
- **General**: DRY, KISS, YAGNI, Boy Scout Rule, fail fast

## Development Methodology

Follow Martin Fowler's Refactoring, Kent Beck's Tidy Code, and t_wada's TDD principles:

### Core Philosophy

- **Small, safe changes**: Tiny, reversible, testable modifications
- **Separate concerns**: Never mix features with refactoring
- **Test-driven**: Tests provide safety and drive design
- **Economic**: Only refactor when it aids immediate work

### TDD Cycle

1. **Red** → Write failing test
2. **Green** → Minimum code to pass
3. **Refactor** → Clean without changing behavior
4. **Commit** → Separate commits for features vs refactoring

### Practices

- **Before**: Create TODOs, ensure coverage, identify code smells
- **During**: Test-first, small steps, frequent tests, two hats rule
- **Refactoring**: Extract function/variable, rename, guard clauses, remove dead code, normalize symmetries
- **TDD Strategies**: Fake it, obvious implementation, triangulation

### When to Apply

- Rule of Three (3rd duplication)
- Preparatory (before features)
- Comprehension (as understanding grows)
- Opportunistic (daily improvements)

### Key Rules

- One assertion per test
- Separate refactoring commits
- Delete redundant tests
- Human-readable code first

> "Make the change easy, then make the easy change." - Kent Beck
