# ARB·X — Base Arbitrage Scanner

Scanner READ-ONLY untuk deteksi peluang arbitrase antar DEX di Base network.
**Tidak ada eksekusi. Tidak butuh private key.**

---

## Install

```bash
pip install -r requirements.txt
```

---

## Cara Pakai

### Basic (default settings)
```bash
python scanner.py
```

### Custom settings
```bash
# Min spread 0.5%, scan tiap 3 detik, estimasi gas $0.03
python scanner.py --min-spread 0.5 --interval 3 --gas-cost 0.03
```

### Verbose (lihat semua raw price data)
```bash
python scanner.py --verbose
```

---

## Konfigurasi (edit di scanner.py)

| Variable | Default | Keterangan |
|---|---|---|
| `RPC_URL` | `https://mainnet.base.org` | RPC endpoint Base. Bisa pakai Alchemy/Infura/QuickNode buat lebih stabil |
| `MIN_SPREAD_PCT` | `0.3` | Minimum spread % buat dianggap opportunity |
| `GAS_COST_USD` | `0.05` | Estimasi gas cost per arb (Base murah banget) |
| `SCAN_INTERVAL` | `5` | Jeda antar scan (detik) |

---

## DEX yang Di-scan

| DEX | Sumber Data |
|---|---|
| Uniswap V3 | **On-chain RPC** (paling akurat) |
| Aerodrome | The Graph Subgraph |
| BaseSwap | The Graph Subgraph |
| SwapBased | The Graph Subgraph |

---

## Token Pairs yang Di-monitor

- WETH / USDC
- WETH / USDbC
- USDC / USDbC
- USDC / DAI
- cbETH / WETH
- WBTC / WETH
- AERO / WETH

Tambah pair baru di variable `PAIRS` di `scanner.py`.

---

## Output

```
╔══════════════════════════════════════════════════╗
║  ARB·X — Scan #12 — ETH: $3,420                 ║
╠══════════════════════════════════════════════════╣
║ Pair        │ Buy DEX    │ Sell DEX  │ Spread │ Net  │ Signal ║
║ USDC/USDbC  │ Aerodrome  │ Uniswap V3│ 0.41%  │+0.28%│ ● HIGH ║
║ WETH/USDC   │ BaseSwap   │ Uniswap V3│ 0.22%  │+0.09%│ ◑ MED  ║
╚══════════════════════════════════════════════════╝
```

### Kolom penjelasan:
- **Spread %** — selisih harga mentah antar DEX
- **Net % (est)** — spread dikurangi fee + estimasi gas
- **Min Liq. USD** — likuiditas pool terkecil dari keduanya (penting! arb susah kalau liq kecil)
- **Signal** — HIGH: net > 0.5% & liq > $50k | MED: net > 0.2% | LOW: sisanya

---

## Tips

1. **Pakai RPC premium** (Alchemy/QuickNode) buat data on-chain lebih akurat & cepat
2. **Net spread > 0.3%** biasanya baru worth it kalau mau eksekusi manual
3. **Cek liquidity** — spread gede tapi liq kecil = price impact gede saat eksekusi
4. **Subgraph data** bisa delay ~1-5 menit, RPC on-chain selalu real-time
5. Tambah pair di `PAIRS` sesuai token yang mau kamu pantau

---

## Tambah DEX Baru

Cari subgraph URL-nya di [The Graph Explorer](https://thegraph.com/explorer) dengan keyword "base" lalu tambahkan ke dict `SUBGRAPHS`:

```python
SUBGRAPHS = {
    ...
    "NamaDEX": "https://api.thegraph.com/subgraphs/name/...",
}
```
