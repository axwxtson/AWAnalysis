# AW Analysis

Cross-asset market intelligence agent. Ask questions about markets in plain
English; the agent uses live data to answer.

Built as a portfolio piece, applying patterns from an 8-module AI Systems
Engineering programme (see [axwxtson/ai-systems-engineering](https://github.com/axwxtson/ai-systems-engineering)).

## Status

**Stage 1 of 8 — API layer.** Currently supports current crypto price queries
via CoinGecko. Each subsequent stage layers in patterns from one study module.

## Setup

```bash
git clone https://github.com/axwxtson/AWAnalysis.git
cd AWAnalysis
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY
```

## Usage

```bash
# One-shot
aw "What's the current price of BTC?"

# Interactive
aw
```

## Architecture (Stage 1)

user input
│
▼
CLI ──▶ AnthropicClient ──▶ Claude
│
│ tool_use
▼
ToolRegistry ──▶ CoinGecko

The agent loop in `agent/loop.py` handles the tool-use handshake until the
model produces a final answer.

## License

MIT.