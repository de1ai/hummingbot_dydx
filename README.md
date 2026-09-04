![Hummingbot](https://github.com/user-attachments/assets/3213d7f8-414b-4df8-8c1b-a0cd142a82d8)

----
[![License](https://img.shields.io/badge/License-Apache%202.0-informational.svg)](https://github.com/hummingbot/hummingbot/blob/master/LICENSE)
[![Twitter](https://img.shields.io/twitter/url?url=https://twitter.com/_hummingbot?style=social&label=_hummingbot)](https://twitter.com/_hummingbot)
[![Youtube](https://img.shields.io/youtube/channel/subscribers/UCxzzdEnDRbylLMWmaMjywOA)](https://www.youtube.com/@hummingbot)
[![Discord](https://img.shields.io/discord/530578568154054663?logo=discord&logoColor=white&style=flat-square)](https://discord.gg/hummingbot)

This fork integrates **dYdX v4 perpetual market making** on Hummingbot. Use the guide below as the entry point to install, configure, and run maker/taker bots. Upstream Hummingbot CLI, Docker, strategies, and other connectors are in [Hummingbot Framework](#hummingbot-framework).

## Quick Links

* [dYdX v4 Deployment](#dydx-v4-perpetual-market-making): Feature entry — deploy and run dYdX v4 perpetual market making
* [Hummingbot Framework](#hummingbot-framework): Upstream install (`hbot`, Docker, TUI), strategies, and connectors
* [Website and Docs](https://hummingbot.org): Official Hummingbot website and documentation
* [Installation](https://hummingbot.org/installation/): Install Hummingbot on various platforms
* [Discord](https://discord.gg/hummingbot): The main gathering spot for the global Hummingbot community
* [YouTube](https://www.youtube.com/c/hummingbot): Videos that teach you how to get the most out of Hummingbot
* [Twitter](https://twitter.com/_hummingbot): Get the latest announcements about Hummingbot
* [Reported Volumes](https://reporting.hummingbot.org/): Reported trading volumes across all Hummingbot instances
* [Newsletter](https://hummingbot.substack.com): Get our newsletter whenever we ship a new release

## dYdX v4 Perpetual Market Making

This fork ships a ready-to-run **dYdX v4 perpetual market making** setup for local and Docker environments. The sections below cover strategy behavior, connector architecture, node configuration, config files, and common failure modes.

### Strategy overview

The `perpetual_market_making` strategy keeps bids and asks on both sides of the book and captures the spread.

- **Multi-level grid**: One or more laddered levels on each side (for example 5 levels per side), with a configurable spread and size step.
- **Order refresh**: Cancel and replace on `order_refresh_time`, unless the mid-price move is within `order_refresh_tolerance_pct`.
- **Filled-order delay**: After a full fill on one side, wait before replacing, to avoid being run over in a fast market.
- **Risk management**:
  - **Profit taking**: Place reduce-only exits when long/short PnL reaches `long/short_profit_taking_spread`.
  - **Stop loss**: Flatten when loss reaches `stop_loss_spread`, with a slippage buffer.
  - **Price ceiling & floor**: Pause one side of quoting outside a protected price band.

### Connector architecture

dYdX v4 runs on Cosmos SDK (dYdX Chain). The `dydx_v4_perpetual` connector uses a hybrid stack:

```
+-------------------------------------------------------------+
|                      Hummingbot Core                        |
+------------------------------+------------------------------+
                               |
       +-----------------------+-----------------------+
       | (REST / WebSocket)                            | (gRPC / Cosmos Tx)
       v                                               v
+-----------------------------+                 +-----------------------------+
|     dYdX Indexer API        |                 |   dYdX Node (Validator)     |
| (market data / order book / |                 | (gRPC tx broadcast and      |
|  account history / WS)      |                 |  account queries)           |
+-----------------------------+                 +-----------------------------+
```

**Indexer REST / WebSocket**

- `GET /v4/perpetualMarkets`: market specs, tick size, leverage rules
- `GET /v4/orderbooks/perpetualMarket`: order book snapshot
- `GET /v4/time`: server clock sync
- `WS v4_orderbook / v4_trades`: live depth and trades
- `WS v4_subaccounts`: positions, margin, and fills

**Validator gRPC (on-chain)**

- Query: `cosmos.auth.v1beta1.QueryStub` (account number and sequence)
- Broadcast: `cosmos.tx.v1beta1.ServiceStub.BroadcastTx` (signed place/cancel)
- Place: `dydxprotocol.clob.tx_pb2.MsgPlaceOrder` (short-term orders expire after ~20 blocks)
- Cancel: `dydxprotocol.clob.tx_pb2.MsgCancelOrder`

### Environment and node configuration

Set nodes in `hummingbot/connector/derivative/dydx_v4_perpetual/dydx_v4_perpetual_constants.py` for a local chain, testnet, or mainnet:

```python
# gRPC node (signed tx broadcast and sequence queries)
DYDX_V4_AERIAL_CONFIG_URL = '127.0.0.1:9090'        # local nodes often use 9090
DYDX_V4_QUERY_AERIAL_CONFIG_URL = '127.0.0.1:9090'
DYDX_V4_GRPC_INSECURE = True                        # True for plaintext local/private; False for mainnet TLS
CHAIN_ID = 'localdydxprotocol'                      # mainnet: dydx-mainnet-1

# Indexer and WebSocket
DYDX_V4_INDEXER_REST_BASE_URL = "http://127.0.0.1:3002"
DYDX_V4_WS_URL = "ws://127.0.0.1:3003/v4/ws"
```

### Local install and run

```bash
# Conda env + C/Cython extensions
make install

# dYdX-specific conda env (setup/environment_dydx.yml)
make install DYDX=1

conda activate hummingbot

# Rebuild Cython after connector/strategy C changes
python setup.py build_ext --inplace
```

Write the wallet mnemonic and chain address to `conf/connectors/dydx_v4_perpetual.yml` (or the matching file under a `conf_dydx_*` directory):

```yaml
dydx_v4_perpetual_secret_phrase: "your twelve or twenty four word mnemonic phrase ..."
dydx_v4_perpetual_chain_address: "dydx1..."
```

Ready-made layouts in this repo:

| Role | Directory | Strategy / script |
|------|-----------|-------------------|
| ETH-USD maker | `conf_dydx_eth_maker/` | `strategies/dydx_eth_usd_maker.yml` |
| DDT-USD maker | `conf_dydx_ddt_maker/` | `strategies/dydx_ddt_usd_maker.yml` |
| ETH-USD taker | `conf_dydx_eth_taker/` | `scripts/dydx_auto_order_taker_eth.yml` |
| DDT-USD taker | `conf_dydx_ddt_taker/` | `scripts/dydx_auto_order_taker_ddt.yml` |

Encrypt credentials with:

```bash
python scripts/dydx_connector_config.py <output_dir> <password> '<mnemonic>' 'dydx1...'
```

Quickstart (background / automation):

```bash
./bin/hummingbot_quickstart.py --config dydx_eth_usd_maker.yml --wallet-password "your_password"
```

Interactive client:

```bash
bin/hummingbot.py
```

Then in the client:

```text
connect dydx_v4_perpetual
import dydx_eth_usd_maker.yml
start
```

### Docker install and run

```bash
docker build -t hummingbot/hummingbot:latest -f Dockerfile .
```

`docker-compose.yml` bind-mounts local `conf`, `logs`, `data`, and `scripts`:

```bash
docker compose up -d
docker compose logs -f hummingbot
docker attach hummingbot
```

One-shot container:

```bash
docker run -it --rm \
  --name dydx_maker \
  --network host \
  -v $(pwd)/conf:/home/hummingbot/conf \
  -v $(pwd)/logs:/home/hummingbot/logs \
  -v $(pwd)/data:/home/hummingbot/data \
  hummingbot/hummingbot:latest \
  ./bin/hummingbot_quickstart.py --config dydx_eth_usd_maker.yml --wallet-password "your_password"
```

Copy or symlink a `conf_dydx_*` tree into `conf/` before starting, so the container sees connectors and strategies.

### Config reference

Example `perpetual_market_making` template:

```yaml
template_version: 6
strategy: perpetual_market_making

# Connector and market
derivative: dydx_v4_perpetual
market: ETH-USD                     # e.g. ETH-USD, DDT-USD

# Leverage and position mode
leverage: 5
position_mode: One-way

# Spreads and grid
bid_spread: 0.3                     # first bid distance from mid (%)
ask_spread: 0.3                     # first ask distance from mid (%)
order_levels: 5                     # levels per side (10 orders total)
order_level_spread: 0.3             # extra spread per additional level (%)
order_level_amount: 0.0             # size increment per level (0 = same size)
order_amount: 0.006                 # base size per level

# Refresh
order_refresh_time: 30.0            # refresh interval (seconds)
order_refresh_tolerance_pct: 0.1    # skip cancel if price moved less than this
filled_order_delay: 10.0            # wait after a full fill before re-quoting

# Risk
stop_loss_spread: 2.0               # flatten at 2.0% loss
stop_loss_slippage_buffer: 0.5      # stop-loss slippage buffer (%)
time_between_stop_loss_orders: 60.0 # retry interval if stop is unfilled
long_profit_taking_spread: 1.5      # take profit on longs at 1.5%
short_profit_taking_spread: 1.5     # take profit on shorts at 1.5%

# Price band (-1.0 = disabled)
price_ceiling: -1.0
price_floor: -1.0

# Pricing
order_optimization_enabled: false   # jump-the-book optimization
price_source: current_market        # price from the local order book
price_type: mid_price               # mid_price or last_price
```

### Operations and monitoring

CLI:

- `status`: strategy state, spreads, open orders, position, and PnL
- `history`: fills, maker PnL, and fees
- `config`: view or change parameters
- `stop`: stop the strategy and cancel open orders

Logs under `./logs/`:

- `logs/logs_<config_name>.log`: strategy lifecycle and order state
- `logs/hummingbot_quickstart.log`: launcher log

### FAQ

**`account sequence mismatch`**

Cosmos txs must use a strictly increasing sequence. Concurrent local broadcasts or txs from another wallet desync it. The connector in `dydx_v4_data_source.py` detects the mismatch and calls `initialize_trading_account()` to resync.

**`Stateful order does not exist`**

Short-term orders expire after a block-height window (typically ~20 blocks). If a cancel arrives after the chain has already dropped the order, the connector treats it as already cancelled.

**Order size rejected / precision error**

Each market has `stepBaseQuantums` (size step) and `subticksPerTick` (price step). Check that `order_amount` meets the minimum size and that margin covers the configured leverage.

---

## Hummingbot Framework

Hummingbot is an open-source framework that helps you design and deploy automated trading strategies, or **bots**, that can run on many centralized or decentralized exchanges. Over the past year, Hummingbot users have generated over $34 billion in trading volume across 140+ unique trading venues.

The Hummingbot codebase is free and publicly available under the Apache 2.0 open-source license. Our mission is to **democratize high-frequency trading** by creating a global community of algorithmic traders and developers that share knowledge and contribute to the codebase.

### Getting Started

#### Condor (AI harness)

**[Condor](https://github.com/hummingbot/condor)** is the AI harness for building and running agentic strategies and bot instances. It connects LLM-powered decision-making to deterministic trade execution via the Hummingbot API, controlled through Telegram or its web dashboard. See **[condor.hummingbot.org](https://condor.hummingbot.org/)** to get started.

#### `hbot` CLI

The recommended way to run the Hummingbot client directly is the **`hbot` command-line interface**, installed from
source. `hbot` runs, controls, and monitors a trading bot non-interactively: start/stop a bot, author
and tune configs, and read trades, PnL, logs, and status — all scriptable, as compact Markdown with
stable exit codes. See the **[hbot CLI guide](hummingbot/cli/README.md)** for the full reference.

Requires [Anaconda or Miniconda](https://www.anaconda.com/download).

```bash
# Clone the repository
git clone https://github.com/hummingbot/hummingbot.git
cd hummingbot

# Create the conda environment, build extensions, and expose the `hbot` CLI
make install

# Activate the environment
conda activate hummingbot
hbot --help
```

To use `hbot` outside the conda environment, run `make link-cli` to add it to your host PATH.

On first use, `hbot` prompts for a keystore password that encrypts your exchange API keys — set `HBOT_PASSWORD` or pass `--password-stdin` to run non-interactively (e.g. in scripts or agent workflows).

Then create a config and run the `simple_pmm` **paper trading script** — it simulates trading against live Binance market data, so no API keys are required:

```bash
hbot create simple_pmm --name conf_paper_bot.yml \
     --set exchange=binance_paper_trade --set trading_pair=BTC-USDT
hbot start conf_paper_bot.yml                          # run it (one bot per install)
hbot status                                            # check on it
hbot stop                                              # stop gracefully
```

To trade **live**, connect your exchange API keys and run a **strategy controller** like `pmm_mister` — a reusable V2 strategy whose settings can be tuned live while the bot runs:

```bash
hbot connect binance                                   # store API keys (encrypted)
hbot create pmm_mister --name conf_my_bot.yml \
     --set connector_name=binance --set trading_pair=BTC-USDT --set total_amount_quote=100
hbot start conf_my_bot.yml                             # run it (one bot per install)
```

Full command reference and ontology: **[hbot CLI guide](hummingbot/cli/README.md)**.

#### Docker

Prefer containers? `hbot` works the same way — install [Docker Compose](https://docs.docker.com/compose/install/), then:

```bash
git clone https://github.com/hummingbot/hummingbot.git
cd hummingbot
make setup            # answer `y` to "Include Gateway?" to add the DEX middleware
make deploy           # start the container (interactive client by default)
make link-cli         # put the `hbot` command on your host PATH (dispatches into the container)

hbot --help           # same commands as the source install above
```

`make link-cli` installs a small wrapper that runs `hbot` inside the container, so every command
above is identical whether you installed from source or Docker. (Or skip it and use
`docker exec -it hummingbot hbot <command>`.) To dedicate the container to `hbot` instead of the
interactive client, uncomment `command: tail -f /dev/null` in `docker-compose.yml` before
`make deploy` — see [Running in Docker](hummingbot/cli/README.md#running-in-docker).

#### Interactive Client (TUI)

The classic full-screen client is the Docker default:
`make deploy`, then `docker attach hummingbot` — or run it from source with
`make install && make run`. With Gateway included it starts in development mode
(unencrypted HTTP); for production HTTPS use the `DEV=false` flag and run `gateway generate-certs`.
See [Development vs Production Modes](https://hummingbot.org/gateway/installation/#development-vs-production-modes).

For comprehensive installation instructions and troubleshooting, visit our [Installation](https://hummingbot.org/installation/) documentation.

### Strategies

Hummingbot offers several frameworks for building and running algorithmic trading strategies — see the [Strategies docs](https://hummingbot.org/strategies/) for a full overview:

* **[Scripts](./scripts)**: Single-file Python strategies — the easiest way to build and customize your own bot. Example: [`simple_pmm.py`](./scripts/simple_pmm.py), a basic market making script.
* **[Controllers](./controllers)**: Reusable V2 strategies whose configs can be backtested, deployed, and tuned live while running. Example: [`pmm_mister.py`](./controllers/generic/pmm_mister.py), a full-featured market making controller.
* **[Executors](./hummingbot/strategy_v2/executors)**: Self-contained building blocks that manage order lifecycles for common patterns — position, DCA, grid, arbitrage, XEMM, TWAP, and LP. Example: [`position_executor`](./hummingbot/strategy_v2/executors/position_executor), which manages a directional position with triple-barrier risk controls.
* **[V1 Strategies](./hummingbot/strategy)**: Classic legacy strategies such as Pure Market Making, Avellaneda Market Making, and Cross-Exchange Market Making. Example: [`cross_exchange_market_making`](./hummingbot/strategy/cross_exchange_market_making), which market makes on one exchange and hedges fills on another.

### Exchange Connectors

Hummingbot connectors standardize REST and WebSocket API interfaces to different types of exchanges, enabling you to build sophisticated trading strategies that can be deployed across many exchanges with minimal changes.

#### Connector Types

We classify exchange connectors into three main categories:

* **CLOB CEX**: Centralized exchanges with central limit order books that take custody of your funds. Connect via API keys.
  - **Spot**: Trading spot markets
  - **Perpetual**: Trading perpetual futures markets

* **CLOB DEX**: Decentralized exchanges with on-chain central limit order books. Non-custodial, connect via wallet keys.
  - **Spot**: Trading spot markets on-chain
  - **Perpetual**: Trading perpetual futures on-chain

* **AMM DEX**: Decentralized exchanges using Automated Market Maker protocols. Non-custodial, connect via Gateway middleware.
  - **Router**: DEX aggregators that find optimal swap routes
  - **AMM**: Traditional constant product (x*y=k) pools
  - **CLMM**: Concentrated Liquidity Market Maker pools with custom price ranges

#### Exchange Sponsors

We are grateful for the following exchanges that support the development and maintenance of Hummingbot via broker partnerships and sponsorships.

| Exchange | Type | Sub-Type(s) | Connector ID(s) | Discount |
|------|------|------|-------|----------|
| [Backpack](https://hummingbot.org/exchanges/backpack/) | CLOB CEX | Spot, Perpetual | `backpack`, `backpack_perpetual` | [![Sign up for Backpack using Hummingbot's referral link!](https://img.shields.io/static/v1?label=Sponsor&message=Link&color=orange)](https://backpack.exchange/join/1tvdqfkk) |
| [Binance](https://hummingbot.org/exchanges/binance/) | CLOB CEX | Spot, Perpetual | `binance`, `binance_perpetual` | [![Sign up for Binance using Hummingbot's referral link for a 10% discount!](https://img.shields.io/static/v1?label=Fee&message=%2d10%25&color=orange)](https://accounts.binance.com/register?ref=CBWO4LU6) |
| [Bitget](https://hummingbot.org/exchanges/bitget/) | CLOB CEX | Spot, Perpetual | `bitget`, `bitget_perpetual` | [![Sign up for Bitget using Hummingbot's referral link!](https://img.shields.io/static/v1?label=Sponsor&message=Link&color=orange)](https://www.bitget.com/expressly?channelCode=v9cb&vipCode=26rr&languageType=0) |
| [Derive](https://hummingbot.org/exchanges/derive/) | CLOB DEX | Spot, Perpetual | `derive`, `derive_perpetual` | [![Sign up for Derive using Hummingbot's referral link!](https://img.shields.io/static/v1?label=Sponsor&message=Link&color=orange)](https://www.derive.xyz/invite/7SA0V) |
| [Gate.io](https://hummingbot.org/exchanges/gate-io/) | CLOB CEX | Spot, Perpetual | `gate_io`, `gate_io_perpetual` | [![Sign up for Gate.io using Hummingbot's referral link for a 20% discount!](https://img.shields.io/static/v1?label=Fee&message=%2d20%25&color=orange)](https://www.gate.io/referral/invite/HBOTGATE_0_103) |
| [Hyperliquid](https://hummingbot.org/exchanges/hyperliquid/) | CLOB DEX | Spot, Perpetual | `hyperliquid`, `hyperliquid_perpetual` | - |
| [KuCoin](https://hummingbot.org/exchanges/kucoin/) | CLOB CEX | Spot, Perpetual | `kucoin`, `kucoin_perpetual` | [![Sign up for Kucoin using Hummingbot's referral link for a 20% discount!](https://img.shields.io/static/v1?label=Fee&message=%2d20%25&color=orange)](https://www.kucoin.com/r/af/hummingbot) |
| [Meteora](https://hummingbot.org/exchanges/gateway/meteora/) | AMM DEX | CLMM | `meteora` | - |
| [OKX](https://hummingbot.org/exchanges/okx/) | CLOB CEX | Spot, Perpetual | `okx`, `okx_perpetual` | [![Sign up for OKX using Hummingbot's referral link for a 20% discount!](https://img.shields.io/static/v1?label=Fee&message=%2d20%25&color=orange)](https://www.okx.com/join/1931920269) |
| [Orca](https://hummingbot.org/exchanges/gateway/orca/) | AMM DEX | CLMM | `orca` | - |
| [XRP Ledger](https://hummingbot.org/exchanges/xrpl/) | CLOB DEX | Spot | `xrpl` | - |

#### Other Exchange Connectors

Currently, the master branch of Hummingbot also includes the following exchange connectors, which are maintained and updated through the Hummingbot Foundation governance process. See [Governance](https://hummingbot.org/about/governance/) for more information.

| Exchange | Type | Sub-Type(s) | Connector ID(s) | Discount |
|------|------|------|-------|----------|
| [0x Protocol](https://hummingbot.org/gateway/connectors/) | AMM DEX | Router | `0x` | - |
| [Aevo](https://hummingbot.org/exchanges/aevo/) | CLOB CEX | Perpetual | `aevo_perpetual` | - |
| [Architect](https://hummingbot.org/exchanges/architect/) | CLOB CEX | Perpetual | `architect_perpetual` | - |
| [Balancer](https://hummingbot.org/exchanges/gateway/balancer/) | AMM DEX | AMM | `balancer` | - |
| [BingX](https://hummingbot.org/exchanges/bing_x/) | CLOB CEX | Spot | `bing_x` | - |
| [Bitrue](https://hummingbot.org/exchanges/bitrue/) | CLOB CEX | Spot | `bitrue` | - |
| [Bitstamp](https://hummingbot.org/exchanges/bitstamp/) | CLOB CEX | Spot | `bitstamp` | - |
| [BTC Markets](https://hummingbot.org/exchanges/btc-markets/) | CLOB CEX | Spot | `btc_markets` | - |
| [Bybit](https://hummingbot.org/exchanges/bybit/) | CLOB CEX | Spot, Perpetual | `bybit`, `bybit_perpetual` | - |
| [Coinbase](https://hummingbot.org/exchanges/coinbase/) | CLOB CEX | Spot | `coinbase_advanced_trade` | - |
| [Curve](https://hummingbot.org/exchanges/gateway/curve/) | AMM DEX | AMM | `curve` | - |
| [Decibel](https://hummingbot.org/exchanges/decibel/) | CLOB CEX | Perpetual | `decibel_perpetual` | - |
| [Dexalot](https://hummingbot.org/exchanges/dexalot/) | CLOB DEX | Spot | `dexalot` | - |
| [DFlow](https://hummingbot.org/exchanges/gateway/jupiter/#other-solana-routers) | AMM DEX | Router | `dflow` | - |
| [dYdX](https://hummingbot.org/exchanges/dydx/) | CLOB DEX | Perpetual | `dydx_v4_perpetual` | - |
| [EVEDEX](https://hummingbot.org/exchanges/evedex/) | CLOB CEX | Perpetual | `evedex_perpetual` | - |
| [Foxbit](https://hummingbot.org/exchanges/foxbit/) | CLOB CEX | Spot | `foxbit` | - |
| [Gemini](https://hummingbot.org/exchanges/gemini/) | CLOB CEX | Spot | `gemini` | - |
| [GRVT](https://hummingbot.org/exchanges/grvt/) | CLOB CEX | Perpetual | `grvt_perpetual` | - |
| [HTX (Huobi)](https://hummingbot.org/exchanges/htx/) | CLOB CEX | Spot | `htx` | - |
| [Injective Helix](https://hummingbot.org/exchanges/injective/) | CLOB DEX | Spot, Perpetual | `injective_v2`, `injective_v2_perpetual` | - |
| [Jupiter](https://hummingbot.org/exchanges/gateway/jupiter/) | AMM DEX | Router | `jupiter` | - |
| [Kraken](https://hummingbot.org/exchanges/kraken/) | CLOB CEX | Spot | `kraken` | - |
| [Lambdaplex](https://hummingbot.org/exchanges/lambdaplex/) | CLOB DEX | Spot | `lambdaplex` | - |
| [Lighter](https://hummingbot.org/exchanges/lighter/) | CLOB DEX | Spot, Perpetual | `lighter`, `lighter_perpetual` | - |
| [MEXC](https://hummingbot.org/exchanges/mexc/) | CLOB CEX | Spot | `mexc` | - |
| [NDAX](https://hummingbot.org/exchanges/ndax/) | CLOB CEX | Spot | `ndax` | - |
| [OKX DEX](https://hummingbot.org/exchanges/gateway/jupiter/#other-solana-routers) | AMM DEX | Router | `okx` | - |
| [Pacifica](https://hummingbot.org/exchanges/pacifica/) | CLOB CEX | Perpetual | `pacifica_perpetual` | - |
| [PancakeSwap](https://hummingbot.org/exchanges/gateway/pancakeswap/) | AMM DEX | AMM | `pancakeswap` | - |
| [Raydium](https://hummingbot.org/exchanges/gateway/raydium/) | AMM DEX | AMM, CLMM | `raydium` | - |
| [Titan](https://hummingbot.org/exchanges/gateway/jupiter/#other-solana-routers) | AMM DEX | Router | `titan` | - |
| [Uniswap](https://hummingbot.org/exchanges/gateway/uniswap/) | AMM DEX | Router, AMM, CLMM | `uniswap` | - |

### Other Hummingbot Repos

* [Condor](https://github.com/hummingbot/condor): AI harness for building and running agentic strategies and bot instances
* [Hummingbot API](https://github.com/hummingbot/hummingbot-api): The central hub for running Hummingbot trading bots
* [Gateway](https://github.com/hummingbot/gateway): Typescript based API client for DEX connectors
* [Hummingbot Site](https://github.com/hummingbot/hummingbot-site): Official documentation for Hummingbot - we welcome contributions here too!

### Getting Help

If you encounter issues or have questions, here's how you can get assistance:

* Consult our [FAQ](https://hummingbot.org/faq/), [Troubleshooting Guide](https://hummingbot.org/troubleshooting/), or [Glossary](https://hummingbot.org/glossary/)
* To report bugs or suggest features, submit a [GitHub issue](https://github.com/hummingbot/hummingbot/issues)
* Join our [Discord community](https://discord.gg/hummingbot) and ask questions in the #support channel

We pledge that we will not use the information/data you provide us for trading purposes nor share them with third parties.

### Contributions

The Hummingbot architecture features modular components that can be maintained and extended by individual community members.

We welcome contributions from the community! Please review these [guidelines](./CONTRIBUTING.md) before submitting a pull request.

If you represent an exchange that wants an official Hummingbot connector, see [How to Add a Hummingbot Connector](https://hummingbot.org/exchanges/#how-to-add-a-hummingbot-connector) for the available integration options.

### Legal

* **License**: Hummingbot is open source and licensed under [Apache 2.0](./LICENSE).
* **Data collection**: See [Reporting](https://hummingbot.org/reporting/) for information on anonymous data collection and reporting in Hummingbot.
