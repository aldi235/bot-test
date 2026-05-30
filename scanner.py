"""
ARB·X v2 — Base Network Arbitrage Scanner
- Discover top tokens by volume via GeckoTerminal API (gratis, no key)
- Price comparison antar DEX via on-chain RPC
- Filter: modal $1, net profit positif setelah gas

READ-ONLY. No execution. No private key needed.
"""

import asyncio
import aiohttp
import time
import json
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict
from web3 import Web3
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
import argparse

console = Console()

# ─── CONFIG ──────────────────────────────────────────────────────────────────

RPC_URL        = "https://mainnet.base.org"   # Ganti ke Alchemy/QuickNode buat lebih stabil
MIN_NET_PROFIT = 0.001                         # Min profit USD setelah gas (modal $1)
TRADE_SIZE_USD = 1.0                           # Modal simulasi
GAS_COST_USD   = 0.02                          # Estimasi gas Base (~$0.01-0.05)
SCAN_INTERVAL  = 10                            # Detik antar scan
TOP_POOLS_PER_DEX = 50                         # Berapa pool per DEX yang di-fetch
MAX_PAIRS_TO_SCAN  = 80                        # Max pair unik yang dibandingkan

# DEX dex_id di GeckoTerminal untuk Base network
GECKOTERMINAL_DEXES = [
    "uniswap-v3-base",
    "aerodrome-slipstream",
    "aerodrome-base",
    "baseswap",
    "sushiswap-v3-base",
    "maverick-protocol-base",
    "pancakeswap-v3-base",
]

# ─── UNISWAP V3 STYLE POOL ABI (berlaku untuk semua CLMMs di Base) ──────────

POOL_ABI = json.loads("""[
  {"inputs":[],"name":"slot0","outputs":[
    {"name":"sqrtPriceX96","type":"uint160"},
    {"name":"tick","type":"int24"},
    {"name":"observationIndex","type":"uint16"},
    {"name":"observationCardinality","type":"uint16"},
    {"name":"observationCardinalityNext","type":"uint16"},
    {"name":"feeProtocol","type":"uint8"},
    {"name":"unlocked","type":"bool"}
  ],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"liquidity","outputs":[{"name":"","type":"uint128"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"fee","outputs":[{"name":"","type":"uint24"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}
]""")

# Aerodrome stable pool ABI (getReserves style)
STABLE_POOL_ABI = json.loads("""[
  {"inputs":[],"name":"getReserves","outputs":[
    {"name":"_reserve0","type":"uint256"},
    {"name":"_reserve1","type":"uint256"},
    {"name":"_blockTimestampLast","type":"uint256"}
  ],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"stable","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"}
]""")

# ─── DATA STRUCTURES ──────────────────────────────────────────────────────────

@dataclass
class PoolInfo:
    address: str
    dex: str
    dex_id: str
    token0_addr: str
    token1_addr: str
    token0_symbol: str
    token1_symbol: str
    token0_decimals: int
    token1_decimals: int
    price_usd_token0: float   # harga token0 dalam USD dari GeckoTerminal
    price_usd_token1: float
    volume_24h: float
    liquidity_usd: float
    pool_type: str            # "clmm" | "stable" | "xy"
    fee_pct: float

@dataclass
class LivePrice:
    pool: PoolInfo
    price: float              # token1 per token0 (on-chain)
    price_usd: float          # harga token0 dalam USD (derived)
    source: str               # "rpc" | "gecko"
    ok: bool = True
    error: str = ""

@dataclass
class Opportunity:
    token0: str
    token1: str
    buy_pool: PoolInfo
    sell_pool: PoolInfo
    buy_price: float          # harga token0 in token1 (beli murah)
    sell_price: float         # harga token0 in token1 (jual mahal)
    spread_pct: float
    fee_total_pct: float
    net_spread_pct: float
    profit_usd: float         # profit USD kalau modal $1
    liquidity_min_usd: float
    confidence: str

# ─── WEB3 ────────────────────────────────────────────────────────────────────

w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 10}))

def sqrtX96_to_price(sqrtPriceX96: int, dec0: int, dec1: int) -> float:
    if sqrtPriceX96 == 0:
        return 0.0
    p = (Decimal(sqrtPriceX96) / Decimal(2**96)) ** 2
    p *= Decimal(10 ** (dec0 - dec1))
    return float(p)

def get_clmm_price(pool_info: PoolInfo) -> LivePrice:
    """Fetch harga dari CLMM pool (Uniswap V3 style) via RPC."""
    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(pool_info.address),
            abi=POOL_ABI
        )
        slot0 = contract.functions.slot0().call()
        sqrtPriceX96 = slot0[0]
        if sqrtPriceX96 == 0:
            return LivePrice(pool=pool_info, price=0, price_usd=0, source="rpc", ok=False, error="zero price")

        # Cek urutan token0 on-chain vs kita
        onchain_t0 = contract.functions.token0().call().lower()
        expected_t0 = pool_info.token0_addr.lower()

        price = sqrtX96_to_price(sqrtPriceX96, pool_info.token0_decimals, pool_info.token1_decimals)

        if onchain_t0 != expected_t0:
            price = 1.0 / price if price > 0 else 0

        price_usd = price * pool_info.price_usd_token1 if pool_info.price_usd_token1 > 0 else pool_info.price_usd_token0

        return LivePrice(pool=pool_info, price=price, price_usd=price_usd, source="rpc", ok=True)
    except Exception as e:
        return LivePrice(pool=pool_info, price=0, price_usd=0, source="rpc", ok=False, error=str(e)[:60])

def get_xy_price(pool_info: PoolInfo) -> LivePrice:
    """Fetch harga dari AMM xy=k pool (Aerodrome/Velodrome style) via RPC."""
    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(pool_info.address),
            abi=STABLE_POOL_ABI
        )
        res = contract.functions.getReserves().call()
        r0 = res[0] / (10 ** pool_info.token0_decimals)
        r1 = res[1] / (10 ** pool_info.token1_decimals)

        if r0 == 0 or r1 == 0:
            return LivePrice(pool=pool_info, price=0, price_usd=0, source="rpc", ok=False, error="zero reserves")

        onchain_t0 = contract.functions.token0().call().lower()
        expected_t0 = pool_info.token0_addr.lower()

        price = r1 / r0  # token1 per token0
        if onchain_t0 != expected_t0:
            price = r0 / r1

        price_usd = price * pool_info.price_usd_token1 if pool_info.price_usd_token1 > 0 else pool_info.price_usd_token0

        return LivePrice(pool=pool_info, price=price, price_usd=price_usd, source="rpc", ok=True)
    except Exception as e:
        return LivePrice(pool=pool_info, price=0, price_usd=0, source="rpc", ok=False, error=str(e)[:60])

# ─── GECKOTERMINAL API ────────────────────────────────────────────────────────

GECKO_BASE = "https://api.geckoterminal.com/api/v2"

async def fetch_top_pools(
    session: aiohttp.ClientSession,
    dex_id: str,
    page: int = 1
) -> list[dict]:
    """Ambil top pools dari GeckoTerminal untuk DEX tertentu di Base."""
    url = f"{GECKO_BASE}/networks/base/dexes/{dex_id}/pools"
    params = {"page": page, "sort": "h24_volume_usd_liquidity_desc"}
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 429:
                await asyncio.sleep(2)
                return []
            if r.status != 200:
                return []
            data = await r.json()
            return data.get("data", [])
    except Exception:
        return []

async def fetch_eth_price(session: aiohttp.ClientSession) -> float:
    try:
        async with session.get(
            f"{GECKO_BASE}/simple/networks/base/token_price/0x4200000000000000000000000000000000000006",
            timeout=aiohttp.ClientTimeout(total=6)
        ) as r:
            data = await r.json()
            prices = data.get("data", {}).get("attributes", {}).get("token_prices", {})
            addr = "0x4200000000000000000000000000000000000006"
            return float(prices.get(addr, 3400))
    except Exception:
        return 3400.0

def parse_pool(raw: dict, dex_name: str, dex_id: str) -> Optional[PoolInfo]:
    """Parse raw GeckoTerminal pool data → PoolInfo."""
    try:
        attr = raw["attributes"]
        rels = raw.get("relationships", {})

        # Address pool
        pool_addr = attr.get("address", "")
        if not pool_addr or len(pool_addr) != 42:
            return None

        # Token info
        base_token = attr.get("base_token_price_usd")
        quote_token = attr.get("quote_token_price_usd")

        if base_token is None or quote_token is None:
            return None

        # Ambil symbol dari name (format: "TOKEN0 / TOKEN1 X.XX%")
        name = attr.get("name", "")
        parts = name.split(" / ")
        if len(parts) < 2:
            return None
        t0_sym = parts[0].strip()
        t1_sym = parts[1].split(" ")[0].strip()

        # Harga USD
        t0_usd = float(base_token) if base_token else 0
        t1_usd = float(quote_token) if quote_token else 0

        # Liquidity & volume
        liq = float(attr.get("reserve_in_usd", 0) or 0)
        vol = float(attr.get("volume_usd", {}).get("h24", 0) or 0)

        # Filter: likuiditas terlalu kecil tidak worth it
        if liq < 1000:
            return None

        # Fee dari nama (e.g. "0.05%") atau default
        fee_pct = 0.3
        for part in name.split():
            if "%" in part:
                try:
                    fee_pct = float(part.replace("%", ""))
                    break
                except ValueError:
                    pass

        # Token addresses dari relationships
        t0_addr = ""
        t1_addr = ""
        try:
            included_tokens = rels.get("base_token", {}).get("data", {})
            t0_addr = included_tokens.get("id", "").split("_")[-1] if included_tokens else ""
            included_tokens2 = rels.get("quote_token", {}).get("data", {})
            t1_addr = included_tokens2.get("id", "").split("_")[-1] if included_tokens2 else ""
        except Exception:
            pass

        # Detect pool type dari dex_id
        if "aerodrome" in dex_id and "slipstream" not in dex_id:
            pool_type = "xy"
        else:
            pool_type = "clmm"

        return PoolInfo(
            address=pool_addr,
            dex=dex_name,
            dex_id=dex_id,
            token0_addr=t0_addr,
            token1_addr=t1_addr,
            token0_symbol=t0_sym,
            token1_symbol=t1_sym,
            token0_decimals=18,   # default, override kalau ada info
            token1_decimals=18,
            price_usd_token0=t0_usd,
            price_usd_token1=t1_usd,
            volume_24h=vol,
            liquidity_usd=liq,
            pool_type=pool_type,
            fee_pct=fee_pct,
        )
    except Exception:
        return None

async def discover_pools(session: aiohttp.ClientSession) -> list[PoolInfo]:
    """Fetch top pools dari semua DEX secara paralel."""
    tasks = []
    meta = []

    DEX_NAMES = {
        "uniswap-v3-base": "Uniswap V3",
        "aerodrome-slipstream": "Aerodrome CL",
        "aerodrome-base": "Aerodrome",
        "baseswap": "BaseSwap",
        "sushiswap-v3-base": "SushiSwap V3",
        "maverick-protocol-base": "Maverick",
        "pancakeswap-v3-base": "PancakeSwap V3",
    }

    for dex_id in GECKOTERMINAL_DEXES:
        tasks.append(fetch_top_pools(session, dex_id, page=1))
        meta.append((dex_id, DEX_NAMES.get(dex_id, dex_id)))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    pools = []
    for (dex_id, dex_name), raw_list in zip(meta, results):
        if isinstance(raw_list, list):
            for raw in raw_list[:TOP_POOLS_PER_DEX]:
                pool = parse_pool(raw, dex_name, dex_id)
                if pool:
                    pools.append(pool)

    return pools

# ─── PAIR GROUPING ────────────────────────────────────────────────────────────

def group_by_pair(pools: list[PoolInfo]) -> dict[str, list[PoolInfo]]:
    """Group pools yang punya token pair sama (normalized)."""
    groups: dict[str, list[PoolInfo]] = defaultdict(list)
    for p in pools:
        # Normalize pair key — sort alphabetically biar konsisten
        key = tuple(sorted([p.token0_symbol.upper(), p.token1_symbol.upper()]))
        groups[f"{key[0]}/{key[1]}"].append(p)
    # Hanya pair yang ada di ≥2 DEX berbeda
    return {k: v for k, v in groups.items() if len({p.dex for p in v}) >= 2}

# ─── PRICE FETCHING ───────────────────────────────────────────────────────────

def fetch_live_price(pool: PoolInfo) -> LivePrice:
    """Fetch on-chain price berdasarkan pool type."""
    if pool.pool_type == "xy":
        return get_xy_price(pool)
    else:
        return get_clmm_price(pool)

async def fetch_all_prices(pools: list[PoolInfo]) -> list[LivePrice]:
    """Fetch harga semua pool secara concurrent (pakai thread pool buat RPC calls)."""
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(None, fetch_live_price, pool)
        for pool in pools
    ]
    return await asyncio.gather(*tasks)

# ─── OPPORTUNITY DETECTION ────────────────────────────────────────────────────

def find_opportunities(
    pair_groups: dict[str, list[PoolInfo]],
    live_prices: dict[str, LivePrice],
) -> list[Opportunity]:
    opps = []

    for pair_key, pools in pair_groups.items():
        # Kumpulkan harga valid per pool
        priced = []
        for pool in pools:
            lp = live_prices.get(pool.address)
            if lp and lp.ok and lp.price > 0:
                priced.append(lp)

        if len(priced) < 2:
            continue

        # Normalize: pastikan semua dalam arah yang sama
        # Gunakan token0_symbol dari pair_key sebagai referensi
        ref_t0 = pair_key.split("/")[0]

        normalized = []
        for lp in priced:
            p = lp.pool
            if p.token0_symbol.upper() == ref_t0:
                normalized.append((lp.price, lp))
            else:
                # Flip harga
                flipped = 1.0 / lp.price if lp.price > 0 else 0
                normalized.append((flipped, lp))

        normalized.sort(key=lambda x: x[0])
        cheapest_price, cheapest_lp = normalized[0]
        priciest_price, priciest_lp = normalized[-1]

        if cheapest_price == 0:
            continue

        spread_pct = ((priciest_price - cheapest_price) / cheapest_price) * 100
        if spread_pct < 0.05:
            continue

        total_fee = cheapest_lp.pool.fee_pct + priciest_lp.pool.fee_pct
        gas_pct = (GAS_COST_USD / TRADE_SIZE_USD) * 100
        net_spread_pct = spread_pct - total_fee - gas_pct

        profit_usd = (net_spread_pct / 100) * TRADE_SIZE_USD
        min_liq = min(cheapest_lp.pool.liquidity_usd, priciest_lp.pool.liquidity_usd)

        # Confidence
        if net_spread_pct > 0.5 and min_liq > 50_000 and profit_usd > 0:
            conf = "HIGH"
        elif net_spread_pct > 0.1 and min_liq > 5_000 and profit_usd > 0:
            conf = "MED"
        elif profit_usd > 0:
            conf = "LOW"
        else:
            conf = "NEG"

        opps.append(Opportunity(
            token0=ref_t0,
            token1=pair_key.split("/")[1],
            buy_pool=cheapest_lp.pool,
            sell_pool=priciest_lp.pool,
            buy_price=cheapest_price,
            sell_price=priciest_price,
            spread_pct=spread_pct,
            fee_total_pct=total_fee,
            net_spread_pct=net_spread_pct,
            profit_usd=profit_usd,
            liquidity_min_usd=min_liq,
            confidence=conf,
        ))

    return sorted(opps, key=lambda x: x.profit_usd, reverse=True)

# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def render_table(opps: list[Opportunity], scan_num: int, eth_usd: float,
                 n_pools: int, n_pairs: int, elapsed: float) -> Panel:

    # Split profitable vs not
    profitable = [o for o in opps if o.profit_usd > 0]
    negative   = [o for o in opps if o.profit_usd <= 0]

    if not opps:
        return Panel("[dim]Belum ada data...[/dim]", border_style="dim blue")

    table = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold cyan",
        border_style="dim blue",
        expand=True,
        show_lines=False,
    )

    table.add_column("Pair",          min_width=13)
    table.add_column("Buy DEX",       min_width=14)
    table.add_column("Sell DEX",      min_width=14)
    table.add_column("Spread",        justify="right", min_width=7)
    table.add_column("Fees",          justify="right", min_width=6)
    table.add_column("Net %",         justify="right", min_width=8)
    table.add_column("Profit $1",     justify="right", min_width=9)
    table.add_column("Min Liq",       justify="right", min_width=10)
    table.add_column("Signal",        justify="center", min_width=7)

    CONF_STYLE = {
        "HIGH": "[bold green]●HIGH[/bold green]",
        "MED":  "[yellow]◑ MED[/yellow]",
        "LOW":  "[dim]○ LOW[/dim]",
        "NEG":  "[red]✗ NEG[/red]",
    }

    # Profitable dulu, lalu negatif (max 30 baris)
    shown = (profitable + negative)[:30]

    for o in shown:
        nc = "bright_green" if o.net_spread_pct > 0.3 else "yellow" if o.net_spread_pct > 0 else "red"
        pc = "bright_green" if o.profit_usd > 0 else "red"
        liq_str = f"${o.liquidity_min_usd:>8,.0f}"

        table.add_row(
            f"{o.token0}/{o.token1}",
            o.buy_pool.dex,
            o.sell_pool.dex,
            f"{o.spread_pct:.3f}%",
            f"{o.fee_total_pct:.2f}%",
            f"[{nc}]{o.net_spread_pct:+.3f}%[/{nc}]",
            f"[{pc}]${o.profit_usd:+.5f}[/{pc}]",
            liq_str,
            CONF_STYLE.get(o.confidence, "?"),
        )

    title = (
        f"[bold cyan]ARB·X v2[/bold cyan] [dim]Base · Scan #{scan_num} · "
        f"ETH ${eth_usd:,.0f} · {n_pools} pools · {n_pairs} pairs · {elapsed:.1f}s[/dim]"
    )
    subtitle = (
        f"[green]{len(profitable)} profitable[/green]  "
        f"[dim]{len(negative)} negative[/dim]  "
        f"[dim]Modal: ${TRADE_SIZE_USD} · Est. gas: ${GAS_COST_USD}[/dim]"
    )

    return Panel(
        table,
        title=title,
        subtitle=subtitle,
        border_style="blue"
    )

# ─── MAIN ────────────────────────────────────────────────────────────────────

async def main(args):
    global MIN_NET_PROFIT, SCAN_INTERVAL, GAS_COST_USD, TRADE_SIZE_USD

    if args.interval:   SCAN_INTERVAL = args.interval
    if args.gas_cost:   GAS_COST_USD  = args.gas_cost
    if args.trade_size: TRADE_SIZE_USD = args.trade_size

    console.print(Panel.fit(
        "[bold cyan]ARB·X v2 — Base Arbitrage Scanner[/bold cyan]\n"
        "[dim]Source: GeckoTerminal API (no key) + On-chain RPC[/dim]\n"
        f"[dim]Modal simulasi: ${TRADE_SIZE_USD} · Est. gas: ${GAS_COST_USD} · Interval: {SCAN_INTERVAL}s[/dim]",
        border_style="cyan"
    ))

    # Cek RPC
    try:
        block = w3.eth.block_number
        console.print(f"[green]✓ RPC connected[/green] — Block #{block:,}")
    except Exception as e:
        console.print(f"[red]✗ RPC Error: {e}[/red]")
        console.print("[yellow]Tip: Ganti RPC_URL di bagian CONFIG. Coba Alchemy/QuickNode free tier.[/yellow]")
        return

    scan_num = 0
    pools_cache: list[PoolInfo] = []
    cache_age = 0
    CACHE_TTL = 60  # refresh pool list tiap 60 detik

    async with aiohttp.ClientSession(
        headers={"Accept": "application/json;version=20230302"}
    ) as session:

        eth_usd = await fetch_eth_price(session)
        console.print(f"[green]✓ ETH Price:[/green] ${eth_usd:,.0f}")
        console.print("\n[dim]Discovering pools... (Ctrl+C untuk stop)[/dim]\n")

        while True:
            scan_num += 1
            t0 = time.time()

            # Refresh pool list dari GeckoTerminal tiap CACHE_TTL detik
            if not pools_cache or (time.time() - cache_age) > CACHE_TTL:
                with console.status("[cyan]Fetching top pools dari GeckoTerminal...[/cyan]"):
                    pools_cache = await discover_pools(session)
                    cache_age = time.time()
                console.print(f"[dim]  → {len(pools_cache)} pools ditemukan dari {len(GECKOTERMINAL_DEXES)} DEX[/dim]")

            # Group by pair
            pair_groups = group_by_pair(pools_cache)
            # Batasi jumlah pair yang di-scan on-chain
            pair_groups_limited = dict(list(pair_groups.items())[:MAX_PAIRS_TO_SCAN])

            # Kumpulkan semua pools yang perlu di-fetch
            pools_to_fetch = [p for pools in pair_groups_limited.values() for p in pools]

            # Fetch harga on-chain (concurrent)
            with console.status(f"[cyan]Fetching harga on-chain untuk {len(pools_to_fetch)} pools...[/cyan]"):
                live_price_list = await fetch_all_prices(pools_to_fetch)

            live_prices: dict[str, LivePrice] = {
                lp.pool.address: lp for lp in live_price_list
            }

            # Find opportunities
            opps = find_opportunities(pair_groups_limited, live_prices)

            elapsed = time.time() - t0

            console.rule(f"[dim cyan]Scan #{scan_num}[/dim cyan]")
            console.print(render_table(opps, scan_num, eth_usd,
                                       len(pools_to_fetch), len(pair_groups_limited), elapsed))

            if args.verbose:
                console.print("\n[dim]Pools dengan error RPC:[/dim]")
                errors = [lp for lp in live_price_list if not lp.ok][:10]
                for lp in errors:
                    console.print(f"  [red]{lp.pool.dex}[/red] {lp.pool.address[:10]}... {lp.error}")

            console.print(f"\n[dim]Next scan dalam {SCAN_INTERVAL}s...[/dim]\n")

            # Refresh ETH price tiap 3 scan
            if scan_num % 3 == 0:
                eth_usd = await fetch_eth_price(session)

            await asyncio.sleep(SCAN_INTERVAL)

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARB·X v2 — Base Arb Scanner")
    parser.add_argument("--interval",   type=float, default=10,   help="Interval scan detik (default: 10)")
    parser.add_argument("--gas-cost",   type=float, default=0.02, help="Estimasi gas USD (default: 0.02)")
    parser.add_argument("--trade-size", type=float, default=1.0,  help="Simulasi modal USD (default: 1.0)")
    parser.add_argument("--verbose",    action="store_true",       help="Tampilkan error RPC")
    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Scanner stopped.[/yellow]")
