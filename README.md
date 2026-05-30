# ARB·X v2 — Base Arbitrage Scanner

Scanner READ-ONLY. Tidak ada eksekusi. Tidak butuh private key.

## Cara Install & Jalanin (GitHub Codespaces)

```bash
pip install -r requirements.txt
python scanner.py
```

## Options

```bash
python scanner.py --interval 5          # scan tiap 5 detik (default: 10)
python scanner.py --trade-size 1        # simulasi modal $1 (default)
python scanner.py --gas-cost 0.02       # estimasi gas per arb (default: $0.02)
python scanner.py --verbose             # tampilkan pool dengan RPC error
```

## Cara Kerja

1. **GeckoTerminal API** (gratis, no key) → discover top pools by volume di 7 DEX Base
2. **On-chain RPC** → fetch harga real-time langsung dari smart contract tiap pool
3. Group pool yang punya token pair sama → bandingkan harga → hitung spread & profit

## Output Kolom

| Kolom | Keterangan |
|---|---|
| Pair | Token pair |
| Buy DEX | DEX dengan harga paling murah (beli di sini) |
| Sell DEX | DEX dengan harga paling mahal (jual di sini) |
| Spread | Selisih harga kotor antar DEX |
| Fees | Total fee buy + sell pool |
| Net % | Spread - fees - estimasi gas |
| Profit $1 | Estimasi profit USD kalau modal $1 |
| Min Liq | Likuiditas terkecil dari kedua pool |
| Signal | HIGH/MED/LOW/NEG |

## DEX yang Di-scan

- Uniswap V3
- Aerodrome CL (Slipstream)
- Aerodrome (xy=k)
- BaseSwap
- SushiSwap V3
- Maverick Protocol
- PancakeSwap V3

## Ganti RPC (Recommended)

Public Base RPC bisa lambat. Pakai yang lebih stabil:

1. Daftar gratis di [alchemy.com](https://alchemy.com)
2. Buat app → pilih Base Mainnet
3. Copy HTTPS URL
4. Edit baris di `scanner.py`:
```python
RPC_URL = "https://base-mainnet.g.alchemy.com/v2/API_KEY_KAMU"
```

## Catatan

- `Profit $1` adalah estimasi kasar — price impact, slippage, dan timing bisa beda
- Likuiditas kecil = price impact besar = profit aktual lebih kecil
- Signal HIGH belum tentu profitable kalau dieksekusi — ini cuma detektor
