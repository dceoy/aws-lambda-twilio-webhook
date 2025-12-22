# API Endpoint Workflows

This document contains Mermaid diagrams showing the workflow for each API endpoint in the Twilio webhook Lambda function.

## Overview

The Twilio webhook Lambda function provides a comprehensive set of endpoints for handling voice calls, monitoring call status, and managing interactive voice response (IVR) flows. The API includes:

- **Health Check** - Basic endpoint for monitoring Lambda function status
- **Call Handling** - Process incoming calls with TwiML templates
- **Call Transfer** - Route calls based on DTMF input
- **Call Monitoring** - Retrieve individual and batch call information
- **Digit Processing** - Handle user input for features like birthdate collection

All POST endpoints require Twilio signature validation for security, while GET endpoints are designed for internal monitoring and reporting.

## Health Check Endpoint

```mermaid
flowchart TD
    A[GET /health] --> B[check_health]
    B --> C[Return JSON Response]
    C --> D["Success message JSON"]
    D --> E[HTTP 200 OK]
```

## Transfer Call Endpoint

```mermaid
flowchart TD
    A[POST /transfer-call] --> B[Extract digits parameter]
    B --> C[Retrieve SSM parameters]
    C --> D[Validate Twilio signature]
    D --> E{Signature valid?}
    E -->|No| F[HTTP 401 Unauthorized]
    E -->|Yes| G{Check digits value}

    G -->|digits=1| H[Load connect.twiml.xml]
    H --> I[Update Stream URL with media API]
    I --> J[Set caller phone in Stream Parameter]
    J --> K[Return Voice Assistant TwiML]

    G -->|digits=2| L[Load dial.twiml.xml]
    L --> M[Format operator number to E164]
    M --> N[Set dial target]
    N --> O[Return Operator Transfer TwiML]

    G -->|Other digits| P[Load hangup.twiml.xml]
    P --> Q[Return Hangup TwiML]

    C --> R[SSM Parameters:<br/>- twilio-auth-token<br/>- media-api-url<br/>- operator-phone-number]
```

## Monitor Call Endpoint

```mermaid
flowchart TD
    A["GET /monitor-call/{call_sid}"] --> B[Retrieve SSM parameters]
    B --> C[Get Twilio credentials]
    C --> D[Create Twilio client with timeout]
    D --> E[Fetch call details]
    E --> F{Call found?}
    F -->|No| G[HTTP 404 Bad Request]
    F -->|Yes| H[Return call details JSON]
    H --> I[HTTP 200 OK]

    E --> J{Twilio API error?}
    J -->|Yes| K{Error code 20404?}
    K -->|Yes| G
    K -->|No| L[HTTP 500 Internal Server Error]

    B --> M[SSM Parameters:<br/>- twilio-account-sid<br/>- twilio-auth-token]
```

## Batch Monitor Calls Endpoint

```mermaid
flowchart TD
    A["GET /batch-monitor-calls"] --> B[Extract query parameters]
    B --> C[Validate parameters]
    C --> D{Valid parameters?}
    D -->|No| E[HTTP 400 Bad Request]
    D -->|Yes| F[Retrieve SSM parameters]
    F --> G[Create Twilio client]
    G --> H[Build filter parameters]
    H --> I[Fetch calls from Twilio]
    I --> J[Format response with pagination]
    J --> K[Return JSON response]
    K --> L[HTTP 200 OK]

    C --> M[Validation checks:<br/>- start_date required<br/>- end_date required<br/>- Valid date format<br/>- start_date <= end_date<br/>- limit 1-1000]

    H --> N[Optional filters:<br/>- status<br/>- direction<br/>- page_token]

    J --> O[Response includes:<br/>- calls array<br/>- count<br/>- next_page_token]

    F --> P[SSM Parameters:<br/>- twilio-account-sid<br/>- twilio-auth-token]
```

## Incoming Call Endpoint

```mermaid
flowchart TD
    A["POST /handle-incoming-call/{twiml_file_stem}"] --> B[Validate template exists]
    B --> C{Template found?}
    C -->|No| D[HTTP 404 Not Found]
    C -->|Yes| E[Extract caller phone number]
    E --> F[Retrieve SSM parameters]
    F --> G[Validate Twilio signature]
    G --> H{Signature valid?}
    H -->|No| I[HTTP 401 Unauthorized]
    H -->|Yes| J[Load TwiML template]
    J --> K{Template type?}

    K -->|connect.twiml.xml| L[Set media stream URL]
    L --> M[Set caller phone parameter]
    M --> N[Return Voice Assistant TwiML]

    K -->|gather.twiml.xml| O[Set webhook callback URL]
    O --> P[Return IVR Menu TwiML]

    K -->|birthdate.twiml.xml| Q[Set birthdate processing URL]
    Q --> R[Return Birthdate Input TwiML]

    K -->|Other templates| S[Use template as-is]
    S --> T[Return Static TwiML]

    F --> U[SSM Parameters:<br/>- twilio-auth-token<br/>- media-api-url<br/>- webhook-api-url]
```

## Process Birthdate Endpoint

```mermaid
flowchart TD
    A[POST /process-birthdate] --> B[Extract digits parameter]
    B --> C{Digits present?}
    C -->|No| D[HTTP 400 Bad Request]
    C -->|Yes| E{8 digits & numeric?}
    E -->|No| F[HTTP 400 Bad Request]
    E -->|Yes| G[Parse YYYYMMDD format]
    G --> H[Extract year, month, day]
    H --> I[Retrieve SSM parameters]
    I --> J[Validate Twilio signature]
    J --> K{Signature valid?}
    K -->|No| L[HTTP 401 Unauthorized]
    K -->|Yes| M[Load birthdate-confirmation.twiml.xml]
    M --> N[Update Say element with readable date]
    N --> O[Set confirmation callback URL]
    O --> P[Set retry redirect URL]
    P --> Q[Return Confirmation TwiML]

    I --> R[SSM Parameters:<br/>- twilio-auth-token<br/>- webhook-api-url]
```

## Confirm Birthdate Endpoint

```mermaid
flowchart TD
    A[POST /confirm-birthdate] --> B[Extract digits and birthdate parameters]
    B --> C[Retrieve SSM parameters]
    C --> D[Validate Twilio signature]
    D --> E{Signature valid?}
    E -->|No| F[HTTP 401 Unauthorized]
    E -->|Yes| G{Check digits value}

    G -->|digits=1| H[Load birthdate-confirmed.twiml.xml]
    H --> I[Return Success Message TwiML]

    G -->|digits=2| J[Load birthdate-retry.twiml.xml]
    J --> K[Set redirect to birthdate entry]
    K --> L[Return Retry TwiML]

    G -->|Other digits| M[Load birthdate-invalid-input.twiml.xml]
    M --> N[Return Invalid Input TwiML]

    C --> O[SSM Parameters:<br/>- twilio-auth-token<br/>- webhook-api-url]
```

## Complete Call Flow

```mermaid
flowchart TD
    A[Incoming Call] --> B[POST /incoming-call/gather]
    B --> C[Return IVR Menu TwiML]
    C --> D[User presses DTMF key]

    D --> E[POST /transfer-call?digits=X]
    E --> F{Digits value?}

    F -->|"1"| G[Connect to Voice Assistant]
    G --> H[Media Stream established]

    F -->|"2"| I[Transfer to Operator]
    I --> J[Call forwarded to operator]

    F -->|Other| K[Hangup call]

    style A fill:#e1f5fe
    style H fill:#e8f5e8
    style J fill:#e8f5e8
    style K fill:#ffebee
```

## Birthdate Collection Flow

```mermaid
flowchart TD
    A[Incoming Call] --> B[POST /incoming-call/birthdate]
    B --> C[Play birthdate prompt]
    C --> D[User enters 8 digits]

    D --> E[POST /process-birthdate?digits=YYYYMMDD]
    E --> F{Valid format?}
    F -->|No| G[Return error TwiML]
    F -->|Yes| H[Parse date components]
    H --> I[Play confirmation prompt]

    I --> J[User confirms/retries]
    J --> K[POST /confirm-birthdate?digits=X&birthdate=YYYYMMDD]
    K --> L{Confirmation choice?}

    L -->|"1" - Confirm| M[Play success message]
    L -->|"2" - Retry| N[Redirect to birthdate entry]
    L -->|Other| O[Play invalid input message]

    N --> C
    O --> I

    style A fill:#e1f5fe
    style M fill:#e8f5e8
    style G fill:#fff3e0
    style O fill:#fff3e0
```

## Security and Infrastructure Components

```mermaid
flowchart TD
    A[Twilio Webhook Request] --> B[AWS Lambda Function URL]
    B --> C[Lambda Handler]
    C --> D[Extract Request Data]
    D --> E[AWS SSM Parameter Store]
    E --> F[Retrieve Auth Token]
    F --> G[Twilio Signature Validation]
    G --> H{Valid Signature?}
    H -->|No| I[HTTP 401 Response]
    H -->|Yes| J[Process Request]
    J --> K[Load TwiML Template]
    K --> L[Defused XML Parser]
    L --> M[Dynamic Value Injection]
    M --> N[Generate TwiML Response]
    N --> O[Return XML to Twilio]

    E --> P[Secure Parameters:<br/>- twilio-auth-token<br/>- media-api-url<br/>- operator-phone-number<br/>- webhook-api-url]

    style E fill:#fff3e0
    style G fill:#e8f5e8
    style L fill:#e8f5e8
    style I fill:#ffebee
```
