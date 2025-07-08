# Simple Chatbot to demonstrate Ponder's usage with Pipecat

A FastAPI server that manages bot instances and provides endpoints for both Daily Prebuilt and Pipecat client connections.

## Environment Variables

Copy `env.example` to `.env` and configure:

```ini
# Required API Keys
DAILY_API_KEY=           # Your Daily API key
OPENAI_API_KEY=          # Your OpenAI API key (required for the LLM)
PONDER_API_KEY=          # Your Ponder API key

# Optional Configuration
HOST=                    # Optional: Host address (defaults to 0.0.0.0)
FAST_API_PORT=           # Optional: Port number (defaults to 7860)
```


## Running the Server

Set up and activate your virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the server:

```bash
python server.py
```

The simplest way to connect to the chatbot using Daily's Prebuilt UI.

1. Visit http://localhost:7860

2. Allow microphone access when prompted

3. Start talking with the bot


## Troubleshooting

If you encounred this error:

```bash
aiohttp.client_exceptions.ClientConnectorCertificateError: Cannot connect to host api.daily.co:443 ssl:True [SSLCertVerificationError: (1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1000)')]
```

It's because Python cannot verify the SSL certificate from https://api.daily.co when making a POST request to create a room or token.

This is a common issue when the system doesn't have the proper CA certificates.

Install SSL Certificates (macOS): `/Applications/Python\ 3.12/Install\ Certificates.command`
