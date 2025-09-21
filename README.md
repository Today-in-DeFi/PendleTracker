# Pendle PT APY Tracker

A Python command-line tool to track Pendle Principal Token (PT) APYs and market data in real-time.

## Features

- 🔍 **Real-time PT APY tracking** - Get current implied APY, underlying APY, and LP APY
- 📊 **Historical data analysis** - Track APY trends and statistics
- 🚨 **Alert system** - Set thresholds for APY and liquidity alerts
- 🔄 **Watch mode** - Continuous monitoring with auto-refresh
- 📁 **Multiple output formats** - Table, JSON, CSV, and compact views
- ⚙️ **Flexible configuration** - Environment variables, config files, and CLI arguments
- 🎨 **Rich terminal output** - Colored tables and formatted data

## Installation

```bash
pip install -r requirements.txt
```

Or install in development mode:

```bash
pip install -e .
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

### Config File

Copy `config.example.json` to `config.json` and add your PT market addresses:

```json
{
  "pts": [
    {
      "name": "stETH PT",
      "marketAddress": "0x...",
      "chainId": 1,
      "alertThreshold": 15.0,
      "enabled": true
    }
  ]
}
```

## Usage

### Basic Commands

```bash
# Track a specific PT market
pendle-tracker --pt 0x1234567890abcdef...

# Search for PT markets by symbol
pendle-tracker --search "stETH"

# Use configuration file
pendle-tracker --config config.json

# Watch mode with continuous updates
pendle-tracker --pt 0x1234... --watch

# Export data to file
pendle-tracker --pt 0x1234... --export data.json
```

### Alternative Usage (without installation)

```bash
# Run directly with Python
python -m pendle_tracker.cli --pt 0x1234...

# Or run the CLI script directly
python pendle_tracker/cli.py --pt 0x1234...
```

### Command Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `-p, --pt <address>` | PT market address to track | `--pt 0x1234...` |
| `-s, --search <query>` | Search PT markets by symbol | `--search "stETH"` |
| `-c, --config <path>` | Configuration file path | `--config pts.json` |
| `--chain-id <id>` | Blockchain chain ID | `--chain-id 1` |
| `-f, --format <type>` | Output format (table/json/csv/compact) | `--format json` |
| `-h, --history` | Include historical data | `--history` |
| `-w, --watch` | Continuous monitoring mode | `--watch` |
| `--watch-interval <sec>` | Update interval in seconds | `--watch-interval 60` |
| `--export <file>` | Export data to file | `--export data.csv` |
| `--alert-threshold <percent>` | APY alert threshold | `--alert-threshold 20` |
| `--no-colors` | Disable colored output | `--no-colors` |
| `-q, --quiet` | Minimal output | `--quiet` |
| `-v, --verbose` | Verbose error output | `--verbose` |

### Output Formats

**Table (default)** - Rich formatted table with colors
```bash
pendle-tracker --pt 0x1234... --format table
```

**JSON** - Machine-readable JSON output
```bash
pendle-tracker --pt 0x1234... --format json
```

**CSV** - Comma-separated values for spreadsheets
```bash
pendle-tracker --pt 0x1234... --format csv
```

**Compact** - Minimal single-line output
```bash
pendle-tracker --pt 0x1234... --format compact
```

## Examples

### Track Multiple PTs from Config

Create `config.json`:
```json
{
  "pts": [
    {
      "name": "stETH PT Dec 2024",
      "marketAddress": "0xabc123...",
      "chainId": 1,
      "enabled": true
    },
    {
      "name": "USDC PT Mar 2024",
      "marketAddress": "0xdef456...",
      "chainId": 1,
      "enabled": true
    }
  ],
  "alerts": {
    "enabled": true,
    "thresholds": {
      "impliedApyMin": 10.0,
      "impliedApyMax": 50.0
    }
  }
}
```

```bash
pendle-tracker --config config.json
```

### Monitor with Alerts

```bash
pendle-tracker --config config.json --watch --watch-interval 120
```

### Export Historical Data

```bash
pendle-tracker --pt 0x1234... --history --export historical-data.csv --format csv
```

### Search and Track

```bash
pendle-tracker --search "stETH" --format table --history
```

## API Data

The tracker fetches the following data from Pendle API:

### APY Metrics
- **Implied APY** - Market-derived yield expectations
- **Underlying APY** - Base protocol yields (Interest + Rewards)
- **LP APY** - Liquidity provider returns
- **Swap Fee APY** - Trading fee returns

### Market Metrics
- **Total Liquidity** - Current market liquidity
- **24h Volume** - Trading volume in last 24 hours
- **Time to Expiry** - Remaining time until PT expiry

### Historical Data
- APY trends and statistics
- Liquidity changes over time
- Min/max/average APY values

## Rate Limiting

The tool respects Pendle API rate limits (60 requests/minute by default). Requests are automatically throttled to prevent hitting limits.

## Troubleshooting

### Common Issues

**No PT data retrieved**
- Verify the market address is correct
- Check if the PT market is active
- Ensure proper chain ID

**API rate limit errors**
- Reduce watch interval frequency
- Check if multiple instances are running

**Configuration file not found**
- Verify file path is correct
- Use absolute path if needed

### Debug Mode

Run with verbose flag for detailed error information:
```bash
pendle-tracker --pt 0x1234... --verbose
```

## API Reference

Uses Pendle Finance API v2:
- Base URL: `https://api-v2.pendle.finance/core`
- Documentation: https://api-v2.pendle.finance/core/docs

## License

MIT