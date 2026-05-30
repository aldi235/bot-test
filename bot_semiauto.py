"""
ARB·X — Base Network Arbitrage Scanner
Detects price discrepancies between DEXs on Base.
Data sources: On-chain RPC (web3.py) + The Graph subgraphs.

NO execution. READ-ONLY. Safe to run.
"""

import asyncio
import aiohttp
import time
import json
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Optional
from web3 import Web3
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich import box
from rich.text import Text
from rich.columns import Columns
import argparse

console = Console()

# ─── CONFIG ──────────────────────────────────────────────────────────────────

# Ganti dengan RPC Base kamu (gratis: publicnode, llamarpc, dll)
RPC_URL = "https://mainnet.base.org"

# Minimum spread (%) setelah estimasi gas buat dianggap opportunity
MIN_SPREAD_PCT = 0.3

# Estimasi gas cost untuk 1 arb trade di Base (dalam USD)
# Base gas sangat murah, ~$0.01-0.05 per swap
GAS_COST_USD = 0.05

# Interval scan (detik)
SCAN_INTERVAL = 5

# ─── DEX SUBGRAPH ENDPOINTS (The Graph) ──────────────────────────────────────

SUBGRAPHS = {
    "Uniswap V3": "https://api.thegraph.com/subgraphs/name/lyotam/base-v3",
    "Aerodrome":  "https://api.thegraph.com/subgraphs/name/aerodrome-finance/aerodrome",
    "BaseSwap":   "https://api.thegraph.com/subgraphs/name/baseswapfi/v3-base",
    "SwapBased":  "https://api.thegraph.com/subgraphs/name/swapbased/exchange",
}

# ─── TOKEN LIST (Base Mainnet) ────────────────────────────────────────────────

TOKENS = {
    "WETH":  "0x4200000000000000000000000000000000000006",
    "USDC":  "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "USDbC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
    "DAI":   "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "cbETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
    "WBTC":  "0x1ceA84203673764244E05693e42E6Ace62bE9BA5",
    "AERO":  "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
    "BSWAP": "0x78a087d713Be963Bf307b18F2Ff8122EF9A09aa6",
}

# Pair yang mau di-scan
PAIRS = [
    ("WETH", "USDC"),
    ("WETH", "USDbC"),
    ("USDC", "USDbC"),
    ("USDC", "DAI"),
    ("cbETH", "WETH"),
    ("WBTC", "WETH"),
    ("AERO", "WETH"),
]

# ─── UNISWAP V3 ABI (minimal, hanya slot0 + liquidity) ──────────────────────

POOL_ABI = json.loads("""[
  {
    "inputs": [],
    "name": "slot0",
    "outputs": [
      {"name": "sqrtPriceX96", "type": "uint160"},
      {"name": "tick", "type": "int24"},
      {"name": "observationIndex", "type": "uint16"},
      {"name": "observationCardinality", "type": "uint16"},
      {"name": "observationCardinalityNext", "type": "uint16"},
      {"name": "feeProtocol", "type": "uint8"},
      {"name": "unlocked", "type": "bool"}
    ],
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [],
    "name": "liquidity",
    "outputs": [{"name": "", "type": "uint128"}],
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [],
    "name": "fee",
    "outputs": [{"name": "", "type": "uint24"}],
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [],
    "name": "token0",
    "outputs": [{"name": "", "type": "address"}],
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [],
    "name": "token1",
    "outputs": [{"name": "", "type": "address"}],
    "stateMutability": "view",
    "type": "function"
  }
]""")

# Uniswap V3 Factory (Base)
UNISWAPV3_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
FACTORY_ABI = json.loads("""[{
  "inputs": [
    {"name": "tokenA", "type": "address"},
    {"name": "tokenB", "type": "address"},
    {"name": "fee", "type": "uint24"}
  ],
  "name": "getPool",
  "outputs": [{"name": "pool", "type": "address"}],
  "stateMutability": "view",
  "type": "function"
}]""")

# ─── DATA STRUCTURES ──────────────────────────────────────────────────────────

@dataclass
class PriceData:
    dex: str
    pair: str
    price: float          # token1 per token0
    liquidity_usd: float
    fee_pct: float
    source: str           # "rpc" | "subgraph"
    timestamp: float = field(default_factory=time.time)

@dataclass
class Opportunity:
    pair: str
    buy_dex: str
    sell_dex: str
    buy_price: float
    sell_price: float
    spread_pct: float
    net_spread_pct: float  # setelah fee + estimasi gas
    liquidity_usd: float
    confidence: str        # HIGH / MEDIUM / LOW

# ─── WEB3 ────────────────────────────────────────────────────────────────────

w3 = Web3(Web3.HTTPProvider(RPC_URL))
factory = w3.eth.contract(
    address=Web3.to_checksum_address(UNISWAPV3_FACTORY),
    abi=FACTORY_ABI
)

def sqrtPriceX96_to_price(sqrtPriceX96: int, token0_decimals: int, token1_decimals: int) -> float:
    """Convert Uniswap V3 sqrtPriceX96 → human-readable price."""
    price = (Decimal(sqrtPriceX96) / Decimal(2**96)) ** 2
    price *= Decimal(10 ** (token0_decimals - token1_decimals))
    return float(price)

TOKEN_DECIMALS = {
    "WETH": 18, "USDC": 6, "USDbC": 6, "DAI": 18,
    "cbETH": 18, "WBTC": 8, "AERO": 18, "BSWAP": 18,
}

def get_pool_price_rpc(token0_sym: str, token1_sym: str, fee: int = 500) -> Optional[PriceData]:
    """Ambil harga langsung dari smart contract pool Uniswap V3."""
    try:
        t0 = Web3.to_checksum_address(TOKENS[token0_sym])
        t1 = Web3.to_checksum_address(TOKENS[token1_sym])
        pool_addr = factory.functions.getPool(t0, t1, fee).call()
        
        if pool_addr == "0x0000000000000000000000000000000000000000":
            # Coba fee tier lain
            for alt_fee in [100, 3000, 10000]:
                if alt_fee == fee:
                    continue
                pool_addr = factory.functions.getPool(t0, t1, alt_fee).call()
                if pool_addr != "0x0000000000000000000000000000000000000000":
                    fee = alt_fee
                    break
            else:
                return None

        pool = w3.eth.contract(
            address=Web3.to_checksum_address(pool_addr),
            abi=POOL_ABI
        )
        
        slot0 = pool.functions.slot0().call()
        sqrtPriceX96 = slot0[0]
        liquidity = pool.functions.liquidity().call()
        actual_fee = pool.functions.fee().call()
        
        if sqrtPriceX96 == 0:
            return None

        # Cek urutan token0/token1 di pool
        pool_token0 = pool.functions.token0().call().lower()
        expected_t0 = TOKENS[token0_sym].lower()
        
        dec0 = TOKEN_DECIMALS.get(token0_sym, 18)
        dec1 = TOKEN_DECIMALS.get(token1_sym, 18)
        
        price = sqrtPriceX96_to_price(sqrtPriceX96, dec0, dec1)
        
        # Kalau token0 di pool beda urutannya, flip
        if pool_token0 != expected_t0:
            price = 1.0 / price if price != 0 else 0
        
        fee_pct = actual_fee / 1_000_000 * 100  # fee dalam persen
        liq_usd = float(liquidity) / (10 ** dec0)  # approx
        
        return PriceData(
            dex="Uniswap V3",
            pair=f"{token0_sym}/{token1_sym}",
            price=price,
            liquidity_usd=liq_usd,
            fee_pct=fee_pct,
            source="rpc"
        )
    except Exception as e:
        return None


# ─── SUBGRAPH QUERIES ─────────────────────────────────────────────────────────

PAIR_QUERY = """
{
  pools(
    where: {
      token0_in: ["%s", "%s"],
      token1_in: ["%s", "%s"]
    }
    orderBy: totalValueLockedUSD
    orderDirection: desc
    first: 3
  ) {
    id
    token0 { symbol id decimals }
    token1 { symbol id decimals }
    token0Price
    token1Price
    totalValueLockedUSD
    feeTier
    volumeUSD
  }
}
"""

async def fetch_subgraph_price(
    session: aiohttp.ClientSession,
    dex_name: str,
    url: str,
    token0_sym: str,
    token1_sym: str
) -> Optional[PriceData]:
    """Query harga dari The Graph subgraph."""
    t0_addr = TOKENS.get(token0_sym, "").lower()
    t1_addr = TOKENS.get(token1_sym, "").lower()
    
    query = PAIR_QUERY % (t0_addr, t1_addr, t0_addr, t1_addr)
    
    try:
        async with session.post(
            url,
            json={"query": query},
            timeout=aiohttp.ClientTimeout(total=8)
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            pools = data.get("data", {}).get("pools", [])
            
            if not pools:
                return None
            
            pool = pools[0]  # Pool dengan TVL tertinggi
            
            # Tentuin harga berdasarkan urutan token
            t0_sym_pool = pool["token0"]["symbol"]
            price = float(pool["token0Price"]) if t0_sym_pool == token0_sym else float(pool["token1Price"])
            
            if price == 0:
                return None
                
            tvl = float(pool.get("totalValueLockedUSD", 0))
            fee_pct = int(pool.get("feeTier", 3000)) / 10000  # dalam persen
            
            return PriceData(
                dex=dex_name,
                pair=f"{token0_sym}/{token1_sym}",
                price=price,
                liquidity_usd=tvl,
                fee_pct=fee_pct,
                source="subgraph"
            )
    except Exception:
        return None


# ─── SCANNER CORE ─────────────────────────────────────────────────────────────

async def scan_all_prices(session: aiohttp.ClientSession) -> dict[str, list[PriceData]]:
    """
    Scan semua pair di semua DEX secara paralel.
    Return: { "WETH/USDC": [PriceData, PriceData, ...], ... }
    """
    results: dict[str, list[PriceData]] = {f"{t0}/{t1}": [] for t0, t1 in PAIRS}
    
    # ── On-chain (RPC) untuk Uniswap V3 ──
    for t0, t1 in PAIRS:
        pair_key = f"{t0}/{t1}"
        data = get_pool_price_rpc(t0, t1)
        if data:
            results[pair_key].append(data)
    
    # ── Subgraph queries (paralel) ──
    tasks = []
    task_meta = []
    
    for dex_name, url in SUBGRAPHS.items():
        if dex_name == "Uniswap V3":
            continue  # Udah dapat dari RPC
        for t0, t1 in PAIRS:
            tasks.append(fetch_subgraph_price(session, dex_name, url, t0, t1))
            task_meta.append(f"{t0}/{t1}")
    
    subgraph_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for meta, result in zip(task_meta, subgraph_results):
        if isinstance(result, PriceData) and result is not None:
            results[meta].append(result)
    
    return results


def find_opportunities(prices: dict[str, list[PriceData]], eth_price_usd: float = 3400) -> list[Opportunity]:
    """Cari arbitrase opportunities dari data harga."""
    opportunities = []
    
    for pair, price_list in prices.items():
        if len(price_list) < 2:
            continue
        
        # Sort by price
        sorted_prices = sorted(price_list, key=lambda x: x.price)
        
        cheapest = sorted_prices[0]   # beli di sini
        priciest = sorted_prices[-1]  # jual di sini
        
        if cheapest.price == 0 or priciest.price == 0:
            continue
        
        spread_pct = ((priciest.price - cheapest.price) / cheapest.price) * 100
        
        # Kurangi total fee (buy fee + sell fee)
        total_fee = cheapest.fee_pct + priciest.fee_pct
        
        # Estimasi gas dalam % (asumsi trade $1000)
        trade_size_usd = 1000
        gas_pct = (GAS_COST_USD / trade_size_usd) * 100
        
        net_spread = spread_pct - total_fee - gas_pct
        
        if spread_pct < MIN_SPREAD_PCT * 0.5:  # Filter noise
            continue
        
        min_liquidity = min(cheapest.liquidity_usd, priciest.liquidity_usd)
        
        # Confidence level
        if net_spread > 0.5 and min_liquidity > 50000:
            confidence = "HIGH"
        elif net_spread > 0.2 and min_liquidity > 10000:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        
        opportunities.append(Opportunity(
            pair=pair,
            buy_dex=cheapest.dex,
            sell_dex=priciest.dex,
            buy_price=cheapest.price,
            sell_price=priciest.price,
            spread_pct=spread_pct,
            net_spread_pct=net_spread,
            liquidity_usd=min_liquidity,
            confidence=confidence
        ))
    
    # Sort: net spread tertinggi duluan
    return sorted(opportunities, key=lambda x: x.net_spread_pct, reverse=True)


async def get_eth_price_usd(session: aiohttp.ClientSession) -> float:
    """Ambil harga ETH dari CoinGecko (gratis, no API key)."""
    try:
        async with session.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            data = await r.json()
            return float(data["ethereum"]["usd"])
    except Exception:
        return 3400.0  # fallback


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def render_opportunities(opps: list[Opportunity], scan_num: int, eth_usd: float) -> Panel:
    if not opps:
        return Panel(
            "[dim]Tidak ada opportunity ditemukan. Spread terlalu kecil atau liquidity rendah.[/dim]",
            title="[cyan]⚡ Arbitrage Opportunities[/cyan]",
            border_style="dim blue"
        )
    
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        border_style="dim blue",
        expand=True
    )
    
    table.add_column("Pair", style="white", min_width=12)
    table.add_column("Buy DEX", style="yellow", min_width=12)
    table.add_column("Sell DEX", style="yellow", min_width=12)
    table.add_column("Buy Price", justify="right", min_width=12)
    table.add_column("Sell Price", justify="right", min_width=12)
    table.add_column("Spread %", justify="right", min_width=9)
    table.add_column("Net % (est)", justify="right", min_width=10)
    table.add_column("Min Liq. USD", justify="right", min_width=12)
    table.add_column("Signal", justify="center", min_width=8)

    for opp in opps[:15]:  # Max 15 baris
        spread_color = "green" if opp.spread_pct > 0.5 else "yellow" if opp.spread_pct > 0.2 else "dim"
        net_color = "bright_green" if opp.net_spread_pct > 0.3 else "yellow" if opp.net_spread_pct > 0 else "red"
        conf_style = {
            "HIGH": "[bold green]● HIGH[/bold green]",
            "MEDIUM": "[yellow]◑ MED[/yellow]",
            "LOW": "[dim]○ LOW[/dim]"
        }.get(opp.confidence, "?")
        
        liq_str = f"${opp.liquidity_usd:,.0f}" if opp.liquidity_usd > 0 else "N/A"
        
        table.add_row(
            opp.pair,
            opp.buy_dex,
            opp.sell_dex,
            f"{opp.buy_price:.6f}",
            f"{opp.sell_price:.6f}",
            f"[{spread_color}]{opp.spread_pct:.3f}%[/{spread_color}]",
            f"[{net_color}]{opp.net_spread_pct:+.3f}%[/{net_color}]",
            liq_str,
            conf_style
        )
    
    title = f"[cyan]⚡ Arb Opportunities[/cyan] [dim]— Scan #{scan_num} — ETH: ${eth_usd:,.0f}[/dim]"
    return Panel(table, title=title, border_style="blue")


def render_header(scan_num: int, total_opps: int, high_conf: int) -> str:
    return (
        f"[bold cyan]ARB·X[/bold cyan] [dim]Base Network Scanner[/dim]  "
        f"[dim]│[/dim]  Scan [cyan]#{scan_num}[/cyan]  "
        f"[dim]│[/dim]  Opps: [yellow]{total_opps}[/yellow]  "
        f"[dim]│[/dim]  HIGH signal: [green]{high_conf}[/green]  "
        f"[dim]│[/dim]  {time.strftime('%H:%M:%S')}"
    )


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

async def main(args):
    global MIN_SPREAD_PCT, SCAN_INTERVAL, GAS_COST_USD
    
    if args.min_spread:
        MIN_SPREAD_PCT = args.min_spread
    if args.interval:
        SCAN_INTERVAL = args.interval
    if args.gas_cost:
        GAS_COST_USD = args.gas_cost

    console.print(Panel.fit(
        "[bold cyan]ARB·X — Base Network Arbitrage Scanner[/bold cyan]\n"
        "[dim]Mode: READ-ONLY | No execution | No private key needed[/dim]\n"
        f"[dim]RPC: {RPC_URL}[/dim]\n"
        f"[dim]Min spread: {MIN_SPREAD_PCT}% | Scan interval: {SCAN_INTERVAL}s | Est. gas: ${GAS_COST_USD}[/dim]",
        border_style="cyan"
    ))

    # Cek koneksi
    try:
        block = w3.eth.block_number
        console.print(f"[green]✓ RPC connected[/green] — Block #{block:,}")
    except Exception as e:
        console.print(f"[red]✗ RPC Error: {e}[/red]")
        console.print("[yellow]Tip: Ganti RPC_URL di config. Coba: https://mainnet.base.org[/yellow]")
        return

    scan_num = 0
    
    async with aiohttp.ClientSession() as session:
        eth_usd = await get_eth_price_usd(session)
        console.print(f"[green]✓ ETH Price:[/green] ${eth_usd:,.0f}")
        console.print("\n[dim]Mulai scanning... (Ctrl+C untuk stop)[/dim]\n")
        
        while True:
            scan_num += 1
            start_t = time.time()
            
            console.rule(f"[dim cyan]Scan #{scan_num}[/dim cyan]")
            
            with console.status("[cyan]Fetching prices from RPC + Subgraphs...[/cyan]"):
                prices = await scan_all_prices(session)
                opps = find_opportunities(prices, eth_usd)
            
            elapsed = time.time() - start_t
            high_conf = sum(1 for o in opps if o.confidence == "HIGH")
            
            # Print summary
            console.print(render_header(scan_num, len(opps), high_conf))
            console.print(render_opportunities(opps, scan_num, eth_usd))
            
            # Print raw price data kalau verbose
            if args.verbose:
                console.print("\n[dim]Raw price data:[/dim]")
                for pair, pdata_list in prices.items():
                    if pdata_list:
                        console.print(f"  [cyan]{pair}[/cyan]")
                        for pd in pdata_list:
                            console.print(f"    [{pd.source}] {pd.dex}: {pd.price:.6f} (fee: {pd.fee_pct:.2f}%, liq: ${pd.liquidity_usd:,.0f})")
            
            console.print(f"\n[dim]Scan selesai dalam {elapsed:.2f}s. Next scan dalam {SCAN_INTERVAL}s...[/dim]")
            
            # Refresh ETH price tiap 5 scan
            if scan_num % 5 == 0:
                eth_usd = await get_eth_price_usd(session)
            
            await asyncio.sleep(SCAN_INTERVAL)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARB·X — Base Arb Scanner")
    parser.add_argument("--min-spread", type=float, default=0.3,
                        help="Minimum spread %% untuk ditampilkan (default: 0.3)")
    parser.add_argument("--interval", type=float, default=5,
                        help="Interval scan dalam detik (default: 5)")
    parser.add_argument("--gas-cost", type=float, default=0.05,
                        help="Estimasi gas cost USD per trade (default: 0.05)")
    parser.add_argument("--verbose", action="store_true",
                        help="Tampilkan raw price data semua DEX")
    args = parser.parse_args()
    
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Scanner stopped.[/yellow]")
