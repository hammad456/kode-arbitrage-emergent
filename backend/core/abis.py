"""
Contract ABIs for Berachain DEXes
"""
import json

# Uniswap V2 Router ABI (for Kodiak V2)
ROUTER_V2_ABI = json.loads('''[
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsIn","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}
]''')

# ERC20 ABI
ERC20_ABI = json.loads('''[
    {"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"},
    {"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
    {"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"},
    {"constant":false,"inputs":[{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"type":"function"}
]''')

# Multicall3 ABI
MULTICALL_ABI = json.loads('''[
    {"inputs":[{"components":[{"internalType":"address","name":"target","type":"address"},{"internalType":"bytes","name":"callData","type":"bytes"}],"internalType":"struct Multicall3.Call[]","name":"calls","type":"tuple[]"}],"name":"aggregate","outputs":[{"internalType":"uint256","name":"blockNumber","type":"uint256"},{"internalType":"bytes[]","name":"returnData","type":"bytes[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"components":[{"internalType":"address","name":"target","type":"address"},{"internalType":"bool","name":"allowFailure","type":"bool"},{"internalType":"bytes","name":"callData","type":"bytes"}],"internalType":"struct Multicall3.Call3[]","name":"calls","type":"tuple[]"}],"name":"aggregate3","outputs":[{"components":[{"internalType":"bool","name":"success","type":"bool"},{"internalType":"bytes","name":"returnData","type":"bytes"}],"internalType":"struct Multicall3.Result[]","name":"returnData","type":"tuple[]"}],"stateMutability":"view","type":"function"}
]''')

# Pair ABI for reserves
PAIR_ABI = json.loads('''[
    {"constant":true,"inputs":[],"name":"getReserves","outputs":[{"name":"_reserve0","type":"uint112"},{"name":"_reserve1","type":"uint112"},{"name":"_blockTimestampLast","type":"uint32"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"type":"function"}
]''')

# Factory ABI
FACTORY_ABI = json.loads('''[
    {"constant":true,"inputs":[{"name":"tokenA","type":"address"},{"name":"tokenB","type":"address"}],"name":"getPair","outputs":[{"name":"pair","type":"address"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"allPairsLength","outputs":[{"name":"","type":"uint256"}],"type":"function"},
    {"constant":true,"inputs":[{"name":"","type":"uint256"}],"name":"allPairs","outputs":[{"name":"","type":"address"}],"type":"function"}
]''')

# BEX CrocSwap ABI (simplified for query and swap)
BEX_QUERY_ABI = json.loads('''[
    {"inputs":[{"internalType":"address","name":"base","type":"address"},{"internalType":"address","name":"quote","type":"address"},{"internalType":"uint256","name":"poolIdx","type":"uint256"}],"name":"queryPrice","outputs":[{"internalType":"uint128","name":"","type":"uint128"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"address","name":"base","type":"address"},{"internalType":"address","name":"quote","type":"address"},{"internalType":"uint256","name":"poolIdx","type":"uint256"}],"name":"queryLiquidity","outputs":[{"internalType":"uint128","name":"","type":"uint128"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"address","name":"base","type":"address"},{"internalType":"address","name":"quote","type":"address"},{"internalType":"uint256","name":"poolIdx","type":"uint256"},{"internalType":"bool","name":"isBuy","type":"bool"},{"internalType":"bool","name":"inBaseQty","type":"bool"},{"internalType":"uint128","name":"qty","type":"uint128"},{"internalType":"uint16","name":"tip","type":"uint16"},{"internalType":"uint128","name":"limitPrice","type":"uint128"},{"internalType":"uint128","name":"minOut","type":"uint128"},{"internalType":"uint8","name":"reserveFlags","type":"uint8"}],"name":"previewSwap","outputs":[{"internalType":"int128","name":"baseFlow","type":"int128"},{"internalType":"int128","name":"quoteFlow","type":"int128"}],"stateMutability":"view","type":"function"}
]''')

# Uniswap V2 Pair ABI for Flash Swap
FLASH_PAIR_ABI = json.loads('''[
    {"constant":true,"inputs":[],"name":"getReserves","outputs":[{"name":"_reserve0","type":"uint112"},{"name":"_reserve1","type":"uint112"},{"name":"_blockTimestampLast","type":"uint32"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"type":"function"},
    {"constant":false,"inputs":[{"name":"amount0Out","type":"uint256"},{"name":"amount1Out","type":"uint256"},{"name":"to","type":"address"},{"name":"data","type":"bytes"}],"name":"swap","outputs":[],"type":"function"}
]''')
